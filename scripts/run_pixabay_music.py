#!/usr/bin/env python3
"""Select and download background music through real ChatGPT and provider UIs.

No ChatGPT, music-provider, or media API is used. Ordak is the only browser-control
layer.  A Cloudflare human-verification interstitial is detected explicitly and
reported without trying to bypass it; resume the same command after it has
been completed in the visible VNC browser.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import html
import hashlib
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

from pipeline_notifier import PipelineNotifier, format_duration
from pipeline_stages import stage_title


ROOT = Path(__file__).resolve().parents[1]
# ChatGPT often renders a URL in an anchor's href rather than in visible text.
# Keep extraction permissive, then validate host/path structurally below.
URL_CANDIDATE = re.compile(r"https?://[^\s<>\"'`]+", re.I)
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
MIN_FALLBACK_AUDIO_BYTES = 64 * 1024
SUPPORTED_PROVIDERS = ("freesound", "mixkit", "pixabay")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def dump(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@contextmanager
def primary_deadline(seconds: float):
    """Interrupt any hidden browser/socket hang so local fallback can run."""
    if not hasattr(signal, "setitimer"):
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)

    def expired(_signum, _frame) -> None:
        raise TimeoutError(f"Primary browser music workflow exceeded {seconds:g} seconds")

    signal.signal(signal.SIGALRM, expired)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, max(1.0, seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audio_duration(path: Path) -> float | None:
    """Probe an audio file with a hard timeout; return None when unusable."""
    if not path.is_file() or path.stat().st_size < MIN_FALLBACK_AUDIO_BYTES or not shutil.which("ffprobe"):
        return None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        duration = float(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return duration if result.returncode == 0 and duration >= 10 else None


def cached_music_candidates(project: Path, provider: str) -> list[tuple[Path, dict[str, Any], Path]]:
    """Find previously verified provider tracks that can keep a run moving."""
    candidates: list[tuple[Path, dict[str, Any], Path]] = []
    for meta_path in sorted((ROOT / "videos").glob("*/music/MUSIC_SELECTION.json")):
        source_project = meta_path.parent.parent
        if source_project == project:
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            source_url = valid_track_url(str(meta.get("source_url") or ""), provider)
            relative_file = Path(str(meta.get("file") or ""))
            source = (source_project / relative_file).resolve()
            if not source.is_relative_to(source_project.resolve()):
                continue
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if source_url and audio_duration(source) is not None:
            candidates.append((source, {**meta, "source_url": source_url}, source_project))
    # Prefer a track already used successfully more than once: it is the least
    # risky generic background fallback. Break ties in favor of newer receipts.
    digest_counts = Counter(file_sha256(source) for source, _, _ in candidates)
    candidates.sort(key=lambda item: (digest_counts[file_sha256(item[0])], item[0].stat().st_mtime), reverse=True)
    return candidates


def install_audio(source: Path, destination: Path, *, move: bool = False) -> float:
    """Atomically install only a decodable audio file."""
    duration = audio_duration(source)
    if duration is None:
        raise RuntimeError(f"Downloaded/cached music is not a valid audio file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".installing")
    if move:
        shutil.move(str(source), temporary)
    else:
        shutil.copy2(source, temporary)
    temporary.replace(destination)
    return duration


def provider_name(provider: str) -> str:
    return {"freesound": "Freesound", "pixabay": "Pixabay", "mixkit": "Mixkit"}[provider]


def parse_provider_priority(value: str | list[str]) -> list[str]:
    """Validate an ordered, duplicate-free provider chain from CLI or panel input."""
    parts = value if isinstance(value, list) else value.split(",")
    providers = [part.strip().lower() for part in parts if part.strip()]
    if not providers:
        raise ValueError("Choose at least one music provider.")
    invalid = [provider for provider in providers if provider not in SUPPORTED_PROVIDERS]
    if invalid:
        raise ValueError("Unsupported music provider: " + ", ".join(invalid))
    if len(set(providers)) != len(providers):
        raise ValueError("Music providers must not be repeated.")
    return providers


def install_cached_fallback(
    project: Path,
    providers: list[str],
    meta_path: Path,
    attempts: list[dict[str, Any]],
    started: float,
    notifier: PipelineNotifier,
    stage_message: Any | None = None,
) -> Path:
    """Use a verified local track only after every requested provider has failed."""
    candidate: tuple[Path, dict[str, Any], Path] | None = None
    selected_provider = ""
    for provider in providers:
        candidates = cached_music_candidates(project, provider)
        if candidates:
            candidate = candidates[0]
            selected_provider = provider
            break
    if candidate is None:
        detail = "; ".join(f"{item['provider']}: {item['error']}" for item in attempts)
        raise RuntimeError(f"All music providers failed and no verified local fallback track exists. {detail}")
    source, source_meta, source_project = candidate
    destination = project / "assets" / "music" / f"background{source.suffix.lower()}"
    duration = install_audio(source, destination)
    dump(meta_path, {
        "schema_version": 3,
        "provider": f"{provider_name(selected_provider)} verified local fallback",
        "provider_priority": providers,
        "provider_attempts": attempts,
        "source_url": source_meta["source_url"],
        "status": "DONE",
        "selection_mode": "CACHE_FALLBACK",
        "cached_from": str(source.relative_to(ROOT)),
        "installed_at": utcnow(),
        "file": str(destination.relative_to(project)),
        "bytes": destination.stat().st_size,
        "sha256": file_sha256(destination),
        "duration_seconds": round(duration, 3),
        "license": source_meta.get("license") or f"{provider_name(selected_provider)} source license; verify current source page before publication.",
    })
    # Cache fallback is a successful completion with a different provenance, not a warning
    # message that obscures the stage log.  Keep it on the original mutable entry.
    lines = [
        "✅ Stage complete — verified cache fallback",
        f"⏱ Duration: {format_duration(time.perf_counter() - started)}",
        f"📄 Saved: {destination.relative_to(project)}",
        f"ℹ️ Providers exhausted: {', '.join(provider_name(item['provider']) for item in attempts)}",
    ]
    if hasattr(notifier, "stage_update"):
        notifier.stage_update(stage_message, stage_title("background_music"), lines)
    else:  # compatibility for minimal notifier doubles and external integrations
        notifier.stage_complete("Background music cache fallback", time.perf_counter() - started, artifact=str(destination.relative_to(project)))
    print(f"MUSIC: PASS (VERIFIED LOCAL FALLBACK: {provider_name(selected_provider)})\nFile: {destination}", flush=True)
    return destination


def normalize_track_url(value: str) -> str | None:
    """Return a canonical http(s) URL while removing chat/Markdown wrappers."""
    raw = html.unescape(value).strip()
    # A prose full stop or Markdown punctuation is not part of a URL.  Remove
    # it before wrapper characters so `(https://…/).` is handled correctly.
    raw = raw.rstrip(".,;:!?").strip("`<>()[]{}\"'")
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path.rstrip("/") + "/", "", ""))


def valid_track_url(value: str, provider: str) -> str | None:
    """Accept only one direct track page, never a search/category/download URL."""
    url = normalize_track_url(value)
    if url is None:
        return None
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if provider == "pixabay":
        valid = host in {"pixabay.com", "www.pixabay.com"} and parsed.path.startswith("/music/") and len(parsed.path.split("/")) >= 3
    elif provider == "mixkit":
        # Mixkit's direct music pages use this durable item-id route.  Its
        # catalogue/tag pages must not be accepted: their first download button
        # could silently select an unrelated track.
        valid = host in {"mixkit.co", "www.mixkit.co"} and bool(re.fullmatch(r"/free-stock-music/item/\d+/", parsed.path))
    else:
        valid = False
    return url if valid else None


def track_urls(values: list[str], provider: str) -> set[str]:
    """Extract valid direct-provider URLs from visible text and anchor hrefs."""
    found: set[str] = set()
    for value in values:
        for candidate in URL_CANDIDATE.findall(html.unescape(value)):
            url = valid_track_url(candidate, provider)
            if url:
                found.add(url)
    return found


class Browser:
    def __init__(self) -> None:
        sys.path.insert(0, str(ROOT / "services" / "ordak"))
        from app.automation.existing_chrome import execute_javascript, get_tab_info, list_google_chrome_tabs, open_url_in_existing_chrome  # type: ignore[import-not-found]
        self.execute = execute_javascript
        self.get_info = get_tab_info
        self.list_tabs = list_google_chrome_tabs
        self.open_url = open_url_in_existing_chrome
        self.tab: Any | None = None

    def select_or_open(self, url: str) -> None:
        existing = next((tab for tab in self.list_tabs() if tab.url.startswith(url)), None)
        self.tab = existing.ref if existing else self.open_url(url)

    def open_fresh(self, url: str) -> None:
        """Always open an isolated ChatGPT project tab for a new selection request.

        Reusing a matching project tab can inherit an unrelated unsent composer draft from a
        preceding provider attempt.  That made a safe no-overwrite guard look like a Mixkit
        failure.  A fresh project tab keeps the guard intact without touching user text.
        """
        self.tab = self.open_url(url)

    def data(self, expression: str) -> Any:
        if self.tab is None:
            raise RuntimeError("No browser tab is selected.")
        # Chrome's DevTools endpoint occasionally returns an empty payload while
        # a page is navigating or a renderer is being reattached.  That is
        # transient, not a malformed ChatGPT response; retry it locally rather
        # than failing the whole resumable pipeline.
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                raw = self.execute(self.tab, f"JSON.stringify(({expression}))")
                if not isinstance(raw, str) or not raw.strip():
                    raise ValueError("Chrome returned an empty JavaScript result")
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                last_error = exc
                if attempt < 4:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError("Chrome did not return usable page data after 5 attempts.") from last_error

    def point_click(self, expression: str) -> None:
        point = self.data(expression)
        if not isinstance(point, dict) or not point.get("ok"):
            raise RuntimeError("Required visible browser control was not found.")
        info = self.get_info(self.tab)
        websocket_url = getattr(info, "websocket_debugger_url", None)
        if not websocket_url:
            raise RuntimeError("Ordak could not focus the browser tab.")
        from websockets.sync.client import connect
        with connect(websocket_url, proxy=None, open_timeout=5, close_timeout=5) as ws:
            def request(request_id: int, method: str, params: dict[str, Any]) -> None:
                ws.send(json.dumps({"id": request_id, "method": method, "params": params}))
                while True:
                    reply = json.loads(ws.recv(timeout=5))
                    if reply.get("id") == request_id:
                        if reply.get("error"):
                            raise RuntimeError(f"Chrome rejected {method}.")
                        return
            request(1, "Page.bringToFront", {})
            request(2, "Input.dispatchMouseEvent", {"type": "mouseMoved", "x": point["x"], "y": point["y"]})
            request(3, "Input.dispatchMouseEvent", {"type": "mousePressed", "x": point["x"], "y": point["y"], "button": "left", "clickCount": 1})
            request(4, "Input.dispatchMouseEvent", {"type": "mouseReleased", "x": point["x"], "y": point["y"], "button": "left", "clickCount": 1})

    def configure_downloads(self, directory: Path) -> None:
        """Tell the live Chrome profile exactly where this run's audio must land.

        Polling ``~/Downloads`` was unreliable: Ordak can attach to a Chrome
        profile whose configured download directory belongs to a different user
        or browser session.  CDP is the browser's supported download routing
        mechanism, and a per-project staging directory also prevents a stale
        MP3 from being mistaken for this track.
        """
        if self.tab is None:
            raise RuntimeError("No browser tab is selected.")
        directory.mkdir(parents=True, exist_ok=True)
        info = self.get_info(self.tab)
        websocket_url = getattr(info, "websocket_debugger_url", None)
        if not websocket_url:
            raise RuntimeError("Ordak could not configure Chrome downloads.")
        from websockets.sync.client import connect

        with connect(websocket_url, proxy=None, open_timeout=5, close_timeout=5) as ws:
            ws.send(json.dumps({
                "id": 1,
                "method": "Browser.setDownloadBehavior",
                "params": {"behavior": "allow", "downloadPath": str(directory.resolve()), "eventsEnabled": True},
            }))
            while True:
                reply = json.loads(ws.recv(timeout=5))
                if reply.get("id") == 1:
                    if reply.get("error"):
                        raise RuntimeError("Chrome rejected the music download directory.")
                    return

    def press_enter(self) -> None:
        """Submit the composer with a real Enter key event.

        Used only when no Send control could be found: ChatGPT submits a non-empty composer on
        Enter by default, and the caller verifies the send either way, so this can never turn an
        unsent request into a reported success.
        """
        if self.tab is None:
            raise RuntimeError("No ChatGPT tab is selected.")
        info = self.get_info(self.tab)
        websocket_url = getattr(info, "websocket_debugger_url", None)
        if not websocket_url:
            raise RuntimeError("Ordak could not focus the browser tab.")
        from websockets.sync.client import connect

        with connect(websocket_url, proxy=None, open_timeout=5, close_timeout=5) as ws:
            def request(request_id: int, method: str, params: dict[str, Any]) -> None:
                ws.send(json.dumps({"id": request_id, "method": method, "params": params}))
                while True:
                    reply = json.loads(ws.recv(timeout=5))
                    if reply.get("id") == request_id:
                        if reply.get("error"):
                            raise RuntimeError(f"Chrome rejected {method}.")
                        return

            key = {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13}
            request(1, "Page.bringToFront", {})
            request(2, "Input.dispatchKeyEvent", {"type": "rawKeyDown", **key})
            request(3, "Input.dispatchKeyEvent", {"type": "char", "text": "\r", **key})
            request(4, "Input.dispatchKeyEvent", {"type": "keyUp", **key})

    def track_url_snapshot(self) -> list[str]:
        """Read both human-visible answer text and rendered outbound link targets."""
        snapshot = self.data("""(() => ({text:document.body?.innerText||'',hrefs:[...document.querySelectorAll('a[href]')].map(a=>a.href)}))()""")
        if not isinstance(snapshot, dict):
            return []
        values = [str(snapshot.get("text") or "")]
        values.extend(str(value) for value in snapshot.get("hrefs", []) if isinstance(value, str))
        return values

    def insert_and_submit(self, text: str) -> None:
        """Enter a ChatGPT request and prove that the UI accepted Send.

        Ctrl+Enter is a configurable ChatGPT shortcut and is not a dependable
        submission mechanism.  The visible blue Send control is canonical.  A
        failed prior process may leave exactly this request in the composer; in
        that case we preserve it and submit it once rather than duplicating it.
        """
        if self.tab is None:
            raise RuntimeError("No ChatGPT tab is selected.")
        composer = """(() => { const visible=e=>{const r=e.getBoundingClientRect();return !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth}; const e=[...document.querySelectorAll('#prompt-textarea,textarea,[contenteditable=true]')].filter(x=>visible(x)&&(/new chat|message|ask/i.test(`${x.getAttribute('aria-label')||''} ${x.placeholder||''}`)||x.id==='prompt-textarea'))[0];if(!e)return {ok:false};const r=e.getBoundingClientRect();return {ok:true,x:r.left+r.width/2,y:r.top+r.height/2,text:(e.value||e.innerText||'').trim(),is_textarea:e.tagName==='TEXTAREA'}; })()"""
        before = self.data(composer)
        if not isinstance(before, dict) or not before.get("ok"):
            raise RuntimeError("ChatGPT project composer was not visible.")
        # The composer normally clears after sending, but some ChatGPT layouts
        # retain the draft while a response streams.  The user-message count is
        # an independent visible acknowledgement that avoids falsely treating a
        # delivered music request as unsent (and then needlessly skipping Mixkit).
        before_messages = self.data("document.querySelectorAll('[data-message-author-role=\"user\"]').length")
        before_message_count = int(before_messages) if isinstance(before_messages, (int, float)) else 0
        existing = str(before.get("text") or "")
        def normalized(value: str) -> str:
            return re.sub(r"\s+", " ", value).strip()
        expected = normalized(text)
        observed = normalized(existing)
        # Rich-text composers can normalize line endings, spaces around smart
        # punctuation, or non-breaking spaces.  Accept only the same pipeline
        # request shape, never arbitrary text a user may have typed.
        same_pipeline_request = (
            observed == expected
            or (
                observed.startswith("Choose exactly one ")
                and "track for this specific video. Narration duration:" in observed
                and "Source brief/script follows:" in observed
                and "Reply with only one direct https://" in observed
                and expected.startswith(observed[:min(140, len(observed))])
            )
        )
        if existing and not same_pipeline_request:
            raise RuntimeError("ChatGPT composer contains a different unsent request; refusing to overwrite it.")
        self.point_click(f"(() => {{ return {json.dumps(before)}; }})()")
        info = self.get_info(self.tab)
        if not getattr(info, "websocket_debugger_url", None):
            raise RuntimeError("Ordak could not focus the ChatGPT browser tab.")
        if not existing:
            from websockets.sync.client import connect
            with connect(info.websocket_debugger_url, proxy=None, open_timeout=5, close_timeout=5) as ws:
                ws.send(json.dumps({"id": 1, "method": "Input.insertText", "params": {"text": text}}))
                while True:
                    reply = json.loads(ws.recv(timeout=5))
                    if reply.get("id") == 1:
                        if reply.get("error"):
                            raise RuntimeError("Chrome rejected ChatGPT input.")
                        break
        ready = self.data(composer)
        if normalized(str(ready.get("text") or "")) != expected and not (existing and same_pipeline_request):
            raise RuntimeError("ChatGPT did not retain the requested music-selection prompt.")
        send = """(() => { const visible=e=>{const r=e.getBoundingClientRect();return !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth}; const e=[...document.querySelectorAll('button,[role=button]')].filter(visible).find(x=>x.getAttribute('data-testid')==='send-button'||/send (prompt|message)|send$/i.test(`${x.getAttribute('aria-label')||''} ${(x.innerText||'').trim()}`));if(!e||e.disabled||e.getAttribute('aria-disabled')==='true')return {ok:false};const r=e.getBoundingClientRect();return {ok:true,x:r.left+r.width/2,y:r.top+r.height/2}; })()"""
        # The Send control only becomes clickable once ChatGPT's own state has caught up with
        # the inserted text, and demanding it at the first read failed the stage outright with
        # the request left sitting in the composer (observed 2026-09-05). So it is waited for,
        # and if it never appears the composer's own Enter is used — the acknowledgement check
        # below still decides whether anything was actually sent.
        clicked = False
        send_deadline = time.monotonic() + 15
        while time.monotonic() < send_deadline:
            point = self.data(send)
            if isinstance(point, dict) and point.get("ok"):
                self.point_click(f"(() => {{ return {json.dumps(point)}; }})()")
                clicked = True
                break
            time.sleep(0.5)
        if not clicked:
            self.press_enter()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            after = self.data(composer)
            page = str(self.data("document.body?.innerText||''"))
            message_count = self.data("document.querySelectorAll('[data-message-author-role=\"user\"]').length")
            # Empty composer is the strongest acknowledgement.  A visible Stop
            # action or a newly mounted user message covers layouts that retain
            # a transient draft while the answer streams.
            delivered_message = isinstance(message_count, (int, float)) and int(message_count) > before_message_count
            if not str(after.get("text") or "") or re.search(r"\bStop generating\b|\bStop streaming\b", page, re.I) or delivered_message:
                return
            time.sleep(0.4)
        raise RuntimeError("ChatGPT did not acknowledge the visible Send action; request remains unsent for safe retry.")


def video_context(project: Path) -> tuple[str, float]:
    """Build a compact, video-specific music brief from committed artifacts."""
    parts = []
    for name in ("BRIEF.md", "SCRIPT_FINAL.md"):
        path = project / name
        if path.exists():
            parts.append(" ".join(path.read_text(encoding="utf-8").split()))
    if not parts:
        raise RuntimeError("Music selection needs BRIEF.md or SCRIPT_FINAL.md.")
    duration = 0.0
    audio = next((p for p in (project / "assets" / "audio").glob("narration.*") if p.suffix.lower() in AUDIO_EXTENSIONS), None)
    if audio and shutil.which("ffprobe"):
        duration = audio_duration(audio) or 0.0
    return "\n".join(parts)[:2400], duration


def music_prompt(provider: str, context: str, duration: float) -> str:
    provider_text = "Pixabay Music" if provider == "pixabay" else "Mixkit Free Stock Music"
    url_shape = "pixabay.com/music/" if provider == "pixabay" else "mixkit.co/free-stock-music/item/"
    return (
        f"Choose exactly one {provider_text} track for this specific video. "
        f"Narration duration: {duration:.1f} seconds. Source brief/script follows:\n{context}\n\n"
        "Infer the topic, emotional arc, pacing, language and audience from this material. "
        "Choose an instrumental background suitable under spoken narration: no lyrics, no abrupt drops, "
        "and a restrained mix that supports rather than competes with the voice. "
        f"Reply with only one direct https://{url_shape} track URL and no other text."
    )


def choose_track(browser: Browser, project_url: str, prompt: str, provider: str) -> str:
    # Third-party integrations may provide the older Browser protocol; production Browser
    # always opens a fresh tab to avoid inheriting an unrelated composer draft.
    if hasattr(browser, "open_fresh"):
        browser.open_fresh(project_url)
    else:
        browser.select_or_open(project_url)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        snap = browser.data("(() => ({ready:[...document.querySelectorAll('textarea,[contenteditable=true]')].some(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)&&/new chat/i.test(`${e.getAttribute('aria-label')||''} ${e.placeholder||''}`)), text:(document.body?.innerText||'').slice(-4000)}))()")
        if snap.get("ready"):
            break
        time.sleep(1)
    else:
        raise RuntimeError("ChatGPT project composer did not become ready.")
    # Only accept a URL that appeared after this request.  Scanning the whole
    # conversation without a baseline can reuse an old track from a previous
    # video before ChatGPT has answered the current request.
    known_urls = track_urls(browser.track_url_snapshot(), provider)
    requests = [
        prompt,
        (
            f"The previous response did not include a valid direct {provider} track URL. "
            "Reply with exactly one URL in the requested format and nothing else."
        ),
    ]
    selection_timeout = max(15.0, float(os.getenv("YT_MUSIC_SELECTION_TIMEOUT_SECONDS", "75")))
    for request in requests:
        browser.insert_and_submit(request)
        deadline = time.monotonic() + selection_timeout
        while time.monotonic() < deadline:
            candidates = track_urls(browser.track_url_snapshot(), provider) - known_urls
            if candidates:
                # The prompt demands exactly one URL.  Refuse ambiguity rather
                # than choosing arbitrarily, and let the corrective request fix it.
                if len(candidates) == 1:
                    return candidates.pop()
                break
            time.sleep(2)
        # Preserve every URL observed in this attempt so retry N cannot select
        # an invalid/ambiguous response from retry N-1.
        known_urls.update(track_urls(browser.track_url_snapshot(), provider))
    raise RuntimeError(f"ChatGPT did not return exactly one new valid {provider} track URL after 2 attempts.")


def provider_snapshot(browser: Browser, provider: str) -> dict[str, Any]:
    """Find the provider's actual visible download action, not a generic link."""
    return browser.data(f"""(() => {{
      const provider={json.dumps(provider)};
      const text=document.body?.innerText||'';
      const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
      const label=e=>`${{e.innerText||''}} ${{e.getAttribute('aria-label')||''}} ${{e.getAttribute('title')||''}}`.replace(/\\s+/g,' ').trim();
      const controls=[...document.querySelectorAll('button,a,[role=button],[role=menuitem]')].filter(visible).filter(e=>!e.disabled&&e.getAttribute('aria-disabled')!=='true');
      const cookie=controls.find(e=>/^(reject all|decline|accept essential)$/i.test(label(e)));
      const download=controls.filter(e=>{{
        const value=label(e).toLowerCase();
        if (!/download/.test(value)) return false;
        if (/app|our app|plugin|image|video|template|bundle|all assets/.test(value)) return false;
        return provider==='mixkit'
          ? /free download|download free music|download music|download/.test(value)
          : /free download|download free music|download/.test(value);
      }}).sort((a,b)=>{{
        const score=e=>{{ const v=label(e).toLowerCase(); return /free download|download free music/.test(v)?0:/music/.test(v)?1:2; }};
        return score(a)-score(b);
      }})[0];
      const rect=e=>{{const r=e.getBoundingClientRect();return {{ok:true,x:r.left+r.width/2,y:r.top+r.height/2,label:label(e)}}}};
      return {{
        ready:!!download,
        challenge:/verify you are human|turnstile|captcha|security check/i.test(text)||!!document.querySelector('iframe[src*=turnstile],iframe[src*=challenge]'),
        cookie_point:cookie?rect(cookie):null,
        point:download?rect(download):null,
        controls:controls.map(label).filter(Boolean).filter(v=>/download/i.test(v)).slice(0,12),
      }};
    }})()""")


def download_directories(staging: Path) -> list[Path]:
    """Every plausible Chrome destination, ordered from run-specific to default.

    Some Chromium builds acknowledge ``Browser.setDownloadBehavior`` from a
    page target but retain the profile's configured directory.  Watching both
    locations makes that implementation quirk observable rather than turning a
    real Mixkit download into a false timeout.
    """
    configured = os.getenv("YT_MUSIC_DOWNLOAD_DIR", "").strip()
    paths = [staging]
    if configured:
        paths.append(Path(configured).expanduser())
    paths.append(Path.home() / "Downloads")
    unique: list[Path] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def newest_download(directories: Path | list[Path], after: float) -> Path | None:
    """Return a new, completed audio file from any known Chrome destination."""
    paths = [directories] if isinstance(directories, Path) else directories
    files: list[Path] = []
    for directory in paths:
        if not directory.is_dir():
            continue
        files.extend(
            path for path in directory.glob("*")
            if path.is_file()
            and path.suffix.lower() in AUDIO_EXTENSIONS
            and path.stat().st_mtime >= after - 2
            and path.stat().st_size >= MIN_FALLBACK_AUDIO_BYTES
        )
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def resumable_selected_url(meta_path: Path, provider: str) -> str | None:
    """Reuse a durable selection after a download/UI failure; never ask twice."""
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if meta.get("status") == "DONE":
        return None
    return valid_track_url(str(meta.get("source_url") or ""), provider)


def write_music_plan(
    project: Path,
    provider: str,
    prompt: str,
    narration_seconds: float,
    *,
    source_url: str | None = None,
    file: str | None = None,
    status: str = "SELECTED",
) -> None:
    """Record the plan beside the selection receipt (T9.7).

    One bed today; the plan is a segment list so a second cue is an appended entry rather
    than a rewrite. A plan that will not validate is reported and skipped — music must never
    be the reason an otherwise finished episode fails.
    """
    from music_plan import MusicPlanError, single_bed, write_plan

    if narration_seconds <= 0:
        print("music plan skipped: narration duration is unknown", flush=True)
        return
    try:
        write_plan(
            project,
            single_bed(
                narration_seconds=narration_seconds,
                provider=provider,
                query_prompt=prompt,
                source_url=source_url,
                file=file,
            ),
            narration_seconds=narration_seconds,
            status=status,
        )
    except (MusicPlanError, OSError) as exc:
        print(f"music plan warning: {type(exc).__name__}: {exc}", flush=True)


def sync_existing_mix_profile(project: Path, file: str, duration: float) -> None:
    """Point an already-created profile at a newly selected music provider on resume."""
    profile = project / "audio_mix" / "AUDIO_MIX_PROFILE.json"
    if not profile.is_file():
        return
    data = json.loads(profile.read_text(encoding="utf-8"))
    music = data.setdefault("music", {})
    music.update({"enabled": True, "file": file, "segments": [{"file": file, "start_seconds": 0.0, "end_seconds": duration or None, "gain_db": -20.0, "fade_in_sec": 0.8, "fade_out_sec": 1.4, "segment_id": "bed_001"}]})
    profile.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def download_from_provider(
    browser: Browser,
    project: Path,
    provider: str,
    prompt: str,
    duration: float,
    meta_path: Path,
    providers: list[str],
    attempts: list[dict[str, Any]],
) -> tuple[Path, str]:
    """Select and download one track using one provider, with no cache fallback."""
    name = provider_name(provider)
    url = resumable_selected_url(meta_path, provider) or choose_track(
        browser,
        os.getenv("YT_CHATGPT_PROJECT_URL", "https://chatgpt.com/g/g-p-6a9476ed80b08191a4db1065939e08b6/project"),
        prompt,
        provider,
    )
    dump(meta_path, {
        "schema_version": 3,
        "provider": f"{name} web UI",
        "provider_priority": providers,
        "provider_attempts": attempts,
        "source_url": url,
        "selection_prompt": prompt,
        "narration_duration_seconds": duration,
        "selected_at": utcnow(),
        "status": "SELECTED",
    })
    write_music_plan(project, provider, prompt, duration, source_url=url)
    browser.select_or_open(url)
    deadline = time.monotonic() + max(15.0, float(os.getenv("YT_MUSIC_PROVIDER_READY_TIMEOUT_SECONDS", "45")))
    snap: dict[str, Any] = {}
    while time.monotonic() < deadline:
        snap = provider_snapshot(browser, provider)
        if snap.get("cookie_point"):
            browser.point_click(f"(() => {{ return {json.dumps(snap['cookie_point'])}; }})()")
            time.sleep(1)
            continue
        if snap.get("challenge"):
            raise RuntimeError(f"{name} requires visible human verification.")
        if snap.get("ready"):
            break
        time.sleep(1)
    else:
        offered = ", ".join(str(item) for item in snap.get("controls", []))
        raise RuntimeError(f"{name} download control did not become ready. Visible download controls: {offered or 'none'}")

    staging = project / "music" / ".downloads" / provider
    staging.mkdir(parents=True, exist_ok=True)
    # A previous interrupted download must never block this provider attempt.
    for stale in staging.glob("*"):
        if stale.is_file():
            stale.unlink()
    browser.configure_downloads(staging)
    watch_directories = download_directories(staging)
    print("music download directories: " + ", ".join(str(path) for path in watch_directories), flush=True)
    download_started = time.time()
    browser.point_click(f"(() => {{ return {json.dumps(snap['point'])}; }})()")
    deadline = time.monotonic() + max(30.0, float(os.getenv("YT_MUSIC_DOWNLOAD_TIMEOUT_SECONDS", "180")))
    while time.monotonic() < deadline:
        download = newest_download(watch_directories, download_started)
        if download:
            destination = project / "assets" / "music" / f"background{download.suffix.lower()}"
            track_duration = install_audio(download, destination, move=True)
            dump(meta_path, {
                "schema_version": 3,
                "provider": f"{name} web UI",
                "provider_priority": providers,
                "provider_attempts": attempts,
                "source_url": url,
                "downloaded_at": utcnow(),
                "status": "DONE",
                "selection_mode": "BROWSER",
                "file": str(destination.relative_to(project)),
                "bytes": destination.stat().st_size,
                "sha256": file_sha256(destination),
                "duration_seconds": round(track_duration, 3),
                "license": f"{name} source license; verify current source page before publication.",
            })
            write_music_plan(project, provider, prompt, duration, source_url=url, file=str(destination.relative_to(project)), status="DONE")
            return destination, url
        time.sleep(1)
    raise RuntimeError(f"{name} did not write a completed audio file into Chrome's configured staging directory.")


def main() -> None:
    load_dotenv(ROOT / os.getenv("YT_ENV_FILE", ".env"), override=False)
    parser = argparse.ArgumentParser(description="Choose/download background music through ChatGPT and the visible browser.")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--provider", choices=SUPPORTED_PROVIDERS, help="Legacy shorthand for a one-provider run.")
    parser.add_argument("--providers", help="Comma-separated provider priority, e.g. mixkit,pixabay.")
    parser.add_argument("--track-url", help="Skip ChatGPT selection and resume this exact provider URL.")
    args = parser.parse_args()
    projects = [args.project.resolve()] if args.project else list((ROOT / "videos").glob(f"{args.video_id}_*"))
    if len(projects) != 1:
        raise RuntimeError("Pass --project when the video directory is ambiguous.")
    project = projects[0]
    providers = parse_provider_priority(args.providers or args.provider or os.getenv("YT_MUSIC_PROVIDERS") or os.getenv("YT_MUSIC_PROVIDER", "mixkit"))
    if args.track_url and (len(providers) != 1 or not valid_track_url(args.track_url, providers[0])):
        raise RuntimeError("--track-url requires exactly one provider and a valid direct track URL.")
    music_dir, meta_path = project / "assets" / "music", project / "music" / "MUSIC_SELECTION.json"
    notifier = PipelineNotifier(args.video_id, project.name, state_path=project / "pipeline" / "TELEGRAM_NOTIFICATION_STATE.json")
    stage_message = notifier.stage_started(stage_title("background_music"), key="background_music")
    started = time.perf_counter()
    context, duration = video_context(project)
    attempts: list[dict[str, Any]] = []
    browser: Browser | None = None
    for provider in providers:
        prompt = music_prompt(provider, context, duration) if provider != "freesound" else ""
        try:
            if provider == "freesound":
                from freesound_music import acquire
                selected = acquire(project, context, duration, license_policy=os.getenv("YT_FREESOUND_MUSIC_LICENSE_POLICY", "cc0_by"))
                dump(meta_path, {"schema_version": 4, "provider": "Freesound API", "provider_priority": providers, "provider_attempts": attempts, "selection_prompt": selected["query"], "alternate_queries": selected["alternate_queries"], "status": "DONE", **selected})
                write_music_plan(project, "freesound", selected["query"], duration, source_url=selected["source_url"], file=selected["file"], status="DONE")
                sync_existing_mix_profile(project, selected["file"], duration)
                destination = project / selected["file"]
                notifier.stage_update(stage_message, stage_title("background_music"), [f"✅ Stage complete — Freesound ({selected['selection_mode']})", f"⏱ Duration: {format_duration(time.perf_counter() - started)}", f"📄 Saved: {selected['file']}"])
                print(f"MUSIC: PASS (Freesound)\nFile: {destination}\nSource: {selected['source_url']}", flush=True)
                return
            browser = browser or Browser()
            with primary_deadline(max(60.0, float(os.getenv("YT_MUSIC_PRIMARY_TIMEOUT_SECONDS", "300")))):
                if args.track_url:
                    # An explicit URL is intentionally not mixed with ChatGPT selection.
                    url = valid_track_url(args.track_url, provider)
                    if url is None:
                        raise RuntimeError("The explicit track URL is invalid.")
                    dump(meta_path, {"schema_version": 3, "provider": f"{provider_name(provider)} web UI", "provider_priority": providers, "provider_attempts": attempts, "source_url": url, "status": "SELECTED"})
                    browser.select_or_open(url)
                    # Use the same verified downloader after persisting the supplied selection.
                    args.track_url = None
                destination, url = download_from_provider(browser, project, provider, prompt, duration, meta_path, providers, attempts)
            notifier.stage_update(
                stage_message,
                stage_title("background_music"),
                [
                    f"✅ Stage complete — {provider_name(provider)}",
                    f"⏱ Duration: {format_duration(time.perf_counter() - started)}",
                    f"📄 Saved: {destination.relative_to(project)}",
                ],
            )
            sync_existing_mix_profile(project, str(destination.relative_to(project)), duration)
            print(f"MUSIC: PASS ({provider_name(provider)})\nFile: {destination}\nSource: {url}", flush=True)
            return
        except Exception as exc:
            failure = {"provider": provider, "error": f"{type(exc).__name__}: {exc}"[:1000], "failed_at": utcnow()}
            attempts.append(failure)
            print(f"MUSIC PROVIDER FAILED ({provider_name(provider)}): {failure['error']}; trying next provider.", flush=True)
            notifier.stage_update(
                stage_message,
                stage_title("background_music"),
                [
                    f"↻ {provider_name(provider)} unavailable",
                    f"📍 Attempt {len(attempts)}/{len(providers)}",
                    "▶ Trying the next configured provider" if len(attempts) < len(providers) else "⚠️ Checking the verified local cache",
                ],
            )
    # Keep the complete failure evidence even when there is no cache candidate
    # and the caller must surface a hard music-stage failure.
    dump(meta_path, {
        "schema_version": 3,
        "provider_priority": providers,
        "provider_attempts": attempts,
        "status": "FAILED_ALL_PROVIDERS",
        "updated_at": utcnow(),
    })
    try:
        install_cached_fallback(project, providers, meta_path, attempts, started, notifier, stage_message)
    except Exception as exc:
        notifier.stage_failure(stage_message, stage_title("background_music"), time.perf_counter() - started, str(exc))
        raise


if __name__ == "__main__":
    main()

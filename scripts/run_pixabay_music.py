#!/usr/bin/env python3
"""Select and download background music through real ChatGPT and provider UIs.

No ChatGPT, music-provider, or media API is used. Ordak is the only browser-control
layer.  A Cloudflare human-verification interstitial is detected explicitly and
reported without trying to bypass it; resume the same command after it has
been completed in the visible VNC browser.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from pipeline_notifier import PipelineNotifier


ROOT = Path(__file__).resolve().parents[1]
TRACK_URL_PATTERNS = {
    "pixabay": re.compile(r"https?://(?:www\.)?pixabay\.com/music/[\w/-]+", re.I),
    "mixkit": re.compile(r"https?://(?:www\.)?mixkit\.co/free-stock-music/item/\d+/?", re.I),
}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def dump(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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

    def data(self, expression: str) -> Any:
        if self.tab is None:
            raise RuntimeError("No browser tab is selected.")
        raw = self.execute(self.tab, f"JSON.stringify(({expression}))")
        return json.loads(raw)

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
                    reply = json.loads(ws.recv())
                    if reply.get("id") == request_id:
                        if reply.get("error"):
                            raise RuntimeError(f"Chrome rejected {method}.")
                        return
            request(1, "Page.bringToFront", {})
            request(2, "Input.dispatchMouseEvent", {"type": "mouseMoved", "x": point["x"], "y": point["y"]})
            request(3, "Input.dispatchMouseEvent", {"type": "mousePressed", "x": point["x"], "y": point["y"], "button": "left", "clickCount": 1})
            request(4, "Input.dispatchMouseEvent", {"type": "mouseReleased", "x": point["x"], "y": point["y"], "button": "left", "clickCount": 1})

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
                    reply = json.loads(ws.recv())
                    if reply.get("id") == 1:
                        if reply.get("error"):
                            raise RuntimeError("Chrome rejected ChatGPT input.")
                        break
        ready = self.data(composer)
        if normalized(str(ready.get("text") or "")) != expected and not (existing and same_pipeline_request):
            raise RuntimeError("ChatGPT did not retain the requested music-selection prompt.")
        send = """(() => { const visible=e=>{const r=e.getBoundingClientRect();return !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth}; const e=[...document.querySelectorAll('button,[role=button]')].filter(visible).find(x=>x.getAttribute('data-testid')==='send-button'||/send (prompt|message)|send$/i.test(`${x.getAttribute('aria-label')||''} ${(x.innerText||'').trim()}`));if(!e||e.disabled||e.getAttribute('aria-disabled')==='true')return {ok:false};const r=e.getBoundingClientRect();return {ok:true,x:r.left+r.width/2,y:r.top+r.height/2}; })()"""
        self.point_click(send)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            after = self.data(composer)
            page = str(self.data("document.body?.innerText||''"))
            # Empty composer is the strongest acknowledgement.  A visible Stop
            # action covers streaming responses that retain a transient draft.
            if not str(after.get("text") or "") or re.search(r"\bStop generating\b|\bStop streaming\b", page, re.I):
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
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio)], capture_output=True, text=True, check=False)
        try: duration = float(result.stdout.strip())
        except ValueError: pass
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
    browser.select_or_open(project_url)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        snap = browser.data("(() => ({ready:[...document.querySelectorAll('textarea,[contenteditable=true]')].some(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)&&/new chat/i.test(`${e.getAttribute('aria-label')||''} ${e.placeholder||''}`)), text:(document.body?.innerText||'').slice(-4000)}))()")
        if snap.get("ready"):
            break
        time.sleep(1)
    else:
        raise RuntimeError("ChatGPT project composer did not become ready.")
    browser.insert_and_submit(prompt)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        text = str(browser.data("document.body?.innerText||''"))
        found = TRACK_URL_PATTERNS[provider].search(text)
        if found:
            return found.group(0).rstrip("/.") + "/"
        time.sleep(2)
    raise RuntimeError(f"ChatGPT did not return a valid {provider} track URL.")


def provider_snapshot(browser: Browser) -> dict[str, Any]:
    return browser.data("""(() => { const text=document.body?.innerText||''; const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length); const controls=[...document.querySelectorAll('button,a')].filter(visible); const cookie=controls.find(e=>/^reject all$/i.test((e.innerText||'').trim())); const button=controls.find(e=>/^(free download|download free music)$/i.test((e.innerText||'').trim())||/download free music/i.test(e.getAttribute('aria-label')||'')); const rect=e=>{const r=e.getBoundingClientRect();return {ok:true,x:r.left+r.width/2,y:r.top+r.height/2}}; return {ready:!!button, downloading:/downloading/i.test(text), challenge:/verify you are human|turnstile|captcha/i.test(text)||!!document.querySelector('iframe[src*=turnstile],iframe[src*=challenge]'), text:text.slice(0,2500), cookie_point:cookie?rect(cookie):null, point:button?rect(button):null}; })()""")


def newest_download(directory: Path, after: float) -> Path | None:
    files = [p for p in directory.glob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS and p.stat().st_mtime >= after - 2]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def main() -> None:
    load_dotenv(ROOT / os.getenv("YT_ENV_FILE", ".env"), override=False)
    parser = argparse.ArgumentParser(description="Choose/download background music through ChatGPT and the visible browser.")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--provider", choices=tuple(TRACK_URL_PATTERNS), default=os.getenv("YT_MUSIC_PROVIDER", "mixkit"))
    parser.add_argument("--track-url", help="Skip ChatGPT selection and resume this exact provider URL.")
    args = parser.parse_args()
    projects = [args.project.resolve()] if args.project else list((ROOT / "videos").glob(f"{args.video_id}_*"))
    if len(projects) != 1:
        raise RuntimeError("Pass --project when the video directory is ambiguous.")
    project = projects[0]
    if args.track_url and not TRACK_URL_PATTERNS[args.provider].fullmatch(args.track_url.rstrip("/") + "/"):
        raise RuntimeError(f"--track-url is not a valid {args.provider} track URL.")
    music_dir, meta_path = project / "assets" / "music", project / "music" / "MUSIC_SELECTION.json"
    notifier = PipelineNotifier(args.video_id, project.name)
    started = time.perf_counter()
    browser = Browser()
    context, duration = video_context(project)
    prompt = music_prompt(args.provider, context, duration)
    url = args.track_url or choose_track(browser, os.getenv("YT_CHATGPT_PROJECT_URL", "https://chatgpt.com/g/g-p-6a9476ed80b08191a4db1065939e08b6/project"), prompt, args.provider)
    provider_name = "Pixabay" if args.provider == "pixabay" else "Mixkit"
    dump(meta_path, {"schema_version": 1, "provider": f"{provider_name} web UI", "source_url": url, "selection_prompt": prompt, "video_context_sha256": hashlib.sha256(context.encode()).hexdigest(), "narration_duration_seconds": duration, "selected_at": utcnow(), "status": "SELECTED"})
    notifier.send(f"{provider_name} music selected", ["🎵 Background track chosen", f"🔗 Source: {url}"])
    browser.select_or_open(url)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        snap = provider_snapshot(browser)
        if snap.get("cookie_point"):
            browser.point_click(f"(() => {{ return {json.dumps(snap['cookie_point'])}; }})()")
            time.sleep(1)
            snap = provider_snapshot(browser)
        if snap.get("challenge"):
            dump(meta_path, {"schema_version": 1, "provider": f"{provider_name} web UI", "source_url": url, "status": "HUMAN_VERIFICATION_REQUIRED", "detected_at": utcnow()})
            raise RuntimeError(f"{provider_name} requires visible human verification in VNC; complete it, then rerun this command.")
        if snap.get("ready"):
            break
        time.sleep(1)
    else:
        raise RuntimeError(f"{provider_name} Free download control did not become ready.")
    download_dir = Path(os.getenv("YT_MUSIC_DOWNLOAD_DIR", str(Path.home() / "Downloads"))).expanduser()
    download_started = time.time()
    browser.point_click(f"(() => {{ return {json.dumps(snap['point'])}; }})()")
    deadline = time.monotonic() + float(os.getenv("YT_MUSIC_DOWNLOAD_TIMEOUT_SECONDS", "180"))
    while time.monotonic() < deadline:
        download = newest_download(download_dir, download_started)
        if download:
            music_dir.mkdir(parents=True, exist_ok=True)
            destination = music_dir / f"background{download.suffix.lower()}"
            shutil.move(str(download), destination)
            dump(meta_path, {"schema_version": 1, "provider": f"{provider_name} web UI", "source_url": url, "downloaded_at": utcnow(), "status": "DONE", "file": str(destination.relative_to(project)), "bytes": destination.stat().st_size, "license": f"{provider_name} source license; verify current source page before publication."})
            notifier.stage_complete(f"{provider_name} background music", time.perf_counter() - started, artifact=str(destination.relative_to(project)))
            print(f"{provider_name.upper()} MUSIC: PASS\nFile: {destination}")
            return
        time.sleep(2)
    dump(meta_path, {"schema_version": 1, "provider": f"{provider_name} web UI", "source_url": url, "status": "DOWNLOAD_TIMEOUT", "updated_at": utcnow()})
    raise RuntimeError(f"{provider_name} download did not reach Chrome's download directory before timeout.")


if __name__ == "__main__":
    main()

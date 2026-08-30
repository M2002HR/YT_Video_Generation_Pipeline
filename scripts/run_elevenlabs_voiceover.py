#!/usr/bin/env python3
"""Create a resumable ElevenLabs narration through its authenticated web UI.

This runner deliberately does not call an ElevenLabs API.  It uses the same
Ordak Chrome/CDP control layer as the visual workflow, persists parent-owned
state, and downloads the completed audio through the visible web experience.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from pipeline_notifier import PipelineNotifier, format_duration


ROOT = Path(__file__).resolve().parents[1]
ELEVENLABS_HOME_URL = "https://elevenlabs.io/app/home"
AUDIO_EXTENSIONS = (".wav", ".flac", ".mp3", ".m4a", ".ogg")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def bool_env(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class VoiceSettings:
    voice: str | None
    model: str | None
    speed: float | None
    stability: float | None
    similarity: float | None
    style: float | None
    speaker_boost: bool | None

    def supplied(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class State:
    def __init__(self, path: Path, *, video_id: str, input_path: Path, text: str, settings: VoiceSettings) -> None:
        self.path = path
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
            if self.data.get("input_sha256") != digest(text):
                raise RuntimeError("Existing voiceover state belongs to different narration text; use --force only after deliberate review.")
        else:
            self.data = {
                "schema_version": 1,
                "video_id": video_id,
                "created_at": utcnow(),
                "input_path": str(input_path),
                "input_sha256": digest(text),
                "settings": settings.supplied(),
                "status": "PENDING",
                "events": [],
            }
            self.save()

    def save(self) -> None:
        self.data["updated_at"] = utcnow()
        json_dump(self.path, self.data)

    def event(self, operation: str, started: float, **metadata: Any) -> None:
        self.data.setdefault("events", []).append({
            "operation": operation,
            "finished_at": utcnow(),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            **metadata,
        })
        self.save()


class ElevenLabsUI:
    """Small, explicit UI state machine backed by Ordak's authenticated Chrome."""

    def __init__(self, *, poll_seconds: float, stall_seconds: float, max_refreshes: int) -> None:
        sys.path.insert(0, str(ROOT / "services" / "ordak"))
        try:
            from app.automation.existing_chrome import (  # type: ignore[import-not-found]
                execute_javascript,
                get_tab_info,
                list_google_chrome_tabs,
                open_url_in_existing_chrome,
            )
        except ImportError as exc:
            raise RuntimeError("Ordak browser runtime is unavailable; run scripts/setup_services.py first.") from exc
        self._execute = execute_javascript
        self._get_tab_info = get_tab_info
        self._list_tabs = list_google_chrome_tabs
        self._open_url = open_url_in_existing_chrome
        self.poll_seconds = poll_seconds
        self.stall_seconds = stall_seconds
        self.max_refreshes = max_refreshes
        self.tab: Any | None = None

    def _json(self, expression: str) -> dict[str, Any]:
        if self.tab is None:
            raise RuntimeError("ElevenLabs browser tab has not been opened.")
        raw = self._execute(self.tab, f"JSON.stringify(({expression}))")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("ElevenLabs page returned an unreadable browser response.") from exc

    def _trusted_click(self, expression: str) -> None:
        """Click through CDP input events; Radix menus ignore synthetic clicks."""
        point = self._json(expression)
        if not point.get("ok"):
            raise RuntimeError("Required ElevenLabs UI control is not visible.")
        info = self._get_tab_info(self.tab)
        websocket_url = getattr(info, "websocket_debugger_url", None)
        if not websocket_url:
            raise RuntimeError("Ordak could not attach a DevTools target for ElevenLabs.")
        from websockets.sync.client import connect

        with connect(websocket_url, proxy=None, open_timeout=5, close_timeout=5) as websocket:
            websocket.send(json.dumps({"id": 0, "method": "Page.bringToFront", "params": {}}))
            while True:
                response = json.loads(websocket.recv())
                if response.get("id") == 0:
                    if response.get("error"):
                        raise RuntimeError("Chrome could not focus the ElevenLabs tab.")
                    break
            for request_id, params in enumerate((
                {"type": "mouseMoved", "x": point["x"], "y": point["y"]},
                {"type": "mousePressed", "x": point["x"], "y": point["y"], "button": "left", "clickCount": 1},
                {"type": "mouseReleased", "x": point["x"], "y": point["y"], "button": "left", "clickCount": 1},
            ), start=1):
                websocket.send(json.dumps({"id": request_id, "method": "Input.dispatchMouseEvent", "params": params}))
                while True:
                    response = json.loads(websocket.recv())
                    if response.get("id") == request_id:
                        if response.get("error"):
                            raise RuntimeError("Chrome rejected the ElevenLabs UI click.")
                        break

    def open_and_verify(self) -> dict[str, Any]:
        existing = next((tab for tab in self._list_tabs() if "elevenlabs.io" in tab.url), None)
        self.tab = existing.ref if existing is not None else self._open_url(os.getenv("YT_ELEVENLABS_HOME_URL", ELEVENLABS_HOME_URL))
        deadline = time.monotonic() + 45
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.snapshot()
            if last.get("ready"):
                return last
            if last.get("login_required"):
                raise RuntimeError("ElevenLabs login is required in the configured Chrome profile.")
            time.sleep(self.poll_seconds)
        raise RuntimeError(f"ElevenLabs composer did not become ready: {last.get('summary', 'unknown page state')}")

    def snapshot(self) -> dict[str, Any]:
        return self._json("""(() => {
          const visible = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
          const text = document.body?.innerText || '';
          const controls = [...document.querySelectorAll('button,a,[role=button]')]
            .filter(visible).map(e => ({text:(e.innerText||'').trim(), aria:e.getAttribute('aria-label')||'', title:e.getAttribute('title')||''}));
          const input = [...document.querySelectorAll('textarea')].find(e => visible(e) && /start typing|paste text/i.test(e.placeholder||''));
          const generate = controls.find(c => /^generate$/i.test(c.text) || /^generate$/i.test(c.aria));
          const download = controls.filter(c => /download|export/i.test(`${c.text} ${c.aria} ${c.title}`));
          return {
            url: location.href, title: document.title, ready: !!input && !!generate,
            login_required: /sign in|log in|create an account/i.test(text) && !input,
            busy: /generating|queued|creating audio|please wait|processing/i.test(text) || !!document.querySelector('[aria-busy=true],[role=progressbar]'),
            downloads: download, summary: text.slice(0, 1600), generate
          };
        })()""")

    def set_text(self, text: str) -> None:
        encoded = json.dumps(text)
        result = self._json(f"""(() => {{
          const visible = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
          const e = [...document.querySelectorAll('textarea')].find(x => visible(x) && /start typing|paste text/i.test(x.placeholder||''));
          if (!e) return {{ok:false, reason:'narration textarea not found'}};
          const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
          setter.call(e, {encoded});
          e.dispatchEvent(new Event('input', {{bubbles:true}}));
          e.dispatchEvent(new Event('change', {{bubbles:true}}));
          e.focus();
          return {{ok:true, characters:e.value.length}};
        }})()""")
        if not result.get("ok") or int(result.get("characters") or 0) != len(text):
            raise RuntimeError(f"ElevenLabs narration input failed: {result.get('reason', 'text length mismatch')}")

    def select_option(self, kind: str, requested: str) -> None:
        """Open a visible control and choose a visible exact/starts-with option.

        Defaults are intentionally left untouched; this is used only for an
        explicit CLI/env parameter and fails loudly rather than guessing.
        """
        tooltip = "Model" if kind == "model" else "Voice"
        self._trusted_click(f"""(() => {{
          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          const e=[...document.querySelectorAll('button,[role=button]')].filter(visible).find(x=>(x.getAttribute('data-agent-tooltip')||'')==={json.dumps(tooltip)});
          if(!e) return {{ok:false}}; const r=e.getBoundingClientRect(); return {{ok:true,x:r.left+r.width/2,y:r.top+r.height/2}};
        }})()""")
        if kind == "voice":
            # The compact menu is intentionally only a recent-voices list.
            # Enter the full catalog so a profile is not silently limited to it.
            self._trusted_click("""(() => { const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length); const e=[...document.querySelectorAll('[role=menuitem],button,[role=button]')].filter(visible).find(x=>/^all voices$/i.test((x.innerText||'').trim())); if(!e)return {ok:false};const r=e.getBoundingClientRect();return {ok:true,x:r.left+r.width/2,y:r.top+r.height/2}; })()""")
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                search = self._json("""(() => { const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length); const e=[...document.querySelectorAll('input')].find(x=>visible(x)&&/search/i.test(`${x.placeholder||''} ${x.getAttribute('aria-label')||''}`)); if(!e)return {ok:false}; return {ok:true}; })()""")
                if search.get("ok"):
                    self._json(f"""(() => {{ const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length); const e=[...document.querySelectorAll('input')].find(x=>visible(x)&&/search/i.test(`${{x.placeholder||''}} ${{x.getAttribute('aria-label')||''}}`)); const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;setter.call(e,{json.dumps(requested)});e.dispatchEvent(new Event('input',{{bubbles:true}}));return {{ok:true}}; }})()""")
                    break
                time.sleep(0.5)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            point = self._json(f"""(() => {{
              const wanted={json.dumps(requested)}.trim().toLowerCase();
              const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
              const choices=[...document.querySelectorAll('[role=option],button,[role=button],li')].filter(visible);
              const e=choices.find(x=>{{const t=(x.innerText||x.getAttribute('aria-label')||'').trim().toLowerCase(); return t===wanted||t.startsWith(wanted+' ')||t.startsWith(wanted+'-');}});
              if(!e) return {{ok:false}}; const r=e.getBoundingClientRect(); return {{ok:true,x:r.left+r.width/2,y:r.top+r.height/2}};
            }})()""")
            if point.get("ok"):
                self._trusted_click(f"""(() => {{ return {json.dumps(point)}; }})()""")
                return
            time.sleep(0.5)
        raise RuntimeError(f"ElevenLabs did not show the requested {kind} option '{requested}'.")

    def apply_numeric_setting(self, label: str, value: float) -> None:
        self._json("""(() => { const e=[...document.querySelectorAll('button,[role=button]')].find(x=>/more options|voice settings/i.test(`${x.innerText||''} ${x.getAttribute('aria-label')||''}`)); if(!e)return {ok:false};e.click();return {ok:true}; })()""")
        result = self._json(f"""(() => {{
          const wanted={json.dumps(label)}.toLowerCase(); const value={float(value)};
          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          const labelNode=[...document.querySelectorAll('label,span,p,div')].find(x=>visible(x)&&(x.innerText||'').trim().toLowerCase()===wanted);
          const scope=labelNode?.parentElement?.parentElement || labelNode?.parentElement;
          const input=scope?.querySelector('input[type=range]') || [...document.querySelectorAll('input[type=range]')].find(visible);
          if(!input)return {{ok:false}};
          const min=Number(input.min||0), max=Number(input.max||1); if(value<min||value>max)return {{ok:false,range:[min,max]}};
          const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; setter.call(input,String(value));
          input.dispatchEvent(new Event('input',{{bubbles:true}})); input.dispatchEvent(new Event('change',{{bubbles:true}})); return {{ok:true}};
        }})()""")
        if not result.get("ok"):
            raise RuntimeError(f"Could not set ElevenLabs '{label}' to {value}; verify this account's current UI and allowed range.")

    def apply_settings(self, settings: VoiceSettings) -> None:
        if settings.model:
            self.select_option("model", settings.model)
        if settings.voice:
            self.select_option("voice", settings.voice)
        for label, value in (("Speed", settings.speed), ("Stability", settings.stability), ("Similarity", settings.similarity), ("Style", settings.style)):
            if value is not None:
                self.apply_numeric_setting(label, value)
        if settings.speaker_boost is not None:
            wanted = bool(settings.speaker_boost)
            result = self._json(f"""(() => {{ const labels=[...document.querySelectorAll('label')]; const l=labels.find(x=>/speaker boost/i.test(x.innerText||'')); const i=l?.querySelector('input')||l?.parentElement?.querySelector('input[type=checkbox]'); if(!i)return {{ok:false}}; if(i.checked!=={str(wanted).lower()}) i.click(); return {{ok:true}}; }})()""")
            if not result.get("ok"):
                raise RuntimeError("Could not set ElevenLabs Speaker boost in the current UI.")

    def submit(self) -> None:
        self._trusted_click("""(() => { const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length); const e=[...document.querySelectorAll('button,[role=button]')].filter(visible).find(x=>/^generate$/i.test((x.innerText||'').trim())||/^generate$/i.test(x.getAttribute('aria-label')||'')); if(!e||e.disabled||e.getAttribute('aria-disabled')==='true')return {ok:false};const r=e.getBoundingClientRect();return {ok:true,x:r.left+r.width/2,y:r.top+r.height/2}; })()""")

    def refresh(self) -> None:
        self._json("""(() => { location.reload(); return {ok:true}; })()""")

    def download_best_available(self) -> dict[str, Any]:
        """Click the visible UI download option with the strongest advertised format."""
        return self._json("""(() => {
          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          const controls=[...document.querySelectorAll('button,a,[role=button],[role=menuitem]')].filter(visible);
          const candidates=controls.map(e=>({e,t:`${e.innerText||''} ${e.getAttribute('aria-label')||''} ${e.getAttribute('title')||''}`.trim()})).filter(x=>/download|export/i.test(x.t));
          if(!candidates.length)return {ok:false,reason:'no visible download control'};
          const score=t=>{const n=(t.match(/(\\d+)\\s*kbps/i)||[])[1]||0;return (/\\bwav\\b/i.test(t)?1000000:0)+(/\\bflac\\b/i.test(t)?900000:0)+Number(n)*100+(/download/i.test(t)?1:0)};
          candidates.sort((a,b)=>score(b.t)-score(a.t)); candidates[0].e.click();
          return {ok:true,choice:candidates[0].t};
        })()""")


def narration_input(project: Path) -> tuple[Path, str]:
    canonical = project / "voiceover" / "VOICEOVER_INPUT.txt"
    source = canonical if canonical.exists() else project / "SCRIPT_FINAL.md"
    if not source.is_file():
        raise RuntimeError("No voiceover input found: create voiceover/VOICEOVER_INPUT.txt or complete SCRIPT_FINAL.md first.")
    text = source.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError("Voiceover input is empty.")
    if source != canonical:
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text(text + "\n", encoding="utf-8")
    return canonical, text


def find_download(download_dir: Path, started_at: float) -> Path | None:
    candidates = [path for path in download_dir.glob("*") if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS and path.stat().st_mtime >= started_at - 2]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def configure_ordak_browser_environment() -> None:
    """Apply the same root-env mapping used by the Ordak service launcher."""
    from run_ordak import ENV_MAP

    env_file = (ROOT / os.getenv("YT_ENV_FILE", ".env")).resolve()
    os.environ["ORDAK_ENV_FILE"] = str(env_file)
    for source, target in ENV_MAP.items():
        value = os.getenv(source, "").strip()
        if value:
            os.environ[target] = value
    os.environ["BROWSER_HEADLESS"] = "false"
    os.environ["BROWSER_LINUX_X11_FALLBACK_ENABLED"] = "false"


def main() -> None:
    load_dotenv(ROOT / os.getenv("YT_ENV_FILE", ".env"), override=False)
    configure_ordak_browser_environment()
    parser = argparse.ArgumentParser(description="Generate a full narration through the logged-in ElevenLabs web UI.")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--project", type=Path, default=None, help="Defaults to the unique videos/<id>_* directory.")
    parser.add_argument("--voice", default=os.getenv("YT_ELEVENLABS_DEFAULT_VOICE") or None)
    parser.add_argument("--model", default=os.getenv("YT_ELEVENLABS_DEFAULT_MODEL") or None)
    parser.add_argument("--profile", type=Path, default=ROOT / "voice_profiles" / "elevenlabs_mark_default.json", help="Versioned JSON voice profile; CLI values override it.")
    parser.add_argument("--speed", type=float, default=None)
    parser.add_argument("--stability", type=float, default=None)
    parser.add_argument("--similarity", type=float, default=None)
    parser.add_argument("--style", type=float, default=None)
    parser.add_argument("--speaker-boost", choices=("true", "false"), default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Verify authenticated UI and persisted inputs without generating audio.")
    args = parser.parse_args()
    projects = list((ROOT / "videos").glob(f"{args.video_id}_*")) if args.project is None else [args.project]
    if len(projects) != 1:
        raise RuntimeError(f"Expected exactly one project for video ID {args.video_id}; pass --project explicitly.")
    project = projects[0].resolve()
    input_path, text = narration_input(project)
    profile: dict[str, Any] = {}
    if args.profile:
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
    def choose(name: str, cli_value: Any) -> Any:
        return cli_value if cli_value is not None else profile.get(name)
    settings = VoiceSettings(choose("voice", args.voice), choose("model", args.model), choose("speed", args.speed), choose("stability", args.stability), choose("similarity", args.similarity), choose("style", args.style), choose("speaker_boost", None if args.speaker_boost is None else args.speaker_boost == "true"))
    voiceover_dir = project / "voiceover"
    state = State(voiceover_dir / "ELEVENLABS_RUNTIME_STATE.json", video_id=args.video_id, input_path=input_path, text=text, settings=settings)
    output_dir = project / "assets" / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = next((output_dir / f"narration{extension}" for extension in AUDIO_EXTENSIONS if (output_dir / f"narration{extension}").is_file()), None)
    if existing and not args.force:
        state.data.update({"status": "DONE", "output": str(existing.relative_to(project))})
        state.save()
        print(f"ELEVENLABS VOICEOVER: PASS (reused {existing})")
        return
    notifier = PipelineNotifier(args.video_id, project.name)
    started = time.perf_counter()
    ui = ElevenLabsUI(poll_seconds=float(os.getenv("YT_ELEVENLABS_POLL_SECONDS", "5")), stall_seconds=float(os.getenv("YT_ELEVENLABS_STALL_REFRESH_SECONDS", "90")), max_refreshes=int(os.getenv("YT_ELEVENLABS_MAX_STALL_REFRESHES", "3")))
    try:
        ui.open_and_verify()
        state.data["status"] = "UI_READY"; state.save()
        state.event("elevenlabs_ui_ready", started)
        if args.dry_run:
            notifier.stage_complete("ElevenLabs UI readiness", time.perf_counter() - started, artifact=str(input_path.relative_to(project)))
            print("ELEVENLABS VOICEOVER: DRY RUN PASS")
            return
        configured_at = time.perf_counter()
        ui.apply_settings(settings)
        state.event("elevenlabs_settings_applied", configured_at, settings=settings.supplied())
        ui.set_text(text)
        state.data["status"] = "TEXT_ENTERED"; state.save()
        state.event("elevenlabs_text_entered", configured_at, characters=len(text))
        submit_at = time.perf_counter()
        ui.submit()
        state.data.update({"status": "SUBMITTED", "submitted_at": utcnow()}); state.save()
        state.event("elevenlabs_submit", submit_at)
        notifier.send("ElevenLabs generation submitted", ["🎙️ Full narration requested", f"📝 Characters: {len(text)}", "👀 Waiting for the web UI result"])
        download_dir = Path(os.getenv("YT_ELEVENLABS_DOWNLOAD_DIR", str(Path.home() / "Downloads"))).expanduser()
        download_dir.mkdir(parents=True, exist_ok=True)
        last_change, refreshes, download_started = time.monotonic(), 0, time.time()
        prior_signature = ""
        deadline = time.monotonic() + float(os.getenv("YT_ELEVENLABS_GENERATION_TIMEOUT_SECONDS", "900"))
        while time.monotonic() < deadline:
            snapshot = ui.snapshot()
            signature = json.dumps({"busy": snapshot.get("busy"), "downloads": snapshot.get("downloads"), "summary": snapshot.get("summary", "")[:500]}, sort_keys=True)
            if signature != prior_signature:
                prior_signature, last_change = signature, time.monotonic()
            downloaded = find_download(download_dir, download_started)
            if downloaded:
                destination = output_dir / f"narration{downloaded.suffix.lower()}"
                shutil.move(str(downloaded), destination)
                if destination.stat().st_size < 1024:
                    raise RuntimeError("ElevenLabs download is unexpectedly small.")
                state.data.update({"status": "DONE", "output": str(destination.relative_to(project)), "completed_at": utcnow()})
                state.event("elevenlabs_download", submit_at, bytes=destination.stat().st_size, output=str(destination.relative_to(project)))
                json_dump(voiceover_dir / "VOICE_PROFILE.json", {"provider": "ElevenLabs web UI", "settings": settings.supplied(), "input_sha256": digest(text), "output": str(destination.relative_to(project)), "generated_at": utcnow()})
                notifier.stage_complete("ElevenLabs voiceover", time.perf_counter() - started, artifact=str(destination.relative_to(project)))
                print(f"ELEVENLABS VOICEOVER: PASS\nAudio: {destination}")
                return
            if snapshot.get("downloads") and not state.data.get("download_choice"):
                choice = ui.download_best_available()
                if choice.get("ok"):
                    state.data["download_choice"] = choice.get("choice"); state.data["status"] = "DOWNLOAD_TRIGGERED"; state.save()
                    download_started = time.time()
                    notifier.send("ElevenLabs audio ready", ["⬇️ Highest visible quality download requested", f"🎚️ Option: {choice.get('choice', 'Download')[:180]}"])
            if not snapshot.get("busy") and time.monotonic() - last_change >= ui.stall_seconds:
                if refreshes >= ui.max_refreshes:
                    raise RuntimeError("ElevenLabs UI made no progress and did not expose a downloadable result after all recovery refreshes.")
                refreshes += 1
                ui.refresh()
                state.event("elevenlabs_stall_refresh", started, refresh_number=refreshes)
                notifier.warning("ElevenLabs recovery refresh", f"No UI progress for {format_duration(ui.stall_seconds)}; refresh {refreshes}/{ui.max_refreshes} completed.")
                last_change = time.monotonic()
            time.sleep(ui.poll_seconds)
        raise RuntimeError("ElevenLabs generation exceeded the configured timeout.")
    except Exception as exc:
        state.data.update({"status": "FAILED", "error": str(exc), "failed_at": utcnow()}); state.save()
        notifier.failure("ElevenLabs voiceover", time.perf_counter() - started, str(exc))
        raise


if __name__ == "__main__":
    main()

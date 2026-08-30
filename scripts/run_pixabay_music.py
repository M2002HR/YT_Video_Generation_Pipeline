#!/usr/bin/env python3
"""Select and download background music through real ChatGPT and Pixabay UIs.

No ChatGPT, Pixabay, or media API is used.  Ordak is the only browser-control
layer.  A Cloudflare human-verification interstitial is detected explicitly and
reported without trying to bypass it; resume the same command after it has
been completed in the visible VNC browser.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from pipeline_notifier import PipelineNotifier


ROOT = Path(__file__).resolve().parents[1]
PIXABAY_URL_RE = re.compile(r"https?://(?:www\.)?pixabay\.com/music/[\w/-]+", re.I)
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
        if self.tab is None:
            raise RuntimeError("No ChatGPT tab is selected.")
        point = self.data("""(() => { const e=[...document.querySelectorAll('textarea,[contenteditable=true]')].find(x=>!!(x.offsetWidth||x.offsetHeight||x.getClientRects().length)&&/new chat/i.test(`${x.getAttribute('aria-label')||''} ${x.placeholder||''}`));if(!e)return {ok:false};const r=e.getBoundingClientRect();return {ok:true,x:r.left+r.width/2,y:r.top+r.height/2}; })()""")
        self.point_click(f"(() => {{ return {json.dumps(point)}; }})()")
        info = self.get_info(self.tab)
        from websockets.sync.client import connect
        with connect(info.websocket_debugger_url, proxy=None, open_timeout=5, close_timeout=5) as ws:
            def request(i: int, method: str, params: dict[str, Any]) -> None:
                ws.send(json.dumps({"id": i, "method": method, "params": params}))
                while True:
                    if (reply := json.loads(ws.recv())).get("id") == i:
                        if reply.get("error"):
                            raise RuntimeError("Chrome rejected ChatGPT input.")
                        return
            request(1, "Input.insertText", {"text": text})
            request(2, "Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "modifiers": 2})
            request(3, "Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "modifiers": 2})


def choose_track(browser: Browser, project_url: str, prompt: str) -> str:
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
        found = PIXABAY_URL_RE.search(text)
        if found:
            return found.group(0).rstrip("/.") + "/"
        time.sleep(2)
    raise RuntimeError("ChatGPT did not return a Pixabay Music URL.")


def pixabay_snapshot(browser: Browser) -> dict[str, Any]:
    return browser.data("""(() => { const text=document.body?.innerText||''; const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length); const button=[...document.querySelectorAll('button,a')].find(e=>visible(e)&&/^free download$/i.test((e.innerText||'').trim())); const r=button?.getBoundingClientRect(); return {ready:!!button, downloading:/downloading/i.test(text), challenge:/verify you are human|turnstile|captcha/i.test(text)||!!document.querySelector('iframe[src*=turnstile],iframe[src*=challenge]'), text:text.slice(0,2500), point:button?{ok:true,x:r.left+r.width/2,y:r.top+r.height/2}:null}; })()""")


def newest_download(directory: Path, after: float) -> Path | None:
    files = [p for p in directory.glob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS and p.stat().st_mtime >= after - 2]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def main() -> None:
    load_dotenv(ROOT / os.getenv("YT_ENV_FILE", ".env"), override=False)
    parser = argparse.ArgumentParser(description="Choose/download Pixabay music through ChatGPT and the visible browser.")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--pixabay-url", help="Skip ChatGPT selection and resume this exact Pixabay URL.")
    args = parser.parse_args()
    projects = [args.project.resolve()] if args.project else list((ROOT / "videos").glob(f"{args.video_id}_*"))
    if len(projects) != 1:
        raise RuntimeError("Pass --project when the video directory is ambiguous.")
    project = projects[0]
    music_dir, meta_path = project / "assets" / "music", project / "music" / "PIXABAY_SELECTION.json"
    notifier = PipelineNotifier(args.video_id, project.name)
    started = time.perf_counter()
    browser = Browser()
    prompt = ("Recommend exactly one Pixabay Music track for this short English explainer. "
              "Topic: why people forget why they walked into a room. Need a warm, subtle, reflective instrumental, "
              "safe below narration; no lyrics, no dramatic beat drops. Reply with only one direct pixabay.com/music/ track URL.")
    url = args.pixabay_url or choose_track(browser, os.getenv("YT_CHATGPT_PROJECT_URL", "https://chatgpt.com/g/g-p-6a9476ed80b08191a4db1065939e08b6/project"), prompt)
    dump(meta_path, {"schema_version": 1, "provider": "Pixabay web UI", "source_url": url, "selection_prompt": prompt, "selected_at": utcnow(), "status": "SELECTED"})
    notifier.send("Pixabay music selected", ["🎵 Background track chosen", f"🔗 Source: {url}"])
    browser.select_or_open(url)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        snap = pixabay_snapshot(browser)
        if snap.get("challenge"):
            dump(meta_path, {"schema_version": 1, "provider": "Pixabay web UI", "source_url": url, "status": "HUMAN_VERIFICATION_REQUIRED", "detected_at": utcnow()})
            raise RuntimeError("Pixabay requires visible Cloudflare human verification in VNC; complete it, then rerun this command.")
        if snap.get("ready"):
            break
        time.sleep(1)
    else:
        raise RuntimeError("Pixabay Free download control did not become ready.")
    download_dir = Path(os.getenv("YT_PIXABAY_DOWNLOAD_DIR", str(Path.home() / "Downloads"))).expanduser()
    download_started = time.time()
    browser.point_click(f"(() => {{ return {json.dumps(snap['point'])}; }})()")
    deadline = time.monotonic() + float(os.getenv("YT_PIXABAY_DOWNLOAD_TIMEOUT_SECONDS", "180"))
    while time.monotonic() < deadline:
        download = newest_download(download_dir, download_started)
        if download:
            music_dir.mkdir(parents=True, exist_ok=True)
            destination = music_dir / f"background{download.suffix.lower()}"
            shutil.move(str(download), destination)
            dump(meta_path, {"schema_version": 1, "provider": "Pixabay web UI", "source_url": url, "downloaded_at": utcnow(), "status": "DONE", "file": str(destination.relative_to(project)), "bytes": destination.stat().st_size, "license": "Pixabay Content License; verify current source page before publication."})
            notifier.stage_complete("Pixabay background music", time.perf_counter() - started, artifact=str(destination.relative_to(project)))
            print(f"PIXABAY MUSIC: PASS\nFile: {destination}")
            return
        time.sleep(2)
    dump(meta_path, {"schema_version": 1, "provider": "Pixabay web UI", "source_url": url, "status": "DOWNLOAD_TIMEOUT", "updated_at": utcnow()})
    raise RuntimeError("Pixabay download did not reach Chrome's download directory before timeout.")


if __name__ == "__main__":
    main()

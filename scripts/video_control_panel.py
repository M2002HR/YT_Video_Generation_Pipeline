#!/usr/bin/env python3
"""Small authenticated-behind-nginx launch panel for the full video pipeline."""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRESET = "001_cinematic_storybook_green_hoodie"
LAUNCH_LOCK = threading.Lock()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return result or "video"


def next_video_id() -> str:
    ids = []
    for path in (ROOT / "videos").iterdir():
        match = re.match(r"^(\d+)_", path.name)
        if match:
            ids.append(int(match.group(1)))
    return f"{max(ids, default=0) + 1:03d}"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pid_is_live(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        # A zombie process has exited and must never block the next launch.
        if Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2] == "Z":
            return False
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return False


def active_job(jobs_dir: Path) -> dict | None:
    for path in jobs_dir.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if job.get("status") == "RUNNING" and pid_is_live(job.get("pid")):
            return job
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoControlPanel/1.0"

    @property
    def jobs_dir(self) -> Path:
        return ROOT / "control_panel" / "jobs"

    def send_html(self, status: int, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers(); self.wfile.write(encoded)

    def page(self, message: str = "") -> str:
        jobs = []
        for path in sorted(self.jobs_dir.glob("*.json"), reverse=True)[:12]:
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job.get("status") == "RUNNING" and isinstance(job.get("pid"), int):
                    if not pid_is_live(job["pid"]):
                        log = self.jobs_dir / f"{job.get('job_id')}.log"
                        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
                        job["status"] = "DONE" if "FULL VIDEO PIPELINE: PASS" in text else "FAILED"
                        job["completed_at"] = utcnow(); write_json(path, job)
                jobs.append(job)
            except Exception: continue
        rows = "".join(f"<tr><td>{html.escape(str(j.get('video_id','')))}</td><td>{html.escape(str(j.get('topic','')))}</td><td>{html.escape(str(j.get('status','QUEUED')))}</td><td><a href='/logs/{html.escape(str(j.get('job_id','')))}'>log</a></td></tr>" for j in jobs) or "<tr><td colspan='4'>No launches yet.</td></tr>"
        return f"""<!doctype html><meta charset=utf-8><title>Video Pipeline</title>
<style>body{{font:16px system-ui;max-width:850px;margin:32px auto;background:#10131a;color:#e8edf4}}input,select{{width:100%;padding:8px;margin:4px 0 14px;box-sizing:border-box}}button{{padding:10px 18px;background:#58c;color:#fff;border:0;border-radius:5px}}table{{width:100%;border-collapse:collapse;margin-top:28px}}td,th{{padding:8px;border-bottom:1px solid #344;text-align:left}}.msg{{color:#8f8}}</style>
<h1>Video Pipeline Launch</h1><p class=msg>{html.escape(message)}</p>
<form method=post action=/launch><label>Topic<input name=topic required maxlength=220 placeholder="Why you forget why you entered a room"></label>
<label>Minimum duration (seconds)<input name=min_duration_seconds type=number min=15 max=300 value=60 required></label>
<label>Maximum duration (seconds)<input name=max_duration_seconds type=number min=15 max=300 value=90 required></label>
<label>Frame format<select name=aspect_ratio><option value="16:9">16:9 — YouTube landscape</option><option value="9:16">9:16 — Shorts / Reels vertical</option></select></label>
<label>Voice<input name=voice value="Mark - Natural Conversations" required></label>
<label>ElevenLabs model<select name=model><option>Eleven Multilingual v2</option><option>Eleven v3</option></select></label>
<label>Speed<input name=speed type=number min=.7 max=1.2 step=.01 value=.9 required></label>
<label>Stability<input name=stability type=number min=0 max=1 step=.01 value=.45 required></label>
<label>Similarity<input name=similarity type=number min=0 max=1 step=.01 value=.75 required></label>
<label>Style / exaggeration<input name=style type=number min=0 max=1 step=.01 value=.10 required></label>
<label>Music provider<select name=music_provider><option value=mixkit>Mixkit</option><option value=pixabay>Pixabay</option></select></label>
<button type=submit>Launch full pipeline</button></form>
<h2>Recent runs</h2><table><tr><th>ID</th><th>Topic</th><th>Status</th><th>Live log</th></tr>{rows}</table>"""

    def do_GET(self) -> None:
        if self.path == "/": self.send_html(HTTPStatus.OK, self.page()); return
        if self.path.startswith("/logs/"):
            job_id = Path(self.path).name
            if not re.fullmatch(r"[a-f0-9-]{36}", job_id): self.send_error(HTTPStatus.NOT_FOUND); return
            log = self.jobs_dir / f"{job_id}.log"
            text = log.read_text(encoding="utf-8", errors="replace")[-120_000:] if log.exists() else "Waiting for runner output..."
            self.send_html(HTTPStatus.OK, f"<meta http-equiv=refresh content=5><pre>{html.escape(text)}</pre>"); return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/launch": self.send_error(HTTPStatus.NOT_FOUND); return
        length = int(self.headers.get("Content-Length", "0")); values = parse_qs(self.rfile.read(length).decode("utf-8"))
        try:
            topic = values["topic"][0].strip(); video_id = next_video_id()
            duration_min = float(values["min_duration_seconds"][0]); duration_max = float(values["max_duration_seconds"][0]); aspect_ratio = values["aspect_ratio"][0]; voice = values["voice"][0].strip(); model = values["model"][0].strip()
            speed, stability, similarity, style = (float(values[k][0]) for k in ("speed", "stability", "similarity", "style"))
            provider = values["music_provider"][0]
            if not topic or not 15 <= duration_min <= duration_max <= 300 or aspect_ratio not in {"16:9", "9:16"} or not voice or provider not in {"mixkit", "pixabay"} or not .7 <= speed <= 1.2 or not all(0 <= value <= 1 for value in (stability, similarity, style)):
                raise ValueError("Invalid launch values.")
        except (KeyError, ValueError) as exc:
            self.send_html(HTTPStatus.BAD_REQUEST, self.page(str(exc))); return
        with LAUNCH_LOCK:
            active = active_job(self.jobs_dir)
            if active is not None:
                self.send_html(HTTPStatus.CONFLICT, self.page(f"Video {active.get('video_id')} is already running. Wait for it to finish before launching another.")); return
            # Allocate inside the critical section so two quick submissions can
            # never receive the same ID or run concurrently.
            video_id = next_video_id()
            project = ROOT / "videos" / f"{video_id}_{slug(topic)}"; profile = project / "voiceover" / "REQUESTED_VOICE_PROFILE.json"
            write_json(profile, {"voice": voice, "model": model, "speed": speed, "stability": stability, "similarity": similarity, "style": style, "speaker_boost": False, "output_format": "MP3 44.1 kHz (128kbps)"})
            job_id = str(uuid.uuid4()); record = {"schema_version": 3, "job_id": job_id, "status": "RUNNING", "created_at": utcnow(), "topic": topic, "video_id": video_id, "duration_min_seconds": duration_min, "duration_max_seconds": duration_max, "aspect_ratio": aspect_ratio, "project": str(project.relative_to(ROOT)), "voice_profile": str(profile.relative_to(ROOT))}
            request = project / "launch" / "LAUNCH_REQUEST.json"; write_json(request, record); write_json(self.jobs_dir / f"{job_id}.json", record)
            log = self.jobs_dir / f"{job_id}.log"; handle = log.open("w", encoding="utf-8")
            # The panel's live-log page is a monitoring surface.  Run Python
            # unbuffered so each stage is observable immediately instead of
            # appearing only when the complete pipeline exits.
            command = [sys.executable, "-u", "scripts/run_full_video_pipeline.py", "--topic", topic, "--video-id", video_id, "--min-duration-seconds", str(duration_min), "--max-duration-seconds", str(duration_max), "--aspect-ratio", aspect_ratio, "--voice-profile", str(profile), "--music-provider", provider]
            process = subprocess.Popen(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
            record.update({"pid": process.pid, "command": command, "started_at": utcnow()}); write_json(request, record); write_json(self.jobs_dir / f"{job_id}.json", record)
        self.send_html(HTTPStatus.ACCEPTED, self.page(f"Launched {video_id}; live log is available in the table."))


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--host", default="127.0.0.1"); parser.add_argument("--port", type=int, default=4142); args = parser.parse_args()
    (ROOT / "control_panel" / "jobs").mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Video control panel: http://{args.host}:{args.port}", flush=True); server.serve_forever()


if __name__ == "__main__": main()

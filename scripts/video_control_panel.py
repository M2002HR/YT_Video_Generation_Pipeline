#!/usr/bin/env python3
"""Launch panel for the full video pipeline — now with Question Harvest §§62-64."""
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

from content_projects import (
    DEFAULT_CONTENT_PROJECT, list_content_projects, load_content_project,
    validate_content_project, validate_provider_locks, normalize_gemini_model, normalize_flow_model, video_slug
)

ROOT = Path(__file__).resolve().parents[1]
LAUNCH_LOCK = threading.Lock()
PREFERRED_CONTENT_PROJECT = "question_harvest"
CREATIVE_FIELDS = ("working_title", "audience", "narrative_angle", "must_include", "must_avoid", "source_notes")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def form_text(values: dict[str, list[str]], key: str, limit: int = 4_000) -> str:
    value = values.get(key, [""])[0].strip()
    if len(value) > limit:
        raise ValueError(f"{key} is too long (maximum {limit} characters).")
    return value


def pid_is_live(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
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


def reconcile_stuck_jobs_once() -> None:
    """Mark defunct RUNNING jobs as FAILED without requiring a page load (§81, permanent anti-stuck)."""
    jobs_dir = ROOT / "control_panel" / "jobs"
    for path in jobs_dir.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("status") != "RUNNING" or not isinstance(job.get("pid"), int):
                continue
            if pid_is_live(job["pid"]):
                continue
            log = jobs_dir / f"{job.get('job_id')}.log"
            text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
            # consider success only if pipeline explicitly reported PASS
            if "FULL VIDEO PIPELINE: PASS" in text or "QH CORE STAGES DONE" in text or "FULL QH PIPELINE: PASS" in text or "COMPLETION PIPELINE: PASS" in text or "QH PIPELINE BODY IMAGES" in text:
                # body images done but wrapper may have failed later — still mark DONE only if final reports exist
                # check for final.mp4 QC pass
                try:
                    proj = ROOT / str(job.get("project", ""))
                    if (proj / "assets" / "renders" / "final.mp4").is_file() and (proj / "render" / "QC_REPORT.json").is_file():
                        job["status"] = "DONE"
                    else:
                        job["status"] = "FAILED"
                except Exception:
                    job["status"] = "FAILED"
            else:
                job["status"] = "FAILED"
            job["completed_at"] = utcnow()
            # preserve original pid for audit but mark completed
            write_json(path, job)
            # also update launch request
            try:
                proj = ROOT / str(job.get("project", ""))
                req = proj / "launch" / "LAUNCH_REQUEST.json"
                if req.is_file():
                    rq = json.loads(req.read_text(encoding="utf-8"))
                    rq["status"] = job["status"]
                    rq["completed_at"] = job["completed_at"]
                    write_json(req, rq)
            except Exception:
                pass
        except Exception:
            continue

def reconcile_scheduled_resumes() -> None:
    for path in (ROOT / "control_panel" / "jobs").glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("status") != "SCHEDULED" or not job.get("image_limit_schedule"):
                continue
            project = ROOT / str(job["project"])
            subprocess.run([sys.executable, "scripts/schedule_image_limit_resume.py", str(project), "--no-notify"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (KeyError, OSError, subprocess.SubprocessError, json.JSONDecodeError):
            continue

def start_stuck_job_reconciler(interval: int = 30) -> None:
    """Background thread to periodically reconcile stuck jobs — permanent anti-hang (§81)."""
    def loop() -> None:
        while True:
            try:
                reconcile_stuck_jobs_once()
            except Exception:
                pass
            import time
            time.sleep(interval)
    t = threading.Thread(target=loop, daemon=True, name="stuck-job-reconciler")
    t.start()


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoControlPanel/2.0"

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
                        job["status"] = "DONE" if ("FULL VIDEO PIPELINE: PASS" in text or "QH PIPELINE BODY IMAGES" in text or "COMPLETION PIPELINE: PASS" in text) else "FAILED"
                        job["completed_at"] = utcnow(); write_json(path, job)
                jobs.append(job)
            except Exception: continue
        rows = "".join(f"<tr><td>{html.escape(str(j.get('video_id','')))}</td><td>{html.escape(str(j.get('content_project', DEFAULT_CONTENT_PROJECT)))}</td><td>{html.escape(str(j.get('topic','')))}</td><td>{html.escape(str(j.get('status','QUEUED')))}</td><td><a href='/logs/{html.escape(str(j.get('job_id','')))}'>log</a></td></tr>" for j in jobs) or "<tr><td colspan='5'>No launches yet.</td></tr>"
        project_options = "".join(f"<option value='{html.escape(p.project_id)}'{' selected' if p.project_id == PREFERRED_CONTENT_PROJECT else ''}>{html.escape(p.display_name)}</option>" for p in list_content_projects())
        return f"""<!doctype html><meta charset=utf-8><title>Video Pipeline — Question Harvest</title>
<style>
body{{font:16px system-ui;max-width:920px;margin:32px auto;background:#10131a;color:#e8edf4;padding:0 18px}}
input,select,textarea{{width:100%;padding:8px;margin:4px 0 14px;box-sizing:border-box;background:#1a2030;color:#e8edf4;border:1px solid #2a344a;border-radius:4px}}textarea{{min-height:76px;resize:vertical}}
small{{color:#aeb8c8}}button{{padding:11px 22px;background:#58c;color:#fff;border:0;border-radius:6px;font-weight:600;cursor:pointer}}button:hover{{background:#4aa}}
table{{width:100%;border-collapse:collapse;margin-top:28px}}td,th{{padding:8px;border-bottom:1px solid #344;text-align:left}}.msg{{color:#8f8;background:#1a2a1a;padding:8px;border-radius:4px;min-height:18px}}
fieldset{{border:1px solid #334;margin:16px 0;padding:14px 14px 6px;border-radius:6px}}legend{{padding:0 8px;color:#8ab4ff;font-weight:600}}
.notice{{background:#1e293b;padding:10px;border-radius:6px;margin:12px 0;font-size:14px;border-left:4px solid #58c}}
.badge{{display:inline-block;background:#2a3a5a;color:#8ab4ff;padding:2px 7px;border-radius:10px;font-size:12px;margin-left:6px}}
</style>
<h1>Video Pipeline Launch</h1><p class=msg>{html.escape(message)}</p>

<div class=notice>
 <strong>Question Harvest</strong> — A question grows. A book opens. A world begins.<br>
 Providers: Text <span class=badge>ChatGPT / Ordak LOCKED</span> · Images <span class=badge>Gemini / Ordak LOCKED</span> · Videos <span class=badge>Google Flow / Ordak LOCKED</span><br>
 Flow canonical reference: <code>character_sheet.png ONLY</code> — Flow style sheet <strong>DISABLED</strong> by project design (§12). Book spread & world keyframe are scene frame inputs, not style sheets.
</div>

<script>
function onProjectChange() {{
  var sel = document.querySelector('select[name=content_project]').value;
  var qh = sel === 'question_harvest';
  document.getElementById('qh_advanced').style.display = qh ? 'block' : 'none';
  if (qh) {{
    // QH defaults per §64
    document.querySelector('input[name=min_duration_seconds]').value = 40;
    document.querySelector('input[name=max_duration_seconds]').value = 60;
    document.querySelector('select[name=aspect_ratio]').value = '9:16';
    var cb = document.querySelector('input[name=show_subtitles]');
    if (cb) cb.checked = false;
  }}
}}
</script>

<form method=post action=/launch>
 <fieldset><legend>Content Project & Topic</legend>
  <label>Content project <select name=content_project onchange="onProjectChange()">{project_options}</select></label>
  <label>Question / topic <input name=topic required maxlength=220 placeholder="Why do leaves change color in autumn?"></label>
  <label>Working title <small>(optional)</small> <input name=working_title maxlength=220 placeholder="The strange reason years feel shorter"></label>
  <label>Audience <small>(optional; overrides project default)</small> <input name=audience maxlength=500 placeholder="Curious adults who enjoy thoughtful explainers"></label>
  <label>Narrative angle <small>(optional)</small> <textarea name=narrative_angle maxlength=2000 placeholder="Start with a familiar moment, then explain the idea carefully through a surprising metaphor."></textarea></label>
  <label>Must include <small>(optional)</small> <textarea name=must_include maxlength=2000 placeholder="Key examples, questions, or points that must appear."></textarea></label>
  <label>Must avoid <small>(optional)</small> <textarea name=must_avoid maxlength=2000 placeholder="Claims, framing, spoilers, or visual motifs to avoid."></textarea></label>
  <label>Source notes / verified facts <small>(optional but recommended for factual topics)</small> <textarea name=source_notes maxlength=4000 placeholder="Paste only facts, links, quotations, or source summaries you have verified."></textarea></label>
 </fieldset>

 <fieldset><legend>Format & Duration</legend>
  <label>Minimum duration (seconds) <input name=min_duration_seconds type=number min=15 max=300 value=40 required></label>
  <label>Maximum duration (seconds) <input name=max_duration_seconds type=number min=15 max=300 value=60 required></label>
  <label>Frame format <select name=aspect_ratio><option value="16:9">16:9 — YouTube landscape</option><option value="9:16" selected>9:16 — Shorts / Reels vertical</option></select></label>
  <label><input type=checkbox name=show_subtitles> Show subtitles <small>(Question Harvest default: OFF §71)</small></label>
 </fieldset>

 <fieldset id="qh_advanced"><legend>Question Harvest — Advanced (auto when project = question_harvest)</legend>
  <label>Hero presence <select name=hero_presence_mode><option value=auto selected>auto (recommended)</option><option value=opener_only>opener_only</option><option value=limited_in_world>limited_in_world</option><option value=in_world>in_world</option></select> <small>auto chooses based on topic (§44)</small></label>
  <label>World style policy <select name=world_style_policy><option value=auto selected>auto</option><option value=reuse>reuse existing</option><option value=new>force new</option></select></label>
  <label>World style hint <small>(optional, e.g., “charcoal warm paper”)</small> <input name=world_style_hint maxlength=500 placeholder="e.g., charcoal, woodcut, ink wash …"></label>
  <label>Gemini Image Model <select name=gemini_image_model><option value=nano_banana_pro selected>Nano Banana Pro (default, best quality)</option><option value=nano_banana_2>Nano Banana 2</option></select> <small>Provider LOCKED to Gemini (§4)</small></label>
  <label>Flow Video Model <select name=flow_video_model><option value=gemini_omni_1_1_flash selected>Gemini Omni 1.1 Flash (default)</option><option value=veo_3_1_quality>Veo 3.1 Quality</option><option value=veo_3_1_fast>Veo 3.1 Fast</option><option value=veo_3_1_lite>Veo 3.1 Lite</option></select> <small>Provider LOCKED to Google Flow (§4)</small></label>
  <label>Flow Resolution <select name=flow_resolution><option value="720p" selected>720p (default)</option><option value="360p">360p Draft (where supported)</option></select></label>
  <label>Opening Clip A source duration <small>(Flow, default 6s → trimmed to ~5s)</small> <select name=opening_a_seconds><option value=4>4s</option><option value=5>5s</option><option value=6 selected>6s</option><option value=8>8s</option></select></label>
  <label>Opening Clip B source duration <small>(Flow, default 4s → trimmed to ~3s)</small> <select name=opening_b_seconds><option value=3>3s</option><option value=4 selected>4s</option><option value=6>6s</option><option value=8>8s</option></select></label>
 </fieldset>

 <fieldset><legend>Generation Engines (§62-63)</legend>
  <p style="font-size:14px;color:#aeb8c8">
   Text: <strong>ChatGPT / Ordak</strong> LOCKED<br>
   Images: <strong>Gemini / Ordak</strong> LOCKED — Nano Banana Pro default<br>
   Videos: <strong>Google Flow / Ordak</strong> LOCKED — Flow receives <code>character_sheet.png ONLY</code>, never a style sheet.<br>
   Flow character reference: <span style="color:#7fdb9a">ENABLED / required</span> · Flow style sheet: <span style="color:#ff8f8f">DISABLED by project design</span>
  </p>
 </fieldset>

 <fieldset><legend>Voice & Music</legend>
  <label>Voice <input name=voice value="Mark - Natural Conversations" required></label>
  <label>ElevenLabs model <select name=model><option>Eleven Multilingual v2</option><option>Eleven v3</option></select></label>
  <label>Speed <input name=speed type=number min=.7 max=1.2 step=.01 value=.9 required></label>
  <label>Stability <input name=stability type=number min=0 max=1 step=.01 value=.45 required></label>
  <label>Similarity <input name=similarity type=number min=0 max=1 step=.01 value=.75 required></label>
  <label>Style / exaggeration <input name=style type=number min=0 max=1 step=.01 value=.10 required></label>
  <label>Music provider <select name=music_provider><option value=mixkit>Mixkit</option><option value=pixabay>Pixabay</option></select></label>
 </fieldset>

 <button type=submit>Launch full pipeline</button>
</form>
<p><small>Tip: For Question Harvest, duration 40–60, 9:16, Nano Banana Pro + Gemini Omni 1.1 Flash + 720p are defaults per §64. Changing project updates defaults via JS.</small></p>
<h2>Recent runs</h2><table><tr><th>ID</th><th>Project</th><th>Topic</th><th>Status</th><th>Live log</th></tr>{rows}</table>
<script>onProjectChange();</script>
"""

    def do_GET(self) -> None:
        if self.path == "/": self.send_html(HTTPStatus.OK, self.page()); return
        if self.path.startswith("/logs/"):
            job_id = Path(self.path).name
            if not re.fullmatch(r"[a-f0-9-]{36}", job_id): self.send_error(HTTPStatus.NOT_FOUND); return
            log = self.jobs_dir / f"{job_id}.log"
            text = log.read_text(encoding="utf-8", errors="replace")[-150_000:] if log.exists() else "Waiting for runner output..."
            self.send_html(HTTPStatus.OK, f"<meta http-equiv=refresh content=5><pre style='white-space:pre-wrap;word-break:break-word'>{html.escape(text)}</pre>"); return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/launch": self.send_error(HTTPStatus.NOT_FOUND); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length"); return
        if length <= 0 or length > 32_000:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Launch form is too large"); return
        try:
            values = parse_qs(self.rfile.read(length).decode("utf-8"))
        except UnicodeDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Launch form must be UTF-8"); return
        try:
            topic = form_text(values, "topic", 220)
            content_project = values.get("content_project", [DEFAULT_CONTENT_PROJECT])[0].strip()
            available_projects = {project.project_id for project in list_content_projects()}
            duration_min = float(values["min_duration_seconds"][0]); duration_max = float(values["max_duration_seconds"][0])
            aspect_ratio = values["aspect_ratio"][0]; voice = values["voice"][0].strip(); model = values["model"][0].strip()
            speed, stability, similarity, style = (float(values[k][0]) for k in ("speed", "stability", "similarity", "style"))
            provider = values["music_provider"][0]
            show_subtitles = "show_subtitles" in values
            # QH advanced
            hero_presence_mode = values.get("hero_presence_mode", ["auto"])[0].strip() or "auto"
            world_style_policy = values.get("world_style_policy", ["auto"])[0].strip() or "auto"
            world_style_hint = form_text(values, "world_style_hint", 500) if values.get("world_style_hint") else ""
            gemini_image_model = values.get("gemini_image_model", ["nano_banana_pro"])[0].strip() or "nano_banana_pro"
            flow_video_model = values.get("flow_video_model", ["gemini_omni_1_1_flash"])[0].strip() or "gemini_omni_1_1_flash"
            flow_resolution = values.get("flow_resolution", ["720p"])[0].strip() or "720p"
            opening_a_seconds = int(values.get("opening_a_seconds", ["6"])[0])
            opening_b_seconds = int(values.get("opening_b_seconds", ["4"])[0])
            if not topic or content_project not in available_projects or not 15 <= duration_min <= duration_max <= 300 or aspect_ratio not in {"16:9", "9:16"} \
               or not voice or len(voice) > 220 or model not in {"Eleven Multilingual v2", "Eleven v3"} \
               or provider not in {"mixkit", "pixabay"} or not .7 <= speed <= 1.2 or not all(0 <= value <= 1 for value in (stability, similarity, style)):
                raise ValueError("Invalid launch values.")
            if hero_presence_mode not in {"auto", "opener_only", "limited_in_world", "in_world"}:
                raise ValueError("Invalid hero_presence_mode")
            if world_style_policy not in {"auto", "reuse", "new"}:
                raise ValueError("Invalid world_style_policy")
            if gemini_image_model not in {"nano_banana_pro", "nano_banana_2"}:
                try:
                    gemini_image_model = normalize_gemini_model(gemini_image_model)
                except Exception:
                    raise ValueError("Invalid gemini_image_model")
            if flow_video_model not in {"gemini_omni_1_1_flash", "veo_3_1_quality", "veo_3_1_fast", "veo_3_1_lite"}:
                try:
                    flow_video_model = normalize_flow_model(flow_video_model)
                except Exception:
                    raise ValueError(f"Invalid flow_video_model: {flow_video_model}")
            if flow_resolution not in {"720p", "360p"}:
                raise ValueError("Invalid flow_resolution")
            if opening_a_seconds not in {4,5,6,8} or opening_b_seconds not in {3,4,6,8}:
                raise ValueError("Invalid opening durations")
            cp = load_content_project(content_project)
            # provider locks (§60)
            validate_provider_locks(cp)
            # also validate subtitle default: QH default off but user can enable
            # validate preset (will fail if QH preset missing character_sheet)
            validate_content_project(cp)
            creative_brief = {key: form_text(values, key) for key in CREATIVE_FIELDS}
            # also store QH advanced as part of creative brief for downstream pipeline
            creative_brief["_qh"] = {
                "hero_presence_mode": hero_presence_mode,
                "world_style_policy": world_style_policy,
                "world_style_hint": world_style_hint,
                "gemini_image_model": gemini_image_model,
                "flow_video_model": flow_video_model,
                "flow_resolution": flow_resolution,
                "opening_a_source_seconds": opening_a_seconds,
                "opening_b_source_seconds": opening_b_seconds,
                "show_subtitles": show_subtitles,
            }
        except (KeyError, ValueError) as exc:
            self.send_html(HTTPStatus.BAD_REQUEST, self.page(str(exc))); return
        except RuntimeError as exc:
            self.send_html(HTTPStatus.CONFLICT, self.page(str(exc))); return
        with LAUNCH_LOCK:
            active = active_job(self.jobs_dir)
            if active is not None:
                self.send_html(HTTPStatus.CONFLICT, self.page(f"Video {active.get('video_id')} is already running. Wait for it to finish before launching another.")); return
            video_id = next_video_id()
            project = ROOT / "videos" / f"{video_id}_{video_slug(topic)}"; profile = project / "voiceover" / "REQUESTED_VOICE_PROFILE.json"
            write_json(profile, {"voice": voice, "model": model, "speed": speed, "stability": stability, "similarity": similarity, "style": style, "speaker_boost": False, "output_format": "MP3 44.1 kHz (128kbps)"})
            creative_brief_path = project / "launch" / "CREATIVE_BRIEF.json"; write_json(creative_brief_path, creative_brief)
            # also store QH launch request with frozen settings §59
            job_id = str(uuid.uuid4())
            subtitles_enabled = show_subtitles  # QH default off; others default on but panel now explicit
            # legacy default for non-QH was true; QH default false
            if not show_subtitles and content_project != "question_harvest":
                # for legacy, subtitles on by default — but panel now controls it, so respect user choice
                pass
            record = {
                "schema_version": 5, "content_project": content_project, "job_id": job_id, "status": "RUNNING", "created_at": utcnow(),
                "topic": topic, "video_id": video_id, "duration_min_seconds": duration_min, "duration_max_seconds": duration_max,
                "aspect_ratio": aspect_ratio, "project": str(project.relative_to(ROOT)),
                "voice_profile": str(profile.relative_to(ROOT)), "creative_brief": str(creative_brief_path.relative_to(ROOT)),
                "qh": creative_brief["_qh"],
                "subtitles": subtitles_enabled,
            }
            request = project / "launch" / "LAUNCH_REQUEST.json"; write_json(request, record); write_json(self.jobs_dir / f"{job_id}.json", record)
            log = self.jobs_dir / f"{job_id}.log"; handle = log.open("w", encoding="utf-8")
            # Route to correct pipeline per content project profile
            if content_project == "question_harvest":
                # The wrapper owns the whole episode: visual stages, narration, measured
                # timing, opening trims, music, render, QC and publish.
                command = [sys.executable, "-u", "scripts/run_full_video_pipeline_qh_wrapper.py",
                           "--topic", topic, "--video-id", video_id,
                           "--content-project", content_project,
                           "--creative-brief", str(creative_brief_path),
                           "--voice-profile", str(profile),
                           "--aspect-ratio", aspect_ratio,
                           "--music-provider", provider,
                           "--publish"]
            else:
                command = [sys.executable, "-u", "scripts/run_full_video_pipeline.py", "--content-project", content_project, "--topic", topic, "--video-id", video_id, "--min-duration-seconds", str(duration_min), "--max-duration-seconds", str(duration_max), "--aspect-ratio", aspect_ratio, "--voice-profile", str(profile), "--creative-brief", str(creative_brief_path), "--music-provider", provider]
            try:
                process = subprocess.Popen(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
            except OSError as exc:
                handle.close()
                record.update({"status": "FAILED", "completed_at": utcnow(), "error": f"Could not start pipeline: {exc}"})
                write_json(request, record); write_json(self.jobs_dir / f"{job_id}.json", record)
                self.send_html(HTTPStatus.INTERNAL_SERVER_ERROR, self.page(record["error"])); return
            finally:
                if not handle.closed:
                    handle.close()
            record.update({"pid": process.pid, "command": command, "started_at": utcnow()}); write_json(request, record); write_json(self.jobs_dir / f"{job_id}.json", record)
        self.send_html(HTTPStatus.ACCEPTED, self.page(f"Launched {video_id} ({content_project}); live log is available in the table. QH: {gemini_image_model} + {flow_video_model} {flow_resolution} 9:16"))


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--host", default="127.0.0.1"); parser.add_argument("--port", type=int, default=4142); args = parser.parse_args()
    (ROOT / "control_panel" / "jobs").mkdir(parents=True, exist_ok=True)
    reconcile_scheduled_resumes()
    reconcile_stuck_jobs_once()
    start_stuck_job_reconciler(interval=30)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Video control panel: http://{args.host}:{args.port}", flush=True); server.serve_forever()


if __name__ == "__main__": main()

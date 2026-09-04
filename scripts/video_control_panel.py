#!/usr/bin/env python3
"""Single-page launch and monitoring panel for the video pipeline (§§62-64, T9.1/T9.2).

Official address: **http://<host>:4141/** behind nginx basic auth (4144 is kept as a
legacy alias). Everything happens on one page: launch, provider health, a live log tail,
and resume — no navigation, so a long run can be watched from where it was started.

Locked choices (text=ChatGPT, image=Gemini, video=Flow) are rendered as disabled controls
rather than editable ones, so the UI cannot suggest a combination the pipeline would reject.
"""
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
from urllib.parse import parse_qs, urlparse

from content_projects import (
    DEFAULT_CONTENT_PROJECT, list_content_projects, load_content_project,
    validate_content_project, validate_provider_locks, normalize_gemini_model, normalize_flow_model, video_slug
)

ROOT = Path(__file__).resolve().parents[1]
LAUNCH_LOCK = threading.Lock()
PREFERRED_CONTENT_PROJECT = "question_harvest"
CREATIVE_FIELDS = ("working_title", "audience", "narrative_angle", "must_include", "must_avoid", "source_notes")

#: Where Ordak answers, for the provider badges.
ORDAK_BASE_URL = os.getenv("YT_ORDAK_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PROVIDERS = ("chatgpt", "gemini", "flow")
JOB_ID_RE = re.compile(r"^[a-f0-9-]{36}$")


def catalogued_style_ids(content_project: str) -> list[str]:
    """The world styles this content project can reuse, newest catalog order kept."""
    catalog = ROOT / "projects" / content_project / "world_styles" / "CATALOG.json"
    try:
        entries = json.loads(catalog.read_text(encoding="utf-8")).get("styles") or []
    except (OSError, ValueError):
        return []
    return [str(entry.get("style_id")) for entry in entries if entry.get("style_id")]


def style_options_html(content_project: str) -> str:
    """<option> list for the style picker: Auto first, then every catalogued style."""
    options = ['<option value="" selected>Auto — let the director decide (reuse or new)</option>']
    for style_id in catalogued_style_ids(content_project):
        options.append(f'<option value="{html.escape(style_id, quote=True)}">'
                       f'{html.escape(style_id)}</option>')
    return "".join(options)


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

def pipeline_command(record: dict) -> list[str]:
    """The command that runs one episode. Launch and resume must not diverge (§78)."""
    content_project = str(record.get("content_project") or DEFAULT_CONTENT_PROJECT)
    project = ROOT / str(record["project"])
    creative_brief = ROOT / str(record["creative_brief"])
    voice_profile = ROOT / str(record["voice_profile"])
    if content_project == "question_harvest":
        return [
            sys.executable, "-u", "scripts/run_full_video_pipeline_qh_wrapper.py",
            "--topic", str(record["topic"]),
            "--video-id", str(record["video_id"]),
            "--content-project", content_project,
            "--creative-brief", str(creative_brief),
            "--voice-profile", str(voice_profile),
            "--aspect-ratio", str(record.get("aspect_ratio") or "9:16"),
            "--music-provider", str(record.get("music_provider") or "mixkit"),
            "--publish",
        ] + (["--commit"] if record.get("commit_artifacts") else [])
    return [
        sys.executable, "-u", "scripts/run_full_video_pipeline.py",
        "--content-project", content_project,
        "--topic", str(record["topic"]),
        "--video-id", str(record["video_id"]),
        "--min-duration-seconds", str(record.get("duration_min_seconds") or 40),
        "--max-duration-seconds", str(record.get("duration_max_seconds") or 60),
        "--aspect-ratio", str(record.get("aspect_ratio") or "9:16"),
        "--voice-profile", str(voice_profile),
        "--creative-brief", str(creative_brief),
        "--music-provider", str(record.get("music_provider") or "mixkit"),
    ]


def provider_status() -> dict:
    """Ordak's own view of each provider session, for the badges (§9.2).

    An unreachable Ordak is reported as unreachable rather than as "all fine": the panel
    must never imply a provider is ready when nothing confirmed it.
    """
    try:
        import httpx

        response = httpx.get(f"{ORDAK_BASE_URL}/api/diagnostics", timeout=6, trust_env=False)
        data = response.json() if response.status_code == 200 else {}
    except Exception as exc:
        return {
            "reachable": False,
            "error": f"{type(exc).__name__}: {exc}"[:160],
            "chrome_running": None,
            "providers": {name: {"state": "unknown", "logged_in": None} for name in PROVIDERS},
        }
    sessions = data.get("provider_sessions") or {}
    return {
        "reachable": True,
        "error": "",
        "chrome_running": bool(data.get("chrome_running")),
        "providers": {
            name: {
                "state": str((sessions.get(name) or {}).get("login_state") or "unknown"),
                "logged_in": (sessions.get(name) or {}).get("logged_in"),
                "tabs": len((sessions.get(name) or {}).get("open_tabs") or []),
            }
            for name in PROVIDERS
        },
    }


def pipeline_state_of(record: dict) -> dict:
    """The orchestrator's own state for a job, when it has written one (§81)."""
    try:
        path = ROOT / str(record.get("project") or "") / "pipeline" / "QH_RUNTIME_STATE.json"
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    stages = state.get("stages") or {}
    running = [name for name, entry in stages.items() if entry.get("status") == "RUNNING"]
    return {
        "pipeline_state": state.get("pipeline_state"),
        "stage_count": len(stages),
        "done": sum(1 for entry in stages.values() if entry.get("status") in ("DONE", "REUSED")),
        "running": running[0] if running else None,
    }


def job_records(jobs_dir: Path, limit: int = 12) -> list[dict]:
    records: list[dict] = []
    for path in sorted(jobs_dir.glob("*.json"), reverse=True)[:limit]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        record["_pipeline"] = pipeline_state_of(record)
        record["_resumable"] = record.get("status") not in ("RUNNING",) and bool(record.get("project"))
        records.append(record)
    return records


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

    def send_json(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers(); self.wfile.write(encoded)

    def log_tail(self, job_id: str, offset: int) -> dict:
        """Incremental log bytes, so the page can tail without refetching megabytes."""
        log = self.jobs_dir / f"{job_id}.log"
        if not log.exists():
            return {"offset": 0, "text": "", "waiting": True}
        size = log.stat().st_size
        start = min(max(offset, 0), size)
        if size - start > 200_000:  # a page that fell far behind gets the tail, not everything
            start = size - 200_000
        with log.open("rb") as handle:
            handle.seek(start)
            chunk = handle.read()
        return {"offset": size, "text": chunk.decode("utf-8", errors="replace"), "waiting": False}

    def page(self, message: str = "") -> str:
        # Status of defunct RUNNING jobs is settled by the background reconciler, so the
        # page only reads; it never has to decide whether a pid is still alive.
        reconcile_stuck_jobs_once()
        jobs = job_records(self.jobs_dir)
        project_options = "".join(f"<option value='{html.escape(p.project_id)}'{' selected' if p.project_id == PREFERRED_CONTENT_PROJECT else ''}>{html.escape(p.display_name)}</option>" for p in list_content_projects())
        style_options = style_options_html(PREFERRED_CONTENT_PROJECT)
        return f"""<!doctype html><meta charset=utf-8><title>Video Pipeline — Question Harvest</title>
<style>
body{{font:16px system-ui;max-width:920px;margin:32px auto;background:#10131a;color:#e8edf4;padding:0 18px}}
input,select,textarea{{width:100%;padding:8px;margin:4px 0 14px;box-sizing:border-box;background:#1a2030;color:#e8edf4;border:1px solid #2a344a;border-radius:4px}}textarea{{min-height:76px;resize:vertical}}
small{{color:#aeb8c8}}button{{padding:11px 22px;background:#58c;color:#fff;border:0;border-radius:6px;font-weight:600;cursor:pointer}}button:hover{{background:#4aa}}
table{{width:100%;border-collapse:collapse;margin-top:28px}}td,th{{padding:8px;border-bottom:1px solid #344;text-align:left}}.msg{{color:#8f8;background:#1a2a1a;padding:8px;border-radius:4px;min-height:18px}}
fieldset{{border:1px solid #334;margin:16px 0;padding:14px 14px 6px;border-radius:6px}}legend{{padding:0 8px;color:#8ab4ff;font-weight:600}}
.notice{{background:#1e293b;padding:10px;border-radius:6px;margin:12px 0;font-size:14px;border-left:4px solid #58c}}
.badge{{display:inline-block;background:#2a3a5a;color:#8ab4ff;padding:2px 7px;border-radius:10px;font-size:12px;margin-left:6px}}
.pill{{display:inline-block;padding:2px 9px;border-radius:11px;font-size:12px;font-weight:600;margin-right:6px}}
.pill.ok{{background:#12351f;color:#7fdb9a;border:1px solid #2a6b41}}
.pill.warn{{background:#3a2f12;color:#e8c37f;border:1px solid #6b552a}}
.pill.bad{{background:#3a1616;color:#ff9c9c;border:1px solid #6b2a2a}}
#status{{background:#161b28;border:1px solid #2a344a;border-radius:6px;padding:10px 12px;margin:14px 0}}
button.ghost{{background:transparent;color:#8ab4ff;border:1px solid #2a344a;padding:4px 10px;font-size:13px}}
button.ghost:hover{{background:#1a2030}}
#logtail{{background:#0b0e14;border:1px solid #2a344a;border-radius:6px;padding:10px;max-height:340px;
 overflow:auto;white-space:pre-wrap;word-break:break-word;font:13px ui-monospace,monospace}}
[disabled]{{opacity:.55;cursor:not-allowed}}
</style>
<h1>Video Pipeline Launch</h1><p class=msg>{html.escape(message)}</p>

<div id=status><strong>Provider status</strong> <small>(from Ordak /api/diagnostics, refreshed every 5s)</small><br>
 <span id=providers><span class="pill warn">checking…</span></span></div>

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
  <label><input type=checkbox name=commit_artifacts> Commit &amp; push artifacts after QC <small>(needs a remote with write access)</small></label>
 </fieldset>

 <fieldset id="qh_advanced"><legend>Question Harvest — Advanced (auto when project = question_harvest)</legend>
  <label>Hero presence <select name=hero_presence_mode><option value=auto selected>auto (recommended)</option><option value=opener_only>opener_only</option><option value=limited_in_world>limited_in_world</option><option value=in_world>in_world</option></select> <small>auto chooses based on topic (§44)</small></label>
  <label>World style <select name=world_style_id>{style_options}</select> <small>pick a catalogued style to reuse it, or leave on Auto</small></label>
  <label>World style policy <select name=world_style_policy><option value=auto selected>auto — reuse or create, whichever fits</option><option value=reuse>reuse an existing style</option><option value=new>create a new style</option></select> <small>ignored when a style is picked above</small></label>
  <label>World style hint <small>(optional free text; steers a new style)</small> <input name=world_style_hint maxlength=500 placeholder="e.g., charcoal, woodcut, ink wash …"></label>
  <label>Gemini Image Model <select name=gemini_image_model><option value=nano_banana_2 selected>Nano Banana 2 (the model Gemini offers today)</option><option value=nano_banana_pro>Nano Banana Pro (fails until Gemini exposes it)</option></select> <small>Provider LOCKED to Gemini (§4)</small></label>
  <label>Flow Video Model <select name=flow_video_model><option value=gemini_omni_1_1_flash selected>Gemini Omni 1.1 Flash (default)</option><option value=veo_3_1_quality>Veo 3.1 Quality</option><option value=veo_3_1_fast>Veo 3.1 Fast</option><option value=veo_3_1_lite>Veo 3.1 Lite</option></select> <small>Provider LOCKED to Google Flow (§4)</small></label>
  <label>Flow Resolution <select name=flow_resolution><option value="720p" selected>720p (default)</option><option value="360p">360p Draft (where supported)</option></select></label>
  <label>Opening Clip A source duration <small>(Flow, default 6s → trimmed to ~5s)</small> <select name=opening_a_seconds><option value=4>4s</option><option value=5>5s</option><option value=6 selected>6s</option><option value=8>8s</option></select></label>
  <label>Opening Clip B source duration <small>(Flow, default 4s → trimmed to ~3s)</small> <select name=opening_b_seconds><option value=3>3s</option><option value=4 selected>4s</option><option value=6>6s</option><option value=8>8s</option></select></label>
 </fieldset>

 <fieldset><legend>Generation Engines (§62-63) — locked</legend>
  <p style="font-size:14px;color:#aeb8c8">These are fixed by project design, so they are shown
   as they are and cannot be edited here.</p>
  <label>Text provider <input value="ChatGPT / Ordak" disabled></label>
  <label>Image provider <input value="Gemini / Ordak" disabled></label>
  <label>Video provider <input value="Google Flow / Ordak" disabled></label>
  <label>Flow canonical reference <input value="character_sheet.png (Clip A) · first_frame + last_frame (Clip B)" disabled></label>
  <label>Flow style sheet <input value="never uploaded — forbidden by §12-16, §61" disabled></label>
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
<h2>Runs</h2>
<table id=runs><thead><tr><th>ID</th><th>Project</th><th>Topic</th><th>Status</th><th>Progress</th><th></th></tr></thead>
<tbody><tr><td colspan=6>loading…</td></tr></tbody></table>

<section id=logpanel hidden>
 <h2>Live log <span class=badge id=logjob></span>
  <button type=button class=ghost id=logclose>close</button></h2>
 <pre id=logtail></pre>
</section>

<form method=post action=/resume id=resumeform hidden><input type=hidden name=job_id id=resumejob></form>

<p><small>Official panel address: <code>:4141</code> (behind basic auth). Defaults for Question
Harvest are 40–60s, 9:16, Nano Banana Pro + Gemini Omni 1.1 Flash + 720p (§64).</small></p>

<script>
var tailedJob = null, tailOffset = 0;

function badgeClass(entry) {{
  if (entry.state === 'login_required' || entry.state === 'manual_verification_required') return 'bad';
  if (entry.logged_in === true && entry.state === 'ready') return 'ok';
  return 'warn';
}}

function renderProviders(ordak) {{
  var host = document.getElementById('providers');
  if (!ordak.reachable) {{
    host.innerHTML = '<span class="pill bad">Ordak unreachable</span> <small>' +
      (ordak.error || '') + '</small>';
    return;
  }}
  var parts = ['<span class="pill ' + (ordak.chrome_running ? 'ok' : 'bad') +
               '">Chrome ' + (ordak.chrome_running ? 'running' : 'down') + '</span>'];
  Object.keys(ordak.providers).forEach(function (name) {{
    var entry = ordak.providers[name];
    // Ordak keeps exactly one work tab open, so the two providers that are not in
    // use have no tab and cannot be re-confirmed. That is idle, not broken.
    var label = entry.logged_in === true ? 'signed in'
      : (entry.state === 'ready' && entry.tabs === 0 ? 'idle (no tab)' : entry.state);
    parts.push('<span class="pill ' + badgeClass(entry) + '">' + name + ': ' + label + '</span>');
  }});
  host.innerHTML = parts.join(' ');
}}

function renderJobs(jobs) {{
  var body = document.querySelector('#runs tbody');
  if (!jobs.length) {{ body.innerHTML = '<tr><td colspan=6>No launches yet.</td></tr>'; return; }}
  body.innerHTML = jobs.map(function (job) {{
    var progress = job.pipeline && job.pipeline.stage_count
      ? job.pipeline.done + '/' + job.pipeline.stage_count +
        (job.pipeline.running ? ' · ' + job.pipeline.running : '')
      : '—';
    var actions = '<button type=button class=ghost onclick="watch(\'' + job.job_id + '\')">watch</button>';
    if (job.resumable) {{
      actions += ' <button type=button class=ghost onclick="resume(\'' + job.job_id + '\')">resume</button>';
    }}
    return '<tr><td>' + (job.video_id || '') + '</td><td>' + job.content_project +
      '</td><td>' + escapeHtml(job.topic || '') + '</td><td><span class="pill ' +
      (job.status === 'DONE' ? 'ok' : job.status === 'RUNNING' ? 'warn' : 'bad') + '">' +
      job.status + '</span></td><td>' + progress + '</td><td>' + actions + '</td></tr>';
  }}).join('');
}}

function escapeHtml(text) {{
  var div = document.createElement('div'); div.textContent = text; return div.innerHTML;
}}

function watch(jobId) {{
  tailedJob = jobId; tailOffset = 0;
  document.getElementById('logjob').textContent = jobId.slice(0, 8);
  document.getElementById('logtail').textContent = '';
  document.getElementById('logpanel').hidden = false;
  pollLog();
}}

function resume(jobId) {{
  document.getElementById('resumejob').value = jobId;
  document.getElementById('resumeform').submit();
}}

document.getElementById('logclose').addEventListener('click', function () {{
  tailedJob = null; document.getElementById('logpanel').hidden = true;
}});

function pollStatus() {{
  fetch('/api/status').then(function (r) {{ return r.json(); }}).then(function (data) {{
    renderProviders(data.ordak); renderJobs(data.jobs);
  }}).catch(function () {{}});
}}

function pollLog() {{
  if (!tailedJob) return;
  fetch('/api/log/' + tailedJob + '?offset=' + tailOffset)
    .then(function (r) {{ return r.json(); }})
    .then(function (data) {{
      if (data.text) {{
        var pre = document.getElementById('logtail');
        pre.textContent += data.text;
        pre.scrollTop = pre.scrollHeight;
      }}
      if (typeof data.offset === 'number') tailOffset = data.offset;
    }}).catch(function () {{}});
}}

onProjectChange();
pollStatus();
setInterval(pollStatus, 5000);
setInterval(pollLog, 2000);
</script>
"""

    def handle_resume(self) -> None:
        """Re-run an existing episode. Completed stages are reused, so nothing is paid twice."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_html(HTTPStatus.BAD_REQUEST, self.page("Invalid Content-Length")); return
        if length <= 0 or length > 4_000:
            self.send_html(HTTPStatus.BAD_REQUEST, self.page("Invalid resume request")); return
        values = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
        job_id = (values.get("job_id") or [""])[0].strip()
        if not JOB_ID_RE.fullmatch(job_id):
            self.send_html(HTTPStatus.BAD_REQUEST, self.page("Unknown job id")); return
        record_path = self.jobs_dir / f"{job_id}.json"
        if not record_path.is_file():
            self.send_html(HTTPStatus.NOT_FOUND, self.page("That job no longer exists")); return

        with LAUNCH_LOCK:
            active = active_job(self.jobs_dir)
            if active is not None:
                self.send_html(
                    HTTPStatus.CONFLICT,
                    self.page(f"Video {active.get('video_id')} is still running; resume after it finishes."),
                ); return
            record = json.loads(record_path.read_text(encoding="utf-8"))
            try:
                command = pipeline_command(record)
            except (KeyError, TypeError) as exc:
                self.send_html(HTTPStatus.CONFLICT, self.page(f"That job cannot be resumed: {exc}")); return
            log = self.jobs_dir / f"{job_id}.log"
            handle = log.open("a", encoding="utf-8")
            handle.write(f"\n=== resume requested at {utcnow()} ===\n")
            handle.flush()
            try:
                process = subprocess.Popen(
                    command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True
                )
            except OSError as exc:
                handle.close()
                self.send_html(HTTPStatus.INTERNAL_SERVER_ERROR, self.page(f"Could not resume: {exc}")); return
            finally:
                if not handle.closed:
                    handle.close()
            record.update({
                "status": "RUNNING",
                "pid": process.pid,
                "command": command,
                "resumed_at": utcnow(),
                "resume_count": int(record.get("resume_count") or 0) + 1,
            })
            record.pop("completed_at", None)
            write_json(record_path, record)
            request = ROOT / str(record.get("project") or "") / "launch" / "LAUNCH_REQUEST.json"
            if request.is_file():
                write_json(request, record)
        self.send_html(
            HTTPStatus.ACCEPTED,
            self.page(f"Resumed {record.get('video_id')} — completed stages are reused, not regenerated."),
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if route == "/":
            self.send_html(HTTPStatus.OK, self.page()); return

        if route == "/api/status":
            jobs = job_records(self.jobs_dir)
            active = active_job(self.jobs_dir)
            self.send_json(HTTPStatus.OK, {
                "at": utcnow(),
                "ordak": provider_status(),
                "active_job_id": (active or {}).get("job_id"),
                "jobs": [
                    {
                        "job_id": job.get("job_id"),
                        "video_id": job.get("video_id"),
                        "content_project": job.get("content_project", DEFAULT_CONTENT_PROJECT),
                        "topic": job.get("topic", ""),
                        "status": job.get("status", "QUEUED"),
                        "created_at": job.get("created_at"),
                        "pipeline": job.get("_pipeline") or {},
                        "resumable": bool(job.get("_resumable")),
                    }
                    for job in jobs
                ],
            }); return

        if route.startswith("/api/log/"):
            job_id = route.rsplit("/", 1)[-1]
            if not JOB_ID_RE.fullmatch(job_id):
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "unknown job"}); return
            try:
                offset = int((query.get("offset") or ["0"])[0])
            except ValueError:
                offset = 0
            self.send_json(HTTPStatus.OK, self.log_tail(job_id, offset)); return

        if route.startswith("/logs/"):
            # Kept for links already in circulation; the panel itself tails in place now.
            job_id = Path(route).name
            if not JOB_ID_RE.fullmatch(job_id): self.send_error(HTTPStatus.NOT_FOUND); return
            log = self.jobs_dir / f"{job_id}.log"
            text = log.read_text(encoding="utf-8", errors="replace")[-150_000:] if log.exists() else "Waiting for runner output..."
            self.send_html(HTTPStatus.OK, f"<meta http-equiv=refresh content=5><pre style='white-space:pre-wrap;word-break:break-word'>{html.escape(text)}</pre>"); return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/resume": self.handle_resume(); return
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
            commit_artifacts = "commit_artifacts" in values
            # QH advanced
            hero_presence_mode = values.get("hero_presence_mode", ["auto"])[0].strip() or "auto"
            world_style_policy = values.get("world_style_policy", ["auto"])[0].strip() or "auto"
            world_style_hint = form_text(values, "world_style_hint", 500) if values.get("world_style_hint") else ""
            world_style_id = values.get("world_style_id", [""])[0].strip()
            if world_style_id and world_style_id not in catalogued_style_ids(content_project):
                raise ValueError(f"Unknown world style: {world_style_id}")
            gemini_image_model = values.get("gemini_image_model", ["nano_banana_2"])[0].strip() or "nano_banana_2"
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
                "world_style_id": world_style_id,
                "world_style_hint": world_style_hint,
                "min_duration_seconds": duration_min,
                "max_duration_seconds": duration_max,
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
                # Recorded so a resume rebuilds exactly this command (§78).
                "music_provider": provider,
                "commit_artifacts": commit_artifacts,
            }
            request = project / "launch" / "LAUNCH_REQUEST.json"; write_json(request, record); write_json(self.jobs_dir / f"{job_id}.json", record)
            log = self.jobs_dir / f"{job_id}.log"; handle = log.open("w", encoding="utf-8")
            # One builder for launch and resume: the QH wrapper owns the whole episode
            # (visual stages, narration, measured timing, trims, music, render, QC, publish).
            command = pipeline_command(record)
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

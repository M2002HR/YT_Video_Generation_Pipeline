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
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import panel_page
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


def terminate_job(job: dict) -> bool:
    """Signal a job's whole process group; True when something was actually signalled.

    Each stage runs as a child of the wrapper, and the wrapper is started with
    ``start_new_session=True``, so the group is the right unit: signalling only the parent
    leaves a provider stage running in the browser with nothing watching it. TERM first, so
    a stage can close its browser tab, then KILL what ignores it.
    """
    pid = job.get("pid")
    if not pid_is_live(pid):
        return False
    import signal

    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(int(pid)), sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(int(pid), sig)
            except (ProcessLookupError, PermissionError, OSError):
                return True
        for _ in range(20):
            if not pid_is_live(pid):
                return True
            time.sleep(0.1)
    return True


def watchers_for(jobs_dir: Path, video_id: object) -> list[dict]:
    """Every live Flow watcher attached to this episode."""
    found: list[dict] = []
    if video_id is None:
        return found
    for path in jobs_dir.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            job.get("kind") == "flow_watcher"
            and str(job.get("video_id")) == str(video_id)
            and job.get("status") == "RUNNING"
        ):
            found.append(job)
    return found


def active_job(jobs_dir: Path) -> dict | None:
    """The episode currently being produced, if any.

    A Flow watcher does not count: it spends most of its life asleep and must not stand in
    the way of launching the next episode. It only runs the pipeline when Flow returns, and
    the launch lock covers that moment.
    """
    for path in jobs_dir.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if job.get("kind") == "flow_watcher":
            continue
        if job.get("status") == "RUNNING" and pid_is_live(job.get("pid")):
            return job
    return None


#: How often the Flow watcher re-probes, in seconds. Twenty minutes by default.
FLOW_WATCH_INTERVAL_SECONDS = int(os.getenv("YT_FLOW_WATCH_INTERVAL_SECONDS", "1200"))


def flow_watcher_alive(jobs_dir: Path, video_id: str) -> bool:
    """True when a watcher for this episode is already running."""
    for path in jobs_dir.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            job.get("kind") == "flow_watcher"
            and str(job.get("video_id")) == str(video_id)
            and job.get("status") == "RUNNING"
            and pid_is_live(job.get("pid"))
        ):
            return True
    return False


def ensure_flow_watcher(jobs_dir: Path, episode: dict) -> dict | None:
    """Start one watcher job for a parked episode, unless one is already watching.

    The watcher is a control-panel job like any other, so the wait shows up in the runs
    table and can be stopped or deleted from the same page.
    """
    video_id = str(episode.get("video_id") or "")
    if not video_id or flow_watcher_alive(jobs_dir, video_id):
        return None
    project = ROOT / str(episode.get("project") or "")
    command_file = project / "pipeline" / "RESUME_COMMAND.json"
    command_file.parent.mkdir(parents=True, exist_ok=True)
    command_file.write_text(
        json.dumps(pipeline_command(episode), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    job_id = str(uuid.uuid4())
    record = {
        "schema_version": 5,
        "kind": "flow_watcher",
        "job_id": job_id,
        "status": "RUNNING",
        "created_at": utcnow(),
        "video_id": video_id,
        "topic": episode.get("topic"),
        "project": episode.get("project"),
        "watching_job_id": episode.get("job_id"),
        "interval_seconds": FLOW_WATCH_INTERVAL_SECONDS,
    }
    command = [
        sys.executable, "-u", "scripts/flow_availability_watcher.py", str(project),
        "--command-file", str(command_file),
        "--interval-seconds", str(FLOW_WATCH_INTERVAL_SECONDS),
    ]
    log = jobs_dir / f"{job_id}.log"
    handle = log.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True
        )
    except OSError as exc:
        record.update({"status": "FAILED", "completed_at": utcnow(), "error": str(exc)})
        write_json(jobs_dir / f"{job_id}.json", record)
        return record
    finally:
        if not handle.closed:
            handle.close()
    record.update({"pid": process.pid, "command": command, "started_at": utcnow()})
    write_json(jobs_dir / f"{job_id}.json", record)
    return record


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
            # A Flow outage is Google's, not this episode's. The run parks with everything
            # else finished, so it becomes WAITING_FOR_FLOW and a watcher job is started to
            # continue it when Flow answers again — not FAILED.
            if "FLOW_CLIPS_PENDING" in text:
                job["status"] = "WAITING_FOR_FLOW"
                job["completed_at"] = utcnow()
                write_json(path, job)
                try:
                    ensure_flow_watcher(jobs_dir, job)
                except Exception as exc:  # a watcher failure must not wedge the reconciler
                    job["watcher_error"] = f"{type(exc).__name__}: {exc}"
                    write_json(path, job)
                continue
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


def job_records(jobs_dir: Path, limit: int = 20) -> list[dict]:
    """Newest jobs first, with the derived fields the page and the API both need."""
    records: list[dict] = []
    paths = sorted(jobs_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in paths[:limit]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        kind = str(record.get("kind") or "episode")
        live = pid_is_live(record.get("pid"))
        record["kind"] = kind
        record["_live"] = live
        record["_pipeline"] = pipeline_state_of(record) if kind == "episode" else {}
        # A watcher is never resumed: it is stopped or deleted, and the episode it watches
        # is what gets resumed.
        record["_resumable"] = (
            kind == "episode" and not live and bool(record.get("project"))
        )
        record["_stoppable"] = live
        record["_flow_pending"] = flow_pending_of(record) if kind == "episode" else {}
        records.append(record)
    return records


def flow_pending_of(record: dict) -> dict:
    """What the episode is still waiting on Flow for, if anything."""
    project = record.get("project")
    if not project:
        return {}
    path = ROOT / str(project) / "pipeline" / "FLOW_PENDING_STATE.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


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
        """The studio page. Live parts (badges, runs, log) are filled by /api/status."""
        # Status of defunct RUNNING jobs is settled by the background reconciler, so the
        # page only reads; it never has to decide whether a pid is still alive.
        reconcile_stuck_jobs_once()
        project_options = "".join(
            f"<option value='{html.escape(project.project_id)}'"
            f"{' selected' if project.project_id == PREFERRED_CONTENT_PROJECT else ''}>"
            f"{html.escape(project.display_name)}</option>"
            for project in list_content_projects()
        )
        # The handler is constructed without a socket in tests, so Host is read defensively.
        headers = getattr(self, "headers", None)
        host = (headers.get("Host") if headers else None) or "localhost"
        return panel_page.render(
            message=message,
            project_options=project_options,
            style_options=style_options_html(PREFERRED_CONTENT_PROJECT),
            address=f"http://{host}/",
        )

    def read_job_id(self, limit: int = 4_000) -> str | None:
        """The job_id from a form post, or None after already answering with the error."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_html(HTTPStatus.BAD_REQUEST, self.page("Invalid Content-Length")); return None
        if length <= 0 or length > limit:
            self.send_html(HTTPStatus.BAD_REQUEST, self.page("Invalid request")); return None
        values = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
        job_id = (values.get("job_id") or [""])[0].strip()
        if not JOB_ID_RE.fullmatch(job_id):
            self.send_html(HTTPStatus.BAD_REQUEST, self.page("Unknown job id")); return None
        return job_id

    def handle_stop(self) -> None:
        """Stop a running job, and its watcher, without deleting anything it produced.

        The process group is signalled rather than the pid alone: the wrapper runs each
        stage as a child, and killing only the parent would leave a provider job running in
        the browser with nothing watching it.
        """
        job_id = self.read_job_id()
        if job_id is None:
            return
        record_path = self.jobs_dir / f"{job_id}.json"
        if not record_path.is_file():
            self.send_html(HTTPStatus.NOT_FOUND, self.page("That job no longer exists")); return
        try:
            job = json.loads(record_path.read_text(encoding="utf-8"))
        except ValueError:
            self.send_html(HTTPStatus.CONFLICT, self.page("That job record is unreadable")); return

        stopped = terminate_job(job)
        job["status"] = "STOPPED"
        job["completed_at"] = utcnow()
        job["stopped_by"] = "panel"
        write_json(record_path, job)
        for watcher in watchers_for(self.jobs_dir, job.get("video_id")):
            terminate_job(watcher)
            watcher["status"] = "STOPPED"
            watcher["completed_at"] = utcnow()
            write_json(self.jobs_dir / f"{watcher['job_id']}.json", watcher)
        note = "stopped" if stopped else "was not running; marked stopped"
        self.send_html(
            HTTPStatus.ACCEPTED,
            self.page(f"Job {job_id[:8]} ({job.get('video_id') or '—'}) {note}."),
        )

    def handle_delete(self) -> None:
        """Remove a job's record and log. A running job is stopped first.

        Only the panel's own bookkeeping is removed. The episode directory under videos/ is
        left alone: deleting a row must never throw away generated media.
        """
        job_id = self.read_job_id()
        if job_id is None:
            return
        record_path = self.jobs_dir / f"{job_id}.json"
        if not record_path.is_file():
            self.send_html(HTTPStatus.NOT_FOUND, self.page("That job no longer exists")); return
        try:
            job = json.loads(record_path.read_text(encoding="utf-8"))
        except ValueError:
            job = {"job_id": job_id}
        if job.get("status") == "RUNNING" and pid_is_live(job.get("pid")):
            terminate_job(job)
        video_id = job.get("video_id")
        record_path.unlink(missing_ok=True)
        (self.jobs_dir / f"{job_id}.log").unlink(missing_ok=True)
        self.send_html(
            HTTPStatus.ACCEPTED,
            self.page(
                f"Removed job {job_id[:8]} ({video_id or '—'}) from the panel. "
                "Its files under videos/ were kept."
            ),
        )

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
                        "kind": job.get("kind", "episode"),
                        "video_id": job.get("video_id"),
                        "content_project": job.get("content_project", DEFAULT_CONTENT_PROJECT),
                        "topic": job.get("topic", ""),
                        "status": job.get("status", "QUEUED"),
                        "created_at": job.get("created_at"),
                        "pipeline": job.get("_pipeline") or {},
                        "resumable": bool(job.get("_resumable")),
                        "stoppable": bool(job.get("_stoppable")),
                        "live": bool(job.get("_live")),
                        "flow_pending": job.get("_flow_pending") or {},
                        "interval_seconds": job.get("interval_seconds"),
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
        if self.path == "/stop": self.handle_stop(); return
        if self.path == "/delete": self.handle_delete(); return
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

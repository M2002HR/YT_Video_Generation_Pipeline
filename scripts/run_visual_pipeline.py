#!/usr/bin/env python3
"""Run the ChatGPT-via-Ordak topic-to-validated-beat-images workflow.

The parent project owns state, output naming and quality gates.  Ordak remains
the only browser executor: this program never calls a model or image API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from PIL import Image

from pipeline_notifier import PipelineNotifier, StageTimer, format_duration


ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "prompts"
DEFAULT_TOPIC = "Why You Forget Why You Walked Into a Room"
RECOVERABLE_ORDAK_ERRORS = (
    "did not open the configured project url",
    "composer did not become ready",
    "partially loaded page",
    "connection refused",
    "chrome remote debugging is not reachable",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return result or "video"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_template(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def replace_tokens(template: str, **values: str) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def ordak_timing_events(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract machine-readable component timings emitted by the Ordak worker."""
    events: list[dict[str, Any]] = []
    for entry in logs:
        message = str(entry.get("message") or "")
        if not message.startswith("TIMING "):
            continue
        fields: dict[str, Any] = {"timestamp": entry.get("timestamp")}
        for token in message.removeprefix("TIMING ").split():
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            fields[key] = value
        if "elapsed_seconds" in fields:
            try:
                fields["elapsed_seconds"] = float(fields["elapsed_seconds"])
            except (TypeError, ValueError):
                pass
        events.append(fields)
    return events


@dataclass
class Settings:
    base_url: str
    wait_seconds: int
    poll_seconds: float


class OrdakClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = httpx.Client(timeout=max(30.0, settings.wait_seconds + 30), trust_env=False)

    def close(self) -> None:
        self.http.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Keep an in-flight pipeline attached across a brief Ordak API restart.

        Polling an already-created job is idempotent.  A local connection
        refusal must therefore never discard its job ID or cause the visual
        pipeline to create duplicate ChatGPT images.
        """
        deadline = time.monotonic() + min(90.0, max(30.0, float(self.settings.wait_seconds)))
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.http.request(method, url, **kwargs)
                if response.status_code not in {502, 503, 504}:
                    return response
                error: Exception = RuntimeError(f"Ordak API temporarily returned HTTP {response.status_code}")
            except httpx.TransportError as exc:
                error = exc
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Ordak API remained unavailable for {int(min(90.0, max(30.0, float(self.settings.wait_seconds))))}s while {method} {url}: {error}"
                ) from error
            delay = min(8.0, 1.0 * (2 ** min(attempt - 1, 3)))
            print(f"Ordak API transient error; preserving current job and retrying {method} in {delay:.0f}s: {error}", flush=True)
            time.sleep(delay)

    def readiness(self) -> dict[str, Any]:
        health = self._request("GET", f"{self.settings.base_url}/api/health")
        health.raise_for_status()
        diagnostics = self._request("GET", f"{self.settings.base_url}/api/diagnostics")
        diagnostics.raise_for_status()
        data = diagnostics.json()
        if not data.get("chrome_running"):
            raise RuntimeError("Ordak/Chrome readiness check failed; the configured Chrome session is not running.")
        # The diagnostics endpoint only reports a ChatGPT session after a
        # ChatGPT tab exists.  A completed music/ElevenLabs stage can quite
        # legitimately leave a different site as Chrome's sole tab, so do not
        # misclassify that as a logout before Ordak gets a chance to open the
        # configured Project URL.  The Ordak worker performs the authoritative
        # login and project-URL checks immediately after opening that tab.
        return data

    @staticmethod
    def _recoverable(error: Exception) -> bool:
        return isinstance(error, httpx.TransportError) or any(marker in str(error).lower() for marker in RECOVERABLE_ORDAK_ERRORS)

    def _recover_before_retry(self, *, stage: str, attempt: int, error: Exception) -> None:
        """Bounded recovery for a browser page that has not settled yet.

        Ordak itself safely refuses to type into a generic ChatGPT chat.  That
        condition is transient while Chrome restores a project tab, so this
        parent retry rechecks the complete browser session before submitting a
        fresh, project-scoped job.  It never retries unknown failures.
        """
        delay = min(20.0, 2.0 ** attempt)
        print(
            f"ORDAK recoverable error at {stage}; retry {attempt}/4 in {delay:.0f}s: {error}",
            flush=True,
        )
        time.sleep(delay)
        self.readiness()

    def text(self, prompt: str, *, stage: str) -> dict[str, Any]:
        total_started = time.perf_counter()
        failures: list[dict[str, Any]] = []
        for attempt in range(1, 5):
            try:
                response = self._request("POST",
                    f"{self.settings.base_url}/api/chatgpt/respond",
                    json={"question": prompt, "mode": "chat", "start_new_chat": True,
                          "wait_for_completion": True, "wait_timeout_seconds": self.settings.wait_seconds},
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("status") != "completed" or not str(payload.get("answer") or "").strip():
                    raise RuntimeError(f"Ordak text stage {stage} failed: {payload.get('error_message') or payload.get('status')}")
                payload["_client_timing"] = {
                    "operation": "chatgpt_text_request",
                    "stage": stage,
                    "elapsed_seconds": round(time.perf_counter() - total_started, 3),
                    "attempt": attempt,
                    "recovery_failures": failures,
                }
                return payload
            except (httpx.HTTPError, RuntimeError) as exc:
                failures.append({"attempt": attempt, "error": str(exc), "at": utcnow()})
                if attempt == 4 or not self._recoverable(exc):
                    raise
                self._recover_before_retry(stage=stage, attempt=attempt, error=exc)
        raise RuntimeError(f"Ordak text stage {stage} exhausted its recovery attempts.")

    def image(self, prompt: str, references: list[Path], *, beat_id: int) -> dict[str, Any]:
        reference_readings: list[dict[str, Any]] = []
        files = []
        for reference in references:
            read_started = time.perf_counter()
            content = reference.read_bytes()
            reference_readings.append({
                "path": str(reference), "bytes": len(content),
                "read_elapsed_seconds": round(time.perf_counter() - read_started, 3),
            })
            files.append(("image", (reference.name, content, "image/png")))
        data = {
            "question": prompt,
            "provider": "chatgpt",
            "mode": "image_generate",
            "start_new_chat": "true",
            "wait_for_completion": "true",
            "wait_timeout_seconds": str(self.settings.wait_seconds),
        }
        upload_started = time.perf_counter()
        response = self._request("POST", f"{self.settings.base_url}/api/jobs", data=data, files=files)
        response.raise_for_status()
        created = response.json()
        job_id = created["job_id"]
        deadline = time.monotonic() + self.settings.wait_seconds
        poll_started = time.perf_counter()
        poll_count = 0
        while time.monotonic() < deadline:
            poll_count += 1
            job_response = self._request("GET", f"{self.settings.base_url}/api/jobs/{job_id}")
            job_response.raise_for_status()
            job = job_response.json()
            if job.get("status") in {"completed", "failed", "manual_verification_required", "cancelled"}:
                if job.get("status") != "completed":
                    raise RuntimeError(f"Beat {beat_id:03d} Ordak job {job_id} failed: {job.get('error_message') or job.get('status')}")
                job["_client_timing"] = {
                    "operation": "chatgpt_image_request",
                    "beat_id": beat_id,
                    "reference_payload_readings": reference_readings,
                    "upload_and_enqueue_elapsed_seconds": round(poll_started - upload_started, 3),
                    "polling_elapsed_seconds": round(time.perf_counter() - poll_started, 3),
                    "poll_count": poll_count,
                    "ordak_component_timings": ordak_timing_events(list(job.get("logs") or [])),
                    "ordak_job_started_at": job.get("started_at"),
                    "ordak_job_finished_at": job.get("finished_at"),
                }
                return job
            time.sleep(self.settings.poll_seconds)
        raise RuntimeError(f"Beat {beat_id:03d} Ordak job {job_id} exceeded parent wait timeout.")

    def download(self, artifact: str, destination: Path) -> dict[str, Any]:
        started = time.perf_counter()
        url = artifact if artifact.startswith("http") else f"{self.settings.base_url}/{artifact.lstrip('/')}"
        response = self._request("GET", url)
        response.raise_for_status()
        destination.write_bytes(response.content)
        return {"operation": "artifact_download", "elapsed_seconds": round(time.perf_counter() - started, 3), "bytes": len(response.content)}


class Pipeline:
    def __init__(self, root: Path, topic: str, video_id: str, preset: str, duration_min_seconds: float, duration_max_seconds: float, aspect_ratio: str, client: OrdakClient, force: bool) -> None:
        self.root, self.topic, self.video_id, self.preset, self.duration_min_seconds, self.duration_max_seconds, self.aspect_ratio, self.client, self.force = root, topic, video_id, preset, duration_min_seconds, duration_max_seconds, aspect_ratio, client, force
        self.project = root / "videos" / f"{video_id}_{slugify(topic)}"
        self.state_dir = self.project / "visual_pipeline"
        self.state_path = self.state_dir / "RUNTIME_STATE.json"
        self.timing_path = self.state_dir / "EXECUTION_TIMINGS.json"
        self.state: dict[str, Any] = {}
        self.notifier = PipelineNotifier(video_id, topic)

    def save(self) -> None:
        self.state["updated_at"] = utcnow()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        events = self.state.get("timing_events", [])
        totals: dict[str, float] = {}
        for event in events:
            name = str(event.get("operation") or "unknown")
            totals[name] = totals.get(name, 0.0) + float(event.get("elapsed_seconds") or 0.0)
        self.timing_path.write_text(json.dumps({
            "schema_version": 1,
            "video_id": self.video_id,
            "topic": self.topic,
            "events": events,
            "totals_seconds_by_operation": {key: round(value, 3) for key, value in sorted(totals.items())},
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def record_timing(self, operation: str, started_at: str, started: float, **metadata: Any) -> None:
        self.state.setdefault("timing_events", []).append({
            "operation": operation,
            "started_at": started_at,
            "finished_at": utcnow(),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            **metadata,
        })

    def load_or_init(self) -> None:
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            state_min = float(self.state.get("duration_min_seconds", self.state.get("duration_seconds", 60)))
            state_max = float(self.state.get("duration_max_seconds", self.state.get("duration_seconds", 60)))
            state_ratio = self.state.get("aspect_ratio", "16:9")
            if self.state.get("topic") != self.topic or self.state.get("preset") != self.preset or state_min != self.duration_min_seconds or state_max != self.duration_max_seconds or state_ratio != self.aspect_ratio:
                raise RuntimeError("Existing project state has different topic, preset, duration, or frame format; choose another video ID.")
            return
        self.state = {"version": 5, "topic": self.topic, "preset": self.preset, "duration_min_seconds": self.duration_min_seconds, "duration_max_seconds": self.duration_max_seconds, "aspect_ratio": self.aspect_ratio, "created_at": utcnow(), "stages": {}, "beats": {}, "timing_events": []}
        self.save()

    def restore_notifier_image_progress(self) -> None:
        """Continue Telegram progress counters from durable accepted beats."""
        durations: dict[int, float] = {}
        for event in self.state.get("timing_events", []):
            if event.get("operation") != "beat_image":
                continue
            try:
                durations[int(event["beat_id"])] = float(event.get("elapsed_seconds") or 0)
            except (KeyError, TypeError, ValueError):
                continue
        accepted = []
        for key, record in sorted(self.state.get("beats", {}).items()):
            if record.get("status") != "DONE":
                continue
            try:
                accepted.append(durations.get(int(key), 0.0))
            except ValueError:
                continue
        self.notifier.restore_image_progress(accepted)

    def write_once(self, relative: str, content: str) -> Path:
        target = self.project / relative
        if self.force or not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content.strip() + "\n", encoding="utf-8")
        return target

    def brief(self) -> Path:
        target_words = round(((self.duration_min_seconds + self.duration_max_seconds) / 2) * 2.3)
        minimum_words = round(self.duration_min_seconds * 2.05)
        maximum_words = round(self.duration_max_seconds * 2.5)
        return self.write_once("BRIEF.md", f"""# Video Brief

Topic: {self.topic}
Language: English
Target range: {self.duration_min_seconds:g}–{self.duration_max_seconds:g} seconds; roughly {minimum_words}–{maximum_words} spoken words (aim near {target_words}). Choose the most natural duration within this range; do not pad merely to reach the maximum.
Frame format: {self.aspect_ratio}. Compose visual ideas for {'a vertical mobile frame with a clear central subject and generous top/bottom safe space' if self.aspect_ratio == '9:16' else 'a horizontal widescreen frame with balanced left/right composition'}.
Audience: general viewers interested in an engaging psychology/neuroscience short.
Constraints: no medical diagnosis or medical advice; avoid unsupported claims and invented statistics.
""")

    def _stage_text(self, name: str, prompt: str, output: str, validator) -> str:
        started_at, started = utcnow(), time.perf_counter()
        target = self.project / output
        if target.exists() and not self.force:
            content = target.read_text(encoding="utf-8").strip()
            validator(content)
            self.record_timing("reuse_text_artifact", started_at, started, stage=name, artifact=output)
            self.save()
            return content
        result = self.client.text(prompt, stage=name)
        content = str(result["answer"]).strip()
        validator(content)
        self.write_once(output, content)
        self.record_timing("text_stage", started_at, started, stage=name, artifact=output, ordak_job_id=result["job_id"], request_timing=result.get("_client_timing"))
        self.state["stages"][name] = {"status": "DONE", "ordak_job_id": result["job_id"], "completed_at": utcnow()}
        self.save()
        self.notifier.stage_complete(name, time.perf_counter() - started, artifact=output)
        return content

    def validate_script(self, text: str) -> None:
        words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)
        minimum_words = round(self.duration_min_seconds * 2.05)
        maximum_words = round(self.duration_max_seconds * 2.5)
        if not minimum_words <= len(words) <= maximum_words or "###" in text:
            raise RuntimeError(f"Script validation failed: expected {minimum_words}–{maximum_words} spoken words for {self.duration_min_seconds:g}–{self.duration_max_seconds:g}s, got {len(words)} words.")

    def parse_beats(self, text: str) -> list[dict[str, str]]:
        # ChatGPT commonly omits Markdown's optional ``###`` while retaining
        # the requested labelled Beat structure. Both forms are semantically
        # identical and must be accepted before image generation can begin.
        pattern = re.compile(
            r"(?:^|\n)(?:###\s*)?Beat\s+0*(\d+)\s*\n+\s*"
            r"Narration:\s*\n+(.*?)\n+\s*"
            r"Visual:\s*\n+(.*?)\n+\s*"
            r"Purpose:\s*\n+(.*?)\n+\s*"
            r"Type:\s*\n+(.*?)\n+\s*"
            r"Continuity:\s*\n+(.*?)(?=\n+(?:###\s*)?Beat\s+\d+\s*\n|\Z)",
            re.S | re.I | re.M,
        )
        beats = [{"id": int(match.group(1)), "narration": match.group(2).strip(), "visual": match.group(3).strip(), "purpose": match.group(4).strip(), "type": match.group(5).strip(), "continuity": match.group(6).strip()} for match in pattern.finditer(text)]
        minimum = max(4, round(self.duration_min_seconds / 3.5) - 4)
        maximum = round(self.duration_max_seconds / 3.5) + 5
        if not minimum <= len(beats) <= maximum or [beat["id"] for beat in beats] != list(range(1, len(beats) + 1)):
            raise RuntimeError(f"Visual beat validation failed: expected {minimum}–{maximum} sequential complete beats for {self.duration_min_seconds:g}–{self.duration_max_seconds:g}s.")
        if any(not all(str(value).strip() for key, value in beat.items() if key != "id") for beat in beats):
            raise RuntimeError("Visual beat validation failed: one or more required fields are empty.")
        return beats

    def run(self) -> Path:
        total_timer = StageTimer()
        try:
            self.client.readiness()
            self.load_or_init()
            self.restore_notifier_image_progress()
            brief = self.brief().read_text(encoding="utf-8")
            script_draft = self._stage_text("script_draft", replace_tokens(load_template("01_script_writer.md"), VIDEO_BRIEF=brief), "SCRIPT_DRAFT.md", self.validate_script)
            script = self._stage_text("retention_edit", replace_tokens(load_template("02_retention_editor.md"), VIDEO_BRIEF=brief, CURRENT_SCRIPT=script_draft), "SCRIPT_FINAL.md", self.validate_script)
            beats_text = self._stage_text("visual_beats", replace_tokens(load_template("03_visual_beats.md"), VIDEO_BRIEF=brief, FINAL_SCRIPT=script), "VISUAL_BEATS.md", self.parse_beats)
            beats = self.parse_beats(beats_text)
            self.write_once("VISUAL_PRESET.md", f"# Visual Preset\n\nSelected preset: `{self.preset}`\n")
            preset_root = self.root / "visual_presets" / self.preset
            style, character = preset_root / "style_anchor.png", preset_root / "character_anchor.png"
            if not style.is_file() or not character.is_file():
                raise RuntimeError("Selected visual preset is missing canonical style or character anchors.")
            style_rules = (preset_root / "README.md").read_text(encoding="utf-8")
            for beat in beats:
                beat_id = beat["id"]
                prompt_path = self.project / "beats" / f"BEAT_{beat_id:03d}_PROMPT.md"
                if not prompt_path.exists() or self.force:
                    started_at, started = utcnow(), time.perf_counter()
                    prompt_request = replace_tokens(load_template("04_single_beat_image_prompt_writer.md"), STYLE_RULES=style_rules, VISUAL_BEAT=json.dumps(beat, ensure_ascii=False), REFERENCE_IMAGES="style anchor, character anchor, and previous accepted beat where applicable", PREVIOUS_BEAT="No previous beat for Beat 001." if beat_id == 1 else "Use the supplied previous accepted beat only for short-range continuity.", ASPECT_RATIO=self.aspect_ratio, FRAME_GUIDANCE="Use a tall mobile-first composition: keep the protagonist and key action in the center column, preserve comfortable headroom and lower-screen safe space, and use vertical depth rather than wide lateral detail." if self.aspect_ratio == "9:16" else "Use a cinematic widescreen composition: use left/right depth and balanced horizontal staging while keeping the main action readable.")
                    prompt_result = self.client.text(prompt_request, stage=f"beat_{beat_id:03d}_prompt")
                    prompt = str(prompt_result["answer"]).strip()
                    if "exactly one" not in prompt.lower() or self.aspect_ratio not in prompt:
                        raise RuntimeError(f"Beat {beat_id:03d} prompt validation failed.")
                    self.write_once(str(prompt_path.relative_to(self.project)), prompt)
                    self.record_timing("beat_prompt", started_at, started, beat_id=beat_id, artifact=str(prompt_path.relative_to(self.project)), ordak_job_id=prompt_result["job_id"], request_timing=prompt_result.get("_client_timing"))
                    self.notifier.prompt_complete(beat_id, len(beats), time.perf_counter() - started)
                self.state["beats"].setdefault(f"{beat_id:03d}", {"status": "PROMPT_READY", "attempts": 0})["prompt_path"] = str(prompt_path.relative_to(self.project))
                self.save()
            images_timer = StageTimer()
            self.generate_images(beats, style, character)
            completed = sum(1 for value in self.state["beats"].values() if value.get("status") == "DONE")
            self.notifier.images_complete(len(beats), images_timer.elapsed, completed=completed)
            report = self.write_report(beats)
            self.notifier.send("Visual pipeline complete", ["🏁 Quality checks passed", f"📍 Images: {completed}/{len(beats)}", f"⏱ Total runtime: {format_duration(total_timer.elapsed)}"])
            return report
        except Exception as exc:
            self.notifier.failure("Visual pipeline", total_timer.elapsed, str(exc))
            raise

    def valid_image(self, path: Path, previous_sha: str | None = None) -> dict[str, Any]:
        if not path.is_file() or path.stat().st_size < 10_000:
            raise RuntimeError(f"Image missing or too small: {path}")
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
        aspect = width / height
        digest = sha256(path)
        expected_aspect = 16 / 9 if self.aspect_ratio == "16:9" else 9 / 16
        if abs(aspect - expected_aspect) > expected_aspect * 0.12:
            raise RuntimeError(f"Image must be approximately {self.aspect_ratio}: {path} ({width}x{height})")
        if previous_sha and digest == previous_sha:
            raise RuntimeError(f"Image duplicates previous accepted beat: {path}")
        return {"path": str(path.relative_to(self.project)), "bytes": path.stat().st_size, "width": width, "height": height, "aspect_ratio": aspect, "sha256": digest}

    def generate_images(self, beats: list[dict[str, str]], style: Path, character: Path) -> None:
        output_dir = self.project / "assets" / "raw_beats"
        output_dir.mkdir(parents=True, exist_ok=True)
        previous: Path | None = None
        previous_sha: str | None = None
        for beat in beats:
            beat_id = int(beat["id"])
            key = f"{beat_id:03d}"
            record = self.state["beats"].setdefault(key, {})
            target = output_dir / f"beat_{beat_id:03d}.png"
            if target.exists() and not self.force:
                try:
                    metadata = self.valid_image(target, previous_sha)
                    record.update({"status": "DONE", "output": metadata})
                    previous, previous_sha = target, metadata["sha256"]
                    self.save()
                    continue
                except RuntimeError:
                    record["status"] = "INVALID"
                    self.save()
            if previous is None and beat_id > 1:
                raise RuntimeError(f"Beat {beat_id:03d} is blocked until Beat {beat_id - 1:03d} is accepted.")
            references = [style, character] + ([previous] if previous else [])
            record.update({"status": "GENERATING", "references": [str(path.relative_to(self.root)) for path in references], "attempts": int(record.get("attempts", 0)) + 1, "last_error": None})
            self.save()
            try:
                started_at, started = utcnow(), time.perf_counter()
                job = self.client.image((self.project / record["prompt_path"]).read_text(encoding="utf-8"), references, beat_id=beat_id)
                artifacts = list(job.get("output_images") or [])
                if not artifacts:
                    raise RuntimeError(f"Beat {beat_id:03d} did not produce a generated artifact.")
                # ChatGPT can expose multiple UI representations/variations
                # for one requested image even when the prompt asks for one.
                # Ordak exports these in deterministic rank order (generated
                # hint, largest native area, then document position).  The
                # pipeline therefore uses the highest-ranked item as the only
                # canonical beat, while preserving all alternatives in state
                # for audit rather than failing or picking at random.
                canonical_artifact = str(artifacts[0])
                alternative_artifacts = [str(item) for item in artifacts[1:]]
                temporary = target.with_suffix(".download")
                download_timing = self.client.download(canonical_artifact, temporary)
                shutil.move(temporary, target)
                metadata = self.valid_image(target, previous_sha)
            except Exception as exc:
                target.unlink(missing_ok=True)
                record.update({"status": "FAILED", "last_error": str(exc)})
                self.save()
                self.notifier.failure(f"Beat {beat_id:03d} image", time.perf_counter() - started, str(exc))
                raise
            record.update({
                "status": "DONE",
                "ordak_job_id": job["job_id"],
                "output": metadata,
                "canonical_artifact": canonical_artifact,
                "alternative_artifacts": alternative_artifacts,
                "completed_at": utcnow(),
            })
            self.record_timing("beat_image", started_at, started, beat_id=beat_id, ordak_job_id=job["job_id"], references=[str(path.relative_to(self.root)) for path in references], request_timing=job.get("_client_timing"), download_timing=download_timing, output=metadata)
            previous, previous_sha = target, metadata["sha256"]
            self.save()
            self.notifier.image_complete(beat_id, len(beats), time.perf_counter() - started)

    def write_report(self, beats: list[dict[str, str]]) -> Path:
        results = [self.state["beats"].get(f"{int(beat['id']):03d}", {}) for beat in beats]
        valid = [result for result in results if result.get("status") == "DONE"]
        payload = {"passed": len(valid) == len(beats), "topic": self.topic, "aspect_ratio": self.aspect_ratio, "total_planned_beats": len(beats), "total_valid_images": len(valid), "missing_beats": [index + 1 for index, result in enumerate(results) if result.get("status") != "DONE"], "invalid_beats": [index + 1 for index, result in enumerate(results) if result.get("status") == "INVALID"], "images": [{"beat_id": index + 1, "attempts": result.get("attempts", 0), "previous_beat_reference_required": index > 0, "previous_beat_reference_present": len(result.get("references", [])) >= 3 if index > 0 else False, **(result.get("output") or {})} for index, result in enumerate(results)], "completed_at": utcnow()}
        target = self.state_dir / "VISUAL_QC_REPORT.json"
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (self.state_dir / "RUN_SUMMARY.md").write_text(f"# Visual pipeline run\n\nPassed: `{payload['passed']}`\n\nFrame format: `{self.aspect_ratio}`\n\nPlanned beats: {len(beats)}\n\nValid images: {len(valid)}\n", encoding="utf-8")
        return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--preset", required=True)
    parser.add_argument("--duration-seconds", type=float, default=None, help="Legacy fixed-duration shorthand.")
    parser.add_argument("--min-duration-seconds", type=float, default=None)
    parser.add_argument("--max-duration-seconds", type=float, default=None)
    parser.add_argument("--aspect-ratio", choices=("16:9", "9:16"), default="16:9")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.duration_seconds is not None and (args.min_duration_seconds is not None or args.max_duration_seconds is not None):
        raise RuntimeError("Use either --duration-seconds or a min/max duration range, not both.")
    duration_min = args.min_duration_seconds if args.min_duration_seconds is not None else args.duration_seconds
    duration_max = args.max_duration_seconds if args.max_duration_seconds is not None else args.duration_seconds
    if duration_min is None or duration_max is None or not 15 <= duration_min <= duration_max <= 300:
        raise RuntimeError("Duration range must be within 15..300 seconds and minimum must not exceed maximum.")
    env_file = ROOT / os.getenv("YT_ENV_FILE", ".env")
    load_dotenv(env_file, override=False)
    client = OrdakClient(Settings(os.getenv("YT_ORDAK_BASE_URL", "http://127.0.0.1:8000").rstrip("/"), int(os.getenv("YT_ORDAK_JOB_WAIT_TIMEOUT_SECONDS", "900")), float(os.getenv("YT_ORDAK_JOB_POLL_INTERVAL_SECONDS", "2"))))
    try:
        report = Pipeline(ROOT, args.topic, args.video_id, args.preset, duration_min, duration_max, args.aspect_ratio, client, args.force).run()
    finally:
        client.close()
    print(f"VISUAL PIPELINE: PASS\nReport: {report}")


if __name__ == "__main__":
    main()

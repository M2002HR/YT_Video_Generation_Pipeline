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

    def readiness(self) -> dict[str, Any]:
        health = self.http.get(f"{self.settings.base_url}/api/health")
        health.raise_for_status()
        diagnostics = self.http.get(f"{self.settings.base_url}/api/diagnostics")
        diagnostics.raise_for_status()
        data = diagnostics.json()
        chatgpt = (data.get("provider_sessions") or {}).get("chatgpt") or {}
        if not data.get("chrome_running") or not chatgpt.get("logged_in") or chatgpt.get("login_state") != "ready":
            raise RuntimeError("Ordak/Chrome/ChatGPT readiness check failed; run python scripts/check_ordak.py.")
        return data

    def text(self, prompt: str, *, stage: str) -> dict[str, Any]:
        started = time.perf_counter()
        response = self.http.post(
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
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
        return payload

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
        response = self.http.post(f"{self.settings.base_url}/api/jobs", data=data, files=files)
        response.raise_for_status()
        created = response.json()
        job_id = created["job_id"]
        deadline = time.monotonic() + self.settings.wait_seconds
        poll_started = time.perf_counter()
        poll_count = 0
        while time.monotonic() < deadline:
            poll_count += 1
            job_response = self.http.get(f"{self.settings.base_url}/api/jobs/{job_id}")
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
        response = self.http.get(url)
        response.raise_for_status()
        destination.write_bytes(response.content)
        return {"operation": "artifact_download", "elapsed_seconds": round(time.perf_counter() - started, 3), "bytes": len(response.content)}


class Pipeline:
    def __init__(self, root: Path, topic: str, video_id: str, preset: str, duration_seconds: float, client: OrdakClient, force: bool) -> None:
        self.root, self.topic, self.video_id, self.preset, self.duration_seconds, self.client, self.force = root, topic, video_id, preset, duration_seconds, client, force
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
            if self.state.get("topic") != self.topic or self.state.get("preset") != self.preset or float(self.state.get("duration_seconds", 60)) != self.duration_seconds:
                raise RuntimeError("Existing project state has different topic, preset, or duration; choose another video ID.")
            return
        self.state = {"version": 3, "topic": self.topic, "preset": self.preset, "duration_seconds": self.duration_seconds, "created_at": utcnow(), "stages": {}, "beats": {}, "timing_events": []}
        self.save()

    def write_once(self, relative: str, content: str) -> Path:
        target = self.project / relative
        if self.force or not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content.strip() + "\n", encoding="utf-8")
        return target

    def brief(self) -> Path:
        target_words = round(self.duration_seconds * 2.3)
        minimum_words = round(self.duration_seconds * 2.05)
        maximum_words = round(self.duration_seconds * 2.5)
        return self.write_once("BRIEF.md", f"""# Video Brief

Topic: {self.topic}
Language: English
Target: {self.duration_seconds:g} seconds; roughly {minimum_words}–{maximum_words} spoken words (aim near {target_words}).
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
        minimum_words = round(self.duration_seconds * 2.05)
        maximum_words = round(self.duration_seconds * 2.5)
        if not minimum_words <= len(words) <= maximum_words or "###" in text:
            raise RuntimeError(f"Script validation failed: expected {minimum_words}–{maximum_words} spoken words for {self.duration_seconds:g}s, got {len(words)} words.")

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
        expected = max(6, round(self.duration_seconds / 3.5))
        minimum, maximum = max(4, expected - 4), expected + 5
        if not minimum <= len(beats) <= maximum or [beat["id"] for beat in beats] != list(range(1, len(beats) + 1)):
            raise RuntimeError(f"Visual beat validation failed: expected {minimum}–{maximum} sequential complete beats for {self.duration_seconds:g}s.")
        if any(not all(str(value).strip() for key, value in beat.items() if key != "id") for beat in beats):
            raise RuntimeError("Visual beat validation failed: one or more required fields are empty.")
        return beats

    def run(self) -> Path:
        total_timer = StageTimer()
        try:
            self.client.readiness()
            self.load_or_init()
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
                    prompt_request = replace_tokens(load_template("04_single_beat_image_prompt_writer.md"), STYLE_RULES=style_rules, VISUAL_BEAT=json.dumps(beat, ensure_ascii=False), REFERENCE_IMAGES="style anchor, character anchor, and previous accepted beat where applicable", PREVIOUS_BEAT="No previous beat for Beat 001." if beat_id == 1 else "Use the supplied previous accepted beat only for short-range continuity.")
                    prompt_result = self.client.text(prompt_request, stage=f"beat_{beat_id:03d}_prompt")
                    prompt = str(prompt_result["answer"]).strip()
                    if "exactly one" not in prompt.lower() or "16:9" not in prompt:
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
        if not 1.60 <= aspect <= 1.90:
            raise RuntimeError(f"Image must be landscape ~16:9: {path} ({width}x{height})")
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
                if len(artifacts) != 1:
                    raise RuntimeError(f"Beat {beat_id:03d} needs exactly one canonical generated artifact; got {len(artifacts)}.")
                temporary = target.with_suffix(".download")
                download_timing = self.client.download(str(artifacts[0]), temporary)
                shutil.move(temporary, target)
                metadata = self.valid_image(target, previous_sha)
            except Exception as exc:
                target.unlink(missing_ok=True)
                record.update({"status": "FAILED", "last_error": str(exc)})
                self.save()
                self.notifier.failure(f"Beat {beat_id:03d} image", time.perf_counter() - started, str(exc))
                raise
            record.update({"status": "DONE", "ordak_job_id": job["job_id"], "output": metadata, "completed_at": utcnow()})
            self.record_timing("beat_image", started_at, started, beat_id=beat_id, ordak_job_id=job["job_id"], references=[str(path.relative_to(self.root)) for path in references], request_timing=job.get("_client_timing"), download_timing=download_timing, output=metadata)
            previous, previous_sha = target, metadata["sha256"]
            self.save()
            self.notifier.image_complete(beat_id, len(beats), time.perf_counter() - started)

    def write_report(self, beats: list[dict[str, str]]) -> Path:
        results = [self.state["beats"].get(f"{int(beat['id']):03d}", {}) for beat in beats]
        valid = [result for result in results if result.get("status") == "DONE"]
        payload = {"passed": len(valid) == len(beats), "topic": self.topic, "total_planned_beats": len(beats), "total_valid_images": len(valid), "missing_beats": [index + 1 for index, result in enumerate(results) if result.get("status") != "DONE"], "invalid_beats": [index + 1 for index, result in enumerate(results) if result.get("status") == "INVALID"], "images": [{"beat_id": index + 1, "attempts": result.get("attempts", 0), "previous_beat_reference_required": index > 0, "previous_beat_reference_present": len(result.get("references", [])) >= 3 if index > 0 else False, **(result.get("output") or {})} for index, result in enumerate(results)], "completed_at": utcnow()}
        target = self.state_dir / "VISUAL_QC_REPORT.json"
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (self.state_dir / "RUN_SUMMARY.md").write_text(f"# Visual pipeline run\n\nPassed: `{payload['passed']}`\n\nPlanned beats: {len(beats)}\n\nValid images: {len(valid)}\n", encoding="utf-8")
        return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--preset", required=True)
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not 15 <= args.duration_seconds <= 300:
        raise RuntimeError("--duration-seconds must be between 15 and 300.")
    env_file = ROOT / os.getenv("YT_ENV_FILE", ".env")
    load_dotenv(env_file, override=False)
    client = OrdakClient(Settings(os.getenv("YT_ORDAK_BASE_URL", "http://127.0.0.1:8000").rstrip("/"), int(os.getenv("YT_ORDAK_JOB_WAIT_TIMEOUT_SECONDS", "900")), float(os.getenv("YT_ORDAK_JOB_POLL_INTERVAL_SECONDS", "2"))))
    try:
        report = Pipeline(ROOT, args.topic, args.video_id, args.preset, args.duration_seconds, client, args.force).run()
    finally:
        client.close()
    print(f"VISUAL PIPELINE: PASS\nReport: {report}")


if __name__ == "__main__":
    main()

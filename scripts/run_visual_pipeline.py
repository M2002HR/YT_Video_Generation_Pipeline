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
        response = self.http.post(
            f"{self.settings.base_url}/api/chatgpt/respond",
            json={"question": prompt, "mode": "chat", "start_new_chat": True,
                  "wait_for_completion": True, "wait_timeout_seconds": self.settings.wait_seconds},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "completed" or not str(payload.get("answer") or "").strip():
            raise RuntimeError(f"Ordak text stage {stage} failed: {payload.get('error_message') or payload.get('status')}")
        return payload

    def image(self, prompt: str, references: list[Path], *, beat_id: int) -> dict[str, Any]:
        files = [("image", (reference.name, reference.read_bytes(), "image/png")) for reference in references]
        data = {
            "question": prompt,
            "provider": "chatgpt",
            "mode": "image_generate",
            "start_new_chat": "true",
            "wait_for_completion": "true",
            "wait_timeout_seconds": str(self.settings.wait_seconds),
        }
        response = self.http.post(f"{self.settings.base_url}/api/jobs", data=data, files=files)
        response.raise_for_status()
        created = response.json()
        job_id = created["job_id"]
        deadline = time.monotonic() + self.settings.wait_seconds
        while time.monotonic() < deadline:
            job_response = self.http.get(f"{self.settings.base_url}/api/jobs/{job_id}")
            job_response.raise_for_status()
            job = job_response.json()
            if job.get("status") in {"completed", "failed", "manual_verification_required", "cancelled"}:
                if job.get("status") != "completed":
                    raise RuntimeError(f"Beat {beat_id:03d} Ordak job {job_id} failed: {job.get('error_message') or job.get('status')}")
                return job
            time.sleep(self.settings.poll_seconds)
        raise RuntimeError(f"Beat {beat_id:03d} Ordak job {job_id} exceeded parent wait timeout.")

    def download(self, artifact: str, destination: Path) -> None:
        url = artifact if artifact.startswith("http") else f"{self.settings.base_url}/{artifact.lstrip('/')}"
        response = self.http.get(url)
        response.raise_for_status()
        destination.write_bytes(response.content)


class Pipeline:
    def __init__(self, root: Path, topic: str, video_id: str, preset: str, client: OrdakClient, force: bool) -> None:
        self.root, self.topic, self.video_id, self.preset, self.client, self.force = root, topic, video_id, preset, client, force
        self.project = root / "videos" / f"{video_id}_{slugify(topic)}"
        self.state_dir = self.project / "visual_pipeline"
        self.state_path = self.state_dir / "RUNTIME_STATE.json"
        self.state: dict[str, Any] = {}

    def save(self) -> None:
        self.state["updated_at"] = utcnow()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def load_or_init(self) -> None:
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if self.state.get("topic") != self.topic or self.state.get("preset") != self.preset:
                raise RuntimeError("Existing project state has a different topic or preset; choose another video ID.")
            return
        self.state = {"version": 1, "topic": self.topic, "preset": self.preset, "created_at": utcnow(), "stages": {}, "beats": {}}
        self.save()

    def write_once(self, relative: str, content: str) -> Path:
        target = self.project / relative
        if self.force or not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content.strip() + "\n", encoding="utf-8")
        return target

    def brief(self) -> Path:
        return self.write_once("BRIEF.md", f"""# Video Brief

Topic: {self.topic}
Language: English
Target: 55–65 seconds; roughly 125–155 spoken words.
Audience: general viewers interested in an engaging psychology/neuroscience short.
Constraints: no medical diagnosis or medical advice; avoid unsupported claims and invented statistics.
""")

    def _stage_text(self, name: str, prompt: str, output: str, validator) -> str:
        target = self.project / output
        if target.exists() and not self.force:
            content = target.read_text(encoding="utf-8").strip()
            validator(content)
            return content
        result = self.client.text(prompt, stage=name)
        content = str(result["answer"]).strip()
        validator(content)
        self.write_once(output, content)
        self.state["stages"][name] = {"status": "DONE", "ordak_job_id": result["job_id"], "completed_at": utcnow()}
        self.save()
        return content

    @staticmethod
    def validate_script(text: str) -> None:
        words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)
        if not 115 <= len(words) <= 170 or "###" in text:
            raise RuntimeError(f"Script validation failed: expected a clean ~60-second narration, got {len(words)} words.")

    @staticmethod
    def parse_beats(text: str) -> list[dict[str, str]]:
        pattern = re.compile(r"### Beat\s+(\d+)\s*\nNarration:\s*\n(.*?)\n\s*Visual:\s*\n(.*?)\n\s*Purpose:\s*\n(.*?)\n\s*Type:\s*\n(.*?)\n\s*Continuity:\s*\n(.*?)(?=\n### Beat\s+|\Z)", re.S | re.I)
        beats = [{"id": int(match.group(1)), "narration": match.group(2).strip(), "visual": match.group(3).strip(), "purpose": match.group(4).strip(), "type": match.group(5).strip(), "continuity": match.group(6).strip()} for match in pattern.finditer(text)]
        if not 14 <= len(beats) <= 22 or [beat["id"] for beat in beats] != list(range(1, len(beats) + 1)):
            raise RuntimeError("Visual beat validation failed: expected 14–22 sequential complete beats.")
        if any(not all(str(value).strip() for key, value in beat.items() if key != "id") for beat in beats):
            raise RuntimeError("Visual beat validation failed: one or more required fields are empty.")
        return beats

    def run(self) -> Path:
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
                prompt_request = replace_tokens(load_template("04_single_beat_image_prompt_writer.md"), STYLE_RULES=style_rules, VISUAL_BEAT=json.dumps(beat, ensure_ascii=False), REFERENCE_IMAGES="style anchor, character anchor, and previous accepted beat where applicable", PREVIOUS_BEAT="No previous beat for Beat 001." if beat_id == 1 else "Use the supplied previous accepted beat only for short-range continuity.")
                prompt_result = self.client.text(prompt_request, stage=f"beat_{beat_id:03d}_prompt")
                prompt = str(prompt_result["answer"]).strip()
                if "exactly one" not in prompt.lower() or "16:9" not in prompt:
                    raise RuntimeError(f"Beat {beat_id:03d} prompt validation failed.")
                self.write_once(str(prompt_path.relative_to(self.project)), prompt)
            self.state["beats"].setdefault(f"{beat_id:03d}", {"status": "PROMPT_READY", "attempts": 0})["prompt_path"] = str(prompt_path.relative_to(self.project))
            self.save()
        self.generate_images(beats, style, character)
        return self.write_report(beats)

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
                job = self.client.image((self.project / record["prompt_path"]).read_text(encoding="utf-8"), references, beat_id=beat_id)
                artifacts = list(job.get("output_images") or [])
                if len(artifacts) != 1:
                    raise RuntimeError(f"Beat {beat_id:03d} needs exactly one canonical generated artifact; got {len(artifacts)}.")
                temporary = target.with_suffix(".download")
                self.client.download(str(artifacts[0]), temporary)
                shutil.move(temporary, target)
                metadata = self.valid_image(target, previous_sha)
            except Exception as exc:
                target.unlink(missing_ok=True)
                record.update({"status": "FAILED", "last_error": str(exc)})
                self.save()
                raise
            record.update({"status": "DONE", "ordak_job_id": job["job_id"], "output": metadata, "completed_at": utcnow()})
            previous, previous_sha = target, metadata["sha256"]
            self.save()

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
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    env_file = ROOT / os.getenv("YT_ENV_FILE", ".env")
    load_dotenv(env_file, override=False)
    client = OrdakClient(Settings(os.getenv("YT_ORDAK_BASE_URL", "http://127.0.0.1:8000").rstrip("/"), int(os.getenv("YT_ORDAK_JOB_WAIT_TIMEOUT_SECONDS", "900")), float(os.getenv("YT_ORDAK_JOB_POLL_INTERVAL_SECONDS", "2"))))
    try:
        report = Pipeline(ROOT, args.topic, args.video_id, args.preset, client, args.force).run()
    finally:
        client.close()
    print(f"VISUAL PIPELINE: PASS\nReport: {report}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Question Harvest — the bookworld mixed-media pipeline (§57), production path only.

Stage order:

    workspace → creative brief → script (JSON) → retention edit → episode direction
    → world style decision → world style anchor → body visual plan → world keyframe prompt
    → Gemini world keyframe → book spread composition → Flow Clip A/B prompts
    → Flow Clip A → Flow Clip B → per-beat image prompts → Gemini body images

Rules this file exists to keep (master_prompt §4, §60-61):

* **No synthetic media, ever.** There is no fallback that draws a placeholder or renders a
  colour card. A provider failure becomes a ``PAUSED_*``/``FAILED_*`` state with the
  provider's own error code, and the run stops there.
* **No provider fallback.** text=ChatGPT, image=Gemini, video=Flow — each through Ordak.
* **The generation contract travels as data**, not as text smuggled into the prompt: model,
  aspect, duration and resolution go through ``ordak_jobs.Generation``, and every upload
  declares its role through ``ordak_jobs.Reference``.
* **Flow never receives a style sheet.** ``flow_reference_policy`` decides what each clip may
  receive, and the Ordak side enforces it again at the upload boundary.
* Every expensive stage is resumable: a valid artifact plus a recorded DONE state is reused.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from content_projects import (  # noqa: E402
    load_content_project,
    normalize_flow_model,
    normalize_gemini_model,
    validate_content_project,
    validate_provider_locks,
    video_slug,
)
from flow_reference_policy import build_flow_uploads  # noqa: E402
from ordak_jobs import (  # noqa: E402
    Generation,
    JobResult,
    OrdakJobError,
    OrdakJobs,
    Reference,
    sha256_file,
    sha256_text,
)
from pipeline_notifier import PipelineNotifier, format_duration  # noqa: E402
from pipeline_stages import stage_title as full_stage_title  # noqa: E402

WORLD_STYLES_ROOT = ROOT / "projects" / "question_harvest" / "world_styles"
BOOK_TEMPLATES_ROOT = ROOT / "projects" / "question_harvest" / "book_templates"
# Ordak's typed request schema permits 20,000 characters. Keep a small safety
# margin so a future prompt expansion cannot become an opaque HTTP 500 before a
# job is even recorded.
ORDAK_QUESTION_LIMIT = 19_000

MIN_IMAGE_BYTES = 10_000
MIN_VIDEO_BYTES = 100_000


# ------------------------------------------------------------------ state machine (§81)

#: The only states a stage may hold. There is deliberately no FALLBACK_* state.
STATE_PENDING = "PENDING"
STATE_RUNNING = "RUNNING"
STATE_DONE = "DONE"
STATE_REUSED = "REUSED"
PAUSE_STATES = ("PAUSED_LOGIN_REQUIRED", "PAUSED_MANUAL_VERIFICATION", "PAUSED_CREDITS")


class StageFailure(RuntimeError):
    """A stage that cannot be completed. Carries the pipeline state it maps to."""

    def __init__(self, stage: str, state: str, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        self.stage = stage
        self.state = state
        self.message = message
        self.error_code = error_code

    @property
    def needs_human(self) -> bool:
        return self.state in PAUSE_STATES


def utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class QHState:
    """Durable per-video stage state, persisted after every transition (§81)."""

    def __init__(self, project: Path, video_id: str, topic: str) -> None:
        self.project = project
        self.path = project / "pipeline" / "QH_RUNTIME_STATE.json"
        if self.path.is_file():
            try:
                self.state = load_json(self.path)
            except ValueError:
                self.state = {}
        else:
            self.state = {}
        if not self.state:
            self.state = {
                "schema_version": 2,
                "video_id": video_id,
                "topic": topic,
                "created_at": utcnow(),
                "pipeline_state": STATE_RUNNING,
                "stages": {},
                "events": [],
            }
        self.state["video_id"] = video_id
        self.state["topic"] = topic
        # A resumed process is actively making forward progress even though the
        # durable file still contains the last terminal failure.  Clear that stale
        # terminal label before the first stage writes, so the panel and recovery
        # tooling never report a live pipeline as failed.
        if self.state.get("pipeline_state") != STATE_DONE:
            self.state["pipeline_state"] = STATE_RUNNING
            self.save()

    def save(self) -> None:
        self.state["updated_at"] = utcnow()
        save_json(self.path, self.state)

    def done(self, stage: str) -> bool:
        return self.state.get("stages", {}).get(stage, {}).get("status") in (STATE_DONE, STATE_REUSED)

    def mark(self, stage: str, status: str, **extra: Any) -> None:
        self.state.setdefault("stages", {})[stage] = {
            "status": status,
            "updated_at": utcnow(),
            **extra,
        }
        self.save()

    def record(self, stage: str, status: str, elapsed: float, **meta: Any) -> None:
        self.state.setdefault("events", []).append(
            {"stage": stage, "status": status, "elapsed_seconds": round(elapsed, 3), "at": utcnow(), **meta}
        )
        self.save()

    def fail(self, stage: str, failure: StageFailure) -> None:
        self.state["pipeline_state"] = failure.state
        self.mark(
            stage,
            failure.state,
            message=failure.message[:500],
            error_code=failure.error_code,
        )

    def finish(self) -> None:
        self.state["pipeline_state"] = STATE_DONE
        self.save()


# ---------------------------------------------------------------------- artifact checks


def ffprobe_duration(path: Path) -> float:
    output = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        text=True,
        timeout=30,
    )
    return float(output.strip())


def valid_image(path: Path) -> bool:
    """A real decodable image, not a truncated download."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size < MIN_IMAGE_BYTES:
        return False
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        return True
    except Exception:
        return False


def valid_video(path: Path) -> bool:
    path = Path(path)
    if not path.is_file() or path.stat().st_size < MIN_VIDEO_BYTES:
        return False
    try:
        return ffprobe_duration(path) > 0.2
    except Exception:
        return False


def strip_fences(text: str) -> str:
    """Tolerate the Markdown fence ChatGPT sometimes adds around JSON (§50)."""
    body = text.strip()
    if body.startswith("```"):
        body = re.sub(r"^```(?:json)?\s*", "", body, flags=re.IGNORECASE)
        body = re.sub(r"\s*```\s*$", "", body)
    return body.strip()


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text))


# --------------------------------------------------------------------- provider plumbing


def require_verified_image_model(stage: str, model: str, receipt: dict[str, Any] | None) -> None:
    """A Gemini image is only usable if the UI confirmed the model that made it (§8, §18).

    ``model_verified`` cannot be set without an observed label — the receipt schema refuses
    that — so an unverified receipt means Ordak never read the model control, and the image
    could have come from any model Gemini happened to have selected.
    """
    data = dict(receipt or {})
    if not data.get("model_verified"):
        raise StageFailure(
            stage,
            "FAILED_MODEL_SELECTION",
            f"{stage}: Gemini did not confirm {model!r} in its own UI "
            f"(observed label: {data.get('actual_model_label')!r}), so this image cannot be "
            "accepted as produced by the requested model.",
        )
    if model == "nano_banana_pro" and not data.get("pro_regeneration_used"):
        raise StageFailure(
            stage,
            "FAILED_MODEL_SELECTION",
            f"{stage}: Nano Banana Pro was requested but the receipt shows no Pro "
            "regeneration, and a Nano Banana 2 image is never accepted as Pro (§6).",
        )


def require_verified_video_model(stage: str, model: str, receipt: dict[str, Any] | None) -> None:
    """A Flow clip is only usable if Flow confirmed the model that rendered it (§18)."""
    data = dict(receipt or {})
    if not data.get("model_verified"):
        raise StageFailure(
            stage,
            "FAILED_MODEL_SELECTION",
            f"{stage}: Flow did not confirm {model!r} in its own settings menu "
            f"(observed label: {data.get('actual_model_label')!r}).",
        )


class Runner:
    """One place where every provider call happens, so the rules hold everywhere.

    A failed call is translated into a :class:`StageFailure` carrying the provider's own
    error code, which the state machine turns into a ``PAUSED_*``/``FAILED_*`` state. No call
    site is allowed to catch a provider failure and substitute something it made up.
    """

    def __init__(self, jobs: OrdakJobs, notifier: PipelineNotifier | None, state: QHState) -> None:
        self.jobs = jobs
        self.notifier = notifier
        self.state = state
        self.stage_messages: dict[str, Any] = {}

    # -- stage bookkeeping and Telegram log (§9.3) -----------------------

    def _send(self, title: str, lines: list[str]) -> None:
        if self.notifier is None:
            return
        try:
            self.notifier.send(title, lines)
        except Exception as exc:  # pragma: no cover - telemetry must never break a run
            print(f"notify failed: {exc}", flush=True)

    @staticmethod
    def _stage_title(stage: str) -> str:
        return full_stage_title(stage)

    def stage_start(self, stage: str) -> float:
        self.state.mark(stage, STATE_RUNNING)
        print(f"▶ {stage}", flush=True)
        if self.notifier is not None:
            self.stage_messages[stage] = self.notifier.stage_started(self._stage_title(stage))
        return time.perf_counter()

    def stage_done(self, stage: str, started: float, summary: str = "", **meta: Any) -> None:
        elapsed = time.perf_counter() - started
        self.state.mark(stage, STATE_DONE, **meta)
        self.state.record(stage, STATE_DONE, elapsed, **meta)
        print(f"✔ {stage} ({elapsed:.1f}s){' — ' + summary if summary else ''}", flush=True)
        if self.notifier is not None:
            try:
                lines = ["✅ Stage complete", f"⏱ Duration: {format_duration(elapsed)}"]
                if summary:
                    lines.append(f"📄 Saved: {summary}")
                self.notifier.stage_update(self.stage_messages.pop(stage, None), self._stage_title(stage), lines)
            except Exception as exc:  # pragma: no cover
                print(f"notify failed: {exc}", flush=True)

    def stage_reused(self, stage: str, summary: str = "") -> None:
        self.state.mark(stage, STATE_REUSED, artifact=summary or None)
        print(f"↻ {stage} reused{(' — ' + summary) if summary else ''}", flush=True)
        if self.notifier is not None:
            self.notifier.stage_reused(self._stage_title(stage), ["↻ Reused existing artifact", summary])

    def stage_progress(self, stage: str, lines: list[str]) -> None:
        """Refresh one aggregate stage message; used for the whole body-image batch."""
        if self.notifier is not None:
            self.notifier.stage_update(self.stage_messages.get(stage), self._stage_title(stage), lines)

    def stage_failed(self, stage: str, failure: StageFailure, started: float) -> None:
        self.state.fail(stage, failure)
        elapsed = time.perf_counter() - started
        print(f"✘ {stage} [{failure.state}] {failure.message}", flush=True)
        if self.notifier is not None:
            try:
                # Failure is intentionally a separate alert. The last normal-stage entry stays
                # intact, so one new message always means the pipeline needs attention.
                self.stage_messages.pop(stage, None)
                self.notifier.failure(self._stage_title(stage), elapsed, f"{failure.state}: {failure.message}")
            except Exception as exc:  # pragma: no cover
                print(f"notify failed: {exc}", flush=True)

    # -- provider calls --------------------------------------------------

    def _run(
        self,
        stage: str,
        question: str,
        *,
        provider: str,
        mode: str,
        generation: Generation | None = None,
        references: list[Reference] = (),
        timeout_seconds: int | None = None,
    ) -> JobResult:
        if len(question) > ORDAK_QUESTION_LIMIT:
            raise StageFailure(
                stage,
                "FAILED_VALIDATION",
                f"Prompt is {len(question):,} characters, above the safe Ordak limit of {ORDAK_QUESTION_LIMIT:,}. "
                "Pass a stage-specific summary instead of a full downstream artifact.",
            )
        try:
            return self.jobs.run(
                question,
                provider=provider,
                mode=mode,
                generation=generation,
                references=references,
                timeout_seconds=timeout_seconds,
                attempts=3 if provider == "gemini" and mode == "image_generate" else 1,
                on_log=lambda message: print(f"    [{provider}] {message[:160]}", flush=True),
            )
        except OrdakJobError as exc:
            raise StageFailure(
                stage,
                exc.pipeline_state,
                f"{provider}/{mode} failed: {exc.message}",
                error_code=exc.error_code,
            ) from exc

    def text(self, stage: str, prompt: str, *, references: list[Reference] = ()) -> str:
        """One ChatGPT call. An empty answer is a failure, not something to invent around."""
        result = self._run(stage, prompt, provider="chatgpt", mode="chat", references=references)
        answer = (result.answer or "").strip()
        if not answer:
            raise StageFailure(stage, "FAILED", f"ChatGPT returned an empty answer for {stage}.")
        return answer

    def json(
        self, stage: str, prompt: str, *, retries: int = 2, references: list[Reference] = ()
    ) -> Any:
        """ChatGPT call that must parse as JSON, with a bounded correction retry (§50)."""
        current = prompt
        last_error = ""
        last_raw = ""
        for attempt in range(retries + 1):
            last_raw = self.text(f"{stage}_json{attempt + 1}", current, references=references)
            try:
                return json.loads(strip_fences(last_raw))
            except ValueError as exc:
                last_error = str(exc)
                current = (
                    f"Your previous output was not valid JSON ({exc}). Return ONLY raw JSON with "
                    f"no markdown fences and no commentary.\n\nOriginal task:\n{prompt}\n\n"
                    f"Your previous output:\n{last_raw[:2000]}"
                )
        raise StageFailure(
            stage,
            "FAILED_VALIDATION",
            f"{stage} never produced valid JSON after {retries + 1} attempts: {last_error}; "
            f"last output began {last_raw[:200]!r}",
        )

    def image(
        self,
        stage: str,
        prompt: str,
        references: list[Reference],
        *,
        model: str,
        destination: Path,
    ) -> JobResult:
        """One Gemini image, downloaded and verified. Returns the job result for the receipt."""
        result = self._run(
            stage,
            prompt,
            provider="gemini",
            mode="image_generate",
            generation=Generation(model=model, quality="best", aspect_ratio="9:16"),
            references=references,
        )
        if not result.output_images:
            raise StageFailure(stage, "FAILED_DOWNLOAD", f"{stage}: Gemini produced no image artifact.")
        receipt_notes = list((result.generation_receipt or {}).get("notes") or [])
        if "artifact_source=download" not in receipt_notes:
            raise StageFailure(
                stage,
                "FAILED_VALIDATION",
                f"{stage}: Gemini artifact has no verified download provenance; refusing to save it.",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".download")
        self.jobs.download(result.output_images[0], partial)
        partial.replace(destination)
        if not valid_image(destination):
            raise StageFailure(
                stage,
                "FAILED_VALIDATION",
                f"{stage}: the downloaded image is not a decodable image ({destination}).",
            )
        require_verified_image_model(stage, model, result.generation_receipt)
        return result

    def video(
        self,
        stage: str,
        prompt: str,
        references: list[Reference],
        *,
        model: str,
        resolution: str,
        aspect_ratio: str,
        duration_seconds: int,
        destination: Path,
    ) -> JobResult:
        """One Flow clip. The duration is part of the contract because it costs credits."""
        result = self._run(
            stage,
            prompt,
            provider="flow",
            mode="video_generate",
            generation=Generation(
                model=model,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
            ),
            references=references,
            timeout_seconds=int(os.getenv("YT_ORDAK_FLOW_JOB_WAIT_SECONDS", "1200")),
        )
        artifacts = result.output_videos or result.output_images
        if not artifacts:
            raise StageFailure(stage, "FAILED_DOWNLOAD", f"{stage}: Flow produced no video artifact.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".download")
        self.jobs.download(artifacts[0], partial)
        partial.replace(destination)
        if not valid_video(destination):
            raise StageFailure(
                stage,
                "FAILED_VALIDATION",
                f"{stage}: the downloaded file is not a playable video ({destination}).",
            )
        require_verified_video_model(stage, model, result.generation_receipt)
        return result


# ------------------------------------------------------------------- script plan (§67)

SCRIPT_PLAN_KEYS = ("opening_question_spark", "book_transition", "body", "cta", "full_narration")

#: Spoken words per second, measured against the format's own 40-60s => 92-150 word rule.
WORDS_PER_SECOND_RANGE = (2.3, 2.5)

#: A 60–90s episode needs a new picture roughly every 2.5–4 seconds, rather
#: than holding one generic illustration over a whole compound thought.
MIN_BODY_BEATS = 18
MAX_BODY_BEATS = 30


@dataclass(frozen=True)
class DurationTarget:
    """The episode length the operator asked for, in the terms each prompt needs."""

    min_seconds: float
    max_seconds: float

    @property
    def word_min(self) -> int:
        return int(round(self.min_seconds * WORDS_PER_SECOND_RANGE[0]))

    @property
    def word_max(self) -> int:
        return int(round(self.max_seconds * WORDS_PER_SECOND_RANGE[1]))

    @property
    def word_target(self) -> int:
        return int(round((self.word_min + self.word_max) / 2))

    @property
    def beat_min(self) -> int:
        """Visual units scale to keep a brisk 2.5–4s editorial image cadence."""
        return max(6, round(MIN_BODY_BEATS * self.min_seconds / 60))

    @property
    def beat_max(self) -> int:
        return max(self.beat_min + 3, round(MAX_BODY_BEATS * self.max_seconds / 90))

    @property
    def beat_range(self) -> str:
        return f"{self.beat_min}\u2013{self.beat_max}"

    @property
    def duration_range(self) -> str:
        return f"{self.min_seconds:g}\u2013{self.max_seconds:g}s"

    @property
    def word_range(self) -> str:
        return f"~{self.word_min}\u2013{self.word_max}"

    def as_prompt_values(self) -> dict[str, str]:
        return {
            "DURATION_RANGE": self.duration_range,
            "WORD_RANGE": self.word_range,
            "WORD_TARGET": str(self.word_target),
            "BEAT_RANGE": self.beat_range,
            "BEAT_MIN": str(self.beat_min),
            "BEAT_MAX": str(self.beat_max),
        }


#: The format default, kept as the fallback when no length was requested.
MIN_SCRIPT_WORDS = 92
MAX_SCRIPT_WORDS = 150


def _plan_tokens(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?", text)]


def validate_script_plan(stage: str, data: Any, duration: "DurationTarget" | None = None) -> dict[str, Any]:
    """Accept a script only if its segments really are the narration.

    Downstream, the Flow clips are trimmed to the measured end of ``opening_question_spark``
    and ``book_transition``. If those strings are not literally part of the narration that
    ElevenLabs speaks, every trim is computed against words that were never said — and the
    result still looks plausible. So the concatenation is checked here, before anything is
    generated (§67).
    """
    if not isinstance(data, dict):
        raise StageFailure(stage, "FAILED_VALIDATION", "The script must be a JSON object.")
    missing = [key for key in SCRIPT_PLAN_KEYS if key not in data]
    if missing:
        raise StageFailure(stage, "FAILED_VALIDATION", f"The script is missing keys: {missing}")

    # The acceptable ranges follow the length that was asked for. A fixed 8-15 beats or
    # 92-150 words would reject a correctly written 25-30s script for being that length.
    target = duration or DurationTarget(40.0, 60.0)

    body = data.get("body")
    if not isinstance(body, list) or not all(isinstance(item, str) and item.strip() for item in body):
        raise StageFailure(stage, "FAILED_VALIDATION", "`body` must be a list of non-empty strings.")
    if any(len(re.findall(r"[.!?…](?:[\"')\]]|\s)*", item.strip())) > 1 for item in body):
        raise StageFailure(
            stage,
            "FAILED_VALIDATION",
            "A `body` entry contains more than one sentence. Split it into atomic visual units.",
        )
    if any(len(_plan_tokens(item)) > 16 for item in body):
        raise StageFailure(
            stage,
            "FAILED_VALIDATION",
            "A body visual unit exceeds 16 words. Split distinct actions, actors, reveals, and consequences into faster picture beats.",
        )
    if not target.beat_min <= len(body) <= target.beat_max:
        raise StageFailure(
            stage,
            "FAILED_VALIDATION",
            f"`body` has {len(body)} beats; a {target.duration_range} Short needs "
            f"{target.beat_min}-{target.beat_max}.",
        )

    ordered = [
        str(data.get("opening_question_spark") or "").strip(),
        str(data.get("book_transition") or "").strip(),
        *[item.strip() for item in body],
        str(data.get("optional_closing") or "").strip(),
        str(data.get("cta") or "").strip(),
    ]
    joined = " ".join(part for part in ordered if part)
    full = str(data.get("full_narration") or "").strip()
    if _plan_tokens(joined) != _plan_tokens(full):
        raise StageFailure(
            stage,
            "FAILED_VALIDATION",
            "`full_narration` is not the concatenation of the segments, so the opening trims "
            "would be measured against words that are not spoken.",
        )

    words = word_count(full)
    low, high = target.word_min, target.word_max
    if not low <= words <= high:
        raise StageFailure(
            stage,
            "FAILED_VALIDATION",
            f"The narration is {words} words; a {target.duration_range} Short needs "
            f"{low}-{high}.",
        )

    normalized = {key: data.get(key) for key in ("opening_question_spark", "book_transition", "cta")}
    normalized["body"] = [item.strip() for item in body]
    normalized["optional_closing"] = str(data.get("optional_closing") or "").strip()
    normalized["full_narration"] = full
    normalized["word_count"] = words
    normalized["created_at"] = utcnow()
    return normalized


# -------------------------------------------------------------------------- prompt files


def resolve_prompt(content_project: Any, name: str) -> str:
    from content_projects import resolve_pipeline_prompt

    return resolve_pipeline_prompt(content_project, name).read_text(encoding="utf-8")


def fill(template: str, **values: str) -> str:
    """Substitute prompt tokens and refuse to send a template with holes left in it."""
    filled = template
    for key, value in values.items():
        filled = filled.replace("{{" + key + "}}", value)
    leftover = re.findall(r"\{\{([A-Z_]+)\}\}", filled)
    if leftover:
        raise StageFailure(
            "prompt_fill",
            "FAILED_VALIDATION",
            f"Prompt still contains unfilled tokens: {sorted(set(leftover))}",
        )
    return filled


# ------------------------------------------------------------------------------- stages


def ask_with_correction(
    runner: Runner,
    stage: str,
    prompt: str,
    validate: Any,
    *,
    attempts: int = 3,
    hint: str = "",
) -> Any:
    """Ask for JSON and send the validator's own complaint back when it refuses.

    A miss that names its own fix — one word over the range, one beat too many — is
    correctable, and the writer needs nothing but the complaint to correct it. Only a plan
    that still fails after the corrections becomes a stage failure, so an episode is never
    thrown away for something the next answer would have fixed. The validator stays the
    authority: nothing here relaxes a rule to make an answer pass.
    """
    failure: StageFailure | None = None
    current = prompt
    for attempt in range(attempts):
        label = stage if attempt == 0 else f"{stage}_fix{attempt}"
        try:
            return validate(runner.json(label, current))
        except StageFailure as exc:
            failure = exc
            print(f"    ↻ {stage} rejected: {exc.message}", flush=True)
            current = (
                f"{prompt}\n\nYour previous answer was rejected: {exc.message}\n"
                f"Return the same JSON shape, corrected.{(' ' + hint) if hint else ''}"
            )
    assert failure is not None
    raise failure


def ask_for_script(
    runner: Runner,
    stage: str,
    prompt: str,
    duration: DurationTarget,
    *,
    attempts: int = 3,
) -> dict[str, Any]:
    """One script plan, re-asked with the complaint until it satisfies the validator."""
    return ask_with_correction(
        runner,
        stage,
        prompt,
        lambda data: validate_script_plan(stage, data, duration),
        attempts=attempts,
        hint=(
            "Keep `full_narration` exactly the concatenation of the segments in order, and "
            "respect the word and beat counts."
        ),
    )


def stage_script(
    runner: Runner, project: Path, content_project: Any, brief: str, duration: DurationTarget
) -> dict[str, Any]:
    stage = "script_draft"
    target = project / "creative" / "SCRIPT_DRAFT.json"
    if runner.state.done(stage) and target.is_file():
        runner.stage_reused(stage, target.name)
        return load_json(target)
    started = runner.stage_start(stage)
    prompt = fill(
        resolve_prompt(content_project, "01_script_writer.md"),
        VIDEO_BRIEF=brief,
        **duration.as_prompt_values(),
    )
    plan = ask_for_script(runner, stage, prompt, duration)
    save_json(target, plan)
    runner.stage_done(stage, started, f"{plan['word_count']} words, {len(plan['body'])} beats", words=plan["word_count"])
    return plan


def stage_retention(
    runner: Runner,
    project: Path,
    content_project: Any,
    brief: str,
    draft: dict[str, Any],
    duration: DurationTarget,
) -> dict[str, Any]:
    stage = "retention_edit"
    target = project / "creative" / "SCRIPT_PLAN.json"
    if runner.state.done(stage) and target.is_file():
        runner.stage_reused(stage, target.name)
        return load_json(target)
    started = runner.stage_start(stage)
    prompt = fill(
        resolve_prompt(content_project, "02_retention_editor.md"),
        VIDEO_BRIEF=brief,
        CURRENT_SCRIPT=json.dumps(draft, ensure_ascii=False, indent=2),
        **duration.as_prompt_values(),
    )
    plan = ask_for_script(runner, stage, prompt, duration)
    save_json(target, plan)
    # The plain-text narration is what ElevenLabs speaks; it must be the same words.
    (project / "SCRIPT_FINAL.md").write_text(plan["full_narration"] + "\n", encoding="utf-8")
    runner.stage_done(stage, started, f"{plan['word_count']} words", words=plan["word_count"])
    return plan


def _recent_history(project_id: str = "question_harvest", limit: int = 4) -> list[dict[str, Any]]:
    """The last few episodes' traits, for the anti-repetition heuristics (§35)."""
    from episode_history import recent

    return recent(project_id, limit)


def stage_episode_director(
    runner: Runner, project: Path, content_project: Any, topic: str, brief: str, plan: dict[str, Any]
) -> dict[str, Any]:
    stage = "episode_director"
    target = project / "creative" / "EPISODE_PLAN.json"
    if runner.state.done(stage) and target.is_file():
        runner.stage_reused(stage, target.name)
        return load_json(target)
    started = runner.stage_start(stage)
    from episode_history import avoidance_note, repeated_traits

    history = _recent_history(getattr(content_project, "project_id", "question_harvest"))
    base_prompt = fill(
        resolve_prompt(content_project, "03_episode_director.md"),
        TOPIC=topic,
        CREATIVE_BRIEF=brief,
        FINAL_SCRIPT=plan["full_narration"],
        RECENT_HISTORY=json.dumps(history, ensure_ascii=False),
    )
    prompt = base_prompt
    if history:
        prompt = f"{base_prompt}\n\n{avoidance_note(history)}"

    # §35 is a hard rule, not a hint: an opening that repeats a recent episode is sent back
    # once with the specific repeat named, and only then treated as a validation failure.
    data: Any = None
    repeats: dict[str, str] = {}
    for attempt in range(2):
        data = runner.json(f"{stage}_try{attempt + 1}" if attempt else stage, prompt)
        if not isinstance(data, dict) or not data.get("opening_activity"):
            raise StageFailure(stage, "FAILED_VALIDATION", "The episode plan has no opening_activity.")
        repeats = repeated_traits(data, history)
        if not repeats:
            break
        named = ", ".join(f"{key}={value!r}" for key, value in repeats.items())
        prompt = (
            f"{base_prompt}\n\n{avoidance_note(history)}\n\n"
            f"Your previous plan repeated: {named}. Choose different ones and return the same JSON shape."
        )
    if repeats:
        raise StageFailure(
            stage,
            "FAILED_VALIDATION",
            "The episode plan still repeats a recent episode after a correction attempt: "
            + ", ".join(f"{key}={value!r}" for key, value in repeats.items()),
        )
    save_json(target, data)
    runner.stage_done(stage, started, str(data.get("opening_activity")), activity=data.get("opening_activity"))
    return data


def style_directive(policy: str, style_id: str, hint: str) -> str:
    """State the operator's style choice to the director in one binding sentence."""
    style_id = (style_id or "").strip()
    hint = (hint or "").strip()
    policy = (policy or "auto").strip().lower()
    if style_id:
        return (
            f"Reuse the catalogued style {style_id!r}. Answer decision='reuse' with "
            f"style_id={style_id!r} and reuse_of={style_id!r}. Do not invent a new style."
        )
    if policy == "reuse":
        return (
            "Reuse the best-fitting style already in the catalog; answer decision='reuse'. "
            "Only if the catalog is empty may you propose a new one."
            + (f" Operator steer for the choice: {hint}." if hint else "")
        )
    if policy == "new":
        return (
            "Create a new style; answer decision='new' and reuse_of=null."
            + (f" Operator steer for the new style: {hint}." if hint else "")
        )
    if hint:
        return (
            "Choose freely between reuse and new, whichever fits the topic better. "
            f"Operator steer: {hint}."
        )
    return "No operator constraint: choose reuse or new on the merits, per the rules below."


def stage_world_style_director(
    runner: Runner,
    project: Path,
    content_project: Any,
    topic: str,
    plan: dict[str, Any],
    episode_plan: dict[str, Any],
    directive: str,
) -> dict[str, Any]:
    stage = "world_style_director"
    target = project / "creative" / "WORLD_STYLE_PLAN.json"
    if runner.state.done(stage) and target.is_file():
        runner.stage_reused(stage, target.name)
        return load_json(target)
    started = runner.stage_start(stage)
    catalog = {}
    catalog_path = WORLD_STYLES_ROOT / "CATALOG.json"
    if catalog_path.is_file():
        catalog = load_json(catalog_path)
    prompt = fill(
        resolve_prompt(content_project, "04_world_style_director.md"),
        TOPIC=topic,
        FINAL_SCRIPT=plan["full_narration"],
        EPISODE_PLAN=json.dumps(episode_plan, ensure_ascii=False),
        STYLE_CATALOG=json.dumps(catalog, ensure_ascii=False),
        RECENT_STYLES=json.dumps([item.get("world_style_id") for item in _recent_history()], ensure_ascii=False),
        STYLE_DIRECTIVE=directive,
    )
    def check_style(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict) or not data.get("style_id"):
            raise StageFailure(stage, "FAILED_VALIDATION", "The world style plan has no style_id.")
        return data

    data = ask_with_correction(runner, stage, prompt, check_style)
    save_json(target, data)
    runner.stage_done(stage, started, f"{data.get('style_id')} ({data.get('decision')})", style_id=data.get("style_id"))
    return data


def stage_record_history(
    runner: Runner,
    content_project: Any,
    video_id: str,
    episode_plan: dict[str, Any],
    world_style_plan: dict[str, Any],
) -> None:
    """Write this episode's traits into VIDEOS.json so the next one can avoid them (§35).

    This runs as soon as the traits are decided rather than at publication, so an episode
    that fails later still constrains the following one instead of vanishing from history.
    """
    stage = "episode_history"
    from episode_history import EpisodeHistoryError, record_traits, traits_from_plans

    started = runner.stage_start(stage)
    project_id = getattr(content_project, "project_id", "question_harvest")
    traits = traits_from_plans(episode_plan, world_style_plan)
    try:
        path = record_traits(project_id, video_id, traits)
    except (EpisodeHistoryError, OSError) as exc:
        raise StageFailure(
            stage,
            "FAILED_VALIDATION",
            f"Could not record the episode traits in projects/{project_id}/VIDEOS.json: {exc}",
        ) from exc
    runner.stage_done(
        stage,
        started,
        str(path.relative_to(ROOT)),
        **{key: value for key, value in traits.items() if value is not None},
    )


def stage_world_style_anchor(
    runner: Runner, project: Path, content_project: Any, world_style_plan: dict[str, Any]
) -> Path:
    """The style anchor is a Gemini image or a catalog reuse — never a drawn placeholder."""
    stage = "world_style_anchor"
    target = project / "references" / "world_style_anchor.png"
    if target.is_file() and valid_image(target) and runner.state.done(stage):
        runner.stage_reused(stage, target.name)
        return target
    started = runner.stage_start(stage)

    reuse_of = world_style_plan.get("reuse_of")
    if str(world_style_plan.get("decision") or "").lower() == "reuse" and reuse_of:
        catalog_path = WORLD_STYLES_ROOT / "CATALOG.json"
        entries = load_json(catalog_path).get("styles", []) if catalog_path.is_file() else []
        for entry in entries:
            if entry.get("style_id") != reuse_of:
                continue
            source = WORLD_STYLES_ROOT / str(entry.get("path") or "") / "style_anchor.png"
            if not valid_image(source):
                break
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(source), str(target))
            from world_style_catalog import WorldStyleCatalogError, record_reuse

            try:
                uses = record_reuse(getattr(content_project, "project_id", "question_harvest"), reuse_of)
            except WorldStyleCatalogError:
                uses = None
            runner.stage_done(
                stage, started, f"reused {reuse_of}", reuse_of=reuse_of,
                sha256=sha256_file(target), **({"usage_count": uses} if uses else {}),
            )
            return target
        raise StageFailure(
            stage,
            "FAILED_VALIDATION",
            f"The style plan asks to reuse {reuse_of!r} but no usable style_anchor.png exists "
            "for it in the catalog.",
        )

    prompt = (
        "Create exactly one 9:16 vertical style reference sheet — a texture and palette sample, "
        f"not a scene. Medium: {world_style_plan.get('medium')}. "
        f"Texture family: {world_style_plan.get('texture_family')}. "
        f"Palette: {world_style_plan.get('palette_summary')}. "
        f"Line treatment: {world_style_plan.get('line_treatment')}. "
        f"Lighting: {world_style_plan.get('lighting')}. "
        f"Avoid: {world_style_plan.get('negative_constraints')}. "
        "No characters, no text, no logos, no photorealism."
    )
    launch = load_json(project / "launch" / "LAUNCH_REQUEST.json")
    model = normalize_gemini_model(launch.get("image_generation", {}).get("model") or "nano_banana_2")
    result = runner.image(stage, prompt, [], model=model, destination=target)
    _write_image_receipt(project, "gemini_world_style_anchor", result, prompt, [], target, model)

    # A new style is only reusable once it is in the catalog: the director is shown that
    # file, the panel lists it, and a later episode can be pinned to it (§35).
    from world_style_catalog import WorldStyleCatalogError, publish_style

    published = ""
    try:
        entry = publish_style(
            getattr(content_project, "project_id", "question_harvest"), world_style_plan, target
        )
        published = str(entry.get("path") or "")
    except WorldStyleCatalogError as exc:
        raise StageFailure(
            stage,
            "FAILED_VALIDATION",
            f"The new style could not be registered for reuse: {exc}",
        ) from exc

    runner.stage_done(
        stage, started, f"{target.name} → catalog/{published}",
        sha256=sha256_file(target), model=model, catalog_path=published,
    )
    return target


def _receipt_path(project: Path, output: Path) -> str:
    """A stable, readable path for the receipt.

    Most outputs live inside the episode directory, but a few are project-level assets
    shared by every episode — the book design sheet is written into the content project's
    preset directory. Those are recorded relative to the repository root instead of
    crashing on ``relative_to``.
    """
    for base in (project, ROOT):
        try:
            return str(output.relative_to(base))
        except ValueError:
            continue
    return str(output)


def _write_image_receipt(
    project: Path,
    name: str,
    result: JobResult,
    prompt: str,
    references: list[Reference],
    output: Path,
    requested_model: str,
) -> Path:
    """Persist what the provider reported, not what we hoped for (§8).

    ``model_verified`` is copied from the provider receipt only. If Ordak could not confirm
    the model in the UI, this file says so — nothing here upgrades an unverified run.
    """
    receipt = dict(result.generation_receipt or {})
    from PIL import Image

    with Image.open(output) as image:
        dimensions = list(image.size)
    payload = {
        "provider": "gemini",
        "job_id": result.job_id,
        "requested_model": requested_model,
        "actual_model_label": receipt.get("actual_model_label"),
        "model_verified": bool(receipt.get("model_verified")),
        "pro_regeneration_used": bool(receipt.get("pro_regeneration_used")),
        "provider_receipt": receipt,
        "references": [
            {"role": ref.role, "path": str(Path(ref.path).relative_to(ROOT)), "sha256": sha256_file(ref.path)}
            for ref in references
        ],
        "prompt_sha256": sha256_text(prompt),
        "output_path": _receipt_path(project, output),
        "output_sha256": sha256_file(output),
        "output_dimensions": dimensions,
        "elapsed_seconds": result.elapsed_seconds,
        "completed_at": utcnow(),
    }
    path = project / "pipeline" / "provider_receipts" / f"{name}.json"
    save_json(path, payload)
    return path


def _write_video_receipt(
    project: Path,
    name: str,
    result: JobResult,
    prompt: str,
    references: list[Reference],
    output: Path,
    requested: Generation,
) -> Path:
    receipt = dict(result.generation_receipt or {})
    payload = {
        "provider": "flow",
        "job_id": result.job_id,
        "requested": {
            "model": requested.model,
            "resolution": requested.resolution,
            "aspect_ratio": requested.aspect_ratio,
            "duration_seconds": requested.duration_seconds,
        },
        "actual_model_label": receipt.get("actual_model_label"),
        "model_verified": bool(receipt.get("model_verified")),
        "duration_actual": receipt.get("actual_duration_seconds") or round(ffprobe_duration(output), 3),
        "resolution_actual": receipt.get("actual_resolution"),
        "aspect_actual": receipt.get("actual_aspect_ratio"),
        "reference_roles": receipt.get("reference_roles") or [ref.role for ref in references],
        "submission_fingerprint": receipt.get("submission_fingerprint"),
        "workspace_url": receipt.get("workspace_url"),
        "provider_receipt": receipt,
        "uploaded_roles": [ref.role for ref in references],
        "prompt_sha256": sha256_text(prompt),
        "output_file": _receipt_path(project, output),
        "output_sha256": sha256_file(output),
        "elapsed_seconds": result.elapsed_seconds,
        "completed_at": utcnow(),
    }
    path = project / "pipeline" / "provider_receipts" / f"{name}.json"
    save_json(path, payload)
    return path


def stage_visual_plan(
    runner: Runner,
    project: Path,
    content_project: Any,
    plan: dict[str, Any],
    episode_plan: dict[str, Any],
    world_style_plan: dict[str, Any],
    body_seconds: float,
) -> dict[str, Any]:
    stage = "visual_plan"
    target = project / "creative" / "VISUAL_PLAN.json"
    if runner.state.done(stage) and target.is_file():
        runner.stage_reused(stage, target.name)
        return load_json(target)
    started = runner.stage_start(stage)
    prompt = fill(
        resolve_prompt(content_project, "05_visual_beat_planner.md"),
        FINAL_SCRIPT=json.dumps(
            {"opening_question_spark": plan["opening_question_spark"],
             "book_transition": plan["book_transition"],
             "body": plan["body"],
             "optional_closing": plan["optional_closing"],
             "cta": plan["cta"]},
            ensure_ascii=False,
            indent=2,
        ),
        EPISODE_PLAN=json.dumps(episode_plan, ensure_ascii=False),
        WORLD_STYLE_PLAN=json.dumps(world_style_plan, ensure_ascii=False),
        VIDEO_BRIEF="aspect 9:16 vertical Short",
        BODY_DURATION_SECONDS=f"{body_seconds:.0f}",
    )
    def check(data: Any) -> dict[str, Any]:
        beats = data.get("beats") if isinstance(data, dict) else None
        if not isinstance(beats, list) or not beats:
            raise StageFailure(stage, "FAILED_VALIDATION", "The visual plan has no beats.")
        if len(beats) != len(plan["body"]):
            raise StageFailure(
                stage,
                "FAILED_VALIDATION",
                f"The visual plan has {len(beats)} beats but the narration has {len(plan['body'])} "
                "body segments; one beat must correspond to one segment or the images will not "
                "land on their own sentences.",
            )
        fingerprints = [str(item.get("visual_fingerprint") or "").strip().lower() for item in beats if isinstance(item, dict)]
        if len(fingerprints) != len(beats) or any(not value for value in fingerprints):
            raise StageFailure(stage, "FAILED_VALIDATION", "Every visual beat needs a non-empty visual_fingerprint.")
        if len(set(fingerprints)) != len(fingerprints):
            raise StageFailure(stage, "FAILED_VALIDATION", "Visual fingerprints repeat; assign every beat a genuinely different composition.")
        return data

    # One beat per narration segment is a hard rule, but a plan with the wrong count is a
    # correctable answer: it is sent back with the two counts named (§35, §57).
    data = ask_with_correction(
        runner,
        stage,
        prompt,
        check,
        hint=f"Return exactly {len(plan['body'])} beats, one per narration body segment, in order.",
    )
    beats = data["beats"]
    save_json(target, data)
    runner.stage_done(stage, started, f"{len(beats)} beats", beats=len(beats))
    return data


def stage_world_keyframe_prompt(
    runner: Runner,
    project: Path,
    content_project: Any,
    plan: dict[str, Any],
    episode_plan: dict[str, Any],
    world_style_plan: dict[str, Any],
    visual_plan: dict[str, Any],
) -> str:
    stage = "world_keyframe_prompt"
    target = project / "references" / "world_keyframe_prompt.txt"
    if runner.state.done(stage) and target.is_file():
        runner.stage_reused(stage, target.name)
        return target.read_text(encoding="utf-8")
    started = runner.stage_start(stage)
    # The keyframe writer needs the visual world's representative motifs, not the
    # full prose of every fast-cut body beat. Passing the complete 20–30 beat plan
    # exceeded Ordak's 20k request schema and failed before a job existed.
    keyframe_beats = list(visual_plan.get("beats") or [])
    representative = keyframe_beats[:3]
    if len(keyframe_beats) > 3:
        representative.append(keyframe_beats[len(keyframe_beats) // 2])
        representative.append(keyframe_beats[-1])
    compact_visual_plan = {
        "beat_count": len(keyframe_beats),
        "representative_beats": [
            {
                key: beat.get(key)
                for key in ("beat_id", "narration_slice", "visual", "purpose", "visual_fingerprint", "type")
            }
            for beat in representative
            if isinstance(beat, dict)
        ],
    }
    prompt = fill(
        resolve_prompt(content_project, "06_world_keyframe_prompt_writer.md"),
        FINAL_SCRIPT=plan["full_narration"],
        EPISODE_PLAN=json.dumps(episode_plan, ensure_ascii=False),
        WORLD_STYLE_PLAN=json.dumps(world_style_plan, ensure_ascii=False),
        VISUAL_PLAN=json.dumps(compact_visual_plan, ensure_ascii=False),
    )
    text = runner.text(stage, prompt)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.strip() + "\n", encoding="utf-8")
    runner.stage_done(stage, started, target.name, prompt_sha256=sha256_text(text))
    return text


def character_sheet_path(content_project: Any) -> Path:
    return (
        ROOT
        / "projects"
        / content_project.project_id
        / "visual_presets"
        / content_project.default_visual_preset
        / "character_sheet.png"
    )


def book_design_sheet_path(content_project: Any) -> Path:
    return (
        ROOT
        / "projects"
        / content_project.project_id
        / "visual_presets"
        / content_project.default_visual_preset
        / "book_design_sheet_v2.png"
    )


def stage_book_design_sheet(runner: Runner, project: Path, content_project: Any) -> Path:
    """The canonical book identity, generated once and then reused forever (§2, §47).

    Clip B sends this instead of the character sheet, because the book-transition shot is
    explicitly people-free — see the deviation recorded in IMPLEMENTATION_PLAN §3.5.
    """
    stage = "book_design_sheet"
    target = book_design_sheet_path(content_project)
    if valid_image(target):
        runner.stage_reused(stage, target.name)
        return target
    started = runner.stage_start(stage)
    # The identity file describes the object. The older path fed this stage the *clip B video*
    # prompt — a shot list with audio notes and one episode's subject named in it — which is why
    # the sheet came out as a scene rather than a clean, natural reference.
    reference_dir = ROOT / "projects" / content_project.project_id / "prompts" / "reference"
    reference_prompt = reference_dir / "book_identity.txt"
    if not reference_prompt.is_file():
        reference_prompt = reference_dir / "book_transition_reference_prompt.txt"
    if not reference_prompt.is_file():
        raise StageFailure(
            stage,
            "FAILED_VALIDATION",
            f"The locked book identity description is missing: {reference_dir / 'book_identity.txt'}",
        )
    identity = reference_prompt.read_text(encoding="utf-8")
    prompt = (
        "A premium hand-drawn object turnaround of the same antique storybook, 9:16 vertical. "
        "Split the frame into TWO large, equally clear product-reference views on a plain warm "
        "parchment backdrop: a CLOSED FRONT COVER in the upper half and a WIDE-OPEN TWO-PAGE "
        "SPREAD in the lower half. Both views must be fully visible, centred, large, and have the "
        "same proportions and binding. This is an object reference, not a scene: no people, no "
        "hands, no room, no props, no labels, no arrows, no writing.\n\n"
        "Locked identity, which must match exactly:\n"
        "- antique brown leather cover, softly worn at the edges\n"
        "- brass corner protectors on all four corners\n"
        "- a brass clasp on the fore-edge\n"
        "- an eye symbol centred on the cover, a crescent moon above it, small scattered stars\n"
        "- a thick block of aged, uneven pages\n"
        "- a green ribbon bookmark falling from the pages\n"
        "- no title, no lettering, no numbers, no extra symbols anywhere\n\n"
        "The OPEN view is mandatory and must visibly show two completely blank aged pages with "
        "a generous clean rectangular illustration area on the right page, warm paper grain, "
        "clean margins and a soft shadow along the inner spine. Leave both pages empty — an "
        "episode's illustration is composited onto the right page later, so any drawing or "
        "writing there would fight it.\n\n"
        "Style: refined 2D illuminated-storybook illustration, confident clean ink contours, "
        "rich but restrained chestnut leather, antique gold/brass with hand-painted highlights, "
        "subtle cel shading, warm parchment texture, elegant page deck and believable hand-drawn "
        "craftsmanship. It should feel like a beautifully illustrated heirloom reference from a "
        "premium educational adventure book, never generic clip-art. No 3D, CGI, photoreal leather "
        "or metal, lens effects, glowing magic, portal, text, diagrams, or watermark.\n\n"
        "The locked description this sheet must agree with:\n"
        f"{identity[:4000]}"
    )
    launch = load_json(project / "launch" / "LAUNCH_REQUEST.json")
    model = normalize_gemini_model(launch.get("image_generation", {}).get("model") or "nano_banana_2")
    result = runner.image(stage, prompt, [], model=model, destination=target)
    _write_image_receipt(project, "gemini_book_design_sheet", result, prompt, [], target, model)
    runner.stage_done(stage, started, str(target.relative_to(ROOT)), sha256=sha256_file(target))
    return target


def stage_world_keyframe(
    runner: Runner, project: Path, content_project: Any, prompt: str, world_style_anchor: Path
) -> Path:
    """The one image that defines the episode's world. Gemini only, verified, no substitute."""
    stage = "world_keyframe"
    target = project / "references" / "world_keyframe.png"
    receipt = project / "pipeline" / "provider_receipts" / "gemini_world_keyframe.json"
    if valid_image(target) and receipt.is_file() and runner.state.done(stage):
        runner.stage_reused(stage, target.name)
        return target
    started = runner.stage_start(stage)
    launch = load_json(project / "launch" / "LAUNCH_REQUEST.json")
    model = normalize_gemini_model(launch.get("image_generation", {}).get("model") or "nano_banana_2")

    # §30 reference order: the recurring identity first, then the style, then continuity.
    references: list[Reference] = []
    character = character_sheet_path(content_project)
    if valid_image(character):
        references.append(Reference(role="character_sheet", path=character))
    if valid_image(world_style_anchor):
        references.append(Reference(role="style_reference", path=world_style_anchor))

    result = runner.image(stage, prompt, references, model=model, destination=target)
    _write_image_receipt(project, "gemini_world_keyframe", result, prompt, references, target, model)
    runner.stage_done(stage, started, target.name, sha256=sha256_file(target), model=model)
    return target


def stage_book_spread(runner: Runner, project: Path, world_keyframe: Path, episode_plan: dict[str, Any]) -> Path:
    """Composite the world keyframe onto a book page — the Start frame for Clip B."""
    stage = "book_spread"
    target = project / "references" / "book_spread_frame.png"
    if valid_image(target) and runner.state.done(stage):
        runner.stage_reused(stage, target.name)
        return target
    started = runner.stage_start(stage)
    from compose_book_spread import compose

    template_id = str(episode_plan.get("book_template_id") or "001")
    template_path = BOOK_TEMPLATES_ROOT / template_id / "blank_book.png"
    if not template_path.is_file():
        raise StageFailure(
            stage,
            "FAILED_VALIDATION",
            f"Book template {template_id!r} has no blank_book.png at {template_path}. "
            "The compositor never draws a stand-in book, so this must be fixed in the catalog.",
        )
    seed = int(hashlib.sha256((str(project) + template_id).encode()).hexdigest()[:8], 16) % 100_000
    meta = compose(
        world_keyframe=world_keyframe,
        output=target,
        template_id=template_id,
        seed=seed,
        aspect_ratio="9:16",
        template_path=template_path,
    )
    save_json(project / "creative" / "BOOK_SPREAD_META.json", meta)
    runner.stage_done(stage, started, target.name, template_id=template_id, sha256=meta["sha256"])
    return target


def stage_flow_prompt(
    runner: Runner,
    project: Path,
    content_project: Any,
    clip: str,
    narration: str,
    episode_plan: dict[str, Any],
    world_style_plan: dict[str, Any],
    world_keyframe_description: str,
    topic: str,
    source_seconds: int,
) -> str:
    """Every Flow prompt comes from ChatGPT; none of them is hardcoded (§194)."""
    stage = f"flow_prompt_{'a' if clip == 'A' else 'b'}"
    target = project / "references" / f"flow_prompt_{'opening_a' if clip == 'A' else 'book_transition'}.txt"
    if runner.state.done(stage) and target.is_file():
        runner.stage_reused(stage, target.name)
        return target.read_text(encoding="utf-8")
    started = runner.stage_start(stage)
    if clip == "A":
        prompt = fill(
            resolve_prompt(content_project, "08_opening_video_prompt_writer.md"),
            OPENING_A_NARRATION=narration,
            EPISODE_PLAN=json.dumps(episode_plan, ensure_ascii=False),
            WORLD_STYLE_PLAN=json.dumps(world_style_plan, ensure_ascii=False),
        )
    else:
        prompt = fill(
            resolve_prompt(content_project, "09_book_transition_video_prompt_writer.md"),
            BOOK_TRANSITION_NARRATION=narration,
            EPISODE_PLAN=json.dumps(episode_plan, ensure_ascii=False),
            TOPIC=topic,
            WORLD_STYLE_PLAN=json.dumps(world_style_plan, ensure_ascii=False),
            WORLD_KEYFRAME_DESC=world_keyframe_description,
            SOURCE_DURATION_SECONDS=str(source_seconds),
        )
    text = runner.text(stage, prompt)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.strip() + "\n", encoding="utf-8")
    runner.stage_done(stage, started, target.name, prompt_sha256=sha256_text(text))
    return text


def stage_flow_clip(
    runner: Runner,
    project: Path,
    content_project: Any,
    clip: str,
    prompt: str,
    *,
    book_spread: Path | None,
    world_keyframe: Path | None,
    model: str,
    resolution: str,
    aspect_ratio: str,
    source_seconds: int,
) -> Path:
    """Generate one Flow clip with the references its role contract allows.

    The source is generated one second longer than the planned narration segment so the
    measured trim has headroom (§67 step 5). Nothing here retries a failed generation: a Flow
    retry spends credits, so recovery is the worker's reconciliation path, not a loop here.
    """
    stage = f"flow_clip_{clip.lower()}"
    filename = "question_spark_source.mp4" if clip == "A" else "book_transition_source.mp4"
    receipt_name = "flow_opening_a" if clip == "A" else "flow_opening_b"
    target = project / "assets" / "opening" / filename
    receipt = project / "pipeline" / "provider_receipts" / f"{receipt_name}.json"
    if valid_video(target) and receipt.is_file() and runner.state.done(stage):
        runner.stage_reused(stage, f"{filename} ({ffprobe_duration(target):.2f}s)")
        return target
    started = runner.stage_start(stage)

    if clip == "A":
        uploads = build_flow_uploads(clip="A", character_sheet=character_sheet_path(content_project))
    else:
        uploads = build_flow_uploads(
            clip="B",
            book_spread_frame=book_spread,
            world_keyframe=world_keyframe,
        )
    references = [Reference(role=role, path=path) for role, path in uploads]

    requested = Generation(
        model=model,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        duration_seconds=source_seconds,
    )
    result = runner.video(
        stage,
        prompt,
        references,
        model=model,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        duration_seconds=source_seconds,
        destination=target,
    )
    _write_video_receipt(project, receipt_name, result, prompt, references, target, requested)
    duration = ffprobe_duration(target)
    runner.stage_done(
        stage,
        started,
        f"{filename} {duration:.2f}s roles={[ref.role for ref in references]}",
        duration_seconds=round(duration, 3),
        roles=[ref.role for ref in references],
        sha256=sha256_file(target),
    )
    return target


def _beat_reference_stack(
    content_project: Any,
    beat: dict[str, Any],
    world_style_anchor: Path,
    world_keyframe: Path,
    previous: Path | None,
) -> list[Reference]:
    """§30 reference order: identity, style, world, then texture-only continuity.

    The character sheet is only sent when the hero is actually in the shot — sending it for a
    hero-free beat is how a character drifts into scenes that should not contain one.
    """
    references: list[Reference] = []
    character = character_sheet_path(content_project)
    if beat.get("hero_present", True) and valid_image(character):
        references.append(Reference(role="character_sheet", path=character))
    if valid_image(world_style_anchor):
        references.append(Reference(role="style_reference", path=world_style_anchor))
    if valid_image(world_keyframe):
        references.append(Reference(role="world_keyframe", path=world_keyframe))
    if previous is not None and valid_image(previous):
        references.append(Reference(role="previous_beat", path=previous))
    return references


def stage_beat_prompt(
    runner: Runner,
    project: Path,
    content_project: Any,
    beat: dict[str, Any],
    world_style_plan: dict[str, Any],
    references: list[Reference],
) -> str:
    beat_id = int(beat["beat_id"])
    target = project / "beats" / f"BEAT_{beat_id:03d}_PROMPT.md"
    if target.is_file() and target.read_text(encoding="utf-8").strip():
        return target.read_text(encoding="utf-8")
    stage = f"beat_prompt_{beat_id:03d}"
    preset_readme = (
        ROOT
        / "projects"
        / content_project.project_id
        / "visual_presets"
        / content_project.default_visual_preset
        / "README.md"
    )
    if not preset_readme.is_file():
        raise StageFailure(stage, "FAILED_VALIDATION", f"Style rules are missing: {preset_readme}")
    prompt = fill(
        resolve_prompt(content_project, "07_single_beat_image_prompt_writer.md"),
        STYLE_RULES=preset_readme.read_text(encoding="utf-8"),
        WORLD_STYLE_PLAN=json.dumps(world_style_plan, ensure_ascii=False),
        VISUAL_BEAT=json.dumps(beat, ensure_ascii=False),
        REFERENCE_IMAGES=", ".join(ref.role for ref in references) or "none",
        PREVIOUS_BEAT=(
            "No previous image — establish the world's texture and palette from the canonical anchors."
            if not any(ref.role == "previous_beat" for ref in references)
            else "Previous image is supplied only for texture, palette, lighting continuity, and world material. "
            "Never copy its composition, crop, camera angle, pose, subject placement, or focal object."
        ),
        ASPECT_RATIO="9:16",
    )
    text = runner.text(stage, prompt)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.strip() + "\n", encoding="utf-8")
    return text


def stage_body_images(
    runner: Runner,
    project: Path,
    content_project: Any,
    visual_plan: dict[str, Any],
    world_style_plan: dict[str, Any],
    world_style_anchor: Path,
    world_keyframe: Path,
    regenerate_beats: set[int] | None = None,
) -> list[Path]:
    """One Gemini image per body beat, sequential because each uses the previous for continuity."""
    beats = list(visual_plan.get("beats") or [])
    requested_regenerations = regenerate_beats or set()
    unknown_regenerations = requested_regenerations - {int(beat["beat_id"]) for beat in beats}
    if unknown_regenerations:
        raise StageFailure(
            "body_images",
            "FAILED_VALIDATION",
            f"Requested regeneration for unknown beat IDs: {sorted(unknown_regenerations)}.",
        )
    output_dir = project / "assets" / "raw_beats"
    output_dir.mkdir(parents=True, exist_ok=True)
    launch = load_json(project / "launch" / "LAUNCH_REQUEST.json")
    model = normalize_gemini_model(launch.get("image_generation", {}).get("model") or "nano_banana_2")

    batch_started = runner.stage_start("body_images")
    produced: list[Path] = []
    previous: Path | None = None
    try:
        for beat in beats:
            beat_id = int(beat["beat_id"])
            stage = f"beat_image_{beat_id:03d}"
            target = output_dir / f"beat_{beat_id:03d}.png"

            if valid_image(target) and beat_id not in requested_regenerations:
                runner.state.mark(stage, STATE_REUSED, artifact=target.name)
                print(f"↻ {stage} reused — {target.name}", flush=True)
                produced.append(target)
                previous = target
                runner.stage_progress("body_images", ["🖼️ Image batch in progress", f"📍 Progress: {len(produced)}/{len(beats)} images", "↻ Existing image reused"])
                continue

            started = time.perf_counter()
            runner.state.mark(stage, STATE_RUNNING)
            print(f"▶ {stage}", flush=True)
            references = _beat_reference_stack(content_project, beat, world_style_anchor, world_keyframe, previous)
            prompt = stage_beat_prompt(runner, project, content_project, beat, world_style_plan, references)
            result = runner.image(stage, prompt, references, model=model, destination=target)
            _write_image_receipt(project, f"gemini_beat_{beat_id:03d}", result, prompt, references, target, model)
            elapsed = time.perf_counter() - started
            runner.state.mark(stage, STATE_DONE, sha256=sha256_file(target), references=[ref.role for ref in references])
            runner.state.record(stage, STATE_DONE, elapsed, sha256=sha256_file(target), references=[ref.role for ref in references])
            print(f"✔ {stage} ({elapsed:.1f}s) — {target.name}", flush=True)
            produced.append(target)
            previous = target
            runner.stage_progress("body_images", ["🖼️ Image batch in progress", f"📍 Progress: {len(produced)}/{len(beats)} images", f"⏱ Latest image: {format_duration(elapsed)}"])
    except StageFailure as exc:
        raise StageFailure("body_images", exc.state, f"Body image batch stopped: {exc.message}", error_code=exc.error_code) from exc

    if len(produced) != len(beats):
        raise StageFailure(
            "body_images",
            "FAILED_VALIDATION",
            f"{len(produced)} of {len(beats)} body images were produced.",
        )
    runner.stage_done("body_images", batch_started, f"{len(produced)}/{len(beats)} unique images")
    return produced


TRANSITION_EDITOR_TYPES = {
    "fade", "dissolve", "fadeblack", "fadewhite", "smoothleft", "smoothright", "smoothup", "smoothdown",
    "wipeleft", "wiperight", "wipeup", "wipedown", "wipetl", "wipetr", "wipebl", "wipebr",
    "slideleft", "slideright", "slideup", "slidedown", "radial", "circleopen", "circleclose", "zoomin",
    "hblur", "distance", "diagtl", "diagtr", "diagbl", "diagbr", "coverleft", "coverright", "coverup",
    "coverdown", "revealleft", "revealright", "revealup", "revealdown",
}
TRANSITION_EDITOR_MOTIONS = {"still", "slow_zoom_in", "slow_zoom_out", "zoom_in", "zoom_out"}


def stage_transition_direction(
    runner: Runner,
    project: Path,
    content_project: Any,
    visual_plan: dict[str, Any],
    images: list[Path],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Let ChatGPT inspect adjacent rendered images and make semantic edit decisions.

    The stage owns one Telegram message even though each boundary is an individual Ordak chat
    request. Sending exactly the two adjacent images gives the editor visual context without
    turning a twenty-image request into an unreliable, uninspectable collage.
    """
    stage = "transition_direction"
    target = project / "creative" / "TRANSITION_PLAN.json"
    beats = list(visual_plan.get("beats") or [])
    if len(beats) != len(images):
        raise StageFailure(stage, "FAILED_VALIDATION", "Transition editor needs one accepted image for every visual beat.")
    if not force and runner.state.done(stage) and target.is_file():
        runner.stage_reused(stage, target.name)
        return load_json(target)

    started = runner.stage_start(stage)
    decisions: list[dict[str, Any]] = []
    previous_transition = ""
    for index in range(1, len(beats)):
        previous, current = beats[index - 1], beats[index]
        prompt = fill(
            resolve_prompt(content_project, "10_transition_editor.md"),
            PREVIOUS_BEAT=json.dumps(previous, ensure_ascii=False),
            NEXT_BEAT=json.dumps(current, ensure_ascii=False),
        )
        raw = runner.json(
            f"{stage}_{index:03d}", prompt,
            references=[
                Reference(role="previous_beat_for_edit", path=images[index - 1]),
                Reference(role="next_beat_for_edit", path=images[index]),
            ],
        )
        transition = str(raw.get("transition_in") or "").lower().strip() if isinstance(raw, dict) else ""
        motion = str(raw.get("next_motion") or "").lower().strip() if isinstance(raw, dict) else ""
        try:
            seconds = float(raw.get("transition_seconds")) if isinstance(raw, dict) else 0.0
        except (TypeError, ValueError):
            seconds = 0.0
        if transition not in TRANSITION_EDITOR_TYPES or motion not in TRANSITION_EDITOR_MOTIONS or not 0.14 <= seconds <= 0.42:
            raise StageFailure(stage, "FAILED_VALIDATION", f"Transition editor returned an unsupported decision for boundary {index}->{index + 1}.")
        if transition == previous_transition and transition not in {"fade", "dissolve"}:
            # A repeated flashy effect is editorially arbitrary. Ask once with an explicit repair.
            repair = prompt + f"\n\nYour previous boundary used {transition!r}. Choose a different restrained transition; return the same JSON."
            raw = runner.json(
                f"{stage}_{index:03d}_repair", repair,
                references=[Reference(role="previous_beat_for_edit", path=images[index - 1]), Reference(role="next_beat_for_edit", path=images[index])],
            )
            transition = str(raw.get("transition_in") or "").lower().strip() if isinstance(raw, dict) else ""
            motion = str(raw.get("next_motion") or "").lower().strip() if isinstance(raw, dict) else ""
            seconds = float(raw.get("transition_seconds") or 0.0) if isinstance(raw, dict) else 0.0
            if transition not in TRANSITION_EDITOR_TYPES or motion not in TRANSITION_EDITOR_MOTIONS or not 0.14 <= seconds <= 0.42:
                raise StageFailure(stage, "FAILED_VALIDATION", f"Transition editor repair was invalid for boundary {index}->{index + 1}.")
        decision = {
            "from_beat_id": int(previous["beat_id"]), "to_beat_id": int(current["beat_id"]),
            "transition_in": transition, "transition_seconds": round(seconds, 3), "next_motion": motion,
            "reason": str(raw.get("reason") or "").strip()[:400],
        }
        decisions.append(decision)
        previous_transition = transition
        runner.stage_progress(stage, ["🎞️ Picture edit in progress", f"📍 Boundaries: {len(decisions)}/{len(beats) - 1}", f"✦ Latest: {transition} · {seconds:.2f}s · {motion}"])
    payload = {"schema_version": 1, "decisions": decisions, "created_at": utcnow()}
    save_json(target, payload)
    runner.stage_done(stage, started, f"{len(decisions)} image boundaries", boundaries=len(decisions))
    return payload


# --------------------------------------------------------------------------- workspace


def ensure_launch_request(
    project: Path,
    content_project_id: str,
    gemini_model: str,
    flow_model: str,
    flow_resolution: str,
    opening_a_seconds: int,
    opening_b_seconds: int,
    duration: "DurationTarget",
    style_policy: str,
    style_id: str,
    style_hint: str,
) -> dict[str, Any]:
    """The immutable launch contract (§59, §79). An existing file is never rewritten."""
    path = project / "launch" / "LAUNCH_REQUEST.json"
    if path.is_file():
        return load_json(path)
    data = {
        "schema_version": 3,
        "content_project": content_project_id,
        "created_at": utcnow(),
        "providers": {"text": "chatgpt", "image": "gemini", "video": "flow", "voice": "elevenlabs_web"},
        "image_generation": {"model": normalize_gemini_model(gemini_model), "quality": "best"},
        "video_generation": {
            "model": normalize_flow_model(flow_model),
            "resolution": flow_resolution,
            "opening_a_source_seconds": opening_a_seconds,
            "opening_b_source_seconds": opening_b_seconds,
            "outputs": "x1",
            "flow_style_sheet_upload": False,
        },
        "episode": {
            "min_duration_seconds": duration.min_seconds,
            "max_duration_seconds": duration.max_seconds,
            "word_range": duration.word_range,
        },
        "world_style": {
            "policy": style_policy,
            "requested_style_id": style_id or None,
            "hint": style_hint or None,
        },
        "project": str(project.relative_to(ROOT)),
    }
    save_json(path, data)
    return data


def write_visual_beats_markdown(project: Path, plan: dict[str, Any], visual_plan: dict[str, Any]) -> Path:
    """VISUAL_BEATS.md is what align_beats.py reads, so it must carry the spoken words."""
    lines = ["# Visual Beats", ""]
    for beat, narration in zip(visual_plan.get("beats") or [], plan["body"]):
        lines += [
            f"### Beat {int(beat['beat_id'])}",
            "",
            "Narration:",
            narration.strip(),
            "",
            "Visual:",
            str(beat.get("visual") or "").strip(),
            "",
        ]
    path = project / "VISUAL_BEATS.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_brief(
    project: Path, topic: str, content_project: Any, duration: DurationTarget
) -> str:
    brief_path = project / "launch" / "CREATIVE_BRIEF.json"
    brief_json = brief_path.read_text(encoding="utf-8") if brief_path.is_file() else "{}"
    return (
        f"Topic: {topic}\n"
        "Language: English\n"
        f"Target: {duration.duration_range} vertical Short, aspect 9:16 "
        f"({duration.word_range} spoken words, aim near {duration.word_target})\n"
        f"Content project: {content_project.display_name}\n"
        f"Brief JSON: {brief_json}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Question Harvest pipeline (production path)")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--content-project", default="question_harvest")
    parser.add_argument("--creative-brief", type=Path, default=None)
    parser.add_argument("--voice-profile", type=Path, default=None)
    parser.add_argument(
        "--gemini-model",
        default="nano_banana_2",
        help=(
            "Gemini image model to verify against the UI. Gemini currently names only "
            "Nano Banana 2 in its image composer, so nano_banana_pro fails with "
            "MODEL_NOT_AVAILABLE rather than running on a model nobody asked for."
        ),
    )
    parser.add_argument("--flow-model", default="gemini_omni_1_1_flash")
    parser.add_argument("--flow-resolution", default="720p")
    parser.add_argument("--aspect-ratio", default="9:16")
    parser.add_argument(
        "--opening-a-seconds",
        type=int,
        default=6,
        help="Flow source length for Clip A; one second of headroom over the planned segment.",
    )
    parser.add_argument("--opening-b-seconds", type=int, default=4)
    parser.add_argument(
        "--min-duration-seconds",
        type=float,
        default=40.0,
        help="Shortest acceptable episode length; the script prompts are written for it.",
    )
    parser.add_argument(
        "--max-duration-seconds",
        type=float,
        default=60.0,
        help="Longest acceptable episode length.",
    )
    parser.add_argument(
        "--world-style-policy",
        default="auto",
        choices=("auto", "reuse", "new"),
        help="auto lets the director choose; reuse forbids a new style; new forbids reuse.",
    )
    parser.add_argument(
        "--world-style-id",
        default="",
        help=(
            "Reuse this catalogued style_id instead of letting the director pick. "
            "Implies --world-style-policy reuse."
        ),
    )
    parser.add_argument(
        "--world-style-hint",
        default="",
        help="Free-text steer for a new style, e.g. 'charcoal warm paper'.",
    )
    parser.add_argument(
        "--regenerate-beats",
        default="",
        help="Comma-separated body beat IDs to regenerate even when their existing files are valid (for example: 1,9,13).",
    )
    args = parser.parse_args()
    if args.min_duration_seconds > args.max_duration_seconds:
        parser.error("--min-duration-seconds cannot exceed --max-duration-seconds")
    try:
        regenerate_beats = {
            int(part.strip()) for part in str(args.regenerate_beats).split(",") if part.strip()
        }
    except ValueError:
        parser.error("--regenerate-beats must contain only comma-separated positive integer beat IDs")
    if any(beat_id < 1 for beat_id in regenerate_beats):
        parser.error("--regenerate-beats must contain only positive beat IDs")

    load_dotenv(ROOT / os.getenv("YT_ENV_FILE", ".env"), override=False)

    content_project = load_content_project(args.content_project)
    validate_provider_locks(content_project)
    validate_content_project(content_project)

    project = ROOT / "videos" / f"{args.video_id}_{video_slug(args.topic)}"
    project.mkdir(parents=True, exist_ok=True)
    (project / "PROJECT.md").write_text(
        f"# Content Project\n\nProject: `{content_project.project_id}`\n", encoding="utf-8"
    )

    brief_target = project / "launch" / "CREATIVE_BRIEF.json"
    brief_target.parent.mkdir(parents=True, exist_ok=True)
    if args.creative_brief and Path(args.creative_brief).is_file():
        if Path(args.creative_brief).resolve() != brief_target.resolve():
            shutil.copy(str(args.creative_brief), str(brief_target))
    elif not brief_target.is_file():
        save_json(brief_target, {"topic": args.topic})

    if args.voice_profile and Path(args.voice_profile).is_file():
        voice_target = project / "voiceover" / "REQUESTED_VOICE_PROFILE.json"
        voice_target.parent.mkdir(parents=True, exist_ok=True)
        if Path(args.voice_profile).resolve() != voice_target.resolve():
            shutil.copy(str(args.voice_profile), str(voice_target))

    duration = DurationTarget(float(args.min_duration_seconds), float(args.max_duration_seconds))
    requested_style_id = str(args.world_style_id or "").strip()
    style_policy = "reuse" if requested_style_id else str(args.world_style_policy)
    directive = style_directive(style_policy, requested_style_id, args.world_style_hint)
    if requested_style_id:
        catalogued = {
            str(entry.get("style_id"))
            for entry in (load_json(WORLD_STYLES_ROOT / "CATALOG.json").get("styles") or [])
        } if (WORLD_STYLES_ROOT / "CATALOG.json").is_file() else set()
        if requested_style_id not in catalogued:
            print(
                f"FAILED_VALIDATION: world style {requested_style_id!r} is not in "
                f"projects/{args.content_project}/world_styles/CATALOG.json "
                f"(known: {sorted(catalogued)}).",
                file=sys.stderr,
                flush=True,
            )
            return 2

    launch = ensure_launch_request(
        project,
        args.content_project,
        args.gemini_model,
        args.flow_model,
        args.flow_resolution,
        args.opening_a_seconds,
        args.opening_b_seconds,
        duration,
        style_policy,
        requested_style_id,
        args.world_style_hint,
    )
    state = QHState(project, args.video_id, args.topic)
    notifier = PipelineNotifier(video_id=args.video_id, topic=args.topic)

    video_generation = launch.get("video_generation", {})
    flow_model = normalize_flow_model(video_generation.get("model") or args.flow_model)
    flow_resolution = str(video_generation.get("resolution") or args.flow_resolution)
    opening_a_seconds = int(video_generation.get("opening_a_source_seconds") or args.opening_a_seconds)
    opening_b_seconds = int(video_generation.get("opening_b_source_seconds") or args.opening_b_seconds)

    with OrdakJobs() as jobs:
        runner = Runner(jobs, notifier, state)
        current_stage = "preflight"
        try:
            # Fail before spending anything if the browser stack is not usable (§65).
            jobs.require_ready(["chatgpt", "gemini", "flow"])
            brief = build_brief(project, args.topic, content_project, duration)

            draft = stage_script(runner, project, content_project, brief, duration)
            plan = stage_retention(runner, project, content_project, brief, draft, duration)
            episode_plan = stage_episode_director(runner, project, content_project, args.topic, brief, plan)
            world_style_plan = stage_world_style_director(
                runner, project, content_project, args.topic, plan, episode_plan, directive
            )
            if requested_style_id and str(world_style_plan.get("style_id") or "") != requested_style_id:
                raise StageFailure(
                    "world_style_director",
                    "FAILED_VALIDATION",
                    f"The operator asked for style {requested_style_id!r} but the director "
                    f"answered {world_style_plan.get('style_id')!r}.",
                )
            world_style_anchor = stage_world_style_anchor(runner, project, content_project, world_style_plan)
            stage_record_history(runner, content_project, args.video_id, episode_plan, world_style_plan)

            body_seconds = max(20.0, plan["word_count"] * 0.42 - (opening_a_seconds + opening_b_seconds))
            visual_plan = stage_visual_plan(
                runner, project, content_project, plan, episode_plan, world_style_plan, body_seconds
            )
            write_visual_beats_markdown(project, plan, visual_plan)

            keyframe_prompt = stage_world_keyframe_prompt(
                runner, project, content_project, plan, episode_plan, world_style_plan, visual_plan
            )
            world_keyframe = stage_world_keyframe(
                runner, project, content_project, keyframe_prompt, world_style_anchor
            )
            stage_book_design_sheet(runner, project, content_project)
            book_spread = stage_book_spread(runner, project, world_keyframe, episode_plan)

            clip_a_prompt = stage_flow_prompt(
                runner, project, content_project, "A", plan["opening_question_spark"],
                episode_plan, world_style_plan, keyframe_prompt, args.topic, opening_a_seconds,
            )
            clip_b_prompt = stage_flow_prompt(
                runner, project, content_project, "B", plan["book_transition"],
                episode_plan, world_style_plan, keyframe_prompt, args.topic, opening_b_seconds,
            )

            # The body images depend only on the plan, the style anchor and the world
            # keyframe, so they run before the Flow clips. Flow is the stage most likely to
            # be unavailable for reasons outside this host — quota, high demand, or a
            # regional block — and doing the image work first means an outage there costs a
            # resume rather than the whole visual half.
            body_images = stage_body_images(
                runner, project, content_project, visual_plan, world_style_plan,
                world_style_anchor, world_keyframe, regenerate_beats,
            )
            stage_transition_direction(
                runner,
                project,
                content_project,
                visual_plan,
                body_images,
                force=bool(regenerate_beats),
            )

            clip_a = stage_flow_clip(
                runner, project, content_project, "A", clip_a_prompt,
                book_spread=None, world_keyframe=None,
                model=flow_model, resolution=flow_resolution, aspect_ratio=args.aspect_ratio,
                source_seconds=opening_a_seconds,
            )
            clip_b = stage_flow_clip(
                runner, project, content_project, "B", clip_b_prompt,
                book_spread=book_spread, world_keyframe=world_keyframe,
                model=flow_model, resolution=flow_resolution, aspect_ratio=args.aspect_ratio,
                source_seconds=opening_b_seconds,
            )

            state.mark("qh_visual_complete", STATE_DONE, body_images=len(body_images))
            state.finish()
            summary = [
                f"🎬 Clip A: {clip_a.name} ({ffprobe_duration(clip_a):.2f}s)",
                f"🎬 Clip B: {clip_b.name} ({ffprobe_duration(clip_b):.2f}s)",
                f"🖼 Body images: {len(body_images)}",
                f"📝 Narration: {plan['word_count']} words",
            ]
            print("\n".join(summary), flush=True)
            print(f"Project: {project}", flush=True)
            print("NEXT: narration → align_beats.py → trim_opening_clips.py → build_timeline.py → render_video.py", flush=True)
            return 0
        except StageFailure as failure:
            current_stage = failure.stage or current_stage
            runner.stage_failed(current_stage, failure, time.perf_counter())
            print(f"PIPELINE {failure.state}: {failure.message}", file=sys.stderr, flush=True)
            return 3 if failure.needs_human else 2
        except OrdakJobError as exc:
            failure = StageFailure(current_stage, exc.pipeline_state, exc.message, error_code=exc.error_code)
            runner.stage_failed(current_stage, failure, time.perf_counter())
            print(f"PIPELINE {failure.state}: {failure.message}", file=sys.stderr, flush=True)
            return 3 if failure.needs_human else 2


if __name__ == "__main__":
    sys.exit(main())

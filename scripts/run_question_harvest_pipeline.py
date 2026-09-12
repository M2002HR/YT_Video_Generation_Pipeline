#!/usr/bin/env python3
"""Q Station — the bookworld mixed-media pipeline (§57), production path only.

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
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from content_projects import (  # noqa: E402
    character_registry_path,
    load_content_project,
    normalize_flow_model,
    normalize_gemini_model,
    validate_content_project,
    validate_provider_locks,
    video_slug,
)
from character_runtime import (  # noqa: E402
    CharacterContext,
    CharacterResolution,
    load_character_registry,
    parse_character_request,
    resolve_character,
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
from image_artifacts import CONTRACT_VERSION, receipt_status, request_fingerprint

# Initialized from the resolved project in main. Kept as module globals for compatibility
# with existing helpers/tests that monkeypatch catalog roots.
WORLD_STYLES_ROOT = ROOT / "projects" / "q_station" / "world_styles"
BOOK_TEMPLATES_ROOT = ROOT / "projects" / "q_station" / "book_templates"
# Ordak's typed request schema permits 20,000 characters. Keep a small safety
# margin so a future prompt expansion cannot become an opaque HTTP 500 before a
# job is even recorded.
ORDAK_QUESTION_LIMIT = 19_000

MIN_IMAGE_BYTES = 10_000
MIN_VIDEO_BYTES = 100_000


# Image review is a production safety gate, not an aesthetic taste gate. Gemini images
# routinely have small presentational defects which a human can review later and which
# should not discard a paid-for, otherwise usable image.
_IMAGE_QC_BLOCKING_MARKERS = (
    "wrong subject", "incorrect subject", "subject is wrong", "main subject is absent",
    "main subject is missing", "requested subject is missing", "does not contain the requested subject",
    "not a scene", "character turnaround", "palette sheet", "grid instead of", "wrong output type",
    "entirely blank", "completely blank", "no usable image", "recurring host is present",
    "selected host is present", "foreground person is present", "foreground character is present",
    "character identity drift", "canonical character mismatch", "wrong character appearance",
    "style continuity drift", "canonical style mismatch", "recurring style mismatch",
)


def _is_blocking_image_qc_violation(violation: str) -> bool:
    """Whether a reviewer finding makes the image fundamentally unusable."""
    text = violation.casefold()
    return any(marker in text for marker in _IMAGE_QC_BLOCKING_MARKERS)


def assess_image_content_qc(check: Any) -> tuple[dict[str, Any], list[str]]:
    """Normalize a visual-QC response into an acceptance decision and warnings.

    ``passed`` in the returned receipt means accepted by the pipeline. The original
    reviewer decision remains in the receipt for later human review.
    """
    if not isinstance(check, dict) or not isinstance(check.get("passed"), bool):
        raise ValueError("Image content QC must return an object with boolean passed.")
    description = check.get("description")
    violations = check.get("violations")
    if not isinstance(description, str) or not description.strip() or not isinstance(violations, list):
        raise ValueError("Image content QC must include a description and violations array.")
    if not all(isinstance(item, str) and item.strip() for item in violations):
        raise ValueError("Image content QC violations must be non-empty strings.")

    declared = check.get("blocking_violations", [])
    if declared is None:
        declared = []
    if not isinstance(declared, list) or not all(isinstance(item, str) and item.strip() for item in declared):
        raise ValueError("Image content QC blocking_violations must be an array of non-empty strings.")
    regressions = check.get("regressions", [])
    if regressions is None:
        regressions = []
    if not isinstance(regressions, list) or not all(isinstance(item, str) and item.strip() for item in regressions):
        raise ValueError("Image content QC regressions must be an array of non-empty strings.")
    # The reviewer can suggest a severity, but the pipeline owns the stop decision.
    # This prevents an over-cautious model from turning a label or a minor composition
    # issue into a blocking finding merely by placing it in blocking_violations.
    reported = [*declared, *violations]
    blocking = list(dict.fromkeys(item for item in reported if _is_blocking_image_qc_violation(item)))
    if check["passed"] is False and not violations:
        raise ValueError("Image content QC rejected the image without explaining why.")

    warnings = list(dict.fromkeys([
        *(item for item in violations if item not in blocking),
        *(item for item in regressions if item not in blocking),
    ]))
    normalized = dict(check)
    normalized["raw_passed"] = check["passed"]
    normalized["raw_violations"] = list(violations)
    normalized["blocking_violations"] = blocking
    normalized["observations"] = warnings
    normalized["regressions"] = list(regressions)
    normalized["passed"] = not blocking
    normalized["review_status"] = "passed" if not warnings else "passed_with_warnings"
    return normalized, warnings


def episode_frame_contract(world_style_plan: dict[str, Any]) -> str:
    """A non-negotiable layout contract appended to every Gemini still prompt.

    Prompt writers describe each narrative scene independently, which used to let a later
    image silently drop the page/card material that made earlier frames feel like one world.
    This compact instruction travels with the final image request as well as the writer prompt.
    """
    frame = str(world_style_plan.get("frame_language") or "the chosen medium's recurring outer material, edge treatment and inner illustration window").strip()
    if not bool(world_style_plan.get("reserve_subtitle_space", True)):
        return (
            "NON-NEGOTIABLE EPISODE FRAME CONTRACT: Preserve this recurring frame language in this "
            f"image: {frame}. Preserve its material/edge grammar, texture, palette and inner "
            "illustration window while changing only the scene inside it. Do not reserve a lower "
            "caption field, blank strip, empty panel or low-detail band. Continue the scene and its "
            "natural texture through the full usable height, guided by the previous accepted image, "
            "without adding text, letters, numbers, captions, labels, words or UI."
        )
    reserve = str(world_style_plan.get("subtitle_reserve") or "a calm lower caption field occupying only the bottom 8–10% of the frame, enough for two subtitle lines").strip()
    return (
        "NON-NEGOTIABLE EPISODE FRAME CONTRACT: Preserve this recurring frame language in this "
        f"image: {frame}. Preserve its material/edge grammar and inner illustration window while "
        "changing only the scene inside it. Keep "
        f"{reserve}; keep faces, hands, focal action and critical details above it. "
        "The reserve must stay completely free of any text, letters, numbers, captions, labels, words or UI — leave it as calm texture/atmosphere only, never an oversized empty banner or a UI panel."
    )


def caption_layout_rule(world_style_plan: dict[str, Any]) -> str:
    if bool(world_style_plan.get("reserve_subtitle_space", True)):
        return (
            "Reserve a calm, low-detail caption field inside only the bottom 8–10% of the image, "
            "enough for two subtitle lines. Keep faces, hands, focal action and critical details "
            "above it. Continue the established material and texture through this quiet field; it "
            "must contain no text and must never look like a banner or UI panel."
        )
    return (
        "Do not reserve any lower caption field, blank strip, empty panel or low-detail band. "
        "Use the full illustration height for a naturally composed continuation of the scene, "
        "matching the previous accepted image's frame material, texture, palette and lighting."
    )


# ------------------------------------------------------------------ state machine (§81)

#: The only states a stage may hold. There is deliberately no FALLBACK_* state.
STATE_PENDING = "PENDING"
STATE_RUNNING = "RUNNING"
STATE_DONE = "DONE"
STATE_REUSED = "REUSED"
PAUSE_STATES = ("PAUSED_LOGIN_REQUIRED", "PAUSED_MANUAL_VERIFICATION", "PAUSED_CREDITS", "ACTION_REQUIRED")


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
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


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
            image.load()
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


def repair_unescaped_json_string_quotes(text: str) -> str:
    """Conservatively escape prose quotes that make an otherwise JSON response invalid.

    Image-review models occasionally return a valid JSON shape except for a quoted visible
    label inside a string, for example ``"labels: "CLOSED COVER""``.  This function only
    changes a quote that cannot legally terminate the current JSON string according to its
    immediate structural follow-up.  It is deliberately *not* a general JSON repairer:
    missing commas, brackets, values, or other malformed structures still fail normally.
    """
    output: list[str] = []
    inside_string = False
    index = 0

    def next_nonspace(start: int) -> tuple[str, int]:
        while start < len(text) and text[start].isspace():
            start += 1
        return (text[start] if start < len(text) else ""), start

    def can_terminate_string(quote_index: int) -> bool:
        following, following_index = next_nonspace(quote_index + 1)
        if following in {":", "}", "]"}:
            return True
        if following != ",":
            return False
        # A comma after a real JSON string is followed by another JSON value/key or a
        # container close.  Prose such as `"CLOSED COVER", and ...` is not.
        after_comma, _ = next_nonspace(following_index + 1)
        if after_comma in {'"', "{", "[", "}", "]", "-"} or after_comma.isdigit():
            return True
        return after_comma in {"t", "f", "n"}  # true, false, null

    while index < len(text):
        char = text[index]
        if inside_string and char == "\\":
            output.append(char)
            if index + 1 < len(text):
                output.append(text[index + 1])
                index += 2
                continue
        elif char == '"':
            if not inside_string:
                inside_string = True
            elif can_terminate_string(index):
                inside_string = False
            else:
                output.append("\\")
            output.append(char)
            index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


def parse_structured_json(text: str) -> tuple[Any, bool]:
    """Parse a provider's JSON, recovering only unescaped prose quotes when safe."""
    raw = strip_fences(text)
    try:
        return json.loads(raw), False
    except json.JSONDecodeError as original_error:
        repaired = repair_unescaped_json_string_quotes(raw)
        if repaired == raw:
            raise original_error
        try:
            return json.loads(repaired), True
        except json.JSONDecodeError:
            raise original_error


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
    if data.get("requested_model") != model:
        raise StageFailure(stage, "FAILED_MODEL_SELECTION", "Image receipt belongs to another requested model.")
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

    def __init__(self, jobs: OrdakJobs, notifier: PipelineNotifier | None, state: QHState, *, chatgpt_fallback_mode: str = "approval", image_qc_correction_policy: str = "0", beat_image_qc_disabled: bool = False) -> None:
        self.jobs = jobs
        self.notifier = notifier
        self.state = state
        self.stage_messages: dict[str, Any] = {}
        self.stage_started_at: dict[str, float] = {}
        self.chatgpt_fallback_mode = chatgpt_fallback_mode if chatgpt_fallback_mode in {"auto", "approval"} else "approval"
        self.image_qc_correction_policy = image_qc_correction_policy if image_qc_correction_policy in {"0", "1", "2", "strict"} else "0"
        self.beat_image_qc_disabled = bool(beat_image_qc_disabled)

    def image_qc_disabled_for(self, stage: str) -> bool:
        """Whether this body beat must never be uploaded to the ChatGPT reviewer."""
        return bool(getattr(self, "beat_image_qc_disabled", False)) and stage.startswith("beat_image_")

    @staticmethod
    def disabled_image_qc_receipt() -> dict[str, Any]:
        return {
            "passed": True,
            "raw_passed": None,
            "review_status": "disabled",
            "description": "ChatGPT visual QC disabled by the launch configuration.",
            "violations": [],
            "raw_violations": [],
            "blocking_violations": [],
            "observations": [],
            "regressions": [],
            "review_provider": None,
        }

    @staticmethod
    def _fallback_stage(stage: str) -> str:
        """Map internal JSON-attempt labels back to the visible pipeline node."""
        stage = re.sub(r"_json\d+(?:_repair)?$", "", stage)
        stage = re.sub(r"_try\d+$", "", stage)
        return re.sub(r"_\d{3}(?:_repair)?$", "", stage)

    def _consume_fallback_approval(self, stage: str) -> bool:
        path = self.state.project / "pipeline" / "FALLBACK_APPROVAL.json"
        try:
            approved = load_json(path)
        except (OSError, ValueError):
            return False
        if not isinstance(approved, dict) or str(approved.get("stage") or "") != stage:
            return False
        path.unlink(missing_ok=True)
        return True

    def _require_fallback_approval(self, stage: str, failure: StageFailure) -> None:
        visible = self._fallback_stage(stage)
        request = {
            "schema_version": 1,
            "status": "ACTION_REQUIRED",
            "stage": stage,
            "visible_stage": visible,
            "from_provider": "chatgpt",
            "to_provider": "gemini",
            "error_code": failure.error_code,
            "reason": failure.message[:1000],
            "created_at": utcnow(),
        }
        save_json(self.state.project / "pipeline" / "FALLBACK_ACTION_REQUIRED.json", request)
        self.state.mark(visible, "ACTION_REQUIRED", **{key: value for key, value in request.items() if key not in {"status", "stage"}})
        raise StageFailure(
            stage,
            "ACTION_REQUIRED",
            f"ChatGPT failed at {visible}; Gemini fallback is ready but requires approval.",
            error_code=failure.error_code,
        ) from failure

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
        started = time.perf_counter()
        self.stage_started_at[stage] = started
        if self.notifier is not None:
            self.stage_messages[stage] = self.notifier.stage_started(self._stage_title(stage), key=stage)
        return started

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
        if self.notifier is not None and not stage.startswith("beat_image_"):
            self.notifier.stage_reused(self._stage_title(stage), ["↻ Reused existing artifact", summary])

    def stage_progress(self, stage: str, lines: list[str]) -> None:
        """Refresh one aggregate stage message; used for the whole body-image batch."""
        if self.notifier is not None:
            self.notifier.stage_update(self.stage_messages.get(stage), self._stage_title(stage), lines)

    def stage_failed(self, stage: str, failure: StageFailure, started: float) -> None:
        self.state.fail(stage, failure)
        elapsed = time.perf_counter() - self.stage_started_at.get(stage, started)
        print(f"✘ {stage} [{failure.state}] {failure.message}", flush=True)
        if self.notifier is not None:
            try:
                message = self.stage_messages.pop(stage, None)
                detail = f"{failure.state}: {failure.message}"
                if failure.needs_human or failure.state.startswith(("PAUSED", "WAITING")):
                    self.notifier.stage_waiting(message, self._stage_title(stage), detail)
                else:
                    self.notifier.stage_failure(message, self._stage_title(stage), elapsed, detail)
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
        """ChatGPT text with an auditable, operator-controlled Gemini fallback."""
        try:
            result = self._run(stage, prompt, provider="chatgpt", mode="chat", references=references)
        except StageFailure as failure:
            if self.chatgpt_fallback_mode != "auto" and not self._consume_fallback_approval(stage):
                self._require_fallback_approval(stage, failure)
            print(f"    [fallback] ChatGPT failed; continuing {stage} with approved Gemini fallback.", flush=True)
            result = self._run(stage, prompt, provider="gemini", mode="chat", references=references)
            self.state.mark(self._fallback_stage(stage), STATE_RUNNING, fallback_from="chatgpt", fallback_to="gemini", fallback_reason=failure.message[:500])
        answer = (result.answer or "").strip()
        if not answer:
            raise StageFailure(stage, "FAILED", f"Provider returned an empty answer for {stage}.")
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
                parsed, repaired = parse_structured_json(last_raw)
                if repaired:
                    print(
                        f"    [{stage}] recovered unescaped quotes in provider JSON; preserving the raw response for audit.",
                        flush=True,
                    )
                return parsed
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
        self, stage: str, prompt: str, references: list[Reference], *, model: str, destination: Path,
        skip_content_qc: bool = False, retain_candidates_dir: Path | None = None,
    ) -> JobResult:
        """Generate, review and commit the best acceptable candidate atomically.

        Non-blocking findings use the operator's stage-wide correction budget. Blocking
        failures always consume another available attempt and can never be selected. The
        previous candidate is supplied as a quality-floor reference on corrections, and
        the final file is replaced only after the best reviewed candidate is known.
        """
        qc_disabled = skip_content_qc or self.image_qc_disabled_for(stage)
        policy = "disabled" if qc_disabled else getattr(self, "image_qc_correction_policy", "0")
        policy = policy if policy in {"disabled", "0", "1", "2", "strict"} else "0"
        max_attempts = {"disabled": 1, "0": 2, "1": 2, "2": 3, "strict": 3}[policy]
        correction_budget = {"disabled": 0, "0": 0, "1": 1, "2": 2, "strict": 2}[policy]
        request_id = request_fingerprint(prompt, model, references)[:16]
        candidates_dir = destination.parent / ".qc_candidates"
        iterations: list[dict[str, Any]] = []
        accepted: list[tuple[tuple[int, int, int, int], Path, JobResult, int]] = []
        prior_candidate: Path | None = None
        current_prompt = prompt
        current_references = list(references)

        try:
            for attempt in range(max_attempts):
                candidate = candidates_dir / f"{destination.stem}.{request_id}.attempt-{attempt + 1}.png"
                attempt_options = {"skip_content_qc": True} if skip_content_qc else {}
                result = self._image_attempt(
                    stage,
                    current_prompt,
                    current_references,
                    model=model,
                    destination=candidate,
                    **attempt_options,
                )
                check = dict((result.generation_receipt or {}).get("quality_check") or {})
                blocking = list(check.get("blocking_violations") or [])
                observations = list(check.get("observations") or check.get("violations") or [])
                regressions = list(check.get("regressions") or [])
                fully_clean = not blocking and not observations and not regressions
                record = {
                    "attempt": attempt + 1,
                    "job_id": result.job_id,
                    "prompt_sha256": sha256_text(current_prompt),
                    "output_sha256": sha256_file(candidate),
                    "quality_check": check,
                    "fully_clean": fully_clean,
                }
                if retain_candidates_dir is not None:
                    retain_candidates_dir.mkdir(parents=True, exist_ok=True)
                    retained = retain_candidates_dir / f"{destination.stem}.attempt_{attempt + 1}.png"
                    retained_partial = retained.with_name(f".{retained.name}.{uuid.uuid4().hex}.tmp")
                    try:
                        shutil.copyfile(candidate, retained_partial)
                        retained_partial.replace(retained)
                    finally:
                        retained_partial.unlink(missing_ok=True)
                    record["retained_candidate"] = str(retained)
                iterations.append(record)
                if not blocking:
                    # A candidate with a newly introduced regression can never displace a
                    # regression-free one. Then lower risk/count wins; earlier wins ties.
                    risk = sum(
                        3 if re.search(r"\b(?:major|severe|distort|anatom|identity|continuity|unreadable|missing)\b", finding, re.I) else 1
                        for finding in observations
                    )
                    accepted.append(((int(bool(regressions)), risk, len(observations), attempt), candidate, result, attempt + 1))

                if fully_clean:
                    break
                if not blocking and attempt >= correction_budget:
                    break
                if attempt + 1 >= max_attempts:
                    break

                prior_candidate = candidate
                findings = blocking or observations
                current_prompt = self._image_qc_correction_prompt(stage, prompt, findings)
                current_references = [
                    *references,
                    Reference(role="qc_previous_candidate", path=prior_candidate),
                ]
                print(
                    f"    [image QC] {stage}: correction {attempt + 1}/{max_attempts - 1} "
                    f"for {len(findings)} finding(s).",
                    flush=True,
                )

            if policy == "strict" and not any(item["fully_clean"] for item in iterations):
                raise StageFailure(
                    stage,
                    "FAILED_VALIDATION",
                    f"{stage}: strict image QC found no fully clean candidate after 3 attempts.",
                    error_code="image_content_rejected",
                )
            if not accepted:
                raise StageFailure(
                    stage,
                    "FAILED_VALIDATION",
                    f"{stage}: image content QC rejected every candidate with a blocking violation.",
                    error_code="image_content_rejected",
                )

            _score, selected_path, selected_result, selected_attempt = min(accepted, key=lambda item: item[0])
            for item in iterations:
                item["selected"] = item["attempt"] == selected_attempt
            receipt = dict(selected_result.generation_receipt or {})
            receipt.update({
                "quality_check": iterations[selected_attempt - 1]["quality_check"],
                "quality_iterations": iterations,
                "qc_policy": policy,
                "qc_selected_attempt": selected_attempt,
                "request_fingerprint": request_fingerprint(prompt, model, references),
            })
            selected_result.generation_receipt = receipt
            destination.parent.mkdir(parents=True, exist_ok=True)
            committed = destination.with_name(f".{destination.stem}.{uuid.uuid4().hex}.png")
            try:
                shutil.copyfile(selected_path, committed)
                committed.replace(destination)
            finally:
                committed.unlink(missing_ok=True)
            return selected_result
        finally:
            for item in candidates_dir.glob(f"{destination.stem}.{request_id}.attempt-*.png") if candidates_dir.is_dir() else ():
                item.unlink(missing_ok=True)
            try:
                candidates_dir.rmdir()
            except OSError:
                pass

    @staticmethod
    def _image_qc_correction_prompt(stage: str, original_prompt: str, findings: list[str]) -> str:
        stage_guard = (
            "Preserve the established character identity, story moment, composition, camera, palette, medium, and frame language."
            if stage.startswith("beat_image_") else
            "Preserve the world composition, camera, palette, medium, texture, and host-free intent."
            if stage == "world_keyframe" else
            "Preserve the book identity, view, layout, materials, motifs, and usable blank areas."
            if "book" in stage else
            "Preserve the established medium, palette, texture family, line treatment, lighting, and layout."
        )
        numbered = "\n".join(f"{index}. {finding}" for index, finding in enumerate(findings, 1))
        return (
            "Create exactly one corrected 9:16 replacement image. The attachment with role "
            "qc_previous_candidate is the previous output and the minimum quality floor, not a new "
            "scene request. Make the smallest targeted changes needed to fix ONLY the QC findings "
            "below. Do not redesign, simplify, crop, restyle, or replace elements that already work. "
            f"{stage_guard} Introduce no new text, logos, objects, anatomy problems, identity drift, "
            "style drift, or continuity errors. The replacement must be equal or better in every "
            "unmentioned respect.\n\nQC findings to correct:\n"
            f"{numbered}\n\nOriginal art direction remains authoritative:\n{original_prompt}"
        )

    def _image_attempt(
        self,
        stage: str,
        prompt: str,
        references: list[Reference],
        *,
        model: str,
        destination: Path,
        skip_content_qc: bool = False,
    ) -> JobResult:
        """One Gemini image, downloaded and verified. Returns the job result for the receipt."""
        fingerprint = request_fingerprint(prompt, model, references)
        before = {str(ref.path): sha256_file(ref.path) for ref in references}
        pending = destination.parent / ".pending_images" / destination.name
        metadata = pending.with_suffix(".json")
        try:
            saved = load_json(metadata) if metadata.is_file() else {}
            if not isinstance(saved, dict) or not isinstance(saved.get("result", {}), dict):
                saved = {}
        except (OSError, ValueError):
            saved = {}
        if (saved.get("fingerprint") == fingerprint and valid_image(pending) and
                saved.get("sha256") == sha256_file(pending)):
            result = JobResult(**saved["result"])
        else:
            result = self._run(
                stage, prompt, provider="gemini", mode="image_generate",
                generation=Generation(model=model, quality="best", aspect_ratio="9:16"),
                references=references,
            )
            pending.unlink(missing_ok=True)
            metadata.unlink(missing_ok=True)
        if len(result.output_images) != 1:
            raise StageFailure(stage, "FAILED_DOWNLOAD", f"{stage}: Expected exactly one image, got {len(result.output_images)}.")
        receipt_notes = list((result.generation_receipt or {}).get("notes") or [])
        if "artifact_source=download" not in receipt_notes:
            raise StageFailure(
                stage,
                "FAILED_VALIDATION",
                f"{stage}: Gemini artifact has no verified download provenance; refusing to save it.",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        require_verified_image_model(stage, model, result.generation_receipt)
        partial = destination.with_name(f".{destination.stem}.{uuid.uuid4().hex}.png")
        try:
            if pending.is_file() and saved.get("fingerprint") == fingerprint and saved.get("sha256") == sha256_file(pending):
                shutil.copyfile(pending, partial)
            else:
                self.jobs.download(result.output_images[0], partial)
            if not valid_image(partial):
                raise StageFailure(stage, "FAILED_VALIDATION", f"{stage}: Image cannot be fully decoded.")
            from PIL import Image, ImageChops, ImageStat
            with Image.open(partial) as candidate:
                if abs((candidate.width / candidate.height) / (9 / 16) - 1) > 0.08:
                    raise StageFailure(stage, "FAILED_VALIDATION", "Image aspect ratio is not 9:16.")
                reduced = candidate.convert("RGB").resize((96, 96))
            for ref in references:
                if ref.role == "qc_previous_candidate":
                    # Corrective edits are intentionally close to their quality-floor
                    # candidate; content QC, not a pixel-distance heuristic, decides
                    # whether the listed defect was actually improved.
                    continue
                with Image.open(ref.path) as reference:
                    difference = ImageStat.Stat(ImageChops.difference(reduced, reference.convert("RGB").resize((96, 96))))
                if sum(difference.mean) / 3 < 2:
                    raise StageFailure(stage, "FAILED_VALIDATION", f"Output copies uploaded reference: {ref.role}")
            # Preserve a paid-for candidate across a pause in the text reviewer.
            pending.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(partial, pending)
            save_json(metadata, {"fingerprint": fingerprint, "sha256": sha256_file(pending), "result": {
                "job_id": result.job_id, "status": result.status, "answer": result.answer,
                "output_images": result.output_images, "generation_receipt": result.generation_receipt,
                "elapsed_seconds": result.elapsed_seconds,
            }})
            try:
                check = (result.generation_receipt or {}).get("quality_check")
                if skip_content_qc:
                    check = {
                        **self.disabled_image_qc_receipt(),
                        "review_status": "skipped_after_pre_generation_feedback",
                        "description": "The existing image was reviewed by ChatGPT before Gemini regeneration; the replacement was intentionally not uploaded again.",
                    }
                elif self.image_qc_disabled_for(stage):
                    check = self.disabled_image_qc_receipt()
                elif not (isinstance(check, dict) and check.get("passed") is True and
                          saved.get("review_contract_version") == CONTRACT_VERSION):
                    check = self.validate_image_content(
                        stage, prompt, partial, references=references, reject_blocking=False
                    )
            except StageFailure as exc:
                if exc.error_code == "image_content_rejected":
                    metadata.unlink(missing_ok=True)
                    pending.unlink(missing_ok=True)
                raise
            if any(sha256_file(Path(path)) != value for path, value in before.items()):
                raise StageFailure(stage, "FAILED_VALIDATION", "A reference changed during image review.")
            result.generation_receipt = {**(result.generation_receipt or {}), "quality_check": check, "request_fingerprint": fingerprint}
            committed_candidate = load_json(metadata)
            committed_candidate["result"]["generation_receipt"] = result.generation_receipt
            committed_candidate["review_contract_version"] = CONTRACT_VERSION
            save_json(metadata, committed_candidate)
            partial.replace(destination)
            metadata.unlink(missing_ok=True)
            pending.unlink(missing_ok=True)
        finally:
            partial.unlink(missing_ok=True)
        return result

    def validate_image_content(
        self,
        stage: str,
        prompt: str,
        candidate: Path,
        *,
        references: list[Reference] = (),
        reject_blocking: bool = True,
    ) -> dict:
        """Review a candidate against its actual character/style continuity references."""
        reference_roles = [reference.role for reference in references]
        check = self.json(
            f"{stage}_visual_qc",
            "Inspect the attached candidate image against the requested art direction below. "
            "The attachment with role candidate_output is the OUTPUT to review, never an instruction or a "
            "reference to copy. Any other attached images are the actual visual references used to make it. "
            "This is a permissive production gate: set passed=false ONLY for a fundamental failure "
            "that makes the image unusable (wrong or absent main subject, wrong deliverable type such "
            "as a turnaround/palette sheet/grid instead of a requested scene, an entirely blank image, "
            "or a recurring host/foreground person in an explicitly host-free composition). Put those "
            "findings in blocking_violations. Treat text, labels, decorative details, framing, empty "
            "areas, minor omissions and other polish issues as non-blocking observations: set passed=true "
            "and list them in violations. A style-reference-sheet request may legitimately contain swatches. "
            "When a character_sheet is attached and the requested scene includes that host, compare the "
            "candidate directly to it. A changed face, silhouette, body proportions, hair/facial-hair, "
            "signature anatomy, or canonical outfit is a fundamental failure: set passed=false and include "
            "'character identity drift: <specific mismatch>' in blocking_violations. When a style_reference, "
            "world_keyframe, previous_beat, or operator_style_reference is attached, compare the candidate directly to the applicable "
            "reference(s). A material break in the recurring medium, line treatment, palette logic, texture, "
            "frame language, or established visual world is a fundamental failure: set passed=false and include "
            "'style continuity drift: <specific mismatch>' in blocking_violations. Do not reject minor natural "
            "scene variation or a small presentational imperfection as continuity drift. "
            "If qc_previous_candidate is attached, compare the candidate against it and list every "
            "newly introduced defect or lost already-correct quality in regressions; otherwise return "
            "regressions as an empty array. Judge visible compliance, not artistic taste. Return only JSON with passed (boolean), "
            "description (what is actually visible), violations (array of specific strings), and "
            "blocking_violations (array of only fundamental failures), and regressions (array). Do not use "
            "literal double-quote characters inside description or violation strings; use single quotes "
            "for visible labels instead. "
            f"Attached continuity-reference roles: {reference_roles or ['none']}.\n"
            f"Requested art direction:\n{prompt}",
            references=[Reference(role="candidate_output", path=candidate), *references],
        )
        try:
            accepted, warnings = assess_image_content_qc(check)
        except ValueError as exc:
            raise StageFailure(stage, "FAILED_VALIDATION", f"Image content QC returned an invalid review: {exc}") from exc
        if accepted["passed"] is not True and reject_blocking:
            raise StageFailure(stage, "FAILED_VALIDATION", f"Image content QC rejected output: {str(accepted)[:1200]}", error_code="image_content_rejected")
        if warnings:
            print(f"    [image QC] accepted with {len(warnings)} non-blocking observation(s): {warnings[:2]}", flush=True)
        return accepted

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
    references: list[Reference] = (),
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
            return validate(runner.json(label, current, references=references))
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


def _character_prompt_context(character: CharacterContext) -> str:
    return json.dumps(
        {
            "id": character.id,
            "display_name": character.display_name,
            "appearance": character.appearance_full,
            "behavior": character.behavior,
            "negative_constraints": character.negative_constraints,
            "environment_policy": character.environment_policy,
            "environment_affinities": list(character.environment_affinities),
            "reference_mode": character.reference_mode,
        },
        ensure_ascii=False,
    )


def _coerce_character_context(value: Any) -> CharacterContext:
    """Compatibility for old direct helper callers; identity still comes from registry."""
    if isinstance(value, CharacterContext):
        return value
    registry_file = character_registry_path(value)
    if registry_file is None:
        raise CharacterSelectionError("This content project has no character registry.")
    registry = load_character_registry(registry_file)
    return registry.get(registry.legacy_default_character_id)


def stage_character_resolution(
    runner: Runner,
    project: Path,
    content_project: Any,
    topic: str,
    brief: str,
    plan: dict[str, Any],
    launch: dict[str, Any],
    *,
    is_legacy_run: bool,
) -> tuple[CharacterResolution, CharacterContext]:
    """Resolve WHO once, after final script and before Episode Director, then persist it."""
    registry_file = character_registry_path(content_project)
    if registry_file is None:
        raise StageFailure("character_resolution", "FAILED_VALIDATION", "Q Station character registry is not configured.")
    registry = load_character_registry(registry_file)
    request = launch.get("character") if isinstance(launch.get("character"), dict) else None
    resolution_path = project / "creative" / "CHARACTER_RESOLUTION.json"
    persisted = launch.get("character_resolution") if isinstance(launch.get("character_resolution"), dict) else None
    if persisted is None and resolution_path.is_file():
        candidate = load_json(resolution_path)
        persisted = candidate if isinstance(candidate, dict) else None
    mode, requested_id = parse_character_request(request)

    def auto_selector() -> Any:
        selector = content_project.root / "prompts" / "characters" / "AUTO_CHARACTER_SELECTOR.md"
        template = selector.read_text(encoding="utf-8")
        prompt = fill(
            template,
            TOPIC=topic,
            USER_REQUEST=topic,
            CREATIVE_BRIEF=brief,
            FINAL_SCRIPT=plan["full_narration"],
            CHARACTER_PROFILES=json.dumps(
                [registry.get(char_id).selection_summary() for char_id in registry.enabled_ids()],
                ensure_ascii=False,
            ),
            RECENT_CHARACTERS="[]",
        )
        return runner.json("character_auto_selector", prompt)

    resolution = resolve_character(
        registry,
        persisted=persisted,
        requested_mode=mode,
        requested_character_id=requested_id,
        is_legacy_run=is_legacy_run,
        run_auto_selector=auto_selector,
    )
    context = registry.get(resolution.resolved_character_id)
    payload = resolution.to_state()
    if persisted is None and not is_legacy_run:
        launch["character"] = {
            "mode": resolution.requested_mode,
            **({"character_id": resolution.requested_character_id} if resolution.requested_character_id else {}),
        }
        launch["character_resolution"] = payload
        save_json(project / "launch" / "LAUNCH_REQUEST.json", launch)
    save_json(resolution_path, payload)
    runner.state.mark(
        "character_resolution",
        STATE_REUSED if persisted else STATE_DONE,
        **payload,
    )
    print(
        f"Character requested: {'Auto' if resolution.requested_mode == 'auto' else context.display_name}\n"
        f"Character resolved: {context.display_name}\n"
        f"Resolution: {resolution.source}"
        + (f"\nReason: {resolution.reason}" if resolution.reason else ""),
        flush=True,
    )
    return resolution, context


def _recent_history(project_id: str = "q_station", limit: int = 4) -> list[dict[str, Any]]:
    """The last few episodes' traits, for the anti-repetition heuristics (§35)."""
    from episode_history import recent

    return recent(project_id, limit)


OPENING_LINK_TYPES = frozenset({"direct", "metaphor", "irony", "cause_effect", "historical_echo"})
REQUIRED_EPISODE_OPENING_FIELDS = (
    "opening_activity",
    "topic_visual_link",
    "link_type",
    "opening_visual_proof",
)


def validate_episode_opening_contract(data: Any) -> dict[str, Any]:
    """Require a new episode plan to make its topic link visibly actionable.

    Existing completed episodes are deliberately not passed through this function: their
    persisted plan remains resumable. New director responses must name the visual proof
    that Flow Clip A will put on screen, rather than hiding the topic connection in a
    free-form rationale.
    """
    if not isinstance(data, dict):
        raise StageFailure("episode_director", "FAILED_VALIDATION", "The episode plan must be a JSON object.")

    missing = [
        field for field in REQUIRED_EPISODE_OPENING_FIELDS
        if not isinstance(data.get(field), str) or not data[field].strip()
    ]
    if missing:
        raise StageFailure(
            "episode_director",
            "FAILED_VALIDATION",
            "The episode plan is missing required opening-link fields: " + ", ".join(missing) + ".",
        )

    link_type = str(data["link_type"]).strip()
    if link_type not in OPENING_LINK_TYPES:
        raise StageFailure(
            "episode_director",
            "FAILED_VALIDATION",
            "The episode plan has invalid link_type " + repr(link_type) + "; expected one of "
            + ", ".join(sorted(OPENING_LINK_TYPES)) + ".",
        )
    return data


def stage_episode_director(
    runner: Runner, project: Path, content_project: Any, topic: str, brief: str,
    plan: dict[str, Any], character: CharacterContext | None = None,
) -> dict[str, Any]:
    character = _coerce_character_context(character or content_project)
    stage = "episode_director"
    target = project / "creative" / "EPISODE_PLAN.json"
    if runner.state.done(stage) and target.is_file():
        runner.stage_reused(stage, target.name)
        return load_json(target)
    started = runner.stage_start(stage)
    from episode_history import avoidance_note, repeated_traits

    history = _recent_history(getattr(content_project, "project_id", "q_station"))
    base_prompt = fill(
        resolve_prompt(content_project, "03_episode_director.md"),
        TOPIC=topic,
        CREATIVE_BRIEF=brief,
        FINAL_SCRIPT=plan["full_narration"],
        CHARACTER_CONTEXT=_character_prompt_context(character),
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
        data = validate_episode_opening_contract(data)
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


def operator_style_reference(project: Path) -> Reference | None:
    """Resolve only a hash-pinned, run-owned operator reference from the frozen brief."""
    try:
        manifest = (load_json(project / "launch" / "CREATIVE_BRIEF.json").get("_qh") or {}).get("world_style_reference")
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(manifest, dict):
        return None
    relative, digest = str(manifest.get("path") or ""), str(manifest.get("sha256") or "")
    try:
        path = (ROOT / relative).resolve()
        path.relative_to(project.resolve())
    except ValueError:
        raise StageFailure("world_style_director", "FAILED_VALIDATION", "Style reference path is outside this run.")
    if not re.fullmatch(r"[a-f0-9]{64}", digest) or not valid_image(path) or sha256_file(path) != digest:
        raise StageFailure("world_style_director", "FAILED_VALIDATION", "Style reference failed integrity verification.")
    return Reference(role="operator_style_reference", path=path)


def stage_world_style_director(
    runner: Runner,
    project: Path,
    content_project: Any,
    topic: str,
    plan: dict[str, Any],
    directive: str,
) -> dict[str, Any]:
    stage = "world_style_director"
    target = project / "creative" / "WORLD_STYLE_PLAN.json"
    if runner.state.done(stage) and target.is_file():
        runner.stage_reused(stage, target.name)
        return load_json(target)
    started = runner.stage_start(stage)
    reference = operator_style_reference(project)
    catalog = {}
    catalog_path = WORLD_STYLES_ROOT / "CATALOG.json"
    if catalog_path.is_file():
        catalog = load_json(catalog_path)
    prompt = fill(
        resolve_prompt(content_project, "04_world_style_director.md"),
        TOPIC=topic,
        FINAL_SCRIPT=plan["full_narration"],
        STYLE_CATALOG=json.dumps(catalog, ensure_ascii=False),
        RECENT_STYLES=json.dumps(
            [item.get("world_style_id") for item in _recent_history(getattr(content_project, "project_id", "q_station"))],
            ensure_ascii=False,
        ),
        STYLE_DIRECTIVE=directive,
    )
    def check_style(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict) or not data.get("style_id"):
            raise StageFailure(stage, "FAILED_VALIDATION", "The world style plan has no style_id.")
        if not str(data.get("frame_language") or "").strip() or not str(data.get("subtitle_reserve") or "").strip():
            raise StageFailure(
                stage,
                "FAILED_VALIDATION",
                "The world style plan must define both frame_language and subtitle_reserve.",
            )
        if reference and str(data.get("decision") or "").lower() != "new":
            raise StageFailure(stage, "FAILED_VALIDATION", "An operator style reference requires a new style, not catalog reuse.")
        return data

    data = ask_with_correction(runner, stage, prompt, check_style, references=[reference] if reference else ())
    if reference:
        data["operator_style_reference"] = {
            "path": str(reference.path.relative_to(ROOT)), "sha256": sha256_file(reference.path), "role": reference.role,
        }
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
    project_id = getattr(content_project, "project_id", "q_station")
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
    reference = operator_style_reference(project)
    prompt = (
        "Create exactly one 9:16 vertical style reference sheet — a texture and palette sample, "
        f"not a scene. Medium: {world_style_plan.get('medium')}. "
        f"Texture family: {world_style_plan.get('texture_family')}. "
        f"Palette: {world_style_plan.get('palette_summary')}. "
        f"Line treatment: {world_style_plan.get('line_treatment')}. "
        f"Lighting: {world_style_plan.get('lighting')}. "
        f"Avoid: {world_style_plan.get('negative_constraints')}. "
        "No characters, no text, no logos, no photorealism."
        + (
            " The attached operator_style_reference is style-only: use its palette, material texture, "
            "line language and lighting as inspiration for this original neutral anchor. Do not copy "
            "its subject, composition, text, logo, person, or recognizable layout."
            if reference else ""
        )
    )
    launch = load_json(project / "launch" / "LAUNCH_REQUEST.json")
    model = normalize_gemini_model(launch.get("image_generation", {}).get("model") or "nano_banana_2")
    receipt_path = project / "pipeline" / "provider_receipts" / "gemini_world_style_anchor.json"
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
            source.resolve().relative_to(WORLD_STYLES_ROOT.resolve())
            refs = [Reference(role="catalog_style", path=source)]
            fingerprint = request_fingerprint(prompt, "catalog", refs)
            if receipt_status(project, target, receipt_path, fingerprint=fingerprint)["status"] == "verified":
                runner.stage_reused(stage, target.name)
                return target
            started = runner.stage_start(stage)
            check = runner.validate_image_content(stage, prompt, source)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            try:
                shutil.copyfile(source, temporary)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            save_json(receipt_path, {
                "contract_version": CONTRACT_VERSION, "source_type": "catalog",
                "request_fingerprint": fingerprint, "quality_check": check,
                "output_sha256": sha256_file(target), "output_path": _receipt_path(project, target),
                "references": [{"role": "catalog_style", "path": str(source.resolve()), "sha256": sha256_file(source)}],
            })
            from world_style_catalog import WorldStyleCatalogError, record_reuse

            try:
                uses = record_reuse(getattr(content_project, "project_id", "q_station"), reuse_of)
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

    references = [reference] if reference else []
    reused = reusable_image(runner, project, stage, target, receipt_path, prompt, model, references)
    started = None
    if not reused:
        started = runner.stage_start(stage)
        result = runner.image(stage, prompt, references, model=model, destination=target)
        _write_image_receipt(project, "gemini_world_style_anchor", result, prompt, references, target, model)

    # A new style is only reusable once it is in the catalog: the director is shown that
    # file, the panel lists it, and a later episode can be pinned to it (§35).
    from world_style_catalog import WorldStyleCatalogError, publish_style

    published = ""
    try:
        entry = publish_style(
            getattr(content_project, "project_id", "q_station"), world_style_plan, target
        )
        published = str(entry.get("path") or "")
    except WorldStyleCatalogError as exc:
        raise StageFailure(
            stage,
            "FAILED_VALIDATION",
            f"The new style could not be registered for reuse: {exc}",
        ) from exc

    if reused:
        runner.stage_reused(stage, f"{target.name} → catalog/{published}")
    else:
        assert started is not None
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


def reusable_image(runner, project: Path, stage: str, target: Path, receipt: Path,
                   prompt: str, model: str, references: list[Reference]) -> bool:
    if not valid_image(target):
        return False
    fingerprint = request_fingerprint(prompt, model, references)
    status = receipt_status(project, target, receipt, fingerprint=fingerprint)
    if status["status"] == "verified":
        return True
    # Old receipts can be upgraded by reviewing the existing pixels, without paying
    # for a new image. Never bless a changed file, changed reference, or failed model.
    original = receipt_status(project, target, receipt)
    if original["status"] != "unverified" or not receipt.is_file():
        return False
    data = load_json(receipt)
    expected_refs = [(ref.role, sha256_file(ref.path)) for ref in references]
    recorded_refs = [(ref.get("role"), ref.get("sha256")) for ref in data.get("references", [])]
    if (data.get("output_sha256") != sha256_file(target) or data.get("requested_model") != model or
            data.get("prompt_sha256") != sha256_text(prompt) or expected_refs != recorded_refs):
        return False
    require_verified_image_model(stage, model, data.get("provider_receipt"))
    if runner.image_qc_disabled_for(stage):
        # The provider/model/hash/reference checks above remain mandatory. Only the
        # ChatGPT visual review is bypassed, so this path never uploads the pixels.
        data.update(
            contract_version=CONTRACT_VERSION,
            request_fingerprint=fingerprint,
            quality_check=runner.disabled_image_qc_receipt(),
        )
        save_json(receipt, data)
        return True
    try:
        check = runner.validate_image_content(stage, prompt, target, references=references)
    except StageFailure as exc:
        if exc.error_code == "image_content_rejected":
            return False
        raise
    data.update(contract_version=CONTRACT_VERSION, request_fingerprint=fingerprint, quality_check=check)
    save_json(receipt, data)
    return True


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
        "contract_version": CONTRACT_VERSION,
        "request_fingerprint": request_fingerprint(prompt, requested_model, references),
        "quality_check": receipt.get("quality_check", {}),
        "provider": "gemini",
        "job_id": result.job_id,
        "requested_model": requested_model,
        "actual_model_label": receipt.get("actual_model_label"),
        "model_verified": bool(receipt.get("model_verified")),
        "pro_regeneration_used": bool(receipt.get("pro_regeneration_used")),
        "provider_receipt": receipt,
        "references": [
            {"role": ref.role, "path": _receipt_path(ROOT, Path(ref.path)), "sha256": sha256_file(ref.path)}
            for ref in references
        ],
        "prompt_sha256": sha256_text(prompt),
        "prompt": prompt,
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
    character: CharacterContext,
) -> dict[str, Any]:
    stage = "visual_plan"
    target = project / "creative" / "VISUAL_PLAN.json"
    if runner.state.done(stage) and target.is_file():
        runner.stage_reused(stage, target.name)
        return load_json(target)
    started = runner.stage_start(stage)
    body_episode_context = {
        key: episode_plan.get(key)
        for key in ("hero_presence_mode", "closing_mode")
        if episode_plan.get(key) is not None
    }
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
        EPISODE_PLAN=json.dumps(body_episode_context, ensure_ascii=False),
        WORLD_STYLE_PLAN=json.dumps(world_style_plan, ensure_ascii=False),
        VIDEO_BRIEF="aspect 9:16 vertical Short",
        BODY_DURATION_SECONDS=f"{body_seconds:.0f}",
        CHARACTER_CONTEXT=json.dumps(
            {"id": character.id, "display_name": character.display_name, "behavior": character.behavior},
            ensure_ascii=False,
        ),
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
    world_style_plan: dict[str, Any],
) -> str:
    stage = "world_keyframe_prompt"
    target = project / "references" / "world_keyframe_prompt.txt"
    if runner.state.done(stage) and target.is_file():
        runner.stage_reused(stage, target.name)
        return target.read_text(encoding="utf-8").strip()
    started = runner.stage_start(stage)
    # Deliberately ignore episode direction and character-aware body planning. Clip B's
    # last frame depends only on the factual script and inside-book world style.
    prompt = fill(
        resolve_prompt(content_project, "06_world_keyframe_prompt_writer.md"),
        FINAL_SCRIPT=plan["full_narration"],
        WORLD_STYLE_PLAN=json.dumps(world_style_plan, ensure_ascii=False),
        CAPTION_LAYOUT_RULE=caption_layout_rule(world_style_plan),
    )
    text = runner.text(stage, prompt).strip()
    # The world keyframe is the visual constitution for every body frame, so make its
    # repeatable material border and caption reserve explicit in the actual Gemini prompt.
    text = (
        f"{text} {episode_frame_contract(world_style_plan)} "
        "Binding isolation: no recurring host, no selected host, and no foreground person or character."
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n", encoding="utf-8")
    runner.stage_done(stage, started, target.name, prompt_sha256=sha256_text(text))
    return text


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

    Gemini uses it to construct the episode-specific book frame. Flow Clip B stays in
    frames-only mode and therefore receives neither this sheet nor a character sheet.
    """
    stage = "book_design_sheet"
    target = book_design_sheet_path(content_project)
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
    canonical_receipt = target.with_suffix(target.suffix + ".receipt.json")
    canonical_fingerprint = request_fingerprint(prompt, "canonical", [])
    if valid_image(target):
        status = receipt_status(
            project, target, canonical_receipt, fingerprint=canonical_fingerprint
        )
        if status["status"] == "verified":
            runner.stage_reused(stage, target.name)
            return target
        # Migrate an older shared asset only after inspecting its actual pixels against
        # the current identity contract. A content rejection falls through to generation.
        try:
            check = runner.validate_image_content(stage, prompt, target)
        except StageFailure as exc:
            if exc.error_code != "image_content_rejected":
                raise
        else:
            _write_canonical_image_receipt(target, prompt, check)
            runner.stage_reused(stage, target.name)
            return target

    started = runner.stage_start(stage)
    result = runner.image(stage, prompt, [], model=model, destination=target)
    _write_image_receipt(project, "gemini_book_design_sheet", result, prompt, [], target, model)
    check = (result.generation_receipt or {}).get("quality_check")
    if not isinstance(check, dict) or check.get("passed") is not True:
        raise StageFailure(stage, "FAILED_VALIDATION", "Generated book sheet has no successful content review.")
    _write_canonical_image_receipt(target, prompt, check, result=result, model=model)
    runner.stage_done(stage, started, str(target.relative_to(ROOT)), sha256=sha256_file(target))
    return target


def _write_canonical_image_receipt(
    target: Path,
    prompt: str,
    quality_check: dict[str, Any],
    *,
    result: JobResult | None = None,
    model: str | None = None,
) -> Path:
    """Commit the project-level book identity independently of an episode/model."""
    from PIL import Image

    with Image.open(target) as image:
        dimensions = list(image.size)
    payload = {
        "contract_version": CONTRACT_VERSION,
        "source_type": "canonical",
        "request_fingerprint": request_fingerprint(prompt, "canonical", []),
        "quality_check": quality_check,
        "prompt": prompt,
        "prompt_sha256": sha256_text(prompt),
        "output_path": _receipt_path(ROOT, target),
        "output_sha256": sha256_file(target),
        "output_dimensions": dimensions,
        "references": [],
        "validated_at": utcnow(),
    }
    if result is not None:
        payload["origin"] = {
            "provider": "gemini",
            "job_id": result.job_id,
            "requested_model": model,
            "provider_receipt": result.generation_receipt,
        }
    receipt = target.with_suffix(target.suffix + ".receipt.json")
    save_json(receipt, payload)
    return receipt


def stage_world_keyframe(
    runner: Runner,
    project: Path,
    content_project: Any,
    prompt: str,
    world_style_anchor: Path,
    *,
    force: bool = False,
) -> Path:
    """The one image that defines the episode's world. Gemini only, verified, no substitute."""
    stage = "world_keyframe"
    target = project / "references" / "world_keyframe.png"
    receipt = project / "pipeline" / "provider_receipts" / "gemini_world_keyframe.json"
    launch = load_json(project / "launch" / "LAUNCH_REQUEST.json")
    model = normalize_gemini_model(launch.get("image_generation", {}).get("model") or "nano_banana_2")

    # WORLD_KEYFRAME is deliberately host-free: it is Clip B's last frame and must not
    # know which recurring host was selected. Only the subject-world style is referenced.
    references: list[Reference] = []
    if valid_image(world_style_anchor):
        references.append(Reference(role="style_reference", path=world_style_anchor))
    reference = operator_style_reference(project)
    if reference:
        references.append(reference)
        prompt = (
            f"{prompt.rstrip()}\n\nThe attached operator_style_reference is style-only. Preserve the "
            "newly established world plan while echoing only its texture, palette, line work and lighting; "
            "do not copy its subject, text, people, logo, or composition."
        )

    if not force and reusable_image(runner, project, stage, target, receipt, prompt, model, references):
        runner.stage_reused(stage, target.name)
        return target
    started = runner.stage_start(stage)
    result = runner.image(stage, prompt, references, model=model, destination=target)
    _write_image_receipt(project, "gemini_world_keyframe", result, prompt, references, target, model)
    runner.stage_done(stage, started, target.name, sha256=sha256_file(target), model=model)
    return target


def stage_book_spread(
    runner: Runner,
    project: Path,
    world_keyframe: Path,
    episode_plan: dict[str, Any],
    *,
    force: bool = False,
) -> Path:
    """Composite the world keyframe onto a book page — the Start frame for Clip B."""
    stage = "book_spread"
    target = project / "references" / "book_spread_frame.png"
    if not force and valid_image(target) and runner.state.done(stage):
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


def stage_topic_book_cover(
    runner: Runner, project: Path, content_project: Any, topic: str, world_style_anchor: Path, *, force: bool = False
) -> Path:
    """Generate Clip B's closed, topic-symbolic first frame — never an open spread."""
    stage = "book_cover"
    target = project / "references" / "book_cover_frame.png"
    receipt = project / "pipeline" / "provider_receipts" / "gemini_book_cover.json"
    launch = load_json(project / "launch" / "LAUNCH_REQUEST.json")
    # Direct, stage-only runs may use a placeholder CLI topic.  The durable launch
    # request is the canonical subject for an episode asset and must win in that case.
    launch_topic = str(launch.get("topic") or "").strip()
    cover_topic = launch_topic if launch_topic and topic.strip().lower() in {"", "topic"} else topic
    # A bare topic prompt makes image models fall back to generic "book" symbols.
    # First pin down a small, auditable set of subject-specific visual facts.
    brief_stage = "book_cover_design"
    brief_target = project / "creative" / "BOOK_COVER_DESIGN.txt"
    if force or not (runner.state.done(brief_stage) and brief_target.is_file()):
        brief_started = runner.stage_start(brief_stage)
        brief_prompt = (
            "Create a compact visual art-direction brief (55–90 words) for a CLOSED illustrated book cover "
            f"about this episode topic: {cover_topic!r}. Name exactly 3–5 concrete, non-textual motifs, materials or "
            "ornaments unmistakably tied to this topic, plus their arrangement on a cover. If the topic mentions "
            "a real person, represent only their era, field, tools, place, or values indirectly: never their face, "
            "body, name, initials, signature, or likeness. Do not use generic compass, globe, ship, starfield, "
            "laurel, lightbulb, or random celestial/nautical imagery unless the topic itself requires it. No words, "
            "letters, numbers, logos, UI, markdown, or explanation; return the art-direction brief only."
        )
        cover_design = runner.text(brief_stage, brief_prompt).strip()
        if len(cover_design) < 40:
            raise StageFailure(brief_stage, "FAILED_VALIDATION", "Book-cover design brief was unusably short.")
        brief_target.parent.mkdir(parents=True, exist_ok=True)
        brief_target.write_text(cover_design + "\n", encoding="utf-8")
        runner.stage_done(brief_stage, brief_started, brief_target.name, prompt_sha256=sha256_text(cover_design))
    else:
        runner.stage_reused(brief_stage, brief_target.name)
        cover_design = brief_target.read_text(encoding="utf-8").strip()

    model = normalize_gemini_model(launch.get("image_generation", {}).get("model") or "nano_banana_2")
    prompt = (
        "Create exactly one 9:16 vertical first frame for an animated storybook transition. Camera is perfectly "
        "top-down/orthographic, never tilted or three-quarter: one CLOSED hardback book lies flat, centered and "
        "occupies about 82–88% of the canvas height with narrow even margins. The entire cover and page block are "
        "visible. The surrounding tabletop/paper/ground uses ONLY the supplied episode style reference's texture, "
        "palette and frame language; it must not borrow the book-cover subject matter. The cover itself is uniquely "
        f"and richly crafted for this topic: {cover_topic}. The authoritative COVER DESIGN BRIEF is: {cover_design} "
        "Render every named motif as visible cover craftsmanship — central emblem, border, binding, corners or page "
        "edges — rather than as tiny incidental decoration. Use ONLY motifs justified by that brief; do not substitute "
        "generic book imagery. No title, letters, numbers, readable marks, logos or real-person "
        "likeness. This is a closed cover only: no open pages, no two-page spread, no hands, no people, no UI, no "
        "photorealism and no 3D."
    )
    refs = [Reference(role="style_reference", path=world_style_anchor)] if valid_image(world_style_anchor) else []
    if not force and reusable_image(runner, project, stage, target, receipt, prompt, model, refs):
        runner.stage_reused(stage, target.name)
        return target
    started = runner.stage_start(stage)
    result = runner.image(stage, prompt, refs, model=model, destination=target)
    _write_image_receipt(project, "gemini_book_cover", result, prompt, refs, target, model)
    runner.stage_done(stage, started, target.name, sha256=sha256_file(target), model=model)
    return target


def stage_flow_prompt(
    runner: Runner,
    project: Path,
    content_project: Any,
    clip: str,
    narration: str,
    episode_plan: dict[str, Any] | None,
    world_style_plan: dict[str, Any],
    world_keyframe_description: str,
    topic: str,
    source_seconds: int, *, force: bool = False,
    character: CharacterContext | None = None,
) -> str:
    """Every Flow prompt comes from ChatGPT; none of them is hardcoded (§194)."""
    stage = f"flow_prompt_{'a' if clip == 'A' else 'b'}"
    target = project / "references" / f"flow_prompt_{'opening_a' if clip == 'A' else 'book_transition'}.txt"
    if not force and runner.state.done(stage) and target.is_file():
        runner.stage_reused(stage, target.name)
        return target.read_text(encoding="utf-8").strip()
    started = runner.stage_start(stage)
    if clip == "A":
        if character is None:
            raise StageFailure(stage, "FAILED_VALIDATION", "Clip A requires resolved CharacterContext.")
        if episode_plan is None:
            raise StageFailure(stage, "FAILED_VALIDATION", "Clip A requires episode direction.")
        preset_rules = (
            content_project.root / "visual_presets" / content_project.default_visual_preset / "README.md"
        ).read_text(encoding="utf-8")
        prompt = fill(
            resolve_prompt(content_project, "08_opening_video_prompt_writer.md"),
            OPENING_A_NARRATION=narration,
            EPISODE_PLAN=json.dumps(episode_plan, ensure_ascii=False),
            VISUAL_PRESET_RULES=preset_rules,
            CHARACTER_CONTEXT=_character_prompt_context(character),
        )
    else:
        prompt = fill(
            resolve_prompt(content_project, "09_book_transition_video_prompt_writer.md"),
            BOOK_TRANSITION_NARRATION=narration,
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
    force: bool = False,
    character: CharacterContext | None = None,
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
    receipt_duration = None
    if receipt.is_file():
        try:
            receipt_duration = int((load_json(receipt).get("requested") or {}).get("duration_seconds") or 0)
        except (OSError, ValueError, TypeError):
            pass
    # A recovered episode may need a longer opening source after real narration
    # alignment.  Never silently reuse a clip generated to an older, shorter
    # contract: trim_opening_clips correctly refuses to stretch it later.
    # Legacy receipts did not persist the requested source length.  They remain valid
    # resumable artifacts; only a *known*, conflicting contract forces regeneration.
    if (
        not force
        and valid_video(target)
        and receipt.is_file()
        and runner.state.done(stage)
        and receipt_duration in (None, 0, source_seconds)
    ):
        runner.stage_reused(stage, f"{filename} ({ffprobe_duration(target):.2f}s)")
        return target
    started = runner.stage_start(stage)

    if clip == "A":
        character = _coerce_character_context(character or content_project)
        uploads = build_flow_uploads(clip="A", character_sheet=character.sheet_path)
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


FLOW_POLICY_RETRY_LIMIT = 3
FLOW_POLICY_REPAIR_REQUEST = "FLOW_POLICY_REPAIR_REQUEST.json"


def is_flow_policy_rejection(failure: StageFailure) -> bool:
    """Only a provider-confirmed policy rejection may rewrite paid-for media inputs.

    Timeouts, credit limits and "unusual activity" are service/account conditions.  Altering
    an episode for those would hide the real fault and repeatedly spend credits without a
    reason.  Ordak preserves Flow's visible message in ``failure.message`` for the audit.
    """
    return failure.error_code == "flow_policy_violation"


def stage_flow_policy_repair_prompt(
    runner: Runner,
    project: Path,
    clip: str,
    original_prompt: str,
    flow_evidence: str,
    attempt: int,
) -> str:
    """Ask the text provider for one conservative, Flow-safe replacement prompt.

    The replacement deliberately removes the two common causes of an ambiguous policy
    rejection: a real person's identity/likeness and depictions of harm.  It does not invent
    a substitute video or silently switch providers.
    """
    stage = f"flow_policy_repair_{clip.lower()}_{attempt:02d}"
    target = project / "references" / f"flow_prompt_{clip.lower()}_policy_repair_{attempt:02d}.txt"
    started = runner.stage_start(stage)
    instruction = (
        "Rewrite the following Google Flow video prompt after Flow rejected it. Return ONLY one "
        "compact production prompt, no explanation or markdown. Preserve the supplied frame-to-frame "
        "camera transition and 2D illustrated-book treatment, but make it policy-safe: depict only "
        "fictional, non-identifiable adults; do not name, imitate or recreate any real person or public "
        "figure; do not include injury, fighting, weapons, threats, extremist symbols, logos, readable "
        "text, or claims about a real person. Keep all action calm, symbolic and non-violent. Do not tell "
        "Flow to upload references or change its settings.\n\n"
        f"Flow's visible rejection message: {flow_evidence[:500]}\n\n"
        f"Original prompt:\n{original_prompt[:8000]}"
    )
    repaired = runner.text(stage, instruction).strip()
    if len(repaired) < 40:
        raise StageFailure(stage, "FAILED_VALIDATION", "Policy-repair writer returned an unusably short Flow prompt.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(repaired + "\n", encoding="utf-8")
    runner.stage_done(
        stage,
        started,
        target.name,
        attempt=attempt,
        flow_evidence=flow_evidence[:300],
        prompt_sha256=sha256_text(repaired),
    )
    return repaired


def policy_safe_frame_prompt(original: str, flow_evidence: str, attempt: int) -> str:
    """A narrow image-stage rewind for Flow's two endpoint frames.

    Flow cannot tell us reliably whether it objected to text or a frame.  On a real policy
    rejection we therefore regenerate the *only* images sent to Flow (world keyframe and its
    composed book spread), keeping all body images and already-completed work intact.
    """
    return (
        f"{original.strip()}\n\n"
        "FLOW POLICY-SAFE FRAME REVISION: This endpoint must be a host-free hand-drawn subject-world scene. "
        "Include no recurring host, selected host, foreground person or character. Depict no combat, injury, "
        "weapons, threats, political/extremist symbols, readable text or brand marks. Keep the action "
        "calm, educational and non-violent while preserving the requested medium, composition and 9:16 frame. "
        f"This is revision {attempt}, prompted by Flow UI evidence: {flow_evidence[:300]}"
    )


def consume_flow_policy_repair_request(project: Path, clip: str) -> str | None:
    """Consume one explicit operator-confirmed policy-repair request, if present.

    Automatic recovery remains tied to Ordak's ``flow_policy_violation``.  This tiny durable
    hand-off exists for an older timed-out job where the operator saw Flow's rejection in the
    browser after Ordak had stopped polling; it is consumed once, audited in state, and cannot
    cause future resumes to keep rewriting media.
    """
    path = project / "pipeline" / FLOW_POLICY_REPAIR_REQUEST
    try:
        data = load_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or str(data.get("clip") or "").upper() != clip.upper():
        return None
    evidence = str(data.get("flow_evidence") or "operator confirmed a Flow policy rejection").strip()
    path.unlink(missing_ok=True)
    return evidence[:500]


def stage_flow_clip_with_policy_recovery(
    runner: Runner,
    project: Path,
    content_project: Any,
    clip: str,
    prompt: str,
    *,
    book_spread: Path | None,
    world_keyframe: Path | None,
    world_keyframe_prompt: str | None,
    world_style_anchor: Path | None,
    model: str,
    resolution: str,
    aspect_ratio: str,
    source_seconds: int,
    character: CharacterContext | None = None,
) -> Path:
    """Run a Flow clip and perform up to three audited policy-only rewinds.

    Each retry gets a fresh Ordak/Flow job.  For Clip B, the rewind regenerates both endpoint
    images — including its subject-specific closed cover — then retries with a rewritten prompt.  The
    maximum is intentional: repeated provider policy rejections must end as a clear failure,
    not an unbounded credit loop.
    """
    active_prompt = prompt
    active_book_spread = book_spread
    active_world_keyframe = world_keyframe
    requested_evidence = consume_flow_policy_repair_request(project, clip)
    if requested_evidence:
        recovery_stage = f"flow_policy_recovery_{clip.lower()}"
        runner.state.mark(
            recovery_stage,
            STATE_RUNNING,
            attempt=0,
            trigger="operator_confirmed_policy_rejection",
            flow_evidence=requested_evidence,
        )
        print(f"↻ {recovery_stage}: applying the operator-confirmed Flow policy repair before retrying.", flush=True)
        active_prompt = stage_flow_policy_repair_prompt(
            runner, project, clip, active_prompt, requested_evidence, 0
        )
        if clip == "B":
            if world_keyframe_prompt is None or world_style_anchor is None:
                raise StageFailure(recovery_stage, "FAILED_VALIDATION", "Clip B policy recovery is missing its endpoint-frame inputs.")
            safe_prompt = policy_safe_frame_prompt(world_keyframe_prompt, requested_evidence, 0)
            active_world_keyframe = stage_world_keyframe(
                runner, project, content_project, safe_prompt, world_style_anchor, force=True
            )
            active_book_spread = stage_topic_book_cover(
                runner, project, content_project, runner.state.state["topic"], world_style_anchor, force=True
            )
        runner.state.mark(recovery_stage, STATE_DONE, attempt=0, next_attempt=1)
    for attempt in range(1, FLOW_POLICY_RETRY_LIMIT + 1):
        try:
            return stage_flow_clip(
                runner, project, content_project, clip, active_prompt,
                book_spread=active_book_spread, world_keyframe=active_world_keyframe,
                model=model, resolution=resolution, aspect_ratio=aspect_ratio,
                source_seconds=source_seconds,
                character=character,
            )
        except StageFailure as failure:
            if not is_flow_policy_rejection(failure) or attempt == FLOW_POLICY_RETRY_LIMIT:
                if is_flow_policy_rejection(failure):
                    raise StageFailure(
                        failure.stage,
                        failure.state,
                        f"Flow rejected this clip after {attempt} policy-safe attempt(s); stopping to avoid further credit spend. "
                        f"Last reason: {failure.message}",
                        error_code=failure.error_code,
                    ) from failure
                raise

            recovery_stage = f"flow_policy_recovery_{clip.lower()}"
            runner.state.mark(
                recovery_stage,
                STATE_RUNNING,
                attempt=attempt,
                error_code=failure.error_code,
                flow_evidence=failure.message[:500],
            )
            print(
                f"↻ {recovery_stage}: Flow policy rejection detected; rewinding prompt and endpoint frames "
                f"for retry {attempt + 1}/{FLOW_POLICY_RETRY_LIMIT}.",
                flush=True,
            )
            active_prompt = stage_flow_policy_repair_prompt(
                runner, project, clip, active_prompt, failure.message, attempt
            )
            if clip == "B":
                if world_keyframe_prompt is None or world_style_anchor is None:
                    raise StageFailure(recovery_stage, "FAILED_VALIDATION", "Clip B policy recovery is missing its endpoint-frame inputs.")
                safe_prompt = policy_safe_frame_prompt(world_keyframe_prompt, failure.message, attempt)
                active_world_keyframe = stage_world_keyframe(
                    runner, project, content_project, safe_prompt, world_style_anchor, force=True
                )
                active_book_spread = stage_topic_book_cover(
                    runner, project, content_project, runner.state.state["topic"], world_style_anchor, force=True
                )
            runner.state.mark(recovery_stage, STATE_DONE, attempt=attempt, next_attempt=attempt + 1)
    raise AssertionError("policy recovery loop must return or raise")


def _beat_reference_stack(
    character: Any | None,
    beat: dict[str, Any],
    world_style_anchor: Path,
    world_keyframe: Path,
    previous: Path | None,
    operator_reference: Reference | None = None,
) -> list[Reference]:
    """§30 reference order: identity, style, world, then texture-only continuity.

    The character sheet is only sent when the hero is actually in the shot — sending it for a
    hero-free beat is how a character drifts into scenes that should not contain one.
    """
    references: list[Reference] = []
    if beat.get("hero_present", False):
        if character is None:
            raise CharacterSelectionError("A host-present beat requires CharacterContext.")
        character = _coerce_character_context(character)
        if valid_image(character.sheet_path):
            references.append(Reference(role="character_sheet", path=character.sheet_path))
    if valid_image(world_style_anchor):
        references.append(Reference(role="style_reference", path=world_style_anchor))
    if valid_image(world_keyframe):
        references.append(Reference(role="world_keyframe", path=world_keyframe))
    if operator_reference is not None:
        references.append(operator_reference)
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
    character: CharacterContext | None = None,
) -> str:
    if beat.get("hero_present", False):
        character = _coerce_character_context(character or content_project)
    beat_id = int(beat["beat_id"])
    target = project / "beats" / f"BEAT_{beat_id:03d}_PROMPT.md"
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
        CAPTION_LAYOUT_RULE=caption_layout_rule(world_style_plan),
        PREVIOUS_BEAT=(
            "No previous image — establish the world's texture and palette from the canonical anchors."
            if not any(ref.role == "previous_beat" for ref in references)
            else "Previous image is binding for the recurring frame language, material/edge treatment, "
            "inner illustration window, texture, palette and lighting. Follow the explicit caption-layout "
            "rule for whether its lower reserve is retained or filled. "
            "Never copy its composition, crop, camera angle, pose, subject placement, or focal object."
        ),
        ASPECT_RATIO="9:16",
        CHARACTER_CONTEXT=(
            _character_prompt_context(character)
            if beat.get("hero_present", False)
            else "HOST ABSENT. Do not depict or mention the selected recurring host."
        ),
    )
    cache_path = target.with_suffix(".inputs.json")
    cache_key = sha256_text(prompt)
    cached = load_json(cache_path) if cache_path.is_file() else {}
    if (target.is_file() and cached.get("input_sha256") == cache_key and
            cached.get("output_sha256") == sha256_file(target)):
        return target.read_text(encoding="utf-8").strip()
    # One-time migration for episodes created before writer-input caches existed. The
    # image receipt proves which exact prompt produced the paid image, so preserve it
    # and begin tracking the current writer inputs without calling a provider again.
    if target.is_file() and not cache_path.is_file() and runner.state.done(stage):
        existing = target.read_text(encoding="utf-8").strip()
        image_receipt = (
            project / "pipeline" / "provider_receipts" / f"gemini_beat_{beat_id:03d}.json"
        )
        try:
            recorded = load_json(image_receipt) if image_receipt.is_file() else {}
        except (OSError, ValueError):
            recorded = {}
        if recorded.get("prompt_sha256") == sha256_text(existing):
            save_json(
                cache_path,
                {"input_sha256": cache_key, "output_sha256": sha256_file(target)},
            )
            return existing
    text = runner.text(stage, prompt).strip()
    # Do not rely solely on a text-writer's summary: Gemini receives this direct final
    # constraint with every beat, including a composition that otherwise changes radically.
    text = f"{text} {episode_frame_contract(world_style_plan)}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n", encoding="utf-8")
    save_json(cache_path, {"input_sha256": cache_key, "output_sha256": sha256_file(target)})
    return text


def chatgpt_revision_guidance(
    runner: Runner,
    project: Path,
    beat_id: int,
    original_prompt: str,
    request: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Review the old image once, before regeneration, and durably reuse that advice."""
    instruction = str(request.get("instruction") or "").strip()
    relative_source = Path(str(request.get("source_image") or ""))
    source = (project / relative_source).resolve()
    try:
        source.relative_to(project.resolve())
    except ValueError as exc:
        raise StageFailure(
            f"beat_image_{beat_id:03d}", "FAILED_VALIDATION",
            "ChatGPT revision source must stay inside the episode project.",
        ) from exc
    if not instruction or not valid_image(source):
        raise StageFailure(
            f"beat_image_{beat_id:03d}", "FAILED_VALIDATION",
            "ChatGPT revision feedback requires both an operator note and the archived current image.",
        )

    fingerprint = sha256_text("\n".join((instruction, original_prompt, sha256_file(source))))
    receipt_path = project / "pipeline" / "provider_receipts" / f"chatgpt_revision_feedback_beat_{beat_id:03d}.json"
    try:
        cached = load_json(receipt_path) if receipt_path.is_file() else {}
    except (OSError, ValueError):
        cached = {}
    if cached.get("request_fingerprint") == fingerprint and str(cached.get("guidance") or "").strip():
        return str(cached["guidance"]).strip(), cached

    stage = f"beat_image_{beat_id:03d}_revision_feedback"
    response = runner._run(
        stage,
        "You are the pre-generation visual QC reviewer for a precise image revision. "
        "Inspect the attached current image and translate the operator's requested change into concise, concrete "
        "instructions for Gemini. Preserve every successful, unmentioned part of the image, including identity, "
        "style, composition, continuity, palette, and aspect ratio. Identify only visible changes needed to satisfy "
        "the operator. Return plain text instructions, with no JSON, preamble, score, or approval verdict.\n\n"
        f"OPERATOR REQUEST:\n{instruction}\n\nORIGINAL ART DIRECTION:\n{original_prompt}",
        provider="chatgpt",
        mode="chat",
        references=[Reference(role="current_image_to_revise", path=source)],
    )
    guidance = str(response.answer or "").strip()
    if not guidance:
        raise StageFailure(stage, "FAILED_VALIDATION", "ChatGPT returned empty revision guidance.")
    receipt = {
        "schema_version": 1,
        "beat_id": beat_id,
        "provider": "chatgpt",
        "phase": "pre_generation_feedback",
        "request_fingerprint": fingerprint,
        "source_image": str(relative_source),
        "source_sha256": sha256_file(source),
        "operator_instruction": instruction,
        "guidance": guidance,
        "created_at": utcnow(),
    }
    save_json(receipt_path, receipt)
    return guidance, receipt


def stage_body_images(
    runner: Runner,
    project: Path,
    content_project: Any,
    visual_plan: dict[str, Any],
    world_style_plan: dict[str, Any],
    world_style_anchor: Path,
    world_keyframe: Path,
    regenerate_beats: set[int] | None = None,
    revision_feedback: dict[int, str] | None = None,
    character: CharacterContext | None = None,
    chatgpt_revision_requests: dict[int, dict[str, Any]] | None = None,
    preserve_downstream_beats: bool = False,
) -> list[Path]:
    """One Gemini image per body beat, sequential because each uses the previous for continuity."""
    character = _coerce_character_context(character or content_project)
    beats = list(visual_plan.get("beats") or [])
    requested_regenerations = regenerate_beats or set()
    revision_feedback = revision_feedback or {}
    chatgpt_revision_requests = chatgpt_revision_requests or {}
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

            beat_character = character if beat.get("hero_present", False) else None
            references = _beat_reference_stack(
                beat_character, beat, world_style_anchor, world_keyframe, previous,
                operator_style_reference(project),
            )
            prompt = stage_beat_prompt(
                runner, project, content_project, beat, world_style_plan, references, beat_character
            )
            revision_path = project / "beats" / f"BEAT_{beat_id:03d}_PROMPT.revision.md"
            if revision_feedback.get(beat_id):
                prompt = f"{prompt.rstrip()}\n\nADMIN REVISION REQUEST (binding): {revision_feedback[beat_id].strip()}"
                revision_path.write_text(prompt + "\n", encoding="utf-8")
            elif revision_path.is_file():
                revision = revision_path.read_text(encoding="utf-8").strip()
                if revision.startswith(prompt.rstrip() + "\n\nADMIN REVISION REQUEST"):
                    prompt = revision
            receipt = project / "pipeline" / "provider_receipts" / f"gemini_beat_{beat_id:03d}.json"
            # Isolated revision is an explicit operator override of the normal continuity
            # cascade. Keep every unselected accepted image byte-for-byte, even when the
            # selected predecessor now has a different hash. Timeline/render descendants
            # still rebuild so the revised image reaches the delivered video.
            if (
                preserve_downstream_beats
                and beat_id not in requested_regenerations
                and valid_image(target)
            ):
                runner.state.mark(stage, STATE_REUSED, artifact=target.name, isolated_revision=True)
                produced.append(target)
                previous = target
                continue
            if beat_id not in requested_regenerations and reusable_image(runner, project, stage, target, receipt, prompt, model, references):
                runner.state.mark(stage, STATE_REUSED, artifact=target.name)
                print(f"↻ {stage} reused — {target.name}", flush=True)
                produced.append(target)
                previous = target
                continue

            started = time.perf_counter()
            runner.state.mark(stage, STATE_RUNNING)
            print(f"▶ {stage}", flush=True)
            revision_guidance_receipt = None
            if beat_id in chatgpt_revision_requests:
                guidance, revision_guidance_receipt = chatgpt_revision_guidance(
                    runner, project, beat_id, prompt, chatgpt_revision_requests[beat_id]
                )
                prompt = (
                    f"{prompt.rstrip()}\n\nCHATGPT PRE-GENERATION QC GUIDANCE (binding):\n{guidance}\n\n"
                    "Apply this guidance in the replacement while preserving all unmentioned successful details."
                )
            image_options = {"skip_content_qc": True} if revision_guidance_receipt is not None else {}
            result = runner.image(
                stage, prompt, references, model=model, destination=target,
                **image_options,
            )
            if revision_guidance_receipt is not None:
                result.generation_receipt = {
                    **(result.generation_receipt or {}),
                    "pre_generation_chatgpt_feedback": {
                        "request_fingerprint": revision_guidance_receipt["request_fingerprint"],
                        "source_sha256": revision_guidance_receipt["source_sha256"],
                        "post_generation_chatgpt_qc": "skipped",
                    },
                }
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


TRANSITION_EDITOR_STYLES = {
    "cuts": ("cut",),
    "cut_fade": ("cut", "fade"),
    "cut_fade_dissolve": ("cut", "fade", "dissolve"),
}

TRANSITION_EDITOR_TYPES = (
    "cut", "fade", "dissolve", "fadeblack", "fadewhite", "smoothleft",
    "smoothright", "wipeleft", "wiperight", "slideleft", "slideright",
)


def transition_editor_settings(value: Any) -> dict[str, Any]:
    """Normalize the frozen policy before deciding image boundaries."""
    raw = value if isinstance(value, dict) else {}
    style = str(raw.get("image_transition_style") or "cut_fade_dissolve")
    if style not in TRANSITION_EDITOR_STYLES:
        style = "cut_fade_dissolve"
    try:
        seconds = float(raw.get("transition_seconds", .28))
    except (TypeError, ValueError):
        seconds = .28
    default_type = str(raw.get("transition_default_type") or "fade").lower().strip()
    if default_type not in TRANSITION_EDITOR_TYPES:
        default_type = "fade"
    # Keep the old image-policy vocabulary available to the Motion Director, but the
    # dedicated transition editor may choose any deliberately exposed timeline effect.
    return {
        "ai_enabled": bool(raw.get("transition_ai_enabled", False)),
        "allowed": TRANSITION_EDITOR_TYPES,
        "default_type": default_type,
        "seconds": 0.0 if default_type == "cut" else round(min(.45, max(.08, seconds)), 3),
    }


def stage_transition_direction(
    runner: Runner,
    project: Path,
    content_project: Any,
    visual_plan: dict[str, Any],
    images: list[Path],
    *,
    settings: dict[str, Any] | None = None,
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
    policy = transition_editor_settings(settings)
    manual = {
        (str(item.get("from_beat_id") or ""), str(item.get("to_beat_id") or "")): item
        for item in ((settings or {}).get("transition_overrides") or [])
        if isinstance(item, dict)
    }
    for index in range(1, len(beats)):
        previous, current = beats[index - 1], beats[index]
        boundary = (str(previous["beat_id"]), str(current["beat_id"]))
        if boundary in manual:
            item = manual[boundary]
            decisions.append({
                "from_beat_id": int(previous["beat_id"]), "to_beat_id": int(current["beat_id"]),
                "transition_in": str(item.get("type") or "fade"), "transition_seconds": float(item.get("duration") or 0),
                "reason": "Manual Studio override.", "source": "manual",
            })
            continue
        if not policy["ai_enabled"]:
            decisions.append({
                "from_beat_id": int(previous["beat_id"]), "to_beat_id": int(current["beat_id"]),
                "transition_in": policy["default_type"], "transition_seconds": policy["seconds"],
                "reason": "Frozen default transition policy (AI selection disabled).", "source": "default",
            })
            continue
        prompt = fill(
            resolve_prompt(content_project, "10_transition_editor.md"),
            PREVIOUS_BEAT=json.dumps(previous, ensure_ascii=False),
            NEXT_BEAT=json.dumps(current, ensure_ascii=False),
            ALLOWED_TRANSITIONS="|".join(policy["allowed"]),
            SOFT_TRANSITION_SECONDS=f"{policy['seconds']:.2f}",
        )
        raw = runner.json(
            f"{stage}_{index:03d}", prompt,
            references=[
                Reference(role="previous_beat_for_edit", path=images[index - 1]),
                Reference(role="next_beat_for_edit", path=images[index]),
            ],
        )
        transition = str(raw.get("transition_in") or "").lower().strip() if isinstance(raw, dict) else ""
        try:
            seconds = float(raw.get("transition_seconds")) if isinstance(raw, dict) else 0.0
        except (TypeError, ValueError):
            seconds = 0.0
        expected_seconds = 0.0 if transition == "cut" else policy["seconds"]
        if transition not in policy["allowed"] or abs(seconds - expected_seconds) > .005:
            raise StageFailure(stage, "FAILED_VALIDATION", f"Transition editor returned an unsupported decision for boundary {index}->{index + 1}.")
        decision = {
            "from_beat_id": int(previous["beat_id"]), "to_beat_id": int(current["beat_id"]),
            "transition_in": transition, "transition_seconds": round(seconds, 3),
            "reason": str(raw.get("reason") or "").strip()[:400],
            "source": "ai",
        }
        decisions.append(decision)
        runner.stage_progress(stage, ["🎞️ Picture edit in progress", f"📍 Boundaries: {len(decisions)}/{len(beats) - 1}", f"✦ Latest: {transition} · {seconds:.2f}s"])
    payload = {"schema_version": 2, "ai_selection_enabled": policy["ai_enabled"], "decisions": decisions, "created_at": utcnow()}
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
    opening_speed_tolerance: float,
    duration: "DurationTarget",
    style_policy: str,
    style_id: str,
    style_hint: str,
    image_qc_correction_policy: str = "0",
    beat_image_qc_disabled: bool = False,
    character_mode: str = "auto",
    character_id: str | None = None,
) -> dict[str, Any]:
    """The immutable launch contract (§59, §79). An existing file is never rewritten."""
    path = project / "launch" / "LAUNCH_REQUEST.json"
    if path.is_file():
        return load_json(path)
    data = {
        "schema_version": 3,
        "content_project": content_project_id,
        "character": {
            "mode": character_mode,
            **({"character_id": character_id} if character_id else {}),
        },
        "created_at": utcnow(),
        "providers": {"text": "chatgpt", "image": "gemini", "video": "flow", "voice": "elevenlabs_web"},
        "image_generation": {
            "model": normalize_gemini_model(gemini_model),
            "quality": "best",
            "qc_correction_policy": image_qc_correction_policy,
            "beat_qc_disabled": bool(beat_image_qc_disabled),
            "extended_thinking_required": True,
        },
        "video_generation": {
            "model": normalize_flow_model(flow_model),
            "resolution": flow_resolution,
            "opening_a_source_seconds": opening_a_seconds,
            "opening_b_source_seconds": opening_b_seconds,
            "opening_speed_tolerance": opening_speed_tolerance,
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
    global WORLD_STYLES_ROOT, BOOK_TEMPLATES_ROOT
    parser = argparse.ArgumentParser(description="Q Station pipeline (production path)")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--content-project", default="q_station")
    parser.add_argument("--character-mode", choices=("auto", "manual"), default="auto")
    parser.add_argument("--character-id", default="")
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
    parser.add_argument("--beat-feedback-json", type=Path, help="Revision feedback keyed by numeric beat id.")
    parser.add_argument(
        "--chatgpt-revision-feedback-json",
        type=Path,
        help="One-shot ChatGPT review requests for archived beat images before Gemini regeneration.",
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
        "--opening-speed-tolerance",
        type=float,
        default=None,
        help="Max fraction a silent opening clip may be slowed to meet narration (default 0.1).",
    )
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
        "--chatgpt-fallback-mode",
        choices=("approval", "auto"),
        default="approval",
        help="Use Gemini after a ChatGPT/Ordak failure automatically, or pause for panel approval.",
    )
    parser.add_argument(
        "--image-qc-correction-policy",
        choices=("0", "1", "2", "strict"),
        default="0",
        help=(
            "Correct non-blocking image-QC findings 0, 1 or 2 times; strict makes "
            "three total attempts and fails unless one candidate is fully clean."
        ),
    )
    parser.add_argument(
        "--disable-beat-image-qc",
        action="store_true",
        help="Never upload generated body-beat images to ChatGPT for visual QC.",
    )
    parser.add_argument(
        "--regenerate-beats",
        default="",
        help="Comma-separated body beat IDs to regenerate even when their existing files are valid (for example: 1,9,13).",
    )
    parser.add_argument(
        "--preserve-downstream-beats",
        action="store_true",
        help="Keep every unselected beat image unchanged during an isolated beat revision.",
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
    if args.preserve_downstream_beats and len(regenerate_beats) != 1:
        parser.error("--preserve-downstream-beats requires exactly one --regenerate-beats ID")
    revision_feedback: dict[int, str] = {}
    if args.beat_feedback_json:
        try:
            raw_feedback = load_json(args.beat_feedback_json)
            revision_feedback = {int(key): str(value).strip() for key, value in raw_feedback.items() if str(value).strip()}
        except (OSError, ValueError, TypeError):
            parser.error("--beat-feedback-json must be a JSON object keyed by beat number")
    chatgpt_revision_requests: dict[int, dict[str, Any]] = {}
    if args.chatgpt_revision_feedback_json:
        try:
            raw_requests = load_json(args.chatgpt_revision_feedback_json)
            if not isinstance(raw_requests, dict):
                raise ValueError("request root must be an object")
            for key, value in raw_requests.items():
                beat_id = int(key)
                if beat_id < 1 or not isinstance(value, dict):
                    raise ValueError("each beat request must be an object")
                instruction = str(value.get("instruction") or "").strip()
                source_image = str(value.get("source_image") or "").strip()
                if not instruction or not source_image:
                    raise ValueError("each request needs instruction and source_image")
                chatgpt_revision_requests[beat_id] = {
                    "instruction": instruction,
                    "source_image": source_image,
                }
        except (OSError, ValueError, TypeError):
            parser.error("--chatgpt-revision-feedback-json must map beat IDs to instruction/source_image objects")
    if set(chatgpt_revision_requests) - regenerate_beats:
        parser.error("ChatGPT revision feedback may target only explicitly regenerated beats")

    load_dotenv(ROOT / os.getenv("YT_ENV_FILE", ".env"), override=False)

    content_project = load_content_project(args.content_project)
    WORLD_STYLES_ROOT = content_project.root / "world_styles"
    BOOK_TEMPLATES_ROOT = content_project.root / "book_templates"
    validate_provider_locks(content_project)
    validate_content_project(content_project)

    project = ROOT / "videos" / f"{args.video_id}_{video_slug(args.topic)}"
    project.mkdir(parents=True, exist_ok=True)
    project_marker = project / "PROJECT.md"
    if not project_marker.is_file():
        project_marker.write_text(
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

    launch_path = project / "launch" / "LAUNCH_REQUEST.json"
    existed_before_launch = launch_path.is_file()
    existing_launch = load_json(launch_path) if existed_before_launch else {}
    if args.opening_speed_tolerance is not None:
        speed_tolerance = float(args.opening_speed_tolerance)
    else:
        speed_tolerance = 0.1
        try:
            brief_candidate = (load_json(brief_target).get("_qh") or {}).get("opening_speed_tolerance")
            if brief_candidate is not None and str(brief_candidate) != "":
                speed_tolerance = float(brief_candidate)
        except (OSError, ValueError, TypeError):
            pass
        if speed_tolerance == 0.1:
            try:
                defaults = (content_project.config.get("defaults") or {})
                if defaults.get("opening_speed_tolerance") is not None:
                    speed_tolerance = float(defaults["opening_speed_tolerance"])
            except (TypeError, ValueError):
                pass
    if not 0 <= speed_tolerance <= 0.5:
        parser.error("--opening-speed-tolerance must be within 0..0.5")
    is_legacy_run = bool(
        existed_before_launch
        and existing_launch.get("content_project") == "question_harvest"
        and "character" not in existing_launch
        and "character_resolution" not in existing_launch
    )
    requested_mode = args.character_mode
    requested_character_id = str(args.character_id or "").strip() or None
    if requested_mode == "manual" and not requested_character_id:
        parser.error("--character-id is required when --character-mode=manual")
    launch = ensure_launch_request(
        project,
        content_project.project_id,
        args.gemini_model,
        args.flow_model,
        args.flow_resolution,
        args.opening_a_seconds,
        args.opening_b_seconds,
        speed_tolerance,
        duration,
        style_policy,
        requested_style_id,
        args.world_style_hint,
        args.image_qc_correction_policy,
        args.disable_beat_image_qc,
        requested_mode,
        requested_character_id,
    )
    registry_file = character_registry_path(content_project)
    if registry_file is None:
        raise RuntimeError("Q Station character registry is not configured.")
    preflight_registry = load_character_registry(registry_file)
    launch_mode, launch_character_id = parse_character_request(launch.get("character"))
    if launch_mode == "manual":
        preflight_registry.get(str(launch_character_id))
    persisted_character = launch.get("character_resolution")
    persisted_file = project / "creative" / "CHARACTER_RESOLUTION.json"
    if not isinstance(persisted_character, dict) and persisted_file.is_file():
        candidate = load_json(persisted_file)
        persisted_character = candidate if isinstance(candidate, dict) else None
    if isinstance(persisted_character, dict) and persisted_character.get("resolved_character_id"):
        preflight_registry.get(str(persisted_character["resolved_character_id"]))
    state = QHState(project, args.video_id, args.topic)
    notifier = PipelineNotifier(
        video_id=args.video_id,
        topic=args.topic,
        state_path=project / "pipeline" / "TELEGRAM_NOTIFICATION_STATE.json",
    )

    video_generation = launch.get("video_generation", {})
    flow_model = normalize_flow_model(video_generation.get("model") or args.flow_model)
    flow_resolution = str(video_generation.get("resolution") or args.flow_resolution)
    opening_a_seconds = int(video_generation.get("opening_a_source_seconds") or args.opening_a_seconds)
    opening_b_seconds = int(video_generation.get("opening_b_source_seconds") or args.opening_b_seconds)

    with OrdakJobs() as jobs:
        runner = Runner(
            jobs,
            notifier,
            state,
            chatgpt_fallback_mode=args.chatgpt_fallback_mode,
            image_qc_correction_policy=args.image_qc_correction_policy,
            beat_image_qc_disabled=args.disable_beat_image_qc,
        )
        current_stage = "preflight"
        try:
            # Fail before spending anything if the browser stack is not usable (§65).
            jobs.require_ready(["chatgpt", "gemini", "flow"])
            brief = build_brief(project, args.topic, content_project, duration)

            draft = stage_script(runner, project, content_project, brief, duration)
            plan = stage_retention(runner, project, content_project, brief, draft, duration)
            _resolution, character = stage_character_resolution(
                runner, project, content_project, args.topic, brief, plan, launch,
                is_legacy_run=is_legacy_run,
            )
            episode_plan = stage_episode_director(
                runner, project, content_project, args.topic, brief, plan, character
            )
            world_style_plan = stage_world_style_director(
                runner, project, content_project, args.topic, plan, directive
            )
            brief_settings = load_json(project / "launch" / "CREATIVE_BRIEF.json")
            qh_settings = brief_settings.get("_qh") if isinstance(brief_settings.get("_qh"), dict) else {}
            reserve_subtitle_space = bool(qh_settings.get("reserve_subtitle_space", True))
            original_reserve = str(
                world_style_plan.get("style_subtitle_reserve")
                or world_style_plan.get("subtitle_reserve")
                or "a calm lower caption field occupying only the bottom 8–10% of the frame"
            )
            world_style_plan = {
                **world_style_plan,
                "style_subtitle_reserve": original_reserve,
                "reserve_subtitle_space": reserve_subtitle_space,
                "subtitle_reserve": (
                    original_reserve
                    if reserve_subtitle_space
                    else "no dedicated caption reserve; the scene and matching texture fill the complete illustration height"
                ),
            }
            save_json(project / "creative" / "WORLD_STYLE_PLAN.json", world_style_plan)
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
                runner, project, content_project, plan, episode_plan, world_style_plan, body_seconds, character
            )
            write_visual_beats_markdown(project, plan, visual_plan)

            keyframe_prompt = stage_world_keyframe_prompt(
                runner, project, content_project, plan, world_style_plan
            )
            world_keyframe = stage_world_keyframe(
                runner, project, content_project, keyframe_prompt, world_style_anchor
            )
            stage_book_design_sheet(runner, project, content_project)
            # Clip B now begins on an episode-specific closed cover.  The old spread remains
            # available for legacy episodes, but is never a Flow start frame for new work.
            book_cover = stage_topic_book_cover(
                runner, project, content_project, args.topic, world_style_anchor
            )

            clip_a_prompt = stage_flow_prompt(
                runner, project, content_project, "A", plan["opening_question_spark"],
                episode_plan, world_style_plan, keyframe_prompt, args.topic, opening_a_seconds,
                character=character,
            )
            clip_b_prompt = stage_flow_prompt(
                runner, project, content_project, "B", plan["book_transition"],
                None, world_style_plan, keyframe_prompt, args.topic, opening_b_seconds,
            )

            # The body images depend only on the plan, the style anchor and the world
            # keyframe, so they run before the Flow clips. Flow is the stage most likely to
            # be unavailable for reasons outside this host — quota, high demand, or a
            # regional block — and doing the image work first means an outage there costs a
            # resume rather than the whole visual half.
            body_images = stage_body_images(
                runner, project, content_project, visual_plan, world_style_plan,
                world_style_anchor, world_keyframe, regenerate_beats,
                revision_feedback,
                character,
                chatgpt_revision_requests=chatgpt_revision_requests,
                preserve_downstream_beats=args.preserve_downstream_beats,
            )
            stage_transition_direction(
                runner,
                project,
                content_project,
                visual_plan,
                body_images,
                settings=brief_settings.get("_motion") if isinstance(brief_settings.get("_motion"), dict) else None,
                force=bool(regenerate_beats),
            )

            clip_a = stage_flow_clip_with_policy_recovery(
                runner, project, content_project, "A", clip_a_prompt,
                book_spread=None, world_keyframe=None,
                world_keyframe_prompt=None, world_style_anchor=None,
                model=flow_model, resolution=flow_resolution, aspect_ratio=args.aspect_ratio,
                source_seconds=opening_a_seconds,
                character=character,
            )
            clip_b = stage_flow_clip_with_policy_recovery(
                runner, project, content_project, "B", clip_b_prompt,
                book_spread=book_cover, world_keyframe=world_keyframe,
                world_keyframe_prompt=keyframe_prompt, world_style_anchor=world_style_anchor,
                model=flow_model, resolution=flow_resolution, aspect_ratio=args.aspect_ratio,
                source_seconds=opening_b_seconds,
            )

            state.mark("qh_visual_complete", STATE_DONE, body_images=len(body_images))
            state.finish()
            # This runner is also invoked directly during recovery.  Without an
            # explicit terminal notification, Telegram appears to go silent after
            # the final Flow clip even though the visual phase finished normally.
            # The wrapper may continue with narration/render afterwards, but this
            # checkpoint must stand on its own for both entry points.
            if notifier is not None:
                notifier.send(
                    "Visual phase complete",
                    [
                        "✅ Script, images, transitions and Flow clips are complete",
                        f"🖼 Body images: {len(body_images)}",
                        "▶ Next: narration, timing, render and delivery",
                    ],
                )
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
            runner.stage_failed(current_stage, failure, runner.stage_started_at.get(current_stage, time.perf_counter()))
            print(f"PIPELINE {failure.state}: {failure.message}", file=sys.stderr, flush=True)
            return 3 if failure.needs_human else 2
        except OrdakJobError as exc:
            failure = StageFailure(current_stage, exc.pipeline_state, exc.message, error_code=exc.error_code)
            runner.stage_failed(current_stage, failure, runner.stage_started_at.get(current_stage, time.perf_counter()))
            print(f"PIPELINE {failure.state}: {failure.message}", file=sys.stderr, flush=True)
            return 3 if failure.needs_human else 2


if __name__ == "__main__":
    sys.exit(main())

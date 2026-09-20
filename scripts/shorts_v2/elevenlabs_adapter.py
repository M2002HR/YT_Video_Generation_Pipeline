"""Model-aware ElevenLabs web contracts and result ownership.

The browser-specific runner supplies observed DOM data.  This module makes all
capability and ownership decisions deterministic and provider-free-testable.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from .contracts import ContractError, TTSModel, canonical_tts_model


CAPABILITY_SCHEMA_VERSION = 1
PARTIAL_SUFFIXES = frozenset({".crdownload", ".part", ".partial", ".tmp"})
AUDIO_SUFFIXES = frozenset({".mp3", ".wav", ".m4a", ".flac", ".ogg"})


class AdapterErrorCode(StrEnum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    UI_DRIFT = "UI_DRIFT"
    MODEL_IDENTITY_MISMATCH = "MODEL_IDENTITY_MISMATCH"
    VOICE_IDENTITY_MISMATCH = "VOICE_IDENTITY_MISMATCH"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    TEXT_MISMATCH = "TEXT_MISMATCH"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    RESULT_IDENTITY_UNPROVEN = "RESULT_IDENTITY_UNPROVEN"
    DOWNLOAD_IDENTITY_UNPROVEN = "DOWNLOAD_IDENTITY_UNPROVEN"
    PARTIAL_DOWNLOAD = "PARTIAL_DOWNLOAD"


class ElevenLabsAdapterError(ContractError):
    def __init__(self, code: AdapterErrorCode, message: str, *, evidence: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.evidence = dict(evidence or {})
        super().__init__(f"{code.value}: {message}")


@dataclass(frozen=True)
class CapabilityProbe:
    observed_model: str
    observed_voice: str
    numeric_controls: frozenset[str]
    stability_modes: frozenset[str]
    speaker_boost_available: bool
    editor_kind: str
    observed_at: str

    def receipt(self) -> dict[str, Any]:
        return {
            "schema_version": CAPABILITY_SCHEMA_VERSION,
            "observed_model": self.observed_model,
            "observed_voice": self.observed_voice,
            "numeric_controls": sorted(self.numeric_controls),
            "stability_modes": sorted(self.stability_modes),
            "speaker_boost_available": self.speaker_boost_available,
            "editor_kind": self.editor_kind,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True)
class ExecutionPlan:
    model: TTSModel
    execution_mode: str
    numeric_settings: dict[str, float]
    stability_mode: str | None
    speaker_boost: bool | None
    inactive_settings: dict[str, Any]


def normalized_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def text_fingerprint(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _number(settings: Mapping[str, Any], key: str, low: float, high: float) -> float | None:
    value = settings.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ElevenLabsAdapterError(AdapterErrorCode.CAPABILITY_MISMATCH, f"{key} must be numeric")
    result = float(value)
    if not low <= result <= high:
        raise ElevenLabsAdapterError(AdapterErrorCode.CAPABILITY_MISMATCH, f"{key} must be between {low} and {high}")
    return result


def build_execution_plan(requested: Mapping[str, Any], probe: CapabilityProbe) -> ExecutionPlan:
    model = canonical_tts_model(requested.get("tts_model") or requested.get("model"))
    expected_label = "Eleven v3" if model is TTSModel.ELEVEN_V3 else "Eleven Multilingual v2"
    if normalized_label(probe.observed_model) != normalized_label(expected_label):
        raise ElevenLabsAdapterError(
            AdapterErrorCode.MODEL_IDENTITY_MISMATCH,
            f"requested {expected_label!r}, observed {probe.observed_model!r}",
            evidence=probe.receipt(),
        )
    numeric: dict[str, float] = {}
    inactive: dict[str, Any] = {}
    stability_mode: str | None = None
    speaker_boost: bool | None = None
    if model is TTSModel.ELEVEN_V3:
        for key in ("speed", "stability", "similarity", "style", "speaker_boost"):
            if requested.get(key) is not None:
                inactive[key] = requested[key]
        stability_mode = str(requested.get("stability_mode") or "Natural").strip().title()
        if stability_mode not in {"Creative", "Natural", "Robust"}:
            raise ElevenLabsAdapterError(AdapterErrorCode.CAPABILITY_MISMATCH, "v3 stability_mode must be Creative, Natural, or Robust")
        if stability_mode.casefold() in probe.stability_modes:
            pass
        elif "stability" in probe.numeric_controls:
            # The current web UI has also represented the same three named
            # modes as a 0/.5/1 slider. This is a categorical adapter mapping,
            # not reuse of a Multilingual-v2 free numeric request.
            numeric["stability"] = {"Creative": 0.0, "Natural": 0.5, "Robust": 1.0}[stability_mode]
            inactive["stability_mode_control"] = "categorical_numeric_slider"
        else:
            raise ElevenLabsAdapterError(
                AdapterErrorCode.UI_DRIFT,
                f"v3 stability mode {stability_mode!r} is not exposed by the current UI",
                evidence=probe.receipt(),
            )
        if any(name in probe.numeric_controls for name in ("speed", "similarity", "style")):
            # Extra controls are observable, but never silently become part of a
            # request until the versioned capability contract is updated.
            inactive["unexpected_ui_controls"] = sorted(probe.numeric_controls)
        execution_mode = "expressive_v3"
    else:
        ranges = {"speed": (0.7, 1.2), "stability": (0.0, 1.0), "similarity": (0.0, 1.0), "style": (0.0, 1.0)}
        for key, (low, high) in ranges.items():
            value = _number(requested, key, low, high)
            if value is not None:
                if key not in probe.numeric_controls:
                    raise ElevenLabsAdapterError(
                        AdapterErrorCode.UI_DRIFT,
                        f"requested v2 control {key!r} is absent",
                        evidence=probe.receipt(),
                    )
                numeric[key] = value
        if requested.get("stability_mode") is not None:
            inactive["stability_mode"] = requested["stability_mode"]
        if requested.get("speaker_boost") is not None:
            speaker_boost = bool(requested["speaker_boost"])
            if speaker_boost and not probe.speaker_boost_available:
                raise ElevenLabsAdapterError(AdapterErrorCode.UI_DRIFT, "requested Speaker Boost is absent", evidence=probe.receipt())
            if not probe.speaker_boost_available:
                inactive["speaker_boost"] = speaker_boost
                speaker_boost = None
        execution_mode = "optimized_v2"
    if probe.editor_kind not in {"textarea", "contenteditable"}:
        raise ElevenLabsAdapterError(AdapterErrorCode.UI_DRIFT, "no supported TTS editor is visible", evidence=probe.receipt())
    return ExecutionPlan(model, execution_mode, numeric, stability_mode, speaker_boost, inactive)


@dataclass(frozen=True)
class ResultSnapshot:
    identities: frozenset[str]
    busy: bool
    download_enabled: bool


def result_snapshot(raw: Mapping[str, Any]) -> ResultSnapshot:
    identities = frozenset(str(value).strip() for value in raw.get("result_identities", []) if str(value).strip())
    return ResultSnapshot(identities, bool(raw.get("busy")), bool(raw.get("downloads")))


def bind_new_result(baseline: ResultSnapshot, current: ResultSnapshot) -> str | None:
    new_ids = sorted(current.identities - baseline.identities)
    if len(new_ids) > 1:
        raise ElevenLabsAdapterError(
            AdapterErrorCode.RESULT_IDENTITY_UNPROVEN,
            f"multiple new result identities appeared: {new_ids}",
        )
    if len(new_ids) == 1:
        return new_ids[0]
    if current.download_enabled and not current.busy:
        raise ElevenLabsAdapterError(
            AdapterErrorCode.RESULT_IDENTITY_UNPROVEN,
            "a download is available but no result identity can bind it to this request",
        )
    return None


def validate_download_candidate(path: Path, *, attempt_root: Path, started_at: float, minimum_bytes: int = 1024) -> Path:
    root = attempt_root.resolve()
    candidate = path.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ElevenLabsAdapterError(AdapterErrorCode.DOWNLOAD_IDENTITY_UNPROVEN, "download escaped the dedicated attempt directory") from exc
    if candidate.suffix.casefold() in PARTIAL_SUFFIXES or any(candidate.name.casefold().endswith(suffix) for suffix in PARTIAL_SUFFIXES):
        raise ElevenLabsAdapterError(AdapterErrorCode.PARTIAL_DOWNLOAD, "partial browser download is not consumable")
    if candidate.suffix.casefold() not in AUDIO_SUFFIXES:
        raise ElevenLabsAdapterError(AdapterErrorCode.DOWNLOAD_IDENTITY_UNPROVEN, "download has an unsupported audio extension")
    if not candidate.is_file() or candidate.stat().st_size < minimum_bytes:
        raise ElevenLabsAdapterError(AdapterErrorCode.DOWNLOAD_IDENTITY_UNPROVEN, "download is missing or unexpectedly small")
    if candidate.stat().st_mtime < started_at - 0.5:
        raise ElevenLabsAdapterError(AdapterErrorCode.DOWNLOAD_IDENTITY_UNPROVEN, "download predates the bound result request")
    return candidate


class AttemptStateMachine:
    ORDER = (
        "OPEN", "VERIFY_SESSION", "SELECT_MODEL", "SELECT_VOICE", "PROBE_CAPABILITIES",
        "APPLY_EFFECTIVE_SETTINGS", "VERIFY_SETTINGS", "ENTER_COMPILED_TEXT", "VERIFY_TEXT",
        "CAPTURE_RESULT_BASELINE", "SUBMIT_ONCE", "ACKNOWLEDGED", "WAIT_FOR_BOUND_RESULT",
        "DOWNLOAD_BOUND_RESULT", "VERIFY_DECODE_AND_IDENTITY", "COMMIT_RECEIPT",
    )

    def __init__(self) -> None:
        self.index = -1

    @property
    def current(self) -> str | None:
        return self.ORDER[self.index] if self.index >= 0 else None

    def advance(self, state: str) -> None:
        wanted = self.index + 1
        if wanted >= len(self.ORDER) or self.ORDER[wanted] != state:
            raise ElevenLabsAdapterError(
                AdapterErrorCode.SUBMISSION_UNCERTAIN,
                f"invalid adapter transition {self.current!r} -> {state!r}",
            )
        self.index = wanted

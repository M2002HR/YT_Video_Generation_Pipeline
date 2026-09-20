"""Strict, versioned settings and artifact contracts for Shorts V2.2."""
from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Mapping


SCHEMA_VERSION = 1
DESIGN_VERSION = "2.2"
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class ContractError(ValueError):
    """An input is unsafe, ambiguous, incomplete, or incompatible."""


class EditingEngine(StrEnum):
    LEGACY = "legacy"
    SHORTS_V2 = "shorts_v2"


class TTSModel(StrEnum):
    ELEVEN_V3 = "eleven_v3"
    ELEVEN_MULTILINGUAL_V2 = "eleven_multilingual_v2"


class VoiceExecution(StrEnum):
    EXPRESSIVE_V3 = "expressive_v3"
    OPTIMIZED_V2 = "optimized_v2"


class MediaReview(StrEnum):
    OFF = "off"
    REPORT = "report"
    STRICT = "strict"


class EditingObservation(StrEnum):
    AUTO_ONCE = "auto_once"
    OFF = "off"


MODEL_LABELS: dict[TTSModel, str] = {
    TTSModel.ELEVEN_V3: "Eleven v3",
    TTSModel.ELEVEN_MULTILINGUAL_V2: "Eleven Multilingual v2",
}
MODEL_ALIASES = {
    "eleven_v3": TTSModel.ELEVEN_V3,
    "eleven v3": TTSModel.ELEVEN_V3,
    "eleven_multilingual_v2": TTSModel.ELEVEN_MULTILINGUAL_V2,
    "eleven multilingual v2": TTSModel.ELEVEN_MULTILINGUAL_V2,
}
EXECUTION_FOR_MODEL = {
    TTSModel.ELEVEN_V3: VoiceExecution.EXPRESSIVE_V3,
    TTSModel.ELEVEN_MULTILINGUAL_V2: VoiceExecution.OPTIMIZED_V2,
}

DEFAULT_QUALITY: dict[str, Any] = {
    "media_review": MediaReview.OFF.value,
    "media_review_scope": "all_visual_assets",
    "media_auto_corrections": 0,
    "editorial_render_review": "off",
    "audio_performance_review": "off",
    "technical_validation": True,
    "text_contract_review": True,
    "editing_observation": EditingObservation.AUTO_ONCE.value,
    "observation_failure_policy": "safe_geometry_fallback",
    "human_approval_required": False,
}
QUALITY_FIELDS = frozenset(DEFAULT_QUALITY)
VOICE_FIELDS = frozenset({
    "tts_model", "transport", "execution_mode", "voice_id", "voice_label",
    "candidate_count", "manual_take_selection", "v2", "v3", "manual_locks",
})
SHORTS_FIELDS = frozenset({
    "schema_version", "design_version", "editing_engine", "voice", "quality",
    "recipe_version", "locks", "test_fixture_mode",
})


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise ContractError(f"{path} contains unknown field(s): {', '.join(unknown)}")


def _finite_tree(value: Any, path: str = "request") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError(f"{path} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _finite_tree(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _finite_tree(item, f"{path}[{index}]")
        return
    raise ContractError(f"{path} contains unsupported value type {type(value).__name__}")


def stable_id(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not ID_PATTERN.fullmatch(result):
        raise ContractError(f"{field} must match {ID_PATTERN.pattern}")
    return result


def canonical_tts_model(value: Any) -> TTSModel:
    key = re.sub(r"\s+", " ", str(value or "").strip().casefold())
    try:
        return MODEL_ALIASES[key]
    except KeyError as exc:
        raise ContractError(
            "tts_model must be exactly eleven_v3 or eleven_multilingual_v2; "
            "automatic, unknown, or fallback models are forbidden"
        ) from exc


def _normalize_voice(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ContractError("shorts_v2.voice must be an object")
    _reject_unknown(raw, VOICE_FIELDS, "shorts_v2.voice")
    model = canonical_tts_model(raw.get("tts_model"))
    expected_execution = EXECUTION_FOR_MODEL[model]
    requested_execution = str(raw.get("execution_mode") or expected_execution.value)
    if requested_execution != expected_execution.value:
        raise ContractError(
            f"{model.value} requires execution_mode={expected_execution.value}; "
            "model fallback or cross-model markup is forbidden"
        )
    transport = str(raw.get("transport") or "elevenlabs_web")
    if transport != "elevenlabs_web":
        raise ContractError("Shorts V2 voice transport must be elevenlabs_web")
    candidate_count = raw.get("candidate_count", 1)
    if isinstance(candidate_count, bool) or not isinstance(candidate_count, int) or not 1 <= candidate_count <= 4:
        raise ContractError("voice.candidate_count must be an integer from 1 to 4")
    manual_take = raw.get("manual_take_selection", False)
    if not isinstance(manual_take, bool):
        raise ContractError("voice.manual_take_selection must be boolean")
    voice_id = str(raw.get("voice_id") or "").strip()
    voice_label = str(raw.get("voice_label") or "").strip()
    if not voice_id and not voice_label:
        raise ContractError("voice requires a configured voice_id or exact voice_label")
    v2 = deepcopy(raw.get("v2") or {})
    v3 = deepcopy(raw.get("v3") or {})
    if not isinstance(v2, dict) or not isinstance(v3, dict):
        raise ContractError("voice.v2 and voice.v3 must be objects")
    return {
        "tts_model": model.value,
        "provider_model_label": MODEL_LABELS[model],
        "transport": transport,
        "execution_mode": expected_execution.value,
        "voice_id": voice_id or None,
        "voice_label": voice_label or None,
        "candidate_count": candidate_count,
        "manual_take_selection": manual_take,
        "profiles": {"eleven_multilingual_v2": v2, "eleven_v3": v3},
        "manual_locks": deepcopy(raw.get("manual_locks") or {}),
    }


def _normalize_quality(raw: Any) -> dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ContractError("shorts_v2.quality must be an object")
    _reject_unknown(raw, QUALITY_FIELDS, "shorts_v2.quality")
    result = {**DEFAULT_QUALITY, **deepcopy(dict(raw))}
    try:
        review = MediaReview(str(result["media_review"]))
        observation = EditingObservation(str(result["editing_observation"]))
    except ValueError as exc:
        raise ContractError(str(exc)) from exc
    if result["technical_validation"] is not True:
        raise ContractError("technical_validation cannot be disabled for publishable output")
    if not isinstance(result["text_contract_review"], bool):
        raise ContractError("text_contract_review must be boolean")
    if not isinstance(result["human_approval_required"], bool):
        raise ContractError("human_approval_required must be boolean")
    corrections = result["media_auto_corrections"]
    if isinstance(corrections, bool) or not isinstance(corrections, int) or not 0 <= corrections <= 3:
        raise ContractError("media_auto_corrections must be an integer from 0 to 3")
    if review is MediaReview.OFF:
        if corrections != 0:
            raise ContractError("media_review=off requires media_auto_corrections=0")
        if result["human_approval_required"]:
            raise ContractError("media_review=off cannot create a mandatory human approval gate")
        if result["media_review_scope"] != "all_visual_assets":
            raise ContractError("media_review=off must cover all_visual_assets")
    if result["observation_failure_policy"] != "safe_geometry_fallback":
        raise ContractError("unsupported observation failure policy")
    result["media_review"] = review.value
    result["editing_observation"] = observation.value
    return result


def normalize_engine_settings(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize one launch/brief without opting legacy work into the new engine.

    The versioned Shorts settings may be passed directly or under `_shorts_v2`.
    A missing engine marker always resolves to legacy and does not materialize
    new defaults into an old run.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ContractError("launch settings must be an object")
    nested = raw.get("_shorts_v2")
    source: Mapping[str, Any]
    if nested is not None:
        if not isinstance(nested, Mapping):
            raise ContractError("_shorts_v2 must be an object")
        source = nested
    else:
        source = raw
    engine_value = source.get("editing_engine")
    if engine_value in (None, ""):
        return {"schema_version": SCHEMA_VERSION, "editing_engine": EditingEngine.LEGACY.value}
    try:
        engine = EditingEngine(str(engine_value))
    except ValueError as exc:
        raise ContractError("editing_engine must be legacy or shorts_v2") from exc
    if engine is EditingEngine.LEGACY:
        return {"schema_version": SCHEMA_VERSION, "editing_engine": engine.value}
    _reject_unknown(source, SHORTS_FIELDS, "shorts_v2")
    if int(source.get("schema_version", SCHEMA_VERSION)) != SCHEMA_VERSION:
        raise ContractError(f"unsupported Shorts V2 schema_version; expected {SCHEMA_VERSION}")
    if str(source.get("design_version") or DESIGN_VERSION) != DESIGN_VERSION:
        raise ContractError(f"unsupported design_version; expected {DESIGN_VERSION}")
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "design_version": DESIGN_VERSION,
        "editing_engine": engine.value,
        "recipe_version": str(source.get("recipe_version") or "shorts_v2.2-r1"),
        "voice": _normalize_voice(source.get("voice")),
        "quality": _normalize_quality(source.get("quality")),
        "locks": deepcopy(source.get("locks") or {}),
        "test_fixture_mode": bool(source.get("test_fixture_mode", False)),
    }
    _finite_tree(normalized)
    return normalized


def resolve_precedence(
    *, defaults: Mapping[str, Any], ai: Mapping[str, Any] | None = None,
    profile: Mapping[str, Any] | None = None, user: Mapping[str, Any] | None = None,
    locked_fields: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Apply defaults < AI < profile < user while requiring every lock in user."""
    result = deepcopy(dict(defaults))
    for layer in (ai or {}, profile or {}, user or {}):
        result.update(deepcopy(dict(layer)))
    missing = sorted(set(locked_fields) - set(user or {}))
    if missing:
        raise ContractError(f"locked field(s) have no explicit user value: {', '.join(missing)}")
    _finite_tree(result, "effective_settings")
    return result


@dataclass(frozen=True)
class ArtifactEnvelope:
    schema_version: int
    design_version: str
    editing_engine: str
    episode_id: str
    revision_id: str
    artifact_type: str
    producer_stage: str
    producer_version: str
    input_fingerprint: str
    created_at: str
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_artifact_envelope(value: Mapping[str, Any]) -> ArtifactEnvelope:
    required = set(ArtifactEnvelope.__dataclass_fields__)
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing or unknown:
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if unknown:
            parts.append("unknown: " + ", ".join(unknown))
        raise ContractError("invalid artifact envelope (" + "; ".join(parts) + ")")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("artifact schema_version is unsupported")
    if value.get("design_version") != DESIGN_VERSION:
        raise ContractError("artifact design_version is unsupported")
    if value.get("editing_engine") != EditingEngine.SHORTS_V2.value:
        raise ContractError("artifact editing_engine must be shorts_v2")
    for field in ("episode_id", "revision_id", "artifact_type", "producer_stage"):
        stable_id(value.get(field), field)
    fingerprint = str(value.get("input_fingerprint") or "")
    if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise ContractError("input_fingerprint must be a lowercase SHA-256 digest")
    provenance = value.get("provenance")
    if not isinstance(provenance, dict) or not isinstance(provenance.get("observed"), bool):
        raise ContractError("provenance must contain boolean observed")
    _finite_tree(value, "artifact")
    return ArtifactEnvelope(**dict(value))


def canonical_json_hash(value: Any) -> str:
    _finite_tree(value)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

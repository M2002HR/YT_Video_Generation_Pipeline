"""Typed voice-performance plan and model-specific TTS compilers (P05)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .canonical_text import CanonicalDocument
from .contracts import ContractError, TTSModel, canonical_json_hash, canonical_tts_model, stable_id
from .elevenlabs_adapter import CapabilityProbe, build_execution_plan, text_fingerprint

V3_TAGS = frozenset({
    "whispers", "laughs", "sighs", "sarcastic", "curious", "mischievously",
    "excited", "short pause", "long pause",
})
EVENT_KINDS = frozenset({"delivery", "emphasis", "pause", "nonverbal"})
ANCHOR_POSITIONS = frozenset({"before", "after", "on"})
CALIBRATION = frozenset({"calibrated", "documented_not_calibrated", "not_applicable"})
BREAK_RE = re.compile(r'<break time="([0-9]+(?:\.[0-9]+)?)s"\s*/>')


@dataclass(frozen=True)
class PerformanceEvent:
    event_id: str
    word_id: str
    position: str
    kind: str
    intent: str
    implementation_type: str
    value: str
    calibration_status: str
    required: bool


@dataclass(frozen=True)
class CompiledVoice:
    schema_version: int
    model_family: str
    execution_mode: str
    canonical_text_hash: str
    performance_hash: str
    tts_input: str
    tts_input_hash: str
    token_map: tuple[dict[str, Any], ...]
    implemented_event_ids: tuple[str, ...]
    unfulfilled_intents: tuple[dict[str, str], ...]
    take_policy: dict[str, Any]

    def receipt_payload(self) -> dict[str, Any]:
        return asdict(self)


def validate_performance_plan(
    value: Mapping[str, Any], *, document: CanonicalDocument, tts_model: str,
) -> dict[str, Any]:
    required = {
        "schema_version", "model_family", "canonical_text_hash", "spoken_text_mutation_allowed",
        "events", "global_direction", "take_policy",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ContractError("voice performance plan has missing or unknown fields")
    if value.get("schema_version") != 1:
        raise ContractError("unsupported voice performance schema")
    model = canonical_tts_model(tts_model).value
    if canonical_tts_model(value.get("model_family")).value != model:
        raise ContractError("performance plan model does not match selected TTS model")
    if value.get("canonical_text_hash") != document.text_sha256:
        raise ContractError("performance plan is stale for canonical text")
    if value.get("spoken_text_mutation_allowed") is not False:
        raise ContractError("performance stage cannot mutate spoken words")
    direction = value.get("global_direction")
    if not isinstance(direction, Mapping) or set(direction) != {"emotion", "cadence", "hook_intensity", "body_intensity"}:
        raise ContractError("global performance direction is incomplete")
    for key in ("hook_intensity", "body_intensity"):
        number = direction[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not 0 <= number <= 1:
            raise ContractError(f"{key} must be finite in the 0..1 design range")
    take = value.get("take_policy")
    if take != {"candidate_count": 1, "manual_selection": False, "acceptance": "technical"}:
        raise ContractError("normal production requires one take and technical acceptance")
    spoken_ids = {token.word_id for token in document.tokens if token.spoken}
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value.get("events") or []:
        if not isinstance(raw, Mapping) or set(raw) != set(PerformanceEvent.__dataclass_fields__):
            raise ContractError("performance event has missing or unknown fields")
        event_id = stable_id(raw.get("event_id"), "event_id")
        if event_id in seen:
            raise ContractError(f"duplicate performance event {event_id}")
        seen.add(event_id)
        if raw.get("word_id") not in spoken_ids:
            raise ContractError(f"event {event_id} has an unknown/non-spoken word anchor")
        if raw.get("position") not in ANCHOR_POSITIONS or raw.get("kind") not in EVENT_KINDS:
            raise ContractError(f"event {event_id} has invalid anchor or kind")
        if raw.get("calibration_status") not in CALIBRATION or not isinstance(raw.get("required"), bool):
            raise ContractError(f"event {event_id} has invalid provenance/requirement")
        if not str(raw.get("intent") or "").strip():
            raise ContractError(f"event {event_id} requires an intent")
        events.append(dict(raw))
    return {**dict(value), "events": events, "performance_hash": canonical_json_hash(value)}


def _event_insert(event: Mapping[str, Any], model: TTSModel) -> tuple[str | None, str | None]:
    """Return (insert, unmet reason); insertion is markup, never a new spoken word."""
    kind, impl, value = event["kind"], event["implementation_type"], str(event["value"]).strip()
    if model is TTSModel.ELEVEN_V3:
        if impl == "audio_tag":
            normalized = value.strip("[]").casefold()
            if normalized not in V3_TAGS:
                raise ContractError(f"unknown or unbounded v3 audio tag {value!r}")
            return f"[{normalized}]", None
        if impl == "punctuation" and value in {"...", "—", "!", ","}:
            return value, None
        return None, f"{kind} implementation {impl!r} is unsupported by expressive_v3"
    if impl == "break":
        match = BREAK_RE.fullmatch(value)
        if not match or not 0.05 <= float(match.group(1)) <= 1.5:
            raise ContractError("v2 break must be a finite 0.05..1.5 second <break> node")
        return value, None
    if impl == "punctuation" and value in {"...", "—", "!", ","}:
        return value, None
    if impl == "capitalization" and kind == "emphasis":
        return "__CAPITALIZE__", None
    return None, f"{kind} implementation {impl!r} is unsupported by optimized_v2"


def compile_voice(
    plan: Mapping[str, Any], *, document: CanonicalDocument, tts_model: str,
) -> CompiledVoice:
    checked = validate_performance_plan(plan, document=document, tts_model=tts_model)
    model = canonical_tts_model(tts_model)
    before: dict[str, list[tuple[str, str]]] = {}
    after: dict[str, list[tuple[str, str]]] = {}
    capitalize: set[str] = set()
    implemented: list[str] = []
    unmet: list[dict[str, str]] = []
    for event in checked["events"]:
        insert, reason = _event_insert(event, model)
        if reason:
            if event["required"]:
                raise ContractError(f"required performance event {event['event_id']} cannot be compiled: {reason}")
            unmet.append({"event_id": event["event_id"], "intent": event["intent"], "reason": reason})
            continue
        if insert == "__CAPITALIZE__":
            capitalize.add(event["word_id"])
        else:
            target = before if event["position"] in {"before", "on"} else after
            target.setdefault(event["word_id"], []).append((event["event_id"], insert or ""))
        implemented.append(event["event_id"])
    parts: list[str] = []
    mapping: list[dict[str, Any]] = []
    cursor = 0
    for token in document.tokens:
        parts.append(document.text[cursor:token.start])
        if token.spoken:
            for _, insertion in before.get(token.word_id, []):
                parts.extend((insertion, " "))
            start = sum(len(part) for part in parts)
            rendered = token.text.upper() if token.word_id in capitalize else token.text
            parts.append(rendered)
            mapping.append({
                "word_id": token.word_id, "unit_id": token.unit_id, "occurrence": token.occurrence,
                "canonical_text": token.text, "execution_text": rendered,
                "execution_start": start, "execution_end": start + len(rendered),
            })
            for _, insertion in after.get(token.word_id, []):
                parts.extend((" ", insertion))
        else:
            parts.append(token.text)
        cursor = token.end
    parts.append(document.text[cursor:])
    tts_input = "".join(parts)
    if model is TTSModel.ELEVEN_V3 and ("<break" in tts_input or re.search(r"<[^>]+>", tts_input)):
        raise ContractError("expressive_v3 output cannot contain SSML/XML")
    if model is TTSModel.ELEVEN_MULTILINGUAL_V2 and re.search(r"\[[^\]]+\]", tts_input):
        raise ContractError("optimized_v2 output cannot contain v3 bracket tags")
    if [row["canonical_text"].casefold() for row in mapping] != [token.text.casefold() for token in document.tokens if token.spoken]:
        raise ContractError("compiled TTS input changed canonical spoken words")
    return CompiledVoice(
        schema_version=1, model_family=model.value,
        execution_mode="expressive_v3" if model is TTSModel.ELEVEN_V3 else "optimized_v2",
        canonical_text_hash=document.text_sha256, performance_hash=checked["performance_hash"],
        tts_input=tts_input, tts_input_hash=text_fingerprint(tts_input), token_map=tuple(mapping),
        implemented_event_ids=tuple(implemented), unfulfilled_intents=tuple(unmet),
        take_policy=dict(checked["take_policy"]),
    )


def build_tts_execution_request(
    compiled: CompiledVoice, *, voice_id: str | None, voice_label: str | None,
    requested_settings: Mapping[str, Any], probe: CapabilityProbe,
) -> dict[str, Any]:
    """Join compilation to the P03 adapter without a provider/model fallback."""
    if not (str(voice_id or "").strip() or str(voice_label or "").strip()):
        raise ContractError("TTS execution requires an explicitly resolved voice")
    request = {**dict(requested_settings), "tts_model": compiled.model_family}
    execution = build_execution_plan(request, probe)
    if execution.execution_mode != compiled.execution_mode:
        raise ContractError("compiler and ElevenLabs adapter execution modes disagree")
    effective = {
        "model": compiled.model_family, "execution_mode": compiled.execution_mode,
        "voice_id": voice_id, "voice_label": voice_label, "tts_input_hash": compiled.tts_input_hash,
        "numeric_settings": execution.numeric_settings, "stability_mode": execution.stability_mode,
        "speaker_boost": execution.speaker_boost,
    }
    return {
        "schema_version": 1, "tts_input": compiled.tts_input,
        "tts_input_hash": compiled.tts_input_hash, "voice_token_map": list(compiled.token_map),
        "effective": effective, "inactive_settings": execution.inactive_settings,
        "tts_effective_hash": canonical_json_hash(effective),
    }

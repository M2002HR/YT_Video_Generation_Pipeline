"""Canonical narration units and stable token identities."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .contracts import ContractError, stable_id


TOKEN_RE = re.compile(
    r"(?<!\w)[+-]?(?:\d+(?:[.,]\d+)*)(?:%|[a-zA-Z]+)?(?!\w)"
    r"|[A-Za-z]+(?:[’'][A-Za-z]+)*"
    r"|[^\w\s]",
    re.UNICODE,
)


@dataclass(frozen=True)
class CanonicalToken:
    word_id: str
    unit_id: str
    occurrence: int
    text: str
    start: int
    end: int
    spoken: bool


@dataclass(frozen=True)
class CanonicalDocument:
    text: str
    text_sha256: str
    units: tuple[dict[str, Any], ...]
    tokens: tuple[CanonicalToken, ...]


def freeze_canonical_text(units: Iterable[dict[str, Any]]) -> CanonicalDocument:
    normalized_units: list[dict[str, Any]] = []
    tokens: list[CanonicalToken] = []
    seen: set[str] = set()
    cursor = 0
    full_parts: list[str] = []
    occurrence = 0
    for raw in units:
        if not isinstance(raw, dict):
            raise ContractError("canonical narration units must be objects")
        unit_id = stable_id(raw.get("unit_id"), "unit_id")
        if unit_id in seen:
            raise ContractError(f"duplicate unit_id: {unit_id}")
        seen.add(unit_id)
        text = str(raw.get("text") or "").strip()
        if not text:
            raise ContractError(f"canonical unit {unit_id} has empty text")
        if full_parts:
            cursor += 1
        unit_start = cursor
        full_parts.append(text)
        for match in TOKEN_RE.finditer(text):
            token_text = match.group(0)
            spoken = bool(re.search(r"[A-Za-z0-9]", token_text))
            if spoken:
                occurrence += 1
            token_index = len(tokens) + 1
            tokens.append(CanonicalToken(
                word_id=f"{unit_id}.w{token_index:04d}",
                unit_id=unit_id,
                occurrence=occurrence if spoken else 0,
                text=token_text,
                start=unit_start + match.start(),
                end=unit_start + match.end(),
                spoken=spoken,
            ))
        normalized_units.append({"unit_id": unit_id, "text": text, "start": unit_start, "end": unit_start + len(text)})
        cursor += len(text)
    if not normalized_units:
        raise ContractError("canonical narration requires at least one unit")
    full_text = "\n".join(full_parts)
    return CanonicalDocument(
        text=full_text,
        text_sha256=hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
        units=tuple(normalized_units),
        tokens=tuple(tokens),
    )

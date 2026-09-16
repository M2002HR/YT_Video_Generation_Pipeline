"""Shared spoken-English policy and review contracts; no provider calls on import.

The model reviews meanings in context. This module validates evidence/provenance, never
claims to assign CEFR levels or silently rewrites words using a blacklist.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

POLICY_VERSION = 1
POLICY_FILE = "PLAIN_ENGLISH_POLICY.md"
REVIEWER_FILE = "02_plain_english_reviewer.md"
MAX_EDIT_ATTEMPTS = 3
REVIEW_CHECKS = (
    "everyday_words", "clear_sentence_meaning", "terms_explained",
    "easy_to_follow_once", "meaning_preserved",
)
REPORT_PATHS = {
    "core": "creative/CORE_LANGUAGE_REVIEW.json",
    "cta": "creative/CTA_LANGUAGE_REVIEW.json",
}


class LanguageContractError(ValueError):
    """An actionable language-review contract error, not a provider fallback."""


def fingerprint(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def policy_text(prompt_root: Path) -> str:
    path = Path(prompt_root) / POLICY_FILE
    text = path.read_text(encoding="utf-8").strip()
    if not text or "{{" in text or "}}" in text:
        raise LanguageContractError("Spoken-English policy must be non-empty literal text.")
    return text


def expand_policy(template: str, prompt_root: Path) -> str:
    """Expand only an explicit include; visual prompts and other projects stay untouched."""
    if "{{LANGUAGE_POLICY}}" not in template:
        return template
    return template.replace("{{LANGUAGE_POLICY}}", policy_text(prompt_root))


def spoken_segments(plan: dict[str, Any], entry_key: str, scope: str) -> dict[str, str]:
    if scope == "cta":
        return {"cta": str(plan.get("cta") or "").strip()}
    if scope != "core":
        raise LanguageContractError("Language scope must be core or cta.")
    result = {key: str(plan.get(key) or "").strip() for key in ("opening_question_spark", entry_key)}
    result.update({f"body_{index:02d}": str(text).strip() for index, text in enumerate(plan.get("body") or [], 1)})
    closing = str(plan.get("optional_closing") or "").strip()
    if closing:
        result["optional_closing"] = closing
    return result


def validate_review(payload: Any, segments: dict[str, str]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("checks"), dict):
        raise LanguageContractError("Language review requires checks, issues and optional notes.")
    checks = payload["checks"]
    if set(checks) != set(REVIEW_CHECKS) or any(type(checks[key]) is not bool for key in REVIEW_CHECKS):
        raise LanguageContractError("All five language checks must be explicit booleans with the declared keys.")
    issues = payload.get("issues")
    notes = payload.get("notes", [])
    if not isinstance(issues, list) or len(issues) > 12:
        raise LanguageContractError("Language issues must be an array with at most 12 priority items.")
    if not isinstance(notes, list) or len(notes) > 12 or any(not isinstance(x, str) or not x.strip() for x in notes):
        raise LanguageContractError("Language notes must be an array of non-empty strings (at most 12).")
    normalized = []
    for issue in issues:
        fields = ("check", "segment", "quote", "problem", "suggestion")
        if not isinstance(issue, dict) or any(not isinstance(issue.get(k), str) or not issue[k].strip() for k in fields):
            raise LanguageContractError("Each issue needs check, segment, exact quote, problem and suggestion.")
        item = {k: issue[k].strip() for k in fields}
        if item["check"] not in REVIEW_CHECKS or checks[item["check"]]:
            raise LanguageContractError("Each issue must identify a failed language check.")
        if item["segment"] not in segments or item["quote"] not in segments[item["segment"]]:
            raise LanguageContractError("Language issue must quote actual text from its named spoken segment.")
        if any(len(item[k]) > 800 for k in fields):
            raise LanguageContractError("Language feedback must be concise (800 characters per field).")
        normalized.append(item)
    failed = {key for key in REVIEW_CHECKS if not checks[key]}
    if failed != {item["check"] for item in normalized}:
        raise LanguageContractError("Every failed check needs an actionable issue; all true requires no issues.")
    return {"checks": {key: checks[key] for key in REVIEW_CHECKS}, "issues": normalized,
            "notes": notes, "passed": not failed}


def report_matches(report: Any, segments: dict[str, str], scope: str) -> bool:
    if not isinstance(report, dict) or report.get("scope") != scope or report.get("passed") is not True:
        return False
    if report.get("policy_version") != POLICY_VERSION or report.get("content_fingerprint") != fingerprint(segments):
        return False
    try:
        return validate_review(report, segments)["passed"]
    except LanguageContractError:
        return False


def correction_feedback(report: dict[str, Any], *, max_chars: int = 3500) -> str:
    # Keep complete issues. The full report remains on disk; subsequent reviews revisit all
    # segments. Factual source notes are never shortened to make optional feedback fit.
    lines = []
    for row in report["issues"]:
        line = f"{row['segment']}: {row['quote']!r}. {row['problem']} Suggested direction: {row['suggestion']}"
        if len("\n".join([*lines, line])) <= max_chars:
            lines.append(line)
    if not lines:
        raise LanguageContractError("Language correction exceeds the safe prompt budget; shorten editorial context without losing source qualifications.")
    return "\n".join(lines)

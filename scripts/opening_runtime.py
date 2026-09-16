"""Topic-first opening design: bounded candidates, independent review and stable context.

This module has no provider or filesystem side effects on import. Presentation mechanics,
character identity, factual narration and world styling remain separate contracts.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

POLICY_VERSION = 2
CANDIDATE_COUNT = 3
MAX_ATTEMPTS = 3
PROMPT_LIMIT = 19000
CONCEPT_FIELDS = (
    "hook_line", "viewer_expectation", "visible_contradiction", "frame_zero",
    "character_action", "reaction", "activity", "location", "topic_link",
    "factual_anchor", "payoff",
)
BRIDGE_FIELDS = ("a_end", "b_start", "reveal", "world_entry")
SIGNATURE_FIELDS = ("action_family", "tension_family", "prop_family", "reveal_family")
CRITERIA = ("topic_fit", "visible_hook", "character_fit", "honesty", "payoff", "entry_fit", "feasibility", "novelty", "spoken_clarity")
WEIGHTS = {"topic_fit": 3, "visible_hook": 3, "character_fit": 2, "honesty": 3, "payoff": 3, "entry_fit": 2, "feasibility": 2, "novelty": 2, "spoken_clarity": 3}
REVIEW_CHECKS = (
    "topic_specific", "visible_from_start", "character_consistent", "honest_claims",
    "hook_paid_off", "entry_continuity", "production_feasible", "meaningfully_distinct",
)


class OpeningContractError(ValueError):
    """An actionable text-stage error, never a reason to fabricate a usable plan."""


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(compact(value).encode("utf-8")).hexdigest()


def fill_prompt(template: str, **values: Any) -> str:
    result = template
    for key, value in values.items():
        result = result.replace("{{" + key + "}}", value if isinstance(value, str) else compact(value))
    holes = re.findall(r"\{\{([A-Z_]+)\}\}", result)
    if holes:
        raise OpeningContractError(f"Unfilled opening prompt tokens: {sorted(set(holes))}")
    if len(result) > PROMPT_LIMIT:
        raise OpeningContractError(f"Opening prompt exceeds {PROMPT_LIMIT} characters; shorten stage context, not the factual source.")
    return result


def fill_history_prompt(template: str, *, suffix: str = "", history_key: str = "RECENT_OPENINGS", **values: Any) -> tuple[str, list[dict[str, Any]]]:
    """Fit optional history to the provider budget; never truncate sources or constraints.

    The effective rows are returned for audit. Recent history wins over old rows, while the
    saved full snapshot remains stable. A genuinely oversized mandatory context fails clearly.
    """
    values = dict(values)
    rows = list(values.get(history_key) or [])
    while True:
        values[history_key] = rows
        try:
            prompt = fill_prompt(template, **values) + suffix
            if len(prompt) <= PROMPT_LIMIT:
                return prompt, rows
        except OpeningContractError as exc:
            if "exceeds" not in str(exc):
                raise
        if not rows:
            raise OpeningContractError("Mandatory opening context exceeds the provider limit even without history; shorten candidate descriptions or editorial source notes.")
        rows = rows[1:]


def narrative_brief(raw: dict[str, Any], topic: str, duration: Any) -> dict[str, Any]:
    """Only editorial inputs: subtitle fonts, provider settings and CTA hints are irrelevant.

    Bound each human field explicitly. Never silently truncate a must-include/avoid or source.
    The caller can report an actionable validation error instead of dropping a constraint.
    """
    if not isinstance(raw, dict):
        raise OpeningContractError("Creative brief must be a JSON object.")
    result: dict[str, Any] = {"topic": topic, "language": "English", "duration_seconds": [duration.min_seconds, duration.max_seconds]}
    for key in ("working_title", "audience", "narrative_angle", "must_include", "must_avoid", "source_notes"):
        value = str(raw.get(key) or "").strip()
        if len(value) > 2500:
            raise OpeningContractError(f"Creative brief field {key} exceeds 2500 characters. Supply concise source notes and constraints.")
        if value:
            result[key] = value
    qh = raw.get("_qh") if isinstance(raw.get("_qh"), dict) else {}
    result["hero_presence_mode"] = qh.get("hero_presence_mode", "auto")
    if len(compact(result)) > 6000:
        raise OpeningContractError("Editorial brief exceeds 6000 characters; shorten the source summary before generating an opening.")
    return result


def character_story_context(character: Any) -> dict[str, Any]:
    """WHO/acting for writers, not full anatomy or a style instruction."""
    return {
        "id": character.id, "archetype": character.archetype, "tone": list(character.tone),
        "behavior": character.behavior, "negative_constraints": character.negative_constraints,
        "environment_policy": character.environment_policy,
        "environment_affinities": list(character.environment_affinities),
    }


def _text(obj: dict[str, Any], key: str, limit: int | None = 240) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OpeningContractError(f"Opening field {key!r} must be a non-empty string.")
    value = value.strip()
    if limit is not None and len(value) > limit:
        raise OpeningContractError(f"Opening field {key!r} exceeds {limit} characters; be concrete and concise.")
    return value


def normalize(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value).casefold()))


def semantic_terms(value: Any) -> set[str]:
    """Cheap, transparent screening; independent review handles semantic paraphrases.

    A family match alone is never a veto. Sorting can be appropriate for a sorting topic.
    """
    aliases = {
        "sorting": "sort", "sorted": "sort", "sorts": "sort", "arranging": "sort",
        "organizing": "sort", "organising": "sort", "placing": "place", "puts": "place",
        "tools": "tool", "wrenches": "tool", "wrench": "tool", "equipment": "tool",
        "apples": "apple", "watering": "water", "irrigating": "water", "irrigation": "water",
        "misters": "water", "spraying": "water", "sleeve": "sleeve", "revealing": "reveal",
    }
    stop = {"a", "an", "the", "in", "on", "at", "to", "of", "for", "and", "with", "by", "after", "before", "while", "into", "his", "her", "their", "one", "same", "small", "quiet"}
    return {aliases.get(token, token) for token in normalize(value).split() if token not in stop}


def _similar(a: Any, b: Any) -> float:
    first, second = semantic_terms(a), semantic_terms(b)
    return len(first & second) / len(first | second) if first and second else 0.0


def repetition_evidence(candidate: dict[str, Any], history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hard collisions require a whole premise, not a camera, recurring prop or activity."""
    found = []
    signature = candidate.get("novelty") or {}
    premise = candidate.get("visible_contradiction") or candidate.get("situation_summary") or ""
    activity = candidate.get("activity") or candidate.get("opening_activity") or ""
    for item in history:
        other = item.get("opening_signature") or item.get("novelty") or {}
        matched = [key for key in SIGNATURE_FIELDS if normalize(signature.get(key)) and normalize(signature.get(key)) == normalize(other.get(key))]
        old_premise = item.get("situation_summary") or item.get("visible_contradiction") or ""
        score = _similar(premise, old_premise)
        action_score = _similar(activity, item.get("opening_activity") or item.get("activity"))
        hard = bool(old_premise and score >= .86) or (len(matched) == 4 and score >= .42)
        if hard or matched or action_score >= .35:
            found.append({"video_id": item.get("video_id"), "hard_collision": hard,
                          "matched_families": matched, "premise_similarity": round(score, 3),
                          "activity_similarity": round(action_score, 3),
                          "note": "Compare the actual conflict/payoff. A shared activity or entry object alone is allowed."})
    return found


def validate_candidates(payload: Any, allowed_variants: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list) or len(payload["candidates"]) != CANDIDATE_COUNT:
        raise OpeningContractError(f"Return exactly {CANDIDATE_COUNT} opening candidates in a candidates array.")
    out = []
    ids: set[str] = set()
    for raw in payload["candidates"]:
        if not isinstance(raw, dict):
            raise OpeningContractError("Each opening candidate must be an object.")
        key = _text(raw, "id", 30)
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", key) or key in ids:
            raise OpeningContractError("Candidate ids must be unique simple identifiers.")
        ids.add(key)
        item = {"id": key, **{name: _text(raw, name) for name in CONCEPT_FIELDS}}
        if len(re.findall(r"\b[\w']+\b", item["hook_line"])) > 16:
            raise OpeningContractError(f"Candidate {key}: hook_line must be at most 16 spoken words.")
        item["claim_mode"] = _text(raw, "claim_mode", 30)
        if item["claim_mode"] not in {"source_supported", "conservative", "hypothetical"}:
            raise OpeningContractError("claim_mode must be source_supported, conservative or hypothetical.")
        item["entry_variant"] = _text(raw, "entry_variant", 40)
        if allowed_variants and item["entry_variant"] not in allowed_variants:
            raise OpeningContractError(f"Unsupported entry_variant {item['entry_variant']!r}; choose {allowed_variants}.")
        bridge = raw.get("entry_bridge")
        novelty = raw.get("novelty")
        if not isinstance(bridge, dict) or not isinstance(novelty, dict):
            raise OpeningContractError("entry_bridge and novelty must be objects.")
        item["entry_bridge"] = {name: _text(bridge, name, 200) for name in BRIDGE_FIELDS}
        item["novelty"] = {name: _text(novelty, name, 80) for name in SIGNATURE_FIELDS}
        if len(compact(item)) > 3200:
            raise OpeningContractError(f"Candidate {key} exceeds its 3200-character context budget.")
        for previous in out:
            if normalize(item["visible_contradiction"]) == normalize(previous["visible_contradiction"]) or item["novelty"] == previous["novelty"]:
                raise OpeningContractError("Candidates must differ in dramatic mechanism, not just scenery or wording.")
        out.append(item)
    return out


def select_candidate(payload: Any, candidates: list[dict[str, Any]], history: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The code ranks independent assessments; the writer cannot declare its own winner."""
    reviews = payload.get("reviews") if isinstance(payload, dict) else None
    if not isinstance(reviews, list) or len(reviews) != len(candidates):
        raise OpeningContractError("Reviewer must assess every candidate exactly once.")
    indexed = {item["id"]: item for item in candidates}
    seen: set[str] = set()
    decisions = []
    for raw in reviews:
        if not isinstance(raw, dict) or raw.get("id") not in indexed or raw["id"] in seen:
            raise OpeningContractError("Reviewer returned an unknown or duplicate candidate id.")
        key = raw["id"]
        seen.add(key)
        scores = raw.get("scores")
        issues = raw.get("blocking_issues")
        if not isinstance(scores, dict) or any(type(scores.get(name)) is not int or not 0 <= scores[name] <= 4 for name in CRITERIA):
            raise OpeningContractError("Each criterion score must be an integer from 0 to 4 (not a boolean).")
        if not isinstance(issues, list) or any(not isinstance(item, str) or not item.strip() for item in issues):
            raise OpeningContractError("blocking_issues must be an array of concrete strings.")
        issues = list(issues)
        collision = repetition_evidence(indexed[key], history)
        if any(item["hard_collision"] for item in collision):
            issues.append("Near-identical recent premise: " + ", ".join(str(item["video_id"]) for item in collision if item["hard_collision"]))
        if any(scores[name] < 3 for name in ("topic_fit", "honesty", "payoff", "entry_fit", "feasibility")) or scores["visible_hook"] < 2 or scores["character_fit"] < 2 or scores["novelty"] < 2 or scores["spoken_clarity"] < 3:
            issues.append("Insufficient topic fit, honesty, payoff, entry feasibility, visible hook or spoken clarity.")
        decisions.append({"id": key, "scores": scores, "blocking_issues": issues,
                          "reason": _text(raw, "reason", None), "repetition_evidence": collision,
                          "weighted_score": sum(scores[name] * WEIGHTS[name] for name in CRITERIA)})
    eligible = [item for item in decisions if not item["blocking_issues"]]
    if not eligible:
        details = "; ".join(item["id"] + ": " + ", ".join(item["blocking_issues"]) for item in decisions)
        raise OpeningContractError("No usable opening candidate. " + details[:1800])
    best = max(eligible, key=lambda item: item["weighted_score"])
    return indexed[best["id"]], decisions


def validate_review(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("checks"), dict):
        raise OpeningContractError("Opening review must contain checks and issues.")
    checks = payload["checks"]
    if any(type(checks.get(key)) is not bool for key in REVIEW_CHECKS):
        raise OpeningContractError("All opening review checks must be explicit booleans.")
    issues = payload.get("issues")
    if not isinstance(issues, list) or any(not isinstance(item, str) or not item.strip() for item in issues):
        raise OpeningContractError("Opening review issues must be specific strings.")
    if not all(checks[key] for key in REVIEW_CHECKS):
        if not issues:
            issues = ["Failed review: " + ", ".join(key for key in REVIEW_CHECKS if not checks[key])]
        raise OpeningContractError("Opening story review failed: " + "; ".join(issues)[:1600])
    if issues:
        raise OpeningContractError("Review says all checks passed but reports blocking issues: " + "; ".join(issues)[:1200])
    return {"checks": {key: checks[key] for key in REVIEW_CHECKS}, "issues": [], "passed": True}


def selected_context(concept: dict[str, Any] | None) -> dict[str, Any]:
    if not concept:
        return {}
    return {"policy_version": concept.get("policy_version"), "concept_id": concept.get("concept_id"),
            "selected": concept.get("selected", {})}


def entry_context(concept: dict[str, Any] | None, episode: dict[str, Any] | None = None) -> dict[str, Any]:
    """Only the A/B seam and subject-world reveal, never full host/environment prose."""
    selected = (concept or {}).get("selected") or {}
    bridge = (episode or {}).get("entry_bridge") or selected.get("entry_bridge") or {}
    return {"entry_variant": (episode or {}).get("entry_variant") or selected.get("entry_variant"),
            "entry_bridge": bridge, "payoff": selected.get("payoff", "")}


def world_entry_context(concept: dict[str, Any] | None) -> str:
    """A subject-world brief only; the keyframe remains strictly host-free."""
    return str((((concept or {}).get("selected") or {}).get("entry_bridge") or {}).get("world_entry") or "Choose the strongest host-free subject-world establishing moment from the factual body.")


def validate_episode_seam(episode: dict[str, Any], concept: dict[str, Any], variants: tuple[str, ...]) -> dict[str, Any]:
    if episode.get("concept_id") != concept.get("concept_id"):
        raise OpeningContractError("Episode direction must cite the selected concept_id, not invent another opening.")
    if variants and episode.get("entry_variant") not in variants:
        raise OpeningContractError("Episode direction chose an unsupported entry variant.")
    bridge = episode.get("entry_bridge")
    if not isinstance(bridge, dict):
        raise OpeningContractError("Episode direction needs an explicit entry_bridge for the A/B seam.")
    for key in BRIDGE_FIELDS:
        _text(bridge, key, 500)
    actions = episode.get("opening_actions")
    if not isinstance(actions, list) or not 1 <= len(actions) <= 3 or any(not isinstance(value, str) or not value.strip() for value in actions):
        raise OpeningContractError("Use one to three readable opening_actions, not a long choreography.")
    return episode

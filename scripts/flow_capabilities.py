"""Verified Flow generation capabilities used by the production planner and Studio.

This is deliberately a conservative contract: a duration may be selected only when it has
been observed in Flow's settings UI for that model.  Unknown model capabilities are not
guessed; the run stops before a paid media request can be submitted.
"""
from __future__ import annotations


# Source: services/ordak/app/automation/flow_settings.py's live settings vocabulary and
# the capability snapshot captured by Flow for Omni 1.1 Flash on 2026-09-15.
FLOW_DURATION_OPTIONS: dict[str, tuple[int, ...]] = {
    "gemini_omni_1_1_flash": (4, 6, 8, 10),
}


def durations_for_model(model: str) -> tuple[int, ...]:
    """Return verified durations, refusing to invent support for another Flow model."""
    return FLOW_DURATION_OPTIONS.get(str(model or "").strip(), ())

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from elevenlabs_tab_monitor import assess_snapshot


def test_tab_monitor_distinguishes_idle_from_provider_failure() -> None:
    assert assess_snapshot(None)[0] == "idle"
    assert assess_snapshot({"login_required": True})[0] == "blocked"
    assert assess_snapshot({"captcha": True})[0] == "blocked"


def test_tab_monitor_accepts_a_busy_composer_and_flags_missing_composer() -> None:
    assert assess_snapshot({"ready": True, "busy": True})[0] == "healthy"
    assert assess_snapshot({"ready": False, "busy": True})[0] == "transitional"
    assert assess_snapshot({"ready": False, "busy": False})[0] == "degraded"

"""Regression coverage for visible browser-credit extraction."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_browser_credits", ROOT / "scripts" / "check_browser_credits.py"
)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


def test_elevenlabs_uses_the_labelled_remaining_row_not_plan_total(monkeypatch) -> None:
    """The compact 10k label is a plan total; the paired row owns the balance."""
    monkeypatch.setattr(
        checker,
        "evaluate",
        lambda _websocket, _expression: json.dumps({
            "total": "10,000 credits",
            "remaining": "442",
        }),
    )
    assert checker.elevenlabs_balance(object()) == {
        "remaining": 442,
        "unit": "credit",
        "raw": "Total 10,000 credits · Remaining 442",
        "total": 10_000,
        "used": 9_558,
    }


def test_credit_check_tab_creation_never_closes_provider_tabs(monkeypatch) -> None:
    """A balance check may not replace the Flow tab used by jobs/readiness checks."""
    calls: list[tuple[str, str]] = []

    def fake_request(url: str, *, method: str = "GET"):
        calls.append((url, method))
        return {"id": "temporary-credit-tab", "webSocketDebuggerUrl": "ws://example.test/devtools/page/1"}

    monkeypatch.setattr(checker, "_json_request", fake_request)

    assert checker.open_tab("http://127.0.0.1:9222", "https://flow.google.com/")["id"] == "temporary-credit-tab"
    assert calls == [
        ("http://127.0.0.1:9222/json/new?https://flow.google.com/", "PUT"),
    ]

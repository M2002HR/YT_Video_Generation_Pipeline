"""Dispatch boundary and provider-call accounting for the new engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .contracts import ContractError, normalize_engine_settings
from .registry import effective_graph


@dataclass
class ProviderCallSpy:
    """Test/instrumentation wrapper; fixture results can never enter production."""

    fixture_mode: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)

    def record(self, *, stage: str, provider: str, operation: str, attempt_id: str) -> None:
        self.calls.append({
            "stage": stage,
            "provider": provider,
            "operation": operation,
            "attempt_id": attempt_id,
            "fixture": self.fixture_mode,
        })

    def fixture_result(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not self.fixture_mode:
            raise ContractError("fake provider output is forbidden outside explicit fixture mode")
        return {"fixture_only": True, "publishable": False, "payload": dict(payload)}


@dataclass(frozen=True)
class DispatchPlan:
    editing_engine: str
    entrypoint: str
    settings: dict[str, Any]
    graph: dict[str, Any] | None


def dispatch_plan(raw: Mapping[str, Any], *, project: Path | None = None) -> DispatchPlan:
    settings = normalize_engine_settings(raw)
    if settings["editing_engine"] == "legacy":
        return DispatchPlan("legacy", "scripts/run_full_video_pipeline_q_station_wrapper.py", settings, None)
    return DispatchPlan(
        "shorts_v2",
        "scripts/run_shorts_v2_pipeline.py",
        settings,
        effective_graph(settings),
    )


def invoke_provider(
    call: Callable[..., Any], *, spy: ProviderCallSpy, stage: str,
    provider: str, operation: str, attempt_id: str, **kwargs: Any,
) -> Any:
    spy.record(stage=stage, provider=provider, operation=operation, attempt_id=attempt_id)
    return call(**kwargs)

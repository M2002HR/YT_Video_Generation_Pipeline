#!/usr/bin/env python3
"""Shorts V2 orchestration entry point.

C1 intentionally exposes a validated plan/checkpoint path only. Provider-backed
creative/media execution is enabled by later phases; it is never simulated in a
production episode.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from shorts_v2.artifacts import ArtifactResolver, atomic_write_json  # noqa: E402
from shorts_v2.contracts import ContractError, canonical_json_hash, normalize_engine_settings  # noqa: E402
from shorts_v2.registry import effective_graph  # noqa: E402
from shorts_v2.state import StageStateStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and checkpoint a Shorts V2 run.")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--revision-id", default="initial")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()

    raw = json.loads(args.request.read_text(encoding="utf-8"))
    settings = normalize_engine_settings(raw)
    if settings["editing_engine"] != "shorts_v2":
        raise ContractError("run_shorts_v2_pipeline requires explicit editing_engine=shorts_v2")
    resolver = ArtifactResolver(args.project.resolve(), args.revision_id)
    resolver.ensure_layout()
    request_payload = {
        "schema_version": 1,
        "editing_engine": "shorts_v2",
        "settings": settings,
        "request_fingerprint": canonical_json_hash(settings),
    }
    atomic_write_json(resolver.resolve("request"), request_payload)
    state = StageStateStore(
        resolver.resolve_relative("diagnostics/RUNTIME_STATE.json"),
        run_id=args.run_id,
        revision_id=args.revision_id,
    )
    state.transition("preflight", "RUNNING")
    graph = effective_graph(settings, include_disabled=True)
    atomic_write_json(resolver.resolve_relative("diagnostics/EFFECTIVE_GRAPH.json"), graph)
    state.transition("preflight", "DONE", request_fingerprint=request_payload["request_fingerprint"])
    print(json.dumps(graph, ensure_ascii=False, indent=2))
    if args.plan_only:
        return 0
    raise ContractError(
        "Shorts V2 provider execution is not enabled in the C1 orchestration skeleton; "
        "use --plan-only until the owning implementation phases are complete"
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContractError, json.JSONDecodeError, OSError) as exc:
        print(f"SHORTS_V2_CONTRACT_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

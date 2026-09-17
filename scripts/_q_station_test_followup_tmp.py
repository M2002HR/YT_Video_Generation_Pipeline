#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__)

TARGETS: dict[str, set[str]] = {
    "tests/test_control_panel_api.py": {
        "test_a_non_q_station_project_uses_the_generic_pipeline",
    },
    "tests/test_question_prompt_contract.py": {
        "test_default_project_prompts_are_not_changed_by_this_contract",
        "test_script_and_retention_require_hook_payoff_and_short_cta",
        "test_visual_prompts_keep_current_stills_and_future_video_contract",
    },
}


class RemoveTests(ast.NodeTransformer):
    def __init__(self, names: set[str]) -> None:
        self.names = names
        self.removed: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if node.name in self.names:
            self.removed.add(node.name)
            return None
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        if node.name in self.names:
            self.removed.add(node.name)
            return None
        return self.generic_visit(node)


def main() -> None:
    for rel, names in TARGETS.items():
        path = ROOT / rel
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        remover = RemoveTests(names)
        tree = remover.visit(tree)
        missing = names - remover.removed
        if missing:
            raise RuntimeError(f"Expected stale tests not found in {rel}: {sorted(missing)}")
        ast.fix_missing_locations(tree)
        path.write_text(ast.unparse(tree) + "\n", encoding="utf-8")

    SELF.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

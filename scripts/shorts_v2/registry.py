"""The executable Shorts V2 DAG registry shared by runner, UI and revision."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

from .contracts import ContractError


Condition = Callable[[Mapping[str, Any]], bool]


@dataclass(frozen=True)
class StageSpec:
    id: str
    title: str
    phase: str
    dependencies: tuple[str, ...] = ()
    owned_artifacts: tuple[str, ...] = ()
    condition_name: str = "always"
    provider: str | None = None
    revision_policy: str = "cascade"


STAGES: tuple[StageSpec, ...] = (
    StageSpec("preflight", "Shorts V2 preflight", "contract", owned_artifacts=("request",)),
    StageSpec("character_resolution", "Character and presentation", "creative", ("preflight",), ("character_resolution", "character_performance")),
    StageSpec("evidence", "Evidence pack", "creative", ("preflight",), ("evidence_pack",)),
    StageSpec("hook", "Hook tournament", "creative", ("character_resolution", "evidence"), ("hook_packages", "hook_reviews", "hook_tournament"), provider="chatgpt"),
    StageSpec("script", "Canonical script", "creative", ("hook", "evidence"), ("story_blueprint", "script_core", "cta", "script_reviews"), provider="chatgpt"),
    StageSpec("voice_resolution", "Voice resolution and capabilities", "voice", ("character_resolution",), ("voice_resolution", "voice_capabilities"), provider="elevenlabs_web"),
    StageSpec("voice_performance", "Voice performance", "voice", ("script", "voice_resolution"), ("voice_performance",), provider="chatgpt"),
    StageSpec("voice_compile", "Model-specific voice compile", "voice", ("voice_performance",), ("tts_input", "voice_token_map")),
    StageSpec("elevenlabs_voiceover", "Bound ElevenLabs web generation", "voice", ("voice_compile",), ("narration_audio", "tts_receipt"), provider="elevenlabs_web"),
    StageSpec("narration_alignment", "Audio-authoritative alignment", "timing", ("elevenlabs_voiceover", "script"), ("narration_timing",)),
    StageSpec("rhythm_map", "Rhythm map", "timing", ("narration_alignment", "voice_performance"), ("rhythm_map",)),
    StageSpec("shot_plan", "Shot plan", "planning", ("rhythm_map", "script"), ("shot_plan",), provider="chatgpt"),
    StageSpec("asset_manifest", "Independent asset manifest", "planning", ("shot_plan", "character_resolution"), ("asset_manifest",), provider="chatgpt"),
    StageSpec("assets", "Visual assets", "visual", ("asset_manifest",), provider="chatgpt", revision_policy="semantic_manifest_diff"),
    StageSpec("media_review", "Optional media review", "visual", ("assets",), condition_name="media_review", provider="chatgpt"),
    StageSpec("asset_observation", "One-pass edit observation", "visual", ("assets",), condition_name="observation", provider="chatgpt"),
    StageSpec("assets_ready", "Assets ready", "visual", ("assets", "media_review", "asset_observation")),
    StageSpec("edit_direction", "Independent edit direction", "edit", ("assets_ready", "rhythm_map"), ("edit_plan",), provider="chatgpt"),
    StageSpec("captions_sound", "Captions, branding and sound", "edit", ("edit_direction", "narration_alignment")),
    StageSpec("compile_timeline", "Deterministic timeline compile", "render", ("captions_sound",), ("compiled_timeline",)),
    StageSpec("render_preview", "Audible preview", "render", ("compile_timeline",), ("preview",)),
    StageSpec("render_final", "Final render", "render", ("compile_timeline",), ("final", "render_receipt")),
    StageSpec("technical_qc", "Technical validation", "render", ("render_final",)),
    StageSpec("accept_version", "Atomic version acceptance", "revision", ("technical_qc",)),
    StageSpec("delivery", "Enabled delivery", "delivery", ("accept_version",), condition_name="delivery"),
)


def _enabled(name: str, settings: Mapping[str, Any]) -> bool:
    quality = settings.get("quality") if isinstance(settings.get("quality"), Mapping) else {}
    if name == "always":
        return True
    if name == "media_review":
        return quality.get("media_review") != "off"
    if name == "observation":
        return quality.get("editing_observation") == "auto_once"
    if name == "delivery":
        delivery = settings.get("delivery")
        return isinstance(delivery, Mapping) and any(bool(value) for value in delivery.values())
    raise ContractError(f"unknown graph condition: {name}")


def effective_graph(settings: Mapping[str, Any], *, include_disabled: bool = False) -> dict[str, Any]:
    by_id = {stage.id: stage for stage in STAGES}
    if len(by_id) != len(STAGES):
        raise ContractError("Shorts V2 registry contains duplicate stage ids")
    enabled = {stage.id for stage in STAGES if _enabled(stage.condition_name, settings)}
    nodes: list[dict[str, Any]] = []
    for stage in STAGES:
        is_enabled = stage.id in enabled
        if not is_enabled and not include_disabled:
            continue
        node = asdict(stage)
        node["status"] = "QUEUED" if is_enabled else "SKIPPED_CONFIG"
        nodes.append(node)
    visible = {node["id"] for node in nodes}
    edges: list[dict[str, str]] = []
    for stage in STAGES:
        if stage.id not in visible:
            continue
        for dependency in stage.dependencies:
            if dependency not in by_id:
                raise ContractError(f"stage {stage.id} has unknown dependency {dependency}")
            if dependency in visible:
                edges.append({"source": dependency, "target": stage.id, "kind": "data"})
    order = topological_order(nodes, edges)
    return {
        "schema_version": 1,
        "editing_engine": "shorts_v2",
        "nodes": nodes,
        "edges": edges,
        "order": order,
        "phases": list(dict.fromkeys(stage.phase for stage in STAGES)),
    }


def topological_order(nodes: list[dict[str, Any]], edges: list[dict[str, str]]) -> list[str]:
    ids = [str(node["id"]) for node in nodes]
    incoming = {node_id: 0 for node_id in ids}
    children = {node_id: [] for node_id in ids}
    for edge in edges:
        source, target = edge["source"], edge["target"]
        incoming[target] += 1
        children[source].append(target)
    queue = [node_id for node_id in ids if incoming[node_id] == 0]
    ordered: list[str] = []
    while queue:
        current = queue.pop(0)
        ordered.append(current)
        for child in children[current]:
            incoming[child] -= 1
            if incoming[child] == 0:
                queue.append(child)
    if len(ordered) != len(ids):
        raise ContractError("Shorts V2 effective graph contains a cycle")
    return ordered

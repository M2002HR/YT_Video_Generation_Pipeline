"""A created style has to become reusable, or "reuse an existing style" never applies.

The catalog is read by the director, listed by the panel, and pinnable from the panel. If a
newly created style is never written into it, every episode invents one and none is offered
again.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import world_style_catalog as wsc  # noqa: E402


PLAN = {
    "style_id": "ink_wash_vintage_animation_001",
    "decision": "new",
    "medium": "ink wash",
    "texture_family": "warm cream paper",
    "palette_summary": "sepia ink, muted ochres",
}


@pytest.fixture()
def project(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(wsc, "ROOT", tmp_path)
    styles = tmp_path / "projects" / "demo" / "world_styles"
    styles.mkdir(parents=True)
    (styles / "001_woodcut_charcoal").mkdir()
    (styles / "CATALOG.json").write_text(json.dumps({
        "schema_version": 1,
        "styles": [{"style_id": "woodcut_charcoal_warm", "path": "001_woodcut_charcoal",
                    "usage_count": 0}],
    }), encoding="utf-8")
    return "demo"


@pytest.fixture()
def anchor(tmp_path) -> Path:
    path = tmp_path / "world_style_anchor.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    return path


def test_a_new_style_is_registered_with_its_anchor(project, anchor, tmp_path) -> None:
    entry = wsc.publish_style(project, PLAN, anchor)
    assert entry["style_id"] == PLAN["style_id"]
    assert entry["path"] == "002_ink_wash_vintage_animation_001"
    assert entry["status"] == "ready"
    assert entry["usage_count"] == 1

    directory = tmp_path / "projects" / "demo" / "world_styles" / entry["path"]
    assert (directory / "style_anchor.png").read_bytes() == anchor.read_bytes()
    assert json.loads((directory / "STYLE_PLAN.json").read_text())["medium"] == "ink wash"
    assert PLAN["style_id"] in wsc.style_ids(project)


def test_the_ordinal_continues_the_existing_directories(project, anchor) -> None:
    wsc.publish_style(project, PLAN, anchor)
    second = wsc.publish_style(project, {**PLAN, "style_id": "paper_cut_002"}, anchor)
    assert second["path"] == "003_paper_cut_002"


def test_publishing_twice_does_not_duplicate_the_entry(project, anchor) -> None:
    first = wsc.publish_style(project, PLAN, anchor)
    again = wsc.publish_style(project, PLAN, anchor)
    assert again == first
    assert wsc.style_ids(project).count(PLAN["style_id"]) == 1


def test_an_empty_anchor_is_refused(project, tmp_path) -> None:
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    with pytest.raises(wsc.WorldStyleCatalogError):
        wsc.publish_style(project, PLAN, empty)


def test_a_plan_without_an_id_is_refused(project, anchor) -> None:
    with pytest.raises(wsc.WorldStyleCatalogError):
        wsc.publish_style(project, {"decision": "new"}, anchor)


def test_reuse_is_counted(project) -> None:
    assert wsc.record_reuse(project, "woodcut_charcoal_warm") == 1
    assert wsc.record_reuse(project, "woodcut_charcoal_warm") == 2


def test_reusing_an_unknown_style_is_an_error(project) -> None:
    with pytest.raises(wsc.WorldStyleCatalogError):
        wsc.record_reuse(project, "never_created")


def test_a_missing_catalog_reads_as_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(wsc, "ROOT", tmp_path)
    assert wsc.load_catalog("absent")["styles"] == []

#!/usr/bin/env python3
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__)


def remove_cache_artifacts() -> None:
    for path in sorted(ROOT.rglob("__pycache__"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    for path in ROOT.rglob("*.pyc"):
        if path.is_file():
            path.unlink(missing_ok=True)


def normalize_text(path: Path) -> None:
    try:
        raw = path.read_bytes()
    except OSError:
        return
    if b"\x00" in raw[:8192]:
        return
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return

    original = text
    replacements = (
        ("question_harvest", "q_station"),
        ("QUESTION_HARVEST", "Q_STATION"),
        ("Question_Harvest", "Q_Station"),
        ("question-harvest", "q-station"),
        ("Question-Harvest", "Q-Station"),
        ("Question Harvest", "Q Station"),
        ("question harvest", "Q Station"),
        ("world_behind_the_question", "q_station"),
        ("WORLD_BEHIND_THE_QUESTION", "Q_STATION"),
        ("World_Behind_The_Question", "Q_Station"),
        ("world-behind-the-question", "q-station"),
        ("World Behind the Question", "Q Station"),
        ("World Behind The Question", "Q Station"),
        ("world behind the question", "Q Station"),
        ("farmer_host", "red_horned_everyman"),
        ("FARMER_HOST", "RED_HORNED_EVERYMAN"),
        ("Farmer Host", "Red Horned Everyman"),
        ("farmer-host", "red-horned-everyman"),
        ("Farmer-Host", "Red-Horned-Everyman"),
        ("_qh", "_q_station"),
        ("QH_", "Q_STATION_"),
        ("qh_", "q_station_"),
    )
    for old, new in replacements:
        text = text.replace(old, new)

    # The audited retained run set has no topical use of the retired host noun; any remaining
    # occurrence is compatibility prose or an identifier and can be normalized safely.
    text = text.replace("FARMER", "RED_HOST")
    text = text.replace("Farmer", "Red Host")
    text = re.sub(r"farmer", "red_host", text, flags=re.IGNORECASE)

    if text != original:
        path.write_text(text, encoding="utf-8")


def verify_clean() -> None:
    banned_fragments = (
        "question" + "_" + "harvest",
        "question" + " harvest",
        "question" + "-" + "harvest",
        "world" + "_behind_the_" + "question",
        "world" + " behind the " + "question",
        "world" + "-behind-the-" + "question",
        "farmer",
        "_" + "qh",
        "qh" + "_",
    )
    problems: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in {".git", "node_modules", "__pycache__"} for part in path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        lowered_path = rel.lower()
        if any(token in lowered_path for token in banned_fragments):
            problems.append(f"path:{rel}")
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            continue
        try:
            text = raw.decode("utf-8").lower()
        except UnicodeDecodeError:
            continue
        if any(token in text for token in banned_fragments):
            problems.append(f"text:{rel}")
    if problems:
        raise SystemExit("retired identifiers remain:\n" + "\n".join(sorted(set(problems))[:250]))


def main() -> None:
    # The primary cleanup deletes itself and its workflow. This finalizer is one-shot too.
    SELF.unlink(missing_ok=True)
    for path in list(ROOT.rglob("*")):
        if path.is_file() and not any(part in {".git", "node_modules", "__pycache__"} for part in path.parts):
            normalize_text(path)
    remove_cache_artifacts()
    verify_clean()


if __name__ == "__main__":
    main()

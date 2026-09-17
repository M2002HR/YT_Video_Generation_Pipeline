#!/usr/bin/env python3
"""Check a selected character without calling providers or writing any assets."""
from __future__ import annotations

import argparse

from character_runtime import load_character_registry
from content_projects import character_registry_path, load_content_project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="q_station")
    parser.add_argument("--character", required=True)
    args = parser.parse_args(argv)
    try:
        project = load_content_project(args.project)
        path = character_registry_path(project)
        if path is None:
            raise RuntimeError(f"{args.project} has no character registry.")
        registry = load_character_registry(path)
        character = registry.get(args.character)
        profile = character.presentation
        if not profile.entry_variants:
            raise RuntimeError("The presentation has no entry variants.")
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Character preflight FAILED: {exc}")
        return 1
    print(f"READY: {character.display_name} ({character.id})")
    print(f"Character sheet: {character.sheet_path}")
    print(f"Character SHA256: {character.sheet_sha256}")
    print(f"Presentation: {profile.id}; narration={profile.segment_key}")
    print(f"Entry identity: {profile.identity_sheet_path}")
    if not profile.identity_sheet_path.is_file():
        print("Entry identity will be generated and receipt-verified on the first real run.")
    print(f"Entry variants: {', '.join(profile.entry_variants)}")
    print("Select this character manually for its first video; Auto remains topic-dependent.")
    print("No providers called; no artwork, receipts or episode state written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

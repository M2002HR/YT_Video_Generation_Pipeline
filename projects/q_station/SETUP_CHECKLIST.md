# Q Station deployment checklist

Deploy while no generation job is active. Review local changes and use a fast-forward pull of `dev`; do not reset operator configuration, sessions, generated media or submodules.

- [ ] Preserve existing operator assets and service configuration; update the checkout.
- [ ] For Newton, install the complete approved real PNG at `characters/newton_scholar/refs/character_sheet.png` relative to this project directory. No dummy image is supplied.
- [ ] From repository root, run `.venv/bin/python scripts/check_character_setup.py --character newton_scholar`; it must report ready before selecting him.
- [ ] Run `.venv/bin/python scripts/check_opening_setup.py`, then restart the installed panel/API and websocket services.
- [ ] Select each required host manually for first acceptance. Auto does not guarantee a particular host; unready operator packs remain unavailable without disabling the others.
- [ ] Inspect the first red-door B for a topic-textured aperture, visible intentional crossing, correct wall/floor geometry and completion before the narration trim boundary.
- [ ] Inspect the captain's B start for small eyepiece at the visible eye, wider objective outward and a plausible grip. A reversed or ambiguous telescope must fail image review.
- [ ] Inspect topic-world keyframe, body and closing for full-bleed layout with no enclosing page or persistent gateway mask.

New-run mappings: red host -> red door; crone -> orb; captain -> spyglass; Newton-inspired scholar -> existing book. The red door and corrected spyglass identities are generated lazily with verified receipts; no manual object images are required. Their first generation consumes the normal provider credits.

Existing runs keep their frozen mapping. Use explicit Revise for intentional gateway changes or regeneration of affected image branches. See `docs/CHARACTER_GATEWAYS.md` for complete setup, timing, camera, cache, QC and production-smoke requirements. Offline tests do not replace a real provider smoke on the server.

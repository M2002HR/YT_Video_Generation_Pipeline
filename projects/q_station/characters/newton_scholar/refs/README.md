# Install the canonical character sheet

Place the complete approved Newton-inspired turnaround here as `character_sheet.png` (real single-frame PNG, not renamed JPEG). Keep its original resolution and proportions; no portrait crop or background removal is required. Both edges must be at least 256 pixels and the file at least 10,000 bytes. No image is supplied in Git.

From repository root run `.venv/bin/python scripts/check_character_setup.py --character newton_scholar` after upload. Before a valid sheet exists, this pack is excluded from Auto and selectable characters without breaking the other hosts. An explicit request for an unavailable pack fails with the installation reason. Do not replace artwork during an active run.

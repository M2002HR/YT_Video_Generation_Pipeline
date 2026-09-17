# Operator-installed character sheet

Place the supplied sea-captain turnaround here as **character_sheet.png** (a real, single-frame PNG, not a renamed JPEG). Keep the original full-resolution sheet; at least 256 pixels on both edges and 10,000 bytes are required by readiness checks. The supplied 1408 x 1056 sheet is suitable; no portrait crop or transparency is required.

This file is intentionally not supplied, generated or replaced by code. Use an atomic upload and do not replace it during a running generation. Until a valid file is installed, other characters work normally and this character is excluded from Auto and the selectable catalog. Manual/resumed captain requests fail clearly, never switch to another host.

From the repository root run `python scripts/check_character_setup.py --character sea_captain`, then restart the panel/worker services and select **Curious Sea Captain** manually for the first video. See `docs/SEA_CAPTAIN_INTEGRATION.md`.

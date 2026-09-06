from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_elevenlabs_voiceover import output_format_identity  # noqa: E402


def test_output_format_identity_ignores_ui_typography() -> None:
    assert output_format_identity("MP3 44.1 kHz (128kbps)") == output_format_identity("MP3 44.1kHz · 128 kbps")

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_elevenlabs_voiceover import (  # noqa: E402
    DOWNLOAD_SELECTOR,
    ElevenLabsUI,
    output_format_identity,
    setting_label_matches,
)


def test_output_format_identity_ignores_ui_typography() -> None:
    assert output_format_identity("MP3 44.1 kHz (128kbps)") == output_format_identity("MP3 44.1kHz · 128 kbps")


def test_setting_label_matches_provider_descriptor_suffix() -> None:
    assert setting_label_matches("Jerry B - Jolly", "Jerry B - Jolly Santa Claus")
    assert setting_label_matches("Eleven Multilingual v2", "Eleven Multilingual v2")
    assert not setting_label_matches("Jerry B - Jolly", None)
    assert not setting_label_matches("Jerry", "Jerry B - Jolly")


def test_download_uses_canonical_selector_with_pointer_gesture() -> None:
    ui = object.__new__(ElevenLabsUI)
    calls: list[str] = []

    def activate(selector: str) -> dict[str, object]:
        calls.append(selector)
        return {"ok": True, "text": "Download latest"}

    ui._pointer_activate_selector = activate  # type: ignore[method-assign]

    assert ui.download_best_available() == {"ok": True, "choice": "Download latest"}
    assert calls == [DOWNLOAD_SELECTOR]

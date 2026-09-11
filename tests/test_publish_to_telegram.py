from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from publish_to_telegram import upload_progress_body  # noqa: E402


def test_upload_progress_is_compact_and_measured() -> None:
    body = upload_progress_body("007", "compressed", 5 * 1024 * 1024, 10 * 1024 * 1024)
    assert "Video 007 · Telegram upload" in body
    assert "50%" in body
    assert "5.0/10.0 MB" in body
    assert len(body) < 500

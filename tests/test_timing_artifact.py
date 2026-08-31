import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_full_video_pipeline import valid_timing_artifact  # noqa: E402


class TimingArtifactTests(unittest.TestCase):
    def test_only_real_word_stt_timing_is_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            timing = Path(directory) / "BEAT_TIMINGS.json"
            timing.write_text(json.dumps({"stt": {"backend": "ajil", "timestamp_source": "word", "fallback_used": False}}))
            self.assertTrue(valid_timing_artifact(timing))

            timing.write_text(json.dumps({"stt": {"backend": "proportional", "timestamp_source": "script_proportional", "fallback_used": True}}))
            self.assertFalse(valid_timing_artifact(timing))

            timing.write_text(json.dumps({"stt": {"backend": "ajil", "timestamp_source": "segment_interpolated", "fallback_used": False}}))
            self.assertFalse(valid_timing_artifact(timing))


if __name__ == "__main__":
    unittest.main()

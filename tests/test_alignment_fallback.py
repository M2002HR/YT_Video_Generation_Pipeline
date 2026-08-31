from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import align_beats  # noqa: E402


class AlignmentFallbackTests(unittest.TestCase):
    def test_proportional_fallback_uses_exact_approved_tokens(self) -> None:
        beats = [
            {"narration": "A strong opening.", "tokens": ["a", "strong", "opening"]},
            {"narration": "Then the answer.", "tokens": ["then", "the", "answer"]},
        ]
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "narration.mp3"
            audio.write_bytes(b"placeholder")
            with mock.patch.object(align_beats, "ffprobe_duration", return_value=30.0):
                words, transcript, duration, metadata = align_beats.transcribe_proportional(audio, beats)
        self.assertEqual([word.token for word in words], ["a", "strong", "opening", "then", "the", "answer"])
        self.assertEqual(transcript, "A strong opening. Then the answer.")
        self.assertEqual(duration, 30.0)
        self.assertEqual(metadata["timestamp_source"], "script_proportional")
        self.assertLess(words[0].start, words[-1].end)


if __name__ == "__main__":
    unittest.main()

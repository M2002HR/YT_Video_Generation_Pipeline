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

class UnlocatableBeatTests(unittest.TestCase):
    """A beat with no matched token has guessed timing, and a guess must not ship."""

    def _words(self, tokens: list[str], *, duration: float = 12.0) -> list:
        step = duration / max(len(tokens), 1)
        return [
            align_beats.WordStamp(text=token, token=token, start=index * step, end=(index + 1) * step)
            for index, token in enumerate(tokens)
        ]

    def test_a_beat_absent_from_the_transcript_fails_alignment(self) -> None:
        beats = [
            {"beat_id": 1, "narration": "The kettle boils.", "tokens": ["the", "kettle", "boils"]},
            {"beat_id": 2, "narration": "Nothing spoken here.", "tokens": ["zzqq", "wwxx", "vvyy"]},
        ]
        words = self._words(["the", "kettle", "boils"])
        with self.assertRaises(ValueError) as caught:
            align_beats.align_beats(beats, words, 12.0)
        self.assertIn("could not be located", str(caught.exception))
        self.assertIn("2", str(caught.exception))

    def test_fully_matched_beats_align_without_complaint(self) -> None:
        beats = [
            {"beat_id": 1, "narration": "The kettle boils.", "tokens": ["the", "kettle", "boils"]},
            {"beat_id": 2, "narration": "Steam clouds the window.", "tokens": ["steam", "clouds", "the", "window"]},
        ]
        words = self._words(["the", "kettle", "boils", "steam", "clouds", "the", "window"])
        aligned = align_beats.align_beats(beats, words, 12.0)
        self.assertEqual([beat["beat_id"] for beat in aligned], [1, 2])
        self.assertTrue(all(beat["match_confidence"] > 0 for beat in aligned))
        self.assertLess(aligned[0]["speech_end"], aligned[1]["speech_end"])


if __name__ == "__main__":
    unittest.main()

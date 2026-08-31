import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_pixabay_music as music  # noqa: E402
from run_pixabay_music import Browser, choose_track, resumable_selected_url, track_urls, valid_track_url  # noqa: E402


class MusicUrlSelectionTests(unittest.TestCase):
    def test_accepts_canonical_mixkit_item_url(self) -> None:
        self.assertEqual(
            valid_track_url("http://mixkit.co/free-stock-music/item/443/?from=chat", "mixkit"),
            "https://mixkit.co/free-stock-music/item/443/",
        )

    def test_reads_rendered_anchor_href_not_only_message_text(self) -> None:
        values = ["Here is the right track", "https://www.mixkit.co/free-stock-music/item/443/"]
        self.assertEqual(track_urls(values, "mixkit"), {"https://www.mixkit.co/free-stock-music/item/443/"})

    def test_rejects_catalogue_and_cross_provider_urls(self) -> None:
        self.assertIsNone(valid_track_url("https://mixkit.co/free-stock-music/ambient/", "mixkit"))
        self.assertIsNone(valid_track_url("https://pixabay.com/music/ambient-track-1/", "mixkit"))

    def test_strips_chat_punctuation(self) -> None:
        self.assertEqual(
            track_urls(["Use (https://mixkit.co/free-stock-music/item/100/)."], "mixkit"),
            {"https://mixkit.co/free-stock-music/item/100/"},
        )

    def test_ignores_a_stale_link_from_an_earlier_chat_turn(self) -> None:
        class FakeBrowser:
            def __init__(self) -> None:
                self.snapshots = [
                    ["https://mixkit.co/free-stock-music/item/100/"],
                    ["https://mixkit.co/free-stock-music/item/100/", "https://mixkit.co/free-stock-music/item/443/"],
                ]

            def select_or_open(self, _url: str) -> None: pass
            def data(self, _expression: str) -> dict: return {"ready": True}
            def insert_and_submit(self, _text: str) -> None: pass
            def track_url_snapshot(self) -> list[str]: return self.snapshots.pop(0)

        self.assertEqual(
            choose_track(FakeBrowser(), "https://chatgpt.com/project", "choose a track", "mixkit"),
            "https://mixkit.co/free-stock-music/item/443/",
        )

    def test_browser_data_retries_an_empty_devtools_result(self) -> None:
        browser = Browser.__new__(Browser)
        browser.tab = object()
        responses = iter(["", '{"ready": true}'])
        browser.execute = lambda *_args: next(responses)
        self.assertEqual(browser.data("({ready:true})"), {"ready": True})

    def test_selected_url_is_resumed_after_an_interrupted_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "MUSIC_SELECTION.json"
            state.write_text(json.dumps({"status": "SELECTED", "source_url": "https://mixkit.co/free-stock-music/item/168/"}), encoding="utf-8")
            self.assertEqual(resumable_selected_url(state, "mixkit"), "https://mixkit.co/free-stock-music/item/168/")

    def test_browser_failure_installs_a_verified_cached_track(self) -> None:
        class Notifier:
            def warning(self, *_args) -> bool: return True
            def stage_complete(self, *_args, **_kwargs) -> bool: return True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_project = root / "videos" / "001_source"
            source = source_project / "assets" / "music" / "background.mp3"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"audio" * 20_000)
            project = root / "videos" / "002_target"
            meta_path = project / "music" / "MUSIC_SELECTION.json"
            candidate_meta = {"source_url": "https://mixkit.co/free-stock-music/item/443/", "license": "Mixkit source license"}
            with mock.patch.object(music, "ROOT", root), mock.patch.object(music, "audio_duration", return_value=113.0), mock.patch.object(music, "cached_music_candidates", return_value=[(source, candidate_meta, source_project)]):
                output = music.install_cached_fallback(project, "mixkit", meta_path, RuntimeError("browser unavailable"), 0.0, Notifier())
            self.assertTrue(output.is_file())
            receipt = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "DONE")
            self.assertEqual(receipt["selection_mode"], "CACHE_FALLBACK")
            self.assertIn("browser unavailable", receipt["fallback_reason"])

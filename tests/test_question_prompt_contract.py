from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "projects" / "world_behind_the_question" / "prompts" / "pipeline"


class QuestionPromptContractTests(unittest.TestCase):
    def read(self, name: str) -> str:
        return (PROMPTS / name).read_text(encoding="utf-8")

    def test_script_and_retention_require_hook_payoff_and_short_cta(self) -> None:
        for name in ("01_script_writer.md", "02_retention_editor.md"):
            prompt = self.read(name).lower()
            self.assertIn("6–10", prompt)
            self.assertIn("payoff", prompt)
            self.assertIn("12 spoken words", prompt)
            self.assertIn("like", prompt)
            self.assertIn("subscrib", prompt)

    def test_visual_prompts_keep_current_stills_and_future_video_contract(self) -> None:
        planner = self.read("03_visual_beats.md")
        image_writer = self.read("04_single_beat_image_prompt_writer.md")
        self.assertIn("Opening Hook Block", planner)
        self.assertIn("2–3", planner)
        self.assertIn("generated video clip", planner)
        self.assertIn("still generate exactly one image now", image_writer)

    def test_default_project_prompts_are_not_changed_by_this_contract(self) -> None:
        default_script = (ROOT / "projects" / "default" / "prompts" / "pipeline" / "01_script_writer.md").read_text(encoding="utf-8")
        self.assertNotIn("Opening Hook Block", default_script)


if __name__ == "__main__":
    unittest.main()

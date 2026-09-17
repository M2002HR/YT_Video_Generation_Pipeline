from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / 'projects' / 'q_station' / 'prompts' / 'pipeline'

class QuestionPromptContractTests(unittest.TestCase):

    def read(self, name: str) -> str:
        return (PROMPTS / name).read_text(encoding='utf-8')
if __name__ == '__main__':
    unittest.main()

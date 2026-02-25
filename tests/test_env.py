from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from grader.env import load_dotenv_if_present


class EnvLoaderTests(unittest.TestCase):
    def test_loads_values_from_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                """
# comment
GEMINI_API_KEY="abc123"
EMPTY_VALUE=
""".strip(),
                encoding="utf-8",
            )

            os.environ.pop("GEMINI_API_KEY", None)
            loaded = load_dotenv_if_present(env_path)
            self.assertEqual(loaded["GEMINI_API_KEY"], "abc123")
            self.assertEqual(os.environ["GEMINI_API_KEY"], "abc123")

    def test_does_not_override_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("GEMINI_API_KEY=fromfile\n", encoding="utf-8")

            os.environ["GEMINI_API_KEY"] = "fromenv"
            loaded = load_dotenv_if_present(env_path)
            self.assertEqual(loaded, {})
            self.assertEqual(os.environ["GEMINI_API_KEY"], "fromenv")


if __name__ == "__main__":
    unittest.main()

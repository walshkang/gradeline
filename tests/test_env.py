from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from grader.env import load_dotenv_if_present, update_env_file


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

    def test_update_env_file_creates_file_and_sets_environ(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            os.environ.pop("GEMINI_API_KEY", None)

            update_env_file(env_path, "GEMINI_API_KEY", "abc123")

            contents = env_path.read_text(encoding="utf-8")
            self.assertEqual(contents, "GEMINI_API_KEY=abc123\n")
            self.assertEqual(os.environ["GEMINI_API_KEY"], "abc123")

    def test_update_env_file_replaces_existing_and_preserves_others(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "# comment\nFOO=bar\nGEMINI_API_KEY=old\nBAZ=qux\n",
                encoding="utf-8",
            )

            os.environ["GEMINI_API_KEY"] = "old"
            update_env_file(env_path, "GEMINI_API_KEY", "newvalue")

            contents = env_path.read_text(encoding="utf-8")
            lines = contents.splitlines()
            self.assertIn("# comment", lines[0])
            self.assertIn("FOO=bar", lines[1])
            self.assertIn("BAZ=qux", lines[-1])
            self.assertEqual(lines.count("GEMINI_API_KEY=newvalue"), 1)
            self.assertTrue(contents.endswith("\n"))
            self.assertEqual(os.environ["GEMINI_API_KEY"], "newvalue")

    def test_update_env_file_deduplicates_multiple_existing_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "# header\nGEMINI_API_KEY=old1\nFOO=bar\nGEMINI_API_KEY=old2\n",
                encoding="utf-8",
            )

            os.environ["GEMINI_API_KEY"] = "old1"
            update_env_file(env_path, "GEMINI_API_KEY", "newvalue")

            contents = env_path.read_text(encoding="utf-8")
            lines = contents.splitlines()
            # Header and unrelated vars are preserved.
            self.assertIn("# header", lines[0])
            self.assertIn("FOO=bar", contents)
            # Only a single updated definition should remain.
            self.assertEqual(lines.count("GEMINI_API_KEY=newvalue"), 1)
            # File should end with exactly one trailing newline.
            self.assertTrue(contents.endswith("\n"))


if __name__ == "__main__":
    unittest.main()

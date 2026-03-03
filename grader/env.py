from __future__ import annotations

import os
from pathlib import Path


def load_dotenv_if_present(path: Path | None = None, *, override: bool = False) -> dict[str, str]:
    dotenv_path = path or Path(".env")
    if not dotenv_path.exists() or not dotenv_path.is_file():
        return {}

    loaded: dict[str, str] = {}
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if "=" not in raw:
            continue

        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            continue

        value = value.strip()
        if len(value) >= 2 and ((value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'"))):
            value = value[1:-1]

        if override or key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


def update_env_file(env_path: Path, key: str, value: str) -> None:
    """
    Create or update a .env-style file with a single KEY=VALUE definition.

    - Preserves comments and unrelated variables.
    - Normalizes to a single definition for the given key.
    - Ensures the file ends with exactly one trailing newline.
    - Updates os.environ[key] so the new value is visible in the current process.
    """
    key = key.strip()
    if not key:
        raise ValueError("Environment variable name must be non-empty.")

    try:
        if not env_path.exists():
            env_path.write_text(f"{key}={value}\n", encoding="utf-8")
            os.environ[key] = value
            return

        raw_text = env_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"Failed to read .env file {env_path}: {exc}") from exc

    lines = raw_text.splitlines()
    out_lines: list[str] = []
    found = False

    for line in lines:
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            if name == key:
                if not found:
                    out_lines.append(f"{key}={value}")
                    found = True
                # Skip any additional definitions for this key.
                continue
        out_lines.append(line)

    if not found:
        out_lines.append(f"{key}={value}")

    new_text = "\n".join(out_lines)
    if not new_text.endswith("\n"):
        new_text += "\n"

    try:
        env_path.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        raise OSError(f"Failed to write .env file {env_path}: {exc}") from exc

    os.environ[key] = value

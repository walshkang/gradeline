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

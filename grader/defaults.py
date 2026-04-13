from __future__ import annotations

from pathlib import Path
import tomllib

# Centralized defaults for the grader project. The CLI provides a command
# to mutate configs/defaults.toml so this file reflects the repo-level defaults
# at runtime. Falling back to a reasonable default if no config is present.

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULTS_CONFIG = (PROJECT_ROOT / "configs" / "defaults.toml").resolve()


def _read_defaults() -> dict[str, str]:
    if not DEFAULTS_CONFIG.exists():
        return {}
    try:
        raw = DEFAULTS_CONFIG.read_text(encoding="utf-8")
        payload = tomllib.loads(raw)
        if isinstance(payload, dict):
            return payload.get("defaults", {}) or {}
        return {}
    except Exception:
        return {}


# Module-level DEFAULT_MODEL used across the package. Updated by set_default_model
# at runtime when the CLI command is invoked.
_defaults = _read_defaults()
DEFAULT_MODEL: str = _defaults.get("model") or "gemma4-31b-it"


def set_default_model(model: str) -> None:
    """Write the project-level defaults file and update the in-process value.

    This writes configs/defaults.toml with a simple [defaults] section.
    """
    DEFAULTS_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    content = f"[defaults]\nmodel = \"{model}\"\n"
    DEFAULTS_CONFIG.write_text(content, encoding="utf-8")

    # Update in-process value so subsequent imports in the same Python process
    # reflect the change without needing to re-import the module.
    global DEFAULT_MODEL
    DEFAULT_MODEL = model

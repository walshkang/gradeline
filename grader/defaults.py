from __future__ import annotations

from pathlib import Path
import tomllib

# Centralized defaults for the grader project. The CLI provides a command
# to mutate configs/defaults.toml so this file reflects the repo-level defaults
# at runtime. Falling back to a reasonable default if no config is present.

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULTS_CONFIG = (PROJECT_ROOT / "configs" / "defaults.toml").resolve()


def _read_defaults() -> dict:
    if not DEFAULTS_CONFIG.exists():
        return {}
    try:
        raw = DEFAULTS_CONFIG.read_text(encoding="utf-8")
        payload = tomllib.loads(raw)
        if isinstance(payload, dict):
            return payload
        return {}
    except Exception:
        return {}


_defaults = _read_defaults()
# Grading model: check [models].grading, then legacy [defaults].model, then hardcoded fallback.
DEFAULT_MODEL: str = (
    (_defaults.get("models") or {}).get("grading")
    or (_defaults.get("defaults") or {}).get("model")
    or "gemma4-31b-it"
)
DEFAULT_EXTRACTION_MODEL: str = (
    (_defaults.get("models") or {}).get("extraction")
    or "gemini-2.0-flash"
)


def set_default_model(model: str) -> None:
    """Update [models].grading in configs/defaults.toml without touching other sections."""
    DEFAULTS_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if DEFAULTS_CONFIG.exists():
        try:
            payload = tomllib.loads(DEFAULTS_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    else:
        payload = {}

    # Preserve all existing sections; just update the grading model key.
    models = dict(payload.get("models") or {})
    models["grading"] = model
    payload["models"] = models

    lines: list[str] = []
    for section, value in payload.items():
        lines.append(f"[{section}]")
        if isinstance(value, dict):
            for k, v in value.items():
                lines.append(f'{k} = "{v}"')
        lines.append("")
    DEFAULTS_CONFIG.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    # Update in-process value so subsequent imports in the same Python process
    # reflect the change without needing to re-import the module.
    global DEFAULT_MODEL
    DEFAULT_MODEL = model

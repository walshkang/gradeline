from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .types import dump_state_json, utc_now_iso


def review_dir_for_output(output_dir: Path) -> Path:
    return output_dir / "review"


def state_path_for_output(output_dir: Path) -> Path:
    return review_dir_for_output(output_dir) / "review_state.json"


def events_path_for_output(output_dir: Path) -> Path:
    return review_dir_for_output(output_dir) / "review_events.jsonl"


def ensure_review_dir(output_dir: Path) -> Path:
    path = review_dir_for_output(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_state(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Review state must be a JSON object: {path}")
    return payload


def write_state_atomic(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = dump_state_json(payload)

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        tmp_path = Path(handle.name)
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())

    tmp_path.replace(path)
    return path


def append_event(events_path: Path, action: str, payload: dict[str, Any] | None = None) -> None:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": utc_now_iso(),
        "action": str(action).strip(),
        "payload": payload or {},
    }
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def touch_updated_at(state: dict[str, Any]) -> None:
    run_metadata = state.setdefault("run_metadata", {})
    run_metadata["updated_at"] = utc_now_iso()

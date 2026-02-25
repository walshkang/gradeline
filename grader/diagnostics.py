from __future__ import annotations

import json
import traceback
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_TRACEBACK_LIMIT = 1600


@dataclass(frozen=True)
class DiagnosticEvent:
    timestamp: str
    severity: str
    code: str
    stage: str
    message: str
    submission_folder: str | None = None
    exception_type: str | None = None
    traceback_snippet: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "severity": self.severity,
            "code": self.code,
            "stage": self.stage,
            "submission_folder": self.submission_folder,
            "message": self.message,
            "exception_type": self.exception_type,
            "traceback_snippet": self.traceback_snippet,
        }


class DiagnosticsCollector:
    def __init__(self, args_snapshot: dict[str, Any], run_id: str | None = None) -> None:
        self.run_id = run_id or uuid.uuid4().hex
        self.started_at = utc_now_iso()
        self.ended_at: str | None = None
        self.args_snapshot = args_snapshot
        self.events: list[DiagnosticEvent] = []
        self._run_totals: dict[str, Any] = {}

    def record(
        self,
        *,
        severity: str,
        code: str,
        stage: str,
        message: str,
        submission_folder: str | None = None,
        exc: Exception | None = None,
        traceback_limit: int = DEFAULT_TRACEBACK_LIMIT,
    ) -> None:
        exception_type: str | None = None
        traceback_snippet: str | None = None
        if exc is not None:
            exception_type = type(exc).__name__
            rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
            if rendered:
                traceback_snippet = rendered[-traceback_limit:]
        self.events.append(
            DiagnosticEvent(
                timestamp=utc_now_iso(),
                severity=str(severity).strip().lower(),
                code=str(code).strip(),
                stage=str(stage).strip(),
                submission_folder=submission_folder,
                message=message.strip(),
                exception_type=exception_type,
                traceback_snippet=traceback_snippet,
            )
        )

    def set_run_totals(self, totals: dict[str, Any]) -> None:
        self._run_totals = dict(totals)

    def to_payload(self) -> dict[str, Any]:
        self._finalize_time()
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "args_snapshot": self.args_snapshot,
            "totals": self._build_totals(),
            "events": [event.to_dict() for event in self.events],
        }

    def write_json(self, path: Path) -> Path:
        payload = self.to_payload()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def _finalize_time(self) -> None:
        if self.ended_at is None:
            self.ended_at = utc_now_iso()

    def _build_totals(self) -> dict[str, Any]:
        by_severity = Counter(event.severity for event in self.events)
        by_stage = Counter(event.stage for event in self.events)
        by_code = Counter(event.code for event in self.events)
        totals: dict[str, Any] = {
            "event_count": len(self.events),
            "by_severity": dict(sorted(by_severity.items())),
            "by_stage": dict(sorted(by_stage.items())),
            "by_code": dict(sorted(by_code.items())),
        }
        totals.update(self._run_totals)
        return totals


def serialize_cli_args(args: Any) -> dict[str, Any]:
    if hasattr(args, "__dict__"):
        payload = vars(args)
    elif isinstance(args, dict):
        payload = args
    else:
        return {"value": str(args)}
    return {str(key): _serialize_value(value) for key, value in payload.items()}


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

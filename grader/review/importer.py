from __future__ import annotations

import csv
import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..config import load_rubric
from ..discovery import discover_submission_units
from ..types import QuestionResult, SubmissionUnit
from .state import append_event, ensure_review_dir, events_path_for_output, state_path_for_output, write_state_atomic
from .types import (
    SCHEMA_VERSION,
    grade_points_from_args_snapshot,
    normalize_coords,
    question_result_to_payload,
    rubric_to_dict,
    stable_submission_id,
    utc_now_iso,
)


class ReviewInitError(ValueError):
    """Raised when review state cannot be initialized from CLI artifacts."""


def initialize_review_state(output_dir: Path, rubric_yaml: Path | None = None) -> Path:
    ensure_review_dir(output_dir)
    diagnostics_path = output_dir / "grading_diagnostics.json"
    audit_path = output_dir / "grading_audit.csv"

    if not diagnostics_path.exists():
        raise ReviewInitError(f"Missing required diagnostics file: {diagnostics_path}")
    if not audit_path.exists():
        raise ReviewInitError(f"Missing required grading audit CSV: {audit_path}")

    diagnostics_payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    if not isinstance(diagnostics_payload, dict):
        raise ReviewInitError("Diagnostics payload must be a JSON object.")

    args_snapshot = diagnostics_payload.get("args_snapshot", {})
    if not isinstance(args_snapshot, dict):
        raise ReviewInitError("Diagnostics args_snapshot is missing or invalid.")

    rubric_path = resolve_rubric_path(explicit=rubric_yaml, args_snapshot=args_snapshot)
    rubric = load_rubric(rubric_path)
    grade_points = grade_points_from_args_snapshot(args_snapshot)

    submissions_root = path_or_none(args_snapshot.get("submissions_dir"))
    discovered_units = discover_units_safe(submissions_root)

    rows = read_grading_audit_rows(audit_path)
    grouped_rows: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        folder = row.get("folder", "").strip()
        if not folder:
            continue
        grouped_rows.setdefault(folder, []).append(row)

    submissions: dict[str, dict[str, Any]] = {}
    for folder, folder_rows in sorted(grouped_rows.items(), key=lambda item: item[0].lower()):
        unit = resolve_submission_unit(folder=folder, rows=folder_rows, discovered_units=discovered_units, submissions_root=submissions_root)
        submission_payload = build_submission_payload(unit=unit, rows=folder_rows)
        submissions[submission_payload["submission_id"]] = submission_payload

    now = utc_now_iso()
    state = {
        "schema_version": SCHEMA_VERSION,
        "run_metadata": {
            "run_id": str(diagnostics_payload.get("run_id") or uuid.uuid4().hex),
            "output_dir": str(output_dir),
            "diagnostics_path": str(diagnostics_path),
            "initialized_at": now,
            "updated_at": now,
        },
        "grading_context": {
            "args_snapshot": args_snapshot,
            "rubric": rubric_to_dict(rubric),
            "grade_points": grade_points,
        },
        "submissions": submissions,
    }

    state_path = state_path_for_output(output_dir)
    write_state_atomic(state_path, state)
    append_event(
        events_path_for_output(output_dir),
        "state_initialized",
        {
            "submission_count": len(submissions),
            "state_path": str(state_path),
            "rubric_yaml": str(rubric_path),
        },
    )
    return state_path


def resolve_rubric_path(explicit: Path | None, args_snapshot: dict[str, Any]) -> Path:
    candidate: Path | None = None
    if explicit is not None:
        candidate = explicit
    elif args_snapshot.get("rubric_yaml"):
        candidate = Path(str(args_snapshot["rubric_yaml"]))

    if candidate is None:
        raise ReviewInitError(
            "Rubric path was not provided and diagnostics args_snapshot.rubric_yaml is missing. "
            "Pass --rubric-yaml to review init."
        )
    if not candidate.exists():
        raise ReviewInitError(f"Rubric YAML not found: {candidate}")
    return candidate


def path_or_none(value: Any) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return Path(raw)


def discover_units_safe(submissions_root: Path | None) -> dict[str, SubmissionUnit]:
    if submissions_root is None or not submissions_root.exists() or not submissions_root.is_dir():
        return {}
    units = discover_submission_units(submissions_root)
    return {str(unit.folder_relpath): unit for unit in units}


def read_grading_audit_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def resolve_submission_unit(
    *,
    folder: str,
    rows: list[dict[str, str]],
    discovered_units: dict[str, SubmissionUnit],
    submissions_root: Path | None,
) -> SubmissionUnit:
    if folder in discovered_units:
        return discovered_units[folder]

    student_name = rows[0].get("student_name", "").strip() if rows else ""
    if discovered_units and student_name:
        lowered = student_name.lower()
        for unit in discovered_units.values():
            if unit.student_name.lower() == lowered:
                return unit

    folder_token = folder.split(" - ")[0] if folder else "unknown"
    folder_relpath = Path(folder)
    folder_path = (submissions_root / folder_relpath) if submissions_root else folder_relpath

    pdf_paths = infer_pdf_paths(rows=rows, submissions_root=submissions_root, folder_relpath=folder_relpath)
    return SubmissionUnit(
        folder_path=folder_path,
        folder_relpath=folder_relpath,
        folder_token=folder_token,
        student_name=student_name or folder,
        pdf_paths=pdf_paths,
    )


def infer_pdf_paths(
    *,
    rows: list[dict[str, str]],
    submissions_root: Path | None,
    folder_relpath: Path,
) -> list[Path]:
    discovered: list[Path] = []
    if submissions_root is not None:
        expected_dir = submissions_root / folder_relpath
        if expected_dir.exists() and expected_dir.is_dir():
            discovered.extend(sorted(expected_dir.rglob("*.pdf"), key=lambda path: str(path)))
    if discovered:
        return discovered

    raw_pdfs = rows[0].get("pdfs", "") if rows else ""
    values = [item.strip() for item in raw_pdfs.split(";") if item.strip()]
    paths: list[Path] = []
    for item in values:
        path = Path(item)
        if not path.is_absolute() and submissions_root is not None:
            path = submissions_root / folder_relpath / path.name
        paths.append(path)
    return paths


def build_submission_payload(unit: SubmissionUnit, rows: list[dict[str, str]]) -> dict[str, Any]:
    folder_key = str(unit.folder_relpath)
    submission_id = stable_submission_id(folder_key, unit.folder_token, unit.student_name)

    question_map: dict[str, dict[str, Any]] = {}
    has_needs_review = False

    for row in rows:
        question_id = str(row.get("question_id", "")).strip().lower()
        if not question_id:
            continue
        auto_payload = row_to_question_payload(row)
        if auto_payload["verdict"] == "needs_review":
            has_needs_review = True
        question_map[question_id] = {
            "id": question_id,
            "auto": auto_payload,
            "final": deepcopy(auto_payload),
            "is_overridden": False,
            "updated_at": utc_now_iso(),
        }

    first = rows[0] if rows else {}
    auto_summary = {
        "percent": parse_float(first.get("percent"), default=0.0),
        "band": str(first.get("band", "REVIEW_REQUIRED")),
        "points": str(first.get("points", "")),
        "error": str(first.get("error", "")),
        "flags": [],
    }

    review_status = "todo" if (auto_summary["error"] or has_needs_review) else "in_progress"
    now = utc_now_iso()
    return {
        "submission_id": submission_id,
        "identity": {
            "folder_path": str(unit.folder_path),
            "folder_relpath": str(unit.folder_relpath),
            "folder_token": unit.folder_token,
            "student_name": unit.student_name,
            "pdf_paths": [str(path) for path in unit.pdf_paths],
        },
        "auto_summary": auto_summary,
        "final_summary": {
            "percent": auto_summary["percent"],
            "band": auto_summary["band"],
            "points": auto_summary["points"],
        },
        "review_status": review_status,
        "note": "",
        "questions": question_map,
        "updated_at": now,
    }


def row_to_question_payload(row: dict[str, str]) -> dict[str, Any]:
    y = parse_float(row.get("coords_y"), default=None)
    x = parse_float(row.get("coords_x"), default=None)
    coords = normalize_coords([y, x]) if (y is not None and x is not None) else None

    question_result = QuestionResult(
        id=str(row.get("question_id", "")).strip().lower(),
        verdict=str(row.get("verdict", "needs_review")).strip().lower(),
        confidence=parse_float(row.get("confidence"), default=0.0) or 0.0,
        logic_analysis=str(row.get("logic_analysis", "")),
        short_reason=str(row.get("reason", "")),
        detail_reason=str(row.get("detail_reason", "")),
        evidence_quote=str(row.get("evidence_quote", "")),
        coords=(coords[0], coords[1]) if coords else None,
        page_number=parse_int(row.get("page_number"), default=None),
        source_file=str(row.get("source_file", "")).strip() or None,
        placement_source=str(row.get("placement_source", "")).strip() or None,
    )
    return question_result_to_payload(question_result)


def parse_float(value: Any, default: float | None) -> float | None:
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_int(value: Any, default: int | None) -> int | None:
    if value is None or str(value).strip() == "":
        return default
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    if number < 1:
        return default
    return number

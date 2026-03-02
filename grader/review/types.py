from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..types import QuestionResult, QuestionRubric, RubricConfig

SCHEMA_VERSION = 1
VERDICT_VALUES = {"correct", "partial", "rounding_error", "incorrect", "needs_review"}
DEFAULT_GRADE_POINTS = {
    "Check Plus": "100",
    "Check": "85",
    "Check Minus": "65",
    "REVIEW_REQUIRED": "",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_submission_id(folder_relpath: str, folder_token: str, student_name: str) -> str:
    norm = "|".join([folder_relpath.strip(), folder_token.strip(), student_name.strip()])
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:10]  # noqa: S324
    slug = re.sub(r"[^a-z0-9]+", "-", folder_relpath.lower()).strip("-")
    slug = slug[:50] if slug else "submission"
    return f"{slug}-{digest}"


def rubric_to_dict(rubric: RubricConfig) -> dict[str, Any]:
    return asdict(rubric)


def rubric_from_dict(payload: dict[str, Any]) -> RubricConfig:
    questions: list[QuestionRubric] = []
    for item in payload.get("questions", []):
        if not isinstance(item, dict):
            continue
        questions.append(
            QuestionRubric(
                id=str(item.get("id", "")).strip().lower(),
                label_patterns=[str(v) for v in item.get("label_patterns", [])],
                scoring_rules=str(item.get("scoring_rules", "")),
                short_note_pass=str(item.get("short_note_pass", "OK")),
                short_note_fail=str(item.get("short_note_fail", "Check")),
                weight=float(item.get("weight", 1.0)),
                anchor_tokens=[str(v) for v in item.get("anchor_tokens", [])],
            )
        )

    return RubricConfig(
        assignment_id=str(payload.get("assignment_id", "assignment")),
        bands={
            "check_plus_min": float(payload.get("bands", {}).get("check_plus_min", 0.9)),
            "check_min": float(payload.get("bands", {}).get("check_min", 0.7)),
        },
        questions=questions,
        scoring_mode=str(payload.get("scoring_mode", "equal_weights")),
        partial_credit=float(payload.get("partial_credit", 0.5)),
    )


def grade_points_from_args_snapshot(args_snapshot: dict[str, Any]) -> dict[str, str]:
    return {
        "Check Plus": str(args_snapshot.get("check_plus_points", DEFAULT_GRADE_POINTS["Check Plus"])),
        "Check": str(args_snapshot.get("check_points", DEFAULT_GRADE_POINTS["Check"])),
        "Check Minus": str(args_snapshot.get("check_minus_points", DEFAULT_GRADE_POINTS["Check Minus"])),
        "REVIEW_REQUIRED": str(
            args_snapshot.get("review_required_points", DEFAULT_GRADE_POINTS["REVIEW_REQUIRED"])
        ),
    }


def normalize_coords(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        y = float(value[0])
        x = float(value[1])
    except (TypeError, ValueError):
        return None
    return [max(0.0, min(1000.0, y)), max(0.0, min(1000.0, x))]


def question_result_to_payload(result: QuestionResult) -> dict[str, Any]:
    return {
        "verdict": result.verdict,
        "confidence": float(result.confidence),
        "logic_analysis": str(result.logic_analysis),
        "short_reason": str(result.short_reason),
        "detail_reason": str(result.detail_reason),
        "evidence_quote": str(result.evidence_quote),
        "coords": list(result.coords) if result.coords is not None else None,
        "page_number": int(result.page_number) if result.page_number is not None else None,
        "source_file": str(result.source_file) if result.source_file else None,
        "placement_source": str(result.placement_source) if result.placement_source else None,
    }


def question_result_from_payload(question_id: str, payload: dict[str, Any]) -> QuestionResult:
    coords = normalize_coords(payload.get("coords"))
    page_number: int | None = None
    raw_page = payload.get("page_number")
    if raw_page is not None:
        try:
            value = int(raw_page)
            page_number = value if value >= 1 else None
        except (TypeError, ValueError):
            page_number = None
    return QuestionResult(
        id=question_id,
        verdict=str(payload.get("verdict", "needs_review")).strip().lower(),
        confidence=float(payload.get("confidence", 0.0)),
        logic_analysis=str(payload.get("logic_analysis", "")),
        short_reason=str(payload.get("short_reason", "")),
        detail_reason=str(payload.get("detail_reason", "")),
        evidence_quote=str(payload.get("evidence_quote", "")),
        coords=(coords[0], coords[1]) if coords else None,
        page_number=page_number,
        source_file=str(payload.get("source_file") or "").strip() or None,
        placement_source=str(payload.get("placement_source") or "").strip() or None,
    )


def dump_state_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def ensure_path_list(values: list[Any]) -> list[Path]:
    result: list[Path] = []
    for value in values:
        value_str = str(value).strip()
        if not value_str:
            continue
        result.append(Path(value_str))
    return result

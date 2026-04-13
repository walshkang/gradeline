from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_PROFILE_DIR = Path(".manual_runs") / "profiles"
from .defaults import DEFAULT_MODEL
DEFAULT_GRADING_MODE = "unified"
DEFAULT_REVIEW_HOST = "127.0.0.1"
DEFAULT_REVIEW_PORT = 8765
DEFAULT_CONTEXT_CACHE_TTL_SECONDS = 86400
DEFAULT_OCR_CHAR_THRESHOLD = 200


class WorkflowProfileError(ValueError):
    """Raised when a workflow profile is missing or invalid."""


@dataclass(frozen=True)
class GradeProfile:
    submissions_dir: Path
    solutions_pdf: Path
    rubric_yaml: Path
    grades_template_csv: Path
    grade_column: str
    output_dir: Path
    temp_dir: Path | None = None
    cache_dir: Path | None = None
    grading_mode: str = DEFAULT_GRADING_MODE
    provider: str = "gemini"
    model: str = DEFAULT_MODEL
    locator_model: str = ""
    api_key_env: str = "GEMINI_API_KEY"
    identifier_column: str = "OrgDefinedId"
    comment_column: str = ""
    ocr_char_threshold: int = DEFAULT_OCR_CHAR_THRESHOLD
    student_filter: str = ""
    dry_run: bool = False
    annotate_dry_run_marks: bool = False
    check_plus_points: str = "100"
    check_points: str = "85"
    check_minus_points: str = "65"
    review_required_points: str = ""
    context_cache: bool = True
    context_cache_ttl_seconds: int = DEFAULT_CONTEXT_CACHE_TTL_SECONDS
    concurrency: int = 5
    plain: bool = False
    diagnostics_file: Path | None = None
    annotation_font_size: float = 24.0


@dataclass(frozen=True)
class ReviewProfile:
    host: str = DEFAULT_REVIEW_HOST
    port: int = DEFAULT_REVIEW_PORT


@dataclass(frozen=True)
class WorkflowProfile:
    name: str
    path: Path
    grade: GradeProfile
    review: ReviewProfile


REQUIRED_ROOT_KEYS = {"grade"}
ALLOWED_ROOT_KEYS = {"grade", "review"}

REQUIRED_GRADE_KEYS = {
    "submissions_dir",
    "solutions_pdf",
    "rubric_yaml",
    "grades_template_csv",
    "grade_column",
    "output_dir",
}
ALLOWED_GRADE_KEYS = REQUIRED_GRADE_KEYS | {
    "temp_dir",
    "cache_dir",
    "grading_mode",
    "provider",
    "model",
    "locator_model",
    "api_key_env",
    "identifier_column",
    "comment_column",
    "ocr_char_threshold",
    "student_filter",
    "dry_run",
    "annotate_dry_run_marks",
    "check_plus_points",
    "check_points",
    "check_minus_points",
    "review_required_points",
    "context_cache",
    "context_cache_ttl_seconds",
    "concurrency",
    "plain",
    "diagnostics_file",
    "annotation_font_size",
}
ALLOWED_REVIEW_KEYS = {"host", "port"}

PATH_GRADE_FIELDS = {
    "submissions_dir",
    "solutions_pdf",
    "rubric_yaml",
    "grades_template_csv",
    "output_dir",
    "temp_dir",
    "cache_dir",
    "diagnostics_file",
}
INT_GRADE_FIELDS = {"ocr_char_threshold", "context_cache_ttl_seconds", "concurrency"}
FLOAT_GRADE_FIELDS = {"annotation_font_size"}
BOOL_GRADE_FIELDS = {"dry_run", "annotate_dry_run_marks", "context_cache", "plain"}
STRING_GRADE_FIELDS = {
    "grade_column",
    "grading_mode",
    "provider",
    "model",
    "locator_model",
    "api_key_env",
    "identifier_column",
    "comment_column",
    "student_filter",
}
POINT_GRADE_FIELDS = {
    "check_plus_points",
    "check_points",
    "check_minus_points",
    "review_required_points",
}


def load_workflow_profile(
    profile: str | Path,
    *,
    cwd: Path | None = None,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
) -> WorkflowProfile:
    if not str(profile).strip():
        raise WorkflowProfileError("Profile name/path must be non-empty.")

    cwd_path = (cwd or Path.cwd()).resolve()
    path = resolve_profile_path(profile, cwd=cwd_path, profile_dir=profile_dir)
    if not path.exists() or not path.is_file():
        raise WorkflowProfileError(f"Profile file not found: {path}")

    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise WorkflowProfileError(f"Failed to parse profile TOML {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise WorkflowProfileError(f"Profile payload must be an object: {path}")

    _validate_allowed_keys(
        section="profile root",
        payload=payload,
        allowed=ALLOWED_ROOT_KEYS,
    )
    _validate_required_keys(
        section="profile root",
        payload=payload,
        required=REQUIRED_ROOT_KEYS,
    )

    grade_payload = payload.get("grade")
    if not isinstance(grade_payload, dict):
        raise WorkflowProfileError("Profile [grade] section is missing or invalid.")
    _validate_allowed_keys(section="[grade]", payload=grade_payload, allowed=ALLOWED_GRADE_KEYS)
    _validate_required_keys(section="[grade]", payload=grade_payload, required=REQUIRED_GRADE_KEYS)

    review_payload = payload.get("review", {})
    if not isinstance(review_payload, dict):
        raise WorkflowProfileError("Profile [review] section must be an object.")
    _validate_allowed_keys(section="[review]", payload=review_payload, allowed=ALLOWED_REVIEW_KEYS)

    grade = _parse_grade_section(grade_payload, path.parent)
    review = _parse_review_section(review_payload)
    return WorkflowProfile(
        name=path.stem,
        path=path,
        grade=grade,
        review=review,
    )


def list_profile_paths(
    *,
    cwd: Path | None = None,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
) -> list[Path]:
    cwd_path = (cwd or Path.cwd()).resolve()
    root = (cwd_path / profile_dir).resolve()
    if not root.exists() or not root.is_dir():
        return []
    return sorted(path.resolve() for path in root.glob("*.toml") if path.is_file())


def resolve_profile_path(
    profile: str | Path,
    *,
    cwd: Path | None = None,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
) -> Path:
    cwd_path = (cwd or Path.cwd()).resolve()
    spec = str(profile).strip()
    if not spec:
        raise WorkflowProfileError("Profile name/path must be non-empty.")

    is_explicit = (
        spec.endswith(".toml")
        or "/" in spec
        or "\\" in spec
        or Path(spec).is_absolute()
    )
    if is_explicit:
        return _normalize_path(spec, base_dir=cwd_path).resolve()
    return (cwd_path / profile_dir / f"{spec}.toml").resolve()


def _parse_grade_section(payload: dict[str, Any], profile_dir: Path) -> GradeProfile:
    values: dict[str, Any] = {}
    for key, raw in payload.items():
        if key in PATH_GRADE_FIELDS:
            values[key] = _normalize_path_value(raw, profile_dir=profile_dir, field=key)
            continue
        if key in INT_GRADE_FIELDS:
            values[key] = _coerce_int(raw, field=key)
            continue
        if key in FLOAT_GRADE_FIELDS:
            values[key] = _coerce_float(raw, field=key)
            continue
        if key in BOOL_GRADE_FIELDS:
            values[key] = _coerce_bool(raw, field=key)
            continue
        if key in STRING_GRADE_FIELDS:
            values[key] = _coerce_string(raw, field=key, allow_empty=key == "comment_column")
            continue
        if key in POINT_GRADE_FIELDS:
            values[key] = _coerce_points(raw, field=key)
            continue
        raise WorkflowProfileError(f"Unsupported [grade] key '{key}'.")

    for required in REQUIRED_GRADE_KEYS:
        if required not in values:
            raise WorkflowProfileError(f"Missing required [grade] key '{required}'.")

    return GradeProfile(**values)


def _parse_review_section(payload: dict[str, Any]) -> ReviewProfile:
    host = DEFAULT_REVIEW_HOST
    port = DEFAULT_REVIEW_PORT
    if "host" in payload:
        host = _coerce_string(payload["host"], field="review.host", allow_empty=False)
    if "port" in payload:
        port = _coerce_int(payload["port"], field="review.port")
    if port <= 0 or port > 65535:
        raise WorkflowProfileError(f"Field review.port must be 1..65535, got {port}.")
    return ReviewProfile(host=host, port=port)


def _normalize_path_value(raw: Any, *, profile_dir: Path, field: str) -> Path:
    if not isinstance(raw, str):
        raise WorkflowProfileError(f"Field {field} must be a string path.")
    return _normalize_path(raw, base_dir=profile_dir)


def _normalize_path(raw: str, *, base_dir: Path) -> Path:
    import re
    clean_raw = re.sub(r'\\(.)', r'\1', raw.strip("\"'"))
    expanded = os.path.expandvars(clean_raw)
    expanded = os.path.expanduser(expanded)
    path = Path(expanded)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _coerce_int(raw: Any, *, field: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise WorkflowProfileError(f"Field {field} must be an integer.")
    return raw


def _coerce_float(raw: Any, *, field: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise WorkflowProfileError(f"Field {field} must be a number.")
    return float(raw)


def _coerce_bool(raw: Any, *, field: str) -> bool:
    if not isinstance(raw, bool):
        raise WorkflowProfileError(f"Field {field} must be a boolean.")
    return raw


def _coerce_string(raw: Any, *, field: str, allow_empty: bool = False) -> str:
    if not isinstance(raw, str):
        raise WorkflowProfileError(f"Field {field} must be a string.")
    value = raw.strip()
    if not value and not allow_empty:
        raise WorkflowProfileError(f"Field {field} must be non-empty.")
    return value


def _coerce_points(raw: Any, *, field: str) -> str:
    if isinstance(raw, bool):
        raise WorkflowProfileError(f"Field {field} must be a string or number.")
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, (int, float)):
        return str(raw)
    raise WorkflowProfileError(f"Field {field} must be a string or number.")


def _validate_allowed_keys(*, section: str, payload: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if not unknown:
        return
    allowed_text = ", ".join(sorted(allowed))
    raise WorkflowProfileError(f"Unknown keys in {section}: {unknown}. Allowed keys: [{allowed_text}]")


def _validate_required_keys(*, section: str, payload: dict[str, Any], required: set[str]) -> None:
    missing = sorted(required - set(payload))
    if not missing:
        return
    raise WorkflowProfileError(f"Missing required keys in {section}: {missing}")

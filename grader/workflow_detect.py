from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generic, TypeVar

from .workflow_profile import (
    DEFAULT_PROFILE_DIR,
    DEFAULT_REVIEW_HOST,
    DEFAULT_REVIEW_PORT,
    WorkflowProfile,
    WorkflowProfileError,
    list_profile_paths,
    load_workflow_profile,
    resolve_profile_path,
)


DOWNLOADS_RECENCY_DAYS = 7
DEFAULT_QUESTION_IDS = ("a", "b", "c", "d", "e")
_GRADE_COLUMN_ASSIGNMENT_RE = re.compile(r"\bassignment\s*([0-9]+)\b", flags=re.IGNORECASE)
_POINTS_GRADE_RE = re.compile(r"\bpoints\b.*\bgrade\b", flags=re.IGNORECASE)
_SOLUTION_HINT_RE = re.compile(r"(soln|solution|answers|key)", flags=re.IGNORECASE)

OPTIONAL_GRADE_FIELDS = (
    "temp_dir",
    "cache_dir",
    "grading_mode",
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
    "plain",
    "diagnostics_file",
    "annotation_font_size",
)

_OPTIONAL_PATH_FIELDS = {"temp_dir", "cache_dir", "diagnostics_file"}
_OPTIONAL_INT_FIELDS = {"ocr_char_threshold", "context_cache_ttl_seconds"}
_OPTIONAL_FLOAT_FIELDS = {"annotation_font_size"}
_OPTIONAL_BOOL_FIELDS = {"dry_run", "annotate_dry_run_marks", "context_cache", "plain"}
_OPTIONAL_STRING_FIELDS = {
    "grading_mode",
    "model",
    "locator_model",
    "api_key_env",
    "identifier_column",
    "comment_column",
    "student_filter",
}
_OPTIONAL_POINTS_FIELDS = {
    "check_plus_points",
    "check_points",
    "check_minus_points",
    "review_required_points",
}


T = TypeVar("T")


@dataclass(frozen=True)
class DetectedField(Generic[T]):
    value: T | None
    source: str
    confidence: float
    candidates: tuple[T, ...] = ()


@dataclass(frozen=True)
class DiscoveryContext:
    cwd: Path
    profile_path: Path
    profile_name: str
    assignment_token: str | None
    downloads_dir: Path
    recency_days: int


@dataclass(frozen=True)
class ProfileRunSnapshot:
    profile_path: Path
    diagnostics_path: Path
    started_at: str
    totals: dict[str, Any]
    args_snapshot: dict[str, Any]


@dataclass(frozen=True)
class DetectedConfig:
    context: DiscoveryContext
    submissions_dir: DetectedField[Path]
    solutions_pdf: DetectedField[Path]
    rubric_yaml: DetectedField[Path]
    grades_template_csv: DetectedField[Path]
    grade_column: DetectedField[str]
    output_dir: DetectedField[Path]
    host: DetectedField[str]
    port: DetectedField[int]
    optional_grade_values: dict[str, Any]
    prior_rubric_question_ids: tuple[str, ...]


def detect_defaults(
    profile_spec: str,
    cwd: Path,
    *,
    downloads_dir: Path | None = None,
    recency_days: int = DOWNLOADS_RECENCY_DAYS,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
) -> DetectedConfig:
    cwd_resolved = cwd.resolve()
    profile_path = resolve_profile_path(profile_spec, cwd=cwd_resolved, profile_dir=profile_dir)
    profile_name = profile_path.stem
    assignment_token = _extract_assignment_token(profile_name)
    context = DiscoveryContext(
        cwd=cwd_resolved,
        profile_path=profile_path,
        profile_name=profile_name,
        assignment_token=assignment_token,
        downloads_dir=(downloads_dir or (Path.home() / "Downloads")).resolve(),
        recency_days=recency_days,
    )

    existing_profile = _load_profile_if_present(profile_path)
    snapshots = find_recent_profile_runs(cwd=cwd_resolved, profile_dir=profile_dir)
    best_snapshot = snapshots[0] if snapshots else None

    downloads = scan_downloads_candidates(
        profile_name=profile_name,
        assignment_token=assignment_token,
        downloads_dir=context.downloads_dir,
        recency_days=recency_days,
    )

    optional_values = _detect_optional_grade_values(
        existing_profile=existing_profile,
        best_snapshot=best_snapshot,
        cwd=cwd_resolved,
    )

    # Derive candidates from a structured data/{profile}/ directory.
    data_root = (cwd_resolved / "data" / profile_name).resolve()
    data_submissions: list[Path] = []
    data_solutions: list[Path] = []
    data_grades: list[Path] = []
    if data_root.exists() and data_root.is_dir():
        subs_dir = data_root / "submissions"
        if subs_dir.exists() and subs_dir.is_dir() and _has_pdf_one_level_down(subs_dir):
            data_submissions.append(subs_dir)

        solutions_path = data_root / "solutions.pdf"
        if solutions_path.exists() and solutions_path.is_file():
            data_solutions.append(solutions_path)
        else:
            pdfs = sorted(data_root.glob("*.pdf"))
            if pdfs:
                data_solutions.append(pdfs[0])

        grades_path = data_root / "grades.csv"
        if grades_path.exists() and grades_path.is_file():
            data_grades.append(grades_path)
        else:
            csvs = sorted(data_root.glob("*.csv"))
            if csvs:
                data_grades.append(csvs[0])

    submissions_dir = _choose_path_field(
        existing_value=existing_profile.grade.submissions_dir if existing_profile else None,
        snapshot_value=_snapshot_path(best_snapshot, "submissions_dir", cwd_resolved),
        data_values=data_submissions,
        downloads_values=downloads.get("submissions_dir", []),
        default_value=None,
    )
    solutions_pdf = _choose_path_field(
        existing_value=existing_profile.grade.solutions_pdf if existing_profile else None,
        snapshot_value=_snapshot_path(best_snapshot, "solutions_pdf", cwd_resolved),
        data_values=data_solutions,
        downloads_values=downloads.get("solutions_pdf", []),
        default_value=None,
    )
    grades_template_csv = _choose_path_field(
        existing_value=existing_profile.grade.grades_template_csv if existing_profile else None,
        snapshot_value=_snapshot_path(best_snapshot, "grades_template_csv", cwd_resolved),
        data_values=data_grades,
        downloads_values=downloads.get("grades_template_csv", []),
        default_value=None,
    )

    rubric_default = (cwd_resolved / "configs" / f"{profile_name}.yaml").resolve()
    rubric_yaml = _choose_path_field(
        existing_value=existing_profile.grade.rubric_yaml if existing_profile else None,
        snapshot_value=_snapshot_path(best_snapshot, "rubric_yaml", cwd_resolved),
        data_values=[],
        downloads_values=[],
        default_value=rubric_default,
    )

    output_default = (cwd_resolved / "outputs" / profile_name).resolve()
    output_dir = _choose_path_field(
        existing_value=existing_profile.grade.output_dir if existing_profile else None,
        snapshot_value=_snapshot_path(best_snapshot, "output_dir", cwd_resolved),
        data_values=[],
        downloads_values=[],
        default_value=output_default,
    )

    grade_column_requested = _snapshot_str(best_snapshot, "grade_column")
    if existing_profile is not None:
        grade_column_requested = existing_profile.grade.grade_column

    grade_column_candidates = _grade_column_candidates_for_detected_csv(
        grades_template_csv.value,
        assignment_token=assignment_token,
    )
    default_grade_column = (
        f"Assignment {assignment_token} Points Grade" if assignment_token is not None else "Assignment 1 Points Grade"
    )

    if grade_column_requested:
        grade_column_value = grade_column_requested
        grade_column_source = "profile" if existing_profile is not None else "recent_run"
        grade_column_conf = 0.95 if existing_profile is not None else 0.85
    elif grade_column_candidates:
        grade_column_value = grade_column_candidates[0]
        grade_column_source = "template_inference"
        grade_column_conf = 0.7
    else:
        grade_column_value = default_grade_column
        grade_column_source = "default"
        grade_column_conf = 0.35
    grade_column = DetectedField(
        value=grade_column_value,
        source=grade_column_source,
        confidence=grade_column_conf,
        candidates=tuple(_dedupe_values(grade_column_candidates + [grade_column_value])),
    )

    host_value = existing_profile.review.host if existing_profile else DEFAULT_REVIEW_HOST
    host = DetectedField(
        value=host_value,
        source="profile" if existing_profile else "default",
        confidence=0.95 if existing_profile else 0.4,
        candidates=(host_value,),
    )

    port_value = existing_profile.review.port if existing_profile else DEFAULT_REVIEW_PORT
    port = DetectedField(
        value=port_value,
        source="profile" if existing_profile else "default",
        confidence=0.95 if existing_profile else 0.4,
        candidates=(port_value,),
    )

    prior_rubric_path = _snapshot_path(best_snapshot, "rubric_yaml", cwd_resolved)
    prior_ids = infer_question_ids_from_prior_rubric(prior_rubric_path) if prior_rubric_path else []

    return DetectedConfig(
        context=context,
        submissions_dir=submissions_dir,
        solutions_pdf=solutions_pdf,
        rubric_yaml=rubric_yaml,
        grades_template_csv=grades_template_csv,
        grade_column=grade_column,
        output_dir=output_dir,
        host=host,
        port=port,
        optional_grade_values=optional_values,
        prior_rubric_question_ids=tuple(prior_ids),
    )


def find_recent_profile_runs(
    *,
    cwd: Path,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
) -> list[ProfileRunSnapshot]:
    snapshots: list[ProfileRunSnapshot] = []
    for profile_path in list_profile_paths(cwd=cwd, profile_dir=profile_dir):
        try:
            profile = load_workflow_profile(profile_path, cwd=cwd, profile_dir=profile_dir)
        except WorkflowProfileError:
            continue
        diagnostics_path = _diagnostics_path_for_profile(profile)
        if not diagnostics_path.exists() or not diagnostics_path.is_file():
            continue
        payload = _read_json_object(diagnostics_path)
        if not payload:
            continue
        totals = payload.get("totals", {})
        if not isinstance(totals, dict):
            continue
        submissions_processed = _coerce_int(totals.get("submissions_processed"), default=0)
        if submissions_processed <= 0:
            continue
        args_snapshot = payload.get("args_snapshot", {})
        if not isinstance(args_snapshot, dict):
            args_snapshot = {}
        started_at = str(payload.get("started_at", "")).strip()
        snapshots.append(
            ProfileRunSnapshot(
                profile_path=profile.path.resolve(),
                diagnostics_path=diagnostics_path.resolve(),
                started_at=started_at,
                totals=totals,
                args_snapshot=args_snapshot,
            )
        )
    return sorted(snapshots, key=_snapshot_sort_key)


def scan_downloads_candidates(
    *,
    profile_name: str,
    assignment_token: str | None = None,
    downloads_dir: Path | None = None,
    recency_days: int = DOWNLOADS_RECENCY_DAYS,
) -> dict[str, list[Path]]:
    root = (downloads_dir or (Path.home() / "Downloads")).expanduser().resolve()
    candidates: dict[str, list[Path]] = {
        "submissions_dir": [],
        "solutions_pdf": [],
        "grades_template_csv": [],
    }
    if not root.exists() or not root.is_dir():
        return candidates

    cutoff_epoch = datetime.now(timezone.utc).timestamp() - (recency_days * 86400)
    scored_submissions: list[tuple[int, float, Path]] = []
    scored_solutions: list[tuple[int, float, Path]] = []
    scored_csv: list[tuple[int, float, Path]] = []

    try:
        entries = list(os.scandir(root))
    except OSError:
        return candidates

    for entry in entries:
        try:
            stat = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if stat.st_mtime < cutoff_epoch:
            continue
        path = Path(entry.path).resolve()
        lowered_name = entry.name.lower()

        if entry.is_dir(follow_symlinks=False):
            score = _score_submissions_directory(path, lowered_name, profile_name, assignment_token)
            if score > 0:
                scored_submissions.append((score, stat.st_mtime, path))
            continue

        if not entry.is_file(follow_symlinks=False):
            continue
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            score = _score_solution_pdf(path.name.lower(), profile_name, assignment_token)
            if score > 0:
                scored_solutions.append((score, stat.st_mtime, path))
            continue
        if suffix == ".csv":
            inferred = infer_grade_column_from_csv(path, assignment_token=assignment_token)
            if inferred:
                score = _score_grade_csv(path.name.lower(), profile_name, assignment_token)
                scored_csv.append((score, stat.st_mtime, path))

    candidates["submissions_dir"] = [item[2] for item in _sort_scored_paths(scored_submissions)]
    candidates["solutions_pdf"] = [item[2] for item in _sort_scored_paths(scored_solutions)]
    candidates["grades_template_csv"] = [item[2] for item in _sort_scored_paths(scored_csv)]
    return candidates


def infer_grade_column_from_csv(csv_path: Path, assignment_token: str | None = None) -> str | None:
    candidates = _grade_column_candidates_for_detected_csv(csv_path, assignment_token=assignment_token)
    return candidates[0] if candidates else None


def infer_question_ids_from_prior_rubric(rubric_path: Path | None) -> list[str]:
    if rubric_path is None or not rubric_path.exists() or not rubric_path.is_file():
        return []
    try:
        raw_text = rubric_path.read_text(encoding="utf-8")
    except OSError:
        return []

    try:
        import yaml  # Lazy import for quickstart-only rubric inference.

        payload = yaml.safe_load(raw_text)
    except Exception:  # noqa: BLE001
        payload = None

    ids: list[str] = []
    if isinstance(payload, dict):
        questions = payload.get("questions")
        if isinstance(questions, list):
            for item in questions:
                if not isinstance(item, dict):
                    continue
                qid = str(item.get("id", "")).strip().lower()
                if not qid:
                    continue
                ids.append(qid)
            if ids:
                return _dedupe_values(ids)

    # Fallback parser for environments without PyYAML dependency.
    for line in raw_text.splitlines():
        match = re.match(r'^\s*-\s*id:\s*["\']?([a-z0-9_-]+)["\']?\s*$', line.strip(), flags=re.IGNORECASE)
        if match is None:
            continue
        ids.append(match.group(1).lower())
    return _dedupe_values(ids)


def default_question_ids() -> tuple[str, ...]:
    return DEFAULT_QUESTION_IDS


def _load_profile_if_present(profile_path: Path) -> WorkflowProfile | None:
    if not profile_path.exists() or not profile_path.is_file():
        return None
    try:
        return load_workflow_profile(profile_path)
    except WorkflowProfileError:
        return None


def _diagnostics_path_for_profile(profile: WorkflowProfile) -> Path:
    if profile.grade.diagnostics_file is not None:
        return profile.grade.diagnostics_file.resolve()
    return (profile.grade.output_dir / "grading_diagnostics.json").resolve()


def _detect_optional_grade_values(
    *,
    existing_profile: WorkflowProfile | None,
    best_snapshot: ProfileRunSnapshot | None,
    cwd: Path,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if best_snapshot is not None:
        for field in OPTIONAL_GRADE_FIELDS:
            snapshot_value = _snapshot_optional_value(best_snapshot, field, cwd)
            if snapshot_value is not None:
                values[field] = snapshot_value
    if existing_profile is not None:
        grade = existing_profile.grade
        for field in OPTIONAL_GRADE_FIELDS:
            values[field] = getattr(grade, field)
    return values


def _snapshot_optional_value(snapshot: ProfileRunSnapshot, field: str, cwd: Path) -> Any | None:
    if field not in snapshot.args_snapshot:
        return None
    raw = snapshot.args_snapshot.get(field)
    if field in _OPTIONAL_PATH_FIELDS:
        return _coerce_path(raw, cwd)
    if field in _OPTIONAL_INT_FIELDS:
        return _coerce_int_or_none(raw)
    if field in _OPTIONAL_FLOAT_FIELDS:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    if field in _OPTIONAL_BOOL_FIELDS:
        return _coerce_bool_or_none(raw)
    if field in _OPTIONAL_STRING_FIELDS:
        text = str(raw or "").strip()
        if field == "comment_column":
            return text
        return text or None
    if field in _OPTIONAL_POINTS_FIELDS:
        text = str(raw or "").strip()
        return text if text else None
    return None


def _snapshot_path(snapshot: ProfileRunSnapshot | None, key: str, cwd: Path) -> Path | None:
    if snapshot is None:
        return None
    return _coerce_path(snapshot.args_snapshot.get(key), cwd)


def _snapshot_str(snapshot: ProfileRunSnapshot | None, key: str) -> str | None:
    if snapshot is None:
        return None
    text = str(snapshot.args_snapshot.get(key) or "").strip()
    return text or None


def _choose_path_field(
    *,
    existing_value: Path | None,
    snapshot_value: Path | None,
    data_values: list[Path],
    downloads_values: list[Path],
    default_value: Path | None = None,
) -> DetectedField[Path]:
    candidate_values = _dedupe_values(
        [value for value in [existing_value, snapshot_value] if value is not None]
        + list(data_values)
        + list(downloads_values)
    )
    if existing_value is not None:
        return DetectedField(
            value=existing_value.resolve(),
            source="profile",
            confidence=0.98,
            candidates=tuple(candidate_values),
        )
    if snapshot_value is not None:
        return DetectedField(
            value=snapshot_value.resolve(),
            source="recent_run",
            confidence=0.9,
            candidates=tuple(candidate_values),
        )
    if data_values:
        return DetectedField(
            value=data_values[0].resolve(),
            source="data",
            confidence=0.85,
            candidates=tuple(_dedupe_values(data_values)),
        )
    if downloads_values:
        return DetectedField(
            value=downloads_values[0].resolve(),
            source="downloads",
            confidence=0.6,
            candidates=tuple(_dedupe_values(downloads_values)),
        )
    if default_value is not None:
        default_resolved = default_value.resolve()
        return DetectedField(
            value=default_resolved,
            source="default",
            confidence=0.4,
            candidates=(default_resolved,),
        )
    return DetectedField(value=None, source="missing", confidence=0.0, candidates=())


def _grade_column_candidates_for_detected_csv(csv_path: Path | None, assignment_token: str | None) -> list[str]:
    if csv_path is None or not csv_path.exists() or not csv_path.is_file():
        return []
    headers = _read_csv_headers(csv_path)
    if not headers:
        return []
    return _infer_grade_columns_from_headers(headers, assignment_token=assignment_token)


def _infer_grade_columns_from_headers(headers: list[str], assignment_token: str | None) -> list[str]:
    candidates: list[str] = []
    lowered_headers = [header.lower() for header in headers]

    if assignment_token:
        assignment_pattern = re.compile(
            rf"\bassignment\s*{re.escape(assignment_token)}\b.*\bpoints\b.*\bgrade\b",
            flags=re.IGNORECASE,
        )
        for idx, lowered in enumerate(lowered_headers):
            if assignment_pattern.search(lowered):
                candidates.append(headers[idx])

    for idx, lowered in enumerate(lowered_headers):
        if _POINTS_GRADE_RE.search(lowered):
            candidates.append(headers[idx])

    for idx, lowered in enumerate(lowered_headers):
        if "assignment" in lowered and "grade" in lowered:
            candidates.append(headers[idx])

    return _dedupe_values(candidates)


def _read_csv_headers(path: Path) -> list[str]:
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            row = next(reader, None)
            if row is None:
                return []
            return [str(cell).strip() for cell in row]
    except OSError:
        return []


def _score_submissions_directory(path: Path, lowered_name: str, profile_name: str, assignment_token: str | None) -> int:
    if not _has_pdf_one_level_down(path):
        return 0
    score = 1
    if "download" in lowered_name:
        score += 2
    if "assignment" in lowered_name:
        score += 2
    if profile_name.lower() in lowered_name:
        score += 1
    if assignment_token and f"assignment {assignment_token}" in lowered_name:
        score += 2
    if assignment_token and f"a{assignment_token}" in lowered_name:
        score += 1
    return score


def _score_solution_pdf(lowered_name: str, profile_name: str, assignment_token: str | None) -> int:
    if not _SOLUTION_HINT_RE.search(lowered_name):
        return 0
    score = 2
    if profile_name.lower() in lowered_name:
        score += 1
    if assignment_token and f"{assignment_token}" in lowered_name:
        score += 1
    if "answer" in lowered_name or "key" in lowered_name:
        score += 1
    return score


def _score_grade_csv(lowered_name: str, profile_name: str, assignment_token: str | None) -> int:
    score = 1
    if "grade" in lowered_name:
        score += 1
    if profile_name.lower() in lowered_name:
        score += 1
    if assignment_token and assignment_token in lowered_name:
        score += 1
    return score


def _has_pdf_one_level_down(path: Path) -> bool:
    try:
        with os.scandir(path) as first_level:
            first_level_entries = list(first_level)
    except OSError:
        return False
    for entry in first_level_entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        try:
            with os.scandir(entry.path) as children:
                for child in children:
                    try:
                        if child.is_file(follow_symlinks=False) and child.name.lower().endswith(".pdf"):
                            return True
                    except OSError:
                        continue
        except OSError:
            continue
    return False


def _snapshot_sort_key(snapshot: ProfileRunSnapshot) -> tuple[float, int, int, str]:
    started_at = _parse_started_at(snapshot.started_at)
    started_rank = -started_at.timestamp() if started_at is not None else float("inf")
    success_count = _coerce_int(snapshot.totals.get("success_count"), default=0)
    failed_count = _coerce_int(snapshot.totals.get("failed_with_error_count"), default=0)
    return (started_rank, -success_count, failed_count, str(snapshot.profile_path))


def _parse_started_at(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _extract_assignment_token(text: str) -> str | None:
    match = _GRADE_COLUMN_ASSIGNMENT_RE.search(text)
    if match:
        return match.group(1)
    shorthand = re.search(r"\ba([0-9]+)\b", text, flags=re.IGNORECASE)
    if shorthand:
        return shorthand.group(1)
    return None


def _coerce_path(value: Any, cwd: Path) -> Path | None:
    import re
    raw = str(value or "").strip()
    if not raw:
        return None
    clean_raw = re.sub(r'\\(.)', r'\1', raw.strip("\"'"))
    expanded = os.path.expandvars(clean_raw)
    expanded = os.path.expanduser(expanded)
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    return candidate.resolve()


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _sort_scored_paths(values: list[tuple[int, float, Path]]) -> list[tuple[int, float, Path]]:
    return sorted(values, key=lambda item: (-item[0], -item[1], str(item[2]).lower()))


def _dedupe_values(values: list[T]) -> list[T]:
    unique: list[T] = []
    seen: set[Any] = set()
    for value in values:
        key = str(value).lower() if isinstance(value, (Path, str)) else value
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique

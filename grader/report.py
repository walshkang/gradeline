from __future__ import annotations

import csv
from pathlib import Path

from .discovery import normalize_name
from .types import JsonDict, SubmissionResult


def write_grading_audit_csv(output_dir: Path, results: list[SubmissionResult]) -> Path:
    output_path = output_dir / "grading_audit.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "folder",
                "student_name",
                "pdf_count",
                "pdfs",
                "percent",
                "band",
                "points",
                "question_id",
                "verdict",
                "confidence",
                "reason",
                "evidence_quote",
                "source_file",
                "page_number",
                "coords_y",
                "coords_x",
                "placement_source",
                "error",
            ]
        )
        for result in results:
            pdf_relpaths = ";".join(
                str(path.relative_to(output_dir)) if path.is_absolute() and path.exists() else path.name
                for path in result.output_pdf_paths
            )
            for q in result.question_results:
                writer.writerow(
                    [
                        str(result.submission.folder_relpath),
                        result.submission.student_name,
                        len(result.submission.pdf_paths),
                        pdf_relpaths,
                        f"{result.grade_result.percent:.2f}",
                        result.grade_result.band,
                        result.grade_result.points,
                        q.id,
                        q.verdict,
                        f"{q.confidence:.2f}",
                        q.short_reason,
                        q.evidence_quote,
                        q.source_file or "",
                        q.page_number if q.page_number is not None else "",
                        f"{q.coords[0]:.2f}" if q.coords else "",
                        f"{q.coords[1]:.2f}" if q.coords else "",
                        q.placement_source or "",
                        result.error or "",
                    ]
                )
    return output_path


def write_review_queue_csv(output_dir: Path, results: list[SubmissionResult]) -> Path:
    output_path = output_dir / "review_queue.csv"
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "folder",
                "student_name",
                "band",
                "percent",
                "needs_review_questions",
                "flags",
                "error",
            ]
        )
        for result in results:
            needs_review_q = [q.id for q in result.question_results if q.verdict == "needs_review"]
            if result.grade_result.band != "REVIEW_REQUIRED" and not result.error and not needs_review_q:
                continue
            writer.writerow(
                [
                    str(result.submission.folder_relpath),
                    result.submission.student_name,
                    result.grade_result.band,
                    f"{result.grade_result.percent:.2f}",
                    ",".join(needs_review_q),
                    ";".join(result.global_flags),
                    result.error or "",
                ]
            )
    return output_path


def write_brightspace_import_csv(
    output_dir: Path,
    template_csv_path: Path,
    submission_results: list[SubmissionResult],
    grade_column: str,
    identifier_column: str,
    comment_column: str | None = None,
) -> tuple[Path, list[str]]:
    rows, fieldnames = read_csv_rows(template_csv_path)
    resolved_grade_column = resolve_column_name(fieldnames, grade_column, kind="grade")
    resolved_identifier_column, identifier_warning = resolve_identifier_column(
        fieldnames, identifier_column
    )
    resolved_comment_column = (
        resolve_column_name(fieldnames, comment_column, kind="comment")
        if comment_column
        else None
    )

    result_by_token = {normalize_name(r.submission.folder_token): r for r in submission_results}
    result_by_name = {normalize_name(r.submission.student_name): r for r in submission_results}

    warnings: list[str] = []
    if identifier_warning:
        warnings.append(identifier_warning)
    matched_submission_ids: set[int] = set()

    for row in rows:
        result = find_matching_result(
            row=row,
            result_by_token=result_by_token,
            result_by_name=result_by_name,
            identifier_column=resolved_identifier_column,
        )
        if not result:
            continue
        matched_submission_ids.add(id(result))
        row[resolved_grade_column] = result.grade_result.points
        if resolved_comment_column:
            row[resolved_comment_column] = result.grade_result.band

    for result in submission_results:
        if id(result) not in matched_submission_ids:
            warnings.append(
                f"No grade-template match for submission folder '{result.submission.folder_relpath}' "
                f"(student '{result.submission.student_name}')."
            )

    output_path = output_dir / "brightspace_grades_import.csv"
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output_path, warnings


def find_matching_result(
    row: dict[str, str],
    result_by_token: dict[str, SubmissionResult],
    result_by_name: dict[str, SubmissionResult],
    identifier_column: str,
) -> SubmissionResult | None:
    identifier = normalize_name(row.get(identifier_column, ""))
    if identifier and identifier in result_by_token:
        return result_by_token[identifier]

    first = row.get("First Name", "").strip()
    last = row.get("Last Name", "").strip()
    if first or last:
        full_name = normalize_name(f"{first} {last}".strip())
        if full_name in result_by_name:
            return result_by_name[full_name]
        reverse_name = normalize_name(f"{last} {first}".strip())
        if reverse_name in result_by_name:
            return result_by_name[reverse_name]

    name_fields = ("Name", "Student", "Learner")
    for field in name_fields:
        if field in row and row[field].strip():
            candidate = normalize_name(row[field])
            if candidate in result_by_name:
                return result_by_name[candidate]
    return None


def read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        if reader.fieldnames is None:
            raise ValueError(f"CSV template has no header row: {path}")
        return rows, list(reader.fieldnames)


def resolve_column_name(fieldnames: list[str], requested: str, kind: str) -> str:
    if requested in fieldnames:
        return requested

    lowered = requested.lower()
    casefold_matches = [name for name in fieldnames if name.lower() == lowered]
    if len(casefold_matches) == 1:
        return casefold_matches[0]
    if len(casefold_matches) > 1:
        raise ValueError(
            f"Requested {kind} column '{requested}' matches multiple columns by case-insensitive name: "
            f"{casefold_matches}. Use the exact header name."
        )

    prefix_matches = [
        name for name in fieldnames if name.lower().startswith(lowered)
    ]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        raise ValueError(
            f"Requested {kind} column '{requested}' matched multiple prefix columns: {prefix_matches}. "
            "Use the exact header name."
        )

    raise ValueError(
        f"Requested {kind} column '{requested}' was not found in CSV headers: {fieldnames}"
    )


def resolve_identifier_column(fieldnames: list[str], requested: str) -> tuple[str, str | None]:
    try:
        return resolve_column_name(fieldnames, requested, kind="identifier"), None
    except ValueError:
        pass

    preferred_names = (
        "OrgDefinedId",
        "Org Defined ID",
        "Username",
        "User Name",
        "UserName",
    )

    for preferred in preferred_names:
        for field in fieldnames:
            if field.lower() == preferred.lower():
                return (
                    field,
                    f"Identifier column '{requested}' not found; using '{field}' instead.",
                )

    for field in fieldnames:
        normalized = field.lower().replace(" ", "")
        if "orgdefinedid" in normalized or "username" in normalized:
            return (
                field,
                f"Identifier column '{requested}' not found; using '{field}' instead.",
            )

    return (
        "",
        f"Identifier column '{requested}' not found; using name-based fallback matching only.",
    )


def write_index_audit_csv(output_dir: Path, audit_entries: list[JsonDict]) -> Path:
    output_path = output_dir / "index_audit.csv"
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["student_name", "submitted_filename", "submitted_at", "comments"])
        for item in audit_entries:
            writer.writerow(
                [
                    item.get("student_name", ""),
                    item.get("submitted_filename", ""),
                    item.get("submitted_at", ""),
                    item.get("comments", ""),
                ]
            )
    return output_path

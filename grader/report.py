from __future__ import annotations

import csv
from pathlib import Path

from .discovery import normalize_name
from .types import JsonDict, SubmissionResult


def write_grading_audit_csv(
    output_dir: Path,
    results: list[SubmissionResult],
    output_filename: str = "grading_audit.csv",
) -> Path:
    output_path = output_dir / output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    headers = [
        "folder",
        "student_name",
        "pdf_count",
        "pdfs",
        "percent",
        "band",
        "points",
        "question_id",
        "verdict",
        "grading_source",
        "confidence",
        "logic_analysis",
        "reason",
        "detail_reason",
        "evidence_quote",
        "source_file",
        "page_number",
        "coords_y",
        "coords_x",
        "placement_source",
        "error",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "cost_usd",
    ]

    regraded_folders = {str(r.submission.folder_relpath) for r in results}
    existing_rows = []
    
    if output_path.exists():
        with output_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            # Ensure headers match what we expect before trying to merge
            if reader.fieldnames and all(h in reader.fieldnames for h in headers):
                for row in reader:
                    if row.get("folder") not in regraded_folders:
                        existing_rows.append(row)
    
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction='ignore')
        writer.writeheader()
        if existing_rows:
            writer.writerows(existing_rows)
            
        for result in results:
            pdf_relpaths = ";".join(
                str(path.relative_to(output_dir)) if path.is_absolute() and path.exists() else path.name
                for path in result.output_pdf_paths
            )
            for q in result.question_results:
                t = q.token_usage
                q_logic = q.logic_analysis or ("Needs manual review." if q.verdict == "needs_review" else "")
                q_short = q.short_reason or ("Needs review." if q.verdict == "needs_review" else "")
                q_detail = q.detail_reason or ("Review required for final grade determination." if q.verdict == "needs_review" else "")
                writer.writerow(
                    {
                        "folder": str(result.submission.folder_relpath),
                        "student_name": result.submission.student_name,
                        "pdf_count": len(result.submission.pdf_paths),
                        "pdfs": pdf_relpaths,
                        "percent": f"{result.grade_result.percent:.2f}",
                        "band": result.grade_result.band,
                        "points": result.grade_result.points,
                        "question_id": q.id,
                        "verdict": q.verdict,
                        "grading_source": q.grading_source,
                        "confidence": f"{q.confidence:.2f}",
                        "logic_analysis": q_logic,
                        "reason": q_short,
                        "detail_reason": q_detail,
                        "evidence_quote": q.evidence_quote,
                        "source_file": q.source_file or "",
                        "page_number": q.page_number if q.page_number is not None else "",
                        "coords_y": f"{q.coords[0]:.2f}" if q.coords else "",
                        "coords_x": f"{q.coords[1]:.2f}" if q.coords else "",
                        "placement_source": q.placement_source or "",
                        "error": result.error or "",
                        "input_tokens": t.input_tokens if t else 0,
                        "output_tokens": t.output_tokens if t else 0,
                        "cached_tokens": t.cached_tokens if t else 0,
                        "cost_usd": f"{t.cost_usd:.6f}" if t else "0.000000",
                    }
                )
                if q.sub_results:
                    for sub in q.sub_results:
                        st = sub.token_usage or t
                        sub_logic = sub.logic_analysis or ("Needs manual review." if sub.verdict == "needs_review" else "")
                        sub_short = sub.short_reason or ("Needs review." if sub.verdict == "needs_review" else "")
                        sub_detail = sub.detail_reason or ("Review required for final grade determination." if sub.verdict == "needs_review" else "")
                        writer.writerow(
                            {
                                "folder": str(result.submission.folder_relpath),
                                "student_name": result.submission.student_name,
                                "pdf_count": len(result.submission.pdf_paths),
                                "pdfs": pdf_relpaths,
                                "percent": "",
                                "band": "",
                                "points": "",
                                "question_id": sub.id,
                                "verdict": sub.verdict,
                                "grading_source": f"sub_{sub.grading_source}",
                                "confidence": f"{sub.confidence:.2f}",
                                "logic_analysis": sub_logic,
                                "reason": sub_short,
                                "detail_reason": sub_detail,
                                "evidence_quote": sub.evidence_quote,
                                "source_file": sub.source_file or "",
                                "page_number": sub.page_number if sub.page_number is not None else "",
                                "coords_y": f"{sub.coords[0]:.2f}" if sub.coords else "",
                                "coords_x": f"{sub.coords[1]:.2f}" if sub.coords else "",
                                "placement_source": sub.placement_source or "",
                                "error": "",
                                "input_tokens": st.input_tokens if st else 0,
                                "output_tokens": st.output_tokens if st else 0,
                                "cached_tokens": st.cached_tokens if st else 0,
                                "cost_usd": f"{st.cost_usd:.6f}" if st else "0.000000",
                            }
                        )
    return output_path


def write_review_queue_csv(
    output_dir: Path,
    results: list[SubmissionResult],
    output_filename: str = "review_queue.csv",
) -> Path:
    output_path = output_dir / output_filename
    
    headers = [
        "folder",
        "student_name",
        "band",
        "percent",
        "needs_review_questions",
        "flags",
        "error",
    ]

    regraded_folders = {str(r.submission.folder_relpath) for r in results}
    existing_rows = []
    
    if output_path.exists():
        with output_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames and all(h in reader.fieldnames for h in headers):
                for row in reader:
                    if row.get("folder") not in regraded_folders:
                        existing_rows.append(row)
    
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction='ignore')
        writer.writeheader()
        if existing_rows:
            writer.writerows(existing_rows)
            
        for result in results:
            needs_review_q = [q.id for q in result.question_results if q.verdict == "needs_review"]
            if result.grade_result.band != "REVIEW_REQUIRED" and not result.error and not needs_review_q:
                continue
            writer.writerow(
                {
                    "folder": str(result.submission.folder_relpath),
                    "student_name": result.submission.student_name,
                    "band": result.grade_result.band,
                    "percent": f"{result.grade_result.percent:.2f}",
                    "needs_review_questions": ",".join(needs_review_q),
                    "flags": ";".join(result.global_flags),
                    "error": result.error or "",
                }
            )
    return output_path


def write_brightspace_import_csv(
    output_dir: Path,
    template_csv_path: Path,
    submission_results: list[SubmissionResult],
    grade_column: str,
    identifier_column: str,
    comment_column: str | None = None,
    output_filename: str = "brightspace_grades_import.csv",
) -> tuple[Path, list[str]]:
    template_rows, template_fieldnames = read_csv_rows(template_csv_path)
    
    output_path = output_dir / output_filename
    if output_path.exists():
        try:
            old_rows, old_fieldnames = read_csv_rows(output_path)
            if old_fieldnames == template_fieldnames:
                rows = old_rows
                fieldnames = old_fieldnames
            else:
                rows = template_rows
                fieldnames = template_fieldnames
        except Exception:
            rows = template_rows
            fieldnames = template_fieldnames
    else:
        rows = template_rows
        fieldnames = template_fieldnames

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
    if identifier:
        if identifier in result_by_token:
            return result_by_token[identifier]
        # Support prefix matching (e.g., OrgDefinedId "11774" matches folder token "117741199265")
        for token_key, result in result_by_token.items():
            if token_key.startswith(identifier) or identifier.startswith(token_key):
                return result

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


def write_index_audit_csv(
    output_dir: Path,
    audit_entries: list[JsonDict],
    output_filename: str = "index_audit.csv",
) -> Path:
    output_path = output_dir / output_filename
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

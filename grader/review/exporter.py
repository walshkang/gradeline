from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..annotate import annotate_submission_pdfs
from ..report import write_brightspace_import_csv, write_grading_audit_csv, write_review_queue_csv
from ..score import score_submission
from ..types import QuestionResult, SubmissionResult, SubmissionUnit
from .state import append_event, events_path_for_output, state_path_for_output
from .types import question_result_from_payload, rubric_from_dict, utc_now_iso


class ReviewExportError(ValueError):
    """Raised when review outputs cannot be exported."""


def export_review_outputs(output_dir: Path) -> dict[str, Path]:
    state_path = state_path_for_output(output_dir)
    if not state_path.exists():
        raise ReviewExportError(
            f"Review state not found: {state_path}. Run 'python3 -m grader.review_cli init --output-dir {output_dir}'."
        )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ReviewExportError(f"Invalid review state payload: {state_path}")

    grading_context = state.get("grading_context", {})
    if not isinstance(grading_context, dict):
        raise ReviewExportError("Invalid grading_context in review state.")
    rubric_payload = grading_context.get("rubric")
    if not isinstance(rubric_payload, dict):
        raise ReviewExportError("Missing rubric in review state grading_context.")
    rubric = rubric_from_dict(rubric_payload)

    grade_points = grading_context.get("grade_points")
    if not isinstance(grade_points, dict):
        raise ReviewExportError("Missing grade_points in review state grading_context.")
    score_points = {str(key): str(value) for key, value in grade_points.items()}

    args_snapshot = grading_context.get("args_snapshot", {})
    if not isinstance(args_snapshot, dict):
        args_snapshot = {}

    submissions_root = Path(str(args_snapshot.get("submissions_dir", "")).strip())
    if not str(submissions_root).strip():
        raise ReviewExportError("Missing submissions_dir in review state args_snapshot.")

    review_dir = output_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    reviewed_pdf_root = review_dir / "reviewed_pdfs"
    reviewed_pdf_root.mkdir(parents=True, exist_ok=True)

    submission_payloads = state.get("submissions", {})
    if not isinstance(submission_payloads, dict):
        raise ReviewExportError("Invalid submissions payload in review state.")

    results: list[SubmissionResult] = []
    for submission in submission_payloads.values():
        if not isinstance(submission, dict):
            continue
        results.append(
            build_submission_result(
                submission_payload=submission,
                rubric=rubric,
                score_points=score_points,
                submissions_root=submissions_root,
                reviewed_pdf_root=reviewed_pdf_root,
            )
        )

    artifacts: dict[str, Path] = {}
    artifacts["Grading audit reviewed CSV"] = write_grading_audit_csv(
        review_dir,
        results,
        output_filename="grading_audit_reviewed.csv",
    )
    artifacts["Review queue reviewed CSV"] = write_review_queue_csv(
        review_dir,
        results,
        output_filename="review_queue_reviewed.csv",
    )

    template_csv = Path(str(args_snapshot.get("grades_template_csv", "")).strip())
    grade_column = str(args_snapshot.get("grade_column", "")).strip()
    identifier_column = str(args_snapshot.get("identifier_column", "OrgDefinedId")).strip() or "OrgDefinedId"
    comment_column = str(args_snapshot.get("comment_column", "")).strip() or None
    if not template_csv.exists():
        raise ReviewExportError(
            "grades_template_csv from review state does not exist. Cannot write Brightspace reviewed import CSV."
        )
    if not grade_column:
        raise ReviewExportError("grade_column missing in review state args_snapshot.")

    brightspace_csv, _warnings = write_brightspace_import_csv(
        output_dir=review_dir,
        template_csv_path=template_csv,
        submission_results=results,
        grade_column=grade_column,
        identifier_column=identifier_column,
        comment_column=comment_column,
        output_filename="brightspace_grades_import_reviewed.csv",
    )
    artifacts["Brightspace reviewed import CSV"] = brightspace_csv

    decisions_path = review_dir / "review_decisions.json"
    decisions_payload = {
        "generated_at": utc_now_iso(),
        "run_metadata": state.get("run_metadata", {}),
        "grading_context": {
            "grade_points": score_points,
            "rubric": rubric_payload,
        },
        "submissions": submission_payloads,
    }
    decisions_path.write_text(json.dumps(decisions_payload, indent=2, sort_keys=True), encoding="utf-8")
    artifacts["Review decisions JSON"] = decisions_path

    append_event(
        events_path_for_output(output_dir),
        "review_exported",
        {
            "artifact_count": len(artifacts),
            "artifacts": {name: str(path) for name, path in artifacts.items()},
        },
    )

    return artifacts


def build_submission_result(
    *,
    submission_payload: dict[str, Any],
    rubric,
    score_points: dict[str, str],
    submissions_root: Path,
    reviewed_pdf_root: Path,
) -> SubmissionResult:
    unit = submission_unit_from_payload(submission_payload)

    question_payloads = submission_payload.get("questions", {})
    if not isinstance(question_payloads, dict):
        question_payloads = {}

    question_results = build_question_results(question_payloads=question_payloads, rubric_question_ids=[q.id for q in rubric.questions])

    grade_result = score_submission(rubric=rubric, question_results=question_results, grade_points=score_points)

    output_pdf_paths: list[Path] = []
    annotation_error: str | None = None
    if unit.pdf_paths and submissions_root.exists():
        try:
            output_pdf_paths, question_results = annotate_submission_pdfs(
                submission=unit,
                rubric=rubric,
                question_results=question_results,
                output_dir=reviewed_pdf_root,
                submissions_root=submissions_root,
                final_band=grade_result.band,
                dry_run=False,
                annotate_dry_run_marks=False,
            )
        except Exception as exc:  # noqa: BLE001
            annotation_error = f"Reviewed annotation failed: {exc}"
    else:
        annotation_error = "Reviewed annotation skipped: submission PDFs or submissions root missing."

    return SubmissionResult(
        submission=unit,
        question_results=question_results,
        grade_result=grade_result,
        output_pdf_paths=output_pdf_paths,
        extraction_sources={},
        global_flags=["manual_review"],
        error=annotation_error,
    )


def submission_unit_from_payload(submission_payload: dict[str, Any]) -> SubmissionUnit:
    identity = submission_payload.get("identity", {})
    if not isinstance(identity, dict):
        identity = {}

    folder_path = Path(str(identity.get("folder_path", "")).strip() or ".")
    folder_relpath = Path(str(identity.get("folder_relpath", "")).strip() or folder_path.name)
    folder_token = str(identity.get("folder_token", "")).strip() or folder_relpath.name
    student_name = str(identity.get("student_name", "")).strip() or folder_relpath.name

    pdf_paths_raw = identity.get("pdf_paths", [])
    pdf_paths: list[Path] = []
    if isinstance(pdf_paths_raw, list):
        for item in pdf_paths_raw:
            value = str(item).strip()
            if value:
                pdf_paths.append(Path(value))

    return SubmissionUnit(
        folder_path=folder_path,
        folder_relpath=folder_relpath,
        folder_token=folder_token,
        student_name=student_name,
        pdf_paths=pdf_paths,
    )


def build_question_results(*, question_payloads: dict[str, Any], rubric_question_ids: list[str]) -> list[QuestionResult]:
    results: list[QuestionResult] = []
    for question_id in rubric_question_ids:
        row = question_payloads.get(question_id)
        if not isinstance(row, dict):
            results.append(
                QuestionResult(
                    id=question_id,
                    verdict="needs_review",
                    confidence=0.0,
                    short_reason="Missing review result.",
                    evidence_quote="",
                )
            )
            continue
        final_payload = row.get("final", {})
        if not isinstance(final_payload, dict):
            final_payload = {}
        results.append(question_result_from_payload(question_id, final_payload))
    return results

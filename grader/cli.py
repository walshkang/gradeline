from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import replace
from pathlib import Path

from .annotate import annotate_submission_pdfs
from .config import load_rubric
from .diagnostics import DiagnosticsCollector, serialize_cli_args
from .discovery import discover_submission_units, parse_index_html
from .extract import ensure_binaries_present, extract_pdf_text
from .gemini_client import GeminiGrader
from .report import (
    write_brightspace_import_csv,
    write_grading_audit_csv,
    write_index_audit_csv,
    write_review_queue_csv,
)
from .score import score_submission
from .types import QuestionResult, SubmissionResult
from .ui import RunSummary, args_to_subtitle, create_console_ui


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gemini-backed Brightspace PDF grader.")
    parser.add_argument("--submissions-dir", required=True, type=Path)
    parser.add_argument("--solutions-pdf", required=True, type=Path)
    parser.add_argument("--rubric-yaml", required=True, type=Path)
    parser.add_argument("--grades-template-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--temp-dir", type=Path, default=Path(".grader_tmp"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".grader_cache"))
    parser.add_argument("--model", default="gemini-2.5-flash")
    parser.add_argument("--locator-model", default="")
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--identifier-column", default="OrgDefinedId")
    parser.add_argument("--grade-column", required=True)
    parser.add_argument("--comment-column", default="")
    parser.add_argument("--ocr-char-threshold", type=int, default=200)
    parser.add_argument("--student-filter", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--annotate-dry-run-marks", action="store_true")
    parser.add_argument("--check-plus-points", default="100")
    parser.add_argument("--check-points", default="85")
    parser.add_argument("--check-minus-points", default="65")
    parser.add_argument("--review-required-points", default="")
    parser.add_argument("--plain", action="store_true")
    parser.add_argument("--diagnostics-file", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    ui = create_console_ui(force_plain=args.plain)
    ui.banner("Brightspace PDF Grader", subtitle=args_to_subtitle(args))

    diagnostics = DiagnosticsCollector(args_snapshot=serialize_cli_args(args))
    diagnostics_path = args.diagnostics_file or (args.output_dir / "grading_diagnostics.json")
    artifacts: dict[str, Path | None] = {
        "Index audit CSV": None,
        "Grading audit CSV": None,
        "Review queue CSV": None,
        "Brightspace import CSV": None,
    }

    def conclude(exit_code: int, submission_results: list[SubmissionResult], warnings: list[str]) -> int:
        summary = summarize_results(submission_results=submission_results, warning_count=len(warnings))
        diagnostics.set_run_totals(
            {
                "submissions_processed": summary.submissions_processed,
                "success_count": summary.success_count,
                "review_required_count": summary.review_required_count,
                "failed_with_error_count": summary.failed_with_error_count,
                "warning_count": summary.warning_count,
            }
        )

        written_diagnostics: Path | None = None
        try:
            written_diagnostics = diagnostics.write_json(diagnostics_path)
        except Exception as exc:  # noqa: BLE001
            ui.warning(f"Failed to write diagnostics file {diagnostics_path}: {exc}")

        for warning in warnings:
            ui.warning(warning)

        ui.emit_summary(summary)
        artifact_payload = dict(artifacts)
        artifact_payload["Diagnostics JSON"] = written_diagnostics or diagnostics_path
        ui.emit_artifacts(artifact_payload)
        return exit_code

    missing = ensure_binaries_present()
    if missing:
        message = f"Missing required local binaries: {', '.join(missing)}"
        diagnostics.record(
            severity="error",
            code="preflight_missing_binaries",
            stage="preflight",
            message=message,
        )
        ui.error(message)
        return conclude(exit_code=2, submission_results=[], warnings=[])

    required_paths = [
        ("Submissions directory", args.submissions_dir),
        ("Solutions PDF", args.solutions_pdf),
        ("Rubric YAML", args.rubric_yaml),
        ("Grade template CSV", args.grades_template_csv),
    ]
    for label, path in required_paths:
        if not path.exists():
            message = f"{label} not found: {path}"
            diagnostics.record(
                severity="error",
                code="preflight_missing_path",
                stage="preflight",
                message=message,
            )
            ui.error(message)
            return conclude(exit_code=2, submission_results=[], warnings=[])

    for label, path in (("Output directory", args.output_dir), ("Temp directory", args.temp_dir), ("Cache directory", args.cache_dir)):
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            message = f"Failed to prepare {label.lower()} at {path}: {exc}"
            diagnostics.record(
                severity="error",
                code="preflight_directory_create_failed",
                stage="preflight",
                message=message,
                exc=exc,
            )
            ui.error(message)
            return conclude(exit_code=2, submission_results=[], warnings=[])

    try:
        rubric = load_rubric(args.rubric_yaml)
    except Exception as exc:  # noqa: BLE001
        message = f"Failed to load rubric YAML {args.rubric_yaml}: {exc}"
        diagnostics.record(
            severity="error",
            code="rubric_load_failed",
            stage="rubric_load",
            message=message,
            exc=exc,
        )
        ui.error(message)
        return conclude(exit_code=1, submission_results=[], warnings=[])

    try:
        units = discover_submission_units(args.submissions_dir)
    except Exception as exc:  # noqa: BLE001
        message = f"Failed to discover submissions in {args.submissions_dir}: {exc}"
        diagnostics.record(
            severity="error",
            code="preflight_discovery_failed",
            stage="preflight",
            message=message,
            exc=exc,
        )
        ui.error(message)
        return conclude(exit_code=2, submission_results=[], warnings=[])

    if args.student_filter:
        try:
            pattern = re.compile(args.student_filter, flags=re.IGNORECASE)
        except re.error as exc:
            message = f"Invalid --student-filter regex '{args.student_filter}': {exc}"
            diagnostics.record(
                severity="error",
                code="preflight_invalid_student_filter",
                stage="preflight",
                message=message,
                exc=exc,
            )
            ui.error(message)
            return conclude(exit_code=2, submission_results=[], warnings=[])
        units = [unit for unit in units if pattern.search(unit.folder_path.name)]

    if not units:
        ui.info("No submission folders with PDFs found.")
        return conclude(exit_code=0, submission_results=[], warnings=[])

    ui.info(f"Discovered {len(units)} submission folders.")

    try:
        audit_entries = parse_index_html(args.submissions_dir / "index.html")
        artifacts["Index audit CSV"] = write_index_audit_csv(args.output_dir, audit_entries)
    except Exception as exc:  # noqa: BLE001
        message = f"Failed to write index audit CSV: {exc}"
        diagnostics.record(
            severity="error",
            code="report_write_failed",
            stage="report_write",
            message=message,
            exc=exc,
        )
        ui.error(message)
        return conclude(exit_code=1, submission_results=[], warnings=[])

    try:
        solutions_text = extract_pdf_text(
            args.solutions_pdf,
            temp_dir=args.temp_dir,
            ocr_char_threshold=args.ocr_char_threshold,
        ).text
    except Exception as exc:  # noqa: BLE001
        message = f"Failed to extract text from solutions PDF {args.solutions_pdf}: {exc}"
        diagnostics.record(
            severity="error",
            code="solution_extract_failed",
            stage="solution_extract",
            message=message,
            exc=exc,
        )
        ui.error(message)
        return conclude(exit_code=1, submission_results=[], warnings=[])

    grade_points = {
        "Check Plus": args.check_plus_points,
        "Check": args.check_points,
        "Check Minus": args.check_minus_points,
        "REVIEW_REQUIRED": args.review_required_points,
    }

    api_key = os.getenv(args.api_key_env, "").strip()
    if not api_key and not args.dry_run:
        message = f"Environment variable {args.api_key_env} is missing. Set it or run with --dry-run."
        diagnostics.record(
            severity="error",
            code="preflight_missing_api_key",
            stage="preflight",
            message=message,
        )
        ui.error(message)
        return conclude(exit_code=2, submission_results=[], warnings=[])

    grader = None
    if not args.dry_run:
        try:
            grader = GeminiGrader(
                api_key=api_key,
                model=args.model,
                cache_dir=args.cache_dir,
            )
        except Exception as exc:  # noqa: BLE001
            message = f"Failed to initialize Gemini client: {exc}"
            diagnostics.record(
                severity="error",
                code="grading_client_init_failed",
                stage="grading",
                message=message,
                exc=exc,
            )
            ui.error(message)
            return conclude(exit_code=1, submission_results=[], warnings=[])

    submission_results: list[SubmissionResult] = []
    for index, unit in enumerate(units, start=1):
        folder_name = unit.folder_path.name
        ui.submission_started(index=index, total=len(units), folder_name=folder_name)
        try:
            result = grade_one_submission(
                unit=unit,
                submissions_root=args.submissions_dir,
                output_dir=args.output_dir,
                temp_dir=args.temp_dir,
                ocr_char_threshold=args.ocr_char_threshold,
                rubric=rubric,
                solutions_text=solutions_text,
                grade_points=grade_points,
                grader=grader,
                dry_run=args.dry_run,
                locator_model=args.locator_model.strip(),
                annotate_dry_run_marks=args.annotate_dry_run_marks,
                diagnostics=diagnostics,
            )
        except Exception as exc:  # noqa: BLE001
            message = f"Unhandled submission failure: {exc}"
            diagnostics.record(
                severity="error",
                code="grading_unhandled_submission",
                stage="grading",
                message=message,
                submission_folder=folder_name,
                exc=exc,
            )
            result = build_failed_submission_result(
                unit=unit,
                rubric=rubric,
                grade_points=grade_points,
                error_message=message,
            )
        submission_results.append(result)
        ui.submission_finished(
            index=index,
            total=len(units),
            folder_name=folder_name,
            band=result.grade_result.band,
            had_error=bool(result.error),
        )

    warnings: list[str] = []
    try:
        artifacts["Grading audit CSV"] = write_grading_audit_csv(args.output_dir, submission_results)
        artifacts["Review queue CSV"] = write_review_queue_csv(args.output_dir, submission_results)
        artifacts["Brightspace import CSV"], warnings = write_brightspace_import_csv(
            output_dir=args.output_dir,
            template_csv_path=args.grades_template_csv,
            submission_results=submission_results,
            grade_column=args.grade_column,
            identifier_column=args.identifier_column,
            comment_column=args.comment_column or None,
        )
    except Exception as exc:  # noqa: BLE001
        message = f"Failed to write report CSV outputs: {exc}"
        diagnostics.record(
            severity="error",
            code="report_write_failed",
            stage="report_write",
            message=message,
            exc=exc,
        )
        ui.error(message)
        return conclude(exit_code=1, submission_results=submission_results, warnings=[])

    for warning in warnings:
        diagnostics.record(
            severity="warning",
            code="report_mapping_warning",
            stage="report_write",
            message=warning,
        )

    return conclude(exit_code=0, submission_results=submission_results, warnings=warnings)


def summarize_results(submission_results: list[SubmissionResult], warning_count: int) -> RunSummary:
    submissions_processed = len(submission_results)
    failed_with_error_count = sum(1 for result in submission_results if result.error)
    review_required_count = sum(
        1
        for result in submission_results
        if (not result.error) and result.grade_result.band == "REVIEW_REQUIRED"
    )
    success_count = submissions_processed - failed_with_error_count - review_required_count
    return RunSummary(
        submissions_processed=submissions_processed,
        success_count=max(0, success_count),
        review_required_count=review_required_count,
        failed_with_error_count=failed_with_error_count,
        warning_count=warning_count,
    )


def build_failed_submission_result(
    unit,
    rubric,
    grade_points: dict[str, str],
    error_message: str,
) -> SubmissionResult:
    question_results = [
        QuestionResult(
            id=question.id,
            verdict="needs_review",
            confidence=0.0,
            short_reason=error_message,
            evidence_quote="",
        )
        for question in rubric.questions
    ]
    grade_result = score_submission(
        rubric=rubric,
        question_results=question_results,
        grade_points=grade_points,
    )
    return SubmissionResult(
        submission=unit,
        question_results=question_results,
        grade_result=grade_result,
        output_pdf_paths=[],
        extraction_sources={},
        global_flags=["grading_error"],
        error=error_message,
    )


def append_error(existing: str | None, new_error: str) -> str:
    return f"{existing}; {new_error}" if existing else new_error


def grade_one_submission(
    unit,
    submissions_root: Path,
    output_dir: Path,
    temp_dir: Path,
    ocr_char_threshold: int,
    rubric,
    solutions_text: str,
    grade_points: dict[str, str],
    grader: GeminiGrader | None,
    dry_run: bool,
    locator_model: str,
    annotate_dry_run_marks: bool,
    diagnostics: DiagnosticsCollector | None = None,
) -> SubmissionResult:
    extracted = []
    extraction_sources: dict[str, str] = {}
    accumulated_error: str | None = None
    global_flags: list[str] = []

    for pdf_path in unit.pdf_paths:
        try:
            pdf_extract = extract_pdf_text(
                pdf_path=pdf_path,
                temp_dir=temp_dir,
                ocr_char_threshold=ocr_char_threshold,
            )
        except Exception as exc:  # noqa: BLE001
            extraction_sources[pdf_path.name] = "error"
            extraction_error = f"Text extraction failed for {pdf_path.name}: {exc}"
            accumulated_error = append_error(accumulated_error, extraction_error)
            if "extract_error" not in global_flags:
                global_flags.append("extract_error")
            if diagnostics is not None:
                diagnostics.record(
                    severity="error",
                    code="grading_extract_failed",
                    stage="grading",
                    message=extraction_error,
                    submission_folder=unit.folder_path.name,
                    exc=exc,
                )
            continue
        extracted.append(pdf_extract)
        extraction_sources[pdf_path.name] = pdf_extract.source

    combined_text = "\n\n".join(
        f"### FILE: {item.pdf_path.name}\n{item.text}" for item in extracted
    )

    if dry_run:
        question_results = [
            QuestionResult(
                id=question.id,
                verdict="needs_review",
                confidence=0.0,
                short_reason="Dry run mode.",
                evidence_quote="",
            )
            for question in rubric.questions
        ]
        global_flags.append("dry_run")
    else:
        try:
            assert grader is not None
            question_results, model_flags = grader.grade_submission(
                submission_id=unit.folder_path.name,
                pdf_paths=unit.pdf_paths,
                combined_text=combined_text,
                rubric=rubric,
                solutions_text=solutions_text,
            )
            global_flags.extend(model_flags)
        except Exception as exc:  # noqa: BLE001
            grading_error = f"Gemini grading failed: {exc}"
            if diagnostics is not None:
                diagnostics.record(
                    severity="error",
                    code="grading_failed",
                    stage="grading",
                    message=grading_error,
                    submission_folder=unit.folder_path.name,
                    exc=exc,
                )
            question_results = [
                QuestionResult(
                    id=question.id,
                    verdict="needs_review",
                    confidence=0.0,
                    short_reason=grading_error,
                    evidence_quote="",
                )
                for question in rubric.questions
            ]
            global_flags.append("grading_error")
            accumulated_error = append_error(accumulated_error, str(exc))

    if (not dry_run) and locator_model and grader is not None:
        locator_errors: list[str] = []
        candidates = collect_locator_candidates(
            grader=grader,
            pdf_paths=unit.pdf_paths,
            rubric=rubric,
            locator_model=locator_model,
            errors_out=locator_errors,
            diagnostics=diagnostics,
            submission_folder=unit.folder_path.name,
        )
        question_results = apply_locator_candidates(
            question_results=question_results,
            candidates=candidates,
            pdf_paths=unit.pdf_paths,
        )
        if locator_errors:
            if "locator_error" not in global_flags:
                global_flags.append("locator_error")
            locator_error_text = "; ".join(locator_errors)
            accumulated_error = append_error(accumulated_error, locator_error_text)

    grade_result = score_submission(
        rubric=rubric,
        question_results=question_results,
        grade_points=grade_points,
    )
    try:
        output_pdf_paths, question_results = annotate_submission_pdfs(
            submission=unit,
            rubric=rubric,
            question_results=question_results,
            output_dir=output_dir,
            submissions_root=submissions_root,
            final_band=grade_result.band,
            dry_run=dry_run,
            annotate_dry_run_marks=annotate_dry_run_marks,
        )
    except Exception as exc:  # noqa: BLE001
        output_pdf_paths = []
        annotation_error = f"Annotation failed: {exc}"
        if diagnostics is not None:
            diagnostics.record(
                severity="error",
                code="annotation_failed",
                stage="annotation",
                message=annotation_error,
                submission_folder=unit.folder_path.name,
                exc=exc,
            )
        accumulated_error = append_error(accumulated_error, annotation_error)

    return SubmissionResult(
        submission=unit,
        question_results=question_results,
        grade_result=grade_result,
        output_pdf_paths=output_pdf_paths,
        extraction_sources=extraction_sources,
        global_flags=global_flags,
        error=accumulated_error,
    )


def collect_locator_candidates(
    grader: GeminiGrader,
    pdf_paths: list[Path],
    rubric,
    locator_model: str,
    errors_out: list[str],
    diagnostics: DiagnosticsCollector | None = None,
    submission_folder: str | None = None,
) -> dict[str, list[dict]]:
    candidates: dict[str, list[dict]] = {}
    for pdf_path in pdf_paths:
        try:
            per_pdf = grader.locate_answers_for_pdf(
                pdf_path=pdf_path,
                rubric=rubric,
                locator_model=locator_model,
            )
        except Exception as exc:  # noqa: BLE001
            message = f"Locator failed for {pdf_path.name}: {exc}"
            errors_out.append(message)
            if diagnostics is not None:
                diagnostics.record(
                    severity="error",
                    code="locator_failed",
                    stage="locator",
                    message=message,
                    submission_folder=submission_folder,
                    exc=exc,
                )
            continue
        for item in per_pdf:
            qid = str(item.get("id", "")).strip().lower()
            if not qid:
                continue
            candidates.setdefault(qid, []).append(item)
    return candidates


def apply_locator_candidates(
    question_results: list[QuestionResult],
    candidates: dict[str, list[dict]],
    pdf_paths: list[Path],
) -> list[QuestionResult]:
    if not candidates:
        return question_results

    file_rank = {path.name: idx for idx, path in enumerate(pdf_paths)}
    result_map = {result.id: result for result in question_results}

    for question_id, options in candidates.items():
        if question_id not in result_map or not options:
            continue
        ordered = sorted(
            options,
            key=lambda item: (
                -float(item.get("confidence", 0.0)),
                file_rank.get(str(item.get("source_file", "")), 10**9),
            ),
        )
        best = ordered[0]
        coords = best.get("coords")
        if not isinstance(coords, tuple) or len(coords) != 2:
            continue
        result_map[question_id] = replace(
            result_map[question_id],
            coords=coords,
            page_number=best.get("page_number"),
            source_file=str(best.get("source_file", "")).strip() or None,
        )

    return [result_map[result.id] for result in question_results]


if __name__ == "__main__":
    raise SystemExit(main())

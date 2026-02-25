from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import replace
from pathlib import Path

from .annotate import annotate_submission_pdfs
from .config import load_rubric
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    missing = ensure_binaries_present()
    if missing:
        print(f"Missing required local binaries: {', '.join(missing)}", file=sys.stderr)
        return 2

    if not args.submissions_dir.exists():
        print(f"Submissions directory not found: {args.submissions_dir}", file=sys.stderr)
        return 2
    if not args.solutions_pdf.exists():
        print(f"Solutions PDF not found: {args.solutions_pdf}", file=sys.stderr)
        return 2
    if not args.grades_template_csv.exists():
        print(f"Grade template CSV not found: {args.grades_template_csv}", file=sys.stderr)
        return 2

    rubric = load_rubric(args.rubric_yaml)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.temp_dir.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    units = discover_submission_units(args.submissions_dir)
    if args.student_filter:
        pattern = re.compile(args.student_filter, flags=re.IGNORECASE)
        units = [unit for unit in units if pattern.search(unit.folder_path.name)]
    if not units:
        print("No submission folders with PDFs found.")
        return 0

    print(f"Discovered {len(units)} submission folders.")
    audit_entries = parse_index_html(args.submissions_dir / "index.html")
    write_index_audit_csv(args.output_dir, audit_entries)

    solutions_text = extract_pdf_text(
        args.solutions_pdf,
        temp_dir=args.temp_dir,
        ocr_char_threshold=args.ocr_char_threshold,
    ).text

    grade_points = {
        "Check Plus": args.check_plus_points,
        "Check": args.check_points,
        "Check Minus": args.check_minus_points,
        "REVIEW_REQUIRED": args.review_required_points,
    }

    api_key = os.getenv(args.api_key_env, "").strip()
    if not api_key and not args.dry_run:
        print(
            f"Environment variable {args.api_key_env} is missing. "
            "Set it or run with --dry-run.",
            file=sys.stderr,
        )
        return 2

    grader = None
    if not args.dry_run:
        grader = GeminiGrader(
            api_key=api_key,
            model=args.model,
            cache_dir=args.cache_dir,
        )

    submission_results: list[SubmissionResult] = []
    for index, unit in enumerate(units, start=1):
        print(f"[{index}/{len(units)}] Grading {unit.folder_path.name}")
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
        )
        submission_results.append(result)

    audit_path = write_grading_audit_csv(args.output_dir, submission_results)
    review_path = write_review_queue_csv(args.output_dir, submission_results)
    grades_path, warnings = write_brightspace_import_csv(
        output_dir=args.output_dir,
        template_csv_path=args.grades_template_csv,
        submission_results=submission_results,
        grade_column=args.grade_column,
        identifier_column=args.identifier_column,
        comment_column=args.comment_column or None,
    )

    print(f"Grading audit CSV: {audit_path}")
    print(f"Review queue CSV: {review_path}")
    print(f"Brightspace import CSV: {grades_path}")
    if warnings:
        print("Mapping warnings:")
        for warning in warnings:
            print(f"  - {warning}")

    return 0


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
) -> SubmissionResult:
    extracted = []
    extraction_sources: dict[str, str] = {}
    for pdf_path in unit.pdf_paths:
        pdf_extract = extract_pdf_text(
            pdf_path=pdf_path,
            temp_dir=temp_dir,
            ocr_char_threshold=ocr_char_threshold,
        )
        extracted.append(pdf_extract)
        extraction_sources[pdf_path.name] = pdf_extract.source

    combined_text = "\n\n".join(
        f"### FILE: {item.pdf_path.name}\n{item.text}" for item in extracted
    )

    accumulated_error: str | None = None
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
        global_flags = ["dry_run"]
    else:
        try:
            assert grader is not None
            question_results, global_flags = grader.grade_submission(
                submission_id=unit.folder_path.name,
                pdf_paths=unit.pdf_paths,
                combined_text=combined_text,
                rubric=rubric,
                solutions_text=solutions_text,
            )
        except Exception as exc:  # noqa: BLE001
            question_results = [
                QuestionResult(
                    id=question.id,
                    verdict="needs_review",
                    confidence=0.0,
                    short_reason=f"Gemini grading failed: {exc}",
                    evidence_quote="",
                )
                for question in rubric.questions
            ]
            global_flags = ["grading_error"]
            accumulated_error = str(exc)

    if (not dry_run) and locator_model and grader is not None:
        locator_errors: list[str] = []
        candidates = collect_locator_candidates(
            grader=grader,
            pdf_paths=unit.pdf_paths,
            rubric=rubric,
            locator_model=locator_model,
            errors_out=locator_errors,
        )
        question_results = apply_locator_candidates(
            question_results=question_results,
            candidates=candidates,
            pdf_paths=unit.pdf_paths,
        )
        if locator_errors:
            global_flags.append("locator_error")
            locator_error_text = "; ".join(locator_errors)
            accumulated_error = (
                f"{accumulated_error}; {locator_error_text}" if accumulated_error else locator_error_text
            )

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
        accumulated_error = f"{accumulated_error}; {annotation_error}" if accumulated_error else annotation_error

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
            errors_out.append(f"Locator failed for {pdf_path.name}: {exc}")
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

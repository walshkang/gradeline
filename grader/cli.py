from __future__ import annotations

import argparse
import os
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from .annotate import annotate_submission_pdfs
from .config import load_rubric
from .diagnostics import DiagnosticsCollector, serialize_cli_args
from .discovery import discover_submission_units, parse_index_html
from .env import load_dotenv_if_present
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


LEGACY_MODE = "legacy"
UNIFIED_MODE = "unified"
AGENT_MODE = "agent"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_AGENT_TYPE = "gemini"
DEFAULT_OCR_CHAR_THRESHOLD = 200
LOW_CONFIDENCE_THRESHOLD = 0.55
DEFAULT_ANNOTATION_FONT_SIZE = 24.0

# Limit concurrent locator passes across submissions to avoid API rate limits.
LOCATOR_MAX_CONCURRENT = 1
locator_semaphore = threading.Semaphore(LOCATOR_MAX_CONCURRENT)

VERDICT_SYMBOLS = {"correct": "✓", "partial": "◐", "rounding_error": "≈", "incorrect": "✗", "needs_review": "⟳"}


@dataclass
class StageTiming:
    name: str
    start: float = 0.0
    end: float = 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start) if self.end else 0.0


@dataclass
class SubmissionTelemetry:
    stages: list[StageTiming] = field(default_factory=list)
    start: float = 0.0
    end: float = 0.0

    @property
    def total_seconds(self) -> float:
        return max(0.0, self.end - self.start) if self.end else 0.0

    def begin_stage(self, name: str) -> None:
        self.stages.append(StageTiming(name=name, start=time.monotonic()))

    def end_stage(self) -> None:
        if self.stages and not self.stages[-1].end:
            self.stages[-1].end = time.monotonic()


@dataclass(frozen=True)
class RollingSnapshot:
    band_counts: dict[str, int]
    failure_count: int
    submissions_done: int
    total_seconds: float
    mean_seconds: float
    eta_seconds: float


def build_trust_rationale(
    question_results: list[QuestionResult],
    percent: float,
    band: str,
    rubric_bands: dict[str, float],
    global_flags: list[str],
) -> str:
    """Build a deterministic one-line trust rationale for a graded submission."""
    from .ui import _BAND_DISPLAY

    band_label = _BAND_DISPLAY.get(band, band)
    parts = [f"{band_label} ({percent:.2f}%)"]

    counts = {"correct": 0, "partial": 0, "incorrect": 0, "needs_review": 0}
    low_conf: list[str] = []
    for qr in question_results:
        counts[qr.verdict] = counts.get(qr.verdict, 0) + 1
        if qr.verdict != "correct" and qr.confidence < LOW_CONFIDENCE_THRESHOLD:
            low_conf.append(f"{qr.id}({qr.confidence:.2f})")

    mix = f"{counts['correct']}✓ {counts['partial']}◐ {counts['incorrect']}✗ {counts['needs_review']}⟳"
    parts.append(mix)

    # Threshold delta to next band up
    check_plus_pct = float(rubric_bands.get("check_plus_min", 0.9)) * 100.0
    check_pct = float(rubric_bands.get("check_min", 0.7)) * 100.0
    if band == "REVIEW_REQUIRED" or band == "CHECK_MINUS" or band == "Check Minus":
        delta = check_pct - percent
        parts.append(f"{delta:+.2f}→Check")
    elif band == "CHECK" or band == "Check":
        delta = check_plus_pct - percent
        parts.append(f"{delta:+.2f}→Check+")

    if low_conf:
        parts.append(f"low-conf {','.join(low_conf[:4])}")

    if global_flags:
        parts.append(f"flags:{','.join(global_flags[:3])}")

    return " | ".join(parts)


def update_rolling_snapshot(
    previous: RollingSnapshot | None,
    result: SubmissionResult,
    elapsed: float,
    remaining: int,
) -> RollingSnapshot:
    """Accumulate rolling stats after each submission."""
    if previous is None:
        band_counts: dict[str, int] = {}
        failure_count = 0
        total_seconds = 0.0
        submissions_done = 0
    else:
        band_counts = dict(previous.band_counts)
        failure_count = previous.failure_count
        total_seconds = previous.total_seconds
        submissions_done = previous.submissions_done

    submissions_done += 1
    total_seconds += elapsed
    band = result.grade_result.band
    band_counts[band] = band_counts.get(band, 0) + 1
    if result.error:
        failure_count += 1

    mean_seconds = total_seconds / submissions_done if submissions_done else 0.0
    eta_seconds = mean_seconds * remaining

    return RollingSnapshot(
        band_counts=band_counts,
        failure_count=failure_count,
        submissions_done=submissions_done,
        total_seconds=total_seconds,
        mean_seconds=mean_seconds,
        eta_seconds=eta_seconds,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gemini-backed Brightspace PDF grader.")
    parser.add_argument("--submissions-dir", required=True, type=Path)
    parser.add_argument("--solutions-pdf", required=True, type=Path)
    parser.add_argument("--rubric-yaml", required=True, type=Path)
    parser.add_argument("--grades-template-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--temp-dir", type=Path, default=Path(".grader_tmp"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".grader_cache"))
    parser.add_argument("--grading-mode", choices=(LEGACY_MODE, UNIFIED_MODE, AGENT_MODE), default=UNIFIED_MODE)
    parser.add_argument("--agent-type", choices=("gemini", "codex", "claude"), default=DEFAULT_AGENT_TYPE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--locator-model", default="")
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--identifier-column", default="OrgDefinedId")
    parser.add_argument("--grade-column", required=True)
    parser.add_argument("--comment-column", default="")
    parser.add_argument("--ocr-char-threshold", type=int, default=DEFAULT_OCR_CHAR_THRESHOLD)
    parser.add_argument("--student-filter", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--annotate-dry-run-marks", action="store_true")
    parser.add_argument("--check-plus-points", default="100")
    parser.add_argument("--check-points", default="85")
    parser.add_argument("--check-minus-points", default="65")
    parser.add_argument("--review-required-points", default="")
    parser.add_argument("--context-cache", dest="context_cache", action="store_true")
    parser.add_argument("--no-context-cache", dest="context_cache", action="store_false")
    parser.set_defaults(context_cache=True)
    parser.add_argument("--context-cache-ttl-seconds", type=int, default=86400)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--plain", action="store_true")
    parser.add_argument("--diagnostics-file", type=Path, default=None)
    parser.add_argument("--annotation-font-size", type=float, default=DEFAULT_ANNOTATION_FONT_SIZE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv_if_present()
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
    rolling: RollingSnapshot | None = None

    def conclude(exit_code: int, submission_results: list[SubmissionResult], warnings: list[str]) -> int:
        ui.stop_progress()
        ui.clear_status()
        ui.section_heading("Results")
        summary = summarize_results(
            submission_results=submission_results,
            warning_count=len(warnings),
            snapshot=rolling,
        )
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

    if args.grading_mode == LEGACY_MODE:
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
    elif args.grading_mode == AGENT_MODE:
        import shutil
        agent_binary = args.agent_type
        if args.agent_type == "claude":
            agent_binary = "claude"
        
        if shutil.which(agent_binary) is None:
            message = f"Agent CLI '{agent_binary}' not found in path. Required for agentic grading mode."
            diagnostics.record(
                severity="error",
                code="preflight_missing_agent_cli",
                stage="preflight",
                message=message,
            )
            ui.error(message)
            return conclude(exit_code=2, submission_results=[], warnings=[])
    else:
        if args.ocr_char_threshold != DEFAULT_OCR_CHAR_THRESHOLD:
            message = "--ocr-char-threshold is ignored in unified mode."
            diagnostics.record(
                severity="warning",
                code="preflight_unified_ocr_threshold_ignored",
                stage="preflight",
                message=message,
            )
            ui.warning(message)

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

    for label, path in (
        ("Output directory", args.output_dir),
        ("Temp directory", args.temp_dir),
        ("Cache directory", args.cache_dir),
    ):
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

    solutions_text: str | None = None
    if args.grading_mode == LEGACY_MODE:
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
    ui.section_heading("Grading")
    ui.start_progress(len(units))
    
    ui_lock = threading.Lock()
    rolling_lock = threading.Lock()
    completed_submissions = 0

    def locked_status_update(prefix: str) -> Callable[[str], None]:
        def update(message: str) -> None:
            with ui_lock:
                ui.status(f"{prefix} :: {message}")
        return update

    def process_student(index: int, unit) -> tuple[int, SubmissionResult, float]:
        folder_name = unit.folder_path.name
        sub_start = time.monotonic()
        with ui_lock:
            ui.submission_started(index=index, total=len(units), folder_name=folder_name)
        status_prefix = f"[{index}/{len(units)}] {folder_name}"
        if args.grading_mode == LEGACY_MODE:
            with ui_lock:
                ui.status(f"{status_prefix} :: preparing extraction")
        else:
            with ui_lock:
                ui.status(f"{status_prefix} :: preparing unified grading")

        status_update = locked_status_update(prefix=status_prefix)
        try:
            result = grade_one_submission(
                unit=unit,
                submissions_root=args.submissions_dir,
                output_dir=args.output_dir,
                temp_dir=args.temp_dir,
                ocr_char_threshold=args.ocr_char_threshold,
                rubric=rubric,
                solutions_text=solutions_text,
                solutions_pdf_path=args.solutions_pdf,
                grade_points=grade_points,
                grader=grader,
                grading_mode=args.grading_mode,
                agent_type=args.agent_type,
                context_cache=args.context_cache,
                context_cache_ttl_seconds=args.context_cache_ttl_seconds,
                dry_run=args.dry_run,
                locator_model=args.locator_model.strip(),
                annotate_dry_run_marks=args.annotate_dry_run_marks,
                diagnostics=diagnostics,
                status_update=status_update,
            )
        except Exception as exc:  # noqa: BLE001
            message = f"Unhandled submission failure: {exc}"
            with rolling_lock:
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
        
        sub_elapsed = time.monotonic() - sub_start
        with ui_lock:
            ui.clear_status()

        return index, result, sub_elapsed

    def annotate_and_finish(index: int, result: SubmissionResult, sub_elapsed: float) -> SubmissionResult:
        nonlocal rolling, completed_submissions
        folder_name = result.submission.folder_path.name
        
        try:
            output_pdf_paths, updated_question_results = annotate_submission_pdfs(
                submission=result.submission,
                rubric=rubric,
                question_results=result.question_results,
                output_dir=args.output_dir,
                submissions_root=args.submissions_dir,
                final_band=result.grade_result.band,
                dry_run=args.dry_run,
                annotate_dry_run_marks=args.annotate_dry_run_marks,
                annotation_font_size=float(getattr(args, "annotation_font_size", DEFAULT_ANNOTATION_FONT_SIZE)),
            )
            result.output_pdf_paths = output_pdf_paths
            result.question_results = updated_question_results
        except Exception as exc:  # noqa: BLE001
            annotation_error = f"Annotation failed: {exc}"
            with rolling_lock:
                diagnostics.record(
                    severity="error",
                    code="annotation_failed",
                    stage="annotation",
                    message=annotation_error,
                    submission_folder=folder_name,
                    exc=exc,
                )
            result.error = append_error(result.error, annotation_error)

        rationale = build_trust_rationale(
            question_results=result.question_results,
            percent=result.grade_result.percent,
            band=result.grade_result.band,
            rubric_bands=rubric.bands,
            global_flags=result.global_flags,
        )
        
        with rolling_lock:
            completed_submissions += 1
            remaining = len(units) - completed_submissions
            rolling = update_rolling_snapshot(rolling, result, sub_elapsed, remaining)
            current_rolling = rolling

        with ui_lock:
            ui.submission_finished(
                index=index,
                total=len(units),
                folder_name=folder_name,
                band=result.grade_result.band,
                had_error=bool(result.error),
                rationale=rationale,
                elapsed_seconds=sub_elapsed,
                snapshot=current_rolling,
            )
        return result

    with ThreadPoolExecutor(max_workers=args.concurrency) as api_executor:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency // 2)) as annotation_executor:
            # Map API calls
            api_futures = {api_executor.submit(process_student, i, unit): i for i, unit in enumerate(units, start=1)}
            annotation_futures = []
            
            for future in as_completed(api_futures):
                idx, result, elapsed = future.result()
                annotation_futures.append(annotation_executor.submit(annotate_and_finish, idx, result, elapsed))

            for future in as_completed(annotation_futures):
                submission_results.append(future.result())

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


def summarize_results(
    submission_results: list[SubmissionResult],
    warning_count: int,
    snapshot: RollingSnapshot | None = None,
) -> RunSummary:
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
        band_counts=dict(snapshot.band_counts) if snapshot else None,
        mean_seconds=snapshot.mean_seconds if snapshot else None,
        total_seconds=snapshot.total_seconds if snapshot else None,
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


def build_status_updater(ui, prefix: str) -> Callable[[str], None]:
    def update(message: str) -> None:
        ui.status(f"{prefix} :: {message}")

    return update


def dedupe_flags(flags: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for flag in flags:
        value = str(flag).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def context_cache_flag_message(flag: str) -> str:
    if flag == "context_cache_lookup_failed":
        return "Context cache lookup failed; rebuilding or bypassing cache for this submission."
    if flag == "context_cache_create_failed":
        return "Context cache creation failed; continuing without cache."
    if flag == "context_cache_bypassed":
        return "Context cache bypassed for this submission."
    return flag


def grade_one_submission(
    unit,
    submissions_root: Path,
    output_dir: Path,
    temp_dir: Path,
    ocr_char_threshold: int,
    rubric,
    solutions_text: str | None,
    solutions_pdf_path: Path,
    grade_points: dict[str, str],
    grader: GeminiGrader | None,
    grading_mode: str,
    agent_type: str,
    context_cache: bool,
    context_cache_ttl_seconds: int,
    dry_run: bool,
    locator_model: str,
    annotate_dry_run_marks: bool,
    diagnostics: DiagnosticsCollector | None = None,
    status_update: Callable[[str], None] | None = None,
) -> SubmissionResult:
    extracted = []
    extraction_sources: dict[str, str] = {}
    accumulated_error: str | None = None
    global_flags: list[str] = []
    combined_text = ""

    if grading_mode == LEGACY_MODE:
        for pdf_path in unit.pdf_paths:
            if status_update is not None:
                status_update(f"extracting {pdf_path.name}")
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
    else:
        for pdf_path in unit.pdf_paths:
            extraction_sources[pdf_path.name] = "model_vision"

    if dry_run:
        if status_update is not None:
            status_update("dry-run question statuses")
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
            if grading_mode == LEGACY_MODE:
                if status_update is not None:
                    status_update(f"grading {len(rubric.questions)} questions")
                question_results, model_flags = grader.grade_submission(
                    submission_id=unit.folder_path.name,
                    pdf_paths=unit.pdf_paths,
                    combined_text=combined_text,
                    rubric=rubric,
                    solutions_text=solutions_text or "",
                )
                global_flags.extend(model_flags)
            elif grading_mode == UNIFIED_MODE:
                if status_update is not None:
                    status_update(f"unified grading {len(rubric.questions)} questions")
                question_results, model_flags = grader.grade_submission_unified(
                    submission_id=unit.folder_path.name,
                    pdf_paths=unit.pdf_paths,
                    rubric=rubric,
                    solutions_pdf_path=solutions_pdf_path,
                    context_cache_enabled=context_cache,
                    context_cache_ttl_seconds=context_cache_ttl_seconds,
                )
                global_flags.extend(model_flags)
                if diagnostics is not None:
                    for flag in model_flags:
                        if flag in {
                            "context_cache_lookup_failed",
                            "context_cache_create_failed",
                            "context_cache_bypassed",
                        }:
                            diagnostics.record(
                                severity="warning",
                                code=flag,
                                stage="context_cache",
                                message=context_cache_flag_message(flag),
                                submission_folder=unit.folder_path.name,
                            )
            elif grading_mode == AGENT_MODE:
                if status_update is not None:
                    status_update(f"agentic grading ({agent_type}) {len(rubric.questions)} questions")
                question_results, model_flags = grader.grade_submission_agent(
                    submission_id=unit.folder_path.name,
                    pdf_paths=unit.pdf_paths,
                    rubric=rubric,
                    solutions_pdf_path=solutions_pdf_path,
                    agent_type=agent_type,
                )
                global_flags.extend(model_flags)
            else:
                raise ValueError(f"Unsupported grading mode: {grading_mode}")
        except ValueError as exc:
            if grading_mode == UNIFIED_MODE:
                grading_error = f"Unified Gemini schema validation failed: {exc}"
                if diagnostics is not None:
                    diagnostics.record(
                        severity="error",
                        code="unified_schema_invalid",
                        stage="grading",
                        message=grading_error,
                        submission_folder=unit.folder_path.name,
                        exc=exc,
                    )
            else:
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
                    logic_analysis="",
                    short_reason=grading_error,
                    evidence_quote="",
                )
                for question in rubric.questions
            ]
            global_flags.append("grading_error")
            accumulated_error = append_error(accumulated_error, str(exc))
        except Exception as exc:  # noqa: BLE001
            if grading_mode == UNIFIED_MODE:
                grading_error = f"Unified Gemini grading failed: {exc}"
                code = "unified_grading_failed"
            else:
                grading_error = f"Gemini grading failed: {exc}"
                code = "grading_failed"
            if diagnostics is not None:
                diagnostics.record(
                    severity="error",
                    code=code,
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
                    logic_analysis="",
                    short_reason=grading_error,
                    evidence_quote="",
                )
                for question in rubric.questions
            ]
            global_flags.append("grading_error")
            accumulated_error = append_error(accumulated_error, str(exc))

    needs_locator = any(result.coords is None for result in question_results)
    if (not dry_run) and locator_model and grader is not None and needs_locator:
        if status_update is not None:
            status_update("locating answer anchors")
        locator_errors: list[str] = []
        try:
            with locator_semaphore:
                candidates = collect_locator_candidates(
                    grader=grader,
                    pdf_paths=unit.pdf_paths,
                    rubric=rubric,
                    locator_model=locator_model,
                    errors_out=locator_errors,
                    diagnostics=diagnostics,
                    submission_folder=unit.folder_path.name,
                )
        except Exception as exc:  # noqa: BLE001
            locator_errors.append(f"Locator invocation failed: {exc}")
            candidates = {}

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

    return SubmissionResult(
        submission=unit,
        question_results=question_results,
        grade_result=grade_result,
        output_pdf_paths=[],
        extraction_sources=extraction_sources,
        global_flags=dedupe_flags(global_flags),
        error=accumulated_error,
    )


def build_annotation_progress_callback(
    status_update: Callable[[str], None] | None,
    total_questions: int,
) -> Callable[[int, int, str], None] | None:
    if status_update is None:
        return None

    def update(current: int, _: int, question_id: str) -> None:
        status_update(f"annotating question {question_id} ({current}/{total_questions})")

    return update


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
        # Only fill in coordinates for questions that are currently missing them.
        if result_map[question_id].coords is not None:
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
            placement_source="locator_coords",
        )

    return [result_map[result.id] for result in question_results]


if __name__ == "__main__":
    raise SystemExit(main())

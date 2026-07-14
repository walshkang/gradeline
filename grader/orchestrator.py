from __future__ import annotations

import atexit
import concurrent.futures.thread as _cft
import os
import re
import sys
import time
import threading
import inspect
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait as futures_wait
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from .annotate import annotate_submission_pdfs
import queue
from .checkpoint import compute_run_config_hash, save_checkpoint, load_checkpoint, clear_checkpoint, get_checkpoint_path, deserialize_result
from .diagnostics import DiagnosticsCollector
from .extract import (
    extract_pdf_text,
    serialize_extracted_pdf,
    deserialize_extracted_pdf,
    EXTRACTION_VERSION,
)
from .precheck import regex_precheck
from .report import (
    write_brightspace_import_csv,
    write_grading_audit_csv,
    write_index_audit_csv,
    write_review_queue_csv,
)
from .gemini_client import (
    compute_grade_cache_key,
    compute_unified_grade_cache_key,
    compute_context_cache_key,
    compute_agent_grade_cache_key,
)
from .score import score_submission
from .types import QuestionResult, SubmissionResult, ExtractedPdf
from .ui import RunSummary
from .rate_limit import RateLimiterRegistry, DailyLimitExhausted

LEGACY_MODE = "legacy"
UNIFIED_MODE = "unified"
AGENT_MODE = "agent"
LOW_CONFIDENCE_THRESHOLD = 0.55

LOCATOR_MAX_CONCURRENT = 1
locator_semaphore = threading.Semaphore(LOCATOR_MAX_CONCURRENT)

VERDICT_SYMBOLS = {"correct": "✓", "partial": "◐", "rounding_error": "≈", "incorrect": "✗", "needs_review": "⟳"}

@dataclass
class GradingConfig:
    submissions_root: Path
    output_dir: Path
    temp_dir: Path
    ocr_char_threshold: int
    rubric: Any
    rubric_yaml: Path
    solutions_text: str | None
    solutions_pdf_path: Path
    grade_points: dict[str, str]
    grader: Any | None
    grading_mode: str
    agent_type: str
    context_cache: bool
    context_cache_ttl_seconds: int
    dry_run: bool
    locator_model: str
    annotate_dry_run_marks: bool
    extraction_model: str
    gemini_api_key: str | None
    extract_blocks: bool
    diagnostics: DiagnosticsCollector | None
    rate_limiter: Any | None
    annotation_font_size: float
    grade_column: str = "Grade"
    identifier_column: str = "OrgDefinedId"
    comment_column: str | None = None
    grades_template_csv: Path | None = None
    model: str = "gemini-1.5-flash"
    concurrency: int = 1
    json_output: bool = False
    quiet: bool = False
    cache_dir: Path = Path(".grader_cache")


def prompt_interrupt_action(ui) -> str:
    """Prompt the user for how to handle a Ctrl+C interrupt.

    Returns one of: "resume", "stop_keep", "clear_all".
    A second Ctrl+C during the prompt is treated as "stop_keep".
    """

    try:
        from InquirerPy import inquirer  # type: ignore[import-not-found]
    except Exception:
        # Fallback to a simple numbered input prompt.
        options: list[tuple[str, str]] = [
            ("Resume grading", "resume"),
            ("Stop now and keep completed results", "stop_keep"),
            ("Clear this run's outputs and abort", "clear_all"),
        ]
        while True:
            ui.info("Interrupt detected. Choose an action:")
            for idx, (label, _) in enumerate(options, start=1):
                ui.info(f"{idx}. {label}")
            try:
                raw = input("Enter choice [1-3]: ").strip()
            except (KeyboardInterrupt, EOFError):
                ui.info("Second Ctrl+C detected; stopping and keeping completed results.")
                return "stop_keep"
            if raw in {"1", "2", "3"}:
                return options[int(raw) - 1][1]
            ui.warning("Invalid choice. Please enter 1, 2, or 3.")

    options_for_inquirer = [
        ("Resume grading", "resume"),
        ("Stop now and keep completed results", "stop_keep"),
        ("Clear this run's outputs and abort", "clear_all"),
    ]
    try:
        choice = inquirer.select(
            message="Interrupt detected. Choose an action:",
            choices=options_for_inquirer,
        ).execute()
    except KeyboardInterrupt:
        ui.info("Second Ctrl+C detected; stopping and keeping completed results.")
        return "stop_keep"

    return str(choice)

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

    counts = {"correct": 0, "rounding_error": 0, "partial": 0, "incorrect": 0, "needs_review": 0}
    low_conf: list[str] = []
    for qr in question_results:
        counts[qr.verdict] = counts.get(qr.verdict, 0) + 1
        if qr.verdict not in ("correct", "rounding_error") and qr.confidence < LOW_CONFIDENCE_THRESHOLD:
            low_conf.append(f"{qr.id}({qr.confidence:.2f})")

    mix = f"{counts['correct']}✓ {counts['rounding_error']}≈ {counts['partial']}◐ {counts['incorrect']}✗ {counts['needs_review']}⟳"
    parts.append(mix)

    # Threshold delta to next band up
    sorted_bands = []
    for name, val in rubric_bands.items():
        try:
            threshold = float(val)
            if threshold <= 1.0:
                threshold *= 100.0
            sorted_bands.append((name, threshold))
        except (TypeError, ValueError):
            pass
    sorted_bands.sort(key=lambda x: x[1])

    next_band = None
    for name, threshold in sorted_bands:
        if threshold > percent:
            next_band = (name, threshold)
            break

    if next_band is not None and band != "REVIEW_REQUIRED":
        delta = next_band[1] - percent
        dest_label = next_band[0]
        if dest_label == "check_plus_min":
            dest_label = "Check+"
        elif dest_label == "check_min":
            dest_label = "Check"
        parts.append(f"{delta:+.2f}→{dest_label}")

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
    config: GradingConfig,
    status_update: Callable[[str], None] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    pre_extracted: list[ExtractedPdf] | None = None,
) -> SubmissionResult:
    submissions_root = config.submissions_root
    output_dir = config.output_dir
    temp_dir = config.temp_dir
    ocr_char_threshold = config.ocr_char_threshold
    rubric = config.rubric
    solutions_text = config.solutions_text
    solutions_pdf_path = config.solutions_pdf_path
    grade_points = config.grade_points
    grader = config.grader
    grading_mode = config.grading_mode
    agent_type = config.agent_type
    context_cache = config.context_cache
    context_cache_ttl_seconds = config.context_cache_ttl_seconds
    dry_run = config.dry_run
    locator_model = config.locator_model
    annotate_dry_run_marks = config.annotate_dry_run_marks
    extraction_model = config.extraction_model
    gemini_api_key = config.gemini_api_key
    extract_blocks = config.extract_blocks
    diagnostics = config.diagnostics
    rate_limiter = config.rate_limiter

    extracted = []
    extraction_sources: dict[str, str] = {}
    accumulated_error: str | None = None
    global_flags: list[str] = []
    combined_text = ""
    block_registry: dict[str, object] = {}

    if grading_mode == LEGACY_MODE:
        if pre_extracted is not None:
            extracted = pre_extracted
            for item in extracted:
                extraction_sources[item.pdf_path.name] = item.source
        else:
            for pdf_path in unit.pdf_paths:
                if status_update is not None:
                    status_update(f"extracting {pdf_path.name}")
                try:
                    pdf_extract = extract_pdf_text(
                        pdf_path=pdf_path,
                        temp_dir=temp_dir,
                        ocr_char_threshold=ocr_char_threshold,
                        gemini_api_key=gemini_api_key,
                        gemini_model=extraction_model,
                        rate_limiter=rate_limiter,
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
        block_registry = {b.id: b for item in extracted for b in item.blocks}
    else:
        # Unified/agent modes send PDFs directly to the model for grading. Optionally
        # run extraction to build the block registry for spatial annotation placement.
        # Disable with extract_blocks=False to skip OCR overhead when not needed.
        extracted_for_precheck = []
        for pdf_path in unit.pdf_paths:
            extraction_sources[pdf_path.name] = "model_vision"

        if extract_blocks:
            if pre_extracted is not None:
                extracted_for_precheck = pre_extracted
                for item in extracted_for_precheck:
                    block_registry.update({b.id: b for b in item.blocks})
            else:
                for pdf_path in unit.pdf_paths:
                    try:
                        pdf_extract = extract_pdf_text(
                            pdf_path=pdf_path,
                            temp_dir=temp_dir,
                            ocr_char_threshold=ocr_char_threshold,
                            gemini_api_key=gemini_api_key,
                            gemini_model=extraction_model,
                            rate_limiter=rate_limiter,
                        )
                        block_registry.update({b.id: b for b in pdf_extract.blocks})
                        extracted_for_precheck.append(pdf_extract)
                    except Exception:
                        pass

        if extract_blocks:
            combined_text = "\n\n".join(
                f"### FILE: {item.pdf_path.name}\n{item.text}" for item in extracted_for_precheck
            )

    prechecked_results = regex_precheck(rubric, combined_text)

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
                grading_source="dry_run",
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
                    status_update("grading submission in unified mode (this may take up to ~30 seconds)")

                extra_kwargs: dict[str, object] = {}
                if progress_callback is not None:
                    try:
                        sig = inspect.signature(grader.grade_submission_unified)  # type: ignore[attr-defined]
                        if "progress_callback" in sig.parameters:
                            extra_kwargs["progress_callback"] = progress_callback
                    except (ValueError, TypeError, AttributeError):
                        # If we cannot introspect the grader (e.g., fake test grader),
                        # fall back to calling without progress support.
                        pass

                question_results, model_flags = grader.grade_submission_unified(
                    submission_id=unit.folder_path.name,
                    pdf_paths=unit.pdf_paths,
                    rubric=rubric,
                    solutions_pdf_path=solutions_pdf_path,
                    context_cache_enabled=context_cache,
                    context_cache_ttl_seconds=context_cache_ttl_seconds,
                    blocks=list(block_registry.values()) if block_registry else None,
                    **extra_kwargs,
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

    for i, result in enumerate(question_results):
        if result.id in prechecked_results:
            question_results[i] = prechecked_results[result.id]

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
        block_registry=block_registry,
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

def build_grading_progress_callback(
    status_update: Callable[[str], None] | None,
    total_questions: int,
) -> Callable[[int, int, str], None] | None:
    """Return a simple callback that formats grading question progress.

    The returned callback matches the same signature used elsewhere: (current, total, question_id).
    If status_update is None, returns None.
    """
    if status_update is None:
        return None

    def update(current: int, _: int, question_id: str) -> None:
        status_update(f"grading question {question_id} ({current}/{total_questions})")

    return update

def collect_locator_candidates(
    grader: Any,
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

class Orchestrator:
    def __init__(self, config: GradingConfig, ui):
        self.config = config
        self.ui = ui
        self.diagnostics = config.diagnostics
        self.rolling: RollingSnapshot | None = None
        self.completed_submissions = 0
        self.submission_results: list[SubmissionResult] = []
        self.units: list[Any] = []
        self.pending_api: set[Any] = set()
        self.pending_annotation: set[Any] = set()
        self._forced_exit_code: int | None = None
        self.ui_lock = threading.Lock()
        self.rolling_lock = threading.Lock()
        self.artifacts: dict[str, Path | None] = {
            "Index audit CSV": None,
            "Grading audit CSV": None,
            "Review queue CSV": None,
            "Brightspace import CSV": None,
        }
        self.diagnostics_path = config.output_dir / "grading_diagnostics.json"

    def locked_status_update(self, prefix: str) -> Callable[[str], None]:
        def update(message: str) -> None:
            with self.ui_lock:
                self.ui.status(f"{prefix} :: {message}")
        return update

    def process_student(
        self,
        index: int,
        unit,
        pre_extracted: list[ExtractedPdf] | None = None,
        error: Exception | None = None,
    ) -> tuple[int, SubmissionResult, float]:
        folder_name = unit.folder_path.name
        sub_start = time.monotonic()
        with self.ui_lock:
            self.ui.submission_started(index=index, total=len(self.units), folder_name=folder_name)
        status_prefix = f"[{index}/{len(self.units)}] {folder_name}"
        if self.config.grading_mode == LEGACY_MODE:
            with self.ui_lock:
                self.ui.status(f"{status_prefix} :: preparing extraction")
        else:
            with self.ui_lock:
                self.ui.status(f"{status_prefix} :: preparing unified grading")

        status_update = self.locked_status_update(prefix=status_prefix)

        submission_task_id: int | None = None
        grading_progress: Callable[[int, int, str], None] | None = None
        if self.config.grading_mode == UNIFIED_MODE:
            total_questions = len(self.config.rubric.questions)
            if total_questions > 0:
                submission_task_id = self.ui.add_submission_task(folder_name=folder_name, total_questions=total_questions)

                def grading_progress_cb(current: int, total: int, question_id: str) -> None:
                    self.ui.update_submission_task(submission_task_id or 0, current, question_id)
                grading_progress = grading_progress_cb

        try:
            if error is not None:
                raise error
            result = grade_one_submission(
                unit=unit,
                config=self.config,
                status_update=status_update,
                progress_callback=grading_progress,
                pre_extracted=pre_extracted,
            )
        except DailyLimitExhausted:
            raise
        except Exception as exc:
            msg_lower = str(exc).lower()
            if "429" in msg_lower or "resource_exhausted" in msg_lower or "quota" in msg_lower:
                model_name = self.config.grader.model if hasattr(self.config.grader, 'model') else "unknown"
                raise DailyLimitExhausted(model_name, 0, 0) from exc
            message = f"Unhandled submission failure: {exc}"
            with self.rolling_lock:
                if self.diagnostics:
                    self.diagnostics.record(
                        severity="error",
                        code="grading_unhandled_submission",
                        stage="grading",
                        message=message,
                        submission_folder=folder_name,
                        exc=exc,
                    )
            result = SubmissionResult.from_error(
                unit=unit,
                rubric=self.config.rubric,
                grade_points=self.config.grade_points,
                error_message=message,
            )
        finally:
            if submission_task_id is not None:
                self.ui.remove_submission_task(submission_task_id)

        sub_elapsed = time.monotonic() - sub_start
        with self.ui_lock:
            self.ui.clear_status()

        return index, result, sub_elapsed

    def annotate_and_finish(self, index: int, result: SubmissionResult, sub_elapsed: float) -> SubmissionResult:
        folder_name = result.submission.folder_path.name
        
        try:
            output_pdf_paths, updated_question_results = annotate_submission_pdfs(
                submission=result.submission,
                rubric=self.config.rubric,
                question_results=result.question_results,
                block_registry=result.block_registry or {},
                output_dir=self.config.output_dir,
                submissions_root=self.config.submissions_root,
                final_band=result.grade_result.band,
                dry_run=self.config.dry_run,
                annotate_dry_run_marks=self.config.annotate_dry_run_marks,
                annotation_font_size=self.config.annotation_font_size,
            )
            result.output_pdf_paths = output_pdf_paths
            result.question_results = updated_question_results
        except Exception as exc:
            annotation_error = f"Annotation failed: {exc}"
            with self.rolling_lock:
                if self.diagnostics:
                    self.diagnostics.record(
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
            rubric_bands=self.config.rubric.bands,
            global_flags=result.global_flags,
        )
        
        with self.rolling_lock:
            self.completed_submissions += 1
            remaining = len(self.units) - self.completed_submissions
            self.rolling = update_rolling_snapshot(self.rolling, result, sub_elapsed, remaining)
            current_rolling = self.rolling

        with self.ui_lock:
            self.ui.submission_finished(
                index=index,
                total=len(self.units),
                folder_name=folder_name,
                band=result.grade_result.band,
                had_error=bool(result.error),
                rationale=rationale,
                elapsed_seconds=sub_elapsed,
                snapshot=current_rolling,
            )
        return result

    def _shutdown_executors(
        self,
        api_ex: ThreadPoolExecutor,
        ann_ex: ThreadPoolExecutor,
        *,
        cancel_annotation: bool,
    ) -> bool:
        in_flight = sum(1 for f in self.pending_api if not f.done())
        if in_flight > 0:
            self.ui.info(
                f"Waiting for {in_flight} in-flight request(s) to finish…"
                "  (Ctrl+C again to force quit)"
            )
        try:
            api_ex.shutdown(wait=True, cancel_futures=True)
            ann_ex.shutdown(wait=True, cancel_futures=cancel_annotation)
            return True
        except KeyboardInterrupt:
            self.ui.info("Force stopping — some in-flight results may be lost.")
            api_ex.shutdown(wait=False, cancel_futures=True)
            ann_ex.shutdown(wait=False, cancel_futures=True)
            try:
                atexit.unregister(_cft._python_exit)
            except Exception:
                pass
            return False

    def run(self, units: list[Any]) -> int:
        self.units = units
        
        # Load checkpoint
        run_config_hash = compute_run_config_hash(
            rubric_path=self.config.rubric_yaml,
            solutions_pdf=self.config.solutions_pdf_path,
            model=self.config.grader.model if hasattr(self.config.grader, 'model') else "unknown",
            grading_mode=self.config.grading_mode,
        )

        checkpoint_data = None
        checkpoint_file = get_checkpoint_path(self.config.output_dir)
        if checkpoint_file.exists():
            checkpoint_data = load_checkpoint(self.config.output_dir, run_config_hash)
            if checkpoint_data is not None:
                self.ui.info(
                    f"Resuming from checkpoint: {len(checkpoint_data.results)}/{len(self.units)} "
                    f"submissions completed previously."
                )
            else:
                self.ui.warning(f"A stale checkpoint file exists at {checkpoint_file} (rubric or model changed).")
                is_interactive = sys.stdin.isatty() and not getattr(self.config, "quiet", False)
                discard = True
                if is_interactive:
                    try:
                        res = input("Discard stale checkpoint and start fresh? [Y/n]: ").strip().lower()
                        if res == "n":
                            discard = False
                    except (KeyboardInterrupt, EOFError):
                        pass
                if discard:
                    clear_checkpoint(self.config.output_dir)
                    self.ui.info("Cleared stale checkpoint.")

        if checkpoint_data:
            self.submission_results = list(checkpoint_data.results)
            self.rolling = checkpoint_data.rolling
            self.completed_submissions = len(checkpoint_data.results)
            completed_folders = checkpoint_data.completed_folders
            remaining_units = [u for u in self.units if u.folder_token not in completed_folders]
        else:
            self.submission_results = []
            self.rolling = None
            self.completed_submissions = 0
            remaining_units = list(self.units)
        self.ui.section_heading("Grading")
        self.ui.start_progress(len(self.units))
        for _ in range(self.completed_submissions):
            self.ui.advance_progress()

        # Thread pools
        concurrency = getattr(self.config, "concurrency", 1)
        grading_queue = queue.Queue()

        def preprocess_task(idx: int, unit: Any):
            try:
                extracted = self.get_or_compute_preprocessing(unit)
                grading_queue.put((idx, unit, extracted, None))
            except Exception as exc:
                grading_queue.put((idx, unit, None, exc))

        try:
            prep_concurrency = max(1, min(concurrency, os.cpu_count() or 1, 4))
            with ThreadPoolExecutor(max_workers=prep_concurrency) as prep_executor:
                for idx, unit in enumerate(remaining_units, start=self.completed_submissions + 1):
                    prep_executor.submit(preprocess_task, idx, unit)

                remaining_units_to_submit = len(remaining_units)
                future_to_info: dict[Any, tuple[int, Any]] = {}

                with ThreadPoolExecutor(max_workers=concurrency) as api_executor:
                    with ThreadPoolExecutor(max_workers=max(1, concurrency // 2)) as annotation_executor:
                        while remaining_units_to_submit > 0 or self.pending_api or self.pending_annotation:
                            while True:
                                try:
                                    item = grading_queue.get_nowait()
                                    idx, unit, extracted, err = item
                                    future = api_executor.submit(
                                        self.process_student,
                                        idx,
                                        unit,
                                        pre_extracted=extracted,
                                        error=err,
                                    )
                                    self.pending_api.add(future)
                                    future_to_info[future] = (idx, unit)
                                    remaining_units_to_submit -= 1
                                except queue.Empty:
                                    break

                            if not self.pending_api and not self.pending_annotation and remaining_units_to_submit > 0:
                                try:
                                    item = grading_queue.get(timeout=0.5)
                                    idx, unit, extracted, err = item
                                    future = api_executor.submit(
                                        self.process_student,
                                        idx,
                                        unit,
                                        pre_extracted=extracted,
                                        error=err,
                                    )
                                    self.pending_api.add(future)
                                    future_to_info[future] = (idx, unit)
                                    remaining_units_to_submit -= 1
                                except queue.Empty:
                                    pass
                                continue

                            if self.pending_api or self.pending_annotation:
                                try:
                                    all_pending = self.pending_api | self.pending_annotation
                                    done, _ = futures_wait(all_pending, timeout=0.05, return_when=FIRST_COMPLETED)
                                    for future in done:
                                        if future in self.pending_api:
                                            self.pending_api.discard(future)
                                            idx, unit = future_to_info.pop(future, (None, None))
                                            try:
                                                idx_res, result, elapsed = future.result()
                                                ann_future = annotation_executor.submit(
                                                    self.annotate_and_finish,
                                                    idx_res,
                                                    result,
                                                    elapsed,
                                                )
                                                self.pending_annotation.add(ann_future)
                                                if unit:
                                                    future_to_info[ann_future] = (idx_res, unit)
                                            except DailyLimitExhausted as limit_exc:
                                                self.ui.stop_progress()
                                                self.ui.error(f"⚠ Daily API limit reached: {limit_exc}")
                                                api_executor.shutdown(wait=True, cancel_futures=True)
                                                annotation_executor.shutdown(wait=True, cancel_futures=False)
                                                
                                                for api_fut in list(self.pending_api):
                                                    if api_fut.done():
                                                        try:
                                                            idx_h, result_h, elapsed_h = api_fut.result()
                                                            ann_res = self.annotate_and_finish(idx_h, result_h, elapsed_h)
                                                            self.submission_results.append(ann_res)
                                                        except Exception:
                                                            pass
                                                for ann_fut in list(self.pending_annotation):
                                                     if ann_fut.done() and not ann_fut.cancelled():
                                                         try:
                                                             self.submission_results.append(ann_fut.result())
                                                         except Exception:
                                                             pass
                                                 
                                                checkpoint_path = save_checkpoint(
                                                     output_dir=self.config.output_dir,
                                                     results=self.submission_results,
                                                     rolling=self.rolling,
                                                     run_config_hash=run_config_hash,
                                                     stop_reason="rate_limit_exhausted",
                                                )
                                                self.ui.info(
                                                     f"✓ Checkpointed {len(self.submission_results)}/{len(self.units)} "
                                                     f"submissions to {checkpoint_path}"
                                                )
                                                self._forced_exit_code = 5
                                                return self._conclude(5, [])
                                            except Exception as exc:
                                                message = f"Unhandled processing failure: {exc}"
                                                if self.diagnostics:
                                                    self.diagnostics.record(
                                                        severity="error",
                                                        code="grading_unhandled_submission_zero_trust",
                                                        stage="grading",
                                                        message=message,
                                                        submission_folder=unit.folder_path.name if unit else "unknown",
                                                        exc=exc,
                                                    )
                                                if unit:
                                                    err_res = SubmissionResult.from_error(
                                                        unit=unit,
                                                        rubric=self.config.rubric,
                                                        grade_points=self.config.grade_points,
                                                        error_message=message,
                                                    )
                                                    self.submission_results.append(err_res)
                                                    with self.rolling_lock:
                                                        self.completed_submissions += 1
                                                        remaining = len(self.units) - self.completed_submissions
                                                        self.rolling = update_rolling_snapshot(self.rolling, err_res, 0.0, remaining)
                                                        current_rolling = self.rolling
                                                    with self.ui_lock:
                                                        self.ui.submission_finished(
                                                            index=idx,
                                                            total=len(self.units),
                                                            folder_name=unit.folder_path.name,
                                                            band=err_res.grade_result.band,
                                                            had_error=True,
                                                            rationale=f"Zero-Trust Error: {message}",
                                                            elapsed_seconds=0.0,
                                                            snapshot=current_rolling,
                                                        )
                                                    save_checkpoint(
                                                        output_dir=self.config.output_dir,
                                                        results=self.submission_results,
                                                        rolling=self.rolling,
                                                        run_config_hash=run_config_hash,
                                                        stop_reason="incremental",
                                                    )
                                        else:
                                            self.pending_annotation.discard(future)
                                            idx, unit = future_to_info.pop(future, (None, None))
                                            try:
                                                res = future.result()
                                                self.submission_results.append(res)
                                            except Exception as exc:
                                                message = f"Unhandled annotation failure: {exc}"
                                                if self.diagnostics:
                                                    self.diagnostics.record(
                                                        severity="error",
                                                        code="annotation_unhandled_submission_zero_trust",
                                                        stage="annotation",
                                                        message=message,
                                                        submission_folder=unit.folder_path.name if unit else "unknown",
                                                        exc=exc,
                                                    )
                                                if unit:
                                                    err_res = SubmissionResult.from_error(
                                                        unit=unit,
                                                        rubric=self.config.rubric,
                                                        grade_points=self.config.grade_points,
                                                        error_message=message,
                                                    )
                                                    self.submission_results.append(err_res)
                                                    with self.rolling_lock:
                                                        self.completed_submissions += 1
                                                        remaining = len(self.units) - self.completed_submissions
                                                        self.rolling = update_rolling_snapshot(self.rolling, err_res, 0.0, remaining)
                                                        current_rolling = self.rolling
                                                    with self.ui_lock:
                                                        self.ui.submission_finished(
                                                            index=idx,
                                                            total=len(self.units),
                                                            folder_name=unit.folder_path.name,
                                                            band=err_res.grade_result.band,
                                                            had_error=True,
                                                            rationale=f"Zero-Trust Error: {message}",
                                                            elapsed_seconds=0.0,
                                                            snapshot=current_rolling,
                                                        )
                                            save_checkpoint(
                                                output_dir=self.config.output_dir,
                                                results=self.submission_results,
                                                rolling=self.rolling,
                                                run_config_hash=run_config_hash,
                                                stop_reason="incremental",
                                            )
                                except KeyboardInterrupt:
                                    self.ui.stop_progress()
                                    action = prompt_interrupt_action(self.ui)

                                    if action == "resume":
                                        self.ui.start_progress(len(self.units))
                                        continue

                                    if action == "stop_keep":
                                        self.ui.info("Stopping after current tasks finish; keeping completed results.")
                                        self._shutdown_executors(api_executor, annotation_executor, cancel_annotation=False)
                                        for future in list(self.pending_annotation):
                                            if future.cancelled():
                                                continue
                                            try:
                                                self.submission_results.append(future.result())
                                            except Exception:
                                                continue
                                                
                                            save_checkpoint(
                                                output_dir=self.config.output_dir,
                                                results=self.submission_results,
                                                rolling=self.rolling,
                                                run_config_hash=run_config_hash,
                                                stop_reason="user_interrupt",
                                            )
                                        self.pending_api.clear()
                                        self.pending_annotation.clear()
                                        break

                                    if action == "clear_all":
                                        self._shutdown_executors(api_executor, annotation_executor, cancel_annotation=True)
                                        self.delete_session_artifacts()
                                        self.ui.info("Aborted grading run. All outputs and checkpoints from this session have been removed.")
                                        self._forced_exit_code = 130
                                        return 130
        except KeyboardInterrupt:
            pass

        if self._forced_exit_code is not None:
            return self._forced_exit_code
        warnings: list[str] = []
        try:
            self.artifacts["Grading audit CSV"] = write_grading_audit_csv(self.config.output_dir, self.submission_results)
            self.artifacts["Review queue CSV"] = write_review_queue_csv(self.config.output_dir, self.submission_results)
            self.artifacts["Brightspace import CSV"], warnings = write_brightspace_import_csv(
                output_dir=self.config.output_dir,
                template_csv_path=self.config.grades_template_csv if hasattr(self.config, 'grades_template_csv') else Path(),
                submission_results=self.submission_results,
                grade_column=self.config.grade_column if hasattr(self.config, 'grade_column') else "Grade",
                identifier_column=self.config.identifier_column if hasattr(self.config, 'identifier_column') else "OrgDefinedId",
                comment_column=self.config.comment_column if hasattr(self.config, 'comment_column') else None,
            )
        except Exception as exc:
            message = f"Failed to write report CSV outputs: {exc}"
            if self.diagnostics:
                self.diagnostics.record(
                    severity="error",
                    code="report_write_failed",
                    stage="report_write",
                    message=message,
                    exc=exc,
                )
            self.ui.error(message)
            return self._conclude(1, [])

        for warning in warnings:
            if self.diagnostics:
                self.diagnostics.record(
                    severity="warning",
                    code="report_mapping_warning",
                    stage="report_write",
                    message=warning,
                )

        return self._conclude(0, warnings)

    def _conclude(self, exit_code: int, warnings: list[str]) -> int:
        self.ui.stop_progress()
        self.ui.clear_status()
        if exit_code in (0, 3, 4):
            clear_checkpoint(self.config.output_dir)
        self.ui.section_heading("Results")
        summary = summarize_results(
            submission_results=self.submission_results,
            warning_count=len(warnings),
            snapshot=self.rolling,
        )
        
        # Remap exit code unless it's a dry run
        is_dry_run = getattr(self.config, "dry_run", False)
        if exit_code == 0 and not is_dry_run:
            if summary.failed_with_error_count > 0:
                exit_code = 4
            elif summary.review_required_count > 0:
                exit_code = 3

        if self.diagnostics:
            self.diagnostics.set_run_totals(
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
                written_diagnostics = self.diagnostics.write_json(self.diagnostics_path)
            except Exception as exc:
                self.ui.warning(f"Failed to write diagnostics file {self.diagnostics_path}: {exc}")
                
            self.artifacts["Diagnostics JSON"] = written_diagnostics or self.diagnostics_path

        for warning in warnings:
            self.ui.warning(warning)

        self.ui.emit_summary(summary)
        
        # Don't emit artifacts if they are None (except we might have None for not-created)
        artifact_payload = dict(self.artifacts)
        self.ui.emit_artifacts(artifact_payload)

        # Generate and display the visual audit CLI summary for non-dry runs
        if not is_dry_run:
            try:
                from .audit import analyze_grading_audit
                from .ui import print_audit_report
                audit_csv = self.config.output_dir / "grading_audit.csv"
                if audit_csv.exists():
                    report = analyze_grading_audit(audit_csv, rubric=self.config.rubric)
                    print_audit_report(report, self.config.output_dir)
            except Exception as exc:
                self.ui.warning(f"Failed to generate audit report: {exc}")


        # JSON output support
        if getattr(self.config, "json_output", False):
            import json as _json

            payload = {
                "exit_code": exit_code,
                "submissions_processed": summary.submissions_processed,
                "success_count": summary.success_count,
                "review_required_count": summary.review_required_count,
                "failed_with_error_count": summary.failed_with_error_count,
                "warning_count": summary.warning_count,
                "band_counts": summary.band_counts or {},
                "mean_seconds_per_submission": summary.mean_seconds,
                "artifacts": {k: str(v) for k, v in artifact_payload.items() if v is not None},
                "diagnostics_file": str(self.diagnostics_path),
            }
            sys.stdout.write(_json.dumps(payload) + "\n")
            sys.stdout.flush()

        return exit_code


    def compute_submission_pdf_hash(self, pdf_paths: list[Path]) -> str:
        """Compute a combined SHA-256 hash of all PDF files in a submission."""
        import hashlib
        hasher = hashlib.sha256()
        # Sort paths by name for deterministic ordering
        for path in sorted(pdf_paths, key=lambda p: p.name):
            if path.exists():
                with path.open("rb") as handle:
                    while True:
                        block = handle.read(65536)
                        if not block:
                            break
                        hasher.update(block)
        return hasher.hexdigest()

    def get_or_compute_preprocessing(self, unit: Any) -> list[ExtractedPdf]:
        """Load preprocessed PDF text/blocks from cache or compute and save them."""
        if self.config.grading_mode != LEGACY_MODE and not self.config.extract_blocks:
            return []

        import json as _json
        
        pdf_paths = unit.pdf_paths
        pdf_hash = self.compute_submission_pdf_hash(pdf_paths)
        composite_key = f"{pdf_hash}_{EXTRACTION_VERSION}"
        
        cache_dir = getattr(self.config, "cache_dir", Path(".grader_cache"))
        prep_cache_dir = cache_dir / "preprocessing"
        cache_file = prep_cache_dir / f"{composite_key}.json"
        
        if cache_file.exists():
            try:
                raw_data = _json.loads(cache_file.read_text(encoding="utf-8"))
                return [deserialize_extracted_pdf(item) for item in raw_data]
            except Exception:
                # If cache is corrupt, fallback to computing it
                pass
                
        # Compute and cache
        extracted_pdfs = []
        for pdf_path in pdf_paths:
            try:
                pdf_extract = extract_pdf_text(
                    pdf_path=pdf_path,
                    temp_dir=self.config.temp_dir,
                    ocr_char_threshold=self.config.ocr_char_threshold,
                    gemini_api_key=self.config.gemini_api_key,
                    gemini_model=self.config.extraction_model,
                    rate_limiter=self.config.rate_limiter,
                )
            except Exception as exc:
                pdf_extract = ExtractedPdf(
                    pdf_path=pdf_path,
                    blocks=[],
                    text="",
                    source="error",
                    native_char_count=0,
                    ocr_char_count=0,
                )
                # Re-record to diagnostics if configured
                if self.diagnostics is not None:
                    self.diagnostics.record(
                        severity="error",
                        code="grading_extract_failed",
                        stage="grading",
                        message=f"Text extraction failed for {pdf_path.name}: {exc}",
                        submission_folder=unit.folder_path.name,
                        exc=exc,
                    )
            extracted_pdfs.append(pdf_extract)
            
        try:
            prep_cache_dir.mkdir(parents=True, exist_ok=True)
            serialized = [serialize_extracted_pdf(item) for item in extracted_pdfs]
            cache_file.write_text(_json.dumps(serialized, indent=2), encoding="utf-8")
        except Exception:
            # Saving cache failure shouldn't crash the run
            pass
            
        return extracted_pdfs

    def compute_cache_key_for_submission(self, unit: Any, rubric: Any) -> str:
        pdf_paths = [str(f) for f in unit.get_pdfs()]
        if self.config.grading_mode == UNIFIED_MODE:
            context_key = compute_context_cache_key(
                model=self.config.grader.model,
                rubric=rubric,
                solutions_pdf_path=self.config.solutions_pdf_path,
            )
            return compute_unified_grade_cache_key(
                submission_id=unit.folder_token,
                pdf_paths=pdf_paths,
                rubric=rubric,
                model=self.config.grader.model,
                context_key=context_key,
            )
        elif self.config.grading_mode == AGENT_MODE:
            return compute_agent_grade_cache_key(
                submission_id=unit.folder_token,
                pdf_paths=pdf_paths,
                rubric=rubric,
                model=self.config.model,
                agent_type=self.config.agent_type,
            )
        else:
            return compute_grade_cache_key(
                submission_id=unit.folder_token,
                rubric=rubric,
                solutions_text=self.config.solutions_text,
            )

    def regrade_question(self, question_id: str, units: list[Any]) -> int:
        import dataclasses
        self.units = units
        
        run_config_hash = compute_run_config_hash(
            rubric_path=self.config.rubric_yaml,
            solutions_pdf=self.config.solutions_pdf_path,
            model=self.config.grader.model if hasattr(self.config.grader, 'model') else "unknown",
            grading_mode=self.config.grading_mode,
        )

        checkpoint_file = get_checkpoint_path(self.config.output_dir)
        checkpoint_data = None
        if checkpoint_file.exists():
            import json as _json
            from .checkpoint import CheckpointData
            try:
                # Bypass expected hash check to load old checkpoint
                raw = _json.loads(checkpoint_file.read_text(encoding="utf-8"))
                results = [deserialize_result(r) for r in raw.get("results", [])]
                checkpoint_data = CheckpointData(
                    run_config_hash=raw.get("run_config_hash", ""),
                    results=results,
                    rolling=raw.get("rolling"),
                    completed_folders=set(raw.get("completed_folders", []))
                )
            except Exception as exc:
                self.ui.warning(f"Failed to load old checkpoint for regrade: {exc}")

        old_results_by_token = {}
        if checkpoint_data:
            for r in checkpoint_data.results:
                old_results_by_token[r.folder_token] = r

        target_rubric = None
        for q in self.config.rubric.questions:
            if q.id == question_id:
                target_rubric = q
                break
        
        if not target_rubric:
            self.ui.error(f"Question '{question_id}' not found in the current rubric.")
            return 1

        mini_rubric = dataclasses.replace(
            self.config.rubric,
            questions=[target_rubric]
        )

        self.ui.section_heading(f"Regrading Question: {question_id}")
        self.ui.start_progress(len(self.units))
        
        start_time = time.time()
        success_count = 0
        error_count = 0
        
        updated_results = []
        
        for unit in self.units:
            try:
                # 1. Get old results for this submission
                existing_res = old_results_by_token.get(unit.folder_token)
                old_question_results = []
                if existing_res:
                    old_question_results = [q for q in existing_res.question_results if q.id != question_id]
                
                # 2. Extract text for regex precheck
                pdf_paths = unit.get_pdfs()
                if not pdf_paths:
                    raise Exception("No PDFs found")
                    
                pre_extracted = self.get_or_compute_preprocessing(unit)
                combined_text = ""
                for item in pre_extracted:
                    combined_text += item.text + "\n"
                    
                # 3. Try regex precheck
                q_result = regex_precheck(target_rubric, combined_text)
                
                # 4. Fallback to LLM if no regex match
                if not q_result:
                    if self.config.grading_mode == UNIFIED_MODE:
                        llm_results, _ = self.config.grader.grade_submission_unified(
                            submission_id=unit.folder_token,
                            pdf_paths=pdf_paths,
                            rubric=mini_rubric,
                            solutions_pdf_path=self.config.solutions_pdf_path,
                        )
                    elif self.config.grading_mode == AGENT_MODE:
                        llm_results, _ = self.config.grader.grade_submission_agent(
                            submission_id=unit.folder_token,
                            pdf_paths=pdf_paths,
                            rubric=mini_rubric,
                        )
                    else:
                        llm_results, _ = self.config.grader.grade_submission(
                            submission_id=unit.folder_token,
                            combined_text=combined_text,
                            rubric=mini_rubric,
                            solutions_text=self.config.solutions_text or "",
                        )
                    if llm_results:
                        q_result = llm_results[0]
                
                if not q_result:
                    raise Exception(f"Failed to generate result for question {question_id}")
                    
                # 5. Merge and score
                merged_q_results = old_question_results + [q_result]
                grade_result = score_submission(
                    merged_q_results,
                    self.config.rubric,
                    self.config.grade_points,
                    self.config.diagnostics,
                )
                
                new_submission_result = SubmissionResult(
                    folder_path=unit.folder_path,
                    student_name=unit.student_name,
                    folder_token=unit.folder_token,
                    question_results=merged_q_results,
                    grade_result=grade_result,
                    status="graded",
                    output_pdf_paths=[],
                )
                
                # 6. Re-annotate
                out_pdfs = annotate_submission_pdfs(
                    unit,
                    new_submission_result,
                    self.config.output_dir,
                    self.config.rubric,
                    self.config.grade_points,
                    font_size=self.config.annotation_font_size,
                    dry_run_marks=self.config.annotate_dry_run_marks,
                )
                new_submission_result.output_pdf_paths = [str(p) for p in out_pdfs]
                
                # 7. Write to cache with new rubric hash
                new_cache_key = self.compute_cache_key_for_submission(unit, self.config.rubric)
                payload = [
                    {
                        "verdict": qr.verdict,
                        "confidence": qr.confidence,
                        "logic_analysis": qr.logic_analysis,
                        "short_reason": qr.short_reason,
                        "detail_reason": qr.detail_reason,
                        "evidence_quote": qr.evidence_quote,
                        "coords": list(qr.coords) if qr.coords else None,
                        "page_number": qr.page_number,
                        "source_file": qr.source_file,
                        "placement_source": qr.placement_source,
                        "grading_source": qr.grading_source,
                    }
                    for qr in merged_q_results
                ]
                self.config.grader._set_cache(new_cache_key, payload)
                
                updated_results.append(new_submission_result)
                success_count += 1
                
            except Exception as exc:
                error_count += 1
                self.ui.warning(f"Error regrading {unit.folder_path.name}: {exc}")
                # Maintain old result if it exists so we don't drop the student entirely
                if existing_res:
                    updated_results.append(existing_res)
                    
            self.ui.advance_progress()
            
        # Update checkpoint and orchestrator state
        self.submission_results = updated_results
        self.completed_submissions = len(updated_results)
        
        save_checkpoint(self.config.output_dir, updated_results, None, run_config_hash)
        
        # Write CSV artifacts
        from .report import write_brightspace_import_csv, write_grading_audit_csv, write_review_queue_csv
        self.artifacts["Brightspace grades CSV"] = write_brightspace_import_csv(
            self.config.output_dir,
            updated_results,
            self.config.identifier_column,
            self.config.grade_column,
            self.config.comment_column,
            self.config.grades_template_csv,
        )
        self.artifacts["Grading audit CSV"] = write_grading_audit_csv(self.config.output_dir, updated_results, self.config.rubric)
        self.artifacts["Review queue CSV"] = write_review_queue_csv(self.config.output_dir, updated_results)

        elapsed = time.time() - start_time
        summary = RunSummary(
            submissions_processed=len(self.units),
            success_count=success_count,
            failed_with_error_count=error_count,
            review_required_count=sum(1 for r in updated_results if r.grade_result.verdict == "REVIEW_REQUIRED"),
            warning_count=0,
            band_counts={},
            mean_seconds=(elapsed / max(1, len(self.units))),
        )
        
        # We need band counts for the report
        for r in updated_results:
            summary.band_counts[r.grade_result.verdict] = summary.band_counts.get(r.grade_result.verdict, 0) + 1

        self.ui.emit_summary(summary)
        artifact_payload = dict(self.artifacts)
        self.ui.emit_artifacts(artifact_payload)
        
        if not getattr(self.config, "dry_run", False):
            try:
                from .audit import analyze_grading_audit
                from .ui import print_audit_report
                audit_csv = self.config.output_dir / "grading_audit.csv"
                if audit_csv.exists():
                    report = analyze_grading_audit(audit_csv, rubric=self.config.rubric)
                    print_audit_report(report, self.config.output_dir)
            except Exception as exc:
                self.ui.warning(f"Failed to generate audit report: {exc}")
                
        return 0 if error_count == 0 else 1
    def delete_session_artifacts(self) -> None:
        output_root = self.config.output_dir.resolve()
        dangerous_roots = {
            Path("/").resolve(),
            Path.home().resolve(),
            Path.cwd().resolve(),
        }
        if output_root in dangerous_roots:
            self.ui.warning(f"Refusing to delete artifacts: unsafe output_dir {output_root}")
            return

        candidates: set[Path] = set()

        for path in self.artifacts.values():
            if path is not None:
                candidates.add(path)

        for result in self.submission_results:
            for pdf_path in getattr(result, "output_pdf_paths", []) or []:
                candidates.add(Path(pdf_path))

        candidates.add(self.diagnostics_path)

        for path in candidates:
            try:
                resolved = path.resolve()
            except Exception:
                continue

            if not resolved.is_file():
                continue

            try:
                if not resolved.is_relative_to(output_root):
                    continue
            except Exception:
                continue

            try:
                path.unlink()
            except FileNotFoundError:
                continue
            except Exception as exc:
                self.ui.warning(f"Failed to delete artifact {path}: {exc}")
        try:
            clear_checkpoint(self.config.output_dir)
        except Exception:
            pass

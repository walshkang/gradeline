from __future__ import annotations

import threading
from typing import Any

from ..types import SubmissionResult


LOW_CONFIDENCE_THRESHOLD = 0.55


def append_error(existing: str | None, new_error: str) -> str:
    """Helper to combine error strings."""
    if not existing:
        return new_error
    return f"{existing}; {new_error}"


def build_trust_rationale(
    question_results: list[Any],
    percent: float,
    band: str,
    rubric_bands: dict[str, float],
    global_flags: list[str],
) -> str:
    """Build a deterministic one-line trust rationale for a graded submission."""
    from ..ui import _BAND_DISPLAY

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

    return " | ".join(parts)


def update_rolling_snapshot(
    snapshot: Any | None,
    result: SubmissionResult,
    sub_elapsed: float,
    remaining_submissions: int,
) -> Any:
    """Calculate and update the rolling timing snapshot dataclass."""
    from ..orchestrator import RollingSnapshot

    band_counts = dict(snapshot.band_counts) if snapshot else {}
    current_band = result.grade_result.band
    band_counts[current_band] = band_counts.get(current_band, 0) + 1

    failure_count = (snapshot.failure_count if snapshot else 0) + (1 if result.error else 0)
    done_count = (snapshot.submissions_done if snapshot else 0) + 1
    total_sec = (snapshot.total_seconds if snapshot else 0.0) + sub_elapsed
    mean_sec = total_sec / done_count if done_count > 0 else 0.0
    eta_sec = mean_sec * remaining_submissions

    return RollingSnapshot(
        band_counts=band_counts,
        failure_count=failure_count,
        submissions_done=done_count,
        total_seconds=total_sec,
        mean_seconds=mean_sec,
        eta_seconds=eta_sec,
    )


def process_student_annotation(
    index: int,
    result: SubmissionResult,
    sub_elapsed: float,
    config: Any,
    ui: Any,
    rolling: Any | None,
    completed_submissions: int,
    total_units: int,
    diagnostics: Any = None,
    ui_lock: threading.Lock | None = None,
    rolling_lock: threading.Lock | None = None,
) -> tuple[SubmissionResult, Any, int]:
    """Annotates submission PDFs, builds rationale, updates rolling metrics & UI.

    Returns (updated_result, updated_rolling, new_completed_submissions_count).
    """
    from ..orchestrator import annotate_submission_pdfs

    ui_lock = ui_lock or threading.Lock()
    rolling_lock = rolling_lock or threading.Lock()
    folder_name = result.submission.folder_path.name

    try:
        output_pdf_paths, updated_question_results = annotate_submission_pdfs(
            submission=result.submission,
            rubric=config.rubric,
            question_results=result.question_results,
            block_registry=result.block_registry or {},
            output_dir=config.output_dir,
            submissions_root=config.submissions_root,
            final_band=result.grade_result.band,
            dry_run=config.dry_run,
            annotate_dry_run_marks=config.annotate_dry_run_marks,
            annotation_font_size=config.annotation_font_size,
        )
        result.output_pdf_paths = output_pdf_paths
        result.question_results = updated_question_results
    except Exception as exc:
        annotation_error = f"Annotation failed: {exc}"
        with rolling_lock:
            if diagnostics:
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
        rubric_bands=config.rubric.bands,
        global_flags=result.global_flags,
    )

    with rolling_lock:
        new_completed = completed_submissions + 1
        remaining = total_units - new_completed
        updated_rolling = update_rolling_snapshot(rolling, result, sub_elapsed, remaining)

    with ui_lock:
        ui.submission_finished(
            index=index,
            total=total_units,
            folder_name=folder_name,
            band=result.grade_result.band,
            had_error=bool(result.error),
            rationale=rationale,
            elapsed_seconds=sub_elapsed,
            snapshot=updated_rolling,
        )

    return result, updated_rolling, new_completed

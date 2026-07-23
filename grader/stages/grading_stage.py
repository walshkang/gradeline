from __future__ import annotations

import time
import threading
from dataclasses import replace
from typing import Any, Callable

from ..rate_limit import DailyLimitExhausted
from ..types import ExtractedPdf, SubmissionResult


LEGACY_MODE = "legacy"
UNIFIED_MODE = "unified"


def process_student_grading(
    index: int,
    unit: Any,
    config: Any,
    ui: Any,
    pre_extracted: list[ExtractedPdf] | None = None,
    error: Exception | None = None,
    diagnostics: Any = None,
    ui_lock: threading.Lock | None = None,
    rolling_lock: threading.Lock | None = None,
    total_units: int = 1,
    locked_status_update: Callable[[str], None] | None = None,
) -> tuple[int, SubmissionResult, float]:
    """Processes a single student submission through the grading phase.

    Returns (index, SubmissionResult, elapsed_seconds).
    """
    from ..orchestrator import grade_one_submission

    ui_lock = ui_lock or threading.Lock()
    rolling_lock = rolling_lock or threading.Lock()
    folder_name = unit.folder_path.name
    sub_start = time.monotonic()

    with ui_lock:
        ui.submission_started(index=index, total=total_units, folder_name=folder_name)

    status_prefix = f"[{index}/{total_units}] {folder_name}"
    if config.grading_mode == LEGACY_MODE:
        with ui_lock:
            ui.status(f"{status_prefix} :: preparing extraction")
    else:
        with ui_lock:
            ui.status(f"{status_prefix} :: preparing unified grading")

    if locked_status_update is None:
        def status_update(message: str) -> None:
            with ui_lock:
                ui.status(f"{status_prefix} :: {message}")
    else:
        status_update = locked_status_update

    submission_task_id: int | None = None
    grading_progress: Callable[[int, int, str], None] | None = None
    if config.grading_mode == UNIFIED_MODE:
        total_questions = len(config.rubric.questions)
        if total_questions > 0:
            submission_task_id = ui.add_submission_task(folder_name=folder_name, total_questions=total_questions)

            def grading_progress_cb(current: int, total: int, question_id: str) -> None:
                ui.update_submission_task(submission_task_id or 0, current, question_id)

            grading_progress = grading_progress_cb

    try:
        if error is not None:
            raise error
        result = grade_one_submission(
            unit=unit,
            config=config,
            status_update=status_update,
            progress_callback=grading_progress,
            pre_extracted=pre_extracted,
        )
        if pre_extracted and not result.block_registry:
            block_map = {b.id: b for item in pre_extracted for b in item.blocks}
            result = replace(result, block_registry=block_map)
    except DailyLimitExhausted:
        raise
    except Exception as exc:
        msg_lower = str(exc).lower()
        if "429" in msg_lower or "resource_exhausted" in msg_lower or "quota" in msg_lower:
            model_name = config.grader.model if hasattr(config.grader, "model") else "unknown"
            raise DailyLimitExhausted(model_name, 0, 0) from exc
        message = f"Unhandled submission failure: {exc}"
        with rolling_lock:
            if diagnostics:
                diagnostics.record(
                    severity="error",
                    code="grading_unhandled_submission",
                    stage="grading",
                    message=message,
                    submission_folder=folder_name,
                    exc=exc,
                )
        result = SubmissionResult.from_error(
            unit=unit,
            rubric=config.rubric,
            grade_points=config.grade_points,
            error_message=message,
        )
    finally:
        if submission_task_id is not None:
            ui.remove_submission_task(submission_task_id)

    sub_elapsed = time.monotonic() - sub_start
    with ui_lock:
        ui.clear_status()

    return index, result, sub_elapsed

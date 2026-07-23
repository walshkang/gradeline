from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..types import SubmissionResult
from ..ui import RunSummary


def summarize_results(
    submission_results: list[SubmissionResult],
    warning_count: int,
    snapshot: Any | None,
) -> RunSummary:
    """Summarizes grading session results into a RunSummary dataclass."""
    success_count = 0
    review_required_count = 0
    failed_with_error_count = 0
    band_counts: dict[str, int] = {}

    for r in submission_results:
        band = r.grade_result.band
        band_counts[band] = band_counts.get(band, 0) + 1

        if r.error:
            failed_with_error_count += 1
        elif band == "REVIEW_REQUIRED":
            review_required_count += 1
        else:
            success_count += 1

    return RunSummary(
        submissions_processed=len(submission_results),
        success_count=success_count,
        review_required_count=review_required_count,
        failed_with_error_count=failed_with_error_count,
        warning_count=warning_count,
        band_counts=band_counts,
        mean_seconds=snapshot.mean_seconds if snapshot else 0.0,
    )


def write_reports_and_conclude(
    config: Any,
    ui: Any,
    submission_results: list[SubmissionResult],
    artifacts: dict[str, Path | None],
    rolling: Any | None,
    diagnostics_path: Path,
    diagnostics: Any = None,
    forced_exit_code: int | None = None,
) -> int:
    """Writes report CSVs, diagnostics JSON, renders CLI summaries, and returns final exit code."""
    from ..orchestrator import (
        write_brightspace_import_csv,
        write_grading_audit_csv,
        write_review_queue_csv,
    )

    if forced_exit_code is not None:
        exit_code = forced_exit_code
        warnings: list[str] = []
    else:
        warnings = []
        try:
            artifacts["Grading audit CSV"] = write_grading_audit_csv(config.output_dir, submission_results)
            artifacts["Review queue CSV"] = write_review_queue_csv(config.output_dir, submission_results)
            artifacts["Brightspace import CSV"], warnings = write_brightspace_import_csv(
                output_dir=config.output_dir,
                template_csv_path=getattr(config, "grades_template_csv", Path()),
                submission_results=submission_results,
                grade_column=getattr(config, "grade_column", "Grade"),
                identifier_column=getattr(config, "identifier_column", "OrgDefinedId"),
                comment_column=getattr(config, "comment_column", None),
            )
            exit_code = 0
        except Exception as exc:
            message = f"Failed to write report CSV outputs: {exc}"
            if diagnostics:
                diagnostics.record(
                    severity="error",
                    code="report_write_failed",
                    stage="report_write",
                    message=message,
                    exc=exc,
                )
            ui.error(message)
            exit_code = 1

    for warning in warnings:
        if diagnostics:
            diagnostics.record(
                severity="warning",
                code="report_mapping_warning",
                stage="report_write",
                message=warning,
            )

    ui.stop_progress()
    ui.clear_status()

    summary = summarize_results(
        submission_results=submission_results,
        warning_count=len(warnings),
        snapshot=rolling,
    )

    is_dry_run = getattr(config, "dry_run", False)
    if exit_code == 0 and not is_dry_run:
        if summary.failed_with_error_count > 0:
            exit_code = 4
        elif summary.review_required_count > 0:
            exit_code = 3

    if diagnostics:
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
        except Exception as exc:
            ui.warning(f"Failed to write diagnostics file {diagnostics_path}: {exc}")

        artifacts["Diagnostics JSON"] = written_diagnostics or diagnostics_path

    for warning in warnings:
        ui.warning(warning)

    ui.emit_summary(summary)
    artifact_payload = dict(artifacts)
    ui.emit_artifacts(artifact_payload)

    # Generate visual audit CLI summary for non-dry runs
    if not is_dry_run:
        try:
            from ..audit import analyze_grading_audit
            from ..ui import print_audit_report

            audit_csv = config.output_dir / "grading_audit.csv"
            if audit_csv.exists():
                report = analyze_grading_audit(audit_csv, rubric=config.rubric)
                print_audit_report(report, config.output_dir)
        except Exception as exc:
            ui.warning(f"Failed to generate audit report: {exc}")

    # JSON output support
    if getattr(config, "json_output", False):
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
            "diagnostics_file": str(diagnostics_path),
        }
        sys.stdout.write(_json.dumps(payload) + "\n")
        sys.stdout.flush()

    return exit_code

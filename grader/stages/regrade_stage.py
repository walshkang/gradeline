from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path
from typing import Any

from ..checkpoint import (
    CheckpointData,
    compute_run_config_hash,
    deserialize_result,
    get_checkpoint_path,
    save_checkpoint,
)
from ..precheck import regex_precheck
from ..preprocessing import compute_cache_key_for_submission, get_or_compute_preprocessing
from ..score import score_submission
from ..types import SubmissionResult
from ..ui import RunSummary

UNIFIED_MODE = "unified"
AGENT_MODE = "agent"


def execute_question_regrade(
    question_id: str,
    units: list[Any],
    config: Any,
    ui: Any,
    artifacts: dict[str, Path | None],
    diagnostics: Any = None,
) -> int:
    """Executes single-question regrading across all student submission units.

    Returns exit code (0 for clean success, 1 for errors).
    """
    from ..orchestrator import (
        annotate_submission_pdfs,
        write_brightspace_import_csv,
        write_grading_audit_csv,
        write_review_queue_csv,
    )

    run_config_hash = compute_run_config_hash(
        rubric_path=config.rubric_yaml,
        solutions_pdf=config.solutions_pdf_path,
        model=config.grader.model if hasattr(config.grader, "model") else "unknown",
        grading_mode=config.grading_mode,
    )

    checkpoint_file = get_checkpoint_path(config.output_dir)
    checkpoint_data = None
    if checkpoint_file.exists():
        try:
            raw = json.loads(checkpoint_file.read_text(encoding="utf-8"))
            results = [deserialize_result(r) for r in raw.get("results", [])]
            checkpoint_data = CheckpointData(
                run_config_hash=raw.get("run_config_hash", ""),
                results=results,
                rolling=raw.get("rolling"),
                completed_folders=set(raw.get("completed_folders", [])),
            )
        except Exception as exc:
            ui.warning(f"Failed to load old checkpoint for regrade: {exc}")

    old_results_by_token = {}
    if checkpoint_data:
        for r in checkpoint_data.results:
            old_results_by_token[r.folder_token] = r

    target_rubric = None
    for q in config.rubric.questions:
        if q.id == question_id:
            target_rubric = q
            break

    if not target_rubric:
        ui.error(f"Question '{question_id}' not found in the current rubric.")
        return 1

    mini_rubric = dataclasses.replace(config.rubric, questions=[target_rubric])

    ui.section_heading(f"Regrading Question: {question_id}")
    ui.start_progress(len(units))

    start_time = time.time()
    success_count = 0
    error_count = 0
    updated_results: list[SubmissionResult] = []

    for unit in units:
        existing_res = old_results_by_token.get(unit.folder_token)
        try:
            old_question_results = []
            if existing_res:
                old_question_results = [q for q in existing_res.question_results if q.id != question_id]

            pdf_paths = unit.get_pdfs()
            if not pdf_paths:
                raise Exception("No PDFs found")

            pre_extracted = get_or_compute_preprocessing(unit, config, diagnostics)
            combined_text = ""
            for item in pre_extracted:
                combined_text += item.text + "\n"

            precheck_results, hints = regex_precheck(mini_rubric, combined_text)
            q_result = precheck_results.get(question_id)

            if not q_result:
                regrade_rubric = mini_rubric
                if question_id in hints:
                    note = (
                        f"\nNote: The student's final answer appears to match the expected value ({hints[question_id]}). "
                        "Focus your evaluation on whether the student showed the required methodology/setup."
                    )
                    hinted_target = dataclasses.replace(target_rubric, scoring_rules=target_rubric.scoring_rules + note)
                    regrade_rubric = dataclasses.replace(mini_rubric, questions=[hinted_target])

                if config.grading_mode == UNIFIED_MODE:
                    llm_results, _ = config.grader.grade_submission_unified(
                        submission_id=unit.folder_token,
                        pdf_paths=pdf_paths,
                        rubric=regrade_rubric,
                        solutions_pdf_path=config.solutions_pdf_path,
                    )
                elif config.grading_mode == AGENT_MODE:
                    llm_results, _ = config.grader.grade_submission_agent(
                        submission_id=unit.folder_token,
                        pdf_paths=pdf_paths,
                        rubric=regrade_rubric,
                    )
                else:
                    llm_results, _ = config.grader.grade_submission(
                        submission_id=unit.folder_token,
                        combined_text=combined_text,
                        rubric=regrade_rubric,
                        solutions_text=config.solutions_text or "",
                    )
                if llm_results:
                    q_result = llm_results[0]

            if not q_result:
                raise Exception(f"Failed to generate result for question {question_id}")

            merged_q_results = old_question_results + [q_result]
            grade_result = score_submission(
                merged_q_results,
                config.rubric,
                config.grade_points,
                config.diagnostics,
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

            out_pdfs = annotate_submission_pdfs(
                unit,
                new_submission_result,
                config.output_dir,
                config.rubric,
                config.grade_points,
                font_size=config.annotation_font_size,
                dry_run_marks=config.annotate_dry_run_marks,
            )
            new_submission_result.output_pdf_paths = [str(p) for p in out_pdfs]

            new_cache_key = compute_cache_key_for_submission(unit, config.rubric, config)
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
            config.grader._set_cache(new_cache_key, payload)

            updated_results.append(new_submission_result)
            success_count += 1

        except Exception as exc:
            error_count += 1
            ui.warning(f"Error regrading {unit.folder_path.name}: {exc}")
            if existing_res:
                updated_results.append(existing_res)

        ui.advance_progress()

    save_checkpoint(config.output_dir, updated_results, None, run_config_hash)

    artifacts["Brightspace grades CSV"] = write_brightspace_import_csv(
        config.output_dir,
        updated_results,
        getattr(config, "identifier_column", "OrgDefinedId"),
        getattr(config, "grade_column", "Grade"),
        getattr(config, "comment_column", None),
        getattr(config, "grades_template_csv", None),
    )
    artifacts["Grading audit CSV"] = write_grading_audit_csv(config.output_dir, updated_results, config.rubric)
    artifacts["Review queue CSV"] = write_review_queue_csv(config.output_dir, updated_results)

    elapsed = time.time() - start_time
    summary = RunSummary(
        submissions_processed=len(units),
        success_count=success_count,
        failed_with_error_count=error_count,
        review_required_count=sum(1 for r in updated_results if r.grade_result.verdict == "REVIEW_REQUIRED"),
        warning_count=0,
        band_counts={},
        mean_seconds=(elapsed / max(1, len(units))),
    )

    for r in updated_results:
        summary.band_counts[r.grade_result.verdict] = summary.band_counts.get(r.grade_result.verdict, 0) + 1

    ui.emit_summary(summary)
    artifact_payload = dict(artifacts)
    ui.emit_artifacts(artifact_payload)

    if not getattr(config, "dry_run", False):
        try:
            from ..audit import analyze_grading_audit
            from ..ui import print_audit_report

            audit_csv = config.output_dir / "grading_audit.csv"
            if audit_csv.exists():
                report = analyze_grading_audit(audit_csv, rubric=config.rubric)
                print_audit_report(report, config.output_dir)
        except Exception as exc:
            ui.warning(f"Failed to generate audit report: {exc}")

    return 0 if error_count == 0 else 1

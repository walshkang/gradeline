from __future__ import annotations

import shutil
import time
from pathlib import Path

from ...prompts import (
    prompt_path,
    prompt_text,
    styled_error,
    styled_info,
    styled_section_heading,
    styled_success,
    styled_warning,
)
from ...report import read_csv_rows
from ...workflow_profile import load_workflow_profile


def spot_grade_interactive(*, profile_spec: str, pdf_path: Path | None, student_name: str | None) -> int:
    import grader.workflow_cli as wcli

    profile = load_workflow_profile(profile_spec, cwd=wcli.get_project_root())

    if pdf_path is None:
        pdf_path = prompt_path("PDF file to grade", required=True, cwd=Path.cwd())
    if not pdf_path.exists() or not pdf_path.is_file():
        styled_error(f"PDF file not found: {pdf_path}")
        return 2

    if student_name is None:
        student_name = prompt_text("Student Name", default=pdf_path.stem, required=True)

    styled_section_heading("Spot Grading")
    styled_info(f"Student: {student_name}")
    styled_info(f"File: {pdf_path}")

    timestamp = int(time.time())
    raw_safe_name = "".join(c for c in student_name if c.isalnum() or c in (" ", "-", "_")).strip()
    safe_name = raw_safe_name or pdf_path.stem or "student"

    spot_run_dir = profile.grade.output_dir / "spot_runs" / f"{timestamp}_{safe_name}"
    spot_run_dir.mkdir(parents=True, exist_ok=True)

    subs_dir = spot_run_dir / "submissions"
    student_dir = subs_dir / f"SpotGrade - {student_name}"
    student_dir.mkdir(parents=True)
    shutil.copy2(pdf_path, student_dir / pdf_path.name)

    dummy_csv = spot_run_dir / "dummy.csv"
    dummy_csv.write_text(
        f"OrgDefinedId,{profile.grade.grade_column}\nspot_grade,\n",
        encoding="utf-8",
    )

    output_dir = spot_run_dir / "output"
    output_dir.mkdir()

    argv = wcli.build_grading_argv(profile.grade)
    for i, val in enumerate(argv):
        if val == "--submissions-dir":
            argv[i + 1] = str(subs_dir)
        elif val == "--grades-template-csv":
            argv[i + 1] = str(dummy_csv)
        elif val == "--output-dir":
            argv[i + 1] = str(output_dir)

    exit_code = wcli.invoke_grading_main(argv)
    if exit_code in (1, 2):
        return exit_code

    dest_dir = profile.grade.output_dir / student_dir.name
    dest_dir.mkdir(parents=True, exist_ok=True)

    annotated_pdf = output_dir / student_dir.name / pdf_path.name
    if annotated_pdf.exists():
        dest = dest_dir / pdf_path.name
        shutil.copy2(annotated_pdf, dest)
        styled_success(f"Graded PDF saved to {dest}")
    else:
        styled_warning("Could not find annotated PDF in output.")

    audit_csv = output_dir / "grading_audit.csv"
    if audit_csv.exists():
        rows, _ = read_csv_rows(audit_csv)
        if rows:
            first = rows[0]
            styled_info(f"Grade: {first.get('band')} ({first.get('percent')}%)")

    for name in (
        "grading_audit.csv",
        "review_queue.csv",
        "brightspace_grades_import.csv",
        "index_audit.csv",
        "grading_diagnostics.json",
    ):
        src = output_dir / name
        if src.exists():
            shutil.copy2(src, dest_dir / name)

    styled_info(f"Run artifacts preserved at: {spot_run_dir}")
    styled_info(f"Key CSV/JSON artifacts also copied to: {dest_dir}")

    return 0

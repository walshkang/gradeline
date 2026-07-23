from __future__ import annotations

import shutil
from pathlib import Path

from ...prompts import (
    prompt_yes_no,
    styled_info,
    styled_section_heading,
    styled_success,
    styled_warning,
)
from ...workflow_profile import load_workflow_profile


def clear_run_from_profile(*, profile_spec: str) -> int:
    import grader.workflow_cli as wcli

    profile = load_workflow_profile(profile_spec, cwd=wcli.get_project_root())
    output_dir = profile.grade.output_dir

    checkpoint_file = wcli.get_checkpoint_path(output_dir)

    checkpoint_exists = checkpoint_file.exists()
    outputs_exist = output_dir.exists() and any(output_dir.iterdir())

    if not checkpoint_exists and not outputs_exist:
        styled_info("No checkpoint or output files found to clear.")
        return 0

    styled_section_heading(f"Clear Grading Run: {profile_spec}")
    styled_warning("This will permanently delete the following files/folders:")
    if checkpoint_exists:
        styled_info(f"  - Checkpoint file: {checkpoint_file}")
    if outputs_exist:
        styled_info(f"  - Outputs & reports: {output_dir}/*")

    if not prompt_yes_no("Are you sure you want to clear this run?", default=False):
        styled_info("Clear run cancelled.")
        return 0

    removed_count = 0
    if checkpoint_exists:
        wcli.clear_checkpoint(output_dir)
        removed_count += 1
        styled_info("Cleared checkpoint file.")

    if output_dir.is_dir():
        for child in output_dir.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                removed_count += 1
            except Exception as exc:
                styled_warning(f"Could not remove {child}: {exc}")

    styled_success(f"Successfully cleared {removed_count} item(s)/folder(s).")
    return 0

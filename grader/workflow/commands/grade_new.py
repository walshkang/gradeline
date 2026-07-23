from __future__ import annotations

from typing import Any

from ..profile_utils import (
    is_interactive_terminal,
    setup_profile_interactive,
)
from ...prompts import (
    prompt_select,
    prompt_text,
    prompt_yes_no,
    styled_error,
    styled_info,
)
from ...workflow_profile import (
    DEFAULT_PROFILE_DIR,
    resolve_profile_path,
)


def grade_new_interactive(args: Any) -> int:
    import grader.workflow_cli as wcli

    if not is_interactive_terminal():
        styled_error("The 'Grade new assignment' flow is only available in interactive mode.")
        return 2

    project_root = wcli.get_project_root()
    styled_info("Press Ctrl+C at any prompt to return to the main menu.")
    while True:
        new_name = prompt_text("New assignment name", required=True)
        profile_path = resolve_profile_path(
            new_name,
            cwd=project_root,
            profile_dir=DEFAULT_PROFILE_DIR,
        )
        if profile_path.exists():
            choice_idx = prompt_select(
                "Profile already exists. Choose an option.",
                [
                    "Use existing profile",
                    "Overwrite with new setup",
                    "Enter a different name",
                    "Back to main menu",
                ],
                default=0,
            )
            if choice_idx is None or choice_idx == 3:
                raise wcli.AbortToMenu
            if choice_idx == 2:
                continue
            profile = new_name
            overwrite_profile = choice_idx == 1
            break
        else:
            profile = new_name
            overwrite_profile = False
            break

    exit_code = setup_profile_interactive(
        profile_spec=profile,
        overwrite=overwrite_profile,
    )
    if exit_code in (1, 2):
        return exit_code

    if prompt_yes_no("Run grading for this assignment now?", default=True):
        exit_code = wcli.run_with_optional_setup(
            profile_spec=profile,
            host_override=getattr(args, "host", None),
            port_override=getattr(args, "port", None),
        )
    return exit_code

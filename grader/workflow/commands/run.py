from __future__ import annotations

import sys
from pathlib import Path

from ...checkpoint import get_checkpoint_path
from ..profile_utils import (
    is_interactive_terminal,
    is_profile_not_found_error,
    setup_profile_interactive,
)
from ...prompts import (
    prompt_select,
    prompt_yes_no,
    styled_error,
    styled_info,
    styled_section_heading,
    styled_url,
    styled_warning,
)
from ..quickstart import quickstart_profile_interactive
from ...workflow_profile import WorkflowProfileError, load_workflow_profile


def run_from_profile(*, profile_spec: str, host_override: str | None, port_override: int | None) -> int:
    import grader.workflow_cli as wcli

    profile = load_workflow_profile(profile_spec, cwd=wcli.get_project_root())
    grading_argv = wcli.build_grading_argv(profile.grade)

    exit_code = wcli.invoke_grading_main(grading_argv)
    if exit_code in (1, 2):
        return exit_code

    state_path = wcli.initialize_review_state(output_dir=profile.grade.output_dir, rubric_yaml=None)
    status, reason = wcli.review_state_status(profile.grade.output_dir)
    if status != "valid":
        raise ValueError(f"Review state invalid at {state_path}: {reason}")

    host = wcli.resolve_host(profile=profile, host_override=host_override)
    requested_port = wcli.resolve_requested_port(profile=profile, port_override=port_override)
    port, shifted = wcli.resolve_available_port(host=host, preferred_port=requested_port)

    styled_section_heading("Review Server")
    styled_info(f"Profile: {profile.name}")
    styled_info(f"Output dir: {profile.grade.output_dir}")
    if shifted:
        styled_warning(f"Port {requested_port} is busy. Using {port}.")
    styled_url("Review URL", f"http://{host}:{port}")
    wcli.run_review_server(output_dir=profile.grade.output_dir, host=host, port=port)
    return 0


def run_with_optional_setup(*, profile_spec: str, host_override: str | None, port_override: int | None) -> int:
    import grader.workflow_cli as wcli

    try:
        return wcli.run_from_profile(profile_spec=profile_spec, host_override=host_override, port_override=port_override)
    except WorkflowProfileError as exc:
        if not is_profile_not_found_error(exc) or not is_interactive_terminal():
            raise
        styled_warning(str(exc))
        bootstrap_code = wcli.bootstrap_missing_profile(profile_spec=profile_spec)
        if bootstrap_code != 0:
            return bootstrap_code
        return wcli.run_from_profile(profile_spec=profile_spec, host_override=host_override, port_override=port_override)


def serve_from_profile(*, profile_spec: str, host_override: str | None, port_override: int | None) -> int:
    import grader.workflow_cli as wcli

    profile = load_workflow_profile(profile_spec)
    status, reason = wcli.review_state_status(profile.grade.output_dir)
    if status != "valid":
        state_path = wcli.state_path_for_output(profile.grade.output_dir)
        raise ValueError(f"Review state invalid at {state_path}: {reason}")

    host = wcli.resolve_host(profile=profile, host_override=host_override)
    requested_port = wcli.resolve_requested_port(profile=profile, port_override=port_override)
    port, shifted = wcli.resolve_available_port(host=host, preferred_port=requested_port)

    styled_section_heading("Review Server")
    styled_info(f"Profile: {profile.name}")
    styled_info(f"Output dir: {profile.grade.output_dir}")
    if shifted:
        styled_warning(f"Port {requested_port} is busy. Using {port}.")
    styled_url("Review URL", f"http://{host}:{port}")
    wcli.run_review_server(output_dir=profile.grade.output_dir, host=host, port=port)
    return 0


def serve_with_optional_setup(*, profile_spec: str, host_override: str | None, port_override: int | None) -> int:
    import grader.workflow_cli as wcli

    try:
        return wcli.serve_from_profile(profile_spec=profile_spec, host_override=host_override, port_override=port_override)
    except WorkflowProfileError as exc:
        if not is_profile_not_found_error(exc) or not is_interactive_terminal():
            raise
        styled_warning(str(exc))
        bootstrap_code = wcli.bootstrap_missing_profile(profile_spec=profile_spec)
        if bootstrap_code != 0:
            return bootstrap_code
        return wcli.serve_from_profile(profile_spec=profile_spec, host_override=host_override, port_override=port_override)


def resume_from_profile(*, profile_spec: str, host_override: str | None, port_override: int | None) -> int:
    import grader.workflow_cli as wcli

    profile = load_workflow_profile(profile_spec, cwd=wcli.get_project_root())

    checkpoint_file = get_checkpoint_path(profile.grade.output_dir)
    if not checkpoint_file.exists():
        styled_error(f"No checkpoint file found at {checkpoint_file} for profile '{profile_spec}'.")
        return 2

    grading_argv = wcli.build_grading_argv(profile.grade)
    grading_argv.append("--resume")

    exit_code = wcli.invoke_grading_main(grading_argv)
    if exit_code in (1, 2):
        return exit_code

    state_path = wcli.initialize_review_state(output_dir=profile.grade.output_dir, rubric_yaml=None)
    status, reason = wcli.review_state_status(profile.grade.output_dir)
    if status != "valid":
        raise ValueError(f"Review state invalid at {state_path}: {reason}")

    host = wcli.resolve_host(profile=profile, host_override=host_override)
    requested_port = wcli.resolve_requested_port(profile=profile, port_override=port_override)
    port, shifted = wcli.resolve_available_port(host=host, preferred_port=requested_port)

    styled_section_heading("Review Server")
    styled_info(f"Profile: {profile.name}")
    styled_info(f"Output dir: {profile.grade.output_dir}")
    if shifted:
        styled_warning(f"Port {requested_port} is busy. Using {port}.")
    styled_url("Review URL", f"http://{host}:{port}")
    wcli.run_review_server(output_dir=profile.grade.output_dir, host=host, port=port)
    return 0


def bootstrap_missing_profile(*, profile_spec: str) -> int:
    import grader.workflow_cli as wcli

    choice = wcli.prompt_missing_profile_bootstrap_choice()
    if choice == "abort":
        raise wcli.AbortToMenu
    if choice == "setup":
        return setup_profile_interactive(profile_spec=profile_spec, overwrite=False)

    quickstart_code = wcli.quickstart_profile_interactive(
        profile_spec=profile_spec,
        overwrite=False,
        auto_run=False,
    )
    if quickstart_code == 0:
        return 0

    if not prompt_yes_no("Quickstart did not complete. Try guided setup instead?", default=True):
        raise wcli.AbortToMenu
    return setup_profile_interactive(profile_spec=profile_spec, overwrite=False)


def prompt_missing_profile_bootstrap_choice() -> str:
    choices = ["quickstart (recommended)", "setup", "abort"]
    idx = prompt_select("Create missing profile with", choices, default=0)
    if idx is None:
        return "abort"
    return ["quickstart", "setup", "abort"][idx]

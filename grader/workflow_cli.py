from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .env import update_env_file
from .gemini_client import GeminiGrader
from .report import read_csv_rows, resolve_column_name
from .review.importer import ReviewInitError, initialize_review_state
from .review.server import run_review_server
from .review.state import state_path_for_output
from .prompts import (
    prompt_int,
    prompt_path,
    prompt_path_candidate,
    prompt_select,
    prompt_text,
    prompt_text_candidate,
    prompt_yes_no,
    styled_banner,
    styled_error,
    styled_info,
    styled_section_heading,
    styled_success,
    styled_table,
    styled_url,
    styled_warning,
)
from .config import load_rubric
from .defaults import resolve_model, set_default_model
from .workflow_detect import (
    DetectedConfig,
    default_question_ids,
    detect_defaults,
    scan_downloads_candidates,
)
from .workflow_profile import (
    DEFAULT_CONTEXT_CACHE_TTL_SECONDS,
    DEFAULT_GRADING_MODE,
    DEFAULT_MODEL,
    DEFAULT_PROFILE_DIR,
    DEFAULT_REVIEW_HOST,
    DEFAULT_REVIEW_PORT,
    GradeProfile,
    WorkflowProfile,
    WorkflowProfileError,
    list_profile_paths,
    load_workflow_profile,
    resolve_profile_path,
)

from .workflow.quickstart import quickstart_profile_interactive
from .workflow.import_cmd import import_assignment_assets
from .workflow.profile_utils import (
    list_profiles,
    setup_profile_interactive,
    set_default_model_interactive,
    configure_api_key_interactive,
    delete_assignment_interactive,
    is_profile_not_found_error,
    is_interactive_terminal,
)



REQUIRED_STATE_KEYS = {"schema_version", "run_metadata", "grading_context", "submissions"}


def get_project_root() -> Path:
    """Return the repository root containing the grader package."""
    return Path(__file__).resolve().parent.parent


class AbortToMenu(Exception):
    """Raised when user aborts an operation; in interactive mode, return to main menu."""


@dataclass(frozen=True)
class CliValueMapping:
    field: str
    flag: str
    value_type: str
    emit_if_empty: bool = True


@dataclass(frozen=True)
class QuickstartFieldSpec:
    key: str
    label: str
    kind: str


CLI_VALUE_MAPPINGS: tuple[CliValueMapping, ...] = (
    CliValueMapping("submissions_dir", "--submissions-dir", "path"),
    CliValueMapping("solutions_pdf", "--solutions-pdf", "path"),
    CliValueMapping("rubric_yaml", "--rubric-yaml", "path"),
    CliValueMapping("grades_template_csv", "--grades-template-csv", "path"),
    CliValueMapping("grade_column", "--grade-column", "str"),
    CliValueMapping("output_dir", "--output-dir", "path"),
    CliValueMapping("temp_dir", "--temp-dir", "path"),
    CliValueMapping("cache_dir", "--cache-dir", "path"),
    CliValueMapping("grading_mode", "--grading-mode", "str"),
    CliValueMapping("provider", "--provider", "str"),
    CliValueMapping("model", "--model", "str"),
    CliValueMapping("extraction_model", "--extraction-model", "str"),
    CliValueMapping("locator_model", "--locator-model", "str", emit_if_empty=False),
    CliValueMapping("api_key_env", "--api-key-env", "str"),
    CliValueMapping("identifier_column", "--identifier-column", "str"),
    CliValueMapping("comment_column", "--comment-column", "str", emit_if_empty=False),
    CliValueMapping("ocr_char_threshold", "--ocr-char-threshold", "int"),
    CliValueMapping("student_filter", "--student-filter", "str", emit_if_empty=False),
    CliValueMapping("check_plus_points", "--check-plus-points", "str"),
    CliValueMapping("check_points", "--check-points", "str"),
    CliValueMapping("check_minus_points", "--check-minus-points", "str"),
    CliValueMapping("review_required_points", "--review-required-points", "str", emit_if_empty=False),
    CliValueMapping("context_cache_ttl_seconds", "--context-cache-ttl-seconds", "int"),
    CliValueMapping("concurrency", "--concurrency", "int"),
    CliValueMapping("diagnostics_file", "--diagnostics-file", "path"),
    CliValueMapping("annotation_font_size", "--annotation-font-size", "float"),
)

CLI_FLAG_MAPPINGS: tuple[tuple[str, str], ...] = (
    ("dry_run", "--dry-run"),
    ("annotate_dry_run_marks", "--annotate-dry-run-marks"),
    ("plain", "--plain"),
    ("force_vision_extraction", "--force-vision-extraction"),
)

QUICKSTART_FIELDS: tuple[QuickstartFieldSpec, ...] = (
    QuickstartFieldSpec("submissions_dir", "Submissions directory (folder with student PDFs)", "path"),
    QuickstartFieldSpec("solutions_pdf", "Solutions PDF (your master answer key)", "path"),
    QuickstartFieldSpec("rubric_yaml", "Rubric YAML (rules and point weights)", "path"),
    QuickstartFieldSpec("grades_template_csv", "Brightspace grades template CSV (exported from course)", "path"),
    QuickstartFieldSpec("grade_column", "Grade column header (exact name in CSV)", "column"),
    QuickstartFieldSpec("output_dir", "Output directory", "path"),
    QuickstartFieldSpec("host", "Review host", "text"),
    QuickstartFieldSpec("port", "Review port", "int"),
)

OPTIONAL_GRADE_RENDER_ORDER: tuple[str, ...] = (
    "temp_dir",
    "cache_dir",
    "grading_mode",
    "provider",
    "model",
    "locator_model",
    "api_key_env",
    "identifier_column",
    "comment_column",
    "ocr_char_threshold",
    "student_filter",
    "dry_run",
    "annotate_dry_run_marks",
    "check_plus_points",
    "check_points",
    "check_minus_points",
    "review_required_points",
    "context_cache",
    "context_cache_ttl_seconds",
    "plain",
    "diagnostics_file",
    "annotation_font_size",
    "force_vision_extraction",
)

_OPTIONAL_PATH_FIELDS = {"temp_dir", "cache_dir", "diagnostics_file"}
_OPTIONAL_INT_FIELDS = {"ocr_char_threshold", "context_cache_ttl_seconds"}
_OPTIONAL_FLOAT_FIELDS = {"annotation_font_size"}
_OPTIONAL_BOOL_FIELDS = {"dry_run", "annotate_dry_run_marks", "context_cache", "extract_blocks", "plain", "force_vision_extraction"}
_OPTIONAL_STRING_FIELDS = {
    "grading_mode",
    "provider",
    "model",
    "locator_model",
    "api_key_env",
    "identifier_column",
    "comment_column",
    "student_filter",
}
_OPTIONAL_POINTS_FIELDS = {
    "check_plus_points",
    "check_points",
    "check_minus_points",
    "review_required_points",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Workflow CLI for profile-based grading runs.")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser(
        "run",
        help="Run grading + review init + review server from a workflow profile.",
    )
    run_parser.add_argument("--profile", required=True)
    run_parser.add_argument("--host", default=None)
    run_parser.add_argument("--port", type=int, default=None)

    serve_parser = subparsers.add_parser(
        "serve",
        help="Start review server from an existing profile output directory.",
    )
    serve_parser.add_argument("--profile", required=True)
    serve_parser.add_argument("--host", default=None)
    serve_parser.add_argument("--port", type=int, default=None)

    setup_parser = subparsers.add_parser(
        "setup",
        help="Interactive profile setup wizard (with optional rubric starter generation).",
    )
    setup_parser.add_argument("--profile", required=True)
    setup_parser.add_argument("--overwrite", action="store_true")
    setup_parser.add_argument(
        "--non-interactive",
        "--yes",
        "-y",
        action="store_true",
        dest="non_interactive",
        help="Bypass interactive prompts and use default configuration values.",
    )

    quickstart_parser = subparsers.add_parser(
        "quickstart",
        help="Interactive quickstart with smart defaults from prior runs and local discovery.",
    )
    quickstart_parser.add_argument("--profile", required=True)
    quickstart_parser.add_argument("--no-run", action="store_true")
    quickstart_parser.add_argument("--overwrite", action="store_true")
    quickstart_parser.add_argument("--force", action="store_true", help="Alias for --overwrite")
    quickstart_parser.add_argument(
        "--non-interactive",
        "--yes",
        "-y",
        action="store_true",
        dest="non_interactive",
        help="Bypass interactive prompts and use detected/default configuration values.",
    )

    import_parser = subparsers.add_parser(
        "import",
        help="Import Brightspace assignment assets into data/{profile}/.",
    )
    import_parser.add_argument("--profile", required=True)
    import_parser.add_argument(
        "--downloads-dir",
        type=Path,
        default=None,
        help="Override the default Downloads directory (defaults to ~/Downloads).",
    )
    import_parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Override the data directory root (defaults to ./data).",
    )
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be imported without copying or moving any files.",
    )
    import_parser.add_argument(
        "--move",
        action="store_true",
        help="Move files out of the Downloads directory instead of copying them (saves disk space).",
    )

    subparsers.add_parser("list", help="List local workflow profiles.")
    set_model_parser = subparsers.add_parser(
        "set-default-model",
        help="Set project default GenAI model (writes configs/defaults.toml)",
    )
    set_model_parser.add_argument("model", help="Model string (e.g., gemma4-31b-it)")

    regrade_parser = subparsers.add_parser(
        "regrade",
        help="Clear cached results and annotated outputs, then re-run grading from scratch.",
    )
    regrade_parser.add_argument("--profile", required=True)
    regrade_parser.add_argument("--question", type=str, default=None, help="Regrade a specific question only.")
    regrade_parser.add_argument("--student-filter", default="", help="Regex to regrade specific students only.")
    regrade_parser.add_argument("--host", default=None)
    regrade_parser.add_argument("--port", type=int, default=None)
    regrade_parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Delete all rows from the grading_cache and context_cache tables in cache.db before starting the run.",
    )

    judge_parser = subparsers.add_parser(
        "judge",
        help="Run Judge LLM over grading audit data to propose grading fixes.",
    )
    judge_parser.add_argument("--profile", required=False, help="Workflow profile to judge")

    spot_grade_parser = subparsers.add_parser(
        "spot-grade",
        help="Grade a single PDF submission directly (no Brightspace CSV required).",
    )
    spot_grade_parser.add_argument("--pdf", type=Path, help="Path to the student's PDF submission.")
    spot_grade_parser.add_argument("--profile", help="Workflow profile to use for rubric and answer key.")
    spot_grade_parser.add_argument("--student-name", help="Name of the student.")

    delete_parser = subparsers.add_parser(
        "delete",
        help="Delete a profile and its associated rubric and outputs.",
    )
    delete_parser.add_argument("--profile", help="Profile to delete.")

    subparsers.add_parser(
        "configure-api-key",
        help="Configure the GenAI API key used via .env across profiles.",
    )

    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume an interrupted grading run from a checkpoint.",
    )
    resume_parser.add_argument("--profile", required=True)
    resume_parser.add_argument("--host", default=None)
    resume_parser.add_argument("--port", type=int, default=None)

    clear_run_parser = subparsers.add_parser(
        "clear-run",
        help="Clear partial grading run checkpoint and associated outputs.",
    )
    clear_run_parser.add_argument("--profile", required=True)

    return parser


_MENU_COMMANDS: list[tuple[str, str]] = [
    ("grade-new", "Grade new assignment"),
    ("import", "Import assignment assets (from Downloads)"),
    ("quickstart", "Auto-detect settings, grade, and review"),
    ("run", "Grade submissions and launch review server"),
    ("resume", "Resume an interrupted grading run"),
    ("clear-run", "Clear partial run (checkpoint + outputs)"),
    ("spot-grade", "Grade a single late submission PDF (no Brightspace ID required)"),
    ("regrade", "Clear cache and re-run grading from scratch"),
    ("serve", "Launch review server for existing results"),
    ("setup", "Interactive profile setup wizard"),
    ("delete", "Delete an assignment (profile, rubric, outputs)"),
    ("set-default-model", "Switch grading model"),
    ("configure-api-key", "Set or change GenAI API key (.env)"),
    ("list", "List local workflow profiles"),
    ("exit", "Exit"),
]

_COMMANDS_NEEDING_PROFILE = {"import", "quickstart", "run", "resume", "clear-run", "serve", "setup", "spot-grade"}
_COMMANDS_WITH_REVIEW_SERVER = {"run", "serve", "regrade", "resume"}


def interactive_command_menu() -> str | None:
    """Show an arrow-key menu and return the chosen command name, or None if cancelled."""
    styled_banner("Gradeline", "Gradeline workflow CLI")
    choices = [f"{name}  —  {desc}" for name, desc in _MENU_COMMANDS]
    idx = prompt_select(
            "Choose a command",
            choices,
            default=0,
            instruction="Type to filter, ↑/↓ to move, Enter to select, Ctrl+Z to exit",
        )
    if idx is None:
        return None
    cmd = _MENU_COMMANDS[idx][0]
    return None if cmd == "exit" else cmd


def prompt_profile_interactive() -> str | None:
    """Prompt the user to pick or type a profile name. Returns None if user selects Back."""
    paths = list_profile_paths()
    if paths:
        names = ["← Back to commands"] + [p.stem for p in paths] + ["Enter name manually"]
        idx = prompt_select(
            "Profile",
            names,
            default=1,
            instruction="Type to filter, ↑/↓ to move, Enter to select, Ctrl+Z to go back",
        )
        if idx is None or idx == 0:
            return None
        if 1 <= idx <= len(paths):
            return paths[idx - 1].stem
        if idx == len(paths) + 1:
            return prompt_text("Profile name", required=True)
    return prompt_text("Profile name", required=True)


def resume_from_profile(*, profile_spec: str, host_override: str | None, port_override: int | None) -> int:
    profile = load_workflow_profile(profile_spec, cwd=get_project_root())
    
    # Check if checkpoint exists before running
    from .checkpoint import get_checkpoint_path
    checkpoint_file = get_checkpoint_path(profile.grade.output_dir)
    if not checkpoint_file.exists():
        styled_error(f"No checkpoint file found at {checkpoint_file} for profile '{profile_spec}'.")
        return 2

    grading_argv = build_grading_argv(profile.grade)
    grading_argv.append("--resume")

    exit_code = invoke_grading_main(grading_argv)
    if exit_code in (1, 2):
        return exit_code

    state_path = initialize_review_state(output_dir=profile.grade.output_dir, rubric_yaml=None)
    status, reason = review_state_status(profile.grade.output_dir)
    if status != "valid":
        raise ValueError(f"Review state invalid at {state_path}: {reason}")

    host = resolve_host(profile=profile, host_override=host_override)
    requested_port = resolve_requested_port(profile=profile, port_override=port_override)
    port, shifted = resolve_available_port(host=host, preferred_port=requested_port)

    styled_section_heading("Review Server")
    styled_info(f"Profile: {profile.name}")
    styled_info(f"Output dir: {profile.grade.output_dir}")
    if shifted:
        styled_warning(f"Port {requested_port} is busy. Using {port}.")
    styled_url("Review URL", f"http://{host}:{port}")
    run_review_server(output_dir=profile.grade.output_dir, host=host, port=port)
    return 0


def clear_run_from_profile(*, profile_spec: str) -> int:
    profile = load_workflow_profile(profile_spec, cwd=get_project_root())
    output_dir = profile.grade.output_dir
    
    from .checkpoint import get_checkpoint_path, clear_checkpoint
    checkpoint_file = get_checkpoint_path(output_dir)
    
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
        clear_checkpoint(output_dir)
        removed_count += 1
        styled_info("Cleared checkpoint file.")
        
    if output_dir.is_dir():
        import shutil
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    interactive_session = args.command is None and is_interactive_terminal()

    while True:
        command = args.command
        if command is None:
            if not is_interactive_terminal():
                build_parser().print_help()
                return 2
            while True:
                command = interactive_command_menu()
                if command is None:
                    return 0
                if command not in _COMMANDS_NEEDING_PROFILE:
                    break
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    continue
                setattr(args, "profile", profile)
                break

        try:
            if command == "run":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    return 0
                exit_code = run_with_optional_setup(
                    profile_spec=profile,
                    host_override=getattr(args, "host", None),
                    port_override=getattr(args, "port", None),
                )
            elif command == "resume":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    return 0
                exit_code = resume_from_profile(
                    profile_spec=profile,
                    host_override=getattr(args, "host", None),
                    port_override=getattr(args, "port", None),
                )
            elif command == "clear-run":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    return 0
                exit_code = clear_run_from_profile(
                    profile_spec=profile,
                )
            elif command == "grade-new":
                if not is_interactive_terminal():
                    styled_error("The 'Grade new assignment' flow is only available in interactive mode.")
                    return 2

                project_root = get_project_root()
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
                            raise AbortToMenu
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
                    exit_code = run_with_optional_setup(
                        profile_spec=profile,
                        host_override=getattr(args, "host", None),
                        port_override=getattr(args, "port", None),
                    )
            elif command == "import":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    return 0
                exit_code = import_assignment_assets(
                    profile_spec=profile,
                    downloads_dir=getattr(args, "downloads_dir", None),
                    data_root=getattr(args, "data_root", None),
                    dry_run=bool(getattr(args, "dry_run", False)),
                    move=bool(getattr(args, "move", False)),
                )
            elif command == "serve":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    return 0
                exit_code = serve_with_optional_setup(
                    profile_spec=profile,
                    host_override=getattr(args, "host", None),
                    port_override=getattr(args, "port", None),
                )
            elif command == "setup":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    return 0
                exit_code = setup_profile_interactive(
                    profile_spec=profile,
                    overwrite=getattr(args, "overwrite", False),
                    non_interactive=getattr(args, "non_interactive", False),
                )
            elif command == "quickstart":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    return 0
                exit_code = quickstart_profile_interactive(
                    profile_spec=profile,
                    overwrite=bool(getattr(args, "overwrite", False) or getattr(args, "force", False)),
                    auto_run=not bool(getattr(args, "no_run", False)),
                    non_interactive=getattr(args, "non_interactive", False),
                )
            elif command == "list":
                exit_code = list_profiles()
            elif command == "set-default-model":
                model_name = getattr(args, "model", None)
                if not model_name:
                    exit_code = set_default_model_interactive()
                else:
                    try:
                        set_default_model(model_name)
                        styled_success(f"Default model → {model_name}")
                        exit_code = 0
                    except Exception as exc:
                        styled_error(f"Failed to set default model: {exc}")
                        return 2
            elif command == "delete":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    continue
                exit_code = delete_assignment_interactive(profile_spec=profile)
            elif command == "configure-api-key":
                exit_code = configure_api_key_interactive()
            elif command == "spot-grade":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    return 0
                exit_code = spot_grade_interactive(
                    profile_spec=profile,
                    pdf_path=getattr(args, "pdf", None),
                    student_name=getattr(args, "student_name", None),
                )
            elif command == "regrade":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    return 0
                exit_code = regrade_from_profile(
                    profile_spec=profile,
                    question=getattr(args, "question", None),
                    student_filter=getattr(args, "student_filter", ""),
                    host_override=getattr(args, "host", None),
                    port_override=getattr(args, "port", None),
                    clear_cache=getattr(args, "clear_cache", False),
                )
            elif command == "judge":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    return 0
                
                from .judge import run_judge
                exit_code = run_judge(profile_spec=profile)
            else:
                styled_error("Unknown command.")
                return 2
        except (AbortToMenu, KeyboardInterrupt):
            if interactive_session:
                styled_info("Returning to main menu.")
                args.command = None
                continue
            return 2
        except WorkflowProfileError as exc:
            styled_error(str(exc))
            return 2
        except ReviewInitError as exc:
            styled_error(f"Review init failed: {exc}")
            return 2
        except ValueError as exc:
            styled_error(str(exc))
            return 2

        if interactive_session and (command in _COMMANDS_WITH_REVIEW_SERVER or command == "configure-api-key"):
            styled_info("Returning to main menu.")
            args.command = None
            continue
        return exit_code


def run_from_profile(*, profile_spec: str, host_override: str | None, port_override: int | None) -> int:
    profile = load_workflow_profile(profile_spec, cwd=get_project_root())
    grading_argv = build_grading_argv(profile.grade)

    exit_code = invoke_grading_main(grading_argv)
    if exit_code in (1, 2):
        return exit_code

    state_path = initialize_review_state(output_dir=profile.grade.output_dir, rubric_yaml=None)
    status, reason = review_state_status(profile.grade.output_dir)
    if status != "valid":
        raise ValueError(f"Review state invalid at {state_path}: {reason}")

    host = resolve_host(profile=profile, host_override=host_override)
    requested_port = resolve_requested_port(profile=profile, port_override=port_override)
    port, shifted = resolve_available_port(host=host, preferred_port=requested_port)

    styled_section_heading("Review Server")
    styled_info(f"Profile: {profile.name}")
    styled_info(f"Output dir: {profile.grade.output_dir}")
    if shifted:
        styled_warning(f"Port {requested_port} is busy. Using {port}.")
    styled_url("Review URL", f"http://{host}:{port}")
    run_review_server(output_dir=profile.grade.output_dir, host=host, port=port)
    return 0


def regrade_from_profile(
    *,
    profile_spec: str,
    question: str | None = None,
    student_filter: str = "",
    host_override: str | None,
    port_override: int | None,
    clear_cache: bool = False,
) -> int:
    """Clear cached results and output artifacts, then re-run grading."""
    profile = load_workflow_profile(profile_spec, cwd=get_project_root())
    output_dir = profile.grade.output_dir
    cache_dir = profile.grade.cache_dir or Path(".grader_cache")
    if not cache_dir.is_absolute():
        cache_dir = get_project_root() / cache_dir

    # Compile optional student filter
    pattern: re.Pattern[str] | None = None
    if student_filter.strip():
        pattern = re.compile(student_filter, flags=re.IGNORECASE)

    styled_section_heading("Regrade")

    # --- Clear local results cache ---
    cache_file = cache_dir / "cache.db"
    if clear_cache:
        if cache_file.exists():
            _clear_db_caches(cache_file)
            styled_info("Deleted all rows from grading_cache and context_cache tables in cache.db.")
    elif question is None:
        if cache_file.exists():
            if pattern is None:
                cache_file.unlink()
                styled_info("Cleared entire results cache.")
            else:
                _purge_cache_entries(cache_file, pattern)

        # --- Remove annotated output folders ---
        removed = 0
        if output_dir.is_dir():
            for child in sorted(output_dir.iterdir()):
                if not child.is_dir():
                    continue
                if pattern is not None and not pattern.search(child.name):
                    continue
                shutil.rmtree(child)
                removed += 1
        styled_info(f"Removed {removed} output folder(s).")

        # --- Remove report artifacts (only on full regrade) ---
        if pattern is None:
            for artifact in (
                "grading_audit.csv",
                "review_queue.csv",
                "brightspace_grades_import.csv",
                "grading_diagnostics.json",
                "index_audit.csv",
            ):
                artifact_path = output_dir / artifact
                if artifact_path.exists():
                    artifact_path.unlink()
            review_dir = output_dir / "review"
            if review_dir.is_dir():
                shutil.rmtree(review_dir)
            styled_info("Cleared report artifacts and review state.")
    else:
        styled_info(f"Performing per-question regrade for question: {question}")


    # --- Re-run grading ---
    grading_argv = build_grading_argv(profile.grade)
    if student_filter.strip():
        grading_argv.extend(["--student-filter", student_filter])
    if question is not None:
        grading_argv.extend(["--regrade-question", question])

    exit_code = invoke_grading_main(grading_argv)

    if exit_code in (1, 2):
        return exit_code

    # --- Launch review server ---
    state_path = initialize_review_state(output_dir=output_dir, rubric_yaml=None)
    status, reason = review_state_status(output_dir)
    if status != "valid":
        raise ValueError(f"Review state invalid at {state_path}: {reason}")

    host = resolve_host(profile=profile, host_override=host_override)
    requested_port = resolve_requested_port(profile=profile, port_override=port_override)
    port, shifted = resolve_available_port(host=host, preferred_port=requested_port)

    styled_section_heading("Review Server")
    styled_info(f"Profile: {profile.name}")
    styled_info(f"Output dir: {output_dir}")
    if shifted:
        styled_warning(f"Port {requested_port} is busy. Using {port}.")
    styled_url("Review URL", f"http://{host}:{port}")
    run_review_server(output_dir=output_dir, host=host, port=port)
    return 0


def _purge_cache_entries(cache_file: Path, pattern: re.Pattern[str]) -> None:
    """Remove cache entries whose keys match the student filter pattern."""
    import sqlite3
    try:
        with sqlite3.connect(cache_file) as conn:
            cur = conn.execute("SELECT hash_key, payload FROM grading_cache")
            rows = cur.fetchall()
            
            to_remove = []
            for row in rows:
                key, payload_text = row
                if pattern.search(key) or pattern.search(payload_text):
                    to_remove.append(key)
            
            for key in to_remove:
                conn.execute("DELETE FROM grading_cache WHERE hash_key = ?", (key,))
            conn.commit()
            styled_info(f"Purged {len(to_remove)} of {len(rows)} cache entries matching filter.")
    except Exception as exc:
        styled_info(f"Could not purge cache entries: {exc}")


def _clear_db_caches(cache_file: Path) -> None:
    """Delete all rows from grading_cache and context_cache tables in cache.db."""
    import sqlite3
    try:
        with sqlite3.connect(cache_file) as conn:
            conn.execute("DELETE FROM grading_cache")
            conn.execute("DELETE FROM context_cache")
            conn.commit()
    except Exception as exc:
        styled_info(f"Could not clear cache tables: {exc}")


def spot_grade_interactive(*, profile_spec: str, pdf_path: Path | None, student_name: str | None) -> int:
    import time

    profile = load_workflow_profile(profile_spec, cwd=get_project_root())

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

    argv = build_grading_argv(profile.grade)
    for i, val in enumerate(argv):
        if val == "--submissions-dir":
            argv[i + 1] = str(subs_dir)
        elif val == "--grades-template-csv":
            argv[i + 1] = str(dummy_csv)
        elif val == "--output-dir":
            argv[i + 1] = str(output_dir)

    exit_code = invoke_grading_main(argv)
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

    # Show a quick summary line from the grading audit, if present.
    audit_csv = output_dir / "grading_audit.csv"
    if audit_csv.exists():
        rows, _ = read_csv_rows(audit_csv)
        if rows:
            first = rows[0]
            styled_info(f"Grade: {first.get('band')} ({first.get('percent')}%)")

    # Copy key artifacts alongside the graded PDF for easy inspection.
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







def run_with_optional_setup(*, profile_spec: str, host_override: str | None, port_override: int | None) -> int:
    try:
        return run_from_profile(profile_spec=profile_spec, host_override=host_override, port_override=port_override)
    except WorkflowProfileError as exc:
        if not is_profile_not_found_error(exc) or not is_interactive_terminal():
            raise
        styled_warning(str(exc))
        bootstrap_code = bootstrap_missing_profile(profile_spec=profile_spec)
        if bootstrap_code != 0:
            return bootstrap_code
        return run_from_profile(profile_spec=profile_spec, host_override=host_override, port_override=port_override)


def serve_from_profile(*, profile_spec: str, host_override: str | None, port_override: int | None) -> int:
    profile = load_workflow_profile(profile_spec)
    status, reason = review_state_status(profile.grade.output_dir)
    if status != "valid":
        state_path = state_path_for_output(profile.grade.output_dir)
        raise ValueError(f"Review state invalid at {state_path}: {reason}")

    host = resolve_host(profile=profile, host_override=host_override)
    requested_port = resolve_requested_port(profile=profile, port_override=port_override)
    port, shifted = resolve_available_port(host=host, preferred_port=requested_port)

    styled_section_heading("Review Server")
    styled_info(f"Profile: {profile.name}")
    styled_info(f"Output dir: {profile.grade.output_dir}")
    if shifted:
        styled_warning(f"Port {requested_port} is busy. Using {port}.")
    styled_url("Review URL", f"http://{host}:{port}")
    run_review_server(output_dir=profile.grade.output_dir, host=host, port=port)
    return 0


def serve_with_optional_setup(*, profile_spec: str, host_override: str | None, port_override: int | None) -> int:
    try:
        return serve_from_profile(profile_spec=profile_spec, host_override=host_override, port_override=port_override)
    except WorkflowProfileError as exc:
        if not is_profile_not_found_error(exc) or not is_interactive_terminal():
            raise
        styled_warning(str(exc))
        bootstrap_code = bootstrap_missing_profile(profile_spec=profile_spec)
        if bootstrap_code != 0:
            return bootstrap_code
        return serve_from_profile(profile_spec=profile_spec, host_override=host_override, port_override=port_override)


def bootstrap_missing_profile(*, profile_spec: str) -> int:
    choice = prompt_missing_profile_bootstrap_choice()
    if choice == "abort":
        raise AbortToMenu
    if choice == "setup":
        return setup_profile_interactive(profile_spec=profile_spec, overwrite=False)

    quickstart_code = quickstart_profile_interactive(
        profile_spec=profile_spec,
        overwrite=False,
        auto_run=False,
    )
    if quickstart_code == 0:
        return 0

    if not prompt_yes_no("Quickstart did not complete. Try guided setup instead?", default=True):
        raise AbortToMenu
    return setup_profile_interactive(profile_spec=profile_spec, overwrite=False)


def prompt_missing_profile_bootstrap_choice() -> str:
    choices = ["quickstart (recommended)", "setup", "abort"]
    idx = prompt_select("Create missing profile with", choices, default=0)
    if idx is None:
        return "abort"
    return ["quickstart", "setup", "abort"][idx]


















_CURATED_MODELS: list[tuple[str, str]] = [
    ("gemini-2.5-flash",      "Recommended — fast, accurate, best value"),
    ("gemini-2.5-pro",        "Most capable, slower"),
    ("gemini-2.5-flash-lite", "Fastest, cheapest, less thorough"),
    ("gemini-2.0-flash",      "Previous gen, solid and fast"),
    ("gemma-4-31b-it",        "Open model"),
    ("gemini-3-pro-preview",  "Newest, cutting edge"),
    ("gemini-3-flash-preview","Newest flash tier"),
]



























def build_grading_argv(profile: GradeProfile) -> list[str]:
    argv: list[str] = []
    for mapping in CLI_VALUE_MAPPINGS:
        raw = getattr(profile, mapping.field)
        if raw is None:
            continue
        rendered = serialize_value(raw, mapping.value_type)
        if (not mapping.emit_if_empty) and rendered == "":
            continue
        argv.extend([mapping.flag, rendered])

    argv.append("--context-cache" if profile.context_cache else "--no-context-cache")
    argv.append("--extract-blocks" if profile.extract_blocks else "--no-extract-blocks")

    for field, flag in CLI_FLAG_MAPPINGS:
        if bool(getattr(profile, field)):
            argv.append(flag)
    return argv


















def invoke_grading_main(argv: list[str]) -> int:
    # Lazy import to keep workflow listing/profile validation available without grading deps.
    from .cli import main as grading_main

    return grading_main(argv)


def serialize_value(value: Any, value_type: str) -> str:
    if value_type == "path":
        if not isinstance(value, Path):
            raise ValueError(f"Expected Path, got {type(value).__name__}")
        return str(value)
    if value_type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"Expected int, got {type(value).__name__}")
        return str(value)
    if value_type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Expected float, got {type(value).__name__}")
        return str(float(value))
    if value_type == "str":
        if not isinstance(value, str):
            raise ValueError(f"Expected str, got {type(value).__name__}")
        return value
    raise ValueError(f"Unsupported value type '{value_type}'")


def resolve_host(*, profile: WorkflowProfile, host_override: str | None) -> str:
    host = host_override if host_override is not None else profile.review.host
    host_value = str(host).strip()
    if not host_value:
        raise ValueError("Host must be non-empty.")
    return host_value


def resolve_requested_port(*, profile: WorkflowProfile, port_override: int | None) -> int:
    port = port_override if port_override is not None else profile.review.port
    if port <= 0 or port > 65535:
        raise ValueError(f"Port must be 1..65535, got {port}.")
    return port


def resolve_available_port(*, host: str, preferred_port: int, max_attempts: int = 25) -> tuple[int, bool]:
    for offset in range(max_attempts):
        candidate = preferred_port + offset
        if candidate > 65535:
            break
        if can_bind_port(host=host, port=candidate):
            return candidate, offset > 0
    raise ValueError(f"No available port found for host {host} in range {preferred_port}-{preferred_port + max_attempts - 1}.")


def can_bind_port(*, host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def review_state_status(output_dir: Path) -> tuple[str, str]:
    path = state_path_for_output(output_dir)
    if not path.exists() or not path.is_file():
        return "missing", "review_state.json not found"

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return "invalid", f"failed to read JSON ({exc})"

    if not isinstance(payload, dict):
        return "invalid", "top-level payload is not a JSON object"

    missing = sorted(REQUIRED_STATE_KEYS - set(payload))
    if missing:
        return "invalid", f"missing keys {missing}"

    return "valid", ""


if __name__ == "__main__":
    raise SystemExit(main())

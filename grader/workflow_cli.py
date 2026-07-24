from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .checkpoint import clear_checkpoint, get_checkpoint_path
from .config import load_rubric
from .defaults import resolve_model, set_default_model
from .env import update_env_file
from .gemini_client import GeminiGrader
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
from .report import read_csv_rows, resolve_column_name
from .review.importer import ReviewInitError, initialize_review_state
from .review.server import run_review_server
from .review.state import state_path_for_output

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

from .workflow.cli_utils import (
    CLI_FLAG_MAPPINGS,
    CLI_VALUE_MAPPINGS,
    OPTIONAL_GRADE_RENDER_ORDER,
    QUICKSTART_FIELDS,
    REQUIRED_STATE_KEYS,
    AbortToMenu,
    CliValueMapping,
    QuickstartFieldSpec,
    _OPTIONAL_BOOL_FIELDS,
    _OPTIONAL_FLOAT_FIELDS,
    _OPTIONAL_INT_FIELDS,
    _OPTIONAL_PATH_FIELDS,
    _OPTIONAL_POINTS_FIELDS,
    _OPTIONAL_STRING_FIELDS,
    build_grading_argv,
    can_bind_port,
    get_project_root,
    invoke_grading_main,
    resolve_available_port,
    resolve_host,
    resolve_requested_port,
    review_state_status,
    serialize_value,
)
from .workflow.commands import (
    _clear_db_caches,
    _purge_cache_entries,
    bootstrap_missing_profile,
    clear_run_from_profile,
    grade_new_interactive,
    prompt_missing_profile_bootstrap_choice,
    regrade_from_profile,
    resume_from_profile,
    run_from_profile,
    run_with_optional_setup,
    serve_from_profile,
    serve_with_optional_setup,
    spot_grade_interactive,
)
from .workflow.import_cmd import import_assignment_assets
from .workflow.profile_utils import (
    configure_api_key_interactive,
    delete_assignment_interactive,
    is_interactive_terminal,
    is_profile_not_found_error,
    list_profiles,
    set_default_model_interactive,
    setup_profile_interactive,
)
from .workflow.quickstart import quickstart_profile_interactive


_MENU_COMMANDS: list[tuple[str, str]] = [
    ("run", "Run grading + review init + review server"),
    ("serve", "Start review server from output directory"),
    ("regrade", "Clear cached results and annotated outputs, then re-run grading"),
    ("spot-grade", "Grade a single PDF submission directly (no Brightspace CSV required)"),
    ("grade-new", "Interactive wizard to configure and run a new assignment"),
    ("import", "Import Brightspace assignment assets into data/{profile}/"),
    ("quickstart", "Interactive quickstart with smart defaults"),
    ("setup", "Guided setup wizard"),
    ("resume", "Resume an interrupted grading run from a checkpoint"),
    ("clear-run", "Clear partial grading run checkpoint and output directory"),
    ("judge", "Run Judge LLM to propose grading fixes"),
    ("audit-pdf", "Zero-token visual annotation health check"),
    ("delete", "Delete profile, rubric, and outputs"),
    ("configure-api-key", "Configure API key in .env"),
    ("set-default-model", "Set project default GenAI model"),
    ("list", "List local workflow profiles"),
    ("exit", "Exit"),
]

_COMMANDS_NEEDING_PROFILE = {"import", "quickstart", "run", "resume", "clear-run", "serve", "setup", "spot-grade"}
_COMMANDS_WITH_REVIEW_SERVER = {"run", "serve", "regrade", "resume"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Workflow CLI for profile-based grading runs.")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser(
        "run",
        help="Run grading + review init + review server from a workflow profile.",
    )
    run_parser.add_argument("--profile", required=False, help="Profile name or file path (e.g. a2 or configs/a2.toml)")
    run_parser.add_argument("--host", default=None, help="Override review server bind host")
    run_parser.add_argument("--port", type=int, default=None, help="Override review server bind port")

    serve_parser = subparsers.add_parser(
        "serve",
        help="Start review server from an existing profile output directory.",
    )
    serve_parser.add_argument("--profile", required=False, help="Profile name or file path")
    serve_parser.add_argument("--host", default=None, help="Override review server bind host")
    serve_parser.add_argument("--port", type=int, default=None, help="Override review server bind port")

    setup_parser = subparsers.add_parser(
        "setup",
        help="Interactive profile setup wizard (with optional rubric starter generation).",
    )
    setup_parser.add_argument("--profile", required=False, help="Profile name or file path")
    setup_parser.add_argument("--overwrite", action="store_true", help="Overwrite profile TOML if it exists")
    setup_parser.add_argument("--non-interactive", action="store_true", help="Disable interactive prompts; use auto defaults")

    quickstart_parser = subparsers.add_parser(
        "quickstart",
        help="Interactive quickstart with smart defaults from prior runs and local discovery.",
    )
    quickstart_parser.add_argument("--profile", required=False, help="Profile name or file path")
    quickstart_parser.add_argument("--overwrite", action="store_true", help="Overwrite profile TOML if it exists")
    quickstart_parser.add_argument("--force", action="store_true", help="Alias for --overwrite")
    quickstart_parser.add_argument("--no-run", action="store_true", help="Save profile without starting grading immediately")
    quickstart_parser.add_argument("--non-interactive", action="store_true", help="Accept detected defaults without interactive prompts")

    import_parser = subparsers.add_parser(
        "import",
        help="Import Brightspace assignment assets into data/{profile}/.",
    )
    import_parser.add_argument("--profile", required=False, help="Profile name or file path")
    import_parser.add_argument("--downloads-dir", default=None, help="Directory containing downloaded Brightspace zip/files")
    import_parser.add_argument("--data-root", default=None, help="Root destination directory (defaults to data/)")
    import_parser.add_argument("--dry-run", action="store_true", help="Preview asset movements without executing")
    import_parser.add_argument("--move", action="store_true", help="Move assets instead of copying")

    subparsers.add_parser("list", help="List local workflow profiles.")

    model_parser = subparsers.add_parser(
        "set-default-model",
        help="Set project default GenAI model (writes configs/defaults.toml)",
    )
    model_parser.add_argument("--model", required=False, help="Model name (e.g. gemini-2.5-flash)")

    regrade_parser = subparsers.add_parser(
        "regrade",
        help="Clear cached results and annotated outputs, then re-run grading from scratch.",
    )
    regrade_parser.add_argument("--profile", required=False, help="Profile name or file path")
    regrade_parser.add_argument("--question", required=False, default=None, help="Only regrade a specific question ID (e.g., 1a)")
    regrade_parser.add_argument("--student-filter", default="", help="Regex filter to target specific student filenames")
    regrade_parser.add_argument("--host", default=None, help="Override review server bind host")
    regrade_parser.add_argument("--port", type=int, default=None, help="Override review server bind port")
    regrade_parser.add_argument("--clear-cache", action="store_true", help="Delete all cached LLM responses from SQLite cache.db before regrading")
    regrade_parser.add_argument("--annotation-mode", type=str, default=None, choices=["answer_inline", "right_margin", "question_prompt", "header_summary_only"], help="PDF annotation layout mode: answer_inline, right_margin, question_prompt, header_summary_only.")

    judge_parser = subparsers.add_parser(
        "judge",
        help="Run Judge LLM over grading audit data to propose grading fixes.",
    )
    judge_parser.add_argument("--profile", required=False, help="Profile name or file path")

    spot_parser = subparsers.add_parser(
        "spot-grade",
        help="Grade a single PDF submission directly (no Brightspace CSV required).",
    )
    spot_parser.add_argument("--profile", required=False, help="Profile name or file path")
    spot_parser.add_argument("--pdf", type=Path, default=None, help="Path to PDF submission file")
    spot_parser.add_argument("--student-name", default=None, help="Student display name")

    delete_parser = subparsers.add_parser(
        "delete",
        help="Delete a profile and its associated rubric and outputs.",
    )
    delete_parser.add_argument("--profile", required=False, help="Profile name or file path")

    subparsers.add_parser(
        "configure-api-key",
        help="Configure the GenAI API key used via .env across profiles.",
    )

    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume an interrupted grading run from a checkpoint.",
    )
    resume_parser.add_argument("--profile", required=False, help="Profile name or file path")
    resume_parser.add_argument("--host", default=None, help="Override review server bind host")
    resume_parser.add_argument("--port", type=int, default=None, help="Override review server bind port")

    clear_parser = subparsers.add_parser(
        "clear-run",
        help="Clear partial grading run checkpoint and associated outputs.",
    )
    clear_parser.add_argument("--profile", required=False, help="Profile name or file path")

    audit_pdf_parser = subparsers.add_parser(
        "audit-pdf",
        help="Run zero-token visual annotation health check across output PDFs.",
    )
    audit_pdf_parser.add_argument("--output-dir", default="outputs", help="Output directory to audit")

    return parser


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
                exit_code = grade_new_interactive(args)
            elif command == "import":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    return 0
                raw_dl = getattr(args, "downloads_dir", None)
                raw_dr = getattr(args, "data_root", None)
                exit_code = import_assignment_assets(
                    profile_spec=profile,
                    downloads_dir=Path(raw_dl) if raw_dl else None,
                    data_root=Path(raw_dr) if raw_dr else None,
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
                    annotation_mode=getattr(args, "annotation_mode", None),
                )
            elif command == "judge":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    return 0

                from .judge import run_judge
                exit_code = run_judge(profile_spec=profile)
            elif command == "audit-pdf":
                out_path = Path(getattr(args, "output_dir", "outputs") or "outputs")
                from .workflow.audit_pdf import audit_pdf_outputs
                res = audit_pdf_outputs(out_path)
                exit_code = 1 if (res.get("oob_defects", 0) > 0 or res.get("overlap_defects", 0) > 0) else 0
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


if __name__ == "__main__":
    raise SystemExit(main())

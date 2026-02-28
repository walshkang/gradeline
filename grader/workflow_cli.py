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
from .workflow_detect import DetectedConfig, default_question_ids, detect_defaults
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


REQUIRED_STATE_KEYS = {"schema_version", "run_metadata", "grading_context", "submissions"}


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
    CliValueMapping("model", "--model", "str"),
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
)

CLI_FLAG_MAPPINGS: tuple[tuple[str, str], ...] = (
    ("dry_run", "--dry-run"),
    ("annotate_dry_run_marks", "--annotate-dry-run-marks"),
    ("plain", "--plain"),
)

QUICKSTART_FIELDS: tuple[QuickstartFieldSpec, ...] = (
    QuickstartFieldSpec("submissions_dir", "Submissions directory", "path"),
    QuickstartFieldSpec("solutions_pdf", "Solutions PDF", "path"),
    QuickstartFieldSpec("rubric_yaml", "Rubric YAML", "path"),
    QuickstartFieldSpec("grades_template_csv", "Grades template CSV", "path"),
    QuickstartFieldSpec("grade_column", "Grade column", "column"),
    QuickstartFieldSpec("output_dir", "Output directory", "path"),
    QuickstartFieldSpec("host", "Review host", "text"),
    QuickstartFieldSpec("port", "Review port", "int"),
)

OPTIONAL_GRADE_RENDER_ORDER: tuple[str, ...] = (
    "temp_dir",
    "cache_dir",
    "grading_mode",
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
)

_OPTIONAL_PATH_FIELDS = {"temp_dir", "cache_dir", "diagnostics_file"}
_OPTIONAL_INT_FIELDS = {"ocr_char_threshold", "context_cache_ttl_seconds"}
_OPTIONAL_BOOL_FIELDS = {"dry_run", "annotate_dry_run_marks", "context_cache", "plain"}
_OPTIONAL_STRING_FIELDS = {
    "grading_mode",
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

    quickstart_parser = subparsers.add_parser(
        "quickstart",
        help="Interactive quickstart with smart defaults from prior runs and local discovery.",
    )
    quickstart_parser.add_argument("--profile", required=True)
    quickstart_parser.add_argument("--no-run", action="store_true")
    quickstart_parser.add_argument("--overwrite", action="store_true")
    quickstart_parser.add_argument("--force", action="store_true", help="Alias for --overwrite")

    subparsers.add_parser("list", help="List local workflow profiles.")

    regrade_parser = subparsers.add_parser(
        "regrade",
        help="Clear cached results and annotated outputs, then re-run grading from scratch.",
    )
    regrade_parser.add_argument("--profile", required=True)
    regrade_parser.add_argument("--student-filter", default="", help="Regex to regrade specific students only.")
    regrade_parser.add_argument("--host", default=None)
    regrade_parser.add_argument("--port", type=int, default=None)

    return parser


_MENU_COMMANDS: list[tuple[str, str]] = [
    ("quickstart", "Auto-detect settings, grade, and review"),
    ("run", "Grade submissions and launch review server"),
    ("regrade", "Clear cache and re-run grading from scratch"),
    ("serve", "Launch review server for existing results"),
    ("setup", "Interactive profile setup wizard"),
    ("list", "List local workflow profiles"),
    ("exit", "Exit"),
]

_COMMANDS_NEEDING_PROFILE = {"quickstart", "run", "serve", "setup"}
_COMMANDS_WITH_REVIEW_SERVER = {"run", "serve", "regrade"}


def interactive_command_menu() -> str | None:
    """Show an arrow-key menu and return the chosen command name, or None if cancelled."""
    styled_banner("Gradeline", "SDA Grader workflow CLI")
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
                )
            elif command == "quickstart":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    return 0
                exit_code = quickstart_profile_interactive(
                    profile_spec=profile,
                    overwrite=bool(getattr(args, "overwrite", False) or getattr(args, "force", False)),
                    auto_run=not bool(getattr(args, "no_run", False)),
                )
            elif command == "list":
                exit_code = list_profiles()
            elif command == "regrade":
                profile = getattr(args, "profile", None) or prompt_profile_interactive()
                if profile is None:
                    return 0
                exit_code = regrade_from_profile(
                    profile_spec=profile,
                    student_filter=getattr(args, "student_filter", ""),
                    host_override=getattr(args, "host", None),
                    port_override=getattr(args, "port", None),
                )
            else:
                styled_error("Unknown command.")
                return 2
        except AbortToMenu:
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

        if interactive_session and command in _COMMANDS_WITH_REVIEW_SERVER:
            styled_info("Returning to main menu.")
            args.command = None
            continue
        return exit_code


def run_from_profile(*, profile_spec: str, host_override: str | None, port_override: int | None) -> int:
    profile = load_workflow_profile(profile_spec)
    grading_argv = build_grading_argv(profile.grade)

    exit_code = invoke_grading_main(grading_argv)
    if exit_code != 0:
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
    student_filter: str = "",
    host_override: str | None,
    port_override: int | None,
) -> int:
    """Clear cached results and output artifacts, then re-run grading."""
    profile = load_workflow_profile(profile_spec)
    output_dir = profile.grade.output_dir
    cache_dir = profile.grade.cache_dir or Path(".grader_cache")
    if not cache_dir.is_absolute():
        cache_dir = Path.cwd() / cache_dir

    # Compile optional student filter
    pattern: re.Pattern[str] | None = None
    if student_filter.strip():
        pattern = re.compile(student_filter, flags=re.IGNORECASE)

    styled_section_heading("Regrade")

    # --- Clear local results cache ---
    cache_file = cache_dir / "cache.db"
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

    # --- Re-run grading ---
    grading_argv = build_grading_argv(profile.grade)
    if student_filter.strip():
        grading_argv.extend(["--student-filter", student_filter])

    exit_code = invoke_grading_main(grading_argv)
    if exit_code != 0:
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


def quickstart_profile_interactive(*, profile_spec: str, overwrite: bool, auto_run: bool) -> int:
    if not is_interactive_terminal():
        styled_error("quickstart requires an interactive terminal (TTY).")
        return 2

    cwd = Path.cwd()
    profile_path = resolve_profile_path(profile_spec, cwd=cwd, profile_dir=DEFAULT_PROFILE_DIR)
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    if profile_path.exists() and not overwrite:
        if not prompt_yes_no(f"Profile already exists at {profile_path}. Overwrite?", default=False):
            styled_warning("Aborted.")
            raise AbortToMenu

    detected = detect_defaults(profile_spec=profile_spec, cwd=cwd)
    values, candidates, metadata = initialize_quickstart_state(detected)

    while True:
        render_quickstart_summary(values=values, metadata=metadata)
        raw = input("Enter to accept, field # to edit, q to abort: ").strip()
        if raw.lower() == "q":
            styled_warning("Aborted.")
            raise AbortToMenu
        if raw == "":
            errors = validate_quickstart_values(values)
            if errors:
                styled_warning("Fix required fields before continuing:")
                for error in errors:
                    styled_warning(f"  • {error}")
                continue
            break

        try:
            index = int(raw)
        except ValueError:
            styled_warning("Please enter a valid field number.")
            continue
        if index < 1 or index > len(QUICKSTART_FIELDS):
            styled_warning(f"Please choose 1..{len(QUICKSTART_FIELDS)}.")
            continue

        field = QUICKSTART_FIELDS[index - 1]
        edit_quickstart_field(field=field, values=values, candidates=candidates, metadata=metadata, cwd=cwd)

    rubric_path = values["rubric_yaml"]
    if not isinstance(rubric_path, Path):
        raise ValueError("Rubric path is required.")
    if not rubric_path.exists():
        if prompt_yes_no(f"Rubric not found at {rubric_path}. Create a starter rubric now?", default=True):
            assignment_id = prompt_text("Assignment ID", default=profile_path.stem, required=True)
            inferred = list(detected.prior_rubric_question_ids) or list(default_question_ids())
            default_qids = ",".join(inferred)
            question_ids_raw = prompt_text(
                "Question IDs (comma-separated, e.g. a,b,c,d)",
                default=default_qids,
                required=True,
            )
            question_ids = parse_question_ids(question_ids_raw)
            write_starter_rubric(rubric_path, assignment_id=assignment_id, question_ids=question_ids)
            styled_success(f"Created starter rubric: {rubric_path}")
            styled_info("Rubric checklist:")
            styled_info("  • Update scoring_rules per question.")
            styled_info("  • Confirm label_patterns and anchor_tokens match your answer key.")
            styled_info("  • Verify bands thresholds for your class policy.")

    profile_text = render_profile_toml(
        submissions_dir=must_path(values["submissions_dir"], "submissions_dir"),
        solutions_pdf=must_path(values["solutions_pdf"], "solutions_pdf"),
        rubric_yaml=rubric_path,
        grades_template_csv=must_path(values["grades_template_csv"], "grades_template_csv"),
        grade_column=must_text(values["grade_column"], "grade_column"),
        output_dir=must_path(values["output_dir"], "output_dir"),
        host=must_text(values["host"], "host"),
        port=must_port(values["port"]),
        optional_grade_values=detected.optional_grade_values,
    )
    profile_path.write_text(profile_text, encoding="utf-8")
    styled_success(f"Wrote profile: {profile_path}")

    if auto_run:
        return run_from_profile(profile_spec=profile_spec, host_override=None, port_override=None)

    styled_info(f"Next step: python3 -m grader.workflow_cli run --profile {profile_path.stem}")
    return 0


def initialize_quickstart_state(
    detected: DetectedConfig,
) -> tuple[dict[str, Any], dict[str, list[Any]], dict[str, tuple[str, float]]]:
    values: dict[str, Any] = {
        "submissions_dir": detected.submissions_dir.value,
        "solutions_pdf": detected.solutions_pdf.value,
        "rubric_yaml": detected.rubric_yaml.value,
        "grades_template_csv": detected.grades_template_csv.value,
        "grade_column": detected.grade_column.value,
        "output_dir": detected.output_dir.value,
        "host": detected.host.value,
        "port": detected.port.value,
    }
    candidates: dict[str, list[Any]] = {
        "submissions_dir": list(detected.submissions_dir.candidates),
        "solutions_pdf": list(detected.solutions_pdf.candidates),
        "rubric_yaml": list(detected.rubric_yaml.candidates),
        "grades_template_csv": list(detected.grades_template_csv.candidates),
        "grade_column": list(detected.grade_column.candidates),
        "output_dir": list(detected.output_dir.candidates),
        "host": list(detected.host.candidates),
        "port": list(detected.port.candidates),
    }
    metadata: dict[str, tuple[str, float]] = {
        "submissions_dir": (detected.submissions_dir.source, detected.submissions_dir.confidence),
        "solutions_pdf": (detected.solutions_pdf.source, detected.solutions_pdf.confidence),
        "rubric_yaml": (detected.rubric_yaml.source, detected.rubric_yaml.confidence),
        "grades_template_csv": (detected.grades_template_csv.source, detected.grades_template_csv.confidence),
        "grade_column": (detected.grade_column.source, detected.grade_column.confidence),
        "output_dir": (detected.output_dir.source, detected.output_dir.confidence),
        "host": (detected.host.source, detected.host.confidence),
        "port": (detected.port.source, detected.port.confidence),
    }
    return values, candidates, metadata


def render_quickstart_summary(*, values: dict[str, Any], metadata: dict[str, tuple[str, float]]) -> None:
    rows = []
    for index, field in enumerate(QUICKSTART_FIELDS, start=1):
        source, confidence = metadata.get(field.key, ("manual", 1.0))
        conf_pct = f"{int(round(confidence * 100))}%"
        rows.append((str(index), field.label, format_quickstart_value(values.get(field.key)), source, conf_pct))

    styled_table(
        "Quickstart Review",
        [
            ("#", {"justify": "right", "style": "dim"}),
            ("Field", {}),
            ("Value", {"overflow": "fold"}),
            ("Source", {}),
            ("Confidence", {"justify": "right"}),
        ],
        rows,
    )


def format_quickstart_value(value: Any) -> str:
    if value is None:
        return "<missing>"
    if isinstance(value, Path):
        return str(value)
    return str(value)


def edit_quickstart_field(
    *,
    field: QuickstartFieldSpec,
    values: dict[str, Any],
    candidates: dict[str, list[Any]],
    metadata: dict[str, tuple[str, float]],
    cwd: Path,
) -> None:
    key = field.key
    if field.kind == "path":
        updated = prompt_path_candidate(
            label=field.label,
            current=values.get(key) if isinstance(values.get(key), Path) else None,
            candidates=[item for item in candidates.get(key, []) if isinstance(item, Path)],
            cwd=cwd,
        )
        values[key] = updated
        metadata[key] = ("manual", 1.0)
        candidates[key] = dedupe_paths([updated] + [item for item in candidates.get(key, []) if isinstance(item, Path)])
        return

    if field.kind == "column":
        updated = prompt_text_candidate(
            label=field.label,
            current=str(values.get(key) or "").strip() or None,
            candidates=[str(item) for item in candidates.get(key, []) if str(item).strip()],
        )
        values[key] = updated
        metadata[key] = ("manual", 1.0)
        candidates[key] = dedupe_strings([updated] + [str(item) for item in candidates.get(key, [])])
        return

    if field.kind == "text":
        values[key] = prompt_text(field.label, default=str(values.get(key) or "").strip() or None, required=True)
        metadata[key] = ("manual", 1.0)
        return

    if field.kind == "int":
        default_port = values.get(key)
        if not isinstance(default_port, int):
            default_port = DEFAULT_REVIEW_PORT
        values[key] = prompt_int(field.label, default=default_port, minimum=1, maximum=65535)
        metadata[key] = ("manual", 1.0)
        return

    raise ValueError(f"Unsupported quickstart field kind: {field.kind}")


def prompt_path_candidate(*, label: str, current: Path | None, candidates: list[Path], cwd: Path) -> Path:
    from .prompts import prompt_path_candidate as _ppc

    return _ppc(label=label, current=current, candidates=candidates, cwd=cwd)


def prompt_text_candidate(*, label: str, current: str | None, candidates: list[str]) -> str:
    from .prompts import prompt_text_candidate as _ptc

    return _ptc(label=label, current=current, candidates=candidates)


def validate_quickstart_values(values: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    submissions_dir = values.get("submissions_dir")
    if not isinstance(submissions_dir, Path):
        errors.append("Submissions directory is required.")
    elif not submissions_dir.exists() or not submissions_dir.is_dir():
        errors.append(f"Submissions directory not found: {submissions_dir}")

    solutions_pdf = values.get("solutions_pdf")
    if not isinstance(solutions_pdf, Path):
        errors.append("Solutions PDF is required.")
    elif not solutions_pdf.exists() or not solutions_pdf.is_file():
        errors.append(f"Solutions PDF not found: {solutions_pdf}")

    rubric_yaml = values.get("rubric_yaml")
    if not isinstance(rubric_yaml, Path):
        errors.append("Rubric YAML path is required.")

    grades_template_csv = values.get("grades_template_csv")
    if not isinstance(grades_template_csv, Path):
        errors.append("Grades template CSV is required.")
    elif not grades_template_csv.exists() or not grades_template_csv.is_file():
        errors.append(f"Grades template CSV not found: {grades_template_csv}")

    grade_column_raw = str(values.get("grade_column") or "").strip()
    if not grade_column_raw:
        errors.append("Grade column is required.")
    elif isinstance(grades_template_csv, Path) and grades_template_csv.exists() and grades_template_csv.is_file():
        try:
            _, headers = read_csv_rows(grades_template_csv)
            resolved = resolve_column_name(headers, grade_column_raw, kind="grade")
            values["grade_column"] = resolved
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Grade column resolution failed: {exc}")

    output_dir = values.get("output_dir")
    if not isinstance(output_dir, Path):
        errors.append("Output directory is required.")

    host = str(values.get("host") or "").strip()
    if not host:
        errors.append("Review host is required.")

    port = values.get("port")
    if not isinstance(port, int) or port <= 0 or port > 65535:
        errors.append(f"Review port must be in range 1..65535 (got {port}).")

    return errors


def must_path(value: Any, field: str) -> Path:
    if not isinstance(value, Path):
        raise ValueError(f"Field {field} must be a path.")
    return value.resolve()


def must_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Field {field} must be non-empty.")
    return text


def must_port(value: Any) -> int:
    if not isinstance(value, int) or value <= 0 or value > 65535:
        raise ValueError("Review port must be in range 1..65535.")
    return value


def dedupe_paths(values: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for value in values:
        key = str(value).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        stripped = str(value).strip()
        if not stripped:
            continue
        key = stripped.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(stripped)
    return deduped


def is_interactive_terminal() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def list_profiles() -> int:
    cwd = Path.cwd()
    profiles = list_profile_paths(cwd=cwd, profile_dir=DEFAULT_PROFILE_DIR)
    root = (cwd / DEFAULT_PROFILE_DIR).resolve()
    if not profiles:
        styled_info(f"No profiles found under {root}")
        return 0

    rows = []
    for path in profiles:
        name = path.stem
        output_dir = "-"
        rubric_yaml = "-"
        status = "profile_invalid"

        try:
            profile = load_workflow_profile(path)
            output_dir = str(profile.grade.output_dir)
            rubric_yaml = str(profile.grade.rubric_yaml)
            status, detail = review_state_status(profile.grade.output_dir)
            status = status if detail == "" else f"{status}:{detail}"
        except WorkflowProfileError as exc:
            status = f"profile_invalid:{exc}"

        rows.append((name, output_dir, rubric_yaml, status))

    styled_table(
        "Workflow Profiles",
        [("Name", {}), ("Output Dir", {"overflow": "fold"}), ("Rubric", {"overflow": "fold"}), ("Review State", {})],
        rows,
    )
    return 0


def setup_profile_interactive(*, profile_spec: str, overwrite: bool) -> int:
    cwd = Path.cwd()
    profile_path = resolve_profile_path(profile_spec, cwd=cwd, profile_dir=DEFAULT_PROFILE_DIR)
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    if profile_path.exists() and not overwrite:
        if not prompt_yes_no(f"Profile already exists at {profile_path}. Overwrite?", default=False):
            styled_warning("Aborted.")
            raise AbortToMenu

    profile_name = profile_path.stem
    styled_banner(f"Configuring profile: {profile_name}", str(profile_path))

    submissions_dir = prompt_path(
        "Submissions directory",
        default=None,
        required=True,
        cwd=cwd,
    )
    solutions_pdf = prompt_path(
        "Solutions PDF (answer key)",
        default=None,
        required=True,
        cwd=cwd,
    )

    default_rubric = (cwd / "configs" / f"{profile_name}.yaml").resolve()
    rubric_yaml = prompt_path(
        "Rubric YAML path",
        default=str(default_rubric),
        required=True,
        cwd=cwd,
    )
    if not rubric_yaml.exists():
        if prompt_yes_no(f"Rubric not found at {rubric_yaml}. Create a starter rubric now?", default=True):
            assignment_id = prompt_text("Assignment ID", default=profile_name, required=True)
            question_ids_raw = prompt_text(
                "Question IDs (comma-separated, e.g. a,b,c,d)",
                default="a,b,c,d,e",
                required=True,
            )
            question_ids = parse_question_ids(question_ids_raw)
            write_starter_rubric(rubric_yaml, assignment_id=assignment_id, question_ids=question_ids)
            styled_success(f"Created starter rubric: {rubric_yaml}")

    grades_template_csv = prompt_path(
        "Brightspace grades template CSV",
        default=None,
        required=True,
        cwd=cwd,
    )
    grade_column = prompt_text(
        "Grade column header",
        default="Assignment 2 Points Grade",
        required=True,
    )
    output_dir = prompt_path(
        "Output directory",
        default=str((cwd / "outputs" / profile_name).resolve()),
        required=True,
        cwd=cwd,
    )
    host = prompt_text("Review host", default=DEFAULT_REVIEW_HOST, required=True)
    port = prompt_int("Review port", default=DEFAULT_REVIEW_PORT, minimum=1, maximum=65535)

    profile_text = render_profile_toml(
        submissions_dir=submissions_dir,
        solutions_pdf=solutions_pdf,
        rubric_yaml=rubric_yaml,
        grades_template_csv=grades_template_csv,
        grade_column=grade_column,
        output_dir=output_dir,
        host=host,
        port=port,
    )
    profile_path.write_text(profile_text, encoding="utf-8")
    styled_success(f"Wrote profile: {profile_path}")
    styled_info(f"Next step: python3 -m grader.workflow_cli run --profile {profile_name}")
    return 0


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

    for field, flag in CLI_FLAG_MAPPINGS:
        if bool(getattr(profile, field)):
            argv.append(flag)
    return argv


def is_profile_not_found_error(exc: WorkflowProfileError) -> bool:
    return "Profile file not found:" in str(exc)


def normalize_user_path(raw: str, *, cwd: Path) -> Path:
    expanded = os.path.expandvars(raw)
    expanded = os.path.expanduser(expanded)
    path = Path(expanded)
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def parse_question_ids(raw: str) -> list[str]:
    values = [item.strip().lower() for item in raw.split(",")]
    question_ids = [value for value in values if value]
    if not question_ids:
        return ["a"]
    return question_ids


def write_starter_rubric(path: Path, *, assignment_id: str, question_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f'assignment_id: "{assignment_id.strip()}"',
        'scoring_mode: "equal_weights"',
        "partial_credit: 0.5",
        "",
        "bands:",
        "  check_plus_min: 0.90",
        "  check_min: 0.70",
        "",
        "questions:",
    ]
    for qid in question_ids:
        lines.extend(
            [
                f'  - id: "{qid}"',
                f'    label_patterns: ["{qid})", "{qid}.", "({qid})"]',
                f'    anchor_tokens: ["{qid})", "{qid}.", "({qid})"]',
                '    scoring_rules: "Define expected answer criteria."',
                '    short_note_pass: "Correct."',
                '    short_note_fail: "Needs revision."',
                "    weight: 1.0",
                "",
            ]
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_profile_toml(
    *,
    submissions_dir: Path,
    solutions_pdf: Path,
    rubric_yaml: Path,
    grades_template_csv: Path,
    grade_column: str,
    output_dir: Path,
    host: str,
    port: int,
    optional_grade_values: dict[str, Any] | None = None,
) -> str:
    defaults: dict[str, Any] = {
        "grading_mode": DEFAULT_GRADING_MODE,
        "model": DEFAULT_MODEL,
        "identifier_column": "OrgDefinedId",
        "context_cache": True,
        "context_cache_ttl_seconds": DEFAULT_CONTEXT_CACHE_TTL_SECONDS,
        "plain": False,
    }
    sanitized_optional = sanitize_optional_grade_values(optional_grade_values or {})
    grade_values = dict(defaults)
    grade_values.update(sanitized_optional)

    lines = [
        "[grade]",
        f"submissions_dir = {toml_quote(str(submissions_dir.resolve()))}",
        f"solutions_pdf = {toml_quote(str(solutions_pdf.resolve()))}",
        f"rubric_yaml = {toml_quote(str(rubric_yaml.resolve()))}",
        f"grades_template_csv = {toml_quote(str(grades_template_csv.resolve()))}",
        f"grade_column = {toml_quote(grade_column)}",
        f"output_dir = {toml_quote(str(output_dir.resolve()))}",
    ]

    for key in OPTIONAL_GRADE_RENDER_ORDER:
        if key not in grade_values:
            continue
        value = grade_values[key]
        rendered = render_optional_grade_value(key, value)
        if rendered is None:
            continue
        lines.append(f"{key} = {rendered}")

    lines.extend(
        [
            "",
            "[review]",
            f"host = {toml_quote(host)}",
            f"port = {port}",
        ]
    )
    return "\n".join(lines) + "\n"


def sanitize_optional_grade_values(values: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, raw in values.items():
        if raw is None:
            continue
        if key in _OPTIONAL_PATH_FIELDS:
            path = raw if isinstance(raw, Path) else Path(str(raw).strip())
            if not str(path).strip():
                continue
            normalized[key] = path.resolve()
            continue
        if key in _OPTIONAL_INT_FIELDS:
            if isinstance(raw, bool):
                continue
            try:
                normalized[key] = int(raw)
            except (TypeError, ValueError):
                continue
            continue
        if key in _OPTIONAL_BOOL_FIELDS:
            if isinstance(raw, bool):
                normalized[key] = raw
                continue
            text = str(raw).strip().lower()
            if text in {"true", "1", "yes", "y"}:
                normalized[key] = True
            elif text in {"false", "0", "no", "n"}:
                normalized[key] = False
            continue
        if key in _OPTIONAL_STRING_FIELDS:
            text = str(raw).strip()
            if not text:
                continue
            normalized[key] = text
            continue
        if key in _OPTIONAL_POINTS_FIELDS:
            text = str(raw).strip()
            if not text:
                continue
            normalized[key] = text
            continue
    return normalized


def render_optional_grade_value(key: str, value: Any) -> str | None:
    if key in _OPTIONAL_PATH_FIELDS:
        if not isinstance(value, Path):
            return None
        return toml_quote(str(value))
    if key in _OPTIONAL_BOOL_FIELDS:
        if not isinstance(value, bool):
            return None
        return "true" if value else "false"
    if key in _OPTIONAL_INT_FIELDS:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return str(value)
    if key in _OPTIONAL_STRING_FIELDS or key in _OPTIONAL_POINTS_FIELDS:
        text = str(value).strip()
        if not text:
            return None
        return toml_quote(text)
    return None


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

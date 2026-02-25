from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .review.importer import ReviewInitError, initialize_review_state
from .review.server import run_review_server
from .review.state import state_path_for_output
from .workflow_profile import (
    DEFAULT_PROFILE_DIR,
    GradeProfile,
    DEFAULT_MODEL,
    DEFAULT_GRADING_MODE,
    DEFAULT_REVIEW_HOST,
    DEFAULT_REVIEW_PORT,
    DEFAULT_CONTEXT_CACHE_TTL_SECONDS,
    WorkflowProfile,
    WorkflowProfileError,
    list_profile_paths,
    load_workflow_profile,
    resolve_profile_path,
)


REQUIRED_STATE_KEYS = {"schema_version", "run_metadata", "grading_context", "submissions"}


@dataclass(frozen=True)
class CliValueMapping:
    field: str
    flag: str
    value_type: str
    emit_if_empty: bool = True


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
    CliValueMapping("diagnostics_file", "--diagnostics-file", "path"),
)

CLI_FLAG_MAPPINGS: tuple[tuple[str, str], ...] = (
    ("dry_run", "--dry-run"),
    ("annotate_dry_run_marks", "--annotate-dry-run-marks"),
    ("plain", "--plain"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Workflow CLI for profile-based grading runs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    subparsers.add_parser("list", help="List local workflow profiles.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])

    try:
        if args.command == "run":
            return run_with_optional_setup(profile_spec=args.profile, host_override=args.host, port_override=args.port)
        if args.command == "serve":
            return serve_with_optional_setup(profile_spec=args.profile, host_override=args.host, port_override=args.port)
        if args.command == "setup":
            return setup_profile_interactive(profile_spec=args.profile, overwrite=args.overwrite)
        if args.command == "list":
            return list_profiles()
    except WorkflowProfileError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    except ReviewInitError as exc:
        print(f"[ERROR] Review init failed: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    print("[ERROR] Unknown command.", file=sys.stderr)
    return 2


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

    print(f"Profile: {profile.name}")
    print(f"Output dir: {profile.grade.output_dir}")
    if shifted:
        print(f"[WARN] Port {requested_port} is busy. Using {port}.")
    print(f"Review URL: http://{host}:{port}")
    run_review_server(output_dir=profile.grade.output_dir, host=host, port=port)
    return 0


def run_with_optional_setup(*, profile_spec: str, host_override: str | None, port_override: int | None) -> int:
    try:
        return run_from_profile(profile_spec=profile_spec, host_override=host_override, port_override=port_override)
    except WorkflowProfileError as exc:
        if not is_profile_not_found_error(exc) or not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise
        print(f"[WARN] {exc}")
        if not prompt_yes_no("Create this profile now with guided setup?", default=True):
            return 2
        setup_code = setup_profile_interactive(profile_spec=profile_spec, overwrite=False)
        if setup_code != 0:
            return setup_code
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

    print(f"Profile: {profile.name}")
    print(f"Output dir: {profile.grade.output_dir}")
    if shifted:
        print(f"[WARN] Port {requested_port} is busy. Using {port}.")
    print(f"Review URL: http://{host}:{port}")
    run_review_server(output_dir=profile.grade.output_dir, host=host, port=port)
    return 0


def serve_with_optional_setup(*, profile_spec: str, host_override: str | None, port_override: int | None) -> int:
    try:
        return serve_from_profile(profile_spec=profile_spec, host_override=host_override, port_override=port_override)
    except WorkflowProfileError as exc:
        if not is_profile_not_found_error(exc) or not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise
        print(f"[WARN] {exc}")
        if not prompt_yes_no("Create this profile now with guided setup?", default=True):
            return 2
        setup_code = setup_profile_interactive(profile_spec=profile_spec, overwrite=False)
        if setup_code != 0:
            return setup_code
        return serve_from_profile(profile_spec=profile_spec, host_override=host_override, port_override=port_override)


def list_profiles() -> int:
    cwd = Path.cwd()
    profiles = list_profile_paths(cwd=cwd, profile_dir=DEFAULT_PROFILE_DIR)
    root = (cwd / DEFAULT_PROFILE_DIR).resolve()
    if not profiles:
        print(f"No profiles found under {root}")
        return 0

    print("name\toutput_dir\trubric_yaml\treview_state")
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

        print(f"{name}\t{output_dir}\t{rubric_yaml}\t{status}")
    return 0


def setup_profile_interactive(*, profile_spec: str, overwrite: bool) -> int:
    cwd = Path.cwd()
    profile_path = resolve_profile_path(profile_spec, cwd=cwd, profile_dir=DEFAULT_PROFILE_DIR)
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    if profile_path.exists() and not overwrite:
        if not prompt_yes_no(f"Profile already exists at {profile_path}. Overwrite?", default=False):
            print("Aborted.")
            return 2

    profile_name = profile_path.stem
    print(f"Configuring profile: {profile_name}")
    print(f"Profile path: {profile_path}")

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
            print(f"Created starter rubric: {rubric_yaml}")

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
    print(f"Wrote profile: {profile_path}")
    print(f"Next step: python3 -m grader.workflow_cli run --profile {profile_name}")
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


def prompt_text(label: str, *, default: str | None, required: bool) -> str:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        raw = input(f"{label}{suffix}: ").strip()
        if raw:
            return raw
        if default is not None:
            return str(default)
        if not required:
            return ""
        print("Value is required.")


def prompt_yes_no(label: str, *, default: bool) -> bool:
    default_text = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{label} [{default_text}]: ").strip().lower()
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        if raw == "":
            return default
        print("Please answer y or n.")


def prompt_int(label: str, *, default: int, minimum: int, maximum: int) -> int:
    while True:
        raw = input(f"{label} [{default}]: ").strip()
        if raw == "":
            return default
        try:
            value = int(raw)
        except ValueError:
            print("Please enter an integer.")
            continue
        if value < minimum or value > maximum:
            print(f"Please enter a value between {minimum} and {maximum}.")
            continue
        return value


def prompt_path(label: str, *, default: str | None, required: bool, cwd: Path) -> Path:
    while True:
        raw = prompt_text(label, default=default, required=required)
        value = raw.strip()
        if not value and not required:
            return cwd
        resolved = normalize_user_path(value, cwd=cwd)
        return resolved


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
) -> str:
    return (
        "[grade]\n"
        f"submissions_dir = {toml_quote(str(submissions_dir))}\n"
        f"solutions_pdf = {toml_quote(str(solutions_pdf))}\n"
        f"rubric_yaml = {toml_quote(str(rubric_yaml))}\n"
        f"grades_template_csv = {toml_quote(str(grades_template_csv))}\n"
        f"grade_column = {toml_quote(grade_column)}\n"
        f"output_dir = {toml_quote(str(output_dir))}\n"
        f'grading_mode = {toml_quote(DEFAULT_GRADING_MODE)}\n'
        f"model = {toml_quote(DEFAULT_MODEL)}\n"
        'identifier_column = "OrgDefinedId"\n'
        "context_cache = true\n"
        f"context_cache_ttl_seconds = {DEFAULT_CONTEXT_CACHE_TTL_SECONDS}\n"
        "plain = false\n"
        "\n"
        "[review]\n"
        f"host = {toml_quote(host)}\n"
        f"port = {port}\n"
    )


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

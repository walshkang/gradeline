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

from ..env import update_env_file
from ..gemini_client import GeminiGrader
from ..report import read_csv_rows, resolve_column_name
from ..review.importer import ReviewInitError, initialize_review_state
from ..review.server import run_review_server
from ..review.state import state_path_for_output
from ..prompts import (
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
from ..config import load_rubric
from ..defaults import resolve_model, set_default_model
from ..workflow_detect import (
    DetectedConfig,
    default_question_ids,
    detect_defaults,
    scan_downloads_candidates,
)
from .profile_utils import (
    is_interactive_terminal,
    render_profile_toml,
    setup_profile_interactive,
    parse_question_ids,
    write_starter_rubric,
)

from .profile_utils import get_project_root
from ..workflow_profile import (
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
)

_OPTIONAL_PATH_FIELDS = {"temp_dir", "cache_dir", "diagnostics_file"}
_OPTIONAL_INT_FIELDS = {"ocr_char_threshold", "context_cache_ttl_seconds"}
_OPTIONAL_FLOAT_FIELDS = {"annotation_font_size"}
_OPTIONAL_BOOL_FIELDS = {"dry_run", "annotate_dry_run_marks", "context_cache", "extract_blocks", "plain"}
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



def quickstart_profile_interactive(*, profile_spec: str, overwrite: bool, auto_run: bool, non_interactive: bool = False) -> int:
    if not non_interactive and not is_interactive_terminal():
        styled_error("quickstart requires an interactive terminal (TTY).")
        return 2

    cwd = get_project_root()
    profile_path = resolve_profile_path(profile_spec, cwd=cwd, profile_dir=DEFAULT_PROFILE_DIR)
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    if profile_path.exists() and not overwrite:
        if non_interactive:
            styled_warning(f"Profile already exists at {profile_path} and --overwrite was not specified. Aborting.")
            raise AbortToMenu
        if not prompt_yes_no(f"Profile already exists at {profile_path}. Overwrite?", default=False):
            styled_warning("Aborted.")
            raise AbortToMenu

    detected = detect_defaults(profile_spec=profile_spec, cwd=cwd)

    # Detect a true "blank" environment and provide guidance before falling back to setup wizard.
    if (
        detected.submissions_dir.value is None
        and not detected.submissions_dir.candidates
        and detected.solutions_pdf.value is None
        and not detected.solutions_pdf.candidates
        and detected.grades_template_csv.value is None
        and not detected.grades_template_csv.candidates
        and not profile_path.exists()
    ):
        styled_banner(f"Quickstart: Assignment {profile_spec}", "No assignment files detected yet")
        styled_info(f"Looks like this is your first time setting up {profile_spec}.")
        styled_warning(f"No assignment files found in data/{profile_spec}/ or {detected.context.downloads_dir}.")
        styled_section_heading("Three ways to get started")
        styled_info(
            f"  1. Import from Downloads (recommended): download from Brightspace, then run "
            f"`./gradeline import --profile {profile_spec}`."
        )
        styled_info(
            f"  2. Place files manually under data/{profile_spec}/: "
            "create a submissions/ folder, copy solutions.pdf and grades.csv, then re-run quickstart."
        )
        styled_info(
            f"  3. Point to files anywhere with the setup wizard: "
            f"`./gradeline setup --profile {profile_spec}`."
        )
        if not non_interactive and is_interactive_terminal():
            raw = input(
                "Press Enter to run the guided setup wizard now, or type q to abort: "
            ).strip().lower()
            if raw == "q":
                styled_warning("Aborted.")
                raise AbortToMenu
            return setup_profile_interactive(profile_spec=profile_spec, overwrite=False)
        # Non-interactive: just print guidance and exit with a non-zero code.
        return 2

    values, candidates, metadata = initialize_quickstart_state(detected)

    if not non_interactive:
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
    else:
        errors = validate_quickstart_values(values)
        if errors:
            styled_warning("Validation errors in detected configuration:")
            for error in errors:
                styled_warning(f"  • {error}")
            return 2

    rubric_path = values["rubric_yaml"]
    if not isinstance(rubric_path, Path):
        raise ValueError("Rubric path is required.")
    if not rubric_path.exists():
        # First, attempt AI-assisted draft generation (interactive)
        solutions_pdf = values.get("solutions_pdf")
        generated = False
        if not non_interactive and isinstance(solutions_pdf, Path) and solutions_pdf.exists() and solutions_pdf.is_file():
            if is_interactive_terminal() and prompt_yes_no("Convert solution key into rubric using AI?", default=True):
                try:
                    generated = maybe_generate_rubric_with_ai(solutions_pdf=solutions_pdf, rubric_yaml=rubric_path, profile_name=profile_path.stem)
                except Exception as exc:  # noqa: BLE001
                    if isinstance(exc, (TypeError, NameError, AttributeError)):
                        raise
                    generated = False
        if not generated:
            # Offer sample template, starter rubric, or skip
            project_root = get_project_root()
            sample_path = (project_root / "configs" / "_templates" / "rubric_sample.yaml").resolve()
            sample_prompt = (project_root / "configs" / "_templates" / "rubric_chat_prompt.txt").resolve()
            if non_interactive:
                choice = "Create starter rubric"
            elif is_interactive_terminal():
                choices = ["Create starter rubric", "Use sample template", "Skip (create later)"]
                idx = prompt_select(f"Rubric not found at {rubric_path}. Choose how to create one:", choices, default=0)
                if idx is None:
                    styled_warning("Aborted.")
                    raise AbortToMenu
                choice = choices[idx]
            else:
                # Non-interactive default: create a starter rubric
                choice = "Create starter rubric"

            if choice == "Use sample template":
                if sample_path.exists() and sample_path.is_file():
                    rubric_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(sample_path, rubric_path)
                    styled_success(f"Copied sample rubric to {rubric_path}")
                    if sample_prompt.exists() and sample_prompt.is_file():
                        styled_section_heading("Chatbot prompt for custom rubric")
                        print(sample_prompt.read_text(encoding="utf-8"))
                else:
                    styled_warning(f"Sample template not found at {sample_path}. Creating starter rubric instead.")
                    choice = "Create starter rubric"

            if choice == "Create starter rubric":
                if non_interactive:
                    assignment_id = profile_path.stem
                    inferred = list(detected.prior_rubric_question_ids) or list(default_question_ids())
                    question_ids_raw = ",".join(inferred)
                else:
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
                if not non_interactive:
                    styled_info("Rubric checklist:")
                    styled_info("  • Update scoring_rules per question.")
                    styled_info("  • Confirm label_patterns and anchor_tokens match your answer key.")
                    styled_info("  • Verify bands thresholds for your class policy.")
            else:
                styled_warning(f"No rubric created at {rubric_path}. You can add one later with `./gradeline setup --profile {profile_path.stem}`.")

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
        from ..workflow_cli import run_from_profile
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
    try:
        _do_edit_quickstart_field(key=key, field=field, values=values, candidates=candidates, metadata=metadata, cwd=cwd)
    except KeyboardInterrupt:
        raise AbortToMenu


def _do_edit_quickstart_field(
    *,
    key: str,
    field: QuickstartFieldSpec,
    values: dict[str, Any],
    candidates: dict[str, list[Any]],
    metadata: dict[str, tuple[str, float]],
    cwd: Path,
) -> None:
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


def maybe_generate_rubric_with_ai(*, solutions_pdf: Path, rubric_yaml: Path, profile_name: str) -> bool:
    """Interactively generate a draft rubric YAML from the solutions PDF using Gemini.

    This is an optional wizard that runs inside the setup_profile_interactive flow.
    It uploads the solutions PDF, asks Gemini to infer a rubric via a structured
    response schema, converts it to YAML, shows a preview, and lets the user
    Accept, Edit in $EDITOR, Retry, or Skip.
    """
    # Only run in an interactive terminal; non-interactive flows must be no-op.
    if not is_interactive_terminal():
        return False

    if not solutions_pdf.exists() or not solutions_pdf.is_file():
        styled_warning(f"Solutions PDF not found at {solutions_pdf}; skipping AI rubric generation.")
        return False
    if solutions_pdf.suffix.lower() != ".pdf":
        styled_warning(
            f"AI rubric generation currently requires a PDF solutions file. "
            f"Got: {solutions_pdf.name}. Skipping AI rubric generation."
        )
        return False

    # If a rubric already exists, confirm whether to overwrite it with an AI draft.
    if rubric_yaml.exists():
        overwrite = prompt_yes_no(
            f"Rubric already exists at {rubric_yaml}. Convert solution key into rubric (overwrite existing)?",
            default=False,
        )
        if not overwrite:
            return False
    else:
        use_ai = prompt_yes_no(
            "Convert solution key into rubric using AI?",
            default=True,
        )
        if not use_ai:
            return False

    # Resolve API key and model.
    api_key_env = "GEMINI_API_KEY"
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        styled_warning(
            f"{api_key_env} is not set. Configure your GenAI API key with "
            "`./gradeline configure-api-key` before using AI rubric generation."
        )
        return False

    project_root = get_project_root()
    cache_dir = project_root / ".grader_cache"

    try:
        resolved_model = resolve_model("rubric", DEFAULT_MODEL)
        grader = GeminiGrader(api_key=api_key, model=resolved_model, cache_dir=cache_dir)
    except ImportError:
        styled_warning(
            "Gemini client dependencies are missing. Install the 'google-genai' package "
            "to enable AI-assisted rubric generation."
        )
        return False
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (TypeError, NameError, AttributeError)):
            raise
        styled_error(f"Failed to initialize Gemini client: {exc}")
        return False

    import subprocess
    import yaml

    # Optional rich status + syntax highlighting.
    try:
        from rich.console import Console
        from rich.status import Status  # type: ignore[import]
        from rich.syntax import Syntax

        _has_rich = True
    except Exception:  # noqa: BLE001
        Console = None  # type: ignore[assignment]
        Status = None  # type: ignore[assignment]
        Syntax = None  # type: ignore[assignment]
        _has_rich = False

    def _print_yaml_preview(yaml_text: str) -> None:
        styled_section_heading("Draft Rubric (YAML)")
        if _has_rich and sys.stdout.isatty():
            console = Console()
            console.print(Syntax(yaml_text, "yaml", line_numbers=False))
        else:
            print(yaml_text)

    while True:
        # --- Call Gemini to generate a draft rubric payload -------------------
        try:
            if _has_rich and sys.stdout.isatty():
                console = Console()
                with console.status("Generating rubric from solutions PDF..."):
                    rubric_payload = grader.generate_rubric_draft(
                        solutions_pdf=solutions_pdf,
                        assignment_id=profile_name,
                    )
            else:
                styled_info("Generating rubric from solutions PDF (this may take up to ~30 seconds)...")
                rubric_payload = grader.generate_rubric_draft(
                    solutions_pdf=solutions_pdf,
                    assignment_id=profile_name,
                )
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, (TypeError, NameError, AttributeError)):
                raise
            styled_error(f"AI rubric generation failed: {exc}")
            if not prompt_yes_no("Retry converting solution key into rubric?", default=False):
                styled_warning("Skipping rubric conversion.")
                return
            continue

        # --- Convert to YAML and show preview --------------------------------
        rubric_yaml.parent.mkdir(parents=True, exist_ok=True)
        yaml_text = yaml.safe_dump(rubric_payload, sort_keys=False, allow_unicode=True)
        _print_yaml_preview(yaml_text)

        # --- Regex Pre-check Candidates --------------------------------------
        styled_section_heading("Regex Pre-check Candidates")
        questions = rubric_payload.get("questions", [])
        has_regex = False
        for q in questions:
            q_id = q.get("id", "?")
            expected_answers = q.get("expected_answers", [])
            if expected_answers:
                styled_info(f"Q{q_id}: expected_answers = {expected_answers}  → deterministic ✓")
                has_regex = True
            else:
                styled_info(f"Q{q_id}: expected_answers = []                → LLM grading")
        
        if not has_regex:
            styled_info("No regex candidates inferred. All questions will use LLM grading.")

        # --- 2-Submission Dry-Run Proof --------------------------------------
        from ..discovery import discover_submission_units
        profile_dir = rubric_yaml.parent
        submissions_dir = profile_dir / "submissions"
        if submissions_dir.exists() and submissions_dir.is_dir():
            try:
                units = discover_submission_units(submissions_dir)
                if units:
                    def unit_size(u):
                        return sum(p.stat().st_size for p in u.pdf_paths if p.exists())
                    
                    units_sorted = sorted(units, key=unit_size, reverse=True)
                    if len(units_sorted) > 1:
                        test_units = [units_sorted[0], units_sorted[-1]]
                    else:
                        test_units = [units_sorted[0]]
                    
                    styled_section_heading("Dry-Run Proof")
                    styled_info(f"Running proof on {len(test_units)} submission(s)...")
                    

                    from ..orchestrator import GradingConfig, Orchestrator
                    from ..ui import create_console_ui
                    
                    # Need to write a temp rubric file to load_rubric
                    project_root = profile_dir.parent.parent
                    temp_out_dir = project_root / ".grader_tmp" / "rubric_proof"
                    temp_rubric_yaml = temp_out_dir / "temp_rubric.yaml"
                    
                    try:
                        temp_out_dir.mkdir(parents=True, exist_ok=True)
                        temp_rubric_yaml.write_text(yaml_text, encoding="utf-8")
                        temp_rubric = load_rubric(temp_rubric_yaml)
                        
                        grader_instance = grader
                        proof_config = GradingConfig(
                            submissions_root=submissions_dir,
                            output_dir=temp_out_dir,
                            temp_dir=project_root / ".grader_tmp",
                            ocr_char_threshold=200,
                            rubric=temp_rubric,
                            rubric_yaml=temp_rubric_yaml,
                            solutions_text="",
                            solutions_pdf_path=solutions_pdf,
                            grade_points={"Check Plus": "1.0", "Check": "0.8", "Check Minus": "0.5", "REVIEW_REQUIRED": "0.0"},
                            grader=grader_instance,
                            grading_mode="unified",
                            agent_type="gemini",
                            context_cache=False,
                            context_cache_ttl_seconds=3600,
                            dry_run=False,
                            locator_model="",
                            annotate_dry_run_marks=False,
                            extraction_model="gemini-1.5-flash",
                            gemini_api_key=api_key or None,
                            extract_blocks=False,
                            diagnostics=None,
                            rate_limiter=None,
                            annotation_font_size=24.0,
                            model=resolve_model("grading", DEFAULT_MODEL),
                            quiet=True,
                            cache_dir=project_root / ".grader_cache",
                        )
                        
                        quiet_ui = create_console_ui(quiet=True)
                        orchestrator = Orchestrator(proof_config, quiet_ui)
                        
                        results = []
                        for idx, unit in enumerate(test_units):
                            _, res, _ = orchestrator.process_student(idx, unit)
                            results.append(res)
                            
                        for res in results:
                            print(f"\n  ── Dry-Run Proof: {res.submission.folder_path.name} ──")
                            for q_res in res.question_results:
                                v_icon = "✓" if q_res.verdict == "correct" else ("≈" if q_res.verdict == "rounding_error" else "✗")
                                print(f"  Q{q_res.id}: {v_icon} {q_res.verdict}  ({q_res.grading_source}, confidence: {q_res.confidence:.2f})")
                                if q_res.evidence_quote:
                                    print(f"      Answer: \"{q_res.evidence_quote[:60]}\"")
                                if q_res.grading_source == "regex":
                                    q_draft = next((q for q in questions if str(q.get("id")) == str(q_res.id)), {})
                                    expected = q_draft.get("expected_answers", [])
                                    print(f"      Expected: regex {expected}")
                                else:
                                    if q_res.short_reason:
                                        print(f"      Reason: \"{q_res.short_reason}\"")
                        print()
                        
                    except Exception as exc:
                        if isinstance(exc, (TypeError, NameError, AttributeError)):
                            raise
                        styled_warning(f"Dry-run proof failed: {exc}")
                    finally:
                        if temp_out_dir.exists():
                            import shutil
                            shutil.rmtree(temp_out_dir, ignore_errors=True)
            except Exception as exc:
                if isinstance(exc, (TypeError, NameError, AttributeError)):
                    raise
                styled_warning(f"Could not discover submissions for dry-run proof: {exc}")

        # --- Interactive choices: Accept / Edit / Retry / Skip ---------------
        choices = [
            "Accept and save rubric",
            "Edit in $EDITOR before saving",
            "Retry rubric generation",
            "Skip (keep existing rubric or create manually)",
        ]
        idx = prompt_select(
            "AI-generated rubric",
            choices,
            default=0,
        )
        if idx is None:
            raise AbortToMenu

        choice = choices[idx]

        if choice.startswith("Accept"):
            rubric_yaml.write_text(yaml_text, encoding="utf-8")
            try:
                # Validate that the YAML can be parsed into a RubricConfig.
                load_rubric(rubric_yaml)
            except Exception as exc:  # noqa: BLE001
                styled_error(f"Saved rubric is not valid: {exc}")
                if prompt_yes_no("Retry AI rubric generation instead?", default=True):
                    continue
                styled_warning(
                    "Leaving the current rubric YAML in place. "
                    "You may edit it manually if needed."
                )
                return False

            styled_success(f"Saved AI-generated rubric to {rubric_yaml}")
            return True

        if "Edit in $EDITOR" in choice:
            # Seed the rubric file with the current draft and open in editor.
            rubric_yaml.write_text(yaml_text, encoding="utf-8")

            editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
            if not editor:
                if sys.platform == "win32":
                    editor = "notepad"
                else:
                    # Prefer nano/vi if available.
                    for candidate in ("nano", "vi"):
                        if shutil.which(candidate):
                            editor = candidate
                            break
                    if not editor:
                        styled_error(
                            "No editor found ($EDITOR/$VISUAL not set and neither 'nano' nor 'vi' is available)."
                        )
                        styled_info(f"Edit the rubric manually at: {rubric_yaml}")
                        return False

            try:
                subprocess.run([editor, str(rubric_yaml)], check=False)
            except FileNotFoundError:
                styled_error(f"Editor '{editor}' not found. Please edit the file manually: {rubric_yaml}")
                return False

            # After editing, load and validate the YAML.
            try:
                # Parse YAML to ensure it is syntactically valid.
                yaml.safe_load(rubric_yaml.read_text(encoding="utf-8"))
                load_rubric(rubric_yaml)
            except Exception as exc:  # noqa: BLE001
                styled_error(f"Edited rubric is not valid: {exc}")
                follow_up_choices = [
                    "Reopen editor to fix YAML",
                    "Retry converting solution key into rubric",
                    "Abort and keep current (possibly invalid) YAML",
                ]
                follow_idx = prompt_select(
                    "Edited rubric is invalid. Choose next step.",
                    follow_up_choices,
                    default=0,
                )
                if follow_idx is None:
                    raise AbortToMenu
                if follow_up_choices[follow_idx].startswith("Abort"):
                    return False
                if follow_up_choices[follow_idx].startswith("Reopen editor"):
                    # Loop back to preview + choices, but keep existing file contents;
                    # the next iteration will re-run generation if chosen.
                    try:
                        subprocess.run([editor, str(rubric_yaml)], check=False)
                    except FileNotFoundError:
                        styled_error(
                            f"Editor '{editor}' not found on second attempt. "
                            f"Please edit the file manually: {rubric_yaml}"
                        )
                        return False
                    # Validate again; if still invalid, fall through to main loop.
                    try:
                        yaml.safe_load(rubric_yaml.read_text(encoding="utf-8"))
                        load_rubric(rubric_yaml)
                        styled_success("Loaded edited rubric.")
                        return True
                    except Exception as exc:  # noqa: BLE001
                        styled_error(f"Edited rubric is still not valid: {exc}")
                        # After another failure, fall back to main AI loop or abort.
                        if not prompt_yes_no("Retry converting solution key into rubric?", default=True):
                            return False
                        continue
                if follow_up_choices[follow_idx].startswith("Retry AI"):
                    continue

            # Edited rubric is valid.
            styled_success("Loaded edited rubric.")
            return True

        if "Retry rubric generation" in choice:
            styled_info("Retrying AI rubric generation with the same solutions PDF...")
            continue

        # Skip choice.
        styled_warning("Skipping rubric conversion.")
        return False



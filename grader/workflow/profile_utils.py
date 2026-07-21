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



def list_profiles() -> int:
    project_root = get_project_root()
    profiles = list_profile_paths(cwd=project_root, profile_dir=DEFAULT_PROFILE_DIR)
    root = (project_root / DEFAULT_PROFILE_DIR).resolve()
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
            from ..workflow_cli import review_state_status
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


def setup_profile_interactive(*, profile_spec: str, overwrite: bool, non_interactive: bool = False) -> int:
    project_root = get_project_root()
    profile_path = resolve_profile_path(profile_spec, cwd=project_root, profile_dir=DEFAULT_PROFILE_DIR)
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    if profile_path.exists() and not overwrite:
        if non_interactive:
            styled_warning(f"Profile already exists at {profile_path} and --overwrite was not specified. Aborting.")
            raise AbortToMenu
        if not prompt_yes_no(f"Profile already exists at {profile_path}. Overwrite?", default=False):
            styled_warning("Aborted.")
            raise AbortToMenu

    profile_name = profile_path.stem
    styled_banner(f"Configuring profile: {profile_name}", str(profile_path))
    if not non_interactive:
        styled_info("Press Ctrl+C at any prompt to return to the main menu.")

    default_data_root = project_root / "data" / profile_name

    if non_interactive:
        submissions_dir = normalize_user_path(str(default_data_root / "submissions"), cwd=project_root)
        solutions_pdf = normalize_user_path(str(default_data_root / "solutions.pdf"), cwd=project_root)
        default_rubric = (project_root / "configs" / f"{profile_name}.yaml").resolve()
        rubric_yaml = normalize_user_path(str(default_rubric), cwd=project_root)
    else:
        submissions_dir = prompt_path(
            "Submissions directory (folder containing all downloaded student PDFs)",
            default=str(default_data_root / "submissions"),
            required=True,
            cwd=project_root,
        )
        solutions_pdf = prompt_path(
            "Solutions PDF (the master answer key used to grade against)",
            default=str(default_data_root / "solutions.pdf"),
            required=True,
            cwd=project_root,
        )

        default_rubric = (project_root / "configs" / f"{profile_name}.yaml").resolve()
        rubric_yaml = prompt_path(
            "Rubric YAML path (rules and point weights for grading)",
            default=str(default_rubric),
            required=True,
            cwd=project_root,
        )
    # Always offer AI rubric generation; maybe_generate_rubric_with_ai handles
    # the "rubric already exists → overwrite?" prompt internally.
    from .quickstart import maybe_generate_rubric_with_ai
    _ = maybe_generate_rubric_with_ai(
        solutions_pdf=solutions_pdf,
        rubric_yaml=rubric_yaml,
        profile_name=profile_name,
    )

    # If we still don't have a valid rubric, offer a starter template (and allow overwriting invalid YAML).
    rubric_valid = False
    if rubric_yaml.exists():
        try:
            load_rubric(rubric_yaml)
            rubric_valid = True
        except Exception:  # noqa: BLE001
            rubric_valid = False

    if not rubric_valid:
        use_starter = True
        if not non_interactive:
            if rubric_yaml.exists():
                starter_prompt = (
                    f"Rubric exists at {rubric_yaml} but is not valid. Overwrite with a starter rubric now?"
                )
            else:
                starter_prompt = f"Rubric not found at {rubric_yaml}. Create a starter rubric now?"
            use_starter = prompt_yes_no(starter_prompt, default=True)

        if use_starter:
            if non_interactive:
                assignment_id = profile_name
                question_ids_raw = "a,b,c,d,e"
            else:
                assignment_id = prompt_text("Assignment ID", default=profile_name, required=True)
                question_ids_raw = prompt_text(
                    "Question IDs (comma-separated, e.g. a,b,c,d)",
                    default="a,b,c,d,e",
                    required=True,
                )
            question_ids = parse_question_ids(question_ids_raw)
            write_starter_rubric(rubric_yaml, assignment_id=assignment_id, question_ids=question_ids)
            styled_success(f"Created starter rubric: {rubric_yaml}")

    if non_interactive:
        grades_template_csv = normalize_user_path(str(default_data_root / "grades.csv"), cwd=project_root)
        grade_column = "Assignment 2 Points Grade"
        output_dir = normalize_user_path(str((project_root / "outputs" / profile_name).resolve()), cwd=project_root)
        host = DEFAULT_REVIEW_HOST
        port = DEFAULT_REVIEW_PORT
    else:
        grades_template_csv = prompt_path(
            "Brightspace grades template CSV (exported from your course to map grades)",
            default=str(default_data_root / "grades.csv"),
            required=True,
            cwd=project_root,
        )
        grade_column = prompt_text(
            "Grade column header (the exact name of the column in the CSV to write grades to)",
            default="Assignment 2 Points Grade",
            required=True,
        )
        output_dir = prompt_path(
            "Output directory",
            default=str((project_root / "outputs" / profile_name).resolve()),
            required=True,
            cwd=project_root,
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


def is_profile_not_found_error(exc: WorkflowProfileError) -> bool:
    return "Profile file not found:" in str(exc)


def normalize_user_path(raw: str, *, cwd: Path) -> Path:
    import re
    clean_raw = re.sub(r'\\(.)', r'\1', raw.strip("\"'"))
    expanded = os.path.expandvars(clean_raw)
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
        "# ==============================================================================",
        "# GRADELINE RUBRIC CONFIGURATION TEMPLATE",
        "# ==============================================================================",
        "# Guidelines for expected_answers & expected_numeric (Regex Precheck):",
        "# 1. Numeric DSL: Use expected_numeric for automatic range and percentage regexes:",
        "#    expected_numeric:",
        "#      value: 0.0808",
        "#      tolerance: 0.001",
        "#      allow_percent: true",
        "# 2. Decimals: Use '\\b0?\\.123\\d*\\b' instead of strict '\\b0\\.123\\b' to allow",
        "#    optional trailing digits of higher precision.",
        "# 3. Fractions/Percentages: Include alternatives using '|' and omit trailing \\b",
        "#    for patterns ending in non-word characters (e.g. '%').",
        "# 4. Single digits: Avoid expected_answers for single-digit or binary answers",
        "#    (e.g., '1', '0') due to high risk of page/label number collisions.",
        "# ==============================================================================",
        "",
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
                '    # expected_numeric: { value: 0.0808, tolerance: 0.001, allow_percent: true }',
                '    expected_answers: [] # (Optional) Manual regex pattern(s) for auto-check',
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
        "provider": "gemini",
        "model": DEFAULT_MODEL,
        "identifier_column": "OrgDefinedId",
        "context_cache": True,
        "context_cache_ttl_seconds": DEFAULT_CONTEXT_CACHE_TTL_SECONDS,
        "extract_blocks": True,
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
        if key in _OPTIONAL_FLOAT_FIELDS:
            if isinstance(raw, bool):
                continue
            try:
                normalized[key] = float(raw)
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
    if key in _OPTIONAL_FLOAT_FIELDS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return str(float(value))
    if key in _OPTIONAL_STRING_FIELDS or key in _OPTIONAL_POINTS_FIELDS:
        text = str(value).strip()
        if not text:
            return None
        return toml_quote(text)
    return None


def delete_assignment_interactive(*, profile_spec: str) -> int:
    """Interactively delete an assignment's profile, rubric, and/or outputs."""
    project_root = get_project_root()
    profile_path = resolve_profile_path(profile_spec, cwd=project_root, profile_dir=DEFAULT_PROFILE_DIR)
    profile_name = profile_path.stem

    # Discover what exists for this assignment.
    rubric_path = (project_root / "configs" / f"{profile_name}.yaml").resolve()
    output_dir = (project_root / "outputs" / profile_name).resolve()

    candidates: list[tuple[str, Path]] = []
    if profile_path.exists():
        candidates.append(("Profile TOML", profile_path))
    if rubric_path.exists():
        candidates.append(("Rubric YAML", rubric_path))
    if output_dir.exists():
        candidates.append(("Outputs folder", output_dir))

    if not candidates:
        styled_warning(f"Nothing found for profile '{profile_name}'.")
        return 0

    styled_section_heading(f"Delete: {profile_name}")
    styled_info("Select what to delete (space to toggle, Enter to confirm):")

    # Show a checklist via prompt_select so the user can pick individual items,
    # or offer "Delete all" and "Cancel" shortcuts.
    choice_labels = [f"{label}  ({path})" for label, path in candidates]
    shortcut_labels = ["— Delete all of the above —", "— Cancel —"]
    all_choices = choice_labels + shortcut_labels

    idx = prompt_select("Choose what to delete", all_choices, default=len(all_choices) - 2)
    if idx is None or all_choices[idx] == "— Cancel —":
        raise AbortToMenu

    if all_choices[idx] == "— Delete all of the above —":
        to_delete = candidates
    else:
        to_delete = [candidates[idx]]

    # Confirm before destroying anything.
    styled_warning("The following will be permanently deleted:")
    for label, path in to_delete:
        styled_info(f"  {label}: {path}")
    if not prompt_yes_no("Confirm delete?", default=False):
        styled_info("Cancelled.")
        return 0

    for label, path in to_delete:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            styled_success(f"Deleted {label}: {path.name}")
        except Exception as exc:  # noqa: BLE001
            styled_error(f"Failed to delete {label}: {exc}")

    return 0


def set_default_model_interactive() -> int:
    """Interactively pick a grading model and write it to configs/defaults.toml."""
    from .defaults import DEFAULT_MODEL

    styled_section_heading("Switch grading model")
    current = DEFAULT_MODEL
    styled_info(f"Current default: {current}")

    choices = [
        f"{name}  —  {desc}" + ("  ✓" if name == current else "")
        for name, desc in _CURATED_MODELS
    ] + ["Enter model name manually"]

    idx = prompt_select("Choose a model", choices, default=0)
    if idx is None:
        raise AbortToMenu

    if idx == len(_CURATED_MODELS):
        model_name = prompt_text("Model name", default=current, required=True)
    else:
        model_name = _CURATED_MODELS[idx][0]

    try:
        set_default_model(model_name)
        styled_success(f"Default model → {model_name}")
        return 0
    except Exception as exc:
        styled_error(f"Failed to set default model: {exc}")
        return 2


def configure_api_key_interactive() -> int:
    """Interactively configure the GenAI API key used via .env across profiles."""
    env_var = "GEMINI_API_KEY"
    cwd = Path.cwd()
    env_path = cwd / ".env"

    styled_section_heading("GenAI API key")

    current = os.getenv(env_var, "")
    if current:
        masked = f"{current[:4]}…" if len(current) >= 4 else "set"
        styled_info(f"{env_var} is currently set (length {len(current)} characters; starts with {masked}).")
    else:
        styled_warning(f"{env_var} is not set.")

    if not prompt_yes_no("Update the GenAI API key now?", default=True):
        styled_info("No changes made.")
        return 0

    while True:
        new_key = prompt_text(
            f"New GenAI API key for {env_var} (stored in .env)",
            required=True,
        ).strip()
        if not new_key:
            styled_warning("Key cannot be empty.")
            if not prompt_yes_no("Try entering the key again?", default=True):
                styled_info("Aborted without changes.")
                return 1
            continue
        if any(ch.isspace() for ch in new_key):
            styled_warning("API keys should not contain whitespace. Please paste the exact key.")
            if not prompt_yes_no("Re-enter the key?", default=True):
                styled_info("Aborted without changes.")
                return 1
            continue
        if len(new_key) < 16:
            if not prompt_yes_no(
                "Key looks very short, which may indicate a copy/paste error. Use it anyway?",
                default=False,
            ):
                continue
        break

    try:
        update_env_file(env_path, env_var, new_key)
    except OSError as exc:
        styled_error(f"Failed to update {env_path}: {exc}")
        return 2

    styled_success(f"Updated {env_var} in {env_path}.")
    styled_info("This key will be used for all profiles that read from GEMINI_API_KEY.")
    return 0



def is_interactive_terminal() -> bool:
    import sys
    return sys.stdin.isatty()

def get_project_root() -> Path:
    from ..workflow_cli import get_project_root as get_root
    return get_root()

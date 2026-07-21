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
from .profile_utils import is_interactive_terminal

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



def import_assignment_assets(
    *,
    profile_spec: str,
    downloads_dir: Path | None,
    data_root: Path | None,
    dry_run: bool,
    move: bool,
) -> int:
    """Import Brightspace submissions, solutions, and grade CSV into data/{profile}/."""
    project_root = get_project_root()
    profile_path = resolve_profile_path(profile_spec, cwd=project_root, profile_dir=DEFAULT_PROFILE_DIR)
    profile_name = profile_path.stem

    downloads_root = (downloads_dir or (Path.home() / "Downloads")).expanduser().resolve()
    data_root_effective = (data_root or (project_root / "data")).resolve()
    target_root = data_root_effective / profile_name
    submissions_target = target_root / "submissions"
    solutions_target = target_root / "solutions.pdf"
    grades_target = target_root / "grades.csv"

    styled_banner(f"Import: Assignment {profile_name}", str(target_root))
    styled_info(f"Scanning {downloads_root} for recent Brightspace downloads...")

    downloads = scan_downloads_candidates(
        profile_name=profile_name,
        assignment_token=None,
        downloads_dir=downloads_root,
    )
    submissions_dirs = downloads.get("submissions_dir", [])
    solutions_pdfs = downloads.get("solutions_pdf", [])
    grade_csvs = downloads.get("grades_template_csv", [])

    submissions_src: Path | None = submissions_dirs[0] if submissions_dirs else None
    solutions_src: Path | None = solutions_pdfs[0] if solutions_pdfs else None
    grades_src: Path | None = grade_csvs[0] if grade_csvs else None

    # If we have no submissions folder candidate, look for a Brightspace ZIP.
    zip_src = None
    if submissions_src is None:
        zip_src = _find_brightspace_zip(downloads_root, profile_name)
        if zip_src is not None:
            styled_info(f"Found Brightspace ZIP: {zip_src.name}")
            if not dry_run:
                if not is_interactive_terminal():
                    unzip = True
                else:
                    unzip = prompt_yes_no(
                        f"Unzip {zip_src.name} into {submissions_target} now?", default=True
                    )
                if unzip:
                    submissions_src = _extract_brightspace_zip(zip_src, profile_name, data_root_effective)

    if submissions_src is None and solutions_src is None and grades_src is None:
        styled_warning("No recent submissions folder, solutions PDF, or grade CSV found in Downloads.")
        styled_info("To use import, first download from Brightspace:")
        styled_info("  1. Go to Assignments → select assignment → Download All (unzips into folders).")
        styled_info("  2. Go to Grades → Export → select the assignment column to get the grade CSV.")
        styled_info("  3. Optionally place your solutions PDF in Downloads as well.")
        styled_info("")
        styled_info("Then re-run:")
        styled_info(f"  ./gradeline import --profile {profile_name}")
        styled_info("")
        styled_info("Or place files manually:")
        styled_info(f"  mkdir -p data/{profile_name}/submissions")
        styled_info(f"  # Copy student folders into data/{profile_name}/submissions")
        styled_info(f"  # Copy your solutions PDF to data/{profile_name}/solutions.pdf")
        styled_info(f"  # Copy the grade template CSV to data/{profile_name}/grades.csv")
        return 2

    # Summary of what we found.
    rows = []
    rows.append(
        (
            "Submissions",
            str(submissions_src) if submissions_src is not None else "<missing>",
            str(submissions_target),
        )
    )
    rows.append(
        (
            "Solutions PDF",
            str(solutions_src) if solutions_src is not None else "<missing>",
            str(solutions_target),
        )
    )
    rows.append(
        (
            "Grade CSV",
            str(grades_src) if grades_src is not None else "<missing>",
            str(grades_target),
        )
    )
    styled_table(
        "Import Preview",
        [
            ("Artifact", {}),
            ("Source", {"overflow": "fold"}),
            ("Destination", {"overflow": "fold"}),
        ],
        rows,
    )

    if dry_run:
        styled_info("Dry run: no files will be copied or moved.")
        return 0

    if is_interactive_terminal():
        proceed = prompt_yes_no("Proceed with import?", default=True)
        if not proceed:
            styled_warning("Import aborted.")
            return 1

    # Ensure target directories exist.
    target_root.mkdir(parents=True, exist_ok=True)
    submissions_target.mkdir(parents=True, exist_ok=True)

    # Copy or move submissions folder contents.
    if submissions_src is not None and submissions_src.exists() and submissions_src.is_dir():
        for child in sorted(submissions_src.iterdir()):
            dest = submissions_target / child.name
            try:
                if move:
                    if dest.exists():
                        # Best-effort merge: leave existing dest in place.
                        continue
                    shutil.move(str(child), str(dest))
                else:
                    if child.is_dir():
                        shutil.copytree(child, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(child, dest)
            except Exception as exc:  # noqa: BLE001
                styled_warning(f"Failed to import {child}: {exc}")

    # Copy or move solutions PDF.
    if solutions_src is not None and solutions_src.exists() and solutions_src.is_file():
        try:
            if move:
                shutil.move(str(solutions_src), str(solutions_target))
            else:
                shutil.copy2(solutions_src, solutions_target)
        except Exception as exc:  # noqa: BLE001
            styled_warning(f"Failed to import solutions PDF {solutions_src}: {exc}")

    # Copy or move grade CSV.
    if grades_src is not None and grades_src.exists() and grades_src.is_file():
        try:
            if move:
                shutil.move(str(grades_src), str(grades_target))
            else:
                shutil.copy2(grades_src, grades_target)
        except Exception as exc:  # noqa: BLE001
            styled_warning(f"Failed to import grade CSV {grades_src}: {exc}")

    styled_success(f"Imported assets into {target_root}")
    styled_info(f"Next step: ./gradeline quickstart --profile {profile_name}")
    return 0


def _find_brightspace_zip(downloads_root: Path, profile_name: str) -> Path | None:
    """Best-effort detection of a Brightspace assignment ZIP in Downloads."""
    best: tuple[int, float, Path] | None = None
    try:
        entries = list(os.scandir(downloads_root))
    except OSError:
        return None

    profile_lower = profile_name.lower()
    for entry in entries:
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
        except OSError:
            continue
        if not entry.name.lower().endswith(".zip"):
            continue
        lowered = entry.name.lower()
        score = 0
        if "download" in lowered:
            score += 2
        if "assignment" in lowered or "assign" in lowered:
            score += 2
        if profile_lower and profile_lower in lowered:
            score += 1
        if score == 0:
            continue
        try:
            stat = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if best is None or score > best[0] or (score == best[0] and stat.st_mtime > best[1]):
            best = (score, stat.st_mtime, Path(entry.path).resolve())

    return best[2] if best is not None else None


def _extract_brightspace_zip(zip_path: Path, profile_name: str, data_root: Path) -> Path:
    """Extract a Brightspace ZIP to a temporary directory under data/ and return the root."""
    import tempfile
    import zipfile

    temp_root = data_root / f".import_tmp_{profile_name}"
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            resolved_temp = temp_root.resolve()
            for member in archive.infolist():
                target_path = (temp_root / member.filename).resolve()
                if not str(target_path).startswith(str(resolved_temp)):
                    styled_warning(f"Skipping unsafe ZIP member (zip-slip): {member.filename}")
                    continue
                archive.extract(member, temp_root)
    except Exception as exc:  # noqa: BLE001
        styled_warning(f"Failed to extract ZIP {zip_path}: {exc}")
        return temp_root

    # Delete D2L metadata and hidden files/folders recursively (bottom-up)
    for root, dirs, files in os.walk(temp_root, topdown=False):
        for name in files:
            if name.lower() in ("index.html", "index.htm", "index.txt") or name.startswith("."):
                try:
                    (Path(root) / name).unlink()
                except Exception:
                    pass
        for name in dirs:
            if name.startswith("."):
                try:
                    shutil.rmtree(Path(root) / name)
                except Exception:
                    pass

    # Many Brightspace zips contain student folders directly at the root.
    return temp_root



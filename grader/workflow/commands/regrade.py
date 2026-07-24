from __future__ import annotations

import re
import shutil
import sqlite3
from pathlib import Path

from ...prompts import (
    styled_info,
    styled_section_heading,
    styled_url,
    styled_warning,
)
from ...workflow_profile import load_workflow_profile


def regrade_from_profile(
    *,
    profile_spec: str,
    question: str | None = None,
    student_filter: str = "",
    host_override: str | None,
    port_override: int | None,
    clear_cache: bool = False,
    annotation_mode: str | None = None,
) -> int:
    """Clear cached results and output artifacts, then re-run grading."""
    import grader.workflow_cli as wcli

    profile = load_workflow_profile(profile_spec, cwd=wcli.get_project_root())
    output_dir = profile.grade.output_dir
    cache_dir = profile.grade.cache_dir or Path(".grader_cache")
    if not cache_dir.is_absolute():
        cache_dir = wcli.get_project_root() / cache_dir

    pattern: re.Pattern[str] | None = None
    if student_filter.strip():
        pattern = re.compile(student_filter, flags=re.IGNORECASE)

    styled_section_heading("Regrade")

    cache_file = cache_dir / "cache.db"
    if clear_cache:
        if cache_file.exists():
            wcli._clear_db_caches(cache_file)
            styled_info("Deleted all rows from grading_cache and context_cache tables in cache.db.")
    elif question is None:
        if cache_file.exists():
            if pattern is None:
                cache_file.unlink()
                styled_info("Cleared entire results cache.")
            else:
                wcli._purge_cache_entries(cache_file, pattern)

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

    grading_argv = wcli.build_grading_argv(profile.grade)
    if student_filter.strip():
        grading_argv.extend(["--student-filter", student_filter])
    if question is not None:
        grading_argv.extend(["--regrade-question", question])
    if annotation_mode:
        grading_argv.extend(["--annotation-mode", annotation_mode])

    exit_code = wcli.invoke_grading_main(grading_argv)

    if exit_code in (1, 2):
        return exit_code

    state_path = wcli.initialize_review_state(output_dir=output_dir, rubric_yaml=None)
    status, reason = wcli.review_state_status(output_dir)
    if status != "valid":
        raise ValueError(f"Review state invalid at {state_path}: {reason}")

    host = wcli.resolve_host(profile=profile, host_override=host_override)
    requested_port = wcli.resolve_requested_port(profile=profile, port_override=port_override)
    port, shifted = wcli.resolve_available_port(host=host, preferred_port=requested_port)

    styled_section_heading("Review Server")
    styled_info(f"Profile: {profile.name}")
    styled_info(f"Output dir: {output_dir}")
    if shifted:
        styled_warning(f"Port {requested_port} is busy. Using {port}.")
    styled_url("Review URL", f"http://{host}:{port}")
    wcli.run_review_server(output_dir=output_dir, host=host, port=port)
    return 0


def _purge_cache_entries(cache_file: Path, pattern: re.Pattern[str]) -> None:
    """Remove cache entries whose keys match the student filter pattern."""
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
    try:
        with sqlite3.connect(cache_file) as conn:
            conn.execute("DELETE FROM grading_cache")
            conn.execute("DELETE FROM context_cache")
            conn.commit()
    except Exception as exc:
        styled_info(f"Could not clear cache tables: {exc}")

from __future__ import annotations

import argparse
import os
import re
import sys
import inspect
from pathlib import Path

from .orchestrator import GradingConfig, Orchestrator
from .config import load_rubric
from .diagnostics import DiagnosticsCollector, serialize_cli_args
from .discovery import discover_submission_units, parse_index_html
from .env import load_dotenv_if_present
from .extract import ensure_binaries_present, extract_pdf_text
from .report import write_index_audit_csv
from .ui import args_to_subtitle, create_console_ui
from .defaults import DEFAULT_CONCURRENCY, DEFAULT_MODEL, DEFAULT_EXTRACTION_MODEL, DEFAULT_RATE_LIMIT_ENABLED, resolve_model
from .rate_limit import RateLimiterRegistry, DailyLimitExhausted

LEGACY_MODE = "legacy"
UNIFIED_MODE = "unified"
AGENT_MODE = "agent"
DEFAULT_AGENT_TYPE = "gemini"
DEFAULT_OCR_CHAR_THRESHOLD = 200
DEFAULT_ANNOTATION_FONT_SIZE = 24.0

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gemini-backed Brightspace PDF grader.")
    parser.add_argument("--submissions-dir", required=True, type=Path)
    parser.add_argument("--solutions-pdf", required=True, type=Path)
    parser.add_argument("--rubric-yaml", required=True, type=Path)
    parser.add_argument("--grades-template-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--temp-dir", type=Path, default=Path(".grader_tmp"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".grader_cache"))
    parser.add_argument("--grading-mode", choices=(LEGACY_MODE, UNIFIED_MODE, AGENT_MODE), default=UNIFIED_MODE)
    parser.add_argument("--provider", default="gemini", help="LLM Provider to use (e.g. gemini, openai).")
    parser.add_argument("--agent-type", choices=("gemini", "codex", "claude"), default=DEFAULT_AGENT_TYPE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--extraction-model", default=DEFAULT_EXTRACTION_MODEL)
    parser.add_argument("--locator-model", default="")
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--identifier-column", default="OrgDefinedId")
    parser.add_argument("--grade-column", required=True)
    parser.add_argument("--comment-column", default="")
    parser.add_argument("--ocr-char-threshold", type=int, default=DEFAULT_OCR_CHAR_THRESHOLD)
    parser.add_argument("--student-filter", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--annotate-dry-run-marks", action="store_true")
    parser.add_argument("--check-plus-points", default="100")
    parser.add_argument("--check-points", default="85")
    parser.add_argument("--check-minus-points", default="65")
    parser.add_argument("--review-required-points", default="")
    parser.add_argument("--context-cache", dest="context_cache", action="store_true")
    parser.add_argument("--no-context-cache", dest="context_cache", action="store_false")
    parser.set_defaults(context_cache=True)
    parser.add_argument("--context-cache-ttl-seconds", type=int, default=86400)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--extract-blocks", dest="extract_blocks", action="store_true")
    parser.add_argument("--no-extract-blocks", dest="extract_blocks", action="store_false")
    parser.set_defaults(extract_blocks=True)
    parser.add_argument("--rate-limit", dest="rate_limit", action="store_true")
    parser.add_argument("--no-rate-limit", dest="rate_limit", action="store_false")
    parser.set_defaults(rate_limit=DEFAULT_RATE_LIMIT_ENABLED)
    parser.add_argument("--resume", action="store_true", default=False, help="Check for and resume from an interrupted run checkpoint.")
    parser.add_argument("--regrade-question", type=str, default=None, help="Question ID for surgical regrade.")
    parser.add_argument("--json", dest="json_output", action="store_true", default=False, help="Emit a JSON summary to stdout on completion (agent-friendly).")
    parser.add_argument("--quiet", action="store_true", default=False, help="Suppress all non-error output. Implies --plain. Errors still go to stderr.")
    parser.add_argument("--plain", action="store_true")
    parser.add_argument("--diagnostics-file", type=Path, default=None)
    parser.add_argument("--annotation-font-size", type=float, default=DEFAULT_ANNOTATION_FONT_SIZE)
    parser.add_argument("--force-vision-extraction", action="store_true", default=False, help="Bypass Tesseract OCR and use Gemini vision extraction directly.")
    return parser.parse_args(argv)





def abort_preflight(exit_code: int, ui, diagnostics, output_dir: Path) -> int:
    try:
        diagnostics.write_json(output_dir / "grading_diagnostics.json")
    except Exception:
        pass
    return exit_code

def main(argv: list[str] | None = None, ui_override: Any = None) -> int:
    load_dotenv_if_present()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    args.model = resolve_model("grading", args.model)
    args.extraction_model = resolve_model("extraction", args.extraction_model)
    if getattr(args, "locator_model", None):
        args.locator_model = resolve_model("locator", args.locator_model)
    if os.environ.get("GRADELINE_PLAIN", "").lower() in {"1", "true", "yes"}:
        args.plain = True
    if os.environ.get("GRADELINE_JSON"):
        args.json_output = True
    if os.environ.get("GRADELINE_QUIET"):
        args.quiet = True
    if getattr(args, "quiet", False):
        args.plain = True
    
    if ui_override is not None:
        ui = ui_override
    else:
        ui = create_console_ui(force_plain=args.plain or args.quiet, quiet=getattr(args, "quiet", False))
    ui.banner("Brightspace PDF Grader", subtitle=args_to_subtitle(args))

    diagnostics = DiagnosticsCollector(args_snapshot=serialize_cli_args(args))

    if args.grading_mode == LEGACY_MODE:
        missing = ensure_binaries_present()
        if missing:
            message = f"Missing required local binaries: {', '.join(missing)}"
            diagnostics.record(
                severity="error",
                code="preflight_missing_binaries",
                stage="preflight",
                message=message,
            )
            ui.error(message)
            return abort_preflight(2, ui, diagnostics, args.output_dir)
    elif args.grading_mode == AGENT_MODE:
        import shutil
        agent_binary = args.agent_type
        if args.agent_type == "claude":
            agent_binary = "claude"
        
        if shutil.which(agent_binary) is None:
            message = f"Agent CLI '{agent_binary}' not found in path. Required for agentic grading mode."
            diagnostics.record(
                severity="error",
                code="preflight_missing_agent_cli",
                stage="preflight",
                message=message,
            )
            ui.error(message)
            return abort_preflight(2, ui, diagnostics, args.output_dir)
    else:
        if args.ocr_char_threshold != DEFAULT_OCR_CHAR_THRESHOLD:
            message = "--ocr-char-threshold is ignored in unified mode."
            diagnostics.record(
                severity="warning",
                code="preflight_unified_ocr_threshold_ignored",
                stage="preflight",
                message=message,
            )
            ui.warning(message)

    required_paths = [
        ("Submissions directory", args.submissions_dir),
        ("Solutions PDF", args.solutions_pdf),
        ("Rubric YAML", args.rubric_yaml),
        ("Grade template CSV", args.grades_template_csv),
    ]
    for label, path in required_paths:
        if not path.exists():
            message = f"{label} not found: {path}"
            diagnostics.record(
                severity="error",
                code="preflight_missing_path",
                stage="preflight",
                message=message,
            )
            ui.error(message)
            return abort_preflight(2, ui, diagnostics, args.output_dir)

    for label, path in (
        ("Output directory", args.output_dir),
        ("Temp directory", args.temp_dir),
        ("Cache directory", args.cache_dir),
    ):
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            message = f"Failed to prepare {label.lower()} at {path}: {exc}"
            diagnostics.record(
                severity="error",
                code="preflight_directory_create_failed",
                stage="preflight",
                message=message,
                exc=exc,
            )
            ui.error(message)
            return abort_preflight(2, ui, diagnostics, args.output_dir)

    try:
        rubric = load_rubric(args.rubric_yaml)
    except Exception as exc:
        message = f"Failed to load rubric YAML {args.rubric_yaml}: {exc}"
        diagnostics.record(
            severity="error",
            code="rubric_load_failed",
            stage="rubric_load",
            message=message,
            exc=exc,
        )
        ui.error(message)
        return abort_preflight(1, ui, diagnostics, args.output_dir)

    try:
        units = discover_submission_units(args.submissions_dir)
    except Exception as exc:
        message = f"Failed to discover submissions in {args.submissions_dir}: {exc}"
        diagnostics.record(
            severity="error",
            code="preflight_discovery_failed",
            stage="preflight",
            message=message,
            exc=exc,
        )
        ui.error(message)
        return abort_preflight(2, ui, diagnostics, args.output_dir)

    if args.student_filter:
        try:
            pattern = re.compile(args.student_filter, flags=re.IGNORECASE)
        except re.error as exc:
            message = f"Invalid --student-filter regex '{args.student_filter}': {exc}"
            diagnostics.record(
                severity="error",
                code="preflight_invalid_student_filter",
                stage="preflight",
                message=message,
                exc=exc,
            )
            ui.error(message)
            return abort_preflight(2, ui, diagnostics, args.output_dir)
        units = [unit for unit in units if pattern.search(unit.folder_path.name)]

    if not units:
        ui.info("No submission folders with PDFs found.")
        return abort_preflight(0, ui, diagnostics, args.output_dir)

    ui.info(f"Discovered {len(units)} submission folders.")
    
    # We still need to write the index audit CSV early
    try:
        audit_entries = parse_index_html(args.submissions_dir / "index.html")
    except Exception as exc:
        message = f"Failed to parse index html: {exc}"
        diagnostics.record(
            severity="error",
            code="report_write_failed",
            stage="report_write",
            message=message,
            exc=exc,
        )
        ui.error(message)
        return abort_preflight(1, ui, diagnostics, args.output_dir)

    api_key = os.getenv(args.api_key_env, "").strip()
    if not api_key and not args.dry_run:
        message = f"Environment variable {args.api_key_env} is missing. Set it or run with --dry-run."
        diagnostics.record(
            severity="error",
            code="preflight_missing_api_key",
            stage="preflight",
            message=message,
        )
        ui.error(message)
        return abort_preflight(2, ui, diagnostics, args.output_dir)

    rate_limiter = None
    if getattr(args, "rate_limit", True) and not args.dry_run:
        rate_limiter = RateLimiterRegistry()
        rpm = 5
        normalized_model = args.model.lower().strip()
        from .rate_limit import FREE_TIER_LIMITS
        for pattern, limits in FREE_TIER_LIMITS.items():
            if pattern in normalized_model:
                rpm = limits["rpm"]
                break
        max_concurrency = max(1, rpm - 1)
        if args.concurrency > max_concurrency:
            ui.warning(
                f"Concurrency clamped from {args.concurrency} → {max_concurrency} "
                f"to stay within {args.model} rate limit of {rpm} RPM."
            )
            args.concurrency = max_concurrency

    grader = None
    if not args.dry_run:
        from .llm_factory import get_llm_provider
        try:
            sig = inspect.signature(get_llm_provider)
            kwargs = {
                "provider_name": getattr(args, "provider", "gemini"),
                "api_key": api_key,
                "model": args.model,
                "cache_dir": args.cache_dir,
            }
            if "rate_limiter" in sig.parameters:
                kwargs["rate_limiter"] = rate_limiter
            grader = get_llm_provider(**kwargs)
        except Exception as exc:
            message = f"Failed to initialize LLM client: {exc}"
            diagnostics.record(
                severity="error",
                code="grading_client_init_failed",
                stage="grading",
                message=message,
                exc=exc,
            )
            ui.error(message)
            return abort_preflight(1, ui, diagnostics, args.output_dir)

    solutions_text: str | None = None
    if args.grading_mode == LEGACY_MODE:
        try:
            solutions_text = extract_pdf_text(
                args.solutions_pdf,
                temp_dir=args.temp_dir,
                ocr_char_threshold=args.ocr_char_threshold,
                gemini_api_key=api_key or None,
                gemini_model=args.extraction_model,
                rate_limiter=rate_limiter,
            ).text
        except DailyLimitExhausted as limit_exc:
            ui.error(f"⚠ Daily API limit reached: {limit_exc}")
            return abort_preflight(5, ui, diagnostics, args.output_dir)
        except Exception as exc:
            message = f"Failed to extract text from solutions PDF {args.solutions_pdf}: {exc}"
            diagnostics.record(
                severity="error",
                code="solution_extract_failed",
                stage="solution_extract",
                message=message,
                exc=exc,
            )
            ui.error(message)
            return abort_preflight(1, ui, diagnostics, args.output_dir)

    grade_points = {
        "Check Plus": args.check_plus_points,
        "Check": args.check_points,
        "Check Minus": args.check_minus_points,
        "REVIEW_REQUIRED": args.review_required_points,
    }

    config = GradingConfig(
        submissions_root=args.submissions_dir,
        output_dir=args.output_dir,
        temp_dir=args.temp_dir,
        ocr_char_threshold=args.ocr_char_threshold,
        rubric=rubric,
        rubric_yaml=args.rubric_yaml,
        solutions_text=solutions_text,
        solutions_pdf_path=args.solutions_pdf,
        grade_points=grade_points,
        grader=grader,
        grading_mode=args.grading_mode,
        agent_type=args.agent_type,
        context_cache=args.context_cache,
        context_cache_ttl_seconds=args.context_cache_ttl_seconds,
        dry_run=args.dry_run,
        locator_model=args.locator_model.strip(),
        annotate_dry_run_marks=args.annotate_dry_run_marks,
        extraction_model=args.extraction_model,
        gemini_api_key=api_key or None,
        extract_blocks=args.extract_blocks,
        diagnostics=diagnostics,
        rate_limiter=rate_limiter,
        annotation_font_size=float(getattr(args, "annotation_font_size", DEFAULT_ANNOTATION_FONT_SIZE)),
        grade_column=args.grade_column,
        identifier_column=args.identifier_column,
        comment_column=args.comment_column or None,
        grades_template_csv=args.grades_template_csv,
        model=args.model,
        concurrency=args.concurrency,
        json_output=getattr(args, "json_output", False),
        quiet=getattr(args, "quiet", False),
        cache_dir=args.cache_dir,
        force_vision_extraction=getattr(args, "force_vision_extraction", False),
    )

    orchestrator = Orchestrator(config, ui)
    # Orchestrator needs index audit CSV written early and tracked
    try:
        orchestrator.artifacts["Index audit CSV"] = write_index_audit_csv(args.output_dir, audit_entries)
    except Exception as exc:
        message = f"Failed to write index audit CSV: {exc}"
        diagnostics.record(
            severity="error",
            code="report_write_failed",
            stage="report_write",
            message=message,
            exc=exc,
        )
        ui.error(message)
        return abort_preflight(1, ui, diagnostics, args.output_dir)

    if getattr(args, "regrade_question", None):
        return orchestrator.regrade_question(args.regrade_question, units)
    return orchestrator.run(units)

if __name__ == "__main__":
    raise SystemExit(main())

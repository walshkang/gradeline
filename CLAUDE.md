CLAUDE.md — Project-level instructions for AI sessions

Repo layout (key files)
- grader/cli.py — Main grading CLI: parse_args(), main(), conclude() closure, RollingSnapshot handling, summarize_results, update_rolling_snapshot.
- grader/ui.py — Console UI: ConsoleUI base class, PlainConsoleUI and RichConsoleUI implementations, create_console_ui(), args_to_subtitle(), RunSummary.
- grader/workflow_cli.py — Profile-driven workflow CLI: build_grading_argv(), run_from_profile/run_with_optional_setup, profile quickstart and regrade flows.
- grader/gemini_client.py — LLM client adapter (GeminiGrader) used by grader for model calls.
- grader/extract.py — PDF text extraction, OCR (tesseract), pdftotext fallback, and Gemini fallback logic; ensure_binaries_present() lives here.
- grader/annotate.py — PDF annotation helpers and annotate_submission_pdfs() (mark placement, headers, fallback summaries).
- grader/types.py — Dataclasses for QuestionResult, GradeResult, SubmissionResult, TextBlock, ExtractedPdf, etc.
- grader/defaults.py — Project defaults and set_default_model() which writes configs/defaults.toml.
- grader/diagnostics.py — DiagnosticsCollector for run diagnostics and write_json().
- configs/defaults.toml — Runtime defaults (models, concurrency, OCR settings).
- .manual_runs/profiles/ — Local workflow profile TOMLs (profile-driven grading settings).

Exit codes
- 0 = full success
- 3 = some REVIEW_REQUIRED (no errors)
- 4 = some grading errors
- 1 = report I/O failure
- 2 = input/preflight error
- 130 = user abort

Running tests
source .venv/bin/activate && python -m pytest tests/ -x -q

Key conventions (verified in code)
- ConsoleUI is the UI base in grader/ui.py; PlainConsoleUI and RichConsoleUI implement its methods. create_console_ui(force_plain=...) chooses PlainConsoleUI when force_plain=True or when stdout is not a TTY or Rich is unavailable; otherwise RichConsoleUI is used.
- --plain: CLI provides --plain (parser.add_argument("--plain")) and callers pass args.plain into create_console_ui(). Workflow profiles can set plain via build_grading_argv() mappings. GRADELINE_PLAIN also forces plain UI when set to 1/true/yes.
- New CLI flags: add to parse_args() in grader/cli.py. If a flag/value should be profile-configurable, add it to CLI_FLAG_MAPPINGS or CLI_VALUE_MAPPINGS in grader/workflow_cli.py so build_grading_argv() will emit it from a GradeProfile.
- RollingSnapshot: update_rolling_snapshot() is used inside annotate_and_finish() (workflow_cli.py) to maintain a RollingSnapshot; the current snapshot is passed as snapshot= to ui.submission_finished(...).
- conclude(): implemented as a closure inside main() in grader/cli.py with access to args, rolling, diagnostics, and artifacts; it emits summary, records diagnostics, and returns the final exit code.
- New grader profile fields: add to GradeProfile dataclass, include the key in ALLOWED_GRADE_KEYS/REQUIRED_GRADE_KEYS, and add the field to the appropriate type set (PATH_GRADE_FIELDS, INT_GRADE_FIELDS, FLOAT_GRADE_FIELDS, BOOL_GRADE_FIELDS, STRING_GRADE_FIELDS or POINT_GRADE_FIELDS) in grader/workflow_profile.py.

Agent invocation example
```bash
# Grade silently and capture structured result (--quiet and --json available after Slice D)
python3 -m grader.cli \
  --submissions-dir "..." --solutions-pdf "..." \
  --rubric-yaml "..." --grades-template-csv "..." \
  --grade-column "..." --output-dir "..." \
  --grading-mode unified --plain
EXIT=$? # 0=success, 3=review_required, 4=errors, 1=io_failure, 2=bad_input
```

Keep this file concise — it is loaded into every AI session context.

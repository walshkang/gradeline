# Plan: TUI + Agent-Friendly CLI

**Status:** Ready to implement  
**Parallelization:** Wave 1 (Blocks 1 + 3 + 4 in parallel) → Wave 2 (Block 2)

---

## Context

Gradeline has a solid two-tier UI (RichConsoleUI / PlainConsoleUI) but several gaps make it feel unpolished for humans and unreliable for AI agents:

- **Humans**: Progress bar shows no count ("14/37") or ETA. Rolling band distribution (`RollingSnapshot`) is calculated after every submission and passed to `submission_finished()` but is silently ignored.
- **Agents**: Exit code `0` means both "all OK" and "some need manual review" — an agent can't tell the difference. No structured stdout output. `--plain` suppresses Rich but still emits status lines. No `CLAUDE.md` to orient an AI assistant session.

---

## Slices + Agent Assignment

### Wave 1 — Run in parallel (no shared files)

---

#### Slice A — Exit codes  
**Agent level:** Sonnet  
**Files:** `grader/cli.py`, `grader/workflow_cli.py`, `tests/test_cli_ui.py`, `tests/test_workflow_cli.py`

New exit code table:

| Code | Meaning |
|---|---|
| `0` | All submissions succeeded, no review required (unchanged) |
| `3` | Run completed; some submissions are REVIEW_REQUIRED (no errors) |
| `4` | Run completed; some submissions failed with grading errors |
| `1` | Report write failure — I/O error writing CSV (unchanged) |
| `2` | CLI / preflight input error (unchanged) |
| `130` | User abort via Ctrl+C (unchanged) |

**Change 1 — `conclude()` in `grader/cli.py`:**

After `summarize_results()` returns `summary`, remap `exit_code` when it is currently `0`:

```python
if exit_code == 0 and not getattr(args, "dry_run", False):
    if summary.failed_with_error_count > 0:
        exit_code = 4
    elif summary.review_required_count > 0:
        exit_code = 3
```

The `dry_run` guard is critical: dry-run marks all questions `needs_review`, which would otherwise always fire exit code 3.

**Change 2 — four gates in `grader/workflow_cli.py`:**

Lines 400, 512, 599, 693 all read `if exit_code != 0: return exit_code` before launching the review server. With codes 3 and 4, grading completed and the user needs to review results — the server should still launch. Change all four to:

```python
if exit_code in (1, 2):
    return exit_code
```

**Change 3 — tests:**

`test_cli_ui.py` and `test_workflow_cli.py` assert `exit_code == 0` in some places. The `dry_run` guard fixes dry-run cases. For any test that produces real REVIEW_REQUIRED submissions, update the assertion to `assertIn(exit_code, (0, 3))`.

---

#### Slice B — Live count + ETA in progress bar  
**Agent level:** Haiku  
**Files:** `grader/ui.py` only

**Change 1 — `RichConsoleUI.start_progress()`:**

Add `MofNCompleteColumn` ("14/37") and `TimeRemainingColumn` (ETA). Both are standard Rich built-ins. Update the import in `ui.py`:

```python
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress, SpinnerColumn,
    TextColumn, TimeElapsedColumn, TimeRemainingColumn,
)
```

Updated `start_progress`:
```python
self._progress = Progress(
    SpinnerColumn(),
    TextColumn("[bold blue]{task.description}", justify="left"),
    BarColumn(bar_width=25),
    MofNCompleteColumn(),
    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    TimeElapsedColumn(),
    TimeRemainingColumn(),
    console=self.console,
)
```

Wrap both new column imports in the existing `try/except ImportError` block at top of `ui.py` as a fallback.

**Change 2 — `RichConsoleUI.submission_finished()` rolling tally:**

`snapshot` is already passed but ignored. After the rationale line, add:

```python
if snapshot is not None and getattr(snapshot, "band_counts", None):
    parts = []
    for band_key in ("CHECK_PLUS", "CHECK", "CHECK_MINUS", "REVIEW_REQUIRED"):
        n = snapshot.band_counts.get(band_key, 0)
        if n:
            color = _BAND_COLORS.get(band_key, "white")
            label = band_key.replace("_", " ").title()
            parts.append(f"[{color}]{label}:{n}[/{color}]")
    if parts:
        self.console.print(f"  [dim]tally:[/dim] {' '.join(parts)}")
```

`PlainConsoleUI` needs no changes for this.

---

#### Slice C — `CLAUDE.md` at repo root  
**Agent level:** Haiku  
**Files:** New file `CLAUDE.md` at repo root

Content to include:
- Repo layout: key files and one-line purpose each
- Exit code table (matching Slice A)
- How to run tests: `source .venv/bin/activate && python -m pytest tests/ -x -q`
- Key conventions:
  - `ConsoleUI` is an ABC — both `PlainConsoleUI` and `RichConsoleUI` must implement every new method
  - `--plain` flag and `GRADELINE_PLAIN` env var both force `PlainConsoleUI`
  - New CLI flags: add to `parse_args()` in `cli.py` AND to `build_grading_argv()` mappings in `workflow_cli.py` if they should be profile-configurable
  - `RollingSnapshot` is computed in `annotate_and_finish()` and passed as `snapshot=` to `submission_finished()`
  - `conclude()` is a closure inside `main()` with access to `args`, `rolling`, `diagnostics`, `artifacts`
- Agent invocation example (preview of Slice D's `--json --quiet`)

---

### Wave 2 — After Wave 1 completes

---

#### Slice D — `--json` + `--quiet` flags  
**Agent level:** Sonnet  
**Files:** `grader/cli.py`, `grader/ui.py`  
**Depends on:** Slice A (needs correct `exit_code` value to embed in JSON)

**Change 1 — `parse_args()` in `grader/cli.py`:**

```python
parser.add_argument("--json", dest="json_output", action="store_true", default=False,
    help="Emit a JSON summary to stdout on completion (agent-friendly).")
parser.add_argument("--quiet", action="store_true", default=False,
    help="Suppress all non-error output. Implies --plain. Errors still go to stderr.")
```

**Change 2 — env var handling in `main()` (add after `parse_args`):**

```python
if os.environ.get("GRADELINE_JSON"):
    args.json_output = True
if os.environ.get("GRADELINE_QUIET"):
    args.quiet = True
if args.quiet:
    args.plain = True
```

**Change 3 — `QuietConsoleUI` in `grader/ui.py`:**

Thin subclass of `PlainConsoleUI` that no-ops all stdout methods. `error()` and `warning()` (stderr) are inherited unchanged:

```python
class QuietConsoleUI(PlainConsoleUI):
    def banner(self, *a, **kw): pass
    def info(self, *a, **kw): pass
    def section_heading(self, *a, **kw): pass
    def submission_started(self, *a, **kw): pass
    def submission_finished(self, *a, **kw): pass
    def emit_artifacts(self, *a, **kw): pass
    def emit_summary(self, *a, **kw): pass
    def status(self, *a, **kw): pass
    def clear_status(self, *a, **kw): pass
    def start_progress(self, *a, **kw): pass
    def advance_progress(self, *a, **kw): pass
    def stop_progress(self, *a, **kw): pass
```

Update `create_console_ui(*, force_plain=False, quiet=False)` to return `QuietConsoleUI()` when `quiet=True`.

Update call site in `main()`:
```python
ui = create_console_ui(force_plain=args.plain or args.quiet, quiet=args.quiet)
```

**Change 4 — JSON emission in `conclude()`:**

After `ui.emit_artifacts(...)`, add:

```python
if getattr(args, "json_output", False):
    import json as _json
    payload = {
        "exit_code": exit_code,
        "submissions_processed": summary.submissions_processed,
        "success_count": summary.success_count,
        "review_required_count": summary.review_required_count,
        "failed_with_error_count": summary.failed_with_error_count,
        "warning_count": summary.warning_count,
        "band_counts": summary.band_counts or {},
        "mean_seconds_per_submission": summary.mean_seconds,
        "artifacts": {k: str(v) for k, v in artifacts.items() if v is not None},
        "diagnostics_file": str(diagnostics_path),
    }
    sys.stdout.write(_json.dumps(payload) + "\n")
    sys.stdout.flush()
```

Raw `sys.stdout.write` bypasses the UI layer — works correctly with `--quiet`.

---

## Agent Prompts

Copy-paste prompts for each slice. Hand each to a fresh coding agent in a worktree.

---

### Prompt — Slice A (Exit codes)

```
You are implementing Slice A of docs/plans/tui-agent-improvements.md in the gradeline repo at /Users/walsh.kang/Documents/GitHub/gradeline.

## What to build

Add meaningful exit codes to the grading CLI so agents can interpret outcomes without parsing files.

New exit code table:
- 0 = all submissions succeeded, no review required (unchanged)
- 3 = run completed; some submissions are REVIEW_REQUIRED (no grading errors)
- 4 = run completed; some submissions had grading errors
- 1 = report write failure (unchanged)
- 2 = CLI/preflight input error (unchanged)
- 130 = user abort (unchanged)

## Changes required

**1. grader/cli.py — conclude() closure**

Read the full conclude() function first. It already computes `summary` via `summarize_results()`. After that call, add exit code remapping when exit_code is currently 0:

```python
if exit_code == 0 and not getattr(args, "dry_run", False):
    if summary.failed_with_error_count > 0:
        exit_code = 4
    elif summary.review_required_count > 0:
        exit_code = 3
```

The dry_run guard is critical — dry-run marks all questions needs_review, which would otherwise always fire exit code 3.

**2. grader/workflow_cli.py — four review server gates**

Lines ~400, ~512, ~599, ~693 all contain `if exit_code != 0: return exit_code` immediately before launching the review server. With codes 3 and 4, grading still completed and the review server should launch. Change all four occurrences to:

```python
if exit_code in (1, 2):
    return exit_code
```

Find them by searching for the pattern — don't rely on exact line numbers.

**3. tests/test_cli_ui.py and tests/test_workflow_cli.py**

Read the existing tests first. The dry_run guard above will keep dry-run-based tests returning 0. For any test that invokes real mock grading and asserts exit_code == 0 where REVIEW_REQUIRED submissions could be produced, update the assertion to `assertIn(exit_code, (0, 3))`. Don't change tests that explicitly test error/invalid paths returning 2.

## Verification

```bash
source .venv/bin/activate
python -m pytest tests/test_cli_ui.py tests/test_workflow_cli.py -x -q
```

All tests must pass. Do not add new tests — only fix assertions that break due to the new exit codes.
```

---

### Prompt — Slice B (Progress bar count + ETA + rolling tally)

```
You are implementing Slice B of docs/plans/tui-agent-improvements.md in the gradeline repo at /Users/walsh.kang/Documents/GitHub/gradeline.

## What to build

Two changes to grader/ui.py only — no other files touched.

**1. Add count and ETA columns to the Rich progress bar**

Read RichConsoleUI.start_progress() first. It currently creates a Progress with SpinnerColumn, TextColumn (description), BarColumn, percentage TextColumn, and TimeElapsedColumn.

Add MofNCompleteColumn (shows "14/37") and TimeRemainingColumn (shows ETA). Both are standard Rich built-ins. New start_progress():

```python
self._progress = Progress(
    SpinnerColumn(),
    TextColumn("[bold blue]{task.description}", justify="left"),
    BarColumn(bar_width=25),
    MofNCompleteColumn(),
    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    TimeElapsedColumn(),
    TimeRemainingColumn(),
    console=self.console,
)
```

Update the rich.progress import at the top of ui.py to include the two new column types. They are in the same `try/except ImportError` block as the existing Rich imports — keep the fallback pattern.

**2. Show rolling band tally in submission_finished()**

Read RichConsoleUI.submission_finished() first. It already receives a `snapshot` parameter (a RollingSnapshot dataclass with band_counts dict) but currently ignores it.

After the existing rationale line output, add:

```python
if snapshot is not None and getattr(snapshot, "band_counts", None):
    parts = []
    for band_key in ("CHECK_PLUS", "CHECK", "CHECK_MINUS", "REVIEW_REQUIRED"):
        n = snapshot.band_counts.get(band_key, 0)
        if n:
            color = _BAND_COLORS.get(band_key, "white")
            label = band_key.replace("_", " ").title()
            parts.append(f"[{color}]{label}:{n}[/{color}]")
    if parts:
        self.console.print(f"  [dim]tally:[/dim] {' '.join(parts)}")
```

_BAND_COLORS is already defined in ui.py. PlainConsoleUI.submission_finished() does not need changes.

## Verification

```bash
source .venv/bin/activate
python -m pytest tests/test_cli_ui.py -x -q
```

All tests must pass. Do not modify any test files.
```

---

### Prompt — Slice C (CLAUDE.md)

```
You are implementing Slice C of docs/plans/tui-agent-improvements.md in the gradeline repo at /Users/walsh.kang/Documents/GitHub/gradeline.

## What to build

Create CLAUDE.md at the repo root (/Users/walsh.kang/Documents/GitHub/gradeline/CLAUDE.md). This is the project-level instructions file that Claude Code loads at the start of every session in this repo.

Before writing, read these files to get accurate details:
- grader/cli.py (skim for parse_args, main, conclude, RollingSnapshot, summarize_results)
- grader/ui.py (skim for ConsoleUI, PlainConsoleUI, RichConsoleUI, create_console_ui)
- grader/workflow_cli.py (skim for build_grading_argv, run_with_optional_setup)
- grader/defaults.py
- grader/diagnostics.py
- configs/defaults.toml

## Required content

1. **Repo layout** — one line per key file describing its purpose. At minimum: grader/cli.py, grader/ui.py, grader/workflow_cli.py, grader/gemini_client.py, grader/extract.py, grader/annotate.py, grader/types.py, grader/defaults.py, grader/diagnostics.py, configs/defaults.toml, .manual_runs/profiles/

2. **Exit codes** — exact table:
   - 0 = full success
   - 3 = some REVIEW_REQUIRED (no errors)
   - 4 = some grading errors
   - 1 = report I/O failure
   - 2 = input/preflight error
   - 130 = user abort

3. **Running tests** — `source .venv/bin/activate && python -m pytest tests/ -x -q`

4. **Key conventions** (accurate — verify against the code before writing):
   - ConsoleUI is an ABC; both PlainConsoleUI and RichConsoleUI must implement every method
   - --plain flag and GRADELINE_PLAIN env var both force PlainConsoleUI
   - New CLI flags go in parse_args() in cli.py; add to build_grading_argv() mappings in workflow_cli.py if they should be profile-configurable
   - RollingSnapshot is computed in annotate_and_finish() and passed as snapshot= to submission_finished()
   - conclude() is a closure inside main() with access to args, rolling, diagnostics, artifacts
   - New grader profile fields: add to GradeProfile dataclass, ALLOWED_GRADE_KEYS, and the appropriate type set in workflow_profile.py

5. **Agent invocation example**:
   ```bash
   # Grade silently and capture structured result (--quiet and --json available after Slice D)
   python3 -m grader.cli \
     --submissions-dir "..." --solutions-pdf "..." \
     --rubric-yaml "..." --grades-template-csv "..." \
     --grade-column "..." --output-dir "..." \
     --grading-mode unified --plain
   EXIT=$?
   # 0=success, 3=review_required, 4=errors, 1=io_failure, 2=bad_input
   ```

Keep it concise — this file is loaded into every AI session's context window.
```

---

### Prompt — Slice D (--json + --quiet flags)

```
You are implementing Slice D of docs/plans/tui-agent-improvements.md in the gradeline repo at /Users/walsh.kang/Documents/GitHub/gradeline.

Slice A (exit codes) must already be merged before running this slice — this slice embeds the exit_code value in the JSON output.

## What to build

Add --json and --quiet flags to the grading CLI so agents can get clean structured output.

**Files to modify: grader/cli.py and grader/ui.py**

## Changes

**1. parse_args() in grader/cli.py — add two new arguments**

```python
parser.add_argument("--json", dest="json_output", action="store_true", default=False,
    help="Emit a JSON summary to stdout on completion (agent-friendly).")
parser.add_argument("--quiet", action="store_true", default=False,
    help="Suppress all non-error output. Implies --plain. Errors still go to stderr.")
```

**2. main() in grader/cli.py — add env var handling**

After parse_args() returns, before ui is constructed, add:

```python
if os.environ.get("GRADELINE_JSON"):
    args.json_output = True
if os.environ.get("GRADELINE_QUIET"):
    args.quiet = True
if args.quiet:
    args.plain = True
```

Also update the create_console_ui() call to pass quiet:
```python
ui = create_console_ui(force_plain=args.plain or args.quiet, quiet=args.quiet)
```

**3. QuietConsoleUI in grader/ui.py**

Add this class after PlainConsoleUI (before RichConsoleUI). It is a thin subclass that no-ops all stdout output methods. error() and warning() are inherited from PlainConsoleUI unchanged (they write to stderr):

```python
class QuietConsoleUI(PlainConsoleUI):
    def banner(self, *a, **kw): pass
    def info(self, *a, **kw): pass
    def section_heading(self, *a, **kw): pass
    def submission_started(self, *a, **kw): pass
    def submission_finished(self, *a, **kw): pass
    def emit_artifacts(self, *a, **kw): pass
    def emit_summary(self, *a, **kw): pass
    def status(self, *a, **kw): pass
    def clear_status(self, *a, **kw): pass
    def start_progress(self, *a, **kw): pass
    def advance_progress(self, *a, **kw): pass
    def stop_progress(self, *a, **kw): pass
    def add_submission_task(self, *a, **kw): return 0
    def update_submission_task(self, *a, **kw): pass
    def remove_submission_task(self, *a, **kw): pass
```

Update create_console_ui() signature to accept quiet=False and return QuietConsoleUI() when quiet=True (check before the force_plain check).

**4. conclude() closure in grader/cli.py — emit JSON**

Read conclude() fully first. After ui.emit_artifacts(...) and ui.emit_summary(...), add the JSON emission block. conclude() already has access to args, diagnostics_path, artifacts (dict of label→Path), and summary (RunSummary dataclass). The exit_code at this point already reflects the new codes from Slice A.

```python
if getattr(args, "json_output", False):
    import json as _json
    payload = {
        "exit_code": exit_code,
        "submissions_processed": summary.submissions_processed,
        "success_count": summary.success_count,
        "review_required_count": summary.review_required_count,
        "failed_with_error_count": summary.failed_with_error_count,
        "warning_count": summary.warning_count,
        "band_counts": summary.band_counts or {},
        "mean_seconds_per_submission": summary.mean_seconds,
        "artifacts": {k: str(v) for k, v in artifacts.items() if v is not None},
        "diagnostics_file": str(diagnostics_path),
    }
    sys.stdout.write(_json.dumps(payload) + "\n")
    sys.stdout.flush()
```

Use raw sys.stdout.write — not print(), not ui.info() — so it bypasses the UI layer and emits even when --quiet is active.

## Verification

```bash
source .venv/bin/activate
python -m pytest tests/ -x -q

# --quiet should suppress all stdout except errors
python3 -m grader.cli \
  --submissions-dir /tmp/fake --solutions-pdf /tmp/fake.pdf \
  --rubric-yaml /tmp/fake.yaml --grades-template-csv /tmp/fake.csv \
  --grade-column "X" --output-dir /tmp/out \
  --quiet --plain 2>/dev/null
# should produce no output (will error on missing files, but stdout should be empty)

# GRADELINE_QUIET env var should behave identically
GRADELINE_QUIET=1 python3 -m grader.cli ... 2>/dev/null
```

All existing tests must pass. Add no new tests.
```

---

## Verification

```bash
source .venv/bin/activate

# All tests pass
python -m pytest tests/ -x -q

# Dry-run returns 0 (not 3)
python3 -m grader.cli \
  --submissions-dir "data/a4/submissions" --solutions-pdf "data/a4/solutions.pdf" \
  --rubric-yaml "configs/a4.yaml" --grades-template-csv "data/a4/grades.csv" \
  --grade-column "Assignment 4 Points Grade" --output-dir "/tmp/test_out" \
  --dry-run --plain; echo "exit: $?"   # expect: 0

# Agent mode: only one JSON line on stdout
python3 -m grader.cli ... --json --quiet 2>/dev/null; echo "exit: $?"

# Progress bar shows count and ETA (run 2-student batch)
python3 -m grader.workflow_cli run --profile .manual_runs/profiles/assignment4.toml \
  --student-filter "Dhaval Patel|Brittney Jones"
# expect: progress bar shows "2/2" and ETA column
```

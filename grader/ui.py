
from __future__ import annotations

import itertools
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised through create_console_ui tests.
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
    from rich.rule import Rule
    from rich.table import Table

    _RICH_AVAILABLE = True
except Exception:  # noqa: BLE001
    Console = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
    Rule = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]
    Progress = None  # type: ignore[assignment]
    _RICH_AVAILABLE = False


# Band color mapping
_BAND_COLORS: dict[str, str] = {
    "CHECK_PLUS": "green",
    "CHECK": "cyan",
    "CHECK_MINUS": "yellow",
    "REVIEW_REQUIRED": "red",
}

# Human-friendly band display names
_BAND_DISPLAY: dict[str, str] = {
    "CHECK_PLUS": "Check+",
    "CHECK": "Check",
    "CHECK_MINUS": "Check−",
    "REVIEW_REQUIRED": "Review Required",
}


@dataclass(frozen=True)
class RunSummary:
    submissions_processed: int
    success_count: int
    review_required_count: int
    failed_with_error_count: int
    warning_count: int
    band_counts: dict[str, int] | None = None
    mean_seconds: float | None = None
    total_seconds: float | None = None


class ConsoleUI:
    def banner(self, title: str, subtitle: str = "") -> None:
        raise NotImplementedError

    def info(self, message: str) -> None:
        raise NotImplementedError

    def warning(self, message: str) -> None:
        raise NotImplementedError

    def error(self, message: str) -> None:
        raise NotImplementedError

    def submission_started(self, index: int, total: int, folder_name: str) -> None:
        raise NotImplementedError

    def submission_finished(
        self,
        index: int,
        total: int,
        folder_name: str,
        *,
        band: str,
        had_error: bool,
        rationale: str = "",
        elapsed_seconds: float = 0.0,
        snapshot: Any = None,
    ) -> None:
        raise NotImplementedError

    def emit_artifacts(self, artifacts: dict[str, Path | None]) -> None:
        raise NotImplementedError

    def emit_summary(self, summary: RunSummary) -> None:
        raise NotImplementedError

    def status(self, message: str) -> None:
        raise NotImplementedError

    def clear_status(self) -> None:
        raise NotImplementedError

    def start_progress(self, total: int) -> None:
        """Start a progress bar for batch grading."""

    def advance_progress(self) -> None:
        """Advance the progress bar by one step."""

    def stop_progress(self) -> None:
        """Stop and remove the progress bar."""

    def section_heading(self, title: str) -> None:
        """Print a prominent section divider."""
        raise NotImplementedError

    def add_submission_task(self, folder_name: str, total_questions: int) -> int:
        """Register a per-submission progress task and return its task id."""
        raise NotImplementedError

    def update_submission_task(self, task_id: int, current: int, question_id: str) -> None:
        """Update the per-submission task with current question progress."""
        raise NotImplementedError

    def remove_submission_task(self, task_id: int) -> None:
        """Remove or hide a per-submission task when grading completes."""
        raise NotImplementedError


class PlainConsoleUI(ConsoleUI):
    def __init__(self) -> None:
        self._status_active = False
        self._status_width = 0
        self._task_counter = itertools.count(1)
        self._task_lock = threading.Lock()
        self._tasks: dict[int, tuple[str, int]] = {}

    def banner(self, title: str, subtitle: str = "") -> None:
        self.clear_status()
        print(f"=== {title} ===")
        if subtitle:
            print(subtitle)

    def info(self, message: str) -> None:
        self.clear_status()
        print(message)

    def warning(self, message: str) -> None:
        self.clear_status()
        print(f"[WARN] {message}")

    def error(self, message: str) -> None:
        self.clear_status()
        print(f"[ERROR] {message}", file=sys.stderr)

    def submission_started(self, index: int, total: int, folder_name: str) -> None:
        self.clear_status()
        print(f"[{index}/{total}] grading {folder_name}")

    def submission_finished(
        self,
        index: int,
        total: int,
        folder_name: str,
        *,
        band: str,
        had_error: bool,
        rationale: str = "",
        elapsed_seconds: float = 0.0,
        snapshot: Any = None,
    ) -> None:
        self.clear_status()
        if had_error:
            status = "FAILED"
        elif band == "REVIEW_REQUIRED":
            status = "REVIEW"
        else:
            status = "OK"
        line = f"[{index}/{total}] {status} {folder_name} -> {_BAND_DISPLAY.get(band, band)}"
        if elapsed_seconds:
            line += f" ({elapsed_seconds:.1f}s)"
        print(line)
        if rationale:
            print(f"  {rationale}")

    def emit_artifacts(self, artifacts: dict[str, Path | None]) -> None:
        self.clear_status()
        print("Artifacts:")
        for label, path in artifacts.items():
            if path is None:
                continue
            print(f"  {label}: {path}")

    def emit_summary(self, summary: RunSummary) -> None:
        self.clear_status()
        print("Run Summary")
        print(f"  Submissions processed: {summary.submissions_processed}")
        print(f"  Success count: {summary.success_count}")
        print(f"  Review required count: {summary.review_required_count}")
        print(f"  Failed with error count: {summary.failed_with_error_count}")
        print(f"  Warning count: {summary.warning_count}")
        if summary.band_counts:
            dist = ", ".join(f"{_BAND_DISPLAY.get(b, b)}: {c}" for b, c in sorted(summary.band_counts.items()))
            print(f"  Band distribution: {dist}")
        if summary.mean_seconds is not None:
            print(f"  Mean time per submission: {summary.mean_seconds:.1f}s")
        if summary.total_seconds is not None:
            print(f"  Total grading time: {summary.total_seconds:.1f}s")

    def section_heading(self, title: str) -> None:
        self.clear_status()
        print(f"\n--- {title} ---")

    def status(self, message: str) -> None:
        clean = " ".join(message.split())
        width = max(self._status_width, len(clean))
        self._status_width = width
        print(f"\r{clean.ljust(width)}", end="", flush=True)
        self._status_active = True

    def clear_status(self) -> None:
        if not self._status_active:
            return
        print(f"\r{' ' * self._status_width}\r", end="", flush=True)
        self._status_active = False
        self._status_width = 0

    def add_submission_task(self, folder_name: str, total_questions: int) -> int:
        with self._task_lock:
            task_id = next(self._task_counter)
            self._tasks[task_id] = (folder_name, total_questions)
        print(f"[grading] {folder_name} ({total_questions} questions)")
        return task_id

    def update_submission_task(self, task_id: int, current: int, question_id: str) -> None:
        with self._task_lock:
            meta = self._tasks.get(task_id)
        if meta is None:
            return
        folder_name, total_questions = meta
        # Simple textual progress; no attempt to overwrite in-place to keep concurrency safe.
        print(f"[grading] {folder_name}: question {question_id} ({current}/{total_questions})")

    def remove_submission_task(self, task_id: int) -> None:
        with self._task_lock:
            meta = self._tasks.pop(task_id, None)
        if meta is None:
            return
        folder_name, _ = meta
        print(f"[grading] {folder_name}: finished")


class QuietConsoleUI(PlainConsoleUI):
    def banner(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def section_heading(self, *a, **kw):
        pass

    def submission_started(self, *a, **kw):
        pass

    def submission_finished(self, *a, **kw):
        pass

    def emit_artifacts(self, *a, **kw):
        pass

    def emit_summary(self, *a, **kw):
        pass

    def status(self, *a, **kw):
        pass

    def clear_status(self, *a, **kw):
        pass

    def start_progress(self, *a, **kw):
        pass

    def advance_progress(self, *a, **kw):
        pass

    def stop_progress(self, *a, **kw):
        pass

    def add_submission_task(self, *a, **kw):
        return 0

    def update_submission_task(self, *a, **kw):
        pass

    def remove_submission_task(self, *a, **kw):
        pass


class RichConsoleUI(ConsoleUI):
    def __init__(self) -> None:
        if not _RICH_AVAILABLE:
            raise RuntimeError("Rich is not available.")
        self.console = Console()  # type: ignore[misc]
        self.err_console = Console(stderr=True)  # type: ignore[misc]
        self._status_ctx: Any | None = None
        self._progress: Any | None = None
        self._progress_task: Any | None = None
        self._submission_meta: dict[int, tuple[str, int]] = {}

    def banner(self, title: str, subtitle: str = "") -> None:
        self.clear_status()
        text = title if not subtitle else f"{title}\n[dim]{subtitle}[/dim]"
        self.console.print(Panel.fit(text, border_style="blue"))

    def info(self, message: str) -> None:
        self.clear_status()
        self.console.print(f"[white]{message}[/white]")

    def warning(self, message: str) -> None:
        self.clear_status()
        self.console.print(f"[yellow]⚠[/yellow] {message}")

    def error(self, message: str) -> None:
        self.clear_status()
        self.err_console.print(f"[red bold]✗[/red bold] {message}")

    def submission_started(self, index: int, total: int, folder_name: str) -> None:
        self.clear_status()
        self.console.print(f"[cyan][{index}/{total}][/cyan] grading [bold]{folder_name}[/bold]")

    def submission_finished(
        self,
        index: int,
        total: int,
        folder_name: str,
        *,
        band: str,
        had_error: bool,
        rationale: str = "",
        elapsed_seconds: float = 0.0,
        snapshot: Any = None,
    ) -> None:
        self.clear_status()
        if had_error:
            status = "[red]✗ FAILED[/red]"
        elif band == "REVIEW_REQUIRED":
            status = "[yellow]⟳ REVIEW[/yellow]"
        else:
            status = "[green]✓ OK[/green]"
        band_color = _BAND_COLORS.get(band, "white")
        band_label = _BAND_DISPLAY.get(band, band)
        time_str = f" [dim]({elapsed_seconds:.1f}s)[/dim]" if elapsed_seconds else ""
        self.console.print(
            f"[cyan][{index}/{total}][/cyan] {status} [bold]{folder_name}[/bold] → [{band_color}]{band_label}[/{band_color}]{time_str}"
        )
        if rationale:
            self.console.print(f"  [dim]{rationale}[/dim]")
        if snapshot is not None and getattr(snapshot, "band_counts", None):
            parts = []
            for band_key in ("CHECK_PLUS", "CHECK", "CHECK_MINUS", "REVIEW_REQUIRED"):
                n = snapshot.band_counts.get(band_key, 0)
                if n:
                    color = _BAND_COLORS.get(band_key, "white")
                    label = band_key.replace("_", " ").title()
                    parts.append(f"[{color}]{label}:{n}[/{color}]")
            if parts:
                self.console.print(f" [dim]tally:[/dim] {' '.join(parts)}")
        self.advance_progress()

    def emit_artifacts(self, artifacts: dict[str, Path | None]) -> None:
        self.clear_status()
        table = Table(title="Artifacts", show_header=True, header_style="bold blue", border_style="dim")
        table.add_column("Output")
        table.add_column("Path", overflow="fold")
        for label, path in artifacts.items():
            if path is None:
                continue
            table.add_row(label, str(path))
        self.console.print(table)

    def emit_summary(self, summary: RunSummary) -> None:
        self.clear_status()
        table = Table(title="Run Summary", show_header=True, header_style="bold blue", border_style="dim")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Submissions processed", str(summary.submissions_processed))
        table.add_row(
            "Success count",
            f"[green]{summary.success_count}[/green]" if summary.success_count else "0",
        )
        table.add_row(
            "Review required",
            f"[yellow]{summary.review_required_count}[/yellow]" if summary.review_required_count else "0",
        )
        table.add_row(
            "Failed with error",
            f"[red]{summary.failed_with_error_count}[/red]" if summary.failed_with_error_count else "0",
        )
        table.add_row(
            "Warnings",
            f"[yellow]{summary.warning_count}[/yellow]" if summary.warning_count else "0",
        )
        if summary.band_counts:
            dist = ", ".join(
                f"[{_BAND_COLORS.get(b, 'white')}]{_BAND_DISPLAY.get(b, b)}: {c}[/{_BAND_COLORS.get(b, 'white')}]"
                for b, c in sorted(summary.band_counts.items())
            )
            table.add_row("Band distribution", dist)
        if summary.mean_seconds is not None:
            table.add_row("Mean time/submission", f"{summary.mean_seconds:.1f}s")
        if summary.total_seconds is not None:
            table.add_row("Total grading time", f"{summary.total_seconds:.1f}s")
        self.console.print(table)

    def section_heading(self, title: str) -> None:
        self.clear_status()
        self.console.print()
        self.console.print(Rule(f"[bold blue]{title}[/bold blue]", style="blue"))

    def status(self, message: str) -> None:
        text = " ".join(message.split())
        if self._status_ctx is None:
            self._status_ctx = self.console.status(text, spinner="dots")
            self._status_ctx.__enter__()
            return
        self._status_ctx.update(text)

    def clear_status(self) -> None:
        if self._status_ctx is None:
            return
        self._status_ctx.__exit__(None, None, None)
        self._status_ctx = None

    def start_progress(self, total: int) -> None:
        if self._progress is not None:
            return
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
        self._progress_task = self._progress.add_task("grading", total=total)
        self._progress.__enter__()

    def advance_progress(self) -> None:
        if self._progress is not None and self._progress_task is not None:
            self._progress.advance(self._progress_task)

    def stop_progress(self) -> None:
        if self._progress is not None:
            self._progress.__exit__(None, None, None)
            self._progress = None
            self._progress_task = None

    def add_submission_task(self, folder_name: str, total_questions: int) -> int:
        if self._progress is None:
            # Progress should already be started by the caller; fail soft if not.
            return 0
        task_id = self._progress.add_task(f"{folder_name}", total=total_questions)
        self._submission_meta[task_id] = (folder_name, total_questions)
        return task_id

    def update_submission_task(self, task_id: int, current: int, question_id: str) -> None:
        if self._progress is None or task_id == 0:
            return
        meta = self._submission_meta.get(task_id)
        folder_name = meta[0] if meta is not None else ""
        description = f"{folder_name} q{question_id}" if folder_name else f"q{question_id}"
        try:
            self._progress.update(task_id, completed=current, description=description)
        except Exception:
            # If the task was already removed or Progress is shutting down, ignore.
            return

    def remove_submission_task(self, task_id: int) -> None:
        if self._progress is None or task_id == 0:
            return
        self._submission_meta.pop(task_id, None)
        try:
            self._progress.remove_task(task_id)
        except Exception:
            return


def create_console_ui(
    *,
    force_plain: bool = False,
    quiet: bool = False,
    is_tty: bool | None = None,
    rich_available: bool | None = None,
) -> ConsoleUI:
    resolved_tty = sys.stdout.isatty() if is_tty is None else is_tty
    resolved_rich = _RICH_AVAILABLE if rich_available is None else rich_available
    if quiet:
        return QuietConsoleUI()
    if force_plain or (not resolved_tty) or (not resolved_rich):
        return PlainConsoleUI()
    try:
        return RichConsoleUI()
    except Exception:  # noqa: BLE001
        return PlainConsoleUI()


def args_to_subtitle(args: Any) -> str:
    mode = "dry-run" if getattr(args, "dry_run", False) else "live"
    model = getattr(args, "model", "")
    grading_mode = getattr(args, "grading_mode", "legacy")
    if grading_mode == "legacy":
        locator_model = getattr(args, "locator_model", "")
        locator_text = locator_model if locator_model else "disabled"
        return f"mode={mode} | grading={grading_mode} | model={model} | locator={locator_text}"
    if grading_mode == "agent":
        return f"mode={mode} | grading={grading_mode} | model={model}"
    cache_enabled = bool(getattr(args, "context_cache", True))
    cache_text = "on" if cache_enabled else "off"
    return f"mode={mode} | grading={grading_mode} | model={model} | cache={cache_text}"

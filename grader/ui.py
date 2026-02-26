
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised through create_console_ui tests.
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    from rich.table import Table

    _RICH_AVAILABLE = True
except Exception:  # noqa: BLE001
    Console = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
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


@dataclass(frozen=True)
class RunSummary:
    submissions_processed: int
    success_count: int
    review_required_count: int
    failed_with_error_count: int
    warning_count: int


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


class PlainConsoleUI(ConsoleUI):
    def __init__(self) -> None:
        self._status_active = False
        self._status_width = 0

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
    ) -> None:
        self.clear_status()
        if had_error:
            status = "FAILED"
        elif band == "REVIEW_REQUIRED":
            status = "REVIEW"
        else:
            status = "OK"
        print(f"[{index}/{total}] {status} {folder_name} -> {band}")

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


class RichConsoleUI(ConsoleUI):
    def __init__(self) -> None:
        if not _RICH_AVAILABLE:
            raise RuntimeError("Rich is not available.")
        self.console = Console()  # type: ignore[misc]
        self.err_console = Console(stderr=True)  # type: ignore[misc]
        self._status_ctx: Any | None = None
        self._progress: Any | None = None
        self._progress_task: Any | None = None

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
    ) -> None:
        self.clear_status()
        if had_error:
            status = "[red]✗ FAILED[/red]"
        elif band == "REVIEW_REQUIRED":
            status = "[yellow]⟳ REVIEW[/yellow]"
        else:
            status = "[green]✓ OK[/green]"
        band_color = _BAND_COLORS.get(band, "white")
        self.console.print(
            f"[cyan][{index}/{total}][/cyan] {status} [bold]{folder_name}[/bold] → [{band_color}]{band}[/{band_color}]"
        )
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
        self.console.print(table)

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
            TextColumn("[bold blue]Grading"),
            BarColumn(bar_width=30),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
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


def create_console_ui(
    *,
    force_plain: bool = False,
    is_tty: bool | None = None,
    rich_available: bool | None = None,
) -> ConsoleUI:
    resolved_tty = sys.stdout.isatty() if is_tty is None else is_tty
    resolved_rich = _RICH_AVAILABLE if rich_available is None else rich_available
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
    cache_enabled = bool(getattr(args, "context_cache", True))
    cache_text = "on" if cache_enabled else "off"
    return f"mode={mode} | grading={grading_mode} | model={model} | cache={cache_text}"

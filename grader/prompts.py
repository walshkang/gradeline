"""Rich-powered interactive prompts with plain-text fallbacks.

Provides styled text input, yes/no confirmation, integer input, path input,
and arrow-key selection menus inspired by Copilot CLI / Claude Code.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm, IntPrompt, Prompt
    from rich.rule import Rule
    from rich.table import Table
    from rich.theme import Theme

    _RICH_AVAILABLE = True
except Exception:  # noqa: BLE001
    _RICH_AVAILABLE = False


_THEME = Theme(
    {
        "prompt.default": "dim",
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "red bold",
        "accent": "blue",
        "muted": "dim",
    }
) if _RICH_AVAILABLE else None


def _console() -> Any:
    return Console(theme=_THEME)


def _err_console() -> Any:
    return Console(stderr=True, theme=_THEME)


# --- Message helpers ---


def styled_info(message: str, *, force_plain: bool = False) -> None:
    if _use_rich(force_plain):
        _console().print(f"[info]ℹ[/info] {message}")
    else:
        print(message)


def styled_success(message: str, *, force_plain: bool = False) -> None:
    if _use_rich(force_plain):
        _console().print(f"[success]✓[/success] {message}")
    else:
        print(message)


def styled_warning(message: str, *, force_plain: bool = False) -> None:
    if _use_rich(force_plain):
        _console().print(f"[warning]⚠[/warning] {message}")
    else:
        print(f"[WARN] {message}")


def styled_error(message: str, *, force_plain: bool = False) -> None:
    if _use_rich(force_plain):
        _err_console().print(f"[error]✗[/error] {message}")
    else:
        print(f"[ERROR] {message}", file=sys.stderr)


def styled_banner(title: str, subtitle: str = "", *, force_plain: bool = False) -> None:
    if _use_rich(force_plain):
        text = title if not subtitle else f"{title}\n[muted]{subtitle}[/muted]"
        _console().print(Panel.fit(text, border_style="blue", padding=(0, 2)))
    else:
        print(f"=== {title} ===")
        if subtitle:
            print(subtitle)


def styled_url(label: str, url: str, *, force_plain: bool = False) -> None:
    if _use_rich(force_plain):
        _console().print(
            Panel(f"[bold]{url}[/bold]", title=label, border_style="green", padding=(0, 2))
        )
    else:
        print(f"{label}: {url}")


def styled_section_heading(title: str, *, force_plain: bool = False) -> None:
    if _use_rich(force_plain):
        c = _console()
        c.print()
        c.print(Rule(f"[bold blue]{title}[/bold blue]", style="blue"))
    else:
        print(f"\n--- {title} ---")


def styled_table(
    title: str,
    columns: list[tuple[str, dict[str, Any]]],
    rows: list[tuple[str, ...]],
    *,
    force_plain: bool = False,
) -> None:
    if _use_rich(force_plain):
        table = Table(
            title=title, show_header=True, header_style="bold blue", border_style="dim"
        )
        for col_name, col_kwargs in columns:
            table.add_column(col_name, **col_kwargs)
        for row in rows:
            table.add_row(*row)
        _console().print(table)
    else:
        print(title)
        for row in rows:
            print("  ".join(row))


# --- Prompt helpers ---


def prompt_text(
    label: str,
    *,
    default: str | None = None,
    required: bool = True,
    force_plain: bool = False,
) -> str:
    if _use_rich(force_plain):
        while True:
            result = Prompt.ask(
                f"[accent]{label}[/accent]", default=default or "", console=_console()
            )
            if result:
                return result
            if default is not None:
                return str(default)
            if not required:
                return ""
            _console().print("[warning]Value is required.[/warning]")
    else:
        return _plain_prompt_text(label, default=default, required=required)


def prompt_yes_no(
    label: str,
    *,
    default: bool = True,
    force_plain: bool = False,
) -> bool:
    if _use_rich(force_plain):
        return Confirm.ask(f"[accent]{label}[/accent]", default=default, console=_console())
    return _plain_prompt_yes_no(label, default=default)


def prompt_int(
    label: str,
    *,
    default: int,
    minimum: int = 0,
    maximum: int = 65535,
    force_plain: bool = False,
) -> int:
    if _use_rich(force_plain):
        while True:
            value = IntPrompt.ask(
                f"[accent]{label}[/accent]", default=default, console=_console()
            )
            if minimum <= value <= maximum:
                return value
            _console().print(
                f"[warning]Please enter a value between {minimum} and {maximum}.[/warning]"
            )
    return _plain_prompt_int(label, default=default, minimum=minimum, maximum=maximum)


def prompt_path(
    label: str,
    *,
    default: str | None = None,
    required: bool = True,
    cwd: Path,
    force_plain: bool = False,
) -> Path:
    while True:
        raw = prompt_text(label, default=default, required=required, force_plain=force_plain)
        value = raw.strip()
        if not value and not required:
            return cwd
        return normalize_user_path(value, cwd=cwd)


def prompt_select(
    label: str,
    choices: list[str],
    *,
    default: int = 0,
    force_plain: bool = False,
    instruction: str | None = None,
) -> int | None:
    """Arrow-key selection menu. Returns selected index, or None if cancelled."""
    if not choices:
        raise ValueError("prompt_select requires at least one choice.")
    if _use_rich(force_plain):
        result = _inquirerpy_select(
            label,
            choices,
            default=default,
            instruction=instruction if instruction is not None else "Type to filter, ↑/↓ to move, Enter to select",
        )
        if result is not None:
            return result
        return None  # User cancelled (e.g. Ctrl+Z)
    return _plain_select(label, choices, default=default)


def prompt_path_candidate(
    *,
    label: str,
    current: Path | None,
    candidates: list[Path],
    cwd: Path,
    force_plain: bool = False,
) -> Path:
    options = _dedupe_paths(([current] if current is not None else []) + candidates)
    if not options:
        return prompt_path(
            f"{label} path",
            default=str(current) if current else None,
            required=True,
            cwd=cwd,
            force_plain=force_plain,
        )

    display = [str(p) for p in options[:3]] + ["Enter path manually"]
    idx = prompt_select(label, display, default=0, force_plain=force_plain)
    if idx is None:
        raise KeyboardInterrupt

    if idx < len(options[:3]):
        return options[idx]
    raw = prompt_text(
        f"{label} path",
        default=str(current) if current else None,
        required=True,
        force_plain=force_plain,
    )
    return normalize_user_path(raw, cwd=cwd)


def prompt_text_candidate(
    *,
    label: str,
    current: str | None,
    candidates: list[str],
    force_plain: bool = False,
) -> str:
    options = _dedupe_strings(([current] if current else []) + candidates)
    if not options:
        return prompt_text(label, default=current, required=True, force_plain=force_plain)

    display = list(options[:3]) + ["Enter manually"]
    idx = prompt_select(label, display, default=0, force_plain=force_plain)
    if idx is None:
        raise KeyboardInterrupt

    if idx < len(options[:3]):
        return options[idx]
    return prompt_text(label, default=current, required=True, force_plain=force_plain)


# --- Interactive selection (InquirerPy fuzzy when available) ---


def _inquirerpy_select(
    label: str,
    choices: list[str],
    *,
    default: int = 0,
    instruction: str = "Type to filter, ↑/↓ to move, Enter to select",
) -> int | None:
    """Use InquirerPy fuzzy for searchable menu; returns index or None if unavailable."""
    try:
        from InquirerPy import inquirer
        from InquirerPy.base import Choice
    except ImportError:
        return None
    q_choices = [Choice(i, name=c) for i, c in enumerate(choices)]
    result = inquirer.fuzzy(
        message=label,
        choices=q_choices,
        instruction=instruction,
        mandatory=False,
    ).execute()
    return result


# --- Plain fallbacks ---


def _plain_prompt_text(label: str, *, default: str | None, required: bool) -> str:
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


def _plain_prompt_yes_no(label: str, *, default: bool) -> bool:
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


def _plain_prompt_int(label: str, *, default: int, minimum: int, maximum: int) -> int:
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


def _plain_select(label: str, choices: list[str], *, default: int = 0) -> int:
    print(f"{label}:")
    for i, choice in enumerate(choices):
        marker = ">" if i == default else " "
        print(f"  {marker} {i + 1}) {choice}")
    while True:
        raw = input(f"Select [{default + 1}]: ").strip()
        if raw == "":
            return default
        try:
            index = int(raw)
        except ValueError:
            print("Please enter a number.")
            continue
        if 1 <= index <= len(choices):
            return index - 1
        print(f"Please choose 1..{len(choices)}.")


# --- Utilities ---


def normalize_user_path(raw: str, *, cwd: Path) -> Path:
    expanded = os.path.expandvars(raw)
    expanded = os.path.expanduser(expanded)
    path = Path(expanded)
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def _use_rich(force_plain: bool) -> bool:
    if force_plain:
        return False
    if os.environ.get("GRADELINE_PLAIN", "").lower() in {"1", "true", "yes"}:
        return False
    return _RICH_AVAILABLE and sys.stdout.isatty()


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for p in paths:
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(p)
    return result


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result

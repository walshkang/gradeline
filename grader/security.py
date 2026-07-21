"""Security utilities for Gradeline.

Provides path traversal validation, prompt injection escaping, and untrusted input isolation wrappers.
"""

from __future__ import annotations

import os
from pathlib import Path


class SecurityError(ValueError):
    """Raised when a security boundary or validation rule is violated."""


def validate_safe_path(target_path: Path | str, base_dir: Path | str) -> Path:
    """Validate that target_path resides within base_dir after resolving symlinks and relative parts.

    Raises:
        SecurityError: If target_path escapes base_dir.
    """
    base_resolved = Path(base_dir).resolve()
    target_resolved = Path(target_path).resolve()

    try:
        target_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise SecurityError(
            f"Path traversal detected: '{target_path}' is outside base directory '{base_dir}'"
        ) from exc

    return target_resolved


def sanitize_prompt_data(text: str) -> str:
    """Sanitize raw student input / OCR text to neutralize control tag escaping attempts."""
    if not text:
        return ""
    # Replace closing XML tags or prompt break sequences that could attempt to exit the data boundary
    text = text.replace("</student_submission_text>", "&lt;/student_submission_text&gt;")
    text = text.replace("</student_response>", "&lt;/student_response&gt;")
    text = text.replace("<|im_end|>", "")
    text = text.replace("<|im_start|>", "")
    return text


def wrap_untrusted_prompt_context(tag: str, content: str) -> str:
    """Wrap untrusted input within explicit XML-like delimiters for LLM prompt isolation."""
    sanitized = sanitize_prompt_data(content)
    return f"<{tag}>\n{sanitized}\n</{tag}>"

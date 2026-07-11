from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .diagnostics import DiagnosticsCollector

@dataclass
class GradingConfig:
    submissions_root: Path
    output_dir: Path
    temp_dir: Path
    ocr_char_threshold: int
    rubric: Any
    solutions_text: str | None
    solutions_pdf_path: Path
    grade_points: dict[str, str]
    grader: Any | None
    grading_mode: str
    agent_type: str
    context_cache: bool
    context_cache_ttl_seconds: int
    dry_run: bool
    locator_model: str
    annotate_dry_run_marks: bool
    extraction_model: str
    gemini_api_key: str | None
    extract_blocks: bool
    diagnostics: DiagnosticsCollector | None
    rate_limiter: Any | None
    annotation_font_size: float

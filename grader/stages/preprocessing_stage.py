from __future__ import annotations

from typing import Any
from ..preprocessing import get_or_compute_preprocessing
from ..types import ExtractedPdf


def run_preprocess_task(
    idx: int,
    unit: Any,
    config: Any,
    diagnostics: Any = None,
) -> tuple[int, Any, list[ExtractedPdf] | None, Exception | None]:
    """Execute preprocessing (OCR and text extraction) for a student submission unit.

    Returns (idx, unit, extracted_pdfs_or_none, exception_or_none).
    """
    try:
        extracted = get_or_compute_preprocessing(unit, config, diagnostics)
        return idx, unit, extracted, None
    except Exception as exc:
        return idx, unit, None, exc

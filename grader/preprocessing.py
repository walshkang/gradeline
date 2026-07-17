from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from .extract import extract_pdf_text, serialize_extracted_pdf, deserialize_extracted_pdf, EXTRACTION_VERSION
from .types import ExtractedPdf
from .gemini_client import compute_grade_cache_key, compute_unified_grade_cache_key, compute_context_cache_key, compute_agent_grade_cache_key
from .orchestrator import LEGACY_MODE, UNIFIED_MODE, AGENT_MODE

@dataclass
class StageTiming:
    name: str
    start: float = 0.0
    end: float = 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start) if self.end else 0.0

@dataclass
class SubmissionTelemetry:
    stages: list[StageTiming] = field(default_factory=list)
    start: float = 0.0
    end: float = 0.0

    @property
    def total_seconds(self) -> float:
        return max(0.0, self.end - self.start) if self.end else 0.0

    def begin_stage(self, name: str) -> None:
        self.stages.append(StageTiming(name=name, start=time.monotonic()))

    def end_stage(self) -> None:
        if self.stages and not self.stages[-1].end:
            self.stages[-1].end = time.monotonic()


def compute_submission_pdf_hash(pdf_paths: list[Path]) -> str:
    """Compute a combined SHA-256 hash of all PDF files in a submission."""
    import hashlib
    hasher = hashlib.sha256()
    # Sort paths by name for deterministic ordering
    for path in sorted(pdf_paths, key=lambda p: p.name):
        if path.exists():
            with path.open("rb") as handle:
                while True:
                    block = handle.read(65536)
                    if not block:
                        break
                    hasher.update(block)
    return hasher.hexdigest()

def get_or_compute_preprocessing(unit: Any, config, diagnostics) -> list[ExtractedPdf]:
    """Load preprocessed PDF text/blocks from cache or compute and save them."""
    if config.grading_mode != LEGACY_MODE and not config.extract_blocks:
        return []

    import json as _json
    
    pdf_paths = unit.pdf_paths
    pdf_hash = compute_submission_pdf_hash(pdf_paths)
    composite_key = f"{pdf_hash}_{EXTRACTION_VERSION}"
    
    cache_dir = getattr(config, "cache_dir", Path(".grader_cache"))
    prep_cache_dir = cache_dir / "preprocessing"
    cache_file = prep_cache_dir / f"{composite_key}.json"
    
    if cache_file.exists():
        try:
            raw_data = _json.loads(cache_file.read_text(encoding="utf-8"))
            return [deserialize_extracted_pdf(item) for item in raw_data]
        except Exception:
            # If cache is corrupt, fallback to computing it
            pass
            
    # Compute and cache
    extracted_pdfs = []
    for pdf_path in pdf_paths:
        try:
            pdf_extract = extract_pdf_text(
                pdf_path=pdf_path,
                temp_dir=config.temp_dir,
                ocr_char_threshold=config.ocr_char_threshold,
                gemini_api_key=config.gemini_api_key,
                gemini_model=config.extraction_model,
                rate_limiter=config.rate_limiter,
            )
        except Exception as exc:
            pdf_extract = ExtractedPdf(
                pdf_path=pdf_path,
                blocks=[],
                text="",
                source="error",
                native_char_count=0,
                ocr_char_count=0,
            )
            # Re-record to diagnostics if configured
            if diagnostics is not None:
                diagnostics.record(
                    severity="error",
                    code="grading_extract_failed",
                    stage="grading",
                    message=f"Text extraction failed for {pdf_path.name}: {exc}",
                    submission_folder=unit.folder_path.name,
                    exc=exc,
                )
        extracted_pdfs.append(pdf_extract)
        
    try:
        prep_cache_dir.mkdir(parents=True, exist_ok=True)
        serialized = [serialize_extracted_pdf(item) for item in extracted_pdfs]
        cache_file.write_text(_json.dumps(serialized, indent=2), encoding="utf-8")
    except Exception:
        # Saving cache failure shouldn't crash the run
        pass
        
    return extracted_pdfs

def compute_cache_key_for_submission(unit: Any, rubric: Any, config) -> str:
    pdf_paths = [str(f) for f in unit.get_pdfs()]
    if config.grading_mode == UNIFIED_MODE:
        context_key = compute_context_cache_key(
            model=config.grader.model,
            rubric=rubric,
            solutions_pdf_path=config.solutions_pdf_path,
        )
        return compute_unified_grade_cache_key(
            submission_id=unit.folder_token,
            pdf_paths=pdf_paths,
            rubric=rubric,
            model=config.grader.model,
            context_key=context_key,
        )
    elif config.grading_mode == AGENT_MODE:
        return compute_agent_grade_cache_key(
            submission_id=unit.folder_token,
            pdf_paths=pdf_paths,
            rubric=rubric,
            model=config.model,
            agent_type=config.agent_type,
        )
    else:
        return compute_grade_cache_key(
            submission_id=unit.folder_token,
            rubric=rubric,
            solutions_text=config.solutions_text,
        )

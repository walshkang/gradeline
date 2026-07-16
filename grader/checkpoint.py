from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from .types import SubmissionResult, QuestionResult


def file_sha256(path: Path) -> str:
    """Compute the SHA-256 hash of a file."""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_run_config_hash(
    rubric_path: Path,
    solutions_pdf: Path,
    model: str,
    grading_mode: str,
) -> str:
    """Generate a unique hash for the grading run configuration."""
    rubric_hash = file_sha256(rubric_path)
    solutions_hash = file_sha256(solutions_pdf)
    combined = f"{rubric_hash}:{solutions_hash}:{model}:{grading_mode}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def get_checkpoint_path(output_dir: Path) -> Path:
    """Return the path to the checkpoint file for a given output directory."""
    return output_dir / ".gradeline_checkpoint.json"


def serialize_question_result(qr: QuestionResult) -> dict[str, Any]:
    """Serialize a QuestionResult recursively."""
    d = {
        "id": qr.id,
        "verdict": qr.verdict,
        "confidence": qr.confidence,
        "short_reason": qr.short_reason,
        "evidence_quote": qr.evidence_quote,
        "logic_analysis": qr.logic_analysis,
        "detail_reason": qr.detail_reason,
        "coords": list(qr.coords) if qr.coords else None,
        "page_number": qr.page_number,
        "source_file": qr.source_file,
        "placement_source": qr.placement_source,
        "block_id": qr.block_id,
        "grading_source": qr.grading_source,
    }
    if qr.sub_results is not None:
        d["sub_results"] = [serialize_question_result(sub) for sub in qr.sub_results]
    return d


def deserialize_question_result(q: dict[str, Any]) -> QuestionResult:
    """Deserialize a QuestionResult recursively."""
    sub_results_raw = q.get("sub_results")
    sub_results = None
    if isinstance(sub_results_raw, list) and sub_results_raw:
        sub_results = tuple(
            deserialize_question_result(sub)
            for sub in sub_results_raw
            if isinstance(sub, dict)
        )
    return QuestionResult(
        id=q["id"],
        verdict=q["verdict"],
        confidence=q["confidence"],
        short_reason=q["short_reason"],
        evidence_quote=q["evidence_quote"],
        logic_analysis=q.get("logic_analysis", ""),
        detail_reason=q.get("detail_reason", ""),
        coords=tuple(q["coords"]) if q.get("coords") else None,
        page_number=q.get("page_number"),
        source_file=q.get("source_file"),
        placement_source=q.get("placement_source"),
        block_id=q.get("block_id"),
        grading_source=q.get("grading_source", "llm"),
        sub_results=sub_results,
    )


def serialize_result(res: SubmissionResult) -> dict[str, Any]:
    """Serialize a SubmissionResult dataclass into a JSON-compatible dictionary."""
    return {
        "folder_token": res.submission.folder_token,
        "student_name": res.submission.student_name,
        "folder_path": str(res.submission.folder_path),
        "folder_relpath": str(res.submission.folder_relpath),
        "pdf_paths": [str(p) for p in res.submission.pdf_paths],
        "question_results": [
            serialize_question_result(qr)
            for qr in res.question_results
        ],
        "grade_result": {
            "percent": res.grade_result.percent,
            "band": res.grade_result.band,
            "points": res.grade_result.points,
            "has_needs_review": res.grade_result.has_needs_review,
            "per_question_scores": res.grade_result.per_question_scores,
        },
        "output_pdf_paths": [str(p) for p in res.output_pdf_paths],
        "extraction_sources": res.extraction_sources,
        "global_flags": res.global_flags,
        "error": res.error,
    }


def deserialize_result(data: dict[str, Any]) -> SubmissionResult:
    """Reconstruct a SubmissionResult dataclass from a dictionary."""
    from .types import SubmissionUnit, GradeResult, SubmissionResult
    
    sub = SubmissionUnit(
        folder_path=Path(data["folder_path"]),
        folder_relpath=Path(data["folder_relpath"]),
        folder_token=data["folder_token"],
        student_name=data["student_name"],
        pdf_paths=[Path(p) for p in data["pdf_paths"]],
    )
    
    q_results = [
        deserialize_question_result(q)
        for q in data["question_results"]
    ]
    
    gr = GradeResult(
        percent=data["grade_result"]["percent"],
        band=data["grade_result"]["band"],
        points=data["grade_result"]["points"],
        has_needs_review=data["grade_result"]["has_needs_review"],
        per_question_scores=data["grade_result"]["per_question_scores"],
    )
    
    return SubmissionResult(
        submission=sub,
        question_results=q_results,
        grade_result=gr,
        output_pdf_paths=[Path(p) for p in data["output_pdf_paths"]],
        extraction_sources=data["extraction_sources"],
        global_flags=data["global_flags"],
        block_registry={},
        error=data["error"],
    )


def serialize_rolling(rolling: Any | None) -> dict[str, Any] | None:
    """Serialize the RollingSnapshot dataclass."""
    if rolling is None:
        return None
    return {
        "band_counts": rolling.band_counts,
        "failure_count": rolling.failure_count,
        "submissions_done": rolling.submissions_done,
        "total_seconds": rolling.total_seconds,
        "mean_seconds": rolling.mean_seconds,
        "eta_seconds": rolling.eta_seconds,
    }


def deserialize_rolling(data: dict[str, Any] | None) -> Any | None:
    """Deserialize the RollingSnapshot dataclass."""
    if data is None:
        return None
    from .orchestrator import RollingSnapshot
    return RollingSnapshot(
        band_counts=data["band_counts"],
        failure_count=data["failure_count"],
        submissions_done=data["submissions_done"],
        total_seconds=data["total_seconds"],
        mean_seconds=data["mean_seconds"],
        eta_seconds=data["eta_seconds"],
    )


def save_checkpoint(
    output_dir: Path,
    results: list[SubmissionResult],
    rolling: Any | None,
    run_config_hash: str,
    stop_reason: str,
) -> Path:
    """Save the current grading session checkpoint to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = get_checkpoint_path(output_dir)
    
    now_str = datetime.datetime.now().isoformat()
    
    # Retrieve existing metadata (like created_at) if it exists
    created_at = now_str
    if checkpoint_file.exists():
        try:
            old_data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
            if isinstance(old_data, dict) and "created_at" in old_data:
                created_at = old_data["created_at"]
        except Exception:
            pass

    payload = {
        "schema_version": 1,
        "created_at": created_at,
        "updated_at": now_str,
        "run_config_hash": run_config_hash,
        "stop_reason": stop_reason,
        "completed_folders": [res.submission.folder_token for res in results],
        "results": [serialize_result(res) for res in results],
        "total_submissions": len(results),
        "rolling_snapshot": serialize_rolling(rolling),
    }
    
    checkpoint_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return checkpoint_file


class CheckpointData:
    def __init__(
        self,
        results: list[SubmissionResult],
        rolling: Any | None,
        stop_reason: str,
        completed_folders: set[str],
    ) -> None:
        self.results = results
        self.rolling = rolling
        self.stop_reason = stop_reason
        self.completed_folders = completed_folders


def load_checkpoint(
    output_dir: Path,
    expected_config_hash: str,
) -> CheckpointData | None:
    """Load a checkpoint file if it exists and matches the expected configuration hash."""
    checkpoint_file = get_checkpoint_path(output_dir)
    if not checkpoint_file.exists():
        return None
        
    try:
        data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
            
        # Verify schema version
        if data.get("schema_version") != 1:
            return None
            
        # Verify config hash matches
        if data.get("run_config_hash") != expected_config_hash:
            return None
            
        results = [deserialize_result(r) for r in data.get("results", [])]
        rolling = deserialize_rolling(data.get("rolling_snapshot"))
        stop_reason = data.get("stop_reason", "unknown")
        completed_folders = set(data.get("completed_folders", []))
        
        return CheckpointData(
            results=results,
            rolling=rolling,
            stop_reason=stop_reason,
            completed_folders=completed_folders,
        )
    except Exception:
        # Ignore corrupt checkpoints and return None (letting CLI handle it)
        return None


def clear_checkpoint(output_dir: Path) -> bool:
    """Delete the checkpoint file. Returns True if deleted, False otherwise."""
    checkpoint_file = get_checkpoint_path(output_dir)
    if checkpoint_file.exists():
        try:
            checkpoint_file.unlink()
            return True
        except Exception:
            return False
    return False

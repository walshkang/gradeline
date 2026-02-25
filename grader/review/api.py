from __future__ import annotations

import csv
import json
import re
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..score import score_submission
from .exporter import export_review_outputs
from .raster import RasterImageCache
from .state import (
    append_event,
    events_path_for_output,
    load_state,
    state_path_for_output,
    touch_updated_at,
    write_state_atomic,
)
from .types import (
    DEFAULT_GRADE_POINTS,
    VERDICT_VALUES,
    normalize_coords,
    question_result_from_payload,
    rubric_from_dict,
    rubric_to_dict,
    utc_now_iso,
)


class ReviewApiError(ValueError):
    """Raised when review API receives invalid input."""


DOCUMENT_SOURCE_ORIGINAL = "original"
DOCUMENT_SOURCE_EDITED = "edited"
DOCUMENT_SOURCE_VALUES = {DOCUMENT_SOURCE_ORIGINAL, DOCUMENT_SOURCE_EDITED}


class ReviewApi:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.state_path = state_path_for_output(output_dir)
        self.events_path = events_path_for_output(output_dir)
        if not self.state_path.exists():
            raise ReviewApiError(
                f"Review state not found: {self.state_path}. Run 'python3 -m grader.review_cli init --output-dir {output_dir}'."
            )
        self._lock = threading.Lock()
        self._state = load_state(self.state_path)
        self.raster_cache = RasterImageCache()

    def get_run(self) -> dict[str, Any]:
        state = self._state
        submissions = state.get("submissions", {})
        if not isinstance(submissions, dict):
            submissions = {}

        status_counts: dict[str, int] = {}
        for item in submissions.values():
            if not isinstance(item, dict):
                continue
            status = str(item.get("review_status", "todo"))
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "run_metadata": state.get("run_metadata", {}),
            "grading_context": {
                "args_snapshot": state.get("grading_context", {}).get("args_snapshot", {}),
                "grade_points": state.get("grading_context", {}).get("grade_points", {}),
                "rubric": state.get("grading_context", {}).get("rubric", {}),
            },
            "submission_count": len(submissions),
            "status_counts": status_counts,
            "outcomes": self._build_outcomes_summary(),
        }

    def list_submissions(self, *, status: str | None = None, query: str | None = None) -> list[dict[str, Any]]:
        status_filter = (status or "").strip().lower()
        query_filter = (query or "").strip().lower()
        items: list[dict[str, Any]] = []

        submissions = self._state.get("submissions", {})
        if not isinstance(submissions, dict):
            return items

        for submission_id, submission in submissions.items():
            if not isinstance(submission, dict):
                continue
            review_status = str(submission.get("review_status", "todo")).strip().lower()
            if status_filter and review_status != status_filter:
                continue

            identity = submission.get("identity", {})
            if not isinstance(identity, dict):
                identity = {}

            student_name = str(identity.get("student_name", ""))
            folder_relpath = str(identity.get("folder_relpath", ""))
            if query_filter:
                haystack = f"{student_name} {folder_relpath} {submission_id}".lower()
                if query_filter not in haystack:
                    continue

            questions = submission.get("questions", {})
            if not isinstance(questions, dict):
                questions = {}

            needs_review_count = 0
            override_count = 0
            for question in questions.values():
                if not isinstance(question, dict):
                    continue
                final_payload = question.get("final", {})
                if isinstance(final_payload, dict) and str(final_payload.get("verdict", "")).lower() == "needs_review":
                    needs_review_count += 1
                if bool(question.get("is_overridden", False)):
                    override_count += 1

            final_summary = submission.get("final_summary", {})
            if not isinstance(final_summary, dict):
                final_summary = {}

            items.append(
                {
                    "submission_id": submission_id,
                    "student_name": student_name,
                    "folder_relpath": folder_relpath,
                    "review_status": review_status,
                    "needs_review_count": needs_review_count,
                    "override_count": override_count,
                    "final_band": final_summary.get("band", ""),
                    "final_percent": final_summary.get("percent", 0.0),
                    "final_points": final_summary.get("points", ""),
                }
            )

        items.sort(key=lambda item: str(item["student_name"]).lower())
        return items

    def get_submission(self, submission_id: str, document_source: str | None = None) -> dict[str, Any]:
        submission = self._get_submission(submission_id)
        payload = deepcopy(submission)
        identity = payload.get("identity", {})
        if not isinstance(identity, dict):
            identity = {}

        resolved_source = normalize_document_source(document_source)
        pdf_paths = self._document_paths_for_submission(submission, document_source=resolved_source)
        documents: list[dict[str, Any]] = []
        for idx, path in enumerate(pdf_paths):
            documents.append(
                {
                    "doc_idx": idx,
                    "path": str(path),
                    "filename": path.name,
                    "exists": path.exists(),
                }
            )
        payload["documents"] = documents
        payload["document_source"] = resolved_source
        return payload

    def get_page_meta(
        self,
        submission_id: str,
        doc_idx: int,
        page_idx: int,
        scale: float,
        document_source: str | None = None,
    ) -> dict[str, Any]:
        resolved_source = normalize_document_source(document_source)
        pdf_path = self.resolve_pdf_path(submission_id, doc_idx, document_source=resolved_source)
        image = self.raster_cache.get_page_image(
            submission_id=submission_id,
            pdf_path=pdf_path,
            doc_idx=doc_idx,
            page_idx=page_idx,
            scale=scale,
        )
        return {
            "submission_id": submission_id,
            "doc_idx": doc_idx,
            "page_idx": page_idx,
            "pdf_path": str(pdf_path),
            "page_width_pt": image.meta.page_width_pt,
            "page_height_pt": image.meta.page_height_pt,
            "image_width_px": image.meta.image_width_px,
            "image_height_px": image.meta.image_height_px,
            "scale": image.meta.scale,
            "etag": image.meta.etag,
            "document_source": resolved_source,
            "image_url": (
                f"/api/submissions/{submission_id}/documents/{doc_idx}/pages/{page_idx}/image"
                f"?scale={image.meta.scale}&doc_source={resolved_source}"
            ),
        }

    def get_page_image(
        self,
        submission_id: str,
        doc_idx: int,
        page_idx: int,
        scale: float,
        document_source: str | None = None,
    ):
        resolved_source = normalize_document_source(document_source)
        pdf_path = self.resolve_pdf_path(submission_id, doc_idx, document_source=resolved_source)
        return self.raster_cache.get_page_image(
            submission_id=submission_id,
            pdf_path=pdf_path,
            doc_idx=doc_idx,
            page_idx=page_idx,
            scale=scale,
        )

    def patch_question(self, submission_id: str, question_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            submission = self._get_submission(submission_id)
            questions = submission.get("questions", {})
            if not isinstance(questions, dict) or question_id not in questions:
                raise ReviewApiError(f"Question '{question_id}' not found for submission '{submission_id}'.")
            question_payload = questions[question_id]
            if not isinstance(question_payload, dict):
                raise ReviewApiError(f"Question payload is invalid for '{question_id}'.")

            final_payload = question_payload.setdefault("final", {})
            auto_payload = question_payload.setdefault("auto", {})
            if not isinstance(final_payload, dict) or not isinstance(auto_payload, dict):
                raise ReviewApiError("Question payload missing auto/final maps.")

            if "verdict_final" in payload:
                verdict = str(payload["verdict_final"]).strip().lower()
                if verdict not in VERDICT_VALUES:
                    raise ReviewApiError(f"Invalid verdict_final '{verdict}'.")
                final_payload["verdict"] = verdict

            if "confidence_final" in payload:
                final_payload["confidence"] = clamp_confidence(payload["confidence_final"])

            if "short_reason_final" in payload:
                final_payload["short_reason"] = str(payload["short_reason_final"] or "")

            if "evidence_quote_final" in payload:
                final_payload["evidence_quote"] = str(payload["evidence_quote_final"] or "")

            if "coords_final" in payload:
                coords = coerce_coords_payload(payload["coords_final"])
                final_payload["coords"] = coords

            if "page_final" in payload:
                final_payload["page_number"] = coerce_page_number(payload["page_final"])

            if "source_file_final" in payload:
                final_payload["source_file"] = self.coerce_source_file(submission, payload["source_file_final"])

            question_payload["is_overridden"] = bool(compare_question_payloads(auto_payload, final_payload))
            question_payload["updated_at"] = utc_now_iso()

            summary = self._recompute_submission_summary(submission)
            submission["updated_at"] = utc_now_iso()
            touch_updated_at(self._state)
            self._persist_state_locked()
            append_event(
                self.events_path,
                "question_updated",
                {
                    "submission_id": submission_id,
                    "question_id": question_id,
                    "changes": sorted(payload.keys()),
                },
            )

            return {
                "submission_id": submission_id,
                "question_id": question_id,
                "question": deepcopy(question_payload),
                "summary": summary,
            }

    def patch_note(self, submission_id: str, note: str) -> dict[str, Any]:
        with self._lock:
            submission = self._get_submission(submission_id)
            submission["note"] = str(note or "")
            submission["updated_at"] = utc_now_iso()
            touch_updated_at(self._state)
            self._persist_state_locked()
            append_event(
                self.events_path,
                "note_updated",
                {"submission_id": submission_id},
            )
            return {"submission_id": submission_id, "note": submission["note"]}

    def patch_grading_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            grading_context = self._state.setdefault("grading_context", {})
            if not isinstance(grading_context, dict):
                raise ReviewApiError("Invalid grading_context in state.")

            incoming_rubric = payload.get("rubric", grading_context.get("rubric", {}))
            incoming_grade_points = payload.get("grade_points", grading_context.get("grade_points", {}))
            if not isinstance(incoming_rubric, dict):
                raise ReviewApiError("rubric must be a JSON object.")
            if not isinstance(incoming_grade_points, dict):
                raise ReviewApiError("grade_points must be a JSON object.")

            normalized_grade_points = normalize_grade_points_payload(incoming_grade_points)
            rubric = rubric_from_dict(incoming_rubric)
            normalized_rubric = rubric_to_dict(rubric)

            grading_context["rubric"] = normalized_rubric
            grading_context["grade_points"] = normalized_grade_points

            recomputed_submissions = 0
            submissions = self._state.get("submissions", {})
            if isinstance(submissions, dict):
                for submission in submissions.values():
                    if not isinstance(submission, dict):
                        continue
                    self._recompute_submission_summary(submission)
                    submission["updated_at"] = utc_now_iso()
                    recomputed_submissions += 1

            touch_updated_at(self._state)
            self._persist_state_locked()
            append_event(
                self.events_path,
                "grading_context_updated",
                {
                    "recomputed_submissions": recomputed_submissions,
                },
            )

            return {
                "grading_context": {
                    "args_snapshot": grading_context.get("args_snapshot", {}),
                    "grade_points": normalized_grade_points,
                    "rubric": normalized_rubric,
                },
                "recomputed_submissions": recomputed_submissions,
            }

    def export(self) -> dict[str, str]:
        artifacts = export_review_outputs(self.output_dir)
        return {name: str(path) for name, path in artifacts.items()}

    def resolve_pdf_path(self, submission_id: str, doc_idx: int, document_source: str | None = None) -> Path:
        submission = self._get_submission(submission_id)
        resolved_source = normalize_document_source(document_source)
        pdf_paths = self._document_paths_for_submission(submission, document_source=resolved_source)
        if doc_idx < 0 or doc_idx >= len(pdf_paths):
            raise ReviewApiError(f"doc_idx '{doc_idx}' out of range for submission '{submission_id}'.")
        pdf_path = pdf_paths[doc_idx]
        if not pdf_path.exists():
            raise ReviewApiError(f"PDF path does not exist: {pdf_path}")
        return pdf_path

    def _document_paths_for_submission(self, submission: dict[str, Any], document_source: str) -> list[Path]:
        identity = submission.get("identity", {})
        if not isinstance(identity, dict):
            raise ReviewApiError("Submission identity is invalid.")
        raw_paths = identity.get("pdf_paths", [])
        if not isinstance(raw_paths, list):
            raise ReviewApiError("Submission pdf_paths is invalid.")

        original_paths = [Path(str(item)) for item in raw_paths if str(item).strip()]
        if document_source == DOCUMENT_SOURCE_ORIGINAL:
            return original_paths

        folder_relpath = Path(str(identity.get("folder_relpath", "")).strip())
        submissions_root = self._submissions_root()
        edited_paths: list[Path] = []
        for original in original_paths:
            edited_paths.append(
                edited_output_path_for_original(
                    output_dir=self.output_dir,
                    original_path=original,
                    submissions_root=submissions_root,
                    folder_relpath=folder_relpath,
                )
            )
        return edited_paths

    def _submissions_root(self) -> Path | None:
        grading_context = self._state.get("grading_context", {})
        if not isinstance(grading_context, dict):
            return None
        args_snapshot = grading_context.get("args_snapshot", {})
        if not isinstance(args_snapshot, dict):
            return None
        raw = str(args_snapshot.get("submissions_dir", "")).strip()
        if not raw:
            return None
        return Path(raw)

    def _build_outcomes_summary(self) -> dict[str, Any]:
        diagnostics_path = self.output_dir / "grading_diagnostics.json"
        audit_path = self.output_dir / "grading_audit.csv"
        review_queue_path = self.output_dir / "review_queue.csv"
        brightspace_path = self.output_dir / "brightspace_grades_import.csv"

        diagnostics = read_json_object(diagnostics_path) if diagnostics_path.exists() else {}
        audit_rows = read_csv_rows(audit_path) if audit_path.exists() else []
        review_rows = read_csv_rows(review_queue_path) if review_queue_path.exists() else []
        brightspace_rows = read_csv_rows(brightspace_path) if brightspace_path.exists() else []

        if not diagnostics and not audit_rows:
            return {
                "available": False,
                "message": "No diagnostics/audit artifacts found in output directory.",
            }

        totals = diagnostics.get("totals", {}) if isinstance(diagnostics, dict) else {}
        args_snapshot = diagnostics.get("args_snapshot", {}) if isinstance(diagnostics, dict) else {}
        if not isinstance(args_snapshot, dict):
            args_snapshot = {}
        by_code = totals.get("by_code", {}) if isinstance(totals, dict) else {}
        if not isinstance(by_code, dict):
            by_code = {}

        summary = {
            "available": True,
            "submissions_processed": coerce_int(totals.get("submissions_processed"), default=0),
            "success_count": coerce_int(totals.get("success_count"), default=0),
            "review_required_count": coerce_int(totals.get("review_required_count"), default=0),
            "failed_with_error_count": coerce_int(totals.get("failed_with_error_count"), default=0),
            "warning_count": coerce_int(totals.get("warning_count"), default=0),
            "band_counts": {},
            "verdict_counts": {},
            "error_submissions": [],
            "cache_warning_count": sum(
                coerce_int(by_code.get(code), default=0)
                for code in ("context_cache_create_failed", "context_cache_bypassed", "context_cache_lookup_failed")
            ),
            "unmatched_grade_rows": 0,
        }

        if audit_rows:
            folder_bands: dict[str, str] = {}
            folder_errors: dict[str, dict[str, str]] = {}
            verdict_counts: dict[str, int] = {}
            for row in audit_rows:
                folder = str(row.get("folder", "")).strip()
                if folder and folder not in folder_bands:
                    folder_bands[folder] = str(row.get("band", "")).strip()
                verdict = str(row.get("verdict", "")).strip().lower()
                if verdict:
                    verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
                error = str(row.get("error", "")).strip()
                if folder and error and folder not in folder_errors:
                    folder_errors[folder] = {
                        "folder": folder,
                        "student_name": str(row.get("student_name", "")).strip(),
                        "error": error,
                    }

            band_counts: dict[str, int] = {}
            for band in folder_bands.values():
                if not band:
                    continue
                band_counts[band] = band_counts.get(band, 0) + 1
            summary["band_counts"] = band_counts
            summary["verdict_counts"] = verdict_counts
            summary["error_submissions"] = sorted(folder_errors.values(), key=lambda item: item["folder"])[:10]

        if brightspace_rows:
            preferred_grade_column = str(args_snapshot.get("grade_column", "")).strip() or None
            grade_column = resolve_grade_column(brightspace_rows, preferred=preferred_grade_column)
            if grade_column:
                summary["unmatched_grade_rows"] = sum(
                    1 for row in brightspace_rows if not str(row.get(grade_column, "")).strip()
                )

        if review_rows and not summary["error_submissions"]:
            queue_errors = []
            for row in review_rows:
                error = str(row.get("error", "")).strip()
                if not error:
                    continue
                queue_errors.append(
                    {
                        "folder": str(row.get("folder", "")).strip(),
                        "student_name": str(row.get("student_name", "")).strip(),
                        "error": error,
                    }
                )
            summary["error_submissions"] = queue_errors[:10]

        if summary["submissions_processed"] <= 0 and audit_rows:
            summary["submissions_processed"] = len({str(row.get("folder", "")).strip() for row in audit_rows if str(row.get("folder", "")).strip()})

        return summary

    def coerce_source_file(self, submission: dict[str, Any], raw_value: Any) -> str | None:
        source_file = str(raw_value or "").strip()
        if not source_file:
            return None

        identity = submission.get("identity", {})
        if not isinstance(identity, dict):
            raise ReviewApiError("Submission identity missing while validating source_file_final.")
        pdf_paths = identity.get("pdf_paths", [])
        filenames = {Path(str(path)).name for path in pdf_paths if str(path).strip()}
        if source_file not in filenames:
            raise ReviewApiError(
                f"source_file_final '{source_file}' does not match submission pdf filenames: {sorted(filenames)}"
            )
        return source_file

    def _recompute_submission_summary(self, submission: dict[str, Any]) -> dict[str, Any]:
        rubric = self._resolve_rubric()
        grade_points = self._resolve_grade_points()

        question_payloads = submission.get("questions", {})
        if not isinstance(question_payloads, dict):
            raise ReviewApiError("Submission questions payload is invalid.")

        question_results = []
        for question in rubric.questions:
            row = question_payloads.get(question.id)
            final_payload = row.get("final", {}) if isinstance(row, dict) else {}
            if not isinstance(final_payload, dict):
                final_payload = {}
            question_results.append(question_result_from_payload(question.id, final_payload))

        grade = score_submission(rubric=rubric, question_results=question_results, grade_points=grade_points)
        summary = {
            "percent": grade.percent,
            "band": grade.band,
            "points": grade.points,
        }
        submission["final_summary"] = summary
        submission["review_status"] = "done" if not grade.has_needs_review else "in_progress"
        return summary

    def _resolve_rubric(self):
        grading_context = self._state.get("grading_context", {})
        if not isinstance(grading_context, dict):
            raise ReviewApiError("Invalid grading_context in state.")
        rubric_payload = grading_context.get("rubric")
        if not isinstance(rubric_payload, dict):
            raise ReviewApiError("Missing rubric in grading_context.")
        return rubric_from_dict(rubric_payload)

    def _resolve_grade_points(self) -> dict[str, str]:
        grading_context = self._state.get("grading_context", {})
        if not isinstance(grading_context, dict):
            return {}
        points = grading_context.get("grade_points", {})
        if not isinstance(points, dict):
            return {}
        return {str(key): str(value) for key, value in points.items()}

    def _get_submission(self, submission_id: str) -> dict[str, Any]:
        submissions = self._state.get("submissions", {})
        if not isinstance(submissions, dict) or submission_id not in submissions:
            raise ReviewApiError(f"Submission '{submission_id}' not found.")
        submission = submissions[submission_id]
        if not isinstance(submission, dict):
            raise ReviewApiError(f"Submission '{submission_id}' has invalid payload.")
        return submission

    def _persist_state_locked(self) -> None:
        write_state_atomic(self.state_path, self._state)


def compare_question_payloads(auto_payload: dict[str, Any], final_payload: dict[str, Any]) -> bool:
    keys = [
        "verdict",
        "confidence",
        "short_reason",
        "evidence_quote",
        "coords",
        "page_number",
        "source_file",
        "placement_source",
    ]
    for key in keys:
        if auto_payload.get(key) != final_payload.get(key):
            return True
    return False


def clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ReviewApiError(f"Invalid confidence_final: {value!r}") from None
    return max(0.0, min(1.0, number))


def coerce_coords_payload(value: Any) -> list[float] | None:
    if value is None:
        return None
    coords = normalize_coords(value)
    if coords is None:
        raise ReviewApiError("coords_final must be [y, x] or null.")
    return coords


def coerce_page_number(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        raise ReviewApiError("page_final must be null or an integer >= 1.") from None
    if number < 1:
        raise ReviewApiError("page_final must be null or an integer >= 1.")
    return number


def normalize_grade_points_payload(payload: dict[str, Any]) -> dict[str, str]:
    if not payload:
        return dict(DEFAULT_GRADE_POINTS)
    return {
        "Check Plus": str(payload.get("Check Plus", DEFAULT_GRADE_POINTS["Check Plus"])),
        "Check": str(payload.get("Check", DEFAULT_GRADE_POINTS["Check"])),
        "Check Minus": str(payload.get("Check Minus", DEFAULT_GRADE_POINTS["Check Minus"])),
        "REVIEW_REQUIRED": str(payload.get("REVIEW_REQUIRED", DEFAULT_GRADE_POINTS["REVIEW_REQUIRED"])),
    }


def normalize_document_source(value: str | None) -> str:
    normalized = str(value or DOCUMENT_SOURCE_ORIGINAL).strip().lower() or DOCUMENT_SOURCE_ORIGINAL
    if normalized not in DOCUMENT_SOURCE_VALUES:
        raise ReviewApiError(f"Invalid document source '{value}'. Allowed values: {sorted(DOCUMENT_SOURCE_VALUES)}")
    return normalized


def edited_output_path_for_original(
    *,
    output_dir: Path,
    original_path: Path,
    submissions_root: Path | None,
    folder_relpath: Path,
) -> Path:
    if submissions_root is not None:
        try:
            rel = original_path.relative_to(submissions_root)
            return output_dir / rel
        except ValueError:
            pass
    if str(folder_relpath).strip():
        return output_dir / folder_relpath / original_path.name
    return output_dir / original_path.name


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            return [dict(row) for row in reader]
    except OSError:
        return []


def coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def resolve_grade_column(rows: list[dict[str, str]], preferred: str | None = None) -> str | None:
    if not rows:
        return None
    fields = list(rows[0].keys())

    resolved_preferred = resolve_requested_column(fields, preferred)
    if resolved_preferred:
        return resolved_preferred

    assignment_grade_pattern = re.compile(r"\bassignment\s*\d+\b.*\bpoints\b.*\bgrade\b")
    for field in fields:
        if assignment_grade_pattern.search(field.lower()):
            return field

    for field in fields:
        if "points grade" in field.lower():
            return field
    return None


def resolve_requested_column(fields: list[str], requested: str | None) -> str | None:
    target = str(requested or "").strip()
    if not target:
        return None

    if target in fields:
        return target

    lowered = target.lower()
    casefold_matches = [field for field in fields if field.lower() == lowered]
    if len(casefold_matches) == 1:
        return casefold_matches[0]
    if len(casefold_matches) > 1:
        return None

    prefix_matches = [field for field in fields if field.lower().startswith(lowered)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    return None

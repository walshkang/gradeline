from __future__ import annotations

import csv
import json
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import RubricConfig


@dataclass(frozen=True)
class QuestionStats:
    question_id: str
    total: int
    correct: int        # includes rounding_error
    incorrect: int
    partial: int
    needs_review: int
    pass_rate: float    # (correct + partial * partial_credit) / total
    regex_count: int    # grading_source == "regex"
    llm_count: int      # grading_source == "llm"


@dataclass(frozen=True)
class Inconsistency:
    question_id: str
    evidence_a: str     # normalized evidence_quote from student A
    verdict_a: str
    student_a: str
    evidence_b: str
    verdict_b: str
    student_b: str


@dataclass(frozen=True)
class BorderlineStudent:
    student_name: str
    folder: str
    percent: float
    band: str
    next_band: str      # the band they almost reached
    gap: float          # how far from the threshold


@dataclass(frozen=True)
class RegexCandidate:
    question_id: str
    llm_correct_count: int   # LLM said correct but no regex match
    sample_answers: list[str]  # up to 3 evidence_quotes from LLM-correct


@dataclass(frozen=True)
class AuditReport:
    question_stats: list[QuestionStats]
    inconsistencies: list[Inconsistency]
    borderline_students: list[BorderlineStudent]
    regex_candidates: list[RegexCandidate]
    total_students: int
    total_questions: int
    band_counts: dict[str, int]
    error_students: list[str]  # folders with non-empty error field


def normalize_quote(quote: str) -> str:
    """Normalize quote by lowercasing, stripping whitespace, and removing punctuation."""
    quote = quote.lower().strip()
    translator = str.maketrans("", "", string.punctuation)
    quote = quote.translate(translator)
    return " ".join(quote.split())


def analyze_grading_audit(audit_csv_path: Path, rubric: RubricConfig | None = None) -> AuditReport:
    """Analyze the grading audit CSV and produce an AuditReport."""
    # 1. Handle missing/empty file gracefully
    if not audit_csv_path.exists():
        return AuditReport(
            question_stats=[],
            inconsistencies=[],
            borderline_students=[],
            regex_candidates=[],
            total_students=0,
            total_questions=0,
            band_counts={},
            error_students=[],
        )

    rows: list[dict[str, str]] = []
    try:
        with audit_csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
    except Exception:
        return AuditReport(
            question_stats=[],
            inconsistencies=[],
            borderline_students=[],
            regex_candidates=[],
            total_students=0,
            total_questions=0,
            band_counts={},
            error_students=[],
        )

    if not rows:
        return AuditReport(
            question_stats=[],
            inconsistencies=[],
            borderline_students=[],
            regex_candidates=[],
            total_students=0,
            total_questions=0,
            band_counts={},
            error_students=[],
        )

    # 2. Resolve partial_credit and bands_thresholds
    bands_thresholds: dict[str, float] = {}
    partial_credit = 0.5

    if rubric is not None:
        partial_credit = rubric.partial_credit
        if "check_plus_min" in rubric.bands and "check_min" in rubric.bands:
            bands_thresholds["Check Plus"] = float(rubric.bands["check_plus_min"]) * 100.0
            bands_thresholds["Check"] = float(rubric.bands["check_min"]) * 100.0
            bands_thresholds["Check Minus"] = 0.0
        else:
            for name, val in rubric.bands.items():
                thresh = float(val)
                if thresh <= 1.0:
                    thresh *= 100.0
                bands_thresholds[name] = thresh
    else:
        # Try to resolve from review/review_state.json or grading_diagnostics.json
        output_dir = audit_csv_path.parent
        review_state_path = output_dir / "review" / "review_state.json"
        diagnostics_path = output_dir / "grading_diagnostics.json"
        resolved = False

        if review_state_path.exists():
            try:
                state_data = json.loads(review_state_path.read_text(encoding="utf-8"))
                rubric_data = state_data.get("grading_context", {}).get("rubric", {})
                if rubric_data:
                    partial_credit = float(rubric_data.get("partial_credit", 0.5))
                    bands_dict = rubric_data.get("bands", {})
                    if "check_plus_min" in bands_dict and "check_min" in bands_dict:
                        bands_thresholds["Check Plus"] = float(bands_dict["check_plus_min"]) * 100.0
                        bands_thresholds["Check"] = float(bands_dict["check_min"]) * 100.0
                        bands_thresholds["Check Minus"] = 0.0
                    else:
                        for name, val in bands_dict.items():
                            thresh = float(val)
                            if thresh <= 1.0:
                                thresh *= 100.0
                            bands_thresholds[name] = thresh
                    resolved = True
            except Exception:
                pass

        if not resolved and diagnostics_path.exists():
            try:
                diag_data = json.loads(diagnostics_path.read_text(encoding="utf-8"))
                rubric_yaml_path = diag_data.get("args_snapshot", {}).get("rubric_yaml")
                if rubric_yaml_path:
                    from .config import load_rubric
                    rub_obj = load_rubric(Path(rubric_yaml_path))
                    partial_credit = rub_obj.partial_credit
                    if "check_plus_min" in rub_obj.bands and "check_min" in rub_obj.bands:
                        bands_thresholds["Check Plus"] = float(rub_obj.bands["check_plus_min"]) * 100.0
                        bands_thresholds["Check"] = float(rub_obj.bands["check_min"]) * 100.0
                        bands_thresholds["Check Minus"] = 0.0
                    else:
                        for name, val in rub_obj.bands.items():
                            thresh = float(val)
                            if thresh <= 1.0:
                                thresh *= 100.0
                            bands_thresholds[name] = thresh
                    resolved = True
            except Exception:
                pass

    # 3. Parse and group rows
    students: dict[str, dict[str, Any]] = {}
    questions_data: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        folder = str(row.get("folder", "")).strip()
        if not folder:
            continue

        student_name = str(row.get("student_name", "")).strip()

        raw_percent = row.get("percent", "0")
        try:
            percent = float(raw_percent)
        except ValueError:
            percent = 0.0

        band = str(row.get("band", "")).strip()
        error = str(row.get("error", "")).strip()

        q_id = str(row.get("question_id", "")).strip()
        verdict = str(row.get("verdict", "")).strip().lower()
        grading_source = str(row.get("grading_source", "")).strip().lower()
        evidence_quote = str(row.get("evidence_quote", "")).strip()

        if folder not in students:
            students[folder] = {
                "student_name": student_name,
                "folder": folder,
                "percent": percent,
                "band": band,
                "error": error,
                "questions": {},
            }

        if q_id:
            students[folder]["questions"][q_id] = {
                "verdict": verdict,
                "grading_source": grading_source,
                "evidence_quote": evidence_quote,
            }
            questions_data.setdefault(q_id, []).append({
                "folder": folder,
                "student_name": student_name,
                "verdict": verdict,
                "grading_source": grading_source,
                "evidence_quote": evidence_quote,
            })

    # 4. Perform dynamic threshold inference if still not resolved
    if not bands_thresholds:
        for student in students.values():
            if student["band"] == "REVIEW_REQUIRED" or student["error"]:
                continue
            b = student["band"]
            p = student["percent"]
            if not b:
                continue
            if b not in bands_thresholds:
                bands_thresholds[b] = p
            else:
                bands_thresholds[b] = min(bands_thresholds[b], p)

    # 5. Compute Question Stats
    question_stats: list[QuestionStats] = []
    for q_id in sorted(questions_data.keys()):
        rows_q = questions_data[q_id]
        total = len(rows_q)
        correct = sum(1 for r in rows_q if r["verdict"] in ("correct", "rounding_error"))
        incorrect = sum(1 for r in rows_q if r["verdict"] == "incorrect")
        partial = sum(1 for r in rows_q if r["verdict"] == "partial")
        needs_review = sum(1 for r in rows_q if r["verdict"] == "needs_review")
        regex_count = sum(1 for r in rows_q if r["grading_source"] == "regex")
        llm_count = sum(1 for r in rows_q if r["grading_source"] == "llm")

        pass_rate = 0.0
        if total > 0:
            pass_rate = (correct + partial * partial_credit) / total

        question_stats.append(
            QuestionStats(
                question_id=q_id,
                total=total,
                correct=correct,
                incorrect=incorrect,
                partial=partial,
                needs_review=needs_review,
                pass_rate=pass_rate,
                regex_count=regex_count,
                llm_count=llm_count,
            )
        )

    # 6. Inconsistency Detection
    inconsistencies: list[Inconsistency] = []
    for q_id in sorted(questions_data.keys()):
        rows_q = questions_data[q_id]
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in rows_q:
            eq = r["evidence_quote"]
            if not eq:
                continue
            norm = normalize_quote(eq)
            if not norm:
                continue
            groups.setdefault(norm, []).append(r)

        for norm_quote, group_rows in groups.items():
            verdicts = {g["verdict"] for g in group_rows}
            if len(verdicts) > 1:
                first = group_rows[0]
                second = None
                for other in group_rows[1:]:
                    if other["verdict"] != first["verdict"]:
                        second = other
                        break
                if second:
                    inconsistencies.append(
                        Inconsistency(
                            question_id=q_id,
                            evidence_a=normalize_quote(first["evidence_quote"]),
                            verdict_a=first["verdict"],
                            student_a=first["student_name"],
                            evidence_b=normalize_quote(second["evidence_quote"]),
                            verdict_b=second["verdict"],
                            student_b=second["student_name"],
                        )
                    )
    inconsistencies = inconsistencies[:10]

    # 7. Borderline Student Detection
    borderline_students: list[BorderlineStudent] = []
    sorted_thresholds = sorted(bands_thresholds.items(), key=lambda x: x[1])

    for student in students.values():
        if student["band"] == "REVIEW_REQUIRED" or student["error"]:
            continue

        s_band = student["band"]
        s_percent = student["percent"]

        idx = -1
        for i, (name, thresh) in enumerate(sorted_thresholds):
            if name == s_band:
                idx = i
                break

        if idx != -1 and idx < len(sorted_thresholds) - 1:
            next_band, next_thresh = sorted_thresholds[idx + 1]
            gap = next_thresh - s_percent
            if 0.0 < gap <= 5.0:
                borderline_students.append(
                    BorderlineStudent(
                        student_name=student["student_name"],
                        folder=student["folder"],
                        percent=s_percent,
                        band=s_band,
                        next_band=next_band,
                        gap=round(gap, 2),
                    )
                )
    borderline_students.sort(key=lambda s: s.folder.lower())

    # 8. Regex Candidate Identification
    regex_candidates: list[RegexCandidate] = []
    for q_id in sorted(questions_data.keys()):
        rows_q = questions_data[q_id]
        llm_correct_rows = [
            r for r in rows_q
            if r["grading_source"] == "llm" and r["verdict"] == "correct"
        ]

        count = len(llm_correct_rows)
        if count >= 3:
            unique_samples: list[str] = []
            for r in llm_correct_rows:
                eq = r["evidence_quote"].strip()
                if eq and eq not in unique_samples:
                    unique_samples.append(eq)
            unique_samples.sort()

            regex_candidates.append(
                RegexCandidate(
                    question_id=q_id,
                    llm_correct_count=count,
                    sample_answers=unique_samples[:3],
                )
            )

    # 9. Additional high-level stats
    total_students = len(students)
    total_questions = len(questions_data)
    band_counts: dict[str, int] = {}
    for student in students.values():
        b = student["band"]
        if b:
            band_counts[b] = band_counts.get(b, 0) + 1

    error_students = []
    for student in students.values():
        if student["error"]:
            error_students.append(student["folder"])
    error_students.sort()

    return AuditReport(
        question_stats=question_stats,
        inconsistencies=inconsistencies,
        borderline_students=borderline_students,
        regex_candidates=regex_candidates,
        total_students=total_students,
        total_questions=total_questions,
        band_counts=band_counts,
        error_students=error_students,
    )

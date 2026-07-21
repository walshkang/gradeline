from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScoringCriterion:
    requirement: str
    weight: float = 1.0
    partial_if: str = ""


@dataclass(frozen=True)
class QuestionRubric:
    id: str
    label_patterns: list[str]
    scoring_rules: str
    short_note_pass: str
    short_note_fail: str
    weight: float = 1.0
    anchor_tokens: list[str] = field(default_factory=list)
    expected_answers: list[str] = field(default_factory=list)
    requires_work: bool = False
    scoring_criteria: list[ScoringCriterion] = field(default_factory=list)


@dataclass(frozen=True)
class RubricConfig:
    assignment_id: str
    bands: dict[str, float]
    questions: list[QuestionRubric]
    scoring_mode: str = "equal_weights"
    partial_credit: float = 0.5


@dataclass(frozen=True)
class SubmissionUnit:
    folder_path: Path
    folder_relpath: Path
    folder_token: str
    student_name: str
    pdf_paths: list[Path]


@dataclass(frozen=True)
class TextBlock:
    id: str
    text: str
    page: int
    left: float
    top: float
    width: float
    height: float
    source: str
    confidence: float = -1.0


@dataclass(frozen=True)
class ExtractedPdf:
    pdf_path: Path
    blocks: list[TextBlock]
    text: str
    source: str
    native_char_count: int
    ocr_char_count: int


from .cost import TokenUsage


@dataclass(frozen=True)
class QuestionResult:
    id: str
    verdict: str
    confidence: float
    short_reason: str
    evidence_quote: str
    logic_analysis: str = ""
    detail_reason: str = ""
    coords: tuple[float, float] | None = None  # [y, x] in 0..1000 normalized space
    page_number: int | None = None
    source_file: str | None = None
    placement_source: str | None = None
    block_id: str | None = None
    grading_source: str = "llm"
    sub_results: tuple[QuestionResult, ...] | None = None  # Subpart breakdown
    diagnostics_trace: tuple[str, ...] | None = None
    token_usage: TokenUsage | None = None


@dataclass(frozen=True)
class GradeResult:
    percent: float
    band: str
    points: str
    has_needs_review: bool
    per_question_scores: dict[str, float]


@dataclass
class SubmissionResult:
    submission: SubmissionUnit
    question_results: list[QuestionResult]
    grade_result: GradeResult
    output_pdf_paths: list[Path]
    extraction_sources: dict[str, str]
    global_flags: list[str]
    block_registry: dict[str, TextBlock] = field(default_factory=dict)
    error: str | None = None
    total_token_usage: TokenUsage | None = None

    def question_result_map(self) -> dict[str, QuestionResult]:
        return {result.id: result for result in self.question_results}

    @classmethod
    def from_error(
        cls,
        unit: SubmissionUnit,
        rubric: RubricConfig,
        grade_points: dict[str, str],
        error_message: str,
    ) -> SubmissionResult:
        from .score import score_submission

        question_results = [
            QuestionResult(
                id=question.id,
                verdict="needs_review",
                confidence=0.0,
                short_reason=error_message,
                evidence_quote="",
            )
            for question in rubric.questions
        ]
        grade_result = score_submission(
            rubric=rubric,
            question_results=question_results,
            grade_points=grade_points,
        )
        return cls(
            submission=unit,
            question_results=question_results,
            grade_result=grade_result,
            output_pdf_paths=[],
            extraction_sources={},
            global_flags=["grading_error"],
            error=error_message,
        )


JsonDict = dict[str, Any]

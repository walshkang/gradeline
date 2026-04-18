from __future__ import annotations

from .types import GradeResult, QuestionResult, RubricConfig


VERDICT_TO_SCORE = {
    "correct": 1.0,
    "rounding_error": 1.0,
    "partial": 0.5,
    "incorrect": 0.0,
    "needs_review": 0.0,
}


def score_submission(
    rubric: RubricConfig,
    question_results: list[QuestionResult],
    grade_points: dict[str, str],
) -> GradeResult:
    question_map = {result.id: result for result in question_results}
    per_question_scores: dict[str, float] = {}

    total_weight = 0.0
    earned_weighted_score = 0.0
    has_needs_review = False

    for question in rubric.questions:
        result = question_map.get(question.id)
        verdict = result.verdict if result else "needs_review"
        if verdict == "needs_review":
            has_needs_review = True

        base_score = VERDICT_TO_SCORE.get(verdict, 0.0)
        if verdict == "partial":
            base_score = rubric.partial_credit
        per_question_scores[question.id] = base_score

        total_weight += question.weight
        earned_weighted_score += question.weight * base_score

    percent = 0.0 if total_weight <= 0 else (earned_weighted_score / total_weight) * 100.0

    band = determine_band(percent=percent, bands=rubric.bands, has_needs_review=has_needs_review)
    points = grade_points.get(band, "")
    return GradeResult(
        percent=round(percent, 2),
        band=band,
        points=str(points),
        has_needs_review=has_needs_review,
        per_question_scores=per_question_scores,
    )


def determine_band(percent: float, bands: dict[str, float], has_needs_review: bool) -> str:
    if has_needs_review:
        return "REVIEW_REQUIRED"

    check_plus_min = float(bands["check_plus_min"]) * 100.0
    check_min = float(bands["check_min"]) * 100.0
    if percent >= check_plus_min:
        return "Check Plus"
    if percent >= check_min:
        return "Check"
    return "Check Minus"


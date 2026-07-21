import re
from .types import GradeResult, QuestionResult, RubricConfig, ScoringCriterion


VERDICT_TO_SCORE = {
    "correct": 1.0,
    "rounding_error": 1.0,
    "partial": 0.5,
    "incorrect": 0.0,
    "needs_review": 0.0,
}


def compute_criteria_partial_score(
    logic_analysis: str,
    criteria: list[ScoringCriterion],
    fallback: float,
) -> float:
    if not criteria or not logic_analysis:
        return fallback

    total_weight = sum(sc.weight for sc in criteria)
    if total_weight <= 0:
        return fallback

    met_indices: set[int] = set()

    # Pattern 1: Explicit list preceding "met" (e.g. "Criteria 1, 3 met", "Criteria 1 and 2 met")
    for match in re.finditer(
        r"(?:criteria|criterion)?\s*([0-9\s,and&]+)\s*met\b",
        logic_analysis,
        flags=re.IGNORECASE,
    ):
        num_str = match.group(1)
        for num in re.findall(r"\b\d+\b", num_str):
            met_indices.add(int(num))

    # Pattern 2: Individual item matches like "Criterion 1: met" or "Criterion 1 is met"
    for match in re.finditer(
        r"\b(?:criterion|criteria)\s*(\d+)\s*(?:is|was|[:=])?\s*met\b",
        logic_analysis,
        flags=re.IGNORECASE,
    ):
        met_indices.add(int(match.group(1)))

    valid_met = {idx for idx in met_indices if 1 <= idx <= len(criteria)}
    if not valid_met:
        return fallback

    earned_weight = sum(criteria[idx - 1].weight for idx in valid_met)
    return earned_weight / total_weight


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
            if question.scoring_criteria and result:
                base_score = compute_criteria_partial_score(
                    logic_analysis=result.logic_analysis,
                    criteria=question.scoring_criteria,
                    fallback=rubric.partial_credit,
                )
            else:
                base_score = rubric.partial_credit
        per_question_scores[question.id] = base_score

        total_weight += question.weight
        earned_weighted_score += question.weight * base_score

    percent = 0.0 if total_weight <= 0 else (earned_weighted_score / total_weight) * 100.0

    band = determine_band(percent=percent, bands=rubric.bands, has_needs_review=has_needs_review)
    points = grade_points.get(band, "")
    if not points and band.replace(".", "", 1).isdigit():
        points = band

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

    # If it is the legacy check style:
    if "check_plus_min" in bands and "check_min" in bands:
        check_plus_min = float(bands["check_plus_min"]) * 100.0
        check_min = float(bands["check_min"]) * 100.0
        if percent >= check_plus_min:
            return "Check Plus"
        if percent >= check_min:
            return "Check"
        return "Check Minus"

    # Otherwise evaluate custom bands dynamically
    sorted_bands = []
    for name, val in bands.items():
        threshold = float(val)
        if threshold <= 1.0:
            threshold *= 100.0
        sorted_bands.append((name, threshold))

    sorted_bands.sort(key=lambda x: x[1], reverse=True)

    for name, threshold in sorted_bands:
        if percent >= threshold:
            return name

    # Fallback to the lowest threshold band if none matched
    if sorted_bands:
        return sorted_bands[-1][0]

    return "Check Minus"


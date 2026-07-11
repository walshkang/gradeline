import re

from .types import QuestionResult, RubricConfig


def regex_precheck(rubric: RubricConfig, combined_text: str) -> dict[str, QuestionResult]:
    """
    Run regex pre-check for questions that define `expected_answers`.
    If ALL patterns match, returns a correct QuestionResult.
    """
    results: dict[str, QuestionResult] = {}

    if not combined_text:
        return results

    for question in rubric.questions:
        if not question.expected_answers:
            continue

        all_matched = True
        evidence_quotes = []
        for pat in question.expected_answers:
            match = re.search(pat, combined_text, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                all_matched = False
                break
            evidence_quotes.append(match.group(0))

        if all_matched:
            results[question.id] = QuestionResult(
                id=question.id,
                verdict="correct",
                confidence=1.0,
                short_reason="",
                evidence_quote=" | ".join(evidence_quotes),
                grading_source="regex",
            )

    return results

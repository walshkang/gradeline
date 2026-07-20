import re

from .types import QuestionResult, RubricConfig


def regex_precheck(
    rubric: RubricConfig, combined_text: str
) -> tuple[dict[str, QuestionResult], dict[str, str]]:
    """
    Run regex pre-check for questions that define `expected_answers`.
    If ALL patterns match:
    - If requires_work is False, returns a correct QuestionResult in results.
    - If requires_work is True, skips prechecked result and populates hints with matched evidence.
    """
    results: dict[str, QuestionResult] = {}
    hints: dict[str, str] = {}

    if not combined_text:
        return results, hints

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
            evidence_str = " | ".join(evidence_quotes)
            if question.requires_work:
                hints[question.id] = evidence_str
            else:
                results[question.id] = QuestionResult(
                    id=question.id,
                    verdict="correct",
                    confidence=1.0,
                    short_reason="",
                    evidence_quote=evidence_str,
                    grading_source="regex",
                )

    return results, hints


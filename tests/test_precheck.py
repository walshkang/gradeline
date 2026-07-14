from grader.precheck import regex_precheck
from grader.types import QuestionRubric, RubricConfig


def test_regex_precheck_full_match():
    rubric = RubricConfig(
        assignment_id="hw1",
        bands={},
        questions=[
            QuestionRubric(
                id="q1",
                label_patterns=[],
                scoring_rules="",
                short_note_pass="",
                short_note_fail="Check",
                expected_answers=["493.*557"],
            )
        ],
    )
    combined_text = "The range is 493,000 to 557,000 as requested."

    results = regex_precheck(rubric, combined_text)
    assert "q1" in results
    assert results["q1"].verdict == "correct"
    assert results["q1"].confidence == 1.0
    assert results["q1"].grading_source == "regex"
    assert results["q1"].short_reason == ""
    assert "493,000 to 557" in results["q1"].evidence_quote


def test_regex_precheck_partial_match_fails():
    rubric = RubricConfig(
        assignment_id="hw1",
        bands={},
        questions=[
            QuestionRubric(
                id="q2",
                label_patterns=[],
                scoring_rules="",
                short_note_pass="",
                short_note_fail="Check",
                expected_answers=["hello", "world"],
            )
        ],
    )
    combined_text = "I am saying hello to you."

    results = regex_precheck(rubric, combined_text)
    assert "q2" not in results


def test_regex_precheck_no_match():
    rubric = RubricConfig(
        assignment_id="hw1",
        bands={},
        questions=[
            QuestionRubric(
                id="q3",
                label_patterns=[],
                scoring_rules="",
                short_note_pass="",
                short_note_fail="Check",
                expected_answers=["493.*557"],
            )
        ],
    )
    combined_text = "The range is 400,000 to 600,000 as requested."

    results = regex_precheck(rubric, combined_text)
    assert "q3" not in results


def test_regex_precheck_no_expected_answers():
    rubric = RubricConfig(
        assignment_id="hw1",
        bands={},
        questions=[
            QuestionRubric(
                id="q4",
                label_patterns=[],
                scoring_rules="",
                short_note_pass="",
                short_note_fail="Check",
                expected_answers=[],
            )
        ],
    )
    combined_text = "This should just fall through to the LLM."

    results = regex_precheck(rubric, combined_text)
    assert "q4" not in results


def test_regex_precheck_multiple_matches_all_success():
    rubric = RubricConfig(
        assignment_id="hw1",
        bands={},
        questions=[
            QuestionRubric(
                id="q5",
                label_patterns=[],
                scoring_rules="",
                short_note_pass="",
                short_note_fail="Check",
                expected_answers=["hello", "world"],
            )
        ],
    )
    combined_text = "I am saying hello to the world."

    results = regex_precheck(rubric, combined_text)
    assert "q5" in results
    assert results["q5"].verdict == "correct"
    assert "hello" in results["q5"].evidence_quote
    assert "world" in results["q5"].evidence_quote


def test_validate_expected_answers():
    import pytest
    import warnings
    from grader.config import validate_expected_answers

    # 1. Test warning when expected answer matches simulated headers/labels
    rubric_bad_label = RubricConfig(
        assignment_id="hw1",
        bands={},
        questions=[
            QuestionRubric(
                id="1",
                label_patterns=["Problem 1"],
                scoring_rules="",
                short_note_pass="",
                short_note_fail="Check",
                expected_answers=["1"],  # Raw '1' will match simulated label 'Problem 1' or '1.'
            )
        ],
    )
    with pytest.warns(UserWarning, match="matches simulated label/header"):
        validate_expected_answers(rubric_bad_label)

    # 2. Test warning when expected answer matches simulated incorrect values (lacks boundaries)
    rubric_no_boundary = RubricConfig(
        assignment_id="hw1",
        bands={},
        questions=[
            QuestionRubric(
                id="q1",
                label_patterns=[],
                scoring_rules="",
                short_note_pass="",
                short_note_fail="Check",
                expected_answers=["124"],  # Lacks boundaries, matches '1240' or '1124'
            )
        ],
    )
    with pytest.warns(UserWarning, match="lacks appropriate word boundaries"):
        validate_expected_answers(rubric_no_boundary)

    # 3. Test NO warning when expected answers have correct boundaries
    rubric_good = RubricConfig(
        assignment_id="hw1",
        bands={},
        questions=[
            QuestionRubric(
                id="q1",
                label_patterns=[],
                scoring_rules="",
                short_note_pass="",
                short_note_fail="Check",
                expected_answers=[r"\b124\b", r"\b-10\b", r"\b0\.114[4]?\b"],
            )
        ],
    )
    # Should not raise warnings for headers or missing boundaries
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        validate_expected_answers(rubric_good)


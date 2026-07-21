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

    results, hints = regex_precheck(rubric, combined_text)
    assert "q1" in results
    assert results["q1"].verdict == "correct"
    assert results["q1"].confidence == 1.0
    assert results["q1"].grading_source == "regex"
    assert results["q1"].short_reason == ""
    assert "493,000 to 557" in results["q1"].evidence_quote
    assert not hints


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

    results, hints = regex_precheck(rubric, combined_text)
    assert "q2" not in results
    assert "q2" not in hints


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

    results, hints = regex_precheck(rubric, combined_text)
    assert "q3" not in results
    assert "q3" not in hints


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

    results, hints = regex_precheck(rubric, combined_text)
    assert "q4" not in results
    assert "q4" not in hints


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

    results, hints = regex_precheck(rubric, combined_text)
    assert "q5" in results
    assert results["q5"].verdict == "correct"
    assert "hello" in results["q5"].evidence_quote
    assert "world" in results["q5"].evidence_quote
    assert not hints


def test_regex_precheck_requires_work_true_skips_result_and_returns_hint():
    rubric = RubricConfig(
        assignment_id="hw1",
        bands={},
        questions=[
            QuestionRubric(
                id="q6",
                label_patterns=[],
                scoring_rules="Must show work.",
                short_note_pass="",
                short_note_fail="Check",
                expected_answers=["167\\.78"],
                requires_work=True,
            )
        ],
    )
    combined_text = "The final answer is 167.78."

    results, hints = regex_precheck(rubric, combined_text)
    assert "q6" not in results
    assert "q6" in hints
    assert hints["q6"] == "167.78"


def test_regex_precheck_requires_work_false_default():
    rubric = RubricConfig(
        assignment_id="hw1",
        bands={},
        questions=[
            QuestionRubric(
                id="q7",
                label_patterns=[],
                scoring_rules="",
                short_note_pass="",
                short_note_fail="Check",
                expected_answers=["167\\.78"],
                requires_work=False,
            )
        ],
    )
    combined_text = "The final answer is 167.78."

    results, hints = regex_precheck(rubric, combined_text)
    assert "q7" in results
    assert "q7" not in hints
    assert results["q7"].verdict == "correct"


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


def test_precheck_optimizes_llm_grading():
    from grader.orchestrator import grade_one_submission, GradingConfig
    from grader.types import SubmissionUnit, QuestionRubric, RubricConfig, ExtractedPdf, QuestionResult
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    
    rubric = RubricConfig(
        assignment_id="test_opt",
        bands={},
        questions=[
            QuestionRubric(
                id="q1",
                label_patterns=[],
                scoring_rules="",
                short_note_pass="",
                short_note_fail="Fail",
                expected_answers=["123"],
            ),
            QuestionRubric(
                id="q2",
                label_patterns=[],
                scoring_rules="",
                short_note_pass="",
                short_note_fail="Fail",
                expected_answers=[],
            ),
        ],
    )
    
    combined_text = "The answer to q1 is 123."
    
    class CaptureGrader:
        def __init__(self):
            self.passed_questions = None
            
        def grade_submission(self, submission_id, pdf_paths, combined_text, rubric, solutions_text, *, questions_to_grade=None):
            self.passed_questions = questions_to_grade
            return [
                QuestionResult(
                    id="q2",
                    verdict="correct",
                    confidence=0.95,
                    short_reason="",
                    evidence_quote="some quote",
                )
            ], []
            
        def locate_answers_for_pdf(self, pdf_path, rubric, locator_model):
            return []
            
    grader = CaptureGrader()
    config = MagicMock()
    config.submissions_root = Path(".")
    config.output_dir = Path(".")
    config.temp_dir = Path(".")
    config.ocr_char_threshold = 100
    config.rubric = rubric
    config.solutions_text = "solution"
    config.solutions_pdf_path = Path("solutions.pdf")
    config.grade_points = {}
    config.grader = grader
    config.grading_mode = "legacy"
    config.agent_type = "gemini"
    config.context_cache = False
    config.context_cache_ttl_seconds = 300
    config.dry_run = False
    config.locator_model = None
    config.annotate_dry_run_marks = False
    config.extraction_model = "gemini-1.5-flash"
    config.gemini_api_key = "fake_key"
    config.extract_blocks = False
    config.diagnostics = None
    config.rate_limiter = None
    
    unit = SubmissionUnit(
        folder_path=Path("/tmp/student1"),
        folder_relpath=Path("student1"),
        folder_token="student1",
        student_name="Test Student",
        pdf_paths=[Path("a.pdf")],
    )
    
    extracted = ExtractedPdf(
        pdf_path=Path("a.pdf"),
        blocks=[],
        text=combined_text,
        source="ocr",
        native_char_count=100,
        ocr_char_count=100,
    )
    
    with patch("grader.grading.extract_pdf_text", return_value=extracted), \
         patch("grader.grading.score_submission") as mock_score:
         
        mock_score.return_value = MagicMock()
        
        res = grade_one_submission(
            unit=unit,
            config=config,
        )
        
        assert grader.passed_questions is not None
        assert len(grader.passed_questions) == 1
        assert grader.passed_questions[0].id == "q2"
        
        q_map = {qr.id: qr for qr in res.question_results}
        assert "q1" in q_map
        assert "q2" in q_map
        
        assert q_map["q1"].grading_source == "regex"
        assert q_map["q1"].diagnostics_trace == ("regex_precheck: match",)
        
        assert q_map["q2"].grading_source == "llm"
        assert q_map["q2"].diagnostics_trace == ("regex_precheck: skipped (no expected_answers)", "llm_grading: legacy")


def test_regex_precheck_with_expected_numeric_rubric():
    from pathlib import Path
    import tempfile
    from grader.config import load_rubric

    rubric_content = """
assignment_id: hw_numeric
scoring_mode: equal_weights
partial_credit: 0.5
bands:
  check_plus_min: 0.9
  check_min: 0.7
questions:
  - id: "q1"
    scoring_rules: "Rule 1"
    short_note_pass: "OK"
    short_note_fail: "Check"
    expected_numeric:
      value: 0.0808
      tolerance: 0.001
      allow_percent: true
"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "rubric.yaml"
        tmp_path.write_text(rubric_content, encoding="utf-8")
        rubric = load_rubric(tmp_path)

    text_dec = "The calculated probability is 0.0808 in this question."
    results_dec, hints_dec = regex_precheck(rubric, text_dec)
    assert "q1" in results_dec
    assert results_dec["q1"].verdict == "correct"
    assert results_dec["q1"].grading_source == "regex"

    text_pct = "The answer is 8.08%."
    results_pct, hints_pct = regex_precheck(rubric, text_pct)
    assert "q1" in results_pct
    assert results_pct["q1"].verdict == "correct"
    assert results_pct["q1"].grading_source == "regex"




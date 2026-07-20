import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from grader.judge import run_judge


def test_judge_prompt_contains_rounding_and_partial_audit(tmp_path, monkeypatch):
    """Test that run_judge includes expanded audit instructions for rounding_error, partial credit, and blank evidence."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    # Create dummy audit CSV
    audit_csv = output_dir / "grading_audit.csv"
    audit_csv.write_text(
        "student_name,question_id,verdict,logic_analysis,evidence_quote,detail_reason\n"
        "Alice Smith,q1,rounding_error,Minor calculation slip,12.5,Should be 12.3\n"
        "Alice Smith,q2,partial,Missing part b,,N/A\n"
    )

    # Create dummy review_state.json
    review_dir = output_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    review_state = {
        "submissions": {
            "sub_1": {
                "student_name": "Alice Smith",
                "questions": {}
            }
        }
    }
    state_file = review_dir / "review_state.json"
    state_file.write_text(json.dumps(review_state))

    # Create dummy rubric yaml
    rubric_file = tmp_path / "rubric.yaml"
    rubric_file.write_text(
        "bands:\n"
        "  Check Plus: 1.0\n"
        "  Check: 0.85\n"
        "  Check Minus: 0.65\n"
        "questions:\n"
        "  - id: q1\n"
        "    scoring_rules: Exact match\n"
        "    short_note_fail: Incorrect value\n"
        "  - id: q2\n"
        "    scoring_rules: Step by step\n"
        "    short_note_fail: Incomplete work\n"
    )

    # Mock workflow profile
    class DummyGradeProfile:
        def __init__(self):
            self.api_key = "dummy_key"
            self.output_dir = output_dir
            self.rubric_yaml = rubric_file
            self.models = {}

    class DummyProfile:
        def __init__(self):
            self.grade = DummyGradeProfile()

    monkeypatch.setattr("grader.judge.load_workflow_profile", lambda *args, **kwargs: DummyProfile())

    # Mock genai Client
    captured_contents = []

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "critiques": [
            {
                "question_id": "q1",
                "critique": "Valid rounding slip",
                "proposed_verdict": "rounding_error",
                "proposed_reason": "",
                "needs_fix": False
            }
        ]
    })
    mock_response.usage_metadata = None

    class MockModels:
        def generate_content(self, model, contents, config):
            captured_contents.append(contents)
            return mock_response

    class MockClient:
        def __init__(self, api_key=None):
            self.models = MockModels()

    monkeypatch.setattr("grader.judge.genai.Client", MockClient)

    # Run judge
    exit_code = run_judge(profile_spec="dummy")
    assert exit_code == 0
    assert len(captured_contents) == 1

    prompt = captured_contents[0]

    # Verify key audit requirements in prompt
    assert "CRITICAL: For any question with verdict 'rounding_error'" in prompt
    assert "A rounding_error verdict is fully forgiven (scored 1.0)" in prompt
    assert "For any question with verdict 'partial'" in prompt
    assert "evidence_quote is non-empty and actually supports" in prompt
    assert "For any non-correct verdict, if evidence_quote is blank or generic" in prompt

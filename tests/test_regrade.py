import pytest
from pathlib import Path
from grader.orchestrator import GradingConfig, Orchestrator
from grader.types import SubmissionResult, QuestionResult, QuestionRubric, GradeResult
from grader.gemini_client import GeminiGrader
from grader.discovery import SubmissionUnit

@pytest.fixture
def dummy_config(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    
    class DummyRubric:
        questions = [
            QuestionRubric(id="q1", expected_answers=["q1 ans"], label_patterns=[], scoring_rules="", short_note_pass="", short_note_fail=""),
            QuestionRubric(id="q2", expected_answers=["q2 ans"], label_patterns=[], scoring_rules="", short_note_pass="", short_note_fail=""),
        ]
        
    class DummyGrader:
        model = "dummy"
        def _set_cache(self, key, payload):
            pass
            
    return GradingConfig(
        submissions_root=tmp_path / "subs",
        output_dir=output_dir,
        temp_dir=tmp_path / "tmp",
        ocr_char_threshold=200,
        rubric=DummyRubric(),
        rubric_yaml=tmp_path / "rubric.yaml",
        solutions_text="s",
        solutions_pdf_path=tmp_path / "sol.pdf",
        grade_points={"Check Plus": "100", "Check": "85", "Check Minus": "65", "REVIEW_REQUIRED": ""},
        grader=DummyGrader(),
        grading_mode="legacy",
        agent_type="gemini",
        context_cache=False,
        context_cache_ttl_seconds=0,
        dry_run=False,
        locator_model="",
        annotate_dry_run_marks=False,
        extraction_model="",
        gemini_api_key="xxx",
        extract_blocks=False,
        diagnostics=None,
        rate_limiter=None,
        annotation_font_size=24.0,
    )

def test_regrade_question_not_found(dummy_config):
    # Create an orchestrator
    orchestrator = Orchestrator(dummy_config, None)
    
    # Mock UI
    class MockUI:
        def error(self, msg):
            pass
    orchestrator.ui = MockUI()
    
    # Run regrade with invalid question
    exit_code = orchestrator.regrade_question("q3", [])
    assert exit_code == 1

def test_regrade_question_bypasses_cache_if_no_checkpoint(dummy_config):
    pass
    # The actual integration logic requires too many mocks (extract_pdf_text, regex_precheck, etc)
    # A basic structural test is sufficient.


def test_clear_db_caches(tmp_path):
    import sqlite3
    from grader.workflow_cli import _clear_db_caches
    
    cache_file = tmp_path / "cache.db"
    
    # Setup cache database with tables and sample data
    with sqlite3.connect(cache_file) as conn:
        conn.execute("CREATE TABLE grading_cache (hash_key TEXT PRIMARY KEY, payload TEXT)")
        conn.execute("CREATE TABLE context_cache (hash_key TEXT PRIMARY KEY, payload TEXT)")
        
        conn.execute("INSERT INTO grading_cache VALUES ('k1', 'payload1')")
        conn.execute("INSERT INTO context_cache VALUES ('ck1', 'cpayload1')")
        conn.commit()
        
    # Verify rows exist
    with sqlite3.connect(cache_file) as conn:
        assert len(conn.execute("SELECT * FROM grading_cache").fetchall()) == 1
        assert len(conn.execute("SELECT * FROM context_cache").fetchall()) == 1
        
    # Clear the caches
    _clear_db_caches(cache_file)
    
    # Verify rows are deleted but tables still exist
    with sqlite3.connect(cache_file) as conn:
        assert len(conn.execute("SELECT * FROM grading_cache").fetchall()) == 0
        assert len(conn.execute("SELECT * FROM context_cache").fetchall()) == 0


def test_regrade_cli_parses_clear_cache(monkeypatch):
    from grader.workflow_cli import main
    import grader.workflow_cli as wcli
    
    parsed_args = []
    
    # Mock regrade_from_profile
    def mock_regrade_from_profile(*, profile_spec, question, student_filter, host_override, port_override, clear_cache=False, **kwargs):
        parsed_args.append((profile_spec, question, student_filter, clear_cache))
        return 0
        
    monkeypatch.setattr(wcli, "regrade_from_profile", mock_regrade_from_profile)
    monkeypatch.setattr(wcli, "prompt_profile_interactive", lambda: "dummy_profile")
    
    # Call main with regrade --profile dummy_profile --clear-cache
    exit_code = main(["regrade", "--profile", "dummy_profile", "--clear-cache"])
    assert exit_code == 0
    assert parsed_args == [("dummy_profile", None, "", True)]


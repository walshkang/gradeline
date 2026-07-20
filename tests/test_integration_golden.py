import shutil
import tempfile
from pathlib import Path
import pytest
import fitz

from grader.config import load_rubric
from grader.extract import extract_pdf_text
from grader.precheck import regex_precheck
from grader.score import score_submission
from grader.annotate import annotate_submission_pdfs
from grader.types import SubmissionUnit, QuestionResult

FIXTURE_DIR = Path(__file__).parent / "fixtures"

def generate_pdf_fixtures():
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    
    sub_path = FIXTURE_DIR / "sample_submission.pdf"
    if not sub_path.exists():
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text(fitz.Point(50, 100), "Student: Golden Student", fontsize=12)
        page.insert_text(fitz.Point(50, 150), "Q1) What is 2 + 2?  Answer: 4", fontsize=12)
        page.insert_text(fitz.Point(50, 200), "Q2) What is 10 * 5? Answer: 50", fontsize=12)
        page.insert_text(fitz.Point(50, 250), "Q3) What is 100 / 4? Answer: 25", fontsize=12)
        doc.save(sub_path)
        doc.close()

    sol_path = FIXTURE_DIR / "sample_solutions.pdf"
    if not sol_path.exists():
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text(fitz.Point(50, 100), "Solutions Key", fontsize=14)
        page.insert_text(fitz.Point(50, 150), "Q1 Solution: 4", fontsize=12)
        page.insert_text(fitz.Point(50, 200), "Q2 Solution: 50", fontsize=12)
        page.insert_text(fitz.Point(50, 250), "Q3 Solution: 25", fontsize=12)
        doc.save(sol_path)
        doc.close()


@pytest.fixture(scope="module", autouse=True)
def setup_fixtures():
    generate_pdf_fixtures()


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext binary not found")
def test_regex_precheck_golden_output():
    rubric_path = FIXTURE_DIR / "sample_rubric.yaml"
    rubric = load_rubric(rubric_path)
    
    sub_path = FIXTURE_DIR / "sample_submission.pdf"
    with tempfile.TemporaryDirectory() as tmpdir:
        extracted = extract_pdf_text(sub_path, temp_dir=Path(tmpdir))
        results, _ = regex_precheck(rubric, extracted.text)
        
        assert "q1" in results
        assert results["q1"].verdict == "correct"
        assert results["q1"].grading_source == "regex"

        assert "q2" in results
        assert results["q2"].verdict == "correct"
        assert results["q2"].grading_source == "regex"

        assert "q3" in results
        assert results["q3"].verdict == "correct"
        assert results["q3"].grading_source == "regex"


def test_scoring_golden_output():
    rubric_path = FIXTURE_DIR / "sample_rubric.yaml"
    rubric = load_rubric(rubric_path)
    
    results = [
        QuestionResult(id="q1", verdict="correct", confidence=1.0, short_reason="", evidence_quote=""),
        QuestionResult(id="q2", verdict="correct", confidence=1.0, short_reason="", evidence_quote=""),
        QuestionResult(id="q3", verdict="correct", confidence=1.0, short_reason="", evidence_quote=""),
    ]
    
    grade = score_submission(
        rubric=rubric,
        question_results=results,
        grade_points={"Check Plus": "100", "Check": "85", "Check Minus": "65", "REVIEW_REQUIRED": ""},
    )
    assert grade.band == "Check Plus"
    assert grade.percent == 100.0


def test_annotation_golden_output():
    rubric_path = FIXTURE_DIR / "sample_rubric.yaml"
    rubric = load_rubric(rubric_path)
    
    results = [
        QuestionResult(id="q1", verdict="correct", confidence=1.0, short_reason="", evidence_quote="", coords=(150, 50), page_number=1, source_file="sample_submission.pdf"),
        QuestionResult(id="q2", verdict="correct", confidence=1.0, short_reason="", evidence_quote="", coords=(200, 50), page_number=1, source_file="sample_submission.pdf"),
        QuestionResult(id="q3", verdict="correct", confidence=1.0, short_reason="", evidence_quote="", coords=(250, 50), page_number=1, source_file="sample_submission.pdf"),
    ]
    
    sub_path = FIXTURE_DIR / "sample_submission.pdf"
    
    submission = SubmissionUnit(
        folder_path=FIXTURE_DIR,
        folder_relpath=Path("fixtures"),
        folder_token="fixtures",
        student_name="Golden Student",
        pdf_paths=[sub_path],
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "out"
        output_paths, _ = annotate_submission_pdfs(
            submission=submission,
            rubric=rubric,
            question_results=results,
            output_dir=output_dir,
            submissions_root=FIXTURE_DIR,
            final_band="Check Plus",
        )
        
        assert len(output_paths) == 1
        annotated_pdf = output_paths[0]
        assert annotated_pdf.exists()
        
        # Verify it's a valid PDF by opening it with fitz
        doc = fitz.open(annotated_pdf)
        assert len(doc) == 1
        page = doc[0]
        annots = list(page.annots())
        # Header + 3 question annotations
        assert len(annots) == 4
        doc.close()

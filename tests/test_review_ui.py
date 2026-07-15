from __future__ import annotations

import json
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Generator
import pytest
import fitz

from grader.review.api import ReviewApi
from grader.review.server import ReviewRequestHandler
from grader.review.state import state_path_for_output, write_state_atomic
from grader.review.types import SCHEMA_VERSION
from playwright.sync_api import Page


def make_pdf(path: Path) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), "dummy submission pdf")
        doc.save(path)
    finally:
        doc.close()


def make_state(output_dir: Path) -> None:
    (output_dir / "subs" / "123 - Jane").mkdir(parents=True, exist_ok=True)
    (output_dir / "subs" / "456 - John").mkdir(parents=True, exist_ok=True)

    pdf_jane = output_dir / "subs" / "123 - Jane" / "submission.pdf"
    pdf_john = output_dir / "subs" / "456 - John" / "submission.pdf"
    make_pdf(pdf_jane)
    make_pdf(pdf_john)

    state = {
        "schema_version": SCHEMA_VERSION,
        "run_metadata": {
            "run_id": "run123",
            "output_dir": str(output_dir),
            "initialized_at": "2026-02-25T00:00:00Z",
            "updated_at": "2026-02-25T00:00:00Z",
        },
        "grading_context": {
            "args_snapshot": {
                "submissions_dir": str(output_dir / "subs"),
            },
            "grade_points": {
                "Check Plus": "100",
                "Check": "85",
                "Check Minus": "65",
                "REVIEW_REQUIRED": "0",
            },
            "rubric": {
                "assignment_id": "a1",
                "bands": {"check_plus_min": 0.9, "check_min": 0.7},
                "scoring_mode": "equal_weights",
                "partial_credit": 0.5,
                "questions": [
                    {
                        "id": "a",
                        "label_patterns": ["a)"],
                        "scoring_rules": "",
                        "short_note_pass": "ok",
                        "short_note_fail": "check",
                        "weight": 1.0,
                        "anchor_tokens": [],
                    },
                    {
                        "id": "b",
                        "label_patterns": ["b)"],
                        "scoring_rules": "",
                        "short_note_pass": "ok",
                        "short_note_fail": "check",
                        "weight": 1.0,
                        "anchor_tokens": [],
                    },
                ],
            },
        },
        "submissions": {
            "sub-jane": {
                "submission_id": "sub-jane",
                "identity": {
                    "folder_path": str(output_dir / "subs" / "123 - Jane"),
                    "folder_relpath": "123 - Jane",
                    "folder_token": "123",
                    "student_name": "Jane",
                    "pdf_paths": [str(pdf_jane)],
                },
                "auto_summary": {"percent": 0.0, "band": "Check Minus", "points": "65", "error": "", "flags": []},
                "final_summary": {"percent": 0.0, "band": "Check Minus", "points": "65"},
                "review_status": "todo",
                "note": "",
                "updated_at": "2026-02-25T00:00:00Z",
                "questions": {
                    "a": {
                        "id": "a",
                        "auto": {
                            "verdict": "needs_review",
                            "confidence": 0.2,
                            "short_reason": "needs manual check",
                            "evidence_quote": "",
                            "coords": [100.0, 200.0],
                            "page_number": 1,
                            "source_file": "submission.pdf",
                            "placement_source": "model_coords",
                        },
                        "final": {
                            "verdict": "needs_review",
                            "confidence": 0.2,
                            "short_reason": "needs manual check",
                            "evidence_quote": "",
                            "coords": [100.0, 200.0],
                            "page_number": 1,
                            "source_file": "submission.pdf",
                            "placement_source": "model_coords",
                        },
                        "is_overridden": False,
                        "updated_at": "2026-02-25T00:00:00Z",
                    },
                    "b": {
                        "id": "b",
                        "auto": {
                            "verdict": "correct",
                            "confidence": 0.95,
                            "short_reason": "ok",
                            "evidence_quote": "",
                            "coords": [100.0, 400.0],
                            "page_number": 2,
                            "source_file": "submission.pdf",
                            "placement_source": "model_coords",
                        },
                        "final": {
                            "verdict": "correct",
                            "confidence": 0.95,
                            "short_reason": "ok",
                            "evidence_quote": "",
                            "coords": [100.0, 400.0],
                            "page_number": 2,
                            "source_file": "submission.pdf",
                            "placement_source": "model_coords",
                        },
                        "is_overridden": False,
                        "updated_at": "2026-02-25T00:00:00Z",
                    },
                },
            },
            "sub-john": {
                "submission_id": "sub-john",
                "identity": {
                    "folder_path": str(output_dir / "subs" / "456 - John"),
                    "folder_relpath": "456 - John",
                    "folder_token": "456",
                    "student_name": "John",
                    "pdf_paths": [str(pdf_john)],
                },
                "auto_summary": {"percent": 1.0, "band": "Check Plus", "points": "100", "error": "", "flags": []},
                "final_summary": {"percent": 1.0, "band": "Check Plus", "points": "100"},
                "review_status": "todo",
                "note": "",
                "updated_at": "2026-02-25T00:00:00Z",
                "questions": {
                    "a": {
                        "id": "a",
                        "auto": {
                            "verdict": "correct",
                            "confidence": 0.95,
                            "short_reason": "ok",
                            "evidence_quote": "",
                            "coords": [100.0, 200.0],
                            "page_number": 1,
                            "source_file": "submission.pdf",
                            "placement_source": "model_coords",
                        },
                        "final": {
                            "verdict": "correct",
                            "confidence": 0.95,
                            "short_reason": "ok",
                            "evidence_quote": "",
                            "coords": [100.0, 200.0],
                            "page_number": 1,
                            "source_file": "submission.pdf",
                            "placement_source": "model_coords",
                        },
                        "is_overridden": False,
                        "updated_at": "2026-02-25T00:00:00Z",
                    }
                },
            },
        },
    }

    (output_dir / "review").mkdir(parents=True, exist_ok=True)
    write_state_atomic(state_path_for_output(output_dir), state)


@pytest.fixture
def review_server() -> Generator[tuple[str, Path], None, None]:
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp)
        make_state(output_dir)

        api = ReviewApi(output_dir)
        import grader.review.server
        static_root = Path(grader.review.server.__file__).parent / "static"

        class BoundHandler(ReviewRequestHandler):
            pass

        BoundHandler.api = api
        BoundHandler.static_root = static_root

        server = ThreadingHTTPServer(("127.0.0.1", 0), BoundHandler)
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}"

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        yield url, output_dir

        server.shutdown()
        server.server_close()
        thread.join()


def test_question_nav_grid_renders(page: Page, review_server: tuple[str, Path]) -> None:
    url, output_dir = review_server
    page.goto(url)

    # Wait for the submissions queue to load and select the first submission (Jane)
    page.wait_for_selector(".queue-item")

    # Verify that the question navigation grid is rendered
    grid = page.locator("#questionNavGrid")
    grid.wait_for()

    # Jane has question "a" (needs_review) and "b" (correct)
    # Check that cards exist with appropriate classes
    card_a = grid.locator(".question-nav-card").filter(has_text="Qa")
    card_b = grid.locator(".question-nav-card").filter(has_text="Qb")

    # Wait for selectors
    card_a.wait_for()
    card_b.wait_for()

    # Verify class names
    classes_a = card_a.evaluate("el => el.className")
    classes_b = card_b.evaluate("el => el.className")

    assert "needs_review" in classes_a
    assert "correct" in classes_b


def test_card_click_navigation(page: Page, review_server: tuple[str, Path]) -> None:
    url, output_dir = review_server
    page.goto(url)

    page.wait_for_selector(".queue-item")
    grid = page.locator("#questionNavGrid")
    grid.wait_for()

    card_b = grid.locator(".question-nav-card").filter(has_text="Qb")
    card_b.wait_for()

    # Initially page should be 1 (since question 'a' is on page 1)
    page_input = page.locator("#pageInput")
    assert page_input.input_value() == "1"

    # Click card B
    card_b.click()

    # Card B is on page 2. Let's verify that pageInput updates to "2"
    page.wait_for_function("document.getElementById('pageInput').value === '2'")
    assert page_input.input_value() == "2"


def test_reviewed_checkbox_patch(page: Page, review_server: tuple[str, Path]) -> None:
    url, output_dir = review_server
    page.goto(url)

    page.wait_for_selector(".queue-item")

    # Find reviewed checkbox
    checkbox = page.locator("#questionReviewedCheckbox")
    checkbox.wait_for()

    # Initially unchecked
    assert not checkbox.is_checked()

    # Check it. We wait for the PATCH request to /api/submissions/*/questions/* to complete
    with page.expect_response("**/api/submissions/*/questions/*") as response_info:
        checkbox.check()

    response = response_info.value
    assert response.status == 200
    assert response.json()["question"]["final"]["reviewed"] is True

    # Also verify in the database file
    state_file = output_dir / "review" / "review_state.json"
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["submissions"]["sub-jane"]["questions"]["a"]["final"]["reviewed"] is True

    # Uncheck it
    with page.expect_response("**/api/submissions/*/questions/*") as response_info:
        checkbox.uncheck()

    response = response_info.value
    assert response.status == 200
    assert response.json()["question"]["final"]["reviewed"] is False

    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["submissions"]["sub-jane"]["questions"]["a"]["final"]["reviewed"] is False


def test_submission_status_patch_done_no_warning(page: Page, review_server: tuple[str, Path]) -> None:
    url, output_dir = review_server
    page.goto(url)
    page.wait_for_selector(".queue-item")

    # Select John (the second submission)
    john_btn = page.locator(".queue-item").filter(has_text="John")
    john_btn.wait_for()
    john_btn.click()

    # Verify John's title is displayed
    page.wait_for_selector("#submissionTitle:has-text('John')")

    # Verify status select value is initially "todo"
    status_select = page.locator("#submissionStatusSelect")
    assert status_select.input_value() == "todo"

    # Select "done". Since there are no needs_review questions, it should proceed directly.
    with page.expect_response("**/api/submissions/sub-john") as response_info:
        status_select.select_option(value="done")

    response = response_info.value
    assert response.status == 200
    assert response.json()["review_status"] == "done"

    # Verify database file
    state_file = output_dir / "review" / "review_state.json"
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["submissions"]["sub-john"]["review_status"] == "done"


def test_submission_status_done_warning_dismiss(page: Page, review_server: tuple[str, Path]) -> None:
    url, output_dir = review_server
    page.goto(url)
    page.wait_for_selector(".queue-item")

    # Jane has question "a" with needs_review, so changing to done triggers a confirmation dialog.
    status_select = page.locator("#submissionStatusSelect")
    assert status_select.input_value() == "todo"

    # Handle the dialog by dismissing it
    def handle_dialog(dialog):
        assert "unresolved questions" in dialog.message
        dialog.dismiss()

    page.once("dialog", handle_dialog)

    # Attempt to change to done
    status_select.select_option(value="done")

    # The selection should revert to "todo"
    page.wait_for_function("document.getElementById('submissionStatusSelect').value === 'todo'")
    assert status_select.input_value() == "todo"

    # Verify no PATCH was persisted
    state_file = output_dir / "review" / "review_state.json"
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["submissions"]["sub-jane"]["review_status"] == "todo"


def test_submission_status_done_warning_accept(page: Page, review_server: tuple[str, Path]) -> None:
    url, output_dir = review_server
    page.goto(url)
    page.wait_for_selector(".queue-item")

    # Jane has question "a" with needs_review
    status_select = page.locator("#submissionStatusSelect")
    assert status_select.input_value() == "todo"

    # Handle the dialog by accepting it
    def handle_dialog(dialog):
        assert "unresolved questions" in dialog.message
        dialog.accept()

    page.once("dialog", handle_dialog)

    # Attempt to change to done. We expect a patch to **/api/submissions/sub-jane
    with page.expect_response("**/api/submissions/sub-jane") as response_info:
        status_select.select_option(value="done")

    response = response_info.value
    assert response.status == 200
    assert response.json()["review_status"] == "done"

    # The selection should be "done"
    assert status_select.input_value() == "done"

    # Verify PATCH was persisted
    state_file = output_dir / "review" / "review_state.json"
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["submissions"]["sub-jane"]["review_status"] == "done"

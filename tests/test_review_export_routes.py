from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import urllib.request

import fitz

from grader.review.api import ReviewApi
from grader.review.server import ReviewRequestHandler
from grader.review.state import state_path_for_output, write_state_atomic
from grader.review.types import SCHEMA_VERSION


def make_test_pdf(path: Path) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 120), "a)", fontsize=12, fontname="helv")
        doc.save(path)
    finally:
        doc.close()


def create_test_review_env(tmp_dir: Path) -> tuple[Path, ReviewApi]:
    submissions_dir = tmp_dir / "subs"
    student_dir = submissions_dir / "123 - Jane Doe"
    student_dir.mkdir(parents=True)
    pdf_path = student_dir / "submission.pdf"
    make_test_pdf(pdf_path)

    output_dir = tmp_dir / "out"
    output_dir.mkdir()
    (output_dir / "review").mkdir()

    template_csv = tmp_dir / "template.csv"
    template_csv.write_text(
        "OrgDefinedId,First Name,Last Name,Assignment 1 Points Grade\n123,Jane,Doe,\n",
        encoding="utf-8",
    )

    submission_id = "sub-1"
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
                "submissions_dir": str(submissions_dir),
                "grades_template_csv": str(template_csv),
                "grade_column": "Assignment 1 Points Grade",
                "identifier_column": "OrgDefinedId",
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
                    }
                ],
            },
        },
        "submissions": {
            submission_id: {
                "submission_id": submission_id,
                "identity": {
                    "folder_path": str(student_dir),
                    "folder_relpath": "123 - Jane Doe",
                    "folder_token": "123",
                    "student_name": "Jane Doe",
                    "pdf_paths": [str(pdf_path)],
                },
                "auto_summary": {"percent": 0.0, "band": "Check Minus", "points": "65", "error": "", "flags": []},
                "final_summary": {"percent": 100.0, "band": "Check Plus", "points": "100"},
                "review_status": "done",
                "note": "",
                "updated_at": "2026-02-25T00:00:00Z",
                "questions": {
                    "a": {
                        "question_id": "a",
                        "verdict_auto": "incorrect",
                        "verdict_final": "correct",
                        "confidence": 1.0,
                        "evidence_quote": "a)",
                        "logic_analysis": "Correct",
                        "short_reason": "ok",
                        "page_number": 1,
                        "bbox_norm": [100, 100, 200, 200],
                        "source_file": "submission.pdf",
                        "grading_source": "manual",
                        "reviewed": True,
                    }
                },
            }
        },
    }

    state_path = state_path_for_output(output_dir)
    write_state_atomic(state_path, state)
    api = ReviewApi(output_dir)
    return output_dir, api


class ReviewExportRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir_obj = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp_dir_obj.name)
        self.output_dir, self.api = create_test_review_env(self.tmp_dir)

        class BoundHandler(ReviewRequestHandler):
            pass

        BoundHandler.api = self.api
        BoundHandler.static_root = self.tmp_dir

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BoundHandler)
        self.port = self.server.server_port
        self.server_thread = Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.tmp_dir_obj.cleanup()

    def test_export_api_helpers_direct(self) -> None:
        # Test export_file CSV
        csv_bytes, csv_name, content_type = self.api.export_file("brightspace_grades_import_reviewed.csv")
        self.assertEqual(csv_name, "brightspace_grades_import_reviewed.csv")
        self.assertEqual(content_type, "text/csv")
        self.assertIn(b"Jane", csv_bytes)

        # Test export_pdfs_zip
        pdfs_bytes, pdfs_name = self.api.export_pdfs_zip()
        self.assertEqual(pdfs_name, "reviewed_pdfs.zip")
        with zipfile.ZipFile(io.BytesIO(pdfs_bytes), "r") as zf:
            names = zf.namelist()
            self.assertTrue(any("submission.pdf" in n for n in names))

        # Test export_bundle_zip
        bundle_bytes, bundle_name = self.api.export_bundle_zip()
        self.assertEqual(bundle_name, "export_bundle.zip")
        with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as zf:
            names = zf.namelist()
            self.assertIn("brightspace_grades_import_reviewed.csv", names)
            self.assertIn("grading_audit_reviewed.csv", names)

    def test_export_get_routes_via_http(self) -> None:
        base_url = f"http://127.0.0.1:{self.port}"

        # 1. GET /api/export/csv
        req = urllib.request.Request(f"{base_url}/api/export/csv")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, HTTPStatus.OK)
            self.assertEqual(resp.headers.get("Content-Type"), "text/csv")
            self.assertIn('attachment; filename="brightspace_grades_import_reviewed.csv"', resp.headers.get("Content-Disposition", ""))
            body = resp.read()
            self.assertIn(b"Jane", body)

        # 2. GET /api/export/audit
        req = urllib.request.Request(f"{base_url}/api/export/audit")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, HTTPStatus.OK)
            self.assertEqual(resp.headers.get("Content-Type"), "text/csv")
            self.assertIn('attachment; filename="grading_audit_reviewed.csv"', resp.headers.get("Content-Disposition", ""))
            body = resp.read()
            self.assertIn(b"Jane Doe", body)

        # 3. GET /api/export/pdfs
        req = urllib.request.Request(f"{base_url}/api/export/pdfs")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, HTTPStatus.OK)
            self.assertEqual(resp.headers.get("Content-Type"), "application/zip")
            self.assertIn('attachment; filename="reviewed_pdfs.zip"', resp.headers.get("Content-Disposition", ""))
            body = resp.read()
            with zipfile.ZipFile(io.BytesIO(body), "r") as zf:
                self.assertTrue(len(zf.namelist()) > 0)

        # 4. GET /api/export/bundle
        req = urllib.request.Request(f"{base_url}/api/export/bundle")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, HTTPStatus.OK)
            self.assertEqual(resp.headers.get("Content-Type"), "application/zip")
            self.assertIn('attachment; filename="export_bundle.zip"', resp.headers.get("Content-Disposition", ""))
            body = resp.read()
            with zipfile.ZipFile(io.BytesIO(body), "r") as zf:
                self.assertIn("brightspace_grades_import_reviewed.csv", zf.namelist())


if __name__ == "__main__":
    unittest.main()

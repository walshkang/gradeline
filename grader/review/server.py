from __future__ import annotations

import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .api import ReviewApi, ReviewApiError
from .raster import parse_scale
from .grading_session import GradingSessionManager


class ReviewRequestHandler(BaseHTTPRequestHandler):
    api: ReviewApi
    static_root: Path
    session_manager: GradingSessionManager

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/run":
            self._send_json(HTTPStatus.OK, self.api.get_run())
            return

        if path == "/api/matrix":
            self._send_json(HTTPStatus.OK, self.api.get_matrix())
            return

        if path == "/api/export/csv":
            try:
                body, filename, content_type = self.api.export_file("brightspace_grades_import_reviewed.csv")
            except Exception as exc:  # noqa: BLE001
                self._send_json_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_file_attachment(HTTPStatus.OK, body, filename, content_type)
            return

        if path == "/api/export/audit":
            try:
                body, filename, content_type = self.api.export_file("grading_audit_reviewed.csv")
            except Exception as exc:  # noqa: BLE001
                self._send_json_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_file_attachment(HTTPStatus.OK, body, filename, content_type)
            return

        if path == "/api/export/pdfs":
            try:
                body, filename = self.api.export_pdfs_zip()
            except Exception as exc:  # noqa: BLE001
                self._send_json_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_file_attachment(HTTPStatus.OK, body, filename, "application/zip")
            return

        if path == "/api/export/bundle":
            try:
                body, filename = self.api.export_bundle_zip()
            except Exception as exc:  # noqa: BLE001
                self._send_json_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_file_attachment(HTTPStatus.OK, body, filename, "application/zip")
            return

        if path == "/api/submissions":
            status = first_query_value(query, "status")
            text_query = first_query_value(query, "q")
            payload = self.api.list_submissions(status=status, query=text_query)
            self._send_json(HTTPStatus.OK, {"items": payload})
            return

        submission_match = re.fullmatch(r"/api/submissions/([^/]+)", path)
        if submission_match:
            submission_id = submission_match.group(1)
            document_source = first_query_value(query, "doc_source")
            try:
                payload = self.api.get_submission(submission_id, document_source=document_source)
            except ReviewApiError as exc:
                self._send_json_error(HTTPStatus.NOT_FOUND, str(exc))
                return
            self._send_json(HTTPStatus.OK, payload)
            return

        meta_match = re.fullmatch(
            r"/api/submissions/([^/]+)/documents/(\d+)/pages/(\d+)/meta",
            path,
        )
        if meta_match:
            submission_id, doc_idx_raw, page_idx_raw = meta_match.groups()
            scale = parse_scale(first_query_value(query, "scale"))
            document_source = first_query_value(query, "doc_source")
            try:
                payload = self.api.get_page_meta(
                    submission_id=submission_id,
                    doc_idx=int(doc_idx_raw),
                    page_idx=int(page_idx_raw),
                    scale=scale,
                    document_source=document_source,
                )
            except (ReviewApiError, FileNotFoundError, ValueError, IndexError) as exc:
                self._send_json_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(HTTPStatus.OK, payload)
            return

        image_match = re.fullmatch(
            r"/api/submissions/([^/]+)/documents/(\d+)/pages/(\d+)/image",
            path,
        )
        if image_match:
            submission_id, doc_idx_raw, page_idx_raw = image_match.groups()
            scale = parse_scale(first_query_value(query, "scale"))
            document_source = first_query_value(query, "doc_source")
            try:
                image = self.api.get_page_image(
                    submission_id=submission_id,
                    doc_idx=int(doc_idx_raw),
                    page_idx=int(page_idx_raw),
                    scale=scale,
                    document_source=document_source,
                )
            except (ReviewApiError, FileNotFoundError, ValueError, IndexError) as exc:
                self._send_json_error(HTTPStatus.BAD_REQUEST, str(exc))
                return

            request_etag = self.headers.get("If-None-Match", "")
            if request_etag and request_etag == image.meta.etag:
                self.send_response(HTTPStatus.NOT_MODIFIED)
                self.send_header("ETag", image.meta.etag)
                self.send_header("Cache-Control", "private, max-age=60")
                self.end_headers()
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(image.png_bytes)))
            self.send_header("ETag", image.meta.etag)
            self.send_header("Cache-Control", "private, max-age=60")
            self.end_headers()
            self.wfile.write(image.png_bytes)
            return

        if path == "/api/grade/status":
            status = self.session_manager.get_status()
            self._send_json(HTTPStatus.OK, status)
            return

        if path == "/api/grade/progress":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            
            try:
                for event_bytes in self.session_manager.events_generator():
                    self.wfile.write(event_bytes)
                    self.wfile.flush()
            except Exception:
                pass
            return

        self._serve_static(path)

    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_json_body()
        if body is None:
            return

        question_match = re.fullmatch(r"/api/submissions/([^/]+)/questions/([^/]+)", path)
        if question_match:
            submission_id, question_id = question_match.groups()
            try:
                payload = self.api.patch_question(submission_id, question_id, body)
            except ReviewApiError as exc:
                self._send_json_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(HTTPStatus.OK, payload)
            return

        note_match = re.fullmatch(r"/api/submissions/([^/]+)/note", path)
        if note_match:
            submission_id = note_match.group(1)
            note = str(body.get("note", "")) if isinstance(body, dict) else ""
            try:
                payload = self.api.patch_note(submission_id, note)
            except ReviewApiError as exc:
                self._send_json_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(HTTPStatus.OK, payload)
            return

        submission_match = re.fullmatch(r"/api/submissions/([^/]+)", path)
        if submission_match:
            submission_id = submission_match.group(1)
            try:
                payload = self.api.patch_submission(submission_id, body)
            except ReviewApiError as exc:
                self._send_json_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(HTTPStatus.OK, payload)
            return

        if path == "/api/grading-context":
            try:
                payload = self.api.patch_grading_context(body)
            except ReviewApiError as exc:
                self._send_json_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(HTTPStatus.OK, payload)
            return

        self._send_json_error(HTTPStatus.NOT_FOUND, f"Unknown path: {path}")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/export":
            try:
                payload = self.api.export()
            except Exception as exc:  # noqa: BLE001
                self._send_json_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(HTTPStatus.OK, {"artifacts": payload})
            return
            
        if path == "/api/grade/start":
            body = self._read_json_body()
            if not body:
                return
            profile = body.get("profile", "").strip()
            if not profile:
                self._send_json_error(HTTPStatus.BAD_REQUEST, "Missing profile.")
                return
            try:
                self.session_manager.start_grading(profile)
                self._send_json(HTTPStatus.OK, {"status": "started"})
            except ValueError as e:
                self._send_json_error(HTTPStatus.CONFLICT, str(e))
            return

        if path == "/api/grade/cancel":
            self.session_manager.cancel()
            self._send_json(HTTPStatus.OK, {"status": "cancelled"})
            return

        if path == "/api/setup/upload":
            parsed_form = self._read_multipart_body()
            if not parsed_form:
                return
            fields, files = parsed_form
            
            profile = fields.get("profile", "").strip()
            if not profile or not re.match(r"^[a-zA-Z0-9_-]+$", profile):
                self._send_json_error(HTTPStatus.BAD_REQUEST, "Invalid profile name.")
                return
                
            from grader.workflow.profile_utils import get_project_root
            data_root = get_project_root() / "data"
            profile_dir = data_root / profile
            profile_dir.mkdir(parents=True, exist_ok=True)
            
            import shutil
            uploaded_metadata = {}
            for field_name, file_info in files.items():
                filename = file_info["filename"]
                fileobj = file_info["file_object"]
                fileobj.seek(0)
                
                if field_name == "submissions_zip" and filename.endswith(".zip"):
                    zip_path = profile_dir / filename
                    with open(zip_path, "wb") as out_f:
                        shutil.copyfileobj(fileobj, out_f)
                    
                    from grader.workflow.import_cmd import _extract_brightspace_zip
                    _extract_brightspace_zip(zip_path, profile, data_root)
                    zip_path.unlink()
                    uploaded_metadata["submissions_zip"] = True
                
                elif field_name == "solutions_pdf":
                    dest = profile_dir / "solutions.pdf"
                    with open(dest, "wb") as out_f:
                        shutil.copyfileobj(fileobj, out_f)
                    uploaded_metadata["solutions_pdf"] = True

                elif field_name == "rubric_yaml":
                    dest = profile_dir / "rubric.yaml"
                    with open(dest, "wb") as out_f:
                        shutil.copyfileobj(fileobj, out_f)
                    uploaded_metadata["rubric_yaml"] = True

                elif field_name == "grades_template_csv":
                    dest = profile_dir / "grades.csv"
                    with open(dest, "wb") as out_f:
                        shutil.copyfileobj(fileobj, out_f)
                    uploaded_metadata["grades_template_csv"] = True
                    
                    from grader.report import read_csv_rows
                    try:
                        _, headers = read_csv_rows(dest)
                        uploaded_metadata["csv_headers"] = headers
                    except Exception as exc:
                        uploaded_metadata["csv_error"] = str(exc)
                        
            self._send_json(HTTPStatus.OK, {"status": "success", "uploaded": uploaded_metadata})
            return

        if path == "/api/setup/profile":
            body = self._read_json_body()
            if not body:
                return
                
            profile = body.get("profile", "").strip()
            if not profile or not re.match(r"^[a-zA-Z0-9_-]+$", profile):
                self._send_json_error(HTTPStatus.BAD_REQUEST, "Invalid profile name.")
                return

            from grader.workflow.profile_utils import render_profile_toml, get_project_root
            data_root = get_project_root() / "data"
            profile_dir = data_root / profile
            profile_dir.mkdir(parents=True, exist_ok=True)
            
            try:
                profile_text = render_profile_toml(
                    submissions_dir=profile_dir / "submissions",
                    solutions_pdf=profile_dir / "solutions.pdf",
                    rubric_yaml=profile_dir / "rubric.yaml",
                    grades_template_csv=profile_dir / "grades.csv",
                    grade_column=body.get("grade_column", "Grade"),
                    output_dir=get_project_root() / "outputs" / profile,
                    host="127.0.0.1",
                    port=8765,
                    optional_grade_values={
                        "model": body.get("model"),
                        "concurrency": body.get("concurrency", 4),
                        "check_plus_points": body.get("check_plus_points"),
                        "check_points": body.get("check_points"),
                        "check_minus_points": body.get("check_minus_points"),
                        "review_required_points": body.get("review_required_points"),
                    }
                )
                
                profile_path = get_project_root() / "configs" / "profiles" / f"{profile}.toml"
                profile_path.parent.mkdir(parents=True, exist_ok=True)
                profile_path.write_text(profile_text, encoding="utf-8")
                
            except Exception as exc:
                self._send_json_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
                
            self._send_json(HTTPStatus.OK, {"status": "success", "profile": profile})
            return

        if path == "/api/setup/rubric/generate":
            body = self._read_json_body()
            if not body:
                return
            profile = body.get("profile", "").strip()
            if not profile or not re.match(r"^[a-zA-Z0-9_-]+$", profile):
                self._send_json_error(HTTPStatus.BAD_REQUEST, "Invalid profile name.")
                return

            from grader.workflow.quickstart import generate_rubric_draft_from_pdf
            from grader.workflow.profile_utils import get_project_root
            import yaml
            
            solutions_pdf = get_project_root() / "data" / profile / "solutions.pdf"
            if not solutions_pdf.exists():
                self._send_json_error(HTTPStatus.NOT_FOUND, "solutions.pdf not found. Please upload it first.")
                return
                
            try:
                draft_dict = generate_rubric_draft_from_pdf(solutions_pdf=solutions_pdf, profile_name=profile)
                draft_yaml = yaml.safe_dump(draft_dict, sort_keys=False, allow_unicode=True)
                
                rubric_yaml_path = get_project_root() / "data" / profile / "rubric.yaml"
                rubric_yaml_path.write_text(draft_yaml, encoding="utf-8")
            except Exception as exc:
                self._send_json_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Failed to generate rubric: {exc}")
                return
                
            self._send_json(HTTPStatus.OK, {"status": "success", "yaml": draft_yaml})
            return

        self._send_json_error(HTTPStatus.NOT_FOUND, f"Unknown path: {path}")

    def _read_multipart_body(self) -> tuple[dict[str, str], dict[str, Any]] | None:
        try:
            from multipart.multipart import parse_form, Field, File
        except ImportError:
            self._send_json_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Multipart library missing.")
            return None

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length header.")
            return None

        if length > 500 * 1024 * 1024:
            self._send_json_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Upload exceeds 500MB limit.")
            return None

        fields: dict[str, str] = {}
        files: dict[str, Any] = {}

        def on_field(f: Field):
            name = f.field_name.decode("utf-8") if isinstance(f.field_name, bytes) else f.field_name
            value = f.value.decode("utf-8") if isinstance(f.value, bytes) else f.value
            fields[name] = value

        def on_file(f: File):
            name = f.field_name.decode("utf-8") if isinstance(f.field_name, bytes) else f.field_name
            filename = f.file_name.decode("utf-8") if isinstance(f.file_name, bytes) else f.file_name
            files[name] = {"filename": filename, "file_object": f.file_object}

        try:
            parse_form(dict(self.headers), self.rfile, on_field, on_file, chunk_size=1048576)
        except Exception as exc:
            self._send_json_error(HTTPStatus.BAD_REQUEST, f"Failed to parse multipart form: {exc}")
            return None

        return fields, files

    def _read_json_body(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length header.")
            return None
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Request body must be valid JSON.")
            return None
        if not isinstance(payload, dict):
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Request JSON must be an object.")
            return None
        return payload

    def _serve_static(self, request_path: str) -> None:
        if request_path in {"", "/"}:
            file_path = self.static_root / "index.html"
        elif request_path.startswith("/static/"):
            rel = request_path.removeprefix("/")
            file_path = self.static_root / rel.replace("static/", "", 1)
        else:
            file_path = self.static_root / "index.html"

        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found.")
            return

        content = file_path.read_bytes()
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json(status, {"error": message})

    def _send_file_attachment(
        self,
        status: HTTPStatus,
        body: bytes,
        filename: str,
        content_type: str,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]


def run_review_server(output_dir: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    from ..prompts import styled_info, styled_url

    api = ReviewApi(output_dir)
    static_root = Path(__file__).parent / "static"
    session_manager = GradingSessionManager()

    class BoundHandler(ReviewRequestHandler):
        pass

    BoundHandler.api = api
    BoundHandler.static_root = static_root
    BoundHandler.session_manager = session_manager

    server = ThreadingHTTPServer((host, port), BoundHandler)
    styled_url("Review server running", f"http://{host}:{port}")
    styled_info(f"Using review state: {api.state_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        styled_info("\nStopping review server.")
    finally:
        server.server_close()

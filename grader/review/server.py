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


class ReviewRequestHandler(BaseHTTPRequestHandler):
    api: ReviewApi
    static_root: Path

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/run":
            self._send_json(HTTPStatus.OK, self.api.get_run())
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
            try:
                payload = self.api.get_submission(submission_id)
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
            try:
                payload = self.api.get_page_meta(
                    submission_id=submission_id,
                    doc_idx=int(doc_idx_raw),
                    page_idx=int(page_idx_raw),
                    scale=scale,
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
            try:
                image = self.api.get_page_image(
                    submission_id=submission_id,
                    doc_idx=int(doc_idx_raw),
                    page_idx=int(page_idx_raw),
                    scale=scale,
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

        self._send_json_error(HTTPStatus.NOT_FOUND, f"Unknown path: {path}")

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

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]


def run_review_server(output_dir: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    api = ReviewApi(output_dir)
    static_root = Path(__file__).parent / "static"

    class BoundHandler(ReviewRequestHandler):
        pass

    BoundHandler.api = api
    BoundHandler.static_root = static_root

    server = ThreadingHTTPServer((host, port), BoundHandler)
    print(f"Review server running at http://{host}:{port}")
    print(f"Using review state: {api.state_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping review server.")
    finally:
        server.server_close()

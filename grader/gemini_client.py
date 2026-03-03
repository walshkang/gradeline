from __future__ import annotations

import hashlib
import json
import random
import re
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from .streaming import StreamProgressParser
from .types import JsonDict, QuestionResult, RubricConfig


PROMPT_VERSION = "2026-02-26-gemini-brightspace-v4"
DEFAULT_CONTEXT_CACHE_TTL_SECONDS = 86400
SHORT_REASON_MAX_CHARS = 42
SHORT_REASON_MAX_WORDS = 12
DETAIL_REASON_MAX_CHARS = 260
DETAIL_REASON_MAX_WORDS = 48
NUMERIC_EQUIVALENCE_RULE = (
    "SYSTEM RULE: You must treat decimal and percentage notation as strictly equivalent when they express "
    "the same quantity (for example: .45, 0.45, and 45%).\n"
    "MATH EVALUATION: You must distinguish between minor intermediate rounding differences and fundamentally flawed logic. "
    "If the student's formula and logic are correct but the final answer is off by a small rounding margin, assign 'rounding_error'. "
    "If the underlying equation or logic is wrong, assign 'incorrect'."
)


class UnifiedQuestionItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    logic_analysis: str
    verdict: Literal["correct", "partial", "rounding_error", "incorrect", "needs_review"]
    confidence: float = 0.0
    short_reason: str = ""
    detail_reason: str = ""
    evidence_quote: str = ""
    coords: list[int] | None = None
    page_number: int | None = None
    source_file: str | None = None


class UnifiedSubmissionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    student_submission_id: str
    questions: list[UnifiedQuestionItem]
    global_flags: list[str] = Field(default_factory=list)


class GeminiGrader:
    def __init__(
        self,
        api_key: str,
        model: str,
        cache_dir: Path,
        max_retries: int = 5,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.cache_dir = cache_dir
        self.max_retries = max_retries
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._resolved_context_names: dict[str, str] = {}

        from google import genai  # Lazy import for testability without dependency.

        self._genai = genai
        self.client = genai.Client(api_key=api_key)

    def grade_submission(
        self,
        submission_id: str,
        pdf_paths: list[Path],
        combined_text: str,
        rubric: RubricConfig,
        solutions_text: str,
    ) -> tuple[list[QuestionResult], list[str]]:
        cache_key = compute_grade_cache_key(
            submission_id=submission_id,
            pdf_paths=pdf_paths,
            rubric=rubric,
            solutions_text=solutions_text,
            model=self.model,
        )
        cached = self._get_cache(cache_key)
        if cached:
            normalized = normalize_model_response(cached, rubric)
            return normalized["questions"], normalized["global_flags"]

        with ThreadPoolExecutor(max_workers=min(4, len(pdf_paths) or 1)) as executor:
            files = list(executor.map(self._upload_and_wait, pdf_paths))

        prompt = build_legacy_grading_prompt(
            submission_id=submission_id,
            rubric=rubric,
            solutions_text=solutions_text,
            combined_text=combined_text,
        )

        def invoke() -> JsonDict:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[*files, prompt],
                config={"response_mime_type": "application/json"},
            )
            text = response_text(response)
            payload = parse_json_maybe_fenced(text)
            return payload

        payload = call_with_backoff(invoke, max_retries=self.max_retries)
        normalized = normalize_model_response(payload, rubric)
        self._set_cache(cache_key, payload)
        return normalized["questions"], normalized["global_flags"]

    def grade_submission_unified(
        self,
        submission_id: str,
        pdf_paths: list[Path],
        rubric: RubricConfig,
        solutions_pdf_path: Path,
        context_cache_enabled: bool = True,
        context_cache_ttl_seconds: int = DEFAULT_CONTEXT_CACHE_TTL_SECONDS,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> tuple[list[QuestionResult], list[str]]:
        context_key = compute_context_cache_key(
            model=self.model,
            rubric=rubric,
            solutions_pdf_path=solutions_pdf_path,
        )
        cache_key = compute_unified_grade_cache_key(
            submission_id=submission_id,
            pdf_paths=pdf_paths,
            rubric=rubric,
            model=self.model,
            context_key=context_key,
        )
        cached = self._get_cache(cache_key)
        if cached:
            normalized = normalize_model_response(cached, rubric)
            return normalized["questions"], normalized["global_flags"]

        # ... (file uploads remain same here for now, will refactor concurrently later)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(4, len(pdf_paths) or 1)) as executor:
            files = list(executor.map(self._upload_and_wait, pdf_paths))

        prompt = build_unified_grading_prompt(
            submission_id=submission_id,
            rubric=rubric,
            pdf_paths=pdf_paths,
        )

        cache_flags: list[str] = []
        cached_content: str | None = None
        if context_cache_enabled:
            cached_content, cache_flags = self._resolve_context_cache(
                context_key=context_key,
                rubric=rubric,
                solutions_pdf_path=solutions_pdf_path,
                ttl_seconds=context_cache_ttl_seconds,
            )

        def invoke() -> JsonDict:
            config: JsonDict = {
                "response_mime_type": "application/json",
                "response_schema": UnifiedSubmissionResponse,
            }
            if cached_content:
                config["cached_content"] = cached_content

            total_questions = len(rubric.questions)

            on_question: Callable[[int, str], None] | None = None
            if progress_callback is not None and total_questions > 0:
                def _on_question(idx: int, qid: str) -> None:
                    # Delegate to the higher-level callback, guarding against
                    # incidental UI errors.
                    try:
                        progress_callback(idx, total_questions, qid)
                    except Exception:
                        pass

                on_question = _on_question

            parser = StreamProgressParser(on_question=on_question)

            stream = self.client.models.generate_content(
                model=self.model,
                contents=[*files, prompt],
                config=config,
                stream=True,
            )

            for chunk in stream:
                text_chunk = getattr(chunk, "text", "")
                if text_chunk:
                    parser.feed(text_chunk)

            full_text = parser.get_buffer()
            payload = parse_json_maybe_fenced(full_text)
            return payload

        payload = call_with_backoff(invoke, max_retries=self.max_retries)
        payload["global_flags"] = merge_flags(payload.get("global_flags", []), cache_flags)
        normalized = normalize_model_response(payload, rubric)
        self._set_cache(cache_key, payload)
        return normalized["questions"], normalized["global_flags"]

    def grade_submission_agent(
        self,
        submission_id: str,
        pdf_paths: list[Path],
        rubric: RubricConfig,
        solutions_pdf_path: Path,
        agent_type: str = "gemini",
    ) -> tuple[list[QuestionResult], list[str]]:
        cache_key = compute_agent_grade_cache_key(
            submission_id=submission_id,
            pdf_paths=pdf_paths,
            rubric=rubric,
            model=self.model,
            agent_type=agent_type,
        )
        cached = self._get_cache(cache_key)
        if cached:
            normalized = normalize_model_response(cached, rubric)
            return normalized["questions"], normalized["global_flags"]

        prompt = build_agent_grading_prompt(
            submission_id=submission_id,
            rubric=rubric,
            pdf_paths=pdf_paths,
            solutions_pdf_path=solutions_pdf_path,
            agent_type=agent_type,
        )

        def invoke() -> JsonDict:
            if agent_type == "gemini":
                cmd = ["gemini", "-p", prompt, "-o", "json"]
                if self.model:
                    cmd.extend(["-m", self.model])
            elif agent_type == "codex":
                cmd = ["codex", "exec", prompt]
                if self.model:
                    cmd.extend(["-m", self.model])
            elif agent_type == "claude":
                cmd = ["claude", "-p", prompt]
            else:
                raise ValueError(f"Unsupported agent type: {agent_type}")

            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise RuntimeError(f"Agent CLI '{agent_type}' failed with exit code {result.returncode}: {result.stderr or result.stdout}")

            output = result.stdout
            if agent_type == "gemini":
                try:
                    # gemini CLI output may contain non-JSON noise (warnings, credential messages)
                    agent_response = parse_json_maybe_fenced(output)
                    # Extract content from 'response' (most common) or fallback to 'turns'.
                    content = agent_response.get("response")
                    if not content:
                        turns = agent_response.get("turns", [])
                        if turns:
                            content = turns[-1].get("content")
                    if not content:
                        raise ValueError("Agent response has no extractable content.")
                    return parse_json_maybe_fenced(content)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"Failed to parse gemini CLI JSON output: {exc}") from exc

            # The output should contain the JSON payload.
            payload = parse_json_maybe_fenced(output)
            return payload

        payload = call_with_backoff(invoke, max_retries=self.max_retries)
        payload["global_flags"] = merge_flags(payload.get("global_flags", []), [f"agent_mode", f"agent_{agent_type}"])
        normalized = normalize_model_response(payload, rubric)
        self._set_cache(cache_key, payload)
        return normalized["questions"], normalized["global_flags"]

    def locate_answers_for_pdf(
        self,
        pdf_path: Path,
        rubric: RubricConfig,
        locator_model: str,
    ) -> list[JsonDict]:
        cache_key = compute_locator_cache_key(
            pdf_path=pdf_path,
            rubric=rubric,
            locator_model=locator_model,
        )
        cached = self._get_cache(cache_key)
        if cached:
            return normalize_locator_response(cached, rubric=rubric, default_source_file=pdf_path.name)

        file_ref = self._upload_and_wait(pdf_path)
        prompt = build_locator_prompt(pdf_name=pdf_path.name, rubric=rubric)

        def invoke() -> JsonDict:
            response = self.client.models.generate_content(
                model=locator_model,
                contents=[file_ref, prompt],
                config={"response_mime_type": "application/json"},
            )
            text = response_text(response)
            return parse_json_maybe_fenced(text)

        payload = call_with_backoff(invoke, max_retries=self.max_retries)
        normalized = normalize_locator_response(payload, rubric=rubric, default_source_file=pdf_path.name)
        self._set_cache(cache_key, payload)
        return normalized

    def _upload_and_wait(self, pdf_path: Path) -> Any:
        file_ref = call_with_backoff(
            lambda: self.client.files.upload(file=str(pdf_path)),
            max_retries=self.max_retries,
        )
        return wait_for_file_active(
            client=self.client,
            file_ref=file_ref,
            max_retries=self.max_retries,
        )

    def _resolve_context_cache(
        self,
        context_key: str,
        rubric: RubricConfig,
        solutions_pdf_path: Path,
        ttl_seconds: int,
    ) -> tuple[str | None, list[str]]:
        flags: list[str] = []
        resolved = self._resolved_context_names.get(context_key)
        if resolved:
            return resolved, flags

        now = int(time.time())
        entry = self._get_context_cache(context_key)
        if isinstance(entry, dict):
            cache_name = str(entry.get("cache_name", "")).strip()
            expires_at = int(entry.get("expires_at", 0))
            if cache_name and expires_at > now:
                try:
                    call_with_backoff(
                        lambda: self.client.caches.get(name=cache_name),
                        max_retries=self.max_retries,
                    )
                    self._resolved_context_names[context_key] = cache_name
                    return cache_name, flags
                except Exception:
                    flags.append("context_cache_lookup_failed")
                    self._delete_context_cache(context_key)

        ttl = max(60, int(ttl_seconds))
        try:
            file_ref = self._upload_and_wait(solutions_pdf_path)
            cache = call_with_backoff(
                lambda: self.client.caches.create(
                    model=self.model,
                    config={
                        "display_name": f"sda-solutions-{context_key[:12]}",
                        "ttl": f"{ttl}s",
                        "contents": [file_ref],
                        "system_instruction": build_context_system_instruction(rubric),
                    },
                ),
                max_retries=self.max_retries,
            )
            cache_name = str(getattr(cache, "name", "")).strip()
            if not cache_name:
                raise ValueError("Context cache create returned no cache name.")
            
            self._set_context_cache(context_key, {
                "cache_name": cache_name,
                "created_at": now,
                "expires_at": now + ttl,
                "model": self.model,
            })
            self._resolved_context_names[context_key] = cache_name
            return cache_name, flags
        except Exception:
            flags.extend(["context_cache_create_failed", "context_cache_bypassed"])
            return None, flags

    def _init_db(self) -> None:
        self.db_path = self.cache_dir / "cache.db"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS grading_cache (hash_key TEXT PRIMARY KEY, payload TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS context_cache (hash_key TEXT PRIMARY KEY, payload TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )

    def _get_cache(self, key: str) -> JsonDict | None:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT payload FROM grading_cache WHERE hash_key = ?", (key,))
            row = cur.fetchone()
            if row:
                return json.loads(row[0])
        return None

    def _set_cache(self, key: str, payload: JsonDict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO grading_cache (hash_key, payload) VALUES (?, ?)",
                (key, json.dumps(payload)),
            )

    def _get_context_cache(self, key: str) -> JsonDict | None:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT payload FROM context_cache WHERE hash_key = ?", (key,))
            row = cur.fetchone()
            if row:
                return json.loads(row[0])
        return None

    def _set_context_cache(self, key: str, payload: JsonDict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO context_cache (hash_key, payload) VALUES (?, ?)",
                (key, json.dumps(payload)),
            )
            
    def _delete_context_cache(self, key: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM context_cache WHERE hash_key = ?", (key,))


def structured_response_payload(response: Any) -> JsonDict:
    parsed = getattr(response, "parsed", None)
    if parsed is None:
        text = response_text(response)
        return parse_json_maybe_fenced(text)

    if isinstance(parsed, dict):
        payload = parsed
    elif hasattr(parsed, "model_dump"):
        payload = parsed.model_dump()  # pydantic model from response_schema.
    else:
        raise ValueError(f"Unexpected parsed response type: {type(parsed)!r}")

    if not isinstance(payload, dict):
        raise ValueError("Structured Gemini response must be an object.")
    return payload


def response_text(response: Any) -> str:
    direct = getattr(response, "text", None)
    if isinstance(direct, str) and direct.strip():
        return direct

    candidates = getattr(response, "candidates", None)
    if not candidates:
        raise ValueError("Gemini response did not include text candidates.")
    parts: list[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", []):
            text = getattr(part, "text", None)
            if text:
                parts.append(text)
    if not parts:
        raise ValueError("Gemini response had no textual content.")
    return "\n".join(parts)


def wait_for_file_active(client: Any, file_ref: Any, max_retries: int = 5) -> Any:
    name = getattr(file_ref, "name", None)
    if not name:
        return file_ref
    max_polls = max_retries * 8
    for _ in range(max_polls):
        refreshed = client.files.get(name=name)
        state = getattr(refreshed, "state", None)
        state_value = str(state).upper() if state is not None else "ACTIVE"
        if any(token in state_value for token in ("ACTIVE", "READY", "SUCCEEDED")):
            return refreshed
        if any(token in state_value for token in ("FAILED", "ERROR")):
            raise RuntimeError(f"Uploaded file entered failure state: {state_value}")
        time.sleep(1.0)
    raise TimeoutError(f"Timed out waiting for uploaded file to become active: {name}")


def parse_json_maybe_fenced(text: str) -> JsonDict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json", "", 1).strip()

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Gemini JSON response must be an object.")
    return payload


def build_legacy_grading_prompt(
    submission_id: str,
    rubric: RubricConfig,
    solutions_text: str,
    combined_text: str,
) -> str:
    rubric_lines = build_rubric_lines(rubric)

    return (
        "You are grading one statistics assignment submission.\n"
        "Return ONLY strict JSON with this shape:\n"
        "{"
        '"student_submission_id":"...",'
        '"questions":[{"id":"a","logic_analysis":"...","verdict":"correct|partial|rounding_error|incorrect|needs_review","confidence":0.0,'
        '"short_reason":"...", "detail_reason":"...", "evidence_quote":"..."}],'
        '"global_flags":["..."]'
        "}\n"
        "No markdown fences. No extra fields.\n"
        "Feedback rules:\n"
        "- Generate logic_analysis to reason through the answer before assigning a verdict.\n"
        "- If verdict is correct, short_reason must be an empty string.\n"
        "- If verdict is incorrect or partial, short_reason must be a pithy correction under 42 characters.\n"
        "- detail_reason is optional and may expand with one concise coaching sentence.\n"
        "- Use direct second-person voice and avoid third-person phrasing.\n\n"
        f"{NUMERIC_EQUIVALENCE_RULE}\n\n"
        f"Submission ID: {submission_id}\n\n"
        "Master solution text:\n"
        f"{solutions_text}\n\n"
        "Rubric:\n"
        f"{chr(10).join(rubric_lines)}\n\n"
        "Student extracted text (may include OCR noise):\n"
        f"{combined_text[:12000]}"
    )


def build_unified_grading_prompt(
    submission_id: str,
    rubric: RubricConfig,
    pdf_paths: list[Path],
) -> str:
    labels = ", ".join(question.id for question in rubric.questions)
    files = ", ".join(path.name for path in pdf_paths)
    return (
        f"Submission ID: {submission_id}\n"
        f"Expected question IDs: {labels}\n"
        f"Attached student files: {files}\n"
        "Grade this submission exactly according to the cached rubric and master solution."
    )

def build_context_system_instruction(rubric: RubricConfig) -> str:
    rubric_lines = build_rubric_lines(rubric)
    return (
        "You are the grading policy context for one statistics assignment.\n"
        "Use the attached master solution PDF and rubric rules below as the source of truth.\n"
        "Return judgments only from the student's provided work and these rubric rules.\n"
        f"{NUMERIC_EQUIVALENCE_RULE}\n"
        "Feedback rules: correct => empty short_reason/detail_reason; incorrect/partial => short_reason under 42 chars plus optional one-sentence detail_reason in second-person voice.\n"
        "Coordinate rule: if your detector yields [ymin, xmin, ymax, xmax], convert it to the center and return [y, x] integers on 0..1000.\n"
        "If uncertain, set verdict=needs_review and confidence near 0.0.\n"
        "You must generate logic_analysis BEFORE determining the verdict.\n"
        "Rubric rules:\n"
        f"{chr(10).join(rubric_lines)}"
    )

def build_agent_grading_prompt(
    submission_id: str,
    rubric: RubricConfig,
    pdf_paths: list[Path],
    solutions_pdf_path: Path,
    agent_type: str = "gemini",
) -> str:
    labels = ", ".join(question.id for question in rubric.questions)
    files_info = "\n".join([f"- Student File: {path.absolute()}" for path in pdf_paths])
    rubric_lines = build_rubric_lines(rubric)

    agent_flavor = ""
    if agent_type == "gemini":
        agent_flavor = "Use your ability to read and analyze PDF files directly."
    elif agent_type == "codex":
        agent_flavor = "Use your code execution and file reading tools to analyze the PDF contents."
    elif agent_type == "claude":
        agent_flavor = "Analyze the PDF files provided in the context."

    return (
        "You are an expert statistics grader. Your goal is to grade a student submission accurately.\n\n"
        f"{agent_flavor}\n\n"
        "### STEP 1: READ THE SOURCE OF TRUTH\n"
        f"Read the master solution PDF at: {solutions_pdf_path.absolute()}\n"
        "Understand the correct answers and the following rubric rules:\n"
        f"{chr(10).join(rubric_lines)}\n\n"
        "### STEP 2: READ THE STUDENT SUBMISSION\n"
        "Use your tools to read the following student PDF files:\n"
        f"{files_info}\n\n"
        "### STEP 3: PERFORM GRADING\n"
        "Carefully evaluate the student's work against the master solution for each question.\n"
        "Handwritten work must be analyzed with high precision.\n\n"
        "### STEP 4: OUTPUT RESULTS\n"
        "Output ONLY a valid JSON object (enclosed in markdown ```json blocks if possible) matching this schema:\n"
        "{\n"
        '  "student_submission_id": "...",\n'
        '  "questions": [\n'
        '    {\n'
        '      "id": "question_id",\n'
        '      "logic_analysis": "step-by-step reasoning",\n'
        '      "verdict": "correct|partial|rounding_error|incorrect|needs_review",\n'
        '      "confidence": 0.0 to 1.0,\n'
        '      "short_reason": "under 42 chars",\n'
        '      "detail_reason": "one concise coaching sentence",\n'
        '      "evidence_quote": "relevant text from submission",\n'
        '      "coords": [y, x], // 0-1000 normalized center of the answer\n'
        '      "page_number": 1-indexed,\n'
        '      "source_file": "filename.pdf"\n'
        "    }\n"
        "  ],\n"
        '  "global_flags": []\n'
        "}\n\n"
        "Rules:\n"
        "- IMPORTANT: You must write logic_analysis BEFORE the verdict.\n"
        "- If verdict is correct, short_reason and detail_reason MUST be empty.\n"
        "- Use direct second-person voice ('You did X') for feedback.\n"
        f"- {NUMERIC_EQUIVALENCE_RULE}\n"
        f"Submission ID: {submission_id}\n"
        f"Expected question IDs: {labels}\n"
    )


def build_locator_prompt(pdf_name: str, rubric: RubricConfig) -> str:
    labels = ", ".join(question.id for question in rubric.questions)
    return (
        "Locate where answers appear in this PDF.\n"
        "Return ONLY strict JSON with this shape:\n"
        "{"
        '"results":[{"q":"a","correct":true,"coords":[500,250],"page_number":1,"source_file":"file.pdf","confidence":0.9}]'
        "}\n"
        "Rules:\n"
        "- coords are [y, x] on 0..1000 scale where 0,0 is top-left.\n"
        "- include only questions that are actually found.\n"
        "- include source_file exactly matching the PDF filename.\n"
        "- no markdown fences and no extra narrative.\n\n"
        f"Expected question labels: {labels}\n"
        f"PDF filename: {pdf_name}\n"
    )


def build_rubric_lines(rubric: RubricConfig) -> list[str]:
    lines: list[str] = []
    for question in rubric.questions:
        labels = ", ".join(question.label_patterns) if question.label_patterns else f"{question.id})"
        lines.append(f"- Q{question.id}: labels=[{labels}] rule={question.scoring_rules}")
    return lines


def normalize_model_response(payload: JsonDict, rubric: RubricConfig) -> JsonDict:
    questions_raw = payload.get("questions")
    if not isinstance(questions_raw, list):
        raise ValueError("Gemini response must include 'questions' list.")

    question_map: dict[str, JsonDict] = {}
    for item in questions_raw:
        if isinstance(item, dict) and "id" in item:
            qid = str(item["id"]).strip().lower()
            question_map[qid] = item

    normalized_questions: list[QuestionResult] = []
    for question in rubric.questions:
        raw = question_map.get(question.id)
        if raw is None:
            normalized_questions.append(
                QuestionResult(
                    id=question.id,
                    verdict="needs_review",
                    confidence=0.0,
                    logic_analysis="",
                    short_reason="Review manually.",
                    detail_reason="",
                    evidence_quote="",
                )
            )
            continue

        verdict = normalize_verdict(raw.get("verdict"))
        confidence = normalize_confidence(raw.get("confidence"))
        logic_analysis = str(raw.get("logic_analysis", "")).strip()
        short_reason, detail_reason = normalize_feedback(
            verdict=verdict,
            raw_short_reason=str(raw.get("short_reason", "")).strip()[:500],
            raw_detail_reason=str(raw.get("detail_reason", "")).strip()[:900],
            fallback_fail_note=question.short_note_fail,
        )
        evidence_quote = str(raw.get("evidence_quote", "")).strip()[:500]
        coords = parse_coords_0_to_1000(raw.get("coords"))
        page_number = parse_page_number(raw.get("page_number") or raw.get("page"))
        source_file = str(raw.get("source_file", "")).strip() or None
        normalized_questions.append(
            QuestionResult(
                id=question.id,
                verdict=verdict,
                confidence=confidence,
                logic_analysis=logic_analysis,
                short_reason=short_reason,
                detail_reason=detail_reason,
                evidence_quote=evidence_quote,
                coords=coords,
                page_number=page_number,
                source_file=source_file,
            )
        )

    global_flags_raw = payload.get("global_flags", [])
    global_flags = [str(item).strip() for item in global_flags_raw if str(item).strip()]
    return {
        "questions": normalized_questions,
        "global_flags": merge_flags(global_flags),
    }


def normalize_feedback(
    *,
    verdict: str,
    raw_short_reason: str,
    raw_detail_reason: str,
    fallback_fail_note: str,
) -> tuple[str, str]:
    if verdict == "correct":
        return "", ""
    if verdict == "needs_review":
        return "Review manually.", ""

    short_reason = derive_short_reason(raw_short_reason=raw_short_reason, fallback_fail_note=fallback_fail_note)
    detail_reason = derive_detail_reason(
        raw_short_reason=raw_short_reason,
        raw_detail_reason=raw_detail_reason,
        short_reason=short_reason,
    )
    return short_reason, detail_reason


def derive_short_reason(*, raw_short_reason: str, fallback_fail_note: str) -> str:
    candidate = extract_pithy_sentence(
        raw_short_reason,
        max_chars=SHORT_REASON_MAX_CHARS,
        max_words=SHORT_REASON_MAX_WORDS,
    )
    if candidate and (not is_third_person_feedback(candidate)):
        return clamp_short_reason(candidate)

    fallback = extract_pithy_sentence(
        fallback_fail_note,
        max_chars=SHORT_REASON_MAX_CHARS,
        max_words=SHORT_REASON_MAX_WORDS,
    )
    if fallback:
        return clamp_short_reason(fallback)
    return "Check your work."


def derive_detail_reason(*, raw_short_reason: str, raw_detail_reason: str, short_reason: str) -> str:
    direct_detail = extract_detail_reason(raw_detail_reason)
    if direct_detail:
        return direct_detail

    overflow = extract_overflow_detail(raw_short_reason, short_reason)
    return extract_detail_reason(overflow)


def extract_detail_reason(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if lowered in {"n/a", "na", "none", "no reason provided by model."}:
        return ""
    words = cleaned.split()
    if len(words) > DETAIL_REASON_MAX_WORDS:
        cleaned = " ".join(words[:DETAIL_REASON_MAX_WORDS]).rstrip()
    if len(cleaned) > DETAIL_REASON_MAX_CHARS:
        cleaned = cleaned[:DETAIL_REASON_MAX_CHARS].rstrip()
        if " " in cleaned:
            cleaned = cleaned.rsplit(" ", 1)[0].rstrip()
    return cleaned


def extract_overflow_detail(raw_short_reason: str, short_reason: str) -> str:
    cleaned = " ".join(str(raw_short_reason or "").split())
    if not cleaned:
        return ""
    if not short_reason:
        return cleaned
    if cleaned == short_reason:
        return ""
    if cleaned.startswith(short_reason):
        return cleaned[len(short_reason) :].lstrip(" .;:-")
    idx = cleaned.find(short_reason)
    if idx >= 0:
        return cleaned[idx + len(short_reason) :].lstrip(" .;:-")
    return ""


def clamp_short_reason(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= SHORT_REASON_MAX_CHARS:
        return cleaned
    clipped = cleaned[:SHORT_REASON_MAX_CHARS].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip()
    return clipped or cleaned[:SHORT_REASON_MAX_CHARS].rstrip()


def extract_pithy_sentence(text: str, max_chars: int = 90, max_words: int = 16) -> str:
    first_line = re.split(r"[\r\n]+", str(text or ""), maxsplit=1)[0].strip()
    if not first_line:
        return ""
    first_sentence = re.split(r"(?<=[.!?])\s+", first_line, maxsplit=1)[0].strip()
    cleaned = " ".join(first_sentence.split())
    if not cleaned:
        return ""

    lowered = cleaned.lower()
    if lowered in {"n/a", "na", "none", "no reason provided by model."}:
        return ""
    if len(cleaned) > max_chars or len(cleaned.split()) > max_words:
        return ""
    return cleaned


def is_third_person_feedback(text: str) -> bool:
    lowered = f" {text.lower()} "
    disallowed_tokens = (
        " the student ",
        " student ",
        " they ",
        " their ",
        " this answer ",
        " the response ",
    )
    return any(token in lowered for token in disallowed_tokens)


def normalize_locator_response(
    payload: JsonDict,
    rubric: RubricConfig,
    default_source_file: str,
) -> list[JsonDict]:
    allowed_ids = {question.id for question in rubric.questions}
    raw_items = payload.get("results")
    if not isinstance(raw_items, list):
        raw_items = payload.get("questions", [])
    if not isinstance(raw_items, list):
        return []

    normalized: list[JsonDict] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        qid = normalize_question_id(item.get("q") or item.get("id"))
        if not qid or qid not in allowed_ids:
            continue
        coords = parse_coords_0_to_1000(item.get("coords"))
        if coords is None:
            continue
        confidence = normalize_confidence(item.get("confidence", 0.0))
        page_number = parse_page_number(item.get("page_number") or item.get("page"))
        source_file = str(item.get("source_file", "")).strip() or default_source_file
        normalized.append(
            {
                "id": qid,
                "coords": coords,
                "confidence": confidence,
                "page_number": page_number,
                "source_file": source_file,
            }
        )
    return normalized


def normalize_verdict(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "pass": "correct",
        "correct": "correct",
        "partial": "partial",
        "partially_correct": "partial",
        "rounding_error": "rounding_error",
        "incorrect": "incorrect",
        "wrong": "incorrect",
        "needs_review": "needs_review",
        "uncertain": "needs_review",
        "unknown": "needs_review",
    }
    return aliases.get(normalized, "needs_review")


def normalize_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def normalize_question_id(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return ""
    return cleaned[0]


def parse_coords_0_to_1000(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)):
        return None

    if len(value) == 2:
        items = value
    elif len(value) == 4:
        try:
            ymin = float(value[0])
            xmin = float(value[1])
            ymax = float(value[2])
            xmax = float(value[3])
        except (TypeError, ValueError):
            return None
        items = [(ymin + ymax) / 2.0, (xmin + xmax) / 2.0]
    else:
        return None

    try:
        y = float(items[0])
        x = float(items[1])
    except (TypeError, ValueError):
        return None
    return (max(0.0, min(1000.0, y)), max(0.0, min(1000.0, x)))


def parse_page_number(value: Any) -> int | None:
    if value is None:
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    if number < 1:
        return None
    return number


def merge_flags(*groups: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            value = str(item).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            merged.append(value)
    return merged


def compute_grade_cache_key(
    submission_id: str,
    pdf_paths: list[Path],
    rubric: RubricConfig,
    solutions_text: str,
    model: str,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(PROMPT_VERSION.encode("utf-8"))
    hasher.update(b"legacy")
    hasher.update(model.encode("utf-8"))
    hasher.update(submission_id.encode("utf-8"))
    hasher.update(json.dumps(rubric_to_cache_payload(rubric), sort_keys=True).encode("utf-8"))
    hasher.update(solutions_text.encode("utf-8"))
    for path in sorted(pdf_paths, key=lambda p: str(p)):
        hasher.update(str(path).encode("utf-8"))
        hasher.update(hash_file(path).encode("utf-8"))
    return hasher.hexdigest()


def compute_unified_grade_cache_key(
    submission_id: str,
    pdf_paths: list[Path],
    rubric: RubricConfig,
    model: str,
    context_key: str,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(PROMPT_VERSION.encode("utf-8"))
    hasher.update(b"unified")
    hasher.update(model.encode("utf-8"))
    hasher.update(context_key.encode("utf-8"))
    hasher.update(submission_id.encode("utf-8"))
    hasher.update(json.dumps(rubric_to_cache_payload(rubric), sort_keys=True).encode("utf-8"))
    for path in sorted(pdf_paths, key=lambda p: str(p)):
        hasher.update(str(path).encode("utf-8"))
        hasher.update(hash_file(path).encode("utf-8"))
    return hasher.hexdigest()


def compute_context_cache_key(
    model: str,
    rubric: RubricConfig,
    solutions_pdf_path: Path,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(PROMPT_VERSION.encode("utf-8"))
    hasher.update(b"context")
    hasher.update(model.encode("utf-8"))
    hasher.update(hash_file(solutions_pdf_path).encode("utf-8"))
    hasher.update(json.dumps(rubric_to_cache_payload(rubric), sort_keys=True).encode("utf-8"))
    return hasher.hexdigest()


def compute_agent_grade_cache_key(
    submission_id: str,
    pdf_paths: list[Path],
    rubric: RubricConfig,
    model: str,
    agent_type: str = "gemini",
) -> str:
    hasher = hashlib.sha256()
    hasher.update(PROMPT_VERSION.encode("utf-8"))
    hasher.update(b"agent")
    hasher.update(agent_type.encode("utf-8"))
    hasher.update(model.encode("utf-8"))
    hasher.update(submission_id.encode("utf-8"))
    hasher.update(json.dumps(rubric_to_cache_payload(rubric), sort_keys=True).encode("utf-8"))
    for path in sorted(pdf_paths, key=lambda p: str(p)):
        hasher.update(str(path).encode("utf-8"))
        hasher.update(hash_file(path).encode("utf-8"))
    return hasher.hexdigest()


def compute_locator_cache_key(
    pdf_path: Path,
    rubric: RubricConfig,
    locator_model: str,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(PROMPT_VERSION.encode("utf-8"))
    hasher.update(b"locator")
    hasher.update(locator_model.encode("utf-8"))
    hasher.update(str(pdf_path).encode("utf-8"))
    hasher.update(hash_file(pdf_path).encode("utf-8"))
    hasher.update(json.dumps(rubric_to_cache_payload(rubric), sort_keys=True).encode("utf-8"))
    return hasher.hexdigest()


def rubric_to_cache_payload(rubric: RubricConfig) -> JsonDict:
    return {
        "assignment_id": rubric.assignment_id,
        "bands": rubric.bands,
        "scoring_mode": rubric.scoring_mode,
        "partial_credit": rubric.partial_credit,
        "questions": [
            {
                "id": question.id,
                "label_patterns": question.label_patterns,
                "scoring_rules": question.scoring_rules,
                "weight": question.weight,
                "anchor_tokens": question.anchor_tokens,
            }
            for question in rubric.questions
        ],
    }


def hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


def call_with_backoff(func: Callable[[], Any], max_retries: int = 5) -> Any:
    attempts = 0
    while True:
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            attempts += 1
            if attempts >= max_retries or not should_retry(exc):
                raise
            delay = (2 ** (attempts - 1)) + random.uniform(0.0, 0.25)
            time.sleep(delay)


def should_retry(exc: Exception) -> bool:
    message = str(exc).lower()
    retry_tokens = ("429", "rate", "503", "502", "500", "timeout", "temporar")
    return any(token in message for token in retry_tokens)

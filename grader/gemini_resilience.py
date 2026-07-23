from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from .gemini_schemas import DEFAULT_CONTEXT_CACHE_TTL_SECONDS, PROMPT_VERSION, build_context_system_instruction
from .types import JsonDict, RubricConfig


def acquire_rate_limit(rate_limiter: Any | None, model: str) -> None:
    """Acquire a token from the rate limiter if configured."""
    if rate_limiter is not None:
        rate_limiter.get_limiter(model).acquire()


def call_with_backoff(func: Callable[[], Any], max_retries: int = 5) -> Any:
    """Execute a callable with exponential backoff retry on transient errors."""
    attempts = 0
    while True:
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            attempts += 1
            if attempts >= max_retries or not should_retry(exc):
                raise
            message = str(exc).lower()
            is_429 = "429" in message or "rate" in message
            if is_429:
                delay = 15.0 + (5.0 * attempts) + random.uniform(0.0, 1.0)
            else:
                delay = (2 ** (attempts - 1)) + random.uniform(0.0, 0.25)
            time.sleep(delay)


def should_retry(exc: Exception) -> bool:
    """Determine whether an exception represents a retryable API error."""
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    message = f"{exc!s} {type(exc).__name__}".lower()
    retry_tokens = ("429", "rate", "503", "502", "500", "timeout", "timed out", "time out", "temporar")
    return any(token in message for token in retry_tokens)


def wait_for_file_active(client: Any, file_ref: Any, max_retries: int = 5) -> Any:
    """Poll an uploaded file reference until it reaches an active processing state."""
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


def structured_response_payload(response: Any) -> JsonDict:
    """Extract a dictionary payload from a structured Gemini model response."""
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
    """Extract raw text output from a Gemini API response object."""
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


def parse_json_maybe_fenced(text: str) -> JsonDict:
    """Parse JSON string which may be enclosed in markdown code fences."""
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


def hash_file(path: Path) -> str:
    """Compute SHA-256 hash of a file's contents."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


def rubric_to_cache_payload(rubric: RubricConfig) -> JsonDict:
    """Serialize rubric fields used in cache key computation."""
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
                "expected_answers": question.expected_answers,
                "scoring_criteria": [
                    {
                        "requirement": sc.requirement,
                        "weight": sc.weight,
                        "partial_if": sc.partial_if,
                    }
                    for sc in question.scoring_criteria
                ],
            }
            for question in rubric.questions
        ],
    }


def compute_grade_cache_key(
    submission_id: str,
    pdf_paths: list[Path],
    rubric: RubricConfig,
    solutions_text: str,
    model: str,
) -> str:
    """Compute cache key for legacy grading requests."""
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
    """Compute cache key for unified grading requests."""
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
    """Compute cache key for context cache instances."""
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
    """Compute cache key for agent grading requests."""
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
    """Compute cache key for answer locator requests."""
    hasher = hashlib.sha256()
    hasher.update(PROMPT_VERSION.encode("utf-8"))
    hasher.update(b"locator")
    hasher.update(locator_model.encode("utf-8"))
    hasher.update(str(pdf_path).encode("utf-8"))
    hasher.update(hash_file(pdf_path).encode("utf-8"))
    hasher.update(json.dumps(rubric_to_cache_payload(rubric), sort_keys=True).encode("utf-8"))
    return hasher.hexdigest()


class GeminiCacheStore:
    """SQLite-backed cache manager for Gemini responses and context caches."""

    def __init__(self, cache_dir: Path, max_retries: int = 5) -> None:
        self.cache_dir = cache_dir
        self.max_retries = max_retries
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / "cache.db"
        self._resolved_context_names: dict[str, str] = {}
        self._failed_context_keys: set[str] = set()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS grading_cache (hash_key TEXT PRIMARY KEY, payload TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS context_cache (hash_key TEXT PRIMARY KEY, payload TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )

    def get_grading_cache(self, key: str) -> JsonDict | None:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT payload FROM grading_cache WHERE hash_key = ?", (key,))
            row = cur.fetchone()
            if row:
                return json.loads(row[0])
        return None

    def set_grading_cache(self, key: str, payload: JsonDict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO grading_cache (hash_key, payload) VALUES (?, ?)",
                (key, json.dumps(payload)),
            )

    def get_context_cache(self, key: str) -> JsonDict | None:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT payload FROM context_cache WHERE hash_key = ?", (key,))
            row = cur.fetchone()
            if row:
                return json.loads(row[0])
        return None

    def set_context_cache(self, key: str, payload: JsonDict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO context_cache (hash_key, payload) VALUES (?, ?)",
                (key, json.dumps(payload)),
            )

    def delete_context_cache(self, key: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM context_cache WHERE hash_key = ?", (key,))

    def resolve_context_cache(
        self,
        client: Any,
        model: str,
        context_key: str,
        rubric: RubricConfig,
        solutions_pdf_path: Path,
        ttl_seconds: int,
        upload_and_wait_fn: Callable[[Path], Any],
        rate_limiter: Any | None = None,
    ) -> tuple[str | None, list[str]]:
        """Check, lookup, or create a remote context cache instance."""
        flags: list[str] = []
        if context_key in self._failed_context_keys:
            flags.extend(["context_cache_create_failed", "context_cache_bypassed"])
            return None, flags

        resolved = self._resolved_context_names.get(context_key)
        if resolved:
            return resolved, flags

        now = int(time.time())
        entry = self.get_context_cache(context_key)
        if isinstance(entry, dict):
            cache_name = str(entry.get("cache_name", "")).strip()
            expires_at = int(entry.get("expires_at", 0))
            if cache_name and expires_at > now:
                try:
                    call_with_backoff(
                        lambda: client.caches.get(name=cache_name),
                        max_retries=self.max_retries,
                    )
                    self._resolved_context_names[context_key] = cache_name
                    return cache_name, flags
                except Exception:
                    flags.append("context_cache_lookup_failed")
                    self.delete_context_cache(context_key)

        ttl = max(60, int(ttl_seconds))

        def create_cache() -> Any:
            acquire_rate_limit(rate_limiter, model)
            return client.caches.create(
                model=model,
                config={
                    "display_name": f"sda-solutions-{context_key[:12]}",
                    "ttl": f"{ttl}s",
                    "contents": [file_ref],
                    "system_instruction": build_context_system_instruction(rubric),
                },
            )

        try:
            file_ref = upload_and_wait_fn(solutions_pdf_path)
            cache = call_with_backoff(
                create_cache,
                max_retries=self.max_retries,
            )
            cache_name = str(getattr(cache, "name", "")).strip()
            if not cache_name:
                raise ValueError("Context cache create returned no cache name.")

            self.set_context_cache(context_key, {
                "cache_name": cache_name,
                "created_at": now,
                "expires_at": now + ttl,
                "model": model,
            })
            self._resolved_context_names[context_key] = cache_name
            return cache_name, flags
        except Exception:
            self._failed_context_keys.add(context_key)
            flags.extend(["context_cache_create_failed", "context_cache_bypassed"])
            return None, flags

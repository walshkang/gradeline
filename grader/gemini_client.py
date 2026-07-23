from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from .cost import extract_token_usage
from .gemini_normalize import (
    aggregate_subpart_verdicts,
    canonical_id,
    clamp_short_reason,
    derive_detail_reason,
    derive_short_reason,
    extract_detail_reason,
    extract_overflow_detail,
    extract_pithy_sentence,
    is_third_person_feedback,
    match_subparts_to_parent,
    merge_flags,
    normalize_confidence,
    normalize_draft_rubric_payload,
    normalize_feedback,
    normalize_locator_response,
    normalize_model_response,
    normalize_question_id,
    normalize_verdict,
    parse_coords_0_to_1000,
    parse_page_number,
)
from .gemini_resilience import (
    GeminiCacheStore,
    acquire_rate_limit,
    call_with_backoff,
    compute_agent_grade_cache_key,
    compute_context_cache_key,
    compute_grade_cache_key,
    compute_locator_cache_key,
    compute_unified_grade_cache_key,
    hash_file,
    parse_json_maybe_fenced,
    response_text,
    rubric_to_cache_payload,
    should_retry,
    structured_response_payload,
    time,
    wait_for_file_active,
)
from .gemini_schemas import (
    DEFAULT_CONTEXT_CACHE_TTL_SECONDS,
    DETAIL_REASON_MAX_CHARS,
    DETAIL_REASON_MAX_WORDS,
    NUMERIC_EQUIVALENCE_RULE,
    PROMPT_VERSION,
    SHORT_REASON_MAX_CHARS,
    SHORT_REASON_MAX_WORDS,
    DraftRubricBands,
    DraftRubricConfig,
    DraftRubricQuestion,
    DraftScoringCriterion,
    UnifiedQuestionItem,
    UnifiedSubmissionResponse,
    build_agent_grading_prompt,
    build_context_system_instruction,
    build_legacy_grading_prompt,
    build_locator_prompt,
    build_rubric_draft_prompt,
    build_rubric_lines,
    build_unified_grading_prompt,
)
from .types import JsonDict, QuestionRubric, QuestionResult, RubricConfig, TextBlock

__all__ = [
    "GeminiGrader",
    "GeminiCacheStore",
    "call_with_backoff",
    "should_retry",
    "wait_for_file_active",
    "structured_response_payload",
    "response_text",
    "parse_json_maybe_fenced",
    "compute_grade_cache_key",
    "compute_unified_grade_cache_key",
    "compute_context_cache_key",
    "compute_agent_grade_cache_key",
    "compute_locator_cache_key",
    "rubric_to_cache_payload",
    "hash_file",
    # Schema re-exports
    "DEFAULT_CONTEXT_CACHE_TTL_SECONDS",
    "DETAIL_REASON_MAX_CHARS",
    "DETAIL_REASON_MAX_WORDS",
    "NUMERIC_EQUIVALENCE_RULE",
    "PROMPT_VERSION",
    "SHORT_REASON_MAX_CHARS",
    "SHORT_REASON_MAX_WORDS",
    "DraftRubricBands",
    "DraftRubricConfig",
    "DraftRubricQuestion",
    "DraftScoringCriterion",
    "UnifiedQuestionItem",
    "UnifiedSubmissionResponse",
    "build_agent_grading_prompt",
    "build_context_system_instruction",
    "build_legacy_grading_prompt",
    "build_locator_prompt",
    "build_rubric_draft_prompt",
    "build_rubric_lines",
    "build_unified_grading_prompt",
    # Normalization re-exports
    "aggregate_subpart_verdicts",
    "canonical_id",
    "clamp_short_reason",
    "derive_detail_reason",
    "derive_short_reason",
    "extract_detail_reason",
    "extract_overflow_detail",
    "extract_pithy_sentence",
    "is_third_person_feedback",
    "match_subparts_to_parent",
    "merge_flags",
    "normalize_confidence",
    "normalize_draft_rubric_payload",
    "normalize_feedback",
    "normalize_locator_response",
    "normalize_model_response",
    "normalize_question_id",
    "normalize_verdict",
    "parse_coords_0_to_1000",
    "parse_page_number",
]


class GeminiGrader:
    """API client for Gemini grading operations, stitching together schemas, normalization, and resilience."""

    def __init__(
        self,
        api_key: str,
        model: str,
        cache_dir: Path,
        max_retries: int = 5,
        rate_limiter: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.cache_dir = cache_dir
        self.max_retries = max_retries
        self.rate_limiter = rate_limiter

        self.cache_store = GeminiCacheStore(cache_dir=cache_dir, max_retries=max_retries)

        from google import genai  # Lazy import for testability without dependency.

        self._genai = genai
        self.client = genai.Client(api_key=api_key)

    def _acquire(self, model: str) -> None:
        acquire_rate_limit(self.rate_limiter, model)

    def _get_cache(self, key: str) -> JsonDict | None:
        return self.cache_store.get_grading_cache(key)

    def _set_cache(self, key: str, payload: JsonDict) -> None:
        self.cache_store.set_grading_cache(key, payload)

    def _get_context_cache(self, key: str) -> JsonDict | None:
        return self.cache_store.get_context_cache(key)

    def _set_context_cache(self, key: str, payload: JsonDict) -> None:
        self.cache_store.set_context_cache(key, payload)

    def _delete_context_cache(self, key: str) -> None:
        self.cache_store.delete_context_cache(key)

    def _resolve_context_cache(
        self,
        context_key: str,
        rubric: RubricConfig,
        solutions_pdf_path: Path,
        ttl_seconds: int,
    ) -> tuple[str | None, list[str]]:
        return self.cache_store.resolve_context_cache(
            client=self.client,
            model=self.model,
            context_key=context_key,
            rubric=rubric,
            solutions_pdf_path=solutions_pdf_path,
            ttl_seconds=ttl_seconds,
            upload_and_wait_fn=self._upload_and_wait,
            rate_limiter=self.rate_limiter,
        )

    def grade_submission(
        self,
        submission_id: str,
        pdf_paths: list[Path],
        combined_text: str,
        rubric: RubricConfig,
        solutions_text: str,
        *,
        questions_to_grade: list[QuestionRubric] | None = None,
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
            questions_to_grade=questions_to_grade,
        )

        def invoke() -> tuple[JsonDict, Any]:
            self._acquire(self.model)
            response = self.client.models.generate_content(
                model=self.model,
                contents=[*files, prompt],
                config={"response_mime_type": "application/json"},
            )
            text = response_text(response)
            payload = parse_json_maybe_fenced(text)
            return payload, response

        payload, response = call_with_backoff(invoke, max_retries=self.max_retries)
        token_usage = extract_token_usage(response, self.model)
        payload["token_usage"] = token_usage.to_dict()
        normalized = normalize_model_response(payload, rubric, token_usage=token_usage)
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
        blocks: list[TextBlock] | None = None,
        *,
        questions_to_grade: list[QuestionRubric] | None = None,
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

        with ThreadPoolExecutor(max_workers=min(4, len(pdf_paths) or 1)) as executor:
            files = list(executor.map(self._upload_and_wait, pdf_paths))

        prompt = build_unified_grading_prompt(
            submission_id=submission_id,
            rubric=rubric,
            pdf_paths=pdf_paths,
            blocks=blocks or [],
            questions_to_grade=questions_to_grade,
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

        def invoke() -> tuple[JsonDict, Any]:
            self._acquire(self.model)
            config: JsonDict = {
                "response_mime_type": "application/json",
                "response_schema": UnifiedSubmissionResponse,
            }
            if cached_content:
                config["cached_content"] = cached_content

            response = self.client.models.generate_content(
                model=self.model,
                contents=[*files, prompt],
                config=config,
            )
            return structured_response_payload(response), response

        payload, response = call_with_backoff(invoke, max_retries=self.max_retries)
        token_usage = extract_token_usage(response, self.model)
        payload["token_usage"] = token_usage.to_dict()

        # Simulate per-question grading progress after the full response is available.
        qs = questions_to_grade if questions_to_grade is not None else rubric.questions
        total_questions = len(qs)
        if progress_callback is not None and total_questions > 0:
            for idx, question in enumerate(qs, start=1):
                try:
                    progress_callback(idx, total_questions, question.id)
                except Exception:
                    # Progress UI errors should never fail grading.
                    pass

        payload["global_flags"] = merge_flags(payload.get("global_flags", []), cache_flags)
        normalized = normalize_model_response(payload, rubric, token_usage=token_usage)
        self._set_cache(cache_key, payload)
        return normalized["questions"], normalized["global_flags"]

    def grade_submission_agent(
        self,
        submission_id: str,
        pdf_paths: list[Path],
        rubric: RubricConfig,
        solutions_pdf_path: Path,
        agent_type: str = "gemini",
        *,
        questions_to_grade: list[QuestionRubric] | None = None,
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
            questions_to_grade=questions_to_grade,
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
                raise RuntimeError(
                    f"Agent CLI '{agent_type}' failed with exit code {result.returncode}: {result.stderr or result.stdout}"
                )

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
            self._acquire(locator_model)
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

    def generate_rubric_draft(
        self,
        *,
        solutions_pdf: Path,
        assignment_id: str,
    ) -> JsonDict:
        """Generate a draft rubric config from the master solutions PDF."""
        if not solutions_pdf.exists() or not solutions_pdf.is_file():
            raise ValueError(f"Solutions PDF not found: {solutions_pdf}")

        file_ref = self._upload_and_wait(solutions_pdf)
        prompt = build_rubric_draft_prompt(assignment_id=assignment_id)

        def invoke() -> JsonDict:
            self._acquire(self.model)
            response = self.client.models.generate_content(
                model=self.model,
                contents=[file_ref, prompt],
                config={
                    "response_mime_type": "application/json",
                    "response_schema": DraftRubricConfig,
                },
            )
            return structured_response_payload(response)

        raw = call_with_backoff(invoke, max_retries=self.max_retries)
        return normalize_draft_rubric_payload(raw, assignment_id=assignment_id)

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

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from .agents import AgentDefinition, build_agent_cmd, get_agent
from .gemini_client import (
    build_agent_grading_prompt,
    call_with_backoff,
    compute_agent_grade_cache_key,
    merge_flags,
    normalize_model_response,
)
from .types import QuestionResult, RubricConfig


class AgentGrader:
    """Grades submissions using an external CLI agent (no Gemini API key required)."""

    def __init__(
        self,
        agent_type: str,
        model: str,
        cache_dir: Path,
        max_retries: int = 5,
    ) -> None:
        self.agent: AgentDefinition = get_agent(agent_type)
        self.agent_type = agent_type
        self.model = model
        self.cache_dir = cache_dir
        self.max_retries = max_retries
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def grade_submission(
        self,
        submission_id: str,
        pdf_paths: list[Path],
        rubric: RubricConfig,
        solutions_pdf_path: Path,
    ) -> tuple[list[QuestionResult], list[str]]:
        cache_key = compute_agent_grade_cache_key(
            submission_id=submission_id,
            pdf_paths=pdf_paths,
            rubric=rubric,
            model=self.model,
            agent_type=self.agent_type,
        )
        cached = self._get_cache(cache_key)
        if cached:
            normalized = normalize_model_response(cached, rubric)
            return normalized["questions"], normalized["global_flags"]

        prompt = _build_prompt(
            submission_id=submission_id,
            rubric=rubric,
            pdf_paths=pdf_paths,
            solutions_pdf_path=solutions_pdf_path,
            prompt_flavor=self.agent.prompt_flavor,
        )

        def invoke():
            cmd = build_agent_cmd(self.agent, prompt, self.model)
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, shell=False)
            if result.returncode != 0:
                raise RuntimeError(
                    f"Agent CLI '{self.agent_type}' failed with exit code {result.returncode}: "
                    f"{result.stderr or result.stdout}"
                )
            return self.agent.parse_output(result.stdout)

        payload = call_with_backoff(invoke, max_retries=self.max_retries)
        payload["global_flags"] = merge_flags(
            payload.get("global_flags", []),
            ["agent_mode", f"agent_{self.agent_type}"],
        )
        normalized = normalize_model_response(payload, rubric)
        self._set_cache(cache_key, payload)
        return normalized["questions"], normalized["global_flags"]

    def _init_db(self) -> None:
        self.db_path = self.cache_dir / "cache.db"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS grading_cache "
                "(hash_key TEXT PRIMARY KEY, payload TEXT, "
                "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS context_cache "
                "(hash_key TEXT PRIMARY KEY, payload TEXT, "
                "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )

    def _get_cache(self, key: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT payload FROM grading_cache WHERE hash_key = ?", (key,)
            )
            row = cur.fetchone()
            if row:
                return json.loads(row[0])
        return None

    def _set_cache(self, key: str, payload: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO grading_cache (hash_key, payload) VALUES (?, ?)",
                (key, json.dumps(payload)),
            )


def _build_prompt(
    submission_id: str,
    rubric: RubricConfig,
    pdf_paths: list[Path],
    solutions_pdf_path: Path,
    prompt_flavor: str,
) -> str:
    """Build the agent grading prompt using the given flavor string."""
    # Reuse the existing prompt builder but override the agent_type lookup
    # by temporarily passing a known agent type and replacing its flavor inline.
    # We call the original function with agent_type="gemini" (for structure) but
    # swap the flavor by building the prompt ourselves using the same template.
    from .gemini_client import build_rubric_lines, NUMERIC_EQUIVALENCE_RULE

    labels = ", ".join(question.id for question in rubric.questions)
    files_info = "\n".join([f"- Student File: {path.absolute()}" for path in pdf_paths])
    rubric_lines = build_rubric_lines(rubric)

    return (
        "You are an expert statistics grader. Your goal is to grade a student submission accurately.\n\n"
        f"{prompt_flavor}\n\n"
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

import csv
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from google import genai
from google.genai import types

from .config import load_rubric
from .review.state import load_state, write_state_atomic, state_path_for_output
from .workflow_profile import load_workflow_profile, get_project_root
from .defaults import DEFAULT_MODEL, resolve_model
from .ui import styled_info, styled_warning, styled_success, styled_error


class JudgeQuestionCritique(BaseModel):
    question_id: str
    critique: str
    proposed_verdict: Literal["correct", "partial", "rounding_error", "incorrect", "needs_review"]
    proposed_reason: str
    needs_fix: bool


class JudgeCritiqueResponse(BaseModel):
    critiques: list[JudgeQuestionCritique]


def run_judge(*, profile_spec: str) -> int:
    profile = load_workflow_profile(profile_spec, cwd=get_project_root())
    
    api_key = profile.grade.api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        styled_error("GEMINI_API_KEY is not set.")
        return 1

    audit_csv = profile.grade.output_dir / "grading_audit.csv"
    if not audit_csv.exists():
        styled_error(f"Audit CSV not found at {audit_csv}")
        return 1

    try:
        rubric = load_rubric(profile.grade.rubric_yaml)
    except Exception as e:
        styled_error(f"Failed to load rubric: {e}")
        return 1

    model = profile.grade.models.get("judge") if hasattr(profile.grade, "models") else None
    if not model:
        model = DEFAULT_MODEL
    
    try:
        model = resolve_model("judge", model)
    except (NameError, ImportError):
        pass  # If resolve_model not fully implemented in defaults.py, fallback to raw model.

    client = genai.Client(api_key=api_key)

    # Group rows by student name
    student_rows = defaultdict(list)
    with audit_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            student_name = row.get("student_name")
            if student_name:
                student_rows[student_name].append(row)

    state_path = state_path_for_output(profile.grade.output_dir)
    if not state_path.exists():
        styled_error("review_state.json not found. You must run grading and let it initialize the review state before running the judge.")
        return 1
        
    review_state = load_state(state_path)
    submissions = review_state.get("submissions", {})
    
    # Map student names to submission IDs to easily patch state
    student_to_sub_id = {}
    for sub_id, sub_data in submissions.items():
        sn = sub_data.get("student_name")
        if sn:
            student_to_sub_id[sn] = sub_id

    questions_dict = {q.id: q for q in rubric.questions}
    judged_count = 0

    # Iterate and critique
    for student_name, rows in student_rows.items():
        if student_name not in student_to_sub_id:
            styled_warning(f"Student {student_name} not found in review_state.json. Skipping.")
            continue
            
        sub_id = student_to_sub_id[student_name]
        styled_info(f"Judging student: {student_name}...")
        
        prompt_parts = [f"Please critique the grading for student: {student_name}.\n"]
        has_questions = False
        for row in rows:
            q_id = row.get("question_id")
            if not q_id or q_id not in questions_dict:
                continue
            
            has_questions = True
            q_rubric = questions_dict[q_id]
            prompt_parts.append(
                f"Question ID: {q_id}\n"
                f"Scoring Rules: {q_rubric.scoring_rules}\n"
                f"Short Note Fail: {q_rubric.short_note_fail}\n"
                f"Verdict Given: {row.get('verdict')}\n"
                f"Logic Analysis: {row.get('logic_analysis')}\n"
                f"Evidence Quote: {row.get('evidence_quote')}\n"
                f"Detail Reason: {row.get('detail_reason')}\n"
                "---\n"
            )

        if not has_questions:
            continue

        prompt_parts.append("Identify any grading mistakes. If the verdict is incorrect or partial, ensure a proposed_reason is provided. If you do not have a reason, fall back to the short_note_fail.")

        try:
            response = client.models.generate_content(
                model=model,
                contents="".join(prompt_parts),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=JudgeCritiqueResponse,
                    temperature=0.0,
                )
            )
            
            payload = json.loads(response.text)
            critique_resp = JudgeCritiqueResponse.model_validate(payload)
            
            for critique in critique_resp.critiques:
                q_id = critique.question_id
                
                # Rule: Never promote REVIEW_REQUIRED to a passing grade automatically.
                if critique.proposed_verdict in ["needs_review", "REVIEW_REQUIRED"]:
                    pass
                
                # Rule: Never annotate a point deduction without a short_reason. Fall back to short_note_fail.
                if critique.proposed_verdict in ["incorrect", "partial"] and not critique.proposed_reason.strip():
                    if q_id in questions_dict:
                        critique.proposed_reason = questions_dict[q_id].short_note_fail

                # Inject into state
                sub_questions = review_state["submissions"][sub_id].setdefault("questions", {})
                if q_id not in sub_questions:
                    sub_questions[q_id] = {}
                    
                sub_questions[q_id]["judge_critique"] = {
                    "critique": critique.critique,
                    "proposed_verdict": critique.proposed_verdict,
                    "proposed_reason": critique.proposed_reason,
                    "needs_fix": critique.needs_fix
                }
            
            judged_count += 1
                
        except Exception as e:
            styled_error(f"Failed to judge student {student_name}: {e}")
            continue

    write_state_atomic(state_path, review_state)
    styled_success(f"Successfully judged {judged_count} students. Wrote critiques to {state_path}")
    return 0

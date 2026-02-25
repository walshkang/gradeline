from __future__ import annotations

from pathlib import Path

from .types import QuestionRubric, RubricConfig


def load_rubric(path: Path) -> RubricConfig:
    import yaml  # Lazy import for friendlier CLI behavior before dependency install.

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Rubric config must be a mapping.")

    questions_raw = payload.get("questions")
    if not isinstance(questions_raw, list) or not questions_raw:
        raise ValueError("Rubric config must include a non-empty 'questions' list.")

    questions: list[QuestionRubric] = []
    for item in questions_raw:
        if not isinstance(item, dict):
            raise ValueError("Each rubric question must be an object.")
        questions.append(
            QuestionRubric(
                id=str(item["id"]).strip().lower(),
                label_patterns=[str(v) for v in item.get("label_patterns", [])],
                scoring_rules=str(item.get("scoring_rules", "")).strip(),
                short_note_pass=str(item.get("short_note_pass", "OK")).strip(),
                short_note_fail=str(item.get("short_note_fail", "Check")).strip(),
                weight=float(item.get("weight", 1.0)),
                anchor_tokens=[str(v) for v in item.get("anchor_tokens", [])],
            )
        )

    bands_raw = payload.get("bands")
    if not isinstance(bands_raw, dict):
        raise ValueError("Rubric config must include 'bands'.")
    if "check_plus_min" not in bands_raw or "check_min" not in bands_raw:
        raise ValueError("Bands must include check_plus_min and check_min.")

    return RubricConfig(
        assignment_id=str(payload.get("assignment_id", "assignment")).strip(),
        bands={
            "check_plus_min": float(bands_raw["check_plus_min"]),
            "check_min": float(bands_raw["check_min"]),
        },
        questions=questions,
        scoring_mode=str(payload.get("scoring_mode", "equal_weights")).strip(),
        partial_credit=float(payload.get("partial_credit", 0.5)),
    )

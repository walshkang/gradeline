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

    import warnings

    questions: list[QuestionRubric] = []
    for item in questions_raw:
        if not isinstance(item, dict):
            raise ValueError("Each rubric question must be an object.")
        q_rubric = QuestionRubric(
            id=str(item["id"]).strip().lower(),
            label_patterns=[str(v) for v in item.get("label_patterns", [])],
            scoring_rules=str(item.get("scoring_rules", "")).strip(),
            short_note_pass=str(item.get("short_note_pass", "OK")).strip(),
            short_note_fail=str(item.get("short_note_fail", "Check")).strip(),
            weight=float(item.get("weight", 1.0)),
            anchor_tokens=[str(v) for v in item.get("anchor_tokens", [])],
            expected_answers=[str(v) for v in item.get("expected_answers", [])],
            requires_work=bool(item.get("requires_work", False)),
        )
        if not q_rubric.short_note_fail or q_rubric.short_note_fail == "Check":
            warnings.warn(
                f"Question '{q_rubric.id}' has an empty or generic short_note_fail ('{q_rubric.short_note_fail}'). "
                "It is recommended to provide a descriptive failure note.",
                UserWarning,
            )
        questions.append(q_rubric)

    bands_raw = payload.get("bands")
    if not isinstance(bands_raw, dict):
        raise ValueError("Rubric config must include 'bands'.")
    if not bands_raw:
        raise ValueError("Bands must not be empty.")

    bands = {str(k).strip(): float(v) for k, v in bands_raw.items()}

    rubric = RubricConfig(
        assignment_id=str(payload.get("assignment_id", "assignment")).strip(),
        bands=bands,
        questions=questions,
        scoring_mode=str(payload.get("scoring_mode", "equal_weights")).strip(),
        partial_credit=float(payload.get("partial_credit", 0.5)),
    )
    validate_expected_answers(rubric)
    return rubric


def validate_expected_answers(rubric: RubricConfig) -> None:
    import re
    import warnings

    for question in rubric.questions:
        if not question.expected_answers:
            continue

        # 1. Question label matching check (headers/numbers)
        test_headers = [
            f"Problem {question.id}",
            f"Question {question.id}",
            f"P{question.id}",
            f"Q{question.id}",
            f"{question.id}.",
            f"{question.id})"
        ]
        for pattern in question.label_patterns:
            test_headers.append(pattern)
            test_headers.append(f"{pattern} {question.id}")

        for pat in question.expected_answers:
            for header in test_headers:
                try:
                    if re.search(pat, header, flags=re.IGNORECASE | re.DOTALL):
                        warnings.warn(
                            f"Question '{question.id}' expected_answers regex '{pat}' matches simulated label/header '{header}'. "
                            "This will cause false positive matches on student submissions. Remove this regex or add strict boundaries.",
                            UserWarning,
                        )
                        break
                except re.error as e:
                    warnings.warn(
                        f"Question '{question.id}' expected_answers regex '{pat}' is invalid: {e}",
                        UserWarning,
                    )
                    break

            # 2. Missing word boundaries check (substring/suffix matches)
            alts = pat.split('|')
            for alt in alts:
                clean_alt = alt.replace('\\b', '').replace('\\.', '.').replace('\\', '')
                if re.match(r'^-?\d+(?:\.\d+)?$', clean_alt):
                    test_cases = []
                    if clean_alt.startswith('-'):
                        test_cases.append(clean_alt + '0')
                    else:
                        test_cases.append(clean_alt + '0')
                        test_cases.append('1' + clean_alt)
                    if '.' in clean_alt:
                        test_cases.append(clean_alt + '9')

                    for wrong_val in test_cases:
                        try:
                            if re.search(pat, wrong_val, flags=re.IGNORECASE | re.DOTALL):
                                warnings.warn(
                                    f"Question '{question.id}' expected_answers regex '{pat}' matches simulated incorrect value '{wrong_val}'. "
                                    "This suggests the regex lacks appropriate word boundaries (e.g. use '\\b' or double backslashes in YAML).",
                                    UserWarning,
                                )
                                break
                        except re.error:
                            pass


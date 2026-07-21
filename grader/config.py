from __future__ import annotations

from pathlib import Path

from .types import ExpectedNumeric, QuestionRubric, RubricConfig, ScoringCriterion


def compile_numeric_regex(exp_num: ExpectedNumeric) -> list[str]:
    """Compile numeric range into word-bounded regex patterns for decimals and percentages."""
    import math

    value = float(exp_num.value)
    tolerance = abs(float(exp_num.tolerance))
    allow_percent = bool(exp_num.allow_percent)

    min_val = round(value - tolerance, 10)
    max_val = round(value + tolerance, 10)
    if min_val > max_val:
        min_val, max_val = max_val, min_val

    sub_patterns: list[str] = []

    def _format_decimal_pattern(v: float, is_primary: bool) -> str:
        is_neg = v < 0
        abs_v = abs(v)
        str_val = f"{abs_v:.10f}".rstrip("0").rstrip(".") if "." in f"{abs_v:.10f}" else f"{abs_v:.0f}"
        if not str_val:
            str_val = "0"

        prefix = r"-\s*" if is_neg else ""
        if "." in str_val:
            parts = str_val.split(".")
            int_part = parts[0]
            dec_part = parts[1]
            if int_part == "0" or int_part == "":
                boundary = r"(?<![\w.])"
                if is_primary:
                    pattern = rf"{boundary}{prefix}0?\.{dec_part}\d*\b"
                else:
                    pattern = rf"{boundary}{prefix}0?\.{dec_part}0*\b"
            else:
                boundary = r"\b"
                if is_primary:
                    pattern = rf"{boundary}{prefix}{int_part}\.{dec_part}\d*\b"
                else:
                    pattern = rf"{boundary}{prefix}{int_part}\.{dec_part}0*\b"
        else:
            boundary = r"\b"
            pattern = rf"{boundary}{prefix}{str_val}(?:\.0+)?\b"

        return pattern

    def _format_percent_pattern(v: float, is_primary: bool) -> str:
        pct_v = v * 100
        is_neg = pct_v < 0
        abs_v = abs(pct_v)
        str_val = f"{abs_v:.10f}".rstrip("0").rstrip(".") if "." in f"{abs_v:.10f}" else f"{abs_v:.0f}"
        if not str_val:
            str_val = "0"

        prefix = r"-\s*" if is_neg else ""
        if "." in str_val:
            parts = str_val.split(".")
            int_part = parts[0]
            dec_part = parts[1]
            if int_part == "0" or int_part == "":
                boundary = r"(?<![\w.])"
                if is_primary:
                    pattern = rf"{boundary}{prefix}0?\.{dec_part}\d*\s*%"
                else:
                    pattern = rf"{boundary}{prefix}0?\.{dec_part}\s*%"
            else:
                boundary = r"\b"
                if is_primary:
                    pattern = rf"{boundary}{prefix}{int_part}\.{dec_part}\d*\s*%"
                else:
                    pattern = rf"{boundary}{prefix}{int_part}\.{dec_part}\s*%"
        else:
            boundary = r"\b"
            pattern = rf"{boundary}{prefix}{str_val}\s*%"

        return pattern

    p_primary = _format_decimal_pattern(value, is_primary=True)
    if p_primary not in sub_patterns:
        sub_patterns.append(p_primary)

    if allow_percent:
        p_pct = _format_percent_pattern(value, is_primary=True)
        if p_pct not in sub_patterns:
            sub_patterns.append(p_pct)

    candidates: set[float] = set()
    for prec in range(0, 6):
        mult = 10**prec
        c_round = round(value, prec)
        c_floor = math.floor(value * mult) / mult
        c_ceil = math.ceil(value * mult) / mult

        for candidate in (c_round, c_floor, c_ceil):
            cand_rounded = round(candidate, 10)
            if min_val <= cand_rounded <= max_val:
                candidates.add(cand_rounded)

    candidates.discard(round(value, 10))

    for cand in sorted(candidates):
        pat_dec = _format_decimal_pattern(cand, is_primary=False)
        if pat_dec not in sub_patterns:
            sub_patterns.append(pat_dec)
        if allow_percent:
            pat_pct = _format_percent_pattern(cand, is_primary=False)
            if pat_pct not in sub_patterns:
                sub_patterns.append(pat_pct)

    if not sub_patterns:
        return []
    if len(sub_patterns) == 1:
        return [sub_patterns[0]]
    return ["(?:" + "|".join(sub_patterns) + ")"]



def load_rubric(path: Path | str) -> RubricConfig:
    import yaml  # Lazy import for friendlier CLI behavior before dependency install.

    path = Path(path)
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
        q_id = str(item["id"]).strip().lower()

        scoring_criteria_raw = item.get("scoring_criteria", [])
        scoring_criteria: list[ScoringCriterion] = []
        if isinstance(scoring_criteria_raw, list):
            for sc in scoring_criteria_raw:
                if not isinstance(sc, dict):
                    raise ValueError(f"Each scoring_criteria entry in question '{q_id}' must be a mapping.")
                req = str(sc.get("requirement", "")).strip()
                if not req:
                    raise ValueError(f"Scoring criterion in question '{q_id}' has an empty requirement.")
                try:
                    weight_val = float(sc.get("weight", 1.0))
                except (TypeError, ValueError):
                    weight_val = 1.0
                partial_if_val = str(sc.get("partial_if", "")).strip()
                scoring_criteria.append(
                    ScoringCriterion(
                        requirement=req,
                        weight=weight_val,
                        partial_if=partial_if_val,
                    )
                )

        exp_num_raw = item.get("expected_numeric")
        expected_numeric: ExpectedNumeric | None = None
        if isinstance(exp_num_raw, dict):
            if "value" not in exp_num_raw:
                raise ValueError(f"Question '{q_id}' expected_numeric must contain a 'value'.")
            try:
                val = float(exp_num_raw["value"])
                tol = float(exp_num_raw.get("tolerance", 0.0))
                allow_pct = bool(exp_num_raw.get("allow_percent", True))
                expected_numeric = ExpectedNumeric(
                    value=val,
                    tolerance=tol,
                    allow_percent=allow_pct,
                )
            except (TypeError, ValueError) as e:
                raise ValueError(f"Invalid expected_numeric fields in question '{q_id}': {e}") from e

        expected_answers = [str(v) for v in item.get("expected_answers", [])]
        if expected_numeric is not None:
            compiled = compile_numeric_regex(expected_numeric)
            for pat in compiled:
                if pat not in expected_answers:
                    expected_answers.append(pat)

        q_rubric = QuestionRubric(
            id=q_id,
            label_patterns=[str(v) for v in item.get("label_patterns", [])],
            scoring_rules=str(item.get("scoring_rules", "")).strip(),
            short_note_pass=str(item.get("short_note_pass", "OK")).strip(),
            short_note_fail=str(item.get("short_note_fail", "Check")).strip(),
            weight=float(item.get("weight", 1.0)),
            anchor_tokens=[str(v) for v in item.get("anchor_tokens", [])],
            expected_answers=expected_answers,
            requires_work=bool(item.get("requires_work", False)),
            scoring_criteria=scoring_criteria,
            expected_numeric=expected_numeric,
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


import math
import re
from collections.abc import Mapping


def _normalized_text(value: str, config: Mapping) -> str:
    if config.get("trim_whitespace", True):
        value = value.strip()
    if config.get("ignore_spaces", False):
        value = re.sub(r"\s+", "", value)
    if not config.get("case_sensitive", False):
        value = value.casefold()
    return value


def _partial_choice_score(
    question: dict,
    selected_ids: set[str],
    correct_ids: set[str],
) -> float:
    points = float(question["points"])
    rules = question.get("partial_credit") or {}
    if rules.get("all_or_nothing", True):
        return points if selected_ids == correct_ids else 0.0
    score = len(selected_ids & correct_ids) * float(rules.get("per_correct_option", 0))
    score -= len(selected_ids - correct_ids) * float(rules.get("penalty_per_incorrect_option", 0))
    return min(points, max(0.0, score))


def auto_grade(question: dict, answer: dict | None) -> float | None:
    question_type = question["question_type"]
    if question_type in ("long_answer", "code"):
        return None

    answer = answer or {}
    config = question.get("answer_config") or {}
    points = float(question["points"])

    if question_type in ("single_choice", "multiple_choice", "true_false"):
        selected = {str(value) for value in answer.get("selected_option_ids", [])}
        correct = {str(value) for value in question.get("correct_option_ids", [])}
        return _partial_choice_score(question, selected, correct)

    if question_type in ("fill_blank", "short_answer"):
        value = answer.get("text_answer")
        if value is None:
            return 0.0
        normalized = _normalized_text(value, config)
        accepted = {
            _normalized_text(item, config)
            for item in question.get("accepted_answers", [])
        }
        return points if normalized in accepted else 0.0

    if question_type == "numeric":
        value = (answer.get("answer_data") or {}).get("value", answer.get("text_answer"))
        try:
            actual = float(value)
            expected = float(config["correct_value"])
            tolerance = float(config.get("tolerance", 0))
        except (TypeError, ValueError, KeyError):
            return 0.0
        unit = (answer.get("answer_data") or {}).get("unit")
        expected_unit = config.get("unit")
        if (
            not math.isfinite(actual)
            or not math.isfinite(expected)
            or not math.isfinite(tolerance)
            or (expected_unit is not None and unit != expected_unit)
        ):
            return 0.0
        return points if abs(actual - expected) <= tolerance else 0.0

    submitted = answer.get("answer_data") or {}
    expected = config.get("correct_answer")
    if expected is None:
        return 0.0
    if question_type == "hotspot" and isinstance(expected, Mapping):
        try:
            distance = math.dist(
                (float(submitted["x"]), float(submitted["y"])),
                (float(expected["x"]), float(expected["y"])),
            )
        except (KeyError, TypeError, ValueError):
            return 0.0
        return points if distance <= float(config.get("tolerance", 0)) else 0.0
    actual = submitted.get("value", submitted)
    return points if actual == expected else 0.0

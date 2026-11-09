import ast
import math
import operator
import re
import secrets
from decimal import Decimal


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _evaluate(node: ast.AST, values: dict[str, float], depth: int = 0) -> float:
    if depth > 20:
        raise ValueError("Numeric answer expression is too complex")
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, values, depth + 1)
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        result = float(node.value)
    elif isinstance(node, ast.Name) and node.id in values:
        result = values[node.id]
    elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate(node.left, values, depth + 1)
        right = _evaluate(node.right, values, depth + 1)
        if isinstance(node.op, ast.Pow) and abs(right) > 8:
            raise ValueError("Exponents in numeric answer expressions are limited to 8")
        result = _BINARY_OPERATORS[type(node.op)](left, right)
    elif isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        result = _UNARY_OPERATORS[type(node.op)](_evaluate(node.operand, values, depth + 1))
    else:
        raise ValueError("Numeric answer expression contains an unsupported operation")
    if not math.isfinite(result) or abs(result) > 1e100:
        raise ValueError("Numeric answer expression result is outside supported bounds")
    return result


def _format_value(value: float) -> str:
    return str(int(value)) if value.is_integer() else format(value, ".12g")


def materialize_question(
    question: dict,
    parameter_values: dict[str, str] | None = None,
) -> dict:
    parameter_config = question.get("parameter_config") or {}
    if not parameter_config:
        return question

    values: dict[str, float] = {}
    if parameter_values is not None:
        values = {name: float(value) for name, value in parameter_values.items()}
    else:
        for name, bounds in parameter_config.items():
            minimum = Decimal(str(bounds["minimum"]))
            maximum = Decimal(str(bounds["maximum"]))
            step = Decimal(str(bounds.get("step", 1)))
            steps = int((maximum - minimum) // step)
            values[name] = float(minimum + secrets.randbelow(steps + 1) * step)

    rendered = dict(question)
    placeholders = {name: _format_value(value) for name, value in values.items()}

    def replace(text: str) -> str:
        return re.sub(
            r"\{([A-Za-z_][A-Za-z0-9_]*)\}",
            lambda match: placeholders.get(match.group(1), match.group(0)),
            text,
        )

    def render(value):
        if isinstance(value, str):
            return replace(value)
        if isinstance(value, list):
            return [render(item) for item in value]
        if isinstance(value, dict):
            return {key: render(item) for key, item in value.items()}
        return value

    rendered["question_text"] = replace(question["question_text"])
    rendered["_parameter_values"] = placeholders
    rendered["accepted_answers"] = render(question.get("accepted_answers", []))
    rendered["answer_config"] = render(question.get("answer_config", {}))
    expression = (question.get("answer_config") or {}).get("correct_value_expression")
    if expression:
        parsed = ast.parse(expression, mode="eval")
        rendered["answer_config"]["correct_value"] = _evaluate(parsed, values)
        rendered["answer_config"].pop("correct_value_expression", None)
    rendered["interaction_config"] = render(question.get("interaction_config", {}))
    return rendered


def materialize_option(option: dict, values: dict | None = None) -> dict:
    placeholders = values or {}
    rendered = dict(option)
    replace = lambda text: re.sub(
        r"\{([A-Za-z_][A-Za-z0-9_]*)\}",
        lambda match: placeholders.get(match.group(1), match.group(0)),
        text,
    )
    rendered["option_text"] = replace(option["option_text"])
    if option.get("feedback"):
        rendered["feedback"] = replace(option["feedback"])
    rendered["media"] = [
        {
            **media,
            "alt_text": replace(media["alt_text"]) if media.get("alt_text") else None,
        }
        for media in option.get("media", [])
    ]
    return rendered

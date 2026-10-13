"""Bounded, typed three-valued predicates; no executable uploaded code."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

ENGINE_VERSION = "PH4_TYPED_RULES_V1"
OPERATORS = {
    "literal",
    "field",
    "and",
    "or",
    "not",
    "required",
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "contains_all",
    "set_equal",
    "all",
}


def validate(expression, depth=0, counter=None):
    counter = counter if counter is not None else [0]
    counter[0] += 1
    if depth > 12 or counter[0] > 256 or not isinstance(expression, dict):
        raise ValueError("Rule expression exceeds the bounded typed grammar")
    op = expression.get("op")
    allowed = (
        {"op", "value"}
        if op == "literal"
        else {"op", "path", "type"}
        if op == "field"
        else {"op", "args", "type"}
    )
    if op not in OPERATORS or set(expression) - allowed:
        raise ValueError("Unknown rule operator or expression field")
    if op == "field":
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", expression.get("path", "")):
            raise ValueError("Use a named input field, not an executable path")
        if expression.get("type", "value") not in {
            "value",
            "money",
            "decimal",
            "date",
            "timestamp",
            "boolean",
        }:
            raise ValueError("Unsupported field type")
    elif op == "literal":
        value = expression.get("value")
        if (
            isinstance(value, dict)
            or (
                isinstance(value, list)
                and (len(value) > 100 or any(isinstance(v, list | dict | float) for v in value))
            )
            or (isinstance(value, str) and len(value) > 1000)
        ):
            raise ValueError("Literal values are bounded scalars or scalar lists")
        if isinstance(expression.get("value"), float):
            raise ValueError("Rule numbers are integer or decimal strings, never floats")
    else:
        args = expression.get("args")
        arity = 1 if op in {"not", "required"} else 2 if op not in {"and", "or"} else None
        if (
            not isinstance(args, list)
            or (arity and len(args) != arity)
            or (not arity and not 1 <= len(args) <= 40)
        ):
            raise ValueError("Wrong operator argument count")
        for arg in args:
            validate(arg, depth + 1, counter)
    return expression


def get(context, path):
    value = context
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return None if value in ("UNKNOWN", "NOT_PROVIDED") else value


def typed(value, kind):
    if value is None:
        return None
    try:
        if kind in {"money", "decimal"}:
            if isinstance(value, float | bool) or not isinstance(value, str | int | Decimal):
                return None
            number = Decimal(value)
            if not number.is_finite() or (kind == "money" and number != number.to_integral_value()):
                return None
            return number
        if kind == "date":
            return date.fromisoformat(value) if isinstance(value, str) else value
        if kind == "timestamp":
            result = (
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                if isinstance(value, str)
                else value
            )
            return result if result.tzinfo else None
        if kind == "boolean":
            return value if type(value) is bool else None
    except (ValueError, TypeError, InvalidOperation, AttributeError):
        return None
    return value


def evaluate(expression, context):
    op = expression["op"]
    if op == "literal":
        return expression.get("value")
    if op == "field":
        return typed(get(context, expression["path"]), expression.get("type", "value"))
    args = [evaluate(arg, context) for arg in expression["args"]]
    if op == "and":
        return (
            False
            if any(a is False for a in args)
            else True
            if all(a is True for a in args)
            else None
        )
    if op == "or":
        return (
            True
            if any(a is True for a in args)
            else False
            if all(a is False for a in args)
            else None
        )
    if op == "not":
        return not args[0] if type(args[0]) is bool else None
    if op == "required":
        return args[0] is not None and args[0] != ""
    if any(a is None for a in args):
        return None
    a, b = args
    kind = expression.get("type", "value")
    a, b = typed(a, kind), typed(b, kind)
    if a is None or b is None:
        return None
    try:
        if op == "eq":
            if isinstance(a, bool) != isinstance(b, bool):
                return None
            return a == b
        if op == "ne":
            if isinstance(a, bool) != isinstance(b, bool):
                return None
            return a != b
        if op == "gt":
            return a > b
        if op == "gte":
            return a >= b
        if op == "lt":
            return a < b
        if op == "lte":
            return a <= b
        if op == "in":
            return a in b
        if op == "contains_all":
            return set(b) <= set(a)
        if op == "set_equal":
            return set(a) == set(b)
        if op == "all":
            return all(item is True for item in a) if isinstance(a, list) and b is True else None
    except (TypeError, ValueError):
        return None
    return None

"""Deterministic checks for numerical questions.

A generated numerical problem carries its solution as a formula over named givens, e.g.
`v0 + a*t` with `{"v0": 2.5, "a": 2.0, "t": 5.0}`. The formula is evaluated here with a
whitelist interpreter, so an answer key is accepted only if arithmetic reproduces it.
"""
from __future__ import annotations

import ast
import math
import operator
import re

FUNCTIONS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin,
    "acos": math.acos, "atan": math.atan, "atan2": math.atan2, "exp": math.exp, "log": math.log,
    "log10": math.log10, "abs": abs, "radians": math.radians, "degrees": math.degrees,
    "min": min, "max": max, "pow": pow,
}
CONSTANTS = {"pi": math.pi, "e": math.e, "g": 9.8}
BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
}
UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}


class FormulaError(ValueError):
    pass


def evaluate(formula: str, variables: dict[str, float]) -> float:
    """Evaluate an arithmetic expression. Only numbers, the given names, + - * / ** % and maths functions."""
    names = {**CONSTANTS, **{k: float(v) for k, v in variables.items()}}

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise FormulaError(f"unknown name '{node.id}'")
            return names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            return BINARY[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY:
            return UNARY[type(node.op)](walk(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords:
            return float(FUNCTIONS[node.func.id](*[walk(arg) for arg in node.args]))
        raise FormulaError(f"unsupported expression element: {type(node).__name__}")

    try:
        value = walk(ast.parse(formula.replace("^", "**"), mode="eval"))
    except (SyntaxError, ZeroDivisionError, OverflowError, TypeError, ValueError) as error:
        raise FormulaError(str(error)) from error
    if isinstance(value, complex) or math.isnan(value) or math.isinf(value):
        raise FormulaError("result is not a finite real number")
    return value


def close(a: float, b: float, tolerance_pct: float = 2.0) -> bool:
    """Relative agreement within `tolerance_pct` percent (absolute near zero)."""
    scale = max(abs(a), abs(b))
    if scale < 1e-9:
        return True
    return abs(a - b) <= max(scale * tolerance_pct / 100.0, 1e-9)


NUMBER = re.compile(r"[-+]?\d[\d,]*\.?\d*(?:\s*(?:[eE]|[x×*]\s*10\s*\^?)\s*[-+]?\d+)?|[-+]?\.\d+")


def parse_number(text: str) -> float | None:
    """First number in a student's answer: '12.5 m/s', '-3', '4.0 x 10^3', '1,200'."""
    match = NUMBER.search(text.replace("−", "-"))
    if not match:
        return None
    token = match.group(0).replace(",", "")
    token = re.sub(r"\s*[x×*]\s*10\s*\^?\s*", "e", token).replace(" ", "")
    try:
        return float(token)
    except ValueError:
        return None


def diagnose(response: float, key: float, tolerance_pct: float, unit: str = "") -> str:
    """Name the slip behind a wrong numerical answer when its signature is recognisable.

    A conversion factor is only suggested when the answer's unit makes that slip possible:
    3.6 for a speed, 60 for a time, 9.8 for a force or a weight.
    """
    if close(response, -key, tolerance_pct) and abs(key) > 1e-9:
        return "sign error: the magnitude is right but the direction (sign) is reversed"
    unit = unit.lower().replace("\\text", "").replace("{", "").replace("}", "").replace(" ", "")
    speed = "m/s" in unit and "s^2" not in unit and "s2" not in unit or "km/h" in unit
    time = unit in ("s", "min", "h", "seconds", "minutes", "hours")
    force = unit in ("n", "newtons", "kg") or unit.endswith("n")
    candidates = [
        (1000.0, "unit conversion: off by a factor of 1000 (for example grams and kilograms, or metres and kilometres)", True),
        (3.6, "unit conversion: km/h and m/s were mixed (factor of 3.6)", speed),
        (60.0, "unit conversion: minutes and seconds were mixed (factor of 60)", time),
        (9.8, "the factor g = 9.8 m/s² is missing or extra (mass and weight were mixed)", force),
        (2.0, "a factor of 2 is missing or extra (check a ½ in the formula)", True),
    ]
    for factor, label, applies in candidates:
        if applies and (close(response, key * factor, tolerance_pct) or close(response, key / factor, tolerance_pct)):
            return label
    if key != 0 and response != 0:
        power = math.log10(abs(response / key))
        if abs(power - round(power)) < 0.01 and round(power) != 0:
            return "power-of-ten slip: the digits are right but the decimal point is misplaced"
    return ""

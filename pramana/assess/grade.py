"""Grading with cited feedback.

MCQ and numerical answers are graded deterministically. A wrong MCQ choice maps to the
misconception its distractor was written to catch; a wrong number is checked against the
signatures of common slips (sign, unit conversion, a missing ½). Short answers are graded by
a model against the item's key points, and fall back to key-point overlap when no model is
available.
"""
from __future__ import annotations

import re

from ..config import settings
from ..llm import LLMError, ReplayMiss, llm
from . import numeric

SHORT_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "points_met": {"type": "array", "items": {"type": "boolean"}},
        "feedback": {"type": "string"},
        "misconception": {"type": "string"},
    },
    "required": ["score", "points_met", "feedback", "misconception"],
}

SHORT_PROMPT = """Grade a student's short answer for a course quiz.

Question: {stem}
Reference answer: {reference}
Key points a correct answer must contain:
{points}

Student's answer: {response}

Return:
- "points_met": one boolean per key point, in order.
- "score": 1 if all key points are met and nothing stated is wrong; 0.5 if some are met; 0 if none are met or the answer asserts something false about the concept.
- "feedback": two sentences addressed to the student: what was right, then what is missing or wrong.
- "misconception": if the answer reveals a specific mistaken belief, name it in a short phrase; otherwise an empty string.

Judge meaning, not wording. Do not reward an answer that only restates the question.
"""


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3}


def grade(question: dict, response) -> dict:
    """Score a response in [0, 1] with feedback. `response` is an option index, a number/string, or text."""
    answer = question["answer"]
    kind = question["type"]
    out = {"score": 0.0, "correct_answer": answer.get("text", ""), "feedback": "", "misconception": "", "graded_by": "rule"}

    if kind == "mcq":
        try:
            chosen = int(response)
        except (TypeError, ValueError):
            chosen = -1
        out["score"] = 1.0 if chosen == answer["option"] else 0.0
        out["correct_option"] = answer["option"]
        if out["score"] < 1 and 0 <= chosen < len(answer.get("misconceptions", [])):
            out["misconception"] = answer["misconceptions"][chosen]
        out["feedback"] = "Correct." if out["score"] == 1 else "Not quite."
        return out

    if kind == "numeric":
        value = response if isinstance(response, (int, float)) else numeric.parse_number(str(response))
        tolerance = float(answer.get("tolerance_pct", 2.0))
        unit = f" {answer['unit']}" if answer.get("unit") else ""
        out["correct_answer"] = f"{answer['value']:.4g}{unit}"
        if value is None:
            out["feedback"] = "No number found in the answer."
            return out
        if numeric.close(float(value), float(answer["value"]), tolerance):
            out["score"], out["feedback"] = 1.0, "Correct."
            return out
        out["misconception"] = numeric.diagnose(float(value), float(answer["value"]), tolerance, answer.get("unit", ""))
        out["feedback"] = f"Expected {out['correct_answer']}."
        return out

    # short answer
    text = str(response or "").strip()
    points = answer.get("key_points") or [answer.get("text", "")]
    if len(text.split()) < 2:
        out["feedback"] = "No answer given."
        return out
    try:
        result = llm().chat(
            [{"role": "user", "content": SHORT_PROMPT.format(
                stem=question["stem"], reference=answer.get("text", ""),
                points="\n".join(f"- {p}" for p in points), response=text)}],
            models=settings.verifier_models, namespace="grade-short", schema=SHORT_SCHEMA,
        ).json()
        score = float(result.get("score", 0))
        out.update({
            "score": 1.0 if score >= 0.99 else 0.5 if score >= 0.4 else 0.0,
            "feedback": result.get("feedback", ""), "misconception": result.get("misconception", ""),
            "points_met": result.get("points_met", []), "graded_by": "model",
        })
    except (LLMError, ReplayMiss):
        # No model reachable: credit the share of key points whose content words appear in the answer.
        said = _words(text)
        met = [len(_words(p) & said) >= max(1, len(_words(p)) // 2) for p in points]
        share = sum(met) / len(met)
        out.update({
            "score": 1.0 if share >= 0.99 else 0.5 if share >= 0.4 else 0.0, "points_met": met,
            "feedback": "Graded by key-point overlap (no grading model was reachable).", "graded_by": "overlap",
        })
    return out

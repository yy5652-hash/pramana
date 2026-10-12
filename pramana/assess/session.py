"""Assessment lifecycle: start, answer, report.

Three kinds share one flow:

* `diagnostic`: for a student with no history. A short adaptive sweep that walks the
  prerequisite map: each answer rules concepts in or out, so ten questions place a student
  across the whole course.
* `quiz`: adaptive practice on a chosen scope, with cited feedback after every answer.
* `exam`: a fixed mock paper with even coverage; feedback is held back until the end.
"""
from __future__ import annotations

import json

from ..cite import citations_for, study_links
from ..db import Database, new_id, now
from ..learner import WEAK, Learner
from .grade import grade
from .select import Selector

DEFAULT_LENGTH = {"diagnostic": 10, "quiz": 8, "exam": 12}


def public(question: dict) -> dict:
    """A question as the student sees it: no key, no explanation."""
    return {
        "id": question["id"], "concept_id": question["concept_id"], "type": question["type"],
        "difficulty": question["difficulty"], "stem": question["stem"], "options": question["options"],
        "unit": question["answer"].get("unit", "") if question["type"] == "numeric" else "",
    }


def start(db: Database, student_id: str, kind: str, concept_ids: list[str] | None = None,
          n: int | None = None, types: list[str] | None = None, policy: str = "adaptive") -> dict:
    scope = concept_ids or [c["id"] for c in db.all("SELECT id FROM concepts ORDER BY ord")]
    length = n or DEFAULT_LENGTH[kind]
    selector = Selector(db, student_id, policy)
    question_ids: list[str] = []
    if kind == "exam":
        question_ids = [q["id"] for q in selector.exam(scope, length, types)]
    assessment = {
        "id": new_id("a"), "student_id": student_id, "kind": kind,
        "scope": {"concept_ids": scope, "n": length, "types": types, "policy": policy},
        "question_ids": question_ids, "created": now(), "finished": None, "report": None,
    }
    db.insert("assessments", assessment)
    return {"assessment_id": assessment["id"], "kind": kind, "length": length, "question": next_question(db, assessment["id"])}


def next_question(db: Database, assessment_id: str) -> dict | None:
    """The next unanswered question (public view), choosing it now for adaptive kinds."""
    assessment = db.one("SELECT * FROM assessments WHERE id = ?", [assessment_id])
    answered = [r["question_id"] for r in db.all("SELECT question_id FROM attempts WHERE assessment_id = ? ORDER BY id", [assessment_id])]
    scope = assessment["scope"]
    if len(answered) >= scope["n"]:
        return None
    if assessment["kind"] == "exam":
        remaining = [q for q in assessment["question_ids"] if q not in answered]
        question = db.one("SELECT * FROM questions WHERE id = ?", [remaining[0]]) if remaining else None
    else:
        pending = [q for q in assessment["question_ids"] if q not in answered]
        if pending:  # a question was already chosen and shown; do not re-roll it
            question = db.one("SELECT * FROM questions WHERE id = ?", [pending[0]])
        else:
            selector = Selector(db, assessment["student_id"], scope.get("policy", "adaptive"))
            if assessment["kind"] == "diagnostic":
                question = selector.diagnostic_question(assessment["question_ids"])
            else:
                question = selector.next_question(scope["concept_ids"], assessment["question_ids"], scope.get("types"))
            if question:
                db.run("UPDATE assessments SET question_ids = ? WHERE id = ?",
                       [json.dumps(assessment["question_ids"] + [question["id"]]), assessment_id])
    if not question:
        return None
    return {**public(question), "position": len(answered) + 1, "of": scope["n"]}


def answer(db: Database, course_id: str, assessment_id: str, question_id: str, response) -> dict:
    """Grade one answer, update the learner model, and say what comes next."""
    assessment = db.one("SELECT * FROM assessments WHERE id = ?", [assessment_id])
    question = db.one("SELECT * FROM questions WHERE id = ?", [question_id])
    learner = Learner(db, assessment["student_id"])
    result = grade(question, response)
    before, after = learner.observe(
        question["concept_id"], result["score"], question["type"], question["difficulty"],
        source="diagnostic" if assessment["kind"] == "diagnostic" else "quiz",
        detail={"question_id": question_id, "assessment_id": assessment_id, "misconception": result["misconception"]},
    )
    feedback = {
        **result,
        "explanation": question["explanation"],
        "citations": citations_for(db, course_id, question["unit_ids"], question["explanation"]),
        "concept_id": question["concept_id"],
        "concept": learner.concepts[question["concept_id"]]["name"],
        "mastery_before": round(before, 4), "mastery_after": round(after, 4),
    }
    db.insert("attempts", {
        "assessment_id": assessment_id, "student_id": assessment["student_id"], "question_id": question_id,
        "ts": now(), "response": {"value": response}, "score": result["score"], "feedback": feedback,
    })
    upcoming = next_question(db, assessment_id)
    out = {"next": upcoming, "done": upcoming is None}
    # An exam holds its feedback back until the paper is finished.
    out["feedback"] = feedback if assessment["kind"] != "exam" else {"recorded": True}
    if upcoming is None:
        out["report"] = finish(db, course_id, assessment_id)
    return out


def finish(db: Database, course_id: str, assessment_id: str) -> dict:
    """Build and store the post-assessment report."""
    assessment = db.one("SELECT * FROM assessments WHERE id = ?", [assessment_id])
    attempts = db.all(
        "SELECT a.*, q.concept_id, q.stem, q.type, q.difficulty FROM attempts a JOIN questions q ON q.id = a.question_id "
        "WHERE a.assessment_id = ? ORDER BY a.id", [assessment_id])
    learner = Learner(db, assessment["student_id"])
    state = learner.state()
    by_concept: dict[str, dict] = {}
    misconceptions: dict[tuple[str, str], dict] = {}
    for attempt in attempts:
        concept_id = attempt["concept_id"]
        entry = by_concept.setdefault(concept_id, {
            "concept_id": concept_id, "name": learner.concepts[concept_id]["name"], "asked": 0, "earned": 0.0,
            "mastery_before": attempt["feedback"]["mastery_before"],
        })
        entry["asked"] += 1
        entry["earned"] += attempt["score"]
        entry["mastery_after"] = round(state[concept_id].current, 4)
        entry["level"] = state[concept_id].level
        label = (attempt["feedback"].get("misconception") or "").strip()
        if label and attempt["score"] < 1:
            item = misconceptions.setdefault((concept_id, label.lower()), {
                "label": label, "concept_id": concept_id, "concept": learner.concepts[concept_id]["name"], "count": 0, "evidence": [],
            })
            item["count"] += 1
            item["evidence"].append(attempt["stem"][:140])

    weak = []
    for entry in by_concept.values():
        share = entry["earned"] / entry["asked"]
        if share < 0.6 or state[entry["concept_id"]].current < WEAK:
            blocker = learner.weakest_prerequisite(entry["concept_id"], state)
            reason = f"{entry['earned']:g} of {entry['asked']} correct; estimated mastery {state[entry['concept_id']].current:.0%}"
            weak.append({
                "concept_id": entry["concept_id"], "name": entry["name"], "why": reason,
                "blocked_by": {"concept_id": blocker, "name": learner.concepts[blocker]["name"],
                               "mastery": round(state[blocker].current, 3)} if blocker else None,
                "study": study_links(db, course_id, blocker or entry["concept_id"]),
            })
    weak.sort(key=lambda w: state[w["concept_id"]].current)

    steps = []
    for item in weak[:3]:
        if item["blocked_by"]:
            steps.append(f"Start with “{item['blocked_by']['name']}”: “{item['name']}” rests on it and it is not yet secure.")
        else:
            steps.append(f"Review “{item['name']}” from the linked sources, then take a short quiz on it.")
    if not weak:
        steps.append("No weak concepts in this sitting. Try a harder quiz or move to the next topic.")

    earned = sum(a["score"] for a in attempts)
    report = {
        "assessment_id": assessment_id, "kind": assessment["kind"],
        "score": {"earned": earned, "possible": len(attempts), "pct": round(100 * earned / max(len(attempts), 1), 1)},
        "by_concept": sorted(by_concept.values(), key=lambda e: e["earned"] / e["asked"]),
        "weak_topics": weak,
        "misconceptions": sorted(misconceptions.values(), key=lambda m: -m["count"]),
        "next_steps": steps,
        "review": [
            {"question_id": a["question_id"], "stem": a["stem"], "type": a["type"], "difficulty": a["difficulty"],
             "response": a["response"]["value"], "score": a["score"], "feedback": a["feedback"]}
            for a in attempts
        ],
    }
    db.run("UPDATE assessments SET finished = ?, report = ? WHERE id = ?",
           [now(), json.dumps(report, ensure_ascii=False), assessment_id])
    return report

"""Study schedule from the learner model: weak topics first, in prerequisite order, with
reviews placed where the forgetting curve says a concept is about to slip.

Deterministic on purpose. A plan a student has to trust should be explainable line by line,
so every item carries the reason it is there.
"""
from __future__ import annotations

import datetime as dt

from .cite import study_links
from .db import Database, now
from .learner import DAY, MASTERED, WEAK, Learner, days_until, decayed

LEARN_MINUTES = 20      # first pass over a weak or unseen concept: read/watch, then practise
PRACTICE_MINUTES = 15   # a concept that is developing
REVIEW_MINUTES = 8      # a quick recall session
REVIEW_GAPS = (2, 5)    # days after first study at which a new concept is revisited
REVIEW_BELOW = 0.60     # schedule a review before predicted mastery falls under this


def build(db: Database, course_id: str, student_id: str, days: int = 14, minutes_per_day: int = 45,
          start: float | None = None) -> dict:
    learner = Learner(db, student_id)
    start = now() if start is None else start
    state = learner.state(start)
    order = {c: i for i, c in enumerate(learner.concepts)}   # teaching order is a topological order
    days = max(2, days)
    study_days = days - 1                                     # the last day is kept for a mock exam

    tasks: list[dict] = []   # {"earliest": day, "minutes", "kind", "concept_id", "why", "priority"}
    for concept_id, concept in learner.concepts.items():
        s = state[concept_id]
        if s.n_obs == 0 or s.current < WEAK:
            why = "not assessed yet" if s.n_obs == 0 else f"weak ({s.current:.0%})"
            tasks.append({"earliest": 0, "minutes": LEARN_MINUTES, "kind": "learn", "concept_id": concept_id, "why": why,
                          "priority": (0, order[concept_id])})
        elif s.current < MASTERED:
            tasks.append({"earliest": 0, "minutes": PRACTICE_MINUTES, "kind": "practise", "concept_id": concept_id,
                          "why": f"developing ({s.current:.0%})", "priority": (1, order[concept_id])})
        else:
            # Mastered now: will it still be there on exam day?
            slips_in = days_until(s.p, s.successes, REVIEW_BELOW)
            if slips_in is not None:
                day = int(max(0.0, slips_in - (start - s.updated) / DAY))
                if day < study_days:
                    tasks.append({"earliest": max(0, day - 1), "minutes": REVIEW_MINUTES, "kind": "review", "concept_id": concept_id,
                                  "why": f"predicted to fall below {REVIEW_BELOW:.0%} in {day} days without review",
                                  "priority": (2, order[concept_id])})

    capacity = [minutes_per_day] * study_days
    plan: list[list[dict]] = [[] for _ in range(days)]
    unscheduled = []

    def place(task: dict) -> int | None:
        for day in range(min(task["earliest"], study_days - 1), study_days):
            if capacity[day] >= task["minutes"]:
                capacity[day] -= task["minutes"]
                plan[day].append(task)
                return day
        return None

    for task in sorted(tasks, key=lambda t: (t["earliest"], t["priority"])):
        day = place(task)
        if day is None:
            unscheduled.append(task)
        elif task["kind"] == "learn":
            # A newly learned concept is revisited at expanding gaps, room permitting.
            for gap in REVIEW_GAPS:
                if day + gap < study_days:
                    review = {"earliest": day + gap, "minutes": REVIEW_MINUTES, "kind": "review", "concept_id": task["concept_id"],
                              "why": f"spaced review {gap} days after first study", "priority": (2, order[task["concept_id"]])}
                    if place(review) is None:
                        unscheduled.append(review)

    weakest = sorted(learner.concepts, key=lambda c: state[c].current)[:4]
    plan[days - 1].append({"kind": "mock", "concept_id": None, "minutes": minutes_per_day,
                           "why": "full mock exam, then one more look at: " + ", ".join(learner.concepts[c]["name"] for c in weakest)})

    first_day = dt.date.fromtimestamp(start)
    out_days = []
    for index, items in enumerate(plan):
        if not items:
            continue
        out_days.append({
            "day": index + 1,
            "date": (first_day + dt.timedelta(days=index)).isoformat(),
            "minutes": sum(i["minutes"] for i in items),
            "items": [
                {"kind": i["kind"], "concept_id": i["concept_id"], "minutes": i["minutes"], "why": i["why"],
                 "name": learner.concepts[i["concept_id"]]["name"] if i["concept_id"] else "Mock exam",
                 "links": study_links(db, course_id, i["concept_id"], limit=2) if i["kind"] in ("learn", "practise") and i["concept_id"] else []}
                for i in items
            ],
        })
    exam_time = start + (days - 1) * DAY
    return {
        "days": out_days,
        "exam_date": (first_day + dt.timedelta(days=days - 1)).isoformat(),
        "minutes_per_day": minutes_per_day,
        "unscheduled": [
            {"kind": t["kind"], "name": learner.concepts[t["concept_id"]]["name"], "why": t["why"]} for t in unscheduled
        ],
        # What the forgetting curve predicts for exam day if nothing is reviewed.
        "without_review": [
            {"concept_id": c, "name": learner.concepts[c]["name"], "today": round(state[c].current, 3),
             "on_exam_day": round(decayed(state[c].p, exam_time - state[c].updated, state[c].successes), 3)}
            for c in learner.concepts if state[c].n_obs > 0
        ],
    }

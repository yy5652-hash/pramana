"""Revision material aimed at a student's weak concepts: cited flashcards.

Cards are written by a model from the concept's own source units and each card names the
unit it came from. With no model reachable, cards are drawn from the verified question bank
instead, which is already grounded and checked.
"""
from __future__ import annotations

from .assess.generate import _material_block, concept_material
from .cite import citations_for
from .config import settings
from .db import Database
from .learner import Learner
from .llm import LLMError, ReplayMiss, llm

CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "front": {"type": "string"},
                    "back": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["front", "back", "source"],
            },
        }
    },
    "required": ["cards"],
}

CARD_PROMPT = """Write {n} flashcards to help a student revise the concept "{name}" ({description}).

Use only the course material below. Each card: "front" is a short prompt (a term to define, a law to state, a quantity to relate, a quick "what happens if"), "back" is the answer in at most two sentences with maths as LaTeX between $...$, and "source" is the id (S1, S2, ...) of the excerpt the answer comes from. Cover different points; put the most important first.

Course material:
{material}
"""


def _from_bank(db: Database, course_id: str, concept: dict, n: int) -> list[dict]:
    rows = db.all(
        "SELECT * FROM questions WHERE concept_id = ? AND status = 'verified' AND type != 'numeric' ORDER BY difficulty LIMIT ?",
        [concept["id"], n])
    return [{
        "concept_id": concept["id"], "concept": concept["name"], "front": row["stem"], "back": row["answer"].get("text", ""),
        "citations": citations_for(db, course_id, row["unit_ids"][:1]), "made_by": "question bank",
    } for row in rows]


def flashcards(db: Database, course_id: str, student_id: str, per_concept: int = 3, concepts: int = 3) -> list[dict]:
    """Cards for the student's weakest assessed concepts (or the first concepts, for a new student)."""
    learner = Learner(db, student_id)
    snapshot = learner.snapshot()
    assessed = [c for c in snapshot if c["n_obs"] > 0]
    ranked = sorted(assessed, key=lambda c: c["mastery"]) if assessed else snapshot
    cards: list[dict] = []
    for entry in ranked[:concepts]:
        concept = learner.concepts[entry["concept_id"]]
        units = concept_material(db, concept["id"], limit=5)
        if not units:
            continue
        try:
            result = llm().chat(
                [{"role": "user", "content": CARD_PROMPT.format(
                    n=per_concept, name=concept["name"], description=concept["description"], material=_material_block(units))}],
                models=settings.bulk_models, namespace="flashcards", schema=CARD_SCHEMA,
            )
            for card in result.json().get("cards", [])[:per_concept]:
                token = card.get("source", "")
                position = int(token[1:]) - 1 if token[:1] == "S" and token[1:].isdigit() else 0
                unit = units[position] if 0 <= position < len(units) else units[0]
                cards.append({
                    "concept_id": concept["id"], "concept": concept["name"], "mastery": entry["mastery"],
                    "front": card["front"].strip(), "back": card["back"].strip(),
                    "citations": citations_for(db, course_id, [unit["id"]], card["back"]), "made_by": result.model,
                })
        except (LLMError, ReplayMiss):
            cards.extend({**card, "mastery": entry["mastery"]} for card in _from_bank(db, course_id, concept, per_concept))
    return cards

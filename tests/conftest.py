"""A tiny synthetic course: three concepts in a prerequisite chain and a small question bank.

The tests exercise the deterministic core (learner model, selection, grading, scheduling)
without a language model, an embedding model or any course files.
"""
from __future__ import annotations

import numpy as np
import pytest

from pramana.db import Database, now


def _vector(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=384).astype(np.float32)
    return (v / np.linalg.norm(v)).tobytes()


@pytest.fixture
def db(tmp_path) -> Database:
    database = Database(tmp_path / "kb.sqlite")
    database.insert("sources", {"id": "book", "kind": "textbook", "title": "Book", "file": "book.pdf", "licence": "", "attribution": "", "meta": {}})
    database.insert("topics", {"id": "t", "title": "Motion", "summary": "", "ord": 0})
    for order, concept in enumerate(["position", "velocity", "acceleration"]):
        database.insert("concepts", {"id": concept, "topic_id": "t", "name": concept.title(), "description": "", "ord": order})
        database.insert("units", {"id": f"book:p{order + 1}:1", "source_id": "book", "kind": "text", "modality": "text",
                                  "locator": {"page": order + 1, "rect": [0.1, 0.1, 0.9, 0.3]}, "section": concept, "text": f"About {concept}.", "asset": "book/p0001.jpg", "ord": order})
        database.insert("unit_concepts", {"unit_id": f"book:p{order + 1}:1", "concept_id": concept, "weight": 1.0})
    database.insert("prereqs", {"concept_id": "velocity", "requires_id": "position"})
    database.insert("prereqs", {"concept_id": "acceleration", "requires_id": "velocity"})
    seed = 0
    for order, concept in enumerate(["position", "velocity", "acceleration"]):
        for difficulty in (1, 2, 3, 4):
            for kind in ("mcq", "numeric"):
                seed += 1
                answer = ({"text": "B", "option": 1, "misconceptions": ["confuses speed with velocity", "", "sign error", "unit slip"]}
                          if kind == "mcq" else {"text": "10 m/s", "value": 10.0, "unit": "m/s", "formula": "v0 + a*t", "variables": {"v0": 0, "a": 2, "t": 5}, "tolerance_pct": 2.0})
                database.insert("questions", {
                    "id": f"q-{concept}-{difficulty}-{kind}", "concept_id": concept, "type": kind, "difficulty": difficulty,
                    "stem": f"A question about {concept} at level {difficulty}?", "options": ["A", "B", "C", "D"] if kind == "mcq" else None,
                    "answer": answer, "explanation": "Because.", "unit_ids": [f"book:p{order + 1}:1"], "verification": {}, "status": "verified",
                    "vec": _vector(seed), "created": now(),
                })
    database.insert("students", {"id": "s1", "name": "Test", "created": now(), "profile": {}})
    return database

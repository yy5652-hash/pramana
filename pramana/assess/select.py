"""Adaptive question selection.

The next question is chosen in two steps, both driven by the learner model:

1. **Which concept.** Each concept in scope gets a priority made of three parts: how weak it
   is (scaled down while its prerequisites are shaky, because drilling a concept a student
   is not ready for wastes their time), how little is known about it, and how close a
   previously learned concept is to being forgotten.
2. **Which item.** Among unseen items for that concept, take the one whose predicted chance
   of a correct answer is closest to 85 %, the error rate at which practice teaches fastest
   (Wilson et al., "The Eighty Five Percent Rule for optimal learning", 2019). A weak
   student therefore starts on the easiest items and climbs as the estimate rises.

A question a student has attempted is never served again, and a candidate too similar to
one they have seen (or to one already in this assessment) is skipped.
"""
from __future__ import annotations

import random

import numpy as np

from .. import embed
from ..db import Database
from ..learner import ConceptState, Learner, information, predict_correct

TARGET_SUCCESS = 0.85
SIMILAR = 0.88


# How the three reasons to ask about a concept are weighed, and how quickly a concept's
# priority fades each time it is asked within one sitting.
W_WEAK, W_UNKNOWN, W_FORGET, REPEAT_DAMP = 0.70, 0.10, 0.20, 0.75


def concept_priority(learner: Learner, state: dict[str, ConceptState], concept_id: str) -> float:
    """Expected value of a question on this concept: mostly how much is left to learn there
    *that the student is ready to learn*, plus a little for finding out and for not forgetting."""
    s = state[concept_id]
    weakness = (1 - s.current) * learner.readiness(concept_id, state)
    unknown = 1.0 / (1 + s.n_obs)
    forgetting = max(0.0, s.p - s.current)          # mastery lost to time since the last review
    return W_WEAK * weakness + W_UNKNOWN * unknown + W_FORGET * min(1.0, forgetting * 4)


class Selector:
    def __init__(self, db: Database, student_id: str, policy: str = "adaptive", seed: int | None = None):
        self.db = db
        self.student_id = student_id
        self.policy = policy   # adaptive | random  (random is the evaluation baseline)
        self.rng = random.Random(seed)
        self.learner = Learner(db, student_id)

    def _bank(self, concept_ids: list[str], types: list[str] | None) -> list[dict]:
        marks = ",".join("?" for _ in concept_ids)
        rows = self.db.all(
            f"SELECT * FROM questions WHERE status = 'verified' AND concept_id IN ({marks})", concept_ids)
        return [r for r in rows if not types or r["type"] in types]

    def _seen(self) -> tuple[set[str], np.ndarray | None]:
        attempted = self.db.all(
            "SELECT DISTINCT q.id, q.vec FROM attempts a JOIN questions q ON q.id = a.question_id WHERE a.student_id = ?",
            [self.student_id])
        vectors = [embed.from_blob(r["vec"]) for r in attempted if r["vec"]]
        return {r["id"] for r in attempted}, (np.stack(vectors) if vectors else None)

    def next_question(self, concept_ids: list[str], taken: list[str], types: list[str] | None = None,
                      at: float | None = None, informative: bool = False) -> dict | None:
        """The next question for this student within `concept_ids`, or None when the bank is exhausted.

        Practice picks the item closest to the target success rate. With `informative` (the
        diagnostic) it picks the item whose answer is expected to reveal most about mastery,
        which favours harder, hard-to-guess items over easy recall.
        """
        seen_ids, seen_vectors = self._seen()
        taken_rows = self.db.all(
            f"SELECT concept_id, vec FROM questions WHERE id IN ({','.join('?' for _ in taken)})", taken) if taken else []
        blocked = [embed.from_blob(r["vec"]) for r in taken_rows if r["vec"]]
        if seen_vectors is not None:
            blocked.extend(seen_vectors)
        blocked_matrix = np.stack(blocked) if blocked else None

        def fresh(question: dict) -> bool:
            if question["id"] in seen_ids or question["id"] in taken:
                return False
            if blocked_matrix is not None and question["vec"]:
                return float(np.max(blocked_matrix @ embed.from_blob(question["vec"]))) < SIMILAR
            return True

        candidates = [q for q in self._bank(concept_ids, types) if fresh(q)]
        if not candidates:
            return None
        if self.policy == "random":
            return self.rng.choice(candidates)

        state = self.learner.state(at)
        asked_here: dict[str, int] = {}
        for row in taken_rows:
            asked_here[row["concept_id"]] = asked_here.get(row["concept_id"], 0) + 1
        by_concept: dict[str, list[dict]] = {}
        for question in candidates:
            by_concept.setdefault(question["concept_id"], []).append(question)
        # Spread the sitting a little: each time a concept is asked, its priority fades.
        concept = max(by_concept, key=lambda c: concept_priority(self.learner, state, c) * REPEAT_DAMP ** asked_here.get(c, 0))
        mastery = state[concept].current
        if informative:
            return max(by_concept[concept], key=lambda q: (information(mastery, q["type"], q["difficulty"]), q["id"]))
        return min(
            by_concept[concept],
            key=lambda q: (abs(predict_correct(mastery, q["type"], q["difficulty"]) - TARGET_SUCCESS), q["id"]),
        )

    def diagnostic_question(self, taken: list[str], at: float | None = None) -> dict | None:
        """Cold start: ask about the concept whose answer says most about the rest of the map.

        A concept is worth asking about when the belief in it is uncertain and when it has
        many neighbours in the prerequisite graph, because its answer moves them too: a miss
        caps everything built on it, a hit lifts what it rests on.
        """
        state = self.learner.state(at)
        taken_concepts = {r["concept_id"] for r in self.db.all(
            f"SELECT concept_id FROM questions WHERE id IN ({','.join('?' for _ in taken)})", taken)} if taken else set()

        def value(concept_id: str) -> float:
            uncertainty = 1 - abs(2 * state[concept_id].current - 1)
            reach = len(self.learner._descendants(concept_id)) + len(self.learner.requires[concept_id])
            return uncertainty * (1 + 0.15 * reach) * (0.25 if concept_id in taken_concepts else 1.0)

        for concept_id in sorted(self.learner.concepts, key=value, reverse=True):
            question = self.next_question([concept_id], taken, types=["mcq", "numeric"], at=at, informative=True)
            if question:
                return question
        return None

    def exam(self, concept_ids: list[str], n: int, types: list[str] | None = None) -> list[dict]:
        """A fixed mock exam: even coverage of the scope and a spread of difficulty, no repeats."""
        picked: list[dict] = []
        while len(picked) < n:
            seen_ids, _ = self._seen()
            taken = [q["id"] for q in picked]
            pool = [q for q in self._bank(concept_ids, types) if q["id"] not in seen_ids and q["id"] not in taken]
            if not pool:
                break
            counts = {c: sum(1 for q in picked if q["concept_id"] == c) for c in concept_ids}
            least = min(counts[q["concept_id"]] for q in pool)
            tier = [q for q in pool if counts[q["concept_id"]] == least]
            wanted = 1 + len(picked) % 4       # cycle difficulty 1..4 across the paper
            picked.append(min(tier, key=lambda q: (abs(q["difficulty"] - wanted), self.rng.random())))
        return picked

"""Learner model: per-concept mastery that moves with every answer and every conversation.

The model is Bayesian Knowledge Tracing with three additions that the course map makes
possible:

* **Item-aware slip and guess.** A four-option MCQ can be guessed a quarter of the time, a
  numerical answer almost never; an easy item can be answered from partial knowledge, a hard
  one cannot; a hard item is slipped on more often. So a right answer to a hard numerical
  problem moves mastery much further than a right answer to an easy recall MCQ. This is the
  IRT idea expressed through BKT's two emission parameters.
* **Forgetting.** Mastery decays towards a floor with a time constant that grows with each
  successful recall (the spaced-repetition effect). The decayed value is what the tutor, the
  question selector and the study schedule all read.
* **Prerequisite structure.** Evidence flows along the map: success on a concept is weak
  evidence for its prerequisites, and an unobserved concept cannot be believed much stronger
  than the prerequisites it rests on.

Every update is logged in `evidence` with the belief before and after, so the dashboard can
show why a number is what it is.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .db import Database, now

PRIOR = 0.25            # belief in mastery before any evidence
LEARN = 0.15            # chance an attempt with feedback turns "not yet" into "mastered"
FLOOR = 0.10            # where a never-reviewed concept decays to
TAU_DAYS = 7.0          # forgetting time constant after the first exposure
TAU_GROWTH = 0.7        # each successful recall lengthens it by this fraction
PREREQ_SHARE = 0.50     # how far a success pulls direct prerequisites towards the belief it earned
PREREQ_HEADROOM = 0.15  # an unobserved concept may sit this far above its weakest prerequisite
READY_AT = 0.80         # belief in a prerequisite at which it stops holding a concept back
READY_POWER = 2         # how steeply a weaker prerequisite holds it back
MASTERED = 0.80
WEAK = 0.50
CHANCE = {"mcq": 0.25, "short": 0.05, "numeric": 0.03, "chat": 0.20}   # right by luck alone
# A student who has not mastered a concept still gets its easy items right fairly often:
# recalling a definition does not take mastery. Share of non-masters who can do an item:
PARTIAL = {1: 0.35, 2: 0.20, 3: 0.10, 4: 0.03, 5: 0.0}
DAY = 86400.0


def guess(question_type: str, difficulty: int) -> float:
    """Chance of a right answer without mastery: luck, plus partial knowledge on easy items."""
    chance = CHANCE.get(question_type, 0.1)
    return chance + (1 - chance) * PARTIAL[max(1, min(5, difficulty))]


def slip(difficulty: int) -> float:
    """Chance of a wrong answer despite mastery: 10 % on the easiest items, 26 % on the hardest."""
    return 0.10 + 0.04 * (max(1, min(5, difficulty)) - 1)


def posterior(p: float, score: float, guess: float, slip_rate: float) -> float:
    """Bayes update of P(mastered) on an answer scored in [0, 1] (partial credit is soft evidence)."""
    right = p * (1 - slip_rate) / (p * (1 - slip_rate) + (1 - p) * guess)
    wrong = p * slip_rate / (p * slip_rate + (1 - p) * (1 - guess))
    return score * right + (1 - score) * wrong


def predict_correct(p: float, question_type: str, difficulty: int) -> float:
    """Probability this student answers this kind of item correctly."""
    return p * (1 - slip(difficulty)) + (1 - p) * guess(question_type, difficulty)


def information(p: float, question_type: str, difficulty: int) -> float:
    """Bits an answer to this kind of item is expected to reveal about mastery (mutual information)."""
    def entropy(x: float) -> float:
        return 0.0 if x <= 0 or x >= 1 else -(x * math.log2(x) + (1 - x) * math.log2(1 - x))

    g, s = guess(question_type, difficulty), slip(difficulty)
    return entropy(p * (1 - s) + (1 - p) * g) - (p * entropy(s) + (1 - p) * entropy(g))


def retention(elapsed_seconds: float, successes: int) -> float:
    """Share of mastery kept after a gap; each successful recall lengthens the time constant."""
    tau = TAU_DAYS * DAY * (1 + TAU_GROWTH * successes)
    return math.exp(-max(elapsed_seconds, 0.0) / tau)


def decayed(p: float, elapsed_seconds: float, successes: int) -> float:
    r = retention(elapsed_seconds, successes)
    floor = min(p, FLOOR)
    return floor + (p - floor) * r


def days_until(p: float, successes: int, threshold: float) -> float | None:
    """Days from the last update until decayed mastery crosses `threshold` (None if already below)."""
    floor = min(p, FLOOR)
    if p <= threshold or threshold <= floor:
        return None
    tau_days = TAU_DAYS * (1 + TAU_GROWTH * successes)
    return -tau_days * math.log((threshold - floor) / (p - floor))


@dataclass
class ConceptState:
    concept_id: str
    p: float            # stored belief at `updated`
    n_obs: int
    successes: int
    updated: float
    current: float      # belief now, after forgetting

    @property
    def level(self) -> str:
        if self.n_obs == 0:
            return "unknown"
        if self.current >= MASTERED:
            return "mastered"
        return "developing" if self.current >= WEAK else "weak"


class Learner:
    """Reads and updates one student's state in a course database."""

    def __init__(self, db: Database, student_id: str):
        self.db = db
        self.student_id = student_id
        self.concepts = {c["id"]: c for c in db.all("SELECT * FROM concepts ORDER BY ord")}
        self.requires: dict[str, list[str]] = {c: [] for c in self.concepts}
        self.unlocks: dict[str, list[str]] = {c: [] for c in self.concepts}
        for edge in db.all("SELECT * FROM prereqs"):
            if edge["concept_id"] in self.concepts and edge["requires_id"] in self.concepts:
                self.requires[edge["concept_id"]].append(edge["requires_id"])
                self.unlocks[edge["requires_id"]].append(edge["concept_id"])

    # ---- reading -------------------------------------------------------------------------

    def state(self, at: float | None = None) -> dict[str, ConceptState]:
        at = now() if at is None else at
        rows = {r["concept_id"]: r for r in self.db.all("SELECT * FROM mastery WHERE student_id = ?", [self.student_id])}
        wins = {
            r["concept_id"]: r["n"]
            for r in self.db.all(
                "SELECT concept_id, COUNT(*) AS n FROM evidence WHERE student_id = ? AND correct >= 0.99 "
                "AND source != 'inferred' GROUP BY concept_id", [self.student_id])
        }
        out = {}
        for concept_id in self.concepts:
            row = rows.get(concept_id)
            if row is None:
                out[concept_id] = ConceptState(concept_id, PRIOR, 0, 0, at, PRIOR)
            else:
                successes = wins.get(concept_id, 0)
                out[concept_id] = ConceptState(
                    concept_id, row["p"], row["n_obs"], successes, row["updated"],
                    decayed(row["p"], at - row["updated"], successes),
                )
        return out

    def readiness(self, concept_id: str, state: dict[str, ConceptState]) -> float:
        """How ready the student is to learn this concept: 1.0 when every direct prerequisite
        is mastered, falling steeply as they weaken. A belief of 0.5 in a prerequisite is a
        coin flip, not a foundation, so half-known prerequisites count for little."""
        value = 1.0
        for required in self.requires[concept_id]:
            value *= min(1.0, max(0.15, state[required].current / READY_AT)) ** READY_POWER
        return value

    def weakest_prerequisite(self, concept_id: str, state: dict[str, ConceptState]) -> str | None:
        """The shakiest concept this one rests on, searched through the whole chain.

        Only concepts with real evidence count. A student nobody has assessed yet is not
        "weak on everything", and the tutor should not open every answer with a recap.
        """
        seen, stack, worst = set(), list(self.requires[concept_id]), None
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            observed = state[current].n_obs > 0
            if observed and state[current].current < WEAK and (worst is None or state[current].current < state[worst].current):
                worst = current
            stack.extend(self.requires[current])
        return worst

    # ---- updating ------------------------------------------------------------------------

    def _write(self, concept_id: str, p: float, n_obs: int, at: float) -> None:
        self.db.insert("mastery", {
            "student_id": self.student_id, "concept_id": concept_id,
            "p": min(0.995, max(0.005, p)), "n_obs": n_obs, "updated": at,
        }, replace=True)

    def _log(self, concept_id: str, at: float, source: str, score: float, before: float, after: float, detail: dict) -> None:
        self.db.insert("evidence", {
            "student_id": self.student_id, "concept_id": concept_id, "ts": at, "source": source,
            "correct": score, "p_before": before, "p_after": after, "detail": detail,
        })

    def observe(
        self,
        concept_id: str,
        score: float,
        question_type: str = "mcq",
        difficulty: int = 2,
        source: str = "quiz",
        weight: float = 1.0,
        detail: dict | None = None,
        at: float | None = None,
    ) -> tuple[float, float]:
        """Fold one piece of evidence into the model. Returns (belief before, belief after).

        `weight` below 1 blends the update with the prior belief; conversation signals use it
        because a remark in chat is weaker evidence than a graded answer.
        """
        if concept_id not in self.concepts:
            return (PRIOR, PRIOR)
        at = now() if at is None else at
        state = self.state(at)
        current = state[concept_id]
        before = current.current
        detail = dict(detail or {})
        if source in ("quiz", "diagnostic"):
            detail["predicted"] = round(predict_correct(before, question_type, difficulty), 4)
        updated = posterior(before, score, guess(question_type, difficulty), slip(difficulty))
        # The learning step: an attempt followed by feedback teaches something whatever the
        # score. Classic BKT adds it unconditionally, which lets a wrong answer *raise* a low
        # estimate; here a wrong answer may hold belief where it was but never lifts it.
        # The diagnostic is a measurement, so it assumes no learning at all.
        step = {"quiz": LEARN, "chat": LEARN / 2}.get(source, 0.0)
        learned = updated + (1 - updated) * step
        updated = learned if score > 0 else min(before, learned)
        after = before + weight * (updated - before)
        self._write(concept_id, after, current.n_obs + 1, at)
        self._log(concept_id, at, source, score, before, after, {"type": question_type, "difficulty": difficulty, **detail})

        if score >= 0.99 and weight >= 0.5:
            # Getting this right is evidence that what it rests on is in place too: strongest
            # for direct prerequisites, halving with each further step down the chain.
            for required, distance in self._ancestors(concept_id).items():
                base = state[required]
                share = PREREQ_SHARE * 0.5 ** (distance - 1)
                lifted = base.current + share * max(0.0, after - base.current)   # pulled towards the belief just earned
                if lifted > base.current + 0.02:
                    self._write(required, lifted, base.n_obs, at)
                    self._log(required, at, "inferred", 1.0, base.current, lifted, {"from": concept_id})
        if score <= 0.01 and weight >= 0.5:
            # An unobserved concept cannot be believed much stronger than a prerequisite just failed.
            for dependant in self._descendants(concept_id):
                base = state[dependant]
                ceiling = after + PREREQ_HEADROOM
                if base.n_obs == 0 and base.current > ceiling + 0.02:   # ignore changes too small to matter
                    self._write(dependant, ceiling, 0, at)
                    self._log(dependant, at, "inferred", 0.0, base.current, ceiling, {"from": concept_id})
        return before, after

    def _ancestors(self, concept_id: str) -> dict[str, int]:
        """Every concept this one rests on, with its distance in prerequisite steps."""
        found: dict[str, int] = {}
        frontier = [(r, 1) for r in self.requires[concept_id]]
        while frontier:
            current, distance = frontier.pop(0)
            if current not in found:
                found[current] = distance
                frontier.extend((r, distance + 1) for r in self.requires[current])
        return found

    def _descendants(self, concept_id: str) -> list[str]:
        seen, stack = [], list(self.unlocks[concept_id])
        while stack:
            current = stack.pop()
            if current not in seen:
                seen.append(current)
                stack.extend(self.unlocks[current])
        return seen

    # ---- summaries -----------------------------------------------------------------------

    def snapshot(self, at: float | None = None) -> list[dict]:
        """Everything the dashboard needs about each concept."""
        at = now() if at is None else at
        state = self.state(at)
        out = []
        for concept_id, concept in self.concepts.items():
            s = state[concept_id]
            due_in = days_until(s.p, s.successes, 0.6)
            out.append({
                "concept_id": concept_id,
                "name": concept["name"],
                "topic_id": concept["topic_id"],
                "mastery": round(s.current, 4),
                "stored": round(s.p, 4),
                "level": s.level,
                "n_obs": s.n_obs,
                "successes": s.successes,
                "readiness": round(self.readiness(concept_id, state), 3),
                "requires": self.requires[concept_id],
                "review_in_days": None if due_in is None else round(due_in - (at - s.updated) / DAY, 2),
                "blocked_by": self.weakest_prerequisite(concept_id, state),
            })
        return out

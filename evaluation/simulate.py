"""Simulated students: does adapting help, and does the learner model track the truth?

Each simulated student has a hidden proficiency per concept. They work through the real
question bank over several daily sessions under one of three policies, using the same
selector and learner-model code the app runs:

* adaptive    the app's policy: a diagnostic first, then prerequisite-aware selection
* random      unseen questions drawn uniformly from the bank
* sequential  concepts in syllabus order, one question each, round and round

The simulator's response model is deliberately NOT the learner model's own (BKT), so the
estimator is not graded on its own assumptions: answers come from a logistic item-response
curve in a continuous proficiency.

Two modelling assumptions favour any prerequisite-aware, difficulty-matched policy: a
student learns less from a question whose prerequisites they lack, and less from one far
too easy or far too hard. Both are standard, but they are assumptions, so every result is
also reported for a "flat" learner where both are switched off.

    python -m evaluation.simulate --course mechanics --students 40

No language model is called. Results: evaluation/results/simulation.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import statistics
from pathlib import Path

import numpy as np

from pramana import embed
from pramana.assess.select import Selector
from pramana.config import ROOT, settings
from pramana.db import Database, new_id
from pramana.learner import DAY, PRIOR, Learner, predict_correct

SESSIONS = 7
PER_SESSION = 8
DIFFICULTY_LOCATION = {1: 0.15, 2: 0.30, 3: 0.45, 4: 0.60, 5: 0.75}   # proficiency at which an item is 50:50
TRUE_GUESS = {"mcq": 0.25, "short": 0.02, "numeric": 0.01}
TRUE_SLIP = 0.05
T0 = 1_800_000_000.0   # a fixed epoch so runs are reproducible


def profiles(concepts: list[dict]) -> dict[str, dict]:
    """Starting proficiency per concept, learning rate, and forgetting time constant (days)."""
    n = len(concepts)
    early = {c["id"] for c in concepts[: n // 2]}
    return {
        "novice": {"theta": {c["id"]: 0.12 for c in concepts}, "rate": 0.22, "tau": 9.0},
        "strong start, weak finish": {"theta": {c["id"]: 0.75 if c["id"] in early else 0.15 for c in concepts}, "rate": 0.22, "tau": 9.0},
        "prerequisite gap": {"theta": {c["id"]: 0.15 if c["id"] in early else 0.50 for c in concepts}, "rate": 0.22, "tau": 9.0},
        "advanced": {"theta": {c["id"]: 0.72 for c in concepts}, "rate": 0.22, "tau": 9.0},
        "fast learner": {"theta": {c["id"]: 0.20 for c in concepts}, "rate": 0.40, "tau": 9.0},
        "forgetful": {"theta": {c["id"]: 0.30 for c in concepts}, "rate": 0.25, "tau": 3.0},
    }


def p_true(theta: float, question: dict) -> float:
    guess = TRUE_GUESS[question["type"]]
    curve = 1 / (1 + math.exp(-6 * (theta - DIFFICULTY_LOCATION[question["difficulty"]])))
    return guess + (1 - guess - TRUE_SLIP) * curve


def learn(theta: dict[str, float], question: dict, requires: dict[str, list[str]], rate: float, flat: bool) -> None:
    concept = question["concept_id"]
    gain = rate * (1 - theta[concept])
    if not flat:
        ready = 1.0
        for required in requires[concept]:
            ready *= max(0.2, min(1.0, theta[required] / 0.5))
        reach = math.exp(-(((DIFFICULTY_LOCATION[question["difficulty"]] - theta[concept]) / 0.35) ** 2))
        gain *= ready * (0.35 + 0.65 * reach)
    theta[concept] = min(0.98, theta[concept] + gain)


def auc(scores: list[float], labels: list[int]) -> float | None:
    positives = [s for s, l in zip(scores, labels) if l]
    negatives = [s for s, l in zip(scores, labels) if not l]
    if not positives or not negatives:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


def spearman(a: list[float], b: list[float]) -> float:
    def ranks(values: list[float]) -> np.ndarray:
        order = np.argsort(values)
        out = np.empty(len(values))
        out[order] = np.arange(len(values))
        return out
    ra, rb = ranks(a), ranks(b)
    if np.std(ra) == 0 or np.std(rb) == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def run_student(db: Database, profile: dict, policy: str, seed: int, flat: bool) -> dict:
    rng = random.Random(seed)
    student_id = new_id("sim")
    db.insert("students", {"id": student_id, "name": f"sim-{policy}-{seed}", "created": T0, "profile": {"simulated": True}})
    learner = Learner(db, student_id)
    selector = Selector(db, student_id, policy="random" if policy == "random" else "adaptive", seed=seed)
    concept_ids = list(learner.concepts)
    bank_by_concept: dict[str, list[dict]] = {}
    for row in db.all("SELECT * FROM questions WHERE status = 'verified'"):
        bank_by_concept.setdefault(row["concept_id"], []).append(row)
    theta = dict(profile["theta"])
    start = dict(theta)
    floor = {c: 0.6 * v for c, v in start.items()}
    clock = T0
    served: list[dict] = []
    sessions = []
    cursor = 0
    for session in range(SESSIONS):
        taken: list[str] = []
        predictions, outcomes = [], []
        for _ in range(PER_SESSION):
            if policy == "adaptive":
                question = selector.diagnostic_question(taken, at=clock) if session == 0 else selector.next_question(concept_ids, taken, at=clock)
            elif policy == "random":
                question = selector.next_question(concept_ids, taken, at=clock)
            else:  # sequential: the next concept in syllabus order, its easiest unseen question. No learner model.
                question = None
                seen = {q["id"] for q in served}
                for _ in range(len(concept_ids)):
                    concept = concept_ids[cursor % len(concept_ids)]
                    cursor += 1
                    unseen = [q for q in bank_by_concept.get(concept, []) if q["id"] not in seen]
                    if unseen:
                        question = min(unseen, key=lambda q: (q["difficulty"], q["id"]))
                        break
            if question is None:
                break
            concept = question["concept_id"]
            state = learner.state(clock)
            predictions.append(predict_correct(state[concept].current, question["type"], question["difficulty"]))
            correct = rng.random() < p_true(theta[concept], question)
            outcomes.append(int(correct))
            learner.observe(concept, 1.0 if correct else 0.0, question["type"], question["difficulty"],
                            source="diagnostic" if policy == "adaptive" and session == 0 else "quiz", at=clock)
            db.insert("attempts", {"assessment_id": None, "student_id": student_id, "question_id": question["id"], "ts": clock,
                                   "response": {"value": None}, "score": 1.0 if correct else 0.0, "feedback": {}})
            learn(theta, question, learner.requires, profile["rate"], flat)
            taken.append(question["id"])
            served.append(question)
            clock += 90
        state = learner.state(clock)
        estimate = [state[c].current for c in concept_ids]
        truth = [theta[c] for c in concept_ids]
        weakest_true = set(sorted(concept_ids, key=lambda c: theta[c])[:5])
        weakest_est = set(sorted(concept_ids, key=lambda c: state[c].current)[:5])
        probe = {"type": "numeric", "difficulty": 3}
        errors = [abs(predict_correct(state[c].current, "numeric", 3) - p_true(theta[c], probe)) for c in concept_ids]
        prior_errors = [abs(predict_correct(PRIOR, "numeric", 3) - p_true(theta[c], probe)) for c in concept_ids]
        sessions.append({
            "probe_error": statistics.fmean(errors),
            "probe_error_prior": statistics.fmean(prior_errors),
            "true_mean": statistics.fmean(truth),
            "mastered_share": sum(t >= 0.7 for t in truth) / len(truth),
            "spearman": spearman(estimate, truth),
            "weakest5_overlap": len(weakest_true & weakest_est) / 5,
            "predictions": predictions, "outcomes": outcomes,
        })
        clock += DAY
        for concept in concept_ids:  # a day passes
            theta[concept] = floor[concept] + (theta[concept] - floor[concept]) * math.exp(-1.0 / profile["tau"])

    ids = [q["id"] for q in served]
    vectors = np.stack([embed.from_blob(q["vec"]) for q in served]) if served else np.zeros((0, 384))
    similarity = vectors @ vectors.T - np.eye(len(served)) if len(served) else np.zeros((0, 0))
    return {
        "start_mean": statistics.fmean(start.values()),
        "exam_mean": statistics.fmean(theta.values()),          # one day after the last session
        "sessions": sessions,
        "served": len(ids),
        "exact_repeats": len(ids) - len(set(ids)),
        "near_duplicates": int((np.triu(similarity, 1) >= 0.88).sum()) if len(served) else 0,
    }


def mean_ci(values: list[float]) -> dict:
    mean = statistics.fmean(values)
    half = 1.96 * statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {"mean": round(mean, 4), "ci95": round(half, 4), "n": len(values)}


def simulate(course_id: str, students: int, seed: int = 7) -> dict:
    scratch = settings.data_dir / "work" / "simulation.sqlite"
    scratch.parent.mkdir(parents=True, exist_ok=True)
    # A consistent snapshot of the course, taken with SQLite's backup API; the real database is not touched.
    scratch.unlink(missing_ok=True)
    source = sqlite3.connect(settings.course_db(course_id))
    target = sqlite3.connect(scratch)
    source.backup(target)
    source.close()
    target.close()
    db = Database(scratch)
    db.run("PRAGMA synchronous=OFF")
    for table in ("attempts", "evidence", "mastery", "assessments", "messages", "students"):
        db.run(f"DELETE FROM {table}")
    concepts = db.all("SELECT * FROM concepts ORDER BY ord")
    bank = db.one("SELECT COUNT(*) AS n FROM questions WHERE status = 'verified'")["n"]
    results: dict = {
        "course": course_id, "concepts": len(concepts), "bank": bank, "students_per_cell": students,
        "sessions": SESSIONS, "questions_per_session": PER_SESSION, "learners": {},
    }
    for flat in (False, True):
        cells = {}
        for profile_name, profile in profiles(concepts).items():
            for policy in ("adaptive", "random", "sequential"):
                runs = [run_student(db, profile, policy, seed * 1000 + i, flat) for i in range(students)]
                gains = [r["exam_mean"] - r["start_mean"] for r in runs]
                per_session = []
                for s in range(SESSIONS):
                    rows = [r["sessions"][s] for r in runs if len(r["sessions"]) > s]
                    scores = [p for row in rows for p in row["predictions"]]
                    labels = [o for row in rows for o in row["outcomes"]]
                    per_session.append({
                        "true_mean": mean_ci([row["true_mean"] for row in rows]),
                        "mastered_share": mean_ci([row["mastered_share"] for row in rows]),
                        "spearman": mean_ci([row["spearman"] for row in rows]),
                        "probe_error": mean_ci([row["probe_error"] for row in rows]),
                        "probe_error_prior": mean_ci([row["probe_error_prior"] for row in rows]),
                        "weakest5_overlap": mean_ci([row["weakest5_overlap"] for row in rows]),
                        "auc": None if auc(scores, labels) is None else round(auc(scores, labels), 4),
                        "brier": round(statistics.fmean((p - l) ** 2 for p, l in zip(scores, labels)), 4) if scores else None,
                    })
                served = sum(r["served"] for r in runs)
                cells[f"{profile_name}|{policy}"] = {
                    "profile": profile_name, "policy": policy, "gain": mean_ci(gains),
                    "start_mean": round(statistics.fmean(r["start_mean"] for r in runs), 4),
                    "exam_mean": mean_ci([r["exam_mean"] for r in runs]),
                    "per_session": per_session, "served": served,
                    "exact_repeat_rate": round(sum(r["exact_repeats"] for r in runs) / max(served, 1), 5),
                    "near_duplicate_pairs": sum(r["near_duplicates"] for r in runs),
                }
                print(f"{'flat' if flat else 'structured':10s} {profile_name:26s} {policy:10s} gain {cells[f'{profile_name}|{policy}']['gain']}", flush=True)
        # Pool over profiles: one number per policy.
        summary = {}
        for policy in ("adaptive", "random", "sequential"):
            own = [c for c in cells.values() if c["policy"] == policy]
            summary[policy] = {
                "gain": round(statistics.fmean(c["gain"]["mean"] for c in own), 4),
                "exact_repeat_rate": round(statistics.fmean(c["exact_repeat_rate"] for c in own), 5),
                "auc_first_session": round(statistics.fmean(c["per_session"][0]["auc"] or 0.5 for c in own), 4),
                "auc_last_session": round(statistics.fmean(c["per_session"][-1]["auc"] or 0.5 for c in own), 4),
                "spearman_first_session": round(statistics.fmean(c["per_session"][0]["spearman"]["mean"] for c in own), 4),
                "spearman_last_session": round(statistics.fmean(c["per_session"][-1]["spearman"]["mean"] for c in own), 4),
                "weakest5_last_session": round(statistics.fmean(c["per_session"][-1]["weakest5_overlap"]["mean"] for c in own), 4),
                "probe_error_first_session": round(statistics.fmean(c["per_session"][0]["probe_error"]["mean"] for c in own), 4),
                "probe_error_last_session": round(statistics.fmean(c["per_session"][-1]["probe_error"]["mean"] for c in own), 4),
                "probe_error_without_model": round(statistics.fmean(c["per_session"][-1]["probe_error_prior"]["mean"] for c in own), 4),
            }
        results["learners"]["flat" if flat else "structured"] = {"cells": cells, "summary": summary}
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", default="mechanics")
    parser.add_argument("--students", type=int, default=40, help="simulated students per profile and policy")
    args = parser.parse_args()
    results = simulate(args.course, args.students)
    out = ROOT / "evaluation" / "results" / "simulation.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"wrote {out}")
    for kind, block in results["learners"].items():
        print(kind, json.dumps(block["summary"], indent=1))


if __name__ == "__main__":
    main()

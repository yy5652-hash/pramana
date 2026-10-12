"""Question generation and verification.

A question enters the bank only after it survives four independent checks:

1. **Structure**: the right fields for its type, four distinct options, a valid key.
2. **Grounding**: every cited source unit exists and belongs to the concept's material.
3. **Arithmetic** (numerical items): the answer is recomputed from the item's own formula and
   givens by a whitelist evaluator. A key the arithmetic does not reproduce is rejected.
4. **Blind cross-model solve**: a *different* model, shown only the source excerpt and the
   stem, answers the question without the key. MCQs must match the keyed option, numerical
   answers must agree within tolerance, and for short answers the second model must judge
   the reference answer correct and supported. It also flags ambiguous stems.

Finally a novelty check rejects near-duplicates of anything already in the bank. Each
question keeps the record of its checks in `verification`.
"""
from __future__ import annotations

import hashlib
import random
from typing import Callable

import numpy as np

from .. import embed
from ..config import settings
from ..db import Database, now
from ..llm import LLMError, llm
from . import numeric

QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["mcq", "short", "numeric"]},
                    "difficulty": {"type": "integer"},
                    "stem": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "correct_option": {"type": "integer"},
                    "misconceptions": {"type": "array", "items": {"type": "string"}},
                    "answer": {"type": "string"},
                    "key_points": {"type": "array", "items": {"type": "string"}},
                    "formula": {"type": "string"},
                    "variables": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}, "value": {"type": "number"}},
                            "required": ["name", "value"],
                        },
                    },
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                    "explanation": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                },
                # Every field is required so a model cannot silently drop one; fields that do
                # not apply to a question's type are returned empty (see the prompt).
                "required": ["type", "difficulty", "stem", "options", "correct_option", "misconceptions", "answer",
                             "key_points", "formula", "variables", "value", "unit", "explanation", "sources"],
            },
        }
    },
    "required": ["questions"],
}

GENERATE_PROMPT = """You write assessment questions for a course. Use ONLY the course material below; a student who studied these excerpts must be able to answer, and nothing outside them may be needed (ordinary arithmetic aside).

Concept being assessed: {name} — {description}

Write exactly these questions:
{blueprint}

Difficulty scale: 1 recall a definition or fact; 2 explain or recognise in a new wording; 3 apply in a one-step situation; 4 apply in a multi-step situation; 5 combine with another idea or analyse an unfamiliar case.

Field rules:
- "sources": the ids (e.g. S2) of the excerpts the question and its answer rest on. At least one.
- "explanation": the worked reasoning, two to four sentences, written for a student who got it wrong.
- mcq: "options" has exactly 4 entries, one correct; "correct_option" is its 0-based index (vary its position). "misconceptions" has 4 entries aligned with the options: for each wrong option, the specific mistaken belief that leads a student to pick it (a short phrase, e.g. "treats velocity and acceleration as the same thing"); empty string for the correct option. Wrong options must be plausible and clearly wrong. "answer" repeats the correct option's text.
- short: "answer" is a model answer in one or two sentences; "key_points" lists the 2-3 facts a correct answer must contain.
- numeric: a calculation with a single numerical result. "variables" lists every given quantity (name and value in SI units, names usable in a formula such as v0, a, t, m, mu); "formula" is one arithmetic expression over those names that produces the answer (operators + - * / **, functions sqrt sin cos tan atan radians degrees, constants pi and g = 9.8); "value" is the result; "unit" its unit; "answer" states the result in words. Use numbers different from any worked example in the material.
- Fields that do not apply to a question's type must still be present, empty: "options", "misconceptions", "key_points" and "variables" as [], "correct_option" as -1, "formula" and "unit" as "", "value" as 0.
- Write maths as LaTeX between $...$. Do not mention "the excerpt", "the source" or "the text" in a stem; a stem must stand alone.
{avoid}
Course material:
{material}
"""

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "integer"},
                    "option": {"type": "integer"},
                    "value": {"type": "number"},
                    "reference_correct": {"type": "boolean"},
                    "answerable_from_material": {"type": "boolean"},
                    "ambiguous": {"type": "boolean"},
                    "note": {"type": "string"},
                },
                "required": ["question", "option", "value", "reference_correct", "answerable_from_material", "ambiguous", "note"],
            },
        }
    },
    "required": ["results"],
}

VERIFY_PROMPT = """You are checking exam questions before students see them. Work each one independently and carefully, using the course material below.

For every question return:
- "question": its number.
- mcq: "option" = the 0-based index of the option you judge correct. You are not told the intended key.
- numeric: "value" = your own computed result in the requested unit. You are not told the intended value.
- short: a reference answer is shown; "reference_correct" = true only if it is correct and supported by the material.
- Fields that do not apply to a question's type are still returned: "option" as -1, "value" as 0, "reference_correct" as true.
- "answerable_from_material": false if answering needs facts the material does not contain.
- "ambiguous": true if the stem is unclear, has more than one defensible answer, or (mcq) more than one option is correct or none is.
- "note": one short sentence when you flag a problem, otherwise empty.

Course material:
{material}

Questions:
{questions}
"""


def blueprint_for(quantitative: bool) -> list[tuple[str, int]]:
    """(type, difficulty) for one generation call. Qualitative concepts get no forced calculation."""
    if quantitative:
        return [("mcq", 1), ("mcq", 2), ("mcq", 3), ("short", 2), ("numeric", 3), ("numeric", 4)]
    return [("mcq", 1), ("mcq", 2), ("mcq", 3), ("mcq", 4), ("short", 2), ("short", 3)]


def concept_material(db: Database, concept_id: str, limit: int = 7, seed: int = 0) -> list[dict]:
    """Source units for a concept, mixing textbook, slides and video, strongest tags first."""
    rows = db.all(
        "SELECT u.*, uc.weight FROM units u JOIN unit_concepts uc ON uc.unit_id = u.id "
        "WHERE uc.concept_id = ? ORDER BY uc.weight DESC, u.source_id, u.ord", [concept_id])
    rng = random.Random(f"{concept_id}:{seed}")
    by_kind: dict[str, list[dict]] = {}
    for row in rows:
        by_kind.setdefault(row["kind"], []).append(row)
    for group in by_kind.values():
        primary = [u for u in group if u["weight"] >= 1.0]
        secondary = [u for u in group if u["weight"] < 1.0]
        rng.shuffle(primary)
        rng.shuffle(secondary)
        group[:] = primary + secondary
    # Round-robin over kinds so no single modality supplies every question's evidence.
    picked: list[dict] = []
    order = [k for k in ("text", "slide", "figure", "transcript", "frame") if k in by_kind]
    quota = {"text": 4, "slide": 2, "figure": 1, "transcript": 1, "frame": 1}
    while len(picked) < limit and any(by_kind[k] for k in order):
        for kind in order:
            if by_kind[kind] and quota.get(kind, 1) > 0 and len(picked) < limit:
                picked.append(by_kind[kind].pop(0))
                quota[kind] -= 1
        if all(quota.get(k, 0) <= 0 or not by_kind[k] for k in order):
            break
    return picked


def _material_block(units: list[dict]) -> str:
    return "\n\n".join(f"[S{i}] ({u['kind']}, {u['section'] or ''})\n{u['text'][:1800]}" for i, u in enumerate(units, 1))


def _looks_quantitative(units: list[dict]) -> bool:
    text = " ".join(u["text"] for u in units)
    return text.count("$") >= 12 and any(token in text for token in ("\\frac", "=", "m/s"))


def generate(db: Database, concept: dict, seed: int = 0, avoid_stems: list[str] | None = None,
             blueprint: list[tuple[str, int]] | None = None) -> tuple[list[dict], list[dict], str]:
    """Ask the generator for questions on one concept. Returns (raw questions, source units, model)."""
    units = concept_material(db, concept["id"], seed=seed)
    if not units:
        return [], [], ""
    blueprint = blueprint or blueprint_for(_looks_quantitative(units))
    avoid = ""
    if avoid_stems:
        avoid = "\nDo not repeat or closely paraphrase these existing questions:\n" + "\n".join(f"- {s[:160]}" for s in avoid_stems[-14:]) + "\n"
    prompt = GENERATE_PROMPT.format(
        name=concept["name"], description=concept["description"],
        blueprint="\n".join(f"{i}. type {kind}, difficulty {level}" for i, (kind, level) in enumerate(blueprint, 1)),
        avoid=avoid, material=_material_block(units),
    )
    result = llm().chat(
        [{"role": "user", "content": prompt}],
        models=settings.author_models, namespace="questions-generate", schema=QUESTION_SCHEMA,
        temperature=0.4, salt=f"{concept['id']}:{seed}",
    )
    return result.json().get("questions", []), units, result.model


def _structure(question: dict, units: list[dict]) -> str | None:
    """Reason the question is malformed, or None."""
    if len(question.get("stem", "").split()) < 5:
        return "stem too short"
    cited = [s for s in question.get("sources", []) if s[:1] == "S" and s[1:].isdigit() and 1 <= int(s[1:]) <= len(units)]
    if not cited:
        return "no valid source cited"
    kind = question["type"]
    if kind == "mcq":
        options = [o.strip() for o in question.get("options", [])]
        if len(options) != 4 or len({o.lower() for o in options}) != 4:
            return "needs four distinct options"
        if not 0 <= question.get("correct_option", -1) <= 3:
            return "invalid key"
    elif kind == "numeric":
        if not question.get("formula") or "value" not in question:
            return "missing formula or value"
    elif kind == "short":
        if len(question.get("answer", "").split()) < 3:
            return "reference answer too short"
    return None


def verify(raw: list[dict], units: list[dict], generator_model: str) -> list[dict]:
    """Run the checks. Returns one record per question: {"question", "status", "checks"}."""
    records = []
    for question in raw:
        checks: dict = {"generator": generator_model}
        problem = _structure(question, units)
        checks["structure"] = problem or "ok"
        if not problem and question["type"] == "numeric":
            variables = {v["name"]: v["value"] for v in question.get("variables", [])}
            try:
                recomputed = numeric.evaluate(question["formula"], variables)
                checks["recomputed"] = recomputed
                if numeric.close(recomputed, question["value"], 1.0):
                    checks["arithmetic"] = "ok"
                else:
                    checks["arithmetic"] = f"key {question['value']} but formula gives {recomputed:.6g}"
                    problem = "arithmetic mismatch"
            except numeric.FormulaError as error:
                checks["arithmetic"] = f"formula not evaluable: {error}"
                problem = "formula not evaluable"
        records.append({"question": question, "status": "rejected" if problem else "pending", "checks": checks, "reason": problem})

    pending = [r for r in records if r["status"] == "pending"]
    if pending:
        lines = []
        for number, record in enumerate(pending, 1):
            q = record["question"]
            if q["type"] == "mcq":
                options = "\n".join(f"   ({i}) {o}" for i, o in enumerate(q["options"]))
                lines.append(f"{number}. [mcq] {q['stem']}\n{options}")
            elif q["type"] == "numeric":
                lines.append(f"{number}. [numeric, answer in {q.get('unit') or 'SI units'}] {q['stem']}")
            else:
                lines.append(f"{number}. [short] {q['stem']}\n   Reference answer: {q['answer']}")
        # The blind solver must not be the model that wrote the questions.
        verifiers = [m for m in settings.verifier_models if m != generator_model] or settings.verifier_models
        result = llm().chat(
            [{"role": "user", "content": VERIFY_PROMPT.format(material=_material_block(units), questions="\n\n".join(lines))}],
            models=verifiers, namespace="questions-verify", schema=VERIFY_SCHEMA,
        )
        answers = {r.get("question"): r for r in result.json().get("results", [])}
        for number, record in enumerate(pending, 1):
            q, checks = record["question"], record["checks"]
            verdict = answers.get(number)
            checks["verifier"] = result.model
            if verdict is None:
                record["status"], record["reason"] = "rejected", "verifier returned no verdict"
                continue
            checks["answerable"] = bool(verdict.get("answerable_from_material"))
            checks["ambiguous"] = bool(verdict.get("ambiguous"))
            checks["note"] = verdict.get("note", "")
            agrees = False
            if q["type"] == "mcq":
                checks["blind_option"] = verdict.get("option")
                agrees = verdict.get("option") == q["correct_option"]
            elif q["type"] == "numeric":
                checks["blind_value"] = verdict.get("value")
                agrees = verdict.get("value") is not None and numeric.close(float(verdict["value"]), float(q["value"]), 2.0)
            else:
                agrees = bool(verdict.get("reference_correct"))
            checks["blind_agrees"] = agrees
            if not agrees:
                record["status"], record["reason"] = "rejected", "second model disagrees with the key"
            elif checks["ambiguous"]:
                record["status"], record["reason"] = "rejected", "flagged ambiguous"
            elif not checks["answerable"]:
                record["status"], record["reason"] = "rejected", "not answerable from the material"
            else:
                record["status"] = "verified"
    return records


def _row(concept_id: str, question: dict, units: list[dict], checks: dict, status: str, vector: np.ndarray) -> dict:
    cited = [units[int(s[1:]) - 1]["id"] for s in question.get("sources", []) if s[:1] == "S" and s[1:].isdigit() and 1 <= int(s[1:]) <= len(units)]
    kind = question["type"]
    answer: dict = {"text": question.get("answer", "")}
    options = None
    if kind == "mcq":
        options = question.get("options", [])
        answer.update({"option": question.get("correct_option"), "misconceptions": (question.get("misconceptions") or [""] * 4)[:4]})
    elif kind == "numeric":
        answer.update({
            "value": question.get("value"), "unit": question.get("unit", ""), "formula": question.get("formula", ""),
            "variables": {v["name"]: v["value"] for v in question.get("variables", [])}, "tolerance_pct": 2.0,
        })
    else:
        answer.update({"key_points": question.get("key_points", [])})
    return {
        # The id is derived from the question itself, so rebuilding the bank from the cache
        # gives every question the id it had before.
        "id": "q_" + hashlib.sha1(f"{concept_id}|{question['stem'].strip()}".encode()).hexdigest()[:10],
        "concept_id": concept_id, "type": kind,
        "difficulty": max(1, min(5, int(question.get("difficulty", 2)))),
        "stem": question["stem"].strip(), "options": options, "answer": answer,
        "explanation": question.get("explanation", "").strip(), "unit_ids": cited or [units[0]["id"]],
        "verification": checks, "status": status, "vec": embed.to_blob(vector), "created": now(),
    }


def add_to_bank(db: Database, concept: dict, seed: int = 0, blueprint: list[tuple[str, int]] | None = None,
                duplicate_threshold: float = 0.935) -> dict:
    """Generate, verify and store questions for one concept. Returns counts per outcome."""
    existing = db.all("SELECT stem, vec FROM questions WHERE concept_id = ? AND status = 'verified'", [concept["id"]])
    raw, units, model = generate(db, concept, seed, [e["stem"] for e in existing], blueprint)
    stats = {"generated": len(raw), "verified": 0, "rejected": {}}
    if not raw:
        return stats
    records = verify(raw, units, model)
    # A question's identity is its stem together with its answer: two MCQs may both ask
    # "which statement is correct?" and still test different things.
    vectors = embed.embed_passages([f"{r['question'].get('stem', '')}\n{r['question'].get('answer', '')}" for r in records])
    bank = [embed.from_blob(e["vec"]) for e in existing if e["vec"]]
    for record, vector in zip(records, vectors):
        if record["status"] == "verified" and bank and float(np.max(np.stack(bank) @ vector)) >= duplicate_threshold:
            record["status"], record["reason"] = "rejected", "near-duplicate of a banked question"
        record["checks"]["novelty"] = "ok" if record["status"] == "verified" else record["checks"].get("novelty", "")
        if record["status"] == "verified":
            bank.append(vector)
            stats["verified"] += 1
        else:
            stats["rejected"][record["reason"]] = stats["rejected"].get(record["reason"], 0) + 1
            record["checks"]["rejected_because"] = record["reason"]
        if record["checks"]["structure"] == "ok":  # malformed items are counted but not stored
            db.insert("questions", _row(concept["id"], record["question"], units, record["checks"], record["status"], vector), replace=True)
    return stats


def build_bank(db: Database, rounds: int = 1, progress: Callable[[str], None] = print,
               concept_ids: set[str] | None = None) -> dict:
    """Fill the bank for every concept. Each round adds one blueprint's worth per concept."""
    totals = {"generated": 0, "verified": 0, "rejected": {}}
    concepts = [c for c in db.all("SELECT * FROM concepts ORDER BY ord") if not concept_ids or c["id"] in concept_ids]
    for seed in range(rounds):
        for concept in concepts:
            have = db.one("SELECT COUNT(*) AS n FROM questions WHERE concept_id = ? AND status = 'verified'", [concept["id"]])["n"]
            if have >= 6 * (seed + 1):
                continue
            try:
                stats = add_to_bank(db, concept, seed=seed)
            except LLMError as error:
                # Usually a quota or an overloaded verifier. Nothing half-checked is stored, and
                # running the command again later picks this concept up where it was left.
                progress(f"{concept['id']}: skipped for now ({error})")
                continue
            totals["generated"] += stats["generated"]
            totals["verified"] += stats["verified"]
            for reason, count in stats["rejected"].items():
                totals["rejected"][reason] = totals["rejected"].get(reason, 0) + count
            progress(f"{concept['id']}: {stats['verified']}/{stats['generated']} verified {stats['rejected'] or ''}")
    return totals

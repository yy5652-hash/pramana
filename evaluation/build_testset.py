"""Draft the evaluation test set: questions whose answer has a known location in the sources.

For each sampled unit a model drafts one question a student might ask and a reference
answer, both resting on that unit alone. Units are sampled by how they were obtained, so the
set covers every modality: textbook prose, textbook passages whose maths had to be restored
by vision, textbook figures, slides, spoken lecture passages and readings of the board.

The drafts are written to `evaluation/testset.jsonl`, where they are meant to be read and
edited before being used. For the shipped set that review was done by the AI coding assistant
that built the project, not by a person; docs/evaluation.md says what it changed.
Off-material questions are not drafted by the model; they are listed in OFF_MATERIAL below:
half are far from the subject, half are physics the ingested chapters do not teach.

    python -m evaluation.build_testset --course mechanics
"""
from __future__ import annotations

import argparse
import json
import random

from pramana.config import ROOT, settings
from pramana.db import open_course
from pramana.llm import llm

STRATA = [
    # (label, SQL filter on units u, how many)
    ("textbook-prose", "u.kind = 'text' AND u.modality = 'text' AND u.source_id = 'textbook'", 6),
    ("textbook-maths", "u.kind = 'text' AND u.modality = 'vision' AND u.source_id = 'textbook'", 9),
    ("textbook-figure", "u.kind = 'figure'", 6),
    ("slide", "u.kind = 'slide'", 8),
    ("lecture-speech", "u.kind = 'transcript'", 6),
    ("lecture-board", "u.kind = 'frame'", 5),
]

OFF_MATERIAL = [
    # far from the subject
    ("How does a transformer neural network use self-attention?", "far"),
    ("What is the capital of Australia?", "far"),
    ("Explain how mRNA vaccines train the immune system.", "far"),
    ("What caused the French Revolution?", "far"),
    ("How do I reverse a linked list in Python?", "far"),
    ("What is the difference between a stock and a bond?", "far"),
    # physics, but not taught in the ingested chapters
    ("What is the moment of inertia of a solid sphere about its diameter?", "near"),
    ("State Bernoulli's equation for fluid flow.", "near"),
    ("What is the time dilation formula in special relativity?", "near"),
    ("How does a capacitor store energy, and what is the formula for it?", "near"),
    ("What is the Schrödinger equation?", "near"),
    ("What is the Doppler shift formula for a moving sound source?", "near"),
    ("State Kepler's third law of planetary motion.", "near"),
    ("What is the first law of thermodynamics?", "near"),
]

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "passage": {"type": "integer"},
                    "question": {"type": "string"},
                    "reference": {"type": "string"},
                    "usable": {"type": "boolean"},
                },
                "required": ["passage", "question", "reference", "usable"],
            },
        }
    },
    "required": ["items"],
}

PROMPT = """You are writing a test set for a course question-answering system.

For each numbered passage below, write one question a student studying this course might genuinely ask, whose answer is stated in that passage, and a reference answer of one to three sentences taken from the passage.

Rules:
- Phrase the question in a student's own words. Do not copy the passage's sentences, and do not mention "the passage", "the figure", figure numbers, slide numbers or the lecturer.
- The question must be specific enough that this passage is the natural place to find the answer (avoid "What is physics?").
- The reference answer must be fully supported by the passage. Write maths as LaTeX between $...$.
- If a passage has nothing a student would ask about (a title page, housekeeping, a list of links), set "usable" to false and leave the other fields empty.

Passages:
{passages}
"""


def sample_units(course_id: str, seed: int) -> list[tuple[str, dict]]:
    db = open_course(course_id)
    rng = random.Random(seed)
    picked = []
    for label, where, count in STRATA:
        rows = db.all(
            f"SELECT u.* FROM units u WHERE {where} AND LENGTH(u.text) > 220 "
            "AND EXISTS (SELECT 1 FROM unit_concepts uc WHERE uc.unit_id = u.id) ORDER BY u.id")
        rng.shuffle(rows)
        # Over-sample by half: some drafts will be marked unusable or dropped on review.
        picked.extend((label, row) for row in rows[: count + count // 2])
    return picked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", default="mechanics")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--batch", type=int, default=10)
    args = parser.parse_args()

    sampled = sample_units(args.course, args.seed)
    wanted = {label: count for label, _, count in STRATA}
    kept: dict[str, int] = {label: 0 for label in wanted}
    rows = []
    for start in range(0, len(sampled), args.batch):
        chunk = sampled[start : start + args.batch]
        passages = "\n\n".join(f"{i}. [{unit['section'] or ''}]\n{unit['text'][:1500]}" for i, (_, unit) in enumerate(chunk, 1))
        result = llm().chat(
            [{"role": "user", "content": PROMPT.format(passages=passages)}],
            models=settings.author_models, namespace="eval-testset", schema=SCHEMA, temperature=0.3,
        )
        for item in result.json().get("items", []):
            index = item.get("passage", 0) - 1
            if not item.get("usable") or not 0 <= index < len(chunk):
                continue
            label, unit = chunk[index]
            if kept[label] >= wanted[label]:
                continue
            kept[label] += 1
            rows.append({
                "id": f"in-{len(rows) + 1:02d}", "category": "in_material", "stratum": label,
                "question": item["question"].strip(), "reference": item["reference"].strip(),
                "gold": {"unit_id": unit["id"], "source_id": unit["source_id"], "kind": unit["kind"],
                         "modality": unit["modality"], "locator": unit["locator"]},
                "drafted_by": result.model,
            })
    for number, (question, distance) in enumerate(OFF_MATERIAL, 1):
        rows.append({"id": f"off-{number:02d}", "category": "off_material", "stratum": f"off-{distance}",
                     "question": question, "reference": "", "gold": None, "drafted_by": "hand"})

    out = ROOT / "evaluation" / "testset.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    print(f"wrote {out}: {sum(1 for r in rows if r['category'] == 'in_material')} in-material {kept}, {len(OFF_MATERIAL)} off-material")


if __name__ == "__main__":
    main()

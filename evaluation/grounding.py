"""Run the tutor over the test set and measure what "grounded" promises.

Three questions, three measurements:

1. **Does it decline what the material does not cover?** A confusion matrix over the
   in-material and off-material questions. Off-material questions are split into "far"
   (another subject) and "near" (physics the ingested chapters do not teach); "near" is the
   hard case.
2. **Do its citations point at the right place?** For in-material questions, the share of
   answers that cite the known gold location. Strict: citing the same fact in a different
   source counts as a miss.
3. **Does each cited source actually say what the sentence says?** A different model reads
   every answer segment next to the excerpts it cites and judges whether they support it.

The answers and the retrieved contexts are saved to `results/answers.jsonl`; the RAGAS run
(`evaluation.ragas_eval`) scores those same answers, so every number describes one run.

    python -m evaluation.grounding --course mechanics
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

from pramana import tutor
from pramana.config import settings
from pramana.db import new_id, now, open_course
from pramana.llm import llm
from pramana.retrieve import Index

from .common import RESULTS, load_testset, mean_ci, same_place, write_result

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"segment": {"type": "integer"}, "supported": {"type": "string", "enum": ["yes", "partly", "no"]}, "note": {"type": "string"}},
                "required": ["segment", "supported", "note"],
            },
        }
    },
    "required": ["segments"],
}

JUDGE_PROMPT = """You are auditing citations. Each numbered segment below is a piece of a tutor's answer, followed by the source excerpts it cites.

For each segment decide whether the cited excerpts state what the segment says:
- "yes": every claim in the segment is stated in, or follows directly from, its cited excerpts.
- "partly": some claims are supported and some are not found in the cited excerpts.
- "no": the cited excerpts do not support the segment.

Judge only against the excerpts shown for that segment, not against your own knowledge. A correct statement that the excerpts do not contain is "no". Give a short note when the verdict is not "yes".

{segments}
"""


def answer_all(course_id: str, questions: list[dict], workers: int = 3) -> list[dict]:
    db = open_course(course_id)
    index = Index(db)
    student = {"id": new_id("eval"), "name": "evaluation", "created": now(), "profile": {"simulated": True}}
    db.insert("students", student)

    def run(question: dict) -> dict:
        reply = tutor.respond(db, index, course_id, student["id"], question["question"], personalise=False,
                              record=False, understand=False, namespace="eval-answers")
        cited = [index.by_id[c["unit_id"]] for c in reply["citations"]]
        return {
            "id": question["id"], "category": question["category"], "stratum": question["stratum"],
            "question": question["question"], "reference": question["reference"], "gold": question["gold"],
            "coverage": reply["coverage"], "refused": reply["refused"], "model": reply.get("model"),
            "response": " ".join(s["text"] for s in reply["segments"]),
            "segments": [{"text": s["text"], "cited_unit_ids": [next(c["unit_id"] for c in reply["citations"] if c["n"] == n) for n in s["citations"]]}
                         for s in reply["segments"]],
            "cited_unit_ids": [u["id"] for u in cited],
            "cites_gold_location": bool(question["gold"]) and any(same_place(u, question["gold"]) for u in cited),
            "contexts": reply.get("contexts", []), "context_unit_ids": reply.get("context_unit_ids", []),
            "top_score": reply["retrieval"][0]["score"] if reply["retrieval"] else None,
            "unsourced_segments_removed": reply.get("unsourced_segments_removed", 0),
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, questions))


def judge_support(course_id: str, answers: list[dict], workers: int = 3) -> None:
    """Add a `support` verdict to every segment of every answered question."""
    index = Index(open_course(course_id))

    def run(answer: dict) -> None:
        if not answer["segments"]:
            return
        blocks = []
        for number, segment in enumerate(answer["segments"], 1):
            excerpts = "\n".join(f"   [excerpt] {index.context_for(index.by_id[u])[:1500]}" for u in segment["cited_unit_ids"])
            blocks.append(f"Segment {number}: {segment['text']}\n{excerpts}")
        result = llm().chat(
            [{"role": "user", "content": JUDGE_PROMPT.format(segments="\n\n".join(blocks))}],
            models=[m for m in settings.judge_models if m != answer["model"]] or settings.judge_models,
            namespace="eval-citation-judge", schema=JUDGE_SCHEMA,
        )
        verdicts = {v.get("segment"): v for v in result.json().get("segments", [])}
        for number, segment in enumerate(answer["segments"], 1):
            verdict = verdicts.get(number, {})
            segment["support"] = verdict.get("supported", "unjudged")
            segment["support_note"] = verdict.get("note", "")
        answer["judge_model"] = result.model

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(run, answers))


def judge_control(course_id: str, answers: list[dict], workers: int = 3) -> dict:
    """A check on the judge itself. Every answer's segments are shown again, this time next to
    the excerpts that a *different* answer cites. A judge that actually reads the excerpts
    should refuse nearly all of them; one that waves everything through would not."""
    index = Index(open_course(course_id))
    judged = [a for a in answers if a["segments"]]
    if len(judged) < 2:
        return {}

    def run(position: int) -> list[str]:
        answer, other = judged[position], judged[(position + len(judged) // 2) % len(judged)]
        blocks = []
        for number, segment in enumerate(answer["segments"], 1):
            borrowed = other["segments"][(number - 1) % len(other["segments"])]["cited_unit_ids"]
            excerpts = "\n".join(f"   [excerpt] {index.context_for(index.by_id[u])[:1500]}" for u in borrowed)
            blocks.append(f"Segment {number}: {segment['text']}\n{excerpts}")
        result = llm().chat(
            [{"role": "user", "content": JUDGE_PROMPT.format(segments="\n\n".join(blocks))}],
            models=[m for m in settings.judge_models if m != answer["model"]] or settings.judge_models,
            namespace="eval-citation-judge", schema=JUDGE_SCHEMA,
        )
        verdicts = {v.get("segment"): v.get("supported", "unjudged") for v in result.json().get("segments", [])}
        return [verdicts.get(number, "unjudged") for number in range(1, len(answer["segments"]) + 1)]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        verdicts = [v for group in pool.map(run, range(len(judged))) for v in group if v in ("yes", "partly", "no")]
    return {
        "segments_judged": len(verdicts),
        "fully_supported": round(sum(v == "yes" for v in verdicts) / max(len(verdicts), 1), 4),
        "partly_supported": round(sum(v == "partly" for v in verdicts) / max(len(verdicts), 1), 4),
        "unsupported": round(sum(v == "no" for v in verdicts) / max(len(verdicts), 1), 4),
    }


def summarise(answers: list[dict]) -> dict:
    inside = [a for a in answers if a["category"] == "in_material"]
    outside = [a for a in answers if a["category"] == "off_material"]
    answered_inside = [a for a in inside if not a["refused"]]
    segments = [s for a in answered_inside for s in a["segments"] if s.get("support") in ("yes", "partly", "no")]
    declined_outside = [a for a in outside if a["refused"]]
    true_declines, false_declines = len(declined_outside), len(inside) - len(answered_inside)
    return {
        "n_in_material": len(inside), "n_off_material": len(outside),
        "refusal": {
            "in_material_answered": len(answered_inside), "in_material_declined": false_declines,
            "off_material_declined": true_declines, "off_material_answered": len(outside) - true_declines,
            "decline_precision": round(true_declines / max(true_declines + false_declines, 1), 4),
            "decline_recall": round(true_declines / max(len(outside), 1), 4),
            "by_distance": {
                distance: {"declined": sum(a["refused"] for a in outside if a["stratum"] == f"off-{distance}"),
                           "n": sum(1 for a in outside if a["stratum"] == f"off-{distance}")}
                for distance in ("far", "near")
            },
            "answered_off_material": [{"id": a["id"], "question": a["question"], "coverage": a["coverage"], "response": a["response"][:300]}
                                      for a in outside if not a["refused"]],
            "declined_in_material": [{"id": a["id"], "question": a["question"], "stratum": a["stratum"]} for a in inside if a["refused"]],
        },
        "citation_location": {
            "answers_citing_gold_location": mean_ci([1.0 if a["cites_gold_location"] else 0.0 for a in answered_inside]),
            "by_stratum": {s: mean_ci([1.0 if a["cites_gold_location"] else 0.0 for a in answered_inside if a["stratum"] == s])
                           for s in sorted({a["stratum"] for a in answered_inside})},
        },
        "citation_support": {
            "segments_judged": len(segments),
            "fully_supported": round(sum(s["support"] == "yes" for s in segments) / max(len(segments), 1), 4),
            "partly_supported": round(sum(s["support"] == "partly" for s in segments) / max(len(segments), 1), 4),
            "unsupported": round(sum(s["support"] == "no" for s in segments) / max(len(segments), 1), 4),
            "unsupported_examples": [{"id": a["id"], "segment": s["text"][:240], "note": s.get("support_note", "")}
                                     for a in answered_inside for s in a["segments"] if s.get("support") == "no"][:8],
        },
        "segments_per_answer": mean_ci([float(len(a["segments"])) for a in answered_inside]),
        "unsourced_segments_removed": sum(a["unsourced_segments_removed"] for a in answers),
        "models": {"tutor": sorted({a["model"] for a in answers if a["model"]}), "judge": sorted({a.get("judge_model") for a in answers if a.get("judge_model")})},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", default="mechanics")
    parser.add_argument("--no-judge", action="store_true", help="skip the citation-support judge")
    args = parser.parse_args()
    answers = answer_all(args.course, load_testset())
    answered = [a for a in answers if a["category"] == "in_material" and not a["refused"]]
    if not args.no_judge:
        judge_support(args.course, answered)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "answers.jsonl").write_text("\n".join(json.dumps(a, ensure_ascii=False) for a in answers) + "\n")
    summary = summarise(answers)
    if not args.no_judge:
        summary["citation_support"]["judge_control"] = judge_control(args.course, answered)
    write_result("grounding", summary)
    print(json.dumps({k: summary[k] for k in ("refusal", "citation_location", "citation_support")}, indent=1)[:2500])


if __name__ == "__main__":
    main()

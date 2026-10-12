"""Retrieval quality against known source locations. No language model is called.

For every in-material test question we know where its answer lives (a page, a slide, or a
passage of a lecture). A retrieval counts as a hit at rank r when the r-th result sits at
that location. This is strict: the same fact is often also stated in another source (the
slides repeat the textbook), and landing there is scored as a miss.

Compared: the full pipeline (hybrid + cross-encoder re-ranking), hybrid without re-ranking,
dense only and lexical only. With `--ablation COURSE` the same questions are also run against
a knowledge base built without vision (`pramana ingest ... --no-vision`), to show what the
multimodal reading buys.

    python -m evaluation.retrieval --course mechanics [--ablation mechanics-textonly]
"""
from __future__ import annotations

import argparse

from pramana.db import open_course
from pramana.retrieve import Index

from .common import load_testset, mean_ci, same_place, write_result

MODES = {
    "hybrid + rerank": {"mode": "hybrid", "use_rerank": True},
    "hybrid": {"mode": "hybrid", "use_rerank": False},
    "dense only": {"mode": "dense", "use_rerank": False},
    "lexical only": {"mode": "lexical", "use_rerank": False},
}


def rank_of_gold(index: Index, question: dict, k: int, **options) -> int | None:
    hits = index.search(question["question"], k=k, **options)
    for rank, hit in enumerate(hits, 1):
        if same_place(hit.unit, question["gold"]):
            return rank
        sibling = index.by_id.get(hit.unit["locator"].get("sibling", ""))
        if sibling and same_place(sibling, question["gold"]):
            return rank
    return None


def score(ranks: list[int | None]) -> dict:
    return {
        "hit@1": mean_ci([1.0 if r == 1 else 0.0 for r in ranks]),
        "hit@3": mean_ci([1.0 if r and r <= 3 else 0.0 for r in ranks]),
        "hit@6": mean_ci([1.0 if r and r <= 6 else 0.0 for r in ranks]),
        "mrr": mean_ci([1.0 / r if r else 0.0 for r in ranks]),
    }


def evaluate(course_id: str, questions: list[dict], k: int = 6) -> dict:
    index = Index(open_course(course_id))
    out = {"units": len(index.units), "modes": {}, "by_stratum": {}, "per_question": {}}
    for name, options in MODES.items():
        ranks = [rank_of_gold(index, q, k, **options) for q in questions]
        out["modes"][name] = score(ranks)
        if name == "hybrid + rerank":
            out["per_question"] = {q["id"]: r for q, r in zip(questions, ranks)}
            for stratum in sorted({q["stratum"] for q in questions}):
                out["by_stratum"][stratum] = score([r for q, r in zip(questions, ranks) if q["stratum"] == stratum])
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", default="mechanics")
    parser.add_argument("--ablation", help="course id of a knowledge base built with --no-vision")
    args = parser.parse_args()
    questions = [q for q in load_testset() if q["category"] == "in_material"]
    result = {"n_questions": len(questions), "k": 6, "full": evaluate(args.course, questions)}
    if args.ablation:
        result["no_vision"] = evaluate(args.ablation, questions)
    write_result("retrieval", result)
    for name, scores in result["full"]["modes"].items():
        print(f"{name:18s} hit@1 {scores['hit@1']['mean']:.2f}  hit@3 {scores['hit@3']['mean']:.2f}  hit@6 {scores['hit@6']['mean']:.2f}  MRR {scores['mrr']['mean']:.2f}")
    if args.ablation:
        scores = result["no_vision"]["modes"]["hybrid + rerank"]
        print(f"{'no vision':18s} hit@1 {scores['hit@1']['mean']:.2f}  hit@3 {scores['hit@3']['mean']:.2f}  hit@6 {scores['hit@6']['mean']:.2f}  MRR {scores['mrr']['mean']:.2f}")


if __name__ == "__main__":
    main()

"""What vision buys, measured on content rather than location.

Location-based retrieval metrics cannot see a missing equation: a text-layer unit from the
right page counts as a hit even when the formula the question asks about is not in it. This
script asks the content question instead. For every in-material test question it retrieves
the top contexts from two knowledge bases, the real one and one built with
`pramana ingest --no-vision`, and scores both with RAGAS context recall: what share of the
reference answer's claims can be found in the retrieved text?

    python -m evaluation.ablation --course mechanics --no-vision mechanics-textonly
"""
from __future__ import annotations

import argparse
import math
import warnings

warnings.filterwarnings("ignore")

from ragas import EvaluationDataset, evaluate  # noqa: E402
from ragas.dataset_schema import SingleTurnSample  # noqa: E402
from ragas.metrics import LLMContextRecall  # noqa: E402
from ragas.run_config import RunConfig  # noqa: E402

from pramana.config import settings  # noqa: E402
from pramana.db import open_course  # noqa: E402
from pramana.retrieve import Index  # noqa: E402

from .common import load_testset, mean_ci, write_result  # noqa: E402
from .ragas_eval import LocalEmbeddings, ReplayableLLM  # noqa: E402


def recall(course_id: str, questions: list[dict], contexts: int, workers: int, judge: ReplayableLLM) -> list[float | None]:
    index = Index(open_course(course_id))
    samples = [
        SingleTurnSample(user_input=q["question"], reference=q["reference"], response="",
                         retrieved_contexts=[hit.context for hit in index.search(q["question"], k=contexts)])
        for q in questions
    ]
    result = evaluate(EvaluationDataset(samples=samples), metrics=[LLMContextRecall()], llm=judge, embeddings=LocalEmbeddings(),
                      run_config=RunConfig(max_workers=workers, timeout=600, max_retries=3), raise_exceptions=False, show_progress=True)
    return [None if isinstance(v, float) and math.isnan(v) else round(float(v), 4) for v in result.to_pandas()["context_recall"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", default="mechanics")
    parser.add_argument("--no-vision", default="mechanics-textonly", dest="no_vision")
    parser.add_argument("--contexts", type=int, default=4)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    questions = [q for q in load_testset() if q["category"] == "in_material"]
    judge = ReplayableLLM(settings.judge_models)
    full = recall(args.course, questions, args.contexts, args.workers, judge)
    bare = recall(args.no_vision, questions, args.contexts, args.workers, judge)
    strata = sorted({q["stratum"] for q in questions})
    write_result("ablation", {
        "metric": "RAGAS context recall", "n_questions": len(questions), "contexts_per_question": args.contexts, "judge_models": sorted(judge.used),
        "full": mean_ci(full), "no_vision": mean_ci(bare),
        "by_stratum": {s: {"full": mean_ci([v for q, v in zip(questions, full) if q["stratum"] == s]),
                           "no_vision": mean_ci([v for q, v in zip(questions, bare) if q["stratum"] == s])} for s in strata},
        "per_question": [{"id": q["id"], "stratum": q["stratum"], "full": a, "no_vision": b} for q, a, b in zip(questions, full, bare)],
    })
    print(f"context recall: with vision {mean_ci(full)}, without {mean_ci(bare)}")


if __name__ == "__main__":
    main()

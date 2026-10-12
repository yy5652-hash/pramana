"""RAGAS over the tutor's answers: faithfulness, answer relevancy, context precision, context recall.

RAGAS (https://docs.ragas.io) is used as published. Two adapters connect it to this project:

* `ReplayableLLM` routes every judge call through Pramana's own client, so the judge runs on
  any OpenAI-compatible endpoint, respects rate limits, and is cached. With
  `PRAMANA_LLM_MODE=replay` the whole RAGAS run reproduces from the committed cache without
  an API key.
* `LocalEmbeddings` gives RAGAS the same local embedding model retrieval uses.

It scores the answers saved by `evaluation.grounding`, so run that first.

    python -m evaluation.ragas_eval
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import warnings

warnings.filterwarnings("ignore")

from langchain_core.outputs import Generation, LLMResult  # noqa: E402
from ragas import EvaluationDataset, evaluate  # noqa: E402
from ragas.dataset_schema import SingleTurnSample  # noqa: E402
from ragas.embeddings.base import BaseRagasEmbeddings  # noqa: E402
from ragas.llms.base import BaseRagasLLM  # noqa: E402
from ragas.metrics import Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall, ResponseRelevancy  # noqa: E402
from ragas.run_config import RunConfig  # noqa: E402

from pramana import embed  # noqa: E402
from pramana.config import settings  # noqa: E402
from pramana.llm import llm  # noqa: E402

from .common import RESULTS, mean_ci, write_result  # noqa: E402


class ReplayableLLM(BaseRagasLLM):
    """RAGAS judge backed by Pramana's cached, rate-limited client."""

    def __init__(self, models: list[str]):
        super().__init__(run_config=RunConfig())
        self.models = models
        self.used: set[str] = set()

    def generate_text(self, prompt, n=1, temperature=0.01, stop=None, callbacks=None) -> LLMResult:
        generations = []
        for sample in range(n):
            result = llm().chat(
                [{"role": "user", "content": prompt.to_string()}],
                models=self.models, namespace="eval-ragas", temperature=0.0, salt=f"sample-{sample}" if sample else "",
            )
            self.used.add(result.model)
            generations.append(Generation(text=result.text))
        return LLMResult(generations=[generations])

    async def agenerate_text(self, prompt, n=1, temperature=0.01, stop=None, callbacks=None) -> LLMResult:
        return await asyncio.to_thread(self.generate_text, prompt, n, temperature, stop, callbacks)

    def is_finished(self, response: LLMResult) -> bool:
        return True


class LocalEmbeddings(BaseRagasEmbeddings):
    def embed_query(self, text: str) -> list[float]:
        return embed.embed_query(text).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return embed.embed_passages(texts).tolist()

    async def aembed_query(self, text: str) -> list[float]:
        return await asyncio.to_thread(self.embed_query, text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.embed_documents, texts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--answers", default=str(RESULTS / "answers.jsonl"))
    parser.add_argument("--contexts", type=int, default=4, help="top contexts per question handed to RAGAS")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()

    answers = [json.loads(line) for line in open(args.answers) if line.strip()]
    scored = [a for a in answers if a["category"] == "in_material" and not a["refused"] and a["response"]]
    samples = [
        SingleTurnSample(user_input=a["question"], response=a["response"], reference=a["reference"],
                         retrieved_contexts=a["contexts"][: args.contexts])
        for a in scored
    ]
    judge = ReplayableLLM(settings.judge_models)
    metrics = [Faithfulness(), ResponseRelevancy(strictness=1), LLMContextPrecisionWithReference(), LLMContextRecall()]
    result = evaluate(
        EvaluationDataset(samples=samples), metrics=metrics, llm=judge, embeddings=LocalEmbeddings(),
        run_config=RunConfig(max_workers=args.workers, timeout=600, max_retries=3), raise_exceptions=False, show_progress=True,
    )
    table = result.to_pandas()
    names = [c for c in table.columns if c not in ("user_input", "response", "reference", "retrieved_contexts")]
    per_question = []
    for answer, (_, row) in zip(scored, table.iterrows()):
        per_question.append({"id": answer["id"], "stratum": answer["stratum"],
                             **{n: (None if isinstance(row[n], float) and math.isnan(row[n]) else round(float(row[n]), 4)) for n in names}})
    summary = {
        "framework": "ragas " + __import__("ragas").__version__,
        "n_scored": len(scored),
        "n_in_material": sum(1 for a in answers if a["category"] == "in_material"),
        "contexts_per_question": args.contexts,
        "judge_models": sorted(judge.used), "tutor_models": sorted({a["model"] for a in scored if a["model"]}),
        "embedding_model": settings.embed_model,
        "metrics": {n: mean_ci([q[n] for q in per_question]) for n in names},
        "by_stratum": {s: {n: mean_ci([q[n] for q in per_question if q["stratum"] == s]) for n in names}
                       for s in sorted({q["stratum"] for q in per_question})},
        "unscored": {n: sum(1 for q in per_question if q[n] is None) for n in names},
        "per_question": per_question,
    }
    write_result("ragas", summary)
    for name, value in summary["metrics"].items():
        print(f"{name:40s} {value['mean']}  ± {value['ci95']}  (n={value['n']})")


if __name__ == "__main__":
    main()

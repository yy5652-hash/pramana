"""Hybrid retrieval over content units: BM25 + dense vectors, fused, then re-ranked.

The index is small (about a thousand units per course), so everything is held in memory and
searched exactly. No vector database is needed at this size, and exact search keeps results
reproducible.
"""
from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from . import embed
from .db import Database

TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    "a an and are as at be by for from has have how in is it its of on or that the this to was what "
    "when where which who why with does do can i you we they".split()
)


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOPWORDS]


@dataclass
class Hit:
    unit: dict
    score: float                    # cross-encoder relevance logit
    dense_rank: int | None = None
    lexical_rank: int | None = None
    context: str = ""               # unit text plus, for video, the sibling channel
    extra: dict = field(default_factory=dict)


class Index:
    """In-memory search index for one course."""

    def __init__(self, db: Database):
        self.db = db
        self.lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        with self.lock:
            self.units = self.db.all("SELECT * FROM units ORDER BY source_id, ord")
            self.by_id = {u["id"]: u for u in self.units}
            self.position = {u["id"]: i for i, u in enumerate(self.units)}
            vectors = dict(
                (r["unit_id"], embed.from_blob(r["vec"])) for r in self.db.all("SELECT unit_id, vec FROM embeddings")
            )
            dim = len(next(iter(vectors.values()))) if vectors else 384
            self.matrix = np.stack([vectors.get(u["id"], np.zeros(dim, dtype=np.float32)) for u in self.units]) if self.units else np.zeros((0, dim), dtype=np.float32)
            self.sources = {s["id"]: s for s in self.db.all("SELECT * FROM sources")}
            self.unit_concepts: dict[str, list[str]] = {}
            for row in self.db.all("SELECT unit_id, concept_id FROM unit_concepts ORDER BY weight DESC"):
                self.unit_concepts.setdefault(row["unit_id"], []).append(row["concept_id"])
            # BM25 statistics
            self.doc_tokens = [Counter(tokens(f"{u['section'] or ''} {u['text']}")) for u in self.units]
            self.doc_len = np.array([sum(c.values()) for c in self.doc_tokens], dtype=np.float32)
            self.avg_len = float(self.doc_len.mean()) if len(self.units) else 1.0
            frequency: Counter[str] = Counter()
            for counts in self.doc_tokens:
                frequency.update(counts.keys())
            count = len(self.units)
            self.idf = {t: math.log(1 + (count - n + 0.5) / (n + 0.5)) for t, n in frequency.items()}

    def _bm25(self, query: str, k1: float = 1.5, b: float = 0.75) -> np.ndarray:
        scores = np.zeros(len(self.units), dtype=np.float32)
        for term in set(tokens(query)):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, counts in enumerate(self.doc_tokens):
                tf = counts.get(term)
                if tf:
                    scores[i] += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * self.doc_len[i] / self.avg_len))
        return scores

    def context_for(self, unit: dict) -> str:
        """Text shown to the generator. A video passage and its board reading travel together."""
        sibling = self.by_id.get(unit["locator"].get("sibling", ""))
        if not sibling:
            return unit["text"]
        speech, board = (unit, sibling) if unit["kind"] == "transcript" else (sibling, unit)
        return f"Spoken: {speech['text']}\n\n{board['text']}"

    def search(
        self,
        query: str,
        k: int = 6,
        pool: int = 24,
        source_ids: set[str] | None = None,
        concept_ids: set[str] | None = None,
        use_rerank: bool = True,
        mode: str = "hybrid",
    ) -> list[Hit]:
        """Top-k units for a query. `mode` is hybrid | dense | lexical (the last two for ablations)."""
        if not self.units:
            return []
        allowed = np.ones(len(self.units), dtype=bool)
        if source_ids:
            allowed &= np.array([u["source_id"] in source_ids for u in self.units])
        if concept_ids:
            allowed &= np.array([bool(concept_ids & set(self.unit_concepts.get(u["id"], []))) for u in self.units])

        dense = self.matrix @ embed.embed_query(query) if mode != "lexical" else np.zeros(len(self.units))
        lexical = self._bm25(query) if mode != "dense" else np.zeros(len(self.units))
        dense_order = [i for i in np.argsort(-dense) if allowed[i]][:pool] if mode != "lexical" else []
        lexical_order = [i for i in np.argsort(-lexical) if allowed[i] and lexical[i] > 0][:pool] if mode != "dense" else []
        dense_rank = {i: r for r, i in enumerate(dense_order)}
        lexical_rank = {i: r for r, i in enumerate(lexical_order)}

        # Reciprocal-rank fusion: robust to the two scores living on different scales.
        fused: dict[int, float] = {}
        for ranking in (dense_rank, lexical_rank):
            for i, rank in ranking.items():
                fused[i] = fused.get(i, 0.0) + 1.0 / (60 + rank)
        candidates = sorted(fused, key=lambda i: -fused[i])[:pool]

        # A passage and its board reading describe the same moment; keep the better-ranked one.
        seen_moments: set[tuple] = set()
        unique = []
        for i in candidates:
            unit = self.units[i]
            moment = (unit["source_id"], unit["locator"].get("t_start")) if "t_start" in unit["locator"] else (unit["id"],)
            if moment in seen_moments:
                continue
            seen_moments.add(moment)
            unique.append(i)

        contexts = [self.context_for(self.units[i]) for i in unique]
        if use_rerank:
            scores = embed.rerank(query, [f"{self.units[i]['section'] or ''}\n{c}" for i, c in zip(unique, contexts)])
        else:
            scores = [fused[i] for i in unique]
        ranked = sorted(zip(unique, contexts, scores), key=lambda item: -item[2])[:k]
        return [
            Hit(unit=self.units[i], score=score, dense_rank=dense_rank.get(i), lexical_rank=lexical_rank.get(i), context=context)
            for i, context, score in ranked
        ]


_indexes: dict[str, Index] = {}
_indexes_lock = threading.Lock()


def index_for(course_id: str, db: Database) -> Index:
    with _indexes_lock:
        if course_id not in _indexes:
            _indexes[course_id] = Index(db)
        return _indexes[course_id]

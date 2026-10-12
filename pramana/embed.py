"""Local text embeddings and cross-encoder re-ranking (ONNX on CPU, no API calls)."""
from __future__ import annotations

import threading

import numpy as np

from .config import settings

_lock = threading.Lock()
# onnxruntime sessions are thread-safe, but serialising keeps CPU use predictable under the API server.
_lock_for_inference = threading.Lock()
_embedder = None
_reranker = None


def _model_dir() -> str:
    """Where the two local models are kept. fastembed's own default is the system's temporary
    folder, which the system empties: the models then download again at the next start."""
    path = settings.data_dir / "models" / "fastembed"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _get_embedder():
    global _embedder
    with _lock:
        if _embedder is None:
            from fastembed import TextEmbedding

            _embedder = TextEmbedding(settings.embed_model, cache_dir=_model_dir())
        return _embedder


def _get_reranker():
    global _reranker
    with _lock:
        if _reranker is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            _reranker = TextCrossEncoder(settings.rerank_model, cache_dir=_model_dir())
        return _reranker


def _unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / np.maximum(norms, 1e-12)).astype(np.float32)


def embed_passages(texts: list[str]) -> np.ndarray:
    """Unit-length vectors, one row per text."""
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    with _lock_for_inference:
        return _unit(np.array(list(_get_embedder().embed(texts, batch_size=32))))


def embed_query(text: str) -> np.ndarray:
    with _lock_for_inference:
        return _unit(np.array(list(_get_embedder().query_embed([text]))))[0]


def rerank(query: str, passages: list[str]) -> list[float]:
    """Relevance logit per passage (higher is better; around 0 is the relevant/irrelevant boundary)."""
    if not passages:
        return []
    with _lock_for_inference:
        return [float(score) for score in _get_reranker().rerank(query, passages)]


def to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)

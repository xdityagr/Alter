"""Embedding module for semantic memory search.

Provides a singleton Embedder that shares the SentenceTransformer model
with search_pipeline.py to avoid loading it twice.
"""
from __future__ import annotations

import struct
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_lock = threading.Lock()
_model: "SentenceTransformer | None" = None

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


def _get_model() -> "SentenceTransformer":
    """Lazy-load the sentence-transformer model (singleton)."""
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        # Reuse the global from search_pipeline if already loaded
        try:
            import sys
            sp = sys.modules.get("alter.core.agents.search_pipeline")
            if sp is not None:
                rm = getattr(sp, "_RANKER_MODEL", None)
                if rm is not None:
                    _model = rm
                    return _model
        except Exception:
            pass
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _try_inject_model(m: "SentenceTransformer") -> None:
    """Allow search_pipeline to inject its model so we don't load twice."""
    global _model
    if _model is None:
        _model = m


class Embedder:
    """Thin wrapper around SentenceTransformer for memory embeddings.

    All public methods are thread-safe. The model is loaded once on first use.
    Output vectors are 384-dimensional float32.
    """

    dim: int = EMBEDDING_DIM

    def encode(self, text: str) -> bytes:
        """Encode text to a serialised float32 byte string (for sqlite-vec)."""
        vec = self.encode_list(text)
        return struct.pack(f"{len(vec)}f", *vec)

    def encode_list(self, text: str) -> list[float]:
        """Encode text to a raw Python list of floats."""
        model = _get_model()
        vec = model.encode(text, convert_to_numpy=True)
        return [float(x) for x in vec]

    def encode_batch(self, texts: list[str]) -> list[bytes]:
        """Encode multiple texts, returning serialised byte strings."""
        model = _get_model()
        vecs = model.encode(texts, convert_to_numpy=True)
        results: list[bytes] = []
        for v in vecs:
            results.append(struct.pack(f"{len(v)}f", *[float(x) for x in v]))
        return results

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Pure-Python cosine similarity (for tests / small comparisons)."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

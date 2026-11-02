"""Sentence embedders behind one small interface.

`HashingEmbedder` is the default: deterministic, no download, no network. It hashes
words and character 4-grams into a fixed vector, so it catches shared word stems but
not true synonyms. `FastEmbedEmbedder` runs a real sentence model through fastembed
and is opt-in (`EMBEDDER=fastembed`, plus `pip install -r requirements-fastembed.txt`).

Each embedder carries its own `abstain_cosine`, because cosine scales differ per model.
"""
from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np

_WORD = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    abstain_cosine: float

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def _unit(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    return v / norm if norm else v


class HashingEmbedder:
    abstain_cosine = 0.5

    def __init__(self, dim: int = 2048):
        self.dim = dim

    def _features(self, text: str) -> list[str]:
        feats: list[str] = []
        for word in _WORD.findall(text.lower()):
            feats.append(f"w:{word}")
            feats.extend(f"c:{word[i:i + 4]}" for i in range(len(word) - 3))
        return feats

    def _embed(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, np.float32)
        for feat in self._features(text):
            # blake2b, not hash(): Python randomises str hashes per process.
            digest = hashlib.blake2b(feat.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % self.dim
            v[bucket] += 1.0 if digest[4] & 1 else -1.0
        return _unit(v)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), np.float32)
        return np.stack([self._embed(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed(text)


class FastEmbedEmbedder:
    abstain_cosine = 0.72

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding  # optional dependency

        self._model = TextEmbedding(model)
        self.dim = len(next(iter(self._model.embed(["probe"]))))

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), np.float32)
        return np.stack([_unit(np.asarray(v, np.float32)) for v in self._model.embed(texts)])

    def embed_query(self, text: str) -> np.ndarray:
        return _unit(np.asarray(next(iter(self._model.query_embed(text))), np.float32))


class CachingEmbedder:
    """Remembers document vectors by text, so shared notes embed once across all users."""

    def __init__(self, inner: Embedder):
        self.inner = inner
        self.abstain_cosine = inner.abstain_cosine
        self._vectors: dict[str, np.ndarray] = {}

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        missing = [t for t in dict.fromkeys(texts) if t not in self._vectors]
        if missing:
            self._vectors.update(zip(missing, self.inner.embed_documents(missing)))
        if not texts:
            return self.inner.embed_documents([])
        return np.stack([self._vectors[t] for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self.inner.embed_query(text)


def make_embedder(backend: str) -> Embedder:
    if backend == "hash":
        return CachingEmbedder(HashingEmbedder())
    if backend == "fastembed":
        return CachingEmbedder(FastEmbedEmbedder())
    raise ValueError(f"Unknown embedder backend: {backend}")

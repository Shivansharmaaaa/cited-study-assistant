"""Sentence-level retrieval: BM25 (lexical), dense (embeddings) and a hybrid of both.

BM25 is pure Python and deterministic. The dense retriever scores cosine similarity
between sentence embeddings. The hybrid fuses the two rankings with Reciprocal Rank
Fusion (RRF), which needs no score calibration between the two scorers.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .embeddings import Embedder

STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "to", "and", "or", "is", "are", "was",
    "were", "by", "for", "with", "as", "at", "it", "its", "that", "this", "be",
    "what", "which", "who", "how", "does", "do", "did", "from", "under",
}

_TOKEN = re.compile(r"[a-z0-9]+")
RRF_K = 60


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


def split_sentences(text: str) -> list[str]:
    # Not after an initial ("B. R. Ambedkar") or a short form ("Dr", "v." in case names).
    parts = re.split(r"(?<=[.!?])(?<!\b[A-Z]\.)(?<!\bDr\.)(?<!\bv\.)\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


@dataclass
class Passage:
    note_id: str
    title: str
    sentence: str
    tokens: list[str]


@dataclass
class Hit:
    note_id: str
    title: str
    sentence: str
    score: float          # the ranking score used for ordering (BM25, cosine or RRF)
    bm25: float = 0.0     # raw BM25 score, kept so abstain logic can use the lexical signal
    dense: float = 0.0    # raw cosine similarity, kept for the semantic signal


class BM25Retriever:
    abstain_cosine: float | None = None  # lexical only: no dense signal

    def __init__(self, notes: list[dict], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.passages: list[Passage] = []
        for note in notes:
            for sentence in split_sentences(note["text"]):
                # Title tokens are prepended so a sentence keeps its topic context.
                toks = tokenize(note["title"] + " " + sentence)
                self.passages.append(Passage(note["id"], note["title"], sentence, toks))
        n = len(self.passages)
        self.avg_len = sum(len(p.tokens) for p in self.passages) / max(n, 1)
        df: Counter[str] = Counter()
        for p in self.passages:
            df.update(set(p.tokens))
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    @classmethod
    def from_file(cls, path: str | Path) -> "BM25Retriever":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def _score(self, query_tokens: list[str], passage: Passage) -> float:
        tf = Counter(passage.tokens)
        length_norm = 1 - self.b + self.b * len(passage.tokens) / self.avg_len
        score = 0.0
        for t in query_tokens:
            if t not in tf:
                continue
            freq = tf[t]
            score += self.idf.get(t, 0.0) * (freq * (self.k1 + 1)) / (freq + self.k1 * length_norm)
        return score

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        return [self._score(q, p) for p in self.passages] if q else [0.0] * len(self.passages)

    def search(self, query: str, k: int = 3) -> list[Hit]:
        scored = [(s, p) for s, p in zip(self.scores(query), self.passages) if s > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [Hit(p.note_id, p.title, p.sentence, round(s, 3), bm25=round(s, 3))
                for s, p in scored[:k]]


class HybridRetriever:
    """BM25 + dense embeddings, fused with Reciprocal Rank Fusion."""

    def __init__(self, notes: list[dict], embedder: Embedder, candidates: int = 20):
        self.bm25 = BM25Retriever(notes)
        self.passages = self.bm25.passages
        self.embedder = embedder
        self.abstain_cosine = embedder.abstain_cosine
        self.candidates = candidates
        texts = [f"{p.title}. {p.sentence}" for p in self.passages]
        self.matrix = embedder.embed_documents(texts)

    def dense_scores(self, query: str) -> np.ndarray:
        if not len(self.passages):
            return np.zeros(0, np.float32)
        return self.matrix @ self.embedder.embed_query(query)

    def search(self, query: str, k: int = 3) -> list[Hit]:
        if not self.passages or not tokenize(query):
            return []
        bm = np.array(self.bm25.scores(query))
        de = self.dense_scores(query)
        fused: dict[int, float] = {}
        for rank, i in enumerate(i for i in np.argsort(-bm)[: self.candidates] if bm[i] > 0):
            fused[int(i)] = fused.get(int(i), 0.0) + 1.0 / (RRF_K + rank + 1)
        for rank, i in enumerate(np.argsort(-de)[: self.candidates]):
            fused[int(i)] = fused.get(int(i), 0.0) + 1.0 / (RRF_K + rank + 1)
        order = sorted(fused, key=lambda i: fused[i], reverse=True)[:k]
        return [Hit(self.passages[i].note_id, self.passages[i].title, self.passages[i].sentence,
                    round(fused[i], 5), bm25=round(float(bm[i]), 3), dense=round(float(de[i]), 3))
                for i in order]


class DenseRetriever(HybridRetriever):
    """Dense only. Exists so the eval harness can compare all three strategies."""

    def search(self, query: str, k: int = 3) -> list[Hit]:
        if not self.passages or not tokenize(query):
            return []
        de = self.dense_scores(query)
        bm = self.bm25.scores(query)
        return [Hit(self.passages[i].note_id, self.passages[i].title, self.passages[i].sentence,
                    round(float(de[i]), 3), bm25=round(float(bm[i]), 3), dense=round(float(de[i]), 3))
                for i in np.argsort(-de)[:k]]

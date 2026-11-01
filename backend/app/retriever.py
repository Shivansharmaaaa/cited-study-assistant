"""Sentence-level BM25 retriever with citations and an abstain threshold.

Pure Python on purpose: no model downloads, deterministic, easy to test and to
explain in an interview.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "to", "and", "or", "is", "are", "was",
    "were", "by", "for", "with", "as", "at", "it", "its", "that", "this", "be",
    "what", "which", "who", "how", "does", "do", "did", "from", "under",
}

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
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
    score: float


class BM25Retriever:
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

    def search(self, query: str, k: int = 3) -> list[Hit]:
        q = tokenize(query)
        if not q:
            return []
        scored = [(self._score(q, p), p) for p in self.passages]
        scored = [(s, p) for s, p in scored if s > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [Hit(p.note_id, p.title, p.sentence, round(s, 3)) for s, p in scored[:k]]

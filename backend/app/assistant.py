"""Cited answer composer with an abstain rule.

Design choice: the assistant never writes free text. It only returns sentences
that exist in the notes, each tagged with a citation number. If retrieval is
weak it refuses instead of guessing. That makes every claim traceable and the
behaviour easy to test.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from .retriever import BM25Retriever, Hit

ABSTAIN_THRESHOLD = 2.0  # below this top score the assistant refuses to answer
RELATIVE_CUTOFF = 0.5  # extra citations must score >= 50% of the top hit


@dataclass
class Citation:
    ref: int
    note_id: str
    title: str
    sentence: str
    score: float


@dataclass
class Answer:
    question: str
    answered: bool
    text: str
    citations: list[Citation]

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _dedupe(hits: list[Hit]) -> list[Hit]:
    seen, out = set(), []
    for h in hits:
        if h.sentence not in seen:
            seen.add(h.sentence)
            out.append(h)
    return out


def answer(question: str, retriever: BM25Retriever, k: int = 3,
           threshold: float = ABSTAIN_THRESHOLD) -> Answer:
    hits = _dedupe(retriever.search(question, k=k))
    if hits:
        # Drop weak trailing hits: a sentence must score at least RELATIVE_CUTOFF
        # of the best hit to be cited. Stops one shared word pulling in noise.
        floor = hits[0].score * RELATIVE_CUTOFF
        hits = [h for h in hits if h.score >= floor]
    if not hits or hits[0].score < threshold:
        return Answer(
            question=question,
            answered=False,
            text="I can't answer that from the notes I have. Try rephrasing, or add a note on this topic.",
            citations=[],
        )
    citations, parts = [], []
    for i, h in enumerate(hits, start=1):
        citations.append(Citation(i, h.note_id, h.title, h.sentence, h.score))
        parts.append(f"{h.sentence} [{i}]")
    return Answer(question=question, answered=True, text=" ".join(parts), citations=citations)

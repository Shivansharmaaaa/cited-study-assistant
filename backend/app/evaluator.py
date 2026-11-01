"""Rubric-based answer evaluator.

A rubric is a list of key points; each key point lists acceptable keyword
variants. A key point counts as covered if any variant appears in the answer
(after lowercasing). Score = covered / total. Feedback names what was missed.

This is deliberately simple and transparent. It is not an LLM grader, and the
README says so: the point is a reproducible baseline you can unit test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class KeyPoint:
    label: str
    variants: list[str]


@dataclass
class Evaluation:
    score: float
    covered: list[str]
    missed: list[str]
    feedback: str


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def evaluate(answer_text: str, rubric: list[KeyPoint]) -> Evaluation:
    if not rubric:
        raise ValueError("rubric must contain at least one key point")
    text = _norm(answer_text)
    covered, missed = [], []
    for kp in rubric:
        if any(_norm(v) in text for v in kp.variants):
            covered.append(kp.label)
        else:
            missed.append(kp.label)
    score = round(len(covered) / len(rubric), 2)
    if not missed:
        feedback = "All key points covered."
    else:
        feedback = "Missing: " + "; ".join(missed) + "."
    return Evaluation(score, covered, missed, feedback)


def rubric_from_dicts(items: list[dict]) -> list[KeyPoint]:
    return [KeyPoint(i["label"], list(i["variants"])) for i in items]

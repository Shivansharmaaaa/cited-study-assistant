"""Rubric-based answer evaluator.

A rubric is a list of key points; each key point lists acceptable keyword
variants. A key point counts as covered if any variant appears in the answer
(after lowercasing). Score = covered / total. Feedback names what was missed.

This is deliberately simple and transparent: a reproducible baseline you can unit
test, and the fallback whenever the LLM grader (grader.py) is off or fails.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


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
    grader: str = "keyword"  # "keyword" or "claude"
    evidence: dict[str, str] = field(default_factory=dict)  # label -> verified quote
    rejected: list[str] = field(default_factory=list)  # claimed covered, quote not found


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def feedback_for(missed: list[str]) -> str:
    return "Missing: " + "; ".join(missed) + "." if missed else "All key points covered."


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
    return Evaluation(score, covered, missed, feedback_for(missed))


def rubric_from_dicts(items: list[dict]) -> list[KeyPoint]:
    return [KeyPoint(i["label"], list(i["variants"])) for i in items]

"""SM-2-style spaced repetition.

quality is 0-5 (derived from the rubric score). Below 3 the card lapses: the
streak resets and it comes back tomorrow. Otherwise the interval grows 1 -> 6 ->
previous * ease days, and ease drifts with how hard the recall was (floor 1.3).
"""
from __future__ import annotations

from dataclasses import dataclass

MIN_EASE = 1.3


@dataclass(frozen=True)
class SrsState:
    ease: float = 2.5
    interval_days: int = 0
    repetitions: int = 0


def quality_from_score(score: float) -> int:
    if not 0.0 <= score <= 1.0:
        raise ValueError("score must be between 0 and 1")
    return round(score * 5)


def next_state(state: SrsState, quality: int) -> SrsState:
    if not 0 <= quality <= 5:
        raise ValueError("quality must be between 0 and 5")
    if quality < 3:
        return SrsState(ease=state.ease, interval_days=1, repetitions=0)
    if state.repetitions == 0:
        interval = 1
    elif state.repetitions == 1:
        interval = 6
    else:
        interval = max(1, round(state.interval_days * state.ease))
    ease = state.ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    return SrsState(ease=max(MIN_EASE, round(ease, 4)), interval_days=interval,
                    repetitions=state.repetitions + 1)

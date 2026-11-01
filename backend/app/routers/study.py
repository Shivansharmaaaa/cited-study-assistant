from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..assistant import answer
from ..deps import current_user, get_db
from ..evaluator import evaluate, rubric_from_dicts
from ..models import Attempt, Question, ReviewState, User, utcnow
from ..schemas import (AskIn, AttemptIn, AttemptOut, QuestionIn, QuestionOut, StatsOut, TopicStat)
from ..srs import SrsState, next_state, quality_from_score

router = APIRouter(tags=["study"])


def _visible_question(db: Session, user: User, question_id: int) -> Question:
    q = db.get(Question, question_id)
    if q is None or q.owner_id not in (None, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    return q


def _qout(q: Question) -> QuestionOut:
    return QuestionOut(id=q.id, topic=q.topic, prompt=q.prompt, shared=q.owner_id is None)


@router.post("/ask")
def ask(body: AskIn, request: Request, user: User = Depends(current_user),
        db: Session = Depends(get_db)) -> dict:
    retriever = request.app.state.index_cache.get(db, user.id)
    return answer(body.question, retriever).to_dict()


@router.get("/questions", response_model=list[QuestionOut])
def list_questions(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[QuestionOut]:
    rows = db.scalars(
        select(Question).where(or_(Question.owner_id.is_(None), Question.owner_id == user.id))
        .order_by(Question.id)
    ).all()
    return [_qout(q) for q in rows]


@router.post("/questions", response_model=QuestionOut, status_code=status.HTTP_201_CREATED)
def create_question(body: QuestionIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)) -> QuestionOut:
    q = Question(owner_id=user.id, topic=body.topic, prompt=body.prompt,
                 rubric_json=json.dumps([kp.model_dump() for kp in body.rubric]))
    db.add(q)
    db.commit()
    return _qout(q)


@router.post("/questions/{question_id}/attempts", response_model=AttemptOut,
             status_code=status.HTTP_201_CREATED)
def submit_attempt(question_id: int, body: AttemptIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> AttemptOut:
    q = _visible_question(db, user, question_id)
    result = evaluate(body.answer, rubric_from_dicts(json.loads(q.rubric_json)))

    state_row = db.scalar(select(ReviewState).where(
        ReviewState.user_id == user.id, ReviewState.question_id == q.id))
    if state_row is None:
        # Explicit initial values: column defaults are only applied at flush, and we
        # need to read these fields before that to compute the next state.
        state_row = ReviewState(user_id=user.id, question_id=q.id, ease=2.5,
                                interval_days=0, repetitions=0)
        db.add(state_row)
    new = next_state(SrsState(state_row.ease, state_row.interval_days, state_row.repetitions),
                     quality_from_score(result.score))
    state_row.ease, state_row.interval_days, state_row.repetitions = (
        new.ease, new.interval_days, new.repetitions)
    state_row.due_at = utcnow() + timedelta(days=new.interval_days)

    attempt = Attempt(user_id=user.id, question_id=q.id, answer=body.answer, score=result.score,
                      missed_json=json.dumps(result.missed))
    db.add(attempt)
    db.commit()  # attempt and schedule change land together or not at all
    return AttemptOut(attempt_id=attempt.id, score=result.score, covered=result.covered,
                      missed=result.missed, feedback=result.feedback,
                      interval_days=new.interval_days, next_due_at=state_row.due_at)


@router.get("/review/due", response_model=list[QuestionOut])
def due_questions(limit: int = Query(10, ge=1, le=50), user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> list[QuestionOut]:
    """Questions never attempted come first, then those whose due time has passed."""
    now = utcnow()
    rows = db.execute(
        select(Question, ReviewState.due_at)
        .outerjoin(ReviewState, (ReviewState.question_id == Question.id) & (ReviewState.user_id == user.id))
        .where(or_(Question.owner_id.is_(None), Question.owner_id == user.id))
        .where(or_(ReviewState.id.is_(None), ReviewState.due_at <= now))
        .order_by(ReviewState.due_at.is_not(None), ReviewState.due_at, Question.id)
        .limit(limit)
    ).all()
    return [_qout(q) for q, _ in rows]


@router.get("/stats", response_model=StatsOut)
def stats(user: User = Depends(current_user), db: Session = Depends(get_db)) -> StatsOut:
    per_topic = db.execute(
        select(Question.topic, func.count(Attempt.id), func.avg(Attempt.score))
        .join(Question, Question.id == Attempt.question_id)
        .where(Attempt.user_id == user.id)
        .group_by(Question.topic)
    ).all()
    topics = sorted(
        (TopicStat(topic=t, attempts=n, average_score=round(float(avg), 2)) for t, n, avg in per_topic),
        key=lambda s: (s.average_score, s.topic),
    )
    total = sum(t.attempts for t in topics)
    overall = db.scalar(select(func.avg(Attempt.score)).where(Attempt.user_id == user.id))
    now = utcnow()
    due_now = db.scalar(
        select(func.count()).select_from(Question)
        .outerjoin(ReviewState, (ReviewState.question_id == Question.id) & (ReviewState.user_id == user.id))
        .where(or_(Question.owner_id.is_(None), Question.owner_id == user.id))
        .where(or_(ReviewState.id.is_(None), ReviewState.due_at <= now))
    )
    return StatsOut(
        total_attempts=total,
        average_score=round(float(overall), 2) if overall is not None else 0.0,
        due_now=due_now or 0,
        topics=topics,
        weakest_topics=[t.topic for t in topics if t.average_score < 0.7][:3],
    )

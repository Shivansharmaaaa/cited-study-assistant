from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=10, max_length=20_000)


class NoteOut(BaseModel):
    id: int
    title: str
    text: str
    shared: bool


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class KeyPointIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    variants: list[str] = Field(min_length=1, max_length=10)


class QuestionIn(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=5, max_length=1000)
    rubric: list[KeyPointIn] = Field(min_length=1, max_length=20)


class QuestionOut(BaseModel):
    id: int
    topic: str
    prompt: str
    shared: bool


class AttemptIn(BaseModel):
    answer: str = Field(min_length=1, max_length=5000)


class AttemptOut(BaseModel):
    attempt_id: int
    score: float
    covered: list[str]
    missed: list[str]
    feedback: str
    interval_days: int
    next_due_at: datetime
    grader: str
    evidence: dict[str, str]
    rejected: list[str]


class TopicStat(BaseModel):
    topic: str
    attempts: int
    average_score: float


class StatsOut(BaseModel):
    total_attempts: int
    average_score: float
    due_now: int
    topics: list[TopicStat]
    weakest_topics: list[str]

"""Seed shared notes and practice questions on first boot (idempotent)."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Note, Question

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(Note).where(Note.owner_id.is_(None))) == 0:
        for n in json.loads((DATA_DIR / "notes.json").read_text(encoding="utf-8")):
            db.add(Note(owner_id=None, title=n["title"], text=n["text"]))
    if db.scalar(select(func.count()).select_from(Question).where(Question.owner_id.is_(None))) == 0:
        for q in json.loads((DATA_DIR / "questions.json").read_text(encoding="utf-8")):
            db.add(Question(owner_id=None, topic=q["topic"], prompt=q["prompt"],
                            rubric_json=json.dumps(q["rubric"])))
    db.commit()

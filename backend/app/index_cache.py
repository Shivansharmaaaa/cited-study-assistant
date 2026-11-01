"""Per-user BM25 index cache.

Building an index is O(total sentences). Caching it per user and rebuilding only
when notes change keeps /ask cheap. `version` is bumped on every note write; a
cached entry is valid only if it was built at the current version. Single-process
only: with several workers you would key on a DB-side version counter instead.
"""
from __future__ import annotations

import threading

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Note
from .retriever import BM25Retriever


class IndexCache:
    def __init__(self) -> None:
        self._version = 0
        self._entries: dict[int, tuple[int, BM25Retriever]] = {}
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        with self._lock:
            self._version += 1

    def get(self, db: Session, user_id: int) -> BM25Retriever:
        with self._lock:
            cached = self._entries.get(user_id)
            if cached and cached[0] == self._version:
                return cached[1]
            version = self._version
        rows = db.scalars(
            select(Note).where(or_(Note.owner_id.is_(None), Note.owner_id == user_id)).order_by(Note.id)
        ).all()
        retriever = BM25Retriever(
            [{"id": f"N{n.id}", "title": n.title, "text": n.text} for n in rows]
        )
        with self._lock:
            self._entries[user_id] = (version, retriever)
        return retriever

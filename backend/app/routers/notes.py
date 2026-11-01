from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..deps import current_user, get_db
from ..models import Note, User
from ..schemas import NoteIn, NoteOut

router = APIRouter(prefix="/notes", tags=["notes"])


def _out(n: Note) -> NoteOut:
    return NoteOut(id=n.id, title=n.title, text=n.text, shared=n.owner_id is None)


@router.get("", response_model=list[NoteOut])
def list_notes(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[NoteOut]:
    rows = db.scalars(
        select(Note).where(or_(Note.owner_id.is_(None), Note.owner_id == user.id)).order_by(Note.id)
    ).all()
    return [_out(n) for n in rows]


@router.post("", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
def create_note(body: NoteIn, request: Request, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> NoteOut:
    note = Note(owner_id=user.id, title=body.title, text=body.text)
    db.add(note)
    db.commit()
    request.app.state.index_cache.invalidate()
    return _out(note)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: int, request: Request, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> None:
    note = db.get(Note, note_id)
    # Shared seed notes and other users' notes both look like "not found".
    if note is None or note.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note not found")
    db.delete(note)
    db.commit()
    request.app.state.index_cache.invalidate()

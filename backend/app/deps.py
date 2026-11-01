"""Shared FastAPI dependencies: DB session and the authenticated user."""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .models import User
from .security import decode_token

_bearer = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Invalid or missing token", headers={"WWW-Authenticate": "Bearer"}
    )
    if creds is None:
        raise unauthorized
    user_id = decode_token(creds.credentials, request.app.state.settings.secret_key)
    if user_id is None:
        raise unauthorized
    user = db.get(User, user_id)
    if user is None:
        raise unauthorized
    return user

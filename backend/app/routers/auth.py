from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..deps import current_user, get_db
from ..models import User
from ..schemas import LoginIn, RegisterIn, TokenOut, UserOut
from ..security import create_token, hash_password, verify_password

router = APIRouter(tags=["auth"])

# Hashed once so a login for an unknown email costs the same as a wrong password,
# which stops response timing from revealing which emails are registered.
_DUMMY_HASH = hash_password("not-a-real-password")


@router.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> UserOut:
    email = body.email.lower()
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # unique index on email is the source of truth, not a pre-check
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    return UserOut(id=user.id, email=user.email)


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> TokenOut:
    throttle = request.app.state.throttle
    email = body.email.lower()
    if throttle.is_blocked(email):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts, try again later")
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        throttle.record_failure(email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    throttle.reset(email)
    settings = request.app.state.settings
    return TokenOut(access_token=create_token(user.id, settings.secret_key, settings.token_ttl_minutes))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email)

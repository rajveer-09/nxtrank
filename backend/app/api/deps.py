# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import User


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def session_fingerprint(user: User) -> str:
    """Stored in the session cookie; changes when the password is reset, which logs
    out existing sessions."""
    return user.password_hash[-16:]


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = request.session.get("uid")
    user = db.get(User, uid) if isinstance(uid, int) else None
    if user is None or not user.active or request.session.get("fp") != session_fingerprint(user):
        request.session.clear()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not logged in")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return user


def require_super(user: User = Depends(require_admin)) -> User:
    if not user.is_super:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the super admin can do this")
    return user

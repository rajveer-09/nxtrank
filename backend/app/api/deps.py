# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
import logging
import re
import time
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.config import Settings
from app.db.models import User
from app.services import view_as

log = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# allowed while viewing as an instructor: ending it, and the student page's live rating (a read)
VIEW_AS_ALLOWED = re.compile(r"/api/auth/(return|logout|login)|/api/students/\d+/rating/refresh")


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def session_fingerprint(user: User) -> str:
    """Stored in the session cookie; changes when the password is reset, which logs
    out existing sessions."""
    return user.password_hash[-16:]


def _signed_in(db: Session, uid, fp) -> User | None:
    user = db.get(User, uid) if isinstance(uid, int) else None
    return user if user is not None and user.active and fp == session_fingerprint(user) else None


def acting_admin(request: Request, db: Session) -> User | None:
    """The admin behind a "view as instructor" session, if this is one and it's still valid."""
    admin = _signed_in(db, request.session.get("acting_admin"), request.session.get("acting_fp"))
    return admin if admin is not None and admin.role == "admin" else None


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    store = request.session
    admin = None
    if "acting_admin" in store:
        admin = acting_admin(request, db)
        if admin is None:  # the admin was removed or their password reset meanwhile
            store.clear()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not logged in")
        if time.time() > store.get("acting_until", 0):
            view_as.end(store, db, admin, session_fingerprint, "expired after 60 minutes")
            return admin
    user = _signed_in(db, store.get("uid"), store.get("fp"))
    if user is None:
        if admin is not None:  # the instructor was switched off or changed: back to the admin
            view_as.end(store, db, admin, session_fingerprint, "the instructor's login changed")
            return admin
        store.clear()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not logged in")
    if admin is not None:
        log.info("%s %s by %s, viewing as %s", request.method, request.url.path, admin.username, user.username)
        if request.method not in SAFE_METHODS and not VIEW_AS_ALLOWED.fullmatch(request.url.path):
            raise ApiError(403, f"You're viewing as {user.display_name or user.username}; return to your "
                                "admin account to make changes.", "viewing_as")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return user


def require_super(user: User = Depends(require_admin)) -> User:
    if not user.is_super:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the super admin can do this")
    return user

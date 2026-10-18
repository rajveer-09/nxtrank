# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.fastjson import FastJSONRoute
from app.api.deps import acting_admin, current_user, get_db, get_settings, session_fingerprint
from app.config import Settings
from app.db.models import LoginFailure, User, utcnow
from app.services import view_as
from app.services.users import authenticate

log = logging.getLogger(__name__)

router = APIRouter(route_class=FastJSONRoute, prefix="/api/auth", tags=["auth"])

MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)


class LoginBody(BaseModel):
    username: str
    password: str


def _user_json(user: User, settings: Settings, viewing_as: dict | None = None) -> dict:
    return {"username": user.username, "role": user.role, "name": user.display_name, "is_super": user.is_super,
            "scans_enabled": settings.scans_enabled, "viewing_as": viewing_as}


def _throttle_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "?"
    return f"{host}|{username.strip().lower()}"


@router.post("/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db),
          settings: Settings = Depends(get_settings)) -> dict:
    key = _throttle_key(request, body.username)[:200]
    now = utcnow()
    # failures older than the window no longer count, for anyone
    db.execute(delete(LoginFailure).where(LoginFailure.at < now - FAILURE_WINDOW))
    failures = db.scalar(select(func.count()).select_from(LoginFailure).where(LoginFailure.key == key))
    if failures >= MAX_FAILURES:
        db.commit()
        log.warning("login throttled for %r from %s", body.username.strip().lower(), key.split("|")[0])
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "too many failed logins; try again in 15 minutes")

    user = authenticate(db, body.username, body.password)
    if user is None:
        db.add(LoginFailure(key=key, at=now))
        db.commit()
        log.warning("failed login for %r from %s", body.username.strip().lower(), key.split("|")[0])
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong username or password")
    db.execute(delete(LoginFailure).where(LoginFailure.key == key))
    db.commit()
    request.session.clear()
    request.session.update({"uid": user.id, "fp": session_fingerprint(user)})
    log.info("login %s (%s)", user.username, user.role)
    return _user_json(user, settings)


@router.post("/logout")
def logout(request: Request) -> dict:
    log.info("logout (user id %s)", request.session.get("uid"))
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db),
       settings: Settings = Depends(get_settings)) -> dict:
    viewing = view_as.summary(request.session, db) if "acting_admin" in request.session else None
    return _user_json(user, settings, viewing)


@router.post("/return")
def return_to_admin(request: Request, db: Session = Depends(get_db),
                    settings: Settings = Depends(get_settings)) -> dict:
    """Ends "view as instructor": back to the admin's own account."""
    if "acting_admin" not in request.session:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not viewing as anyone")
    admin = acting_admin(request, db)
    if admin is None:
        request.session.clear()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not logged in")
    view_as.end(request.session, db, admin, session_fingerprint, "returned to admin")
    return _user_json(admin, settings)

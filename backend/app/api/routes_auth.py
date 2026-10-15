# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.fastjson import FastJSONRoute
from app.api.deps import current_user, get_db, session_fingerprint
from app.db.models import User
from app.services.users import authenticate

log = logging.getLogger(__name__)

router = APIRouter(route_class=FastJSONRoute, prefix="/api/auth", tags=["auth"])

MAX_FAILURES = 5
FAILURE_WINDOW_SECS = 15 * 60
_failures: dict[str, deque[float]] = defaultdict(deque)


class LoginBody(BaseModel):
    username: str
    password: str


def _user_json(user: User) -> dict:
    return {"username": user.username, "role": user.role, "name": user.display_name, "is_super": user.is_super}


def _throttle_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "?"
    return f"{host}|{username.strip().lower()}"


@router.post("/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)) -> dict:
    key = _throttle_key(request, body.username)
    attempts = _failures[key]
    now = time.monotonic()
    while attempts and now - attempts[0] > FAILURE_WINDOW_SECS:
        attempts.popleft()
    if len(attempts) >= MAX_FAILURES:
        log.warning("login throttled for %r from %s", body.username.strip().lower(), key.split("|")[0])
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "too many failed logins; try again in 15 minutes")

    user = authenticate(db, body.username, body.password)
    if user is None:
        attempts.append(now)
        log.warning("failed login for %r from %s", body.username.strip().lower(), key.split("|")[0])
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong username or password")
    _failures.pop(key, None)
    request.session.clear()
    request.session.update({"uid": user.id, "fp": session_fingerprint(user)})
    log.info("login %s (%s)", user.username, user.role)
    return _user_json(user)


@router.post("/logout")
def logout(request: Request) -> dict:
    log.info("logout (user id %s)", request.session.get("uid"))
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return _user_json(user)

# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Dashboard users and password hashing (stdlib scrypt)."""

import base64
import hashlib
import hmac
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User

log = logging.getLogger(__name__)

ROLES = ("admin", "instructor", "viewer")
_N, _R, _P = 2**14, 8, 1
MIN_PASSWORD_LENGTH = 10


class UserError(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt),
                                n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Verified against when the username doesn't exist, so timing doesn't reveal it.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = session.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None or not user.active:
        verify_password(password, _DUMMY_HASH)
        return None
    return user if verify_password(password, user.password_hash) else None


def set_user(session: Session, username: str, password: str, role: str, *,
             is_super: bool | None = None, actor: str = "cli", via: str = "cli") -> tuple[User, bool]:
    """Create the user, or reset password/role if it exists (the server's command line:
    this is also how the super admin is changed). Returns (user, created). Commits."""
    from app.services.roster_admin import audit

    username = username.strip().lower()
    if not username:
        raise UserError("username is empty")
    if role not in ROLES:
        raise UserError(f"role must be one of {ROLES}")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise UserError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    user = session.scalar(select(User).where(User.username == username))
    created = user is None
    if created:
        user = User(username=username)
        session.add(user)
    user.password_hash = hash_password(password)
    user.role = role
    user.active = True
    if is_super is not None:
        user.is_super = is_super and role == "admin"
    audit(user, actor, via, created=created)
    session.commit()
    log.info("login %s %s as %s by %s (%s)", username, "created" if created else "reset", role, actor, via)
    return user, created

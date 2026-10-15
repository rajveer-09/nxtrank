# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Admin logins, managed by admins on the dashboard. Admins can add, edit, deactivate
and delete each other -- except the super admin (User.is_super), whom nobody can
change from the dashboard, and their own login, which they can't deactivate or delete.
Every change records when, by whom and how."""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import User
from app.services.roster_admin import audit, audit_json
from app.services.users import MIN_PASSWORD_LENGTH, hash_password

log = logging.getLogger(__name__)

ROLE = "admin"


class AdminError(Exception):
    pass


class ProtectedError(AdminError):
    """The super admin can't be changed from the dashboard."""


def admin_json(user: User, me: User) -> dict:
    return {
        "id": user.id, "email": user.username, "name": user.display_name or user.username,
        "active": user.active, "is_super": user.is_super, "is_you": user.id == me.id,
        "editable": not user.is_super, **audit_json(user),
    }


def list_admins(session: Session, me: User) -> list[dict]:
    users = session.scalars(select(User).where(User.role == ROLE)
                            .order_by(User.is_super.desc(), func.lower(User.display_name), User.username))
    return [admin_json(u, me) for u in users]


def get_admin(session: Session, user_id: int) -> User | None:
    user = session.get(User, user_id)
    return user if user is not None and user.role == ROLE else None


def _protect(user: User) -> None:
    if user.is_super:
        raise ProtectedError("the super admin can't be changed from the dashboard")


def save_admin(session: Session, *, user: User | None, email: str, name: str, password: str | None,
               active: bool, actor: User, via: str) -> User:
    """Create (user=None) or update an admin. Commits."""
    if user is not None:
        _protect(user)
        if user.id == actor.id and not active:
            raise AdminError("you can't deactivate your own login")
    email = email.strip().lower()
    name = " ".join(name.split())
    if not email or any(c.isspace() for c in email):
        raise AdminError("enter the admin's email (used to log in)")
    if not name:
        raise AdminError("enter the admin's name")
    taken = session.scalar(select(User).where(User.username == email))
    if taken is not None and taken is not user:
        raise AdminError(f"{email} already has a login")
    if user is None and not password:
        raise AdminError("set a password for the new admin")
    if password and len(password) < MIN_PASSWORD_LENGTH:
        raise AdminError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")

    created = user is None
    if user is None:
        user = User(username=email, role=ROLE)
        session.add(user)
    user.username, user.display_name, user.active = email, name, active
    if password:
        user.password_hash = hash_password(password)  # also signs out their open sessions
    audit(user, actor.username, via, created=created)
    session.commit()
    log.info("admin %s %s by %s (%s)", email, "added" if created else "updated", actor.username, via)
    return user


def delete_admin(session: Session, user: User, *, actor: User) -> None:
    """Remove an admin login for good. Commits."""
    _protect(user)
    if user.id == actor.id:
        raise AdminError("you can't delete your own login")
    session.delete(user)
    session.commit()
    log.info("admin %s deleted by %s", user.username, actor.username)

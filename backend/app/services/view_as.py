# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""An admin viewing the dashboard as one of the instructors, to check what they see.

The session then belongs to the instructor (`uid`, `fp`), and remembers the admin
(`acting_admin`, `acting_fp`) and when it ends (`acting_until`). It's read-only, lasts at
most an hour, and its start and end go into the audit log. The instructor's own login
and sessions aren't touched."""

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent, User, utcnow

log = logging.getLogger(__name__)

VIEW_AS_SECS = 60 * 60
ACTING_KEYS = ("acting_admin", "acting_fp", "acting_until")


def record(session: Session, actor: str, action: str, target: str | None = None, detail: str | None = None) -> None:
    """Adds an audit event (committed with the caller's transaction)."""
    session.add(AuditEvent(at=utcnow(), actor=actor, action=action, target=target, detail=detail))


def recent_events(session: Session, limit: int = 50) -> list[dict]:
    rows = session.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit))
    return [{"at": e.at.isoformat() if e.at else None, "actor": e.actor, "action": e.action,
             "target": e.target, "detail": e.detail} for e in rows]


def start(store: dict, session: Session, admin: User, instructor: User, fingerprint) -> None:
    store.clear()
    store.update({"uid": instructor.id, "fp": fingerprint(instructor), "acting_admin": admin.id,
                  "acting_fp": fingerprint(admin), "acting_until": time.time() + VIEW_AS_SECS})
    record(session, admin.username, "view_as.start", instructor.username)
    session.commit()
    log.info("admin %s started viewing as instructor %s", admin.username, instructor.username)


def end(store: dict, session: Session, admin: User, fingerprint, reason: str) -> None:
    """Back to the admin's own session."""
    viewed = session.get(User, store.get("uid")) if isinstance(store.get("uid"), int) else None
    for key in ACTING_KEYS:
        store.pop(key, None)
    store.update({"uid": admin.id, "fp": fingerprint(admin)})
    target = viewed.username if viewed else None
    record(session, admin.username, "view_as.end", target, reason)
    session.commit()
    log.info("admin %s stopped viewing as %s (%s)", admin.username, target, reason)


def summary(store: dict, session: Session) -> dict | None:
    """For /api/auth/me: whose admin account is behind this session, and until when."""
    admin_id = store.get("acting_admin")
    admin = session.get(User, admin_id) if isinstance(admin_id, int) else None
    if admin is None:
        return None
    until = datetime.fromtimestamp(store.get("acting_until", 0), timezone.utc)
    return {"admin": admin.display_name or admin.username, "admin_username": admin.username,
            "until": until.isoformat()}

# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""The list of colleges. Only the super admin adds, renames or deletes colleges, so the
list stays clean (no "Alpha Inst." next to "Alpha Institute"); everyone else picks from
it. Every change records when, by whom and how."""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import College, InstructorCollege, Student
from app.services.roster_admin import audit, audit_json

log = logging.getLogger(__name__)

MAX_NAME = 200


class CollegeError(Exception):
    pass


def clean_name(name: str) -> str:
    return " ".join(name.split())


def find(session: Session, name: str) -> College | None:
    """The college with this name, ignoring case and extra spaces."""
    name = clean_name(name)
    return session.scalar(select(College).where(func.lower(College.name) == name.lower())) if name else None


def list_colleges(session: Session) -> list[dict]:
    counts = {cid: (n, n_active) for cid, n, n_active in session.execute(
        select(Student.college_id, func.count(), func.count().filter(Student.active.is_(True)))
        .group_by(Student.college_id))}
    active = {cid: c[1] for cid, c in counts.items()}
    everyone = {cid: c[0] for cid, c in counts.items()}
    instructors = dict(session.execute(select(InstructorCollege.college_id, func.count())
                                       .group_by(InstructorCollege.college_id)).all())
    return [
        {"id": c.id, "name": c.name, "students": active.get(c.id, 0),
         "removed_students": everyone.get(c.id, 0) - active.get(c.id, 0),
         "instructors": instructors.get(c.id, 0), **audit_json(c)}
        for c in session.scalars(select(College).order_by(func.lower(College.name)))
    ]


def add_colleges(session: Session, names: list[str], *, actor: str, via: str, preview: bool = False) -> dict:
    """Add each new name; names already on the list are reported, not duplicated. Commits.
    preview=True only reports what would be added; nothing is saved."""
    added, existing, seen = [], [], set()
    for raw in names:
        name = clean_name(raw)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        if len(name) > MAX_NAME:
            raise CollegeError(f"college name is too long (at most {MAX_NAME} characters): {name[:40]}…")
        found = find(session, name)
        if found is not None:
            existing.append(found.name)
            continue
        college = College(name=name)
        audit(college, actor, via, created=True)
        session.add(college)
        added.append(name)
    if not added and not existing:
        raise CollegeError("enter at least one college name")
    if preview:
        session.rollback()
        return {"added": added, "existing": existing, "preview": True}
    session.commit()
    log.info("colleges added by %s: %s", actor, ", ".join(added) or "none")
    return {"added": added, "existing": existing}


def rename_college(session: Session, college: College, name: str, *, actor: str, via: str) -> College:
    name = clean_name(name)
    if not name:
        raise CollegeError("enter the college name")
    other = find(session, name)
    if other is not None and other.id != college.id:
        raise CollegeError(f"{other.name} is already on the list")
    if college.name != name:
        old, college.name = college.name, name
        audit(college, actor, via, created=False)
        session.commit()
        log.info("college %r renamed to %r by %s", old, name, actor)
    return college


def delete_college(session: Session, college: College) -> None:
    """Only a college no student belongs to (past or present) can be deleted. Commits."""
    n = session.scalar(select(func.count()).select_from(Student).where(Student.college_id == college.id))
    if n:
        raise CollegeError(f"{n} {'student belongs' if n == 1 else 'students belong'} to {college.name}; "
                           "move or remove them first (removed students count too, their history is kept)")
    session.query(InstructorCollege).filter(InstructorCollege.college_id == college.id).delete()
    session.delete(college)
    session.commit()
    log.info("college %r deleted", college.name)

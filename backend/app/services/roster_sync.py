# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Replace the roster with a full list of students (used to seed test databases).
Admins manage students on the dashboard instead (see roster_admin).

Students are identified by roll number:
- new roll numbers are added,
- existing ones get their name / college / handle / extra columns updated
  (a changed handle resets its validation status),
- students missing from the sheet are marked inactive (their past results stay),
- inactive students that reappear are reactivated.
"""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import College, RosterSync, Student, utcnow
from app.services import roster

log = logging.getLogger(__name__)

# Refuse a sync that would deactivate more than this share of active students (and at
# least MIN_GUARDED of them): usually a wrong tab, a filtered view or a renamed column,
# not real removals.
MAX_DEACTIVATE_FRACTION = 0.5
MIN_GUARDED = 5


class RosterSyncError(Exception):
    pass


def normalize_roll(roll: str) -> str:
    return roll.strip().upper()


def sync_roster(
    session: Session,
    students: list[roster.Student],
    issues: list[str],
    source: str,
    *,
    force: bool = False,
    now: datetime | None = None,
) -> RosterSync:
    """Apply the sheet's students to the DB in one transaction. Commits.
    `now` overrides the timestamps (the worker passes its clock)."""
    clock = (lambda: now) if now is not None else utcnow
    now = clock()
    issues = list(issues)
    by_roll: dict[str, roster.Student] = {}
    for s in students:
        roll = normalize_roll(s.roll_no)
        if not roll:
            issues.append(f"row {s.row} ({s.name}): no roll number, skipped")
        elif roll in by_roll:
            issues.append(
                f"row {s.row} ({s.name}): roll number {roll!r} already used by row "
                f"{by_roll[roll].row}, skipped"
            )
        else:
            by_roll[roll] = s

    existing = {st.roll_no: st for st in session.scalars(select(Student))}
    active_before = sum(1 for st in existing.values() if st.active)
    to_deactivate = [st for roll, st in existing.items() if st.active and roll not in by_roll]

    if not by_roll:
        raise RosterSyncError(
            f"{source}: no students with a roll number found (is there a roll number column?)"
        )
    if (
        not force
        and len(to_deactivate) >= MIN_GUARDED
        and len(to_deactivate) > MAX_DEACTIVATE_FRACTION * active_before
    ):
        raise RosterSyncError(
            f"sync would deactivate {len(to_deactivate)} of {active_before} active students; "
            "check the sheet/tab, or re-run with --force if this is intended"
        )

    colleges = {c.name.lower(): c for c in session.scalars(select(College))}

    def college_for(name: str) -> College | None:
        name = name.strip()
        if not name:
            return None
        college = colleges.get(name.lower())
        if college is None:
            college = College(name=name)
            session.add(college)
            colleges[name.lower()] = college
        return college

    sync = RosterSync(source=source, started_at=now, added=0, updated=0, reactivated=0, deactivated=0,
                      unchanged=0, issues=[])
    session.add(sync)

    for roll, s in by_roll.items():
        college = college_for(s.college)
        fields = {
            "name": s.name,
            "college": college,
            "extra": s.extra,
            "lc_handle_raw": s.handle_raw,
            "lc_slug": s.lc_slug,
            "sheet_row": s.row,
        }
        st = existing.get(roll)
        if st is None:
            session.add(Student(roll_no=roll, active=True, created_at=now, updated_at=now, **fields))
            sync.added += 1
            continue

        changed = [k for k, v in fields.items() if k != "sheet_row" and getattr(st, k) != v]
        if "lc_slug" in changed:
            st.handle_status, st.handle_checked_at, st.lc_username = "unchecked", None, None
        for k, v in fields.items():
            setattr(st, k, v)
        was_inactive = not st.active
        st.active = True
        if was_inactive:
            sync.reactivated += 1
        elif changed:
            sync.updated += 1
        else:
            sync.unchanged += 1
        if changed or was_inactive:
            st.updated_at = now

    for st in to_deactivate:
        st.active = False
        st.updated_at = now
    sync.deactivated = len(to_deactivate)

    sync.issues = issues
    sync.status = "complete"
    sync.finished_at = clock()
    session.commit()
    log.info(
        "roster sync: %d added, %d updated, %d reactivated, %d deactivated, %d unchanged, %d issues",
        sync.added, sync.updated, sync.reactivated, sync.deactivated, sync.unchanged, len(issues),
    )
    return sync


def active_roster(session: Session) -> list[roster.Student]:
    """Active DB students in the form the matcher expects."""
    rows = session.scalars(
        select(Student).where(Student.active.is_(True)).order_by(Student.id)
    ).all()
    return [
        roster.Student(
            row=st.sheet_row or 0,
            name=st.name,
            college=st.college.name if st.college else "",
            handle_raw=st.lc_handle_raw,
            lc_slug=st.lc_slug,
            extra=dict(st.extra or {}),
            roll_no=st.roll_no,
            handle_status=st.handle_status,
            db_id=st.id,
        )
        for st in rows
    ]

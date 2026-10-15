# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Upload history: every Excel upload remembers what it changed (only the fields it
changed, before and after), so an admin can see the changes and undo the upload.

Undo puts each row back the way it was before the upload -- unless the row has been
changed since (on the dashboard or by a later upload), in which case it's left alone
and listed, so an old undo never overwrites a newer, deliberate change.
"""

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import College, InstructorStudent, Result, Student, Upload, UploadChange, User, utcnow
from app.services import roster
from app.services.dashboard import iso
from app.services.instructors import ROLE as INSTRUCTOR, instructor_snapshot, save_instructor, InstructorError
from app.services.roster_admin import VIA_UNDO, _Colleges, audit, student_snapshot

log = logging.getLogger(__name__)


class UploadError(Exception):
    pass


def upload_json(u: Upload) -> dict:
    return {
        "id": u.id, "kind": u.kind, "filename": u.filename, "uploaded_by": u.uploaded_by, "via": u.via,
        "uploaded_at": iso(u.uploaded_at), "rows": u.rows, "counts": u.counts or {}, "issues": u.issues or [],
        "status": u.status, "undone_by": u.undone_by, "undone_at": iso(u.undone_at),
        "undo_result": u.undo_result,
    }


def list_uploads(session: Session, kind: str, limit: int = 50) -> list[dict]:
    rows = session.scalars(select(Upload).where(Upload.kind == kind).order_by(Upload.id.desc()).limit(limit)).all()
    changes = dict(session.execute(
        select(UploadChange.upload_id, func.count()).where(UploadChange.upload_id.in_([u.id for u in rows]))
        .group_by(UploadChange.upload_id)).all()) if rows else {}
    return [{**upload_json(u), "changes": changes.get(u.id, 0)} for u in rows]


def upload_detail(session: Session, upload: Upload) -> dict:
    changes = session.scalars(select(UploadChange).where(UploadChange.upload_id == upload.id).order_by(UploadChange.id))
    return {**upload_json(upload),
            "changes": [{"entity": c.entity, "entity_id": c.entity_id, "label": c.label, "action": c.action,
                         "before": c.before, "after": c.after} for c in changes]}


def undo_upload(session: Session, upload: Upload, *, actor: str) -> dict:
    """Undo an upload in one transaction. Returns {reverted, skipped: [reasons]}. Commits."""
    if upload.status == "undone":
        raise UploadError(f"this upload was already undone by {upload.undone_by}")
    changes = session.scalars(select(UploadChange).where(UploadChange.upload_id == upload.id)
                              .order_by(UploadChange.id)).all()
    reverted, skipped = 0, []
    colleges = _Colleges(session, can_add=True, actor=actor, via=VIA_UNDO)

    for ch in changes:
        if ch.entity == "student":
            ok, why = _undo_student(session, ch, colleges, actor)
        elif ch.entity == "instructor":
            ok, why = _undo_instructor(session, ch, actor)
        else:
            continue  # colleges last, once no student points at them
        if ok:
            reverted += 1
        else:
            skipped.append(f"{ch.label}: {why}")

    session.flush()
    for ch in changes:
        if ch.entity != "college":
            continue
        college = session.get(College, ch.entity_id)
        if college is None:
            continue
        used = session.scalar(select(func.count()).select_from(Student).where(Student.college_id == college.id))
        if used:
            skipped.append(f"college {college.name}: still used by {used} {'student' if used == 1 else 'students'}, kept")
        else:
            session.delete(college)
            reverted += 1

    upload.status, upload.undone_by, upload.undone_at = "undone", actor, utcnow()
    upload.undo_result = {"reverted": reverted, "skipped": skipped}
    session.commit()
    log.info("upload #%d (%s) undone by %s: %d reverted, %d skipped", upload.id, upload.filename, actor,
             reverted, len(skipped))
    return upload.undo_result


def _undo_student(session: Session, ch: UploadChange, colleges: _Colleges, actor: str) -> tuple[bool, str]:
    st = session.get(Student, ch.entity_id)
    if st is None:
        return False, "no longer exists"
    now = student_snapshot(st)
    changed_since = [k for k, v in ch.after.items() if now.get(k) != v]
    if changed_since:
        who = f" by {st.updated_by}" if st.updated_by else ""
        return False, f"changed since{who} ({', '.join(changed_since)}), left as it is"

    if ch.action == "added":
        has_results = session.scalar(select(func.count()).select_from(Result).where(Result.student_id == st.id))
        if has_results:
            st.active = False  # results were recorded since: soft remove, so they're kept
        else:
            # never scanned: the upload created it, so undo removes it completely
            session.execute(delete(InstructorStudent).where(InstructorStudent.student_id == st.id))
            session.delete(st)
            return True, ""
    else:
        before = ch.before or {}
        if "leetcode" in before:
            raw = before["leetcode"] or ""
            slug = roster.normalize_handle(raw) if raw else None
            if slug:
                taken = session.scalar(select(Student).where(Student.lc_slug == slug, Student.active.is_(True),
                                                             Student.id != st.id))
                if taken is not None and before.get("active", st.active):
                    return False, f"the old handle {slug} is now used by {taken.name} ({taken.roll_no}), left as it is"
            if slug != st.lc_slug:
                st.handle_status, st.handle_checked_at, st.lc_username = "unchecked", None, None
            st.lc_handle_raw, st.lc_slug = raw, slug
        if "name" in before:
            st.name = before["name"]
        if "college" in before:
            st.college = colleges.get(before["college"] or "")
        if "extra" in before:
            st.extra = before["extra"] or {}
        if "active" in before:
            st.active = bool(before["active"])
    audit(st, actor, VIA_UNDO, created=False)
    return True, ""


def _undo_instructor(session: Session, ch: UploadChange, actor: str) -> tuple[bool, str]:
    user = session.get(User, ch.entity_id)
    if user is None or user.role != INSTRUCTOR:
        return False, "no longer exists"
    now = instructor_snapshot(session, user)
    changed_since = [k for k, v in ch.after.items() if k != "password" and now.get(k) != v]
    if changed_since:
        who = f" by {user.updated_by}" if user.updated_by else ""
        return False, f"changed since{who} ({', '.join(changed_since)}), left as it is"
    if ch.action == "added":
        user.active = False  # the login stops working; it can be deleted on the Admin page
        audit(user, actor, VIA_UNDO, created=False)
        return True, ""
    target = {**now, **{k: v for k, v in (ch.before or {}).items() if k != "password"}}
    try:
        save_instructor(session, user=user, email=target["email"], name=target["name"], password=None,
                        colleges=target["colleges"], roll_nos=target["roll_nos"], active=target["active"],
                        actor=actor, via=VIA_UNDO)
    except InstructorError as e:
        return False, f"{e}, left as it is"
    return True, ""

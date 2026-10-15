# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Managing the student roster from the dashboard: add / edit / remove / restore one
student, or add and update many from an Excel upload. Every change records when, by
whom and how (VIA_UI, VIA_EXCEL or VIA_CLI)."""

import logging

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import College, Student, Upload, UploadChange, utcnow
from app.services import roster
from app.services.dashboard import iso
from app.services.tabular import template
from app.services import vcache

log = logging.getLogger(__name__)

VIA_UI, VIA_EXCEL, VIA_CLI, VIA_UNDO = "ui", "excel", "cli", "undo"

TEMPLATE_HEADER = ["Roll No", "Name", "College", "LeetCode", "Batch", "Section"]
MAX_STUDENT_ROWS = 5_000  # per upload; the import checks every row in memory and saves in one transaction


class RosterEditError(Exception):
    pass


@dataclass
class StudentInput:
    roll_no: str
    name: str
    college: str = ""
    leetcode: str = ""  # handle or profile URL
    extra: dict[str, str] = field(default_factory=dict)  # Batch, Section, ...


def normalize_roll(roll: str) -> str:
    return roll.strip().upper()


def audit(row, actor: str, via: str, *, created: bool) -> None:
    """Stamp a Student or User as changed now by `actor` via `via`."""
    now = utcnow()
    if created:
        row.created_at, row.created_by, row.created_via = now, actor, via
    row.updated_at, row.updated_by, row.updated_via = now, actor, via


def audit_json(row) -> dict:
    return {
        "created_at": iso(row.created_at), "created_by": row.created_by, "created_via": row.created_via,
        "updated_at": iso(row.updated_at), "updated_by": row.updated_by, "updated_via": row.updated_via,
    }


def student_json(st: Student) -> dict:
    return {
        "id": st.id, "roll_no": st.roll_no, "name": st.name,
        "college": st.college.name if st.college else "",
        "leetcode": st.lc_handle_raw, "handle": st.lc_slug, "handle_status": st.handle_status,
        "extra": st.extra or {}, "active": st.active, **audit_json(st),
    }


def _roster(session: Session) -> tuple[list[dict], list[str], list[str]]:
    """Every student (active first, by roll number), the sheet columns, the colleges."""
    students = session.scalars(select(Student).options(selectinload(Student.college))
                               .order_by(Student.active.desc(), Student.roll_no)).all()
    extra_keys: list[str] = []
    for st in students:
        for k in (st.extra or {}):
            if k not in extra_keys:
                extra_keys.append(k)
    colleges = list(session.scalars(select(College.name).order_by(College.name)))
    return [student_json(st) for st in students], extra_keys, colleges


ROSTER_SHOW = ("active", "removed", "all")


def list_students(session: Session, *, version: str | None = None, q: str = "", show: str = "all",
                  offset: int = 0, limit: int | None = None) -> dict:
    """The admin roster, searched and paged on the server. With `version`, the full
    roster is built once per data version (app.services.vcache)."""
    everyone, extra_keys, colleges = (vcache.cached((version, "roster"), lambda: _roster(session))
                                      if version else _roster(session))
    needle = q.strip().lower()
    rows = [s for s in everyone
            if (show == "all" or (show == "active") == s["active"])
            and (not needle or any(needle in v.lower() for v in
                                   (s["roll_no"], s["name"], s["college"], s["leetcode"], *s["extra"].values())))]
    active = sum(1 for s in everyone if s["active"])
    return {
        "students": rows[offset:offset + limit] if limit is not None else rows[offset:],
        "total": len(rows),
        "active": active,
        "removed": len(everyone) - active,
        "colleges": colleges,
        "extra_columns": extra_keys,
        "max_upload_rows": MAX_STUDENT_ROWS,
    }


def _clean(data: StudentInput) -> tuple[str, str, str, str | None]:
    """(roll, name, raw handle, normalized handle), or RosterEditError."""
    roll = normalize_roll(data.roll_no)
    name = " ".join(data.name.split())
    if not roll:
        raise RosterEditError("roll number is required")
    if not name:
        raise RosterEditError("name is required")
    raw = data.leetcode.strip()
    slug = roster.normalize_handle(raw) if raw else None
    if raw and slug is None:
        raise RosterEditError(f"can't read a LeetCode handle from {raw!r}")
    return roll, name, raw, slug


def _extra(data: StudentInput) -> dict[str, str]:
    return {k.strip(): v.strip() for k, v in data.extra.items() if k.strip()}


class _Colleges:
    """Colleges by name (case-insensitive). A new name is added to the list only when
    `can_add` (the super admin, or the server's command line); otherwise it's an error,
    so typos don't create duplicate colleges."""

    def __init__(self, session: Session, *, can_add: bool, actor: str, via: str):
        self.session, self.can_add, self.actor, self.via = session, can_add, actor, via
        self.by_name = {c.name.lower(): c for c in session.scalars(select(College))}
        self.created: list[College] = []

    def get(self, name: str) -> College | None:
        name = " ".join(name.split())
        if not name:
            return None
        college = self.by_name.get(name.lower())
        if college is None:
            if not self.can_add:
                raise RosterEditError(f"college {name!r} isn't on the list; the super admin can add it under Admin → Colleges")
            college = College(name=name)
            audit(college, self.actor, self.via, created=True)
            self.session.add(college)
            self.by_name[name.lower()] = college
            self.created.append(college)
        return college


def student_snapshot(st: Student) -> dict:
    """The fields an upload can change, as recorded in its history."""
    return {"name": st.name, "college": st.college.name if st.college else "",
            "leetcode": st.lc_handle_raw, "extra": dict(st.extra or {}), "active": bool(st.active)}


def diff(before: dict, after: dict) -> tuple[dict, dict]:
    """Only the keys that changed, before and after."""
    keys = [k for k in after if before.get(k) != after[k]]
    return {k: before.get(k) for k in keys}, {k: after[k] for k in keys}


UPLOAD_KEEP_DAYS = 90


def prune_uploads(session: Session) -> None:
    from datetime import timedelta

    old = [u.id for u in session.scalars(select(Upload).where(Upload.uploaded_at < utcnow() - timedelta(days=UPLOAD_KEEP_DAYS)))]
    if old:
        session.query(UploadChange).filter(UploadChange.upload_id.in_(old)).delete(synchronize_session=False)
        session.query(Upload).filter(Upload.id.in_(old)).delete(synchronize_session=False)


def _apply(session: Session, student: Student | None, fields: dict, actor: str, via: str) -> tuple[Student, str]:
    """Create the student or update it with `fields`; returns (student, outcome)."""
    if student is None:
        student = Student(active=True, handle_status="unchecked", **fields)
        session.add(student)
        audit(student, actor, via, created=True)
        return student, "added"
    changed = [k for k, v in fields.items() if getattr(student, k) != v]
    if "lc_slug" in changed:  # validate the new handle before the next scan
        student.handle_status, student.handle_checked_at, student.lc_username = "unchecked", None, None
    for k, v in fields.items():
        setattr(student, k, v)
    restored = not student.active
    student.active = True
    if not changed and not restored:
        return student, "unchanged"
    audit(student, actor, via, created=False)
    return student, "restored" if restored else "updated"


def save_student(session: Session, data: StudentInput, *, actor: str, via: str,
                 student: Student | None = None, can_add_colleges: bool = True) -> tuple[Student, str]:
    """Add a student (`student` None; the roll number must be new) or edit one.
    Returns (student, outcome): added | updated | restored | unchanged. Does not commit."""
    roll, name, raw, slug = _clean(data)
    same_roll = session.scalar(select(Student).where(Student.roll_no == roll))
    if same_roll is not None and same_roll is not student:
        raise RosterEditError(f"roll number {roll} already belongs to {same_roll.name}")
    if slug:
        taken = session.scalar(select(Student).where(Student.lc_slug == slug, Student.active.is_(True)))
        if taken is not None and taken is not student:
            raise RosterEditError(f"LeetCode handle {slug} is already used by {taken.name} ({taken.roll_no})")
    colleges = _Colleges(session, can_add=can_add_colleges, actor=actor, via=via)
    fields = {"roll_no": roll, "name": name, "college": colleges.get(data.college),
              "lc_handle_raw": raw, "lc_slug": slug, "extra": _extra(data)}
    student, outcome = _apply(session, student, fields, actor, via)
    session.flush()
    return student, outcome


def set_active(session: Session, student: Student, active: bool, *, actor: str) -> None:
    """Remove (keep past results, leave scans and analytics) or restore a student. Commits."""
    if student.active == active:
        return
    if active and student.lc_slug:
        taken = session.scalar(select(Student).where(Student.lc_slug == student.lc_slug,
                                                     Student.active.is_(True), Student.id != student.id))
        if taken is not None:
            raise RosterEditError(f"LeetCode handle {student.lc_slug} is now used by {taken.name} ({taken.roll_no})")
    student.active = active
    audit(student, actor, VIA_UI, created=False)
    session.commit()
    log.info("student %s %s by %s", student.roll_no, "restored" if active else "removed", actor)


def import_students(session: Session, rows: list[list[str]], *, actor: str, via: str = VIA_EXCEL,
                    source: str = "upload", can_add_colleges: bool = True, preview: bool = False) -> dict:
    """Add new roll numbers and update existing ones from a sheet; nobody is removed.
    Bad rows are skipped and reported, the rest saved together. The whole roster is
    loaded once and every row checked in memory, so thousands of rows take seconds
    whatever the database latency.

    preview=True works everything out but saves nothing: the result lists every row
    with what would happen to it ("records"), for the admin to review before saving."""
    if len(rows) - 1 > MAX_STUDENT_ROWS:
        raise RosterEditError(f"{len(rows) - 1:,} rows is more than {MAX_STUDENT_ROWS:,} per upload; split the file")
    try:
        parsed, _ = roster.parse_roster(rows, source)
    except roster.RosterError as e:
        raise RosterEditError(str(e).replace(f"{source}: ", ""))
    if not any(s.roll_no for s in parsed):
        raise RosterEditError("no roll numbers found: add a column named Roll No (see the template)")

    everyone = session.scalars(select(Student)).all()
    by_roll = {st.roll_no: st for st in everyone}
    handle_owner = {st.lc_slug: st for st in everyone if st.active and st.lc_slug}
    colleges = _Colleges(session, can_add=can_add_colleges, actor=actor, via=via)
    summary = {"added": 0, "updated": 0, "restored": 0, "unchanged": 0, "skipped": 0, "issues": []}
    row_of: dict[str, int] = {}
    changes: list[tuple[Student, str, dict | None, dict]] = []  # for the upload history
    records: list[dict] = []  # every row and what happens to it (the preview)

    def skip(label: str, why: str, s=None) -> None:
        summary["skipped"] += 1
        summary["issues"].append(f"{label}: {why}, skipped")
        if s is not None:
            records.append({"row": s.row, "key": normalize_roll(s.roll_no), "name": s.name, "action": "skipped",
                            "reason": why})

    for s in parsed:
        label = f"row {s.row}" + (f" ({s.name})" if s.name else "")
        data = StudentInput(s.roll_no, s.name, s.college, s.handle_raw, s.extra)
        try:
            roll, name, raw, slug = _clean(data)
        except RosterEditError as e:
            skip(label, str(e), s)
            continue
        if roll in row_of:
            skip(label, f"roll number {roll} is also on row {row_of[roll]}", s)
            continue
        student = by_roll.get(roll)
        owner = handle_owner.get(slug) if slug else None
        if owner is not None and owner is not student:
            skip(label, f"LeetCode handle {slug} is already used by {owner.name} ({owner.roll_no})", s)
            continue
        old_slug = student.lc_slug if student is not None and student.active else None
        try:
            college = colleges.get(s.college)
        except RosterEditError as e:
            skip(label, str(e), s)
            continue
        fields = {"roll_no": roll, "name": name, "college": college,
                  "lc_handle_raw": raw, "lc_slug": slug, "extra": _extra(data)}
        before = student_snapshot(student) if student is not None else None
        student, outcome = _apply(session, student, fields, actor, via)
        record = {"row": s.row, "key": roll, "name": name, "action": outcome}
        if outcome != "unchanged":
            after = student_snapshot(student)
            b, a = diff(before, after) if before else (None, after)
            changes.append((student, outcome, b, a))
            record.update(before=b, after=a)
        records.append(record)
        by_roll[roll], row_of[roll] = student, s.row
        if old_slug and old_slug != slug and handle_owner.get(old_slug) is student:
            del handle_owner[old_slug]
        if slug:
            handle_owner[slug] = student
        summary[outcome] += 1

    if preview:  # nothing is saved
        session.rollback()
        records.sort(key=lambda r: r["row"])
        return {**summary, "rows": len(parsed), "records": records,
                "new_colleges": sorted(c.name for c in colleges.created)}

    # the upload's history: what it changed, for "View changes" and "Undo"
    session.flush()  # ids for new students and colleges
    upload = Upload(kind="students", filename=source[:255], uploaded_by=actor, via=via, rows=len(parsed),
                    counts={k: summary[k] for k in ("added", "updated", "restored", "unchanged", "skipped")},
                    issues=summary["issues"], status="applied")
    session.add(upload)
    session.flush()
    session.add_all(
        UploadChange(upload_id=upload.id, entity="student", entity_id=st.id, label=f"{st.roll_no} · {st.name}",
                     action=action, before=before, after=after)
        for st, action, before, after in changes)
    session.add_all(
        UploadChange(upload_id=upload.id, entity="college", entity_id=c.id, label=c.name, action="added",
                     before=None, after={"name": c.name})
        for c in colleges.created)
    prune_uploads(session)
    session.commit()
    summary["upload_id"] = upload.id
    log.info("student upload %s (#%d) by %s: %d added, %d updated, %d skipped", source, upload.id, actor,
             summary["added"], summary["updated"], summary["skipped"])
    return summary


def students_template() -> bytes:
    return template(
        "Students", TEMPLATE_HEADER,
        [["NW2026001", "Asha Rao", "Alpha Institute of Technology", "https://leetcode.com/u/asha_rao/", "2026", "A"],
         ["NW2026002", "Ravi Kumar", "Beta College of Engineering", "ravi_k", "2026", "B"]],
        ["Students sheet: one row per student. Upload it on Admin → Student roster → Upload Excel.",
         "Roll No and Name are required. Roll No identifies the student: an existing roll number is updated, a new one is added.",
         "LeetCode: the username or the profile URL. Leave it empty if the student has none yet.",
         "College: written the same way for every student of that college.",
         "Batch, Section and any other columns you add are kept and can be used as filters in Analytics.",
         "Uploading never removes students; remove them one by one on the Admin page.",
         f"Up to {MAX_STUDENT_ROWS:,} students per file (split bigger lists into several files).",
         "Replace the two example rows with your students."],
    )

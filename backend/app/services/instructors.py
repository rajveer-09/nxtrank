# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Instructors: dashboard users who follow a set of students, given as whole colleges
and/or individual roll numbers. Admins add, edit, deactivate and delete them."""

import logging
import re
from collections import defaultdict

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import College, InstructorCollege, InstructorStudent, Student, Upload, UploadChange, User
from app.services.roster_admin import VIA_EXCEL, audit, audit_json, diff, prune_uploads
from app.services.tabular import template
from app.services.users import MIN_PASSWORD_LENGTH, hash_password

log = logging.getLogger(__name__)

ROLE = "instructor"


class InstructorError(Exception):
    pass


def student_ids_for(session: Session, user: User) -> set[int]:
    """Active students the instructor follows."""
    colleges = select(InstructorCollege.college_id).where(InstructorCollege.user_id == user.id)
    picked = select(InstructorStudent.student_id).where(InstructorStudent.user_id == user.id)
    return set(session.scalars(
        select(Student.id).where(Student.active.is_(True),
                                 or_(Student.college_id.in_(colleges), Student.id.in_(picked)))
    ))


def instructor_snapshot(session: Session, user: User) -> dict:
    """The fields an upload can change, as recorded in its history (never the password)."""
    colleges = session.scalars(
        select(College.name).join(InstructorCollege, InstructorCollege.college_id == College.id)
        .where(InstructorCollege.user_id == user.id)).all()
    rolls = session.scalars(
        select(Student.roll_no).join(InstructorStudent, InstructorStudent.student_id == Student.id)
        .where(InstructorStudent.user_id == user.id)).all()
    return {"name": user.display_name or "", "email": user.username, "active": bool(user.active),
            "colleges": sorted(colleges), "roll_nos": sorted(rolls)}


def instructor_json(session: Session, user: User) -> dict:
    colleges = session.scalars(
        select(College.name).join(InstructorCollege, InstructorCollege.college_id == College.id)
        .where(InstructorCollege.user_id == user.id).order_by(College.name)).all()
    rolls = session.scalars(
        select(Student.roll_no).join(InstructorStudent, InstructorStudent.student_id == Student.id)
        .where(InstructorStudent.user_id == user.id).order_by(Student.roll_no)).all()
    return {
        "id": user.id, "email": user.username, "name": user.display_name or user.username,
        "active": user.active,
        "colleges": list(colleges), "roll_nos": list(rolls),
        "students": len(student_ids_for(session, user)),
        **audit_json(user),
    }


def list_instructors(session: Session) -> list[dict]:
    """Every instructor with their assignments and student count, in four queries
    (not three per instructor)."""
    users = session.scalars(select(User).where(User.role == ROLE)
                            .order_by(func.lower(User.display_name), User.username)).all()
    if not users:
        return []
    ids = [u.id for u in users]
    colleges: dict[int, list[str]] = defaultdict(list)
    college_ids: dict[int, set[int]] = defaultdict(set)
    for uid, cid, name in session.execute(
        select(InstructorCollege.user_id, College.id, College.name)
        .join(College, College.id == InstructorCollege.college_id)
        .where(InstructorCollege.user_id.in_(ids)).order_by(College.name)
    ):
        colleges[uid].append(name)
        college_ids[uid].add(cid)
    rolls: dict[int, list[str]] = defaultdict(list)
    picked: dict[int, set[int]] = defaultdict(set)
    for uid, sid, roll in session.execute(
        select(InstructorStudent.user_id, Student.id, Student.roll_no)
        .join(Student, Student.id == InstructorStudent.student_id)
        .where(InstructorStudent.user_id.in_(ids)).order_by(Student.roll_no)
    ):
        rolls[uid].append(roll)
        picked[uid].add(sid)
    active_by_college: dict[int | None, set[int]] = defaultdict(set)
    active: set[int] = set()
    for sid, cid in session.execute(select(Student.id, Student.college_id).where(Student.active.is_(True))):
        active_by_college[cid].add(sid)
        active.add(sid)

    def follows(uid: int) -> int:  # same rule as student_ids_for
        ids_ = set().union(*(active_by_college[c] for c in college_ids[uid])) if college_ids[uid] else set()
        return len(ids_ | (picked[uid] & active))

    return [{"id": u.id, "email": u.username, "name": u.display_name or u.username, "active": u.active,
             "colleges": colleges[u.id], "roll_nos": rolls[u.id], "students": follows(u.id), **audit_json(u)}
            for u in users]


def get_instructor(session: Session, user_id: int) -> User | None:
    user = session.get(User, user_id)
    return user if user is not None and user.role == ROLE else None


def save_instructor(
    session: Session, *, user: User | None = None, email: str, name: str, password: str | None,
    colleges: list[str], roll_nos: list[str], active: bool = True, actor: str, via: str,
) -> User:
    """Create (user=None) or update an instructor and replace their assignments. Commits."""
    email, name, college_rows, student_rows = check_instructor(
        session, user=user, email=email, name=name, password=password, colleges=colleges, roll_nos=roll_nos)

    created = user is None
    if user is None:
        user = User(username=email, role=ROLE)
        session.add(user)
    user.username, user.display_name, user.active = email, name, active
    audit(user, actor, via, created=created)
    if password:
        user.password_hash = hash_password(password)  # also signs out their open sessions
    session.flush()

    session.execute(delete(InstructorCollege).where(InstructorCollege.user_id == user.id))
    session.execute(delete(InstructorStudent).where(InstructorStudent.user_id == user.id))
    session.add_all(InstructorCollege(user_id=user.id, college_id=c.id) for c in college_rows)
    session.add_all(InstructorStudent(user_id=user.id, student_id=s.id) for s in student_rows)
    session.commit()
    log.info("instructor %s %s by %s (%s): %d colleges, %d students by roll no", email,
             "added" if created else "updated", actor, via, len(college_rows), len(student_rows))
    return user


def check_instructor(session: Session, *, user: User | None, email: str, name: str, password: str | None,
                     colleges: list[str], roll_nos: list[str]) -> tuple[str, str, list[College], list[Student]]:
    """Validate an instructor's details without saving; returns (email, name, colleges, students)."""
    email = email.strip().lower()
    name = name.strip()
    if not email or any(c.isspace() for c in email):
        raise InstructorError("enter the instructor's email (used to log in)")
    if not name:
        raise InstructorError("enter the instructor's name")
    taken = session.scalar(select(User).where(User.username == email))
    if taken is not None and taken is not user:
        raise InstructorError(f"{email} already has a login")
    if user is None and not password:
        raise InstructorError("set a password for the new instructor")
    if password is not None and password != "" and len(password) < MIN_PASSWORD_LENGTH:
        raise InstructorError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")

    return email, name, _colleges(session, colleges), _students(session, roll_nos)


def delete_instructor(session: Session, user: User) -> None:
    """Remove the login and its assignments for good. Commits."""
    session.execute(delete(InstructorCollege).where(InstructorCollege.user_id == user.id))
    session.execute(delete(InstructorStudent).where(InstructorStudent.user_id == user.id))
    session.delete(user)
    session.commit()
    log.info("instructor %s deleted", user.username)


def _colleges(session: Session, names: list[str]) -> list[College]:
    wanted = {n.strip() for n in names if n.strip()}
    found = session.scalars(select(College).where(College.name.in_(wanted))).all() if wanted else []
    missing = wanted - {c.name for c in found}
    if missing:
        raise InstructorError(f"unknown college: {', '.join(sorted(missing))}")
    return list(found)


def _students(session: Session, roll_nos: list[str]) -> list[Student]:
    wanted = {r.strip().upper() for r in roll_nos if r.strip()}
    found = session.scalars(select(Student).where(Student.roll_no.in_(wanted))).all() if wanted else []
    missing = wanted - {s.roll_no for s in found}
    if missing:
        raise InstructorError(f"no student with roll number {', '.join(sorted(missing))}")
    return list(found)


# ---- Excel upload ---------------------------------------------------------------------

TEMPLATE_HEADER = ["Name", "Email", "Password", "Colleges", "Roll Nos", "Active"]
MAX_INSTRUCTOR_ROWS = 300  # per upload; each new password is hashed (deliberately slow, ~0.1 s)
_COLUMNS = {"name": ("name", "full_name", "instructor", "instructor_name"),
            "email": ("email", "email_id", "login", "username"),
            "password": ("password",),
            "colleges": ("colleges", "college", "organisations", "organizations", "organisation", "organization"),
            "roll_nos": ("roll_nos", "roll_numbers", "roll_no", "students"),
            "active": ("active", "status")}
_SPLIT = re.compile(r"[,;\n]+")


def _key(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_")


def import_instructors(session: Session, rows: list[list[str]], *, actor: str, via: str = VIA_EXCEL,
                       source: str = "upload", preview: bool = False) -> dict:
    """Add or update instructors by email from a sheet. A new instructor needs a password;
    an empty password keeps an existing one's. Bad rows are skipped and reported."""
    if not rows or not any(rows[0]):
        raise InstructorError("the sheet is empty or has no header row")
    if len(rows) - 1 > MAX_INSTRUCTOR_ROWS:
        raise InstructorError(f"{len(rows) - 1:,} rows is more than {MAX_INSTRUCTOR_ROWS} per upload; split the file")
    keys = {_key(h): i for i, h in enumerate(rows[0]) if h.strip()}
    col = {f: next((keys[a] for a in aliases if a in keys), None) for f, aliases in _COLUMNS.items()}
    missing = [f for f in ("name", "email") if col[f] is None]
    if missing:
        raise InstructorError(f"missing column: {', '.join(m.title() for m in missing)} (see the template)")

    summary = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0, "issues": []}
    seen: dict[str, int] = {}
    changes: list[tuple[int, str, str, dict | None, dict]] = []  # for the upload history
    records: list[dict] = []  # every row and what happens to it (the preview)
    rows_seen = 0

    def skip(row_no: int, email: str, name: str, why: str) -> None:
        summary["skipped"] += 1
        summary["issues"].append(f"row {row_no} ({name or email}): {why}, skipped")
        records.append({"row": row_no, "key": email, "name": name, "action": "skipped", "reason": why})
    for row_no, raw in enumerate(rows[1:], start=2):
        cells = list(raw) + [""] * (len(rows[0]) - len(raw))
        get = lambda f: cells[col[f]].strip() if col[f] is not None else ""  # noqa: E731, B023  (used in this iteration only)
        email, name = get("email").lower(), get("name")
        if not email and not name:
            continue
        rows_seen += 1
        if email in seen:
            skip(row_no, email, name, f"{email} is also on row {seen[email]}")
            continue
        active_text = get("active").lower()
        if active_text not in ("", "yes", "y", "true", "1", "active", "no", "n", "false", "0", "inactive", "deactivated"):
            skip(row_no, email, name, f"Active should be Yes or No, not {get('active')!r}")
            continue
        existing = session.scalar(select(User).where(User.username == email)) if email else None
        if existing is not None and existing.role != ROLE:
            skip(row_no, email, name, f"{email} is an {existing.role} login, not an instructor")
            continue
        password = get("password") or None
        colleges = sorted({" ".join(c.split()) for c in _SPLIT.split(get("colleges")) if c.strip()})
        roll_nos = sorted({r.strip().upper() for r in _SPLIT.split(get("roll_nos")) if r.strip()})
        active = active_text not in ("no", "n", "false", "0", "inactive", "deactivated")
        before = instructor_snapshot(session, existing) if existing is not None else None
        wanted = {"name": " ".join(name.split()), "email": email, "active": active, "colleges": colleges, "roll_nos": roll_nos}
        if before is not None and before == wanted and not password:
            seen[email] = row_no
            summary["unchanged"] += 1  # nothing to do: don't stamp it as changed
            records.append({"row": row_no, "key": email, "name": wanted["name"], "action": "unchanged"})
            continue
        try:
            if preview:
                email_ok, name_ok, college_rows, student_rows = check_instructor(
                    session, user=existing, email=email, name=name, password=password,
                    colleges=colleges, roll_nos=roll_nos)
                after = {"name": name_ok, "email": email_ok, "active": active,
                         "colleges": sorted(c.name for c in college_rows),
                         "roll_nos": sorted(st.roll_no for st in student_rows)}
            else:
                user = save_instructor(session, user=existing, email=email, name=name, password=password,
                                       colleges=colleges, roll_nos=roll_nos, active=active, actor=actor, via=via)
                after = instructor_snapshot(session, user)
        except InstructorError as e:
            session.rollback()
            skip(row_no, email, name, str(e))
            continue
        seen[email] = row_no
        b, a = diff(before, after) if before else (None, after)
        if password and existing is not None:
            a = {**a, "password": "changed"}  # recorded as a fact only; never the password
        action = "updated" if existing is not None else "added"
        records.append({"row": row_no, "key": email, "name": a.get("name") or name, "action": action,
                        "before": b, "after": a})
        if not preview:
            changes.append((user.id, f"{user.display_name} · {user.username}", action, b, a))
        summary[action] += 1

    if preview:  # nothing was saved
        session.rollback()
        return {**summary, "rows": rows_seen, "records": records}

    upload = Upload(kind="instructors", filename=source[:255], uploaded_by=actor, via=via, rows=rows_seen,
                    counts={k: summary[k] for k in ("added", "updated", "unchanged", "skipped")},
                    issues=summary["issues"], status="applied")
    session.add(upload)
    session.flush()
    session.add_all(UploadChange(upload_id=upload.id, entity="instructor", entity_id=uid, label=label[:300],
                                 action=action, before=b, after=a)
                    for uid, label, action, b, a in changes)
    prune_uploads(session)
    session.commit()
    summary["upload_id"] = upload.id
    log.info("instructor upload %s (#%d) by %s: %d added, %d updated, %d skipped", source, upload.id, actor,
             summary["added"], summary["updated"], summary["skipped"])
    return summary


def instructors_template() -> bytes:
    return template(
        "Instructors", TEMPLATE_HEADER,
        [["Asha Rao", "asha.rao@nxtwave.co.in", "choose-a-password", "Alpha Institute of Technology", "", "Yes"],
         ["Ravi Kumar", "ravi.kumar@nxtwave.co.in", "another-password", "Beta College of Engineering, Gamma University", "NW2026001, NW2026002", "Yes"]],
        ["Instructors sheet: one row per instructor. Upload it on Admin → Instructors → Upload Excel.",
         "Name and Email are required; the email is their login. An existing email is updated, a new one is added.",
         f"Password: at least {MIN_PASSWORD_LENGTH} characters, required for new instructors. Leave it empty to keep an existing instructor's password.",
         "Colleges: the colleges whose students they follow, separated by commas, spelled as on the Admin page.",
         "Roll Nos: extra individual students, separated by commas (optional).",
         "Active: Yes or No (empty means Yes). No signs them out and blocks their login.",
         f"Up to {MAX_INSTRUCTOR_ROWS} instructors per file.",
         "Delete the file after uploading: it contains passwords."],
    )

# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Admin-only actions: the student roster, instructors, scan requests, run history."""

import logging
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.etag import conditional
from app.api.fastjson import FastJSONRoute
from app.api.deps import current_user, get_db, get_settings, require_admin, require_super, session_fingerprint
from app.api.errors import ApiError
from app.api.routes_data import scans_allowed
from app.config import Settings
from app.db.models import College, ScanRequest, ScanRun, Student, Upload, User, utcnow
from app.services import drafts, tags, view_as, wake
from app.services.scan_status import set_state
from app.services.dashboard import iso
from app.services.instructors import (
    MAX_INSTRUCTOR_ROWS, InstructorError, delete_instructor, get_instructor, import_instructors, instructor_json, instructors_template,
    list_instructors, save_instructor,
)
from app.services.uploads import UploadError, list_uploads, undo_upload, upload_detail
from app.services.colleges import CollegeError, add_colleges, delete_college, list_colleges, rename_college
from app.services.admins import AdminError, ProtectedError, admin_json, delete_admin, get_admin, list_admins, save_admin
from app.services.roster_admin import (
    VIA_UI, RosterEditError, StudentInput, import_students, list_students, save_student, set_active,
    student_json, students_template,
)
from app.services.tabular import TableError, read_table

log = logging.getLogger(__name__)

router = APIRouter(route_class=FastJSONRoute, prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

_SLUG = re.compile(r"(weekly|biweekly)-contest-\d+")


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _upload(request: Request, filename: str) -> list[list[str]]:
    """The uploaded file is the raw request body; its name says .xlsx or .csv."""
    try:
        return read_table(await request.body(), filename)
    except TableError as e:
        raise HTTPException(422, str(e)) from e


def _xlsx(data: bytes, name: str) -> Response:
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---- student roster -----------------------------------------------------------------


class StudentBody(BaseModel):
    roll_no: str
    name: str
    college: str = ""
    leetcode: str = ""
    extra: dict[str, str] = {}


@router.get("/students")
def students(request: Request, q: str = "", show: Literal["active", "removed", "all"] = "active",
             offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=5000),
             db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    """The roster, removed students too, with who changed them last and how: searched
    and paged on the server."""
    return conditional(request, db, user, lambda version: list_students(
        db, version=version, q=q, show=show, offset=offset, limit=limit))


def _student(db: Session, student_id: int) -> Student:
    st = db.get(Student, student_id)
    if st is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such student")
    return st


def _save_student(db: Session, body: StudentBody, user: User, student: Student | None) -> dict:
    try:
        st, outcome = save_student(db, StudentInput(body.roll_no, body.name, body.college, body.leetcode, body.extra),
                             actor=user.username, via=VIA_UI, student=student, can_add_colleges=user.is_super)
    except RosterEditError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    db.commit()
    log.info("student %s %s by %s", st.roll_no, outcome, user.username)
    return student_json(st)


@router.post("/students", status_code=status.HTTP_201_CREATED)
def add_student(body: StudentBody, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    return _save_student(db, body, user, None)


@router.put("/students/{student_id}")
def edit_student(student_id: int, body: StudentBody, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)) -> dict:
    return _save_student(db, body, user, _student(db, student_id))


class ActiveBody(BaseModel):
    active: bool


@router.post("/students/{student_id}/active")
def student_active(student_id: int, body: ActiveBody, db: Session = Depends(get_db),
                   user: User = Depends(require_admin)) -> dict:
    """Remove a student (their past results stay) or restore them."""
    st = _student(db, student_id)
    try:
        set_active(db, st, body.active, actor=user.username)
    except RosterEditError as e:
        raise HTTPException(422, str(e)) from e
    return student_json(st)


@router.post("/students/import")
async def upload_students(request: Request, filename: str, preview: bool = False, db: Session = Depends(get_db),
                          user: User = Depends(require_admin)) -> dict:
    """preview=true: check the file and list every row with what would happen; nothing is saved."""
    rows = await _upload(request, filename)
    try:
        return import_students(db, rows, actor=user.username, source=filename, can_add_colleges=user.is_super,
                               preview=preview)
    except RosterEditError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/students/template.xlsx")
def student_template() -> Response:
    return _xlsx(students_template(), "students-template.xlsx")


@router.get("/scan-runs")
def scan_runs(limit: int = 30, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(ScanRun).order_by(ScanRun.id.desc()).limit(min(limit, 200)))
    return [
        {"id": r.id, "contest_slug": r.contest_slug, "kind": r.kind, "status": r.status,
         "started_at": iso(r.started_at), "finished_at": iso(r.finished_at),
         "participants": r.user_num, "students": r.students, "error": r.error,
         "review_decision": r.review_decision, "reviewed_by": r.reviewed_by}
        for r in rows
    ]


@router.post("/tags/refresh", status_code=status.HTTP_202_ACCEPTED)
def refresh_tags(db: Session = Depends(get_db), user: User = Depends(require_admin),
                 settings: Settings = Depends(get_settings)) -> dict:
    """Ask the worker to refresh the last 45 days' topic tags now (it talks to LeetCode)."""
    scans_allowed(settings)
    set_state(db, tags.REQUEST_KEY, user.username, utcnow())
    wake.signal()
    return {"requested": True}


# ---- drafts: manual scans waiting for review (services/drafts.py) -----------------------

def _draft_call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except drafts.DraftError as e:
        raise ApiError(409, str(e), "draft_gone") from None


@router.get("/scans/{run_id}/draft")
def draft_summary(run_id: int, db: Session = Depends(get_db)) -> dict:
    """What adding this draft would change on the dashboard."""
    return _draft_call(drafts.summary, db, run_id)


@router.get("/scans/{run_id}/draft/rows")
def draft_rows(run_id: int, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
               db: Session = Depends(get_db)) -> dict:
    return _draft_call(drafts.rows_page, db, run_id, offset=offset, limit=limit)


@router.post("/scans/{run_id}/publish")
def publish_draft(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    run = _draft_call(drafts.publish, db, run_id, user.username)
    return {"published": run.id, "contest_slug": run.contest_slug}


@router.post("/scans/{run_id}/discard")
def discard_draft(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    _draft_call(drafts.discard, db, run_id, user.username)
    return {"discarded": run_id}


class ScanBody(BaseModel):
    slug: str
    # "auto": final results once the contest's final-scan time (5th working day) has passed, else early
    kind: Literal["auto", "provisional", "final"] = "auto"

    @field_validator("slug")
    @classmethod
    def _valid_slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SLUG.fullmatch(v):
            raise ValueError("expected e.g. weekly-contest-520 or biweekly-contest-150")
        return v


def _request_json(r: ScanRequest) -> dict:
    return {"id": r.id, "contest_slug": r.contest_slug, "kind": r.kind,
            "requested_by": r.requested_by, "requested_at": iso(r.requested_at),
            "handled_at": iso(r.handled_at), "scan_run_id": r.scan_run_id, "error": r.error}


@router.post("/scans", status_code=status.HTTP_202_ACCEPTED)
def request_scan(body: ScanBody, db: Session = Depends(get_db),
                 user: User = Depends(require_admin), settings: Settings = Depends(get_settings)) -> dict:
    scans_allowed(settings)
    existing = db.scalar(select(ScanRequest).where(
        ScanRequest.contest_slug == body.slug, ScanRequest.handled_at.is_(None)))
    if existing:
        return _request_json(existing)
    req = ScanRequest(contest_slug=body.slug, kind=body.kind, requested_by=user.username)
    db.add(req)
    db.commit()
    wake.signal()
    return _request_json(req)


@router.get("/scan-requests")
def scan_requests(limit: int = 20, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(ScanRequest).order_by(ScanRequest.id.desc()).limit(min(limit, 100)))
    return [_request_json(r) for r in rows]


# ---- instructors ----------------------------------------------------------------------


class InstructorBody(BaseModel):
    email: str
    name: str
    password: str | None = None  # required for a new instructor; empty keeps the current one
    colleges: list[str] = []
    roll_nos: list[str] = []
    active: bool = True


@router.get("/instructors")
def instructors(db: Session = Depends(get_db)) -> dict:
    return {"instructors": list_instructors(db),
            "colleges": list(db.scalars(select(College.name).order_by(College.name))),
            "max_upload_rows": MAX_INSTRUCTOR_ROWS}


def _save(db: Session, body: InstructorBody, user: User | None, actor: User) -> dict:
    try:
        user = save_instructor(db, user=user, email=body.email, name=body.name, password=body.password,
                               colleges=body.colleges, roll_nos=body.roll_nos, active=body.active,
                               actor=actor.username, via=VIA_UI)
    except InstructorError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    return instructor_json(db, user)


def _instructor(db: Session, user_id: int) -> User:
    user = get_instructor(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such instructor")
    return user


@router.post("/instructors", status_code=status.HTTP_201_CREATED)
def create_instructor(body: InstructorBody, db: Session = Depends(get_db),
                      user: User = Depends(require_admin)) -> dict:
    return _save(db, body, None, user)


@router.put("/instructors/{user_id}")
def update_instructor(user_id: int, body: InstructorBody, db: Session = Depends(get_db),
                      user: User = Depends(require_admin)) -> dict:
    return _save(db, body, _instructor(db, user_id), user)


@router.delete("/instructors/{user_id}")
def remove_instructor(user_id: int, db: Session = Depends(get_db)) -> dict:
    delete_instructor(db, _instructor(db, user_id))
    return {"deleted": user_id}


@router.post("/instructors/{user_id}/view-as")
def start_view_as(user_id: int, request: Request, db: Session = Depends(get_db),
                  admin: User = Depends(require_admin), settings: Settings = Depends(get_settings)) -> dict:
    """See the dashboard as this instructor does (read-only, for up to an hour)."""
    target = get_instructor(db, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such instructor")
    if not target.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "this instructor's login is switched off")
    view_as.start(request.session, db, admin, target, session_fingerprint)
    return {"username": target.username, "role": target.role, "name": target.display_name,
            "is_super": False, "scans_enabled": settings.scans_enabled,
            "viewing_as": view_as.summary(request.session, db)}


@router.get("/audit-events")
def audit_events(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)) -> list[dict]:
    return view_as.recent_events(db, limit)


@router.post("/instructors/import")
async def upload_instructors(request: Request, filename: str, preview: bool = False, db: Session = Depends(get_db),
                             user: User = Depends(require_admin)) -> dict:
    """preview=true: check the file and list every row with what would happen; nothing is saved."""
    rows = await _upload(request, filename)
    try:
        return import_instructors(db, rows, actor=user.username, source=filename, preview=preview)
    except InstructorError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/instructors/template.xlsx")
def instructor_template() -> Response:
    return _xlsx(instructors_template(), "instructors-template.xlsx")


# ---- admins -------------------------------------------------------------------------


class AdminBody(BaseModel):
    email: str
    name: str
    password: str | None = None  # required for a new admin; empty keeps the current one
    active: bool = True


@router.get("/admins")
def admins(db: Session = Depends(get_db), user: User = Depends(require_admin)) -> list[dict]:
    return list_admins(db, user)


def _save_admin(db: Session, body: AdminBody, target: User | None, user: User) -> dict:
    try:
        saved = save_admin(db, user=target, email=body.email, name=body.name, password=body.password,
                           active=body.active, actor=user, via=VIA_UI)
    except ProtectedError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except AdminError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    return admin_json(saved, user)


def _admin(db: Session, user_id: int) -> User:
    target = get_admin(db, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such admin")
    return target


@router.post("/admins", status_code=status.HTTP_201_CREATED)
def create_admin(body: AdminBody, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    return _save_admin(db, body, None, user)


@router.put("/admins/{user_id}")
def update_admin(user_id: int, body: AdminBody, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)) -> dict:
    return _save_admin(db, body, _admin(db, user_id), user)


@router.delete("/admins/{user_id}")
def remove_admin(user_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    try:
        delete_admin(db, _admin(db, user_id), actor=user)
    except ProtectedError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except AdminError as e:
        raise HTTPException(422, str(e)) from e
    return {"deleted": user_id}


# ---- colleges (changes: super admin only) ---------------------------------------------


class CollegesBody(BaseModel):
    names: list[str]


class CollegeBody(BaseModel):
    name: str


@router.get("/colleges")
def colleges(db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    return {"colleges": list_colleges(db), "can_edit": user.is_super}


@router.post("/colleges", status_code=status.HTTP_201_CREATED)
def create_colleges(body: CollegesBody, preview: bool = False, db: Session = Depends(get_db),
                    user: User = Depends(require_super)) -> dict:
    """preview=true: which names are new and which are already on the list; nothing is saved."""
    try:
        return add_colleges(db, body.names, actor=user.username, via=VIA_UI, preview=preview)
    except CollegeError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e


def _college(db: Session, college_id: int) -> College:
    c = db.get(College, college_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such college")
    return c


@router.put("/colleges/{college_id}")
def update_college(college_id: int, body: CollegeBody, db: Session = Depends(get_db),
                   user: User = Depends(require_super)) -> dict:
    try:
        c = rename_college(db, _college(db, college_id), body.name, actor=user.username, via=VIA_UI)
    except CollegeError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    return next(x for x in list_colleges(db) if x["id"] == c.id)


@router.delete("/colleges/{college_id}")
def remove_college(college_id: int, db: Session = Depends(get_db), user: User = Depends(require_super)) -> dict:
    try:
        delete_college(db, _college(db, college_id))
    except CollegeError as e:
        raise HTTPException(422, str(e)) from e
    return {"deleted": college_id}


# ---- upload history (view changes, undo) --------------------------------------------------


@router.get("/uploads")
def uploads(kind: Literal["students", "instructors"], db: Session = Depends(get_db)) -> list[dict]:
    return list_uploads(db, kind)


def _get_upload(db: Session, upload_id: int) -> Upload:
    u = db.get(Upload, upload_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such upload")
    return u


@router.get("/uploads/{upload_id}")
def upload_changes(upload_id: int, db: Session = Depends(get_db)) -> dict:
    return upload_detail(db, _get_upload(db, upload_id))


@router.post("/uploads/{upload_id}/undo")
def undo(upload_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    u = _get_upload(db, upload_id)
    try:
        result = undo_upload(db, u, actor=user.username)
    except UploadError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    return {**result, "upload": upload_detail(db, u)}

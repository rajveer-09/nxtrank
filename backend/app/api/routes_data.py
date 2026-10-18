# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Read-only endpoints for logged-in users."""

import logging
import io
from datetime import datetime, timedelta, timezone

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.etag import conditional
from app.api.fastjson import FastJSONRoute
from app.api.deps import current_user, get_db, get_settings
from app.api.errors import ApiError
from app.config import Settings
from app.db.models import College, Contest, Result, ScanRequest, ScanRun, Student, User, utcnow
from app.services import analytics, dashboard, drafts, rules, tags, topics, vcache, wake
from app.leetcode.client import LeetCodeBlockedError, LeetCodeClient, LeetCodeError
from app.services.instructors import get_instructor, student_ids_for
from app.services.ratings import refresh_student_rating
from app.services.scans import AUTO, kind_by_age
from app.services.schedule import round_up
from app.worker import Policy
from app.services.scan_status import as_utc
from app.services.export import result_dict, write_csv_to, xlsx_bytes
from app.services.results import ContestNotScannedError, load_contest_results
from app.services.scan_status import queue_status

log = logging.getLogger(__name__)

router = APIRouter(route_class=FastJSONRoute, prefix="/api", tags=["data"], dependencies=[Depends(current_user)])

_SLUG = re.compile(r"(weekly|biweekly)-contest-\d+")


def _results(db: Session, slug: str):
    try:
        return load_contest_results(db, slug)
    except ContestNotScannedError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no results for {slug}") from None


def _delay(settings: Settings) -> timedelta:
    return timedelta(minutes=settings.scan_delay_minutes)


@router.get("/contests")
def contests(
    show: Literal["all", "with_data", "without_data"] = "all",
    type: Literal["weekly", "biweekly"] | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    return dashboard.contest_list(db, datetime.now(timezone.utc), _delay(settings), show=show,
                                  contest_type=type, q=q, page=page, per_page=per_page,
                                  final=Policy.from_settings(settings).final)


@router.get("/scan-status")
def scan_status_view(db: Session = Depends(get_db)) -> dict:
    return queue_status(db, datetime.now(timezone.utc))


def _scope(db: Session, user: User, college: str | None, mine: bool,
           instructor_id: int | None = None) -> set[int] | None:
    """Students a contest page is limited to: an instructor's own (`mine`), one
    instructor's (`instructor_id`, admins), one college, or everyone (None)."""
    if instructor_id is not None:
        if user.role != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "only admins can choose an instructor")
        target = get_instructor(db, instructor_id)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such instructor")
        return student_ids_for(db, target)
    if mine:
        if user.role != "instructor":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "only instructors have their own students")
        return student_ids_for(db, user)
    if college:
        return set(db.scalars(select(Student.id).join(College, Student.college_id == College.id)
                              .where(College.name == college)))
    return None


@router.get("/contests/{slug}")
def contest(slug: str, college: str | None = None, mine: bool = False, instructor_id: int | None = None,
            db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
            user: User = Depends(current_user)) -> dict:
    ids = _scope(db, user, college, mine, instructor_id)
    page = dashboard.contest_page(db, slug, now=datetime.now(timezone.utc), scan_delay=_delay(settings),
                                  final=Policy.from_settings(settings).final, student_ids=ids)
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown contest {slug}")
    # admins: a manual scan waiting for review (it doesn't count until they add it)
    # (the status already says whether there is one, so no query when there isn't)
    page["review"] = drafts.pending_for(db, slug) if user.role == "admin" and page["status"].get("in_review") else None
    return page


def _no_instructors(user: User) -> None:
    if user.role == "instructor":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "instructors have read-only access")


@router.get("/contests/{slug}/scan/preview")
def scan_preview(slug: str, db: Session = Depends(get_db), user: User = Depends(current_user),
                 settings: Settings = Depends(get_settings)) -> dict:
    """What queuing a scan of this contest would do (for the confirmation pop-up)."""
    _no_instructors(user)
    if not _SLUG.fullmatch(slug):
        raise HTTPException(422, "not a weekly/biweekly contest")
    now = datetime.now(timezone.utc)
    c = db.get(Contest, slug)
    if c and now.timestamp() < c.start_time + c.duration:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the contest hasn't finished yet")
    has_data = db.scalar(select(Result.contest_slug).where(Result.contest_slug == slug).limit(1)) is not None
    policy = Policy.from_settings(settings)
    final = policy.final
    queue = queue_status(db, now)
    queued = next((q for q in queue["queue"] if q["slug"] == slug), None)
    running = queue["running"]
    last = queue["queue"][-1]["ready_at"] if queue["queue"] else (running["ready_at"] if running else None)
    ready = (datetime.fromisoformat(last) if last else now) + timedelta(seconds=queue["typical_scan_secs"])
    return {
        "slug": slug, "title": c.title if c else None, "has_data": has_data,
        # None: not in the database yet, decided once LeetCode reports the contest's date
        "kind": (kind_by_age(c.start_time, c.duration, now.timestamp(), final) if final else "provisional") if c else None,
        "final_scan_at": dashboard.iso(final.due_at_ts(c.start_time, c.duration)) if c and final else None,
        # when final results should be ready: the final scan's start plus a typical scan
        "final_ready_at": dashboard.iso(round_up(final.due_at_ts(c.start_time, c.duration)
                                                 + timedelta(seconds=queue["typical_scan_secs"]))) if c and final else None,
        "students": db.scalar(select(func.count()).select_from(Student).where(Student.active.is_(True))),
        "ahead": len(queue["queue"]) + (1 if running else 0),
        "ready_at": dashboard.iso(ready), "typical_scan_secs": queue["typical_scan_secs"],
        "already": "scanning" if running and running["slug"] == slug else "queued" if queued else None,
        "worker": queue["worker"],
        "can_request": user.role == "admin" or not has_data,
    }


@router.post("/contests/{slug}/scan", status_code=status.HTTP_202_ACCEPTED)
def request_contest_scan(slug: str, db: Session = Depends(get_db), user: User = Depends(current_user),
                         settings: Settings = Depends(get_settings)) -> dict:
    """Queue a scan of a finished contest. Admins and viewers can fetch a contest that has
    no results yet; rescanning one that has results is admin-only; instructors can't scan."""
    _no_instructors(user)
    scans_allowed(settings)
    if not _SLUG.fullmatch(slug):
        raise HTTPException(422, "not a weekly/biweekly contest")
    now = datetime.now(timezone.utc)
    c = db.get(Contest, slug)
    if c and now.timestamp() < c.start_time + c.duration:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the contest hasn't finished yet")
    has_data = db.scalar(select(Result.contest_slug).where(Result.contest_slug == slug).limit(1))
    if has_data and user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "results already exist; only admins can rescan")
    pending = db.scalar(select(ScanRequest).where(
        ScanRequest.contest_slug == slug, ScanRequest.handled_at.is_(None)))
    if pending is None:
        db.add(ScanRequest(contest_slug=slug, kind=AUTO, requested_by=user.username))  # early/final by age
        db.commit()
        wake.signal()
    queue = queue_status(db, now)
    item = next((x for x in queue["queue"] if x["slug"] == slug), None)
    if queue["running"] and queue["running"]["slug"] == slug:
        item = {"slug": slug, "position": 0, "ready_at": queue["running"]["ready_at"]}
    return {"request": item, "worker": queue["worker"]}


@router.post("/contests/{slug}/scan/cancel")
def cancel_contest_scan(slug: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """Cancel a queued scan, or stop the one running for this contest. Admins can cancel
    any scan; others only scans they requested; instructors none."""
    _no_instructors(user)
    run = db.scalar(select(ScanRun).where(ScanRun.contest_slug == slug, ScanRun.status == "running"))
    req = db.scalar(select(ScanRequest).where(ScanRequest.contest_slug == slug, ScanRequest.handled_at.is_(None)))
    if run is None and req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no queued or running scan for this contest")
    if user.role != "admin" and (req is None or req.requested_by != user.username):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only admins or the person who requested the scan can cancel it")
    if run is not None:
        # only while still running: a scan that has just finished keeps its results
        stopped = db.execute(update(ScanRun).where(ScanRun.id == run.id, ScanRun.status == "running")
                             .values(cancel_requested=True)).rowcount
        db.commit()
        if not stopped:
            raise HTTPException(status.HTTP_409_CONFLICT, "the scan has already finished")
        return {"cancelled": "running"}  # the worker stops within a few seconds and closes the request
    req.handled_at = utcnow()
    req.error = f"cancelled by {user.username}"
    db.commit()
    return {"cancelled": "queued"}


@router.get("/contests/{slug}/results")
def contest_results(request: Request, slug: str, college: str | None = None, mine: bool = False,
                    instructor_id: int | None = None, db: Session = Depends(get_db),
                    user: User = Depends(current_user)) -> Response:
    def build(version):
        ids = _scope(db, user, college, mine, instructor_id)

        def everyone():
            stored = _results(db, slug)
            return stored.labels, [(r.student.db_id, result_dict(slug, r)) for r in stored.results]
        labels, rows = vcache.cached((version, "results", slug), everyone)
        return {"labels": labels, "rows": [row for sid, row in rows if ids is None or sid in ids]}
    return conditional(request, db, user, build)


@router.get("/contests/{slug}/export.csv")
def export_csv(slug: str, db: Session = Depends(get_db)) -> Response:
    stored = _results(db, slug)
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel reads UTF-8 names correctly
    write_csv_to(buf, slug, stored.results, stored.labels)
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{slug}.csv"'})


@router.get("/contests/{slug}/export.xlsx")
def export_xlsx(slug: str, db: Session = Depends(get_db)) -> Response:
    stored = _results(db, slug)
    data = xlsx_bytes(stored.contest.title, slug, stored.results, stored.labels)
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{slug}.xlsx"'},
    )


@router.get("/students")
def students(request: Request, q: str = "", college: str = "", handle: str = "", include_removed: bool = False,
             sort: str = "name", offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=5000),
             db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    """The Students page, filtered, sorted and paged on the server."""
    def build(version):
        try:
            return dashboard.students_page(db, version=version, q=q, college=college, handle=handle,
                                           include_removed=include_removed, sort=sort, offset=offset, limit=limit)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
    return conditional(request, db, user, build)


@router.get("/students/{student_id}")
def student(request: Request, student_id: int, db: Session = Depends(get_db),
            user: User = Depends(current_user)) -> Response:
    def build(_version):
        detail = dashboard.student_detail(db, student_id)
        if detail is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown student")
        return detail
    return conditional(request, db, user, build)


def scans_allowed(settings: Settings) -> None:
    """Staging runs on a copy of production's data; scanning there would only drift it."""
    if not settings.scans_enabled:
        raise ApiError(409, "Scans run on production. Reset staging from production for fresh data.",
                       "scans_disabled")


LIVE_RATING_EVERY = timedelta(minutes=10)  # one student page view asks LeetCode at most this often


@router.post("/students/{student_id}/rating/refresh")
async def refresh_rating(student_id: int, db: Session = Depends(get_db),
                         settings: Settings = Depends(get_settings)) -> dict:
    """The student's LeetCode rating, fetched now (or kept if fetched in the last 10 min)."""
    st = db.get(Student, student_id)
    if st is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown student")
    if not st.lc_slug:
        raise HTTPException(422, "this student has no LeetCode handle")
    synced = st.ratings_synced_at
    fresh = synced is not None and datetime.now(timezone.utc) - as_utc(synced) < LIVE_RATING_EVERY
    fresh = fresh or not settings.scans_enabled  # staging: show the copied rating, don't ask LeetCode
    if not fresh:
        try:
            async with LeetCodeClient(proxy=settings.proxy_url, max_retries=2, timeout=15) as client:
                await refresh_student_rating(db, client, st)
        except LeetCodeBlockedError as e:
            db.rollback()
            log.warning("live rating for %s blocked: %s", st.lc_slug, e)
            raise ApiError(503, "LeetCode is blocking requests from the server right now. The rating shown "
                                "is the last one saved; the worker refreshes ratings after each final scan.",
                           "leetcode_blocked") from e
        except LeetCodeError as e:
            db.rollback()
            log.warning("live rating for %s failed: %s", st.lc_slug, e)
            raise ApiError(502, "LeetCode didn't answer in time. The rating shown is the last one saved.",
                           "upstream") from e
    return {"rating": round(st.lc_rating) if st.lc_rating is not None else None,
            "top_percentage": st.lc_top_percentage, "contests_attended": st.lc_contests_attended,
            "synced_at": dashboard.iso(st.ratings_synced_at), "fetched_now": not fresh}


@router.get("/students/{student_id}/analytics")
def student_analytics(request: Request, student_id: int, last: int | None = Query(None, ge=1),
                      db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    def build(version):
        data = analytics.student_analytics(db, student_id, last=last, version=version)
        if data is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown student")
        return data
    return conditional(request, db, user, build)


def _extra(request: Request) -> dict[str, str] | None:
    """Sheet-column filters: `extra.<Column>=<value>`, e.g. `?extra.Batch=2026`."""
    return {k[len("extra."):]: v for k, v in request.query_params.items() if k.startswith("extra.") and v} or None


def _instructor(db: Session, user: User, instructor_id: int | None) -> User:
    """Whose students: an instructor's own; admins choose an instructor."""
    if user.role == "admin" and instructor_id is not None:
        target = get_instructor(db, instructor_id)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such instructor")
        return target
    if user.role == "instructor":
        return user
    raise HTTPException(status.HTTP_403_FORBIDDEN, "for instructors (admins: choose an instructor)")


def _students_page(db: Session, request: Request, version: str, student_ids: set[int] | None, *, last, college,
                   q, sort, desc, offset, limit) -> dict:
    try:
        return analytics.students_page(db, last=last, college=college or None, extra=_extra(request),
                                       student_ids=student_ids, search=q, sort=sort, desc=desc,
                                       offset=offset, limit=limit, version=version)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/analytics")
def analytics_overview(request: Request, last: int | None = Query(None, ge=1), college: str | None = None,
                       db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    """Cohort analytics (the student list is served a page at a time by /analytics/students)."""
    return conditional(request, db, user, lambda version: analytics.overview(
        db, last=last, college=college or None, extra=_extra(request), include_students=False, version=version))


@router.get("/analytics/students")
def analytics_students(request: Request, last: int | None = Query(None, ge=1), college: str | None = None,
                       q: str = "", sort: str = "portal_rank", desc: bool = False,
                       offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=5000),
                       db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    """The "All students" table: searched, sorted and paged on the server."""
    return conditional(request, db, user, lambda version: _students_page(
        db, request, version, None, last=last, college=college, q=q, sort=sort, desc=desc,
        offset=offset, limit=limit))


@router.get("/instructor/analytics")
def instructor_analytics(request: Request, last: int | None = Query(None, ge=1), college: str | None = None,
                         instructor_id: int | None = None, db: Session = Depends(get_db),
                         user: User = Depends(current_user)) -> Response:
    """Analytics for an instructor's students: their own as an instructor; admins pick one."""
    target = _instructor(db, user, instructor_id)

    def build(version):
        data = analytics.overview(db, last=last, college=college or None, extra=_extra(request),
                                  student_ids=student_ids_for(db, target), include_students=False, version=version)
        data["instructor"] = {"id": target.id, "name": target.display_name or target.username,
                              "email": target.username}
        return data
    return conditional(request, db, user, build)


@router.get("/instructor/analytics/students")
def instructor_analytics_students(request: Request, last: int | None = Query(None, ge=1),
                                  college: str | None = None, instructor_id: int | None = None,
                                  q: str = "", sort: str = "portal_rank", desc: bool = False,
                                  offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=5000),
                                  db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    target = _instructor(db, user, instructor_id)
    return conditional(request, db, user, lambda version: _students_page(
        db, request, version, student_ids_for(db, target), last=last, college=college, q=q, sort=sort,
        desc=desc, offset=offset, limit=limit))


# ---- topics (services/topics.py, services/tags.py) -----------------------------------------

def _college_ids(db: Session, college: str | None) -> set[int] | None:
    if not college:
        return None
    return set(db.scalars(select(Student.id).join(College, Student.college_id == College.id)
                          .where(College.name == college)))


def _both(a: set[int] | None, b: set[int] | None) -> set[int] | None:
    return b if a is None else a if b is None else a & b


@router.get("/analytics/topics")
def analytics_topics(request: Request, last: int | None = Query(None, ge=1), college: str | None = None,
                     db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    """Topic-wise stats for every active student (or one college), weakest topics, coverage."""
    return conditional(request, db, user, lambda version: topics.group_topics(
        db, last=last, student_ids=_college_ids(db, college), version=version))


@router.get("/instructor/analytics/topics")
def instructor_topics(request: Request, last: int | None = Query(None, ge=1), college: str | None = None,
                      instructor_id: int | None = None, db: Session = Depends(get_db),
                      user: User = Depends(current_user)) -> Response:
    target = _instructor(db, user, instructor_id)
    return conditional(request, db, user, lambda version: topics.group_topics(
        db, last=last, student_ids=_both(student_ids_for(db, target), _college_ids(db, college)), version=version))


@router.get("/students/{student_id}/topics")
def student_topics(request: Request, student_id: int, last: int | None = Query(None, ge=1),
                   db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    if db.get(Student, student_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown student")
    return conditional(request, db, user, lambda version: topics.student_topics(db, student_id, last=last))


@router.get("/tags/status")
def tags_status(db: Session = Depends(get_db)) -> dict:
    """The last tag refresh, how many questions are in each state, and each question's tags."""
    return tags.status_json(db)


@router.get("/rules")
def rule_book(settings: Settings = Depends(get_settings)) -> dict:
    """The thresholds behind every number, for the Guide's rule book."""
    return rules.rules(settings)

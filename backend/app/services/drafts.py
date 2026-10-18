# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""Manual scans as drafts: a scan requested from the dashboard ("Get results",
"Rescan") is kept aside until an admin adds it to the dashboard or throws it away.
Automatic scans skip this and count straight away.

A draft holds the exact rows a direct scan would have written, and publishing writes them
with the same code (scans.write_rows), so a published draft equals a direct scan. The
analytics summaries rebuild in the same transaction, as for any change to results."""

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import AppState, Result, ScanDraft, ScanRun, Student, utcnow
from app.services.scan_status import as_utc, iso
from app.services.view_as import record

log = logging.getLogger(__name__)

KEEP_FOR = timedelta(days=7)  # unreviewed drafts are discarded after this
PARTICIPATED = ("solved", "zero")


class DraftError(Exception):
    """Can't do that with this draft (gone, already decided, or outdated)."""


def supersede(session: Session, slug: str, *, keep: int, decision: str) -> None:
    """Older drafts of `slug` when a newer scan arrives: a newer draft replaces them
    ("replaced"); a direct scan makes them "outdated" (they can only be discarded)."""
    for run in session.scalars(select(ScanRun).where(
            ScanRun.contest_slug == slug, ScanRun.status == "review", ScanRun.id != keep)):
        if decision == "outdated":
            run.review_decision = "outdated"
        else:
            _close(session, run, "discarded", decision, None)


def _close(session: Session, run: ScanRun, status: str, decision: str, actor: str | None) -> None:
    run.status, run.review_decision = status, decision
    run.reviewed_by, run.reviewed_at = actor, utcnow()
    session.execute(delete(ScanDraft).where(ScanDraft.run_id == run.id))


def _get(session: Session, run_id: int) -> tuple[ScanRun, ScanDraft]:
    run = session.get(ScanRun, run_id)
    draft = session.get(ScanDraft, run_id)
    if run is None or draft is None or run.status != "review":
        raise DraftError("this draft no longer exists (it was added, discarded or replaced)")
    return run, draft


def _current(session: Session, slug: str) -> dict[int, Result]:
    return {r.student_id: r for r in session.scalars(select(Result).where(Result.contest_slug == slug))}


def _changes(rows: list[dict], current: dict[int, Result]) -> dict:
    now = {r["student_id"] for r in rows if r["status"] in PARTICIPATED}
    before = {sid for sid, r in current.items() if r.status in PARTICIPATED}
    rank = sum(1 for r in rows if (c := current.get(r["student_id"])) is not None
               and (c.college_rank != r["college_rank"] or c.status != r["status"]))
    return {"participated": len(now), "participated_before": len(before) if current else None,
            "joined": len(now - before) if current else None, "left": len(before - now) if current else None,
            "changed": rank if current else None}


def review_json(session: Session, run: ScanRun, draft: ScanDraft) -> dict:
    """What the draft would change: for the banner and the review dialog."""
    rows = draft.rows
    return {
        "run_id": run.id, "contest_slug": run.contest_slug, "title": draft.contest.get("title"),
        "kind": run.kind, "finished_at": iso(run.finished_at),
        "expires_at": iso(run.finished_at + KEEP_FOR) if run.finished_at else None,
        "outdated": run.review_decision == "outdated",
        "students": len(rows), "solved_any": sum(1 for r in rows if r["status"] == "solved"),
        **_changes(rows, _current(session, run.contest_slug)),
    }


def pending_for(session: Session, slug: str) -> dict | None:
    """The newest draft of a contest still waiting for review, if any."""
    run = session.scalars(select(ScanRun).where(ScanRun.contest_slug == slug, ScanRun.status == "review")
                          .order_by(ScanRun.id.desc()).limit(1)).first()
    draft = session.get(ScanDraft, run.id) if run else None
    return review_json(session, run, draft) if draft else None


def summary(session: Session, run_id: int) -> dict:
    run, draft = _get(session, run_id)
    return review_json(session, run, draft)


def rows_page(session: Session, run_id: int, *, offset: int = 0, limit: int = 50) -> dict:
    """The draft leaderboard (best college rank first), each row with its current values."""
    run, draft = _get(session, run_id)
    current = _current(session, run.contest_slug)
    ordered = sorted(draft.rows, key=lambda r: (r["college_rank"] is None, r["college_rank"] or 0, r["student_id"]))
    page = ordered[offset:offset + limit]
    people = {s.id: s for s in session.scalars(
        select(Student).where(Student.id.in_([r["student_id"] for r in page])).options(joinedload(Student.college)))}
    out = []
    for r in page:
        st, c = people.get(r["student_id"]), current.get(r["student_id"])
        out.append({
            "student_id": r["student_id"], "name": st.name if st else "(removed)",
            "roll_no": st.roll_no if st else None, "college": st.college.name if st and st.college else None,
            "status": r["status"], "college_rank": r["college_rank"], "global_rank": r["global_rank"],
            "score": r["score"], "solved": r["solved_count"],
            "before": {"status": c.status, "college_rank": c.college_rank, "score": c.score} if c else None,
        })
    return {"total": len(ordered), "offset": offset, "rows": out}


def publish(session: Session, run_id: int, actor: str) -> ScanRun:
    """Add the draft to the dashboard: replaces the contest's results in one transaction."""
    from app.services.scans import write_rows  # scans imports this module
    from app.worker import RATINGS_KEY

    run, draft = _get(session, run_id)
    if run.review_decision == "outdated":
        raise DraftError("an automatic scan has updated this contest since; discard this draft instead")
    write_rows(session, draft.contest, draft.rows, run)
    _close(session, run, "complete", "published", actor)
    if run.kind == "final":  # LeetCode ratings settle with final results: the worker refreshes them next
        session.execute(delete(AppState).where(AppState.key == RATINGS_KEY))
    record(session, actor, "scan.publish", run.contest_slug, f"scan run {run.id} ({run.kind})")
    session.commit()
    log.info("%s added scan run %d of %s to the dashboard", actor, run.id, run.contest_slug)
    return run


def discard(session: Session, run_id: int, actor: str) -> None:
    run, _ = _get(session, run_id)
    _close(session, run, "discarded", "discarded", actor)
    record(session, actor, "scan.discard", run.contest_slug, f"scan run {run.id} ({run.kind})")
    session.commit()
    log.info("%s discarded the draft of scan run %d (%s)", actor, run.id, run.contest_slug)


def expire(session: Session, now: datetime) -> int:
    """Discard drafts nobody reviewed within KEEP_FOR. Returns how many."""
    now = as_utc(now)
    old = [r for r in session.scalars(select(ScanRun).where(ScanRun.status == "review"))
           if r.finished_at is None or as_utc(r.finished_at) < now - KEEP_FOR]
    for run in old:
        _close(session, run, "discarded", "expired", None)
        log.info("draft of scan run %d (%s) expired unreviewed", run.id, run.contest_slug)
    if old:
        session.commit()
    return len(old)

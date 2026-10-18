# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Scan a contest and store the results for all active students."""

import logging
import re
import time

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import Contest, ProblemResult, Result, ScanDraft, ScanRun, utcnow
from app.scan.matcher import StudentResult, match_students
from app.scan.parser import parse_rows, question_labels
from app.scan.scanner import ScanCancelledError, ScanResult, scan_contest
from app.services import drafts, flags
from app.services.ratings import apply_profile_ranks, rerank
from app.services.roster_sync import active_roster
from app.services.schedule import DEFAULT_FINAL, FinalSchedule

log = logging.getLogger(__name__)

PROGRESS_EVERY_SECS = 5
AUTO = "auto"  # requested scans: early (provisional) or final, decided by the contest's age

_TYPE = re.compile(r"^(weekly|biweekly)-contest-\d+$")


def contest_type(slug: str) -> str:
    m = _TYPE.match(slug)
    return m.group(1) if m else "other"


def kind_by_age(start_time: int, duration: int, now: float, final: FinalSchedule = DEFAULT_FINAL) -> str:
    """'final' once the contest's final-scan time has passed (LeetCode has settled it),
    else 'provisional' (early results)."""
    return "final" if now >= final.due_at_ts(start_time, duration).timestamp() else "provisional"


async def scan_and_store(
    session: Session, client, slug: str, *, kind: str = "provisional", concurrency: int = 4,
    allow_unfinished: bool = False, final: FinalSchedule = DEFAULT_FINAL, now: float | None = None,
    draft: bool = False,
) -> ScanRun:
    """Scan `slug` and replace its stored results. A failed scan leaves earlier
    results for the contest untouched and is recorded as a failed ScanRun.
    kind=AUTO picks early/final from the contest's age (learnt from LeetCode if the
    contest isn't in the database yet). With `draft`, the results wait for an admin's
    review (services/drafts.py) instead of replacing what the dashboard shows."""
    now = time.time() if now is None else now
    auto = kind == AUTO
    if auto:
        known = session.get(Contest, slug)
        kind = kind_by_age(known.start_time, known.duration, now, final) if known else "provisional"
    run = ScanRun(contest_slug=slug, kind=kind)
    session.add(run)
    session.commit()

    last_commit = 0.0
    cancel = False

    def progress(done: int, total: int) -> None:
        nonlocal last_commit, cancel
        if done < total and time.monotonic() - last_commit < PROGRESS_EVERY_SECS:
            return
        last_commit = time.monotonic()
        run.pages_total, run.pages_done, run.progress_at = total, done, utcnow()
        session.commit()  # only the run row is pending while scanning
        session.refresh(run, attribute_names=["cancel_requested"])  # set from the dashboard
        cancel = run.cancel_requested

    try:
        scan = await scan_contest(
            client, slug, concurrency=concurrency, allow_unfinished=allow_unfinished,
            on_progress=progress, should_cancel=lambda: cancel,
        )
        if auto:
            c = scan.info.contest
            run.kind = kind_by_age(c.start_time, c.duration, now, final)
        results = store_scan(session, scan, run, draft=draft)
    except ScanCancelledError:
        session.rollback()
        run.status, run.error, run.finished_at = "cancelled", "cancelled from the dashboard", utcnow()
        session.commit()
        raise
    except Exception as e:
        session.rollback()
        run.status, run.error, run.finished_at = "failed", str(e)[:4000], utcnow()
        session.commit()
        raise

    log.info("%s: %s for %d students (scan run %d)", slug,
             "draft ready for review" if draft else "stored results", len(results), run.id)
    return run


def scan_rows(session: Session, scan: ScanResult) -> tuple[dict, list[dict], list[StudentResult]]:
    """Match the scan against active students: the contest's details, and one row per
    student with exactly what goes into `results` / `problem_results`."""
    info = scan.info.contest
    labels = question_labels(scan.questions)
    contest = {
        "slug": info.title_slug, "title": info.title, "contest_type": contest_type(info.title_slug),
        "start_time": info.start_time, "duration": info.duration, "user_num": scan.user_num,
        "questions": [{"label": labels[q.question_id], "question_id": q.question_id, "credit": q.credit,
                       "title": q.title, "title_slug": q.title_slug} for q in scan.questions],
    }
    participants = parse_rows(scan.rows, scan.questions, info.start_time)
    results = match_students(active_roster(session), participants)
    rows = []
    for r in results:
        p = r.participant
        rows.append({
            "student_id": r.student.db_id, "status": r.status.value,
            "global_rank": p.global_rank if p else None, "leaderboard_rank": p.position if p else None,
            "rank_source": "scan" if p else None, "college_rank": r.college_rank,
            "score": p.score if p else None, "solved_count": p.solved_count if p else None,
            "total_time_secs": p.total_time_secs if p else None,
            "problems": [{"q_label": label, "question_id": prob.question_id, "solve_secs": prob.solve_secs,
                          "fail_count": prob.fail_count, "lang": prob.lang}
                         for label, prob in (p.problems.items() if p else ())],
        })
    return contest, rows, results


def write_rows(session: Session, contest_data: dict, rows: list[dict], run: ScanRun) -> int:
    """Replace the contest's results with `rows` (not committed). Students removed from
    the roster since keep their old rows; rows for them are skipped. Returns rows written."""
    contest = session.get(Contest, contest_data["slug"]) or Contest(slug=contest_data["slug"])
    for key in ("title", "contest_type", "start_time", "duration", "user_num", "questions"):
        setattr(contest, key, contest_data[key])
    session.add(contest)

    # what the earlier scan showed, to spot students LeetCode penalised since (flags.py)
    before = flags.snapshot(session, contest.slug)

    # Replace only active students' rows: students since removed from the sheet keep
    # their results for this contest when it is rescanned.
    active_ids = {s.db_id for s in active_roster(session)}
    session.execute(delete(ProblemResult).where(
        ProblemResult.contest_slug == contest.slug, ProblemResult.student_id.in_(active_ids)))
    session.execute(delete(Result).where(
        Result.contest_slug == contest.slug, Result.student_id.in_(active_ids)))
    written = 0
    for row in rows:
        if row["student_id"] not in active_ids:
            continue
        written += 1
        session.add(Result(
            contest_slug=contest.slug, scan_run_id=run.id,
            **{k: v for k, v in row.items() if k != "problems"},
            **flags.judge(row, before.get(row["student_id"]), contest_data.get("user_num")),
            problems=[ProblemResult(contest_slug=contest.slug, student_id=row["student_id"], **pr)
                      for pr in row["problems"]],
        ))
    session.flush()
    apply_profile_ranks(session, [contest.slug])  # official ranks, if LeetCode has published them
    rerank(session, contest.slug)  # always numbered 1, 2, 3, ... in contest order
    return written


def _check_cancel(session: Session, run: ScanRun, slug: str) -> None:
    # Last chance to honour a stop: lock the run row so a cancel from the dashboard
    # either lands before this check (nothing is saved) or finds the scan already done.
    session.flush()
    session.refresh(run, attribute_names=["cancel_requested"], with_for_update=True)
    if run.cancel_requested:
        raise ScanCancelledError(f"{slug}: scan cancelled")


def store_scan(session: Session, scan: ScanResult, run: ScanRun, *, draft: bool = False) -> list[StudentResult]:
    """Match the scan against active students and replace the contest's results, or with
    `draft` keep them for an admin's review (nothing on the dashboard changes). Commits.
    Raises ScanCancelledError (with nothing committed) if a stop was requested meanwhile."""
    contest, rows, results = scan_rows(session, scan)
    slug = contest["slug"]
    if draft:
        if session.get(Contest, slug) is None:  # a contest never seen before: list it (no results yet)
            session.add(Contest(**{k: contest[k] for k in ("slug", "title", "contest_type", "start_time",
                                                           "duration", "user_num", "questions")}))
        _check_cancel(session, run, slug)
        drafts.supersede(session, slug, keep=run.id, decision="replaced")
        session.add(ScanDraft(run_id=run.id, contest_slug=slug, contest=contest, rows=rows))
        run.status = "review"
    else:
        write_rows(session, contest, rows, run)
        _check_cancel(session, run, slug)
        drafts.supersede(session, slug, keep=run.id, decision="outdated")
        run.status = "complete"
    run.pages_total = run.pages_done = scan.pages
    run.user_num = scan.user_num
    run.students = len(results)
    run.finished_at = utcnow()
    session.commit()
    return results

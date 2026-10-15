# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Scan a contest and store the results for all active students."""

import logging
import re
import time

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import Contest, ProblemResult, Result, ScanRun, utcnow
from app.scan.matcher import StudentResult, match_students
from app.scan.parser import parse_rows, question_labels
from app.scan.scanner import ScanCancelledError, ScanResult, scan_contest
from app.services.ratings import apply_profile_ranks
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
) -> ScanRun:
    """Scan `slug` and replace its stored results. A failed scan leaves earlier
    results for the contest untouched and is recorded as a failed ScanRun.
    kind=AUTO picks early/final from the contest's age (learnt from LeetCode if the
    contest isn't in the database yet)."""
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
        results = store_scan(session, scan, run)
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

    log.info("%s: stored results for %d students (scan run %d)", slug, len(results), run.id)
    return run


def store_scan(session: Session, scan: ScanResult, run: ScanRun) -> list[StudentResult]:
    """Match the scan against active students and replace the contest's results. Commits.
    Raises ScanCancelledError (with nothing committed) if a stop was requested meanwhile."""
    info = scan.info.contest
    labels = question_labels(scan.questions)
    contest = session.get(Contest, info.title_slug) or Contest(slug=info.title_slug)
    contest.title = info.title
    contest.contest_type = contest_type(info.title_slug)
    contest.start_time = info.start_time
    contest.duration = info.duration
    contest.user_num = scan.user_num
    contest.questions = [
        {"label": labels[q.question_id], "question_id": q.question_id, "credit": q.credit,
         "title": q.title, "title_slug": q.title_slug}
        for q in scan.questions
    ]
    session.add(contest)

    participants = parse_rows(scan.rows, scan.questions, info.start_time)
    roster = active_roster(session)
    results = match_students(roster, participants)

    # Replace only active students' rows: students since removed from the sheet keep
    # their results for this contest when it is rescanned.
    active_ids = [s.db_id for s in roster]
    session.execute(delete(ProblemResult).where(
        ProblemResult.contest_slug == contest.slug, ProblemResult.student_id.in_(active_ids)))
    session.execute(delete(Result).where(
        Result.contest_slug == contest.slug, Result.student_id.in_(active_ids)))
    for r in results:
        p = r.participant
        session.add(Result(
            contest_slug=contest.slug,
            student_id=r.student.db_id,
            scan_run_id=run.id,
            status=r.status.value,
            global_rank=p.global_rank if p else None,
            leaderboard_rank=p.position if p else None,
            rank_source="scan" if p else None,
            college_rank=r.college_rank,
            score=p.score if p else None,
            solved_count=p.solved_count if p else None,
            total_time_secs=p.total_time_secs if p else None,
            problems=[
                ProblemResult(
                    contest_slug=contest.slug, student_id=r.student.db_id, q_label=label,
                    question_id=prob.question_id, solve_secs=prob.solve_secs,
                    fail_count=prob.fail_count, lang=prob.lang,
                )
                for label, prob in (p.problems.items() if p else ())
            ],
        ))

    session.flush()
    apply_profile_ranks(session, [contest.slug])  # official ranks, if LeetCode has published them

    # Last chance to honour a stop: lock the run row so a cancel from the dashboard
    # either lands before this check (nothing is saved) or finds the scan already complete.
    session.flush()
    session.refresh(run, attribute_names=["cancel_requested"], with_for_update=True)
    if run.cancel_requested:
        raise ScanCancelledError(f"{scan.info.contest.title_slug}: scan cancelled")

    run.status = "complete"
    run.pages_total = run.pages_done = scan.pages
    run.user_num = scan.user_num
    run.students = len(results)
    run.finished_at = utcnow()
    session.commit()
    return results

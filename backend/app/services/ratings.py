# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Pull students' LeetCode contest ratings (current + per-contest history)."""

import asyncio
import logging
import re
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import RatingHistory, Result, Student, utcnow
from app.leetcode.client import LeetCodeBlockedError, LeetCodeError

log = logging.getLogger(__name__)


@dataclass
class RatingSummary:
    checked: int = 0
    rated: int = 0  # have a contest rating
    errors: int = 0


def title_to_slug(title: str) -> str:
    """'Weekly Contest 520' -> 'weekly-contest-520'"""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


async def sync_ratings(
    session: Session, client, *, concurrency: int = 4, commit_every: int = 50
) -> RatingSummary:
    """Refresh ratings for active students with a valid handle. Commits in batches."""
    students = session.scalars(
        select(Student).where(
            Student.active.is_(True), Student.lc_slug.is_not(None),
            Student.handle_status != "invalid",
        ).order_by(Student.id)
    ).all()
    summary = RatingSummary()
    if not students:
        return summary
    log.info("syncing ratings for %d students", len(students))
    sem = asyncio.Semaphore(concurrency)
    blocked = asyncio.Event()

    async def one(st: Student) -> None:
        async with sem:
            if blocked.is_set():
                return
            try:
                ranking, history = await client.contest_ranking(st.lc_username or st.lc_slug)
            except LeetCodeBlockedError as e:
                blocked.set()
                log.error("blocked by Cloudflare, stopping: %s", e)
                summary.errors += 1
                return
            except LeetCodeError as e:
                log.warning("ratings for %s failed: %s", st.lc_slug, e)
                summary.errors += 1
                return
            store_rating(session, st, ranking, history)
            summary.checked += 1
            summary.rated += ranking is not None
            if summary.checked % commit_every == 0:
                session.commit()
                log.info("ratings: %d/%d", summary.checked, len(students))

    await asyncio.gather(*(one(st) for st in students))
    session.flush()
    apply_profile_ranks(session)
    session.commit()
    log.info("ratings: %d checked, %d rated, %d errors", summary.checked, summary.rated, summary.errors)
    return summary


async def refresh_student_rating(session: Session, client, st: Student) -> None:
    """Fetch one student's rating from LeetCode now (the student page does this). Commits."""
    ranking, history = await client.contest_ranking(st.lc_username or st.lc_slug)
    store_rating(session, st, ranking, history)
    session.flush()
    apply_profile_ranks(session)
    session.commit()


def store_rating(session: Session, st: Student, ranking: dict | None, history: list[dict]) -> None:
    st.lc_rating = ranking["rating"] if ranking else None
    st.lc_global_ranking = ranking.get("globalRanking") if ranking else None
    st.lc_top_percentage = ranking.get("topPercentage") if ranking else None
    st.lc_contests_attended = ranking.get("attendedContestsCount") if ranking else None
    st.ratings_synced_at = utcnow()
    session.execute(delete(RatingHistory).where(RatingHistory.student_id == st.id))
    seen: set[int] = set()
    for h in history:
        start = h["contest"]["startTime"]
        if start in seen:
            continue
        seen.add(start)
        session.add(RatingHistory(
            student_id=st.id, start_time=start, contest_title=h["contest"]["title"],
            contest_slug=title_to_slug(h["contest"]["title"]), rating=h["rating"],
            ranking=h.get("ranking"), problems_solved=h.get("problemsSolved"),
            total_problems=h.get("totalProblems"),
        ))


def apply_profile_ranks(session: Session, slugs: list[str] | None = None) -> int:
    """Use the rank from each student's LeetCode contest history (what their profile shows)
    wherever LeetCode has published it, then redo college ranks for the contests touched.
    Does not commit. Returns the number of results changed."""
    q = (select(Result, RatingHistory.ranking)
         .join(RatingHistory, (RatingHistory.student_id == Result.student_id)
               & (RatingHistory.contest_slug == Result.contest_slug))
         .where(Result.global_rank.is_not(None), RatingHistory.ranking > 0))
    if slugs is not None:
        q = q.where(Result.contest_slug.in_(slugs))
    changed: set[str] = set()
    n = 0
    for result, ranking in session.execute(q):
        if result.global_rank != ranking or result.rank_source != "profile":
            result.global_rank, result.rank_source = ranking, "profile"
            changed.add(result.contest_slug)
            n += 1
    for slug in changed:
        ranked = session.scalars(select(Result).where(Result.contest_slug == slug, Result.global_rank.is_not(None))
                                 .order_by(Result.global_rank, Result.student_id)).all()
        for i, r in enumerate(ranked, start=1):
            r.college_rank = i
    return n

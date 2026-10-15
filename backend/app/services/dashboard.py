# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Read models for the dashboard API: contest summaries, question stats, students.

Each function loads what its page needs in a fixed, small number of queries (the
same count whether there are 10 students or 1,500): filtering and paging run in the
database, and scan state comes from one ScanSnapshot."""

import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased, joinedload, selectinload

from app.db.models import College, Contest, ProblemResult, Result, Student
from app.leetcode.links import contest_ranking_url
from app.services import vcache
from app.services.scan_status import (
    AUTO_LOOKBACK, ScanSnapshot, contest_states, load_snapshot, lookback_filter, queue_status,
)
from app.services.schedule import DEFAULT_FINAL, FinalSchedule

PARTICIPATED = ("solved", "zero")


def _end(c: Contest) -> int:
    return c.start_time + c.duration


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _has_results(contest=Contest):
    return select(Result.contest_slug).where(Result.contest_slug == contest.slug).exists()


def _summary(counts: Counter, avg_solved: float | None, best_rank: int | None) -> dict:
    students = sum(counts.values())
    participated = sum(counts[s] for s in PARTICIPATED)
    return {
        "students": students,
        "participated": participated,
        "solved_any": counts["solved"],
        "zero": counts["zero"],
        "absent": counts["absent"],
        "invalid_handle": counts["invalid_handle"],
        "no_handle": counts["no_handle"] + counts["duplicate_handle"],
        "participation_rate": participated / students if students else None,
        "avg_solved": avg_solved,
        "best_global_rank": best_rank,
    }


SAME_WEEKEND = 2 * 86400  # a biweekly (Saturday evening) and a weekly (Sunday morning)


def latest_contests(past: list[Contest]) -> list[str]:
    """The most recent finished contest, plus the most recent one of the other kind
    (weekly / biweekly) when it was held the same weekend. `past` is newest first."""
    if not past:
        return []
    newest = past[0]
    other = next((c for c in past[1:] if c.contest_type != newest.contest_type), None)
    if other is not None and newest.start_time - other.start_time <= SAME_WEEKEND:
        return [newest.slug, other.slug]
    return [newest.slug]


def contest_list(
    session: Session, now: datetime, scan_delay: timedelta, *, show: str = "all",
    contest_type: str | None = None, q: str | None = None, page: int = 1, per_page: int = 25,
    final: FinalSchedule | None = DEFAULT_FINAL,
) -> dict:
    """Upcoming/live contests, plus a page of finished ones (newest first) with their
    state and result summary. show: all | with_data | without_data."""
    now_ts = int(now.timestamp())
    end = Contest.start_time + Contest.duration

    # 1. one page of finished contests, filtered and paged in the database, with the
    #    filtered total and the number of contests that have results
    has_results = _has_results()
    other = aliased(Contest)
    with_data_total = (select(func.count()).select_from(other).where(_has_results(other))
                       .scalar_subquery())
    past = [end <= now_ts]
    if contest_type:
        past.append(Contest.contest_type == contest_type)
    if q and q.strip():
        needle = q.strip().lower()
        past.append(or_(func.lower(Contest.title).contains(needle, autoescape=True),
                        Contest.slug.contains(needle, autoescape=True)))
    if show == "with_data":
        past.append(has_results)
    elif show == "without_data":
        past.append(~has_results)
    rows = session.execute(
        select(Contest, has_results.label("has_results"), func.count().over().label("total"),
               with_data_total.label("with_data"))
        .where(*past).order_by(Contest.start_time.desc())
        .limit(per_page).offset((page - 1) * per_page)
    ).all()
    page_items = [r.Contest for r in rows]
    page_with_results = {r.Contest.slug for r in rows if r.has_results}
    if rows:
        total, with_data = rows[0].total, rows[0].with_data
    else:  # past the last page (or nothing matches): still report the totals
        total = session.scalar(select(func.count()).select_from(Contest).where(*past)) if page > 1 else 0
        with_data = session.scalar(select(func.count()).select_from(Contest).where(has_results))

    # 2. context: upcoming, recently ended (the worker may still scan them) and the
    #    newest few finished contests (for the "latest" badge, regardless of filters)
    newest = select(Contest.slug).where(end <= now_ts).order_by(Contest.start_time.desc()).limit(3)
    context = session.scalars(select(Contest).where(or_(lookback_filter(now), Contest.slug.in_(newest)))).all()
    upcoming = sorted((c for c in context if now_ts < _end(c)), key=lambda c: c.start_time)
    candidates = [c for c in context if _end(c) >= int((now - AUTO_LOOKBACK).timestamp())]
    latest_slugs = latest_contests(sorted((c for c in context if _end(c) <= now_ts),
                                          key=lambda c: c.start_time, reverse=True))

    # 3. scan state, once
    shown = upcoming + page_items
    snap = load_snapshot(session, [c.slug for c in shown] + [c.slug for c in candidates])
    queue = queue_status(session, now, snap)
    states = contest_states(session, shown, now, scan_delay, queue, final, snap=snap, candidates=candidates)

    # 4. result summaries for the page, in one grouped query
    counts: dict[str, Counter] = defaultdict(Counter)
    solved_sum: Counter = Counter()
    solved_n: Counter = Counter()
    best: dict[str, int] = {}
    slugs = [c.slug for c in page_items if c.slug in page_with_results]
    if slugs:
        for slug, st, n, s_sum, s_n, rank in session.execute(
            select(Result.contest_slug, Result.status, func.count(), func.sum(Result.solved_count),
                   func.count(Result.solved_count), func.min(Result.global_rank))
            .where(Result.contest_slug.in_(slugs)).group_by(Result.contest_slug, Result.status)
        ):
            counts[slug][st] = n
            if st in PARTICIPATED:
                solved_sum[slug] += s_sum or 0
                solved_n[slug] += s_n
                if rank is not None:
                    best[slug] = min(rank, best.get(slug, rank))

    def item(c: Contest) -> dict:
        avg = solved_sum[c.slug] / solved_n[c.slug] if solved_n[c.slug] else None
        return {
            "slug": c.slug, "title": c.title, "contest_type": c.contest_type,
            "start_time": c.start_time, "duration": c.duration,
            "participants_worldwide": c.user_num, **states[c.slug],
            "summary": _summary(counts[c.slug], avg, best.get(c.slug)) if c.slug in counts else None,
        }

    return {
        "upcoming": [item(c) for c in upcoming],
        "items": [item(c) for c in page_items],
        "total": total, "page": page, "per_page": per_page,
        "with_data": with_data,
        "latest_slugs": latest_slugs,
        **queue,
    }


# ---- one contest -------------------------------------------------------------------------

def _scoped(rows: list, student_ids: set[int] | None) -> list:
    return rows if student_ids is None else [r for r in rows if r[0].student_id in student_ids]


def _detail(c: Contest, rows: list, problems: list[ProblemResult], student_ids: set[int] | None,
            snap: ScanSnapshot | None) -> dict:
    """Summary and per-question stats from already-loaded rows ((Result, college name) pairs)."""
    scoped = _scoped(rows, student_ids)
    counts = Counter(r.status for r, _ in scoped)
    participants = [r for r, _ in scoped if r.status in PARTICIPATED]
    participant_ids = {r.student_id for r in participants}
    solved = [r.solved_count or 0 for r in participants]
    ranks = [r.global_rank for r in participants if r.global_rank]

    by_q: dict[str, list[ProblemResult]] = defaultdict(list)
    for pr in problems:
        if pr.student_id in participant_ids:
            by_q[pr.q_label].append(pr)
    questions = []
    for q in c.questions:
        prs = by_q.get(q["label"], [])
        questions.append({
            **q,
            "url": f"https://leetcode.com/problems/{q['title_slug']}/" if q.get("title_slug") else None,
            "solved": len(prs),
            "solve_rate": len(prs) / len(participants) if participants else None,
            "median_solve_secs": int(statistics.median(p.solve_secs for p in prs)) if prs else None,
            "avg_wrong": sum(p.fail_count for p in prs) / len(prs) if prs else None,
        })

    complete = [r for r in (snap.runs_of(c.slug) if snap else []) if r.status == "complete"]
    run = complete[-1] if complete else None
    return {
        "slug": c.slug,
        "title": c.title,
        "contest_type": c.contest_type,
        "start_time": c.start_time,
        "duration": c.duration,
        "participants_worldwide": c.user_num,
        "leetcode_url": f"https://leetcode.com/contest/{c.slug}/",
        "scan": {"kind": run.kind, "finished_at": iso(run.finished_at)} if run else None,
        "summary": _summary(counts, sum(solved) / len(solved) if solved else None,
                            min(ranks) if ranks else None),
        "questions": questions,
        "colleges": sorted({name for _, name in rows if name}),
    }


def _load_contest_rows(session: Session, slug: str) -> tuple[list, list[ProblemResult]]:
    """Every result of the contest with the student's college name, and every solved problem."""
    rows = session.execute(
        select(Result, College.name).join(Student, Student.id == Result.student_id)
        .outerjoin(College, College.id == Student.college_id).where(Result.contest_slug == slug)
    ).all()
    problems = session.scalars(select(ProblemResult).where(ProblemResult.contest_slug == slug)).all()
    return [tuple(r) for r in rows], list(problems)


def contest_page(session: Session, slug: str, *, now: datetime, scan_delay: timedelta,
                 final: FinalSchedule | None = DEFAULT_FINAL, student_ids: set[int] | None = None) -> dict | None:
    """Everything the contest page shows, in six queries."""
    from app.services.analytics import distributions  # analytics imports this module

    lookback_cutoff = int((now - AUTO_LOOKBACK).timestamp())
    contests = session.scalars(select(Contest).where(or_(Contest.slug == slug, lookback_filter(now)))).all()
    c = next((x for x in contests if x.slug == slug), None)
    if c is None:
        return None
    candidates = [x for x in contests if _end(x) >= lookback_cutoff]
    snap = load_snapshot(session, [slug] + [x.slug for x in candidates])
    queue = queue_status(session, now, snap)
    state = contest_states(session, [c], now, scan_delay, queue, final, snap=snap, candidates=candidates)[slug]

    # The results, summary and charts only change with the data (a completed scan
    # commits its results and its run together), so they're built once per data
    # version; the status above depends on the clock and is worked out every time.
    def body() -> dict:
        rows, problems = _load_contest_rows(session, slug)
        return {
            **_detail(c, rows, problems, student_ids, snap),
            "distributions": distributions(c, _scoped(rows, student_ids), problems, student_ids),
        }
    scope = frozenset(student_ids) if student_ids is not None else None
    data = vcache.cached((snap.data_version, "contest_page", slug, scope), body) if snap.data_version else body()
    return {
        **data,
        "status": state,
        "final_scan_at": iso(final.due_at_ts(c.start_time, c.duration)) if final else None,
    }


def contest_detail(session: Session, slug: str, student_ids: set[int] | None = None) -> dict | None:
    """Summary and per-question stats; `student_ids` limits them to those students."""
    c = session.get(Contest, slug)
    if c is None:
        return None
    rows, problems = _load_contest_rows(session, slug)
    return _detail(c, rows, problems, student_ids, load_snapshot(session, [slug]))


# ---- students ----------------------------------------------------------------------------

def student_list(session: Session) -> list[dict]:
    """Every student (removed ones too), by name."""
    counts = {sid: (scanned, attended) for sid, scanned, attended in session.execute(
        select(Result.student_id, func.count(), func.count().filter(Result.status.in_(PARTICIPATED)))
        .group_by(Result.student_id)
    )}
    rows = session.execute(
        select(Student.id, Student.roll_no, Student.name, College.name, Student.extra, Student.lc_username,
               Student.lc_slug, Student.lc_handle_raw, Student.handle_status, Student.active, Student.lc_rating,
               Student.lc_top_percentage, Student.lc_contests_attended, Student.ratings_synced_at)
        .outerjoin(College, College.id == Student.college_id)
        .order_by(Student.name, Student.id)
    )
    return [
        {
            "id": sid,
            "roll_no": roll_no,
            "name": name,
            "college": college or "",
            "extra": extra or {},
            "leetcode_handle": username or slug or raw,
            "handle_status": status if slug else "missing",
            "active": active,
            "contests_attended": counts.get(sid, (0, 0))[1],
            "contests_scanned": counts.get(sid, (0, 0))[0],
            "rating": round(rating) if rating is not None else None,
            "rating_top_pct": top_pct,
            "rated_contests": rated,
            "rating_synced_at": iso(synced),
        }
        for sid, roll_no, name, college, extra, username, slug, raw, status, active, rating, top_pct, rated, synced
        in rows
    ]


STUDENT_SORTS = ("name", "rating_desc", "rating_asc", "attended_desc", "attended_asc")


def students_page(session: Session, *, version: str, q: str = "", college: str = "", handle: str = "",
                  include_removed: bool = False, sort: str = "name", offset: int = 0, limit: int = 100) -> dict:
    """The Students page: filtered, sorted and sliced on the server. The full list is
    built once per data version (app.services.vcache)."""
    if sort not in STUDENT_SORTS:
        raise ValueError(f"can't sort by {sort!r}")
    everyone = vcache.cached((version, "student_list"), lambda: student_list(session))
    needle = q.strip().lower()
    rows = [s for s in everyone
            if (include_removed or s["active"])
            and (not college or s["college"] == college)
            and (not handle or s["handle_status"] == handle)
            and (not needle or needle in s["name"].lower() or needle in s["roll_no"].lower()
                 or needle in s["leetcode_handle"].lower())]
    if sort != "name":  # already by name
        desc = sort.endswith("_desc")
        if sort.startswith("attended"):  # ties: better attendance rate, then name
            def key(s):
                rate = s["contests_attended"] / (s["contests_scanned"] or 1)
                return (s["contests_attended"], rate) if not desc else (-s["contests_attended"], -rate)
            rows = sorted(rows, key=key)
        else:  # unrated students last, whichever way
            rated = sorted((s for s in rows if s["rating"] is not None), key=lambda s: s["rating"], reverse=desc)
            rows = rated + [s for s in rows if s["rating"] is None]
    active = [s for s in everyone if s["active"]]
    return {
        "rows": rows[offset:offset + limit],
        "total": len(rows),
        "active": len(active),
        "handle_problems": sum(1 for s in active if s["handle_status"] in ("invalid", "missing")),
        "colleges": sorted({s["college"] for s in everyone if s["college"]}),
    }


def student_detail(session: Session, student_id: int) -> dict | None:
    st = session.get(Student, student_id, options=[joinedload(Student.college)])
    if st is None:
        return None
    rows = session.execute(
        select(Result, Contest).join(Contest, Contest.slug == Result.contest_slug)
        .where(Result.student_id == student_id)
        .options(selectinload(Result.problems))
        .order_by(Contest.start_time.desc())
    ).all()
    history = [
        {
            "contest_slug": c.slug,
            "contest_title": c.title,
            "start_time": c.start_time,
            "questions": [q["label"] for q in c.questions],
            "status": r.status,
            "global_rank": r.global_rank,
            "ranking_url": contest_ranking_url(c.slug, r.leaderboard_rank or r.global_rank) if r.global_rank else None,
            "rank_official": r.rank_source == "profile",
            "leaderboard_rank": r.leaderboard_rank or r.global_rank,
            "college_rank": r.college_rank,
            "solved": r.solved_count,
            "total_time_secs": r.total_time_secs,
            "problems": {
                p.q_label: {"solve_secs": p.solve_secs, "fail_count": p.fail_count, "lang": p.lang}
                for p in r.problems
            },
        }
        for r, c in rows
    ]
    handle = st.lc_username or st.lc_slug
    return {
        "id": st.id,
        "roll_no": st.roll_no,
        "name": st.name,
        "college": st.college.name if st.college else "",
        "extra": st.extra or {},
        "leetcode_handle": handle or st.lc_handle_raw,
        "leetcode_url": f"https://leetcode.com/u/{handle}/" if handle else None,
        "handle_status": st.handle_status if st.lc_slug else "missing",
        "active": st.active,
        "history": history,
    }

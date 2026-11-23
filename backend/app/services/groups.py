# Author: Rajveer Sharma
# © NxtWave
# Date: 23 November 2026
"""A group of students picked by a sheet column (e.g. Group = "Top K"): how they did in
each contest and how they rank among themselves.

- In a contest, a student's group rank is their place among the group's students who
  took part, in the contest's own order (college rank: global rank, then less time).
- Overall, the group is ranked like the portal ranking in Analytics: most LeetCode
  contest points over the contests shown, ties to less total time, then the better
  best global rank. Students with no points are listed after, unranked."""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Result, Student
from app.services import vcache
from app.services.analytics import MAX_FILTER_VALUES, PARTICIPATED, _scanned_contests

DEFAULT_KEY, DEFAULT_VALUE = "Group", "Top K"


def _round(x: float | None, digits: int = 2) -> float | None:
    return None if x is None else round(x, digits)


def group_options(students: list[Student]) -> list[dict]:
    """Sheet columns with 2-40 distinct values among active students, and their values."""
    values: dict[str, set[str]] = defaultdict(set)
    for st in students:
        for k, v in (st.extra or {}).items():
            if v:
                values[k].add(v)
    return [{"key": k, "values": sorted(vs)} for k, vs in sorted(values.items())
            if 2 <= len(vs) <= MAX_FILTER_VALUES]


def group_report(session: Session, *, key: str = DEFAULT_KEY, value: str = DEFAULT_VALUE,
                 last: int | None = None, version: str | None = None) -> dict:
    def compute():
        return _report(session, key, value, last)
    if version is None:
        return compute()
    return vcache.cached((version, "group", key, value, last), compute)


def _report(session: Session, key: str, value: str, last: int | None) -> dict:
    active = list(session.scalars(select(Student).where(Student.active.is_(True))
                                  .options(selectinload(Student.college))))
    members = {st.id: st for st in active if (st.extra or {}).get(key) == value}
    contests = _scanned_contests(session)
    if last:
        contests = contests[-last:]
    slugs = [c.slug for c in contests]

    rows: dict[int, dict[str, Result]] = defaultdict(dict)  # student -> slug -> result
    if members and slugs:
        q = select(Result).where(Result.contest_slug.in_(slugs), Result.student_id.in_(list(members)))
        for r in session.scalars(q):
            rows[r.student_id][r.contest_slug] = r

    colleges = {st.id: st.college.name if st.college else "" for st in members.values()}

    # each contest: the group's participants in the contest's order -> group rank
    group_rank: dict[tuple[int, str], int] = {}
    contest_out = []
    for c in contests:
        ranked = sorted(((sid, by[c.slug]) for sid, by in rows.items()
                         if c.slug in by and by[c.slug].college_rank is not None),
                        key=lambda x: x[1].college_rank)
        for i, (sid, _) in enumerate(ranked, start=1):
            group_rank[(sid, c.slug)] = i
        part = [by[c.slug] for by in rows.values() if c.slug in by and by[c.slug].status in PARTICIPATED]
        solved = [r.solved_count or 0 for r in part]
        contest_out.append({
            "slug": c.slug, "title": c.title, "start_time": c.start_time,
            "questions": len(c.questions or []),
            "students": len(members),
            "participated": len(part),
            "participation_rate": _round(len(part) / len(members), 3) if members else None,
            "avg_solved": _round(sum(solved) / len(solved)) if solved else None,
            "solved_all": sum(1 for r in part if c.questions and (r.solved_count or 0) >= len(c.questions)),
            "best_global_rank": min((r.global_rank for r in part if r.global_rank), default=None),
            "top": [{"id": sid, "name": members[sid].name, "solved": r.solved_count, "global_rank": r.global_rank,
                     "college_rank": r.college_rank}
                    for sid, r in ranked[:3]],
        })

    students = []
    for sid, st in members.items():
        by = rows.get(sid, {})
        att = [r for r in by.values() if r.status in PARTICIPATED]
        ranks = [group_rank[(sid, s)] for s in by if (sid, s) in group_rank]
        students.append({
            "id": sid, "name": st.name, "roll_no": st.roll_no, "college": colleges[sid], "extra": st.extra or {},
            "handle": st.lc_slug or st.lc_handle_raw or "",
            "points": sum(r.score or 0 for r in att),
            "total_time_secs": sum(r.total_time_secs or 0 for r in att),
            "attended": len(att),
            "avg_solved": _round(sum(r.solved_count or 0 for r in att) / len(att)) if att else None,
            "best_global_rank": min((r.global_rank for r in att if r.global_rank), default=None),
            "best_group_rank": min(ranks, default=None),
            "avg_group_rank": _round(sum(ranks) / len(ranks), 1) if ranks else None,
            "results": {
                s: {"status": r.status, "rank": group_rank.get((sid, s)), "solved": r.solved_count,
                    "global_rank": r.global_rank, "college_rank": r.college_rank, "score": r.score,
                    "total_time_secs": r.total_time_secs}
                for s, r in by.items()
            },
        })
    # the portal ranking's rule (analytics.standings), within the group
    students.sort(key=lambda s: (s["points"] <= 0, -s["points"], s["total_time_secs"],
                                 s["best_global_rank"] or 10**9, s["name"].lower()))
    rank = 0
    for s in students:
        s["rank"] = (rank := rank + 1) if s["points"] > 0 else None

    return {
        "key": key, "value": value, "last": last,
        "options": group_options(active),
        "contests": contest_out[::-1],  # newest first
        "students": students,
    }

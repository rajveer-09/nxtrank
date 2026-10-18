# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""Topic-wise stats over the last N scanned contests, from the effective tags
(services/tags.py). A question with several tags counts toward each of them.

| metric       | definition                                                        |
|--------------|-------------------------------------------------------------------|
| appeared     | tagged questions in contests the student(s) attended              |
| solved       | how many of those were solved                                     |
| solve rate   | solved / appeared                                                 |
| accuracy     | accepted / (accepted + wrong submissions on those questions)      |
| median time  | of the solves in that topic (groups: to the minute)               |

Each question has one tag source, so every number is kept as an official part and a
provisional part that add up exactly; "official only" uses just the first. Medians
can't be added, so they're kept both ways."""

import json
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from app.db.models import AppState, Contest, ProblemResult, QuestionTag, QuestionTagStatus, Result, Student
from app.services import vcache
from app.services.analytics import _scanned_contests
from app.services.tags import LAST_RUN_KEY

ATTENDED = ("solved", "zero")
WEAK_MIN_APPEARED = 10  # "weakest topics" only among topics seen at least this often
WEAKEST = 5


@dataclass
class _Part:
    appeared: int = 0
    solved: int = 0
    wrong: int = 0
    times: dict[int, int] = field(default_factory=lambda: defaultdict(int))  # value -> how many
    questions: set = field(default_factory=set)

    def add(self, other: "_Part") -> None:
        self.appeared += other.appeared
        self.solved += other.solved
        self.wrong += other.wrong
        for k, n in other.times.items():
            self.times[k] += n
        self.questions |= other.questions


def _median(times: dict[int, int], minutes: bool) -> int | None:
    total = sum(times.values())
    if not total:
        return None
    seen = 0
    for value in sorted(times):
        seen += times[value]
        if seen * 2 >= total:
            return value * 60 + 30 if minutes else value
    return None


def _metrics(p: _Part, minutes: bool) -> dict:
    return {
        "appeared": p.appeared, "solved": p.solved,
        "solve_rate": round(p.solved / p.appeared, 4) if p.appeared else None,
        "accuracy": round(p.solved / (p.solved + p.wrong), 4) if p.solved + p.wrong else None,
        "median_secs": _median(p.times, minutes),
    }


def _window(session: Session, last: int | None) -> list[Contest]:
    contests = _scanned_contests(session)  # oldest first
    return contests[-last:] if last else contests


def _tag_map(session: Session, contests: list[Contest]) -> tuple[dict, dict, dict]:
    """(contest, label) -> [(tag slug, name, source)], question slug per (contest, label),
    and each window question's state."""
    where = {(c.slug, q["label"]): q["title_slug"] for c in contests for q in c.questions or [] if q.get("title_slug")}
    slugs = set(where.values())
    tags: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    states: dict[str, str] = {}
    if slugs:
        for t in session.scalars(select(QuestionTag).where(QuestionTag.question_slug.in_(slugs))):
            tags[t.question_slug].append((t.tag_slug, t.tag_name, t.source))
        states = dict(session.execute(select(QuestionTagStatus.question_slug, QuestionTagStatus.state)
                                      .where(QuestionTagStatus.question_slug.in_(slugs))).all())
    by_question = {key: tags.get(slug, []) for key, slug in where.items()}
    return by_question, where, {s: states.get(s, "pending") for s in slugs}


def _coverage(contests: list[Contest], where: dict, states: dict[str, str], last_run: str | None) -> dict:
    provisional_contests = {c for (c, _label), slug in where.items() if states.get(slug) == "provisional"}
    count = defaultdict(int)
    for state in states.values():
        count[state] += 1
    return {"contests": len(contests), "contests_provisional": len(provisional_contests),
            "questions": len(states), "official": count["official"], "provisional": count["provisional"],
            "insufficient": count["insufficient"], "pending": count["pending"], "last_refresh": last_run}


def _rows(parts: dict[tuple[str, str], dict[str, _Part]], minutes: bool) -> list[dict]:
    rows = []
    for (slug, name), by_source in parts.items():
        everything = _Part()
        for p in by_source.values():
            everything.add(p)
        official = by_source.get("official", _Part())
        provisional = by_source.get("community", _Part())
        rows.append({
            "slug": slug, "name": name, **_metrics(everything, minutes),
            "official": _metrics(official, minutes),
            "provisional_appeared": provisional.appeared,
            "provisional_questions": len(provisional.questions),
        })
    rows.sort(key=lambda r: (-r["appeared"], r["name"]))
    return rows


def _last_run(session: Session) -> str | None:
    row = session.get(AppState, LAST_RUN_KEY)
    return json.loads(row.value).get("at") if row and row.value else None


def group_topics(session: Session, *, last: int | None = None, student_ids: set[int] | None = None,
                 version: str | None = None) -> dict:
    """Topic stats for a group: every active student, or `student_ids`. Three grouped
    queries over the window, whatever the number of students."""
    def compute():
        contests = _window(session, last)
        tag_of, where, states = _tag_map(session, contests)
        slugs = [c.slug for c in contests]
        attended: dict[str, int] = {}
        solved: dict[tuple[str, str], tuple[int, int]] = {}
        minutes: dict[tuple[str, str], dict[int, int]] = defaultdict(dict)
        if slugs and (student_ids is None or student_ids):
            scope = [Student.active.is_(True), Result.contest_slug.in_(slugs), Result.status.in_(ATTENDED)]
            if student_ids is not None:
                scope.append(Result.student_id.in_(student_ids))
            attended = dict(session.execute(
                select(Result.contest_slug, func.count()).join(Student, Student.id == Result.student_id)
                .where(*scope).group_by(Result.contest_slug)).all())
            joined = (select(ProblemResult.contest_slug, ProblemResult.q_label)
                      .join(Result, (Result.contest_slug == ProblemResult.contest_slug)
                            & (Result.student_id == ProblemResult.student_id))
                      .join(Student, Student.id == Result.student_id).where(*scope))
            for c, label, n, wrong in session.execute(
                    joined.add_columns(func.count(), func.coalesce(func.sum(ProblemResult.fail_count), 0))
                    .group_by(ProblemResult.contest_slug, ProblemResult.q_label)):
                solved[(c, label)] = (n, int(wrong))
            # a literal 60: PostgreSQL treats two bound parameters as different GROUP BY expressions
            minute = ProblemResult.solve_secs / literal_column("60")
            for c, label, m, n in session.execute(
                    joined.add_columns(minute, func.count())
                    .group_by(ProblemResult.contest_slug, ProblemResult.q_label, minute)):
                minutes[(c, label)][int(m)] = n

        parts: dict[tuple[str, str], dict[str, _Part]] = defaultdict(dict)
        for (c, label), tags in tag_of.items():
            n, wrong = solved.get((c, label), (0, 0))
            for slug, name, source in tags:
                p = parts[(slug, name)].setdefault(source, _Part())
                p.appeared += attended.get(c, 0)
                p.solved += n
                p.wrong += wrong
                for m, k in minutes.get((c, label), {}).items():
                    p.times[m] += k
                p.questions.add(where[(c, label)])
        rows = _rows(parts, minutes=True)
        weak = sorted((r for r in rows if r["appeared"] >= WEAK_MIN_APPEARED and r["solve_rate"] is not None),
                      key=lambda r: (r["solve_rate"], r["name"]))[:WEAKEST]
        return {"topics": rows, "weakest": [r["slug"] for r in weak],
                "coverage": _coverage(contests, where, states, _last_run(session))}

    if version is None:
        return compute()
    scope_key = frozenset(student_ids) if student_ids is not None else None
    return vcache.cached((version, "topics", last, scope_key), compute)


def student_topics(session: Session, student_id: int, *, last: int | None = None) -> dict:
    """One student's topic stats (exact medians)."""
    contests = _window(session, last)
    tag_of, where, states = _tag_map(session, contests)
    slugs = [c.slug for c in contests]
    went = set(session.scalars(select(Result.contest_slug).where(
        Result.student_id == student_id, Result.contest_slug.in_(slugs), Result.status.in_(ATTENDED)))) if slugs else set()
    solves = {(p.contest_slug, p.q_label): p for p in session.scalars(select(ProblemResult).where(
        ProblemResult.student_id == student_id, ProblemResult.contest_slug.in_(went)))} if went else {}
    parts: dict[tuple[str, str], dict[str, _Part]] = defaultdict(dict)
    for (c, label), tags in tag_of.items():
        if c not in went:
            continue
        pr = solves.get((c, label))
        for slug, name, source in tags:
            p = parts[(slug, name)].setdefault(source, _Part())
            p.appeared += 1
            p.questions.add(where[(c, label)])
            if pr is not None:
                p.solved += 1
                p.wrong += pr.fail_count
                p.times[pr.solve_secs] += 1
    return {"topics": _rows(parts, minutes=False), "coverage": _coverage(contests, where, states, _last_run(session))}


def contest_tags(session: Session, contest: Contest) -> dict[str, dict]:
    """label -> {state, tags, mentions, fetched_at} for a contest page's tag chips."""
    slugs = {q["title_slug"]: q["label"] for q in contest.questions or [] if q.get("title_slug")}
    if not slugs:
        return {}
    tags: dict[str, list[dict]] = defaultdict(list)
    statuses: dict[str, QuestionTagStatus] = {}
    # one query: each question's status, joined to its effective tags (if any)
    for st, t in session.execute(
            select(QuestionTagStatus, QuestionTag)
            .outerjoin(QuestionTag, QuestionTag.question_slug == QuestionTagStatus.question_slug)
            .where(QuestionTagStatus.question_slug.in_(slugs)).order_by(QuestionTag.tag_name)):
        statuses[st.question_slug] = st
        if t is not None:
            tags[t.question_slug].append({"slug": t.tag_slug, "name": t.tag_name, "source": t.source})
    out = {}
    for slug, label in slugs.items():
        st = statuses.get(slug)
        fetched = st.community_fetched_at if st and st.state == "provisional" else (st.official_fetched_at if st else None)
        out[label] = {"state": st.state if st else "pending", "tags": tags.get(slug, []),
                      "mentions": st.community_mentions if st else None,
                      "fetched_at": fetched.isoformat() if fetched else None}
    return out

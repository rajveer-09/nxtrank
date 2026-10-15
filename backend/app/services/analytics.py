# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Cross-contest analytics: consistency, question-wise performance, cohort trends,
college comparison and watch lists.

Definitions (also shown in the UI): attended = on the leaderboard; top % = global rank /
participants x 100; consistency (>= 3 scanned contests) = 60% attendance + 40% stability,
stability = 1 - min(1, std-dev of problems solved / 1.5); trend = average solved in the
last (up to 4) attended contests minus the same number before them. Wrong submissions
only count problems that were eventually accepted.

Raw numbers come from the summary tables (PostgreSQL) or from the rows in Python (SQLite,
and the reference the summaries are tested against); the rules are applied here, once.
"""

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models import College, Contest, ProblemResult, RatingHistory, Result, Student, StudentStats
from app.services import summaries, vcache

PARTICIPATED = ("solved", "zero")
MAX_FILTER_VALUES = 40
TREND_THRESHOLD = 0.5
ABSENT_STREAK_ALERT = 3
TOP_N = 100  # colleges are compared by how many students they have in the portal's top 100
MEDALS = 3


@dataclass
class Row:
    status: str
    global_rank: int | None
    college_rank: int | None
    solved: int | None
    total_time: int | None
    problems: dict[str, tuple[int, int]] = field(default_factory=dict)  # label -> (secs, fails)
    score: int | None = None  # LeetCode contest points

    @property
    def attended(self) -> bool:
        return self.status in PARTICIPATED


@dataclass
class Window:
    contests: list[Contest]  # scanned, oldest first
    students: dict[int, Student]
    rows: dict[int, dict[str, Row]]  # student_id -> slug -> row
    labels: list[str]

    def labels_of(self, c: Contest) -> list[str]:
        return [q["label"] for q in c.questions]


@dataclass(slots=True)
class Person:
    """What analytics show about a student: plain values, much cheaper to load for
    1,500 students than ORM objects."""

    id: int
    name: str
    roll_no: str
    college_id: int | None
    college: str  # "" if none
    extra: dict
    rating: float | None
    active: bool

    @classmethod
    def of(cls, st: Student) -> "Person":
        return cls(st.id, st.name, st.roll_no, st.college_id, st.college.name if st.college else "",
                   st.extra or {}, st.lc_rating, st.active)


# label -> (attended contests that had it, solved, median secs, total secs, best secs, wrong submissions)
QuestionRaw = tuple[int, int, float | None, int | None, int | None, int]
NO_QUESTION: QuestionRaw = (0, 0, None, None, None, 0)


@dataclass
class Raw:
    """A student's raw numbers over a window (the columns of student_stats)."""

    scanned: int = 0
    attended: int = 0
    sum_solved: int = 0
    sum_solved_sq: int = 0
    max_solved: int | None = None
    avg_top_pct: float | None = None
    best_global_rank: int | None = None
    best_college_rank: int | None = None
    points: int = 0
    total_time: int = 0
    longest_streak: int = 0
    current_streak: int = 0
    absent_streak: int = 0
    trend_k: int | None = None
    trend_recent: int | None = None
    trend_before: int | None = None
    questions: dict[str, QuestionRaw] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row) -> "Raw":
        """From a student_stats row or a live summaries.student_select() row."""
        values = dict(zip(summaries.STUDENT_COLUMNS, row))
        values.pop("student_id")
        values["questions"] = {k: tuple(v) for k, v in (values["questions"] or {}).items()}
        return cls(**values)


@dataclass
class CohortRaw:
    """Aggregates over a set of students (the shapes of summaries.cohort_select())."""

    q_att: dict[str, int] = field(default_factory=dict)  # label -> attempts
    q_sol: dict[str, tuple] = field(default_factory=dict)  # label -> (solved, median, p25, p75, wrong)
    colleges: dict[str, float | None] = field(default_factory=dict)  # college name -> median top %
    contests: dict[str, tuple] = field(default_factory=dict)  # slug -> (students, part, sum_solved, median %, best)
    contest_q: dict[tuple[str, str], tuple] = field(default_factory=dict)  # (slug, label) -> (solved, median, wrong)

    @classmethod
    def from_payload(cls, payload: dict, college_names: dict[int, str]) -> "CohortRaw":
        return cls(
            q_att=dict(payload["q_att"]),
            q_sol={k: tuple(v) for k, v in payload["q_sol"].items()},
            colleges={college_names.get(int(k), ""): v for k, v in payload["colleges"].items()},
            contests={k: tuple(v) for k, v in payload["contests"].items()},
            contest_q={tuple(k.rsplit("/", 1)): tuple(v) for k, v in payload["contest_q"].items()},
        )


def _round(x: float | None, digits: int = 2) -> float | None:
    return None if x is None else round(x, digits)


def _median(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def top_pct(rank: int | None, user_num: int | None) -> float | None:
    if not rank or not user_num:
        return None
    return rank / user_num * 100


def _quantile(xs: list[int], q: float) -> float | None:
    """Linear interpolation between closest ranks (= PostgreSQL percentile_cont)."""
    if not xs:
        return None
    xs = sorted(xs)
    i = (len(xs) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def _labels(contests: list[Contest]) -> list[str]:
    return sorted({q["label"] for c in contests for q in c.questions}, key=lambda s: int(s[1:]))


def _scanned_contests(session: Session) -> list[Contest]:
    has_results = select(Result.contest_slug).where(Result.contest_slug == Contest.slug).exists()
    return list(session.scalars(select(Contest).where(has_results).order_by(Contest.start_time, Contest.slug)))


# ---- rules: raw numbers -> metrics ------------------------------------------------------


def consistency_score(n_scanned: int, n_attended: int, solved_std: float | None) -> int | None:
    if n_scanned < 3:
        return None
    attendance = n_attended / n_scanned
    stability = 1 - min(1.0, solved_std / 1.5) if (n_attended >= 2 and solved_std is not None) else 0.0
    return round(100 * (0.6 * attendance + 0.4 * stability))


def consistency_label(score: int | None) -> str | None:
    if score is None:
        return None
    if score >= 80:
        return "Very consistent"
    if score >= 60:
        return "Consistent"
    if score >= 40:
        return "Irregular"
    return "Inconsistent"


def solved_trend(values: list[int]) -> float | None:
    if len(values) < 4:
        return None
    k = min(4, len(values) // 2)
    return _mean(values[-k:]) - _mean(values[-2 * k:-k])


def _pstdev(n: int, total: int, total_sq: int) -> float:
    """Population standard deviation from the count, sum and sum of squares (exact
    integer arithmetic until the square root)."""
    return math.sqrt(n * total_sq - total * total) / n


def question_metrics(r: Raw, labels: list[str]) -> dict:
    questions = {}
    for label in labels:
        attempted, solved, median, total, best, wrong = r.questions.get(label, NO_QUESTION)
        questions[label] = {
            "attempted_contests": attempted,
            "solved": solved,
            "solve_rate": _solve_rate(solved, attempted),
            "median_secs": median,
            "avg_secs": _round(total / solved, 0) if solved else None,
            "best_secs": best,
            "wrong": wrong,
            "wrong_per_solve": _round(wrong / solved) if solved else None,
        }
    return questions


def _solve_rate(solved: int, attempted: int) -> float | None:
    return _round(solved / attempted, 3) if attempted else None


def metrics_from_raw(r: Raw, labels: list[str], questions: bool = True) -> dict:
    """The student's metrics; `questions=False` leaves out the per-question detail
    (the costly part, and only needed for students actually shown)."""
    std = _pstdev(r.attended, r.sum_solved, r.sum_solved_sq) if r.attended >= 2 else None
    trend = r.trend_recent / r.trend_k - r.trend_before / r.trend_k if r.trend_k else None
    score = consistency_score(r.scanned, r.attended, std)
    out = {
        "contests_scanned": r.scanned,
        "contests_attended": r.attended,
        "attendance_rate": _round(r.attended / r.scanned, 3) if r.scanned else None,
        "current_streak": r.current_streak,
        "longest_streak": r.longest_streak,
        "absent_streak": r.absent_streak,
        "avg_solved": _round(r.sum_solved / r.attended) if r.attended else None,
        "solved_std": _round(std),
        "avg_top_pct": _round(r.avg_top_pct),
        "best_global_rank": r.best_global_rank,
        "best_college_rank": r.best_college_rank,
        "consistency": score,
        "consistency_label": consistency_label(score),
        "trend": _round(trend),
        "trend_label": (None if trend is None else "improving" if trend >= TREND_THRESHOLD
                        else "declining" if trend <= -TREND_THRESHOLD else "steady"),
    }
    if questions:
        out["questions"] = question_metrics(r, labels)
    return out


def question_summary(labels: list[str], c: CohortRaw) -> list[dict]:
    out = []
    for label in labels:
        attempts = c.q_att.get(label, 0)
        solves, median, p25, p75, wrong = c.q_sol.get(label, (0, None, None, None, 0))
        out.append({
            "label": label, "attempts": attempts, "solved": solves,
            "solve_rate": _round(solves / attempts, 3) if attempts else None,
            "median_secs": median, "p25_secs": p25, "p75_secs": p75, "wrong": wrong,
            "wrong_per_solve": _round(wrong / solves) if solves else None,
        })
    return out


def contest_points(contests: list[Contest], c: CohortRaw) -> list[dict]:
    out = []
    for ct in contests:
        students, part, total_solved, median_pct, best = c.contests.get(ct.slug, (0, 0, 0, None, None))
        qs = {}
        for label in (q["label"] for q in ct.questions):
            solves, median, wrong = c.contest_q.get((ct.slug, label), (0, None, 0))
            qs[label] = {
                "solve_rate": _round(solves / part, 3) if part else None,
                "solved": solves,
                "median_secs": median,
                "wrong_per_solver": _round(wrong / solves) if solves else None,
            }
        out.append({
            "slug": ct.slug, "title": ct.title, "start_time": ct.start_time,
            "students": students, "participated": part,
            "participation_rate": _round(part / students, 3) if students else None,
            "avg_solved": _round(total_solved / part) if part else None,
            "median_top_pct": _round(median_pct),
            "best_global_rank": best,
            "questions": qs,
        })
    return out


def standings(students: dict[int, Person], raw: dict[int, Raw]) -> list[tuple[int, int, int]]:
    """Portal ranking over the window: (student_id, points, total_time), best first.
    Most LeetCode contest points wins; ties go to less total time, then the better
    best global rank -- for a single contest this is LeetCode's own order. Students
    with no points are not ranked."""
    out = []
    for sid, st in students.items():
        r = raw.get(sid)
        if r is None or r.points <= 0:
            continue
        out.append((sid, r.points, r.total_time, r.best_global_rank or 10**9, st.name.lower()))
    out.sort(key=lambda x: (-x[1], x[2], x[3], x[4]))
    return [(sid, points, time) for sid, points, time, _, _ in out]


# ---- reference: raw numbers from the rows, in Python ------------------------------------


def load_window(
    session: Session, *, last: int | None = None, college: str | None = None,
    extra: dict[str, str] | None = None, student_ids: set[int] | None = None,
) -> Window:
    contests = _scanned_contests(session)
    if last:
        contests = contests[-last:]
    slugs = [c.slug for c in contests]

    q = select(Student).options(joinedload(Student.college))
    if student_ids is not None:
        q = q.where(Student.id.in_(student_ids))
    else:
        q = q.where(Student.active.is_(True))
    students = {st.id: st for st in session.scalars(q) if _matches(Person.of(st), college, extra)}

    rows: dict[int, dict[str, Row]] = defaultdict(dict)
    if slugs and students:
        results = select(Result).where(Result.contest_slug.in_(slugs))
        problems = select(ProblemResult).where(ProblemResult.contest_slug.in_(slugs))
        if student_ids is not None and len(student_ids) <= 50:  # a few students: fetch only theirs
            results = results.where(Result.student_id.in_(student_ids))
            problems = problems.where(ProblemResult.student_id.in_(student_ids))
        for r in session.scalars(results):
            if r.student_id in students:
                rows[r.student_id][r.contest_slug] = Row(
                    r.status, r.global_rank, r.college_rank, r.solved_count, r.total_time_secs, score=r.score)
        for p in session.scalars(problems):
            row = rows.get(p.student_id, {}).get(p.contest_slug)
            if row is not None:
                row.problems[p.q_label] = (p.solve_secs, p.fail_count)

    return Window(contests, students, rows, _labels(contests))


def _matches(p: Person, college: str | None, extra: dict[str, str] | None) -> bool:
    if college and p.college != college:
        return False
    return not (extra and any(p.extra.get(k) != v for k, v in extra.items()))


def raw_from_window(w: Window, sid: int) -> Raw:
    rows = w.rows.get(sid, {})
    scanned = [c for c in w.contests if c.slug in rows]
    attended = [c for c in scanned if rows[c.slug].attended]

    flags = [rows[c.slug].attended for c in scanned]
    current = absent = longest = run = 0
    for f in flags:
        run = run + 1 if f else 0
        longest = max(longest, run)
    for f in reversed(flags):
        if not f:
            break
        current += 1
    for f in reversed(flags):
        if f:
            break
        absent += 1

    solved = [rows[c.slug].solved or 0 for c in attended]
    pcts = [p for c in attended if (p := top_pct(rows[c.slug].global_rank, c.user_num)) is not None]
    ranks = [rows[c.slug].global_rank for c in attended if rows[c.slug].global_rank]
    college_ranks = [rows[c.slug].college_rank for c in attended if rows[c.slug].college_rank]
    k = min(4, len(solved) // 2) if len(solved) >= 4 else None

    questions = {}
    for label in w.labels:
        appeared = [c for c in attended if label in w.labels_of(c)]
        if not appeared:
            continue
        solves = [rows[c.slug].problems[label] for c in appeared if label in rows[c.slug].problems]
        secs = [s for s, _ in solves]
        questions[label] = (len(appeared), len(solves), _median(secs), sum(secs) if secs else None,
                            min(secs) if secs else None, sum(f for _, f in solves))

    return Raw(
        scanned=len(scanned), attended=len(attended),
        sum_solved=sum(solved), sum_solved_sq=sum(x * x for x in solved),
        max_solved=max((r.solved for r in rows.values() if r.solved is not None), default=None),
        avg_top_pct=_mean(pcts),
        best_global_rank=min(ranks) if ranks else None,
        best_college_rank=min(college_ranks) if college_ranks else None,
        points=sum(rows[c.slug].score or 0 for c in attended),
        total_time=sum(rows[c.slug].total_time or 0 for c in attended if rows[c.slug].solved),
        longest_streak=longest, current_streak=current, absent_streak=absent,
        trend_k=k, trend_recent=sum(solved[-k:]) if k else None,
        trend_before=sum(solved[-2 * k:-k]) if k else None,
        questions=questions,
    )


def cohort_from_window(w: Window) -> CohortRaw:
    out = CohortRaw()
    q_secs: dict[str, list[int]] = defaultdict(list)
    q_wrong: dict[str, int] = defaultdict(int)
    college_pcts: dict[str, list[float]] = defaultdict(list)
    for c in w.contests:
        rows = [(sid, w.rows[sid][c.slug]) for sid in w.students if c.slug in w.rows.get(sid, {})]
        part = [(sid, r) for sid, r in rows if r.attended]
        pcts = []
        for sid, r in part:
            if (p := top_pct(r.global_rank, c.user_num)) is not None:
                pcts.append(p)
                st = w.students[sid]
                college_pcts[st.college.name if st.college else ""].append(p)
        if rows:
            out.contests[c.slug] = (len(rows), len(part), sum(r.solved or 0 for _, r in part), _median(pcts),
                                    min((r.global_rank for _, r in part if r.global_rank), default=None))
        for label in w.labels_of(c):
            solves = [r.problems[label] for _, r in part if label in r.problems]
            if part:
                out.q_att[label] = out.q_att.get(label, 0) + len(part)
            if solves:
                secs = [s for s, _ in solves]
                wrong = sum(f for _, f in solves)
                out.contest_q[(c.slug, label)] = (len(solves), _median(secs), wrong)
                q_secs[label] += secs
                q_wrong[label] += wrong
    out.q_sol = {label: (len(secs), _median(secs), _quantile(secs, 0.25), _quantile(secs, 0.75), q_wrong[label])
                 for label, secs in q_secs.items()}
    out.colleges = {name: _median(pcts) for name, pcts in college_pcts.items()}
    return out


def student_metrics(w: Window, sid: int) -> dict:
    return metrics_from_raw(raw_from_window(w, sid), w.labels)


# ---- loading: one entry point, either source --------------------------------------------


@dataclass
class Cohort:
    contests: list[Contest]  # the window, oldest first
    labels: list[str]
    students: dict[int, Person]  # after filters
    candidates: list[Person]  # before the college/sheet-column filters (for filter options)
    raw: dict[int, Raw]
    agg: CohortRaw


def _load(session: Session, *, last: int | None, college: str | None, extra: dict[str, str] | None,
          student_ids: set[int] | None) -> Cohort:
    if not summaries.supported(session):
        w = load_window(session, last=last, student_ids=student_ids)
        candidates = [Person.of(st) for st in w.students.values()]
        students = {p.id: p for p in candidates if _matches(p, college, extra)}
        w.students = {sid: st for sid, st in w.students.items() if sid in students}
        return Cohort(w.contests, w.labels, students, candidates,
                      {sid: raw_from_window(w, sid) for sid in students}, cohort_from_window(w))

    scanned = _scanned_contests(session)
    contests = scanned[-last:] if last else scanned
    win = summaries.window_key(last, len(scanned))

    q = (select(Student.id, Student.name, Student.roll_no, Student.college_id, College.name, Student.extra,
                Student.lc_rating, Student.active)
         .outerjoin(College, College.id == Student.college_id))
    q = q.where(Student.id.in_(student_ids)) if student_ids is not None else q.where(Student.active.is_(True))
    if win is not None:  # stored: one query for students and their numbers
        q = q.add_columns(*[getattr(StudentStats, c) for c in summaries.STUDENT_COLUMNS]).outerjoin(
            StudentStats, (StudentStats.student_id == Student.id) & (StudentStats.win == win))
    candidates, raw = [], {}
    for sid, name, roll_no, college_id, college_name, extra_values, rating, active, *row in session.execute(q):
        candidates.append(Person(sid, name, roll_no, college_id, college_name or "", extra_values or {}, rating, active))
        if row and row[0] is not None:
            raw[sid] = Raw.from_row(row)
    students = {p.id: p for p in candidates if _matches(p, college, extra)}
    filtered = student_ids is not None or bool(college or extra)
    ids = sorted(students) if filtered else None

    if not contests or not students:
        return Cohort(contests, _labels(contests), students, candidates, {}, CohortRaw())
    if win is None:
        live = summaries.student_rows(session, last, ids)
        raw = {row[0]: Raw.from_row(row) for row in live}
    names = {p.college_id: p.college for p in students.values() if p.college_id}
    agg = CohortRaw.from_payload(summaries.cohort_payload(session, win, last, ids), names)
    return Cohort(contests, _labels(contests), students, candidates, raw, agg)


# ---- cohort ----------------------------------------------------------------------


def _student_ref(p: Person) -> dict:
    return {"id": p.id, "name": p.name, "roll_no": p.roll_no, "college": p.college, "extra": p.extra,
            "rating": _round(p.rating, 0)}


def _filter_options(students: list[Person]) -> dict:
    """College and sheet-column values to filter by, from the (unfiltered) candidates."""
    colleges: set[str] = set()
    values: dict[str, set[str]] = defaultdict(set)
    for p in students:
        if not p.active:
            continue
        if p.college:
            colleges.add(p.college)
        for k, v in p.extra.items():
            if v:
                values[k].add(v)
    return {
        "colleges": sorted(colleges),
        "extras": {k: sorted(vs) for k, vs in values.items() if 2 <= len(vs) <= MAX_FILTER_VALUES},
    }


def _medals(students: list[dict], by_college: dict[str, list[int]]) -> tuple[dict, list[dict]]:
    """Toppers (overall and per college) and colleges ranked by students in the top 100."""
    keys = ("id", "name", "roll_no", "college", "points", "portal_rank", "contests_attended",
            "avg_solved", "best_global_rank")
    ranked = sorted((s for s in students if s["portal_rank"]), key=lambda s: s["portal_rank"])
    brief = lambda s: {k: s[k] for k in keys}  # noqa: E731
    by_id = {s["id"]: s for s in students}

    colleges = []
    for name, sids in by_college.items():
        mine = sorted((by_id[s] for s in sids if by_id[s]["portal_rank"]), key=lambda s: s["portal_rank"])
        colleges.append({
            "college": name or "(no college)", "students": len(sids),
            "ranked": len(mine),
            "in_top": sum(1 for s in mine if s["portal_rank"] <= TOP_N),
            "in_top_10": sum(1 for s in mine if s["portal_rank"] <= 10),
            "best_portal_rank": mine[0]["portal_rank"] if mine else None,
            "toppers": [brief(s) for s in mine[:MEDALS]],
        })
    colleges.sort(key=lambda c: (-c["in_top"], -c["in_top_10"], c["best_portal_rank"] or 10**9, c["college"]))
    for i, c in enumerate(colleges, start=1):
        c["rank"] = i if c["in_top"] else None
    toppers = {"overall": [brief(s) for s in ranked[:MEDALS]],
               "colleges": [{"college": c["college"], "students": c["students"], "toppers": c["toppers"]}
                            for c in sorted(colleges, key=lambda c: (c["best_portal_rank"] or 10**9, c["college"]))]}
    top = [{k: v for k, v in c.items() if k != "toppers"} for c in colleges]
    return toppers, top


def student_rows(co: Cohort, questions: bool = True) -> list[dict]:
    """Every student in the cohort with their metrics and portal rank, best first
    (a fixed order, so ties everywhere downstream come out the same every time)."""
    portal = {sid: (i, points) for i, (sid, points, _) in enumerate(standings(co.students, co.raw), start=1)}
    empty = Raw()
    rows = [{**_student_ref(st), **metrics_from_raw(co.raw.get(sid, empty), co.labels, questions),
             "points": portal[sid][1] if sid in portal else 0,
             "portal_rank": portal[sid][0] if sid in portal else None}
            for sid, st in co.students.items()]
    rows.sort(key=lambda s: (s["portal_rank"] or 10**9, s["name"].lower(), s["id"]))
    return rows


# ---- computed once per data version (app.services.vcache) ------------------------------


def _filters_key(last, college, extra, student_ids) -> tuple:
    return (last, college, tuple(sorted((extra or {}).items())),
            frozenset(student_ids) if student_ids is not None else None)


def _cohort(session: Session, *, last, college, extra, student_ids, version: str | None) -> tuple[Cohort, list[dict]]:
    """The cohort and its student rows (without per-question detail), computed once
    per data version and filter."""
    if version is None:
        version = summaries.data_version(session)

    def compute():
        co = _load(session, last=last, college=college, extra=extra, student_ids=student_ids)
        return co, student_rows(co, questions=False)
    return vcache.cached((version, "cohort", *_filters_key(last, college, extra, student_ids)), compute)


def overview(session: Session, *, last: int | None = None, college: str | None = None,
             extra: dict[str, str] | None = None, student_ids: set[int] | None = None,
             include_students: bool = True, version: str | None = None) -> dict:
    """Cohort analytics. `student_ids` limits it to those students (an instructor's).
    `include_students=False` leaves out the per-student list (served page by page).
    `version`: the current data_version, if the caller already read it."""
    if version is None:
        version = summaries.data_version(session)

    def compute():
        co, rows = _cohort(session, last=last, college=college, extra=extra, student_ids=student_ids,
                           version=version)
        return _overview(co, rows, include_students)
    key = (version, "overview", include_students, *_filters_key(last, college, extra, student_ids))
    return dict(vcache.cached(key, compute))  # a copy: callers may add keys


def _overview(co: Cohort, students: list[dict], include_students: bool) -> dict:
    by_id = {s["id"]: s for s in students}
    empty = Raw()

    by_college: dict[str, list[int]] = defaultdict(list)
    for sid, p in co.students.items():
        by_college[p.college].append(sid)
    colleges = []
    for name, sids in sorted(by_college.items()):
        raws = [co.raw.get(s, empty) for s in sids]
        scanned = sum(r.scanned for r in raws)
        attended = sum(r.attended for r in raws)
        ratings = [co.students[s].rating for s in sids if co.students[s].rating]
        scores = [by_id[s]["consistency"] for s in sids if by_id[s]["consistency"] is not None]
        colleges.append({
            "college": name or "(no college)", "students": len(sids),
            "participation_rate": _round(attended / scanned, 3) if scanned else None,
            "avg_solved": _round(sum(r.sum_solved for r in raws) / attended) if attended else None,
            "median_top_pct": _round(co.agg.colleges.get(name)),
            "best_global_rank": min((m for s in sids if (m := by_id[s]["best_global_rank"])), default=None),
            "avg_consistency": _round(_mean(scores), 0),
            "avg_rating": _round(_mean(ratings), 0),
            "solved_any_share": _round(sum(1 for r in raws if r.max_solved) / len(sids), 3),
        })

    brief_keys = ("id", "name", "roll_no", "college", "rating", "contests_scanned", "contests_attended",
                  "attendance_rate", "absent_streak", "avg_solved", "avg_top_pct", "best_global_rank",
                  "consistency", "consistency_label", "trend", "trend_label", "reasons")

    def top(rows: list[dict], key, n: int = 10, reverse: bool = True) -> list[dict]:
        ranked = sorted(rows, key=key, reverse=reverse)[:n]
        return [{k: s[k] for k in brief_keys if k in s} for s in ranked]

    min_attended = min(3, len(co.contests)) or 1
    eligible = [s for s in students if s["contests_attended"] >= min_attended]
    attention = []
    for s in students:
        reasons = attention_reasons(s)
        if reasons:
            attention.append({**s, "reasons": reasons})

    toppers, college_ranking = _medals(students, by_college)
    raws = [co.raw.get(sid, empty) for sid in co.students]
    all_scanned = sum(r.scanned for r in raws)
    all_attended = sum(r.attended for r in raws)
    ratings = [p.rating for p in co.students.values() if p.rating]
    out = {
        "window": {"contests": len(co.contests), "first": co.contests[0].title if co.contests else None,
                   "last": co.contests[-1].title if co.contests else None},
        "labels": co.labels,
        "summary": {
            "students": len(co.students),
            "participation_rate": _round(all_attended / all_scanned, 3) if all_scanned else None,
            "avg_solved": _round(sum(r.sum_solved for r in raws) / all_attended) if all_attended else None,
            "active_participants": sum(1 for r in raws if r.attended),
            "avg_rating": _round(_mean(ratings), 0),
            "rated_students": len(ratings),
            "needs_attention": len(attention),
        },
        "trend": contest_points(co.contests, co.agg),
        "questions": question_summary(co.labels, co.agg),
        "colleges": colleges,
        "leaders": {
            "consistent": top([s for s in students if s["consistency"] is not None],
                              key=lambda s: (s["consistency"], s["avg_solved"] or 0)),
            "top_performers": top(eligible, key=lambda s: s["avg_top_pct"] if s["avg_top_pct"] is not None else 1e9,
                                  reverse=False),
            "improved": top([s for s in students if s["trend_label"] == "improving"], key=lambda s: s["trend"]),
            "attention": top(attention, key=lambda s: (s["absent_streak"], -(s["trend"] or 0)), n=25),
        },
        "toppers": toppers,
        "college_ranking": college_ranking,
        "top_n": TOP_N,
        "filters": _filter_options(co.candidates),
    }
    if include_students:
        out["students"] = [{**s, "questions": question_metrics(co.raw.get(s["id"], empty), co.labels)}
                           for s in students]
    return out


def attention_reasons(s: dict) -> list[str]:
    reasons = []
    if s["absent_streak"] >= ABSENT_STREAK_ALERT:
        reasons.append(f"missed the last {s['absent_streak']} contests")
    if s["trend_label"] == "declining":
        reasons.append(f"solving {abs(s['trend']):.1f} fewer problems than before")
    return reasons


# ---- the "All students" table, a page at a time ----------------------------------------

# sort key -> value for a student row (None sorts last in both directions)
SORTS = {
    "name": lambda s, r: s["name"].lower(),
    "portal_rank": lambda s, r: s["portal_rank"],
    "attendance": lambda s, r: s["attendance_rate"],
    "consistency": lambda s, r: s["consistency"],
    "avg_solved": lambda s, r: s["avg_solved"],
    "wrong": lambda s, r: sum(q[5] for q in r.questions.values()),
    "top_pct": lambda s, r: s["avg_top_pct"],
    "rating": lambda s, r: s["rating"],
    "trend": lambda s, r: s["trend"],
}


def _sort_value(key: str):
    """(student row, Raw) -> the value to sort by."""
    if key in SORTS:
        return SORTS[key]
    if key[:1] == "Q" and key[1:].isdigit():  # a question's solve rate
        def rate(s, r):
            attempted, solved, *_ = r.questions.get(key, NO_QUESTION)
            return _solve_rate(solved, attempted)
        return rate
    raise ValueError(f"can't sort by {key!r}")


def students_page(session: Session, *, last: int | None = None, college: str | None = None,
                  extra: dict[str, str] | None = None, student_ids: set[int] | None = None,
                  search: str = "", sort: str = "portal_rank", desc: bool = False,
                  offset: int = 0, limit: int | None = 50, version: str | None = None) -> dict:
    """Students for the analytics table: searched, sorted and sliced on the server, so
    the browser gets 50 rows instead of the whole cohort. Ties keep portal order.
    `limit=None` returns every match (CSV download)."""
    value = _sort_value(sort)
    co, rows = _cohort(session, last=last, college=college, extra=extra, student_ids=student_ids,
                       version=version)
    q = search.strip().lower()
    if q:
        rows = [s for s in rows if q in s["name"].lower() or q in s["roll_no"].lower()]
    empty = Raw()
    keyed = [(value(s, co.raw.get(s["id"], empty)), s) for s in rows]
    present = [(v, s) for v, s in keyed if v is not None]
    present.sort(key=lambda vs: vs[0], reverse=desc)  # stable: ties stay in portal order
    rows = [s for _, s in present] + [s for v, s in keyed if v is None]
    page = rows[offset:offset + limit] if limit is not None else rows[offset:]
    page = [{**s, "questions": question_metrics(co.raw.get(s["id"], empty), co.labels)}  # only rows shown
            for s in page]
    return {"labels": co.labels, "total": len(rows), "offset": offset, "rows": page}


# ---- one student --------------------------------------------------------------------


def student_analytics(session: Session, student_id: int, *, last: int | None = None,
                      version: str | None = None) -> dict | None:
    """One student's analytics. With `version` (the current data_version), the parts
    every student page shares (the scanned contests, the cohort's numbers) come from
    the per-version cache: 2 fewer queries per page once warm."""
    if summaries.supported(session):
        loaded = _student_from_summaries(session, student_id, last, version)
    else:
        loaded = _student_from_rows(session, student_id, last)
    if loaded is None:
        return None
    st, contests, labels, raw, agg, rows = loaded
    m = metrics_from_raw(raw, labels)

    cohort_q = {q["label"]: q for q in question_summary(labels, agg)}
    for label, q in m["questions"].items():
        c = cohort_q.get(label, {})
        q["cohort_solve_rate"] = c.get("solve_rate")
        q["cohort_median_secs"] = c.get("median_secs")
        q["cohort_wrong_per_solve"] = c.get("wrong_per_solve")

    series = []
    for c in contests:
        r = rows.get(c.slug)
        if r is None:
            continue
        series.append({
            "slug": c.slug, "title": c.title, "start_time": c.start_time, "status": r.status,
            "solved": r.solved, "questions": len(c.questions), "global_rank": r.global_rank,
            "top_pct": _round(top_pct(r.global_rank, c.user_num)), "college_rank": r.college_rank,
            "total_time_secs": r.total_time,
        })

    history = session.scalars(
        select(RatingHistory).where(RatingHistory.student_id == student_id)
        .order_by(RatingHistory.start_time)
    ).all()
    return {
        **m,
        "labels": labels,
        "series": series,
        "rating": {
            "current": _round(st.lc_rating, 0),
            "global_ranking": st.lc_global_ranking,
            "top_percentage": st.lc_top_percentage,
            "contests_attended": st.lc_contests_attended,
            "synced_at": st.ratings_synced_at.isoformat() if st.ratings_synced_at else None,
            "history": [{"title": h.contest_title, "slug": h.contest_slug, "start_time": h.start_time,
                         "rating": round(h.rating), "ranking": h.ranking,
                         "solved": h.problems_solved, "total": h.total_problems} for h in history],
        },
    }


def _student_from_rows(session: Session, student_id: int, last: int | None):
    cohort = load_window(session, last=last)
    st = cohort.students.get(student_id)
    if st is not None:  # active: their rows are already in the cohort window
        mine = Window(cohort.contests, {student_id: st}, {student_id: cohort.rows.get(student_id, {})}, cohort.labels)
    else:  # removed students aren't in the cohort
        st = session.get(Student, student_id)
        if st is None:
            return None
        mine = load_window(session, last=last, student_ids={student_id})
    return (st, mine.contests, mine.labels, raw_from_window(mine, student_id), cohort_from_window(cohort),
            mine.rows.get(student_id, {}))


def _student_from_summaries(session: Session, student_id: int, last: int | None, version: str | None):
    def shared(key: str, compute):
        return vcache.cached((version, key, last), compute) if version else compute()

    scanned = shared("scanned_contests", lambda: _scanned_contests(session))
    contests = scanned[-last:] if last else scanned
    win = summaries.window_key(last, len(scanned))
    if win is not None:
        q = (select(Student, *[getattr(StudentStats, c) for c in summaries.STUDENT_COLUMNS])
             .outerjoin(StudentStats, (StudentStats.student_id == Student.id) & (StudentStats.win == win))
             .where(Student.id == student_id))
        found = session.execute(q).first()
        if found is None:
            return None
        st, *row = found
        raw = Raw.from_row(row) if row[0] is not None else Raw()
    else:
        st = session.get(Student, student_id)
        if st is None:
            return None
        live = summaries.student_rows(session, last, [student_id])
        raw = Raw.from_row(live[0]) if live else Raw()
    agg = (shared("cohort_payload", lambda: CohortRaw.from_payload(summaries.cohort_payload(session, win, last), {}))
           if contests else CohortRaw())
    slugs = [c.slug for c in contests]
    rows = {r.contest_slug: Row(r.status, r.global_rank, r.college_rank, r.solved_count, r.total_time_secs,
                                score=r.score)
            for r in session.scalars(select(Result).where(Result.student_id == student_id,
                                                          Result.contest_slug.in_(slugs)))} if slugs else {}
    return st, contests, _labels(contests), raw, agg, rows


# ---- one contest: distributions & college breakdown ---------------------------------


def distributions(c: Contest, rows: list, problems: list[ProblemResult],
                  student_ids: set[int] | None = None, bin_minutes: int = 10) -> dict:
    """Solve-time histograms, wrong-attempt counts and the per-college table, from rows
    already loaded by the contest page ((Result, college name) pairs)."""
    n_bins = max(1, math.ceil(c.duration / 60 / bin_minutes))
    labels = [q["label"] for q in c.questions]
    bins = {label: [0] * n_bins for label in labels}
    wrong = {label: {"0": 0, "1": 0, "2": 0, "3+": 0} for label in labels}
    for p in problems:
        if p.q_label not in bins or (student_ids is not None and p.student_id not in student_ids):
            continue
        i = min(n_bins - 1, max(0, p.solve_secs // (bin_minutes * 60)))
        bins[p.q_label][i] += 1
        wrong[p.q_label]["3+" if p.fail_count >= 3 else str(p.fail_count)] += 1

    by_college: dict[str, list[Result]] = defaultdict(list)
    for r, college in rows:
        if student_ids is not None and r.student_id not in student_ids:
            continue
        by_college[college or ""].append(r)
    colleges = []
    for name, rs in sorted(by_college.items()):
        part = [r for r in rs if r.status in PARTICIPATED]
        colleges.append({
            "college": name or "(no college)", "students": len(rs), "participated": len(part),
            "participation_rate": _round(len(part) / len(rs), 3) if rs else None,
            "avg_solved": _round(_mean([r.solved_count or 0 for r in part])),
            "solved_all": sum(1 for r in part if r.solved_count == len(labels)),
            "best_global_rank": min((r.global_rank for r in part if r.global_rank), default=None),
            "best_college_rank": min((r.college_rank for r in part if r.college_rank), default=None),
        })
    return {"bin_minutes": bin_minutes, "time_bins": bins, "wrong_distribution": wrong, "colleges": colleges}


def contest_distributions(session: Session, slug: str, bin_minutes: int = 10,
                          student_ids: set[int] | None = None) -> dict:
    from app.services.dashboard import _load_contest_rows

    c = session.get(Contest, slug)
    if c is None:
        return {}
    rows, problems = _load_contest_rows(session, slug)
    return distributions(c, rows, problems, student_ids, bin_minutes)

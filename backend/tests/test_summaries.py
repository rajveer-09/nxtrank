# Author: Rajveer Sharma
# © NxtWave
# Date: 15 October 2026
"""Summary tables (PostgreSQL) against the Python reference: identical answers on a messy
synthetic history, correct after every kind of change, and within budget at full size.
"""

import math
import random
import time

import pytest
from sqlalchemy import delete, event, insert, select, update

from app.db.migrate import upgrade
from app.db.models import College, Contest, ProblemResult, Result, ScanRun, Student, StudentStats
from app.db.session import make_engine, make_session_factory
from app.services import analytics, summaries, vcache
from tests.dbutil import fresh_url, needs_postgres

pytestmark = needs_postgres

WEEK = 7 * 86400
T0 = 1_700_000_000
STATUSES = ["solved"] * 6 + ["zero"] * 2 + ["absent"] * 4 + ["invalid_handle", "no_handle", "duplicate_handle"]


def seed(factory, n_students: int, n_contests: int, seed: int = 7) -> None:
    """Random but reproducible history, with the awkward cases on purpose."""
    rng = random.Random(seed)
    with factory() as s:
        colleges = [College(name=f"College {c}") for c in "ABCDE"]
        s.add_all(colleges)
        s.flush()
        rows = []
        for i in range(n_students):
            rows.append({
                "roll_no": f"S{i:05d}", "name": f"Student {i % (n_students // 3 or 1)}",  # repeated names: tie-breaks
                "college_id": None if i % 17 == 0 else colleges[i % len(colleges)].id,
                "extra": {"Batch": str(2025 + i % 3)}, "lc_handle_raw": f"h{i}", "lc_slug": f"h{i}",
                "handle_status": "valid", "active": i % 23 != 5,  # some removed students (with results)
                "lc_rating": None if i % 4 == 0 else 1400 + rng.random() * 800,
            })
        s.execute(insert(Student), rows)
        ids = list(s.scalars(select(Student.id).order_by(Student.id)))

        for k in range(n_contests):
            slug = f"weekly-contest-{300 + k}"
            n_q = 3 if k % 9 == 4 else 4  # some contests had three questions
            s.add(Contest(slug=slug, title=f"Weekly Contest {300 + k}", contest_type="weekly",
                          start_time=T0 + k * WEEK, duration=5400,
                          user_num=None if k == 2 else rng.randint(20_000, 40_000),
                          questions=[{"label": f"Q{n + 1}", "question_id": k * 10 + n, "credit": 4,
                                      "title": "t", "title_slug": "t"} for n in range(n_q)]))
            run = ScanRun(contest_slug=slug, kind="final", status="complete")
            s.add(run)
            s.flush()
            results, problems = [], []
            for j, sid in enumerate(ids):
                joined = j % 11  # later students joined later: fewer scanned contests
                if k < joined or j % 31 == 7:  # ...and a few never have any results
                    continue
                status = rng.choice(STATUSES)
                if j % 29 == 3:
                    status = "absent"  # never attends
                if j % 37 == 1 and k > 1:
                    status = "no_handle"  # only the first two contests
                on_board = status in ("solved", "zero")
                solved = rng.randint(1, n_q) if status == "solved" else 0
                rank = (0 if rng.random() < 0.03 else rng.randint(1, 30_000)) if on_board else None
                results.append({
                    "contest_slug": slug, "student_id": sid, "scan_run_id": run.id, "status": status,
                    "global_rank": rank, "college_rank": rng.randint(1, 50) if on_board else None,
                    "score": solved * 4 if on_board else None,
                    "solved_count": solved if on_board else None,
                    "total_time_secs": rng.randint(300, 5400) if solved else (0 if on_board else None),
                    "rank_source": "scan",
                })
                for n in rng.sample(range(n_q), solved):
                    problems.append({"contest_slug": slug, "student_id": sid, "q_label": f"Q{n + 1}",
                                     "question_id": n, "solve_secs": rng.randint(60, 5400),
                                     "fail_count": rng.choice([0, 0, 0, 1, 2, 3, 5]), "lang": "python3"})
            if results:
                s.execute(insert(Result), results)
            if problems:
                s.execute(insert(ProblemResult), problems)
        s.commit()


@pytest.fixture
def factory(tmp_path):
    url = fresh_url(tmp_path)
    upgrade(url)
    return make_session_factory(make_engine(url))


@pytest.fixture
def data(factory):
    seed(factory, 160, 27)
    return factory


def reference(monkeypatch):
    """Run the next call from the raw rows, in Python."""
    monkeypatch.setattr(analytics.summaries, "supported", lambda session: False)


def same(a, b, path="") -> list[str]:
    """Differences between two JSON-like values (floats within 1e-9)."""
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None or not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9):
            return [f"{path}: {a!r} != {b!r}"]
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return [f"{path}: keys {sorted(a.keys() ^ b.keys())}"]
        return [d for k in a for d in same(a[k], b[k], f"{path}.{k}")]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: {len(a)} items != {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in same(x, y, f"{path}[{i}]")]
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def by_id(overview: dict) -> dict:
    overview["students"] = sorted(overview["students"], key=lambda s: s["id"])
    return overview


VIEWS = [
    {},  # stored windows, whole cohort
    {"college": "College B"},
    {"extra": {"Batch": "2026"}},
    {"college": "College C", "extra": {"Batch": "2025"}},
]


@pytest.mark.parametrize("last", [None, 5, 10, 20, 7, 1, 100])
def test_overview_matches_reference(data, monkeypatch, last):
    instructor = None
    with data() as s:
        instructor = set(list(s.scalars(select(Student.id).order_by(Student.id)))[3:40:2])  # incl. a removed one
    for view in [*VIEWS, {"student_ids": instructor}]:
        with data() as s:
            fast = by_id(analytics.overview(s, last=last, **view))
        with monkeypatch.context() as m:
            reference(m)
            with data() as s:
                slow = by_id(analytics.overview(s, last=last, **view))
        assert slow["students"], view
        diffs = same(fast, slow)
        assert not diffs, (last, view, diffs[:10])


@pytest.mark.parametrize("last", [None, 10, 3])
def test_student_page_matches_reference(data, monkeypatch, last):
    with data() as s:
        ids = list(s.scalars(select(Student.id).order_by(Student.id)))
    for sid in ids[::7] + [ids[5], ids[28], ids[7], ids[3]]:  # incl. removed, never-attending, no results
        with data() as s:
            fast = analytics.student_analytics(s, sid, last=last)
        with monkeypatch.context() as m:
            reference(m)
            with data() as s:
                slow = analytics.student_analytics(s, sid, last=last)
        diffs = same(fast, slow)
        assert not diffs, (sid, last, diffs[:10])


def test_students_page_sorts_and_pages_like_the_full_list(data):
    with data() as s:
        full = analytics.students_page(s, last=10, sort="avg_solved", desc=True, limit=None)
        first = analytics.students_page(s, last=10, sort="avg_solved", desc=True, limit=50)
        second = analytics.students_page(s, last=10, sort="avg_solved", desc=True, offset=50, limit=50)
        found = analytics.students_page(s, last=10, search="s0001", limit=None)
        q2 = analytics.students_page(s, sort="Q2", limit=None)
    assert first["total"] == full["total"] == len(full["rows"])
    assert [r["id"] for r in first["rows"] + second["rows"]] == [r["id"] for r in full["rows"][:100]]
    solved = [r["avg_solved"] for r in full["rows"]]
    present = [v for v in solved if v is not None]
    assert present == sorted(present, reverse=True) and all(v is None for v in solved[len(present):])
    assert found["rows"] and all("S0001" in r["roll_no"] for r in found["rows"])
    rates = [r["questions"]["Q2"]["solve_rate"] for r in q2["rows"] if r["questions"]["Q2"]["solve_rate"] is not None]
    assert rates == sorted(rates)
    with data() as s, pytest.raises(ValueError):
        analytics.students_page(s, sort="password")


# ---- keeping current ------------------------------------------------------------------


def stored(factory) -> tuple[dict, dict, str]:
    with factory() as s:
        st = {(r.win, r.student_id): r.attended for r in s.scalars(select(StudentStats))}
        co = {w: p for w, p in s.execute(select(summaries_table().c.win, summaries_table().c.payload))}
        return st, co, summaries.data_version(s)


def summaries_table():
    from app.db.models import CohortStats
    return CohortStats.__table__


def rebuilt_from_scratch(factory) -> tuple[dict, dict]:
    with factory() as s:
        summaries.rebuild(s)
        st = {(r.win, r.student_id): r.attended for r in s.scalars(select(StudentStats))}
        co = {w: p for w, p in s.execute(select(summaries_table().c.win, summaries_table().c.payload))}
        s.rollback()
    return st, co


def test_summaries_follow_every_kind_of_change(data):
    st0, co0, v0 = stored(data)
    assert len(co0) == len(summaries.WINDOWS) and st0
    assert (st0, co0) == rebuilt_from_scratch(data)  # built on startup

    # a rescan changes some results (ORM objects)
    with data() as s:
        latest = s.scalars(select(Contest).order_by(Contest.start_time.desc())).first()
        for r in s.scalars(select(Result).where(Result.contest_slug == latest.slug).limit(15)):
            r.status, r.solved_count, r.score = "solved", 1, 4
        s.commit()
    st1, co1, v1 = stored(data)
    assert int(v1) > int(v0) and (st1, co1) != (st0, co0)
    assert (st1, co1) == rebuilt_from_scratch(data)

    # bulk statements (as scans use) are noticed too
    with data() as s:
        s.execute(delete(ProblemResult).where(ProblemResult.contest_slug == latest.slug))
        s.execute(update(Result).where(Result.contest_slug == latest.slug).values(status="absent"))
        s.commit()
    st2, co2, v2 = stored(data)
    assert int(v2) > int(v1) and (st2, co2) == rebuilt_from_scratch(data)

    # a student removed, another moved college: only the cohort numbers change
    with data() as s:
        a, b = s.scalars(select(Student).where(Student.active.is_(True)).order_by(Student.id).limit(2))
        a.active = False
        b.college_id = None
        s.commit()
    st3, co3, v3 = stored(data)
    assert int(v3) > int(v2) and st3 == st2 and co3 != co2
    assert (st3, co3) == rebuilt_from_scratch(data)

    # a name change: nothing to recompute, but pages showing it must refresh
    with data() as s:
        s.scalars(select(Student).limit(1)).one().name = "Renamed"
        s.commit()
    st4, co4, v4 = stored(data)
    assert int(v4) > int(v3) and (st4, co4) == (st3, co3)

    # a rolled-back change leaves no trace
    with data() as s:
        s.execute(update(Result).values(status="zero"))
        s.rollback()
        s.add(Contest(slug="x", title="x", contest_type="weekly", start_time=0, duration=1, questions=[]))
        s.flush()
        s.rollback()
    assert stored(data) == (st4, co4, v4)


def test_cancelled_scan_changes_nothing(data):
    """store_scan raises before committing when cancelled: the rollback must also
    leave the summaries and data_version alone."""
    before = stored(data)
    with data() as s:
        s.execute(update(Result).values(global_rank=1))
        s.rollback()
    assert stored(data) == before


# ---- performance at full size ---------------------------------------------------------


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    url = fresh_url(tmp_path_factory.mktemp("full"))
    upgrade(url)
    factory = make_session_factory(make_engine(url))
    seed(factory, 1500, 52, seed=11)
    return factory


def queries(factory):
    seen = []
    engine = factory.kw["bind"]
    listener = lambda *a, **k: seen.append(1)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    return seen, lambda: event.remove(engine, "before_cursor_execute", listener)


def timed(fn, repeat: int = 3) -> float:
    best = float("inf")
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t)
    return best


def test_rebuild_after_a_scan_takes_under_2s(full):
    def rebuild():
        with full() as s:
            summaries.rebuild(s)
            s.commit()
    took = timed(rebuild, repeat=2)
    print(f"\nrebuild, all windows, 1500 x 52: {took * 1000:.0f} ms")
    assert took < 2.0


@pytest.mark.parametrize("last", [10, None])
def test_analytics_at_full_size(full, last):
    with full() as s:
        sid = s.scalars(select(Student.id).where(Student.active.is_(True))).first()
        college = s.scalars(select(College.name)).first()

    def page():
        with full() as s:
            analytics.overview(s, last=last, include_students=False)
            analytics.students_page(s, last=last)

    def student():
        with full() as s:
            analytics.student_analytics(s, sid, last=last)

    def college_view():
        with full() as s:
            analytics.overview(s, last=last, college=college, include_students=False)

    def cold(fn):  # the first request after a data change: computed from the summary tables
        def run():
            vcache.clear()
            fn()
        return run

    # (name, call, cold budget, warm budget) in seconds; the portal call is two requests
    report = {}
    for name, fn, cold_budget, warm_budget in [("portal", page, 0.4, 0.04), ("student", student, 0.2, 0.2),
                                               ("college", college_view, 0.3, 0.02)]:
        seen, stop = queries(full)
        took = timed(cold(fn))
        stop()
        warm = timed(fn)
        report[name] = {"cold ms": round(took * 1000), "warm ms": round(warm * 1000), "queries": len(seen) // 3}
        assert took < cold_budget and warm < warm_budget, (name, last, report)
    print(f"\nlast={last}: (ms, queries per call) {report}")

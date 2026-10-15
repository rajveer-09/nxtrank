# Author: Rajveer Sharma
# © NxtWave
# Date: 15 October 2026
"""Query budgets: each page's API runs a fixed number of queries, however much data
there is. A count that grows with the data is an N+1 bug."""

from contextlib import contextmanager

import pytest
from sqlalchemy import event

from app.db.models import Contest, ProblemResult, Result, ScanRun, Student
from app.services import vcache
from app.services.instructors import save_instructor
from tests.test_admins import _with_super
from tests.dbutil import needs_postgres
from tests.test_api import SLUG, client_for, env  # noqa: F401  (env is a fixture)

# endpoint -> the most queries it may run (including the signed-in user lookup and,
# for responses with an ETag, reading data_version)
BUDGET = {
    "/api/auth/me": 1,
    "/api/contests": 7,
    "/api/scan-status": 4,
    f"/api/contests/{SLUG}": 7,
    f"/api/contests/{SLUG}/results": 5,
    "/api/analytics": 6,  # 5 on PostgreSQL (summary tables); SQLite computes from the rows
    "/api/analytics/students": 6,
    "/api/students": 4,
    "/api/students/{sid}": 5,
    "/api/students/{sid}/analytics": 7,
    "/api/admin/students": 5,
    "/api/admin/instructors": 6,
    "/api/admin/colleges": 4,
    "/api/admin/admins": 2,
    "/api/admin/uploads?kind=students": 3,
    "/api/admin/scan-runs": 2,
}


@contextmanager
def counting(factory):
    engine = factory.kw["bind"]
    seen: list[str] = []

    def on_execute(conn, cursor, statement, *args):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)


def measure(client, factory, sid: int) -> dict[str, int]:
    out = {}
    for path in BUDGET:
        url = path.replace("{sid}", str(sid))
        vcache.clear()  # measure the work, not the cache
        with counting(factory) as seen:
            r = client.get(url)
        assert r.status_code == 200, (url, r.text)
        out[path] = len(seen)
    return out


def grow(factory, boss):
    """Ten times the data: more contests with results, students, colleges, instructors, uploads."""
    with factory() as s:
        template = s.get(Contest, SLUG)
        base_students = s.query(Student).count()
        for i in range(30):  # students
            s.add(Student(roll_no=f"G{i:03d}", name=f"Grown {i}", lc_handle_raw=f"g{i}", lc_slug=f"g{i}",
                          handle_status="valid", active=True))
        s.flush()
        students = s.query(Student).all()
        for w in range(12):  # past contests, each scanned, with results for everyone
            slug = f"weekly-contest-{300 + w}"
            s.add(Contest(slug=slug, title=f"Weekly Contest {300 + w}", contest_type="weekly",
                          start_time=template.start_time - (w + 1) * 7 * 86400, duration=5400,
                          user_num=30000, questions=template.questions))
            s.flush()
            run = ScanRun(contest_slug=slug, kind="final", status="complete", students=len(students))
            s.add(run)
            s.flush()
            for j, st in enumerate(students):
                solved = j % 5
                s.add(Result(contest_slug=slug, student_id=st.id, scan_run_id=run.id,
                             status="solved" if solved else "zero", global_rank=100 + j, score=solved * 4,
                             solved_count=solved, total_time_secs=600 * solved or None, rank_source="scan"))
                for k in range(1, solved):
                    s.add(ProblemResult(contest_slug=slug, student_id=st.id, q_label=f"Q{k}", question_id=k,
                                        solve_secs=300 * k, fail_count=k % 2, lang="python3"))
        s.commit()
        assert s.query(Student).count() > base_students
    boss.post("/api/admin/colleges", json={"names": [f"College {c}" for c in "CDEFG"]})
    with factory() as s:
        for i in range(6):
            save_instructor(s, email=f"t{i}@x.in", name=f"Teacher {i}", password="teach-password-1",
                            colleges=["College A", "College B"], roll_nos=["R1"], actor="test", via="ui")
    for i in range(4):  # uploads with changes
        boss.post("/api/admin/students/import", params={"filename": f"u{i}.csv"},
                  content=f"Roll No,Name,LeetCode\nU{i},Upload {i},up_{i}\n".encode(),
                  headers={"Content-Type": "application/octet-stream"})


def seed_one(factory, boss):
    """One of everything, so endpoints that skip work on empty data run their full path."""
    with factory() as s:
        save_instructor(s, email="first@x.in", name="First Teacher", password="teach-password-1",
                        colleges=["College A"], roll_nos=[], actor="test", via="ui")
    boss.post("/api/admin/students/import", params={"filename": "first.csv"},
              content="Roll No,Name,LeetCode\nF1,First Upload,first_up\n".encode(),
              headers={"Content-Type": "application/octet-stream"})


def test_unchanged_data_costs_two_queries(env):
    """A revalidation that matches: the user lookup and data_version, nothing else."""
    c = client_for(env, "viewer")
    _, factory = env
    for url in ["/api/analytics", "/api/students", f"/api/contests/{SLUG}/results"]:
        tag = c.get(url).headers["etag"]
        with counting(factory) as seen:
            assert c.get(url, headers={"If-None-Match": tag}).status_code == 304
        assert len(seen) == 2, (url, seen)


@pytest.mark.parametrize("path", list(BUDGET))
def test_query_budget_is_met_and_does_not_grow_with_data(env, path):
    _, factory = env
    boss = _with_super(env)
    seed_one(factory, boss)
    # a student with results from the start (not "the first by name": name order depends on
    # the database's collation, and a student without results skips one query)
    sid = next(s["id"] for s in boss.get("/api/students", params={"q": "R1"}).json()["rows"] if s["roll_no"] == "R1")
    small = measure(boss, factory, sid)[path]
    grow(factory, boss)
    large = measure(boss, factory, sid)[path]
    assert large == small, f"{path}: {small} queries with little data, {large} with more (N+1?)"
    assert large <= BUDGET[path], f"{path}: {large} queries, budget {BUDGET[path]}"


@needs_postgres
def test_student_pages_share_the_cohort_parts(env):
    """The scanned contests and the cohort's numbers are the same for every student page
    (until the data changes): after the first page, each one costs 5 queries."""
    _, factory = env
    c = client_for(env, "viewer")
    ids = [s["id"] for s in c.get("/api/students").json()["rows"]]
    c.get(f"/api/students/{ids[0]}/analytics")  # first page of this data version
    with counting(factory) as seen:
        assert c.get(f"/api/students/{ids[1]}/analytics").status_code == 200
    assert len(seen) == 5, seen  # user, version, student + numbers, their results, rating history

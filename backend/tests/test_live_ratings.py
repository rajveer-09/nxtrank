# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Students' LeetCode ratings: refreshed daily by the worker, and live from a student's page."""

import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.api import routes_data
from app.db.models import Student
from tests.test_api import client_for, env  # noqa: F401  (env is a fixture)
from tests.test_worker import END, WorkerClient, factory, make_worker, students  # noqa: F401  (fixtures)


def test_worker_refreshes_ratings_once_a_day(factory, students):
    client = WorkerClient(upcoming=[])
    worker, _, clock = make_worker(factory, client, END + timedelta(days=30))
    asyncio.run(worker.tick())
    first = client.rating_calls
    assert first == 3  # every active student with a handle
    with factory() as s:
        assert {st.lc_rating for st in s.scalars(select(Student))} == {1600.0}

    clock["now"] += timedelta(hours=23)
    asyncio.run(worker.tick())
    assert client.rating_calls == first  # not again within a day

    clock["now"] += timedelta(hours=2)
    asyncio.run(worker.tick())
    assert client.rating_calls == 2 * first


class FakeLive:
    calls = 0

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def contest_ranking(self, handle):
        FakeLive.calls += 1
        return {"rating": 1712.4, "globalRanking": 9000, "topPercentage": 4.2, "attendedContestsCount": 12}, []


def test_student_page_fetches_the_rating_live(env, monkeypatch):
    monkeypatch.setattr(routes_data, "LeetCodeClient", FakeLive)
    c = client_for(env, "viewer")
    sid = next(s["id"] for s in c.get("/api/students").json()["rows"] if s["roll_no"] == "R1")
    r = c.post(f"/api/students/{sid}/rating/refresh").json()
    assert (r["rating"], r["top_percentage"], r["contests_attended"], r["fetched_now"]) == (1712, 4.2, 12, True)
    listed = next(s for s in c.get("/api/students").json()["rows"] if s["id"] == sid)
    assert (listed["rating"], listed["rated_contests"]) == (1712, 12) and listed["rating_synced_at"]

    again = c.post(f"/api/students/{sid}/rating/refresh").json()  # within 10 minutes: not asked again
    assert again["fetched_now"] is False and FakeLive.calls == 1

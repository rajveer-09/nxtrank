# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Contest page scoped to a college / an instructor's students, and the "latest" badge."""

from app.db.models import Contest
from app.services.dashboard import latest_contests
from tests.test_api import SLUG, client_for, env  # noqa: F401  (env is a fixture)

DAY = 86400


def contest(slug, kind, start):
    return Contest(slug=slug, title=slug, contest_type=kind, start_time=start, duration=5400, questions=[])


def test_latest_marks_both_contests_of_the_same_weekend():
    sunday, saturday = 10 * DAY, 10 * DAY - 13 * 3600
    weekly = contest("weekly-contest-2", "weekly", sunday)
    biweekly = contest("biweekly-contest-1", "biweekly", saturday)
    older = contest("weekly-contest-1", "weekly", sunday - 7 * DAY)
    assert latest_contests([weekly, biweekly, older]) == ["weekly-contest-2", "biweekly-contest-1"]
    # an off week: the last biweekly was the weekend before
    old_biweekly = contest("biweekly-contest-1", "biweekly", saturday - 7 * DAY)
    assert latest_contests([weekly, older, old_biweekly]) == ["weekly-contest-2"]
    assert latest_contests([]) == []


def test_contest_page_scoped_to_a_college(env):
    c = client_for(env, "viewer")
    everyone = c.get(f"/api/contests/{SLUG}").json()
    assert everyone["colleges"] == ["College A", "College B"]
    a = c.get(f"/api/contests/{SLUG}", params={"college": "College A"}).json()
    assert a["summary"]["students"] == 2 < everyone["summary"]["students"]
    assert [x["college"] for x in a["distributions"]["colleges"]] == ["College A"]
    assert sum(q["solved"] for q in a["questions"]) <= sum(q["solved"] for q in everyone["questions"])
    rows = c.get(f"/api/contests/{SLUG}/results", params={"college": "College A"}).json()["rows"]
    assert {r["college"] for r in rows} == {"College A"} and len(rows) == 2


def test_contest_page_for_an_instructors_students(env):
    admin = client_for(env, "admin")
    admin.post("/api/admin/instructors", json={"email": "t@x.in", "name": "T", "password": "teach-password-1",
                                               "colleges": [], "roll_nos": ["R3"]})
    t = client_for(env)
    t.post("/api/auth/login", json={"username": "t@x.in", "password": "teach-password-1"})
    rows = t.get(f"/api/contests/{SLUG}/results", params={"mine": "true"}).json()["rows"]
    assert [r["roll_no"] for r in rows] == ["R3"]
    assert t.get(f"/api/contests/{SLUG}", params={"mine": "true"}).json()["summary"]["students"] == 1
    assert admin.get(f"/api/contests/{SLUG}", params={"mine": "true"}).status_code == 400

# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""Admins: an instructor's students on contest pages, and viewing the dashboard as an
instructor (read-only, an hour at most, audited)."""

import time

from app.db.models import User
from app.services import view_as
from tests.test_api import SLUG, client_for, env  # noqa: F401  (env is a fixture)
from tests.test_instructors import PASSWORD, _create, _login


def _instructor(admin, **kw):
    r = _create(admin, **kw)
    assert r.status_code == 201, r.text
    return r.json()


def test_contest_pages_limited_to_one_instructors_students(env):
    admin = client_for(env, "admin")
    ins = _instructor(admin, colleges=[], roll_nos=["R1", "R3"])
    rows = admin.get(f"/api/contests/{SLUG}/results", params={"instructor_id": ins["id"]}).json()["rows"]
    assert {r["roll_no"] for r in rows} == {"R1", "R3"}
    detail = admin.get(f"/api/contests/{SLUG}", params={"instructor_id": ins["id"]}).json()
    assert detail["summary"]["students"] == 2
    assert admin.get(f"/api/contests/{SLUG}", params={"instructor_id": 999}).status_code == 404

    c, _ = _login(env)
    assert c.get(f"/api/contests/{SLUG}", params={"instructor_id": ins["id"]}).status_code == 403
    assert client_for(env, "viewer").get(f"/api/contests/{SLUG}/results",
                                         params={"instructor_id": ins["id"]}).status_code == 403


def test_view_as_an_instructor_and_return(env):
    admin = client_for(env, "admin")
    ins = _instructor(admin, colleges=[], roll_nos=["R1"])

    r = admin.post(f"/api/admin/instructors/{ins['id']}/view-as")
    assert r.status_code == 200 and r.json()["role"] == "instructor"
    me = admin.get("/api/auth/me").json()
    assert me["username"] == "asha@nxtwave.co.in" and me["viewing_as"]["admin_username"] == "admin"

    # sees what the instructor sees: their students, no admin pages
    mine = admin.get("/api/instructor/analytics/students").json()
    assert {s["roll_no"] for s in mine["rows"]} == {"R1"}
    assert admin.get("/api/admin/instructors").status_code == 403

    # read-only
    r = admin.post(f"/api/contests/{SLUG}/scan")
    assert r.status_code == 403 and r.json()["code"] == "viewing_as" and "Asha Rao" in r.json()["detail"]

    r = admin.post("/api/auth/return")
    assert r.status_code == 200 and r.json()["role"] == "admin" and r.json()["viewing_as"] is None
    assert admin.get("/api/admin/instructors").status_code == 200
    events = admin.get("/api/admin/audit-events").json()
    assert [(e["action"], e["actor"], e["target"]) for e in events] == [
        ("view_as.end", "admin", "asha@nxtwave.co.in"), ("view_as.start", "admin", "asha@nxtwave.co.in")]

    # the instructor's own login still works
    _, login = _login(env, password=PASSWORD)
    assert login.status_code == 200


def test_view_as_ends_after_an_hour(env, monkeypatch):
    admin = client_for(env, "admin")
    ins = _instructor(admin)
    admin.post(f"/api/admin/instructors/{ins['id']}/view-as")
    later = time.time() + view_as.VIEW_AS_SECS + 1
    monkeypatch.setattr("app.api.deps.time.time", lambda: later)
    me = admin.get("/api/auth/me").json()
    assert me["role"] == "admin" and me["viewing_as"] is None
    assert admin.get("/api/admin/audit-events").json()[0]["detail"] == "expired after 60 minutes"


def test_only_admins_view_as_and_only_instructors(env):
    admin = client_for(env, "admin")
    ins = _instructor(admin)
    with env[1]() as s:
        admin_id = s.query(User).filter_by(username="admin").one().id
    assert admin.post(f"/api/admin/instructors/{admin_id}/view-as").status_code == 404  # not an instructor
    c, _ = _login(env)
    assert c.post(f"/api/admin/instructors/{ins['id']}/view-as").status_code == 403
    assert client_for(env, "viewer").post(f"/api/admin/instructors/{ins['id']}/view-as").status_code == 403
    assert admin.post("/api/auth/return").status_code == 400  # not viewing as anyone

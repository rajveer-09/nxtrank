# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Instructors (admin-managed logins that follow some students) and portal toppers."""

from tests.test_api import client_for, env  # noqa: F401  (env is a fixture)

PASSWORD = "teach-password-1"


def _create(admin, **kw):
    body = {"email": "Asha@NxtWave.co.in", "name": "Asha Rao", "password": PASSWORD,
            "colleges": ["College A"], "roll_nos": [], **kw}
    return admin.post("/api/admin/instructors", json=body)


def _login(env, email="asha@nxtwave.co.in", password=PASSWORD):
    c = client_for(env)
    return c, c.post("/api/auth/login", json={"username": email, "password": password})


def test_admin_adds_edits_deactivates_and_deletes_an_instructor(env):
    admin = client_for(env, "admin")
    r = _create(admin)
    assert r.status_code == 201, r.text
    ins = r.json()
    assert ins["email"] == "asha@nxtwave.co.in" and ins["colleges"] == ["College A"] and ins["students"] == 2

    listing = admin.get("/api/admin/instructors").json()
    assert [i["name"] for i in listing["instructors"]] == ["Asha Rao"]
    assert listing["colleges"] == ["College A", "College B"]

    # follow College B's R3 as well; keep the password
    r = admin.put(f"/api/admin/instructors/{ins['id']}", json={
        "email": ins["email"], "name": "Asha R.", "password": "", "colleges": ["College A"], "roll_nos": ["r3"]})
    assert r.status_code == 200 and r.json()["roll_nos"] == ["R3"] and r.json()["students"] == 3

    c, login = _login(env)
    assert login.json() == {"username": "asha@nxtwave.co.in", "role": "instructor", "name": "Asha R.", "is_super": False, "scans_enabled": True, "viewing_as": None}
    mine = c.get("/api/instructor/analytics/students").json()
    assert {s["roll_no"] for s in mine["rows"]} == {"R1", "R2", "R3"} and mine["total"] == 3
    assert c.get("/api/instructor/analytics").json()["instructor"]["name"] == "Asha R."
    assert c.get("/api/admin/instructors").status_code == 403  # instructors can't manage instructors

    # deactivating removes access; deleting removes the login
    admin.put(f"/api/admin/instructors/{ins['id']}", json={**r.json(), "active": False, "password": ""})
    assert c.get("/api/instructor/analytics").status_code == 401
    assert admin.delete(f"/api/admin/instructors/{ins['id']}").json() == {"deleted": ins["id"]}
    assert admin.get("/api/admin/instructors").json()["instructors"] == []
    assert _login(env)[1].status_code == 401


def test_instructor_validation(env):
    admin = client_for(env, "admin")
    assert _create(admin, colleges=["Nowhere"]).json()["detail"] == "unknown college: Nowhere"
    assert "R99" in _create(admin, roll_nos=["R99"]).json()["detail"]
    assert "password" in _create(admin, password="short").json()["detail"]
    assert _create(admin, email="admin").json()["detail"] == "admin already has a login"
    assert admin.get("/api/admin/instructors").json()["instructors"] == []  # nothing half-saved
    admin_id = 1
    assert admin.delete(f"/api/admin/instructors/{admin_id}").status_code == 404  # only instructors


def test_who_can_see_instructor_analytics(env):
    admin = client_for(env, "admin")
    ins = _create(admin, colleges=["College B"]).json()
    assert client_for(env, "viewer").get("/api/instructor/analytics").status_code == 403
    assert admin.get("/api/instructor/analytics").status_code == 403  # admins must pick one
    data = admin.get("/api/instructor/analytics", params={"instructor_id": ins["id"]}).json()
    assert data["filters"]["colleges"] == ["College B"] and data["summary"]["students"] == 2
    rows = admin.get("/api/instructor/analytics/students", params={"instructor_id": ins["id"]}).json()["rows"]
    assert {s["roll_no"] for s in rows} == {"R3", "R4"}
    assert client_for(env, "viewer").get("/api/instructor/analytics/students").status_code == 403


def test_toppers_and_college_ranking(env):
    c = client_for(env, "viewer")
    data = c.get("/api/analytics").json()
    students = c.get("/api/analytics/students", params={"limit": 5000}).json()["rows"]
    ranked = [s for s in students if s["portal_rank"]]  # served best first
    assert [s["portal_rank"] for s in ranked] == list(range(1, len(ranked) + 1))
    # most points first
    assert all(a["points"] >= b["points"] for a, b in zip(ranked, ranked[1:]))
    assert all(s["points"] == 0 for s in students if not s["portal_rank"])

    overall = data["toppers"]["overall"]
    assert [t["id"] for t in overall] == [s["id"] for s in ranked[:3]]
    by_college = {c["college"]: c for c in data["toppers"]["colleges"]}
    for name, c in by_college.items():
        mine = [s["id"] for s in ranked if s["college"] == name][:3]
        assert [t["id"] for t in c["toppers"]] == mine

    ranking = data["college_ranking"]
    assert data["top_n"] == 100
    assert sum(c["in_top"] for c in ranking) == min(100, len(ranked))
    assert [c["in_top"] for c in ranking] == sorted((c["in_top"] for c in ranking), reverse=True)

# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Upload history: each Excel upload records what it changed, and can be undone."""

from tests.test_admins import _with_super
from tests.test_api import client_for, env  # noqa: F401  (env is a fixture)
from tests.test_roster_admin import upload, xlsx

HEADER = ["Roll No", "Name", "College", "LeetCode", "Batch"]


def _students(c):
    return {s["roll_no"]: s for s in c.get("/api/admin/students", params={"show": "all", "limit": 5000}).json()["students"]}


def test_upload_records_only_what_changed_and_undo_puts_it_back(env):
    boss = _with_super(env)
    before = _students(boss)
    r = upload(boss, "students", xlsx([
        HEADER,
        ["R1", "Top Ranker Renamed", "College A", "karanVk", 2026],  # name changed
        ["R2", "Penalty Case", "College B", "kunaallll", 2026],  # college changed
        ["NW1", "New Student", "Fresh College", "fresh_one", 2027],  # added, with a new college
    ]), "march.xlsx").json()
    assert (r["added"], r["updated"]) == (1, 2) and r["upload_id"]

    history = boss.get("/api/admin/uploads", params={"kind": "students"}).json()
    assert history[0]["filename"] == "march.xlsx" and history[0]["uploaded_by"] == "boss@nxtwave.co.in"
    assert history[0]["status"] == "applied" and history[0]["changes"] == 4  # 3 students + 1 college

    detail = boss.get(f"/api/admin/uploads/{r['upload_id']}").json()
    by = {c["label"].split(" · ")[0]: c for c in detail["changes"] if c["entity"] == "student"}
    assert by["R1"]["before"] == {"name": "Top Ranker"} and by["R1"]["after"] == {"name": "Top Ranker Renamed"}
    assert by["R2"]["before"] == {"college": "College A"} and by["R2"]["after"] == {"college": "College B"}
    assert by["NW1"]["action"] == "added" and by["NW1"]["before"] is None
    assert any(c["entity"] == "college" and c["label"] == "Fresh College" for c in detail["changes"])

    undone = boss.post(f"/api/admin/uploads/{r['upload_id']}/undo").json()
    assert undone["reverted"] == 4 and undone["skipped"] == []
    after = _students(boss)
    assert after["R1"]["name"] == before["R1"]["name"] and after["R2"]["college"] == "College A"
    assert "NW1" not in after  # added by the upload and never scanned -> removed completely
    assert (after["R1"]["updated_via"], after["R1"]["updated_by"]) == ("undo", "boss@nxtwave.co.in")
    assert "Fresh College" not in [c["name"] for c in boss.get("/api/admin/colleges").json()["colleges"]]

    again = boss.post(f"/api/admin/uploads/{r['upload_id']}/undo")
    assert again.status_code == 409 and "already undone" in again.json()["detail"]
    assert boss.get("/api/admin/uploads", params={"kind": "students"}).json()[0]["status"] == "undone"


def test_rows_changed_since_are_left_alone(env):
    admin = client_for(env, "admin")
    r = upload(admin, "students", xlsx([HEADER, ["R1", "Name One", "College A", "karanVk", 2026],
                                        ["R2", "Name Two", "College A", "kunaallll", 2026]])).json()
    # someone fixes R2 on the dashboard after the upload
    r2 = _students(admin)["R2"]
    admin.put(f"/api/admin/students/{r2['id']}", json={**r2, "name": "Name Two (fixed)"})

    undone = admin.post(f"/api/admin/uploads/{r['upload_id']}/undo").json()
    assert undone["reverted"] == 1 and len(undone["skipped"]) == 1
    assert "R2" in undone["skipped"][0] and "changed since by admin" in undone["skipped"][0]
    now = _students(admin)
    assert now["R1"]["name"] == "Top Ranker" and now["R2"]["name"] == "Name Two (fixed)"


def test_instructor_upload_history_and_undo(env):
    admin = client_for(env, "admin")
    first = upload(admin, "instructors", xlsx([
        ["Name", "Email", "Password", "Colleges", "Active"],
        ["Asha", "asha@x.in", "teach-password-1", "College A", "Yes"],
    ])).json()
    assert first["added"] == 1
    second = upload(admin, "instructors", xlsx([
        ["Name", "Email", "Password", "Colleges", "Active"],
        ["Asha Rao", "asha@x.in", "new-password-12", "College A, College B", "Yes"],
    ])).json()
    assert second["updated"] == 1
    change = admin.get(f"/api/admin/uploads/{second['upload_id']}").json()["changes"][0]
    assert change["before"] == {"name": "Asha", "colleges": ["College A"]}
    assert change["after"]["password"] == "changed" and "new-password" not in str(change)

    same = upload(admin, "instructors", xlsx([["Name", "Email", "Colleges"], ["Asha Rao", "asha@x.in", "College A, College B"]])).json()
    assert same["unchanged"] == 1  # nothing changed: not stamped, nothing to undo

    admin.post(f"/api/admin/uploads/{second['upload_id']}/undo")
    asha = next(i for i in admin.get("/api/admin/instructors").json()["instructors"] if i["email"] == "asha@x.in")
    assert (asha["name"], asha["colleges"], asha["updated_via"]) == ("Asha", ["College A"], "undo")

    admin.post(f"/api/admin/uploads/{first['upload_id']}/undo")  # added -> deactivated
    asha = next(i for i in admin.get("/api/admin/instructors").json()["instructors"] if i["email"] == "asha@x.in")
    assert asha["active"] is False


def test_only_admins_see_or_undo_uploads(env):
    viewer = client_for(env, "viewer")
    assert viewer.get("/api/admin/uploads", params={"kind": "students"}).status_code == 403
    assert viewer.post("/api/admin/uploads/1/undo").status_code == 403
    assert client_for(env, "admin").post("/api/admin/uploads/999/undo").status_code == 404


def test_added_student_with_results_is_only_removed(env):
    from app.db.models import Result, ScanRun

    admin = client_for(env, "admin")
    r = upload(admin, "students", xlsx([HEADER, ["NW9", "Later Scanned", "College A", "later_one", 2026]])).json()
    sid = _students(admin)["NW9"]["id"]
    _, factory = env
    with factory() as s:  # a scan ran after the upload and found this student
        run = s.query(ScanRun).first()
        s.add(Result(contest_slug=run.contest_slug, student_id=sid, scan_run_id=run.id, status="absent"))
        s.commit()
    admin.post(f"/api/admin/uploads/{r['upload_id']}/undo")
    nw9 = _students(admin)["NW9"]
    assert nw9["active"] is False  # kept (removed), so its result history survives

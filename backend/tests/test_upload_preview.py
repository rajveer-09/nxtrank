# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Uploads are reviewed first: preview lists every record and saves nothing; Save writes."""

from tests.test_admins import _with_super
from tests.test_api import client_for, env  # noqa: F401  (env is a fixture)
from tests.test_roster_admin import xlsx


def send(c, what, data, name="list.xlsx", preview=False):
    return c.post(f"/api/admin/{what}/import", params={"filename": name, "preview": str(preview).lower()}, content=data,
                  headers={"Content-Type": "application/octet-stream"})


def roster(c):
    return {s["roll_no"]: s for s in c.get("/api/admin/students", params={"show": "all", "limit": 5000}).json()["students"]}


def test_student_preview_lists_every_record_and_saves_nothing(env):
    boss = _with_super(env)
    before = roster(boss)
    data = xlsx([
        ["Roll No", "Name", "College", "LeetCode", "Batch"],
        ["R1", "Top Ranker", "College A", "karanVk", 2026],  # unchanged
        ["R2", "Penalty Case", "College B", "kunaallll", 2026],  # college changes
        ["NW1", "New One", "Fresh College", "new_one", 2027],  # new student + new college
        ["NW2", "", "College A", "x", 2027],  # no name -> skipped
    ])
    p = send(boss, "students", data, "oct.xlsx", preview=True).json()
    assert (p["rows"], p["added"], p["updated"], p["unchanged"], p["skipped"]) == (4, 1, 1, 1, 1)
    assert "upload_id" not in p and p["new_colleges"] == ["Fresh College"]
    recs = {r["key"]: r for r in p["records"]}
    assert [r["row"] for r in p["records"]] == [2, 3, 4, 5]  # file order
    assert recs["R1"]["action"] == "unchanged"
    assert recs["R2"]["action"] == "updated" and recs["R2"]["before"] == {"college": "College A"} and recs["R2"]["after"] == {"college": "College B"}
    assert recs["NW1"]["action"] == "added" and recs["NW1"]["after"]["college"] == "Fresh College"
    assert recs["NW2"]["action"] == "skipped" and "name is required" in recs["NW2"]["reason"]

    # nothing saved: same roster, no new college, no history entry
    assert roster(boss) == before
    assert "Fresh College" not in [c["name"] for c in boss.get("/api/admin/colleges").json()["colleges"]]
    assert boss.get("/api/admin/uploads", params={"kind": "students"}).json() == []

    # Save: the same file, for real
    saved = send(boss, "students", data, "oct.xlsx").json()
    assert (saved["added"], saved["updated"]) == (1, 1) and saved["upload_id"]
    assert roster(boss)["R2"]["college"] == "College B" and "NW1" in roster(boss)


def test_instructor_preview_saves_nothing(env):
    admin = client_for(env, "admin")
    data = xlsx([["Name", "Email", "Password", "Colleges"],
                 ["Asha", "asha@x.in", "teach-password-1", "College A"],
                 ["Nope", "nope@x.in", "", "College A"]])  # new without a password
    p = send(admin, "instructors", data, preview=True).json()
    assert (p["added"], p["skipped"]) == (1, 1)
    asha = next(r for r in p["records"] if r["key"] == "asha@x.in")
    assert asha["action"] == "added" and asha["after"]["colleges"] == ["College A"] and "password" not in asha["after"]
    assert admin.get("/api/admin/instructors").json()["instructors"] == []
    assert send(admin, "instructors", data).json()["added"] == 1

# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""The college list: only the super admin changes it; everyone else picks from it."""

from tests.test_admins import _with_super
from tests.test_api import client_for, env  # noqa: F401  (env is a fixture)


def test_super_admin_adds_renames_and_deletes_colleges(env):
    boss = _with_super(env)
    r = boss.post("/api/admin/colleges", json={"names": ["  Delta  Institute ", "college a", "Delta Institute", "", "Epsilon"]})
    assert r.status_code == 201
    assert r.json() == {"added": ["Delta Institute", "Epsilon"], "existing": ["College A"]}

    listing = boss.get("/api/admin/colleges").json()
    assert listing["can_edit"] is True
    by = {c["name"]: c for c in listing["colleges"]}
    assert by["College A"]["students"] == 2 and by["Delta Institute"]["students"] == 0
    assert (by["Delta Institute"]["created_via"], by["Delta Institute"]["created_by"]) == ("ui", "boss@nxtwave.co.in")

    eps = by["Epsilon"]["id"]
    assert "already on the list" in boss.put(f"/api/admin/colleges/{eps}", json={"name": "delta institute"}).json()["detail"]
    renamed = boss.put(f"/api/admin/colleges/{eps}", json={"name": "Epsilon University"}).json()
    assert renamed["name"] == "Epsilon University" and renamed["updated_by"] == "boss@nxtwave.co.in"

    assert boss.delete(f"/api/admin/colleges/{eps}").json() == {"deleted": eps}
    busy = by["College A"]["id"]
    assert "2 students belong" in boss.delete(f"/api/admin/colleges/{busy}").json()["detail"]


def test_other_admins_only_pick_from_the_list(env):
    admin = client_for(env, "admin")
    listing = admin.get("/api/admin/colleges").json()
    assert listing["can_edit"] is False and [c["name"] for c in listing["colleges"]] == ["College A", "College B"]
    assert admin.post("/api/admin/colleges", json={"names": ["X"]}).status_code == 403
    cid = listing["colleges"][0]["id"]
    assert admin.put(f"/api/admin/colleges/{cid}", json={"name": "Y"}).status_code == 403
    assert admin.delete(f"/api/admin/colleges/{cid}").status_code == 403

    # adding a student with a college that isn't on the list is refused...
    r = admin.post("/api/admin/students", json={"roll_no": "Z1", "name": "Zed", "college": "Collge A"})
    assert r.status_code == 422 and "Admin → Colleges" in r.json()["detail"]
    # ...an existing one (any case) is fine
    assert admin.post("/api/admin/students", json={"roll_no": "Z1", "name": "Zed", "college": "college b"}).json()["college"] == "College B"


def test_adding_colleges_can_be_reviewed_first(env):
    boss = _with_super(env)
    p = boss.post("/api/admin/colleges", params={"preview": "true"}, json={"names": ["Zeta College", "college a"]}).json()
    assert p == {"added": ["Zeta College"], "existing": ["College A"], "preview": True}
    assert "Zeta College" not in [c["name"] for c in boss.get("/api/admin/colleges").json()["colleges"]]  # not saved
    assert boss.post("/api/admin/colleges", json={"names": ["Zeta College"]}).json()["added"] == ["Zeta College"]

# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Admins manage each other on the dashboard; the super admin can't be changed by anyone."""

from app.services.users import set_user
from tests.test_api import client_for, env  # noqa: F401  (env is a fixture)

BOSS = "boss@nxtwave.co.in"


def _login(env, username, password):
    c = client_for(env)
    assert c.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200
    return c


def _with_super(env):
    _, factory = env
    with factory() as s:
        set_user(s, BOSS, "boss-password-1", "admin", is_super=True)
    return _login(env, BOSS, "boss-password-1")


def test_super_admin_cannot_be_changed_by_anyone(env):
    boss = _with_super(env)
    assert boss.get("/api/auth/me").json()["is_super"] is True
    admin = client_for(env, "admin")
    sup = next(a for a in admin.get("/api/admin/admins").json() if a["is_super"])
    assert sup["email"] == BOSS and sup["editable"] is False and sup["created_via"] == "cli"

    body = {"email": BOSS, "name": "Hacked", "password": "", "active": False}
    assert admin.put(f"/api/admin/admins/{sup['id']}", json=body).status_code == 403
    assert admin.delete(f"/api/admin/admins/{sup['id']}").status_code == 403
    assert boss.put(f"/api/admin/admins/{sup['id']}", json=body).status_code == 403  # not even themselves
    still = next(a for a in admin.get("/api/admin/admins").json() if a["is_super"])
    assert still["name"] == sup["name"] and still["active"] is True


def test_admins_add_and_edit_each_other_with_audit(env):
    boss = _with_super(env)
    r = boss.post("/api/admin/admins", json={"email": "Ops@x.in", "name": "Ops", "password": "ops-password-1"})
    assert r.status_code == 201
    ops = r.json()
    assert (ops["email"], ops["created_by"], ops["created_via"], ops["editable"]) == ("ops@x.in", BOSS, "ui", True)

    # another (non-super) admin edits Ops: recorded as them, via the UI
    admin = client_for(env, "admin")
    r = admin.put(f"/api/admin/admins/{ops['id']}", json={"email": "ops@x.in", "name": "Ops Team", "password": "", "active": True})
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["updated_by"], r.json()["updated_via"]) == ("Ops Team", "admin", "ui")
    assert r.json()["created_by"] == BOSS  # creation stays recorded

    # Ops can log in, and edit the other admin back
    ops_client = _login(env, "ops@x.in", "ops-password-1")
    me_id = next(a["id"] for a in admin.get("/api/admin/admins").json() if a["is_you"])
    assert ops_client.put(f"/api/admin/admins/{me_id}", json={"email": "admin", "name": "Admin", "password": "", "active": True}).status_code == 200

    # deactivate signs Ops out; delete removes the login
    admin.put(f"/api/admin/admins/{ops['id']}", json={"email": "ops@x.in", "name": "Ops Team", "active": False})
    assert ops_client.get("/api/admin/admins").status_code == 401
    assert admin.delete(f"/api/admin/admins/{ops['id']}").json() == {"deleted": ops["id"]}


def test_admin_rules(env):
    admin = client_for(env, "admin")
    me = next(a for a in admin.get("/api/admin/admins").json() if a["is_you"])
    assert "own login" in admin.put(f"/api/admin/admins/{me['id']}",
                                    json={"email": "admin", "name": "A", "active": False}).json()["detail"]
    assert "own login" in admin.delete(f"/api/admin/admins/{me['id']}").json()["detail"]
    assert "already has a login" in admin.post("/api/admin/admins", json={"email": "viewer", "name": "V", "password": "x" * 12}).json()["detail"]
    assert "password" in admin.post("/api/admin/admins", json={"email": "n@x.in", "name": "N"}).json()["detail"]
    assert client_for(env, "viewer").get("/api/admin/admins").status_code == 403
    viewer_id = 2
    assert admin.delete(f"/api/admin/admins/{viewer_id}").status_code == 404  # only admins here

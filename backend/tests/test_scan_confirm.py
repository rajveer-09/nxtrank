# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""The scan confirmation pop-up's preview, and instructors being read-only."""

from tests.test_api import SLUG, client_for, env  # noqa: F401  (env is a fixture)
from tests.test_instructors import _create, _login


def test_preview_describes_the_scan(env):
    admin = client_for(env, "admin")
    p = admin.get(f"/api/contests/{SLUG}/scan/preview").json()
    assert p["has_data"] is True and p["kind"] in ("provisional", "final") and p["final_scan_at"]
    assert p["students"] == 4 and p["ahead"] == 0 and p["ready_at"] and p["already"] is None and p["can_request"] is True

    admin.post(f"/api/contests/{SLUG}/scan")
    assert admin.get(f"/api/contests/{SLUG}/scan/preview").json()["already"] == "queued"

    unknown = admin.get("/api/contests/weekly-contest-999/scan/preview").json()
    assert unknown["kind"] is None and unknown["title"] is None and unknown["has_data"] is False
    assert admin.get("/api/contests/not-a-contest/scan/preview").status_code == 422

    viewer = client_for(env, "viewer")  # viewers may fetch a contest without results, not rescan
    assert viewer.get(f"/api/contests/{SLUG}/scan/preview").json()["can_request"] is False


def test_instructors_cannot_scan_rescan_or_cancel(env):
    admin = client_for(env, "admin")
    _create(admin)
    teacher, _ = _login(env)
    assert teacher.get(f"/api/contests/{SLUG}/scan/preview").status_code == 403
    assert teacher.post("/api/contests/weekly-contest-511/scan").status_code == 403  # no results yet: still no
    assert teacher.post(f"/api/contests/{SLUG}/scan").status_code == 403
    admin.post("/api/contests/weekly-contest-511/scan")
    assert teacher.post("/api/contests/weekly-contest-511/scan/cancel").status_code == 403
    assert teacher.get(f"/api/contests/{SLUG}/results").status_code == 200  # reading is fine

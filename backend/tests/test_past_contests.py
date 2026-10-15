# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Past-contest list, scan status (progress / queue / ETA) and on-demand scans."""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models import Contest, Result, ScanRequest, ScanRun, Student
from app.leetcode.schemas import Contest as ContestSchema
from app.services.discovery import sync_past_contests
from app.services.roster import parse_roster
from app.services.roster_sync import sync_roster
from app.services.scan_status import HEARTBEAT_KEY, contest_states, queue_status, set_state
from app.services.scans import scan_and_store
from tests.conftest import FakeClient
from tests.test_api import ROSTER, SLUG, client_for, env  # noqa: F401  (env is a fixture)
from tests.test_worker import WorkerClient, add_contest, factory  # noqa: F401  (factory is a fixture)

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
DELAY = timedelta(minutes=30)
WEEK = 7 * 86400


def schema(n, start):
    return ContestSchema(id=0, title=f"Weekly Contest {n}", title_slug=f"weekly-contest-{n}",
                         start_time=start, duration=5400)


def test_sync_past_contests_incremental(factory):
    base = int(NOW.timestamp()) - 30 * WEEK
    past = [schema(n, base + (n - 500) * WEEK) for n in range(525, 500, -1)]  # 25 contests, 3 pages
    client = WorkerClient(past=past)
    with factory() as s:
        assert len(asyncio.run(sync_past_contests(s, client))) == 25
        assert len(s.scalars(select(Contest)).all()) == 25
        client.past = [schema(526, base + 26 * WEEK)] + past
        assert asyncio.run(sync_past_contests(s, client)) == ["weekly-contest-526"]


def test_queue_status_eta_and_progress(factory):
    with factory() as s:
        for i in range(3):  # typical scan: 8 minutes
            started = NOW - timedelta(hours=5 + i)
            s.add(ScanRun(contest_slug=f"weekly-contest-{400 + i}", status="complete",
                          started_at=started, finished_at=started + timedelta(minutes=8)))
        s.add(ScanRun(contest_slug="weekly-contest-500", status="running",
                      started_at=NOW - timedelta(minutes=4), pages_done=500, pages_total=1000,
                      progress_at=NOW))
        s.add_all([ScanRequest(contest_slug="weekly-contest-500", requested_by="a"),
                   ScanRequest(contest_slug="weekly-contest-501", requested_by="a"),
                   ScanRequest(contest_slug="weekly-contest-502", requested_by="b")])
        set_state(s, HEARTBEAT_KEY, "x", NOW - timedelta(minutes=1))
        q = queue_status(s, NOW)
    assert q["worker"]["alive"] and q["typical_scan_secs"] == 480
    assert q["running"]["slug"] == "weekly-contest-500" and q["running"]["progress"] == 0.5
    assert q["running"]["ready_at"] == (NOW + timedelta(minutes=4)).isoformat()  # half done in 4 min
    assert [(x["slug"], x["position"]) for x in q["queue"]] == [
        ("weekly-contest-501", 1), ("weekly-contest-502", 2)]
    assert q["queue"][1]["ready_at"] == (NOW + timedelta(minutes=4 + 16)).isoformat()


def test_queue_without_worker_has_no_eta(factory):
    with factory() as s:
        s.add(ScanRequest(contest_slug="weekly-contest-501", requested_by="a"))
        set_state(s, HEARTBEAT_KEY, "x", NOW - timedelta(hours=1))
        q = queue_status(s, NOW)
    assert not q["worker"]["alive"] and q["queue"][0]["ready_at"] is None


def test_contest_states(factory):
    recent_start = int((NOW - timedelta(hours=2)).timestamp()) - 5400
    old_start = int((NOW - timedelta(days=40)).timestamp())
    for slug, start in [("weekly-contest-530", int((NOW + timedelta(days=3)).timestamp())),
                        ("weekly-contest-529", int(NOW.timestamp()) - 600),
                        ("weekly-contest-528", recent_start),
                        ("weekly-contest-500", old_start), ("weekly-contest-499", old_start),
                        ("weekly-contest-498", old_start)]:
        add_contest(factory, slug, start)
    with factory() as s:
        set_state(s, HEARTBEAT_KEY, "x", NOW)
        s.add(ScanRun(contest_slug="weekly-contest-499", status="failed", error="HTTP 502",
                      started_at=NOW - timedelta(days=1)))
        s.add(ScanRequest(contest_slug="weekly-contest-498", requested_by="a"))
        s.commit()
        st = contest_states(s, s.scalars(select(Contest)).all(), NOW, DELAY)
    assert st["weekly-contest-530"]["state"] == "upcoming"
    assert st["weekly-contest-529"]["state"] == "live"
    assert st["weekly-contest-528"]["state"] == "scheduled" and st["weekly-contest-528"]["ready_at"]
    assert st["weekly-contest-500"]["state"] == "not_scanned"
    assert st["weekly-contest-499"]["state"] == "failed" and st["weekly-contest-499"]["error"] == "HTTP 502"
    assert st["weekly-contest-498"]["state"] == "queued" and st["weekly-contest-498"]["position"] == 1
    # the due automatic scan runs after the queued request
    assert st["weekly-contest-528"]["ready_at"] > st["weekly-contest-498"]["ready_at"]


def _sync(s, rows):
    students, issues = parse_roster(rows, "sheet")
    sync_roster(s, students, issues, "sheet", force=True)


def test_scan_records_progress(factory):
    with factory() as s:
        _sync(s, ROSTER)
        run = asyncio.run(scan_and_store(s, FakeClient(), SLUG))
        assert (run.pages_done, run.pages_total) == (3, 3) and run.progress_at is not None


def test_rescan_keeps_removed_students_rows(factory):
    with factory() as s:
        _sync(s, ROSTER)
        asyncio.run(scan_and_store(s, FakeClient(), SLUG))
        _sync(s, ROSTER[:4])  # R4 removed from the sheet
        asyncio.run(scan_and_store(s, FakeClient(), SLUG, kind="final"))
        rows = {st.roll_no: r for r, st in s.execute(
            select(Result, Student).join(Student, Student.id == Result.student_id))}
    assert set(rows) == {"R1", "R2", "R3", "R4"}
    assert rows["R4"].status == "absent"  # kept from the first scan


# ---- API --------------------------------------------------------------------------


def _add_past(env):
    _, factory_ = env
    with factory_() as s:
        for k in range(5):
            s.add(Contest(slug=f"weekly-contest-{510 + k}", title=f"Weekly Contest {510 + k}",
                          contest_type="weekly", start_time=1_700_000_000 + k * WEEK, duration=5400,
                          questions=[]))
        s.add(Contest(slug="biweekly-contest-150", title="Biweekly Contest 150",
                      contest_type="biweekly", start_time=1_700_100_000, duration=5400, questions=[]))
        s.commit()


def test_api_contest_list_filters_and_pages(env):
    _add_past(env)
    c = client_for(env, "viewer")
    data = c.get("/api/contests").json()
    assert data["total"] == 7 and data["with_data"] == 1 and "worker" in data and "queue" in data
    assert data["items"][0]["slug"] == SLUG  # newest first
    assert data["latest_slugs"] == [SLUG]  # most recent contest on LeetCode, whatever the filter
    assert c.get("/api/contests", params={"type": "biweekly"}).json()["latest_slugs"] == [SLUG]
    assert c.get("/api/contests", params={"q": "512"}).json()["latest_slugs"] == [SLUG]
    assert c.get("/api/contests", params={"show": "with_data"}).json()["total"] == 1
    assert c.get("/api/contests", params={"show": "without_data"}).json()["total"] == 6
    assert c.get("/api/contests", params={"type": "biweekly"}).json()["total"] == 1
    assert c.get("/api/contests", params={"q": "512"}).json()["items"][0]["slug"] == "weekly-contest-512"
    page2 = c.get("/api/contests", params={"per_page": 5, "page": 2}).json()
    assert len(page2["items"]) == 2 and page2["items"][0]["state"] == "not_scanned"


def test_api_request_scan_permissions(env):
    _add_past(env)
    viewer = client_for(env, "viewer")
    r = viewer.post("/api/contests/weekly-contest-511/scan")
    assert r.status_code == 202 and r.json()["request"]["position"] == 1
    again = viewer.post("/api/contests/weekly-contest-511/scan").json()
    assert again["request"]["position"] == 1  # not queued twice
    assert viewer.post(f"/api/contests/{SLUG}/scan").status_code == 403  # rescans: admins only
    assert viewer.post("/api/contests/not-a-contest/scan").status_code == 422

    admin = client_for(env, "admin")
    assert admin.post(f"/api/contests/{SLUG}/scan").status_code == 202
    queue = admin.get("/api/scan-status").json()["queue"]
    assert [q["slug"] for q in queue] == ["weekly-contest-511", SLUG]

    detail = viewer.get("/api/contests/weekly-contest-511").json()
    assert detail["status"]["state"] == "queued" and detail["summary"]["students"] == 0

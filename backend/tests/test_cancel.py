# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Cancelling queued and running scans."""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.models import Contest, Result, ScanRequest, ScanRun
from app.scan.scanner import ScanCancelledError, scan_contest
from app.services import scans as scans_module
from app.services.roster import parse_roster
from app.services.roster_sync import sync_roster
from app.services.scans import scan_and_store
from tests.conftest import FakeClient
from tests.test_api import ROSTER, SLUG, client_for, env  # noqa: F401  (env is a fixture)
from tests.test_worker import END, WorkerClient, factory, make_worker  # noqa: F401  (factory is a fixture)


def test_scanner_stops_when_asked():
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 1  # let one page through, then cancel

    with pytest.raises(ScanCancelledError):
        asyncio.run(scan_contest(FakeClient(), SLUG, now=2_000_000_000, should_cancel=should_cancel, concurrency=1))


def _sync(s):
    students, issues = parse_roster(ROSTER, "sheet")
    sync_roster(s, students, issues, "sheet")


class CancellingClient(WorkerClient):
    """Sets cancel_requested on the running scan (as the API would) after page 2."""

    def __init__(self, factory, **kw):
        super().__init__(**kw)
        self.factory = factory

    async def ranking_page(self, slug, page):
        if page == 2:
            with self.factory() as other:  # a different session, like the API process
                run = other.scalars(select(ScanRun).where(ScanRun.status == "running")).one()
                run.cancel_requested = True
                other.commit()
        return await super().ranking_page(slug, page)


def test_running_scan_cancelled_from_db_keeps_previous_results(factory, monkeypatch):
    monkeypatch.setattr(scans_module, "PROGRESS_EVERY_SECS", 0)  # poll the flag on every page
    with factory() as s:
        _sync(s)
        asyncio.run(scan_and_store(s, FakeClient(), SLUG))
        before = s.scalar(select(Result).where(Result.contest_slug == SLUG).limit(1))
        assert before is not None
        with pytest.raises(ScanCancelledError):
            asyncio.run(scan_and_store(s, CancellingClient(factory), SLUG, kind="final", concurrency=1))
        runs = s.scalars(select(ScanRun).order_by(ScanRun.id)).all()
        assert [r.status for r in runs] == ["complete", "cancelled"]
        assert len(s.scalars(select(Result).where(Result.contest_slug == SLUG)).all()) == 4  # untouched


def test_worker_closes_cancelled_request_without_failure_alert(factory, monkeypatch):
    monkeypatch.setattr(scans_module, "PROGRESS_EVERY_SECS", 0)
    with factory() as s:
        s.add(ScanRequest(contest_slug=SLUG, kind="final", requested_by="admin"))
        s.commit()
    worker, alerts, _ = make_worker(factory, CancellingClient(factory, upcoming=[]), END + timedelta(days=1))
    asyncio.run(worker.tick())
    with factory() as s:
        req = s.scalars(select(ScanRequest)).one()
        run = s.scalars(select(ScanRun)).one()
    assert req.handled_at is not None and req.error == "cancelled from the dashboard"
    assert run.status == "cancelled"
    assert not any("failed" in m for m in alerts.messages)


# ---- API -------------------------------------------------------------------------------------


def test_api_cancel_queued_permissions(env):
    viewer = client_for(env, "viewer")
    assert viewer.post("/api/contests/weekly-contest-511/scan").status_code == 202  # viewer's own request
    admin = client_for(env, "admin")
    assert admin.post(f"/api/contests/{SLUG}/scan").status_code == 202  # admin's request

    assert viewer.post(f"/api/contests/{SLUG}/scan/cancel").status_code == 403  # not theirs
    r = viewer.post("/api/contests/weekly-contest-511/scan/cancel")
    assert r.status_code == 200 and r.json() == {"cancelled": "queued"}
    assert admin.post(f"/api/contests/{SLUG}/scan/cancel").json() == {"cancelled": "queued"}
    assert admin.post(f"/api/contests/{SLUG}/scan/cancel").status_code == 404  # nothing left
    assert admin.get("/api/scan-status").json()["queue"] == []

    _, factory_ = env
    with factory_() as s:
        errors = {r.contest_slug: r.error for r in s.scalars(select(ScanRequest))}
    assert errors == {"weekly-contest-511": "cancelled by viewer", SLUG: "cancelled by admin"}


def test_api_cancel_running_sets_flag(env):
    _, factory_ = env
    with factory_() as s:
        s.add(ScanRun(contest_slug="weekly-contest-511", status="running", pages_done=10, pages_total=100))
        s.commit()
    viewer = client_for(env, "viewer")
    assert viewer.post("/api/contests/weekly-contest-511/scan/cancel").status_code == 403  # automatic scan: admins only
    admin = client_for(env, "admin")
    assert admin.post("/api/contests/weekly-contest-511/scan/cancel").json() == {"cancelled": "running"}
    running = admin.get("/api/scan-status").json()["running"]
    assert running["slug"] == "weekly-contest-511" and running["cancel_requested"] is True


class CancelSecondRequestClient(WorkerClient):
    """While the first requested scan runs, someone cancels the next queued request."""

    def __init__(self, factory, **kw):
        super().__init__(**kw)
        self.factory = factory

    async def ranking_page(self, slug, page):
        if page == 2:
            with self.factory() as other:
                req = other.scalars(select(ScanRequest).where(ScanRequest.contest_slug == "weekly-contest-511")).one()
                if req.handled_at is None:
                    req.handled_at, req.error = END, "cancelled by admin"
                    other.commit()
        return await super().ranking_page(slug, page)


def test_worker_skips_requests_cancelled_while_another_scan_runs(factory):
    with factory() as s:
        s.add_all([ScanRequest(contest_slug=SLUG, requested_by="admin"),
                   ScanRequest(contest_slug="weekly-contest-511", requested_by="admin")])
        s.commit()
    worker, _, _ = make_worker(factory, CancelSecondRequestClient(factory, upcoming=[]), END + timedelta(days=1))
    asyncio.run(worker.tick())
    with factory() as s:
        scanned = [r.contest_slug for r in s.scalars(select(ScanRun))]
        second = s.scalars(select(ScanRequest).where(ScanRequest.contest_slug == "weekly-contest-511")).one()
    assert scanned == [SLUG]
    assert second.error == "cancelled by admin" and second.scan_run_id is None


def test_stop_arriving_with_the_last_page_still_cancels():
    stop = {"now": False}

    def on_progress(done, total):
        if done == total:  # the dashboard's stop is picked up with the final progress update
            stop["now"] = True

    with pytest.raises(ScanCancelledError):
        asyncio.run(scan_contest(FakeClient(), SLUG, now=2_000_000_000, on_progress=on_progress,
                                 should_cancel=lambda: stop["now"]))


def test_stop_after_all_pages_are_fetched_saves_nothing(factory, monkeypatch):
    real_scan = scans_module.scan_contest

    async def scan_then_stop(*args, **kw):
        result = await real_scan(*args, **kw)
        with factory() as other:  # stop clicked while the results are being matched and stored
            run = other.scalars(select(ScanRun).where(ScanRun.status == "running")).one()
            run.cancel_requested = True
            other.commit()
        return result

    monkeypatch.setattr(scans_module, "scan_contest", scan_then_stop)
    with factory() as s:
        _sync(s)
        with pytest.raises(ScanCancelledError):
            asyncio.run(scan_and_store(s, FakeClient(), SLUG))
        run = s.scalars(select(ScanRun)).one()
        assert run.status == "cancelled" and run.finished_at is not None
        assert s.scalars(select(Result)).all() == []  # nothing stored
        assert s.get(Contest, SLUG) is None  # contest details not updated either

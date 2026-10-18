# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
"""Letting the database sleep: /api/warm, the worker's wake-up signal, and the worker
sleeping outside the awake window until its next job."""

import asyncio
import io
import json
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import routes_ops
from app.api.app import create_app
from app.api.observe import watch
from app.db.models import AppState, ScanRequest
from app.services import wake
from app.services.scan_status import worker_status
from app.services.tags import NIGHTLY_KEY
from app.worker import MAX_SLEEP, MAX_SLEEP_WITH_SIGNAL, RATINGS_KEY, Worker
from tests.test_api import SLUG, client_for, env  # noqa: F401  (env is a fixture)
from tests.test_worker import Alerts, WorkerClient, add_contest, factory, settings  # noqa: F401  (fixtures)

IST = timezone(timedelta(hours=5, minutes=30))
NIGHT = datetime(2026, 10, 20, 22, 0, tzinfo=IST).astimezone(timezone.utc)  # 22:00 IST, outside the window


@pytest.fixture(autouse=True)
def fresh_signal(tmp_path, monkeypatch):
    monkeypatch.setattr(wake, "SIGNAL", tmp_path / "wake")
    routes_ops._warmed.clear()


def test_warm_touches_the_database_once_per_10_seconds(env, caplog):
    settings_, factory_ = env
    c = TestClient(create_app(settings_, factory_))
    queries = []
    engine = factory_.kw["bind"]
    watch(engine)

    from sqlalchemy import event

    def count(conn, cursor, statement, *a):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        with caplog.at_level(logging.INFO, logger="app.requests"):
            first = c.get("/api/warm")
            second = c.get("/api/warm")
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert first.json() == {"ok": True} and second.json() == {"ok": True}
    assert queries == ["SELECT 1"]  # the second call didn't touch the database
    assert "/api/warm" not in caplog.text  # no log line per call


def test_scan_requests_signal_the_worker(env):
    c = client_for(env, "admin")
    assert c.get("/api/worker/wake").json() == {"at": None}
    assert c.post("/api/admin/scans", json={"slug": SLUG, "kind": "final"}).status_code == 202
    at = c.get("/api/worker/wake").json()["at"]
    assert at and abs(at - datetime.now(timezone.utc).timestamp()) < 60


def sleepy_worker(factory, now, **overrides):
    clock = {"now": now}
    worker = Worker(factory, lambda: WorkerClient(upcoming=[]), settings=replace(settings(), **overrides),
                    notifier=Alerts(), clock=lambda: clock["now"])
    worker._last_discovery = now  # discovery just ran
    with factory() as s:
        s.merge(AppState(key=RATINGS_KEY, value=now.isoformat(), updated_at=now))  # ratings just synced
        s.merge(AppState(key=NIGHTLY_KEY, value=now.isoformat(), updated_at=now))  # tags refreshed tonight
        s.commit()
    return worker, clock


def test_worker_checks_every_minute_inside_the_window(factory):
    worker, _ = sleepy_worker(factory, datetime(2026, 10, 20, 11, 0, tzinfo=IST))
    assert worker.plan_sleep(60) is None


def test_worker_sleeps_outside_the_window_and_still_counts_as_running(factory):
    worker, _ = sleepy_worker(factory, NIGHT)
    wake_at = worker.plan_sleep(60)
    assert wake_at == NIGHT + MAX_SLEEP
    with factory() as s:
        later = worker_status(s, NIGHT + timedelta(minutes=25))
        assert later["alive"] is True and later["next_check"]
        assert worker_status(s, wake_at + timedelta(minutes=5))["alive"] is False  # it overslept


def test_with_the_wake_signal_it_sleeps_longer_but_not_past_the_window(factory):
    worker, _ = sleepy_worker(factory, NIGHT, worker_wake_url="http://site/api/worker/wake")
    # 22:00 + 3 h would pass midnight, when the nightly tag refresh is due
    assert worker.plan_sleep(60) == datetime(2026, 10, 21, 0, 0, tzinfo=IST).astimezone(timezone.utc)
    late = datetime(2026, 10, 21, 1, 0, tzinfo=IST).astimezone(timezone.utc)
    worker, _ = sleepy_worker(factory, late, worker_wake_url="http://site/api/worker/wake")
    assert worker.plan_sleep(60) == late + MAX_SLEEP_WITH_SIGNAL
    early = datetime(2026, 10, 21, 8, 0, tzinfo=IST).astimezone(timezone.utc)
    worker, _ = sleepy_worker(factory, early, worker_wake_url="http://site/api/worker/wake")
    assert worker.plan_sleep(60) == datetime(2026, 10, 21, 9, 30, tzinfo=IST).astimezone(timezone.utc)


def test_worker_wakes_for_due_scans_and_requests(factory):
    # a contest from 20:00 to 21:30 IST: its first scan is due at 22:00 (NIGHT)
    add_contest(factory, slug="weekly-contest-999", start=int((NIGHT - timedelta(hours=2)).timestamp()))
    worker, _ = sleepy_worker(factory, NIGHT + timedelta(minutes=10))
    assert worker.plan_sleep(60) is None  # 22:10: the scan is due now

    worker, _ = sleepy_worker(factory, NIGHT - timedelta(minutes=20))
    assert worker.plan_sleep(60) == NIGHT  # 21:40: sleep until the scan is due

    with factory() as s:
        s.add(ScanRequest(contest_slug="weekly-contest-999", kind="provisional", requested_by="admin"))
        s.commit()
    assert worker.plan_sleep(60) is None  # a requested scan is waiting


def test_a_sleeping_worker_wakes_on_the_signal(factory, monkeypatch):
    worker, clock = sleepy_worker(factory, NIGHT, worker_wake_url="http://site/api/worker/wake")
    worker._tick_started = NIGHT
    answers = iter([None, None, NIGHT.timestamp() + 60])

    def fake_urlopen(url, timeout):
        return io.BytesIO(json.dumps({"at": next(answers)}).encode())

    async def no_wait(_secs):
        clock["now"] += timedelta(seconds=30)

    monkeypatch.setattr("app.worker.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("app.worker.asyncio.sleep", no_wait)
    asyncio.run(worker._sleep_until(NIGHT + timedelta(hours=3)))
    assert clock["now"] == NIGHT + timedelta(seconds=90)  # the third check saw the request


def test_a_missed_nightly_tag_refresh_keeps_the_worker_up(factory):
    worker, _ = sleepy_worker(factory, NIGHT)
    with factory() as s:
        s.merge(AppState(key=NIGHTLY_KEY, value="", updated_at=NIGHT - timedelta(days=2)))
        s.commit()
    assert worker.plan_sleep(60) is None

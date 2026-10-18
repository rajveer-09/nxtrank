# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
import asyncio
import csv
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.migrate import upgrade
from app.db.models import Contest, ScanRun, Student
from app.db.session import make_engine, make_session_factory
from app.services.schedule import DEFAULT_FINAL
from app.leetcode.client import ContestNotFoundError, LeetCodeBlockedError, LeetCodeError
from app.leetcode.schemas import Contest as ContestSchema
from app.services.discovery import discover_contests
from app.worker import Policy, Worker, due_scans
from tests.conftest import FakeClient
from tests.dbutil import fresh_url

START = 1789871400  # weekly-contest-520 (fixtures)
END = datetime.fromtimestamp(START + 5400, timezone.utc)
SLUG = "weekly-contest-520"

ROSTER_CSV = """Roll No,Name,College,LeetCode
R1,Top Ranker,A,karanVk
R2,Penalty Case,A,kunaallll
R3,Ghost,B,ghost_handle_xyz
"""


def contest(slug, start=START, duration=5400):
    n = slug.rsplit("-", 1)[1]
    return ContestSchema(id=0, title=f"Contest {n}", title_slug=slug, start_time=start,
                         duration=duration)


class WorkerClient(FakeClient):
    """FakeClient + discovery + handle validation."""

    def __init__(self, *, upcoming=(), known=(), past=(), handles=("karanVk", "kunaallll"), **kw):
        super().__init__(**kw)
        self.upcoming = list(upcoming)
        self.past = list(past)
        self.known = {c.title_slug: c for c in known}
        self.handles = {h.lower(): h for h in handles}
        self.info_requests = []

    async def upcoming_contests(self):
        return self.upcoming

    async def past_contests(self, page):
        pages = [self.past[i:i + 10] for i in range(0, len(self.past), 10)] or [[]]
        return pages[page - 1], len(pages)

    async def contest_info(self, slug):
        self.info_requests.append(slug)
        if slug == SLUG:
            return self.info
        if slug in self.known:
            return self.info.model_copy(update={"contest": self.known[slug], "questions": []})
        raise ContestNotFoundError(slug)

    async def matched_user(self, handle):
        return self.handles.get(handle.lower())

    async def contest_ranking(self, handle):
        self.rating_calls = getattr(self, "rating_calls", 0) + 1
        return {"rating": 1600.0, "globalRanking": 1, "topPercentage": 1.0, "attendedContestsCount": 1}, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


class Alerts:
    def __init__(self):
        self.messages = []
        self.enabled = True

    def send(self, text):
        self.messages.append(text)


@pytest.fixture
def factory(tmp_path):
    url = fresh_url(tmp_path)
    upgrade(url)
    return make_session_factory(make_engine(url))


@pytest.fixture
def students(factory):
    """The roster, uploaded the way an admin would (Excel / CSV import)."""
    from app.services.roster_admin import import_students

    with factory() as s:
        import_students(s, list(csv.reader(io.StringIO(ROSTER_CSV))), actor="admin")


def settings():
    return Settings(
        database_url="", proxy_url=None, google_credentials=None,
        slack_webhook_url=None, telegram_bot_token=None, telegram_chat_id=None,
        display_tz="Asia/Kolkata", scan_delay_minutes=30, final_scan_working_days=5, final_scan_time="23:00",
        secret_key="test", cookie_secure=False, frontend_dist=Path("/nonexistent"),
        scan_review_enabled=False,  # the draft tests turn it on (test_drafts.py)
    )


def make_worker(factory, client, now):
    alerts = Alerts()
    clock = {"now": now}
    worker = Worker(factory, lambda: client, settings=settings(), notifier=alerts,
                    clock=lambda: clock["now"])
    return worker, alerts, clock


def add_contest(factory, slug=SLUG, start=START):
    with factory() as s:
        s.add(Contest(slug=slug, title=slug, contest_type="weekly", start_time=start,
                      duration=5400, questions=[]))
        s.commit()


def add_run(factory, kind, status, slug=SLUG, started_at=None):
    with factory() as s:
        s.add(ScanRun(contest_slug=slug, kind=kind, status=status,
                      started_at=started_at or datetime.now(timezone.utc)))
        s.commit()


def due(factory, now):
    with factory() as s:
        return [(d.slug, d.kind, d.attempt) for d in due_scans(s, Policy(), now)]


# ---- scheduling rules ----------------------------------------------------------


def test_provisional_schedule_and_retries(factory):
    add_contest(factory)
    assert due(factory, END + timedelta(minutes=29)) == []
    assert due(factory, END + timedelta(minutes=30)) == [(SLUG, "provisional", 1)]

    add_run(factory, "provisional", "failed")
    assert due(factory, END + timedelta(minutes=44)) == []
    assert due(factory, END + timedelta(minutes=45)) == [(SLUG, "provisional", 2)]

    add_run(factory, "provisional", "failed")
    add_run(factory, "provisional", "failed")
    assert due(factory, END + timedelta(minutes=89)) == []
    assert due(factory, END + timedelta(minutes=90)) == [(SLUG, "provisional", 4)]

    add_run(factory, "provisional", "failed")
    assert due(factory, END + timedelta(hours=5)) == []  # gave up


def test_final_scan_and_lookback(factory):
    add_contest(factory)
    add_run(factory, "provisional", "complete")
    final_at = DEFAULT_FINAL.due_at(END)  # Sunday contest -> Friday 11 pm IST
    assert due(factory, final_at - timedelta(minutes=1)) == []
    assert due(factory, final_at) == [(SLUG, "final", 1)]
    add_run(factory, "final", "complete")
    assert due(factory, final_at + timedelta(days=1)) == []

    add_contest(factory, "weekly-contest-400", start=START - 86400 * 30)
    assert due(factory, final_at + timedelta(days=1)) == []  # older than the 14-day lookback


def test_final_due_skips_provisional_and_running_blocks(factory):
    add_contest(factory)
    # worker was down until after the final-scan time: only the final scan runs
    late = DEFAULT_FINAL.due_at(END) + timedelta(hours=1)
    assert due(factory, late) == [(SLUG, "final", 1)]
    add_run(factory, "final", "running")
    assert due(factory, late) == []


# ---- discovery ---------------------------------------------------------------------


def test_discovery_fills_gaps_and_probes_ahead(factory):
    add_contest(factory, "weekly-contest-518")
    week = 7 * 86400
    client = WorkerClient(
        upcoming=[contest("weekly-contest-521", START + week), contest("biweekly-contest-190")],
        known=[contest("weekly-contest-519", START - week), contest(SLUG),
               contest("weekly-contest-522", START + 2 * week)],
    )
    with factory() as s:
        new = asyncio.run(discover_contests(s, client))
    assert set(new) == {"weekly-contest-521", "biweekly-contest-190", "weekly-contest-519",
                        "weekly-contest-520", "weekly-contest-522"}
    # gap 519-520 filled, 522 found ahead, stopped at the first missing number after that
    assert "weekly-contest-523" in client.info_requests
    assert "weekly-contest-524" not in client.info_requests


# ---- worker ticks ------------------------------------------------------------------


def test_tick_discovers_and_scans(factory, students):
    client = WorkerClient(upcoming=[contest(SLUG)])
    worker, alerts, clock = make_worker(factory, client, END - timedelta(days=1))

    asyncio.run(worker.tick())  # a day before: discover, nothing to scan
    assert any("Scheduled Contest 520" in m and "Sun 20 Sep 10:00" in m for m in alerts.messages)
    with factory() as s:
        assert s.scalars(select(ScanRun)).all() == []

    clock["now"] = END + timedelta(minutes=31)
    asyncio.run(worker.tick())
    with factory() as s:
        runs = s.scalars(select(ScanRun)).all()
        assert [(r.kind, r.status) for r in runs] == [("provisional", "complete")]
        statuses = {st.roll_no: st.handle_status for st in s.scalars(select(Student))}
        assert statuses == {"R1": "valid", "R2": "valid", "R3": "invalid"}
    assert "Results for Weekly Contest 520: 2/3 students participated, 2 solved" in alerts.messages[-1]

    asyncio.run(worker.tick())  # nothing more to do
    with factory() as s:
        assert len(s.scalars(select(ScanRun)).all()) == 1


def test_tick_reports_failures_with_next_retry(factory, students):
    client = WorkerClient(upcoming=[contest(SLUG)], fail={2: LeetCodeError("HTTP 502")})
    worker, alerts, clock = make_worker(factory, client, END + timedelta(minutes=30))
    asyncio.run(worker.tick())
    assert "failed, attempt 1/4" in alerts.messages[-1]
    assert "Next try Sun 20 Sep 10:15" in alerts.messages[-1]

    client.fail = {2: LeetCodeBlockedError("challenge")}
    clock["now"] = END + timedelta(minutes=45)
    asyncio.run(worker.tick())
    assert alerts.messages[-1].startswith("Blocked by Cloudflare.")

    client.fail = {}
    clock["now"] = END + timedelta(minutes=60)
    asyncio.run(worker.tick())
    assert alerts.messages[-1].startswith("Results for Weekly Contest 520")


def test_tick_gives_up_after_last_attempt(factory, students):
    client = WorkerClient(upcoming=[contest(SLUG)])
    worker, alerts, _ = make_worker(factory, client, END + timedelta(minutes=90))
    for _ in range(3):
        add_run(factory, "provisional", "failed")
    client.fail = {2: LeetCodeError("HTTP 502")}
    asyncio.run(worker.tick())
    assert "attempt 4/4" in alerts.messages[-1] and "Giving up" in alerts.messages[-1]


def test_interrupted_running_scan_is_marked_failed(factory):
    add_contest(factory)
    now = END + timedelta(hours=2)
    add_run(factory, "provisional", "running", started_at=now - timedelta(hours=1, minutes=5))
    client = WorkerClient(upcoming=[])
    worker, _, _ = make_worker(factory, client, now)
    asyncio.run(worker.tick())
    with factory() as s:
        runs = s.scalars(select(ScanRun).order_by(ScanRun.id)).all()
    assert runs[0].status == "failed" and "interrupted" in runs[0].error
    # no students in the DB, so the retry (attempt 2) itself has nobody to match but still completes
    assert runs[1].status == "complete"


def test_tick_runs_requested_scans(factory, students):
    from app.db.models import ScanRequest

    with factory() as s:
        s.add_all([ScanRequest(contest_slug=SLUG, kind="final", requested_by="admin"),
                   ScanRequest(contest_slug="weekly-contest-999", requested_by="admin")])
        s.commit()
    client = WorkerClient(upcoming=[])
    worker, alerts, _ = make_worker(factory, client, END + timedelta(days=1))
    asyncio.run(worker.tick())

    with factory() as s:
        reqs = s.scalars(select(ScanRequest).order_by(ScanRequest.id)).all()
        runs = s.scalars(select(ScanRun).order_by(ScanRun.id)).all()
    assert all(r.handled_at is not None for r in reqs)
    assert reqs[0].scan_run_id == runs[0].id and runs[0].kind == "final" and reqs[0].error is None
    assert "Cannot find contest" in reqs[1].error or "weekly-contest-999" in reqs[1].error
    assert any("Final results for Weekly Contest 520 (requested by admin)" in m for m in alerts.messages)
    assert any("Requested scan of weekly-contest-999 failed" in m for m in alerts.messages)
    assert client.rating_calls == 2  # ratings refreshed after the final scan (valid handles only)
    # the completed final scan also satisfies the scheduled provisional scan
    assert [r.kind for r in runs if r.contest_slug == SLUG] == ["final"]


def test_request_made_during_a_scan_runs_before_next_automatic_scan(factory):
    from app.db.models import ScanRequest

    add_contest(factory, "weekly-contest-519", START - 7 * 86400)
    add_contest(factory, SLUG, START)
    worker, _, clock = make_worker(factory, WorkerClient(upcoming=[]), END + timedelta(hours=2))
    order = []

    async def fake_scan(session, client, job):
        order.append(job.slug)
        if len(order) == 1:  # someone clicks "Get results" during the first scan
            session.add(ScanRequest(contest_slug="weekly-contest-150", requested_by="a"))
        session.add(ScanRun(contest_slug=job.slug, kind=job.kind, status="complete"))
        session.commit()

    async def fake_requested(session, client):
        for req in session.scalars(select(ScanRequest).where(ScanRequest.handled_at.is_(None))).all():
            order.append(req.contest_slug)
            req.handled_at = clock["now"]
        session.commit()

    worker._run_scan = fake_scan
    worker._run_requested = fake_requested
    asyncio.run(worker.tick())
    assert order == ["weekly-contest-519", "weekly-contest-150", SLUG]


def test_worker_checks_in_on_a_timer(factory):
    """The dashboard must not report the worker as stopped while a tick works for minutes
    (a scan, then the ratings sync) without passing the check-in at the start of the next tick."""
    from app.services.scan_status import worker_status

    worker, _, _ = make_worker(factory, WorkerClient(upcoming=[]), END)
    with factory() as s:
        assert worker_status(s, END)["alive"] is False

    async def go():
        beat = asyncio.create_task(worker._heartbeat_forever(0.01))
        await asyncio.sleep(0.05)
        beat.cancel()

    asyncio.run(go())
    with factory() as s:
        assert worker_status(s, END)["alive"] is True


def test_requested_scans_pick_early_or_final_by_the_contests_age(factory, students):
    """A contest that ended over 4 days ago is already settled on LeetCode: final results."""
    from app.db.models import ScanRequest
    from app.services.scans import AUTO, kind_by_age

    final_at = DEFAULT_FINAL.due_at(END).timestamp()
    assert kind_by_age(START, 5400, final_at) == "final"
    assert kind_by_age(START, 5400, final_at - 1) == "provisional"

    for days_after, expected in ((1, "provisional"), (7, "final")):
        with factory() as s:
            s.add(ScanRequest(contest_slug=SLUG, kind=AUTO, requested_by="admin"))
            s.commit()
        client = WorkerClient(upcoming=[])
        worker, alerts, _ = make_worker(factory, client, END + timedelta(days=days_after))
        asyncio.run(worker.tick())
        with factory() as s:
            run = s.scalars(select(ScanRun).order_by(ScanRun.id.desc())).first()
        assert (run.kind, run.status) == (expected, "complete")
        assert ("Final results" if expected == "final" else "Results") in " ".join(alerts.messages)

# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""Manual scans as drafts: nothing on the dashboard changes until an admin adds the
draft, adding it equals a direct scan, and old or outdated drafts are dealt with."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.models import Result, ScanDraft, ScanRequest, ScanRun
from app.scan.scanner import ScanCancelledError
from app.services import drafts, scans, summaries
from app.services.scans import scan_and_store
from app.worker import Worker
from tests.conftest import FakeClient
from tests.test_api import SLUG, client_for, env  # noqa: F401  (env is a fixture)
from tests.test_worker import END, Alerts, WorkerClient, settings


def results_of(factory):
    with factory() as s:
        return sorted(
            (r.student_id, r.status, r.global_rank, r.leaderboard_rank, r.rank_source, r.college_rank,
             r.score, r.solved_count, r.total_time_secs,
             tuple((p.q_label, p.question_id, p.solve_secs, p.fail_count, p.lang) for p in r.problems))
            for r in s.scalars(select(Result).where(Result.contest_slug == SLUG)))


def make_draft(factory) -> int:
    with factory() as s:
        return asyncio.run(scan_and_store(s, FakeClient(), SLUG, draft=True)).id


def version(factory):
    with factory() as s:
        return summaries.data_version(s)


def test_a_draft_changes_nothing_until_it_is_added(env):
    _, factory = env
    before, v = results_of(factory), version(factory)
    run_id = make_draft(factory)
    assert results_of(factory) == before and version(factory) == v  # nothing counted, caches still valid
    with factory() as s:
        assert s.get(ScanRun, run_id).status == "review"

    admin = client_for(env, "admin")
    review = admin.get(f"/api/contests/{SLUG}").json()["review"]
    assert review["run_id"] == run_id and review["participated"] == 3 and review["participated_before"] == 3
    assert client_for(env, "viewer").get(f"/api/contests/{SLUG}").json()["review"] is None
    rows = admin.get(f"/api/admin/scans/{run_id}/draft/rows").json()
    assert rows["total"] == 4 and rows["rows"][0]["college_rank"] == 1 and rows["rows"][0]["before"]
    assert client_for(env, "viewer").post(f"/api/admin/scans/{run_id}/publish").status_code == 403


def test_adding_a_draft_equals_a_direct_scan(env):
    _, factory = env
    direct = results_of(factory)
    with factory() as s:  # start from a different state, so the publish visibly writes
        for r in s.scalars(select(Result).where(Result.contest_slug == SLUG)):
            r.score = 0
        s.commit()
    run_id = make_draft(factory)
    admin = client_for(env, "admin")
    assert admin.post(f"/api/admin/scans/{run_id}/publish").json() == {"published": run_id, "contest_slug": SLUG}
    assert results_of(factory) == direct
    with factory() as s:
        run = s.get(ScanRun, run_id)
        assert (run.status, run.review_decision, run.reviewed_by) == ("complete", "published", "admin")
        assert s.get(ScanDraft, run_id) is None
        assert {r.scan_run_id for r in s.scalars(select(Result).where(Result.contest_slug == SLUG))} == {run_id}
    assert admin.post(f"/api/admin/scans/{run_id}/publish").json()["code"] == "draft_gone"


def test_discarding_leaves_everything_as_it_was(env):
    _, factory = env
    before, v = results_of(factory), version(factory)
    run_id = make_draft(factory)
    assert client_for(env, "admin").post(f"/api/admin/scans/{run_id}/discard").json() == {"discarded": run_id}
    assert results_of(factory) == before and version(factory) == v
    with factory() as s:
        assert s.get(ScanRun, run_id).status == "discarded" and s.get(ScanDraft, run_id) is None


def test_a_newer_draft_replaces_the_older_and_a_direct_scan_outdates_it(env):
    _, factory = env
    first, second = make_draft(factory), make_draft(factory)
    with factory() as s:
        assert (s.get(ScanRun, first).status, s.get(ScanRun, first).review_decision) == ("discarded", "replaced")
        asyncio.run(scan_and_store(s, FakeClient(), SLUG))  # e.g. the scheduled final scan
        assert s.get(ScanRun, second).review_decision == "outdated"
    admin = client_for(env, "admin")
    assert admin.get(f"/api/contests/{SLUG}").json()["review"]["outdated"] is True
    r = admin.post(f"/api/admin/scans/{second}/publish")
    assert r.status_code == 409 and "discard" in r.json()["detail"]
    assert admin.post(f"/api/admin/scans/{second}/discard").status_code == 200


def test_unreviewed_drafts_expire_after_a_week(env):
    _, factory = env
    run_id = make_draft(factory)
    with factory() as s:
        finished = s.get(ScanRun, run_id).finished_at
        assert drafts.expire(s, finished + timedelta(days=6)) == 0
        assert drafts.expire(s, finished + drafts.KEEP_FOR + timedelta(minutes=1)) == 1
        run = s.get(ScanRun, run_id)
        assert (run.status, run.review_decision) == ("discarded", "expired")


def test_a_cancelled_scan_leaves_no_draft(env, monkeypatch):
    _, factory = env

    def cancelled(session, run, slug):
        raise ScanCancelledError(slug)

    monkeypatch.setattr(scans, "_check_cancel", cancelled)
    with factory() as s, pytest.raises(ScanCancelledError):
        asyncio.run(scan_and_store(s, FakeClient(), SLUG, draft=True))
    with factory() as s:
        assert s.scalars(select(ScanDraft)).first() is None
        assert s.scalars(select(ScanRun).order_by(ScanRun.id.desc())).first().status == "cancelled"


def test_the_worker_keeps_requested_scans_as_drafts(env):
    _, factory = env
    before = results_of(factory)
    with factory() as s:
        s.add(ScanRequest(contest_slug=SLUG, kind="provisional", requested_by="admin"))
        s.commit()
    alerts = Alerts()
    worker = Worker(factory, lambda: WorkerClient(upcoming=[]), settings=replace(settings(), scan_review_enabled=True),
                    notifier=alerts, clock=lambda: END + timedelta(days=1))
    asyncio.run(worker.tick())
    with factory() as s:
        assert s.scalars(select(ScanRun).order_by(ScanRun.id.desc())).first().status == "review"
    assert results_of(factory) == before
    assert any("ready for review" in m for m in alerts.messages)

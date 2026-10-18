# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
"""Production hardening: security headers, the Origin check, API docs off in production,
the shared login throttle, the single-worker lock and rate-limited crash alerts."""

import logging
from dataclasses import replace
from datetime import timedelta

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.services import notify
from app.worker import LOCK_LEASE, Worker
from tests.test_api import client_for, env  # noqa: F401  (env is a fixture)
from tests.test_worker import END, factory, make_worker, settings  # noqa: F401  (fixtures)

THEME = "document.documentElement.dataset.theme = 'dark';"


def app_with_page(env, tmp_path, **overrides):
    settings_, factory_ = env
    dist = tmp_path / "site"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text(f"<html><head><script>{THEME}</script></head><body></body></html>")
    return TestClient(create_app(replace(settings_, frontend_dist=dist, **overrides), factory_))


def test_security_headers_on_pages_and_api(env, tmp_path):
    c = app_with_page(env, tmp_path)
    page = c.get("/students")
    csp = page.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert "'sha256-" in csp  # the inline theme script is allowed by its hash only
    api = c.get("/api/health")
    assert api.headers["Content-Security-Policy"].startswith("default-src 'none'")
    for r in (page, api):
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "Strict-Transport-Security" not in r.headers  # plain http in tests

    secure = app_with_page(env, tmp_path, cookie_secure=True)
    assert secure.get("/api/health").headers["Strict-Transport-Security"].startswith("max-age=")


def test_change_requests_from_other_sites_are_refused(env):
    c = client_for(env)
    login = {"username": "viewer", "password": "viewer-password-1"}
    r = c.post("/api/auth/login", json=login, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["code"] == "bad_origin"
    r = c.post("/api/auth/login", json=login, headers={"Referer": "https://evil.example/page"})
    assert r.status_code == 403
    assert c.post("/api/auth/login", json=login, headers={"Origin": "null"}).status_code == 403
    # our own page, and tools that send no Origin at all
    assert c.post("/api/auth/login", json=login, headers={"Origin": "http://testserver"}).status_code == 200
    assert c.post("/api/auth/logout").status_code == 200
    # reading is never blocked
    assert c.get("/api/health", headers={"Origin": "https://evil.example"}).status_code == 200


def test_allowed_origins_setting(env):
    settings_, factory_ = env
    c = TestClient(create_app(replace(settings_, allowed_origins=("http://localhost:5173",)), factory_))
    r = c.post("/api/auth/login", json={"username": "viewer", "password": "viewer-password-1"},
               headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200


def test_api_docs_only_outside_production(env):
    settings_, factory_ = env
    assert TestClient(create_app(settings_, factory_)).get("/api/docs").status_code == 200
    prod = TestClient(create_app(replace(settings_, app_env="production"), factory_))
    assert prod.get("/api/docs").status_code == 404
    assert prod.get("/api/openapi.json").status_code == 404


def test_login_throttle_is_shared_by_every_process(env):
    settings_, factory_ = env
    one, two = (TestClient(create_app(settings_, factory_)) for _ in range(2))
    for i in range(5):
        (one if i % 2 else two).post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    fresh = TestClient(create_app(settings_, factory_))  # e.g. after a restart
    r = fresh.post("/api/auth/login", json={"username": "admin", "password": "admin-password-1"})
    assert r.status_code == 429 and r.json()["code"] == "rate_limited"


def test_only_one_worker_runs(factory):
    first, _, clock = make_worker(factory, None, END)
    second = Worker(factory, lambda: None, settings=settings(), notifier=None, clock=lambda: clock["now"])
    assert first.claim_lock() and first.claim_lock()  # renewing is fine
    assert not second.claim_lock() and second.lock_holder == first.lock_id

    clock["now"] += LOCK_LEASE + timedelta(seconds=1)  # the first one stopped renewing
    assert second.claim_lock() and not first.claim_lock()

    second.release_lock()
    assert first.claim_lock()


class _Sent:
    def __init__(self):
        self.texts = []
        self.enabled = True

    def send(self, text):
        self.texts.append(text)


class _Now:
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def test_crash_alerts_are_rate_limited(monkeypatch):
    monkeypatch.setattr(notify.threading, "Thread", _Now)
    sent, now = _Sent(), {"t": 0.0}
    handler = notify.CrashAlerts(sent, every=600, clock=lambda: now["t"])
    logger = logging.getLogger("tests.crash")
    logger.addHandler(handler)
    try:
        for t in (0, 10, 20, 700):
            now["t"] = t
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                logger.exception("unhandled error on GET /api/x")
    finally:
        logger.removeHandler(handler)
    assert len(sent.texts) == 2
    assert "RuntimeError: boom" in sent.texts[0]
    assert "2 more since the last alert" in sent.texts[1]


def test_scans_can_be_switched_off_for_staging(env):
    settings_, factory_ = env
    c = TestClient(create_app(replace(settings_, scans_enabled=False), factory_))
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin-password-1"})
    assert r.json()["scans_enabled"] is False
    for path, body in [("/api/admin/scans", {"slug": "weekly-contest-400", "kind": "final"}),
                       ("/api/contests/weekly-contest-400/scan", None)]:
        r = c.post(path, json=body)
        assert r.status_code == 409 and r.json()["code"] == "scans_disabled", path

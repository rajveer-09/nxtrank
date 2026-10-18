# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
"""Every API error has one shape (detail, code, request_id), crashes don't leak internals,
and the request ID in a reply matches the one in the server's log."""

import logging

from fastapi.testclient import TestClient

from app.api import routes_data
from app.api.app import create_app
from app.leetcode.client import LeetCodeBlockedError
from tests.test_api import client_for, env  # noqa: F401  (env is a fixture)


def test_errors_have_a_code_and_a_request_id(env):
    c = client_for(env, "viewer")
    r = c.get("/api/contests/no-such-contest/results")
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "not_found" and isinstance(body["detail"], str)
    assert body["request_id"] == r.headers["X-Request-ID"]

    assert client_for(env).get("/api/auth/me").json()["code"] == "unauthorized"


def test_a_good_incoming_request_id_is_kept_and_a_bad_one_replaced(env):
    c = client_for(env)
    assert c.get("/api/auth/me", headers={"X-Request-ID": "trace-12345678"}).headers["X-Request-ID"] == "trace-12345678"
    assert c.get("/api/auth/me", headers={"X-Request-ID": "bad id\n"}).headers["X-Request-ID"] != "bad id\n"
    assert c.get("/api/health").headers["X-Request-ID"]


def test_validation_errors_read_as_text(env):
    c = client_for(env)
    r = c.post("/api/auth/login", json={"username": "admin"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation"
    assert "password" in body["detail"] and isinstance(body["detail"], str)
    assert body["errors"][0]["field"] == "password"


def test_a_crash_returns_a_safe_500_with_the_logged_reference(env, caplog):
    settings, factory = env
    app = create_app(settings, factory)

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("secret internals")

    with caplog.at_level(logging.ERROR, logger="app.errors"):
        r = TestClient(app).get("/api/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["code"] == "internal" and "secret" not in r.text
    rid = r.headers["X-Request-ID"]
    assert body["request_id"] == rid and rid in body["detail"]
    assert r.headers["Cache-Control"] == "private, no-store"
    crash = next(rec for rec in caplog.records if rec.name == "app.errors")
    assert crash.exc_info and "secret internals" in caplog.text


class BlockedLive:
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def contest_ranking(self, handle):
        raise LeetCodeBlockedError("challenge page")


def test_a_blocked_live_rating_says_so(env, monkeypatch):
    monkeypatch.setattr(routes_data, "LeetCodeClient", BlockedLive)
    c = client_for(env, "viewer")
    sid = next(s["id"] for s in c.get("/api/students").json()["rows"] if s["roll_no"] == "R1")
    r = c.post(f"/api/students/{sid}/rating/refresh")
    assert r.status_code == 503 and r.json()["code"] == "leetcode_blocked"

# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
"""Per-request timing: a `Server-Timing` header (db / app /
total, shown in DevTools) and one JSON log line per API call, read by scripts/slow_routes.py.
"""

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import Engine, event
from starlette.datastructures import MutableHeaders

from app.api.errors import body
from app.request_context import request_id

log = logging.getLogger("app.requests")
crash_log = logging.getLogger("app.errors")

_GOOD_ID = re.compile(r"[A-Za-z0-9-]{8,64}")


@dataclass
class _Stats:
    queries: int = 0
    db: float = 0.0  # seconds


# The current request's counters. Endpoints run in a worker thread with a copy of this
# context, which still points at the same _Stats object.
_current: ContextVar[_Stats | None] = ContextVar("request_stats", default=None)


def watch(engine: Engine) -> None:
    """Count every statement this engine runs, and its time, against the current request."""
    if getattr(engine, "_observed", False):
        return
    engine._observed = True  # type: ignore[attr-defined]

    @event.listens_for(engine, "before_cursor_execute")
    def _start(conn, cursor, statement, params, context, executemany):
        conn.info.setdefault("observe_t0", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _stop(conn, cursor, statement, params, context, executemany):
        started = conn.info["observe_t0"].pop()
        stats = _current.get()
        if stats is not None:
            stats.queries += 1
            stats.db += time.perf_counter() - started


class Observe:
    """ASGI middleware for every /api request: a request ID (X-Request-ID, in and out),
    the Server-Timing header, one log line, and a safe 500 when an endpoint crashes.

    Crashes are caught here rather than by FastAPI, whose crash handler runs outside
    user middleware, where the request ID is already gone."""

    QUIET = {"/api/health", "/api/warm", "/api/worker/wake"}  # polled on a timer; not worth a line each time

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/"):
            return await self.app(scope, receive, send)

        incoming = next((v.decode("latin-1") for k, v in scope.get("headers", ()) if k == b"x-request-id"), "")
        rid = incoming if _GOOD_ID.fullmatch(incoming) else uuid.uuid4().hex[:16]
        stats = _Stats()
        token = _current.set(stats)
        rid_token = request_id.set(rid)
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_timing(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                total = (time.perf_counter() - started) * 1000
                db = stats.db * 1000
                headers = MutableHeaders(scope=message)
                headers.append(
                    "Server-Timing",
                    f'db;dur={db:.1f};desc="{stats.queries} queries", app;dur={max(0.0, total - db):.1f}, '
                    f"total;dur={total:.1f}")
                headers["X-Request-ID"] = rid
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        except Exception:
            crash_log.exception("unhandled error on %s %s", scope.get("method"), path)
            if not response_started:
                await _send_crash(send_with_timing, rid)
        finally:
            _current.reset(token)
            if path not in self.QUIET:
                route = scope.get("route")
                log.info(json.dumps({
                    "route": getattr(route, "path", None) or "(unmatched)",
                    "method": scope.get("method"),
                    "status": status,
                    "ms": round((time.perf_counter() - started) * 1000, 1),
                    "db_ms": round(stats.db * 1000, 1),
                    "queries": stats.queries,
                    "rid": rid,
                }, separators=(",", ":")))
            request_id.reset(rid_token)


async def _send_crash(send, rid: str) -> None:
    """The reply to a crash: no internals, just a reference the user can quote."""
    payload = json.dumps(body(500, f"Something went wrong on our side. Reference: {rid}", "internal")).encode()
    await send({"type": "http.response.start", "status": 500, "headers": [
        (b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode()),
        (b"cache-control", b"private, no-store")]})
    await send({"type": "http.response.body", "body": payload})

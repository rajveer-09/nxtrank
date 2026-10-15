# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
"""Per-request timing: a `Server-Timing` header (db / app /
total, shown in DevTools) and one JSON log line per API call, read by scripts/slow_routes.py.
"""

import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import Engine, event
from starlette.datastructures import MutableHeaders

log = logging.getLogger("app.requests")


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
    """ASGI middleware: Server-Timing header and a log line for every /api request."""

    QUIET = {"/api/health"}  # polled by the proxy; not worth a line each time

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/"):
            return await self.app(scope, receive, send)

        stats = _Stats()
        token = _current.set(stats)
        started = time.perf_counter()
        status = 500

        async def send_with_timing(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                total = (time.perf_counter() - started) * 1000
                db = stats.db * 1000
                MutableHeaders(scope=message).append(
                    "Server-Timing",
                    f'db;dur={db:.1f};desc="{stats.queries} queries", app;dur={max(0.0, total - db):.1f}, '
                    f"total;dur={total:.1f}")
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
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
                }, separators=(",", ":")))

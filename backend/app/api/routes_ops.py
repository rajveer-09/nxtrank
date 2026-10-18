# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
"""Endpoints for keeping things awake, open without a login and returning no data:
/api/warm wakes the database (called by cron-job.org in working hours, and by the login
page), /api/worker/wake tells a sleeping worker that a scan was requested."""

import logging
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from app.services import wake

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", include_in_schema=False)

WARM_EVERY_SECS = 10  # one database touch per client per 10 s is plenty to keep it awake
_warmed: dict[str, float] = {}
_warm_lock = threading.Lock()


@router.get("/warm")
def warm(request: Request) -> dict:
    """Runs SELECT 1, so a suspended database starts waking while the user signs in."""
    client = request.client.host if request.client else "?"
    now = time.monotonic()
    with _warm_lock:
        if now - _warmed.get(client, -WARM_EVERY_SECS) < WARM_EVERY_SECS:
            return {"ok": True}
        _warmed[client] = now
        if len(_warmed) > 1000:  # forget old clients
            for key in [k for k, t in _warmed.items() if now - t > WARM_EVERY_SECS]:
                _warmed.pop(key, None)
    try:
        with request.app.state.session_factory() as db:
            db.execute(text("SELECT 1"))
    except Exception as e:
        log.warning("warm-up query failed: %s", e)
        raise HTTPException(503, "the database is starting; try again in a few seconds") from None
    return {"ok": True}


@router.get("/worker/wake")
def worker_wake() -> dict:
    """When a scan was last requested (seconds since 1970), or null. No database query."""
    return {"at": wake.last_signal()}

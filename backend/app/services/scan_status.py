# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Where each contest stands (results / scanning / queued / scheduled / failed / not
scanned) and when its results should be ready.

Everything here works from a ScanSnapshot: the scan runs, pending requests and worker
heartbeat a page needs, loaded once per request in three small queries and then
reused for the queue, contest states and ETAs (instead of each piece querying again).
"""

import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import AppState, Contest, ScanRequest, ScanRun
from app.services.schedule import DEFAULT_FINAL, FinalSchedule, round_up
from app.services.summaries import DATA_VERSION

HEARTBEAT_KEY = "worker_heartbeat"
WORKER_STALE = timedelta(minutes=3)  # the worker checks in every minute
DEFAULT_SCAN = timedelta(minutes=10)
AUTO_LOOKBACK = timedelta(days=14)  # the worker auto-scans contests that ended this recently
AUTO_ATTEMPTS = 4
TYPICAL_FROM = 5  # the typical scan time is the median of the last few completed scans


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def iso(dt: datetime | None) -> str | None:
    return as_utc(dt).isoformat() if dt else None


def set_state(session: Session, key: str, value: str, now: datetime) -> None:
    row = session.get(AppState, key) or AppState(key=key)
    row.value, row.updated_at = value, now
    session.add(row)
    session.commit()


@dataclass
class ScanSnapshot:
    """Scan runs (for the contests asked about, plus whatever is running and the last
    few completed runs), pending requests oldest first, and the worker heartbeat."""

    runs: list[ScanRun]
    pending: list[ScanRequest]
    heartbeat: datetime | None
    data_version: str | None = None  # read in the same query as the heartbeat

    def runs_of(self, slug: str) -> list[ScanRun]:
        return [r for r in self.runs if r.contest_slug == slug]

    @property
    def running(self) -> ScanRun | None:
        return next((r for r in reversed(self.runs) if r.status == "running"), None)

    @property
    def typical(self) -> timedelta:
        done = [r for r in self.runs if r.status == "complete" and r.finished_at is not None]
        done.sort(key=lambda r: r.id)
        secs = [(as_utc(r.finished_at) - as_utc(r.started_at)).total_seconds() for r in done[-TYPICAL_FROM:]]
        secs = [s for s in secs if s > 0]
        return timedelta(seconds=statistics.median(secs)) if secs else DEFAULT_SCAN


def load_snapshot(session: Session, slugs: Iterable[str] = ()) -> ScanSnapshot:
    """Three queries, bounded by the contests asked about (never the whole history)."""
    last_complete = (select(ScanRun.id)
                     .where(ScanRun.status == "complete", ScanRun.finished_at.is_not(None))
                     .order_by(ScanRun.id.desc()).limit(TYPICAL_FROM))
    wanted = [ScanRun.status == "running", ScanRun.id.in_(last_complete)]
    slugs = list(dict.fromkeys(slugs))
    if slugs:
        wanted.append(ScanRun.contest_slug.in_(slugs))
    runs = session.scalars(select(ScanRun).where(or_(*wanted)).order_by(ScanRun.id)).all()
    pending = session.scalars(select(ScanRequest).where(ScanRequest.handled_at.is_(None))
                              .order_by(ScanRequest.id)).all()
    state = {s.key: s for s in session.scalars(select(AppState).where(AppState.key.in_((HEARTBEAT_KEY, DATA_VERSION))))}
    hb = state.get(HEARTBEAT_KEY)
    version = state.get(DATA_VERSION)
    return ScanSnapshot(list(runs), list(pending), as_utc(hb.updated_at) if hb else None,
                        version.value if version else None)


def worker_status(session: Session, now: datetime, snap: ScanSnapshot | None = None) -> dict:
    snap = snap or load_snapshot(session)
    seen = [snap.heartbeat] if snap.heartbeat else []
    seen += [as_utc(r.progress_at) for r in snap.runs if r.status == "running" and r.progress_at]
    last = max(seen) if seen else None
    return {"alive": bool(last and now - last < WORKER_STALE), "last_seen": iso(last)}


def typical_scan_time(session: Session) -> timedelta:
    return load_snapshot(session).typical


def queue_status(session: Session, now: datetime, snap: ScanSnapshot | None = None) -> dict:
    """The scan in progress (with progress and ETA) and the queued requests, each with
    an estimated ready time. Requests run one after another, oldest first."""
    snap = snap or load_snapshot(session)
    typical = snap.typical
    worker = worker_status(session, now, snap)

    running = None
    run = snap.running
    base = now
    if run:
        started = as_utc(run.started_at)
        done, total = run.pages_done or 0, run.pages_total or 0
        fraction = done / total if total else 0.0
        if fraction >= 0.05:
            elapsed = (as_utc(run.progress_at) or now) - started
            ready = (as_utc(run.progress_at) or now) + elapsed * (1 - fraction) / fraction
        else:
            ready = started + typical
        ready = max(ready, now + timedelta(seconds=30))
        base = ready
        req = next((r for r in snap.pending if r.contest_slug == run.contest_slug), None)
        running = {"slug": run.contest_slug, "kind": run.kind, "pages_done": done,
                   "cancel_requested": run.cancel_requested,
                   "requested_by": req.requested_by if req else None,
                   "pages_total": total or None, "progress": round(fraction, 3),
                   "started_at": iso(started), "ready_at": iso(ready)}

    queue = []
    for req in snap.pending:
        if running and req.contest_slug == running["slug"]:
            continue  # this request is the scan in progress
        base = base + typical
        queue.append({"slug": req.contest_slug, "kind": req.kind, "position": len(queue) + 1,
                      "requested_by": req.requested_by, "requested_at": iso(req.requested_at),
                      "ready_at": iso(base) if worker["alive"] else None})
    return {"worker": worker, "running": running, "queue": queue,
            "typical_scan_secs": int(typical.total_seconds())}


def lookback_filter(now: datetime):
    """Contests the worker may still scan automatically (ended within AUTO_LOOKBACK, or later)."""
    return Contest.start_time + Contest.duration >= int((now - AUTO_LOOKBACK).timestamp())


def _auto_scan_etas(now: datetime, scan_delay: timedelta, queue: dict, typical: timedelta,
                    candidates: list[Contest], snap: ScanSnapshot) -> dict[str, datetime]:
    """Ready times for contests the worker will scan automatically. Due ones run one by
    one, oldest first, after the scan in progress and the queued requests."""
    busy_until = now
    if queue["running"] and queue["running"]["ready_at"]:
        busy_until = datetime.fromisoformat(queue["running"]["ready_at"])
    busy_until += typical * len(queue["queue"])
    taken = {q["slug"] for q in queue["queue"]} | ({queue["running"]["slug"]} if queue["running"] else set())
    done = {r.contest_slug for r in snap.runs if r.status == "complete"}
    etas = {}
    for c in sorted(candidates, key=lambda c: c.start_time):
        if c.slug in done or c.slug in taken:
            continue
        due = datetime.fromtimestamp(c.start_time + c.duration, timezone.utc) + scan_delay
        start = max(due, busy_until)
        etas[c.slug] = start + typical
        if due <= busy_until:
            busy_until = start + typical  # waits its turn behind the others
    return etas


def contest_states(session: Session, contests: list[Contest], now: datetime,
                   scan_delay: timedelta, queue: dict | None = None,
                   final: FinalSchedule | None = DEFAULT_FINAL, *,
                   snap: ScanSnapshot | None = None, candidates: list[Contest] | None = None) -> dict[str, dict]:
    """State of each contest for display. Early (provisional) results also carry
    `final_at`: when the final scan should have finished.

    `candidates` (contests within the auto-scan lookback) and `snap` can be passed in by
    callers that already loaded them; otherwise they're loaded here."""
    if candidates is None:
        candidates = list(session.scalars(select(Contest).where(lookback_filter(now))))
    if snap is None:
        snap = load_snapshot(session, [c.slug for c in contests] + [c.slug for c in candidates])
    queue = queue or queue_status(session, now, snap)
    queued = {q["slug"]: q for q in queue["queue"]}
    running = queue["running"]
    typical = timedelta(seconds=queue["typical_scan_secs"])
    alive = queue["worker"]["alive"]
    auto_eta = _auto_scan_etas(now, scan_delay, queue, typical, candidates, snap)

    out = {}
    for c in contests:
        start = datetime.fromtimestamp(c.start_time, timezone.utc)
        end = start + timedelta(seconds=c.duration)
        rs = snap.runs_of(c.slug)
        complete = [r for r in rs if r.status == "complete"]
        failed = [r for r in rs if r.status in ("failed", "cancelled")]
        state: dict = {"has_data": bool(complete)}
        if complete:
            last = complete[-1]
            state.update(state=last.kind, scanned_at=iso(last.finished_at))
            if last.kind == "provisional" and final is not None:
                state["final_at"] = iso(round_up(final.due_at(end) + typical))
        if running and running["slug"] == c.slug:
            state.update(state="scanning", progress=running["progress"], ready_at=running["ready_at"],
                         rescan=bool(complete), requested_by=running["requested_by"],
                         cancel_requested=running["cancel_requested"])
        elif c.slug in queued:
            q = queued[c.slug]
            state.update(state="queued", position=q["position"], ready_at=q["ready_at"],
                         rescan=bool(complete), requested_by=q["requested_by"])
        elif complete:
            pass
        elif now < start:
            state.update(state="upcoming", ready_at=iso(end + scan_delay + typical))
        elif now < end:
            state.update(state="live", ready_at=iso(end + scan_delay + typical))
        elif now - end <= AUTO_LOOKBACK and len(failed) < AUTO_ATTEMPTS:
            ready = auto_eta.get(c.slug, end + scan_delay + typical)
            state.update(state="scheduled", ready_at=iso(ready) if alive or now < end + scan_delay else None)
        elif failed and failed[-1].status == "failed":
            state.update(state="failed", error=failed[-1].error)
        else:
            state.update(state="not_scanned")
        out[c.slug] = state
    return out

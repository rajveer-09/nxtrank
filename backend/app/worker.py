# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Background worker: discovers contests and scans them after they end.

Every tick (default: each minute) it looks at the database and does whatever is due:

1. discover upcoming contests and keep the list of past contests (every 6 h),
2. check new or changed LeetCode handles right before each scan,
3. scan contests that ended:
   - provisional: end + 30 min, retried at +45, +60, +90 min,
   - final:       11 pm on the 5th working day after the contest (LeetCode settles ranks and
                  ratings "within 5 working days"), retried 1 h and 3 h later;
                  then students' LeetCode ratings are refreshed,
4. run scans requested from the dashboard (rescans, backfills),
5. send alerts for new contests' results, failures and Cloudflare blocks.

All state lives in the database (`contests`, `scan_runs`, `scan_requests`), so the worker
can be restarted at any time. One worker per database: a lease in app_state makes a
second one wait (and take over if the first stops).
"""

import asyncio
import json
import logging
import os
import socket
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import AppState, Contest, ScanRequest, ScanRun, utcnow
from app.leetcode.client import LeetCodeBlockedError, LeetCodeError
from app.scan.scanner import ScanCancelledError, ScanIncompleteError
from app.services import drafts, tags
from app.services.discovery import discover_contests, sync_past_contests
from app.services.scan_status import HEARTBEAT_KEY, set_state
from app.services.export import summarize
from app.services.handles import validate_handles
from app.services.ratings import sync_ratings
from app.services.results import load_contest_results
from app.services.scans import scan_and_store
from app.services.schedule import DEFAULT_FINAL, FinalSchedule, parse_time

log = logging.getLogger(__name__)

HEARTBEAT_EVERY_SECS = 30  # well inside scan_status.WORKER_STALE
# The worker lock: "<owner>|<held until>" in app_state, renewed with every heartbeat.
# A lease rather than a Postgres advisory lock: Neon's pooled connections don't keep
# session locks, and a connection held open all day would keep the database awake.
LOCK_KEY = "worker_lock"
LOCK_LEASE = timedelta(seconds=HEARTBEAT_EVERY_SECS * 4)
# Outside the awake window the worker sleeps until its next job, and asks the website
# every WAKE_POLL_SECS whether someone requested a scan meanwhile. Without that signal
# (no WORKER_WAKE_URL) it checks the database at least every MAX_SLEEP instead; each
# check wakes Neon for 5 minutes, so the cap is longer when the signal is there.
MAX_SLEEP = timedelta(minutes=30)
MAX_SLEEP_WITH_SIGNAL = timedelta(hours=3)
WAKE_POLL_SECS = 30
RATINGS_KEY = "ratings_synced_at"  # app_state: when everyone's rating was last refreshed


@dataclass(frozen=True)
class Policy:
    scan_delay: timedelta = timedelta(minutes=30)
    # attempt n runs at (end + scan_delay) + retries[n-1]: by default end + 30, 45, 60, 90 min
    provisional_retries: tuple[timedelta, ...] = (
        timedelta(0), timedelta(minutes=15), timedelta(minutes=30), timedelta(minutes=60),
    )
    final: FinalSchedule | None = DEFAULT_FINAL  # None: no final scans
    # attempt n runs at final.due_at(end) + final_retries[n-1]
    final_retries: tuple[timedelta, ...] = (timedelta(0), timedelta(hours=1), timedelta(hours=3))
    lookback: timedelta = timedelta(days=14)  # never auto-scan contests that ended earlier
    discovery_every: timedelta = timedelta(hours=6)
    ratings_every: timedelta = timedelta(hours=24)  # plus right after each final scan
    stale_run_after: timedelta = timedelta(hours=1)  # a 'running' scan this old was interrupted

    @classmethod
    def from_settings(cls, settings: Settings) -> "Policy":
        final = (FinalSchedule(settings.final_scan_working_days, parse_time(settings.final_scan_time), settings.display_tz)
                 if settings.final_scan_working_days > 0 else None)
        return cls(scan_delay=timedelta(minutes=settings.scan_delay_minutes), final=final)


def as_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; everything is stored in UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def format_time(dt: datetime, tz_name: str) -> str:
    return f"{as_utc(dt).astimezone(ZoneInfo(tz_name)):%a %d %b %H:%M} ({tz_name})"


@dataclass(frozen=True)
class DueScan:
    slug: str
    kind: str  # provisional | final
    attempt: int  # 1-based
    max_attempts: int


def due_scans(session: Session, policy: Policy, now: datetime) -> list[DueScan]:
    """Scans that should run now. A final scan, when due, is listed before the
    provisional one; a completed final scan also satisfies the provisional."""
    earliest_end = int((now - policy.lookback).timestamp())
    contests = session.scalars(
        select(Contest).where(Contest.start_time + Contest.duration >= earliest_end)
        .order_by(Contest.start_time)
    ).all()

    due: list[DueScan] = []
    for c in contests:
        end = datetime.fromtimestamp(c.start_time + c.duration, timezone.utc)
        if now < end:
            continue
        runs = session.scalars(select(ScanRun).where(ScanRun.contest_slug == c.slug)).all()
        complete = {r.kind for r in runs if r.status == "complete"}
        failed = {kind: sum(1 for r in runs if r.kind == kind and r.status in ("failed", "cancelled"))
                  for kind in ("provisional", "final")}
        if any(r.status == "running" for r in runs):
            continue  # another attempt is in progress

        if policy.final is not None and "final" not in complete:
            d = _due(policy.final.due_at(end), policy.final_retries, failed["final"], now)
            if d:
                due.append(DueScan(c.slug, "final", *d))
                continue
        if not complete:
            d = _due(end + policy.scan_delay, policy.provisional_retries, failed["provisional"], now)
            if d:
                due.append(DueScan(c.slug, "provisional", *d))
    return due


def _due(first_at: datetime, retries: tuple[timedelta, ...], failures: int,
         now: datetime) -> tuple[int, int] | None:
    if failures >= len(retries):
        return None  # gave up
    at = first_at + retries[failures]
    return (failures + 1, len(retries)) if now >= at else None


def next_retry_at(end: datetime, policy: Policy, kind: str, failures: int) -> datetime | None:
    retries = policy.provisional_retries if kind == "provisional" else policy.final_retries
    if failures >= len(retries):
        return None
    first = end + policy.scan_delay if kind == "provisional" else policy.final.due_at(end)
    return first + retries[failures]


def next_due_at(session: Session, policy: Policy, now: datetime) -> datetime | None:
    """When the next automatic scan (first try or retry) is due; None if nothing is planned.
    The counterpart of due_scans, for deciding how long the worker may sleep."""
    earliest_end = int((now - policy.lookback).timestamp())
    contests = session.scalars(select(Contest).where(Contest.start_time + Contest.duration >= earliest_end)).all()
    times: list[datetime | None] = []
    for c in contests:
        end = datetime.fromtimestamp(c.start_time + c.duration, timezone.utc)
        runs = session.scalars(select(ScanRun).where(ScanRun.contest_slug == c.slug)).all()
        complete = {r.kind for r in runs if r.status == "complete"}
        failed = {kind: sum(1 for r in runs if r.kind == kind and r.status in ("failed", "cancelled"))
                  for kind in ("provisional", "final")}
        if policy.final is not None and "final" not in complete:
            times.append(next_retry_at(end, policy, "final", failed["final"]))
        if not complete:
            times.append(next_retry_at(end, policy, "provisional", failed["provisional"]))
    return min((t for t in times if t is not None), default=None)


def parse_window(text: str) -> tuple[time, time] | None:
    """'09:30-18:00' -> (09:30, 18:00); 'always' (or empty) -> None, meaning all day."""
    text = (text or "").strip().lower()
    if text in ("", "always", "24h"):
        return None
    start, _, end = text.partition("-")
    return parse_time(start), parse_time(end)


class Worker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        client_factory: Callable,
        *,
        settings: Settings,
        notifier,
        policy: Policy | None = None,
        clock: Callable[[], datetime] = utcnow,
    ):
        self.session_factory = session_factory
        self.client_factory = client_factory
        self.settings = settings
        self.notifier = notifier
        self.policy = policy or Policy.from_settings(settings)
        self.clock = clock
        self._last_discovery: datetime | None = None
        self.lock_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.awake_window = parse_window(settings.worker_awake_window)
        self._tick_started: datetime | None = None
        self.lock_holder: str | None = None  # who holds the lock when we couldn't get it

    def fmt(self, dt: datetime) -> str:
        return format_time(dt, self.settings.display_tz)

    def claim_lock(self, until: datetime | None = None) -> bool:
        """Take or renew the worker lock (held until `until`, plus the lease); False while
        another live worker holds it."""
        now = self.clock()
        with self.session_factory() as session:
            row = session.get(AppState, LOCK_KEY, with_for_update=True)
            if row is not None and row.value:
                owner, _, held_until = row.value.partition("|")
                if owner != self.lock_id and datetime.fromisoformat(held_until) > now:
                    self.lock_holder = owner
                    session.rollback()
                    return False
            value = f"{self.lock_id}|{(max(now, until or now) + LOCK_LEASE).isoformat()}"
            if row is None:
                session.add(AppState(key=LOCK_KEY, value=value, updated_at=now))
            else:
                row.value, row.updated_at = value, now
            try:
                session.commit()
            except IntegrityError:  # another worker inserted the row first
                session.rollback()
                return False
        self.lock_holder = None
        return True

    def release_lock(self) -> None:
        with self.session_factory() as session:
            row = session.get(AppState, LOCK_KEY)
            if row is not None and (row.value or "").startswith(f"{self.lock_id}|"):
                row.value = None
                session.commit()

    async def run_forever(self, interval: float = 60) -> None:
        log.info("worker %s started; checking every %ss", self.lock_id, interval)
        waiting = False
        while not self.claim_lock():
            if not waiting:
                log.error("another worker (%s) is running against this database; "
                          "waiting until it stops", self.lock_holder)
                waiting = True
            await asyncio.sleep(interval)
        if waiting:
            log.info("the other worker stopped; taking over")
        with self.session_factory() as session:
            # we hold the lock, so a scan still marked running was cut off by a restart
            self._fail_stale_runs(session, self.clock(), everything=True)
        try:
            while True:
                try:
                    if self.claim_lock():
                        await self._tick_with_heartbeat()
                    else:
                        log.error("worker lock taken over by %s; pausing", self.lock_holder)
                except Exception:
                    log.exception("worker tick failed")
                wake_at = None
                try:
                    wake_at = self.plan_sleep(interval)
                except Exception:
                    log.warning("could not plan the next check; checking again in %ss", interval, exc_info=True)
                if wake_at is None:
                    await asyncio.sleep(interval)
                else:
                    await self._sleep_until(wake_at)
        finally:
            try:
                self.release_lock()
            except Exception:
                log.warning("could not release the worker lock", exc_info=True)

    async def _tick_with_heartbeat(self) -> None:
        """A tick, checking in on a timer meanwhile (a scan can take many minutes)."""
        self._tick_started = self.clock()
        beat = asyncio.create_task(self._heartbeat_forever())
        try:
            await self.tick()
        finally:
            beat.cancel()

    # ---- sleeping outside the awake window ----------------------------------------

    def in_awake_window(self, now: datetime) -> bool:
        if self.awake_window is None:
            return True
        start, end = self.awake_window
        local = now.astimezone(ZoneInfo(self.settings.display_tz)).time()
        return start <= local < end if start <= end else (local >= start or local < end)

    def plan_sleep(self, interval: float) -> datetime | None:
        """When to check next, if later than the usual interval: the next due job, at most
        MAX_SLEEP (or MAX_SLEEP_WITH_SIGNAL) away and never past the start of the awake window. None = the usual
        interval. Before sleeping it says so in the database, so the dashboard still shows
        the worker as running, and the lock is held until then."""
        now = self.clock()
        if self.in_awake_window(now):
            return None
        with self.session_factory() as session:
            if session.scalar(select(ScanRequest.id).where(ScanRequest.handled_at.is_(None)).limit(1)):
                return None  # requested scans waiting
            cap = MAX_SLEEP_WITH_SIGNAL if self.settings.worker_wake_url else MAX_SLEEP
            due = [now + cap, next_due_at(session, self.policy, now), self._next_window_start(now)]
            if self._last_discovery:
                due.append(self._last_discovery + self.policy.discovery_every)
            ratings = session.get(AppState, RATINGS_KEY)
            due.append(self._next_tags_at(session, now))
            if ratings is not None:
                due.append(as_utc(ratings.updated_at) + self.policy.ratings_every)
            wake_at = min(t for t in due if t is not None)
            if wake_at <= now + timedelta(seconds=interval) or not self.claim_lock(until=wake_at):
                return None
            set_state(session, HEARTBEAT_KEY, wake_at.isoformat(), now)
        log.info("nothing due; sleeping until %s (the database can suspend meanwhile)", self.fmt(wake_at))
        return wake_at

    def _next_window_start(self, now: datetime) -> datetime | None:
        if self.awake_window is None:
            return None
        tz = ZoneInfo(self.settings.display_tz)
        local = now.astimezone(tz)
        start = datetime.combine(local.date(), self.awake_window[0], tz)
        if start <= local:
            start += timedelta(days=1)
        return start.astimezone(timezone.utc)

    async def _sleep_until(self, wake_at: datetime) -> None:
        """Sleep, but wake early when the website reports a new scan request."""
        while True:
            remaining = (wake_at - self.clock()).total_seconds()
            if remaining <= 0:
                return
            await asyncio.sleep(min(WAKE_POLL_SECS, remaining))
            if await self._woken():
                log.info("woken by a scan request from the website")
                return

    async def _woken(self) -> bool:
        """Whether the website saw a scan request after our last tick began. Asks the
        website, not the database, so the database can stay suspended."""
        url = self.settings.worker_wake_url
        if not url or self._tick_started is None:
            return False

        def fetch():
            with urllib.request.urlopen(url, timeout=10) as r:
                return json.load(r)

        try:
            at = (await asyncio.to_thread(fetch)).get("at")
        except Exception as e:  # the website asleep or unreachable: sleep on
            log.debug("wake check failed: %s", e)
            return False
        # a few seconds of slack for the two machines' clocks
        return at is not None and at > self._tick_started.timestamp() - 5

    async def _heartbeat_forever(self, every: float = HEARTBEAT_EVERY_SECS) -> None:
        """Check in on a timer, so the dashboard doesn't report the worker as stopped
        while a tick spends minutes on scans, ratings or handle checks."""
        while True:
            await asyncio.sleep(every)
            try:
                if self.claim_lock():  # renews the lease
                    self.heartbeat()
            except Exception:
                log.warning("heartbeat failed", exc_info=True)

    def heartbeat(self) -> None:
        now = self.clock()
        with self.session_factory() as session:
            set_state(session, HEARTBEAT_KEY, now.isoformat(), now)

    async def tick(self) -> None:
        now = self.clock()
        with self.session_factory() as session:
            set_state(session, HEARTBEAT_KEY, now.isoformat(), now)
            self._fail_stale_runs(session, now)
            drafts.expire(session, now)  # unreviewed for a week
            async with self.client_factory() as client:
                await self._maybe_discover(session, client, now)
                # Requests made while a scan runs go next, ahead of further automatic
                # scans (the order the dashboard's "ready by" estimates assume).
                while True:
                    await self._run_requested(session, client)
                    jobs = due_scans(session, self.policy, self.clock())
                    if not jobs:
                        break
                    await self._run_scan(session, client, jobs[0])
                # lowest priority: only once nothing else is waiting
                await self._maybe_refresh_tags(session, client, self.clock())
                await self._maybe_sync_ratings(session, client, self.clock())

    # ---- steps ------------------------------------------------------------------

    def _fail_stale_runs(self, session: Session, now: datetime, *, everything: bool = False) -> None:
        cutoff = now - self.policy.stale_run_after
        stale = [r for r in session.scalars(select(ScanRun).where(ScanRun.status == "running"))
                 if everything or as_utc(r.started_at) < cutoff]
        for r in stale:
            log.warning("scan run #%d for %s was interrupted; marking failed", r.id, r.contest_slug)
            session.execute(update(ScanRun).where(ScanRun.id == r.id).values(
                status="failed", error="interrupted (worker stopped during the scan)",
                finished_at=now))
        if stale:
            session.commit()

    async def _maybe_discover(self, session: Session, client, now: datetime) -> None:
        if self._last_discovery and now - self._last_discovery < self.policy.discovery_every:
            return
        try:
            new = await discover_contests(session, client)
            await sync_past_contests(session, client)
        except LeetCodeError as e:
            session.rollback()
            log.warning("contest discovery failed: %s", e)
            return
        self._last_discovery = now
        for slug in new:
            c = session.get(Contest, slug)
            start = datetime.fromtimestamp(c.start_time, timezone.utc)
            end = start + timedelta(seconds=c.duration)
            if end > now:
                self.notifier.send(
                    f"Scheduled {c.title}: starts {self.fmt(start)}, "
                    f"results scan at {self.fmt(end + self.policy.scan_delay)}."
                )

    async def _prepare_scan(self, session: Session, client) -> None:
        try:
            await validate_handles(session, client)
        except LeetCodeError as e:
            session.rollback()
            log.warning("handle validation skipped: %s", e)

    async def _scan(self, session: Session, client, slug: str, kind: str, *, draft: bool = False) -> ScanRun:
        try:
            return await scan_and_store(session, client, slug, kind=kind,
                                        final=self.policy.final or DEFAULT_FINAL,
                                        now=self.clock().timestamp(), draft=draft)
        except Exception as e:  # recorded as a failed / cancelled scan run by scan_and_store
            if not isinstance(e, (ScanIncompleteError, ScanCancelledError, LeetCodeError)):
                log.exception("unexpected error scanning %s", slug)
            raise

    async def _run_scan(self, session: Session, client, job: DueScan) -> None:
        contest = session.get(Contest, job.slug)
        log.info("scanning %s (%s, attempt %d/%d)", job.slug, job.kind, job.attempt, job.max_attempts)
        await self._prepare_scan(session, client)
        try:
            await self._scan(session, client, job.slug, job.kind)
        except ScanCancelledError:
            self.notifier.send(f"Scan of {contest.title} was cancelled from the dashboard.")
            return
        except Exception as e:
            self._report_failure(contest, job, e)
            return
        self._report_success(session, job.slug, job.kind)
        await self._refresh_contest_tags(session, client, job.slug)
        if job.kind == "final":
            await self._sync_ratings(session, client)

    async def _run_requested(self, session: Session, client) -> None:
        """Scans requested from the dashboard (admin "Rescan" / backfill), oldest first.
        The queue is re-read before each one, so requests cancelled meanwhile are skipped."""
        while True:
            session.expire_all()  # see cancellations made by the API since the last read
            req = session.scalars(
                select(ScanRequest).where(ScanRequest.handled_at.is_(None)).order_by(ScanRequest.id).limit(1)
            ).first()
            if req is None:
                return
            log.info("requested scan of %s (%s) by %s", req.contest_slug, req.kind, req.requested_by)
            await self._prepare_scan(session, client)
            try:
                # manual scans wait for an admin's review (services/drafts.py)
                run = await self._scan(session, client, req.contest_slug, req.kind,
                                       draft=self.settings.scan_review_enabled)
            except Exception as e:
                req.error = "cancelled from the dashboard" if isinstance(e, ScanCancelledError) else str(e)[:2000]
                req.scan_run_id = session.scalar(
                    select(ScanRun.id).where(ScanRun.contest_slug == req.contest_slug)
                    .order_by(ScanRun.id.desc()).limit(1))
                req.handled_at = self.clock()
                session.commit()
                if not isinstance(e, ScanCancelledError):
                    self.notifier.send(f"Requested scan of {req.contest_slug} failed: {e}")
                continue
            req.scan_run_id = run.id
            req.handled_at = self.clock()
            session.commit()
            await self._refresh_contest_tags(session, client, req.contest_slug)
            if run.status == "review":
                self._report_draft(session, run, requested_by=req.requested_by)
                continue
            self._report_success(session, req.contest_slug, run.kind, requested_by=req.requested_by)
            if run.kind == "final":
                await self._sync_ratings(session, client)

    # ---- topic tags (services/tags.py) ------------------------------------------------

    def _tags_times(self, now: datetime) -> tuple[datetime, datetime]:
        """The latest nightly (00:00) and monthly (the 1st, 00:30) refresh times, local time."""
        tz = ZoneInfo(self.settings.display_tz)
        local = now.astimezone(tz)
        nightly = datetime.combine(local.date(), time(0, 0), tz)
        monthly = datetime.combine(local.date().replace(day=1), time(0, 30), tz)
        if monthly > local:  # before 00:30 on the 1st: last month's
            prev = (local.date().replace(day=1) - timedelta(days=1)).replace(day=1)
            monthly = datetime.combine(prev, time(0, 30), tz)
        return nightly.astimezone(timezone.utc), monthly.astimezone(timezone.utc)

    def _ran_since(self, session: Session, key: str, since: datetime) -> bool:
        row = session.get(AppState, key)
        return row is not None and as_utc(row.updated_at) >= since

    def _next_tags_at(self, session: Session, now: datetime) -> datetime:
        """When the next tag refresh is due (for planning a sleep): now if one was missed."""
        nightly, _ = self._tags_times(now)
        if not self._ran_since(session, tags.NIGHTLY_KEY, nightly):
            return now
        return nightly + timedelta(days=1)

    async def _maybe_refresh_tags(self, session: Session, client, now: datetime) -> None:
        """Nightly: the last 45 days' questions (community topics while there are no
        official tags). Monthly: official tags for every stored question. Also when an
        admin asks. A worker that was off catches up when it starts."""
        nightly, monthly = self._tags_times(now)
        requested = session.get(AppState, tags.REQUEST_KEY)
        try:
            if requested is not None and requested.value:
                log.info("tag refresh requested by %s", requested.value)
                await tags.refresh(session, client, tags.recent_questions(session, now), now=now)
                set_state(session, tags.REQUEST_KEY, "", now)
                set_state(session, tags.NIGHTLY_KEY, now.isoformat(), now)
            elif not self._ran_since(session, tags.NIGHTLY_KEY, nightly):
                await tags.refresh(session, client, tags.recent_questions(session, now), now=now)
                set_state(session, tags.NIGHTLY_KEY, now.isoformat(), now)
            if not self._ran_since(session, tags.MONTHLY_KEY, monthly):
                await tags.refresh(session, client, tags.all_questions(session), official_only=True, now=now)
                set_state(session, tags.MONTHLY_KEY, now.isoformat(), now)
        except Exception:
            session.rollback()
            log.exception("tag refresh failed")

    async def _refresh_contest_tags(self, session: Session, client, slug: str) -> None:
        """Right after a scan: that contest's questions."""
        contest = session.get(Contest, slug)
        if contest is None:
            return
        try:
            await tags.refresh(session, client, tags.contest_questions([contest]), now=self.clock())
        except Exception:
            session.rollback()
            log.exception("tag refresh for %s failed", slug)

    async def _maybe_sync_ratings(self, session: Session, client, now: datetime) -> None:
        """Everyone's LeetCode rating, once a day."""
        last = session.get(AppState, RATINGS_KEY)
        if last is not None and now - as_utc(last.updated_at) < self.policy.ratings_every:
            return
        await self._sync_ratings(session, client)

    async def _sync_ratings(self, session: Session, client) -> None:
        """LeetCode updates ratings a few days after a contest, so this runs after final
        scans, and daily (_maybe_sync_ratings)."""
        try:
            summary = await sync_ratings(session, client)
        except Exception:
            session.rollback()
            log.exception("rating sync failed")
            return
        now = self.clock()
        set_state(session, RATINGS_KEY, now.isoformat(), now)
        if summary.errors:
            self.notifier.send(f"Rating sync: {summary.checked} students updated, {summary.errors} failed.")

    def _report_success(self, session: Session, slug: str, kind: str,
                        requested_by: str | None = None) -> None:
        contest = session.get(Contest, slug)
        stored = load_contest_results(session, slug)
        s = summarize(stored.results)
        participated = s.get("solved", 0) + s.get("zero", 0)
        label = "Final results" if kind == "final" else "Results"
        by = f" (requested by {requested_by})" if requested_by else ""
        self.notifier.send(
            f"{label} for {contest.title}{by}: {participated}/{s['students']} students participated, "
            f"{s.get('solved', 0)} solved at least one problem "
            f"({contest.user_num} participants worldwide)."
        )

    def _report_draft(self, session: Session, run: ScanRun, requested_by: str | None) -> None:
        review = drafts.pending_for(session, run.contest_slug) or {}
        label = "Final results" if run.kind == "final" else "Results"
        self.notifier.send(
            f"{label} for {review.get('title') or run.contest_slug} (requested by {requested_by}) are ready for "
            f"review: {review.get('participated', 0)}/{review.get('students', 0)} students took part. "
            f"Nothing changes on the dashboard until an admin adds them on the contest page."
        )

    def _report_failure(self, contest: Contest, job: DueScan, error: Exception) -> None:
        blocked = isinstance(error, LeetCodeBlockedError) or getattr(error, "blocked", False)
        end = datetime.fromtimestamp(contest.start_time + contest.duration, timezone.utc)
        retry = next_retry_at(end, self.policy, job.kind, job.attempt)
        msg = f"Scan of {contest.title} ({job.kind}) failed, attempt {job.attempt}/{job.max_attempts}: {error}"
        if blocked:
            msg = "Blocked by Cloudflare. " + msg + " Consider setting PROXY_URL."
        msg += f" Next try {self.fmt(retry)}." if retry else " Giving up; run the scan manually."
        self.notifier.send(msg)

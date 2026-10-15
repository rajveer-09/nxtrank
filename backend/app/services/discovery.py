# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Find upcoming (and recently missed) contests and record them in the `contests` table."""

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Contest
from app.leetcode.client import ContestNotFoundError
from app.leetcode.schemas import Contest as ContestSchema
from app.services.scans import contest_type

log = logging.getLogger(__name__)

_NUMBERED = re.compile(r"^(weekly|biweekly)-contest-(\d+)$")

# How many consecutive contest numbers to probe past the newest known one per type.
# Covers contests that started and ended while the worker was down.
PROBE_AHEAD = 3
# Don't fill gaps further back than this many contest numbers.
MAX_GAP = 4


def upsert_contest(session: Session, c: ContestSchema) -> bool:
    """Insert or refresh schedule fields. Returns True if the contest is new."""
    row = session.get(Contest, c.title_slug)
    is_new = row is None
    if is_new:
        row = Contest(slug=c.title_slug, questions=[])
        session.add(row)
    row.title = c.title
    row.contest_type = contest_type(c.title_slug)
    row.start_time = c.start_time
    row.duration = c.duration
    return is_new


def _newest_numbers(session: Session) -> dict[str, int]:
    newest: dict[str, int] = {}
    for slug in session.scalars(select(Contest.slug)):
        m = _NUMBERED.match(slug)
        if m:
            newest[m.group(1)] = max(newest.get(m.group(1), 0), int(m.group(2)))
    return newest


async def discover_contests(session: Session, client) -> list[str]:
    """Record upcoming contests, fill numbering gaps since the newest contest known
    before this run (contests missed while the worker was down), and probe a few
    numbers ahead. Returns the slugs that were new. Commits."""
    known_before = _newest_numbers(session)
    new: list[str] = []
    for c in await client.upcoming_contests():
        if upsert_contest(session, c):
            new.append(c.title_slug)
    session.flush()
    known_now = _newest_numbers(session)

    for kind, newest in known_now.items():
        start = max(known_before.get(kind, newest), newest - MAX_GAP) + 1
        for n in range(start, newest + 1 + PROBE_AHEAD):
            slug = f"{kind}-contest-{n}"
            if session.get(Contest, slug) is not None:
                continue
            try:
                info = await client.contest_info(slug)
            except ContestNotFoundError:
                if n > newest:
                    break  # nothing scheduled further ahead
                continue
            if upsert_contest(session, info.contest):
                new.append(slug)

    session.commit()
    if new:
        log.info("discovered contests: %s", ", ".join(new))
    return new


async def sync_past_contests(session: Session, client, *, full: bool = False) -> list[str]:
    """Record LeetCode's finished contests (newest first, 10 per page). Stops at the
    first page with nothing new unless `full`; the first run fetches all ~70 pages.
    Returns the slugs that were new. Commits per page."""
    new: list[str] = []
    page = 1
    while True:
        contests, pages = await client.past_contests(page)
        added = [c.title_slug for c in contests if upsert_contest(session, c)]
        session.commit()
        new += added
        if page >= pages or (not added and not full):
            break
        page += 1
    if new:
        log.info("added %d past contests", len(new))
    return new

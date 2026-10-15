# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Full leaderboard scan with an all-pages-or-fail guarantee.

A missing page would silently turn up to 25 participants into "absent", so the
scan raises ScanIncompleteError unless every page was fetched and validated.
"""

import asyncio
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from app.leetcode.client import LeetCodeBlockedError, LeetCodeError
from app.leetcode.links import PAGE_SIZE
from app.leetcode.schemas import ContestInfo, Question, RankingPage, RankRow, Submission

log = logging.getLogger(__name__)


class ContestNotFinishedError(Exception):
    pass


class ScanCancelledError(Exception):
    """The scan was cancelled from the dashboard; nothing was stored."""


class ScanIncompleteError(Exception):
    def __init__(self, failed_pages: dict[int, str], total_pages: int, blocked: bool):
        self.failed_pages = failed_pages
        self.total_pages = total_pages
        self.blocked = blocked
        first = sorted(failed_pages.items())[:5]
        detail = "; ".join(f"page {p}: {err}" for p, err in first)
        reason = "blocked by Cloudflare" if blocked else "pages failed"
        super().__init__(
            f"Scan incomplete ({reason}): {len(failed_pages)}/{total_pages} pages "
            f"missing. {detail}"
        )


@dataclass(frozen=True)
class ScanResult:
    info: ContestInfo
    questions: list[Question]  # from the ranking endpoint, ordered Q1..Qn
    user_num: int
    pages: int
    rows: list[tuple[RankRow, dict[str, Submission]]]  # in rank order, deduped


async def scan_contest(
    client,
    slug: str,
    *,
    concurrency: int = 4,
    allow_unfinished: bool = False,
    now: float | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ScanResult:
    """`on_progress(pages_done, pages_total)` is called after every page; when
    `should_cancel()` turns true the remaining pages are skipped and
    ScanCancelledError is raised."""
    info = await client.contest_info(slug)
    now = time.time() if now is None else now
    if not allow_unfinished and now < info.contest.end_time:
        raise ContestNotFinishedError(
            f"{slug} ends at unix {info.contest.end_time}; "
            f"{int(info.contest.end_time - now)}s from now"
        )

    first = await client.ranking_page(slug, 1)
    total_pages = max(1, math.ceil(first.user_num / PAGE_SIZE))
    log.info("%s: %d participants, %d pages", slug, first.user_num, total_pages)
    if on_progress:
        on_progress(1, total_pages)

    pages: dict[int, RankingPage] = {1: first}
    failed: dict[int, str] = {}
    blocked = asyncio.Event()
    cancelled = asyncio.Event()
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def fetch(page: int) -> None:
        nonlocal done
        async with sem:
            if cancelled.is_set() or (should_cancel and should_cancel()):
                cancelled.set()
                return
            if blocked.is_set():
                failed[page] = "skipped after Cloudflare block"
                return
            try:
                pages[page] = await client.ranking_page(slug, page)
            except LeetCodeBlockedError as e:
                blocked.set()
                failed[page] = str(e)
            except (LeetCodeError, ValidationError) as e:
                failed[page] = str(e)
            done += 1
            if done % 100 == 0:
                log.info("%s: fetched %d/%d pages", slug, done + 1, total_pages)
            if on_progress:
                on_progress(done + 1, total_pages)

    await asyncio.gather(*(fetch(p) for p in range(2, total_pages + 1)))
    # also checked after the last page: a stop can arrive with the final progress update
    if cancelled.is_set() or (should_cancel and should_cancel()):
        raise ScanCancelledError(f"{slug}: scan cancelled")

    for page, data in pages.items():
        is_last = page == total_pages
        if not is_last and len(data.total_rank) != PAGE_SIZE:
            failed[page] = f"expected {PAGE_SIZE} rows, got {len(data.total_rank)}"
        elif is_last and not data.total_rank:
            failed[page] = "last page is empty"

    if failed:
        raise ScanIncompleteError(failed, total_pages, blocked.is_set())

    rows: list[tuple[RankRow, dict[str, Submission]]] = []
    seen: set[str] = set()
    for page in range(1, total_pages + 1):
        for row, subs in zip(pages[page].total_rank, pages[page].submissions):
            key = f"{row.data_region}:{row.user_slug.lower()}"  # a .cn user may share a .com handle
            if key in seen:  # leaderboard shifted between page fetches
                continue
            seen.add(key)
            rows.append((row, subs))

    if len(rows) != first.user_num:
        log.warning("%s: got %d unique rows, user_num says %d", slug, len(rows), first.user_num)

    return ScanResult(
        info=info,
        questions=first.questions,
        user_num=first.user_num,
        pages=total_pages,
        rows=rows,
    )

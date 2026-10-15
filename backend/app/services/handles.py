# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Check that students' LeetCode handles exist (GraphQL matchedUser)."""

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Student, utcnow
from app.leetcode.client import LeetCodeBlockedError, LeetCodeError

log = logging.getLogger(__name__)


@dataclass
class ValidationSummary:
    checked: int = 0
    valid: int = 0
    invalid: int = 0
    errors: int = 0


async def validate_handles(
    session: Session, client, *, recheck_all: bool = False, concurrency: int = 4,
    commit_every: int = 50,
) -> ValidationSummary:
    """Validate active students' handles. By default only `unchecked` ones (new or
    changed since the last check). Commits progress in batches."""
    query = select(Student).where(Student.active.is_(True), Student.lc_slug.is_not(None))
    if not recheck_all:
        query = query.where(Student.handle_status == "unchecked")
    students = session.scalars(query.order_by(Student.id)).all()
    summary = ValidationSummary()
    if not students:
        return summary
    log.info("validating %d handles", len(students))

    sem = asyncio.Semaphore(concurrency)
    blocked = asyncio.Event()

    async def check(st: Student) -> None:
        async with sem:
            if blocked.is_set():
                return
            try:
                username = await client.matched_user(st.lc_slug)
            except LeetCodeBlockedError as e:
                blocked.set()
                log.error("blocked by Cloudflare, stopping: %s", e)
                summary.errors += 1
                return
            except LeetCodeError as e:
                log.warning("could not check %s: %s", st.lc_slug, e)
                summary.errors += 1
                return
            st.handle_status = "valid" if username else "invalid"
            st.lc_username = username
            st.handle_checked_at = utcnow()
            summary.checked += 1
            if username:
                summary.valid += 1
            else:
                summary.invalid += 1
            if summary.checked % commit_every == 0:
                session.commit()
                log.info("checked %d/%d handles", summary.checked, len(students))

    await asyncio.gather(*(check(st) for st in students))
    session.commit()
    log.info(
        "handles: %d checked (%d valid, %d invalid), %d errors",
        summary.checked, summary.valid, summary.invalid, summary.errors,
    )
    return summary

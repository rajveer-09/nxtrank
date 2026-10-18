# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""Topic tags for contest questions.

LeetCode publishes official topic tags 1-4 weeks after a contest. Until then, the
topics that community solutions use stand in as **provisional** tags. Each question
uses exactly one source at a time, official first, so a question never counts twice:

| state        | tags used                                   |
|--------------|---------------------------------------------|
| official     | LeetCode's official tags                    |
| provisional  | community topics that pass PROVISIONAL rule |
| insufficient | none: too little community data yet         |
| pending      | none: not checked yet                       |

Raw tags are stored per source (question_tag_sources); the effective ones
(question_tags) are derived here and rewritten only when they change, which bumps
data_version once, so caches and ETags refresh and nothing else is written."""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import AppState, Contest, LeetCodeTopic, QuestionTag, QuestionTagSource, QuestionTagStatus, utcnow
from app.leetcode.client import LeetCodeError

log = logging.getLogger(__name__)

# ---- the provisional rule (also shown in the rule book) ------------------------------
MIN_MENTIONS = 2  # a topic needs at least this many community solutions...
TOP_SHARE = 0.30  # ...and at least this share of the most-used topic's count
MAX_TAGS = 4  # at most this many provisional tags per question
MIN_TOP = 3  # not enough data: the most-used topic has fewer mentions than this
MIN_TOTAL = 5  # not enough data: fewer topic mentions than this in total

RECENT = timedelta(days=45)  # the nightly refresh covers questions from contests this recent
LAST_RUN_KEY = "tags_last_run"  # app_state: JSON summary of the last refresh
NIGHTLY_KEY = "tags_nightly_at"
MONTHLY_KEY = "tags_monthly_at"
REQUEST_KEY = "tags_refresh_requested"  # set from the dashboard, picked up by the worker



def _slugify(name: str) -> str:
    return "-".join("".join(ch if ch.isalnum() else " " for ch in name.lower()).split())


def provisional_tags(community: list[tuple[str, str, int]], allowed: set[str]) -> list[tuple[str, str]] | None:
    """The provisional tags from community topic counts, or None if there's too little
    data. Keeps LeetCode topics only, with count >= max(MIN_MENTIONS, TOP_SHARE x top),
    at most MAX_TAGS, most-used first."""
    total = sum(n for _, _, n in community)
    topics: dict[str, tuple[str, int]] = {}
    for slug, name, n in community:
        key = slug if slug in allowed else _slugify(name)
        if key in allowed and n > topics.get(key, ("", -1))[1]:
            topics[key] = (name, n)
    top = max((n for _, n in topics.values()), default=0)
    if top < MIN_TOP or total < MIN_TOTAL:
        return None
    floor = max(MIN_MENTIONS, TOP_SHARE * top)
    kept = sorted(((n, key, name) for key, (name, n) in topics.items() if n >= floor), key=lambda t: (-t[0], t[1]))
    return [(key, name) for _, key, name in kept[:MAX_TAGS]]


def _hash(state: str, tags: list[tuple[str, str]], source: str | None) -> str:
    return hashlib.sha1(json.dumps([state, source, sorted(tags)]).encode()).hexdigest()


@dataclass
class RefreshSummary:
    checked: int = 0
    became_official: int = 0
    provisional_updated: int = 0
    insufficient: int = 0
    failed: int = 0
    changed: list[str] = field(default_factory=list)

    def line(self) -> str:
        return (f"tags: {self.checked} checked · {self.became_official} became official · "
                f"{self.provisional_updated} provisional updated · {self.insufficient} insufficient · "
                f"{self.failed} failed")


def allowed_topics(session: Session) -> set[str]:
    """LeetCode's topics (the leetcode_topics table) plus every official tag stored.
    Community topics outside them ("Brute-Force Search", "Prime Number Sieve", ...) aren't
    LeetCode topics and are dropped."""
    seen = session.scalars(select(QuestionTagSource.tag_slug).where(QuestionTagSource.source == "official").distinct())
    return set(session.scalars(select(LeetCodeTopic.slug))) | set(seen)


def _replace_source(session: Session, slug: str, source: str, rows: list[tuple], now: datetime) -> None:
    session.execute(delete(QuestionTagSource).where(
        QuestionTagSource.question_slug == slug, QuestionTagSource.source == source))
    for row in rows:
        tag_slug, name, *n = row
        session.add(QuestionTagSource(question_slug=slug, source=source, tag_slug=tag_slug, tag_name=name,
                                      mentions=n[0] if n else None, fetched_at=now))


def _derive(session: Session, slug: str, status: QuestionTagStatus, allowed: set[str]):
    """(state, effective tags, their source) from the stored raw rows."""
    raw = session.scalars(select(QuestionTagSource).where(QuestionTagSource.question_slug == slug)).all()
    official = [(r.tag_slug, r.tag_name) for r in raw if r.source == "official"]
    if official:
        return "official", official, "official"
    if status.community_fetched_at is None:
        return "pending", [], None
    community = [(r.tag_slug, r.tag_name, r.mentions or 0) for r in raw if r.source == "community"]
    tags = provisional_tags(community, allowed)
    return ("provisional", tags, "community") if tags else ("insufficient", [], None)


async def refresh(session: Session, client, slugs: list[str], *, official_only: bool = False,
                  now: datetime | None = None) -> RefreshSummary:
    """Fetch tags for these questions and update the effective tags where they changed.
    Community topics are asked for only while a question has no official tags. A
    LeetCode error leaves that question's stored tags as they were. Commits."""
    now = now or utcnow()
    summary = RefreshSummary()
    allowed = allowed_topics(session)
    for slug in dict.fromkeys(slugs):
        status = session.get(QuestionTagStatus, slug) or QuestionTagStatus(question_slug=slug, state="pending")
        session.add(status)
        try:
            official = await client.question_tags(slug)
        except LeetCodeError as e:
            log.warning("official tags for %s failed: %s", slug, e)
            summary.failed += 1
            continue
        summary.checked += 1
        _replace_source(session, slug, "official", official, now)
        status.official_fetched_at, status.official_found = now, bool(official)
        allowed |= {t for t, _ in official}
        if not official and not official_only:
            try:
                community = await client.community_topics(slug)
            except LeetCodeError as e:
                log.warning("community topics for %s failed: %s", slug, e)
                summary.failed += 1
            else:
                _replace_source(session, slug, "community", community, now)
                status.community_fetched_at = now
                status.community_mentions = sum(n for _, _, n in community)

        session.flush()
        state, tags, source = _derive(session, slug, status, allowed)
        if state == "insufficient":
            summary.insufficient += 1
        digest = _hash(state, tags, source)
        if digest == status.effective_hash:
            continue  # nothing to rewrite
        if state == "official" and status.state != "official":
            summary.became_official += 1
        elif state == "provisional":
            summary.provisional_updated += 1
        session.execute(delete(QuestionTag).where(QuestionTag.question_slug == slug))
        for tag_slug, name in tags:
            session.add(QuestionTag(question_slug=slug, tag_slug=tag_slug, tag_name=name, source=source))
        status.state, status.effective_hash, status.state_changed_at = state, digest, now
        summary.changed.append(slug)

    state = session.get(AppState, LAST_RUN_KEY) or AppState(key=LAST_RUN_KEY)
    state.value = json.dumps({"at": now.isoformat(), "line": summary.line(), "checked": summary.checked,
                              "failed": summary.failed, "changed": len(summary.changed)})
    state.updated_at = now
    session.add(state)
    session.commit()  # question_tags changes bump data_version (summaries.VERSION_TABLES)
    log.info(summary.line())
    return summary


# ---- which questions -----------------------------------------------------------------

def contest_questions(contests) -> list[str]:
    return [q["title_slug"] for c in contests for q in (c.questions or []) if q.get("title_slug")]


def recent_questions(session: Session, now: datetime) -> list[str]:
    since = int((now - RECENT).timestamp())
    return contest_questions(session.scalars(select(Contest).where(Contest.start_time >= since)))


def all_questions(session: Session) -> list[str]:
    return contest_questions(session.scalars(select(Contest)))


def status_json(session: Session) -> dict:
    """For Admin → Topics and the coverage notes: the last run, and each question's state."""
    last = session.get(AppState, LAST_RUN_KEY)
    statuses = {s.question_slug: s for s in session.scalars(select(QuestionTagStatus))}
    tags: dict[str, list[dict]] = {}
    for t in session.scalars(select(QuestionTag).order_by(QuestionTag.question_slug, QuestionTag.tag_name)):
        tags.setdefault(t.question_slug, []).append({"slug": t.tag_slug, "name": t.tag_name, "source": t.source})
    questions, counts = [], {"official": 0, "provisional": 0, "insufficient": 0, "pending": 0}
    for c in session.scalars(select(Contest).order_by(Contest.start_time.desc())):
        for q in c.questions or []:
            slug = q.get("title_slug")
            if not slug:
                continue
            st = statuses.get(slug)
            state = st.state if st else "pending"
            counts[state] += 1
            questions.append({"contest": c.slug, "contest_title": c.title, "label": q["label"], "slug": slug,
                              "title": q.get("title"), "state": state, "tags": tags.get(slug, []),
                              "mentions": st.community_mentions if st else None,
                              "fetched_at": (st.official_fetched_at.isoformat() if st and st.official_fetched_at else None)})
    requested = session.get(AppState, REQUEST_KEY)
    return {"last_run": json.loads(last.value) if last and last.value else None, "counts": counts,
            "refresh_requested": bool(requested and requested.value), "questions": questions}

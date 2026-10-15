# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""HTTP client for LeetCode's contest endpoints.

Uses curl_cffi with Chrome TLS impersonation: plain requests/httpx/curl get a
Cloudflare challenge page (HTTP 403) on these endpoints.
"""

import asyncio
import logging
import random
import time

from curl_cffi.requests import AsyncSession, RequestsError

from app.leetcode.links import RANKING_REGION
from app.leetcode.schemas import Contest, ContestInfo, RankingPage

log = logging.getLogger(__name__)

BASE_URL = "https://leetcode.com"


class LeetCodeError(Exception):
    """A request failed permanently (after retries, or a non-retryable status)."""


class LeetCodeBlockedError(LeetCodeError):
    """Cloudflare kept serving a challenge page; retrying won't help soon."""


class ContestNotFoundError(LeetCodeError):
    pass


class RateLimiter:
    """Spaces request starts at least 1/rps seconds apart, across all tasks."""

    def __init__(self, rps: float):
        self._interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self._interval
        if delay > 0:
            await asyncio.sleep(delay)


def _is_json(resp) -> bool:
    return "json" in (resp.headers.get("content-type") or "")


def _is_challenge(resp) -> bool:
    text = resp.text[:2000] if resp.text else ""
    return "challenges.cloudflare.com" in text or "Just a moment..." in text


class LeetCodeClient:
    """Async client; use as `async with LeetCodeClient(...) as client:`."""

    def __init__(
        self,
        *,
        proxy: str | None = None,
        rps: float = 3.0,
        max_retries: int = 5,
        timeout: float = 30.0,
        backoff_base: float = 1.0,
        session=None,
    ):
        self.proxy = proxy
        self.max_retries = max_retries
        self.timeout = timeout
        self.backoff_base = backoff_base
        self._limiter = RateLimiter(rps)
        self._session = session
        self._owns_session = session is None
        self._questions: dict[str, list] = {}  # contest slug -> question list
        self._questions_lock = asyncio.Lock()

    async def __aenter__(self) -> "LeetCodeClient":
        if self._session is None:
            self._session = AsyncSession(impersonate="chrome")
        return self

    async def __aexit__(self, *exc) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def get_json(self, path: str, params: dict | None = None) -> dict:
        return await self._request("GET", path, params=params)

    async def post_json(self, path: str, body: dict) -> dict:
        return await self._request("POST", path, json=body, headers={"Referer": BASE_URL + "/"})

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        url = BASE_URL + path
        send = getattr(self._session, method.lower())
        last_error = ""
        blocked = False
        for attempt in range(1, self.max_retries + 1):
            await self._limiter.wait()
            try:
                resp = await send(url, proxy=self.proxy, timeout=self.timeout, **kwargs)
            except RequestsError as e:
                last_error = f"network error: {e}"
            else:
                if resp.status_code == 200 and _is_json(resp):
                    try:
                        return resp.json()
                    except ValueError:
                        last_error = "invalid JSON body"
                elif resp.status_code == 404:
                    raise LeetCodeError(f"{method} {url} -> 404 Not Found")
                elif _is_challenge(resp):
                    blocked = True
                    last_error = f"Cloudflare challenge (HTTP {resp.status_code})"
                else:
                    last_error = f"HTTP {resp.status_code}"

            if attempt < self.max_retries:
                delay = self.backoff_base * 2 ** (attempt - 1)
                delay += random.uniform(0, self.backoff_base)
                log.warning(
                    "%s %s failed (%s), attempt %d/%d, retrying in %.1fs",
                    method, url, last_error, attempt, self.max_retries, delay,
                )
                await asyncio.sleep(delay)

        error_cls = LeetCodeBlockedError if blocked else LeetCodeError
        raise error_cls(f"{method} {url} failed after {self.max_retries} attempts: {last_error}")

    async def contest_info(self, slug: str) -> ContestInfo:
        data = await self.get_json(f"/contest/api/info/{slug}/")
        if "contest" not in data and "error" in data:  # unknown slug: 200 + {"error": ...}
            raise ContestNotFoundError(f"{slug}: {data['error']}")
        return ContestInfo.model_validate(data)

    async def upcoming_contests(self) -> list[Contest]:
        """Next weekly and biweekly contests. Both GraphQL fields are queried because
        `upcomingContests` has been seen to omit the biweekly contest."""
        data = await self.post_json("/graphql/", {"query": _UPCOMING})
        found: dict[str, Contest] = {}
        for field in ("topTwoContests", "upcomingContests"):
            for c in (data.get("data") or {}).get(field) or []:
                found[c["titleSlug"]] = Contest(
                    id=0, title=c["title"], title_slug=c["titleSlug"],
                    start_time=c["startTime"], duration=c["duration"],
                )
        if not found and data.get("errors"):
            raise LeetCodeError(f"upcoming contests query failed: {str(data['errors'])[:300]}")
        return sorted(found.values(), key=lambda c: c.start_time)

    async def ranking_page(self, slug: str, page: int) -> RankingPage:
        """One page of the leaderboard exactly as leetcode.com shows it ("global_v2":
        leetcode.com and leetcode.cn users together, ranked from 0). The older "global"
        list leaves leetcode.cn users out for some contests, so its pages and ranks
        don't line up with the website."""
        data = await self.get_json(
            f"/contest/api/ranking/{slug}/",
            params={"pagination": str(page), "region": RANKING_REGION},
        )
        if "submissions" not in data:  # global_v2 nests submissions in each row, without the question list
            data = {
                **data,
                "questions": await self._contest_questions(slug),
                "submissions": [
                    {qid: {**sub, "question_id": int(qid)} for qid, sub in (row.get("submissions") or {}).items()}
                    for row in data.get("total_rank") or []
                ],
            }
        return RankingPage.model_validate(data)

    async def _contest_questions(self, slug: str) -> list:
        """Questions in Q1..Qn order, from the older leaderboard endpoint (fetched once)."""
        async with self._questions_lock:
            if slug not in self._questions:
                data = await self.get_json(f"/contest/api/ranking/{slug}/", params={"pagination": "1", "region": "global"})
                self._questions[slug] = data["questions"]
            return self._questions[slug]

    async def past_contests(self, page: int) -> tuple[list[Contest], int]:
        """One page of finished contests, newest first (LeetCode serves 10 per page).
        Returns (contests, number of pages)."""
        data = await self.post_json("/graphql/", {"query": _PAST, "variables": {"p": page}})
        pc = (data.get("data") or {}).get("pastContests")
        if not pc:
            raise LeetCodeError(f"pastContests page {page}: {str(data)[:300]}")
        contests = [
            Contest(id=0, title=c["title"], title_slug=c["titleSlug"],
                    start_time=c["startTime"], duration=c["duration"])
            for c in pc["data"]
        ]
        return contests, pc["pageNum"]

    async def matched_user(self, handle: str) -> str | None:
        """Canonical username for `handle` (lookup is case-insensitive), or None if
        no such LeetCode user exists."""
        data = await self.post_json("/graphql/", {"query": _MATCHED_USER, "variables": {"u": handle}})
        user = (data.get("data") or {}).get("matchedUser")
        if user:
            return user["username"]
        messages = [e.get("message", "") for e in data.get("errors") or []]
        if "data" in data and all("does not exist" in m for m in messages):
            return None
        raise LeetCodeError(f"matchedUser({handle!r}) unexpected response: {str(data)[:300]}")

    async def contest_ranking(self, handle: str) -> tuple[dict | None, list[dict]]:
        """(current ranking, attended-contest history) for a user. The ranking is None
        for users who never took a rated contest (or don't exist)."""
        data = await self.post_json(
            "/graphql/", {"query": _CONTEST_RANKING, "variables": {"u": handle}}
        )
        if "data" not in data:
            raise LeetCodeError(f"contest ranking for {handle!r}: {str(data)[:300]}")
        d = data["data"] or {}
        history = [h for h in d.get("userContestRankingHistory") or [] if h.get("attended")]
        return d.get("userContestRanking"), history


_MATCHED_USER = "query q($u: String!) { matchedUser(username: $u) { username } }"
_CONTEST_RANKING = """query q($u: String!) {
  userContestRanking(username: $u) { attendedContestsCount rating globalRanking topPercentage }
  userContestRankingHistory(username: $u) {
    attended rating ranking problemsSolved totalProblems contest { title startTime }
  }
}"""
_PAST = """query q($p: Int!) {
  pastContests(pageNo: $p) { pageNum data { title titleSlug startTime duration } }
}"""
_UPCOMING = """{
  topTwoContests { title titleSlug startTime duration }
  upcomingContests { title titleSlug startTime duration }
}"""

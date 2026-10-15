# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
import asyncio

import pytest

from app.leetcode.client import LeetCodeBlockedError, LeetCodeClient, LeetCodeError

CHALLENGE = "<!DOCTYPE html><title>Just a moment...</title> https://challenges.cloudflare.com"


class Resp:
    def __init__(self, status, body, content_type="application/json"):
        self.status_code = status
        self.text = body if isinstance(body, str) else ""
        self._body = body
        self.headers = {"content-type": content_type}

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def get(self, url, **kw):
        self.calls += 1
        return self.responses.pop(0)


def get(session, max_retries=3):
    async def go():
        async with LeetCodeClient(session=session, rps=0, backoff_base=0,
                                  max_retries=max_retries) as c:
            return await c.get_json("/x")
    return asyncio.run(go())


def test_retries_then_succeeds():
    session = FakeSession([
        Resp(403, CHALLENGE, "text/html"),
        Resp(502, "bad gateway", "text/html"),
        Resp(200, {"ok": 1}),
    ])
    assert get(session) == {"ok": 1}
    assert session.calls == 3


def test_persistent_challenge_raises_blocked():
    session = FakeSession([Resp(403, CHALLENGE, "text/html")] * 3)
    with pytest.raises(LeetCodeBlockedError):
        get(session)


def test_404_is_not_retried():
    session = FakeSession([Resp(404, "nope", "text/html")])
    with pytest.raises(LeetCodeError, match="404"):
        get(session)
    assert session.calls == 1


def test_200_html_is_treated_as_failure():
    session = FakeSession([Resp(200, "<html>maintenance</html>", "text/html")] * 2)
    with pytest.raises(LeetCodeError) as exc:
        get(session, max_retries=2)
    assert not isinstance(exc.value, LeetCodeBlockedError)


class RecordingSession(FakeSession):
    def __init__(self, responses):
        super().__init__(responses)
        self.params = []

    async def get(self, url, **kw):
        self.params.append(kw.get("params"))
        return await super().get(url, **kw)


def test_ranking_page_reads_the_website_leaderboard():
    question = {"question_id": 7, "credit": 3, "title": "A", "title_slug": "a"}
    row = {"user_slug": "rajveer-09", "username": "Rajveer", "rank": 4169, "score": 3, "finish_time": 100,
           "data_region": "US", "submissions": {"7": {"date": 90, "fail_count": 1, "lang": "cpp"}}}
    v2 = {"user_num": 41784, "total_rank": [row]}
    session = RecordingSession([Resp(200, v2), Resp(200, {"questions": [question]}), Resp(200, v2)])

    async def go():
        async with LeetCodeClient(session=session, rps=0, backoff_base=0) as c:
            return await c.ranking_page("weekly-contest-519", 167), await c.ranking_page("weekly-contest-519", 168)

    page, _ = asyncio.run(go())
    assert [p["region"] for p in session.params] == ["global_v2", "global", "global_v2"]  # questions fetched once
    assert page.user_num == 41784 and page.questions[0].question_id == 7
    assert page.total_rank[0].rank == 4169
    assert page.submissions[0]["7"].question_id == 7 and page.submissions[0]["7"].fail_count == 1

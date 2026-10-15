# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
import asyncio

import pytest
from pydantic import ValidationError

from app.leetcode.client import LeetCodeBlockedError, LeetCodeError
from app.leetcode.schemas import RankingPage
from app.scan.scanner import ContestNotFinishedError, ScanIncompleteError, scan_contest
from tests.conftest import FakeClient, ranking


def run(client, **kw):
    kw.setdefault("now", 2_000_000_000)
    return asyncio.run(scan_contest(client, "weekly-contest-520", **kw))


def test_full_scan_returns_all_rows_in_order():
    client = FakeClient()
    result = run(client)
    assert result.pages == 3
    assert len(result.rows) == 59
    assert result.rows[0][0].user_slug == "karanVk"
    assert sorted(client.requested) == [1, 2, 3]


def test_refuses_unfinished_contest():
    client = FakeClient()
    with pytest.raises(ContestNotFinishedError):
        run(client, now=client.info.contest.start_time + 60)
    assert run(client, now=client.info.contest.start_time + 60, allow_unfinished=True).rows


def test_any_failed_page_fails_whole_scan():
    client = FakeClient(fail={2: LeetCodeError("HTTP 502")})
    with pytest.raises(ScanIncompleteError) as exc:
        run(client)
    assert set(exc.value.failed_pages) == {2}
    assert not exc.value.blocked


def test_schema_change_fails_scan():
    with pytest.raises(ValidationError) as exc:
        RankingPage.model_validate({"user_num": 1})
    client = FakeClient(fail={3: exc.value})
    with pytest.raises(ScanIncompleteError):
        run(client)


def test_short_middle_page_fails_scan():
    client = FakeClient()
    p2 = client.pages[2]
    client.pages[2] = p2.model_copy(
        update={"total_rank": p2.total_rank[:10], "submissions": p2.submissions[:10]}
    )
    with pytest.raises(ScanIncompleteError, match="expected 25 rows"):
        run(client)


def test_cloudflare_block_stops_remaining_requests():
    p1 = ranking(1).model_copy(update={"user_num": 25 * 20})
    pages = {i: ranking(40) for i in range(2, 21)}
    pages[1] = p1
    client = FakeClient(fail={2: LeetCodeBlockedError("challenge")}, pages=pages)
    with pytest.raises(ScanIncompleteError) as exc:
        run(client, concurrency=1)
    assert exc.value.blocked
    assert client.requested == [1, 2]  # nothing fetched after the block


def test_duplicate_rows_across_pages_are_dropped():
    client = FakeClient()
    client.pages[3] = client.pages[3].model_copy(
        update={
            "total_rank": [client.pages[2].total_rank[0], *client.pages[3].total_rank[1:]],
        }
    )
    result = run(client)
    slugs = [row.user_slug.lower() for row, _ in result.rows]
    assert len(slugs) == len(set(slugs)) == 58

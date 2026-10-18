# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Fixtures are real responses recorded from weekly-contest-520 (41,484 participants):
info.json, ranking_p1.json (top), ranking_p40.json (has wrong attempts),
ranking_p1000.json (score 0), ranking_p1660.json (last page, 9 rows)."""

import json
from pathlib import Path

import pytest

from app.leetcode.schemas import ContestInfo, RankingPage
from app.services import vcache

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _fresh_cache():
    """Each test has its own database; don't let one see another's cached results."""
    vcache.clear()
    yield
    vcache.clear()


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def info() -> ContestInfo:
    return ContestInfo.model_validate(load("info.json"))


def ranking(n: int) -> RankingPage:
    return RankingPage.model_validate(load(f"ranking_p{n}.json"))


class FakeClient:
    """Serves a 3-page contest (59 users) built from fixture pages 1, 40, 1660.

    `fail` maps page number -> exception to raise for that page.
    """

    def __init__(self, fail: dict[int, Exception] | None = None, pages: dict | None = None):
        self.info = ContestInfo.model_validate(load("info.json"))
        p1 = ranking(1)
        self.pages = pages or {
            1: p1.model_copy(update={"user_num": 59}),
            2: ranking(40),
            3: ranking(1660),
        }
        self.fail = fail or {}
        self.requested: list[int] = []

    async def contest_info(self, slug):
        return self.info

    async def question_tags(self, slug):
        return []

    async def community_topics(self, slug):
        return []

    async def ranking_page(self, slug, page):
        self.requested.append(page)
        if page in self.fail:
            raise self.fail[page]
        return self.pages[page]

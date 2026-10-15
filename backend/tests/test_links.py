# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
import pytest

from app.leetcode.links import contest_ranking_url, ranking_page


@pytest.mark.parametrize("rank, page", [(1, 1), (25, 1), (26, 2), (976, 40), (1000, 40), (24976, 1000)])
def test_ranking_page(rank, page):
    assert ranking_page(rank) == page


def test_contest_ranking_url():
    assert contest_ranking_url("weekly-contest-520", 976) == (
        "https://leetcode.com/contest/weekly-contest-520/ranking/40/?region=global_v2"
    )

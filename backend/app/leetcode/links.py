# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Links to LeetCode's own pages."""

PAGE_SIZE = 25  # rows per leaderboard page, same on the website and the API
RANKING_REGION = "global_v2"  # the leaderboard the website shows as "Global"


def ranking_page(global_rank: int) -> int:
    return (global_rank - 1) // PAGE_SIZE + 1


def contest_ranking_url(slug: str, global_rank: int) -> str:
    """The leaderboard page on leetcode.com that shows this rank."""
    return f"https://leetcode.com/contest/{slug}/ranking/{ranking_page(global_rank)}/?region={RANKING_REGION}"

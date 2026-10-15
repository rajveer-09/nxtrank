# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Global ranks match what students see on their LeetCode profiles."""

import asyncio

from sqlalchemy import select

from app.db.models import RatingHistory, Result
from app.leetcode.links import contest_ranking_url
from app.leetcode.schemas import RankRow
from app.scan.matcher import match_students
from app.scan.parser import parse_rows
from app.services.ratings import apply_profile_ranks
from app.services.scans import scan_and_store
from tests.conftest import FakeClient
from tests.test_api import SLUG
from tests.test_cancel import _sync
from tests.test_matcher import student
from tests.test_worker import factory  # noqa: F401  (fixture)


def rows(*spec):
    """spec: (handle, rank, region)"""
    return [(RankRow(user_slug=h, username=h, rank=rank, score=0, finish_time=0, data_region=region), {})
            for h, rank, region in spec]


def test_fresh_leaderboard_is_numbered_from_zero():
    people = parse_rows(rows(("a", 0, "US"), ("b", 1, "US"), ("c", 2, "US")), [], 0)
    assert [(p.global_rank, p.leaderboard_rank) for p in people] == [(1, 1), (2, 2), (3, 3)]


def test_published_leaderboard_skips_leetcode_cn_users():
    # once ratings are out, ranks start at 1 and leetcode.cn users are mixed in
    people = parse_rows(rows(("cn1", 1, "CN"), ("a", 2, "US"), ("cn2", 3, "CN"), ("cn3", 4, "CN"), ("b", 5, "US")), [], 0)
    by = {p.user_slug: p for p in people}
    assert (by["a"].global_rank, by["a"].leaderboard_rank) == (1, 2)
    assert (by["b"].global_rank, by["b"].leaderboard_rank) == (2, 5)
    assert contest_ranking_url(SLUG, by["b"].position).endswith("/ranking/1/?region=global_v2")


def test_cn_users_tied_with_a_student_are_not_ahead():
    people = parse_rows(rows(("a", 1, "US"), ("cn", 2, "CN"), ("b", 2, "US"), ("c", 4, "US")), [], 0)
    assert {p.user_slug: p.global_rank for p in people if p.data_region == "US"} == {"a": 1, "b": 2, "c": 3}


def test_leetcode_cn_user_with_the_same_handle_is_not_matched():
    people = parse_rows(rows(("alice", 1, "CN"), ("bob", 2, "US")), [], 0)
    results = match_students([student("Alice", "alice"), student("Bob", "bob")], people)
    assert {r.student.name: r.status.value for r in results} == {"Alice": "absent", "Bob": "zero"}


def test_official_profile_ranks_replace_scan_ranks_and_survive_rescans(factory):
    with factory() as s:
        _sync(s)
        asyncio.run(scan_and_store(s, FakeClient(), SLUG))
        ranked = s.scalars(select(Result).where(Result.global_rank.is_not(None)).order_by(Result.global_rank)).all()
        assert all(r.rank_source == "scan" and r.leaderboard_rank == r.global_rank for r in ranked)
        first, second = ranked[0], ranked[1]
        official = ranked[-1].global_rank + 1  # now behind every other student
        # LeetCode publishes ranks in which the second student finished ahead of the first
        s.add_all([
            RatingHistory(student_id=first.student_id, start_time=1, contest_title="Weekly Contest 520",
                          contest_slug=SLUG, rating=1500, ranking=official),
            RatingHistory(student_id=second.student_id, start_time=1, contest_title="Weekly Contest 520",
                          contest_slug=SLUG, rating=1500, ranking=0),  # unrated: keep the scan rank
        ])
        s.flush()
        assert apply_profile_ranks(s) == 1
        s.commit()
        s.refresh(first)
        s.refresh(second)
        assert (first.global_rank, first.rank_source, first.leaderboard_rank) == (official, "profile", 1)
        assert second.rank_source == "scan" and second.college_rank == 1 and first.college_rank == len(ranked)

        asyncio.run(scan_and_store(s, FakeClient(), SLUG))  # a rescan keeps the official rank
        again = s.scalars(select(Result).where(Result.student_id == first.student_id)).one()
        assert (again.global_rank, again.rank_source) == (official, "profile")

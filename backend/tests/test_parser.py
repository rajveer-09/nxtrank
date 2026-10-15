# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
import pytest

from app.scan.parser import PENALTY_SECS, parse_participant, parse_rows, question_labels
from tests.conftest import ranking


def test_question_labels_follow_contest_order(info):
    labels = question_labels(info.questions)
    assert labels == {4418: "Q1", 4417: "Q2", 4196: "Q3", 4028: "Q4"}


def test_top_participant(info):
    p1 = ranking(1)
    start = info.contest.start_time
    labels = question_labels(p1.questions)
    first = parse_participant(p1.total_rank[0], p1.submissions[0], start, labels)

    assert first.global_rank == 1  # API rank is 0-based
    assert first.user_slug == "karanVk"
    assert first.display_name == "Karan V"  # display name, not the handle
    assert first.key == "karanvk"
    assert first.solved_count == 4
    assert list(first.problems) == ["Q1", "Q2", "Q3", "Q4"]
    assert first.problems["Q1"].solve_secs == 1789871538 - start
    assert first.total_time_secs == 1789871735 - start


def test_finish_time_already_includes_penalty(info):
    p40 = ranking(40)
    people = parse_rows(list(zip(p40.total_rank, p40.submissions)), p40.questions,
                        info.contest.start_time)
    with_fails = [p for p in people if any(q.fail_count for q in p.problems.values())]
    assert with_fails, "fixture should contain wrong attempts"
    for p in people:
        last_ac = max(q.solve_secs for q in p.problems.values())
        fails = sum(q.fail_count for q in p.problems.values())
        assert p.total_time_secs == last_ac + PENALTY_SECS * fails


def test_score_zero_rows(info):
    p1000 = ranking(1000)
    people = parse_rows(list(zip(p1000.total_rank, p1000.submissions)), p1000.questions,
                        info.contest.start_time)
    assert all(p.score == 0 and p.solved_count == 0 for p in people)
    assert all(p.total_time_secs is None for p in people)
    assert people[0].global_rank == 24976


def test_unknown_question_id_fails_loudly(info):
    p1 = ranking(1)
    with pytest.raises(ValueError, match="unknown question_id"):
        parse_participant(p1.total_rank[0], p1.submissions[0], 0, {4418: "Q1"})

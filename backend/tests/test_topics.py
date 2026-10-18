# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""Topic tags (official first, provisional from community solutions) and topic stats:
no double counting, no work when nothing changed, the official/provisional split."""

import asyncio
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select

from app.db.models import AppState, Contest, ProblemResult, QuestionTag, Result, Student
from app.leetcode.client import LeetCodeError
from app.services import summaries, tags, topics
from app.worker import Worker
from tests.test_api import SLUG, client_for, env  # noqa: F401  (env is a fixture)
from tests.test_worker import END, Alerts, WorkerClient, settings



class TagClient:
    """LeetCode answering from dicts: slug -> official tags / community topics."""

    def __init__(self, official=None, community=None, fail=()):
        self.official, self.community, self.fail = official or {}, community or {}, set(fail)
        self.asked: list[tuple[str, str]] = []

    async def question_tags(self, slug):
        self.asked.append(("official", slug))
        if slug in self.fail:
            raise LeetCodeError("blocked")
        return self.official.get(slug, [])

    async def community_topics(self, slug):
        self.asked.append(("community", slug))
        return self.community.get(slug, [])


def questions(factory) -> list[str]:
    with factory() as s:
        return [q["title_slug"] for q in s.get(Contest, SLUG).questions]


def refresh(factory, client, slugs=None, **kw):
    with factory() as s:
        return asyncio.run(tags.refresh(s, client, slugs or questions(factory), **kw))


def version(factory):
    with factory() as s:
        return summaries.data_version(s)


# ---- the provisional rule -------------------------------------------------------------

def test_provisional_rule(env):
    with env[1]() as s:
        ALLOWED = tags.allowed_topics(s)  # LeetCode's topic list, from the database
    assert {"array", "dynamic-programming", "heap-priority-queue"} <= ALLOWED
    rule = tags.provisional_tags
    # LeetCode topics only; >= max(2, 30% of the top); at most 4, most used first
    got = rule([("math", "Math", 10), ("simulation", "Simulation", 5), ("number-theory", "Number Theory", 4),
                ("prime-sieve", "Prime Number Sieve", 9), ("greedy", "Greedy", 2), ("array", "Array", 3)], ALLOWED)
    assert got == [("math", "Math"), ("simulation", "Simulation"), ("number-theory", "Number Theory"),
                   ("array", "Array")]
    assert len(rule([(t, t, 10) for t in ("math", "array", "greedy", "graph", "tree")], ALLOWED)) == 4
    assert rule([("math", "Math", 2), ("array", "Array", 2), ("greedy", "Greedy", 2)], ALLOWED) is None  # top < 3
    assert rule([("math", "Math", 4)], ALLOWED) is None  # fewer than 5 mentions in all
    assert rule([], ALLOWED) is None
    # a community slug that differs but names a LeetCode topic still counts
    assert rule([("dp", "Dynamic Programming", 6)], ALLOWED) == [("dynamic-programming", "Dynamic Programming")]


# ---- refreshing ---------------------------------------------------------------------------

def test_official_wins_and_a_question_counts_once(env):
    _, factory = env
    q1, q2, q3, q4 = questions(factory)
    client = TagClient(official={q1: [("array", "Array"), ("math", "Math")]},
                       community={q1: [("greedy", "Greedy", 20)], q2: [("math", "Math", 8), ("array", "Array", 3)],
                                  q3: [("math", "Math", 2)]})
    s = refresh(factory, client)
    assert (s.checked, s.provisional_updated, s.insufficient) == (4, 1, 2)
    assert ("community", q1) not in client.asked  # no community topics once official tags exist
    with factory() as db:
        rows = db.execute(select(QuestionTag.question_slug, QuestionTag.tag_slug, QuestionTag.source)).all()
    assert sorted(rows) == sorted([(q1, "array", "official"), (q1, "math", "official"),
                                   (q2, "math", "community"), (q2, "array", "community")])


def test_no_change_no_version_bump_and_official_replaces_provisional(env):
    _, factory = env
    q1, q2, *_ = questions(factory)
    community = {q2: [("math", "Math", 8), ("array", "Array", 3)]}
    refresh(factory, TagClient(community=community))
    v = version(factory)
    again = refresh(factory, TagClient(community=community))
    assert again.changed == [] and version(factory) == v  # nothing changed: caches stay valid

    became = refresh(factory, TagClient(official={q2: [("math", "Math")]}, community=community))
    assert became.became_official == 1 and became.changed == [q2]
    assert int(version(factory)) == int(v) + 1  # bumped once
    with factory() as db:
        assert db.execute(select(QuestionTag.tag_slug, QuestionTag.source)
                          .where(QuestionTag.question_slug == q2)).all() == [("math", "official")]


def test_a_failure_leaves_stored_tags_alone(env):
    _, factory = env
    q1, *_ = questions(factory)
    refresh(factory, TagClient(official={q1: [("array", "Array")]}))
    s = refresh(factory, TagClient(fail={q1}), slugs=[q1])
    assert s.failed == 1
    with factory() as db:
        assert db.scalars(select(QuestionTag.tag_slug).where(QuestionTag.question_slug == q1)).all() == ["array"]


# ---- stats ---------------------------------------------------------------------------------

def _tag_two(factory):
    q1, q2, q3, q4 = questions(factory)
    refresh(factory, TagClient(official={q1: [("array", "Array")], q3: [("array", "Array"), ("math", "Math")]},
                               community={q2: [("math", "Math", 9), ("array", "Array", 2)], q4: []}))
    return {"Q1": [("array", "official")], "Q2": [("math", "community")],
            "Q3": [("array", "official"), ("math", "official")], "Q4": []}


def _reference(factory, tagged, student_ids=None):
    """Topic counts worked out the slow way, straight from results."""
    out = defaultdict(lambda: defaultdict(int))
    with factory() as s:
        active = {st.id for st in s.scalars(select(Student).where(Student.active.is_(True)))}
        went = [r for r in s.scalars(select(Result).where(Result.contest_slug == SLUG))
                if r.status in ("solved", "zero") and r.student_id in active
                and (student_ids is None or r.student_id in student_ids)]
        solves = {(p.student_id, p.q_label): p for p in s.scalars(select(ProblemResult))}
        for r in went:
            for label, ts in tagged.items():
                for tag, source in ts:
                    out[tag]["appeared"] += 1
                    out[tag][f"{source}_appeared"] += 1
                    if (pr := solves.get((r.student_id, label))) is not None:
                        out[tag]["solved"] += 1
                        out[tag]["wrong"] += pr.fail_count
    return out


def test_group_and_student_topic_stats_match_the_results(env):
    _, factory = env
    tagged = _tag_two(factory)
    ref = _reference(factory, tagged)
    with factory() as s:
        group = {t["slug"]: t for t in topics.group_topics(s)["topics"]}
        assert set(group) == {"array", "math"}
        for slug, t in group.items():
            assert (t["appeared"], t["solved"]) == (ref[slug]["appeared"], ref[slug]["solved"])
            # official + provisional parts add up exactly
            assert t["official"]["appeared"] + t["provisional_appeared"] == t["appeared"]
            assert t["official"]["appeared"] == ref[slug]["official_appeared"]
        assert group["math"]["provisional_questions"] == 1

        # every student's own numbers add up to the group's
        totals = defaultdict(lambda: [0, 0])
        for st in s.scalars(select(Student).where(Student.active.is_(True))):
            for t in topics.student_topics(s, st.id)["topics"]:
                totals[t["slug"]][0] += t["appeared"]
                totals[t["slug"]][1] += t["solved"]
        assert {k: tuple(v) for k, v in totals.items()} == {k: (g["appeared"], g["solved"]) for k, g in group.items()}

        cov = topics.group_topics(s)["coverage"]
        assert (cov["contests"], cov["contests_provisional"], cov["official"], cov["provisional"],
                cov["insufficient"]) == (1, 1, 2, 1, 1)


def test_topic_endpoints_and_contest_chips(env):
    _, factory = env
    _tag_two(factory)
    c = client_for(env, "viewer")
    data = c.get("/api/analytics/topics").json()
    assert {t["slug"] for t in data["topics"]} == {"array", "math"} and data["coverage"]["contests_provisional"] == 1
    sid = next(s["id"] for s in c.get("/api/students").json()["rows"] if s["roll_no"] == "R1")
    assert c.get(f"/api/students/{sid}/topics").json()["topics"]
    chips = {q["label"]: q["topics"] for q in c.get(f"/api/contests/{SLUG}").json()["questions"]}
    assert chips["Q1"]["state"] == "official" and chips["Q1"]["tags"][0]["source"] == "official"
    assert chips["Q2"]["state"] == "provisional" and chips["Q2"]["mentions"] == 11
    assert chips["Q4"]["state"] == "insufficient" and chips["Q4"]["tags"] == []
    status = c.get("/api/tags/status").json()
    assert status["counts"] == {"official": 2, "provisional": 1, "insufficient": 1, "pending": 0}


def test_admins_ask_the_worker_to_refresh(env):
    settings_, factory = env
    admin = client_for(env, "admin")
    assert admin.post("/api/admin/tags/refresh").status_code == 202
    assert client_for(env, "viewer").post("/api/admin/tags/refresh").status_code == 403
    with factory() as s:
        s.merge(AppState(key=tags.NIGHTLY_KEY, value="x", updated_at=END + timedelta(days=1)))
        s.merge(AppState(key=tags.MONTHLY_KEY, value="x", updated_at=END + timedelta(days=1)))
        s.commit()
    client = WorkerClient(upcoming=[])
    worker = Worker(factory, lambda: client, settings=settings(), notifier=Alerts(), clock=lambda: END + timedelta(days=1))
    asyncio.run(worker.tick())
    with factory() as s:
        assert not s.get(AppState, tags.REQUEST_KEY).value  # picked up and cleared
        assert s.get(AppState, tags.LAST_RUN_KEY).value

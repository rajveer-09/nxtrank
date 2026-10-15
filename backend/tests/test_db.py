# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
import asyncio

import pytest
from sqlalchemy import func, select

from app.db.migrate import upgrade
from app.db.models import College, ProblemResult, Result, RosterSync, ScanRun, Student
from app.db.session import make_engine, make_session_factory
from app.leetcode.client import LeetCodeError
from app.scan.scanner import ScanIncompleteError
from app.services.export import write_csv
from app.services.handles import validate_handles
from app.services.results import load_contest_results
from app.services.roster import parse_roster
from app.services.roster_sync import RosterSyncError, sync_roster
from app.services.scans import scan_and_store
from tests.conftest import FakeClient
from tests.dbutil import fresh_url

HEADER = ["Roll No", "Full Name", "College", "Batch", "LeetCode Profile URL"]


@pytest.fixture
def db_url(tmp_path):
    """SQLite per test, or TEST_DATABASE_URL (see tests/dbutil.py)."""
    url = fresh_url(tmp_path)
    upgrade(url)  # runs the real Alembic migrations
    return url


@pytest.fixture
def session(db_url):
    with make_session_factory(make_engine(db_url))() as s:
        yield s


def sync(session, rows, **kw):
    students, issues = parse_roster([HEADER, *rows], "sheet")
    return sync_roster(session, students, issues, "sheet", **kw)


ROSTER = [
    ["R1", "Top Ranker", "College A", "2026", "https://leetcode.com/u/karanVk/"],
    ["R2", "Penalty Case", "College A", "2026", "KUNAALLLL"],
    ["R3", "Penalty Two", "College B", "2026", "@SaranyaMohanasundharam"],
    ["R4", "Zero Solver", "College B", "2027", "Tanishq_yadav7"],
    ["R5", "Ghost", "College A", "2027", "ghost_handle_xyz"],
    ["R6", "No Handle", "College B", "2027", ""],
]


def students_by_roll(session):
    return {s.roll_no: s for s in session.scalars(select(Student))}


# ---- roster sync ---------------------------------------------------------------


def test_sync_adds_students_and_colleges(session):
    result = sync(session, ROSTER)
    assert (result.added, result.updated, result.deactivated) == (6, 0, 0)
    st = students_by_roll(session)
    assert st["R1"].lc_slug == "karanvk" and st["R1"].college.name == "College A"
    assert st["R1"].extra == {"Batch": "2026"}
    assert st["R6"].lc_slug is None
    assert session.scalar(select(func.count()).select_from(College)) == 2
    assert result.issues == ["row 7 (No Handle): no LeetCode handle"]


def test_sync_updates_deactivates_and_reactivates(session):
    sync(session, ROSTER)
    st = students_by_roll(session)
    st["R2"].handle_status = "valid"
    st["R3"].handle_status = "valid"
    session.commit()

    changed = [list(r) for r in ROSTER[:5]]
    changed[1][1] = "Penalty Case Renamed"   # name change keeps handle status
    changed[2][4] = "new_handle_r3"          # handle change resets it
    result = sync(session, changed)
    assert (result.added, result.updated, result.deactivated, result.unchanged) == (0, 2, 1, 3)
    st = students_by_roll(session)
    assert st["R2"].name == "Penalty Case Renamed" and st["R2"].handle_status == "valid"
    assert st["R3"].lc_slug == "new_handle_r3" and st["R3"].handle_status == "unchecked"
    assert st["R6"].active is False

    result = sync(session, ROSTER)
    assert result.reactivated == 1
    assert students_by_roll(session)["R6"].active is True


def test_sync_roll_numbers_are_case_insensitive_and_deduped(session):
    result = sync(session, [
        ["r1", "A", "C", "", "a1"],
        ["R1", "A again", "C", "", "a2"],
        ["", "No roll", "C", "", "a3"],
    ])
    assert result.added == 1
    assert any("already used by row 2" in i for i in result.issues)
    assert any("no roll number" in i for i in result.issues)
    assert list(students_by_roll(session)) == ["R1"]


def test_sync_refuses_mass_deactivation(session):
    sync(session, ROSTER)
    with pytest.raises(RosterSyncError, match="deactivate 5 of 6"):
        sync(session, ROSTER[:1])
    assert sum(s.active for s in students_by_roll(session).values()) == 6
    assert sync(session, ROSTER[:1], force=True).deactivated == 5


def test_sync_refuses_sheet_without_roll_numbers(session):
    students, issues = parse_roster([["name", "leetcode"], ["A", "a"]], "sheet")
    with pytest.raises(RosterSyncError, match="no students with a roll number"):
        sync_roster(session, students, issues, "sheet")
    assert session.scalar(select(func.count()).select_from(RosterSync)) == 0


# ---- handle validation -----------------------------------------------------------


class HandleClient:
    def __init__(self, existing, fail=()):
        self.existing = {h.lower(): h for h in existing}
        self.fail = set(fail)
        self.calls = []

    async def matched_user(self, handle):
        self.calls.append(handle)
        if handle in self.fail:
            raise LeetCodeError("HTTP 502")
        return self.existing.get(handle.lower())


def test_validate_only_unchecked_then_all(session):
    sync(session, ROSTER)
    client = HandleClient(["karanVk", "kunaallll", "SaranyaMohanasundharam", "Tanishq_yadav7"],
                          fail=["kunaallll"])
    summary = asyncio.run(validate_handles(session, client))
    assert (summary.checked, summary.valid, summary.invalid, summary.errors) == (4, 3, 1, 1)
    st = students_by_roll(session)
    assert st["R1"].handle_status == "valid" and st["R1"].lc_username == "karanVk"
    assert st["R5"].handle_status == "invalid"
    assert st["R2"].handle_status == "unchecked"  # errored, retried next time

    client.fail.clear()
    client.calls.clear()
    asyncio.run(validate_handles(session, client))
    assert client.calls == ["kunaallll"]

    client.calls.clear()
    asyncio.run(validate_handles(session, client, recheck_all=True))
    assert len(client.calls) == 5  # R6 has no handle


# ---- scans -------------------------------------------------------------------------


def test_scan_stores_results_and_rescan_replaces_them(session):
    sync(session, ROSTER)
    students_by_roll(session)["R5"].handle_status = "invalid"
    session.commit()

    run = asyncio.run(scan_and_store(session, FakeClient(), "weekly-contest-520"))
    assert run.status == "complete" and run.students == 6

    stored = load_contest_results(session, "weekly-contest-520")
    assert stored.labels == ["Q1", "Q2", "Q3", "Q4"]
    by_roll = {r.student.roll_no: r for r in stored.results}
    assert by_roll["R1"].status == "solved" and by_roll["R1"].participant.global_rank == 1
    assert by_roll["R1"].college_rank == 1
    assert by_roll["R2"].participant.global_rank == 976
    assert by_roll["R2"].participant.problems["Q4"].fail_count == 2
    assert by_roll["R2"].participant.total_time_secs == 43 * 60 + 16
    assert by_roll["R5"].status == "invalid_handle"
    assert by_roll["R6"].status == "no_handle"
    # Zero Solver is on page 1000, which the 3-page fake contest doesn't include
    assert by_roll["R4"].status == "absent"
    assert [r.student.roll_no for r in stored.results][:3] == ["R1", "R2", "R3"]

    # rescanning replaces rows instead of duplicating them
    asyncio.run(scan_and_store(session, FakeClient(), "weekly-contest-520", kind="final"))
    assert session.scalar(select(func.count()).select_from(Result)) == 6
    assert session.scalar(select(func.count()).select_from(ProblemResult)) == 4 + 3 + 3


def test_failed_scan_keeps_previous_results(session):
    sync(session, ROSTER)
    asyncio.run(scan_and_store(session, FakeClient(), "weekly-contest-520"))

    with pytest.raises(ScanIncompleteError):
        asyncio.run(scan_and_store(
            session, FakeClient(fail={2: LeetCodeError("HTTP 502")}), "weekly-contest-520"
        ))
    runs = session.scalars(select(ScanRun).order_by(ScanRun.id)).all()
    assert [r.status for r in runs] == ["complete", "failed"]
    assert "HTTP 502" in runs[1].error
    assert session.scalar(select(func.count()).select_from(Result)) == 6


def test_inactive_students_are_not_in_new_scans(session):
    sync(session, ROSTER)
    sync(session, ROSTER[:5])  # R6 removed from sheet
    asyncio.run(scan_and_store(session, FakeClient(), "weekly-contest-520"))
    rolls = {r.student.roll_no for r in load_contest_results(session, "weekly-contest-520").results}
    assert "R6" not in rolls and len(rolls) == 5


def test_export_from_db(session, tmp_path):
    import csv

    sync(session, ROSTER)
    asyncio.run(scan_and_store(session, FakeClient(), "weekly-contest-520"))
    stored = load_contest_results(session, "weekly-contest-520")
    out = tmp_path / "out.csv"
    write_csv(out, "weekly-contest-520", stored.results, stored.labels)
    with open(out, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[1]["name"] == "Penalty Case"
    assert rows[1]["roll_no"] == "R2"
    assert rows[1]["Batch"] == "2026"
    assert rows[1]["total_time"] == "0:43:16"
    assert rows[1]["ranking_url"].endswith("/ranking/40/?region=global_v2")


# ---- CLI -------------------------------------------------------------------------


def test_cli_sync_export_status(db_url, tmp_path, capsys, monkeypatch):
    from app import cli

    roster_csv = tmp_path / "roster.csv"
    roster_csv.write_text(",".join(HEADER) + "\n" + "\n".join(",".join(r) for r in ROSTER) + "\n",
                          encoding="utf-8")
    assert cli.main(["import-students", str(roster_csv), "--database-url", db_url]) == 0
    assert "6 added" in capsys.readouterr().out

    # scan via the CLI with the fake LeetCode client
    monkeypatch.setattr(cli, "_client", lambda args: _AsyncCM(FakeClient()))
    assert cli.main(["scan", "weekly-contest-520", "--database-url", db_url]) == 0
    assert "solved=3" in capsys.readouterr().out

    out = tmp_path / "export.csv"
    assert cli.main(["export", "weekly-contest-520", "--database-url", db_url, "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8-sig").count("\n") == 7

    assert cli.main(["status", "--database-url", db_url]) == 0
    status = capsys.readouterr().out
    assert "6 active" in status and "weekly-contest-520 provisional complete" in status

    assert cli.main(["export", "weekly-contest-999", "--database-url", db_url]) == 1


class _AsyncCM:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, *exc):
        return None

# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Final scans run at 11 pm (IST) on the 5th working day after a contest."""

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from app.services.schedule import FinalSchedule

IST = ZoneInfo("Asia/Kolkata")


def ist(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def test_weekly_and_biweekly_both_finalise_on_friday_night():
    final = FinalSchedule()
    weekly_end = ist(2026, 10, 18, 9, 30)  # Sunday
    biweekly_end = ist(2026, 10, 24, 21, 30)  # Saturday
    assert final.due_at(weekly_end).astimezone(IST) == ist(2026, 10, 23, 23)  # Friday
    assert final.due_at(biweekly_end).astimezone(IST) == ist(2026, 10, 30, 23)  # Friday


def test_counts_only_working_days_and_uses_the_configured_time():
    final = FinalSchedule(working_days=5, at=time(22, 30))
    wednesday_end = ist(2026, 10, 14, 12)
    # Thu, Fri, (Sat, Sun skipped), Mon, Tue, Wed
    assert final.due_at(wednesday_end).astimezone(IST) == ist(2026, 10, 21, 22, 30)
    assert final.due_at(wednesday_end).tzinfo == timezone.utc


def test_early_results_say_when_final_results_arrive(tmp_path):
    from datetime import timedelta

    from app.db.migrate import upgrade
    from app.db.models import Contest, ScanRun
    from app.db.session import make_engine, make_session_factory
    from app.services.scan_status import contest_states

    from tests.dbutil import fresh_url

    url = fresh_url(tmp_path)
    upgrade(url)
    factory = make_session_factory(make_engine(url))
    end = ist(2026, 10, 18, 9, 30)  # Sunday weekly
    with factory() as s:
        c = Contest(slug="weekly-contest-524", title="Weekly Contest 524", contest_type="weekly",
                    start_time=int(end.timestamp()) - 5400, duration=5400, questions=[])
        s.add(c)
        s.add(ScanRun(contest_slug=c.slug, kind="provisional", status="complete",
                      started_at=end + timedelta(minutes=30), finished_at=end + timedelta(minutes=40)))
        s.commit()
        state = contest_states(s, [c], end + timedelta(hours=1), timedelta(minutes=30))[c.slug]
    assert state["state"] == "provisional"
    final_at = datetime.fromisoformat(state["final_at"]).astimezone(IST)
    assert final_at.date() == ist(2026, 10, 23, 0).date() and final_at.hour == 23  # Friday, 11 pm + the scan

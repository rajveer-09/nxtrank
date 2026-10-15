# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""When a contest's final scan runs.

LeetCode says ratings (and with them the settled ranks) are updated "within 5 working
days" of a contest, so the final scan runs late on the 5th working day (Mon-Fri) after
the contest, in the dashboard's timezone. For a Sunday weekly or a Saturday biweekly
that's Friday night.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class FinalSchedule:
    working_days: int = 5
    at: time = time(23, 0)
    tz: str = "Asia/Kolkata"

    def due_at(self, end: datetime) -> datetime:
        """The final scan time for a contest that ended at `end` (aware datetime)."""
        zone = ZoneInfo(self.tz)
        day = end.astimezone(zone).date()
        counted = 0
        while counted < self.working_days:
            day += timedelta(days=1)
            if day.weekday() < 5:  # Monday..Friday
                counted += 1
        return datetime.combine(day, self.at, tzinfo=zone).astimezone(timezone.utc)

    def due_at_ts(self, start_time: int, duration: int) -> datetime:
        return self.due_at(datetime.fromtimestamp(start_time + duration, timezone.utc))


DEFAULT_FINAL = FinalSchedule()


def parse_time(text: str) -> time:
    """'23:00' -> time(23, 0)"""
    hours, _, minutes = text.strip().partition(":")
    return time(int(hours), int(minutes or 0))


def round_up(dt: datetime, minutes: int = 5) -> datetime:
    """11:09 -> 11:10: estimates read better on round minutes."""
    step = minutes * 60
    ts = dt.timestamp()
    return datetime.fromtimestamp(-(-ts // step) * step, dt.tzinfo or timezone.utc)

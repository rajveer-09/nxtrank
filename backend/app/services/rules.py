# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""The numbers behind every rule, for the Guide's rule book (/api/rules). They're read
from the constants the calculations use, so the rule book can't drift from the code."""

from app.config import Settings
from app.services import analytics, drafts, summaries, tags, topics, view_as
from app.services.scan_status import AUTO_LOOKBACK
from app.worker import MAX_SLEEP, Policy

# analytics constants the rule book shows (tests check none is missing)
ANALYTICS_RULES = (
    "TREND_THRESHOLD", "TREND_K", "ABSENT_STREAK_ALERT", "TOP_N", "MEDALS", "CONSISTENCY_MIN_CONTESTS",
    "ATTENDANCE_WEIGHT", "STABILITY_WEIGHT", "STD_CAP",
)


def rules(settings: Settings) -> dict:
    policy = Policy.from_settings(settings)
    final = policy.final
    return {
        "analytics": {
            **{name.lower(): getattr(analytics, name) for name in ANALYTICS_RULES},
            "consistency_labels": [{"from": floor, "label": label} for floor, label in analytics.CONSISTENCY_LABELS],
            "windows": [w for w in summaries.WINDOWS if w],  # plus "all"
        },
        "schedule": {
            "timezone": settings.display_tz,
            "scan_delay_minutes": int(policy.scan_delay.total_seconds() // 60),
            "provisional_retries_minutes": [int(r.total_seconds() // 60) for r in policy.provisional_retries],
            "final_working_days": final.working_days if final else None,
            "final_time": final.at.strftime("%H:%M") if final else None,
            "final_retries_hours": [int(r.total_seconds() // 3600) for r in policy.final_retries],
            "auto_lookback_days": AUTO_LOOKBACK.days,
            "ratings_every_hours": int(policy.ratings_every.total_seconds() // 3600),
            "worker_awake_window": settings.worker_awake_window,
            "worker_max_sleep_minutes": int(MAX_SLEEP.total_seconds() // 60),
        },
        "tags": {
            "min_mentions": tags.MIN_MENTIONS, "top_share": tags.TOP_SHARE, "max_tags": tags.MAX_TAGS,
            "min_top": tags.MIN_TOP, "min_total": tags.MIN_TOTAL, "recent_days": tags.RECENT.days,
            "nightly_time": "00:00", "monthly": "the 1st, 00:30",
            "weak_min_appeared": topics.WEAK_MIN_APPEARED, "weakest_shown": topics.WEAKEST,
        },
        "review": {
            "enabled": settings.scan_review_enabled, "draft_days": drafts.KEEP_FOR.days,
            "view_as_minutes": view_as.VIEW_AS_SECS // 60,
        },
    }

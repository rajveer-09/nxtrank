# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Settings from environment variables, plus `backend/.env` if present (real
environment variables take precedence over the file)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env", override=False)
DEFAULT_DATABASE_URL = f"sqlite:///{(BACKEND_DIR / 'data' / 'dashboard.db').as_posix()}"


@dataclass(frozen=True)
class Settings:
    database_url: str
    proxy_url: str | None
    google_credentials: str | None
    # alerts (any combination; none configured = log only)
    slack_webhook_url: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    display_tz: str  # timezone for times in alerts/logs
    # worker schedule
    scan_delay_minutes: int  # first scan this long after the contest ends
    final_scan_working_days: int  # final scan on this working day (Mon-Fri) after the contest, 0 = off
    final_scan_time: str  # ... at this time of day in display_tz, e.g. "23:00"
    # web API
    secret_key: str | None  # signs session cookies; required in production
    cookie_secure: bool  # send the session cookie only over HTTPS
    frontend_dist: Path  # built frontend served by the API, if present
    app_env: str = "development"  # development | staging | production (API docs are off in production)
    allowed_origins: tuple[str, ...] = ()  # other sites allowed to send change requests (dev tools)
    # worker: inside this daily window (display_tz) it checks every minute, since the database
    # is kept awake then anyway; outside it, it sleeps until the next due job (at most 30 min)
    # so Neon can suspend. "always" = check every minute all day.
    worker_awake_window: str = "09:30-18:00"
    worker_wake_url: str | None = None  # the website's /api/worker/wake, polled while asleep
    scans_enabled: bool = True  # false on staging: its data is a copy, scans run on production
    scan_review_enabled: bool = True  # scans requested from the dashboard wait for an admin's review

    @property
    def production(self) -> bool:
        return self.app_env == "production"


def _env(name: str) -> str | None:
    return os.environ.get(name) or None


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        proxy_url=_env("PROXY_URL"),
        google_credentials=_env("GOOGLE_APPLICATION_CREDENTIALS"),
        slack_webhook_url=_env("SLACK_WEBHOOK_URL"),
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
        display_tz=os.environ.get("DISPLAY_TZ", "Asia/Kolkata"),
        scan_delay_minutes=int(os.environ.get("SCAN_DELAY_MINUTES", "30")),
        final_scan_working_days=int(os.environ.get("FINAL_SCAN_WORKING_DAYS", "5")),
        final_scan_time=os.environ.get("FINAL_SCAN_TIME", "23:00"),
        secret_key=_env("SECRET_KEY"),
        cookie_secure=os.environ.get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes"),
        frontend_dist=Path(os.environ.get("FRONTEND_DIST", BACKEND_DIR.parent / "frontend" / "dist")),
        app_env=os.environ.get("APP_ENV", "development").strip().lower(),
        worker_awake_window=os.environ.get("WORKER_AWAKE_WINDOW", "09:30-18:00"),
        worker_wake_url=_env("WORKER_WAKE_URL"),
        scans_enabled=os.environ.get("SCANS_ENABLED", "true").lower() not in ("0", "false", "no"),
        scan_review_enabled=os.environ.get("SCAN_REVIEW_ENABLED", "true").lower() not in ("0", "false", "no"),
        allowed_origins=tuple(o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()),
    )

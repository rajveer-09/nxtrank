# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Alerts to Slack and/or Telegram (worker events and API crashes). Failures to deliver
are logged, never raised."""

import json
import logging
import threading
import time
import urllib.error
import urllib.request

from app.config import Settings
from app.request_context import request_id

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, *, slack_webhook_url: str | None = None,
                 telegram_bot_token: str | None = None, telegram_chat_id: str | None = None):
        self.slack_webhook_url = slack_webhook_url
        self.telegram = (telegram_bot_token, telegram_chat_id) if telegram_bot_token and telegram_chat_id else None

    @classmethod
    def from_settings(cls, settings: Settings) -> "Notifier":
        return cls(slack_webhook_url=settings.slack_webhook_url,
                   telegram_bot_token=settings.telegram_bot_token,
                   telegram_chat_id=settings.telegram_chat_id)

    @property
    def enabled(self) -> bool:
        return bool(self.slack_webhook_url or self.telegram)

    def send(self, text: str) -> None:
        text = f"NxtRank: {text}"  # say which app it's from in Slack / Telegram
        log.info("alert: %s", text)
        if self.slack_webhook_url:
            self._post(self.slack_webhook_url, {"text": text}, "Slack")
        if self.telegram:
            token, chat_id = self.telegram
            self._post(f"https://api.telegram.org/bot{token}/sendMessage",
                       {"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                       "Telegram")

    @staticmethod
    def _post(url: str, payload: dict, name: str) -> None:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15):
                pass
        except (urllib.error.URLError, TimeoutError) as e:
            log.warning("could not send %s alert: %s", name, e)


class CrashAlerts(logging.Handler):
    """Sends API crashes (the `app.errors` log) as alerts: the first right away, then at
    most one every `every` seconds, saying how many more happened in between. Sending
    runs in a background thread, so the request that crashed isn't held up."""

    def __init__(self, notifier: Notifier, every: float = 600, clock=time.monotonic):
        super().__init__(level=logging.ERROR)
        self.notifier, self.every, self.clock = notifier, every, clock
        self._lock = threading.Lock()
        self._last: float | None = None
        self._held = 0  # crashes since the last alert, not sent yet

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            now = self.clock()
            if self._last is not None and now - self._last < self.every:
                self._held += 1
                return
            more, self._held, self._last = self._held, 0, now
        rid = request_id.get() or "?"
        text = f"API error: {record.getMessage()} (reference {rid})"
        if record.exc_info and record.exc_info[1] is not None:
            text += f": {type(record.exc_info[1]).__name__}: {str(record.exc_info[1])[:200]}"
        if more:
            text += f". {more} more since the last alert"
        threading.Thread(target=self.notifier.send, args=(text,), daemon=True).start()


def install_crash_alerts(notifier: Notifier, logger: str = "app.errors") -> None:
    """(Re)attach the crash alerts to the API's crash log; nothing to do without a channel."""
    target = logging.getLogger(logger)
    for old in [h for h in target.handlers if isinstance(h, CrashAlerts)]:
        target.removeHandler(old)
    if notifier.enabled:
        target.addHandler(CrashAlerts(notifier))

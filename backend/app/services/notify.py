# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Alerts to Slack and/or Telegram. Failures to deliver are logged, never raised."""

import json
import logging
import urllib.error
import urllib.request

from app.config import Settings

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

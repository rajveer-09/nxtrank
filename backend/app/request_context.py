# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
"""The current request's ID, shared by the API's log lines, its error replies and the
`X-Request-ID` header, so a user's "Reference: …" leads straight to the server's log."""

import logging
from contextvars import ContextVar

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s%(rid_tag)s: %(message)s"


class RequestIdFilter(logging.Filter):
    """Adds `rid_tag` (" [<id>]" during a request, "" otherwise) to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        rid = request_id.get()
        record.rid_tag = f" [{rid}]" if rid else ""
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Root logging for the CLI (serve, worker, scans): one plain line per record."""
    logging.basicConfig(level=level, format=LOG_FORMAT)
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RequestIdFilter) for f in handler.filters):
            handler.addFilter(RequestIdFilter())

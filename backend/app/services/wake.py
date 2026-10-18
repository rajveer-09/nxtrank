# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
"""The worker's wake-up signal: when someone asks for a scan, the website notes the time
in a small file on its own disk. A sleeping worker reads it through /api/worker/wake,
without touching the database, so the database can stay suspended until there's work."""

import tempfile
import time
from pathlib import Path

SIGNAL = Path(tempfile.gettempdir()) / "nxtrank-worker-wake"


def signal() -> None:
    """A scan was requested just now."""
    try:
        SIGNAL.write_text(str(time.time()))
    except OSError:
        pass  # the worker still finds the request on its next regular check


def last_signal() -> float | None:
    try:
        return float(SIGNAL.read_text())
    except (OSError, ValueError):
        return None

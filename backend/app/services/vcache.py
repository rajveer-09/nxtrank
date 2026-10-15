# Author: Rajveer Sharma
# © NxtWave
# Date: 15 October 2026
"""Per-process cache keyed by data_version. Every data change bumps the version in its own
transaction, so an entry is never served after the data it came from has changed.
"""

import threading
from collections import OrderedDict
from typing import Callable, TypeVar

SIZE = 24  # entries per process (a cohort with 1,500 students is ~1 MB)

T = TypeVar("T")
_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()


def cached(key: tuple, compute: Callable[[], T]) -> T:
    """`key` must start with the data_version the value is computed at."""
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    value = compute()
    with _lock:
        _cache[key] = value
        while len(_cache) > SIZE:
            _cache.popitem(last=False)
    return value


def clear() -> None:
    with _lock:
        _cache.clear()

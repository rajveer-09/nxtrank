# Author: Rajveer Sharma
# © NxtWave
# Date: 15 October 2026
"""Conditional GETs. The ETag hashes the code build, data_version,
user and role, and the URL; with `private, no-cache` the browser revalidates and gets a
304 with no body when nothing changed. Only for responses that depend on data alone.
"""

import hashlib
from pathlib import Path
from typing import Any, Callable

from fastapi import Request, Response
from sqlalchemy.orm import Session

from app.api.fastjson import FastJSONResponse
from app.db.models import User
from app.services import summaries

CACHE_CONTROL = "private, no-cache"


def _build_id() -> str:
    """A hash of the backend's code, the same in every worker of one deploy."""
    h = hashlib.sha1()
    root = Path(__file__).resolve().parents[1]
    for path in sorted(root.rglob("*.py")):
        h.update(path.relative_to(root).as_posix().encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:12]


BUILD = _build_id()


def etag_for(request: Request, user: User, version: str) -> str:
    query = "&".join(sorted(f"{k}={v}" for k, v in request.query_params.multi_items()))
    raw = f"{BUILD}|{version}|{user.id}|{user.role}|{request.url.path}?{query}"
    return f'W/"{hashlib.sha1(raw.encode()).hexdigest()[:24]}"'


def _matches(header: str | None, tag: str) -> bool:
    if not header:
        return False
    if header.strip() == "*":
        return True
    weak = lambda t: t.strip().removeprefix("W/")  # noqa: E731  (If-None-Match compares weakly)
    return weak(tag) in {weak(t) for t in header.split(",")}


def conditional(request: Request, db: Session, user: User, build: Callable[[str], Any]) -> Response:
    """`build(data_version)` -> the JSON payload; only called if the browser's copy is stale."""
    version = summaries.data_version(db)
    tag = etag_for(request, user, version)
    headers = {"ETag": tag, "Cache-Control": CACHE_CONTROL}
    if _matches(request.headers.get("if-none-match"), tag):
        return Response(status_code=304, headers=headers)
    return FastJSONResponse(build(version), headers=headers)

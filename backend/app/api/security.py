# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
"""Browser-side protection the app sets itself (Render has no Caddy in front of it):
security headers on every response, and an Origin check on every change request."""

import base64
import hashlib
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders

from app.api.errors import body

log = logging.getLogger(__name__)

# The NxtWave logo in the header comes from NxtWave's CDN; avatars are data: URIs.
_IMAGES = "'self' data: https://d14qv6cm1t62pm.cloudfront.net"


def page_policy(index_html: Path | None) -> str:
    """The content security policy for the web page: only our own scripts, plus the
    inline theme script in index.html, allowed by its hash (so no 'unsafe-inline')."""
    scripts = ["'self'"]
    if index_html is not None and index_html.is_file():
        html = index_html.read_text(encoding="utf-8")
        for code in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, flags=re.S):
            digest = base64.b64encode(hashlib.sha256(code.encode()).digest()).decode()
            scripts.append(f"'sha256-{digest}'")
    return "; ".join([
        "default-src 'self'",
        f"script-src {' '.join(scripts)}",
        "style-src 'self' 'unsafe-inline'",  # React's style={} attributes
        f"img-src {_IMAGES}",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


API_POLICY = "default-src 'none'; frame-ancestors 'none'"  # JSON never runs anything


class SecurityHeaders:
    """nosniff, no framing, a strict referrer and a CSP on everything; HSTS over HTTPS."""

    def __init__(self, app, *, https: bool, page_csp: str):
        self.app = app
        self.page_csp = page_csp
        self.static = [
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
            ("Referrer-Policy", "strict-origin-when-cross-origin"),
            ("Cross-Origin-Opener-Policy", "same-origin"),
            ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
        ]
        if https:
            self.static.append(("Strict-Transport-Security", "max-age=31536000; includeSubDomains"))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        csp = API_POLICY if scope["path"].startswith("/api/") else self.page_csp

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.static:
                    headers.setdefault(name, value)
                headers.setdefault("Content-Security-Policy", csp)
            await send(message)

        await self.app(scope, receive, send_with_headers)


UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower() if parts.scheme and parts.netloc else None


class OriginCheck:
    """Refuses a change request (POST/PUT/PATCH/DELETE under /api/) sent by another site.

    The session cookie is SameSite=Lax, which already stops most cross-site posts; this
    is the second lock. Browsers send Origin (or at least Referer) on such requests, so
    one that names a different site is refused. Requests with neither come from scripts
    and tools, not from a page in a browser, and are left to the usual login check."""

    def __init__(self, app, *, allowed: tuple[str, ...] = ()):
        self.app = app
        self.allowed = {o.rstrip("/").lower() for o in allowed}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in UNSAFE or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        claimed = headers.get("origin")
        source = _origin_of(claimed) if claimed and claimed != "null" else None
        if source is None and not claimed:
            referer = headers.get("referer")
            source = _origin_of(referer) if referer else None
            if not referer:
                return await self.app(scope, receive, send)
        host = headers.get("x-forwarded-host") or headers.get("host", "")
        scheme = headers.get("x-forwarded-proto") or scope.get("scheme", "http")
        own = f"{scheme}://{host}".lower()
        # the host alone also counts: a proxy may end TLS without saying so
        if source is not None and (source == own or urlsplit(source).netloc == host.lower() or source in self.allowed):
            return await self.app(scope, receive, send)

        log.warning("refused %s %s from origin %r (host %r)", scope["method"], scope["path"], claimed or source, host)
        payload = json.dumps(body(403, "This request came from another site and was refused.", "bad_origin")).encode()
        await send({"type": "http.response.start", "status": 403, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]})
        await send({"type": "http.response.body", "body": payload})

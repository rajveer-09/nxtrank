# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""FastAPI application: JSON API under /api, plus the built frontend (if present).

Run:  uvicorn app.api.app:create_app --factory --port 8000   (see README)
"""

import logging
import mimetypes
import secrets

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.sessions import SessionMiddleware

from app.api import routes_admin, routes_auth, routes_data
from app.api.observe import Observe, watch
from app.config import Settings, get_settings
from app.db.migrate import upgrade
from app.db.session import make_engine, make_session_factory

log = logging.getLogger(__name__)

SESSION_MAX_AGE = 7 * 24 * 3600


def create_app(settings: Settings | None = None, session_factory=None) -> FastAPI:
    settings = settings or get_settings()
    if session_factory is None:
        upgrade(settings.database_url)
        session_factory = make_session_factory(make_engine(settings.database_url))

    app = FastAPI(title="NxtRank API", docs_url="/api/docs",
                  openapi_url="/api/openapi.json", redoc_url=None)
    app.state.settings = settings
    app.state.session_factory = session_factory
    watch(session_factory.kw["bind"])  # per-request query counts and database time

    secret = settings.secret_key
    if not secret:
        log.warning("SECRET_KEY not set: using a random key, logins reset when the API restarts")
        secret = secrets.token_urlsafe(32)
    app.add_middleware(
        SessionMiddleware, secret_key=secret, session_cookie="lcdash_session",
        max_age=SESSION_MAX_AGE, same_site="lax", https_only=settings.cookie_secure,
    )

    app.add_middleware(ApiNoStore)
    app.add_middleware(Observe)  # outermost: times everything below it
    app.include_router(routes_auth.router)
    app.include_router(routes_data.router)
    app.include_router(routes_admin.router)

    @app.get("/api/health", include_in_schema=False)
    def health() -> dict:
        return {"ok": True}

    _mount_frontend(app, settings)
    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    dist = settings.frontend_dist
    index = dist / "index.html"
    if not index.is_file():
        log.info("no built frontend at %s; serving the API only", dist)
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", HashedAssets(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate, headers={"Cache-Control": "public, max-age=86400"})
        # client-side routes: always revalidate, so a new deploy is picked up immediately
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


class ApiNoStore:
    """API responses hold user and student data: never cache them in the browser's
    disk cache or any shared proxy (unless a route sets its own Cache-Control)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "cache-control" not in headers:
                    headers["Cache-Control"] = "private, no-store"
            await send(message)

        await self.app(scope, receive, send_with_header)


class HashedAssets(StaticFiles):
    """Vite gives every asset a content hash in its name, so it can be cached forever.
    Serves the .br / .gz copies made at build time when the browser accepts them (in
    production Caddy does this; this keeps the app fast when run on its own too)."""

    ENCODINGS = (("br", ".br"), ("gzip", ".gz"))

    async def get_response(self, path, scope):
        accepted = Headers(scope=scope).get("accept-encoding", "")
        for encoding, suffix in self.ENCODINGS:
            if encoding in accepted:
                full, stat = self.lookup_path(path + suffix)
                if stat is not None:
                    original, _ = self.lookup_path(path)
                    response = FileResponse(full, stat_result=stat, media_type=_media_type(original or path))
                    response.headers["Content-Encoding"] = encoding
                    response.headers["Vary"] = "Accept-Encoding"
                    return self._immutable(response)
        return self._immutable(await super().get_response(path, scope))

    @staticmethod
    def _immutable(response):
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def _media_type(path: str) -> str | None:
    return mimetypes.guess_type(path)[0]

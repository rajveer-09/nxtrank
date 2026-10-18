# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
"""One shape for every API error: {"detail": readable text, "code": stable machine name,
"request_id": the reference shown to the user}. Crashes are caught in observe.py."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.request_context import request_id

CODES = {
    400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
    405: "method_not_allowed", 409: "conflict", 413: "too_large", 422: "validation",
    429: "rate_limited", 502: "upstream", 503: "unavailable",
}


class ApiError(HTTPException):
    """An HTTPException with its own code, for errors the UI handles specially."""

    def __init__(self, status_code: int, detail: str, code: str, headers: dict | None = None):
        super().__init__(status_code, detail, headers)
        self.code = code


def body(status: int, detail, code: str | None = None, **extra) -> dict:
    return {"detail": detail, "code": code or CODES.get(status, "error"), "request_id": request_id.get(), **extra}


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(body(exc.status_code, exc.detail, getattr(exc, "code", None)),
                        status_code=exc.status_code, headers=getattr(exc, "headers", None))


def _field(err: dict) -> str:
    return ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path", "header", "cookie"))


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    text = "; ".join(f"{_field(e)}: {e.get('msg', 'invalid')}" if _field(e) else str(e.get("msg", "invalid"))
                     for e in errors)
    safe = [{"field": _field(e), "msg": e.get("msg"), "type": e.get("type")} for e in errors]
    return JSONResponse(body(422, text or "invalid request", errors=safe), status_code=422)


def install(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)

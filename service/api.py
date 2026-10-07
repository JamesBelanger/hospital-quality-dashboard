"""HTTP front door for the "Ask the data" service.

    GET  /health   liveness check; touches neither the database nor the model
    POST /ask      {"question": "..."} -> the Answer from service.pipeline.ask
    GET  /status   usage and latency from the request log (no question text)

/ask order: body-size check (413) -> validation (422, never echoes the input) -> limits (the request log plus the
requests in flight in this process; 429 or 503, no model call) -> ask() -> log the request (also when ask()
raises) -> leave the in-flight registry -> response. Every response carries an X-Release header; /ask responses
also carry nosniff and no-store. There is no /docs, /redoc or /openapi.json.
The pipeline is imported on first use so a container can report healthy before it has opened any connection.
"""
from __future__ import annotations

import os
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from service import limits

MAX_QUESTION_CHARS = 300
MAX_BODY_BYTES = 4096
RELEASE = os.environ.get("HQ_RELEASE", "dev")
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "HQ_ALLOWED_ORIGINS", "https://jamesbelanger.com,http://localhost:4321").split(",") if o.strip()]

app = FastAPI(title="Hospital Quality: Ask the data", version=RELEASE, docs_url=None, redoc_url=None, openapi_url=None)

_TOO_LARGE = b'{"detail":"request body too large"}'


class _BodyTooLarge(Exception):
    pass


class BodyLimit:
    """ASGI middleware: refuse a request body over MAX_BODY_BYTES with 413 before anything parses it.
    A declared Content-Length over the cap is refused without reading the body; a chunked (or lying) body is
    cut off as soon as the bytes read pass the cap."""

    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES):
        self.app, self.max_bytes = app, max_bytes

    @staticmethod
    async def _start(send):
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(_TOO_LARGE)).encode())]})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self.max_bytes:
                    await self._start(send)
                    return await send({"type": "http.response.body", "body": _TOO_LARGE})
        state = {"read": 0, "over": False, "started": False}

        async def counted_receive():
            msg = await receive()
            if msg["type"] == "http.request":
                state["read"] += len(msg.get("body", b""))
                if state["read"] > self.max_bytes:
                    state["over"] = True
                    raise _BodyTooLarge()
            return msg

        async def guarded_send(msg):
            if not state["over"]:
                return await send(msg)
            # the framework turned our exception into an error response of its own: swap it for the 413
            if msg["type"] == "http.response.start" and not state["started"]:
                state["started"] = True
                return await self._start(send)
            if msg["type"] == "http.response.body":
                return await send({"type": "http.response.body", "body": _TOO_LARGE})

        try:
            await self.app(scope, counted_receive, guarded_send)
        except _BodyTooLarge:
            if not state["started"]:
                await self._start(send)
                await send({"type": "http.response.body", "body": _TOO_LARGE})


app.add_middleware(BodyLimit)  # innermost: CORS and the release header still wrap its 413
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["content-type"], expose_headers=["X-Release", "Retry-After"])


@app.middleware("http")
async def add_release_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Release"] = RELEASE
    if request.url.path == "/ask":
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
    return response


_VALIDATION_TEXT = {"string_too_short": "is too short",
                    "string_too_long": f"is too long (at most {MAX_QUESTION_CHARS} characters)",
                    "missing": "is required", "string_type": "must be text"}


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 with the field name and a fixed message per error type. The submitted input is never echoed."""
    parts = []
    for err in exc.errors()[:3]:
        loc = [str(x) for x in err.get("loc", ()) if x != "body"]
        parts.append(f"{'.'.join(loc) or 'body'} {_VALIDATION_TEXT.get(err.get('type'), 'is not valid')}")
    return JSONResponse(status_code=422, content={"detail": "invalid request: " + "; ".join(parts)})


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=MAX_QUESTION_CHARS)


def _model() -> str:
    from service.llm import DEFAULT_MODEL
    return os.environ.get("HQ_MODEL") or DEFAULT_MODEL


@app.get("/health")
def health() -> dict:
    from service.pipeline import prompt_versions  # imports modules only; no connection, no model call
    return {"status": "ok", "release": RELEASE, "model": _model(), "prompt_versions": prompt_versions()}


@app.get("/status")
def status() -> dict:
    from service import logging_store
    try:
        windows = logging_store.status_windows()
        spent = logging_store.spent_today()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="the request log is unavailable") from e
    s = limits.settings()
    return {"release": RELEASE, **windows,
            "budget_today": {"used_usd": round(spent, 6), "limit_usd": s.daily_budget_usd,
                             "resets_at_utc": limits.next_reset().isoformat()}}


@app.post("/ask")
def ask_endpoint(req: AskRequest, request: Request) -> dict:
    from service import logging_store

    who = limits.client_hash(request.headers.get("x-forwarded-for"), request.client.host if request.client else None)
    try:
        token = limits.admit(who)  # atomic: counts logged rows + requests in flight, then registers this one
    except limits.LimitExceeded as e:
        headers = {"Retry-After": str(e.retry_after_s)} if e.retry_after_s else None
        raise HTTPException(status_code=e.status, detail=e.detail, headers=headers) from e

    try:
        from service.pipeline import ask  # deferred: see module docstring

        question = req.question.strip()
        t0 = time.perf_counter()
        try:
            answer = ask(question)
        except Exception as e:  # never leak a stack trace or connection string to a public caller
            logging_store.log_request(None, who, RELEASE, error=f"{type(e).__name__}: {str(e)[:200]}", question=question,
                                      latency_ms=int((time.perf_counter() - t0) * 1000))
            raise HTTPException(status_code=502, detail=f"could not answer: {type(e).__name__}") from e
        logging_store.log_request(answer, who, RELEASE)
        return answer.model_dump(mode="json")
    finally:
        limits.release(token)  # after the row is logged, so a request is never invisible to the next check

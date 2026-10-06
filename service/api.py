"""HTTP front door for the "Ask the data" service.

    GET  /health   liveness check; touches neither the database nor the model
    POST /ask      {"question": "..."} -> the Answer from service.pipeline.ask
    GET  /status   usage and latency from the request log (no question text)

/ask order: limits (from the request log; 429 or 503, no model call) -> ask() -> log the request
(also when ask() raises) -> response. Every response carries an X-Release header.
The pipeline is imported on first use so a container can report healthy before it has opened any connection.
"""
from __future__ import annotations

import os
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from service import limits

MAX_QUESTION_CHARS = 300
RELEASE = os.environ.get("HQ_RELEASE", "dev")
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "HQ_ALLOWED_ORIGINS", "https://jamesbelanger.com,http://localhost:4321").split(",") if o.strip()]

app = FastAPI(title="Hospital Quality: Ask the data", version=RELEASE)
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["content-type"], expose_headers=["X-Release", "Retry-After"])


@app.middleware("http")
async def add_release_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Release"] = RELEASE
    return response


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
        limits.check(who)
    except limits.LimitExceeded as e:
        headers = {"Retry-After": str(e.retry_after_s)} if e.retry_after_s else None
        raise HTTPException(status_code=e.status, detail=e.detail, headers=headers) from e

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

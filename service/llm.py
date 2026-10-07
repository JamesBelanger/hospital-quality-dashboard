"""Thin chat-model wrapper so the provider can be swapped (and faked in tests).

`complete()` asks for a reply that fits a pydantic model and returns it parsed, together
with token counts, cost and latency. Prices are per 1M tokens (input, output).
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gpt-6-luna"
PRICES = {  # USD per 1M tokens: (input, output)
    "gpt-6-luna": (0.10, 0.50),
    "gpt-6-sol": (2.0, 10.0),
    "gpt-6.1-sol": (2.0, 10.0),
    "gpt-6-astra": (10.0, 50.0),
}


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    model: str
    step: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class LLM(Protocol):
    def complete(self, system: str, user: str, schema: type[T], model: str | None = None,
                 max_output_tokens: int | None = None) -> tuple[T, Usage]: ...


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = PRICES.get(model, PRICES["gpt-6-astra"])  # unknown model: assume the dearest
    return (input_tokens * p_in + output_tokens * p_out) / 1_000_000


class OpenAILLM:
    """OpenAI Responses API with structured output (`responses.parse(text_format=...)`).

    No sampling parameters are sent; the model decides its own.
    """

    def __init__(self):
        from openai import OpenAI  # reads OPENAI_API_KEY from the environment

        self._client = OpenAI()

    def complete(self, system: str, user: str, schema: type[T], model: str | None = None,
                 max_output_tokens: int | None = None) -> tuple[T, Usage]:
        model = model or os.environ.get("HQ_MODEL") or DEFAULT_MODEL
        t0 = time.perf_counter()
        extra = {"max_output_tokens": max_output_tokens} if max_output_tokens else {}
        resp = self._client.responses.parse(model=model, instructions=system, input=user, text_format=schema, **extra)
        ms = int((time.perf_counter() - t0) * 1000)
        if resp.output_parsed is None:
            raise RuntimeError("model returned no parsable output")
        u = resp.usage
        return resp.output_parsed, Usage(u.input_tokens, u.output_tokens,
                                         cost_usd(model, u.input_tokens, u.output_tokens), ms, model)

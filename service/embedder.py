"""Text embedding behind a small interface so the provider can be swapped.

`OpenAIEmbedder` is the default. Anything with `.model`, `.dims` and `.encode(texts)`
works in its place (a local model, another vendor), which is what the evaluation
ablations rely on.
"""
from __future__ import annotations

from typing import Protocol, Sequence


class Embedder(Protocol):
    model: str
    dims: int

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    PRICE_PER_1M_TOKENS = {"text-embedding-3-small": 0.02, "text-embedding-3-large": 0.13}
    DIMS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072}

    def __init__(self, model: str = "text-embedding-3-small", batch_size: int = 100):
        from openai import OpenAI  # reads OPENAI_API_KEY from the environment

        self.model, self.dims, self.batch_size = model, self.DIMS[model], batch_size
        self.tokens_used = 0
        self._client = OpenAI()

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            resp = self._client.embeddings.create(model=self.model, input=list(texts[i:i + self.batch_size]))
            self.tokens_used += resp.usage.total_tokens
            out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
        return out

    @property
    def cost_usd(self) -> float:
        return self.tokens_used / 1_000_000 * self.PRICE_PER_1M_TOKENS[self.model]


def to_pgvector(v: Sequence[float]) -> str:
    """pgvector's text input format."""
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"

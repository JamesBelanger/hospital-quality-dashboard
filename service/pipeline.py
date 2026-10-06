"""ask(question): plan -> gather evidence -> answer or refuse.

  1. Plan call: the model picks a route (data / docs / both / refuse) and writes the SQL
     and/or a documentation search query.
  2. Evidence: SQL runs through sql_guard + the read-only login. One repair call per question,
     of one kind: after a failure (kind "error"), or, when the query ran but matched 0 rows,
     one check asking the planner whether a filter was wrong (kind "empty"); documentation is searched and kept only if the best vector similarity
     reaches DOC_SUPPORT_THRESHOLD.
  3. If there is no evidence on any path the model was asked to use, the answer is a
     refusal and no answer call is made.
  4. Answer call: the model writes a short answer from the rows and chunks. Citations it
     invents (unknown chunk id, or a quote not found in that chunk) are dropped. A reply
     marked unsupported, or a docs-only reply left with no valid citation, becomes a refusal.

Prompts live in service/prompts/ and are versioned by file name; the versions used are
returned with every answer.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from service import retrieval
from service.embedder import Embedder
from service.llm import LLM, Usage
from service.retrieval import Chunk, search_docs
from service.sql_runner import DatabaseError, GuardRejected, run_sql

PROMPTS = Path(__file__).parent / "prompts"
PLAN_PROMPT, ANSWER_PROMPT, SCHEMA_PROMPT = "plan_v4", "answer_v5_drill", "schema_v2"  # DRILL: deliberately worse
DOC_SUPPORT_THRESHOLD = 0.35  # smoke test: 0.67-0.80 on-topic, 0.13 off-topic
MAX_ROWS_SHOWN = 50
REFUSAL_NO_EVIDENCE = "I could not find data or documentation in this dataset that answers that question."


def load_prompt(name: str) -> str:
    path = PROMPTS / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt version {name!r} does not exist (no file service/prompts/{name}.md)")
    return path.read_text(encoding="utf-8")


def prompt_versions() -> dict[str, str]:
    """The prompt versions in use: the HQ_PLAN_PROMPT / HQ_SCHEMA_PROMPT / HQ_ANSWER_PROMPT environment
    variables if set, else the defaults above. A name with no file raises at first use (load_prompt)."""
    return {"plan": os.environ.get("HQ_PLAN_PROMPT") or PLAN_PROMPT,
            "schema": os.environ.get("HQ_SCHEMA_PROMPT") or SCHEMA_PROMPT,
            "answer": os.environ.get("HQ_ANSWER_PROMPT") or ANSWER_PROMPT}


# ---- structured outputs the model fills in ----
class Plan(BaseModel):
    route: Literal["data", "docs", "both", "refuse"]
    sql: str | None = None
    doc_query: str | None = None
    reason: str


class CitationIn(BaseModel):
    chunk_id: str
    quote: str


class AnswerOut(BaseModel):
    answer: str
    citations: list[CitationIn]
    supported: bool


# ---- what ask() returns ----
class Citation(BaseModel):
    chunk_id: str
    doc_title: str
    section_title: str | None = None
    page_start: int | None = None
    source_url: str | None = None
    quote: str


class Answer(BaseModel):
    question: str
    route: str
    refused: bool
    refusal_reason: str | None = None
    answer: str | None = None
    sql: str | None = None
    columns: list[str] = []
    rows: list[list] = []
    row_count: int = 0
    citations: list[Citation] = []
    prompt_versions: dict[str, str]
    model: str | None = None
    usage: list[Usage] = []
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    repaired: bool = False
    repair_kind: Literal["error", "empty"] | None = None  # which single repair call was spent, if any
    sql_error: str | None = None  # why the data path produced no rows, if it failed
    timings: dict[str, int] = {}
    retrieved_chunk_ids: list[str] = []  # docs path: ids retrieved, in rank order, whether or not they passed the threshold
    doc_top_similarity: float | None = None
    doc_query: str | None = None  # the text actually sent to documentation search (planner's rewrite, else the question)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def _valid_citations(cites: list[CitationIn], chunks: list[Chunk]) -> list[Citation]:
    by_id = {c.chunk_id: c for c in chunks}
    kept: list[Citation] = []
    for c in cites:
        ch = by_id.get(c.chunk_id)
        q = _norm(c.quote)
        if ch is None or not q or q not in _norm(ch.body):
            continue
        kept.append(Citation(chunk_id=ch.chunk_id, doc_title=ch.doc_title, section_title=ch.section_title,
                             page_start=ch.page_start, source_url=ch.source_url, quote=c.quote.strip()))
    return kept


def _plan_system(versions: dict[str, str]) -> str:
    return load_prompt(versions["plan"]).replace("{{schema}}", load_prompt(versions["schema"]))


def _answer_user(question: str, res, chunks: list[Chunk]) -> str:
    parts = [f"QUESTION: {question}"]
    if res is not None:
        shown = res.rows[:MAX_ROWS_SHOWN]
        note = f" (showing the first {len(shown)} of {res.row_count})" if res.row_count > len(shown) else ""
        if res.row_count == 0:  # a query that ran and matched nothing is evidence: the answer is "none"
            note = " (the query ran successfully and returned 0 rows: no records match)"
        parts.append(f"SQL: {res.sql_run}\n\nSQL RESULT{note}\ncolumns: {json.dumps(res.columns)}\nrows: {json.dumps(shown)}")
    if chunks:
        parts.append("DOCUMENTATION EXCERPTS\n" + "\n\n".join(
            f"[chunk_id: {c.chunk_id}] {c.doc_title} / {c.section_title or ''}\n{c.body}" for c in chunks))
    return "\n\n".join(parts)


def _empty_check(question: str, sql_text: str, res, system: str, call):
    """The query ran and returned 0 rows. Ask the planner once whether a filter could be wrong; run its
    corrected SQL if it differs. Returns (result, sql_text, repaired, repair_kind). If the corrected SQL
    fails or is empty, the original 0-row result stands (no second repair)."""
    fixed = call("empty_check", system,
                 f"QUESTION: {question}\n\nSQL THAT RETURNED 0 ROWS:\n{sql_text}\n\n"
                 "The query ran without error and returned 0 rows. If a filter could be wrong (letter case, "
                 "spelling, an over-narrow condition, or a view that covers only part of the data), return "
                 "corrected SQL. If zero rows is the true answer, return the same SQL unchanged.", Plan)
    new_sql = (fixed.sql or "").strip()
    if new_sql and new_sql != sql_text.strip():
        try:
            return run_sql(new_sql), new_sql, True, "empty"
        except (GuardRejected, DatabaseError):
            pass
    return res, sql_text, True, "empty"


def ask(question: str, llm: LLM | None = None, embedder: Embedder | None = None, model: str | None = None) -> Answer:
    t_start = time.perf_counter()
    if llm is None:
        from service.llm import OpenAILLM
        llm = OpenAILLM()
    usage: list[Usage] = []
    timings: dict[str, int] = {}
    retrieved_ids: list[str] = []
    top_sim: float | None = None
    doc_query_used: str | None = None
    mode = os.environ.get("HQ_RETRIEVAL_MODE") or retrieval.DEFAULT_MODE
    versions = prompt_versions()
    system = _plan_system(versions)  # raises at once if a configured prompt version has no file
    answer_system = load_prompt(versions["answer"])

    def call(step: str, system: str, user: str, schema):
        obj, u = llm.complete(system, user, schema, **({'model': model} if model else {}))
        u.step = step
        usage.append(u)
        timings[step + "_ms"] = timings.get(step + "_ms", 0) + u.latency_ms
        return obj

    def finish(route: str, **kw) -> Answer:
        timings["total_ms"] = int((time.perf_counter() - t_start) * 1000)
        return Answer(
            question=question, route=route, prompt_versions=versions, usage=usage, timings=timings,
            retrieved_chunk_ids=retrieved_ids, doc_top_similarity=top_sim, doc_query=doc_query_used,
            model=usage[0].model if usage else None,
            total_input_tokens=sum(u.input_tokens for u in usage),
            total_output_tokens=sum(u.output_tokens for u in usage),
            total_cost_usd=round(sum(u.cost_usd for u in usage), 6), **kw)

    def refuse(route: str, reason: str, **kw) -> Answer:
        return finish(route, refused=True, refusal_reason=reason, **kw)

    plan = call("plan", system, f"QUESTION: {question}", Plan)
    if plan.route == "refuse":
        return refuse("refuse", plan.reason or REFUSAL_NO_EVIDENCE)

    # ---- data path ----
    res, sql_text, repaired, data_error = None, plan.sql, False, None
    repair_kind: str | None = None
    if plan.route in ("data", "both"):
        if not (plan.sql or "").strip():
            data_error = "the plan contained no SQL"
        else:
            t0 = time.perf_counter()
            for attempt in (0, 1):
                try:
                    res = run_sql(sql_text)
                    data_error = None
                    break
                except (GuardRejected, DatabaseError) as e:
                    data_error = str(e)
                    if attempt == 1:
                        break
                    repaired, repair_kind = True, "error"
                    fixed = call("repair", system,
                                 f"QUESTION: {question}\n\nFAILED SQL:\n{sql_text}\n\nERROR: {data_error}", Plan)
                    sql_text = fixed.sql or sql_text
            if res is not None and res.row_count == 0 and not repaired:
                before_sql = sql_text
                res, sql_text, repaired, repair_kind = _empty_check(question, sql_text, res, system, call)
                if sql_text != before_sql:
                    usage[-1].step = "empty_check_changed"  # lets the eval count how often the check changed the SQL
            timings["sql_ms"] = int((time.perf_counter() - t0) * 1000)

    # ---- docs path ----
    chunks: list[Chunk] = []
    docs_error = None
    if plan.route in ("docs", "both"):
        t0 = time.perf_counter()
        if embedder is None:
            from service.embedder import OpenAIEmbedder
            embedder = OpenAIEmbedder()
        before = (getattr(embedder, "tokens_used", None), getattr(embedder, "cost_usd", None))
        doc_query_used = plan.doc_query or question
        found = search_docs(doc_query_used, retrieval.DEFAULT_K, embedder, mode=mode)
        retrieved_ids = [c.chunk_id for c in found]
        if before[0] is not None:
            usage.append(Usage(embedder.tokens_used - before[0], 0, embedder.cost_usd - before[1],
                               int((time.perf_counter() - t0) * 1000), embedder.model, "embed"))
        timings["retrieval_ms"] = int((time.perf_counter() - t0) * 1000)
        top = top_sim = retrieval.top_similarity(found)
        if top is None or top < DOC_SUPPORT_THRESHOLD:
            docs_error = "no documentation section was close enough to the question"
        else:
            chunks = found

    if res is None and not chunks:
        reason = REFUSAL_NO_EVIDENCE + " (" + "; ".join(e for e in (data_error, docs_error) if e) + ")"
        return refuse(plan.route, reason, sql=sql_text if plan.route != "docs" else None, repaired=repaired,
                      repair_kind=repair_kind, sql_error=data_error)

    # ---- answer ----
    out = call("answer", answer_system, _answer_user(question, res, chunks), AnswerOut)
    citations = _valid_citations(out.citations, chunks)
    base = dict(sql=res.sql_run if res else None, columns=res.columns if res else [],
                rows=res.rows[:MAX_ROWS_SHOWN] if res else [], row_count=res.row_count if res else 0,
                repaired=repaired, repair_kind=repair_kind, sql_error=data_error)
    if not out.supported:
        return refuse(plan.route, "The evidence found does not answer the question: " + out.answer, **base)
    if res is None and not citations:
        return refuse(plan.route, "The answer could not be tied to a verifiable passage of the documentation.", **base)
    return finish(plan.route, refused=False, answer=out.answer, citations=citations, **base)

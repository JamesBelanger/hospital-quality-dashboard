"""Command line: python -m service.cli "question" [--json]"""
from __future__ import annotations

import argparse
import sys

from service.pipeline import Answer, ask


def render(a: Answer) -> str:
    out = [f"Q: {a.question}", f"route: {a.route}" + ("  (repaired SQL)" if a.repaired else "")]
    if a.refused:
        out += ["", "REFUSED: " + (a.refusal_reason or "")]
    else:
        out += ["", a.answer or ""]
    if a.sql:
        out += ["", "SQL:", a.sql]
        if a.rows:
            out += ["", f"rows ({a.row_count} total, showing {min(10, len(a.rows))}):", " | ".join(a.columns)]
            out += [" | ".join("" if v is None else str(v) for v in r) for r in a.rows[:10]]
    if a.citations:
        out += ["", "Sources:"]
        for c in a.citations:
            where = f"{c.doc_title}, {c.section_title or 'n/a'}" + (f", p.{c.page_start}" if c.page_start else "")
            out += [f"- {where}", f'  "{c.quote}"', f"  {c.source_url or ''}"]
    out += ["", f"tokens in/out: {a.total_input_tokens}/{a.total_output_tokens}  "
                f"cost: ${a.total_cost_usd:.5f}  latency: {a.timings.get('total_ms', 0)} ms  model: {a.model}"]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ask a question about the hospital-quality data.")
    ap.add_argument("question")
    ap.add_argument("--json", action="store_true", help="print the full Answer as JSON")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    a = ask(args.question)
    print(a.model_dump_json(indent=2) if args.json else render(a))


if __name__ == "__main__":
    main()

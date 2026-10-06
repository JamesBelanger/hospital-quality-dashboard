"""
chunk_ncd.py — split the raw NCD documents (docs_index/raw/ncd/) into retrieval chunks -> docs_index/chunks_ncd.jsonl.

Usage:  python docs_index/chunk_ncd.py

Same size rule as chunk.py (reused, not copied): 1,200-2,400 chars per chunk, never mid-sentence, 200 chars of
sentence-aligned overlap between consecutive chunks of the same section, hard cap 4,000.

Sections are the NCD's own:
  * "Item/Service Description" (API field item_service_description)
  * "Indications and Limitations of Coverage" (indications_limitations). When this text is longer than one chunk
    and has its own standalone headings (a paragraph that is only bold text, e.g. "B. Nationally Covered
    Indications"), it is split at those headings and the heading is appended to the section title.
  * "Reasons for Denial" (reasons_for_denial) when present.
  Not indexed: revision history (change log), cross-reference lists (pointers, no conditions), AMA statement,
  and other_text (a list of links to downloadable ICD-10 code-list files). No code tables are added.
Every chunk's section_title starts "NCD <manual section> <title> — ..." so a citation names the NCD by itself.
doc_id = ncd_<manual section>; chunk_id = <doc_id>:<n>.
"""
from __future__ import annotations
import importlib.util, html, json, re, statistics, sys
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
MANIFEST = ROOT / "manifest_ncd.json"
OUT = ROOT / "chunks_ncd.jsonl"

# reuse the measure-document chunker (module name "chunk" would shadow the stdlib module, so load it by path)
_spec = importlib.util.spec_from_file_location("hq_chunk", ROOT / "chunk.py")
_chunk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_chunk)
pack_prose, clean, MAX_C = _chunk.pack_prose, _chunk.clean, _chunk.MAX_C

BLOCK = {"p", "li", "ul", "ol", "div", "br", "tr", "table", "tbody", "h1", "h2", "h3", "h4", "h5", "h6", "hr"}
HEADING_MAX = 160


def html_atoms(raw: str) -> list[tuple[str, bool]]:
    """HTML (double-escaped by the API) -> [(text, is_heading)], one atom per paragraph / list item / table row."""
    text = re.sub("�(?=\d)", "§", html.unescape(raw or ""))  # the API text has U+FFFD where "section 1861" was written with a section sign
    soup = BeautifulSoup(text, "lxml")
    atoms: list[tuple[str, bool]] = []
    buf: list[str] = []

    def flush(heading: bool = False):
        t = clean(" ".join(buf)).strip(" |")
        buf.clear()
        if t:
            atoms.append((t, heading))

    def is_heading(p: Tag) -> bool:
        txt = clean(p.get_text(" "))
        bold = clean(" ".join(s.get_text(" ") for s in p.find_all(["strong", "b"])))
        return bool(txt) and txt == bold and len(txt) <= HEADING_MAX and not txt.endswith(".")

    def walk(node):
        for ch in node.children:
            if isinstance(ch, NavigableString):
                buf.append(str(ch))
            elif isinstance(ch, Tag):
                if ch.name == "p" and is_heading(ch):
                    flush(); buf.append(ch.get_text(" ")); flush(True)
                elif ch.name in BLOCK:
                    flush(); walk(ch); flush()
                elif ch.name in ("td", "th"):
                    walk(ch); buf.append(" | ")
                elif ch.name in ("script", "style"):
                    continue
                else:
                    walk(ch)
    walk(soup.body or soup)
    flush()
    return atoms


def sections_for(d: dict, x: dict) -> list[tuple[str, list[tuple]]]:
    """[(section title suffix, atoms)] for one NCD; atoms are (text, 0, 0) for pack_prose."""
    out = []
    desc = [a for a, _ in html_atoms(x.get("item_service_description"))]
    if desc:
        out.append(("Item/Service Description", [(t, 0, 0) for t in desc]))
    il = html_atoms(x.get("indications_limitations"))
    base = "Indications and Limitations of Coverage"
    total = sum(len(t) for t, _ in il)
    if total > MAX_C and any(h for _, h in il):
        head, cur = base, []
        for t, h in il:
            if h:
                if cur:
                    out.append((head, cur))
                head, cur = f"{base} — {t}", []
            else:
                cur.append((t, 0, 0))
        if cur:
            out.append((head, cur))
    elif il:
        out.append((base, [(t, 0, 0) for t, _ in il]))
    den = [a for a, _ in html_atoms(x.get("reasons_for_denial"))]
    if den:
        out.append(("Reasons for Denial", [(t, 0, 0) for t in den]))
    return out


def main():
    docs = json.loads(MANIFEST.read_text("utf-8"))["documents"]
    n_out, sizes, cpt = 0, [], 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as fo:
        for d in docs:
            x = json.loads((RAW / d["file"]).read_text("utf-8"))["data"][0]
            label = f"NCD {d['manual_section']} {d['title']}"
            doc_title = f"Medicare National Coverage Determination {d['manual_section']}: {d['title']}"
            idx = 0
            for suffix, atoms in sections_for(d, x):
                for text, _, _ in pack_prose(atoms):
                    text = text.strip()
                    if sum(c.isalpha() for c in text) < 20:
                        continue
                    rec = dict(chunk_id=f"{d['doc_id']}:{idx}", doc_id=d["doc_id"], doc_title=doc_title,
                               source_url=d["source_url"], section_title=f"{label} — {suffix}",
                               page_start=None, page_end=None, text=text, n_chars=len(text), measure_ids=[],
                               collection="coverage")
                    fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); idx += 1; n_out += 1
                    sizes.append(len(text)); cpt += bool(re.search(r"\bCPT\b", text))
            if idx == 0:
                print(f"WARNING: {d['doc_id']} produced no chunks")
    print(f"{len(docs)} NCDs -> {n_out} chunks -> {OUT.relative_to(ROOT.parent)}")
    print(f"chunk size min/median/max = {min(sizes)}/{int(statistics.median(sizes))}/{max(sizes)}; "
          f">4000: {sum(s > 4000 for s in sizes)}; <1200: {sum(s < 1200 for s in sizes)}; mentioning CPT: {cpt}")


if __name__ == "__main__":
    sys.exit(main())

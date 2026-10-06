"""
chunk.py — split the raw CMS documents (docs_index/raw/) into retrieval chunks -> docs_index/chunks.jsonl.

Usage:  python docs_index/chunk.py

Chunking rule (fixed):
  * split on section headings first (PDF: bold / larger-font short lines; HTML: h1-h4)
  * inside a section: target 1,200-2,400 chars, never split mid-sentence, ~200 chars of sentence-aligned
    overlap between consecutive chunks of the same section
  * tables / data-dictionary entries (one measure, one field group, one dataset) are atomic: a chunk boundary
    only falls BETWEEN entries, entries are never split and never overlap; hard cap 4,000 chars
  * page headers / footers / page numbers that repeat are stripped
Each chunk records which of this project's measure IDs (data/processed/measures.csv) it mentions;
IDs match case-insensitively with '_' and '-' treated as equivalent.
"""
from __future__ import annotations
import csv, json, re, statistics, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
RAW = ROOT / "raw"
MANIFEST = ROOT / "manifest.json"
OUT = ROOT / "chunks.jsonl"
MEASURES_CSV = REPO / "data" / "processed" / "measures.csv"

MIN_C, MAX_C, HARD_MAX, OVERLAP = 1200, 2400, 4000, 200
DICT_DOC = "cms_hospital_data_dictionary"

# ---------------------------------------------------------------- text helpers
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−-"), "_")
_ABBREV = ("e.g", "i.e", "vs", "al", "no", "fig", "approx", "dr", "u.s", "inc", "etc", "cf")


def clean(s: str) -> str:
    s = s.replace(" ", " ").replace("’", "'")
    # PDF font encoding turned dashes AND apostrophes into U+FFFD: apostrophe before s/t/re/ll/ve, else dash
    s = re.sub(r"(?<=\w)�(?=(s|t|re|ll|ve|d))", "'", s).replace("�", "-")
    return re.sub(r"\s+", " ", s).strip()


def norm_id(s: str) -> str:
    return s.upper().translate(_DASHES)


def split_sentences(text: str) -> list[str]:
    """Split on . ! ? followed by space + capital/digit/open-bracket; guard common abbreviations."""
    parts, start = [], 0
    for m in re.finditer(r"[.!?][\"')\]]*\s+(?=[A-Z0-9(\[\"'])", text):
        end = m.end()
        prev = text[start:m.start() + 1].rsplit(" ", 1)[-1].lower().rstrip(".")
        if prev in _ABBREV or re.fullmatch(r"[a-z]", prev):  # abbreviation / initial
            continue
        parts.append(text[start:end].strip())
        start = end
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def hard_split(s: str, limit: int) -> list[str]:
    """Last resort for a single 'sentence' longer than limit: split at whitespace."""
    out = []
    while len(s) > limit:
        cut = s.rfind(" ", 0, limit)
        cut = cut if cut > limit // 2 else limit
        out.append(s[:cut].strip()); s = s[cut:].strip()
    return out + ([s] if s else [])


# ---------------------------------------------------------------- chunk packers
# An "atom" is (text, page_start, page_end). A section is (title, kind, [atoms]) with kind prose|table.

def pack_prose(atoms: list[tuple]) -> list[tuple]:
    """Sentence-aligned packing with ~200-char overlap. Returns [(text, p0, p1)]."""
    sents = []  # (sentence, p0, p1)
    for text, p0, p1 in atoms:
        for s in split_sentences(text):
            for piece in (hard_split(s, MAX_C) if len(s) > HARD_MAX else [s]):
                sents.append((piece, p0, p1))
    chunks, cur, i = [], [], 0
    def size(c): return sum(len(x[0]) for x in c) + max(len(c) - 1, 0)
    def emit(c): chunks.append((" ".join(x[0] for x in c), min(x[1] for x in c), max(x[2] for x in c)))
    new_since_emit = 0
    while i < len(sents):
        s = sents[i]
        if cur and size(cur) + 1 + len(s[0]) > MAX_C and (size(cur) >= MIN_C or size(cur) + 1 + len(s[0]) > HARD_MAX):
            emit(cur); new_since_emit = 0
            # overlap: trailing whole sentences totalling >= OVERLAP chars (skip if the tail sentence is huge)
            ov, tot = [], 0
            for x in reversed(cur):
                if tot >= OVERLAP: break
                if tot + len(x[0]) > 3 * OVERLAP and ov: break
                if len(x[0]) > 3 * OVERLAP: break
                ov.insert(0, x); tot += len(x[0]) + 1
            cur = list(ov)
        cur.append(s); new_since_emit += 1; i += 1
    if cur and new_since_emit:
        # fold a tiny trailing remainder into the previous chunk instead of emitting a stub
        new_part = cur[len(cur) - new_since_emit:]
        if chunks and size(new_part) < 400 and len(chunks[-1][0]) + 1 + size(new_part) <= int(MAX_C * 1.25):
            t, p0, p1 = chunks[-1]
            chunks[-1] = (t + " " + " ".join(x[0] for x in new_part), min(p0, new_part[0][1]), max(p1, new_part[-1][2]))
        else:
            emit(cur)
    return chunks


def pack_table(atoms: list[tuple]) -> list[tuple]:
    """Entry-aligned packing: boundaries only between atoms; atoms never split unless > HARD_MAX."""
    flat = []
    for text, p0, p1 in atoms:
        if len(text) > HARD_MAX:  # pathological entry: fall back to sentence-aligned split
            flat += [(t, a, b) for t, a, b in pack_prose([(text, p0, p1)])]
        else:
            flat.append((text, p0, p1))
    chunks, cur = [], []
    def size(c): return sum(len(x[0]) for x in c) + max(len(c) - 1, 0)
    for a in flat:
        if cur and size(cur) + 1 + len(a[0]) > MAX_C:
            chunks.append(cur); cur = []
        cur.append(a)
    if cur:
        chunks.append(cur)
    return [("\n".join(x[0] for x in c), min(x[1] for x in c), max(x[2] for x in c)) for c in chunks]


# ---------------------------------------------------------------- PDF extraction
def _lines(page):
    """Yield (text, size, bold, y0, y1, block_no) per text line using dict mode."""
    for bi, b in enumerate(page.get_text("dict")["blocks"]):
        for l in b.get("lines", []):
            spans = [s for s in l["spans"] if s["text"].strip()]
            if not spans:
                continue
            txt = clean("".join(s["text"] for s in l["spans"]))
            if not txt or txt in {"•", "-", "o"}:
                continue
            size = max(s["size"] for s in spans)
            bold = all((s["flags"] & 16) or "bold" in s["font"].lower() for s in spans)
            yield dict(text=txt, size=size, bold=bold, y0=l["bbox"][1], y1=l["bbox"][3], block=bi)


def repeated_furniture(doc) -> set[str]:
    """Normalised line texts in the top/bottom 9% band that repeat on >= 40% of pages."""
    cnt = Counter()
    for page in doc:
        h = page.rect.height
        seen = set()
        for ln in _lines(page):
            if ln["y1"] < 0.09 * h or ln["y0"] > 0.91 * h:
                seen.add(re.sub(r"\d+", "#", ln["text"].lower()))
        cnt.update(seen)
    need = max(2, int(0.4 * len(doc)))
    return {k for k, v in cnt.items() if v >= need}


def pdf_pages(path: Path):
    """Return (pages, body_size) where pages = [[line,...]] with furniture / page numbers removed."""
    import pymupdf
    doc = pymupdf.open(path)
    furn = repeated_furniture(doc)
    sizes, pages = Counter(), []
    for pno, page in enumerate(doc, 1):
        h = page.rect.height
        out = []
        for ln in _lines(page):
            key = re.sub(r"\d+", "#", ln["text"].lower())
            edge = ln["y1"] < 0.09 * h or ln["y0"] > 0.91 * h
            if key in furn and edge:
                continue
            if edge and re.fullmatch(r"(page )?\d+( of \d+)?|[ivx]+", ln["text"].lower()):
                continue
            if re.search(r"\.{8,}", ln["text"]):  # TOC leader dots
                continue
            ln["page"] = pno
            sizes[round(ln["size"], 1)] += len(ln["text"])
            out.append(ln)
        pages.append(out)
    body = sizes.most_common(1)[0][0] if sizes else 10.0
    return pages, body


def is_heading(ln, body) -> bool:
    t = ln["text"]
    if len(t) > 130 or len(t) < 3 or t.endswith((".", ",", ";", ":")) and not re.match(r"^\d", t):
        return False
    if not re.search(r"[A-Za-z]{3}", t) or re.match(r"^(table|figure|exhibit)\s+[\dA-Z]+[.:]?\s", t, re.I):
        return False
    if re.fullmatch(r"[\d.,%\s()\-]+", t):
        return False
    if ln["size"] >= body + 1.2:
        return True
    if not ln["bold"]:
        return False
    # bold-only (body-size) lines are often table header cells: require a heading-like shape
    if re.search(r"[%()\d]{1}", t) and not re.match(r"^(\d+(\.\d+)*\.?|[A-Z]\.|Appendix|Step|Section|Part)", t):
        return False
    return len(t.split()) >= 2


def generic_pdf_sections(path: Path):
    """Heading-delimited sections of paragraphs. Paragraph = consecutive lines of one PDF block."""
    pages, body = pdf_pages(path)
    sections = []  # [title, atoms, last_page]
    cur = ["(front matter)", []]
    sections.append(cur)
    pend = None  # paragraph being accumulated: [text, p0, p1, block, page]
    def flush():
        nonlocal pend
        if pend and pend[0].strip():
            cur[1].append((pend[0].strip(), pend[1], pend[2]))
        pend = None
    prev_head = None
    for lines in pages:
        for ln in lines:
            if is_heading(ln, body):
                flush()
                # merge consecutive heading lines of the same block (wrapped headings)
                if prev_head is not None and prev_head[1] == (ln["page"], ln["block"]) and not cur[1]:
                    cur[0] = cur[0] + " " + ln["text"]
                else:
                    cur = [ln["text"], []]; sections.append(cur)
                prev_head = (cur, (ln["page"], ln["block"]))
                continue
            prev_head = None
            key = (ln["page"], ln["block"])
            if pend and pend[3] == key:
                pend[0] += " " + ln["text"]
            else:
                # paragraph continued across a page break (previous ended without terminal punctuation)
                if pend and pend[4] != ln["page"] and not re.search(r"[.!?:]$", pend[0]) and ln["text"][:1].islower():
                    pend[0] += " " + ln["text"]; pend[2] = ln["page"]; pend[3] = key; pend[4] = ln["page"]
                    continue
                flush()
                pend = [ln["text"], ln["page"], ln["page"], key, ln["page"]]
        # paragraph stays pending across the page boundary
    flush()
    return merge_stubs([(t, "prose", a) for t, a in sections if a])


def merge_stubs(secs, min_chars: int = 150):
    """A section with < min_chars of body text is almost always a table cell / label that looked like a
    heading: fold it (heading as run-in text) into the preceding section."""
    out = []
    for t, k, a in secs:
        body = sum(len(x[0]) for x in a)
        if out and body < min_chars and k == "prose" and out[-1][1] == "prose":
            out[-1][2].append((f"{t}: " + " ".join(x[0] for x in a), a[0][1], a[-1][2]))
        else:
            out.append((t, k, list(a)))
    return out


def dictionary_sections(path: Path):
    """CMS data dictionary: 'Name' blocks = dataset descriptions (prose), 'Table' blocks = column lists,
    'Measure ID / Measure Name' blocks = measure lists. Entries are atoms; repeated page-top table headers merged."""
    pages, body = pdf_pages(path)
    seq = [ln for p in pages for ln in p]
    sections, cur = [], None
    def start(title, kind):
        nonlocal cur
        cur = dict(title=title, kind=kind, atoms=[], lines=[])
        sections.append(cur)
    start("Introduction", "prose")
    dtype = re.compile(r"^(Char|Num|Date|Memo)(\(\d+\))?$", re.I)
    idlike = re.compile(r"^[A-Za-z][A-Za-z0-9]*([_\-/][A-Za-z0-9]+)+[a-z]?$|^[A-Z]{2,}[0-9]*$")
    i, n = 0, len(seq)
    last_table = None
    while i < n:
        ln = seq[i]; t = ln["text"]; nxt = seq[i + 1]["text"] if i + 1 < n else ""
        if t == "Table" and nxt:
            title = nxt
            i += 2
            if title == last_table:  # same table continuing onto a new page: skip repeated header
                while i < n and seq[i]["text"] in ("Description", "File Name", "Data Type", "Column Name - CSV") or (
                        i < n and i >= 1 and seq[i - 1]["text"] in ("Description", "File Name") and not dtype.match(seq[i]["text"])):
                    i += 1
                continue
            last_table = title
            start(f"Table: {title}", "table")
            cur["header"] = []
            continue
        if t == "Name" and nxt and not (cur and cur["kind"] == "measures"):
            start(nxt, "prose"); last_table = None; i += 2; continue
        if t == "Name" and nxt:
            start(nxt, "prose"); last_table = None; i += 2; continue
        if t == "Measure ID" and nxt == "Measure Name":
            prev = cur["lines"][-1]["text"] if cur["lines"] else ""
            if cur["kind"] == "measures" and not re.search(r"\.csv$", prev, re.I):
                i += 2; continue  # repeated column header at the top of a continuation page
            if re.search(r"\.csv$", prev, re.I):
                cur["lines"].pop()
                start(f"Measure list: {prev}", "measures")
            else:
                start("Measure list", "measures")
            last_table = None; i += 2; continue
        if t == "Acronym" and nxt == "Meaning":
            start("Acronym Index", "measures"); i += 2; continue
        if ln["bold"] and ln["size"] >= body + 2 and len(t) < 90 and not t.endswith(".") and not (
                nxt == "Measure ID" and t.lower().endswith(".csv")):
            start(t, "prose"); last_table = None; i += 1; continue
        cur["lines"].append(ln)
        i += 1

    out = []
    for s in sections:
        L = s["lines"]
        if not L:
            continue
        pg = lambda a: (a[0]["page"], a[-1]["page"])
        if s["kind"] == "prose":
            text = clean(" ".join(x["text"] for x in L))
            out.append((s["title"], "prose", [(text, *pg(L))]))
        elif s["kind"] == "table":
            atoms, hdr, j = [], [], 0
            while j < len(L) and not (dtype.match(L[j]["text"])):
                hdr.append(L[j]); j += 1
            hdr_txt = re.sub(r"\s*Data Type Column Name - CSV\s*$", "", clean(" ".join(x["text"] for x in hdr)))
            if hdr_txt:
                atoms.append((hdr_txt, *pg(hdr)))
            fields = []
            while j < len(L):
                if dtype.match(L[j]["text"]) and j + 1 < len(L):
                    fields.append((L[j]["text"], L[j + 1]["text"], L[j]["page"])); j += 2
                else:
                    j += 1
            # group consecutive fields that belong to one measure (leading token = measure-id-like) into one atom
            groups, key_prev = [], None
            for dt, name, pgno in fields:
                first = name.split(" ")[0]
                key = first if (re.search(r"\d", first) and re.search(r"[-_]", first)) else None
                if groups and key and key == key_prev:
                    groups[-1].append((dt, name, pgno))
                else:
                    groups.append([(dt, name, pgno)])
                key_prev = key
            for g in groups:
                atoms.append(("; ".join(f"{nm} ({dt})" for dt, nm, _ in g), g[0][2], g[-1][2]))
            out.append((s["title"], "table", atoms))
        else:  # measures: (id, name...) pairs
            atoms, k = [], 0
            while k < len(L):
                if idlike.match(L[k]["text"]) and len(L[k]["text"]) <= 40:
                    j = k + 1
                    while j < len(L) and not (idlike.match(L[j]["text"]) and len(L[j]["text"]) <= 40):
                        j += 1
                    name = clean(" ".join(x["text"] for x in L[k + 1:j]))
                    atoms.append((f"{L[k]['text']}: {name}", L[k]["page"], L[j - 1]["page"]))
                    k = j
                else:
                    atoms.append((L[k]["text"], L[k]["page"], L[k]["page"])); k += 1
            out.append((s["title"], "table", atoms))
    return out


# ---------------------------------------------------------------- HTML extraction (no HTML sources at present)
def html_sections(path: Path):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(path.read_bytes(), "lxml")
    for t in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        t.decompose()
    root = soup.find("main") or soup.body or soup
    sections, cur = [], ["(page)", "prose", []]
    sections.append(cur)
    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"]):
        if el.name in ("h1", "h2", "h3", "h4"):
            cur = [clean(el.get_text(" ")), "prose", []]; sections.append(cur)
        elif el.name == "table":
            rows = [clean(" | ".join(c.get_text(" ") for c in tr.find_all(["th", "td"]))) for tr in el.find_all("tr")]
            cur[1] = "table" if len(rows) > 3 and not cur[2] else cur[1]
            cur[2] += [(r, 0, 0) for r in rows if r]
        elif el.find_parent("table") is None:
            txt = clean(el.get_text(" "))
            if txt:
                cur[2].append((txt, 0, 0))
    return [(t, k, a) for t, k, a in sections if a]


# ---------------------------------------------------------------- main
def load_measure_ids() -> list[str]:
    with open(MEASURES_CSV, newline="", encoding="utf-8") as f:
        return sorted({r["measure_id"] for r in csv.DictReader(f)})


def find_measures(text: str, patterns: list[tuple[str, re.Pattern]]) -> list[str]:
    T = norm_id(text)
    return [mid for mid, pat in patterns if pat.search(T)]


def main():
    ids = load_measure_ids()
    sep = norm_id("_")
    patterns = [(m, re.compile(r"(?<![A-Z0-9])" + r"[\s_\-]*".join(re.escape(part) for part in norm_id(m).split(sep)) + r"(?![A-Z0-9])")) for m in ids]
    docs = json.loads(MANIFEST.read_text("utf-8"))["documents"]
    n_out, dropped = 0, 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as fo:
        for d in docs:
            path = RAW / d["file"]
            is_pdf = path.suffix == ".pdf"
            if d["doc_id"] == DICT_DOC:
                secs = dictionary_sections(path)
            elif is_pdf:
                secs = generic_pdf_sections(path)
            else:
                secs = html_sections(path)
            idx = 0
            for title, kind, atoms in secs:
                packed = pack_table(atoms) if kind == "table" else pack_prose(atoms)
                for text, p0, p1 in packed:
                    text = text.strip()
                    letters = sum(c.isalpha() for c in text)
                    if not text or letters < 0.3 * len(text) or letters < 20:  # numeric-table debris
                        dropped += 1; continue
                    rec = dict(chunk_id=f"{d['doc_id']}:{idx}", doc_id=d["doc_id"], doc_title=d["title"],
                               source_url=d["source_url"], section_title=title,
                               page_start=p0 if is_pdf else None, page_end=p1 if is_pdf else None,
                               text=text, n_chars=len(text), measure_ids=find_measures(text, patterns))
                    fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); idx += 1; n_out += 1
            print(f"{d['doc_id']:36s} {idx:5d} chunks")
    print(f"total {n_out} chunks (dropped {dropped} numeric-debris chunks) -> {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    sys.exit(main())

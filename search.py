"""Retrieval over the indexed catalogues: FTS5 keyword search, part-reference
lookup, query understanding and example-image matching.

Ranking is a two-stage affair. FTS5 `bm25()` produces a candidate set with
column weights (a reference hit counts far more than a word of prose), then a
Python rescoring pass folds in signals BM25 cannot see: how many of the query's
content words actually appear, whether the user named a system (70TH / 32TH /
45TH), whether the page carries drawings, and how much text the page has.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path

import numpy as np

import embed
import imgutil
from indexer import DB_PATH, PDF_DIR, norm_ref, sanitize

# --------------------------------------------------------------------------
# domain vocabulary
# --------------------------------------------------------------------------
# These catalogues are French products documented in English, and customers ask
# in both languages using trade names. Expanding a query along these groups is
# what turns "lift and slide seal" into a hit on "joint levant coulissant".
SYNONYMS: list[set[str]] = [
    {"frame", "dormant", "cadre", "outer"},
    {"sash", "ouvrant", "vantail", "leaf", "panel"},
    {"glazing", "bead", "parclose", "glass", "vitrage"},
    {"gasket", "seal", "joint", "weatherstrip", "weatherseal", "epdm"},
    {"brush", "broom", "brosse"},
    {"hinge", "paumelle", "charniere", "pivot"},
    {"lock", "serrure", "locking", "cremone", "espagnolette", "keep", "striker"},
    {"handle", "poignee", "bequille", "lever"},
    {"threshold", "seuil", "sill"},
    {"mullion", "meneau", "transom", "traverse", "post"},
    {"profile", "profil", "profile", "section", "extrusion"},
    {"crosssection", "section", "coupe", "sectional"},
    {"thermal", "thermique", "insulation", "isolation", "rpt", "break", "barrette"},
    {"lift", "levant", "liftslide", "levantcoulissant"},
    {"slide", "sliding", "coulissant", "coulissante"},
    {"roller", "galet", "chariot", "carriage", "wheel", "trolley"},
    {"rail", "track", "glissiere", "guide"},
    {"drainage", "drain", "evacuation", "weep", "water"},
    {"reinforcement", "renfort", "stiffener"},
    {"cleat", "equerre", "corner", "angle", "bracket"},
    {"screw", "vis", "fixing", "fastener"},
    {"machining", "usinage", "punching", "poinconnage", "drilling", "tooling", "tool"},
    {"assembly", "assemblage", "montage", "fabrication"},
    {"opening", "ouverture", "outward", "inward", "casement"},
    {"door", "porte"},
    {"window", "fenetre"},
    {"weight", "poids", "capacity", "load"},
    {"dimension", "size", "dimensions", "clearance", "tolerance"},
    {"accessory", "accessoire", "hardware", "quincaillerie"},
    {"aluminium", "aluminum", "alu"},          # US spelling finds the EU one
    {"colour", "color", "coloris", "finish", "ral", "anodised", "anodized", "lacquered"},
]

_SYN_INDEX: dict[str, set[str]] = {}
for _grp in SYNONYMS:
    for _w in _grp:
        _SYN_INDEX.setdefault(_w, set()).update(_grp)

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at", "is",
    "are", "was", "be", "with", "by", "from", "as", "it", "its", "this", "that",
    "what", "which", "how", "where", "when", "who", "why", "can", "do", "does",
    "i", "you", "we", "me", "my", "please", "show", "give", "tell", "need",
    "want", "find", "get", "there", "any", "some", "have", "has", "about",
    "le", "la", "les", "un", "une", "des", "du", "de", "et", "ou", "est",
    "pour", "avec", "sur", "dans", "quel", "quelle", "quelles", "quels",
    "comment", "ou", "que", "qui", "je", "vous", "nous", "il", "elle",
}

SYSTEM_ALIASES = {
    "COMETE 70TH": ("comete", "cometé", "70th", "70 th", "70-th"),
    "GALAXIE 32TH": ("galaxie 32", "32th", "32 th", "32-th"),
    "GALAXIE 45TH": ("galaxie 45", "45th", "45 th", "45-th", "lift and slide",
                     "lift & slide", "liftslide", "levant"),
}

# Category-level words: a whole product family, not a component. Asking one of
# these alone is a browsing question, so we offer facets instead of guessing.
BROAD_TERMS = {
    "door", "doors", "porte", "portes", "window", "windows", "fenetre", "fenetres",
    "aluminium", "aluminum", "alu", "metal", "steel",
    "profile", "profiles", "profil", "profiles", "section", "sections",
    "system", "systems", "systeme", "systemes", "range", "ranges", "gamme", "gammes",
    "product", "products", "produit", "produits", "solution", "solutions",
    "hardware", "accessory", "accessories", "accessoire", "accessoires",
    "spec", "specs", "specification", "specifications", "performance", "performances",
    "type", "types", "model", "models", "modele", "option", "options",
    "frame", "frames", "sliding", "coulissant", "installux",
}

# a token found on more than this share of pages cannot narrow anything down
COMMON_TOKEN_SHARE = 0.30

DRAWING_WORDS = {
    "drawing", "drawings", "section", "crosssection", "cross", "figure",
    "diagram", "detail", "sketch", "plan", "coupe", "schema", "image",
    "images", "photo", "picture", "illustration", "visual", "look", "see",
}


# --------------------------------------------------------------------------
# db helpers
# --------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def index_exists() -> bool:
    if not DB_PATH.exists():
        return False
    try:
        conn = _connect()
        n = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        conn.close()
        return n > 0
    except sqlite3.Error:
        return False


# --------------------------------------------------------------------------
# query understanding
# --------------------------------------------------------------------------
def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z0-9]+", text.lower()) if len(t) > 1]


def content_tokens(text: str) -> list[str]:
    return [t for t in tokens(text) if t not in STOPWORDS]


def variants(tok: str) -> list[str]:
    """The word plus its singular. Customers type "doors", the workbook says
    "DOOR", and an FTS prefix match only ever grows a word — never shortens it."""
    out = [tok]
    if len(tok) > 4 and tok.endswith("ies"):
        out.append(tok[:-3] + "y")
    elif len(tok) > 4 and tok.endswith(("ses", "xes", "ches", "shes")):
        out.append(tok[:-2])
    elif len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        out.append(tok[:-1])
    return out


def expand(toks: list[str]) -> list[str]:
    """Add the singular form, trade synonyms and the other language's term."""
    out: list[str] = []
    for t in toks:
        for v in variants(t):
            if v not in out:
                out.append(v)
            for syn in sorted(_SYN_INDEX.get(v, ())):
                if syn not in out:
                    out.append(syn)
    return out


def parse_counts(question: str) -> tuple[int | None, int | None]:
    """Read 'show me 3 images' / '5 results' out of the question text."""
    q = question
    max_images = max_pages = None
    m = re.search(r"(\d{1,2})\s*(?:images?|img|drawings?|pictures?|photos?|"
                  r"illustrations?|figures?|sections?)\b", q, re.I)
    if m:
        max_images = int(m.group(1))
    m = re.search(r"(\d{1,2})\s*(?:answers?|results?|pages?|hits?|entries?|rows?|options?)\b", q, re.I)
    if m:
        max_pages = int(m.group(1))
    return max_pages, max_images


def detect_system(question: str) -> str | None:
    """Which product system the user named, if any."""
    q = " " + re.sub(r"[^a-z0-9&\s]", " ", question.lower()) + " "
    q = re.sub(r"\s+", " ", q)
    for system, aliases in SYSTEM_ALIASES.items():
        for a in aliases:
            if a in q:
                return system
    return None


# Brand and model codes identify *which system* the customer means; they are never
# the thing being asked about. "doors galaxie 32th" is a question about doors,
# narrowed to the 32TH — not a question about the words "galaxie" and "32th".
_SYSTEM_TOKEN_RE = re.compile(r"^(?:comete|comet|galaxie|installux|\d{2}th)$")


def is_system_token(tok: str) -> bool:
    return bool(_SYSTEM_TOKEN_RE.match(tok))


def split_subject(question: str) -> tuple[list[str], list[str]]:
    """Separate what is being asked about from which system it is asked about.

    Returns (subject_tokens, system_tokens). A part is relevant because it
    matches the subject; the system only filters and ranks.
    """
    subject, sys_toks = [], []
    for t in content_tokens(question):
        (sys_toks if is_system_token(t) else subject).append(t)
    return subject, sys_toks


def wants_drawings(question: str) -> bool:
    return bool(set(tokens(question)) & DRAWING_WORDS)


# --------------------------------------------------------------------------
# FTS query building
# --------------------------------------------------------------------------
def _quote(tok: str) -> str:
    return '"' + tok.replace('"', '""') + '"'


def _fts_or(toks: list[str], prefix: bool = True) -> str:
    if not toks:
        return ""
    star = "*" if prefix else ""
    return " OR ".join(f"{_quote(t)}{star}" for t in toks)


def _fts_and(toks: list[str]) -> str:
    if not toks:
        return ""
    return " AND ".join(f"{_quote(t)}*" for t in toks)


def _run_fts(conn, match: str, limit: int) -> list[sqlite3.Row]:
    if not match:
        return []
    try:
        return conn.execute(
            """SELECT p.id, p.doc_id, p.page_num, p.text, p.ocr_text, p.refs, p.summary,
                      d.filename, d.title, d.system, d.systems, d.doc_kind,
                      bm25(pages_fts, 1.0, 8.0, 3.0, 1.5) AS bm
               FROM pages_fts
               JOIN pages p ON p.id = pages_fts.rowid
               JOIN documents d ON d.id = p.doc_id
               WHERE pages_fts MATCH ?
               ORDER BY bm
               LIMIT ?""",
            (match, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []


# Some of these PDFs embed subset fonts with broken ToUnicode maps, so PyMuPDF
# returns junk: private-use glyphs, and C1 control bytes that look
# like text but render as nothing. Keep printable ASCII, Latin-1/Extended and
# ordinary punctuation; drop the rest.
_JUNK_CHAR = re.compile(r"[^\t\n\r\x20-\x7E\xA0-\u024F\u2010-\u203A\u20AC]+")


# A second failure mode in these PDFs: the glyph map is offset, so text comes out
# as Latin-1 look-alikes — "a wide choice of 2 or 3 track" arrives as
# "> \u00dc `i V Vi v \u00d3 \u00c0 \u00ce \u00cc\u00c0>V". Real English and French never put an accented
# capital inside a word, so that is the signal; the one-character fragments
# around it are swept up with it.
_ACC_CAPS = "\u00c0\u00c1\u00c2\u00c3\u00c4\u00c5\u00c6\u00c7\u00c8\u00c9\u00ca\u00cb\u00cc\u00cd\u00ce\u00cf\u00d0\u00d1\u00d2\u00d3\u00d4\u00d5\u00d6\u00d8\u00d9\u00da\u00db\u00dc\u00dd\u00de"
_SYMBOL_ONLY = re.compile(r"^[^0-9A-Za-z\u00c0-\u024f]+$")
_WORDY = re.compile(r"^[" + _ACC_CAPS + r"]?[a-z\u00e0-\u00ff'’-]+$")

JUNK, NEUTRAL, CLEAN = 0, 1, 2


def _classify(tok: str) -> int:
    """JUNK = mis-decoded, NEUTRAL = too short to judge, CLEAN = real text."""
    if not tok:
        return NEUTRAL
    if any(c in _ACC_CAPS for c in tok):
        # legitimate only as "Épaisseur": one leading accented capital, then a word
        return CLEAN if _WORDY.match(tok) and len(tok) >= 3 else JUNK
    if len(tok) <= 2:
        return NEUTRAL
    if _SYMBOL_ONLY.match(tok):
        return NEUTRAL
    return CLEAN


def clean_text(text: str) -> str:
    """Drop mis-decoded glyphs and the whitespace they leave behind."""
    text = _JUNK_CHAR.sub(" ", text)
    out_lines = []
    for line in text.split("\n"):
        toks = line.split(" ")
        kinds = [_classify(t) for t in toks]
        keep, run, junk_in_run = [], [], 0
        for tok, kind in zip(toks, kinds):
            if kind == CLEAN:
                if junk_in_run < 2:
                    keep.extend(run)          # a stray accent, not a garbled run
                keep.append(tok)
                run, junk_in_run = [], 0
            else:
                run.append(tok)
                junk_in_run += kind == JUNK
        if junk_in_run < 2:
            keep.extend(run)
        out_lines.append(" ".join(t for t in keep if t))
    return re.sub(r"[ \t]{2,}", " ", "\n".join(out_lines))


def make_snippet(text: str, terms: list[str], maxlen: int = 420) -> str:
    text = clean_text(re.sub(r"[ \t]+", " ", text)).strip()
    if not text:
        return ""
    low = text.lower()
    pos = [low.find(t) for t in terms]
    pos = [p for p in pos if p >= 0]
    start = max(0, (min(pos) if pos else 0) - 100)
    out = text[start:start + maxlen].replace("\n", " ").strip()
    if start > 0:
        out = "…" + out
    if start + maxlen < len(text):
        out += "…"
    return out


def search_pages(question: str, limit: int = 8, system: str | None = None) -> list[dict]:
    """Rank catalogue pages for a question. Scores are 0-100, higher is better."""
    base = content_tokens(question) or tokens(question)
    if not base:
        return []
    expanded = expand(base)
    system = system or detect_system(question)
    refs = [norm_ref(t) for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9./-]{1,}", question)]

    conn = _connect()
    pool = max(limit * 6, 40)
    # strictest query first; each fallback widens the net
    rows = _run_fts(conn, _fts_and(base), pool)
    strict_ids = {r["id"] for r in rows}
    if len(rows) < pool:
        seen = set(strict_ids)
        for r in _run_fts(conn, _fts_or(expanded), pool):
            if r["id"] not in seen:
                seen.add(r["id"])
                rows.append(r)

    # Dense recall: pages that mean the right thing without sharing a word. It is
    # skipped for reference codes — "10x2" has no semantic content, so its nearest
    # neighbours are arbitrary pages that would then be ranked as confident hits.
    sem = {} if is_reference_query(question) else semantic_hits(question, k=max(limit, 15))
    have = {r["id"] for r in rows}
    extra = [pid for pid in sem if pid not in have]
    if extra:
        marks = ",".join("?" * len(extra))
        rows.extend(conn.execute(
            f"""SELECT p.id, p.doc_id, p.page_num, p.text, p.ocr_text, p.refs, p.summary,
                       d.filename, d.title, d.system, d.systems, d.doc_kind,
                       0.0 AS bm
                FROM pages p JOIN documents d ON d.id = p.doc_id
                WHERE p.id IN ({marks})""", extra).fetchall())
    conn.close()
    if not rows:
        return []

    bms = [r["bm"] for r in rows if r["bm"] < 0] or [0.0]
    best, worst = min(bms), max(bms)
    span = (worst - best) or 1.0

    results = []
    for r in rows:
        body = (r["text"] or "") + " " + (r["ocr_text"] or "")
        text_low = body.lower()
        # 0..1 from BM25 (SQLite bm25 is negative; more negative == better)
        score = (worst - r["bm"]) / span if r["bm"] < 0 else 0.0
        cos = sem.get(r["id"])
        if cos is not None:
            score += 1.4 * max(0.0, cos)      # dense similarity, comparable weight

        hits = sum(1 for t in base if t in text_low)
        coverage = hits / len(base)
        score += 0.9 * coverage
        if r["id"] in strict_ids:
            score += 0.35                                    # every word present
        if len(base) > 1 and " ".join(base) in text_low:
            score += 0.4                                     # exact phrase
        syn_hits = sum(1 for t in expanded if t not in base and t in text_low)
        score += 0.06 * min(syn_hits, 5)

        doc_systems = set(json.loads(r["systems"] or "[]")) | {r["system"]}
        if system:
            score += 0.8 if system in doc_systems else -0.45
        ref_hit = bool(refs and r["refs"] and set(r["refs"].split()) & set(refs))
        if ref_hit:
            score += 1.2
        if len(body.strip()) < 120:
            score -= 0.25                                    # near-empty divider page

        stem = sanitize(r["filename"].rsplit(".", 1)[0].replace("/", "_"))
        results.append({
            "page_id": r["id"],
            "doc_id": r["doc_id"],
            "filename": r["filename"],
            "title": r["title"],
            "system": r["system"],
            "systems": sorted(doc_systems),
            "doc_kind": r["doc_kind"],
            "page_num": r["page_num"],
            "raw_score": round(score, 3),
            "coverage": round(coverage, 2),
            "ref_hit": ref_hit,
            "snippet": make_snippet(r["text"] or r["ocr_text"] or "", expanded),
            "has_ocr": bool((r["ocr_text"] or "").strip()),
            "semantic": round(cos, 3) if cos is not None else None,
            "summary": (r["summary"] or "").strip(),
            "refs": (r["refs"] or "").split(),
            "page_image": f"pages/{stem}/p{r['page_num']:03d}.png",
            "thumb": f"pages/{stem}/p{r['page_num']:03d}_thumb.png",
        })

    # "show me the cross-section" should favour pages that actually carry drawings
    if wants_drawings(question) and results:
        conn = _connect()
        counts = {
            (r["doc_id"], r["page_num"]): r["n"]
            for r in conn.execute(
                "SELECT doc_id, page_num, COUNT(*) AS n FROM figures "
                "WHERE kind = 'drawing' GROUP BY doc_id, page_num")
        }
        conn.close()
        for d in results:
            n = counts.get((d["doc_id"], d["page_num"]), 0)
            d["figure_count"] = n
            if n:
                d["raw_score"] += 0.25 + 0.08 * min(n, 4)

    results.sort(key=lambda d: -d["raw_score"])
    # The displayed percentage is evidence, not rank. Normalising to the best hit
    # made the top row read "100%" even when it contained none of the query — the
    # customer could not tell a real match from the least-bad one.
    for d in results:
        conf = d["coverage"]                       # share of query words present
        if d["ref_hit"]:
            conf = 1.0                             # the page names the reference
        if d["semantic"] is not None:
            # a purely semantic hit is a suggestion, never a certainty
            conf = max(conf, min(0.75, d["semantic"]))
        d["score"] = max(0, min(100, round(100 * conf)))
        d["supported"] = d["coverage"] > 0 or d["ref_hit"]

    # For a part number there is no "close enough": either the page names it or it
    # does not, so unsupported pages are dropped rather than shown at a low score.
    if is_reference_query(question):
        results = [d for d in results if d["supported"]]
    return results[:limit]


def build_context(pages: list[dict], max_chars: int = 12000) -> str:
    """Evidence block handed to the LLM. Page text beats summary: these pages are
    short, and the exact dimensions the customer needs live in the raw text."""
    chunks, total = [], 0
    conn = _connect()
    for p in pages:
        row = conn.execute("SELECT text, ocr_text FROM pages WHERE id = ?",
                           (p["page_id"],)).fetchone()
        body = ((row["text"] if row else "") or "").strip()
        ocr = ((row["ocr_text"] if row else "") or "").strip()
        if ocr and len(ocr) > len(clean_text(body)):
            # the page render was more legible than the embedded text layer
            body = ocr
        elif ocr:
            body = f"{body}\n{ocr}"
        body = body or p.get("snippet", "")
        body = re.sub(r"\n{3,}", "\n\n", clean_text(body)).strip()
        if len(body) > 2600:
            body = body[:2600] + "…"
        if not body:
            continue
        head = f"[{p['system']} · {Path(p['filename']).name} · p.{p['page_num']} ({p['doc_kind']})]"
        block = f"{head}\n{body}"
        if total + len(block) > max_chars:
            break
        chunks.append(block)
        total += len(block)
    conn.close()
    return "\n\n".join(chunks)


def signature(pages: list[dict]) -> str:
    return "|".join(f"{p['filename']}@{p['page_num']}" for p in pages)


# --------------------------------------------------------------------------
# dense vectors
# --------------------------------------------------------------------------
_vec_cache: dict | None = None
_vec_lock = threading.Lock()


def _page_vectors() -> tuple[list[int], np.ndarray]:
    """Every stored page vector as one matrix, cached until the index changes."""
    global _vec_cache
    stamp = DB_PATH.stat().st_mtime_ns if DB_PATH.exists() else 0
    with _vec_lock:
        if _vec_cache is not None and _vec_cache["stamp"] == stamp:
            return _vec_cache["ids"], _vec_cache["mat"]
        ids: list[int] = []
        vecs: list[np.ndarray] = []
        try:
            conn = _connect()
            rows = conn.execute(
                "SELECT id, vec FROM pages WHERE vec IS NOT NULL ORDER BY id").fetchall()
            conn.close()
        except sqlite3.Error:
            rows = []
        dim = None
        for r in rows:
            v = embed.from_b64(r["vec"])
            if v is None or (dim is not None and v.size != dim):
                continue
            dim = v.size
            ids.append(r["id"])
            vecs.append(v)
        mat = np.vstack(vecs) if vecs else np.zeros((0, 0), dtype=np.float32)
        _vec_cache = {"stamp": stamp, "ids": ids, "mat": mat}
        return ids, mat


def has_vectors() -> bool:
    return len(_page_vectors()[0]) > 0


def semantic_hits(question: str, k: int = 15) -> dict[int, float]:
    """page_id -> cosine similarity, for the k nearest pages. {} if unavailable."""
    ids, mat = _page_vectors()
    if not ids:
        return {}
    q = embed.encode([question])
    if q is None or q.shape[1] != mat.shape[1]:
        return {}
    sims = mat @ q[0]
    top = np.argsort(-sims)[:k]
    return {ids[i]: float(sims[i]) for i in top}


# --------------------------------------------------------------------------
# highlighting
# --------------------------------------------------------------------------
_doc_cache: dict[str, object] = {}


def highlight_terms(question: str, exact: dict | None = None) -> list[str]:
    """Words to mark in results: what the customer typed, plus the trade synonyms
    that actually made a page match, plus any part reference they named."""
    base = content_tokens(question)
    terms: list[str] = []
    if exact and exact.get("ref"):
        terms.append(exact["ref"])
        for word in tokens(exact.get("designation") or ""):
            if word not in STOPWORDS and len(word) > 2:
                terms.append(word)
    terms.extend(base)
    # a hit on "broom seal" should light up when the customer asked "joint brosse"
    terms.extend(t for t in expand(base) if t not in base)
    seen, out = set(), []
    for t in terms:
        key = t.lower()
        if key not in seen and len(key) > 2:
            seen.add(key)
            out.append(t)
    return out


def _ocr_rects(doc_id: int, page_num: int, terms: list[str],
               budget: int) -> list[list[float]]:
    """Highlight boxes recovered from OCR, for pages the text layer cannot search."""
    if budget <= 0:
        return []
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT text, x, y, w, h FROM ocr_boxes WHERE doc_id = ? AND page_num = ?",
            (doc_id, page_num)).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    if not rows:
        return []
    lowered = [t.lower() for t in terms if len(t) > 2]
    out: list[list[float]] = []
    for r in rows:
        hay = (r["text"] or "").lower()
        if any(t in hay for t in lowered):
            out.append([r["x"], r["y"], r["w"], r["h"]])
            if len(out) >= budget:
                break
    return out


def highlight_rects(filename: str, page_num: int, terms: list[str],
                    doc_id: int | None = None,
                    max_rects: int = 60) -> list[list[float]]:
    """Where the query words sit on the page, as [x, y, w, h] fractions 0-1.

    The UI overlays these on the page image and on any drawing cut from it, so the
    customer can see *why* a page was returned without reading the whole sheet.

    Two sources: the PDF text layer, and — for the pages whose fonts are broken,
    where `search_for` can never match — the OCR word boxes recorded at index time.
    """
    if not terms:
        return []
    out: list[list[float]] = []
    wanted = [t for t in dict.fromkeys(terms) if len(t) > 2]
    try:
        import fitz
        path = (PDF_DIR / filename)
        if path.exists():
            doc = _doc_cache.get(filename)
            if doc is None:
                doc = fitz.open(path)
                _doc_cache[filename] = doc
            if 1 <= page_num <= len(doc):
                page = doc[page_num - 1]
                rect = page.rect
                if rect.width > 0 and rect.height > 0:
                    for term in wanted:
                        try:
                            found = page.search_for(term, quads=False)
                        except Exception:
                            continue
                        for r in found:
                            out.append([round((r.x0 - rect.x0) / rect.width, 5),
                                        round((r.y0 - rect.y0) / rect.height, 5),
                                        round(r.width / rect.width, 5),
                                        round(r.height / rect.height, 5)])
                            if len(out) >= max_rects:
                                return out
    except Exception:
        pass
    if doc_id is not None:
        out.extend(_ocr_rects(doc_id, page_num, wanted, max_rects - len(out)))
    return out


def marks_within(marks: list[list[float]], box: tuple[float, float, float, float],
                 min_overlap: float = 0.5) -> list[list[float]]:
    """Re-express page highlights inside a cropped figure, in crop fractions.

    A drawing card shows a slice of the page, so a page-level box has to be
    clipped to that slice and rescaled; boxes mostly outside it are dropped
    rather than shown clinging to an edge.
    """
    x0, y0, x1, y1 = box
    cw, ch = x1 - x0, y1 - y0
    if cw <= 0 or ch <= 0:
        return []
    out: list[list[float]] = []
    for mx, my, mw, mh in marks:
        ix0, iy0 = max(mx, x0), max(my, y0)
        ix1, iy1 = min(mx + mw, x1), min(my + mh, y1)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        area = (mx + mw - mx) * (my + mh - my) or 1e-9
        if ((ix1 - ix0) * (iy1 - iy0)) / area < min_overlap:
            continue
        out.append([round((ix0 - x0) / cw, 5), round((iy0 - y0) / ch, 5),
                    round((ix1 - ix0) / cw, 5), round((iy1 - iy0) / ch, 5)])
    return out


# --------------------------------------------------------------------------
# figures
# --------------------------------------------------------------------------
def figures_for_pages(pages: list[dict], limit: int = 12, per_page: int = 4) -> list[dict]:
    """Drawings and photos from the matched pages, biggest drawing first."""
    if not pages:
        return []
    conn = _connect()
    out: list[dict] = []
    for p in pages:
        if len(out) >= limit:
            break
        rows = conn.execute(
            """SELECT filename, thumb, kind, page_num, width, height, x0, y0, x1, y1
               FROM figures WHERE doc_id = ? AND page_num = ?
               ORDER BY CASE kind WHEN 'drawing' THEN 0 ELSE 1 END, area DESC
               LIMIT ?""",
            (p["doc_id"], p["page_num"], per_page),
        ).fetchall()
        for r in rows:
            # keyword boxes found on the page, clipped to this crop
            box = (r["x0"] or 0.0, r["y0"] or 0.0, r["x1"] or 0.0, r["y1"] or 0.0)
            marks = marks_within(p.get("highlights") or [], box) if box[2] > box[0] else []
            out.append({
                "url": f"/media/{r['filename']}",
                "thumb_url": f"/media/{r['thumb'] or r['filename']}",
                "kind": r["kind"],
                "page_num": r["page_num"],
                "filename": r["filename"].rsplit("/", 1)[-1],
                "doc": Path(p["filename"]).name,
                "system": p["system"],
                "page_image": p["page_image"],
                "highlights": marks,
            })
            if len(out) >= limit:
                break
    conn.close()
    return out


def all_figure_paths() -> list[str]:
    conn = _connect()
    rows = conn.execute("SELECT filename FROM figures ORDER BY filename").fetchall()
    conn.close()
    return [r["filename"] for r in rows]


# --------------------------------------------------------------------------
# image similarity (model-free)
# --------------------------------------------------------------------------
_desc_cache: dict | None = None
_desc_lock = threading.Lock()


def _descriptor_tables() -> dict:
    """Load every stored descriptor into numpy arrays once, keyed by DB mtime."""
    global _desc_cache
    stamp = DB_PATH.stat().st_mtime_ns if DB_PATH.exists() else 0
    with _desc_lock:
        if _desc_cache is not None and _desc_cache["stamp"] == stamp:
            return _desc_cache
        conn = _connect()
        fig_rows = conn.execute(
            "SELECT f.filename, f.thumb, f.kind, f.page_num, f.phash, f.dhash, f.edge,"
            "       d.filename AS doc, d.system, d.title "
            "FROM figures f JOIN documents d ON d.id = f.doc_id "
            "WHERE f.edge IS NOT NULL OR f.phash IS NOT NULL"
        ).fetchall()
        ref_rows = conn.execute(
            "SELECT ref, filename, phash, dhash, edge FROM ref_images "
            "WHERE edge IS NOT NULL OR phash IS NOT NULL"
        ).fetchall()
        conn.close()

        def pack(rows):
            ph = np.array([imgutil.hex_to_hash(r["phash"]) if r["phash"] else -1
                           for r in rows], dtype=object)
            dh = [imgutil.hex_to_hash(r["dhash"]) for r in rows]
            edges = np.zeros((len(rows), imgutil.EDGE_DIM), dtype=np.float32)
            for i, r in enumerate(rows):
                v = imgutil.edge_from_b64(r["edge"])
                if v is not None:
                    edges[i] = v
            return ph, dh, edges

        _desc_cache = {
            "stamp": stamp,
            "figures": (fig_rows, *pack(fig_rows)),
            "refs": (ref_rows, *pack(ref_rows)),
        }
        return _desc_cache


def _partial_image_results(upload_path: Path, max_results: int) -> list[dict] | None:
    """Sub-image search: patch embeddings for recall, keypoint geometry to verify.

    Whole-image hashes cannot answer "which page is this a piece of" — cropping
    changes the hash completely — so this runs first whenever the visual index
    has been built, and the hash matcher stays as the fallback.
    """
    try:
        import vismatch
    except Exception:
        return None
    if not vismatch.index_exists() or not vismatch.available():
        return None
    try:
        hits = vismatch.find(upload_path, max_results=max_results)
    except Exception as exc:
        import logging
        logging.getLogger("installux").warning("visual search failed: %s", str(exc)[:160])
        return None
    if not hits:
        return None

    out = []
    for h in hits:
        pct = round(100 * max(0.0, min(1.0, h["score"])))
        entry = {
            "similarity": pct,
            "match": bool(h["match"]),
            "inliers": h["inliers"] if h["inliers"] >= 0 else None,
            "method": "patch+keypoint",
        }
        if h.get("kind") == "part":
            entry.update(kind="part", ref=h.get("ref"),
                         image_url=f"/refmedia/{h['file']}",
                         thumb_url=f"/refmedia/{h['file']}",
                         page_num=None, doc=None, system=None, page_image=None)
        else:
            doc = h.get("doc") or ""
            stem = sanitize(doc.rsplit(".", 1)[0].replace("/", "_"))
            page = h.get("page_num")
            entry.update(kind="catalogue", ref=None,
                         image_url=f"/media/{h['file']}",
                         thumb_url=f"/media/{h['file']}",
                         page_num=page, doc=Path(doc).name if doc else None,
                         system=h.get("system"),
                         page_image=f"pages/{stem}/p{page:03d}.png" if page else None)
        out.append(entry)
    return out


def find_by_image(upload_path: Path, max_results: int = 8,
                  min_similarity: float = 0.85) -> list[dict]:
    """Catalogue figures and part photos that look like the uploaded image.

    Raises ValueError when the upload is not a readable image."""
    desc = imgutil.describe(upload_path)
    if desc is None:
        raise ValueError("unreadable image")

    partial = _partial_image_results(upload_path, max_results)
    if partial:
        return partial

    q_ph, q_dh, q_edge = desc

    tables = _descriptor_tables()
    scored: list[tuple[float, str, sqlite3.Row]] = []
    for kind, key in (("catalogue", "figures"), ("part", "refs")):
        rows, ph, dh, edges = tables[key]
        if not rows:
            continue
        sims = imgutil.similarity_bulk(q_ph, q_dh, q_edge, ph, dh, edges)
        for i in np.argsort(-sims)[: max_results * 4]:
            scored.append((float(sims[i]), kind, rows[i]))
    scored.sort(key=lambda t: -t[0])

    out = []
    for sim, kind, r in scored[:max_results]:
        pct = round(100 * sim)
        if kind == "part":
            out.append({
                "kind": "part", "ref": r["ref"],
                "image_url": f"/refmedia/{r['filename']}",
                "thumb_url": f"/refmedia/{r['filename']}",
                "similarity": pct, "match": sim >= min_similarity,
                "page_num": None, "doc": None, "system": None,
                "page_image": None,
            })
        else:
            stem = sanitize(r["doc"].rsplit(".", 1)[0].replace("/", "_"))
            out.append({
                "kind": "catalogue", "ref": None,
                "image_url": f"/media/{r['filename']}",
                "thumb_url": f"/media/{r['thumb'] or r['filename']}",
                "similarity": pct, "match": sim >= min_similarity,
                "page_num": r["page_num"], "doc": Path(r["doc"]).name,
                "system": r["system"],
                "page_image": f"pages/{stem}/p{r['page_num']:03d}.png",
            })
    return out


# --------------------------------------------------------------------------
# parts
# --------------------------------------------------------------------------
def _part_row(r, photo: str | None) -> dict:
    return {
        "ref": r["ref"], "kind": r["kind"],
        "designation": r["designation"] or "",
        "supplier_ref": (r["supplier_ref"] if "supplier_ref" in r.keys() else "") or "",
        "photo": photo,
    }


def _photo_for(conn, ref: str) -> str | None:
    row = conn.execute(
        "SELECT filename FROM ref_images WHERE ref_norm = ? LIMIT 1", (norm_ref(ref),)
    ).fetchone()
    return f"/refmedia/{row['filename']}" if row else None


def _merged_designation(conn, ref: str, primary: str) -> str:
    """One label per reference, not one per workbook sheet.

    1 421 of the 5 478 references appear twice — once in PROFILES under an
    English name and once in ACCESSORIES under a French one (533 is both
    "SEAL HOLDER" and "PORTE JOINT COULISSANT"). Showing a single sheet's
    wording hides the other, which is exactly how a false friend slips past a
    reader. Show both.
    """
    rows = conn.execute(
        "SELECT designation FROM parts WHERE ref_norm = ? AND length(trim(designation)) > 0",
        (norm_ref(ref),),
    ).fetchall()
    seen, names = set(), []
    for d in [primary] + [r["designation"] for r in rows]:
        d = (d or "").strip()
        key = re.sub(r"[^a-z0-9]", "", d.lower())
        if d and key and key not in seen:
            seen.add(key)
            names.append(d)
    return " · ".join(names[:2])


def lookup_part(ref: str) -> dict | None:
    """Exact reference lookup, tolerant of - / . separator differences."""
    key = norm_ref(ref)
    if not key:
        return None
    conn = _connect()
    row = conn.execute(
        "SELECT ref, kind, designation, supplier_ref FROM parts WHERE ref_norm = ? LIMIT 1",
        (key,),
    ).fetchone()
    if row:
        out = _part_row(row, _photo_for(conn, row["ref"]))
        conn.close()
        return out
    img = conn.execute(
        "SELECT ref, filename FROM ref_images WHERE ref_norm = ? LIMIT 1", (key,)
    ).fetchone()
    conn.close()
    if not img:
        return None
    # a photo on file with no workbook row is still a real, answerable part
    return {"ref": img["ref"], "kind": "part", "designation": "",
            "supplier_ref": "", "photo": f"/refmedia/{img['filename']}"}


# --------------------------------------------------------------------------
# positional reference patterns ("references ending in 000")
# --------------------------------------------------------------------------
# A trailing fragment is a *position*, not a substring: "ends with 000" must not
# return 150001, and "starts with 41" must not return 910041. Each pattern
# captures the fragment; the connector words differ between English and French.
_PATTERN_VALUE = r"[\"'`]?([A-Za-z0-9][A-Za-z0-9./-]*)"

# Alternatives are longest-first and closed with \b: without that, "end" matches
# inside "ending" and the fragment captured is "ing" rather than the digits.
# Accented forms are spelled with a class ("commen[cç]") because a plain literal
# 'c' does not match 'ç'.
_SUFFIX_VERBS = (r"ending|ends|ended|endings|end|finishing|finishes|finished|finish"
                 r"|terminating|terminates|terminated|terminate|termin\w+"
                 r"|finiss\w+|finit|suffixed|suffix")
_PREFIX_VERBS = (r"starting|starts|started|start|beginning|begins|began|begin"
                 r"|prefixed|prefix|commen[cç]\w+|d[eé]but\w+")
_CONTAIN_VERBS = (r"containing|contains|contain|including|includes|include"
                  r"|contenant|contient|comport\w+")

# Customers phrase position both ways round — "ending with 031" and "with 031 at
# the end" — so each mode carries a forward and a reverse form.
_REF_PATTERNS: list[tuple[str, tuple]] = [
    ("suffix", (
        re.compile(rf"\b(?:{_SUFFIX_VERBS})\b\s*"
                   r"(?:with|in|by|on|par|en|avec)?\s*" + _PATTERN_VALUE, re.I),
        re.compile(_PATTERN_VALUE + r"\s+(?:at|in|to)\s+the\s+end\b", re.I),
        re.compile(_PATTERN_VALUE + r"\s+(?:[aà]\s+la\s+fin)\b", re.I),
        re.compile(r"\b(?:last|final|dernier[se]?|derni[eè]res?)\s+(?:\d+\s+)?"
                   r"(?:digits?|characters?|chars?|numbers?|figures?|chiffres?)\s*"
                   r"(?:are|is|=|:)?\s*" + _PATTERN_VALUE, re.I),
    )),
    ("prefix", (
        re.compile(rf"\b(?:{_PREFIX_VERBS})\b\s*"
                   r"(?:with|by|par|en|avec)?\s*" + _PATTERN_VALUE, re.I),
        re.compile(_PATTERN_VALUE + r"\s+(?:at|in)\s+the\s+(?:start|beginning|front)\b", re.I),
        re.compile(_PATTERN_VALUE + r"\s+(?:au\s+d[eé]but)\b", re.I),
        re.compile(r"\b(?:first|leading|premier[se]?|premi[eè]res?)\s+(?:\d+\s+)?"
                   r"(?:digits?|characters?|chars?|numbers?|figures?|chiffres?)\s*"
                   r"(?:are|is|=|:)?\s*" + _PATTERN_VALUE, re.I),
    )),
    ("contains", (
        re.compile(rf"\b(?:{_CONTAIN_VERBS})\b\s*"
                   r"(?:the\s+)?(?:digits?|numbers?|characters?|chiffres?)?\s*"
                   + _PATTERN_VALUE, re.I),
        re.compile(_PATTERN_VALUE + r"\s+(?:in|somewhere\s+in)\s+the\s+middle\b", re.I),
        re.compile(_PATTERN_VALUE + r"\s+anywhere\s+in\b", re.I),
    )),
]

_PATTERN_KINDS = {
    "profile": {"profile", "profiles", "profil", "profils", "extrusion", "extrusions"},
    "accessory": {"accessory", "accessories", "accessoire", "accessoires", "hardware"},
}

_PATTERN_STOP = {"a", "an", "the", "it", "them", "this", "that", "any", "all",
                 "part", "parts", "ref", "reference", "references", "number",
                 "numbers", "digit", "digits", "piece", "pieces"}

# Words that mean "I am asking about a catalogue reference". Without one of
# these a bare number is far more likely to be a dimension or a quantity.
_REF_CONTEXT_WORDS = {
    "profile", "profiles", "profil", "profils", "profile's",
    "accessory", "accessories", "accessoire", "accessoires",
    "part", "parts", "piece", "pieces", "piece", "item", "items",
    "reference", "references", "ref", "refs", "referenced",
    "code", "codes", "number", "numbers", "numero", "numéro",
}

# System codes read like references but are product families, not parts
_SYSTEM_CODES = {"70TH", "32TH", "45TH", "26TH", "70", "32", "45", "26"}

_FRAGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./-]*")


def _implicit_fragment(question: str) -> dict | None:
    """"which profile has 031" — a partial reference, with no positional verb.

    Deliberately strict, because a bare number in a catalogue question is usually
    a dimension or a quantity. All of these must hold: the customer named a
    reference-ish noun (profile / accessory / part / ref), exactly one fragment
    of three or more characters contains a digit, it is not a system code, and it
    is not itself a real reference — an exact hit is answered by the exact path.
    """
    toks = set(tokens(question))
    if not toks & _REF_CONTEXT_WORDS:
        return None
    cands = []
    for raw in _FRAGMENT_RE.findall(question):
        frag = norm_ref(raw)
        if (len(frag) >= 3 and any(c.isdigit() for c in frag)
                and frag not in _SYSTEM_CODES
                and frag.lower() not in _PATTERN_STOP
                and frag not in cands):
            cands.append(frag)
    if len(cands) != 1:
        return None                     # ambiguous, or nothing reference-shaped
    value = cands[0]
    if lookup_part(value):
        return None                     # a real reference: let the exact path answer
    kinds = sorted(k for k, words in _PATTERN_KINDS.items() if toks & words)
    return {"mode": "contains", "value": value,
            "kind": kinds[0] if len(kinds) == 1 else None,
            "kinds": kinds, "implicit": True}


def parse_ref_pattern(question: str) -> dict | None:
    """Read 'references ending in 000' as (mode, fragment, kind), or None.

    Returns the *last* phrase that matches, so "profiles starting with 41" and
    "parts that end with 000" both resolve, and a bare mention of the word
    "contains" with no fragment is ignored.
    """
    for mode, rxs in _REF_PATTERNS:
        value = ""
        for rx in rxs:
            m = None
            for m in rx.finditer(question):
                pass                   # keep the last, closest to the fragment
            if not m:
                continue
            candidate = norm_ref(m.group(1))
            if not candidate or candidate.lower() in _PATTERN_STOP or len(candidate) > 12:
                continue
            # a reference fragment is digits, or a short code like "L" / "TC"
            if not (any(c.isdigit() for c in candidate) or len(candidate) <= 3):
                continue
            value = candidate
            break
        if not value:
            continue
        # "profiles or accessories" names both sheets — filtering to whichever was
        # written first would silently drop half the answer.
        toks = set(tokens(question))
        kinds = sorted(k for k, words in _PATTERN_KINDS.items() if toks & words)
        return {"mode": mode, "value": value,
                # one sheet named -> filter to it; none or both -> search everything
                "kind": kinds[0] if len(kinds) == 1 else None,
                "kinds": kinds}
    # no positional verb: "which profile has 031" still means a partial reference
    return _implicit_fragment(question)


_PATTERN_SQL = {
    "suffix": "ref_norm LIKE '%' || ?",
    "prefix": "ref_norm LIKE ? || '%'",
    "contains": "ref_norm LIKE '%' || ? || '%'",
}

_PATTERN_WORDS = {"suffix": "end with", "prefix": "start with", "contains": "contain"}


def refs_matching(pattern: dict, limit: int = 30) -> tuple[list[dict], int]:
    """(page of references matching the pattern, total number that match).

    De-duplicated by reference, because the workbook lists many of them twice —
    once per sheet. When the customer names one sheet ("profiles ending with
    031") the search stays inside it; otherwise it also covers the references
    that only exist as a part photo, so "all the possibilities" really is all.
    """
    where = _PATTERN_SQL.get(pattern["mode"])
    if not where:
        return [], 0
    value, kind = pattern["value"], pattern.get("kind")
    conn = _connect()
    kind_sql = " AND kind = ?" if kind else ""
    args: list = [value] + ([kind] if kind else [])

    total = conn.execute(
        f"SELECT COUNT(DISTINCT ref_norm) FROM parts WHERE {where}{kind_sql}",
        args).fetchone()[0]
    rows = conn.execute(
        f"""SELECT ref, ref_norm, kind, designation, supplier_ref FROM parts
            WHERE {where}{kind_sql}
            GROUP BY ref_norm ORDER BY length(ref_norm), ref_norm LIMIT ?""",
        [*args, limit]).fetchall()

    out, seen = [], set()
    for r in rows:
        if r["ref_norm"] in seen:
            continue
        seen.add(r["ref_norm"])
        item = _part_row(r, _photo_for(conn, r["ref"]))
        item["designation"] = _merged_designation(conn, r["ref"], r["designation"] or "")
        out.append(item)

    if not kind:
        # references with a photo on file but no workbook row (803 of them)
        photo_where = where.replace("ref_norm", "ref_norm")
        total += conn.execute(
            f"""SELECT COUNT(DISTINCT ref_norm) FROM ref_images
                WHERE {photo_where} AND ref_norm NOT IN (SELECT ref_norm FROM parts)""",
            [value]).fetchone()[0]
        if len(out) < limit:
            extra = conn.execute(
                f"""SELECT ref, ref_norm FROM ref_images
                    WHERE {photo_where} AND ref_norm NOT IN (SELECT ref_norm FROM parts)
                    GROUP BY ref_norm ORDER BY length(ref_norm), ref_norm LIMIT ?""",
                [value, limit - len(out)]).fetchall()
            for r in extra:
                if r["ref_norm"] in seen:
                    continue
                seen.add(r["ref_norm"])
                out.append({"ref": r["ref"], "kind": "photo only",
                            "designation": "", "supplier_ref": "",
                            "photo": _photo_for(conn, r["ref"])})
    conn.close()
    return out, total


_PATTERN_PHRASE = {
    "suffix": ("ends with", "end with"),
    "prefix": ("starts with", "start with"),
    "contains": ("contains", "contain"),
}


_NOUN_PLURAL = {"reference": "references", "profile": "profiles",
                "accessory": "accessories", "part": "parts"}


def describe_ref_pattern(pattern: dict, total: int, shown: int) -> str:
    kinds = pattern.get("kinds") or ([pattern["kind"]] if pattern.get("kind") else [])
    if len(kinds) > 1:
        noun, plural_noun = "reference", "profile and accessory references"
    else:
        noun = pattern.get("kind") or "reference"
        plural_noun = _NOUN_PLURAL.get(noun, noun + "s")
    singular, plural = _PATTERN_PHRASE[pattern["mode"]]
    value = pattern["value"]
    if total == 0:
        return f"No {noun} in the profiles & accessories workbook {singular} `{value}`."
    if total == 1:
        return f"One {noun} {singular} `{value}`:"
    head = f"**{total}** {plural_noun} {plural} `{value}`"
    return f"{head} — showing the first {shown}:" if shown < total else f"{head}:"


def is_reference_query(question: str) -> bool:
    """True when the customer typed a part number rather than a description.

    Matters because dense retrieval is meaningless for reference codes: the
    embedding of "10x2" carries no product meaning, so its nearest neighbours are
    arbitrary pages that would otherwise be presented as confident matches.
    """
    toks = content_tokens(question)
    if not toks or len(toks) > 3:
        return False
    return all(any(c.isdigit() for c in t) for t in toks)


def ref_candidates(ref: str, limit: int = 8) -> list[dict]:
    """References that start with, or closely resemble, what was typed.

    A customer who types `10x2` means `10X2-T`; without this they get nothing
    from the reference lookup and the query falls through to prose search.
    """
    key = norm_ref(ref)
    if len(key) < 3 or not any(c.isdigit() for c in key):
        return []
    conn = _connect()
    rows = conn.execute(
        """SELECT ref, ref_norm, kind, designation, supplier_ref FROM parts
           WHERE ref_norm LIKE ? ORDER BY length(ref_norm), ref_norm LIMIT ?""",
        (key + "%", limit * 3)).fetchall()
    seen = {r["ref_norm"] for r in rows}
    imgs = conn.execute(
        """SELECT ref, ref_norm FROM ref_images WHERE ref_norm LIKE ?
           ORDER BY length(ref_norm), ref_norm LIMIT ?""",
        (key + "%", limit * 3)).fetchall()
    out = [_part_row(r, _photo_for(conn, r["ref"])) for r in rows]
    for r in imgs:
        if r["ref_norm"] in seen:
            continue
        seen.add(r["ref_norm"])
        out.append({"ref": r["ref"], "kind": "part", "designation": "",
                    "supplier_ref": "", "photo": _photo_for(conn, r["ref"])})
    conn.close()
    return out[:limit]


_REF_TOKEN_RE = re.compile(r"[A-Z0-9]+(?:[.\-/][A-Z0-9]+)*")


def find_ref_in_question(question: str) -> dict | None:
    """Pull a real part reference out of free text ('what is 10230A for?').

    Every candidate is validated against the index, so ordinary words and stray
    numbers never produce a false part hit."""
    q = question.upper()
    cands: list[str] = []
    for tok in _REF_TOKEN_RE.findall(q):
        t = tok.strip(".-/ ")
        if len(t) >= 2 and any(c.isdigit() for c in t):
            cands.append(t)
    words = q.split()
    for a, b in zip(words, words[1:]):                      # '140 R', 'RIV 5IN'
        a, b = a.strip(".,!?;:"), b.strip(".,!?;:")
        if not a or not b:
            continue
        if a.isdigit() and 1 <= len(b) <= 3 and b.isalpha():
            cands.append(a + b)
        elif b[0].isdigit() and 2 <= len(a) <= 4 and a.isalpha() and len(b) <= 4:
            cands.append(a + b)
    seen, ordered = set(), []
    for c in sorted(cands, key=lambda t: (-len(t), t)):
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    for t in ordered:
        hit = lookup_part(t)
        if hit:
            return hit
    return None


_SYSTEM_NUM = re.compile(r"\b(\d{2})\s*TH\b", re.I)


def _part_relevance(designation: str, kind: str,
                    subject: list[tuple[str, list[str]]],
                    want_system: str | None) -> float:
    """How well a workbook row answers this question. 0 means: do not show it.

    Relevance has to come from the *subject* of the question. "doors galaxie 32th"
    asks about doors; a row called "OUTIL DORMANT GAL 32TH" matches only the
    system qualifier and answers nothing, so it scores zero.
    """
    # a row with no description has nothing to show a customer; the reference
    # alone is only useful when they asked for it by name (handled by lookup_part)
    if not designation.strip() or not subject:
        return 0.0
    d = f"{designation} {kind}".lower()

    # each subject word counts once, whether it matched directly or via a synonym
    matched, specific = 0, 0
    for tok, forms in subject:
        if any(f in d for f in forms):
            matched += 1
            if tok not in BROAD_TERMS:
                specific += 1
    if not matched:
        return 0.0

    # Category words alone are not evidence. "sliding" + "doors" both match
    # "PORTE JOINT COULISSANT" (a *gasket carrier* — porte is the verb "carries"
    # here, not the noun "door"), and equally match every other sliding-door
    # fitting in the workbook. Without at least one specific word the ranking has
    # nothing to separate a real answer from a coincidence, so show nothing.
    if not specific:
        return 0.0

    score = matched / len(subject) + 0.5 * specific

    # "26TH" when the customer asked about 32TH is the wrong product line
    if want_system:
        asked = _SYSTEM_NUM.search(want_system)
        found = _SYSTEM_NUM.search(designation)
        if asked and found:
            if found.group(1) == asked.group(1):
                score += 1.5
            else:
                return 0.0
    return score


def find_parts(query: str, limit: int = 6) -> list[dict]:
    """Search the workbook for parts that answer the *subject* of the question.

    The system name ("galaxie 32th") narrows and ranks the result; it never
    selects it. A question that is only a system name has no specific part
    behind it, so it returns nothing rather than the first rows that happen to
    carry that model code.
    """
    base, _sys_toks = split_subject(query)
    if not base:
        return []
    want_system = detect_system(query)
    terms = expand(base)
    # (word, all forms it may appear as) — computed once, reused for every row
    subject_forms = [(t, expand([t])) for t in base]
    conn = _connect()
    rows = []
    # precise first (every subject word present), then widen to synonyms
    for match in (_fts_and(base), _fts_or(terms)):
        if not match:
            continue
        try:
            rows = conn.execute(
                """SELECT pr.id, pr.ref, pr.kind, pr.designation, pr.supplier_ref,
                          bm25(parts_fts, 2.0, 1.0) AS bm
                   FROM parts_fts JOIN parts pr ON pr.id = parts_fts.rowid
                   WHERE parts_fts MATCH ? ORDER BY bm LIMIT ?""",
                (match, limit * 6),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        if rows:
            break

    scored = []
    for r in rows:
        rel = _part_relevance(r["designation"] or "", r["kind"] or "",
                              subject_forms, want_system)
        if rel <= 0:
            continue                      # loosely-related rows are worse than none
        scored.append((-(rel * 10 - r["bm"] * 0.1), r))

    # The fuzzy pass rescues typos, but it must obey the same rule as the lexical
    # one: with only category words to go on it would happily return whichever
    # rows are textually closest to "sliding doors", which is the coincidence we
    # just rejected above.
    has_specific = any(t not in BROAD_TERMS for t in base)
    if not scored and has_specific:  # nothing lexical: fall back to fuzzy matching
        try:
            from rapidfuzz import fuzz, process
        except ImportError:
            conn.close()
            return []
        all_rows = conn.execute(
            "SELECT id, ref, kind, designation, supplier_ref FROM parts "
            "WHERE length(designation) > 0"
        ).fetchall()
        choices = {i: (r["designation"] or "").lower() for i, r in enumerate(all_rows)}
        needle = " ".join(base)
        for _, sc, idx in process.extract(needle, choices, scorer=fuzz.token_set_ratio,
                                          limit=limit, score_cutoff=72):
            scored.append((-sc, all_rows[idx]))

    scored.sort(key=lambda t: t[0])
    out, seen = [], set()
    for _, r in scored:
        key = norm_ref(r["ref"])
        if key in seen:
            continue
        seen.add(key)
        row = _part_row(r, _photo_for(conn, r["ref"]))
        row["designation"] = _merged_designation(conn, r["ref"], row["designation"])
        out.append(row)
        if len(out) >= limit:
            break
    conn.close()
    return out


def pages_using_ref(ref: str, limit: int = 6) -> list[dict]:
    """Catalogue pages whose text mentions this reference."""
    key = norm_ref(ref)
    if not key:
        return []
    conn = _connect()
    rows = conn.execute(
        """SELECT p.id, p.doc_id, p.page_num, p.text, p.ocr_text, p.refs, p.summary,
                  d.filename, d.title, d.system, d.systems, d.doc_kind
           FROM pages p JOIN documents d ON d.id = p.doc_id
           WHERE ' ' || p.refs || ' ' LIKE ?
           ORDER BY d.id, p.page_num LIMIT ?""",
        (f"% {key} %", limit),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        stem = sanitize(r["filename"].rsplit(".", 1)[0].replace("/", "_"))
        out.append({
            "page_id": r["id"], "doc_id": r["doc_id"], "filename": r["filename"],
            "title": r["title"], "system": r["system"],
            "systems": sorted(set(json.loads(r["systems"] or "[]")) | {r["system"]}),
            "doc_kind": r["doc_kind"], "page_num": r["page_num"],
            "score": 100, "raw_score": 1.0, "coverage": 1.0,
            "snippet": make_snippet(r["text"] or r["ocr_text"] or "",
                                    [key.lower(), ref.lower()]),
            "has_ocr": bool((r["ocr_text"] or "").strip()), "semantic": None,
            "summary": (r["summary"] or "").strip(), "refs": (r["refs"] or "").split(),
            "page_image": f"pages/{stem}/p{r['page_num']:03d}.png",
            "thumb": f"pages/{stem}/p{r['page_num']:03d}_thumb.png",
        })
    return out


# --------------------------------------------------------------------------
# status / counts
# --------------------------------------------------------------------------
def list_documents() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        """SELECT d.id, d.filename, d.title, d.system, d.systems, d.doc_kind, d.num_pages,
                 (SELECT COUNT(*) FROM figures f WHERE f.doc_id = d.id) AS figure_count,
                 d.indexed_at
           FROM documents d ORDER BY d.system, d.filename"""
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["systems"] = json.loads(d.pop("systems") or "[]") or [d["system"]]
        out.append(d)
    return out


def _count(table: str) -> int:
    try:
        conn = _connect()
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        conn.close()
        return n
    except sqlite3.Error:
        return 0


def count_pages() -> int:
    return _count("pages")


def count_parts() -> int:
    return _count("parts")


def count_ref_images() -> int:
    return _count("ref_images")


def count_figures() -> int:
    return _count("figures")


def count_ocr_pages() -> int:
    try:
        conn = _connect()
        n = conn.execute("SELECT COUNT(*) FROM pages WHERE length(ocr_text) > 0").fetchone()[0]
        conn.close()
        return n
    except sqlite3.Error:
        return 0


def has_summaries() -> bool:
    try:
        conn = _connect()
        n = conn.execute("SELECT COUNT(*) FROM pages WHERE length(summary) > 0").fetchone()[0]
        conn.close()
        return n > 0
    except sqlite3.Error:
        return False


def systems() -> list[str]:
    conn = _connect()
    rows = conn.execute("SELECT DISTINCT systems FROM documents").fetchall()
    conn.close()
    found: set[str] = set()
    for r in rows:
        found.update(json.loads(r["systems"] or "[]"))
    return sorted(found)


# --------------------------------------------------------------------------
# ambiguity
# --------------------------------------------------------------------------
GREETINGS = {"hi", "hello", "hey", "yo", "bonjour", "salut", "coucou", "hola",
             "thanks", "thank", "merci", "ok", "okay", "bye", "goodbye", "test"}


def is_greeting(question: str) -> bool:
    """A greeting or a bare 'help me' — answer conversationally, don't search."""
    toks = tokens(question)
    if not toks or len(toks) > 3:
        return False
    if set(toks) <= GREETINGS:
        return True
    return set(toks) <= (GREETINGS | {"help", "me", "you", "please", "aide", "aidez"}) \
        and bool({"help", "aide", "aidez"} & set(toks))


def greeting_reply() -> tuple[str, list[str]]:
    """Friendly opener plus concrete things this index can actually answer."""
    answer = (
        "Hello! I answer questions about the Installux catalogues on file — "
        f"**{'**, **'.join(systems())}**.\n\n"
        "You can ask me in English or French. Try a part reference, a component, "
        "or a fabrication question:"
    )
    return answer, [
        "What is part 10230A?",
        "Glazing bead options for COMETE 70TH",
        "Punching tools and rails for the 70TH door",
        "Sliding rail drainage on GALAXIE 32TH",
    ]


def is_question_broad(question: str, pages: list[dict]) -> bool:
    """True when we should ask the customer to narrow down rather than guess."""
    q = question.lower().strip(" ?!.,;")
    toks = tokens(question)
    if not toks:
        return True
    if find_ref_in_question(question):        # a real part number is specific
        return False
    content = content_tokens(question)
    if not content:
        return True

    vague = {"help", "info", "information", "general", "overview", "summary",
             "introduction", "everything", "anything", "catalogue", "catalog"}
    if set(content) & vague and len(content) <= 3:
        return True
    if re.fullmatch(r"(hi|hello|hey|bonjour|salut|thanks|merci|ok)\b.*", q):
        return True
    if not pages:
        return True

    # "doors", "aluminium", "profiles" — a whole category. Even with a system named
    # ("70TH doors") there is nothing specific to answer, so offer facets instead.
    if content and all(t in BROAD_TERMS for t in content):
        return True

    # Data-driven version of the same idea, for words no list anticipated: one word
    # that appears across most of the catalogue cannot discriminate between pages.
    # Only single-word queries — a pair like "thermal break" is a real compound term
    # even though both halves are common.
    if len(content) == 1 and page_share(content[0]) > COMMON_TOKEN_SHARE:
        return True

    # a single trade term ("drainage", "poignée", "paumelle") is answerable as-is
    if any(t in _SYN_INDEX for t in content):
        return False
    # nothing the customer said actually appears in the top hit
    if pages[0]["coverage"] == 0 and pages[0]["score"] < 60:
        return True
    # one bare, off-vocabulary word is too open-ended to answer well
    if len(content) == 1 and not detect_system(question) and pages[0]["coverage"] < 1:
        return True
    return False


_page_share_cache: dict[str, float] = {}


def page_share(token: str) -> float:
    """Fraction of indexed pages whose text contains this token (cached)."""
    if token in _page_share_cache:
        return _page_share_cache[token]
    total = count_pages() or 1
    conn = _connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM pages_fts WHERE pages_fts MATCH ?",
                         (_quote(token) + "*",)).fetchone()[0]
    except sqlite3.OperationalError:
        n = 0
    finally:
        conn.close()
    _page_share_cache[token] = n / total
    return _page_share_cache[token]


# Headings in these catalogues are set in capitals: "SINGLE TRACK", "PUNCHING TOOLS",
# "OPENING FRAMES". They are exactly the categories a customer wants to pick from.
_HEADING_RE = re.compile(r"^[A-Z0-9][A-Z0-9 &®°/'’\-\.\+]{4,44}$")
_HEADING_STOP = {
    "PARTS LIST", "ITEM & REFERENCE", "SECTIONS", "MACHINING", "TOOLS", "EDITION",
    "PAGE", "REF", "NOTA", "NOTE", "CONCEPT", "RANGES", "SOLUTIONS", "INSTALLUX",
}


def _readable(s: str) -> bool:
    """Reject text mangled by a broken PDF font encoding.

    Two failure modes appear in these files: private-use glyphs (non-Latin
    codepoints), and Caesar-shifted ASCII — "Usinage" comes out as "Xvlqdjh",
    which is still ASCII but has almost no vowels. Both are unreadable to a
    customer, so neither belongs in a snippet or a suggested category.
    """
    if not s:
        return False
    ok = sum(1 for ch in s if ch.isascii() or ch in "àâäçéèêëîïôöùûüÿœæ°®±×µ–—’")
    if ok / len(s) <= 0.85:
        return False
    longs = re.findall(r"[A-Za-zÀ-ÿ]{6,}", s)
    if longs:
        starved = [w for w in longs
                   if sum(1 for c in w.lower() if c in "aeiouyàâäéèêëîïôöùûü") / len(w) < 0.25]
        # "screw" and "track" are ordinary; a *majority* of vowel-starved words is not
        if len(starved) / len(longs) > 0.5:
            return False
    return True


_PART_KIND_WORDS = {
    "profile": {"profile", "profiles", "profil", "profiles", "extrusion", "section", "sections"},
    "accessory": {"accessory", "accessories", "accessoire", "accessoires",
                  "hardware", "quincaillerie", "fitting", "fittings"},
}


def _designation_group(d: str) -> str:
    """'BROOM SEAL: 7.2-4P-HF-1000' -> 'Broom Seal'; the family, not the variant."""
    d = re.split(r"[:(\[]", d, 1)[0]
    d = re.sub(r"[\d.,/×x]+\s*(mm|MM)?\b", " ", d)
    d = re.sub(r"[^A-Za-z /&'-]+", " ", d)
    d = re.sub(r"\s+", " ", d).strip(" -/&")
    return d.title() if 2 < len(d) <= 34 else ""


def part_facets(question: str, limit: int = 10) -> list[str]:
    """Component families from the workbook — the real categories behind
    'profiles', 'accessories' or any broad component question."""
    toks = set(content_tokens(question))
    kind = next((k for k, words in _PART_KIND_WORDS.items() if toks & words), None)
    conn = _connect()
    try:
        if kind:
            rows = conn.execute(
                "SELECT designation FROM parts WHERE kind = ? AND length(designation) > 2",
                (kind,)).fetchall()
        else:
            match = _fts_or(expand(list(toks)))
            if not match:
                return []
            try:
                rows = conn.execute(
                    "SELECT pr.designation FROM parts_fts JOIN parts pr ON pr.id = parts_fts.rowid "
                    "WHERE parts_fts MATCH ? LIMIT 600", (match,)).fetchall()
            except sqlite3.OperationalError:
                return []
    finally:
        conn.close()

    counts: dict[str, int] = {}
    for r in rows:
        g = _designation_group(r["designation"] or "")
        if g:
            counts[g] = counts.get(g, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [g for g, n in ranked[:limit] if n > 1]


def facets(pages: list[dict], question: str = "", limit: int = 10) -> dict:
    """Real, pickable categories drawn from the index itself.

    Three sources, in order of usefulness: component families from the
    profiles/accessories workbook, section headings on the matching pages, and
    the systems/document types those pages belong to.
    """
    conn = _connect()
    heads: dict[str, int] = {}
    ids = [p["page_id"] for p in pages[:24]]
    if ids:
        q = ",".join("?" * len(ids))
        for row in conn.execute(f"SELECT text FROM pages WHERE id IN ({q})", ids):
            for raw in (row["text"] or "").splitlines():
                line = re.sub(r"\s+", " ", raw).strip(" :·-")
                if (len(line) < 5 or not _HEADING_RE.match(line)
                        or line.upper() in _HEADING_STOP or not _readable(line)):
                    continue
                if sum(c.isdigit() for c in line) > len(line) / 2:
                    continue                      # a dimension row, not a heading
                heads[line.title()] = heads.get(line.title(), 0) + 1
    conn.close()

    ranked = sorted(heads.items(), key=lambda kv: (-kv[1], kv[0]))
    known = systems()
    return {
        "systems": sorted({s for p in pages[:24] for s in p.get("systems", [p["system"]])})
                   or known,
        "doc_kinds": sorted({p["doc_kind"] for p in pages[:24]}),
        "topics": [h for h, _ in ranked[:limit]],
        "components": part_facets(question, limit) if question else [],
    }


def fallback_suggestions(question: str, pages: list[dict]) -> list[str]:
    """Clarifying options built from the index — no LLM required."""
    f = facets(pages, question)
    named = detect_system(question)
    suffix = f" — {named}" if named else ""
    out: list[str] = []

    for comp in f["components"][:4]:
        out.append(f"{comp}{suffix}")
    for topic in f["topics"][:3]:
        out.append(f"{topic}{suffix}")
    if not named:
        for s in f["systems"][:3]:
            out.append(f"What does {s} cover?")
    if "fabrication drawing" in f["doc_kinds"]:
        out.append(f"Fabrication drawings for {named or f['systems'][0]}")
    # de-duplicate while keeping order
    seen, uniq = set(), []
    for s in out:
        if s.lower() not in seen:
            seen.add(s.lower())
            uniq.append(s)
    return uniq[:6]


def compose_evidence_answer(question: str, pages: list[dict], parts: list[dict]) -> str:
    """Readable answer assembled straight from the index, for when no LLM is up."""
    lines: list[str] = []
    if parts:
        lines.append("**Matching references**")
        for p in parts[:5]:
            desc = p["designation"] or "no description recorded in the workbook"
            photo = " · reference photo shown below" if p["photo"] else ""
            lines.append(f"- **{p['ref']}** — {desc} ({p['kind']}){photo}")
        if len(parts) == 1 and not pages:
            lines.append("")
            lines.append(f"No page in the indexed catalogues mentions **{parts[0]['ref']}**, "
                         "so the reference data above is everything on file for it.")
        lines.append("")
    if pages:
        lines.append("**Where this is documented**")
        for p in pages[:5]:
            snippet = re.sub(r"\s+", " ", p["snippet"])[:220]
            lines.append(f"- {p['system']} · {Path(p['filename']).name} p.{p['page_num']} "
                         f"({p['doc_kind']}) — {snippet}")
    if not lines:
        return ("I could not find anything matching that in the indexed catalogues. "
                "Try a part reference (e.g. `10230A`) or name the system "
                "(COMETE 70TH, GALAXIE 32TH, GALAXIE 45TH).")
    lines.append("")
    lines.append("_The local AI model is offline, so this is the raw catalogue evidence "
                 "rather than a written answer._")
    return "\n".join(lines)

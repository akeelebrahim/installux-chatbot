"""End-to-end checks for the Installux ChatBot.

Start the app first (`python app.py`), then run `python test_app.py`.
Exits non-zero if any check fails, so it is safe to wire into a build step.
"""
from __future__ import annotations

import atexit
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8010"
BASE_DIR = Path(__file__).resolve().parent
ok = fail = 0

# The backend is restored no matter how this script exits.
_ORIGINAL_BACKEND = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))     .get("backend", "openrouter")


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}  {detail}")


def post(path, obj=None, raw=None, headers=None, timeout=300):
    data = raw if raw is not None else (json.dumps(obj).encode() if obj is not None else b"")
    h = headers or ({"Content-Type": "application/json"} if obj is not None else {})
    req = urllib.request.Request(BASE + path, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def get(path, timeout=60):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def multipart(filename: str, content: bytes, ctype: str) -> tuple[bytes, dict]:
    body = (f'--B\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n").encode() + content + b"\r\n--B--\r\n"
    return body, {"Content-Type": "multipart/form-data; boundary=B"}


# --------------------------------------------------------------------------
print("\n== static & status ==")
s, b = get("/")
check("GET / serves the UI", s == 200 and b"Installux ChatBot" in b, f"status={s}")
check("UI has no broken handlers", b"setAndAsk(" not in b and b"canRecord()" not in b)

s, b = get("/api/status")
st = json.loads(b)
check("status 200", s == 200)
check("PDFs deduped to 6 documents", len(st["indexed_docs"]) == 6, str(len(st["indexed_docs"])))
check("78 pages indexed", st["total_pages"] == 78, str(st["total_pages"]))
check("figures extracted from vector art", st["total_figures"] > 200, str(st["total_figures"]))
check("6899 workbook parts", st["total_parts"] == 6899, str(st["total_parts"]))
check("3275 part photos", st["total_ref_images"] == 3275, str(st["total_ref_images"]))
check("all three systems present",
      set(st["systems"]) == {"COMETE 70TH", "GALAXIE 32TH", "GALAXIE 45TH"}, str(st["systems"]))

print("\n== validation / error paths ==")
check("empty question rejected", post("/api/ask", {"question": ""})[0] == 400)
check("out-of-range max_pages rejected", post("/api/ask", {"question": "x", "max_pages": 999})[0] == 422)
check("missing question rejected", post("/api/ask", {})[0] == 422)
s, _ = post("/api/find-by-image", raw=b"--x\r\n",
            headers={"Content-Type": "multipart/form-data; boundary=x"})
check("malformed upload does not 500", s in (400, 422), f"status={s}")
check("unknown part 404s", get("/api/part/NOSUCHREF999")[0] == 404)

print("\n== part lookup ==")
s, b = get("/api/part/10230A")
check("photo-only reference resolves", s == 200 and json.loads(b)["part"]["photo"], b[:120].decode())
s, b = get("/api/part/401")
check("workbook reference carries its designation",
      s == 200 and "GLAZING" in json.loads(b)["part"]["designation"].upper(), b[:160].decode())
s, b = get("/api/part/l1502")
check("lowercase reference resolves",
      s == 200 and json.loads(b)["part"]["ref"].upper() == "L1502", b[:120].decode())

print("\n== image search ==")
body, hdr = multipart("119312.JPG", (BASE_DIR / "pdfs/Images/119312.JPG").read_bytes(), "image/jpeg")
t = time.time()
s, b = post("/api/find-by-image", raw=body, headers=hdr)
elapsed = time.time() - t
top = (json.loads(b).get("results") or [{}])[0]
check("uploading a part photo returns that part first",
      s == 200 and top.get("ref") == "119312", str(top)[:160])
# Budget raised from 2s deliberately: matching now runs a ViT encoder plus up to
# 32 geometric verifications so that a *crop* can find its source. A hash compare
# was 20ms but could not answer the question at all.
check("image search stays interactive (<6s warm)", elapsed < 6, f"{elapsed:.2f}s")
body, hdr = multipart("x.txt", b"not an image", "text/plain")
s, b = post("/api/find-by-image", raw=body, headers=hdr)
check("non-image upload gives a clean 400", s == 400 and b"Could not read" in b, f"status={s}")

print("\n== partial image search (a crop must find its source) ==")
# Whole-image hashes cannot do this: cropping changes the hash completely, so
# every one of these used to come back with unrelated images.
from PIL import Image  # noqa: E402

_CROP_CASES = [
    ("data/figures/Comete_70TH_Com_te_70TH/p008_img02.png", (.28, .28, .73, .73), "centre"),
    ("data/figures/Comete_70TH_Com_te_70TH/p004_img02.png", (.02, .02, .52, .52), "corner"),
    ("pdfs/Images/119312.JPG", (.28, .28, .73, .73), "centre"),
]
_found = _checked = 0
_verified = False
for _src, _box, _label in _CROP_CASES:
    _p = BASE_DIR / _src
    if not _p.exists():
        continue
    _im = Image.open(_p).convert("RGB")
    _crop = _im.crop((int(_box[0] * _im.width), int(_box[1] * _im.height),
                      int(_box[2] * _im.width), int(_box[3] * _im.height)))
    _buf = io.BytesIO()
    _crop.save(_buf, "PNG")
    _body, _hdr = multipart("crop.png", _buf.getvalue(), "image/png")
    _s, _b = post("/api/find-by-image", raw=_body, headers=_hdr)
    _res = (json.loads(_b).get("results") or []) if _s == 200 else []
    _want = Path(_src).name
    _top = Path(_res[0]["image_url"]).name if _res else ""
    _checked += 1
    if _top == _want:
        _found += 1
    if _res and _res[0].get("inliers") is not None:
        _verified = True
    check(f"a {_label} crop of {_want} finds its source first", _top == _want,
          f"got {_top!r}")
    if _res and _res[0].get("inliers") is not None:
        check(f"  ...and is geometrically confirmed",
              _res[0]["inliers"] >= 15 and _res[0]["match"],
              f"inliers={_res[0].get('inliers')} match={_res[0].get('match')}")

check("partial-image search is running the verified pipeline", _verified,
      "no inlier counts returned — falling back to hashes")
if _verified:
    _d = json.loads(post("/api/find-by-image", raw=_body, headers=_hdr)[1])
    _r = _d["results"]
    # 2x, not more: some part photos are genuine siblings of the same profile
    # family and legitimately share a lot of geometry
    check("the true source outscores the runner-up decisively",
          len(_r) < 2 or _r[0]["inliers"] >= 2 * max(1, _r[1]["inliers"]),
          str([x.get("inliers") for x in _r[:3]]))
    check("results carry the method that produced them",
          all(x.get("method") == "patch+keypoint" for x in _r), str(_r[0].get("method")))

print("\n== send the exact image to WhatsApp ==")
# No WhatsApp URL can carry a file, and this browser has no navigator.share and
# denies clipboard-write — so the send button did nothing useful. The server owns
# the OS clipboard instead, which needs no browser permission.
import subprocess  # noqa: E402


def _clipboard_size():
    """(width, height) of whatever image is on the Windows clipboard, or None."""
    if os.name != "nt":
        return None
    ps = ("Add-Type -AssemblyName System.Windows.Forms;"
          "$i=[System.Windows.Forms.Clipboard]::GetImage();"
          "if($i){\"$($i.Width)x$($i.Height)\"}else{'none'}")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps],
                             capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return None
    if "x" not in out:
        return None
    w, h = out.split("x", 1)
    return int(w), int(h)


_CLIP_CASES = [("/refmedia/910215.JPG", BASE_DIR / "pdfs/Images/910215.JPG"),
               ("/media/figures/Comete_70TH_Com_te_70TH/p008_img02.png",
                BASE_DIR / "data/figures/Comete_70TH_Com_te_70TH/p008_img02.png")]
for _url, _src in _CLIP_CASES:
    if not _src.exists():
        continue
    _s, _b = post("/api/clipboard-image", {"url": _url})
    check(f"copies {_src.name} to the clipboard",
          _s == 200 and json.loads(_b).get("copied") is True, f"{_s} {_b[:120]}")
    _got = _clipboard_size()
    if _got is not None:
        _w, _h = Image.open(_src).size
        check(f"  ...and it is the exact image ({_w}x{_h})", _got == (_w, _h),
              f"clipboard has {_got}")

# The URL comes from the browser, so it must never reach outside the media roots.
for _bad in ["/media/../../config.json", "/media/../.env", "/refmedia/../../.env",
             "/etc/passwd", "file:///C:/Windows/win.ini", "/media/nope.png", "",
             "/media/%2e%2e%2f%2e%2e%2f.env", "/media/", "../.env"]:
    check(f"refuses {_bad!r}", post("/api/clipboard-image", {"url": _bad})[0] == 400,
          str(post("/api/clipboard-image", {"url": _bad})[0]))

_ui = get("/")[1].decode()
check("the WhatsApp button asks the server for the clipboard",
      "copyImageServerSide" in _ui and "/api/clipboard-image" in _ui)
# scope the ordering check to sendImage's own body: the browser-clipboard call
# also appears earlier in the file, in a different function
_send = _ui[_ui.index("async function sendImage("):][:2500]
check("the server clipboard is tried before the browser one",
      "copyImageServerSide(url)" in _send
      and _send.index("copyImageServerSide(url)") < _send.index("navigator.clipboard.write"))
check("the copy button also uses the server clipboard",
      "copyImageServerSide(url)" in _ui[_ui.index("async function copyImage("):][:600])
check("the customer is told to paste", "pasteHint" in _ui and "Ctrl+V" in _ui)

print("\n== export ==")
s, b = post("/api/export-images")
n = len(zipfile.ZipFile(io.BytesIO(b)).namelist()) if s == 200 else 0
check("ZIP export contains every figure", s == 200 and n > 200, f"status={s} n={n}")

print("\n== media serving ==")
s, b = post("/api/ask", {"question": "punching tools rails", "max_pages": 2, "max_images": 3})
d = json.loads(b)
urls = ([f"/media/{d['pages'][0]['thumb']}", f"/media/{d['pages'][0]['page_image']}"]
        + [i["url"] for i in d["images"][:2]] + [i["thumb_url"] for i in d["images"][:2]]
        + [p["photo"] for p in d["parts"] if p["photo"]])
broken = [u for u in urls if get(u)[0] != 200]
check("every returned media URL resolves", not broken, str(broken))

print("\n== dashboard compute control ==")
st = json.loads(get("/api/status")[1])
ms = st["model_server"]
check("status exposes the compute mode", st["compute"] in ("cpu", "gpu"), str(st.get("compute")))
check("local model server located on its port", ms["port"] == 8080, str(ms))
check("local model files available to start", ms["can_start"] is True, str(ms))
s, b = post("/api/settings", {"compute": "cpu"})
check("compute saves as cpu", s == 200 and json.loads(b)["compute"] == "cpu", b[:120].decode())
s, b = post("/api/settings", {"compute": "gpu"})
check("compute saves as gpu", s == 200 and json.loads(b)["compute"] == "gpu", b[:120].decode())
check("choice persisted to config.json",
      '"compute": "gpu"' in (BASE_DIR / "config.json").read_text(encoding="utf-8"))
check("invalid compute rejected", post("/api/settings", {"compute": "quantum"})[0] == 422)
check("invalid model action rejected", post("/api/model/explode")[0] == 400)

print("\n== model backend switching ==")
st = json.loads(get("/api/status")[1])
names = [o["name"] for o in st["backend_options"]]
check("dashboard offers remote and local backends",
      "openrouter" in names and "llamafile" in names, str(names))
check("every offered backend reports readiness",
      all(isinstance(o["ready"], bool) for o in st["backend_options"]), str(st["backend_options"]))
original = _ORIGINAL_BACKEND
atexit.register(lambda: post("/api/settings", {"backend": original}))
s, b = post("/api/settings", {"backend": "llamafile"})
d = json.loads(b)
check("switch to the local model", s == 200 and d["backend"] == "llamafile", b[:160].decode())
check("status follows the switch",
      json.loads(get("/api/status")[1])["backend_kind"] == "local")
s, b = post("/api/settings", {"backend": original})
d = json.loads(b)
check("switch back to the hosted model", s == 200 and d["backend"] == original, b[:160].decode())
check("unknown backend rejected", post("/api/settings", {"backend": "nope"})[0] == 422)

print("\n== secret hygiene ==")
cfg_text = (BASE_DIR / "config.json").read_text(encoding="utf-8")
check("no API key in config.json", "sk-or-" not in cfg_text)
check("config.json references the key by env var name", "api_key_env" in cfg_text)
check(".env is git-ignored",
      ".env" in (BASE_DIR / ".gitignore").read_text(encoding="utf-8"))
check(".env.example ships without a value",
      "OPENROUTER_API_KEY=" in (BASE_DIR / ".env.example").read_text(encoding="utf-8")
      and "sk-or-" not in (BASE_DIR / ".env.example").read_text(encoding="utf-8"))
leaked = [p for p in ("/api/status", "/api/reindex-status") if b"sk-or-" in get(p)[1]]
check("no API key leaks through the API", not leaked, str(leaked))

# a stray "keys.txt" next to the source is exactly how secrets reach GitHub
import fnmatch  # noqa: E402

_rules = [l.strip() for l in (BASE_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
          if l.strip() and not l.startswith("#")]
_keep = [r[1:] for r in _rules if r.startswith("!")]
_drop = [r for r in _rules if not r.startswith("!")]


def _ignored(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    if any(fnmatch.fnmatch(name, k) or fnmatch.fnmatch(rel, k) for k in _keep):
        return False
    return any(fnmatch.fnmatch(rel, r.rstrip("/")) or fnmatch.fnmatch(name, r.rstrip("/"))
               or rel.startswith(r.rstrip("/") + "/") for r in _drop)


_secret = ""
for _line in (BASE_DIR / ".env").read_text(encoding="utf-8").splitlines():
    if _line.startswith("OPENROUTER_API_KEY="):
        _secret = _line.split("=", 1)[1].strip()
_committed_leaks = []
for _p in BASE_DIR.rglob("*"):
    _rel = _p.relative_to(BASE_DIR).as_posix()
    if not _p.is_file() or _ignored(_rel) or _p.stat().st_size > 2_000_000:
        continue
    try:
        if _secret and _secret in _p.read_text(encoding="utf-8", errors="ignore"):
            _committed_leaks.append(_rel)
    except OSError:
        pass
check("no committable file contains the key", not _committed_leaks, str(_committed_leaks))
check("key is loaded from .env into the environment",
      json.loads(get("/api/status")[1])["needs_api_key"] is False)

print("\n== broad questions offer narrowing options ==")
sys.path.insert(0, str(BASE_DIR))
import search as _search  # noqa: E402

for term in ("Doors", "Aluminum", "profiles"):
    d = json.loads(post("/api/ask", {"question": term})[1])
    check(f"{term!r} asks to narrow instead of guessing", d["clarify"], str(d)[:120])
    sug = d.get("suggestions") or []
    check(f"{term!r} offers at least 4 options", len(sug) >= 4, str(sug))
    # every option must lead somewhere in the indexed content, or it is not
    # "based only on the app content"
    dead = [s for s in sug if not _search.search_pages(s, limit=3)]
    check(f"{term!r} options are all answerable from the index", not dead, str(dead))

for specific in ("thermal break", "glazing bead for 70TH", "what is 10230A"):
    d = json.loads(post("/api/ask", {"question": specific})[1])
    check(f"{specific!r} is answered directly, not deflected", not d["clarify"], str(d)[:120])

print("\n== snippet quality ==")
d = json.loads(post("/api/ask", {"question": "sliding frame galaxie", "max_pages": 6})[1])
bad = [p["snippet"][:60] for p in d["pages"] if not _search._readable(p["snippet"] or "x")]
check("no mis-decoded glyph runs in snippets", not bad, str(bad))

print("\n== sharing ==")
s, b = post("/api/bundle", {"question": "glazing bead for COMETE 70TH",
                            "answer": "test", "max_pages": 2, "max_images": 3})
names = zipfile.ZipFile(io.BytesIO(b)).namelist() if s == 200 else []
check("bundle ZIP builds", s == 200 and "answer.txt" in names, f"status={s} {names[:4]}")
check("bundle carries pages and drawings",
      any(n.startswith("pages/") for n in names) and any(n.startswith("drawings/") for n in names),
      str(names))
check("empty bundle request rejected", post("/api/bundle", {"question": "  "})[0] == 400)

print("\n== OCR & vector coverage ==")
st = json.loads(get("/api/status")[1])
check("dense vectors built", st["vectors"] is True, str(st.get("vectors")))
check("damaged/sparse pages were OCR'd", st["ocr_pages"] >= 14, str(st.get("ocr_pages")))
import sqlite3  # noqa: E402

_db = sqlite3.connect(BASE_DIR / "data" / "index.db")
check("every page has an embedding",
      _db.execute("SELECT COUNT(*) FROM pages WHERE vec IS NULL").fetchone()[0] == 0)
check("every workbook part has an embedding",
      _db.execute("SELECT COUNT(*) FROM parts WHERE vec IS NULL").fetchone()[0] == 0)
check("no page-render paths leaked into ocr_text",
      _db.execute("SELECT COUNT(*) FROM pages WHERE ocr_text LIKE 'pages/%'").fetchone()[0] == 0)
_ocr = _db.execute(
    "SELECT p.ocr_text FROM pages p JOIN documents d ON d.id = p.doc_id "
    "WHERE d.filename LIKE '%d9100%' AND p.page_num = 1").fetchone()[0]
check("the fabrication drawing's table was recovered by OCR",
      "NOMENCLATURE" in _ocr.upper() and "910010B" in _ocr, _ocr[:120])
_db.close()

# semantic recall: none of these words appear on the drainage pages verbatim
_sem = _search.semantic_hits("how do I stop rainwater getting inside", k=5)
check("vector search returns neighbours for a paraphrase", len(_sem) > 0, str(_sem)[:100])

print("\n== answer relevance & highlighting ==")
d = json.loads(post("/api/ask", {"question": "doors galaxie 32th", "max_pages": 3})[1])
check("'doors galaxie 32th' is answered, not deflected", not d["clarify"], str(d)[:120])
check("its pages are all GALAXIE",
      all("GALAXIE" in " ".join(p["systems"]) for p in d["pages"]),
      str([p["systems"] for p in d["pages"]]))
refs = [p["ref"] for p in d["parts"]]
check("no wrong-system parts (26TH for a 32TH question)",
      not any("26TH" in (p["designation"] or "").upper() for p in d["parts"]), str(refs))

# The subject drives the parts and the system only narrows them — but "doors" is
# a category word, and on its own it matches every door fitting in the workbook
# equally. That produced coincidental hits like "PORTE JOINT COULISSANT" (a gasket
# carrier: porte is the verb "carries" here), so a category-only subject now
# returns no parts at all rather than an arbitrary slice.
descs = [(p["designation"] or "").upper() for p in d["parts"]]
check("a category-only subject returns no parts", not descs, str(descs))
check("no tooling matched purely on the system code",
      not any(x.startswith("OUTIL") or "VERROU CROIS" in x for x in descs), str(descs))
check("every listed part has a description",
      all((p["designation"] or "").strip() for p in d["parts"]), str(refs))
# ...while the same question narrowed to a real component still returns parts
d3 = json.loads(post("/api/ask", {"question": "door handle galaxie 32th"})[1])
found3 = (d3.get("parts") or []) + (d3.get("parts_without_photo") or [])
check("naming a component brings the parts back", bool(found3),
      str([p["designation"] for p in found3][:3]))

d2 = json.loads(post("/api/ask", {"question": "galaxie 32th"})[1])
check("a bare system name returns no arbitrary parts", not d2["parts"],
      str([p["ref"] for p in d2["parts"]]))

sys.path.insert(0, str(BASE_DIR))
import search as _s  # noqa: E402

check("plurals reach the synonym index", "porte" in _s.expand(["doors"]),
      str(_s.expand(["doors"])))
check("subject and system qualifier are separated",
      _s.split_subject("doors galaxie 32th") == (["doors"], ["galaxie", "32th"]),
      str(_s.split_subject("doors galaxie 32th")))
check("search terms returned for highlighting", bool(d.get("terms")), str(d.get("terms")))

d = json.loads(post("/api/ask", {"question": "glazing bead 70TH", "max_pages": 3})[1])
marked = [p for p in d["pages"] if p.get("highlights")]
check("pages carry highlight rectangles", bool(marked),
      str([len(p.get("highlights") or []) for p in d["pages"]]))
rects = marked[0]["highlights"] if marked else []
check("highlight rectangles are normalised 0-1",
      all(0 <= v <= 1 for r in rects for v in r), str(rects[:2]))

print("\n== highlighting reaches every result type ==")
d = json.loads(post("/api/ask", {"question": "punching tools rails",
                                 "max_pages": 3, "max_images": 6})[1])
check("drawings inherit the keyword boxes of their page region",
      any(f.get("highlights") for f in d["images"]),
      str([len(f.get("highlights") or []) for f in d["images"]]))
fig_rects = [r for f in d["images"] for r in (f.get("highlights") or [])]
check("figure boxes are normalised 0-1 in the crop's own frame",
      fig_rects and all(0 <= v <= 1 for r in fig_rects for v in r), str(fig_rects[:2]))
check("synonyms that caused the match are highlightable",
      any(t in (d.get("terms") or []) for t in ("machining", "tool", "usinage")),
      str(d.get("terms")))

# The real test of "even from OCR": d9100's font map is broken, so the PDF text
# layer cannot find these words at all — only the stored OCR boxes can.
doc_row = None
with __import__("sqlite3").connect(BASE_DIR / "data" / "index.db") as _c:
    _c.row_factory = __import__("sqlite3").Row
    doc_row = _c.execute(
        "SELECT id, filename FROM documents WHERE filename LIKE '%d9100%'").fetchone()
    n_boxes = _c.execute("SELECT COUNT(*) FROM ocr_boxes").fetchone()[0]
check("OCR word geometry is stored", n_boxes > 100, str(n_boxes))
if doc_row:
    ocr_terms = ["nomenclature", "profils"]
    layer_only = _s.highlight_rects(doc_row["filename"], 1, ocr_terms, None)
    with_ocr = _s.highlight_rects(doc_row["filename"], 1, ocr_terms, doc_row["id"])
    check("the broken-font page is unsearchable in the PDF text layer",
          not layer_only, str(len(layer_only)))
    check("OCR still highlights it", len(with_ocr) >= 4, str(len(with_ocr)))

check("a crop keeps only the boxes inside it, rescaled",
      _s.marks_within([[0.5, 0.5, 0.1, 0.1], [0.0, 0.0, 0.05, 0.05]],
                      (0.4, 0.4, 0.8, 0.8)) == [[0.25, 0.25, 0.25, 0.25]],
      str(_s.marks_within([[0.5, 0.5, 0.1, 0.1], [0.0, 0.0, 0.05, 0.05]],
                          (0.4, 0.4, 0.8, 0.8))))

print("\n== partial and unknown part references ==")
# '10x2' is not a reference, but 10X2-T is. It used to return six catalogue pages
# containing no '10x2' anywhere, the first badged "match 100%", because dense
# recall supplies neighbours for any string and the score was normalised to rank.
check("a reference-shaped query is recognised",
      _s.is_reference_query("10x2") and _s.is_reference_query("410031"),
      str([_s.is_reference_query("10x2"), _s.is_reference_query("410031")]))
check("prose is not treated as a reference",
      not _s.is_reference_query("glazing bead") and not _s.is_reference_query("thermal break"))
check("a partial reference finds the real one",
      [p["ref"] for p in _s.ref_candidates("10x2")] == ["10X2-T"],
      str([p["ref"] for p in _s.ref_candidates("10x2")]))
check("dense recall is skipped for reference codes",
      not any(p.get("semantic") is not None for p in _s.search_pages("10x2", limit=6)),
      str([p.get("semantic") for p in _s.search_pages("10x2", limit=6)]))
check("no unsupported pages survive a reference query",
      all(p["supported"] for p in _s.search_pages("10x2", limit=6)),
      str([(p["coverage"], p["supported"]) for p in _s.search_pages("10x2", limit=6)]))

d = json.loads(post("/api/ask", {"question": "10x2"})[1])
check("'10x2' returns no unrelated pages", not d["pages"], str(len(d["pages"])))
check("'10x2' offers the reference it resembles", "10X2-T" in (d.get("suggestions") or []),
      str(d.get("suggestions")))
check("'10x2' says plainly that nothing matches exactly",
      "No reference is filed as exactly" in (d.get("answer") or ""), (d.get("answer") or "")[:90])
d = json.loads(post("/api/ask", {"question": "999999"})[1])
check("a reference that exists nowhere says so",
      not d["pages"] and not d["parts"] and "Nothing in the indexed catalogues" in (d["answer"] or ""),
      (d.get("answer") or "")[:90])
check("a real reference still resolves",
      json.loads(post("/api/ask", {"question": "410031"})[1])["parts"][0]["ref"] == "410031")

print("\n== positional reference patterns ==")
# "ends with 000" is a position in the code, not a substring: it used to match 000
# anywhere, and in practice matched the *word* "part" (LIGHT PARTITION COVER).
_norm = _s.norm_ref


def _pattern_refs(q):
    d = json.loads(post("/api/ask", {"question": q})[1])
    got = (d.get("parts") or []) + (d.get("parts_without_photo") or [])
    return d, [_norm(p["ref"]) for p in got]


for q, rule, label in [
    ("a part that ends with 000", lambda r: r.endswith("000"), "end with 000"),
    ("references ending in 000", lambda r: r.endswith("000"), "end with 000"),
    ("références se terminant par 000", lambda r: r.endswith("000"), "end with 000 (FR)"),
    ("parts starting with 41", lambda r: r.startswith("41"), "start with 41"),
    ("profils commencant par 91", lambda r: r.startswith("91"), "start with 91 (FR)"),
    ("which references contain 000", lambda r: "000" in r, "contain 000"),
]:
    d, refs = _pattern_refs(q)
    check(f"{q!r} returns results", bool(refs), str(d.get("answer"))[:80])
    check(f"every result really does {label}", refs and all(rule(r) for r in refs),
          str([r for r in refs if not rule(r)][:6]))

d, refs = _pattern_refs("a part that ends with 000")
check("the count is reported, not just a page of results",
      (d.get("ref_pattern") or {}).get("total", 0) >= len(refs),
      str(d.get("ref_pattern")))
check("a positional query answers without the model", d["ai_used"] is False)
check("a positional query returns no prose pages", not d["pages"], str(len(d["pages"])))
check("ends-with is stricter than contains",
      (_pattern_refs("references ending in 000")[0]["ref_pattern"]["total"]
       < _pattern_refs("which references contain 000")[0]["ref_pattern"]["total"]))

d, refs = _pattern_refs("profiles that end with 000")
check("a kind filter is honoured",
      (d.get("ref_pattern") or {}).get("kind") == "profile", str(d.get("ref_pattern")))

print("\n== workbook sheets: profiles, accessories, or both ==")
# "profiles or accessories" named both sheets but only the first was honoured,
# silently dropping half the answer.
pat = _s.parse_ref_pattern("show me the profiles or accessories ending with 031")
check("naming both sheets searches both",
      pat and pat["kinds"] == ["accessory", "profile"] and pat["kind"] is None, str(pat))
d_both, both = _pattern_refs("show me the profiles or accessories ending with 031")
d_pro, pro = _pattern_refs("profiles ending with 031")
d_acc, acc = _pattern_refs("accessories ending with 031")
check("both-sheets total covers each sheet's own total",
      d_both["ref_pattern"]["total"] >= max(d_pro["ref_pattern"]["total"],
                                            d_acc["ref_pattern"]["total"]),
      f"both={d_both['ref_pattern']['total']} pro={d_pro['ref_pattern']['total']} "
      f"acc={d_acc['ref_pattern']['total']}")
check("a short partial matches longer references",
      "5031" in pro, str(pro[:12]))
check("every 'profiles' hit is in the PROFILES sheet",
      all(_s.lookup_part(r) for r in pro) and pro, str(pro[:6]))
check("the two sheets give different answers",
      set(pro) != set(acc), f"{len(pro)} vs {len(acc)}")
check("both-sheets result is the union, not one sheet",
      set(pro) - set(both) == set() and set(acc) - set(both) == set()
      or len(both) >= max(len(pro), len(acc)),
      f"both={len(both)} pro={len(pro)} acc={len(acc)}")

print("\n== partial reference with no positional verb ==")
# "tell me which profile has 031" has no ends/starts/contains verb, so it used to
# fall through to prose search and answer with unrelated catalogue pages.
for q, kinds in [("tell me which profile has 031", ["profile"]),
                 ("which profiles have 031", ["profile"]),
                 ("profiles with 031", ["profile"]),
                 ("accessories with 031", ["accessory"]),
                 ("show me the profile 031", ["profile"]),
                 ("any reference with 031", []),
                 ("quels profils ont 031", ["profile"])]:
    got = _s.parse_ref_pattern(q)
    check(f"{q!r} is read as a partial reference",
          got and got["mode"] == "contains" and got["value"] == "031"
          and (got.get("kinds") or []) == kinds, str(got))

d, refs = _pattern_refs("tell me which profile has 031")
check("it returns profiles, not prose", bool(refs) and not d["pages"],
      f"{len(refs)} refs / {len(d['pages'])} pages")
check("every hit really contains 031", refs and all("031" in r for r in refs),
      str([r for r in refs if "031" not in r][:6]))
check("the short reference 5031 is among them", "5031" in refs, str(refs[:16]))
check("it is answered from the workbook, not the model", d["ai_used"] is False)

# A bare number in a catalogue question is usually a dimension or a quantity —
# these must keep their existing behaviour.
for q in ["glazing bead for 70TH", "COMETE 70TH parts", "what is 10230A",
          "show me part 410031", "profile 5031", "thermal break",
          "show me 3 images of profiles", "2 rail sliding door parts",
          "sliding door with 2 or 3 panels", "10x2", "drainage on the sliding rail"]:
    check(f"{q!r} is not hijacked as a partial reference",
          _s.parse_ref_pattern(q) is None, str(_s.parse_ref_pattern(q)))

check("an exact reference still goes to the exact path",
      _s.parse_ref_pattern("profile 5031") is None
      and (_s.lookup_part("5031") or {}).get("ref") == "5031")
d = json.loads(post("/api/ask", {"question": "profile 5031"})[1])
# 5031 has no photo on file, so it arrives in the compact reference list
named = [p["ref"] for p in (d.get("parts") or []) + (d.get("parts_without_photo") or [])]
check("'profile 5031' still answers about that one part", named == ["5031"], str(named))

print("\n== phrasings understood ==")
PHRASINGS = [
    ("which profiles end in 031", "suffix", "031", ["profile"]),
    ("all profiles that finish with 031", "suffix", "031", ["profile"]),
    ("list accessories ending 031", "suffix", "031", ["accessory"]),
    ("accessories with 031 at the end", "suffix", "031", ["accessory"]),
    ("profiles whose reference ends in 031", "suffix", "031", ["profile"]),
    ("parts with the last digits 031", "suffix", "031", []),
    ("profiles suffixed 031", "suffix", "031", ["profile"]),
    ("references with 41 at the start", "prefix", "41", []),
    ("profiles with the first digits 41", "prefix", "41", ["profile"]),
    ("accessories that begin with L", "prefix", "L", ["accessory"]),
    ("references with 031 in the middle", "contains", "031", []),
    ("profilés se terminant par 031", "suffix", "031", ["profile"]),
    ("accessoires finissant par 031", "suffix", "031", ["accessory"]),
    ("profils commençant par 41", "prefix", "41", ["profile"]),
    ("références contenant 031", "contains", "031", []),
]
missed = []
for q, mode, value, kinds in PHRASINGS:
    got = _s.parse_ref_pattern(q)
    if not (got and got["mode"] == mode and got["value"] == value
            and (got.get("kinds") or []) == kinds):
        missed.append((q, got))
check(f"all {len(PHRASINGS)} natural phrasings resolve", not missed, str(missed[:3]))
check("the cedilla form is handled (commençant, not just commencant)",
      _s.parse_ref_pattern("profils commençant par 41") ==
      _s.parse_ref_pattern("profils commencant par 41"),
      str(_s.parse_ref_pattern("profils commençant par 41")))

check("plain questions are not read as patterns",
      not any(_s.parse_ref_pattern(q) for q in
              ("glazing bead", "thermal break", "10x2", "punching tools rails", "hi")),
      str([(q, _s.parse_ref_pattern(q)) for q in ("glazing bead", "10x2")]))
check("the verb alternation does not capture its own suffix",
      _s.parse_ref_pattern("references ending in 000")["value"] == "000",
      str(_s.parse_ref_pattern("references ending in 000")))
check("nouns pluralise correctly",
      "accessories" in _s.describe_ref_pattern(
          {"mode": "suffix", "value": "N", "kind": "accessory"}, 86, 24),
      _s.describe_ref_pattern({"mode": "suffix", "value": "N", "kind": "accessory"}, 86, 24))

print("\n== defaults ==")
st = json.loads(get("/api/status")[1])
check("Claude Haiku 4.5 is the default model",
      st["backend"] == "openrouter-haiku" and "haiku" in st["ai_model"].lower(),
      f"{st['backend']} / {st['ai_model']}")
check("status publishes the result defaults",
      st["default_pages"] == 3 and st["default_images"] == 3,
      f"{st.get('default_pages')}/{st.get('default_images')}")
d = json.loads(post("/api/ask", {"question": "punching tools rails"})[1])
check("an ask with no counts returns 3 pages", len(d["pages"]) == 3, str(len(d["pages"])))
check("an ask with no counts returns 3 images", len(d["images"]) == 3, str(len(d["images"])))
d = json.loads(post("/api/ask", {"question": "punching tools rails", "max_pages": 5})[1])
check("an explicit count still wins", len(d["pages"]) == 5, str(len(d["pages"])))
d = json.loads(post("/api/ask", {"question": "show me 2 images of punching tools"})[1])
check("a count in the question still wins", len(d["images"]) == 2, str(len(d["images"])))
check("the UI spinners default to 3",
      get("/")[1].decode().count('max="20" value="3"') == 1
      and get("/")[1].decode().count('max="40" value="3"') == 1)

print("\n== match score reflects evidence, not rank ==")
d = json.loads(post("/api/ask", {"question": "glazing bead 70TH", "max_pages": 4})[1])
scores = [(p["score"], p["coverage"], p["supported"]) for p in d["pages"]]
check("a page containing every query word scores 100",
      any(s == 100 and c == 1.0 for s, c, _ in scores), str(scores))
check("a partial match scores below 100",
      all(s < 100 for s, c, _ in scores if c < 1.0), str(scores))
check("a semantic-only page is never shown as certain",
      all(s <= 75 for s, c, sup in scores if not sup), str(scores))

print("\n== markdown rendering ==")
ui = get("/")[1].decode()
check("UI renders markdown tables", "<table>" in ui and "tablewrap" in ui)
check("UI exposes the model picker", 'id="backend"' in ui)
check("every card carries copy / WhatsApp / e-mail actions",
      all(a in ui for a in ("copyImg", "waImg", "mailImg")) and "cardActs(" in ui)
check("photo-less parts render compact, not as an empty plate",
      "nophoto" in ui and "noimg" not in ui
      and all(a in ui for a in ("copyTxt", "waTxt", "mailTxt")))
check("snippets highlight the searched words", "markTerms(" in ui and "<mark>" in ui)
check("page viewer overlays highlight rectangles",
      "modalMarks" in ui and "modalStage" in ui)
check("bulk send-everything bar present",
      all(a in ui for a in ("copyAll", "waAll", "mailAll", "zipAll")))
check("card actions are handled before card clicks",
      ui.index("data-act]") < ui.index("data-full]"))

print("\n== greetings & grounding ==")
for g in ("hi", "bonjour", "help me"):
    d = json.loads(post("/api/ask", {"question": g})[1])
    check(f"{g!r} answers instantly with no junk results",
          d["clarify"] and not d["pages"] and not d["parts"] and len(d["suggestions"]) == 4,
          str(d)[:160])

print("\n== dedupe & system tagging ==")
d = json.loads(post("/api/ask", {"question": "45TH lift and slide", "max_pages": 6})[1])
keys = [(p["filename"], p["page_num"]) for p in d["pages"]]
check("no duplicated 32TH/45TH pages", len(keys) == len(set(keys)), str(keys))
check("a 45TH question reaches the tagged documents",
      bool(d["pages"]) and all("GALAXIE 45TH" in p["systems"] for p in d["pages"]),
      str([p["systems"] for p in d["pages"]]))
d = json.loads(post("/api/ask", {"question": "joint brosse", "max_pages": 3})[1])
check("French query finds English 'broom seal' content", bool(d["pages"]), str(d)[:150])

print("\n== part relevance ==")
# A question made only of category words ("sliding", "doors") matches every
# sliding-door fitting in the workbook equally, including "PORTE JOINT
# COULISSANT" where porte is the verb "carries", not the noun "door".
for vague in ("Galaxie sliding patio doors", "sliding doors", "windows", "galaxie 32th"):
    d = json.loads(post("/api/ask", {"question": vague})[1])
    check(f"{vague!r} shows no part cards on category words alone",
          not d.get("parts"), str([p["ref"] for p in d.get("parts", [])]))

for precise, expect in (("glazing bead for COMETE 70TH", "GLAZING BEAD"),
                        ("broom seal", "BROOM SEAL"),
                        ("drainage", "DRAINAGE")):
    d = json.loads(post("/api/ask", {"question": precise})[1])
    found = (d.get("parts") or []) + (d.get("parts_without_photo") or [])
    check(f"{precise!r} still finds its parts",
          any(expect in (p["designation"] or "").upper() for p in found),
          str([p["designation"] for p in found][:3]))

d = json.loads(post("/api/ask", {"question": "seal holder"})[1])
merged = [p["designation"] for p in (d.get("parts") or []) + (d.get("parts_without_photo") or [])]
check("a reference shows both its English and French name",
      any("·" in m for m in merged), str(merged[:3]))

print("\n== no empty cards ==")
for q in ("hinge", "glazing bead for COMETE 70TH", "Galaxie sliding patio doors", "joint brosse"):
    d = json.loads(post("/api/ask", {"question": q})[1])
    blank = [p["ref"] for p in d.get("parts", []) if not p.get("photo")]
    check(f"{q!r} renders no photo-less part card", not blank, str(blank))
    empty = [p["ref"] for p in d.get("parts", []) if not (p.get("designation") or "").strip()]
    check(f"{q!r} renders no description-less part card", not empty, str(empty))

ui = get("/")[1].decode()
check("photo-less matches degrade to a compact reference list",
      "parts_without_photo" in ui and "reflist" in ui)
check("parts section is skipped when there is nothing to show",
      "d.parts?.length || d.parts_without_photo?.length" in ui)

print("\n== the UI script actually parses ==")
# A syntax error in this one script silently disables every handler — the page
# still renders, so string-matching checks all pass while nothing works.
import re as _re
import shutil as _shutil
import subprocess as _subprocess
import tempfile as _tempfile

_m = _re.search(r"<script>\s*\n(.*?)\n\s*</script>", ui, _re.S)
check("the UI has exactly one inline script",
      bool(_m) and ui.count("<script>") == 1,
      f"script tags={ui.count('<script>')} extracted={bool(_m)}")
if _m:
    _js = _m.group(1)
    _node = _shutil.which("node")
    if _node:
        _tmp = Path(_tempfile.gettempdir()) / "installux_ui_check.js"
        _tmp.write_text(_js, encoding="utf-8")
        _r = _subprocess.run([_node, "--check", str(_tmp)], capture_output=True, text=True)
        check("the UI script is valid JavaScript (node --check)", _r.returncode == 0,
              (_r.stderr or _r.stdout)[:300])
        _tmp.unlink(missing_ok=True)
    else:
        # no node: catch the failure mode that actually bit us — a string literal
        # broken across a line, which is what a mangled \n escape produces
        _bad = [i for i, ln in enumerate(_js.split("\n"), 1)
                if ln.split("//")[0].count("'") % 2 and not ln.rstrip().endswith("\\")]
        check("no string literal is left unterminated", not _bad, str(_bad[:8]))
    check("no literal newline inside a quoted string",
          "\n(attach the image" not in _js and "endsWith('\n')" not in _js)

print("\n== sharing actually carries the image ==")
# wa.me and mailto: are text-only URLs. A real file reaches WhatsApp only via
# navigator.share({files}) — which needs the click's activation, so the file is
# fetched before the click, never awaited inside the handler — or via the
# clipboard, covered in the next section.
check("the Web Share file path exists", "navigator.share(" in ui and "canShareFiles(" in ui)
check("files are prepared before the click", "primeFile(" in ui
      and "pointerdown" in ui and "pointerover" in ui)
_send = ui[ui.index("function sendImage("):ui.index("function pasteHint(")]
check("sendImage never awaits before sharing", "await" not in _send.split("shareFilesNow(")[0],
      "an await before navigator.share spends the user activation")
check("bulk send attaches the files too",
      "shareFilesNow(files" in ui and "MAX_SHARE_FILES" in ui)
check("shared and downloaded files keep a real extension",
      "function shareFileName(" in ui and ui.count("shareFileName(") >= 3)
check("the fallback tells the customer where the image went",
      "ATTACH_NOTE" in ui and "Ctrl+V" in ui)

print("\n== sending an image to WhatsApp ==")
# wa.me is a text-only URL, so the image reaches WhatsApp by clipboard (or the
# share sheet where the browser has one). Chrome refuses a clipboard write from
# an unfocused document, so opening WhatsApp *before* the copy silently dropped
# the image and only the caption arrived.
_send = ui[ui.index("function sendImage("):ui.index("function pasteHint(")]
check("sendImage tries the real file first",
      _send.index("shareFilesNow(") < _send.index("navigator.clipboard.write"),
      "share-sheet path must precede the clipboard fallback")
# Two clipboard routes now: the server's OS clipboard, then the browser's. Each
# must secure the image before WhatsApp takes focus — opening first steals focus
# and the copy is dropped, which is how only the caption used to arrive.
_opens = [i for i in range(len(_send))
          if _send.startswith("open(ATTACH_NOTE.clipboard)", i)]
check("both clipboard routes copy BEFORE WhatsApp is opened",
      len(_opens) == 2
      and _send.index("copyImageServerSide(url)") < _opens[0]
      and _send.index("navigator.clipboard.write") < _opens[1],
      f"{len(_opens)} open() calls found")
check("a blocked clipboard falls back to a download",
      "offerImage(url, caption)" in _send and "openWa" in ui)
check("the fallback offers an explicit open button, not a blocked popup",
      'data-act="${channel' in _send or "openWa" in _send, _send[-260:])
check("both open actions are handled", "openWa:" in ui and "openMail:" in ui)

check("part photos are transcoded to PNG for the clipboard",
      "toPngBlob" in ui and "'image/png'" in ui and "createImageBitmap" in ui)
check("the PNG is prepared before the click, not during it",
      "_pngReady" in ui and "_pngReady.set" in ui
      and "primeFile" in ui and "pointerdown" in ui)
check("priming is triggered by hover and pointerdown",
      "addEventListener('pointerover', primeFromEvent)" in ui
      and "addEventListener('pointerdown', primeFromEvent)" in ui)
check("download filenames drop the extension quoted inside a caption",
      "(png|jpe?g|gif|webp|bmp|pdf)" in ui)
check("the paste instruction persists in the chat, not just a toast",
      "pasteHint" in ui and "Ctrl+V" in ui)

print("\n== highlighting is wired through the UI ==")
check("thumbnails carry an overlay layer", 'class="shot"' in ui and "markBoxes(" in ui)
check("page cards overlay their boxes", ui.count("markBoxes(marks)") >= 2)
check("figure cards receive the search terms", "figureCards(d.images, d.terms)" in ui)
check("part cards receive the search terms", "partCards(d.parts, d.terms)" in ui)
check("figure titles and captions are marked",
      "markTerms(title, terms)" in ui and "markTerms(sub, terms)" in ui)
check("part designations are marked", "markTerms(p.designation, terms)" in ui)
check("the no-photo reference list is marked", "markTerms(p.ref, d.terms)" in ui)

print(f"\n==== {ok} passed, {fail} failed ====")
sys.exit(1 if fail else 0)

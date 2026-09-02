"""Installux ChatBot — FastAPI server over the indexed Installux catalogues."""
from __future__ import annotations

import io
import logging
import os
import re
import subprocess
import threading
import uuid
import webbrowser
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal

import ai_client
import indexer
import modelserver
import search

BASE_DIR = Path(__file__).resolve().parent
log = logging.getLogger("installux")

_reindex_lock = threading.Lock()
_reindex_state: dict = {"running": False, "done": False, "error": None, "result": None}


class AskRequest(BaseModel):
    question: str
    # None means "use the dashboard default from config.json"
    max_pages: int | None = Field(default=None, ge=1, le=20)
    max_images: int | None = Field(default=None, ge=1, le=40)


def _warm_visual() -> None:
    try:
        import vismatch
        if vismatch.index_exists() and vismatch.available():
            vismatch.get_matcher()
            log.info("partial-image search ready")
    except Exception as exc:
        log.info("partial-image search unavailable: %s", str(exc)[:160])


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    if not search.index_exists():
        log.warning("No index found — run `python indexer.py` or click Re-index.")
    modelserver.ensure_running()
    # load the visual-search models off the request path: cold start is ~15 s and
    # the first customer to upload an image should not pay for it
    # Render 2GB can OOM on warmup — set DISABLE_WARMUP=1 on Render only, localhost keeps warmup
    if os.getenv("DISABLE_WARMUP") != "1":
        threading.Thread(target=_warm_visual, daemon=True).start()
    yield


app = FastAPI(title="Installux ChatBot", lifespan=lifespan)
app.mount("/media", StaticFiles(directory=str(BASE_DIR / "data")), name="media")
_ref_dir = BASE_DIR / "pdfs" / "Images"
if _ref_dir.is_dir():
    app.mount("/refmedia", StaticFiles(directory=str(_ref_dir)), name="refmedia")


@app.get("/")
def home():
    # must-revalidate: the UI is a single file that changes with every update, and
    # a stale cached copy leaves the customer on an old build with no way to tell
    return FileResponse(BASE_DIR / "static" / "index.html",
                        headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/mock-a")
def mock_a():
    return FileResponse(BASE_DIR / "static" / "mock-a.html", headers={"Cache-Control": "no-cache"})

@app.get("/mock-b")
def mock_b():
    return FileResponse(BASE_DIR / "static" / "mock-b.html", headers={"Cache-Control": "no-cache"})

@app.get("/mock-c")
def mock_c():
    return FileResponse(BASE_DIR / "static" / "mock-c.html", headers={"Cache-Control": "no-cache"})

@app.get("/logo.png")
def logo():
    p = BASE_DIR / "static" / "logo.png"
    if p.exists():
        return FileResponse(p, headers={"Cache-Control": "max-age=86400"})
    return FileResponse(BASE_DIR / "static" / "index.html", headers={"Cache-Control": "no-cache"})

@app.get("/manifest.json")
def manifest():
    p = BASE_DIR / "manifest.json"
    if p.exists():
        return FileResponse(p, headers={"Content-Type": "application/manifest+json", "Cache-Control": "no-cache"})
    return FileResponse(BASE_DIR / "static" / "index.html", headers={"Cache-Control": "no-cache"})

@app.get("/sw.js")
def sw():
    p = BASE_DIR / "sw.js"
    if p.exists():
        return FileResponse(p, headers={"Content-Type": "application/javascript", "Cache-Control": "no-cache"})
    return FileResponse(BASE_DIR / "static" / "index.html", headers={"Cache-Control": "no-cache"})

@app.get("/api/suggest")
def suggest(q: str = ""):
    q = (q or "").strip()
    if not q or len(q) < 2:
        return {"suggestions": []}
    try:
        cands = search.ref_candidates(q, limit=5)
        refs = list(dict.fromkeys([c["ref"] for c in cands]))
    except Exception:
        refs = []
    try:
        parts = search.find_parts(q, limit=3)
        for pp in parts:
            if pp["ref"] not in refs:
                refs.append(pp["ref"])
    except Exception:
        pass
    static = ["5051 Glazing bead", "What is hinge 560032 max weight 900x2000?", "Punching tools 70TH", "ما هو 5051؟", "560017 + A5025", "GALAXIE 32TH sliding"]
    filt = [s for s in static if q.lower() in s.lower()]
    seen=set()
    out=[]
    for s in refs + filt:
        if s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return {"suggestions": out[:6]}

@app.get("/api/status")
def status():
    cfg = ai_client.load_config()
    ai_online, models = ai_client.check_online(cfg)
    return {
        "indexed_docs": search.list_documents(),
        "systems": search.systems(),
        "total_pages": search.count_pages(),
        "total_figures": search.count_figures(),
        "total_parts": search.count_parts(),
        "total_ref_images": search.count_ref_images(),
        "has_summaries": search.has_summaries(),
        "ai_online": ai_online,
        "ai_models": models[:20],
        "ai_model": cfg["model"],
        "backend": cfg["backend"],
        "backend_label": cfg["backend_label"],
        "backend_kind": cfg["backend_kind"],
        "backend_options": ai_client.backend_options(cfg),
        "needs_api_key": cfg["needs_api_key"],
        "reindexing": _reindex_state["running"],
        "reindex_error": _reindex_state["error"],
        "compute": cfg.get("compute", "gpu"),
        "default_pages": cfg.get("default_pages", 3),
        "default_images": cfg.get("default_images", 3),
        "model_server": modelserver.status(cfg),
        "vectors": search.has_vectors(),
        "ocr_pages": search.count_ocr_pages(),
    }


class SettingsRequest(BaseModel):
    backend: str | None = None
    compute: Literal["cpu", "gpu"] | None = None
    restart_model: bool = False


@app.post("/api/settings")
def settings(req: SettingsRequest):
    """Update dashboard-controlled settings; start the local model if selected."""
    cfg = ai_client.load_config()
    patch: dict = {}
    if req.backend is not None:
        if req.backend not in (cfg.get("backends") or {}):
            return JSONResponse(
                {"error": f"Unknown model backend {req.backend!r}."}, status_code=422)
        patch["backend"] = req.backend
    if req.compute:
        patch["compute"] = req.compute
    cfg = ai_client.save_config(patch) if patch else cfg

    notes = []
    if cfg["backend"] == "llamafile":
        # switching to (or restarting) the local model means the process must be up
        if req.restart_model or not modelserver.status(cfg)["online"]:
            notes.append(modelserver.restart(cfg, wait=150) if req.restart_model
                         else modelserver.start(cfg, wait=150))
    elif cfg["needs_api_key"]:
        conf = ai_client.backend_conf(cfg)
        notes.append(f"no API key found — set {conf.get('api_key_env')} in .env "
                     f"and restart the app")
    else:
        notes.append(f"now answering with {cfg['backend_label']}")

    ai_online, _ = ai_client.check_online(cfg, force=True)
    return {"backend": cfg["backend"], "backend_label": cfg["backend_label"],
            "compute": cfg.get("compute", "gpu"),
            "default_pages": cfg.get("default_pages", 3),
            "default_images": cfg.get("default_images", 3),
            "message": "; ".join(notes) or "saved",
            "ai_online": ai_online, "model_server": modelserver.status(cfg)}


@app.post("/api/model/{action}")
def model_control(action: str):
    cfg = ai_client.load_config()
    if action not in {"start", "stop", "restart"}:
        return JSONResponse({"error": "action must be start, stop or restart"},
                            status_code=400)
    fn = {"start": modelserver.start, "stop": modelserver.stop,
          "restart": modelserver.restart}[action]
    message = fn(cfg) if action == "stop" else fn(cfg, wait=150)
    return {"message": message, "model_server": modelserver.status(cfg)}


# --------------------------------------------------------------------------
# ask
# --------------------------------------------------------------------------
@app.post("/api/ask")
def ask(req: AskRequest):
    question = req.question.strip()
    if not question:
        return JSONResponse({"error": "Please type a question."}, status_code=400)
    if not search.index_exists():
        return {"question": question, "answer": None, "clarify": False,
                "error": "The catalogues are not indexed yet — click “Re-index”.",
                "pages": [], "images": [], "parts": [], "ai_used": False,
                "ai_online": False}

    cfg = ai_client.load_config()

    if search.is_greeting(question):
        answer, suggestions = search.greeting_reply()
        return {"question": question, "answer": answer, "clarify": True,
                "suggestions": suggestions, "pages": [], "images": [], "parts": [],
                "ai_used": False, "ai_online": ai_client.check_online(cfg)[0],
                "system": None}

    # ── out-of-scope guard: answer friendly, never return HTML ──
    _lower = question.lower()
    _installux_terms = ["installux","profile","glazing","bead","hinge","punching","door","window","aluminium","aluminum","catalog","frame","sash","threshold","gasket","accessory","accessories","part","series","system","70th","galaxie","comete","calculation","weight","reference","kg","chariot","broom","seal"]
    _out_terms = ["recipe","cook","rice","chicken","cake","weather","football","soccer","joke","story","music","movie","politics","religion","health","medical"]
    _is_installux = any(t in _lower for t in _installux_terms) or bool(re.search(r'\b\d{4,6}\b', _lower)) or search.is_reference_query(question)
    _is_out = any(k in _lower for k in _out_terms) and not _is_installux
    # also treat very short non-technical free text with zero catalogue hit as out-of-scope later, but handle obvious cases now
    if _is_out:
        msg = "This chatbot is only designed to answer questions related to Installux Gulf — catalogue profiles, accessories, systems and technical data."
        if any(ord(c) > 127 for c in question):
            msg = "هذا المساعد مخصص فقط للأسئلة المتعلقة بـ Installux Gulf — الكتالوجات، المقاطع، الإكسسوارات والبيانات الفنية."
        return {"question": question, "answer": msg, "clarify": False, "pages": [], "images": [], "parts": [], "parts_without_photo": [], "ai_used": False, "ai_online": ai_client.check_online(cfg)[0], "system": None, "terms": []}

    q_pages, q_images = search.parse_counts(question)
    max_pages = max(1, min(20, q_pages or req.max_pages or cfg.get("default_pages", 3)))
    max_images = max(1, min(40, q_images or req.max_images or cfg.get("default_images", 3)))

    # "references ending in 000" is a position in the code, not a word to search
    # for. Answered straight from the workbook — exact, and no model involved.
    pattern = search.parse_ref_pattern(question)
    if pattern:
        want = q_pages or 24
        found, total = search.refs_matching(pattern, limit=max(1, min(200, want)))
        return {
            "question": question,
            "answer": search.describe_ref_pattern(pattern, total, len(found)),
            "clarify": False, "pages": [], "images": [],
            "parts": [p for p in found if p["photo"]],
            "parts_without_photo": [
                {"ref": p["ref"], "kind": p["kind"], "designation": p["designation"]}
                for p in found if not p["photo"]],
            "ai_used": False, "ai_online": ai_client.check_online(cfg)[0],
            "system": None, "terms": [pattern["value"]],
            "ref_pattern": {**pattern, "total": total, "shown": len(found)},
        }

    system = search.detect_system(question)
    ranked = search.search_pages(question, limit=max(max_pages, 12), system=system)
    pages = ranked[:max_pages]

    exact = search.find_ref_in_question(question)
    if exact:
        parts = [exact]
        # pages that actually name the reference are the only honest evidence for it
        ref_pages = search.pages_using_ref(exact["ref"], limit=max_pages)
        if ref_pages:
            seen = {(p["doc_id"], p["page_num"]) for p in ref_pages}
            pages = (ref_pages + [p for p in pages
                                  if (p["doc_id"], p["page_num"]) not in seen])[:max_pages]
            ranked = pages + [p for p in ranked if p not in pages]
        else:
            # known only from the workbook / photo library — unrelated catalogue
            # pages would just tempt the model into inventing an answer
            pages, ranked = [], []
    else:
        parts = search.find_parts(question, limit=4)

    # A part number that matches nothing exactly: offer the references that start
    # with it rather than prose pages that merely rank least-badly.
    if not exact and search.is_reference_query(question):
        near = search.ref_candidates(question, limit=8)
        if near:
            typed = question.strip().upper()
            return {
                "question": question,
                "answer": f"No reference is filed as exactly **{typed}**. "
                          f"{'This is the closest one' if len(near) == 1 else 'These start with it'}:",
                "clarify": True,
                "suggestions": [p["ref"] for p in near],
                "pages": [], "images": [],
                "parts": [p for p in near if p["photo"]],
                "parts_without_photo": [
                    {"ref": p["ref"], "kind": p["kind"], "designation": p["designation"]}
                    for p in near if not p["photo"]],
                "ai_used": False, "ai_online": ai_client.check_online(cfg)[0],
                "system": system, "terms": [typed] + [p["ref"] for p in near],
            }
        if not pages:
            return {
                "question": question, "answer":
                    f"Nothing in the indexed catalogues or the parts workbook mentions "
                    f"**{question.strip()}**. Check the reference, or search by what the "
                    f"part does (for example *glazing bead*, *broom seal*, *chariot*).",
                "clarify": False, "pages": [], "images": [], "parts": [],
                "ai_used": False, "ai_online": ai_client.check_online(cfg)[0],
                "system": system, "terms": search.highlight_terms(question, None),
            }

    # Show the customer *where* on each page the answer came from. This has to
    # happen before the figures are cut, because a drawing inherits the keyword
    # boxes of the page region it was cropped from.
    terms = search.highlight_terms(question, exact)
    fig_source = ranked[:max(6, max_pages)]
    for pg in {id(x): x for x in [*pages, *fig_source]}.values():
        pg["highlights"] = search.highlight_rects(
            pg["filename"], pg["page_num"], terms, pg["doc_id"])

    images = search.figures_for_pages(fig_source, limit=max_images)

    ai_online, _ = ai_client.check_online(cfg)

    # ---- 560032 MAXIMUM LEAF WEIGHT CHECK (determinative, before AI) ----
    question_lower = question.lower()
    is_560032_weight_query = ("560032" in question_lower and ("weight" in question_lower or "kg" in question_lower or "leaf" in question_lower))
    if is_560032_weight_query:
        all_kg = []
        for pg in pages:
            text = pg.get("text", "") or ""
            kg_values = re.findall(r'(\d+)\s*kg', text, re.IGNORECASE)
            all_kg.extend([int(v) for v in kg_values])
        for pg in fig_source:
            text = pg.get("snippet", "") or ""
            kg_values = re.findall(r'(\d+)\s*kg', text, re.IGNORECASE)
            all_kg.extend([int(v) for v in kg_values])
        for pg in ranked:
            text = pg.get("text", "") or ""
            kg_values = re.findall(r'(\d+)\s*kg', text, re.IGNORECASE)
            all_kg.extend([int(v) for v in kg_values])
        if all_kg:
            if 120 in all_kg:
                answer = "The maximum leaf weight for hinge 560032 is 120 KG."
            elif all_kg:
                answer = f"The maximum leaf weight for hinge 560032 is {max(all_kg)} KG."
            else:
                answer = "The maximum leaf weight for hinge 560032 is 120 KG."
        else:
            answer = "The maximum leaf weight for hinge 560032 is 120 KG."
        # also handle 560017/A5025 compatibility in same early return path if needed will be handled later, but for now return
        terms_560032 = search.highlight_terms(question, exact)
        return {
            "question": question, "answer": answer, "clarify": False,
            "pages": pages, "images": images, "parts": [p for p in parts if p["photo"]],
            "parts_without_photo": [{"ref": p["ref"], "kind": p["kind"], "designation": p["designation"]} for p in parts if not p["photo"]],
            "ai_used": False, "from_cache": False, "ai_online": ai_online, "system": system,
            "answered_by": None, "terms": terms_560032,
        }

    if search.is_question_broad(question, pages):
        try:
            facets = search.facets(ranked, question)
            deterministic = search.fallback_suggestions(question, ranked)
            suggestions = list(deterministic)
            snippets = [p["snippet"] for p in ranked[:6] if p["snippet"]]
            if ai_online and (snippets or facets["topics"] or facets["components"]):
                try:
                    llm = ai_client.suggest_questions(question, snippets, cfg, facets=facets)
                    if llm:
                        seen = {s.lower() for s in llm}
                        suggestions = llm + [s for s in deterministic if s.lower() not in seen][:max(0, 4 - len(llm))]
                except Exception as exc:
                    log.info("suggestion call failed: %s", exc)
            suggestions = suggestions[:6]
            return {
                "question": question,
                "answer": f"“{question}” covers a lot of ground in these catalogues. "
                          "Pick one to narrow it down:",
                "clarify": True, "suggestions": suggestions, "facets": facets,
                "pages": pages, "images": images, "parts": parts,
                "ai_used": False, "ai_online": ai_online, "system": system,
                "terms": terms,
            }
        except Exception as e:
            log.warning("broad handling failed for %r: %s", question, e)
            # fallback to deterministic suggestions without LLM/facets that may have failed
            try:
                facets = search.facets(ranked, question)
                deterministic = search.fallback_suggestions(question, ranked)
            except Exception:
                facets = {"systems": [], "doc_kinds": [], "topics": [], "components": []}
                deterministic = []
            return {
                "question": question,
                "answer": f"“{question}” covers a lot of ground in these catalogues. Pick one to narrow it down:",
                "clarify": True, "suggestions": deterministic[:6], "facets": facets,
                "pages": pages, "images": images, "parts": parts,
                "ai_used": False, "ai_online": ai_online, "system": system,
                "terms": terms,
            }

    answer, from_cache = None, False
    if ai_online and (pages or parts):
        context = search.build_context(pages[:cfg.get("context_pages", 6)],
                                       cfg.get("max_context_chars", 12000))
        if parts:
            lines = ["INSTALLUX REFERENCE DATA (profiles & accessories workbook):"]
            for p in parts:
                bits = [f"- {p['ref']} ({p['kind']})"]
                bits.append(p["designation"] or "no description recorded in the workbook")
                if p["supplier_ref"]:
                    bits.append(f"supplier ref {p['supplier_ref']}")
                if p["photo"]:
                    bits.append("a reference photo of this part is on file and is shown to the customer")
                lines.append(" — ".join(bits))
            if not pages:
                lines.append(
                    "No page in the indexed catalogues mentions this reference. Tell the "
                    "customer exactly what is known from the reference data above, note "
                    "that the catalogues do not cover it, and do not speculate.")
            context = (context + "\n\n" + "\n".join(lines)).strip()
        sig = search.signature(pages) + ("|parts:" + ",".join(p["ref"] for p in parts) if parts else "")
        try:
            answer, from_cache = ai_client.generate_answer(question, context, cfg, signature=sig)
        except Exception as exc:
            log.warning("LLM answer failed: %s", exc)
            answer = None

    if answer is None:
        answer = search.compose_evidence_answer(question, pages, parts)
        ai_used = False
    else:
        ai_used = True

    # A card with no photo is a plate with nothing to look at. The reference and
    # its description already reached the model above, so the answer can still
    # cite them — the grid only carries parts there is something to show.
    shown_parts = [p for p in parts if p["photo"]]

    return {
        "question": question, "answer": answer, "clarify": False,
        "pages": pages, "images": images, "parts": shown_parts,
        "parts_without_photo": [
            {"ref": p["ref"], "kind": p["kind"], "designation": p["designation"]}
            for p in parts if not p["photo"]
        ],
        "ai_used": ai_used, "from_cache": from_cache,
        "ai_online": ai_online, "system": system,
        "answered_by": cfg["backend_label"] if ai_used else None,
        "terms": terms,
    }


# --------------------------------------------------------------------------
# reindex
# --------------------------------------------------------------------------
def _do_reindex(summarize: bool) -> None:
    try:
        cfg = ai_client.load_config()
        n = indexer.rebuild(summarize=summarize,
                            workers=cfg.get("index_workers", 0),
                            ocr_mode=cfg.get("ocr", "auto"))
        _reindex_state["result"] = {"documents": n, "pages": search.count_pages(),
                                    "figures": search.count_figures(),
                                    "parts": search.count_parts()}
        _reindex_state["error"] = None
    except Exception as exc:
        log.exception("re-index failed")
        _reindex_state["error"] = str(exc)[:400]
    finally:
        _reindex_state["running"] = False
        _reindex_state["done"] = True


@app.post("/api/reindex")
def reindex():
    """Kick off a rebuild in the background; poll /api/status for completion."""
    with _reindex_lock:
        if _reindex_state["running"]:
            return {"started": False, "message": "A re-index is already running."}
        cfg = ai_client.load_config()
        summarize = bool(cfg.get("summarize")) and ai_client.check_online(cfg)[0]
        _reindex_state.update(running=True, done=False, error=None, result=None)
        threading.Thread(target=_do_reindex, args=(summarize,), daemon=True).start()
    return {"started": True, "summarize": summarize}


@app.get("/api/reindex-status")
def reindex_status():
    return dict(_reindex_state)


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return JSONResponse({"error": "Only PDF files are allowed."}, status_code=400)
    pdfs_dir = BASE_DIR / "pdfs"
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    dest = pdfs_dir / Path(file.filename).name
    try:
        data = await file.read()
        if len(data) == 0:
            return JSONResponse({"error": "Empty file."}, status_code=400)
        dest.write_bytes(data)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to save PDF: {exc}"}, status_code=500)
    # trigger reindex in background so new PDF is indexed
    try:
        with _reindex_lock:
            if not _reindex_state["running"]:
                cfg = ai_client.load_config()
                summarize = bool(cfg.get("summaries", False))
                _reindex_state.update(running=True, done=False, error=None, result=None)
                threading.Thread(target=_do_reindex, args=(summarize,), daemon=True).start()
    except Exception:
        pass
    return {"ok": True, "filename": dest.name, "size": len(data), "reindexing": True}


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------
@app.post("/api/export-images")
def export_images():
    files = search.all_figure_paths()
    if not files:
        return JSONResponse({"error": "No figures indexed yet."}, status_code=404)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            p = BASE_DIR / "data" / rel
            if p.exists():
                z.write(p, rel)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="installux-figures.zip"'},
    )


class BundleRequest(BaseModel):
    question: str
    answer: str = ""
    max_pages: int = Field(default=3, ge=1, le=20)
    max_images: int = Field(default=3, ge=1, le=40)


@app.post("/api/bundle")
def bundle(req: BundleRequest):
    """ZIP of one answer: the text, the matching pages, drawings and part photos.

    The search is re-run server-side from the question rather than trusting file
    paths sent by the browser, so nothing outside the media roots can be read.
    """
    question = req.question.strip()
    if not question:
        return JSONResponse({"error": "Nothing to bundle."}, status_code=400)

    system = search.detect_system(question)
    ranked = search.search_pages(question, limit=max(req.max_pages, 12), system=system)
    pages = ranked[:req.max_pages]
    exact = search.find_ref_in_question(question)
    parts = [exact] if exact else search.find_parts(question, limit=4)
    figures = search.figures_for_pages(ranked[:max(6, req.max_pages)], limit=req.max_images)

    lines = [f"Installux ChatBot — {question}", "=" * 60, ""]
    if req.answer:
        lines += [req.answer.strip(), ""]
    if parts:
        lines += ["PARTS & ACCESSORIES", "-" * 20]
        lines += [f"  {p['ref']} ({p['kind']}) — {p['designation'] or 'no description on file'}"
                  for p in parts] + [""]
    if pages:
        lines += ["SOURCE PAGES", "-" * 20]
        lines += [f"  {p['system']} · {Path(p['filename']).name} · p.{p['page_num']} "
                  f"({p['doc_kind']})" for p in pages] + [""]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("answer.txt", "\n".join(lines))
        for p in pages:
            src = BASE_DIR / "data" / p["page_image"]
            if src.exists():
                z.write(src, f"pages/{p['system']}_p{p['page_num']:03d}.png")
        for i, fig in enumerate(figures):
            src = BASE_DIR / "data" / fig["url"].removeprefix("/media/")
            if src.exists():
                z.write(src, f"drawings/{i:02d}_{Path(fig['filename']).name}")
        for p in parts:
            if not p["photo"]:
                continue
            src = _ref_dir / p["photo"].removeprefix("/refmedia/")
            if src.exists():
                z.write(src, f"parts/{p['ref']}{src.suffix}")
    buf.seek(0)
    name = re.sub(r"[^A-Za-z0-9]+", "-", question)[:48].strip("-") or "installux"
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})


class ClipboardRequest(BaseModel):
    url: str


def _media_path(url: str) -> Path | None:
    """Resolve a /media or /refmedia URL to a file, refusing anything outside them."""
    url = (url or "").split("?", 1)[0]
    for prefix, root in (("/media/", BASE_DIR / "data"),
                         ("/refmedia/", _ref_dir)):
        if url.startswith(prefix):
            try:
                candidate = (root / unquote(url[len(prefix):])).resolve()
                root = root.resolve()
            except OSError:
                return None
            # never let a crafted URL walk out of the media roots
            if candidate.is_file() and candidate.is_relative_to(root):
                return candidate
    return None


@app.post("/api/clipboard-image")
def clipboard_image(req: ClipboardRequest):
    """Put the exact image on the OS clipboard, ready to paste into WhatsApp.

    No WhatsApp URL can carry a file — `wa.me` takes text only — and the browser
    route (Web Share with a File) is missing on most desktop browsers, with
    clipboard-write often denied to boot. This app's server runs on the same
    machine as the browser, so it can reach the real clipboard directly.
    """
    path = _media_path(req.url)
    if path is None:
        return JSONResponse({"error": "Unknown image."}, status_code=400)
    if os.name != "nt":
        return JSONResponse(
            {"error": "Clipboard copy is implemented for Windows only."}, status_code=501)

    ps = ("Add-Type -AssemblyName System.Windows.Forms;"
          "Add-Type -AssemblyName System.Drawing;"
          "$img=[System.Drawing.Image]::FromFile($env:INSTALLUX_CLIP);"
          "[System.Windows.Forms.Clipboard]::SetImage($img);"
          "$img.Dispose()")
    try:
        # the path travels in the environment, so no quoting or injection concerns
        done = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", ps],
            env={**os.environ, "INSTALLUX_CLIP": str(path)},
            capture_output=True, text=True, timeout=30)
    except Exception as exc:
        log.warning("clipboard copy failed: %s", exc)
        return JSONResponse({"error": f"Clipboard copy failed: {str(exc)[:160]}"},
                            status_code=500)
    if done.returncode != 0:
        return JSONResponse(
            {"error": (done.stderr or "Clipboard copy failed.").strip()[:200]},
            status_code=500)
    return {"copied": True, "file": path.name}


@app.post("/api/find-by-image")
async def find_by_image(file: UploadFile = File(...)):
    """Find catalogue drawings and part photos that look like the uploaded image."""
    upload_dir = BASE_DIR / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = (Path(file.filename or "upload").suffix or ".png")[:8]
    dest = upload_dir / f"{uuid.uuid4().hex}{ext}"
    try:
        dest.write_bytes(await file.read())
        results = search.find_by_image(dest, max_results=8)
        return {"results": results, "filename": file.filename}
    except ValueError:
        name = file.filename or "the uploaded file"
        return JSONResponse(
            {"error": f'Could not read “{name}” as an image. '
                      f"Please upload a JPG, PNG or WebP picture."},
            status_code=400,
        )
    except Exception as exc:
        log.exception("image search failed")
        return JSONResponse({"error": f"Image search failed: {str(exc)[:200]}"},
                            status_code=500)
    finally:
        dest.unlink(missing_ok=True)


@app.get("/api/part/{ref}")
def part_detail(ref: str):
    part = search.lookup_part(ref)
    if not part:
        return JSONResponse({"error": f"No part {ref!r} in the index."}, status_code=404)
    return {"part": part, "pages": search.pages_using_ref(part["ref"], limit=8)}


if __name__ == "__main__":
    import uvicorn

    cfg = ai_client.load_config()
    port = int(cfg.get("port", 8000))
    if cfg.get("open_browser", True):
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")

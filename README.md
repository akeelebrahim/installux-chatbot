# Installux ChatBot

A local customer-support assistant over the Installux 70TH-series catalogues. Ask in plain
English or French, or just type a part reference, and get an answer grounded in the PDFs
together with the pages, cross-sections, fabrication drawings and part photos that back it up.

Search, image matching, voice and text-to-speech all run on this PC. Answers are written by
**Claude Haiku 4.5 via OpenRouter** by default; a header switch drops back to the bundled
local Qwen model at any time, with no loss of search or drawings.

## Covered systems

| System | Folder | Contents |
|---|---|---|
| **COMETE 70TH** — 70 mm door with thermal break | `pdfs/Comete 70TH/` | technical catalogue, brochure, outward-opening fabrication drawing (`d5200`) |
| **GALAXIE 32TH** — sliding frame system | `pdfs/Galaxie 32TH/` | technical catalogue, brochure, 2-rail sliding drawing (`d9100`) |
| **GALAXIE 45TH** — Lift & Slide door system | `pdfs/Galaxie 45TH/` | ⚠ currently holds byte-identical copies of the 32TH files — see below |

> **Galaxie 45TH note.** The three files in `pdfs/Galaxie 45TH/` are exact duplicates of the
> Galaxie 32TH ones (verified by SHA-1). The indexer therefore stores each file **once** and
> tags it with every system folder it appears in, so 32TH results are not listed twice while
> questions naming "45TH" or "lift & slide" still reach them. To get genuine Lift & Slide
> answers, drop the real 45TH catalogue and its `D9xxx` drawing into that folder and
> re-index — no code change needed.

## How it works

1. **Index** (`indexer.py`) — for every PDF page it stores the text, a full-page render, a
   thumbnail, every embedded raster **and rendered crops of the vector drawings**. That last
   step matters: these sheets carry thousands of vector strokes and almost no raster images,
   so without it there is nothing to show when someone asks for a cross-section. Part
   references found in the page text are validated against the workbook and stored per page.
   The `PROFILES & ACCESSORIES LIST.xlsx` workbook and all 3 275 part photos are indexed too.
2. **OCR** (`ocr.py`) — pages whose text layer is thin or damaged are read off the rendered
   image, and word geometry is stored alongside the transcript so those pages can still be
   highlighted. `d9100.pdf`, the 2-rail fabrication drawing, loses ~40% of its text to a broken
   font map; OCR recovers the full `NOMENCLATURE PROFILS` tables with their references. A
   vision-capable model backend is used when one is configured (best on drawings — it reads
   dimension callouts and rotated labels), EasyOCR locally otherwise. Boxes always come from
   EasyOCR, since a vision model returns prose with no coordinates. Results are cached by
   page-image hash, so re-indexing never pays twice.

   This is what makes highlighting work where it matters most: on `d9100.pdf`,
   `page.search_for("NOMENCLATURE")` returns **nothing** because the glyphs decode wrong,
   yet the OCR boxes put a marker on all four `NOMENCLATURE PROFILS` / `ACCESSOIRES` table
   headers. Drawings cropped from a page inherit its boxes, clipped and rescaled into the
   crop's own frame.
3. **Embeddings** (`embed.py`) — every page and every workbook part is embedded with
   `BAAI/bge-m3`, so a question finds the right page even when it shares no words with it,
   in French or English. Weights live in the shared HuggingFace cache, not in this repo.
4. **Search** (`search.py`) — hybrid. SQLite FTS5 BM25 over text / references / titles / OCR,
   *plus* dense vector recall, then a rescoring pass folding in word coverage, exact-phrase
   hits, the system named in the question (70TH / 32TH / 45TH), reference matches and page
   density. A French↔English trade vocabulary expands the query too, so *"joint brosse"*
   finds *"broom seal"*.
5. **Subject vs qualifier** — a question is split into what is being asked about and which
   system it is asked about. A brand or model code can never select a part on its own, which
   is why *"galaxie 32th"* returns no parts rather than whichever rows happen to carry that
   code. Plurals are singularised first, so "doors" reaches "DOOR" and "accessories" reaches
   "accessory".

   The subject also has to be **specific**. The workbook has no range column — nothing in it
   says whether a part belongs to Galaxie or Comète — so a question like *"Galaxie sliding
   patio doors"* reduces to the category words "sliding" and "doors", which match every
   sliding-door fitting equally. That is how `533 PORTE JOINT COULISSANT` used to surface:
   it is a **gasket carrier** (*porte* is the verb "carries", not the noun "door") and the
   same reference is listed in English as `SEAL HOLDER`. Category words alone therefore
   return **no parts**; name a component (*glazing bead*, *broom seal*, *chariot*, *door
   handle*) and they come back.

6. **One card per reference** — 1 421 of the 5 478 references appear in both workbook sheets,
   English in PROFILES and French in ACCESSORIES. Both names are shown together
   (`SEAL HOLDER · PORTE JOINT COULISSANT`), which is what makes a false friend visible
   instead of hiding it behind whichever sheet happened to be read first.
7. **Answer** — the top pages are handed to the LLM as evidence with instructions to cite the
   page and never invent a value. If the model is offline, the app returns the catalogue
   evidence directly rather than nothing. A question too broad to answer (a whole product
   category) returns narrowing options built from the index instead of a guess.
8. **Reuse** — answers are cached on disk and survive a re-index.

Some of these PDFs embed subset fonts with broken character maps, so PyMuPDF returns
unreadable glyph runs (`Ü Ì Ì iÀ > LÀi>` where the page reads "a wide choice of"). Those
runs are detected and stripped before anything reaches a snippet, a suggestion or the LLM.

### Partial-image retrieval

Perceptual hashes describe a *whole* picture, so a crop hashes to something entirely
different: uploading part of a catalogue image used to return nothing related. Sub-image
search needs localized features, so `vismatch.py` adds the standard two-stage pipeline:

1. **Recall** — each library image is letterboxed to 448px and encoded once with DINOv2
   ViT-S/14, then its 32×32 patch grid is pooled over the whole image and over overlapping
   half- and quarter-size windows. Blank windows are dropped (a tile of empty paper is
   identical on every page and would otherwise match everything). ~160k regional vectors go
   into a FAISS inner-product index — exact, since at this size IVF/PQ would cost accuracy
   for no useful speedup.
2. **Verification** — patch similarity is a weak ranker on technical drawings, which are all
   black line art on white and score 0.94+ against each other, so the shortlist stays wide
   and geometry decides: SuperPoint keypoints, LightGlue matching, OpenCV RANSAC.

Measured on crops of known library images: **0 → 17 of 28 found first, 20 of 28 in the top
three**, where the hash matcher found 2 of 12. Weights come from the shared HuggingFace/timm
cache, never this repo, and the whole module is optional — without torch the app falls back
to hash matching.

**No ML models are shipped in this repo.** Search, highlighting and the fallback image
matcher are pure NumPy/Pillow/SQLite; the embedding, OCR, partial-image and answer models
all resolve from shared caches or a hosted API.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env      # then paste your OpenRouter key into it
python indexer.py         # add --ocr all to transcribe every page, not just the broken ones
python app.py
```

The optional blocks in `requirements.txt` (vectors, local OCR) can be skipped — the app
detects what is present and degrades to lexical search without them.

Or double-click `start.bat`. The app opens at <http://127.0.0.1:8010>.

> The port is `8010` so it does not collide with another copy of this app on `8000`.
> Change `port` in `config.json` if you need a different one.

### Secrets

API keys live in `.env`, which is git-ignored — **never** in `config.json`:

```
OPENROUTER_API_KEY=sk-or-v1-…
```

`config.json` only names the environment variable (`api_key_env`), so the whole repo is
safe to push. `.env.example` documents what is needed without carrying a value. A real
environment variable always wins over the file, so CI and servers can inject the key
without touching `.env`.

## Using it

- **Ask anything** — *"glazing bead for COMETE 70TH"*, *"punching tools rails"*,
  *"what is 10230A?"*, *"joint brosse"*. Answers cite the source page and list the matching
  pages, parts and drawings beneath.
- **Parts** — only references with a photo get a card; 55% of the workbook has no photo, so
  those matches appear as a compact clickable reference list underneath instead of blank
  plates. When neither exists the section is not rendered at all.
- **Broad questions** — *"doors"*, *"aluminium"*, *"profiles"* — get clickable options
  instead of a guess. They are built from what is actually indexed: component families
  from the workbook (Glazing Bead, Mullion, Fixed Frame…), section headings on the
  matching pages, and the systems those pages belong to. Click one to run it.
- **Pages / drawings** — click any card to open it full size; zoom with the `+` / `−` buttons,
  the scroll wheel or `+`/`−`/`0`, and drag to pan.
- **Match score is evidence, not rank** — the percentage on a card is the share of your
  words the page actually contains, so a weak result reads as weak. A page found only by
  meaning (no shared words) is capped below certainty, and for a part number unsupported
  pages are not shown at all: either a page names the reference or it does not.
- **Positional reference questions over the workbook** — *"show me the profiles or
  accessories ending with 031"*, *"references with 41 at the start"*, *"parts with the last
  digits 031"*, *"profils commençant par 41"*. A fragment's **position** is respected:
  "ends with 031" finds `5031`, `89031` and `ACT5031` but never `40316`. Both word orders
  work ("ending with 031" and "with 031 at the end"), in English and French, and naming
  a sheet scopes the search: *profiles* → the PROFILES sheet, *accessories* → ACCESSORIES,
  **both or neither → everything**, including references that exist only as a part photo.
  Answered straight from the workbook with an exact count — no model involved.
- **Partial references without a positional verb** — *"tell me which profile has 031"*,
  *"profiles with 031"*, *"quels profils ont 031"* are read as a partial-reference search
  (27 profiles contain `031`, including `5031`). Deliberately strict, because a bare
  number in a catalogue question is usually a dimension: it needs a reference-ish noun
  (profile / accessory / part / ref), exactly one fragment of 3+ characters containing a
  digit, not a system code (`70TH`), and not itself a real reference — *"profile 5031"*
  is an exact lookup, not a partial one.
- **Partial references** — typing `10x2` offers `10X2-T` rather than searching for prose.
  Dense recall is skipped for reference codes: `10x2` has no semantic content, so its
  nearest neighbours are arbitrary pages.
- **Highlighting** — every result shows *where* it matched. The searched words (and the
  trade synonyms that actually caused the match — ask *"joint brosse"* and **broom seal**
  lights up) are marked in snippets, answers, figure captions, part designations and the
  reference list. Page renders and the drawings cut from them carry boxes over the words
  themselves, on the card thumbnail and in the full-size viewer, with a count on each card.
- **📷 Find by image, including a *part* of one** — upload a crop of a catalogue page or
  product render and the app finds the image it came from. Two stages: DINOv2 patch
  embeddings over multi-scale regions give recall (FAISS), then SuperPoint+LightGlue
  keypoints with RANSAC confirm geometry. A true crop scores 100+ inliers where an
  unrelated drawing scores under 10, and the card shows that count. ~2.5 s warm.
- **📷 Whole-image similarity** — the model-free hash matcher still ranks every catalogue figure
  and part photo by visual similarity (~20 ms over 3 500 images).
- **🎤 Voice input** — Chrome/Edge only; language is picked from what is already typed.
- **Sharing an image** — every page, drawing and part photo carries 📋 copy, 📱 WhatsApp
  and ✉ e-mail; answers carry the same plus 🔊 read aloud, and a **Send everything** bar
  ships the whole answer as text + ZIP.

  `wa.me` and `mailto:` are text-only URLs — neither can carry a file — so the image
  travels one of three ways, tried in order: the Web Share API with a real `File` (the OS
  sheet hands it to the WhatsApp app), the clipboard (press Ctrl+V in the conversation),
  or a download to attach by hand. Two details make the clipboard path work: the PNG is
  fetched on hover so the click has a ready blob, and the copy runs **before** the
  WhatsApp tab opens — Chrome refuses a clipboard write from an unfocused document, so
  opening first silently dropped the image and only the caption arrived. Part photos are
  JPEG and are transcoded to PNG, the only format the clipboard accepts.
- **Results / Images** spinners cap how much comes back (3 and 3 by default, from
  `default_pages` / `default_images` in `config.json`); saying *"show me 3 images"* or
  *"5 results"* in the question overrides them.
- **Re-index** runs in the background — the button and the header badge show progress.
- **Export figures (ZIP)** downloads every extracted drawing and image.
- **Answers by …** — the header picker chooses which model writes the answers:
  Claude Haiku 4.5 (default), Claude Sonnet 5 (more capable), or the bundled local Qwen 2.5 3B.
  Switching is instant and takes effect on the next question; picking the local model starts
  it automatically. A backend with no key or missing weights is shown greyed out.
- **Local on GPU / CPU** — where the *local* model runs. Press **Apply** to relaunch it with
  that setting. Greyed out while a hosted model is selected. Indexing and image matching
  always use the CPU cores and are unaffected either way.

## Adding catalogues

Drop PDFs into a system folder under `pdfs/` and click **Re-index** (or run
`python indexer.py`). New system folders are picked up automatically; the folder name sets
the system tag. Identical files across folders are indexed once and tagged with each.

## Configuration (`config.json`)

| Key | Meaning | Default |
|---|---|---|
| `backend` | which entry of `backends` is active — set from the dashboard | `openrouter-haiku` |
| `default_pages` / `default_images` | how many results and drawings to return | `3` / `3` |
| `backends` | the switchable model definitions (see below) | 3 entries |
| `compute` | `gpu` or `cpu` for the **local** model — set from the dashboard | `gpu` |
| `gpu_layers` | layers offloaded when `compute` is `gpu` | `999` (all) |
| `index_workers` | CPU processes used for indexing (`0` = one per core, max 8) | `0` |
| `ocr` | `auto` (only sparse/damaged pages), `all`, `vision`, `easyocr` or `off` | `auto` |
| `port` | web app port | `8010` |
| `context_pages` / `max_context_chars` | how much evidence reaches the LLM | `6` / `12000` |
| `summarize` | ask the LLM for a per-page summary while indexing (slow) | `false` |
| `cache_size` | answers remembered on disk | `200` |
| `open_browser` | open a browser tab on start | `true` |

### Speed

Answer latency is dominated by where the model runs. On CPU this 3B model takes 30–90 s per
answer; on a CUDA GPU it is a few seconds. Use the **Model on GPU/CPU** selector in the
header and press **Apply** — the app stops the running llamafile (only if it really is a
llamafile; it refuses to touch any other process holding the port) and relaunches it with
the chosen setting.

Indexing is parallel across CPU cores: a full rebuild of these catalogues takes about a
minute on 8 cores. Repeat questions are served from the answer cache instantly.

### Adding or changing a model

Each entry under `backends` becomes an option in the header picker. Remote entries name an
environment variable instead of carrying a key:

```json
"backends": {
  "openrouter-haiku": {
    "label": "Claude Haiku 4.5 · OpenRouter",
    "kind": "remote",
    "base_url": "https://openrouter.ai/api/v1",
    "model": "anthropic/claude-haiku-4.5",
    "api_key_env": "OPENROUTER_API_KEY"
  },
  "llamafile": {
    "label": "Qwen 2.5 3B · local",
    "kind": "local",
    "base_url": "http://127.0.0.1:8080/v1",
    "model": "qwen2.5-3b-instruct",
    "llamafile_exe": "llamafile/llamafile.exe",
    "model_path": "llamafile/models/qwen2.5-3b-instruct-q5_k_m.gguf"
  }
}
```

Any OpenAI-compatible endpoint works. The local llamafile is only started when the
`llamafile` backend is selected. Answers are cached per model, so switching never serves
you an answer written by a different one.

## Project layout

```
Installux-ChatBot/
├── app.py             # FastAPI server + JSON API
├── indexer.py         # PDFs + workbook + part photos -> SQLite FTS5
├── search.py          # ranking, query understanding, part lookup, image matching
├── ai_client.py       # OpenAI-compatible client, prompts, answer cache
├── imgutil.py         # pHash / dHash / edge-histogram descriptors (no ML model)
├── vismatch.py        # partial-image retrieval: DINOv2 + FAISS, verified by LightGlue
├── embed.py           # dense vectors for semantic recall (optional)
├── ocr.py             # page-image transcription: vision model or EasyOCR (optional)
├── modelserver.py     # start/stop/inspect the local llamafile (CPU or GPU)
├── test_app.py        # 243 end-to-end checks against a running app
├── .env               # API keys (git-ignored — copy from .env.example)
├── .env.example
├── .gitignore
├── config.json
├── pdfs/              # Comete 70TH · Galaxie 32TH · Galaxie 45TH · Images · XLS
├── data/              # index.db, page renders, figure crops, cache  (generated)
├── llamafile/         # local LLM runtime + weights
├── static/index.html  # single-page UI
├── start.bat
└── docs/
```

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/ask` | `{question, max_pages, max_images}` → answer, pages, parts, images |
| `GET /api/status` | index counts, systems, AI state, re-index progress |
| `POST /api/reindex` · `GET /api/reindex-status` | background rebuild + polling |
| `POST /api/find-by-image` | multipart upload → ranked visual matches |
| `GET /api/part/{ref}` | one reference plus the pages that mention it |
| `POST /api/export-images` | ZIP of every extracted figure |
| `POST /api/settings` | `{compute, restart_model}` — switch the model between CPU and GPU |
| `POST /api/model/{start\|stop\|restart}` | control the local model server |
| `POST /api/bundle` | ZIP of one answer: text, pages, drawings and part photos |
| `POST /api/clipboard-image` | put one catalogue image on the OS clipboard, ready to paste |

## Testing

```bash
python test_app.py
```

Runs 243 checks against a live app: index counts, dedupe, part lookup, image similarity,
media URLs, validation and error paths, model switching, secret hygiene (no key in
`config.json`, none leaking through the API), markdown and table rendering, sharing
controls, the ZIP bundle, snippet cleanliness, OCR and vector coverage, answer relevance,
highlight geometry, and grounding behaviour — including that **every suggested narrowing
option actually resolves to indexed content**.

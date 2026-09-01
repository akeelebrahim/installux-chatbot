# Installux ChatBot

I made this app to make it easier to search in Installux catalogues. Instead of flipping through PDFs, you can just type a question or a part number and get the right page, drawing and part info.

It works in English and Arabic, on PC and phone, and you can also search by uploading a photo.

## What it covers
- **COMETE 70TH** — 70mm door system
- **GALAXIE 32TH** — sliding system
- **GALAXIE 45TH** — Lift & Slide

All catalogues are in `pdfs/` — you can add more PDFs there and re-index.

## Features
- **Search the catalogues** — type like `5051`, `glazing bead for 70TH`, `punching tools rails` or `ما هو 560032؟` and get the exact pages where it appears, with highlighted matches on the page image.
- **Part lookup** — type a reference (e.g. `560032`) and see the part photos, kind and designation from the `PROFILES & ACCESSORIES LIST.xlsx` workbook.
- **Drawings & images** — every figure from the PDFs is extracted and shown with the answer. Click to zoom and drag to pan.
- **Search by image** — upload a photo or a crop of a catalogue page and find the closest drawings.
- **Voice search** — use the microphone to speak your question (Chrome/Edge).
- **Bilingual** — full English / Arabic interface, switch with `EN / عربي`.
- **Mobile friendly & PWA** — works on phone, add to home screen, and search box has mic and camera inside it.
- **Upload PDFs** — add new catalogues from Settings → Upload PDF, it will re-index automatically.
- **Recent & Favorites** — recent searches and favorite parts are saved in the browser, shown on the main screen on mobile.
- **Copy & Share** — copy answers, copy images to clipboard or share via WhatsApp / Email.

## How to run locally
```bash
pip install -r requirements.txt
python indexer.py        # builds the index from pdfs/
python app.py            # or python start_server.py
```
Open `http://127.0.0.1:8509`

You can also double-click `start.bat`.

## Adding catalogues
Put PDFs in a folder under `pdfs/` (folder name becomes the system name) and click **Re-index** or run `python indexer.py` again.

Uploaded PDFs from the app go to `pdfs/` too and trigger re-index.

## How it works (simple)
1. `indexer.py` reads every PDF page, saves the text, a page image, thumbnails and all figures.
2. `search.py` searches using SQLite FTS5 and ranking — it looks for exact references, words and system names.
3. `app.py` serves the API and the web UI in `static/index.html`.

## Project structure
```
Installux-ChatBot/
├── app.py              # web server
├── indexer.py          # builds the index from PDFs
├── search.py           # search and ranking
├── static/index.html   # web interface
├── pdfs/               # catalogues (Comete, Galaxie, Images)
├── data/               # generated index and images (created after indexing)
├── manifest.json
├── sw.js
├── requirements.txt
└── config.json
```

## Deploy
Push to GitHub and connect to Render:
- Build: `pip install --no-cache-dir --no-require-hashes -r requirements.txt && python indexer.py`
- Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`

The app runs on Render's Standard plan (needs ~2GB RAM for indexing).

---
Made for easier access to Installux technical documentation.

"""Recover text that the PDF text layer does not give us.

Two problems make plain extraction insufficient for these catalogues:

* some pages carry almost no text layer at all (the drawing *is* the page);
* several files embed subset fonts with broken character maps, so extraction
  returns mojibake — `d9100.pdf` loses about 40% of its text that way.

Both are fixed by reading the rendered page image. Two engines are supported:
a vision-capable LLM through the configured backend (best on technical drawings
— it reads dimension callouts, table cells and part references inside the
artwork), and EasyOCR locally when no such backend is configured.

Results are cached by page-image hash, so re-indexing never pays twice.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CACHE_PATH = BASE_DIR / "data" / "ocr_cache.json"
BOX_CACHE_PATH = BASE_DIR / "data" / "ocr_boxes.json"

log = logging.getLogger("installux")
_lock = threading.Lock()
_reader = None
_reader_failed = False

PROMPT = (
    "Transcribe every piece of text visible on this technical catalogue page.\n"
    "Include: headings, body text, table cells, part reference numbers, dimension "
    "callouts and any labels written inside the drawings, including rotated ones.\n"
    "Preserve reading order and keep numbers exactly as printed. Use plain text, one "
    "item per line for tables. Do not describe the images, do not summarise, and do "
    "not add any commentary — output the text only."
)


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------
def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_json(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _load_cache() -> dict:
    return _load_json(CACHE_PATH)


def _save_cache(cache: dict) -> None:
    _save_json(CACHE_PATH, cache)


def _key(image: Path, engine: str) -> str:
    return f"{engine}:{hashlib.sha1(image.read_bytes()).hexdigest()}"


# --------------------------------------------------------------------------
# engines
# --------------------------------------------------------------------------
def vision_supported(cfg: dict) -> bool:
    """Vision transcription needs a hosted multimodal model."""
    if cfg.get("backend_kind") != "remote" or cfg.get("needs_api_key"):
        return False
    model = (cfg.get("model") or "").lower()
    return any(tag in model for tag in ("claude", "gpt-4", "gpt-5", "gemini", "vision", "llava"))


def _vision_text(image: Path, cfg: dict) -> str:
    import ai_client
    b64 = base64.b64encode(image.read_bytes()).decode("ascii")
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
        "temperature": 0,
        "max_tokens": 4000,
    }
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    data = ai_client._post_json(url, payload, cfg.get("api_key", ""), cfg.get("timeout", 180))
    choices = data.get("choices") or []
    return (choices[0].get("message", {}).get("content") or "").strip() if choices else ""


def _easyocr_reader():
    global _reader, _reader_failed
    if _reader is not None or _reader_failed:
        return _reader
    with _lock:
        if _reader is None and not _reader_failed:
            try:
                import easyocr
                import torch
                _reader = easyocr.Reader(["en", "fr"], gpu=torch.cuda.is_available(),
                                         verbose=False)
            except Exception as exc:
                log.warning("EasyOCR unavailable: %s", str(exc)[:160])
                _reader_failed = True
    return _reader


def _easyocr_text(image: Path) -> str:
    reader = _easyocr_reader()
    if reader is None:
        return ""
    try:
        return "\n".join(reader.readtext(str(image), detail=0, paragraph=True))
    except Exception as exc:
        log.warning("EasyOCR failed on %s: %s", image.name, str(exc)[:120])
        return ""


def pick_engine(cfg: dict, requested: str = "auto") -> str:
    """Resolve 'auto' to the best engine actually available. '' means none."""
    if requested == "off":
        return ""
    if requested in ("vision", "easyocr"):
        return requested
    if vision_supported(cfg):
        return "vision"
    try:
        import easyocr  # noqa: F401
        return "easyocr"
    except Exception:
        return ""


def transcribe(image: Path, cfg: dict, engine: str) -> str:
    """Text read off a rendered page image, cached by image hash."""
    if not engine or not image.exists():
        return ""
    cache = _load_cache()
    key = _key(image, engine)
    if key in cache:
        return cache[key]
    try:
        text = _vision_text(image, cfg) if engine == "vision" else _easyocr_text(image)
    except Exception as exc:
        log.warning("OCR failed on %s: %s", image.name, str(exc)[:160])
        return ""
    text = (text or "").strip()
    if text:
        cache[key] = text
        _save_cache(cache)
    return text


def word_boxes(image: Path) -> list[tuple[str, list[float]]]:
    """(text, [x, y, w, h]) for every chunk EasyOCR finds, as fractions 0-1.

    Only the local reader returns geometry — a vision model gives prose back — so
    highlight boxes on a page with a broken text layer always come from EasyOCR,
    whichever engine produced the searchable transcript. Cached by image hash.
    """
    if not image.exists():
        return []
    key = _key(image, "boxes")
    cache = _load_json(BOX_CACHE_PATH)
    if key in cache:
        return [(t, b) for t, b in cache[key]]

    reader = _easyocr_reader()
    if reader is None:
        return []
    try:
        from PIL import Image as PILImage
        with PILImage.open(image) as im:
            width, height = im.size
        found = reader.readtext(str(image), detail=1, paragraph=False)
    except Exception as exc:
        log.warning("EasyOCR boxes failed on %s: %s", image.name, str(exc)[:120])
        return []
    if not width or not height:
        return []

    out: list[tuple[str, list[float]]] = []
    for item in found:
        try:
            box, text = item[0], (item[1] or "").strip()
        except (IndexError, TypeError):
            continue
        if not text:
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        x0, x1 = max(0.0, min(xs)), min(float(width), max(xs))
        y0, y1 = max(0.0, min(ys)), min(float(height), max(ys))
        if x1 <= x0 or y1 <= y0:
            continue
        out.append((text, [round(x0 / width, 5), round(y0 / height, 5),
                           round((x1 - x0) / width, 5), round((y1 - y0) / height, 5)]))
    cache[key] = out
    _save_json(BOX_CACHE_PATH, cache)
    return out


def needs_ocr(raw_text: str, cleaned: str, min_chars: int = 250,
              max_loss: float = 0.15) -> bool:
    """True when the text layer is too thin or too damaged to trust."""
    raw, clean = raw_text.strip(), cleaned.strip()
    if len(clean) < min_chars:
        return True
    return (1 - len(clean) / max(len(raw), 1)) > max_loss

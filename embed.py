"""Dense vector embeddings for semantic recall over pages and parts.

Lexical search (FTS5 + the trade vocabulary) is precise but literal: it only
finds what the customer happened to type. Embeddings add the other half — "how
do I stop water getting in" reaching the drainage pages — and they work across
French and English without a synonym entry for every phrasing.

The model is loaded lazily and cached in the shared HuggingFace cache, not in
this project, so the repository stays free of model weights. If sentence-
transformers or the weights are unavailable the app degrades cleanly to
lexical-only search; nothing here is required for the app to run.
"""
from __future__ import annotations

import base64
import logging
import threading

import numpy as np

log = logging.getLogger("installux")

DEFAULT_MODEL = "BAAI/bge-m3"          # multilingual; these catalogues are FR + EN
FALLBACK_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_lock = threading.Lock()
_model = None
_model_name: str | None = None
_failed = False


def available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return True
    except Exception:
        return False


def get_model(name: str | None = None):
    """Lazy singleton. Returns None when embeddings are not usable."""
    global _model, _model_name, _failed
    name = name or DEFAULT_MODEL
    if _model is not None and _model_name == name:
        return _model
    if _failed:
        return None
    with _lock:
        if _model is not None and _model_name == name:
            return _model
        try:
            import torch
            from sentence_transformers import SentenceTransformer
            device = "cuda" if torch.cuda.is_available() else "cpu"
            for candidate in (name, FALLBACK_MODEL):
                try:
                    log.info("loading embedding model %s on %s…", candidate, device)
                    _model = SentenceTransformer(candidate, device=device)
                    _model_name = candidate
                    return _model
                except Exception as exc:
                    log.warning("could not load %s: %s", candidate, str(exc)[:160])
            _failed = True
        except Exception as exc:
            log.warning("embeddings unavailable: %s", str(exc)[:160])
            _failed = True
    return None


def model_name() -> str | None:
    return _model_name


def encode(texts: list[str], name: str | None = None, batch_size: int = 64,
           progress: bool = False) -> np.ndarray | None:
    """L2-normalised float32 matrix (len(texts) x dim), or None if unavailable."""
    if not texts:
        return None
    m = get_model(name)
    if m is None:
        return None
    try:
        return np.asarray(
            m.encode([t[:2000] for t in texts], batch_size=batch_size,
                     normalize_embeddings=True, show_progress_bar=progress),
            dtype=np.float32,
        )
    except Exception as exc:
        log.warning("encode failed: %s", str(exc)[:160])
        return None


# --------------------------------------------------------------------------
# storage (float16 base64, same convention as the image descriptors)
# --------------------------------------------------------------------------
def to_b64(vec: np.ndarray) -> str:
    return base64.b64encode(np.asarray(vec, dtype=np.float16).tobytes()).decode("ascii")


def from_b64(s: str | None, dim: int | None = None) -> np.ndarray | None:
    if not s:
        return None
    try:
        v = np.frombuffer(base64.b64decode(s), dtype=np.float16).astype(np.float32)
    except Exception:
        return None
    if dim is not None and v.size != dim:
        return None
    return v


def stack(rows: list[str | None]) -> tuple[np.ndarray, np.ndarray]:
    """Pack stored vectors into a matrix plus a mask of which rows had one."""
    vecs, mask, dim = [], [], None
    for s in rows:
        v = from_b64(s)
        if v is not None and (dim is None or v.size == dim):
            dim = v.size
            vecs.append(v)
            mask.append(True)
        else:
            mask.append(False)
    if not vecs:
        return np.zeros((0, 0), dtype=np.float32), np.zeros(len(rows), dtype=bool)
    return np.vstack(vecs), np.asarray(mask, dtype=bool)

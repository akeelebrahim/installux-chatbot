"""Find a catalogue image from a *part* of it.

The perceptual hashes in `imgutil` describe a whole picture, so a crop hashes to
something completely different and cannot be found. Partial retrieval needs
localized features, so this module implements the two-stage pipeline that is
standard for sub-image search:

1. **Recall — dense patch embeddings (DINOv2 ViT-S/14) + FAISS.**
   Every library image is letterboxed to 448px and encoded once, giving a 32x32
   grid of patch tokens. Those tokens are average-pooled over the whole image and
   over overlapping half- and quarter-size windows, so an image contributes many
   regional vectors as well as a global one. A crop then has a region in the
   index it can align with, which a flat global descriptor can never provide.
   Blank windows are dropped: a tile of empty paper is identical on every page in
   the catalogue and would otherwise match everything. Vectors are L2-normalised
   in a FAISS inner-product index (exact — at this corpus size an IVF/PQ
   approximation would cost accuracy for no useful speedup).

2. **Verification — SuperPoint keypoints + LightGlue matching.**
   Patch similarity is a weak ranker on technical drawings, which are all black
   line art on white and score 0.94+ against each other, so the shortlist is
   deliberately wide and geometry decides. SuperPoint detects keypoints,
   LightGlue matches them, and OpenCV's RANSAC keeps only the correspondences
   consistent with a single homography. A true crop scores 100+ inliers where an
   unrelated drawing scores under 10.

   Pairs are matched one at a time on purpose: batching several pairs through
   `post_process_keypoint_matching` returns them out of order, silently
   attributing one pair's matches to another.

Both models come from the shared HuggingFace/timm cache, not from this repo, and
the whole module is optional: without torch the app falls back to hash matching.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
INDEX_PATH = DATA_DIR / "vis_index.faiss"
META_PATH = DATA_DIR / "vis_meta.json"

log = logging.getLogger("installux")

# --- embedding geometry -----------------------------------------------------
DINO_MODEL = "vit_small_patch14_dinov2.lvd142m"
PATCH = 14
GRID = 32                      # 32 x 14 = 448 px input -> 32x32 patch tokens
IMAGE_SIZE = GRID * PATCH
WINDOW_SCALES = ((16, 8), (8, 4))   # (size, stride) in patch units: halves, quarters
BATCH = 16
BLANK_STD = 0.05               # grayscale std below which a window is empty paper

# --- verification -----------------------------------------------------------
LG_MODEL = "ETH-CVG/lightglue_superpoint"
LG_THRESHOLD = 0.20            # per-correspondence confidence
SHORTLIST = 32                 # candidates handed to LightGlue (~60 ms each)
LG_MAX_SIDE = 800              # downscale before SuperPoint; plenty for keypoints
MIN_INLIERS = 15               # RANSAC inliers that make a match trustworthy
RANSAC_PX = 6.0

_lock = threading.Lock()
_dino = None
_dino_cfg: dict = {}
_lg = None
_lg_proc = None
_failed = False


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------
def _device() -> str:
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def get_encoder():
    """DINOv2 patch encoder, or None when torch/timm are unavailable."""
    global _dino, _dino_cfg, _failed
    if _dino is not None or _failed:
        return _dino
    with _lock:
        if _dino is None and not _failed:
            try:
                import timm
                m = timm.create_model(DINO_MODEL, pretrained=True, num_classes=0,
                                      img_size=IMAGE_SIZE)
                m.eval().to(_device())
                cfg = timm.data.resolve_model_data_config(m)
                _dino_cfg = {"mean": np.array(cfg["mean"], dtype=np.float32),
                             "std": np.array(cfg["std"], dtype=np.float32),
                             "prefix": getattr(m, "num_prefix_tokens", 1)}
                _dino = m
                log.info("DINOv2 loaded on %s", _device())
            except Exception as exc:
                log.warning("visual encoder unavailable: %s", str(exc)[:200])
                _failed = True
    return _dino


def get_matcher():
    """LightGlue+SuperPoint pair matcher, or None."""
    global _lg, _lg_proc
    if _lg is not None:
        return _lg
    with _lock:
        if _lg is None:
            try:
                from transformers import AutoImageProcessor, AutoModel
                _lg_proc = AutoImageProcessor.from_pretrained(LG_MODEL)
                _lg = AutoModel.from_pretrained(LG_MODEL).eval().to(_device())
            except Exception as exc:
                log.warning("LightGlue unavailable: %s", str(exc)[:200])
                _lg = None
    return _lg


def available() -> bool:
    return get_encoder() is not None


# --------------------------------------------------------------------------
# windows
# --------------------------------------------------------------------------
def _windows() -> list[tuple[int, int, int, int]]:
    """The whole grid plus overlapping windows at each scale, in patch units."""
    out = [(0, 0, GRID, GRID)]
    for win, stride in WINDOW_SCALES:
        for r in range(0, GRID - win + 1, stride):
            for c in range(0, GRID - win + 1, stride):
                out.append((r, c, r + win, c + win))
    return out


WINDOWS = _windows()
TILES_PER_IMAGE = len(WINDOWS)
# A query is described by its whole self and its halves. Quarter windows of the
# query would be tiny fragments that match far too much.
N_QUERY_WINDOWS = 1 + sum(1 for w in WINDOWS[1:]
                          if (w[2] - w[0]) == WINDOW_SCALES[0][0])


def _load_rgb(path) -> "np.ndarray | None":
    from PIL import Image
    try:
        with Image.open(str(path)) as im:
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
                im = Image.alpha_composite(bg, im)
            im = im.convert("RGB")
            # pad to square on the catalogue's white ground rather than squashing:
            # stretching makes a 691x321 photo and its crop disagree on shape
            side = max(im.width, im.height)
            canvas = Image.new("RGB", (side, side), (255, 255, 255))
            canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
            canvas = canvas.resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BICUBIC)
            return np.asarray(canvas, dtype=np.float32) / 255.0
    except Exception:
        return None


def _informative(rgb: np.ndarray, limit: int | None = None) -> np.ndarray:
    """Boolean mask over WINDOWS: does this window contain anything at all?"""
    gray = rgb.mean(axis=2)
    cell = IMAGE_SIZE // GRID
    wins = WINDOWS[:limit] if limit else WINDOWS
    keep = np.zeros(len(wins), dtype=bool)
    for i, (r0, c0, r1, c1) in enumerate(wins):
        keep[i] = gray[r0 * cell:r1 * cell, c0 * cell:c1 * cell].std() >= BLANK_STD
    keep[0] = True                      # always keep the whole-image vector
    return keep


def embed(paths: list[Path], limit: int | None = None
          ) -> list[tuple[np.ndarray, np.ndarray]]:
    """Per image: (vectors for kept windows, indices of those windows)."""
    model = get_encoder()
    if model is None:
        return []
    import torch

    wins = WINDOWS[:limit] if limit else WINDOWS
    loaded = [(i, _load_rgb(p)) for i, p in enumerate(paths)]
    loaded = [(i, a) for i, a in loaded if a is not None]
    results: list[tuple[np.ndarray, np.ndarray] | None] = [None] * len(paths)
    if not loaded:
        return []

    mean, std = _dino_cfg["mean"], _dino_cfg["std"]
    prefix, dev = _dino_cfg["prefix"], _device()

    with torch.no_grad():
        for start in range(0, len(loaded), BATCH):
            chunk = loaded[start:start + BATCH]
            arr = np.stack([a for _, a in chunk])
            x = torch.from_numpy(((arr - mean) / std).transpose(0, 3, 1, 2)).to(dev)
            tokens = model.forward_features(x)[:, prefix:, :]
            b, _, d = tokens.shape
            grid = tokens.reshape(b, GRID, GRID, d)
            pooled = torch.stack(
                [grid[:, r0:r1, c0:c1, :].mean(dim=(1, 2)) for r0, c0, r1, c1 in wins],
                dim=1)
            pooled = torch.nn.functional.normalize(pooled, dim=-1).float().cpu().numpy()
            for j, (idx, a) in enumerate(chunk):
                keep = _informative(a, limit)
                results[idx] = (pooled[j][keep], np.flatnonzero(keep))
    return [r for r in results if r is not None]


# --------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------
def build_index(items: list[dict], progress=print) -> int:
    """Embed every library image and write the FAISS index."""
    if not items or not available():
        return 0
    import faiss

    index = faiss.IndexFlatIP(get_encoder().num_features)
    meta: list[dict] = []
    done = 0
    for start in range(0, len(items), BATCH * 4):
        chunk = items[start:start + BATCH * 4]
        per_image = embed([Path(it["path"]) for it in chunk])
        for it, (vecs, _) in zip(chunk, per_image):
            if len(vecs) == 0:
                continue
            index.add(vecs)
            meta.extend([{k: v for k, v in it.items() if k != "path"}] * len(vecs))
        done += len(chunk)
        if progress and done % (BATCH * 20) < BATCH * 4:
            progress(f"  embedded {done}/{len(items)} images…")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))
    META_PATH.write_text(json.dumps(meta), encoding="utf-8")
    if progress:
        progress(f"  visual index: {done} images, {index.ntotal} informative regions")
    return done


_index_cache: dict = {}


def _load_index():
    """(faiss index, meta) cached by file mtime; (None, None) if not built."""
    if not INDEX_PATH.exists() or not META_PATH.exists():
        return None, None
    stamp = INDEX_PATH.stat().st_mtime_ns
    if _index_cache.get("stamp") == stamp:
        return _index_cache["index"], _index_cache["meta"]
    try:
        import faiss
        index = faiss.read_index(str(INDEX_PATH))
        meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("visual index unreadable: %s", str(exc)[:160])
        return None, None
    _index_cache.update(stamp=stamp, index=index, meta=meta)
    return index, meta


def index_exists() -> bool:
    return INDEX_PATH.exists() and META_PATH.exists()


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------
def _prep(path: Path | None):
    """Load and downscale one image for keypoint matching."""
    if path is None or not Path(path).exists():
        return None
    from PIL import Image
    try:
        with Image.open(str(path)) as im:
            out = im.convert("RGB")
            out.thumbnail((LG_MAX_SIDE, LG_MAX_SIDE))
            return out
    except Exception:
        return None


def _ransac_inliers(kp0: np.ndarray, kp1: np.ndarray) -> int:
    """Correspondences consistent with one homography. Texture coincidences are
    plentiful between two technical drawings; geometric ones are not."""
    if len(kp0) < 4:
        return len(kp0)
    try:
        import cv2
        _, mask = cv2.findHomography(kp0.reshape(-1, 1, 2), kp1.reshape(-1, 1, 2),
                                     cv2.USAC_MAGSAC, RANSAC_PX, maxIters=5000)
        return int(mask.sum()) if mask is not None else 0
    except Exception:
        return len(kp0)          # no OpenCV: raw correspondence count still ranks


def verify(query_path: Path, candidates: list[Path | None]) -> list[int]:
    """Inlier count per candidate (-1 when the pair could not be processed)."""
    model = get_matcher()
    q = _prep(query_path)
    if model is None or q is None:
        return [-1] * len(candidates)
    import torch

    scores = []
    for path in candidates:
        c = _prep(path)
        if c is None:
            scores.append(-1)
            continue
        try:
            inputs = _lg_proc([[q, c]], return_tensors="pt").to(_device())
            with torch.no_grad():
                out = model(**inputs)
            sizes = torch.tensor([[[q.height, q.width], [c.height, c.width]]],
                                 device=_device())
            pair = _lg_proc.post_process_keypoint_matching(
                out, sizes, threshold=LG_THRESHOLD)[0]
            scores.append(_ransac_inliers(pair["keypoints0"].cpu().numpy(),
                                          pair["keypoints1"].cpu().numpy()))
        except Exception as exc:
            log.debug("LightGlue pair failed: %s", str(exc)[:140])
            scores.append(-1)
    return scores


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------
def find(query_path: Path, max_results: int = 8,
         geometric_check: bool = True) -> list[dict] | None:
    """Library images containing (or contained in) the query. None if unavailable.

    Each result carries `score` (0-1 patch similarity), `inliers` (geometric
    evidence, -1 when verification was skipped) and `match` (trustworthy).
    """
    index, meta = _load_index()
    if index is None or not available():
        return None
    q = embed([query_path], limit=N_QUERY_WINDOWS)
    if not q:
        return None
    qvecs = q[0][0]

    # an image scores by its single best region match: that is exactly what
    # "the crop is somewhere in there" means
    k = min(index.ntotal, 400)
    sims, ids = index.search(qvecs, k)
    best: dict[str, dict] = {}
    for row_s, row_i in zip(sims, ids):
        for s, i in zip(row_s, row_i):
            if i < 0:
                continue
            m = meta[i]
            cur = best.get(m["key"])
            if cur is None or s > cur["score"]:
                best[m["key"]] = {**m, "score": float(s)}
    ranked = sorted(best.values(), key=lambda d: -d["score"])

    if not geometric_check or get_matcher() is None:
        out = ranked[:max_results]
        for r in out:
            r["inliers"] = -1
            r["match"] = r["score"] >= 0.55
        return out

    shortlist = ranked[:SHORTLIST]
    for r, n in zip(shortlist, verify(query_path, [_resolve(r) for r in shortlist])):
        r["inliers"] = n
    # geometry decides, patch similarity only breaks ties
    shortlist.sort(key=lambda d: (-max(d["inliers"], 0), -d["score"]))
    for r in shortlist:
        r["match"] = r["inliers"] >= MIN_INLIERS
    return shortlist[:max_results]


def _resolve(item: dict) -> Path | None:
    """Where a library item's file lives on disk."""
    rel = item.get("file")
    if not rel:
        return None
    root = DATA_DIR if item.get("kind") == "catalogue" else BASE_DIR / "pdfs" / "Images"
    return root / rel

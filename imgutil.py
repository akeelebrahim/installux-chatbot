"""Model-free image descriptors used to find catalogue/part images by example.

Three complementary descriptors are computed per image and stored in the index:

* ``phash``  - 64-bit DCT perceptual hash. Robust to scale, JPEG noise and
  brightness; the coarse "is this the same picture" signal.
* ``dhash``  - 256-bit horizontal-gradient hash. Captures fine structure, which
  is what distinguishes one extruded aluminium profile from another.
* ``edge``   - 512-float gradient-orientation histogram over an 8x8 grid
  (HOG-like). This is the descriptor that actually works on the line drawings
  and cross-sections in these catalogues, where flat-pixel hashes all collapse
  to "mostly white".

Every image is trimmed to its content bounding box before hashing, so a tightly
cropped photo still matches the same part shot with wide margins.

Only numpy + Pillow are required - no ML model is downloaded or shipped.
"""
from __future__ import annotations

import base64

import numpy as np
from PIL import Image, ImageOps

# Descriptor geometry
PHASH_SIZE = 8           # 8x8 low-frequency DCT block -> 64 bits
PHASH_DCT = 32           # DCT is computed on a 32x32 image
DHASH_SIZE = 16          # 16x17 -> 16x16 differences -> 256 bits
EDGE_GRID = 8            # 8x8 spatial cells
EDGE_BINS = 8            # 8 unsigned-gradient orientation bins
EDGE_DIM = EDGE_GRID * EDGE_GRID * EDGE_BINS  # 512

PHASH_BITS = PHASH_SIZE * PHASH_SIZE     # 64
DHASH_BITS = DHASH_SIZE * DHASH_SIZE     # 256

Image.MAX_IMAGE_PIXELS = 200_000_000


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def _dct_matrix(n: int) -> np.ndarray:
    """Orthonormal DCT-II basis, so we don't need scipy."""
    k = np.arange(n).reshape(-1, 1)
    x = np.arange(n).reshape(1, -1)
    m = np.cos(np.pi * (2 * x + 1) * k / (2 * n))
    m[0] *= np.sqrt(1 / n)
    m[1:] *= np.sqrt(2 / n)
    return m


_DCT = _dct_matrix(PHASH_DCT)


def _trim(gray: np.ndarray, tol: int = 12) -> np.ndarray:
    """Crop uniform borders (the white paper around a drawing or part photo)."""
    if gray.size == 0:
        return gray
    bg = np.median(np.concatenate([gray[0], gray[-1], gray[:, 0], gray[:, -1]]))
    mask = np.abs(gray.astype(np.int16) - bg) > tol
    if not mask.any():
        return gray
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    r0, r1 = rows[0], rows[-1] + 1
    c0, c1 = cols[0], cols[-1] + 1
    # ignore a degenerate crop (a stray speck of dust in a corner)
    if (r1 - r0) < 8 or (c1 - c0) < 8:
        return gray
    return gray[r0:r1, c0:c1]


def load_gray(path) -> np.ndarray | None:
    """Open any image as an autocontrasted, content-cropped grayscale array."""
    try:
        with Image.open(str(path)) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                # flatten transparency onto white, matching the catalogue paper
                im = im.convert("RGBA")
                bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
                im = Image.alpha_composite(bg, im)
            im = im.convert("L")
            im.load()
            gray = np.asarray(im, dtype=np.uint8)
    except Exception:
        return None
    if gray.ndim != 2 or gray.size == 0:
        return None
    gray = _trim(gray)
    if gray.size == 0:
        return None
    lo, hi = float(gray.min()), float(gray.max())
    if hi - lo > 1:  # stretch contrast so exposure differences stop mattering
        gray = ((gray.astype(np.float32) - lo) * (255.0 / (hi - lo))).astype(np.uint8)
    return gray


def _resize(gray: np.ndarray, w: int, h: int) -> np.ndarray:
    return np.asarray(
        Image.fromarray(gray, mode="L").resize((w, h), Image.Resampling.LANCZOS),
        dtype=np.uint8,
    )


# --------------------------------------------------------------------------
# descriptors
# --------------------------------------------------------------------------
def _bits_to_int(bits: np.ndarray) -> int:
    out = 0
    for b in bits.astype(np.uint8).flatten():
        out = (out << 1) | int(b)
    return out


def phash_from_gray(gray: np.ndarray) -> int:
    small = _resize(gray, PHASH_DCT, PHASH_DCT).astype(np.float32)
    coeffs = _DCT @ small @ _DCT.T
    block = coeffs[:PHASH_SIZE, :PHASH_SIZE].copy()
    block[0, 0] = 0.0  # drop DC: it only encodes average brightness
    return _bits_to_int(block > np.median(block))


def dhash_from_gray(gray: np.ndarray) -> int:
    small = _resize(gray, DHASH_SIZE + 1, DHASH_SIZE).astype(np.int16)
    return _bits_to_int(small[:, 1:] > small[:, :-1])


def edge_from_gray(gray: np.ndarray) -> np.ndarray:
    """Gradient-orientation histogram grid, L2-normalised (float32, EDGE_DIM)."""
    side = EDGE_GRID * 16  # 128px working canvas -> 16x16 pixels per cell
    g = _resize(gray, side, side).astype(np.float32)
    gy, gx = np.gradient(g)
    mag = np.hypot(gx, gy)
    # unsigned orientation: a line is the same line whichever way it is drawn
    ang = np.arctan2(gy, gx) % np.pi
    bins = np.minimum((ang / np.pi * EDGE_BINS).astype(np.int32), EDGE_BINS - 1)

    cell = side // EDGE_GRID
    hist = np.zeros((EDGE_GRID, EDGE_GRID, EDGE_BINS), dtype=np.float32)
    for r in range(EDGE_GRID):
        for c in range(EDGE_GRID):
            m = mag[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell].ravel()
            b = bins[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell].ravel()
            hist[r, c] = np.bincount(b, weights=m, minlength=EDGE_BINS)
    vec = hist.ravel()
    n = np.linalg.norm(vec)
    return (vec / n).astype(np.float32) if n > 0 else vec


def describe(path) -> tuple[int, int, np.ndarray] | None:
    """Full descriptor set for one image, or None if it cannot be read."""
    gray = load_gray(path)
    if gray is None:
        return None
    return phash_from_gray(gray), dhash_from_gray(gray), edge_from_gray(gray)


# --------------------------------------------------------------------------
# serialisation (DB storage)
# --------------------------------------------------------------------------
def edge_to_b64(vec: np.ndarray) -> str:
    return base64.b64encode(vec.astype(np.float16).tobytes()).decode("ascii")


def edge_from_b64(s: str | None) -> np.ndarray | None:
    if not s:
        return None
    try:
        v = np.frombuffer(base64.b64decode(s), dtype=np.float16).astype(np.float32)
    except Exception:
        return None
    return v if v.size == EDGE_DIM else None


def hash_to_hex(v: int | None) -> str | None:
    return None if v is None else format(v, "x")


def hex_to_hash(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(s, 16)
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------
# comparison
# --------------------------------------------------------------------------
def hamming(a: int | None, b: int | None) -> int:
    """Bit distance between two hashes (999 when either is missing)."""
    if a is None or b is None:
        return 999
    return int(a ^ b).bit_count()


def similarity_bulk(
    q_phash: int, q_dhash: int, q_edge: np.ndarray,
    phashes: np.ndarray, dhashes: list[int | None], edges: np.ndarray,
) -> np.ndarray:
    """Blend the three descriptors into a 0..1 similarity per candidate.

    Weights favour the edge histogram because catalogue art is line work, where
    the bit hashes are far less discriminative than gradient structure.
    """
    n = len(dhashes)
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    p_sim = 1.0 - (np.array(
        [hamming(q_phash, int(p)) if p >= 0 else PHASH_BITS for p in phashes],
        dtype=np.float32,
    ) / PHASH_BITS)
    d_sim = 1.0 - (np.array(
        [hamming(q_dhash, d) if d is not None else DHASH_BITS for d in dhashes],
        dtype=np.float32,
    ) / DHASH_BITS)
    e_sim = np.clip(edges @ q_edge, 0.0, 1.0) if edges.size else np.zeros(n, dtype=np.float32)
    return (0.20 * p_sim + 0.25 * d_sim + 0.55 * e_sim).astype(np.float32)

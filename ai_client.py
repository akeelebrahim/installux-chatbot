"""OpenAI-compatible LLM client (local llamafile or any remote provider),
plus the on-disk answer cache and the prompts used for answers and summaries."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
ENV_PATH = BASE_DIR / ".env"
CACHE_PATH = BASE_DIR / "data" / "cache.json"

DEFAULT_BACKENDS = {
    "openrouter-haiku": {
        "label": "Claude Haiku 4.5 · OpenRouter",
        "kind": "remote",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "anthropic/claude-haiku-4.5",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    "openrouter": {
        "label": "Claude Sonnet 5 · OpenRouter (more capable)",
        "kind": "remote",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "anthropic/claude-sonnet-5",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    "llamafile": {
        "label": "Qwen 2.5 3B · local",
        "kind": "local",
        "base_url": "http://127.0.0.1:8080/v1",
        "model": "qwen2.5-3b-instruct",
        "llamafile_exe": "llamafile/llamafile.exe",
        "model_path": "llamafile/models/qwen2.5-3b-instruct-q5_k_m.gguf",
    },
}

DEFAULT_CONFIG = {
    "backend": "openrouter-haiku",
    "backends": DEFAULT_BACKENDS,
    "default_pages": 3,
    "default_images": 3,
    "compute": "gpu",          # "gpu" or "cpu" — for the local model only
    "gpu_layers": 999,         # layers offloaded when compute == "gpu"
    "index_workers": 0,        # 0 = auto (one per core, capped)
    "context_pages": 6,
    "max_context_chars": 12000,
    "temperature": 0.2,
    "timeout": 180,
    "port": 8010,
    "open_browser": True,
    "summarize": False,
    "max_summary_words": 70,
    "cache_size": 200,
}

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def load_dotenv(path: Path = ENV_PATH) -> None:
    """Read KEY=VALUE pairs from .env into the environment.

    Kept dependency-free on purpose, and existing environment variables always
    win so a real deployment can override the file.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENV_LINE.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        os.environ.setdefault(key, value)


load_dotenv()

SYSTEM_PROMPT = (
    "You are the Installux ChatBot, a technical customer-support assistant for Installux "
    "aluminium joinery systems: COMETE 70TH (70 mm thermally broken door), "
    "GALAXIE 32TH (sliding frame system) and GALAXIE 45TH (Lift & Slide door system).\n"
    "\n"
    "Rules:\n"
    "- Use ONLY the document excerpts supplied below as evidence. Never invent a part "
    "number, dimension or tolerance.\n"
    "- Quote exact values, references and dimensions as written in the source.\n"
    "- When a fact comes from a catalogue page, cite it as [COMETE 70TH p.12]. Facts that come "
    "from the reference data need no citation — never invent a page number for them.\n"
    "- Detect the customer's language: if the question contains Arabic script (\\u0600-\\u06FF), "
    "answer entirely in Arabic (translate French terms to Arabic); otherwise answer in English "
    "(translate French terms to English). Keep part numbers, dimensions and codes unchanged.\n"
    "- When the UI is in Arabic mode the customer will write in Arabic — respect that and "
    "stay in Arabic. When in English, stay in English.\n"
    "- Be concise and well structured: short lines, bullet lists, bold for part references.\n"
    "- If the excerpts do not contain the answer, say so plainly in English and name what you would "
    "need (a system name, a part reference, or which drawing they are looking at)."
)


def _raw_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def backend_conf(cfg: dict, name: str | None = None) -> dict:
    """Settings for one backend (defaults to the active one)."""
    backends = cfg.get("backends") or DEFAULT_BACKENDS
    name = name or cfg.get("backend") or "openrouter-haiku"
    return backends.get(name) or next(iter(backends.values()), {})


def api_key_for(conf: dict) -> str:
    """Resolve a backend's key from the environment — never from config.json."""
    env = conf.get("api_key_env")
    return os.environ.get(env, "").strip() if env else ""


def load_config() -> dict:
    """Effective config with the active backend flattened into base_url/model/api_key.

    Every call site can keep reading cfg["base_url"] / cfg["model"] / cfg["api_key"]
    regardless of which backend is selected.
    """
    cfg = {**DEFAULT_CONFIG, **_raw_config()}
    conf = backend_conf(cfg)
    cfg["base_url"] = conf.get("base_url", "")
    cfg["model"] = conf.get("model", "")
    cfg["api_key"] = api_key_for(conf)
    cfg["backend_kind"] = conf.get("kind", "remote")
    cfg["backend_label"] = conf.get("label", cfg.get("backend", ""))
    cfg["needs_api_key"] = bool(conf.get("api_key_env")) and not cfg["api_key"]
    # the local runtime paths stay reachable even while a remote backend is active
    local = backend_conf(cfg, "llamafile")
    cfg["llamafile_exe"] = local.get("llamafile_exe", "")
    cfg["model_path"] = local.get("model_path", "")
    cfg["local_base_url"] = local.get("base_url", "http://127.0.0.1:8080/v1")
    return cfg


def backend_options(cfg: dict | None = None) -> list[dict]:
    """What the dashboard offers in its model picker."""
    cfg = cfg or load_config()
    out = []
    for name, conf in (cfg.get("backends") or DEFAULT_BACKENDS).items():
        out.append({
            "name": name,
            "label": conf.get("label", name),
            "kind": conf.get("kind", "remote"),
            "model": conf.get("model", ""),
            "ready": bool(api_key_for(conf)) if conf.get("api_key_env")
                     else (BASE_DIR / conf.get("model_path", "")).exists(),
        })
    return out


def save_config(patch: dict) -> dict:
    """Merge `patch` into config.json on disk and return the new effective config.

    Secrets are never written here — API keys live only in .env / the environment.
    """
    current = _raw_config()
    current.update({k: v for k, v in patch.items() if k not in ("api_key", "backends")})
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    return load_config()


def effective_gpu_layers(cfg: dict) -> int:
    """How many layers to offload, honouring the dashboard's CPU/GPU choice."""
    if str(cfg.get("compute", "gpu")).lower() == "cpu":
        return 0
    try:
        return max(0, int(cfg.get("gpu_layers", 999)))
    except (TypeError, ValueError):
        return 999


def _headers(api_key: str) -> dict:
    h = {"Content-Type": "application/json",
         "X-Title": "Installux ChatBot",
         "HTTP-Referer": "http://127.0.0.1/installux-chatbot"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def _post_json(url: str, payload: dict, api_key: str, timeout: int) -> dict:
    headers = _headers(api_key)
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------
# availability (cached: this is polled on every request and every status tick)
# --------------------------------------------------------------------------
_online_lock = threading.Lock()
# keyed by endpoint URL: the status poll probes both the active backend and the
# local llamafile, and a single-slot cache would be invalidated on every call
_online_cache: dict[str, tuple[float, tuple[bool, list[str]]]] = {}
_ONLINE_TTL = 5.0     # seconds to trust a positive result
_OFFLINE_TTL = 15.0   # ...and a negative one, so the UI never blocks on retries
_REMOTE_TTL = 60.0    # remote providers are reachable or not; no need to re-ask often


def check_online(cfg: dict | None = None, force: bool = False) -> tuple[bool, list[str]]:
    cfg = cfg or load_config()
    if cfg.get("needs_api_key"):
        return False, []          # a remote backend with no key is offline by definition
    url = cfg["base_url"].rstrip("/") + "/models"
    now = time.monotonic()
    with _online_lock:
        hit = _online_cache.get(url)
        if not force and hit:
            at, value = hit
            ttl = _ONLINE_TTL if value[0] else _OFFLINE_TTL
            if cfg.get("backend_kind") == "remote":
                ttl = _REMOTE_TTL   # don't hammer a paid API from the status poll
            if now - at < ttl:
                return value
    try:
        req = urllib.request.Request(url, headers=_headers(cfg.get("api_key", "")))
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        value = (True, [m.get("id", "") for m in data.get("data", [])])
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        value = (False, [])
    with _online_lock:
        _online_cache[url] = (now, value)
    return value


# --------------------------------------------------------------------------
# answer cache
# --------------------------------------------------------------------------
_cache_lock = threading.Lock()


def _cache_load() -> dict:
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _cache_key(question: str, signature: str = "") -> str:
    return hashlib.sha256(f"{question.strip().lower()}|{signature}".encode("utf-8")).hexdigest()


def cache_get(question: str, signature: str = "") -> str | None:
    if not load_config().get("cache_size", 0):
        return None
    with _cache_lock:
        return _cache_load().get(_cache_key(question, signature))


def cache_store(question: str, answer: str, signature: str = "") -> None:
    max_size = load_config().get("cache_size", 200)
    if not max_size:
        return
    with _cache_lock:
        cache = _cache_load()
        cache[_cache_key(question, signature)] = answer
        while len(cache) > max_size:
            cache.pop(next(iter(cache)))
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CACHE_PATH)


# --------------------------------------------------------------------------
# generation
# --------------------------------------------------------------------------
def _chat(messages: list[dict], cfg: dict, max_tokens: int, temperature: float) -> str:
    payload = {
        "model": cfg["model"], "messages": messages,
        "temperature": temperature, "max_tokens": max_tokens, "stream": False,
    }
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    data = _post_json(url, payload, cfg.get("api_key", ""), cfg.get("timeout", 180))
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"LLM returned no choices: {str(data)[:200]}")
    return (choices[0].get("message", {}).get("content") or "").strip()


def generate_answer(question: str, context: str, cfg: dict | None = None,
                    signature: str = "") -> tuple[str, bool]:
    """Return (answer, from_cache)."""
    cfg = cfg or load_config()
    # the model is part of the key: switching backends must not serve an answer
    # written by the previous (weaker) model
    signature = f"{cfg['model']}|{signature}"
    cached = cache_get(question, signature)
    if cached:
        return cached, True
    answer = _chat(
        [{"role": "system", "content": SYSTEM_PROMPT},
         {"role": "user",
          "content": f"DOCUMENT EXCERPTS:\n\n{context}\n\nCUSTOMER QUESTION: {question}"}],
        cfg, max_tokens=1600, temperature=cfg.get("temperature", 0.2),
    )
    if not answer:
        raise RuntimeError("LLM returned an empty answer")
    try:
        cache_store(question, answer, signature)
    except Exception:
        pass
    return answer, False


def generate_summary(text: str, cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    if not text.strip():
        return ""
    prompt = (
        "Summarise this catalogue page in English in 1-3 sentences, translating any French to English. "
        f"Focus on product and part names, references, dimensions and technical features. Max {cfg.get('max_summary_words', 70)} "
        "words.\n\nTEXT:\n" + text[:6000]
    )
    return _chat([{"role": "user", "content": prompt}], cfg,
                 max_tokens=160, temperature=0.2)


def suggest_questions(question: str, snippets: list[str], cfg: dict | None = None,
                      facets: dict | None = None) -> list[str]:
    """Narrowing options for a broad question, grounded in what is actually indexed.

    The model is given the systems, document types and headings found in the
    matching pages and told to build options only from those, so a customer never
    gets offered a product line or spec the catalogues do not cover.
    """
    cfg = cfg or load_config()
    facets = facets or {}
    parts = [f'A customer asked a broad question about the Installux catalogues:\n\n"{question}"']
    if facets.get("systems"):
        parts.append("Product systems available: " + ", ".join(facets["systems"]))
    if facets.get("doc_kinds"):
        parts.append("Document types available: " + ", ".join(facets["doc_kinds"]))
    if facets.get("components"):
        parts.append("Component families in the parts workbook (the most useful way to "
                     "narrow a component question):\n"
                     + "\n".join(f"- {c}" for c in facets["components"][:12]))
    if facets.get("topics"):
        parts.append("Section headings found in the matching pages:\n"
                     + "\n".join(f"- {t}" for t in facets["topics"][:12]))
    if snippets:
        parts.append("Excerpts from those pages:\n"
                     + "\n".join(f"- {s[:240]}" for s in snippets[:6]))
    parts.append(
        "Write 4 to 6 options the customer can click to narrow the search — for example "
        "specific product types, configurations, performance figures or fabrication "
        "details.\n"
        "Rules:\n"
        "- Build them ONLY from the systems, component families, headings and excerpts "
        "above. Never invent a product line, standard or specification that is not shown.\n"
        "- When component families are listed, at least half of the options must come from "
        "them — they are concrete catalogue categories, whereas headings are often "
        "marketing copy.\n"
        "- Each option must work as a search query on its own: name the thing, and the "
        "system when it matters. 3 to 9 words.\n"
        "- Make them genuinely different from each other.\n"
        "- Always write in English (translate French terms to English).\n"
        "- Output ONLY the list, one option per line, no numbering and no preamble."
    )
    text = _chat([{"role": "user", "content": "\n\n".join(parts)}], cfg,
                 max_tokens=300, temperature=0.3)
    out = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*•·").strip()
        if line[:1].isdigit() and line[1:2] in ".)":
            line = line[2:].strip()
        line = line.strip('"').strip()
        if 4 < len(line) <= 90 and not line.endswith(":"):
            out.append(line)
    return out[:6]

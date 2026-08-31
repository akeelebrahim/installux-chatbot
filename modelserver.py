"""Start, stop and inspect the local llamafile server.

The dashboard lets the user pick CPU or GPU inference, so the app has to be able
to relaunch the model process with different flags — and to recognise a server it
did not start itself (a leftover from another folder, say) so the UI can explain
why the switch has not taken effect.
"""
from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import ai_client

BASE_DIR = Path(__file__).resolve().parent
log = logging.getLogger("installux")

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_launched_with: str | None = None      # "gpu" / "cpu" for the process we started


def model_port(cfg: dict) -> int:
    """Port of the *local* llamafile, regardless of which backend is selected."""
    try:
        return urlparse(cfg.get("local_base_url") or "").port or 8080
    except Exception:
        return 8080


# --------------------------------------------------------------------------
# process discovery (Windows-first, degrades quietly elsewhere)
# --------------------------------------------------------------------------
def _listener_on(port: int) -> tuple[int, str] | None:
    """(pid, process name) of whatever is listening on `port`, if discoverable."""
    ps = (
        f"$c = Get-NetTCPConnection -LocalPort {port} -State Listen "
        f"-ErrorAction SilentlyContinue | Select-Object -First 1; "
        f"if ($c) {{ $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue; "
        f"if ($p) {{ \"$($p.Id) $($p.ProcessName)\" }} }}"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return None
    m = re.match(r"^(\d+)\s+(.+)$", out)
    return (int(m.group(1)), m.group(2)) if m else None


def _kill(pid: int) -> bool:
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                       capture_output=True, timeout=20)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# status / lifecycle
# --------------------------------------------------------------------------
def _local_cfg(cfg: dict) -> dict:
    """A view of `cfg` whose base_url points at the local llamafile."""
    return {**cfg, "base_url": cfg.get("local_base_url", "http://127.0.0.1:8080/v1"),
            "api_key": "", "needs_api_key": False, "backend_kind": "local"}


def status(cfg: dict | None = None) -> dict:
    cfg = cfg or ai_client.load_config()
    online, _ = ai_client.check_online(_local_cfg(cfg))
    managed = _proc is not None and _proc.poll() is None
    listener = None
    if online and not managed:
        listener = _listener_on(model_port(cfg))
    return {
        "online": online,
        "in_use": cfg.get("backend") == "llamafile",
        "managed": managed,
        "running_compute": _launched_with if managed else None,
        "external_pid": listener[0] if listener else None,
        "external_name": listener[1] if listener else None,
        "port": model_port(cfg),
        "can_start": (BASE_DIR / cfg.get("llamafile_exe", "")).exists()
                     and (BASE_DIR / cfg.get("model_path", "")).exists(),
    }


def stop(cfg: dict | None = None) -> str:
    """Stop the model server. Returns a human-readable outcome."""
    global _proc, _launched_with
    cfg = cfg or ai_client.load_config()
    with _lock:
        if _proc is not None and _proc.poll() is None:
            _proc.terminate()
            try:
                _proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                _proc.kill()
            _proc, _launched_with = None, None
            return "stopped the model server"
        _proc, _launched_with = None, None

    cfg = _local_cfg(cfg)
    port = model_port(cfg)
    found = _listener_on(port)
    if not found:
        return "no model server was running"
    pid, name = found
    # only ever stop a llamafile — never some unrelated service that owns the port
    if "llamafile" not in name.lower():
        return (f"port {port} is held by “{name}” (pid {pid}), which is not a llamafile — "
                f"leaving it alone")
    _kill(pid)
    for _ in range(15):
        if not ai_client.check_online(cfg, force=True)[0]:
            return f"stopped the external llamafile (pid {pid})"
        time.sleep(1)
    return f"asked pid {pid} to stop, but it is still answering on port {port}"


def start(cfg: dict | None = None, wait: int = 0) -> str:
    """Launch llamafile with the dashboard's compute choice."""
    global _proc, _launched_with
    cfg = cfg or ai_client.load_config()
    local = _local_cfg(cfg)
    if ai_client.check_online(local, force=True)[0]:
        return "a local model server is already listening"

    exe = BASE_DIR / cfg.get("llamafile_exe", "")
    model = BASE_DIR / cfg.get("model_path", "")
    if not exe.exists() or not model.exists():
        return "the local model files are not present — running in retrieval-only mode"

    layers = ai_client.effective_gpu_layers(cfg)
    mode = "cpu" if layers == 0 else "gpu"
    cmd = [str(exe), "-m", str(model), "--server", "--nobrowser",
           "--host", "127.0.0.1", "--port", str(model_port(cfg)), "-ngl", str(layers)]
    kwargs = {}
    if hasattr(subprocess, "CREATE_NEW_CONSOLE"):
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    with _lock:
        try:
            _proc = subprocess.Popen(cmd, cwd=str(BASE_DIR), stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, **kwargs)
            _launched_with = mode
        except Exception as exc:
            log.error("could not start llamafile: %s", exc)
            return f"could not start the model: {exc}"

    deadline = time.time() + max(0, wait)
    while time.time() < deadline:
        if ai_client.check_online(local, force=True)[0]:
            return f"local model server started on {mode.upper()}"
        if _proc.poll() is not None:
            return "the model process exited during start-up — check the llamafile console"
        time.sleep(2)
    return f"model server starting on {mode.upper()}…"


def restart(cfg: dict | None = None, wait: int = 120) -> str:
    cfg = cfg or ai_client.load_config()
    stopped = stop(cfg)
    started = start(cfg, wait=wait)
    return f"{stopped}; {started}"


def ensure_running(cfg: dict | None = None) -> None:
    """Background best-effort start used at app boot."""
    cfg = cfg or ai_client.load_config()
    if cfg.get("backend") != "llamafile":
        return                      # a remote backend is selected; nothing to launch
    if ai_client.check_online(_local_cfg(cfg))[0]:
        return
    threading.Thread(target=lambda: log.info(start(cfg, wait=180)), daemon=True).start()

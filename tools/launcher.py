"""Small checks used by install.bat and start.bat (kept in Python so the batch files stay simple).

  python tools/launcher.py up <url> <seconds>    exit 0 once the local URL answers (waits up to <seconds>)
  python tools/launcher.py has-model             exit 0 if the AI model packages, a CUDA GPU and the model files are available
  python tools/launcher.py find-model            say where the model files are looked for and whether they are there
  python tools/launcher.py prefetch              download the chat and embedding models once (install only)
  python tools/launcher.py selftest              one chat turn by rules (the full check is tools/selfcheck.py)
  python tools/launcher.py version               print the version
  python tools/launcher.py stop                  stop the tool (port 8010) and the local AI model (port 8000)
"""
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def up(url, seconds):
    if not url.startswith(("http://127.0.0.1", "http://localhost")):
        sys.exit("only local addresses are checked")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    end = time.time() + float(seconds)
    shown = False
    while True:
        try:
            with opener.open(url, timeout=3) as r:
                if r.status == 200:
                    return 0
        except Exception:
            pass
        if time.time() >= end:
            return 1
        if not shown and float(seconds) > 5:
            print(f"  waiting for {url} ...", flush=True)
            shown = True
        time.sleep(2)


CHAT_DEFAULT, EMBED_DEFAULT = "Qwen/Qwen3.5-9B", "BAAI/bge-base-en-v1.5"


def hf_cache():
    """The Hugging Face cache folder, worked out the same way the transformers library does (no package needed)."""
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"]) / "hub"
    base = Path(os.environ["XDG_CACHE_HOME"]) if os.environ.get("XDG_CACHE_HOME") else Path.home() / ".cache"
    return base / "huggingface" / "hub"


def model_files(name):
    """Where the model named `name` (a Hugging Face id or a local folder) is on disk, or None."""
    p = Path(name)
    if p.is_dir():
        return p if (p / "config.json").exists() or (p / "modules.json").exists() else None
    snaps = hf_cache() / ("models--" + name.replace("/", "--")) / "snapshots"
    found = [s for s in snaps.glob("*") if (s / "config.json").exists()] if snaps.is_dir() else []
    return found[0] if found else None


def find_model(quiet=False):
    ok = True
    if not quiet:
        print(f"  Python for the model: {sys.executable}")
        print(f"  Model files cache:    {hf_cache()}")
    for label, name in (("Chat model", os.environ.get("CHAT_MODEL", CHAT_DEFAULT)),
                        ("Embedding model", os.environ.get("EMBED_MODEL", EMBED_DEFAULT))):
        where = model_files(name)
        ok &= where is not None
        print(f"  {label} {name}: " + (f"found ({where})" if where else "NOT found"))
    if not ok:
        print("  Point at existing files with HF_HOME or CHAT_MODEL / EMBED_MODEL in local_settings.bat,")
        print("  or download them once with: install.bat model")
    return 0 if ok else 1


def _listening_pids(port):
    """PIDs listening on 127.0.0.1:<port> (Windows: netstat; elsewhere: lsof if present)."""
    import subprocess
    pids = set()
    try:
        if os.name == "nt":
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=15).stdout
            for line in out.splitlines():
                parts = line.split()
                # A listening row has foreign address 0.0.0.0:0 or [::]:0 (the state word depends on the Windows language)
                if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].endswith(f":{port}") and parts[2] in ("0.0.0.0:0", "[::]:0") \
                        and parts[-1].isdigit():
                    pids.add(int(parts[-1]))
        else:
            out = subprocess.run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True, timeout=15).stdout
            pids |= {int(x) for x in out.split() if x.isdigit()}
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return pids


def _is_python(pid):
    import subprocess
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=15).stdout.lower()
            return "python" in out
        return "python" in Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").lower()
    except (OSError, subprocess.SubprocessError):
        return False


def _kill(pid):
    import signal
    import subprocess
    if os.name == "nt":
        return subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True).returncode == 0
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def stop():
    """Stop the tool and the local AI model: by their PID files, then by whatever Python process listens on their port.
    Only Python processes are stopped, so another program that happens to use the port is never touched."""
    traces = ROOT / "traces"
    stopped = []
    for name, label, port in (("serve", "tool", 8010), ("qwen", "AI model", 8000)):
        pidfile = traces / f"{name}.pid"
        pids = set()
        try:
            pid_s, port_s = pidfile.read_text().split()[:2]
            pids.add(int(pid_s))
            port = int(port_s)
        except (OSError, ValueError):
            pass
        pids |= _listening_pids(port)
        for pid in sorted(pids):
            if pid != os.getpid() and _is_python(pid) and _kill(pid):
                stopped.append(f"{label} (PID {pid}, port {port})")
        pidfile.unlink(missing_ok=True)
    print("Stopped: " + ", ".join(stopped) if stopped else "Nothing was running.")
    return 0


def has_model():
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as e:
        print(f"  missing package: {e.name}")
        return 1
    import torch
    if not torch.cuda.is_available():
        print("  torch is installed but sees no CUDA GPU (the CPU-only build may be installed)")
        return 1
    print(f"  GPU: {torch.cuda.get_device_name(0)}")
    return find_model(quiet=True)


def prefetch():
    os.environ["LRT_ALLOW_DOWNLOAD"] = "1"          # the one time the model files may be downloaded
    import rag_demo as R
    print(f"  downloading/loading {R.CHAT_MODEL} and {R.EMBED_MODEL} (several GB the first time) ...", flush=True)
    R.load_models()
    print("  models are cached; from now on they load offline.")
    return 0


def selftest():
    """Short form kept for old notes; install.bat runs tools/selfcheck.py, the full non-AI self-check."""
    os.environ["LRT_STUB_LLM"] = "1"
    from assistant.chat import assist
    msg = "Measure warpage on 10 SYN-10001 housings through reflow, peak 260 C"
    print(f"Test message: {msg}")
    r = assist(msg, use_model=True)
    checks = [("test recognised (warpage during reflow)", r["tests"] == ["warpage_reflow"]),
              ("procedure passages cited", bool(r["citations"])),
              ("missing inputs asked for", bool(r["questions"])),
              ("draft proposed, nothing submitted", bool(r["changes"]) and r["state"] in ("incomplete", "ready for review")),
              ("quality check ran", "readiness" in r)]
    print("\nAssistant reply (rules, no AI):\n  " + r["reply"].replace("\n", "\n  "))
    print()
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    ok = all(c for _, c in checks)
    print(f"\nNON-AI SELF-CHECK {'PASSED' if ok else 'FAILED'}. "
          "It checks the files, procedure search, guardrails and quality check. The AI model is checked when start.bat runs.")
    return 0 if ok else 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "up" and len(sys.argv) == 4:
        sys.exit(up(sys.argv[2], sys.argv[3]))
    if cmd == "version":
        import lrt_version
        print(lrt_version.text())
        sys.exit(0)
    sys.exit({"stop": stop, "has-model": has_model, "find-model": find_model, "prefetch": prefetch, "selftest": selftest}.get(cmd, lambda: print(__doc__) or 2)())

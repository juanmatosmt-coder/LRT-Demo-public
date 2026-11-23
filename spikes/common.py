"""Shared settings for the spike tests (run in the AGENTS venv: .venv-agents)."""
import json
import _offline  # noqa: F401  (no outbound traffic; see lrt_offline.py)
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASE_URL = os.environ.get("LRT_BASE_URL", "http://127.0.0.1:8000/v1")
MODEL = "qwen-local"
STUB = os.environ.get("LRT_STUB_LLM") == "1"

REQUEST_S5 = ("Measure warpage through reflow on 10 housings, then thermally cycle the same housings for 200 cycles "
              "and measure warpage through reflow again so we can compare before and after.")


def model_python():
    """Python of the MODEL venv (.venv), which runs the Qwen server and the MCP server."""
    if os.environ.get("LRT_MODEL_PY"):
        return os.environ["LRT_MODEL_PY"]
    for p in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if p.exists():
            return str(p)
    return sys.executable


def mcp_connection():
    env = {k: v for k, v in os.environ.items()}
    return {"command": model_python(), "args": [str(HERE / "mcp_server.py")], "transport": "stdio", "env": env}


def result(name, passed, t0, **details):
    return {"name": name, "passed": bool(passed), "seconds": round(time.time() - t0, 1), "details": details}


def parse_tool_output(out):
    """langchain-mcp-adapters returns text or content blocks; return the decoded JSON value when possible."""
    if isinstance(out, tuple):
        out = out[0]
    if isinstance(out, list):
        texts = [b.get("text", "") if isinstance(b, dict) else getattr(b, "text", str(b)) for b in out]
        vals = []
        for t in texts:
            try:
                vals.append(json.loads(t))
            except (json.JSONDecodeError, TypeError):
                vals.append(t)
        return vals[0] if len(vals) == 1 else vals
    if isinstance(out, str):
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return out
    return out


def mcp_preflight():
    """Start the MCP server in --check mode with the MODEL venv's Python. Returns (ok, message).
    A stdio server that crashes shows only 'Connection closed' to the client; this surfaces the real error."""
    import subprocess
    try:
        p = subprocess.run([model_python(), str(HERE / "mcp_server.py"), "--check"], capture_output=True,
                           text=True, timeout=300, env=dict(os.environ))
    except Exception as e:
        return False, f"could not start {model_python()}: {e!r}"
    if p.returncode != 0:
        return False, f"mcp_server.py --check failed with {model_python()}:\n{(p.stderr or p.stdout)[-2500:]}"
    return True, p.stdout.strip()

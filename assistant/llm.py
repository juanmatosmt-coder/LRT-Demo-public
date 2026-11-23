"""Model access for the agents: the local Qwen server's OpenAI-compatible endpoint (127.0.0.1:8000), nothing else.

LRT_STUB_LLM=1 answers from spikes/stub_llm.py in-process (plumbing tests only; results prove nothing about Qwen).
Every call is logged to the run trace with its prompt size, reply size and seconds."""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import lrt_offline  # noqa: E402,F401

# Which AI: the local Qwen server by default. LRT_BASE_URL + LRT_AI_KEY (+ LRT_AI_MODEL) point at a company AI server
# or a provider the organisation has approved; LRT_ALLOW_REMOTE_AI=1 must be set for anything not on this computer.
BASE_URL = os.environ.get("LRT_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
API_KEY = os.environ.get("LRT_AI_KEY", "")          # read from the environment only; never written to logs or files
MODEL = os.environ.get("LRT_AI_MODEL", "qwen-local")
# Models the person may pick in the chat (comma separated, e.g. claude-sonnet-5-5,claude-opus-5-5,claude-haiku-5-5).
# Only these are accepted from the page, so the setup decides cost and data rules. The first one is not special:
# LRT_AI_MODEL stays the default.
MODELS = list(dict.fromkeys([MODEL] + [m.strip() for m in os.environ.get("LRT_AI_MODELS", "").split(",") if m.strip()]))
CURRENT = MODEL
STUB = os.environ.get("LRT_STUB_LLM") == "1"
TIMEOUT_S = float(os.environ.get("LRT_LLM_TIMEOUT", "240"))
WORKSPACE = os.environ.get("LRT_AI_WORKSPACE", "")   # Claude API keys not scoped to a workspace need anthropic-workspace-id

if not STUB:
    host = BASE_URL.split("//", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0].strip("[]")
    if not BASE_URL.startswith(("http://", "https://")):
        raise SystemExit("[assistant] LRT_BASE_URL must be an http(s) URL")
    if host not in lrt_offline.LOOPBACK and not BASE_URL.startswith("https://") and os.environ.get("LRT_ALLOW_REMOTE_AI") == "1":
        raise SystemExit("[assistant] a remote AI server must use https, so the request text and key are encrypted")
    if host not in lrt_offline.LOOPBACK and os.environ.get("LRT_ALLOW_REMOTE_AI") != "1":
        raise SystemExit(f"[assistant] model endpoint {BASE_URL} is not on this computer. Set LRT_ALLOW_REMOTE_AI=1 "
                         "only for an AI service your organisation has set up.")
else:
    host = ""
LOCAL = host in lrt_offline.LOOPBACK
# Claude through Anthropic's OpenAI-compatible endpoint (https://api.anthropic.com/v1). Current Claude models reject a
# temperature below 1 there, and think before answering (thinking is not returned), so they need more output room.
CLAUDE = host.endswith("anthropic.com")


def use(name=None):
    """Pick the model for the next calls: one of MODELS, else the default. Returns the model in use."""
    global CURRENT
    CURRENT = name if name in MODELS else MODEL
    return CURRENT


def headers(extra=None):
    """Request headers for the AI server. The key is only ever sent to that server; it is never logged."""
    h = {"Content-Type": "application/json", **(extra or {})}
    if API_KEY:
        h["Authorization"] = "Bearer " + API_KEY
        if CLAUDE:
            h["x-api-key"] = API_KEY
            h["anthropic-version"] = "2023-06-01"
    if CLAUDE and WORKSPACE:
        h["anthropic-workspace-id"] = WORKSPACE
    return h


class ModelUnavailable(RuntimeError):
    pass


def chat(messages, trace, node, max_tokens=700, temperature=0.0, label=""):
    t0 = time.time()
    if STUB:
        sys.path.insert(0, str(ROOT / "spikes"))
        from stub_llm import respond
        text = respond(messages)
    else:
        req_body = {"model": CURRENT, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        if CLAUDE:
            req_body.pop("temperature")
            req_body["max_tokens"] = max(max_tokens, int(os.environ.get("LRT_AI_MIN_TOKENS", "4000")))
        req = urllib.request.Request(BASE_URL + "/chat/completions", data=json.dumps(req_body).encode(), headers=headers())
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if LOCAL else urllib.request.build_opener()
        try:
            with opener.open(req, timeout=TIMEOUT_S) as r:
                text = json.loads(r.read())["choices"][0]["message"]["content"] or ""
        except urllib.error.HTTPError as e:
            detail = e.read(600).decode("utf-8", "replace")
            trace.log(node, "llm_error", label=label, error=f"HTTP {e.code}", detail=detail[:300])
            raise ModelUnavailable(f"The AI model at {BASE_URL} answered HTTP {e.code}: {detail[:200]}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            trace.log(node, "llm_error", label=label, error=str(e))
            raise ModelUnavailable(f"The AI model did not answer at {BASE_URL}: {e}")
    trace.log(node, "llm_call", label=label, stub=STUB, seconds=round(time.time() - t0, 2),
              prompt_chars=sum(len(str(m.get("content", ""))) for m in messages), reply_chars=len(text), reply=text[:1500])
    return text


def first_json(text):
    """First JSON value in a reply; code fences and prose around it are ignored."""
    text = re.sub(r"```(?:json)?", "", text or "")
    for i in sorted(i for i in (text.find("["), text.find("{")) if i >= 0):
        try:
            return json.JSONDecoder().raw_decode(text[i:])[0]
        except json.JSONDecodeError:
            continue
    return None

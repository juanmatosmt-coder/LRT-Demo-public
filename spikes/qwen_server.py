#!/usr/bin/env python3
r"""
Local OpenAI-compatible server for Qwen (runs in the MODEL venv: .venv).

Serves the same local model as rag_demo.py (Qwen3.5-9B, 4-bit, thinking off) at
  http://127.0.0.1:8000/v1/chat/completions   and   /v1/models
so CrewAI and LangChain (in .venv-agents) can use it like any OpenAI-style API.
Nothing leaves the laptop. Supports: messages (text or text parts), max_tokens,
temperature (0 = greedy), stop sequences, stream (simple SSE). Tool definitions in a
request are ignored: the agents in these spikes call tools from code, not via the model.

Run:   .\.venv\Scripts\python.exe spikes\qwen_server.py
Stub:  set LRT_STUB_LLM=1 to answer with canned text (for testing the plumbing only).
"""
import _offline  # noqa: F401  (no outbound traffic; see lrt_offline.py)
import json
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402

MODEL_ID = "qwen-local"
HOST, PORT = os.environ.get("LRT_HOST", "127.0.0.1"), int(os.environ.get("LRT_PORT", "8000"))
STUB = os.environ.get("LRT_STUB_LLM") == "1"
LOCK = threading.Lock()
app = FastAPI()
_state = {}


def load():
    if STUB:
        _state["info"] = {"model": "stub", "device": "none"}
        return
    import rag_demo as R
    info = R.load_models()
    _state.update(R=R, info={"model": R.CHAT_MODEL, "quantization": R.QUANT, **info})


def to_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content or "")


def generate(messages, max_tokens, temperature, stops):
    if STUB:
        from stub_llm import respond  # noqa: E402  (spikes/stub_llm.py)
        text = respond(messages)
        for s in stops or []:
            if s in text:
                text = text[:text.index(s)]
        return text, sum(len(to_text(m["content"]).split()) for m in messages), len(text.split())
    import torch
    R = _state["R"]
    msgs = [{"role": m["role"] if m["role"] in ("system", "user", "assistant") else "user",
             "content": to_text(m.get("content"))} for m in messages]
    if R.MULTIMODAL:
        msgs = [{"role": m["role"], "content": [{"type": "text", "text": m["content"]}]} for m in msgs]
    inputs = R._tokenizer.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True, return_dict=True,
                                              return_tensors="pt", enable_thinking=False).to(R._llm.device)
    tok = getattr(R._tokenizer, "tokenizer", R._tokenizer)
    kw = dict(max_new_tokens=max_tokens)
    if temperature and temperature > 0:
        kw.update(do_sample=True, temperature=temperature, top_p=0.8)
    else:
        kw.update(do_sample=False)
    if stops:
        kw.update(stop_strings=stops, tokenizer=tok)
    with torch.no_grad():
        out = R._llm.generate(**inputs, **kw)
    n_in = inputs["input_ids"].shape[-1]
    text = tok.decode(out[0][n_in:], skip_special_tokens=True)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    for s in stops or []:
        if s in text:
            text = text[:text.index(s)]
    return text.strip(), int(n_in), int(out.shape[-1] - n_in)


SERVER_KEY = os.environ.get("LRT_SERVER_KEY", "")


@app.middleware("http")
async def require_key(request, call_next):
    # On this computer no key is needed. Opened to the network (LRT_ALLOW_REMOTE=1), every call needs the key.
    client = request.client.host if request.client else ""
    if SERVER_KEY and client not in ("127.0.0.1", "::1"):
        import hmac
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + SERVER_KEY):
            return JSONResponse({"error": "missing or wrong API key"}, status_code=401)
    return await call_next(request)


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "owned_by": "local", **_state["info"]}]}


@app.get("/health")
def health():
    return {"ok": True, **_state["info"]}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    stops = body.get("stop") or []
    if isinstance(stops, str):
        stops = [stops]
    max_tokens = int(body.get("max_tokens") or body.get("max_completion_tokens") or 900)
    t0 = time.time()
    with LOCK:
        text, n_in, n_out = generate(body.get("messages", []), max_tokens, body.get("temperature", 0), stops)
    cid, created = f"chatcmpl-{uuid.uuid4().hex[:12]}", int(time.time())
    usage = {"prompt_tokens": n_in, "completion_tokens": n_out, "total_tokens": n_in + n_out}
    print(f"[qwen_server] {n_in} in / {n_out} out tokens in {time.time() - t0:.1f} s", flush=True)
    if body.get("stream"):
        def sse():
            base = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": MODEL_ID}
            yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': text}, 'finish_reason': None}]})}\n\n"
            last = {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            if (body.get("stream_options") or {}).get("include_usage"):
                last["usage"] = usage
            yield f"data: {json.dumps(last)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(sse(), media_type="text/event-stream")
    return JSONResponse({"id": cid, "object": "chat.completion", "created": created, "model": MODEL_ID,
                         "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                      "finish_reason": "stop"}], "usage": usage})


if __name__ == "__main__":
    import uvicorn
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    if HOST not in ("127.0.0.1", "localhost", "::1"):
        if os.environ.get("LRT_ALLOW_REMOTE") != "1":
            sys.exit(f"[qwen_server] refusing to listen on {HOST}: use 127.0.0.1, or set LRT_ALLOW_REMOTE=1 and LRT_SERVER_KEY.")
        if len(SERVER_KEY) < 24:
            sys.exit("[qwen_server] opened to the network, the server needs LRT_SERVER_KEY (24+ random characters).")
    load()
    print(f"[qwen_server] ready at http://{HOST}:{PORT}/v1 ({_state['info']})", flush=True)
    import lrt_pidfile
    lrt_pidfile.write("qwen", PORT)             # stop.bat uses it
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")

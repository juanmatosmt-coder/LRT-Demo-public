#!/usr/bin/env python3
"""
Minimal RAG demonstration - Lab Request Assistant (Capstone Checkpoint 3.1).

Runs the same engineer request through a local Qwen model five ways:
  1. no_retrieval            - Qwen sees only the engineer's request
  v1 (one query = the engineer's request):
  2. retrieval_unfiltered    - top-k passages by semantic similarity, all documents
  3. retrieval_filtered      - top-k passages, restricted to active documents of the
                               confirmed test types (failure-mode mitigation)
  v2 (changes to how passages are selected, both on top of the filter):
  4. filtered_mmr            - top-k by Maximal Marginal Relevance (relevance vs. redundancy)
  5. filtered_form_sections  - one query per lab request form section, top 1 each

It also runs retrieval-only probe queries to show ranking behavior and decoys.

Models run locally through Hugging Face transformers / sentence-transformers.
The first run downloads them; later runs are offline. All traces go to ./traces/.
"""
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import lrt_offline  # noqa: F401,E402  (no outbound traffic; see lrt_offline.py)

# ---------------------------------------------------------------- configuration
CHAT_MODEL = os.environ.get("CHAT_MODEL", "Qwen/Qwen3.5-9B")
# Qwen3.5 checkpoints are natively multimodal and load through the multimodal classes.
MULTIMODAL = "qwen3.5" in CHAT_MODEL.lower()
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-base-en-v1.5")
TOP_K = int(os.environ.get("TOP_K", "3"))
MMR_LAMBDA = float(os.environ.get("MMR_LAMBDA", "0.5"))
# QUANT=4bit loads the chat model in 4-bit (bitsandbytes) so it fits on the GPU; QUANT=none = bf16.
QUANT = os.environ.get("QUANT", "4bit").lower()
PROBE_K = 5
MAX_NEW_TOKENS = 900

HERE = Path(__file__).resolve().parent
DOCS_DIR = HERE / "docs"
# One trace folder per chat model, so runs with different models do not overwrite each other.
TRACE_DIR = HERE / "traces" / (CHAT_MODEL.split("/")[-1] + ("-4bit" if QUANT == "4bit" else ""))

# bge models recommend this instruction on queries only; documents get no prefix.
DOC_PREFIX = ""
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

ENGINEER_REQUEST = (
    "I need warpage measured on 10 LCP connector housings (synthetic part SYN-CONN-400, "
    "400 positions, 0.8 mm pitch) through a lead-free reflow cycle. The customer wants to "
    "know whether coplanarity stays within 0.10 mm at peak temperature. "
    "Please prepare the lab request."
)

# Scope confirmed with the engineer and held in short-term memory.
# In the full assistant this comes from the conversation; here it is fixed for the demo.
CONFIRMED_SCOPE = {
    "test_types": {"warpage_reflow", "preparation", "reporting"},
    "status": "active",
}

# Test description held in short-term memory once the engineer confirms the test type.
CONFIRMED_TEST = "warpage measurement during reflow simulation"

# v2: one retrieval query per section of the standard lab request form.
FORM_SECTION_QUERIES = {
    "required_inputs": "information the requester must provide before scheduling {test}",
    "sample_preparation": "sample preparation and preconditioning required before {test}",
    "sample_quantity": "minimum number of samples and sample identification for {test}",
    "test_sequence": "required order of test steps for {test}",
    "reporting": "required data, plots and files to report for {test}",
}

PROBE_QUERIES = [
    "What thermal profile information must the requester provide?",
    "Is moisture preconditioning required before warpage measurement?",
    "How many samples are required and how flat must the housing be?",
]

SYSTEM_PROMPT = """You are a lab request assistant. You help an engineer prepare a DRAFT laboratory test request. The engineer approves the final test plan; you never submit anything.

Rules:
- State a test requirement only if it appears in a REFERENCE PASSAGE, and cite it as [doc_id Rev X, section].
- If an input the procedure requires is missing from the engineer's request, list it under "Questions for the engineer". Do not invent values.
- If no reference passages are provided, or they do not cover something, say which requirements you could not verify.
- Keep the draft short and specific.

Use these headings:
1. Draft request summary
2. Sample preparation and quantity
3. Test sequence
4. Questions for the engineer
5. Sources used"""


# ---------------------------------------------------------------- models (loaded once)
_embedder = None
_tokenizer = None
_llm = None


def load_models():
    global _embedder, _tokenizer, _llm
    import torch
    from sentence_transformers import SentenceTransformer
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"torch {torch.__version__}, device: {device}"
          + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else " - this will be slow"))
    print(f"Loading embedding model {EMBED_MODEL} ...", flush=True)
    _embedder = SentenceTransformer(EMBED_MODEL, device=device)
    print(f"Loading chat model {CHAT_MODEL} (first run downloads it) ...", flush=True)
    # bfloat16 on GPUs that support it (RTX 30xx and newer); float16 on older ones such as Colab's T4.
    half = torch.bfloat16 if device == "cuda" and torch.cuda.is_bf16_supported() else torch.float16
    if MULTIMODAL:
        from transformers import AutoModelForMultimodalLM, AutoProcessor
        _tokenizer = AutoProcessor.from_pretrained(CHAT_MODEL)
        model_cls = AutoModelForMultimodalLM
    else:
        _tokenizer = AutoTokenizer.from_pretrained(CHAT_MODEL)
        model_cls = AutoModelForCausalLM
    if QUANT == "4bit" and device == "cuda":
        from transformers import BitsAndBytesConfig
        _llm = model_cls.from_pretrained(
            CHAT_MODEL,
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=half),
            device_map={"": 0},  # whole model on the GPU, no CPU offload
        )
    else:
        _llm = model_cls.from_pretrained(
            CHAT_MODEL,
            dtype=half if device == "cuda" else torch.float32,
            device_map="auto",
        )
    return {
        "torch": torch.__version__,
        "device": torch.cuda.get_device_name(0) if device == "cuda" else "cpu",
    }


def embed(texts):
    vecs = _embedder.encode(texts, normalize_embeddings=True)
    return [list(map(float, v)) for v in vecs]


def chat(messages):
    import torch
    if MULTIMODAL:
        # The multimodal processor expects message content as a list of typed parts.
        messages = [{"role": m["role"], "content": [{"type": "text", "text": m["content"]}]}
                    for m in messages]
    # enable_thinking=False turns off Qwen3/3.5 reasoning mode; older templates ignore it.
    inputs = _tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True, return_dict=True,
        return_tensors="pt", enable_thinking=False,
    ).to(_llm.device)
    with torch.no_grad():
        out = _llm.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False)
    text = _tokenizer.decode(out[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


# ---------------------------------------------------------------- documents and chunks
def parse_doc(path):
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path.name}: missing metadata header")
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip()] = val.strip()
    return meta, m.group(2)


def chunk_doc(meta, body, source):
    """One chunk per '## ' section, so each requirement stays with its conditions.
    The document ID, revision and title are prepended so they are embedded and visible."""
    chunks = []
    for part in re.split(r"(?m)^## ", body)[1:]:
        heading, _, content = part.partition("\n")
        content = content.strip()
        if not content:
            continue
        header = f"{meta['doc_id']} Rev {meta['revision']} - {meta['title']} - {heading.strip()}"
        chunks.append({
            "doc_id": meta["doc_id"],
            "revision": meta["revision"],
            "title": meta["title"],
            "status": meta["status"],
            "test_type": meta["test_type"],
            "section": heading.strip(),
            "source_file": source,
            "text": f"{header}\n{content}",
        })
    return chunks


def load_library():
    chunks = []
    for path in sorted(DOCS_DIR.glob("*.md")):
        meta, body = parse_doc(path)
        chunks.extend(chunk_doc(meta, body, path.name))
    return chunks


# ---------------------------------------------------------------- retrieval
def cosine(a, b):
    # Embeddings are normalized, so the dot product is the cosine similarity.
    return sum(x * y for x, y in zip(a, b))


def in_scope(chunk, scope):
    return chunk["status"] == scope["status"] and chunk["test_type"] in scope["test_types"]


def retrieve(query_vec, chunks, k, scope=None):
    pool = [c for c in chunks if scope is None or in_scope(c, scope)]
    scored = sorted(((cosine(query_vec, c["vec"]), c) for c in pool),
                    key=lambda t: t[0], reverse=True)
    return [dict(score=round(s, 4), **{k2: v for k2, v in c.items() if k2 != "vec"})
            for s, c in scored[:k]]


def retrieve_mmr(query_vec, chunks, k, lam, scope=None):
    """Maximal Marginal Relevance, as in the Module 3 lab:
    MMR(d) = lam * sim(d, q) - (1 - lam) * max_{s in selected} sim(d, s)."""
    pool = [c for c in chunks if scope is None or in_scope(c, scope)]
    selected = []
    while pool and len(selected) < k:
        best = None
        for c in pool:
            rel = cosine(query_vec, c["vec"])
            red = max((cosine(c["vec"], s["vec"]) for s, _, _ in selected), default=0.0)
            mmr = lam * rel - (1 - lam) * red
            if best is None or mmr > best[2]:
                best = (c, rel, mmr)
        selected.append(best)
        pool.remove(best[0])
    return [dict(score=round(rel, 4), mmr_score=round(mmr, 4),
                 **{k2: v for k2, v in c.items() if k2 != "vec"})
            for c, rel, mmr in selected]


def retrieve_form_sections(chunks, scope, test):
    """One query per form section; keep the top hit of each, skipping duplicates."""
    out, seen = [], set()
    for section, template in FORM_SECTION_QUERIES.items():
        q = template.format(test=test)
        qv = embed([QUERY_PREFIX + q])[0]
        for hit in retrieve(qv, chunks, len(chunks), scope):
            key = (hit["doc_id"], hit["revision"], hit["section"])
            if key not in seen:
                seen.add(key)
                out.append(dict(form_section=section, query=q, **hit))
                break
    return out


def format_passages(passages):
    if not passages:
        return "REFERENCE PASSAGES: (none provided)"
    lines = ["REFERENCE PASSAGES:"]
    for i, p in enumerate(passages, 1):
        flag = "" if p["status"] == "active" else f" [STATUS: {p['status'].upper()}]"
        lines.append(f"\n[{i}] {p['doc_id']} Rev {p['revision']}, section '{p['section']}'{flag}\n{p['text']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- main
def main():
    env = load_models()
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    run_info = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "chat_model": CHAT_MODEL,
        "embed_model": EMBED_MODEL,
        "top_k": TOP_K,
        "mmr_lambda": MMR_LAMBDA,
        "quantization": "4-bit NF4 (bitsandbytes)" if QUANT == "4bit" else "none (bf16)",
        "decoding": f"greedy, max_new_tokens={MAX_NEW_TOKENS}",
        **env,
    }

    chunks = load_library()
    print(f"Loaded {len(chunks)} chunks from {len(set(c['source_file'] for c in chunks))} documents.")
    for c, v in zip(chunks, embed([DOC_PREFIX + c["text"] for c in chunks])):
        c["vec"] = v

    (TRACE_DIR / "chunks.json").write_text(json.dumps(
        [{k: v for k, v in c.items() if k != "vec"} for c in chunks], indent=2), encoding="utf-8")

    # ---- retrieval-only probes (unfiltered) to show ranking and decoys
    probes = []
    for q in PROBE_QUERIES:
        qv = embed([QUERY_PREFIX + q])[0]
        hits = retrieve(qv, chunks, PROBE_K)
        for h in hits:
            h["in_confirmed_scope"] = in_scope(h, CONFIRMED_SCOPE)
        probes.append({"query": q, "results": hits})
    (TRACE_DIR / "probes.json").write_text(json.dumps(probes, indent=2), encoding="utf-8")

    # ---- three runs of the same engineer request
    req_vec = embed([QUERY_PREFIX + ENGINEER_REQUEST])[0]
    modes = {
        "no_retrieval": [],
        "retrieval_unfiltered": retrieve(req_vec, chunks, TOP_K),
        "retrieval_filtered": retrieve(req_vec, chunks, TOP_K, CONFIRMED_SCOPE),
        "filtered_mmr": retrieve_mmr(req_vec, chunks, TOP_K, MMR_LAMBDA, CONFIRMED_SCOPE),
        "filtered_form_sections": retrieve_form_sections(chunks, CONFIRMED_SCOPE, CONFIRMED_TEST),
    }
    results = {}
    for mode, passages in modes.items():
        print(f"Running {mode} ...", flush=True)
        user_msg = f"{format_passages(passages)}\n\nENGINEER REQUEST:\n{ENGINEER_REQUEST}"
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg}]
        t0 = time.time()
        answer = chat(messages)
        results[mode] = {
            "retrieved": passages,
            "messages": messages,
            "response": answer,
            "seconds": round(time.time() - t0, 1),
        }
        print(f"  done in {results[mode]['seconds']} s")
        (TRACE_DIR / f"run_{mode}.json").write_text(json.dumps(
            {"run_info": run_info, "mode": mode, **results[mode]}, indent=2), encoding="utf-8")

    write_summary(run_info, chunks, probes, results)
    print(f"\nDone. Read {TRACE_DIR / 'summary.md'}")


def write_summary(run_info, chunks, probes, results):
    out = ["# RAG demo trace summary", ""]
    out += [f"- {k}: {v}" for k, v in run_info.items()]
    out += [f"- chunks: {len(chunks)}", f"- confirmed scope: {sorted(CONFIRMED_SCOPE['test_types'])}, "
            f"status={CONFIRMED_SCOPE['status']}", "", "## Engineer request", "", ENGINEER_REQUEST, ""]

    out += ["## Retrieval probes (unfiltered, top %d)" % PROBE_K, ""]
    for p in probes:
        out += [f"**Query:** {p['query']}", "", "| Rank | Score | Document | Section | Status | In scope |",
                "|---|---|---|---|---|---|"]
        for i, h in enumerate(p["results"], 1):
            out.append(f"| {i} | {h['score']} | {h['doc_id']} Rev {h['revision']} | {h['section']} | "
                       f"{h['status']} | {'yes' if h['in_confirmed_scope'] else 'NO'} |")
        out.append("")

    for mode, r in results.items():
        out += [f"## Run: {mode}  ({r['seconds']} s)", ""]
        if r["retrieved"]:
            out += ["| Rank | Score | MMR score | Form section | Document | Section | Status |",
                    "|---|---|---|---|---|---|---|"]
            for i, h in enumerate(r["retrieved"], 1):
                out.append(f"| {i} | {h['score']} | {h.get('mmr_score', '')} | {h.get('form_section', '')} | "
                           f"{h['doc_id']} Rev {h['revision']} | {h['section']} | {h['status']} |")
            out.append("")
        else:
            out += ["_No passages retrieved._", ""]
        out += ["**Qwen response:**", "", r["response"], ""]

    (TRACE_DIR / "summary.md").write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    main()

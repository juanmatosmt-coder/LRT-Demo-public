#!/usr/bin/env python3
"""
Retrieval-only comparison of routes (no chat model; a few minutes on a laptop).

For every scenario in scenarios.json, every retrieval route is scored on:
  recall     share of the scenario's required facts found whole inside one retrieved chunk
  worst      lowest recall over the scenarios (the route's weakest case)
  forbidden  forbidden facts retrieved: obsolete or inapplicable rules (total over scenarios)
  off_scope  retrieved chunks from obsolete documents or test types outside the scenario (total)
  passages   chunks passed to the model (mean)
  words      words passed to the model (mean) = the context budget

What varies:
  library    base = the 6 documents used for Checkpoint 3.1 (docs/)
             extended = base + 6 more (docs_extended/): equipment operation, data processing,
             cleaning, another obsolete revision, a look-alike method, another report format
  chunking   section (one chunk per '## ' section) vs fixed100 (course DPR lab: 100-word blocks)
  embedder   bge-base-en-v1.5 vs all-MiniLM-L6-v2 (the course lab's encoder) vs bm25 (keyword baseline)
  route      query = the engineer's request, or one query per form section
             selection = top-k or MMR; metadata filter on or off; k = 3, 5, 8
             'everything in scope' = the whole filtered library (an upper bound, no ranking at all)

Writes eval/results/retrieval_results.csv and eval/results/retrieval_summary.md.
"""
import sys as _s, pathlib as _p; _s.path.insert(0, str(_p.Path(__file__).resolve().parents[1]))
import lrt_offline  # noqa: F401,E402  (no outbound traffic)
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import rag_demo as R  # noqa: E402  (reuses the demo's document parser, section chunker, form-section queries)

OUT = HERE / "results"
SCEN = json.loads((HERE / "scenarios.json").read_text(encoding="utf-8"))

LIBRARIES = {"base": [ROOT / "docs"], "extended": [ROOT / "docs", ROOT / "docs_extended"]}
EMBEDDERS = {
    # name: (model id, query prefix, document prefix)
    "bge-base": ("BAAI/bge-base-en-v1.5", R.QUERY_PREFIX, ""),
    "minilm": ("sentence-transformers/all-MiniLM-L6-v2", "", ""),
}
K_VALUES = [3, 5, 8]
MMR_LAMBDAS = [0.5, 0.7]


# ---------------------------------------------------------------- chunking
def chunk_fixed(meta, body, source, size=100):
    """Course-lab style: fixed word blocks with the title prepended (DPR 'Title [SEP] text')."""
    text = re.sub(r"(?m)^## ", "", body)
    text = re.sub(r"(?m)^SYNTHETIC DOCUMENT.*$", "", text)
    words = text.split()
    chunks = []
    for i in range(0, len(words), size):
        piece = words[i:i + size]
        chunks.append({
            "doc_id": meta["doc_id"], "revision": meta["revision"], "title": meta["title"],
            "status": meta["status"], "test_type": meta["test_type"],
            "section": f"words {i + 1}-{i + len(piece)}", "source_file": source,
            "text": f"{meta['doc_id']} Rev {meta['revision']} - {meta['title']}\n{' '.join(piece)}",
        })
    return chunks


def load_chunks(library, kind):
    chunks = []
    for d in LIBRARIES[library]:
        for path in sorted(d.glob("*.md")):
            meta, body = R.parse_doc(path)
            chunks.extend(R.chunk_doc(meta, body, path.name) if kind == "section"
                          else chunk_fixed(meta, body, path.name))
    return chunks


# ---------------------------------------------------------------- scorers (query -> score per chunk)
def dense_scorer(encode, qprefix, dprefix, chunks):
    vecs = encode([dprefix + c["text"] for c in chunks])
    cache = {}

    def score(q):
        if q not in cache:
            qv = encode([qprefix + q])[0]
            cache[q] = [sum(x * y for x, y in zip(qv, v)) for v in vecs]
        return cache[q]

    def sim(i, j):
        return sum(x * y for x, y in zip(vecs[i], vecs[j]))
    return score, sim


def bm25_scorer(chunks, k1=1.5, b=0.75):
    tok = lambda s: re.findall(r"[a-z0-9]+", s.lower())  # noqa: E731
    docs = [tok(c["text"]) for c in chunks]
    avg = sum(map(len, docs)) / len(docs)
    df = Counter(t for d in docs for t in set(d))
    n = len(docs)
    idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
    tfs = [Counter(d) for d in docs]

    def score(q):
        qt = tok(q)
        return [sum(idf.get(t, 0) * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg))
                    for t in qt if t in tf) for d, tf in zip(docs, tfs)]

    def sim(i, j):  # word-overlap similarity for MMR with the keyword baseline
        a, c = set(docs[i]), set(docs[j])
        return len(a & c) / max(1, len(a | c))
    return score, sim


# ---------------------------------------------------------------- selection
def in_scope(c, types):
    return c["status"] == "active" and c["test_type"] in types


def pool_ids(chunks, types):
    return [i for i, c in enumerate(chunks) if types is None or in_scope(c, types)]


def topk(scores, ids, k):
    return sorted(ids, key=lambda i: scores[i], reverse=True)[:k]


def mmr(scores, sim, ids, k, lam):
    pool, sel = list(ids), []
    while pool and len(sel) < k:
        best = max(pool, key=lambda i: lam * scores[i] - (1 - lam) * max((sim(i, s) for s in sel), default=0.0))
        sel.append(best)
        pool.remove(best)
    return sel


def form_sections(score, chunks, scen, types, per_query=1):
    """One query per form section for each primary test; keep the top hit(s), no duplicates."""
    out, ids = [], pool_ids(chunks, types)
    for test in scen["primary_tests"]:
        desc = SCEN["test_descriptions"][test]
        for template in R.FORM_SECTION_QUERIES.values():
            got = 0
            for i in topk(score(template.format(test=desc)), ids, len(ids)):
                if i not in out:
                    out.append(i)
                    got += 1
                    if got == per_query:
                        break
    return out


def routes(scen, score, sim, chunks):
    types = set(scen["scope_types"])
    s = score(scen["request"])
    unf, fil = pool_ids(chunks, None), pool_ids(chunks, types)
    for k in K_VALUES:
        yield "request, unfiltered", k, topk(s, unf, k)
        yield "request, filtered", k, topk(s, fil, k)
        for lam in MMR_LAMBDAS:
            yield f"request, filtered, MMR {lam}", k, mmr(s, sim, fil, k, lam)
    yield "form sections, unfiltered", "1/section", form_sections(score, chunks, scen, None)
    yield "form sections, filtered", "1/section", form_sections(score, chunks, scen, types)
    yield "form sections, filtered", "2/section", form_sections(score, chunks, scen, types, 2)
    yield "everything in scope (no ranking)", "all", fil


# ---------------------------------------------------------------- scoring
def norm(s):
    return re.sub(r"\s+", " ", s)


def evaluate(scen, retrieved):
    texts = [norm(c["text"]) for c in retrieved]
    req = scen["required_facts"]
    found = [f for f in req if any(f in t for t in texts)]
    forb = [f for f in scen["forbidden_facts"] if any(f in t for t in texts)]
    types = set(scen["scope_types"])
    return {
        "recall": len(found) / len(req),
        "forbidden": len(forb),
        "off_scope": sum(1 for c in retrieved if not in_scope(c, types)),
        "passages": len(retrieved),
        "words": sum(len(c["text"].split()) for c in retrieved),
        "missed": "; ".join(f for f in req if f not in found),
        "forbidden_hits": "; ".join(forb),
    }


# ---------------------------------------------------------------- main
def get_encoder(model_id):
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(model_id, device="cpu")
    return lambda texts: [list(map(float, v)) for v in m.encode(texts, normalize_embeddings=True)]


def run(encoder_factory=get_encoder):
    OUT.mkdir(parents=True, exist_ok=True)
    encoders = {}
    rows = []
    for library in LIBRARIES:
        for chunking in ("section", "fixed100"):
            chunks = load_chunks(library, chunking)
            print(f"{library} library, {chunking} chunks: {len(chunks)}", flush=True)
            scorers = {"bm25": bm25_scorer(chunks)}
            for name, (model_id, qp, dp) in EMBEDDERS.items():
                if name not in encoders:
                    print(f"  loading {model_id}", flush=True)
                    encoders[name] = encoder_factory(model_id)
                scorers[name] = dense_scorer(encoders[name], qp, dp, chunks)
            for emb, (score, sim) in scorers.items():
                for scen in SCEN["scenarios"]:
                    for route, k, ids in routes(scen, score, sim, chunks):
                        rows.append({"library": library, "embedder": emb, "chunking": chunking, "route": route,
                                     "k": k, "scenario": scen["id"],
                                     **evaluate(scen, [chunks[i] for i in ids])})
    write(rows)
    return rows


def summarize(rows):
    groups = {}
    for r in rows:
        groups.setdefault((r["library"], r["embedder"], r["chunking"], r["route"], str(r["k"])), []).append(r)
    out = []
    for (lib, emb, ch, route, k), rs in groups.items():
        out.append({"library": lib, "embedder": emb, "chunking": ch, "route": route, "k": k,
                    "recall": sum(r["recall"] for r in rs) / len(rs), "worst": min(r["recall"] for r in rs),
                    "forbidden": sum(r["forbidden"] for r in rs), "off_scope": sum(r["off_scope"] for r in rs),
                    "passages": sum(r["passages"] for r in rs) / len(rs),
                    "words": sum(r["words"] for r in rs) / len(rs)})
    out.sort(key=lambda s: (-s["recall"], s["forbidden"], s["words"]))
    return out


def table(rows, cols):
    head = "| " + " | ".join(c for c, _ in cols) + " |"
    sep = "|" + "---|" * len(cols)
    body = ["| " + " | ".join(f(r) for _, f in cols) + " |" for r in rows]
    return [head, sep] + body


def write(rows):
    with open(OUT / "retrieval_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    summ = summarize(rows)
    n = len(SCEN["scenarios"])
    cols = [("Embedder", lambda s: s["embedder"]), ("Chunking", lambda s: s["chunking"]),
            ("Route", lambda s: s["route"]), ("k", lambda s: s["k"]),
            ("Recall", lambda s: f"{s['recall']:.2f}"), ("Worst", lambda s: f"{s['worst']:.2f}"),
            ("Forbidden", lambda s: str(s["forbidden"])), ("Off-scope", lambda s: str(s["off_scope"])),
            ("Passages", lambda s: f"{s['passages']:.1f}"), ("Words", lambda s: f"{s['words']:.0f}")]

    md = ["# Retrieval route comparison", "",
          f"{n} synthetic scenarios. **Recall** = share of required facts retrieved whole (mean); **worst** = lowest "
          "single scenario; **forbidden** = obsolete or inapplicable rules retrieved (total); **off-scope** = chunks "
          "outside the scenario's scope (total); passages and words = mean context passed to the model.", ""]

    for lib in LIBRARIES:
        s_lib = [s for s in summ if s["library"] == lib]
        md += [f"## {lib.capitalize()} library: best route per context budget", "",
               "Within each budget (mean words passed to the model): highest recall, then fewest forbidden facts, "
               "then fewest words. Ranked routes only (the everything-in-scope bound is listed separately).", ""]
        best = []
        for budget in (150, 250, 400, 600):
            cand = [s for s in s_lib if s["words"] <= budget and not s["route"].startswith("everything")]
            if cand:
                best.append({**cand[0], "budget": f"≤ {budget}"})
        md += table(best, [("Budget (words)", lambda s: s["budget"])] + cols) + [""]
        allin = [s for s in s_lib if s["route"].startswith("everything")]
        md += ["Upper bound, whole filtered library with no ranking:", ""]
        md += table(allin, [c for c in cols if c[0] not in ("Route", "k")]) + [""]

        md += [f"### {lib.capitalize()} library: same budget, different routes (bge-base, section chunks)", ""]
        md += table([s for s in s_lib if s["embedder"] == "bge-base" and s["chunking"] == "section"], cols) + [""]
        md += [f"### {lib.capitalize()} library: embedder and chunking (filtered request top-5 and form sections 1/section)", ""]
        sel = [s for s in s_lib if (s["route"], s["k"]) in (("request, filtered", "5"),
                                                            ("form sections, filtered", "1/section"))]
        md += table(sel, cols) + [""]

    md += ["## Per scenario (extended library, bge-base, section chunks)", ""]
    md += table([r for r in rows if r["library"] == "extended" and r["embedder"] == "bge-base"
                 and r["chunking"] == "section"],
                [("Scenario", lambda r: r["scenario"]), ("Route", lambda r: r["route"]), ("k", lambda r: str(r["k"])),
                 ("Recall", lambda r: f"{r['recall']:.2f}"), ("Forbidden", lambda r: r["forbidden_hits"] or "—"),
                 ("Missed facts", lambda r: r["missed"] or "—")])
    (OUT / "retrieval_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Wrote {OUT / 'retrieval_summary.md'}")


if __name__ == "__main__":
    run()

#!/usr/bin/env python3
"""
End-to-end comparison: does a better retrieval route give a better draft?

Runs each scenario in scenarios.json through local Qwen with the passages chosen by each
route (bge-base embeddings, section chunks, the same prompt as rag_demo.py) and scores the
draft with the scenario's regex checks:
  coverage   share of output_checks found in the draft (things the draft should state or ask)
  forbidden  output_forbidden patterns found (obsolete or inapplicable rules repeated)
The regex scoring is approximate: use it to compare routes, and read the saved drafts for
any route you intend to rely on.

Usage (from the repo root, inside the venv):
  python eval/eval_generation.py                      # extended library, default routes
  python eval/eval_generation.py --library base
  python eval/eval_generation.py --routes none form1 all --scenarios S1 S5

Writes eval/results/generation_<library>.csv, .jsonl (full drafts) and _summary.md.
About 30-60 s per draft with Qwen3.5-9B 4-bit on a 16 GB laptop GPU.
"""
import sys as _s, pathlib as _p; _s.path.insert(0, str(_p.Path(__file__).resolve().parents[1]))
import lrt_offline  # noqa: F401,E402  (no outbound traffic)
import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import rag_demo as R  # noqa: E402
import eval_retrieval as E  # noqa: E402

# route key: (label, selector(score, sim, chunks, scen) -> chunk indices)
ROUTES = {
    "none": ("no retrieval", None),
    "req_u5": ("request, unfiltered, k=5",
               lambda sc, sim, ch, s: E.topk(sc(s["request"]), E.pool_ids(ch, None), 5)),
    "req_f5": ("request, filtered, k=5",
               lambda sc, sim, ch, s: E.topk(sc(s["request"]), E.pool_ids(ch, set(s["scope_types"])), 5)),
    "mmr07_5": ("request, filtered, MMR 0.7, k=5",
                lambda sc, sim, ch, s: E.mmr(sc(s["request"]), sim, E.pool_ids(ch, set(s["scope_types"])), 5, 0.7)),
    "form1": ("form sections, filtered, 1/section",
              lambda sc, sim, ch, s: E.form_sections(sc, ch, s, set(s["scope_types"]))),
    "form2": ("form sections, filtered, 2/section",
              lambda sc, sim, ch, s: E.form_sections(sc, ch, s, set(s["scope_types"]), 2)),
    "all": ("everything in scope (no ranking)",
            lambda sc, sim, ch, s: E.pool_ids(ch, set(s["scope_types"]))),
}
DEFAULT_ROUTES = ["none", "req_u5", "req_f5", "mmr07_5", "form1", "all"]


def score_draft(scen, text):
    hits = {name: bool(re.search(p, text, re.I)) for name, p in scen["output_checks"].items()}
    bad = {name: bool(re.search(p, text, re.I)) for name, p in scen["output_forbidden"].items()}
    return hits, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", default="extended", choices=list(E.LIBRARIES))
    ap.add_argument("--routes", nargs="+", default=DEFAULT_ROUTES, choices=list(ROUTES))
    ap.add_argument("--scenarios", nargs="+", default=None, help="scenario id prefixes, e.g. S1 S5")
    args = ap.parse_args()

    scenarios = [s for s in E.SCEN["scenarios"]
                 if not args.scenarios or any(s["id"].startswith(p) for p in args.scenarios)]
    env = R.load_models()
    chunks = E.load_chunks(args.library, "section")
    score, sim = E.dense_scorer(R.embed, R.QUERY_PREFIX, R.DOC_PREFIX, chunks)

    E.OUT.mkdir(parents=True, exist_ok=True)
    stem = E.OUT / f"generation_{args.library}"
    rows = []
    with open(f"{stem}.jsonl", "w", encoding="utf-8") as jf:
        for scen in scenarios:
            for key in args.routes:
                label, select = ROUTES[key]
                passages = [] if select is None else [chunks[i] for i in select(score, sim, chunks, scen)]
                user = f"{R.format_passages(passages)}\n\nENGINEER REQUEST:\n{scen['request']}"
                t0 = time.time()
                draft = R.chat([{"role": "system", "content": R.SYSTEM_PROMPT}, {"role": "user", "content": user}])
                secs = round(time.time() - t0, 1)
                hits, bad = score_draft(scen, draft)
                ret = E.evaluate(scen, passages) if passages else {"recall": 0.0, "words": 0}
                row = {"scenario": scen["id"], "route": label, "retrieval_recall": round(ret["recall"], 2),
                       "context_words": ret["words"], "coverage": round(sum(hits.values()) / len(hits), 2),
                       "forbidden": sum(bad.values()), "seconds": secs,
                       "missed_checks": "; ".join(k for k, v in hits.items() if not v),
                       "forbidden_found": "; ".join(k for k, v in bad.items() if v)}
                rows.append(row)
                jf.write(json.dumps({**row, "passages": [f"{p['doc_id']} Rev {p['revision']} / {p['section']}"
                                                          for p in passages], "draft": draft}) + "\n")
                jf.flush()
                print(f"{scen['id']:<28} {label:<38} coverage {row['coverage']:.2f}  "
                      f"forbidden {row['forbidden']}  {secs} s", flush=True)

    with open(f"{stem}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    by = {}
    for r in rows:
        by.setdefault(r["route"], []).append(r)
    md = [f"# Generation comparison ({args.library} library)", "",
          f"Chat model {R.CHAT_MODEL} ({env['device']}, quantization {R.QUANT}); retrieval bge-base, section chunks. "
          "Coverage = share of a scenario's output checks found in the draft (regex, approximate). "
          "Forbidden = obsolete or inapplicable rules repeated in the draft.", "",
          "| Route | Coverage (mean) | Coverage (worst) | Forbidden (total) | Retrieval recall | Context words | s / draft |",
          "|---|---|---|---|---|---|---|"]
    order = sorted(by, key=lambda k: (-sum(r["coverage"] for r in by[k]) / len(by[k]),
                                      sum(r["forbidden"] for r in by[k])))
    for k in order:
        rs = by[k]
        md.append(f"| {k} | {sum(r['coverage'] for r in rs) / len(rs):.2f} | {min(r['coverage'] for r in rs):.2f} | "
                  f"{sum(r['forbidden'] for r in rs)} | {sum(r['retrieval_recall'] for r in rs) / len(rs):.2f} | "
                  f"{sum(r['context_words'] for r in rs) / len(rs):.0f} | {sum(r['seconds'] for r in rs) / len(rs):.0f} |")
    md += ["", "## Per scenario", "", "| Scenario | Route | Coverage | Forbidden found | Missed checks |",
           "|---|---|---|---|---|"]
    md += [f"| {r['scenario']} | {r['route']} | {r['coverage']:.2f} | {r['forbidden_found'] or '—'} | "
           f"{r['missed_checks'] or '—'} |" for r in rows]
    Path(f"{stem}_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nWrote {stem}_summary.md (drafts in {stem.name}.jsonl)")


if __name__ == "__main__":
    main()

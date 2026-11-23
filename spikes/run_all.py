#!/usr/bin/env python3
r"""
Run every spike test and write spikes/results/validation_report.md (+ .json).
Run from the repo root in the AGENTS venv:   .\.venv-agents\Scripts\python.exe spikes\run_all.py

It starts the Qwen server with the MODEL venv's Python (.venv) unless one is already
answering at LRT_BASE_URL, runs tests 1-5, then stops the server it started.
Options: --only 1 2 4   run a subset;   --keep-server   leave the server running.
"""
import _offline  # noqa: F401  (no outbound traffic; see lrt_offline.py)
import argparse
import importlib
import json
import os
import platform
import subprocess
import sys
import time
import traceback
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import BASE_URL, STUB, model_python  # noqa: E402

TESTS = ["t1_server", "t2_langchain", "t3_crewai", "t4_mcp", "t5_tot"]
OUT = HERE / "results"


def health():
    try:
        with urllib.request.urlopen(BASE_URL.rsplit("/v1", 1)[0] + "/health", timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return None


def versions():
    out = {"python": platform.python_version(), "os": platform.platform()}
    for p in ("crewai", "langchain-core", "langchain-openai", "langchain-mcp-adapters", "mcp", "openai"):
        try:
            out[p] = version(p)
        except PackageNotFoundError:
            out[p] = "not installed"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="+", type=int)
    ap.add_argument("--keep-server", action="store_true")
    args = ap.parse_args()

    proc, info = None, health()
    if not info:
        env = {**os.environ, "TRITON_DEFAULT_FP_FUSION": "1"}
        print(f"Starting Qwen server with {model_python()} (loading the model takes a minute) ...", flush=True)
        proc = subprocess.Popen([model_python(), str(HERE / "qwen_server.py")], env=env)
        for _ in range(600):
            time.sleep(1)
            info = health()
            if info or proc.poll() is not None:
                break
        if not info:
            sys.exit("Qwen server did not start; run spikes\\qwen_server.py in the .venv to see the error.")
    print(f"Server: {info}", flush=True)

    results = []
    for i, name in enumerate(TESTS, 1):
        if args.only and i not in args.only:
            continue
        print(f"\n=== Test {i}: {name} ===", flush=True)
        t0 = time.time()
        try:
            r = importlib.import_module(name).run()
        except Exception as e:  # a crash is a failed test with its traceback, not a stopped run
            r = {"name": name, "passed": False, "seconds": round(time.time() - t0, 1),
                 "details": {"error": repr(e), "traceback": traceback.format_exc()[-3000:]}}
        print(f"{'PASSED' if r['passed'] else 'FAILED'} in {r['seconds']} s: {r['name']}", flush=True)
        results.append(r)

    if proc and not args.keep_server:
        proc.terminate()

    OUT.mkdir(exist_ok=True)
    meta = {"timestamp": time.strftime("%Y-%m-%d %H:%M"), "server": info, "stub_model": STUB, "versions": versions()}
    (OUT / "validation_report.json").write_text(json.dumps({"meta": meta, "results": results}, indent=2, default=str),
                                                encoding="utf-8")
    write_md(meta, results)
    print(f"\nWrote {OUT / 'validation_report.md'}")


def write_md(meta, results):
    md = ["# Validation report: framework and ToT spikes", ""]
    if meta["stub_model"]:
        md += ["> **STUB RUN.** The model answers were canned (LRT_STUB_LLM=1). This tests the plumbing only.", ""]
    md += [f"- Run: {meta['timestamp']}", f"- Model server: {meta['server']}",
           "- " + ", ".join(f"{k} {v}" for k, v in meta["versions"].items()), "",
           "| Test | Result | Seconds |", "|---|---|---|"]
    md += [f"| {r['name']} | {'PASS' if r['passed'] else 'FAIL'} | {r['seconds']} |" for r in results]
    for r in results:
        md += ["", f"## {r['name']}: {'PASS' if r['passed'] else 'FAIL'}", ""]
        d = r["details"]
        if "runs" in d:
            for run in d["runs"]:
                md += [f"### Second reflow profile confirmed by the engineer: {'yes' if run['second_profile_confirmed'] else 'no'}", "",
                       f"- Outcome: **{run['outcome']}** in {run['seconds']} s; LLM calls {run['llm_calls']}; "
                       f"proposals {run['proposals']}; nodes in plan state {run['nodes_recorded_in_plan_state']}",
                       f"- Selected plan: `{json.dumps(run['selected_plan'])}`",
                       f"- Critic reason: {run['selected_reason']}",
                       f"- Runner-up: `{json.dumps(run['runner_up'])}`",
                       f"- Independent re-check of selected plan: {run.get('selected_plan_recheck')}", "",
                       "| Depth | Pruned plan | Reason |", "|---|---|---|"]
                for depth, key in ((1, "pruned_depth1"), (2, "pruned_depth2")):
                    md += [f"| {depth} | `{json.dumps(p['plan'])}` | {p['reason']} |" for p in run[key]]
                md += ["", "<details><summary>Raw model replies</summary>", ""]
                for c in run.get("raw_model_replies", []):
                    md += [f"**{c['call']}**", "", "```", c["reply"], "```", ""]
                md += ["</details>", ""]
        else:
            md += ["```json", json.dumps(d, indent=2, default=str)[:6000], "```"]
    (OUT / "validation_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

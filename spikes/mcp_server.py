#!/usr/bin/env python3
"""
MCP server for the Lab Request Assistant tools (runs in the MODEL venv: .venv,
because retrieval needs the embedding model). Clients start it over stdio.

Tools:
  retrieve_requirements(test_type, form_section)  semantic retrieval, filtered (Checkpoint 3.1 route)
  query_equipment(equipment_id)                  equipment database module (synthetic)
  find_equipment(query)                          lab equipment database: equipment for a test name or standard
  check_equipment(equipment_id, ...)             request conditions vs. equipment limits (problems / unknowns)
  validate_plan(plan, ...)                       hard checks from plan_rules.py
  add_branch / score_branch / prune_branch / list_branches   plan-state for ToT
Resource:
  plan://{run_id}                                 the whole tree of one ToT run, as JSON

Stub: LRT_STUB_EMBED=1 uses a hashing embedder instead of bge-base (plumbing tests only).
"""
import _offline  # noqa: F401  (no outbound traffic; see lrt_offline.py)
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(HERE))

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP  # noqa: E402
except ImportError:  # mcp 2.x renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP  # noqa: E402
import plan_rules  # noqa: E402
import equipment_db  # noqa: E402  (LRT_DATA=private for the real lab)

try:
    mcp = FastMCP("lrt-tools", log_level="WARNING")
except TypeError:  # newer mcp releases may not accept log_level here
    mcp = FastMCP("lrt-tools")
_retr = {}
_runs = {}

TEST_DESC = {"warpage_reflow": "warpage measurement during reflow simulation",
             "thermal_cycling": "thermal cycling exposure",
             "flatness_rt": "room-temperature flatness measurement"}
SCOPE = {"warpage_reflow": {"warpage_reflow", "preparation", "reporting"},
         "thermal_cycling": {"thermal_cycling", "preparation", "reporting"},
         "flatness_rt": {"flatness_rt"}}


def _encoder():
    if os.environ.get("LRT_STUB_EMBED") == "1":
        def enc(texts):
            out = []
            for t in texts:
                v = [0.0] * 256
                for w in re.findall(r"[a-z0-9]+", t.lower()):
                    v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1
                n = math.sqrt(sum(x * x for x in v)) or 1
                out.append([x / n for x in v])
            return out
        return enc, ""
    from sentence_transformers import SentenceTransformer
    import rag_demo as R
    m = SentenceTransformer(R.EMBED_MODEL, device="cpu")
    return (lambda texts: [list(map(float, x)) for x in m.encode(texts, normalize_embeddings=True)]), R.QUERY_PREFIX


def _retriever():
    if not _retr:
        import eval_retrieval as E
        import rag_demo as R
        enc, qprefix = _encoder()
        chunks = E.load_chunks("extended", "section")
        score, _ = E.dense_scorer(enc, qprefix, "", chunks)
        _retr.update(E=E, R=R, chunks=chunks, score=score)
    return _retr


@mcp.tool()
def retrieve_requirements(test_type: str, form_section: str = "") -> list:
    """Return the procedure passages for one test type. form_section is one of required_inputs,
    sample_preparation, sample_quantity, test_sequence, reporting; empty = all five sections.
    Only active documents in the test type's scope are searched (metadata filter)."""
    r = _retriever()
    if test_type not in TEST_DESC:
        return [{"error": f"unknown test_type {test_type}; use one of {sorted(TEST_DESC)}"}]
    sections = [form_section] if form_section else list(r["R"].FORM_SECTION_QUERIES)
    ids = r["E"].pool_ids(r["chunks"], SCOPE[test_type])
    out = []
    for s in sections:
        if s not in r["R"].FORM_SECTION_QUERIES:
            out.append({"error": f"unknown form_section {s}"})
            continue
        q = r["R"].FORM_SECTION_QUERIES[s].format(test=TEST_DESC[test_type])
        best = r["E"].topk(r["score"](q), ids, 1)[0]
        c = r["chunks"][best]
        out.append({"form_section": s, "doc_id": c["doc_id"], "revision": c["revision"],
                    "section": c["section"], "text": c["text"]})
    return out


@mcp.tool()
def query_equipment(equipment_id: str) -> dict:
    """Return the capabilities and limits of one instrument from the equipment database module."""
    rec = plan_rules.EQUIPMENT.get(equipment_id)
    return rec if rec else {"error": f"no equipment {equipment_id}; known: {[k for k in plan_rules.EQUIPMENT if not k.startswith('_')]}"}


@mcp.tool()
def find_equipment(query: str) -> dict:
    """Find the lab's test methods and equipment for a test name ("thermal shock"), a standard ("EIA 364-70")
    or a capability word. Returns counts, status (planned units are marked) and known limits."""
    return equipment_db.find(query)


@mcp.tool()
def check_equipment(equipment_id: str, temp_min_c: float = None, temp_max_c: float = None, force_n: float = None,
                    current_a: float = None, voltage_kv: float = None, frequency_hz: float = None) -> dict:
    """Check requested test conditions against one instrument's limits. 'problems' means the request does not fit;
    'unknown' means the database has no limit for it, so ask the lab instead of assuming it fits."""
    temp = None
    if temp_min_c is not None or temp_max_c is not None:
        temp = (temp_min_c if temp_min_c is not None else temp_max_c, temp_max_c if temp_max_c is not None else temp_min_c)
    return equipment_db.check(equipment_id, temp_c=temp, force_n=force_n, current_a=current_a,
                              voltage_kv=voltage_kv, frequency_hz=frequency_hz)


@mcp.tool()
def select_load_cell(expected_peak_n: float, frame: str = "INSTRON-1") -> dict:
    """Pick the smallest load cell on a universal testing frame whose usable range contains the expected peak force (N)."""
    return plan_rules.select_load_cell(expected_peak_n, frame)


@mcp.tool()
def validate_plan(plan: dict, available: int = 10, second_profile_confirmed: bool = False,
                  require_before_after: bool = True) -> dict:
    """Hard checks on a (partial) test plan: sample minimums, preconditioning before every thermal step,
    second reflow profile rule, before/after coverage. Returns {"valid": bool, "violations": [...]}."""
    return plan_rules.validate(plan, available, second_profile_confirmed, require_before_after)


@mcp.tool()
def add_branch(run_id: str, parent_id: str, depth: int, plan: dict, rationale: str = "") -> str:
    """Record a candidate node in a ToT run; returns its node id."""
    run = _runs.setdefault(run_id, {})
    nid = f"n{len(run) + 1}"
    run[nid] = {"id": nid, "parent": parent_id or None, "depth": depth, "plan": plan,
                "rationale": rationale, "score": None, "status": "open", "reason": ""}
    return nid


@mcp.tool()
def score_branch(run_id: str, node_id: str, score: float, reason: str = "") -> str:
    """Set the evaluator score of a node."""
    n = _runs[run_id][node_id]
    n["score"], n["reason"] = score, reason
    return "ok"


@mcp.tool()
def prune_branch(run_id: str, node_id: str, reason: str) -> str:
    """Mark a node as pruned, with the reason (a violated rule or a low score)."""
    n = _runs[run_id][node_id]
    n["status"], n["reason"] = "pruned", reason
    return "ok"


@mcp.tool()
def list_branches(run_id: str) -> list:
    """Return every node of a ToT run."""
    return list(_runs.get(run_id, {}).values())


@mcp.resource("plan://{run_id}")
def plan_tree(run_id: str) -> str:
    """The whole tree of one ToT run as JSON."""
    return json.dumps(list(_runs.get(run_id, {}).values()), indent=2)


if __name__ == "__main__":
    if "--check" in sys.argv:
        # Self-test without a client: load the rules and retrieval, print a summary, exit.
        import importlib.metadata as md
        r = retrieve_requirements("warpage_reflow", "sample_preparation")
        print(json.dumps({"mcp": md.version("mcp"), "python": sys.version.split()[0],
                          "retrieval": f"{r[0].get('doc_id')} / {r[0].get('section')}",
                          "equipment": bool(query_equipment("SM-1").get("max_c")),
                          "load_cell_for_3N": (select_load_cell(3.0)["selected"] or {}).get("id")}))
    else:
        mcp.run()

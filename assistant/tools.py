"""Tools the agents call. Same functions as the MCP server (spikes/mcp_server.py), called directly here so the
pipeline runs without an MCP client. Every call is logged to the run trace.

  retrieve(test_type, form_section)  procedure passages, active revisions of in-scope documents only (metadata filter)
  find_equipment / check_equipment   lab equipment database (equipment_db.py; LRT_DATA=private for the real lab)
  validate_plan                      hard rules in code (spikes/plan_rules.py)
  lookup_part                        parts directory
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "eval", ROOT / "spikes"):
    sys.path.insert(0, str(p))
import equipment_db  # noqa: E402
import plan_rules  # noqa: E402

TEST_DESC = {"warpage_reflow": "warpage measurement during reflow simulation",
             "thermal_cycling": "thermal cycling exposure",
             "flatness_rt": "room-temperature flatness measurement",
             "temperature_rise": "temperature rise versus current (current rating)",
             "llcr": "low-level contact resistance (LLCR)"}
# Document types searched for each test (the metadata filter from Checkpoint 3.1).
SCOPE = {"warpage_reflow": {"warpage_reflow", "preparation", "reporting"},
         "thermal_cycling": {"thermal_cycling", "preparation", "reporting"},
         "flatness_rt": {"flatness_rt", "reporting"},
         "temperature_rise": {"temperature_rise", "reporting"},
         "llcr": {"llcr", "reporting"}}
TEST_SHORT = {"warpage_reflow": "warpage (reflow)", "thermal_cycling": "thermal cycling", "flatness_rt": "flatness",
              "temperature_rise": "T-rise", "llcr": "LLCR"}


# Tests from the registry: their names and the document types searched for them.
def _add_registry():
    from assistant import registry
    for k, t in registry.BY_KEY.items():
        TEST_DESC.setdefault(k, t["name"])
        TEST_SHORT.setdefault(k, t.get("short", k))
        SCOPE.setdefault(k, {k, "reporting"})


_add_registry()
FORM_SECTIONS = {
    "required_inputs": "information the requester must provide before scheduling {test}",
    "sample_preparation": "sample preparation and preconditioning required before {test}",
    "sample_quantity": "minimum number of samples and sample identification for {test}",
    "test_sequence": "required order of test steps for {test}",
    "reporting": "required data, plots and files to report for {test}",
}
EQUIPMENT_QUERY = {"warpage_reflow": "warpage", "thermal_cycling": "thermal cycling", "flatness_rt": "warpage"}

_R = {}


def _retriever(trace):
    if not _R:
        import eval_retrieval as E
        chunks = E.load_chunks("extended", "section")
        kind = os.environ.get("LRT_RETRIEVER", "auto")
        score = None
        if kind in ("auto", "dense"):
            try:
                from sentence_transformers import SentenceTransformer
                import rag_demo as R
                m = SentenceTransformer(R.EMBED_MODEL, device="cpu")
                enc = lambda texts: [list(map(float, v)) for v in m.encode(texts, normalize_embeddings=True)]  # noqa: E731
                score, _ = E.dense_scorer(enc, R.QUERY_PREFIX, "", chunks)
                kind = "dense bge-base-en-v1.5"
            except Exception as e:  # embedding model not installed here: keyword baseline
                if kind == "dense":
                    raise
                trace.log("requirements", "note", text=f"dense retriever unavailable ({type(e).__name__}); using BM25 keyword retrieval")
        if score is None:
            score, _ = E.bm25_scorer(chunks)
            kind = "bm25"
        _R.update(E=E, chunks=chunks, score=score, kind=kind)
    return _R


def retrieve(test_type, form_section, trace):
    r = _retriever(trace)
    q = FORM_SECTIONS[form_section].format(test=TEST_DESC[test_type])
    ids = r["E"].pool_ids(r["chunks"], SCOPE[test_type])           # active, in-scope documents only
    best = r["E"].topk(r["score"](q), ids, 1)
    c = r["chunks"][best[0]] if best else None
    out = None if not c else {"form_section": form_section, "doc_id": c["doc_id"], "revision": c["revision"],
                              "status": c["status"], "section": c["section"], "text": c["text"]}
    trace.log("requirements", "tool_call", tool="retrieve", test_type=test_type, form_section=form_section,
              retriever=r["kind"], result=f"{out['doc_id']} Rev {out['revision']} / {out['section']}" if out else None)
    return out


def find_equipment(test_type, trace):
    r = equipment_db.find(EQUIPMENT_QUERY[test_type])
    avail = [e for e in r["equipment"] if e["status"] == "available"]
    trace.log("requirements", "tool_call", tool="find_equipment", test_type=test_type, found=[e["id"] for e in r["equipment"]])
    return avail


def check_equipment(equipment_id, trace, **req):
    r = equipment_db.check(equipment_id, **req)
    trace.log("reviewer", "tool_call", tool="check_equipment", equipment=equipment_id, request=req,
              fits=r.get("fits"), problems=r.get("problems"), unknown=r.get("unknown"))
    return r


def validate_plan(plan, trace, node="reviewer", **kw):
    r = plan_rules.validate(plan, **kw)
    trace.log(node, "tool_call", tool="validate_plan", plan=plan, valid=r["valid"], violations=r["violations"])
    return r


def parts_directory():
    for p in (ROOT / "data" / "private" / "parts" / "parts.json", ROOT / "data" / "synthetic" / "parts" / "parts.json"):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8")).get("parts", [])
    return []


def lookup_part(text, trace):
    """Part numbers in the request that are in the parts directory (exact match on the part number)."""
    found = []
    for p in parts_directory():
        if re.search(r"(?<![\w-])" + re.escape(p["part_number"]) + r"(?![\w-])", text, re.I):
            found.append(p)
    trace.log("coordinator", "tool_call", tool="lookup_part", found=[p["part_number"] for p in found])
    return found

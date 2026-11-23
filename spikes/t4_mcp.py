"""Test 4: MCP tools (retrieval, equipment, hard checks, plan state) called from LangChain."""
import _offline  # noqa: F401  (no outbound traffic; see lrt_offline.py)
import asyncio
import time

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from common import mcp_preflight, mcp_connection, parse_tool_output, result

NAME = "4. MCP server tools from LangChain (retrieval, equipment, hard checks, plan state)"

PLANS = {
    "one group, preconditioned once (what the linear drafts did)":
        ({"groups": [{"name": "A", "samples": 10, "steps": ["precondition", "warpage_reflow", "thermal_cycling", "warpage_reflow"]}]}, False),
    "two groups of 5, control and cycled":
        ({"groups": [{"name": "A", "samples": 5, "steps": ["precondition", "warpage_reflow"]},
                     {"name": "B", "samples": 5, "steps": ["precondition", "thermal_cycling", "precondition", "warpage_reflow"]}]}, True),
    "groups of 3 and 7":
        ({"groups": [{"name": "A", "samples": 3, "steps": ["precondition", "warpage_reflow"]},
                     {"name": "B", "samples": 7, "steps": ["precondition", "thermal_cycling", "precondition", "warpage_reflow"]}]}, False),
}


async def _run():
    client = MultiServerMCPClient({"lrt": mcp_connection()})
    async with client.session("lrt") as session:
        tools = {t.name: t for t in await load_mcp_tools(session)}
        checks, ok = {}, True
        for label, (plan, expect_valid) in PLANS.items():
            r = parse_tool_output(await tools["validate_plan"].ainvoke({"plan": plan}))
            checks[label] = r
            ok &= isinstance(r, dict) and r.get("valid") == expect_valid
        prep = parse_tool_output(await tools["retrieve_requirements"].ainvoke(
            {"test_type": "warpage_reflow", "form_section": "sample_preparation"}))
        prep = prep[0] if isinstance(prep, list) else prep
        eq = parse_tool_output(await tools["query_equipment"].ainvoke({"equipment_id": "SM-1"}))
        cell = parse_tool_output(await tools["select_load_cell"].ainvoke({"expected_peak_n": 3.0}))
        too_big = parse_tool_output(await tools["select_load_cell"].ainvoke({"expected_peak_n": 1000.0}))
        nid = parse_tool_output(await tools["add_branch"].ainvoke(
            {"run_id": "t4", "parent_id": "", "depth": 1, "plan": PLANS["groups of 3 and 7"][0]}))
        await tools["prune_branch"].ainvoke({"run_id": "t4", "node_id": nid, "reason": "sample minimum"})
        tree = parse_tool_output(await tools["list_branches"].ainvoke({"run_id": "t4"}))
        tree = tree if isinstance(tree, list) else [tree]
        ok &= isinstance(prep, dict) and "precondition" in prep.get("text", "").lower()
        ok &= isinstance(eq, dict) and eq.get("max_c") == 300
        ok &= (cell.get("selected") or {}).get("id") == "LC-500G" and too_big.get("selected") is None
        ok &= any(n.get("status") == "pruned" for n in tree if isinstance(n, dict))
        return ok, {"tools": sorted(tools), "validate_plan": checks,
                    "retrieved_for_sample_preparation": f"{prep.get('doc_id')} Rev {prep.get('revision')}, {prep.get('section')}" if isinstance(prep, dict) else prep,
                    "equipment_SM-1": eq, "load_cell_for_3N": cell, "load_cell_for_1000N": too_big, "plan_state_after_prune": tree}


def run():
    t0 = time.time()
    ok_pre, msg = mcp_preflight()
    if not ok_pre:
        return result(NAME, False, t0, preflight=msg)
    ok, details = asyncio.run(_run())
    return result(NAME, ok, t0, preflight=msg, **details)


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))

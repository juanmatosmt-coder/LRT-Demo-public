"""
Test 5: Tree-of-Thought beam search on the combined scenario (S5), end to end.

Controller: this Python loop with LangChain calls (thought generator and critic on the local Qwen).
Hard checks, retrieval and plan state: MCP tools (one persistent MCP session).
Depth 1 = sample allocation, depth 2 = step sequence per group (depth 3, timing, is not in this spike).
k = 3 proposals per node, beam b = 2, critic weights sure 20 / likely 1 / impossible 0.001.

Run twice: without and with the engineer's confirmation of a second reflow profile.
Pass = both runs select a plan that passes every hard check (this scenario has known valid plans,
so stopping with every branch pruned counts as a failure). The report records the tree, prunes,
timing and the raw model replies.
"""
import _offline  # noqa: F401  (no outbound traffic; see lrt_offline.py)
import asyncio
import json
import re
import time

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from common import mcp_preflight, BASE_URL, MODEL, REQUEST_S5, mcp_connection, parse_tool_output, result

NAME = "5. Tree-of-Thought beam search on the combined reflow + cycling request"
K, BEAM = 3, 2
WEIGHTS = {"sure": 20.0, "likely": 1.0, "impossible": 0.001}

ALLOC = ChatPromptTemplate.from_messages([
    ("system", "You plan laboratory reliability tests. Answer with JSON only."),
    ("user", "SAMPLE ALLOCATION OPTIONS\nEngineer request: {request}\nHousings available: 10.\n"
             "Engineer has confirmed a second reflow profile on the same samples: {confirmed}.\n"
             "Procedure passages:\n{rules}\n\n"
             "Propose {k} DIFFERENT ways to divide the housings into test groups.\n"
             "Answer with a JSON list of {k} options and nothing else. Format example (two options with made-up numbers):\n"
             '[{{"groups": [{{"name": "A", "samples": 8, "purpose": "measured group"}}], "rationale": "one group"}}, '
             '{{"groups": [{{"name": "A", "samples": 6, "purpose": "first group"}}, {{"name": "B", "samples": 6, "purpose": "second group"}}], "rationale": "two groups"}}]'),
])
SEQ = ChatPromptTemplate.from_messages([
    ("system", "You plan laboratory reliability tests. Answer with JSON only."),
    ("user", "STEP SEQUENCE OPTIONS\nEngineer request: {request}\n"
             "Engineer has confirmed a second reflow profile on the same samples: {confirmed}.\n"
             "Procedure passages:\n{rules}\n\nKeep these groups and sample counts exactly: {alloc}\n"
             "Allowed steps: precondition, warpage_reflow, thermal_cycling.\n"
             "Propose {k} DIFFERENT step orders for the groups.\n"
             "Answer with a JSON list of {k} options and nothing else. Each option repeats every group with its steps. "
             "Format example (made-up groups):\n"
             '[{{"groups": [{{"name": "A", "samples": 8, "steps": ["precondition", "thermal_cycling"]}}], "rationale": "short reason"}}]'),
])
CRITIC = ChatPromptTemplate.from_messages([
    ("system", "You review laboratory test plans. Answer with JSON only."),
    ("user", "RATE EACH CANDIDATE\nEngineer request: {request}\n"
             "Question: would this plan let the engineer compare warpage before and after thermal cycling, "
             "as the request asks? All candidates already pass the procedure rules.\n{candidates}\n\n"
             'Return only a JSON list: [{{"index": <n>, "verdict": "sure" | "likely" | "impossible", "reason": "<short>"}}]'),
])


def parse_json_any(text):
    """First JSON value in a model reply (code fences and prose around it ignored)."""
    text = re.sub(r"```(?:json)?", "", text or "")
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    for i in sorted(starts):
        try:
            return json.JSONDecoder().raw_decode(text[i:])[0]
        except json.JSONDecodeError:
            continue
    return None


def _lower(v):
    if isinstance(v, dict):
        return {str(k).lower(): _lower(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_lower(x) for x in v]
    return v


def _is_group(d):
    return isinstance(d, dict) and "groups" not in d and ("samples" in d or "steps" in d)


def _group(d):
    g = dict(d)
    try:
        g["samples"] = int(g.get("samples", 0))
    except (TypeError, ValueError):
        g["samples"] = 0
    return g


def normalize_options(value):
    """Accept the shapes a model plausibly returns and give a list of {"groups": [...], "rationale": str}."""
    v = _lower(value)
    if isinstance(v, dict):
        for key in ("options", "plans", "allocations", "candidates", "proposals"):
            if isinstance(v.get(key), list):
                return normalize_options(v[key])
        return normalize_options([v])
    if not isinstance(v, list):
        return []
    if v and all(_is_group(x) for x in v):          # a flat list of groups = one option
        return [{"groups": [_group(x) for x in v], "rationale": ""}]
    out = []
    for item in v:
        if isinstance(item, dict):
            groups = next((item[k] for k in ("groups", "allocation", "plan", "sample_groups") if isinstance(item.get(k), list)), None)
            if groups and all(_is_group(g) for g in groups):
                out.append({"groups": [_group(g) for g in groups], "rationale": str(item.get("rationale", ""))})
        elif isinstance(item, list) and item and all(_is_group(g) for g in item):
            out.append({"groups": [_group(g) for g in item], "rationale": ""})
    return out


def parse_json_list(text):
    v = parse_json_any(text)
    v = _lower(v)
    if isinstance(v, dict):
        v = next((v[k] for k in ("ratings", "verdicts", "candidates", "results") if isinstance(v.get(k), list)), [v])
    return v if isinstance(v, list) else []


async def tot_run(llm, tools, confirmed, run_id):
    calls, t0 = {"generator": 0, "critic": 0}, time.time()
    rules = []
    for tt, sec in (("warpage_reflow", "sample_quantity"), ("warpage_reflow", "test_sequence"),
                    ("thermal_cycling", "sample_preparation"), ("warpage_reflow", "sample_preparation")):
        p = parse_tool_output(await tools["retrieve_requirements"].ainvoke({"test_type": tt, "form_section": sec}))
        p = p[0] if isinstance(p, list) else p
        rules.append(f"[{p['doc_id']} Rev {p['revision']}, {p['section']}] {p['text'].split(chr(10), 1)[-1]}")
    rules_txt = "\n".join(rules)
    base = {"request": REQUEST_S5, "confirmed": "yes" if confirmed else "no", "rules": rules_txt, "k": K}

    raw_log = []

    async def ask(prompt, kind, **kw):
        calls[kind] += 1
        msgs = prompt.format_messages(**{**base, **kw})
        reply = (await llm.ainvoke(msgs)).content
        raw_log.append({"call": kind, "reply": reply[:1500]})
        if kind == "critic":
            return parse_json_list(reply)
        opts = normalize_options(parse_json_any(reply))
        if not opts:  # one retry with a format reminder
            calls[kind] += 1
            msgs += [AIMessage(content=reply), HumanMessage(content="That answer could not be read as the requested "
                     "JSON. Reply again with only the JSON list of options, in exactly the example format.")]
            reply = (await llm.ainvoke(msgs)).content
            raw_log.append({"call": kind + " (retry)", "reply": reply[:1500]})
            opts = normalize_options(parse_json_any(reply))
        return opts

    async def evaluate(cands, depth, parent):
        """Hard checks (MCP) prune; critic (Qwen) scores survivors; keep top BEAM."""
        survivors, pruned = [], []
        for c in cands:
            plan = {"groups": c.get("groups", [])}
            nid = parse_tool_output(await tools["add_branch"].ainvoke(
                {"run_id": run_id, "parent_id": parent, "depth": depth, "plan": plan, "rationale": c.get("rationale", "")}))
            chk = parse_tool_output(await tools["validate_plan"].ainvoke(
                {"plan": plan, "second_profile_confirmed": confirmed, "require_before_after": depth == 2}))
            if chk.get("valid"):
                survivors.append((nid, plan))
            else:
                reason = "; ".join(chk.get("violations", []))
                pruned.append({"node": nid, "plan": plan, "reason": reason})
                await tools["prune_branch"].ainvoke({"run_id": run_id, "node_id": nid, "reason": reason})
        if not survivors:
            return [], pruned
        listing = "\n".join(f"Candidate {i}: {json.dumps(p)}" for i, (_, p) in enumerate(survivors))
        verdicts = {}
        for v in await ask(CRITIC, "critic", candidates=listing):
            if isinstance(v, dict):
                try:
                    verdicts[int(v.get("index"))] = v
                except (TypeError, ValueError):
                    pass
        scored = []
        for i, (nid, plan) in enumerate(survivors):
            v = verdicts.get(i, {"verdict": "likely", "reason": "critic reply missing: kept as likely"})
            s = WEIGHTS.get(str(v.get("verdict")).lower(), 1.0)
            n_samples = sum(int(g.get("samples", 0)) for g in plan["groups"])
            n_steps = sum(len(g.get("steps", [])) for g in plan["groups"])
            scored.append((s, -n_samples, -n_steps, nid, plan, v.get("reason", "")))
            await tools["score_branch"].ainvoke({"run_id": run_id, "node_id": nid, "score": s, "reason": v.get("reason", "")})
        scored.sort(key=lambda x: x[:3], reverse=True)
        for s in scored[BEAM:]:
            await tools["prune_branch"].ainvoke({"run_id": run_id, "node_id": s[3], "reason": "outside beam"})
            pruned.append({"node": s[3], "plan": s[4], "reason": f"outside beam (critic: {s[0]})"})
        scored = [s for s in scored if s[0] > WEIGHTS["impossible"]]
        return scored[:BEAM], pruned

    allocs = (await ask(ALLOC, "generator"))[:K]
    beam, pruned1 = await evaluate(allocs, 1, "")
    final, pruned2, n2 = [], [], 0
    for s in beam:
        seqs = (await ask(SEQ, "generator", alloc=json.dumps(s[4])))[:K]
        n2 += len(seqs)
        kept, pr = await evaluate(seqs, 2, s[3])
        final += kept
        pruned2 += pr
    final.sort(key=lambda x: x[:3], reverse=True)
    best = final[0] if final else None
    tree = parse_tool_output(await tools["list_branches"].ainvoke({"run_id": run_id}))
    return {
        "second_profile_confirmed": confirmed,
        "outcome": "plan selected" if best else "stopped: every branch pruned, ask the engineer",
        "selected_plan": best[4] if best else None,
        "selected_reason": best[5] if best else None,
        "runner_up": final[1][4] if len(final) > 1 else None,
        "proposals": {"depth1": len(allocs), "depth2": n2},
        "pruned_depth1": pruned1, "pruned_depth2": pruned2,
        "llm_calls": calls, "seconds": round(time.time() - t0, 1),
        "nodes_recorded_in_plan_state": len(tree) if isinstance(tree, list) else None,
        "raw_model_replies": raw_log,
    }


async def _run():
    llm = ChatOpenAI(model=MODEL, base_url=BASE_URL, api_key="local", temperature=0, max_tokens=900)
    client = MultiServerMCPClient({"lrt": mcp_connection()})
    async with client.session("lrt") as session:
        tools = {t.name: t for t in await load_mcp_tools(session)}
        runs = [await tot_run(llm, tools, False, "s5-no-confirm"), await tot_run(llm, tools, True, "s5-confirmed")]
    for r in runs:
        if r["selected_plan"]:
            # independent re-check of the selected plan with the same rules
            import sys
            sys.path.insert(0, __file__.rsplit("t5_tot.py", 1)[0])
            import plan_rules
            r["selected_plan_recheck"] = plan_rules.validate(r["selected_plan"], 10, r["second_profile_confirmed"])
    # This scenario has known valid plans in both runs, so "no plan found" is a failure.
    ok = all(r["selected_plan"] and r["selected_plan_recheck"]["valid"] for r in runs)
    return ok, runs


def run():
    t0 = time.time()
    ok_pre, msg = mcp_preflight()
    if not ok_pre:
        return result(NAME, False, t0, preflight=msg)
    ok, runs = asyncio.run(_run())
    return result(NAME, ok, t0, preflight=msg, runs=runs)


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))

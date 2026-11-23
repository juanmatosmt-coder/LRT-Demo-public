"""
Canned responses used only when LRT_STUB_LLM=1, to test the plumbing (server, LangChain,
CrewAI, MCP, ToT loop) without the real model. Results from stub runs prove nothing about
Qwen; run_all.py labels them as stub runs.
"""
import json
import re


def _text(m):
    c = m.get("content")
    return c if isinstance(c, str) else " ".join(p.get("text", "") for p in (c or []) if isinstance(p, dict))


def respond(messages):
    last = _text(messages[-1]) if messages else ""
    allp = " ".join(_text(m) for m in messages)
    if "Reply with exactly: OK" in last:
        return "OK"
    if "Count from 1 to 10" in last:
        return "1, 2, 3, 4, 5, 6, 7, 8, 9, 10"
    if "SAMPLE ALLOCATION OPTIONS" in allp:
        return json.dumps([
            {"groups": [{"name": "A", "samples": 10, "purpose": "measure, cycle, measure again"}], "rationale": "paired before/after on the same parts"},
            {"groups": [{"name": "A", "samples": 5, "purpose": "baseline warpage"}, {"name": "B", "samples": 5, "purpose": "cycle then measure"}], "rationale": "avoids a second profile on the same parts"},
            {"groups": [{"name": "A", "samples": 3, "purpose": "baseline"}, {"name": "B", "samples": 7, "purpose": "cycled"}], "rationale": "more cycled parts"}])
    if "STEP SEQUENCE OPTIONS" in allp:
        if '"samples": 10' in last:
            return json.dumps([
                {"groups": [{"name": "A", "samples": 10, "steps": ["precondition", "warpage_reflow", "thermal_cycling", "warpage_reflow"]}], "rationale": "simple"},
                {"groups": [{"name": "A", "samples": 10, "steps": ["precondition", "warpage_reflow", "precondition", "thermal_cycling", "precondition", "warpage_reflow"]}], "rationale": "precondition before each thermal step"},
                {"groups": [{"name": "A", "samples": 10, "steps": ["precondition", "thermal_cycling", "precondition", "warpage_reflow"]}], "rationale": "after only"}])
        return json.dumps([
            {"groups": [{"name": "A", "samples": 5, "steps": ["precondition", "warpage_reflow"]}, {"name": "B", "samples": 5, "steps": ["precondition", "thermal_cycling", "precondition", "warpage_reflow"]}], "rationale": "control group and cycled group"},
            {"groups": [{"name": "A", "samples": 5, "steps": ["warpage_reflow"]}, {"name": "B", "samples": 5, "steps": ["thermal_cycling", "warpage_reflow"]}], "rationale": "no preconditioning"},
            {"groups": [{"name": "A", "samples": 5, "steps": ["precondition", "warpage_reflow"]}, {"name": "B", "samples": 5, "steps": ["precondition", "thermal_cycling"]}], "rationale": "no after measurement"}])
    if "RATE EACH CANDIDATE" in allp:
        n = len(re.findall(r"Candidate \d+", last))
        return json.dumps([{"index": i, "verdict": "sure" if i == 0 else "likely", "reason": "stub"} for i in range(n)])
    if "Return only JSON" in last and "test_type" in last:
        return json.dumps({"test_type": "warpage_reflow", "samples": 10, "missing": ["thermal profile"]})
    return "Thought: I now know the final answer\nFinal Answer: Option 1: one group of 10 measured before and after cycling. Option 2: two groups of 5 (control and cycled). Reviewer: option 2 avoids a second reflow profile on the same samples."

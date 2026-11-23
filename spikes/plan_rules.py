"""
Hard checks for a proposed test plan (deterministic, no LLM).

Each rule is taken from the synthetic procedures in docs/ and cites its source, so a
violation can be explained to the engineer. A plan is:
  {"groups": [{"name": "A", "samples": 5, "steps": ["precondition", "warpage_reflow"]}, ...]}
"steps" may be missing for a partial plan (sample allocation only, ToT depth 1).
"""
import json
import os
from pathlib import Path

STEPS = {"precondition", "warpage_reflow", "thermal_cycling"}
THERMAL = {"warpage_reflow", "thermal_cycling"}
MIN_PER_CONDITION = 5  # SYN-TM-101 Rev C, Sample quantity
# LRT_DATA=private reads data/private/ (gitignored, real data); default is data/synthetic/.
DATA_DIR = Path(__file__).resolve().parents[1] / "data" / os.environ.get("LRT_DATA", "synthetic")
EQUIPMENT = json.loads((DATA_DIR / "equipment" / "equipment.json").read_text(encoding="utf-8"))


def select_load_cell(expected_peak_n, frame="INSTRON-1"):
    """Smallest load cell whose usable range (default 10-90 % of capacity) contains the expected peak force."""
    lo, hi = EQUIPMENT.get("_rules", {}).get("load_cell_usable_range_pct_of_capacity", [10, 90])
    cells = sorted(EQUIPMENT[frame]["load_cells"], key=lambda c: c["capacity_n"])
    for c in cells:
        if c["capacity_n"] * lo / 100 <= expected_peak_n <= c["capacity_n"] * hi / 100:
            return {"selected": c, "rule": f"expected peak within {lo}-{hi} % of capacity"}
    return {"selected": None, "rule": f"expected peak within {lo}-{hi} % of capacity",
            "problem": f"no load cell on {frame} fits {expected_peak_n} N; range "
                       f"{cells[0]['capacity_n'] * lo / 100:.3f}-{cells[-1]['capacity_n'] * hi / 100:.1f} N"}


def validate(plan, available=10, second_profile_confirmed=False, require_before_after=True,
             reflow_profile=None, cycling_profile=None):
    v = []
    groups = plan.get("groups") if isinstance(plan, dict) else None
    if not groups:
        return {"valid": False, "violations": ["Plan has no groups"]}
    total = sum(int(g.get("samples", 0)) for g in groups)
    if total > available:
        v.append(f"Uses {total} samples but only {available} are available")
    for g in groups:
        name, n = g.get("name", "?"), int(g.get("samples", 0))
        if n < MIN_PER_CONDITION:
            v.append(f"SYN-TM-101 Sample quantity: group {name} has {n} samples, minimum is {MIN_PER_CONDITION} per test condition")
        steps = g.get("steps")
        if steps is None:
            continue
        unknown = [s for s in steps if s not in STEPS]
        if unknown:
            v.append(f"Group {name}: unknown steps {unknown}")
        conditioned = False
        for i, s in enumerate(steps):
            if s == "precondition":
                conditioned = True
            elif s in THERMAL:
                if not conditioned:
                    v.append(f"SYN-PR-201 / SYN-TM-101 / SYN-TM-110: group {name} step {i + 1} ({s}) is not preceded by preconditioning since the last thermal step")
                conditioned = False
        if steps.count("warpage_reflow") > 1 and not second_profile_confirmed:
            v.append(f"SYN-TM-101 Test sequence: group {name} runs a second reflow profile on the same samples without the engineer's confirmation")
    if require_before_after and all(g.get("steps") is not None for g in groups):
        before = any("warpage_reflow" in g["steps"] and ("thermal_cycling" not in g["steps"]
                     or g["steps"].index("warpage_reflow") < g["steps"].index("thermal_cycling")) for g in groups)
        after = any("thermal_cycling" in g["steps"] and "warpage_reflow" in g["steps"][g["steps"].index("thermal_cycling"):]
                    for g in groups)
        if not (before and after):
            v.append("Objective: the plan needs a warpage measurement before cycling and one after cycling")
    if reflow_profile:
        eq = EQUIPMENT["SM-1"]
        if reflow_profile.get("peak_c", 0) > eq["max_c"]:
            v.append(f"Equipment SM-1: peak {reflow_profile['peak_c']} C exceeds chamber limit {eq['max_c']} C")
        if reflow_profile.get("ramp_c_per_s", 0) > eq["max_ramp_c_per_s"]:
            v.append(f"Equipment SM-1: ramp {reflow_profile['ramp_c_per_s']} C/s exceeds limit {eq['max_ramp_c_per_s']} C/s")
    if cycling_profile:
        eq = EQUIPMENT["TC-2"]
        if cycling_profile.get("min_c", 0) < eq["min_c"] or cycling_profile.get("max_c", 0) > eq["max_c"]:
            v.append(f"Equipment TC-2: cycling range outside {eq['min_c']} to {eq['max_c']} C")
    return {"valid": not v, "violations": v}

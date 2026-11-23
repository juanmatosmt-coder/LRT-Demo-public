#!/usr/bin/env python3
r"""
Lab equipment database: load, check, search, and compare a request against equipment limits.

Data: data/<LRT_DATA>/equipment/lab_equipment.json   (LRT_DATA=private for the real lab, default synthetic)
Schema: data/templates/equipment_record_template.json

  python equipment_db.py summary                       counts by area, planned units, open gaps
  python equipment_db.py find "thermal shock"          test methods and equipment for a test name or standard
  python equipment_db.py find "EIA 364-70"
  python equipment_db.py check VG-ENV-TS --temp -65 150
  python equipment_db.py check VG-MECH-UTM --force-n 5000
  python equipment_db.py gaps                          every field still marked unknown (questions for the lab)
  python equipment_db.py validate                      schema and cross-reference checks

The same functions are MCP tools in spikes/mcp_server.py (find_equipment, check_equipment).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AREAS = {"mechanical", "electrical", "environmental", "analytical", "solderability", "metrology", "process"}


def path(which=None) -> Path:
    return ROOT / "data" / (which or os.environ.get("LRT_DATA", "synthetic")) / "equipment" / "lab_equipment.json"


def load(which=None) -> dict:
    return json.loads(path(which).read_text(encoding="utf-8"))


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def _std_key(s) -> str:
    """'EIA 364-32 (Method A)' and 'eia-364-32' both become 'eia 364 32'."""
    return _norm(re.sub(r"\(.*?\)", "", str(s)))


def find(query: str, db=None) -> dict:
    """Test methods and equipment matching a test name, a standard number, or a capability word."""
    db = db or load()
    q = _norm(query)
    qs = _std_key(query)
    words = [w for w in q.split() if len(w) > 2]
    by_id = {e["id"]: e for e in db["equipment"]}

    def hit(text):
        t = _norm(text)
        return q in t or (words and all(w in t for w in words))

    std_hit = lambda s: bool(qs) and (_std_key(s) == qs or _std_key(s).startswith(qs + " "))
    methods = [m for m in db["test_methods"] if hit(m["name"]) or any(std_hit(s) for s in m["standards"])]
    ids = {i for m in methods for i in m["equipment"]}
    ids |= {e["id"] for e in db["equipment"]
            if hit(e["name"]) or any(hit(c) for c in e.get("capabilities", [])) or any(std_hit(s) for s in e.get("standards", []))}
    equipment = [{k: by_id[i].get(k) for k in ("id", "name", "area", "count", "model", "status", "limits", "unknown")} for i in sorted(ids)]
    return {"query": query, "lab": db["lab"]["name"], "test_methods": methods, "equipment": equipment,
            "note": "No match: the lab may not offer this test, or it is listed under another name." if not methods and not equipment else ""}


# Request keys and the limit keys they are checked against.
CHECKS = {
    "temp_c": ("temp_min_c", "temp_max_c"),
    "force_n": (None, "load_cell_capacity_max_n"),
    "current_a": (None, "current_max_a"),
    "voltage_kv": (None, "voltage_max_kv"),
    "frequency_hz": (None, "frequency_max_hz"),
    "sine_accel_gpk": (None, "sine_accel_max_gpk"),
    "random_accel_grms": (None, "random_accel_max_grms"),
    "rh_pct": ("rh_min_pct", "rh_max_pct"),
    "sample_mm": (None, "sample_max_mm"),
}


LABELS = {"temp_c": ("Temperature", "°C"), "force_n": ("Force", "N"), "current_a": ("Current", "A"), "voltage_kv": ("Voltage", "kV"),
          "frequency_hz": ("Frequency", "Hz"), "sine_accel_gpk": ("Sine acceleration", "gpk"), "random_accel_grms": ("Random acceleration", "grms"),
          "rh_pct": ("Relative humidity", "%"), "sample_mm": ("Sample size", "mm")}


def _fmt(v):
    return "{:g}".format(v) if isinstance(v, (int, float)) else str(v)


def check(equipment_id: str, db=None, **req) -> dict:
    """Compare requested conditions with one instrument's limits.
    req: temp_c=(lo, hi) or a number, force_n, current_a, voltage_kv, frequency_hz, sine_accel_gpk, random_accel_grms, rh_pct, sample_mm.
    Returns ok / problems / unknown. 'unknown' means the database has no limit for it: ask the lab, do not assume."""
    db = db or load()
    e = next((x for x in db["equipment"] if x["id"] == equipment_id), None)
    if not e:
        return {"error": f"no equipment {equipment_id}", "known": [x["id"] for x in db["equipment"]]}
    L = dict(e.get("limits", {}))
    # Two-zone thermal shock: the reachable range runs from the cold zone minimum to the hot zone maximum.
    if "cold_zone_c" in L and "hot_zone_c" in L:
        L.setdefault("temp_min_c", L["cold_zone_c"][0])
        L.setdefault("temp_max_c", L["hot_zone_c"][1])
    if "temp_max_c_by_unit" in L:
        L.setdefault("temp_max_c", max(L["temp_max_c_by_unit"]))
    problems, unknown, ok = [], [], []
    for key, val in req.items():
        if val is None:
            continue
        if key not in CHECKS:
            unknown.append(f"{key}: not a known check")
            continue
        lo_key, hi_key = CHECKS[key]
        name, unit = LABELS.get(key, (key, ""))
        lo_v, hi_v = (val if isinstance(val, (list, tuple)) else (val, val))
        lo_lim, hi_lim = L.get(lo_key) if lo_key else None, L.get(hi_key)
        if (lo_key and lo_lim is None) or hi_lim is None:
            unknown.append(f"{name}: the database has no {'range' if lo_key else 'maximum'} for {equipment_id}")
        if lo_lim is not None and lo_v < lo_lim:
            problems.append(f"{name} {_fmt(lo_v)} {unit} is below the minimum of {_fmt(lo_lim)} {unit}")
        if hi_lim is not None and hi_v > hi_lim:
            problems.append(f"{name} {_fmt(hi_v)} {unit} is above the maximum of {_fmt(hi_lim)} {unit}")
        if not any(p.startswith(name + " ") for p in problems) and hi_lim is not None and (not lo_key or lo_lim is not None):
            shown = f"{_fmt(lo_v)} to {_fmt(hi_v)}" if lo_v != hi_v else _fmt(hi_v)
            ok.append(f"{name} {shown} {unit} is within limits ({_fmt(lo_lim) + ' to ' if lo_key else 'max '}{_fmt(hi_lim)} {unit})")
    if e["status"] != "available":
        problems.append(f"status is '{e['status']}'")
    return {"equipment": equipment_id, "name": e["name"], "status": e["status"], "count": e.get("count"),
            "fits": not problems and not unknown, "problems": problems, "unknown": unknown, "ok": ok}


def gaps(db=None) -> list:
    db = db or load()
    return [{"id": e["id"], "name": e["name"], "missing": e["unknown"]} for e in db["equipment"] if e.get("unknown")]


def summary(db=None) -> dict:
    db = db or load()
    areas = {}
    for e in db["equipment"]:
        a = areas.setdefault(e["area"], {"records": 0, "units": 0})
        a["records"] += 1
        a["units"] += e["count"] or 0
    return {"lab": db["lab"], "records": len(db["equipment"]), "areas": areas,
            "planned": [f"{e['id']} ({e['status']})" for e in db["equipment"] if e["status"] != "available"],
            "test_methods": len(db["test_methods"]), "open_gaps": sum(len(e.get("unknown", [])) for e in db["equipment"])}


def validate(db=None) -> list:
    db = db or load()
    errs, ids = [], set()
    tests = {m["id"] for m in db["test_methods"]}
    for e in db["equipment"]:
        for k in ("id", "name", "area", "status", "limits"):
            if k not in e:
                errs.append(f"{e.get('id', '?')}: missing {k}")
        if e["id"] in ids:
            errs.append(f"{e['id']}: duplicate id")
        ids.add(e["id"])
        if e.get("area") not in AREAS:
            errs.append(f"{e['id']}: area '{e.get('area')}' not in {sorted(AREAS)}")
        for t in e.get("tests", []):
            if t not in tests:
                errs.append(f"{e['id']}: test {t} not in test_methods")
        for k, v in e.get("limits", {}).items():
            if k.endswith(("_c", "_pct")) and isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v) and v[0] > v[1]:
                errs.append(f"{e['id']}: limit {k} has min > max")
    for m in db["test_methods"]:
        for i in m["equipment"]:
            if i not in ids:
                errs.append(f"{m['id']}: equipment {i} not in equipment list")
        if not m["equipment"]:
            errs.append(f"{m['id']} {m['name']}: no equipment listed")
    return errs


def main():
    ap = argparse.ArgumentParser(description="Lab equipment database")
    ap.add_argument("--data", help="synthetic (default) or private")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("summary"); sub.add_parser("gaps"); sub.add_parser("validate")
    f = sub.add_parser("find"); f.add_argument("query")
    c = sub.add_parser("check"); c.add_argument("equipment_id")
    c.add_argument("--temp", nargs="+", type=float, help="one value or min max, deg C")
    for k in ("force-n", "current-a", "voltage-kv", "frequency-hz", "sine-accel-gpk", "random-accel-grms", "sample-mm"):
        c.add_argument("--" + k, type=float)
    a = ap.parse_args()
    db = load(a.data)
    if a.cmd == "summary":
        out = summary(db)
    elif a.cmd == "gaps":
        out = gaps(db)
    elif a.cmd == "validate":
        out = validate(db) or "OK: no problems found"
    elif a.cmd == "find":
        out = find(a.query, db)
    else:
        req = {k.replace("-", "_"): getattr(a, k.replace("-", "_")) for k in ("force-n", "current-a", "voltage-kv", "frequency-hz", "sine-accel-gpk", "random-accel-grms", "sample-mm")}
        if a.temp:
            req["temp_c"] = tuple(a.temp) if len(a.temp) == 2 else a.temp[0]
        out = check(a.equipment_id, db, **req)
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())

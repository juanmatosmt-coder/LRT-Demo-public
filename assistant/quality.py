"""Quality flags for a lab request draft (typed by the engineer or filled by the assistant).

Each flag points at a field and says what is wrong, why it matters (with its source), and how to fix it:
  error  the lab cannot schedule the request as written (missing required input, obsolete spec, too few samples,
         a condition outside the equipment limits)
  warn   likely to cause a question back from the lab, a delay, or results that cannot be compared
  info   what high-quality past requests also state (from the example library)

The checks are deterministic: they use the procedure library, the equipment database, the parts directory and the
form schema, so the same draft always gets the same flags and every flag can be traced to its rule.
  python -m assistant.quality data/synthetic/lab_requests/EX-01.json
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import equipment_db  # noqa: E402
from assistant import guardrails as G  # noqa: E402

SCHEMA = json.loads((ROOT / "data" / "templates" / "lab_request_forms.json").read_text(encoding="utf-8"))
LEAD_TIME_WORKDAYS = 10        # synthetic lab rule: requests need two working weeks
SHOP_LEAD_TIME_WORKDAYS = 5    # synthetic machine shop rule
APPROVAL_LIMIT_USD = 5000      # synthetic purchasing rule: second approval above this


def _int(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0
MIN_SAMPLES = {"warpage_reflow": (5, "SYN-TM-101 Rev C, Sample quantity: minimum 5 per test condition"),
               "flatness_rt": (10, "SYN-TM-104 Rev A, Sample quantity: minimum 10 per lot"),
               "temperature_rise": (3, "SYN-TM-120 Rev A, Sample quantity: at least 3 mated samples per configuration (fewer need a reason)"),
               "llcr": (3, "SYN-TM-130 Rev A, Sample quantity: at least 3 mated samples per configuration (fewer need a reason)")}
PROCEDURE = {"warpage_reflow": "SYN-TM-101", "thermal_cycling": "SYN-TM-110", "flatness_rt": "SYN-TM-104",
             "temperature_rise": "SYN-TM-120", "llcr": "SYN-TM-130"}
ELEVATED = {"warpage_reflow", "thermal_cycling"}


def _add_registry():
    from assistant import registry
    for k, t in registry.BY_KEY.items():
        PROCEDURE.setdefault(k, t["doc_id"])
        if t.get("min_samples"):
            MIN_SAMPLES.setdefault(k, (t["min_samples"], f"{registry.source(k)}, Sample quantity: at least {t['min_samples']} per configuration (fewer need a reason)"))


_add_registry()


def _library():
    lib = {}
    for d in (ROOT / "docs", ROOT / "docs_extended"):
        for p in d.glob("*.md"):
            head = p.read_text(encoding="utf-8").split("---")[1]
            meta = dict(line.split(":", 1) for line in head.strip().splitlines() if ":" in line)
            meta = {k.strip(): v.strip() for k, v in meta.items()}
            lib.setdefault(meta["doc_id"], {})[meta["revision"]] = {"status": meta["status"], "title": meta["title"]}
    return lib


LIB = _library()


def current_rev(doc_id):
    revs = [r for r, m in LIB.get(doc_id, {}).items() if m["status"] == "active"]
    return revs[0] if revs else None


def _expand(fields):
    return [f for x in (fields or []) for f in (SCHEMA["common_steps"][x[1:]] if isinstance(x, str) else [x])]


def _table(step):
    t = step.get("table")
    return SCHEMA["common_steps"][t[1:]] if isinstance(t, str) else t


def review(form_key, fields, today=None):
    form = SCHEMA["forms"][form_key]
    today = today or dt.date.today()
    flags = []

    def flag(sev, field, step, message, why, fix=None, source=None, row=None):
        flags.append({"id": f"F{len(flags) + 1:02d}", "severity": sev, "field": field, "row": row, "step": step,
                      "message": message, "why": why, "fix": fix, "source": source})

    steps = {s["n"]: s for s in form["steps"]}
    rows = {n: fields.get(f"step{n}_rows") or [] for n in steps}
    test_step = next((n for n, s in steps.items() if (_table(s) or {}).get("columns") and any(c["key"] == "testsToBePerformed" for c in _table(s)["columns"])), None)
    sample_step = next((n for n, s in steps.items() if (_table(s) or {}).get("columns") and any(c["key"] == "quantity" for c in _table(s)["columns"])), None)
    tests_text = " ".join(f"{r.get('testsToBePerformed', '')} {r.get('applicableSpecifications', '')}" for r in rows.get(test_step, []))
    info = str(fields.get("additionalInformation", ""))
    extra = " ".join(f"{r.get('resinInformation', '')} {r.get('additionalInformation', '')}" for n in steps for r in rows[n] if "resinInformation" in r)
    attached = " ".join(str(x.get("name", "")) for x in (fields.get("attachments") or []) if isinstance(x, dict))
    all_text = f"{tests_text}\n{info}\n{extra}\nattachments: {attached}"
    found, out_of_scope = G.detect_tests(all_text)
    if form_key == "smt_lab_test_request" and any(rows[n] for n, s_ in steps.items() if "warpage" in s_["title"].lower()):
        found.add("warpage_reflow")      # dynamic warpage items are warpage-during-reflow measurements
    if form_key in ("machine_shop_request", "purchase_requisition"):
        found, out_of_scope = set(), []  # not lab tests

    def row_with(rx):
        """Index of the first test item whose text matches, so a flag lands on the item it is about."""
        for i, r in enumerate(rows.get(test_step, [])):
            if re.search(rx, f"{r.get('testsToBePerformed', '')} {r.get('applicableSpecifications', '')} {r.get('specificationRevision', '')}", re.I):
                return i
        return None
    values = G.parse_values(all_text)

    item = "Line" if form_key == "purchase_requisition" else "Item"

    # 1. Required fields and rows (the form itself)
    for n, s in steps.items():
        for f in _expand(s.get("fields")):
            if f.get("required") and f["type"] != "file" and not str(fields.get(f["key"], "")).strip():
                if f["key"] == "sendCopiesTo":
                    # The requester always gets the report: the form needs at least their own address here.
                    own = str(fields.get("email", "")).strip()
                    flag("info", f["key"], n, "Reports go to you by default" + (f" ({own})" if own else "") + "; add others here if they need a copy.",
                         "The form needs at least one address; the requester's own email is used when this is left empty.",
                         "Leave it to use your own email, or add up to 4 more.", "Request form")
                    continue
                flag("error", f["key"], n, f"{f['label']} is empty.", "Required by the request form.", f"Fill in {f['label']}.", "Request form")
        t = _table(s)
        if t:
            if len(rows[n]) < t.get("min_rows", 0):
                flag("error", None, n, f"{s['title']}: add at least {t['min_rows']} item.", "Required by the request form.", source="Request form")
            for i, r in enumerate(rows[n]):
                for c in t["columns"]:
                    if c.get("required") and not str(r.get(c["key"], "")).strip():
                        flag("error", c["key"], n, f"{item} {i + 1}: {c['label']} is empty.", "Required by the request form.", source="Request form", row=i)

    # 2. Cited procedures: current revision, cited at all
    cited = {}
    for i, r in enumerate(rows.get(test_step, [])):
        text = f"{r.get('applicableSpecifications', '')} {r.get('specificationRevision', '')}"
        for doc, rev in re.findall(r"(SYN-[A-Z]{2}-\d{3})(?:\s*Rev\.?\s*([A-Z]))?", text):
            cited.setdefault(doc, set()).add(rev)
            cur = current_rev(doc)
            if doc not in LIB:
                flag("info", "applicableSpecifications", test_step, f"Item {i + 1}: {doc} is not in the procedure library.",
                     "The assistant cannot check requirements it does not have.", "Check the document number, or attach the document.", "Procedure library", i)
            elif rev and LIB[doc].get(rev, {}).get("status") != "active":
                flag("error", "specificationRevision", test_step, f"Item {i + 1}: {doc} Rev {rev} is obsolete.",
                     f"The current revision is Rev {cur}; obsolete revisions have different requirements.", f"Cite {doc} Rev {cur}.", f"{doc} Rev {cur}", i)
    for doc in sorted(d for d, revs in cited.items() if revs == {""}):
        if doc in LIB:
            i = next((k for k, r in enumerate(rows.get(test_step, [])) if doc in str(r.get("applicableSpecifications", "")) and doc not in str(r.get("specificationRevision", ""))), None)
            flag("warn", "specificationRevision", test_step, f"{doc} is cited without a revision.", "The lab works to a specific revision.",
                 f"Add Rev {current_rev(doc)} (current).", f"{doc} Rev {current_rev(doc)}", i)
    for t in sorted(found):
        doc = PROCEDURE[t]
        if doc not in cited:
            flag("warn", "applicableSpecifications", test_step, f"The request describes {G.SUPPORTED and t.replace('_', ' ')} but does not cite {doc}.",
                 "The lab needs to know which procedure governs the test.", f"Cite {doc} Rev {current_rev(doc)}.", f"{doc} Rev {current_rev(doc)}")
    if found & ELEVATED and "SYN-PR-201" not in cited and not re.search(r"precondition|bake", all_text, re.I):
        flag("warn", "additionalInformation", None, "Preconditioning is not mentioned.",
             "SYN-PR-201 requires moisture preconditioning before every elevated-temperature test.", "Add 'Precondition per SYN-PR-201 Rev B (bake 125 C / 24 h)'.", "SYN-PR-201 Rev B")
    for name in out_of_scope:
        flag("info", "testsToBePerformed", test_step, f"'{name}' has no procedure in the assistant's library.",
             "The assistant cannot check this test's requirements; the lab will.", "Cite the governing standard and revision.", "Procedure library")

    # 3. Inputs each procedure needs before scheduling
    if "warpage_reflow" in found:
        if not (re.search(r"profile", all_text, re.I) and (re.search(r"peak", all_text, re.I) or re.search(r"attach", all_text, re.I))):
            flag("error", "additionalInformation", None, "No thermal profile for the reflow simulation.", "SYN-TM-101 Rev C: a request without a thermal profile cannot be scheduled.",
                 "Give ramp rate, soak, peak temperature, time above liquidus and cooling rate, or attach the profile.", "SYN-TM-101 Rev C")
        if not re.search(r"datum|measurement area|seating plane", all_text, re.I):
            flag("error", "additionalInformation", None, "No measurement area or datum.", "SYN-TM-101 Rev C requires them; without a datum, coplanarity values cannot be compared.",
                 "State the area and datum, for example 'terminal seating plane, datum = three standoffs'.", "SYN-TM-101 Rev C")
        if values.get("second_profile_requested") and not re.search(r"second (reflow )?profile[^.]{0,60}(confirm|intend|accept|ok)", all_text, re.I):
            flag("warn", "testsToBePerformed", test_step, "The same samples go through reflow twice.", "SYN-TM-101 Rev C: no second profile on the same samples unless the request states it explicitly; the first profile changes the parts.",
                 "Either state that a second profile is intended, or split into a control group and a cycled group (see example EX-03).", "SYN-TM-101 Rev C", row_with(r"again"))
    if "thermal_cycling" in found:
        if "cycling_min_c" not in values:
            flag("error", "testsToBePerformed", test_step, "No cycling temperature range.", "SYN-TM-110 Rev D requires minimum and maximum temperature.", "Add for example '-40 C to 125 C'.", "SYN-TM-110 Rev D", row_with(r"cycl"))
        if "cycles" not in values:
            flag("error", "testsToBePerformed", test_step, "No number of cycles.", "SYN-TM-110 Rev D requires the number of cycles.", source="SYN-TM-110 Rev D", row=row_with(r"cycl"))
        if not re.search(r"dwell", all_text, re.I) or not re.search(r"ramp|c/min", all_text, re.I):
            flag("warn", "testsToBePerformed", test_step, "Dwell time or ramp rate is missing.", "SYN-TM-110 Rev D requires both; the lab would otherwise use its default.", "Add for example '15 min dwell, 10 C/min ramp'.", "SYN-TM-110 Rev D", row_with(r"thermal(ly)? cycl|cycling -?\d"))
        if "cycling_min_c" in values:
            eq = equipment_db.find("thermal cycling")["equipment"]
            eq = [e for e in eq if e["status"] == "available"]
            if not eq:
                flag("info", None, None, "No thermal cycling chamber in the lab equipment database.", "The range cannot be checked against a chamber.", source="Equipment database")
            else:
                c = equipment_db.check(eq[0]["id"], temp_c=(values["cycling_min_c"], values["cycling_max_c"]))
                for p in c["problems"]:
                    flag("error", "testsToBePerformed", test_step, f"{eq[0]['name']}: {p}.", "The chamber cannot run this profile.", "Change the range or ask the lab for another chamber.",
                         f"Equipment database: {eq[0]['id']}", row_with(re.escape(str(values['cycling_min_c'])) + r"\s*°?\s*c"))
    if "flatness_rt" in found:
        if not re.search(r"datum|measurement area|seating plane", all_text, re.I):
            flag("error", "additionalInformation", None, "No measurement area or datum.", "SYN-TM-104 Rev A requires them.", source="SYN-TM-104 Rev A")
        if "acceptance_limit_mm" not in values:
            flag("error", "additionalInformation", None, "No acceptance limit.", "SYN-TM-104 Rev A requires the limit.", source="SYN-TM-104 Rev A")
    if "temperature_rise" in found:
        src = "SYN-TM-120 Rev A"
        row = row_with(r"rise|current|amp")
        files = bool(G.BOARD.search(all_text.lower()) and G.BOARD_FILES.search(all_text.lower()))   # board files cover routing, holes, copper
        if "currents_a" not in values:
            flag("error", "testsToBePerformed", test_step, "No test current.", f"{src} requires the test current or current steps in amperes.",
                 "Add for example '5 A, 10 A and 15 A steps'.", src, row)
        elif max(values["currents_a"]) > 100:
            flag("error", "testsToBePerformed", test_step, f"{max(values['currents_a'])} A is above the bench's 100 A per circuit.",
                 "The temperature rise bench (SYN-ELEC-TRISE) supplies up to 100 A per circuit.", "Split the current, or ask the lab.", "Equipment database", row)
        if not re.search(r"(all|every|each|single|one|adjacent|\d+)\s+(contacts?|pins?|positions?|circuits?)|energi[sz]e|fully loaded", all_text, re.I):
            flag("error", "testsToBePerformed", test_step, "The energized pattern is missing.", f"{src} requires how many contacts are energized and in which pattern.",
                 "Add for example 'all contacts energized in series'.", src, row)
        if not files and "wire_awg" not in values and not re.search(r"\bawg\b|trace width|copper weight|busbar", all_text, re.I):
            flag("error", "testsToBePerformed", test_step, "The current-carrying conductor is missing.", f"{src} requires the wire gauge and length, or the board trace width and copper weight.",
                 "Add for example '18 AWG wire, 300 mm per lead'.", src, row)
        if not re.search(r"thermocouples?|\btcs?\b|\bt/c\b|monitored contacts?|hottest contact", all_text, re.I):
            flag("error", "testsToBePerformed", test_step, "Thermocouple (TC) locations are missing.",
                 f"{src} requires which contacts are monitored, how many TCs per sample and where on the contact.",
                 "Add for example '3 TCs per sample at the mating interface of the center contacts'.", src, row)
        if files:
            flag("info", "attachments", None, "Board files are listed: the lab reviewer checks routing, thermocouple holes and copper in them.",
                 "This tool cannot open attachments.", None, src)
        elif G.BOARD.search(all_text.lower()):
            flag("info", "attachments", None, "Recommended: list the test board files under Attachments (schematic and layout PDF; Gerber/ODB++ by link).",
                 f"{src}: they show routing, current entry and exit, thermocouple holes and copper directly. Not required.", None, src)
        if G.BOARD.search(all_text.lower()):
            if not re.search(r"already (soldered|mounted|reflowed|pressed|assembled|on)|pre-?mounted|lab (to|will|should|must|can) (mount|solder|reflow|press)|"
                             r"needs? (to be )?(mounted|soldered|reflowed|pressed)|(un|not )mounted|assembled boards?|mounted boards?", all_text, re.I):
                flag("error", "testsToBePerformed", test_step, "It is not stated whether the connectors are already mounted on the test boards.",
                     f"{src}: the lab must know whether to mount them (and to which reflow profile or press-fit spec).",
                     "Add for example 'connectors already reflowed on the test boards'.", src, row)
            if not files and not re.search(r"(tc|thermocouple)s?[^.]{0,40}holes?|holes?[^.]{0,40}(tcs?|thermocouples?)|pre-?drilled|access holes?|lab (to|will|may|can) drill|no drilling",
                             all_text, re.I):
                flag("error", "testsToBePerformed", test_step, "Thermocouple access through the board is not stated.",
                     f"{src}: say whether the boards already have TC holes under the monitored contacts or the lab drills them (where, what size).",
                     "Add for example 'boards have 1 mm TC holes under the center contacts'.", src, row)
            if not files and not re.search(r"\bseries\b|\bparallel\b|daisy[- ]?chain", all_text, re.I):
                flag("warn", "testsToBePerformed", test_step, "Current routing (series or parallel) is not stated.",
                     f"{src} requires how the current is routed through the contacts and where it enters and leaves the board.", None, src, row)
        if not re.search(r"ambient|still air|enclosure|room temperature|no (forced )?air ?flow", all_text, re.I):
            flag("warn", "testsToBePerformed", test_step, "Ambient temperature and air condition are missing.",
                 f"{src} requires the ambient temperature; airflow changes the rise.", "Add for example '23 C ambient, still air'.", src, row)
        if "trise_limit_c" not in values:
            flag("warn", "testsToBePerformed", test_step, "No temperature rise limit.", f"{src}: without a limit the lab reports the rise but cannot state a current rating.",
                 "Add for example 'limit 30 C rise above ambient'.", src, row)
    if "llcr" in found:
        src = "SYN-TM-130 Rev A"
        row = row_with(r"llcr|contact resistance|interface resistance")
        if not re.search(r"(all|every|each|\d+)\s+(positions?|contacts?|pins?|circuits?|channels?)|positions?\s+\d", all_text, re.I):
            flag("error", "testsToBePerformed", test_step, "The measured positions are missing.", f"{src} requires which contacts are measured and how many per sample.",
                 "Add for example 'positions 1-20 on each sample'.", src, row)
        if not (re.search(r"measurement points?|sense (leads?|points?)|kelvin|4[- ]wire|four[- ]wire|at the (board )?pads?|\bvias?\b|from the crimp|bulk resistance", all_text, re.I)
                or (G.BOARD.search(all_text.lower()) and G.BOARD_FILES.search(all_text.lower()))):
            flag("error", "testsToBePerformed", test_step, "The measurement points are missing.",
                 f"{src} requires where the current and sense leads attach on each side of the mated pair, so every readout measures the same path.",
                 "Add for example 'sense at the board pads, bulk resistance subtracted', or list the board files.", src, row)
        if not re.search(r"initial|before and after|after (each|every|\d+)|readouts?|baseline", all_text, re.I):
            flag("error", "testsToBePerformed", test_step, "The readout schedule is missing.", f"{src} requires when readings are taken.",
                 "Add for example 'initial, after 50 mating cycles, after 500 thermal cycles'.", src, row)
        if not re.search(r"\d+(\.\d+)?\s*m(illi)?(ω|ohms?|Ω)|delta ?r|Δr|change (of|from|limit)", all_text, re.I):
            flag("warn", "testsToBePerformed", test_step, "No resistance-change limit.", f"{src}: without a limit the lab reports values but cannot say which positions failed.",
                 "Add for example 'max 10 mOhm change from initial'.", src, row)
    # Registry tests: every input the procedure requires that the request does not give (same entries as the chat's questions)
    from assistant import registry
    for k in sorted(found & set(registry.BY_KEY)):
        src = registry.source(k)
        row = row_with("|".join(registry.BY_KEY[k]["detect"]))
        for i in registry.missing_inputs(k, all_text):
            flag("error" if i["blocking"] else "warn", "testsToBePerformed", test_step, i["missing"], f"{src} requires it before scheduling." if i["blocking"]
                 else f"{src}: the lab otherwise uses its default or cannot judge the result.", f"Add for example '{i['example']}'.", src, row)
    if found & ELEVATED and not re.search(r"storage|as-molded|as molded|dry.?pack|since molding|reflowed assembly", all_text, re.I):
        flag("warn", "additionalInformation", None, "Sample storage history is missing.", "SYN-PR-201 Rev B: state storage history since molding and whether samples are as-molded.",
             "Add for example 'as-molded, in moisture barrier bags since 2026-11-02'.", "SYN-PR-201 Rev B")

    # 4. Samples: quantity against the procedure minimum (lab request), traceability
    if sample_step and form_key == "lab_test_request":
        total = sum(_int(r.get("quantity")) for r in rows[sample_step])
        groups = max(1, len(set(re.findall(r"\bgroup\s+([a-z0-9])\b", tests_text, re.I))))
        rules = [MIN_SAMPLES[t] for t in found if t in MIN_SAMPLES]
        if total and rules:
            need, src = max(rules)
            if total < need * groups:
                reason = re.search(r"\bonly (\d+|one|two)\s+(\w+\s+){0,3}(available|built|exist|left|made|received|on hand)\b|\breason\b|\bbecause\b|"
                                   r"\blimited (samples|parts|build|quantity)\b|\bprototypes? (build|run)\b|\bno more (samples|parts)\b", all_text, re.I)
                flag("warn" if reason else "error", "quantity", sample_step,
                     f"{total} samples for {groups} test condition(s); the procedure needs at least {need} per condition" +
                     (" (a reason is given, so the lab decides)." if reason else ", or a reason for fewer."), src,
                     f"Send at least {need * groups} samples, or give the reason in Additional Information "
                     f"(for example 'only {total} prototypes available').", src.split(",")[0])
        for i, r in enumerate(rows[sample_step]):
            lot = str(r.get("traceabilityMfgLotInfo", ""))
            if lot and not re.search(r"\d", lot):
                flag("warn", "traceabilityMfgLotInfo", sample_step, f"Item {i + 1}: no lot number or sample IDs.", "SYN-TM-101 Rev C: each sample needs an ID traceable to its molding lot.",
                     "Give the lot and the sample ID range.", "SYN-TM-101 Rev C", i)

    # 5. Every table with part numbers: parts directory, quantities, per-item files (all forms)
    from assistant.tools import parts_directory
    pdir = {p["part_number"].lower(): p for p in parts_directory()}
    dir_flagged = set()          # a part listed in several tables is checked against the directory once
    for n, s_ in steps.items():
        t = _table(s_)
        if not t:
            continue
        keys = {c["key"] for c in t["columns"]}
        pn_key = "partNumberRevision" if "partNumberRevision" in keys else ("partNumber" if "partNumber" in keys else None)
        qty_key = "quantity" if "quantity" in keys else ("qty" if "qty" in keys else None)
        seen = {}
        for i, r in enumerate(rows[n]):
            if qty_key and str(r.get(qty_key, "")).strip() and _int(r.get(qty_key)) < 1:
                flag("error", qty_key, n, f"{item} {i + 1}: quantity must be a whole number of at least 1.", "A zero or blank quantity cannot be built, tested or ordered.", source="Request form", row=i)
            if pn_key and r.get(pn_key):
                raw = str(r[pn_key])
                pn = re.split(r"\s+rev\b", raw, flags=re.I)[0].strip().lower()
                rev = (re.search(r"rev\.?\s*([a-z0-9]+)", raw, re.I) or [None, None])[1] if pn_key == "partNumberRevision" else r.get("rev")
                key = (pn, str(rev or "").upper())
                no_pn = bool(re.match(r"^(n/?a|none|tbd|prototype|various|multiple)\b", pn))
                # Same part from different lots or under a different name is a deliberate comparison, not a slip.
                key = key + (str(r.get("traceabilityMfgLotInfo") or "").strip().lower(), str(r.get("productName") or "").strip().lower())
                if key in seen and form_key != "smt_lab_test_request" and not no_pn:
                    flag("warn", pn_key, n, f"Item {i + 1} repeats item {seen[key] + 1} ({raw}{' Rev ' + str(rev) if pn_key == 'partNumber' and rev else ''}).", "Duplicate items are usually a copy-paste slip and get built or ordered twice.", "Merge them or change one.", "Request form", i)
                seen.setdefault(key, i)
                p = pdir.get(pn)
                first = (pn, str(rev or "").upper()) not in dir_flagged   # directory notes once per part, whatever the lot
                dir_flagged.add((pn, str(rev or "").upper()))
                if not first:
                    pass
                elif no_pn:   # no part number given: the empty-field and lot checks cover it
                    pass
                elif pn_key and not p and form_key != "purchase_requisition":
                    flag("info", pn_key, n, f"Item {i + 1}: {pn.upper()} is not in the parts directory.", "Material and revision cannot be checked.", source="Parts directory", row=i)
                elif p and first:
                    if p.get("status") == "obsolete":
                        flag("error", pn_key, n, f"Item {i + 1}: {p['part_number']} is obsolete in the parts directory.", "An obsolete part rarely supports a current decision or build.", "Confirm the part number.", "Parts directory", i)
                    if rev and p.get("rev") and str(rev).upper() != str(p["rev"]).upper():
                        flag("warn", "rev" if pn_key == "partNumber" else pn_key, n, f"Item {i + 1}: Rev {str(rev).upper()} differs from the parts directory (Rev {p['rev']}).", "The work may not match the current design.", f"Use Rev {p['rev']} or explain why.", "Parts directory", i)
                    for k, src in (("housingMaterial", "housing_material"), ("contactPlating", "contact_plating"), ("material", "material")):
                        if r.get(k) and p.get(src) and r[k].strip().lower() != p[src].strip().lower():
                            flag("warn", k, n, f"Item {i + 1}: {r[k]} differs from the parts directory ({p[src]}).", "Mismatched material data leads to the wrong build or results that are hard to interpret.", f"Check; the directory says {p[src]}.", "Parts directory", i)
            cfg = t.get("item_files") or {}
            files = r.get("_files") or {}
            for k in cfg.get("required", []):
                if not files.get(k):
                    flag("error", "_file_" + k, n, f"Item {i + 1}: no {'drawing (PDF)' if k == 'drawing' else 'STEP file' if k == 'cad' else k} attached.", cfg.get("match") or "Required for this item.", "Attach it to this item.", "Request form", i)
            dname, cname = (files.get("drawing") or [{}])[0].get("name"), (files.get("cad") or [{}])[0].get("name")
            if cfg.get("match") and dname and cname and re.sub(r"\.[^.]+$", "", dname).lower() != re.sub(r"\.[^.]+$", "", cname).lower():
                flag("warn", "_file_cad", n, f"Item {i + 1}: drawing '{dname}' and STEP '{cname}' have different names.", cfg["match"], "Check both files are the same part and revision.", "Request form", i)

    # 6. Form-specific rules
    if form_key == "smt_lab_test_request":
        for i, r in enumerate(rows.get(2, [])):
            if r.get("solderPaste") and r.get("sphereAlloy") and r["solderPaste"] != r["sphereAlloy"]:
                flag("warn", "sphereAlloy", 2, f"Item {i + 1}: {r['sphereAlloy']} spheres with {r['solderPaste']} paste (mixed alloy).", "Mixed-alloy joints need a profile that suits both alloys; the lab will ask which one to use.",
                     "Confirm the mix is intended and give the profile.", "SMT practice", i)
            if r.get("sphereDiameter") == "Other":
                flag("warn", "sphereDiameter", 2, f"Item {i + 1}: sphere diameter is 'Other'.", "The lab cannot order or set up spheres without the size.", "Give the diameter in Additional Information.", "Request form", i)
        bga_paste = {re.split(r"\s+rev\b", str(r.get("partNumberRevision", "")), flags=re.I)[0].lower(): r.get("solderPaste") for r in rows.get(2, [])}
        for i, r in enumerate(rows.get(3, [])):
            pn = re.split(r"\s+rev\b", str(r.get("partNumberRevision", "")), flags=re.I)[0].lower()
            if pn in bga_paste and bga_paste[pn] and r.get("solderPaste") and r["solderPaste"] != bga_paste[pn]:
                flag("warn", "solderPaste", 3, f"Item {i + 1}: board attach paste ({r['solderPaste']}) differs from the BGA paste ({bga_paste[pn]}) for the same part.", "Two reflow chemistries on one part changes the joint and the warpage behaviour.", "Use one paste or explain why.", "SMT practice", i)
            if r.get("stencil") in ("Other", "Needs Designed") and not str(r.get("stencilNumber", "")).strip():
                flag("warn", "stencilNumber", 3, f"Item {i + 1}: stencil is '{r['stencil']}' with no stencil number or details.", "A new or non-standard stencil adds lead time; the lab needs the aperture design or drawing.", "Give the stencil number, or attach the stencil drawing.", "SMT practice", i)
    if form_key == "machine_shop_request":
        scope = str(fields.get("scopeOfWork", ""))
        if scope and len(scope.split()) < 8:
            flag("warn", "scopeOfWork", 2, f"Scope of work is only {len(scope.split())} words.", "The shop needs what the part is for, critical features and tolerances, and finish.",
                 "Describe purpose, critical dimensions and tolerances, finish and any inspection needed.", "Shop practice", None)
        if fields.get("priority") == "Line down" and not re.search(r"line|customer|down|stopp|halt", scope, re.I):
            flag("warn", "priority", 2, "Priority is 'Line down' but the scope does not say what is stopped.", "Line-down jobs push other work back; the shop confirms the impact first.",
                 "Say which line or customer is affected.", "Shop practice")
        if fields.get("partDeliveryMethod") == "Ship to another site" and not re.search(r"ship to|address|attn", str(fields.get("additionalInformation", "")), re.I):
            flag("warn", "additionalInformation", 4, "Parts ship to another site but no address is given.", "The shop cannot ship without it.", "Add the ship-to address and contact.", "Request form")
        lists = SCHEMA["shared_lists"]
        for k, lk in (("businessUnit", "businessUnit"), ("costCenter", "bPCNumber")):
            v = str(fields.get(k, "")).strip()
            if v and lists.get(lk) and v not in lists[lk] and not re.match(r"^(I_)?U\d{4}", v):
                flag("info", k, 1, f"'{v}' is not in the {k == 'costCenter' and 'cost center' or 'business unit'} list.", "Typed values are allowed but checked by Finance.", "Pick from the list if it is there.", "Request form")
    if form_key == "purchase_requisition":
        lines = rows.get(3, [])
        subtotal = 0.0
        for i, r in enumerate(lines):
            q, pr = _num(r.get("qty")), _num(r.get("unitPrice"))
            if str(r.get("unitPrice", "")).strip() and pr <= 0:
                flag("error", "unitPrice", 3, f"Line {i + 1}: unit price is {r.get('unitPrice')}.", "Purchasing cannot raise an order at zero price.", "Enter the quoted price.", "Purchasing rule", i)
            subtotal += q * pr
        tax = _num(fields.get("tax"))
        if fields.get("salesTax") == "Exempt" and tax > 0:
            flag("warn", "tax", 4, f"Sales tax is 'Exempt' but tax is {tax:.2f}.", "The two answers contradict each other.", "Remove the tax, or change Sales Tax to Taxable.", "Purchasing rule")
        if not str(fields.get("supplierCode", "")).strip():
            flag("info", "supplierCode", 1, "No supplier code: Purchasing will treat this as a new supplier.", "New suppliers need vendor set-up before the order (synthetic rule).", "Add the code if the supplier is already set up.", "Purchasing rule (synthetic)")
        has_quote = any((r.get("_files") or {}).get("quote") for r in lines) or str(fields.get("rfqNumber", "")).strip()
        if lines and not has_quote:
            flag("warn", "rfqNumber", 1, "No quote number and no quote attached.", "Prices without a quote are usually sent back by Purchasing.", "Add the RFQ or quote number, or attach the quote to a line.", "Purchasing rule")
        if str(fields.get("dateRequired", "")).strip().upper() == "ASAP":
            flag("info", "dateRequired", 4, "Date required is 'ASAP'.", "Purchasing plans to dates; ASAP is treated as the standard lead time.", "Give the date you actually need the parts.", "Purchasing rule")
        total = subtotal + tax - _num(fields.get("discount")) + _num(fields.get("shipping"))
        if total > APPROVAL_LIMIT_USD:
            flag("info", None, 4, f"Estimated cost {total:,.2f} USD is above {APPROVAL_LIMIT_USD:,.0f} USD.", "Needs a second approval (synthetic rule).", "Allow time for the extra approval.", "Purchasing rule (synthetic)")

    # 7. Clarity, dates, contacts (all forms)
    for i, r in enumerate(rows.get(test_step, [])):
        if r.get("testsToBePerformed") and len(str(r["testsToBePerformed"]).split()) < 5:
            flag("warn", "testsToBePerformed", test_step, f"Item {i + 1}: '{r['testsToBePerformed']}' is too short to plan from.", "The lab needs the method, conditions and what to measure.",
                 "Describe the test, conditions and measurements in one sentence.", "Example library", i)
    why_text = info + " " + " ".join(str(r.get("testsToBePerformed", "")) + " " + str(r.get("applicableSpecifications", "")) for r in rows.get(test_step, []))
    if test_step and info and not re.search(r"objective|purpose|goal|decision|so (that|we)|in order to|looking (for|to)|please verify|"
                                             r"\bto (confirm|check|compare|verify|qualify|determine|assess|identify|evaluate|understand|investigate|see if|find out)\b",
                                             why_text, re.I):
        flag("warn", "additionalInformation", None, "The objective is not stated.", "Without the decision the data supports, the lab cannot suggest a better test.",
             "Start with 'Objective: ...' (see the examples).", "Example library")
    for key, lead, who in (("requestedTestingCompletionDate", LEAD_TIME_WORKDAYS, "Lab"), ("requestedDueDate", SHOP_LEAD_TIME_WORKDAYS, "Shop")):
        d = fields.get(key)
        step_n = next((n for n, s_ in steps.items() if any(f.get("key") == key for f in _expand(s_.get("fields")))), None)
        if not d:
            continue
        try:
            due = dt.date.fromisoformat(d)
        except ValueError:
            continue
        days = sum(1 for k in range(1, (due - today).days + 1) if (today + dt.timedelta(k)).weekday() < 5)
        if due < today:
            flag("error", key, step_n, "The requested date is in the past.", f"The {who.lower()} cannot plan to it.", source="Request form")
        elif days < lead and not (key == "requestedDueDate" and fields.get("priority") == "Line down"):
            flag("warn", key, step_n, f"Only {days} working days until the requested date.", f"{who} lead time is about {lead} working days (synthetic rule).", f"Allow more time or call the {who.lower()} first.", f"{who} rule (synthetic)")
    for key in ("sendCopiesTo", "emailCc", "email"):
        emails = [e.strip() for e in str(fields.get(key, "")).split(",") if e.strip()]
        if key == "sendCopiesTo" and len(emails) > 5:
            flag("error", key, None, f"{len(emails)} addresses; the form takes at most 5.", "Request form rule.", source="Request form")
        for e in emails:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", e, re.I):
                flag("error", key, None, f"'{e}' is not an email address.", "Messages would not reach this person.", source="Request form")
    if fields.get("confidentialTestsOrSamples") == "yes" and fields.get("canTestingBeSubcontracted") == "yes":
        flag("warn", "canTestingBeSubcontracted", None, "Confidential samples are allowed to be subcontracted.", "Subcontracting sends confidential samples outside the lab.", "Confirm both answers.", "Request form")

    # 8. What good past requests also state (example library)
    if found:
        exemplar_points = [("report contents", r"report|plot|contour|table")]
        if found & {"warpage_reflow", "flatness_rt"}:
            exemplar_points.append(("acceptance limit", r"limit|within|below|under|max(imum)?\s+\d"))
        for label, rx in exemplar_points:
            if not re.search(rx, info, re.I):
                flag("info", "additionalInformation", None, f"High-quality past requests for this test also state the {label}.", "From the example library.", None, "Example library")

    errors = sum(f["severity"] == "error" for f in flags)
    warns = sum(f["severity"] == "warn" for f in flags)
    readiness = "Not ready: fix the errors first" if errors else ("Ready to submit, with warnings" if warns else "Ready to submit")
    return {"form": form_key, "readiness": readiness, "errors": errors, "warnings": warns,
            "info": sum(f["severity"] == "info" for f in flags), "tests_detected": sorted(found), "flags": flags}


if __name__ == "__main__":
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    r = review(d["form"], d["fields"])
    print(json.dumps({k: v for k, v in r.items() if k != "flags"}, indent=1))
    for f in r["flags"]:
        print(f"[{f['severity']:5}] {f['message']}  ({f['source']})")

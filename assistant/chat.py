"""Chat assistant for the request form: the engineer describes the test, the assistant drafts the form.

    reply = assist(message, history, form_key, fields)

One turn does, in order (every step is logged to traces/runs/<run>.jsonl):
  1. guard     screen the message (hidden characters, instructions aimed at the AI, links, credentials); refuse to
               submit, to reveal prompts, keys or private files; nothing here ever submits a request
  2. scope     recognise the tests; a test with no procedure in the library is referred to the lab (no invented rules)
  3. cite      retrieve the procedure passages for each recognised test (active revisions only) and cite them
  4. ask       list the inputs the procedure requires that the engineer has not given yet
  5. draft     the local model proposes field values from the conversation; code keeps only values whose numbers
               appear in what the engineer wrote, and fills specifications and revisions from the citations itself
  6. check     run the same quality check as the form (assistant/quality.py) on the proposed draft
  7. state     incomplete (questions or must-fix flags left) or ready for review; only a person approves

With LRT_STUB_LLM=1, or when the model does not answer, step 5 uses rules instead of the model and says so.
"""
import json
import re
import time

from assistant import guardrails as G
from assistant import quality
from assistant import tools
from assistant.trace import Trace

LLM_CALLS_PER_TURN = 1
MAX_MESSAGE_CHARS = 4000

SYSTEM = """You fill in a laboratory test request form for an engineer at a connector company.
Use ONLY facts the engineer wrote in the conversation. Never invent numbers, part numbers, lots, dates, materials or
procedure names. If a value is not given, use an empty string. Do not decide pass/fail and do not promise results.
Return ONLY one JSON object with exactly these keys (all strings):
{"productName": "", "partNumberRevision": "", "traceabilityMfgLotInfo": "", "quantity": "", "contactBaseMaterial": "",
 "contactPlating": "", "housingMaterial": "", "testsToBePerformed": "", "objective": "", "additionalInformation": ""}
testsToBePerformed: one or two plain sentences naming each test with the conditions the engineer gave.
objective: one sentence on what decision the results support, only if the engineer said it."""

FIELD_KEYS = ["productName", "partNumberRevision", "traceabilityMfgLotInfo", "quantity", "contactBaseMaterial",
              "contactPlating", "housingMaterial", "testsToBePerformed", "objective", "additionalInformation"]
SAMPLE_KEYS = ["productName", "partNumberRevision", "traceabilityMfgLotInfo", "contactBaseMaterial", "contactPlating",
               "contactLubricant", "housingMaterial", "quantity"]

REVIEW = re.compile(r"\b(what do you think|thoughts on|review|critique|feedback|look (at|over)|check (this|it|my)|evaluate|"
                    r"is (this|it|my request|the request) (ok|okay|good|ready|complete|clear|enough)|what('?s| is) missing|"
                    r"anything missing|improve|better|ready to (send|enter))\b", re.I)
CONTACT = {"firstName", "lastName", "email", "phone", "bPCNumber", "businessUnit", "mFGSite", "extension", "sendCopiesTo"}

SYSTEM_REVIEW = """You review a draft laboratory test request for an engineer at a connector company, as an experienced
lab engineer would. Use ONLY the draft, the cited procedure passages and the quality-check findings you are given.
Write 3 to 6 short bullet points, each starting with "- ": what the lab will understand, what is missing or ambiguous
for the lab to run and report the test, and how to state the objective (the decision the results support) if it is
weak. Never invent numbers, part numbers, procedure names or results. Do not decide pass/fail or promise results.
Plain text only."""

SUBMIT = re.compile(r"\b(submit|send (it|this)|file (it|this)|post (it|this)|approve (it|this))\b", re.I)
DISCLOSE = re.compile(r"\b(system prompt|your (instructions|prompt|rules)|api[_ -]?key|password|users\.json|session[_ ]key|"
                      r"other (user|people)'?s? drafts?|data/private|\.\./|show me (the )?(private|secret))", re.I)
OVERCONFIDENT = {"will pass": "is expected to meet", "guaranteed": "expected", "always": "typically", "never": "rarely",
                 "no risk": "low risk", "meets spec": "is to be compared with the specification", "certainly": "likely",
                 "proven": "supported by data", "100%": "fully"}

# How to tell from the engineer's words that a required input has been given.
ANSWERED = {
    "part": lambda t, v: v.get("_part_found") or re.search(r"\b[a-z]{2,6}-\d{3,}[\w-]*|\bp/?n\b|part (number|no\.?)\s*[:#]?\s*\w", t),
    "samples": lambda t, v: "samples" in v or re.search(r"\b(quantity|qty)\b\s*[:=]?\s*\d", t),
    "objective": lambda t, v: re.search(r"\b(objective|purpose|goal|to (confirm|compare|check|verify|qualify|determine|decide|release|support)|so (that|we)|"
                                        r"qualif\w+|release|comparison|compare)\b", t),
    "reflow_profile": lambda t, v: "reflow_peak_c" in v and re.search(r"ramp|soak|liquidus|tal\b|j-std-020|profile [a-z0-9]", t),
    "measurement_area": lambda t, v: re.search(r"datum|seating plane|measurement area|whole part|full part|region|area of", t),
    "capture_temps": lambda t, v: re.search(r"25\s*°?\s*c.*(peak|max)|capture|every \d+\s*°?\s*c|readings? at", t),
    "cycling_profile": lambda t, v: "cycling_min_c" in v and "cycles" in v and re.search(r"dwell|ramp|c/min|minutes? at", t),
    "readouts": lambda t, v: "readout_every" in v or re.search(r"readout|interim|after \d+ (and|,)", t),
    "acceptance_limit": lambda t, v: "acceptance_limit_mm" in v,
    "storage_history": lambda t, v: re.search(r"stor(ed|age)|as[- ]molded|baked?|dry|moisture|msl|since molding", t),
    "trise_currents": lambda t, v: "currents_a" in v,
    "trise_pattern": lambda t, v: re.search(r"(all|every|each|single|one|adjacent|\d+)\s+(contacts?|pins?|positions?|circuits?)\s*(energi[sz]ed|powered|loaded)?|"
                                            r"energi[sz]e|fully loaded|all positions", t),
    "trise_conductor": lambda t, v: (G.BOARD.search(t) and G.BOARD_FILES.search(t)) or "wire_awg" in v or re.search(r"\bawg\b|trace width|copper weight|\boz\b copper|busbar", t),
    "trise_limit": lambda t, v: "trise_limit_c" in v,
    "mount_kind": lambda t, v: G.BOARD.search(t) or G.WIRE.search(t),
    "trise_mounted": lambda t, v: re.search(r"already (soldered|mounted|reflowed|pressed|assembled|on)|pre-?mounted|"
                                            r"lab (to|will|should|must|can) (mount|solder|reflow|press)|needs? (to be )?(mounted|soldered|reflowed|pressed)|"
                                            r"(un|not )mounted|loose (connectors|parts)|assembled boards?|mounted boards?", t),
    "trise_tc_access": lambda t, v: (G.BOARD.search(t) and G.BOARD_FILES.search(t)) or re.search(r"(tc|thermocouple)s?[^.]{0,40}holes?|holes?[^.]{0,40}(tcs?|thermocouples?)|pre-?drilled|"
                                              r"access holes?|lab (to|will|may|can) drill|no drilling|drill(ed)? (through|from|under)", t),
    "trise_routing": lambda t, v: re.search(r"\bseries\b|\bparallel\b|daisy[- ]?chain", t) or (G.BOARD.search(t) and G.BOARD_FILES.search(t)),
    "trise_board_files": lambda t, v: G.BOARD_FILES.search(t),
    "trise_boards": lambda t, v: re.search(r"(boards?|pcbs?)[^.]{0,30}(supplied|provided|rev(ision)?\b|\bid\b|from)|"
                                           r"we (will )?(supply|provide|send)|lab (supplies|provides|has)", t),
    "trise_wire_term": lambda t, v: re.search(r"crimp(ed)?|pre-?terminated|already terminated|lab (to|will) terminate|soldered (wires|leads)", t),
    "trise_housing": lambda t, v: re.search(r"(drill|modify|hole)[^.]{0,30}housing|housing[^.]{0,30}(drill|modif|intact|hole)", t),
    "llcr_positions": lambda t, v: re.search(r"(all|every|each|\d+)\s+(positions?|contacts?|pins?|circuits?|channels?)|positions?\s+\d|pins?\s+\d+\s*(-|to|,)", t),
    "llcr_points": lambda t, v: re.search(r"measurement points?|sense (leads?|points?)|kelvin|4[- ]wire|four[- ]wire|probe (at|on)|at the (board )?pads?|"
                                          r"\bvias?\b|from the crimp|bulk resistance", t) or (G.BOARD.search(t) and G.BOARD_FILES.search(t)),
    "llcr_readouts": lambda t, v: re.search(r"initial|before and after|after (each|every|\d+)|readouts?|\bt0\b|baseline", t),
    "llcr_limit": lambda t, v: re.search(r"\d+(\.\d+)?\s*m(illi)?(ω|ohms?|Ω)|delta ?r|Δr|change (of|from|limit)", t),
    "trise_tc": lambda t, v: re.search(r"thermocouples?|\btcs?\b|\bt/c\b|monitored contacts?|hottest contact", t),
    "trise_ambient": lambda t, v: re.search(r"ambient|still air|enclosure|room temperature|no (forced )?air ?flow", t),
    "material_grade": lambda t, v: re.search(r"lcp|ppa|ppS\b|pa\d|grade|zenite|vectra|sumika|laperos|e\d{3,4}", t, re.I),
}


def _registry_answered():
    """Answered-checks for the registry tests' inputs (same patterns the rule check uses)."""
    from assistant import registry
    for t in registry.TESTS:
        for i in t["inputs"]:
            ANSWERED.setdefault(i["key"], (lambda rx: lambda text, v: re.search(rx, text, re.I))(i["answered"]))


_registry_answered()


def _numbers(s):
    return re.findall(r"(?<![\w.])\d+(?:\.\d+)?", s or "")


def _grounded_text(value, source):
    """Every number in a model-written value must appear in what the engineer wrote."""
    missing = [n for n in _numbers(value) if not G.grounded(n, source)]
    return not missing, missing


def calibration(text):
    """During-generation check (Lab 6.1): absolute wording in a draft, with a hedged rewrite."""
    found, hedged = [], text
    for word, softer in OVERCONFIDENT.items():
        if re.search(r"\b" + re.escape(word) + r"\b", text, re.I):
            found.append(word)
            hedged = re.sub(r"\b" + re.escape(word) + r"\b", softer, hedged, flags=re.I)
    sentences = max(1, len(re.findall(r"[.!?](\s|$)", text)) or 1)
    score = min(1.0, len(found) / sentences)
    return {"markers": found, "score": round(score, 2), "verdict": "FAIL" if score >= .5 else "WARN" if found else "PASS", "hedged": hedged}


def _latest_order(user_msgs, tests):
    """The step order from the most recent message that gives one (two or more steps); a later correction wins."""
    for m in reversed(user_msgs):
        o = G.sequence(m, tests)
        if len(o) > 1:
            return o + [k for k in G.sequence(" ".join(user_msgs), tests) if k not in o]
    return G.sequence(" ".join(user_msgs), tests)


def _rule_draft(text, values, tests, parts, out_of_scope=()):
    """Draft without the model: only what can be read reliably from the text."""
    d = {k: "" for k in FIELD_KEYS}
    if parts:
        p = parts[0]
        d.update(productName=p.get("product_name", ""), partNumberRevision=f"{p['part_number']} Rev {p['rev']}",
                 contactBaseMaterial=p.get("contact_base_material", ""), contactPlating=p.get("contact_plating", ""),
                 housingMaterial=p.get("housing_material", ""))
    if "samples" in values:
        d["quantity"] = str(values["samples"])
    m = re.search(r"\blot\s*(?:#|no\.?|number)?\s*[:=]?\s*([A-Z0-9][\w-]{2,})", text, re.I)
    if m:
        d["traceabilityMfgLotInfo"] = m.group(1)
    bits = []
    for t in sorted(tests):
        s = tools.TEST_DESC[t][0].upper() + tools.TEST_DESC[t][1:]
        if t == "warpage_reflow" and "reflow_peak_c" in values:
            s += f", peak {values['reflow_peak_c']} °C"
        if t == "thermal_cycling" and "cycling_min_c" in values:
            s += f", {values['cycling_min_c']} to {values['cycling_max_c']} °C"
            if "cycles" in values:
                s += f", {values['cycles']} cycles"
            if "readout_every" in values:
                s += f", readouts every {values['readout_every']} cycles"
        if t == "temperature_rise" and "currents_a" in values:
            s += ", at " + ", ".join(f"{a} A" for a in values["currents_a"])
            if "wire_awg" in values:
                s += f", {values['wire_awg']} AWG wire"
            if "trise_limit_c" in values:
                s += f", rise limit {values['trise_limit_c']} °C above ambient"
        if t == "llcr":
            s += ", dry circuit (20 mV open circuit, 100 mA max)"
        if t == "flatness_rt" and "acceptance_limit_mm" in values:
            s += f", acceptance limit {values['acceptance_limit_mm']} mm"
        bits.append(s + ".")
    for o in out_of_scope:       # no procedure here: name the test, the lab defines method and conditions
        bits.append(f"{o[0].upper() + o[1:]} (method and conditions to be defined by the lab).")
    order = values.get("_order") or G.sequence(text, tests)
    if len(order) > 1:           # several steps: write them in the order the engineer asked for
        by_test = dict(zip(sorted(tests), bits[:len(tests)]))
        steps = ["Unmate the connectors." if k == "_unmate" else
                 by_test.get(k, "").replace("(LLCR)", "(LLCR) on the mated connectors", 1) if k == "llcr" and "_unmate" in order and order.index(k) < order.index("_unmate") else
                 by_test.get(k, "") for k in order] + bits[len(tests):]
        bits = [f"{i + 1}. {x}" for i, x in enumerate(x for x in steps if x)]
        bits.insert(0, "Sequence:")
    d["testsToBePerformed"] = " ".join(bits)
    m = re.search(r"[^.]*\b(objective|purpose|goal|to (confirm|compare|check|verify|qualify|determine|decide)|so (that|we))\b[^.]*\.?", text, re.I)
    if m:
        d["objective"] = m.group(0).strip()
    # Without the model, keep the engineer's own words so no detail is lost (profile, datum, storage, ...).
    if tests or parts or out_of_scope:
        d["additionalInformation"] = "Details from the request: " + re.sub(r"\s+", " ", text).strip()[:1500]
    return d


# Questions about the assistant itself. Only counted when the message is a question (so "only 2 samples available"
# in a request is not one).
CAPS = re.compile(r"\bavailable\b|\bsupport(ed|s)?\b|what (can|do|could) you|what (kinds?|types?|sorts?) of|"
                  r"\b(what|which) (lab )?(requests?|forms?|tests?|procedures?|methods?|documents?|standards?)\b|"
                  r"list (of )?(your |the )?(tests|procedures|requests|forms)|\bhelp\b|capabilit|how (do|does) (this|it|you) work", re.I)
# A new test in a later message: "another/new/separate ... request" starts over; "add/also/then" adds to the current one.
NEW_REQ = re.compile(r"\b(new|separate|another|different|second|fresh)\b[^.]{0,40}\b(request|test|one|draft)\b|\bstart (a )?new\b|\bstart over\b", re.I)
ADD_REQ = re.compile(r"\b(add|also|as well|plus|in addition|and then|after that|followed by|then|too)\b", re.I)
QUESTION = re.compile(r"\?\s*$|^\s*(what|which|how|can|could|do|does|is|are|list|show|tell|help)\b", re.I)


def library():
    """The active procedures the assistant can cite (SYNTHETIC), from the documents' own headers."""
    docs = []
    for d in (tools.ROOT / "docs", tools.ROOT / "docs_extended"):
        for f in sorted(d.glob("*.md")):
            head = f.read_text(encoding="utf-8").split("---")[1] if f.read_text(encoding="utf-8").startswith("---") else ""
            meta = dict(l.split(":", 1) for l in head.strip().splitlines() if ":" in l)
            meta = {k.strip(): v.strip() for k, v in meta.items()}
            if meta.get("status") == "active":
                docs.append(meta)
    return docs


def _capabilities():
    lines = ["Request forms: I draft and review the General lab form. On the SMT lab, Machine shop and Purchase req forms you "
             "fill the fields yourself and Check quality reviews them.",
             "Tests I can draft and check against a procedure:"]
    lines += [f"- {d[0].upper() + d[1:]}" for d in tools.TEST_DESC.values()]
    lines.append("Procedures I can cite (SYNTHETIC library, active revisions only):")
    lines += [f"- {d['doc_id']} Rev {d['revision']}: {d['title']}" for d in library()]
    lines.append("For any other test (for example CT scan, humidity, vibration, salt spray) I still draft the request in your words and ask for the "
                 "part, samples and purpose, but the lab defines the method. To ask for a procedure to be added, use "
                 "Give feedback on this, then Suggest a missing question or check.")
    return lines


def _question_lines(questions, head):
    """Must-answer questions first, numbered; then the optional ones under their own heading."""
    must = [q for q in questions if q["blocking"]]
    nice = [q for q in questions if not q["blocking"]]
    lines = []
    if must:
        lines += [head] + [f"{i + 1}. {q['question']}" for i, q in enumerate(must)]
    if nice:
        lines += ["Also useful:" if must else head] + [f"{len(must) + i + 1}. {q['question']}" for i, q in enumerate(nice)]
    return lines


def _split_reply(out, lines, a, b, head):
    """The page shows the questions as separate items (each can be rated): text before them, the heading, text after."""
    out["reply_parts"] = {"before": lines[:a], "questions_head": head, "after_index": b}


def _ai_mode():
    from assistant import llm
    m = model_info()
    if m and (m["where"] != "this computer" or len(llm.MODELS) > 1):     # name the model actually used
        return f"AI ({llm.CURRENT} · {m['where']})"
    return f"AI ({m['label']})" if m else "AI (model name not reported)"


def form_text(fields):
    """The engineer's own entries on the form, as text (contact details left out)."""
    out = []

    def walk(k, v):
        if k in CONTACT or k.startswith("_"):
            return
        if isinstance(v, dict):
            for kk, vv in v.items():
                walk(kk, vv)
        elif isinstance(v, list):
            for x in v:
                walk(k, x)
        elif isinstance(v, str) and v.strip() and v.strip().lower() not in ("yes", "no", "-- select --"):
            out.append(f"{k}: {v.strip()}")
    walk("", fields or {})
    return "\n".join(out)[:6000]


def _rule_review(tests, out_of_scope, cites, flags, ftext):
    bullets = []
    if tests:
        bullets.append("The draft asks for " + ", ".join(tools.TEST_DESC[x] for x in sorted(tests)) + "; I checked it against "
                       + ", ".join(dict.fromkeys(f"{c['doc_id']} Rev {c['revision']}" for c in cites)) + ".")
    elif out_of_scope:
        bullets.append("The test in the draft (" + ", ".join(out_of_scope) + ") has no procedure in my library, so I can only "
                       "check completeness; the lab defines its requirements.")
    else:
        bullets.append("I could not match the test in the draft to a procedure in my library (warpage during reflow, thermal "
                       "cycling, room-temperature flatness, temperature rise), so I can only check completeness. Name the test and its "
                       "conditions in Tests to be Performed.")
    if not re.search(r"\b(objective|purpose|to (confirm|compare|check|verify|qualify|determine|decide|support)|so (that|we))\b", ftext, re.I):
        example = {"temperature_rise": "confirm the 10 A rating before release, or compare two contact platings",
                   "warpage_reflow": "release the new mold, or compare two resin lots",
                   "thermal_cycling": "qualify the part for the automotive temperature range",
                   "flatness_rt": "accept a new molding cavity"}.get(sorted(tests)[0] if tests else "", "release a design change, or compare two options")
        bullets.append(f"State the decision the results support (for example: {example}); it tells the lab what matters most in the report.")
    errs = [f["message"] for f in flags if f["severity"] == "error"]
    if errs:
        bullets.append(f"{len(errs)} must-fix item(s) before the lab can schedule it; they are listed under Still to fix.")
    return bullets


def _model_review(ftext, cites, flags, question, trace):
    from assistant import llm
    ctx = "\n".join(f"[{c['doc_id']} Rev {c['revision']} - {c['section'].split(' - ')[-1]}] {c['snippet']}" for c in cites) or "none"
    found = "\n".join(f"- {f['message']}" for f in flags[:10]) or "none"
    user = (G.wrap_untrusted("DRAFT REQUEST", ftext) + "\n" + G.wrap_untrusted("ENGINEER'S QUESTION", question) +
            f"\nCITED PROCEDURE PASSAGES:\n{ctx}\nQUALITY-CHECK FINDINGS:\n{found}")
    reply = llm.chat([{"role": "system", "content": SYSTEM_REVIEW}, {"role": "user", "content": user}], trace, "reviewer",
                     max_tokens=500, label="review_draft")
    return [re.sub(r"^\s*[-*•\d.)]+\s*", "", l).strip() for l in (reply or "").splitlines() if re.match(r"^\s*([-*•]|\d+[.)])\s+\S", l)]


def _model_draft(convo, tests, trace):
    from assistant import llm
    user = G.wrap_untrusted("CONVERSATION", convo) + "\nRecognised tests: " + (", ".join(tools.TEST_DESC[t] for t in sorted(tests)) or "none")
    reply = llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], trace, "coordinator",
                     max_tokens=600, label="draft_fields")
    d = llm.first_json(reply)
    if not isinstance(d, dict):
        return None
    return {k: str(d.get(k, "") or "").strip()[:1500] for k in FIELD_KEYS}


def assist(message, history=None, form_key="lab_test_request", fields=None, use_model=True, trace=None, model=None):
    trace = trace or Trace()
    fields = fields or {}
    from assistant import llm as _llm_pick
    trace.log("coordinator", "model", model=_llm_pick.use(model))     # only a model from the allowed list
    history = [h for h in (history or []) if h.get("role") in ("user", "assistant")][-12:]
    out = {"run_id": trace.run_id, "state": "incomplete", "reply": "", "questions": [], "citations": [], "proposed": {},
           "changes": [], "flags": [], "escalations": [], "warnings": [], "mode": "", "tests": [], "out_of_scope": [],
           "field_sources": {}, "review_points": [], "choices": []}
    # field_sources / review_points say who wrote each value or remark: "ai" (the local model, after the guardrail
    # checks), "rule" (fixed rules), "procedure" (copied from a cited procedure), "parts" (the parts directory).
    if form_key != "lab_test_request":
        out["reply"] = ("The assistant drafts the general lab request for now. Switch to the General lab form, or fill this "
                        "form by hand and use Check quality.")
        return out

    # 1. guard
    msg, findings = G.screen_untrusted(message, MAX_MESSAGE_CHARS)
    trace.log("coordinator", "guardrail_screen", findings=findings, chars=len(msg))
    if findings:
        out["warnings"] += [f"Your message {f}. It was treated as information only." for f in findings]
    if DISCLOSE.search(msg):
        trace.log("coordinator", "guardrail_refusal", reason="disclosure")
        out["reply"] = ("I can't show system instructions, keys, accounts, other people's drafts or private files. "
                        "Describe the test you need and I'll help draft the request.")
        out["state"] = "refused"
        return out
    if SUBMIT.search(msg):
        trace.log("coordinator", "guardrail_refusal", reason="submit")
        out["warnings"].append("Nothing is submitted from here. When the draft is ready, review it and enter it on the "
                               "lab's request form yourself.")
    # A question about the assistant itself ("what tests are available?") gets a direct answer; nothing is drafted.
    asked_tests, asked_oos = G.detect_tests(msg)
    warp_q = G.warpage_unclear(msg)
    if (asked_tests or asked_oos or warp_q) and QUESTION.search(msg) and not re.search(r"\d", msg) and \
            re.search(r"\b(available|support\w*|do you (have|do|know|cover)|can you (do|run|handle|draft)|is there a procedure)\b", msg, re.I):
        # "Are SEM and FTIR available?": answer for those tests; nothing is drafted.
        from assistant import registry
        lines = []
        for k in sorted(asked_tests):
            doc = registry.source(k) if k in registry.BY_KEY else next((f"{c['doc_id']} Rev {c['revision']}" for c in [tools.retrieve(k, "required_inputs", trace)] if c), "")
            lines.append(f"Yes: {tools.TEST_DESC[k]}" + (f", procedure {doc}." if doc else "."))
        if warp_q:
            lines.append("Yes: warpage, two procedures: during a reflow temperature profile (SYN-TM-101 Rev C) and at room "
                         "temperature as flatness (SYN-TM-104 Rev A).")
        lines += [f"{o[0].upper() + o[1:]}: no procedure in my library; I can still draft it in your words and the lab defines the method." for o in asked_oos]
        lines.append("Describe the part, the number of samples and the conditions, and I'll draft the request and ask what the procedure needs.")
        out.update(reply="\n".join(lines), state="info", tests=sorted(asked_tests), out_of_scope=asked_oos, summary=trace.summary())
        return out
    if CAPS.search(msg) and QUESTION.search(msg) and not REVIEW.search(msg) and not any(G.detect_tests(msg)):
        out["reply"] = "\n".join(_capabilities())
        out["state"] = "info"
        trace.log("coordinator", "capabilities")
        out["summary"] = trace.summary()
        return out
    # A test not in the current conversation: add it, or start a separate request? (The engineer decides.)
    prev_user = [h["content"] for h in history if h["role"] == "user"]
    cur_tests, cur_oos = G.detect_tests(msg)
    prev_tests, prev_oos = G.detect_tests(" ".join(prev_user)) if prev_user else (set(), [])
    newcomer = sorted(cur_tests - prev_tests) + [o for o in cur_oos if o not in prev_oos]
    if newcomer and (prev_tests or prev_oos):
        names = ", ".join(tools.TEST_SHORT.get(k, k) for k in newcomer)
        if NEW_REQ.search(msg):
            history, prev_user = [], []                 # a separate request: earlier messages no longer count
            out["choices"] = [{"label": "Start a new draft for this request (the current one stays in My drafts)", "send": msg, "action": "new_draft"}]
            out["new_request"] = True
        elif not ADD_REQ.search(msg) and not REVIEW.search(msg):
            out.update(state="info", reply=f"Do you want {names} added to the current request, or as a separate request?\n"
                       "1. Add it to the current request\n2. Start a separate request (the current draft stays in My drafts)")
            out["choices"] = [{"label": f"Add {names} to the current request", "send": "Add to this request: " + msg},
                              {"label": f"Start a separate {names} request", "send": msg, "action": "new_draft"}]
            out["summary"] = trace.summary()
            return out
    user_text = "\n".join(prev_user + [msg])
    convo = "\n".join(f"{h['role']}: {h['content']}" for h in history) + f"\nuser: {msg}"
    ftext = form_text(fields)                      # what the engineer already entered on the form
    both = user_text + "\n" + ftext
    t = both.lower()

    # 2. scope: the tests in the message and in the draft on the form
    msg_tests, msg_oos = G.detect_tests(user_text)
    # Review the draft when asked to, or when a real message names no test but the form has one.
    # Review the draft when asked to, or for another question about it when the message names no test.
    review = bool(ftext) and (bool(REVIEW.search(msg)) or (not G.detect_tests(msg)[0] and not G.detect_tests(msg)[1] and bool(QUESTION.search(msg))))
    out["review"] = review
    if review:                                     # the tests and values come from the draft and the message
        tests, out_of_scope = G.detect_tests(both)
        values = G.parse_values(both)
    else:                                          # a new or added request: what the engineer is asking now
        tests, out_of_scope = msg_tests, msg_oos
        values = G.parse_values(user_text)
        t = user_text.lower()
    out["tests"], out["out_of_scope"] = sorted(tests), out_of_scope
    trace.log("coordinator", "scope", tests=sorted(tests), out_of_scope=out_of_scope, values=values)
    for o in out_of_scope:
        out["escalations"].append(G.escalate({"escalations": [], "trace": trace}, "OUT_OF_SCOPE", o, "coordinator"))

    # 3. cite
    cites = []
    for test in sorted(tests):
        for section in ("required_inputs", "sample_quantity", "test_sequence", "reporting"):
            c = tools.retrieve(test, section, trace)
            if c and not any(x["doc_id"] == c["doc_id"] and x["section"] == c["section"] for x in cites):
                cites.append({**c, "test": test, "snippet": re.sub(r"\s+", " ", c["text"])[:280]})
    out["citations"] = [{k: c[k] for k in ("doc_id", "revision", "section", "snippet", "test")} for c in cites]

    parts = tools.lookup_part(user_text, trace) or (tools.lookup_part(ftext, trace) if ftext else [])
    if parts:
        values["_part_found"] = True
    # 4. ask
    needs = [r for test in sorted(tests) for r in G.REQUIRED_INPUTS.get(test, [])]
    if tests or out_of_scope:
        needs = G.REQUIRED_INPUTS["_general"][:2] + needs + G.REQUIRED_INPUTS["_general"][2:]
    if tests & {"warpage_reflow", "thermal_cycling"}:
        needs += G.REQUIRED_INPUTS["_elevated"]
    order = _latest_order([h["content"] for h in history if h["role"] == "user"] + [msg], tests)
    values["_order"] = order
    if "llcr" in tests and "_unmate" in order and order.index("_unmate") < order.index("llcr"):
        needs.insert(0, ("llcr_mated", "SYN-TM-130 Rev A", "LLCR is measured on mated contacts. Should the LLCR readings be taken before the "
                         "connectors are unmated (or after re-mating them), with the inspection on the unmated contact areas afterwards?", True))
        ANSWERED.setdefault("llcr_mated", lambda t, v: re.search(r"before (un|de)-?mat|re-?mat(e|ed|ing)|while mated|on mated|mated (llcr|reading)", t))
    seen = set()
    for key, src, question, blocking, *when in needs:
        if when and not when[0](t, values):          # a setup question that does not apply to this request
            continue
        if key in seen or ANSWERED.get(key, lambda *_: False)(t, values):
            continue
        seen.add(key)
        out["questions"].append({"key": key, "question": question, "source": src, "blocking": blocking})
    trace.log("coordinator", "questions", keys=[q["key"] for q in out["questions"]])

    # 5. draft
    from assistant import llm as _llm
    draft, mode = None, "rules"
    if use_model and _llm.STUB:
        mode = "demo: no AI (fixed rules)"
    elif use_model and review:
        mode = _ai_mode()                           # the model writes the review below, not field values
    elif use_model and not tests and not parts and not out_of_scope:
        mode = "no AI draft (the test is not clear yet)"   # ask first; the model does not draft a test the rules cannot name
    elif use_model:
        try:
            draft = _model_draft(convo, tests, trace)
            mode = _ai_mode() if draft else "no AI: fixed rules (the AI's reply was not usable)"
        except Exception as e:                       # ModelUnavailable or a bad reply: fall back, say so
            trace.log("coordinator", "llm_fallback", error=str(e)[:300])
            mode = "no AI: fixed rules (the AI model did not answer)"
    rules = _rule_draft(user_text, values, tests, parts, out_of_scope)
    src = {k: "rule" for k in FIELD_KEYS}
    if review:                                    # reviewing: keep the engineer's entries; only fill specs/revisions below
        rules = {k: "" for k in FIELD_KEYS}
    if draft is None:
        draft = rules
    else:
        for k in FIELD_KEYS:                          # grounding: numbers the engineer did not write are dropped
            ok, missing = _grounded_text(draft[k], both)
            if not ok:
                trace.log("coordinator", "guardrail_grounding", field=k, numbers=missing)
                out["warnings"].append(f"The model wrote {', '.join(missing)} in {k}, which you did not give; that value was not used.")
                draft[k] = rules[k]
            elif not draft[k] and rules[k]:
                draft[k] = rules[k]
            elif draft[k]:
                src[k] = "ai"
        if parts:                                     # the parts directory beats the model for part data
            for k in ("productName", "partNumberRevision", "contactBaseMaterial", "contactPlating", "housingMaterial"):
                if rules[k]:
                    draft[k], src[k] = rules[k], "parts"
    if parts:
        for k in ("productName", "partNumberRevision", "contactBaseMaterial", "contactPlating", "housingMaterial"):
            if draft[k] and draft[k] == rules[k] and src[k] == "rule":
                src[k] = "parts"
    cal = calibration(draft["testsToBePerformed"] + " " + draft["objective"])
    if cal["markers"]:
        trace.log("coordinator", "guardrail_calibration", **{k: cal[k] for k in ("markers", "score", "verdict")})
        out["warnings"].append("Absolute wording was softened: " + ", ".join(cal["markers"]) + ".")
        draft["testsToBePerformed"] = calibration(draft["testsToBePerformed"])["hedged"]
        draft["objective"] = calibration(draft["objective"])["hedged"]
    out["mode"] = mode

    # Build the proposal in the form's own shape. Specifications and revisions come from the citations, not the model.
    proposed = {}
    sample = {k: draft.get(k, "") for k in SAMPLE_KEYS}
    if any(sample.values()):
        proposed["step2_rows"] = [sample]
    if draft["testsToBePerformed"] or (review and cites):
        docs = list(dict.fromkeys(c["doc_id"] for c in cites))
        revs = list(dict.fromkeys(f"{c['doc_id']} Rev {c['revision']}" for c in cites))   # the form's format: doc + revision
        proposed["step3_rows"] = [{"testsToBePerformed": "" if review else draft["testsToBePerformed"],
                                   "applicableSpecifications": "; ".join(docs), "specificationRevision": "; ".join(revs)}]
    obj, more = draft["objective"], draft["additionalInformation"]
    info = more if obj and obj.rstrip(".") in more else " ".join(x for x in (obj, more) if x).strip()
    if info and not review:
        proposed["additionalInformation"] = info
    # Only fill what is empty in the current draft; never overwrite the engineer's own entries.
    merged = json.loads(json.dumps(fields))
    for k, v in proposed.items():
        if k.endswith("_rows"):
            cur = merged.get(k) or []
            if not any(any(str(x).strip() for x in r.values()) for r in cur):
                merged[k] = v
                out["changes"].append(k)
            else:
                row0 = cur[0]
                for ck, cv in v[0].items():
                    if cv and not str(row0.get(ck, "")).strip():
                        row0[ck] = cv
                        out["changes"].append(f"{k}.{ck}")
        elif v and not str(merged.get(k, "")).strip():
            merged[k] = v
            out["changes"].append(k)
    out["proposed"] = merged
    # Never overwritten: if the form already has a different test description, say so and show the new one to paste.
    new_t = (proposed.get("step3_rows") or [{}])[0].get("testsToBePerformed", "")
    cur_t = str(((fields.get("step3_rows") or [{}])[0] or {}).get("testsToBePerformed", "")).strip()
    if new_t and cur_t and new_t != cur_t and not review:
        out["warnings"].append("Your form already has Tests to be Performed, so I did not change it. If it should change, "
                               "replace it with: " + new_t)
    for c in out["changes"]:
        k, _, col = c.partition(".")
        cols = [col] if col else [x for x, v in (proposed[k][0] if k.endswith("_rows") else {}).items() if v]
        if not k.endswith("_rows"):
            out["field_sources"][k] = "ai" if "ai" in (src["objective"], src["additionalInformation"]) else "rule"
        for x in cols:
            out["field_sources"][f"{k}.{x}"] = "procedure" if x in ("applicableSpecifications", "specificationRevision") \
                else src.get(x, "rule")

    # 6. check
    q = quality.review(form_key, merged)
    contact = {"firstName", "lastName", "email", "phone", "bPCNumber", "businessUnit", "mFGSite"}
    out["flags"] = [f for f in q["flags"] if f["severity"] in ("error", "warn") and f["field"] not in contact][:12]
    if any(f["field"] in contact and f["severity"] == "error" for f in q["flags"]):
        out["flags"].insert(0, {"severity": "error", "field": "firstName", "step": 1, "row": None, "message":
                                "Your name, contact and business details are still empty (step 1).", "why": "", "fix": None, "source": "Request form"})
    out["readiness"] = q["readiness"]
    trace.log("reviewer", "quality", errors=q["errors"], warnings=q["warnings"])

    # 7. state
    blocking = [x for x in out["questions"] if x["blocking"]] or [e for e in out["escalations"] if e["severity"] == "block"]
    out["state"] = "incomplete" if blocking or q["errors"] else "ready for review"
    trace.log("coordinator", "state", state=out["state"], mode=mode)

    files_note = None
    if "temperature_rise" in tests and G.BOARD.search(t) and G.BOARD_FILES.search(t):
        files_note = ("The board files you listed cover the routing, current entry and exit, thermocouple holes and copper. "
                      "I can't open them; the lab reviewer checks them.")
    elif "temperature_rise" in tests and G.BOARD.search(t):
        files_note = ("Tip (recommended, not required): list the test board files under Attachments (schematic and layout as "
                      "PDF; Gerber or ODB++ by link). They answer the routing, thermocouple-hole and copper questions below, "
                      "and the lab reviewer can check them directly.")

    # Review of the draft on the form: the model's critique (checked) or the rules' critique.
    if review:
        bullets, how = [], "rules"
        if use_model and not _llm.STUB:
            try:
                raw = _model_review(ftext, cites, out["flags"], msg, trace)
                ids = {c["doc_id"] for c in cites}
                src = both + " " + " ".join(c["text"] for c in cites)
                dropped = 0
                for b in raw[:6]:
                    # a prediction of the result (will pass, guaranteed ...) is removed, not reworded
                    b = " ".join(x for x in re.split(r"(?<=[.!?])\s+", b) if not calibration(x)["markers"]).strip()
                    if not b:
                        dropped += 1
                        continue
                    bad_ids = [x for x in re.findall(r"\b[A-Z]{2,5}-[A-Z]{2,4}-\d{2,4}\b", b) if x not in ids and x not in both]
                    ok, missing = _grounded_text(b, src)
                    if bad_ids or not ok:
                        trace.log("reviewer", "guardrail_grounding", text=b[:200], numbers=missing, ids=bad_ids)
                        dropped += 1
                        continue
                    bullets.append(b[:400])
                if dropped:
                    out["warnings"].append(f"{dropped} point(s) of the AI's review were left out: they used a number or "
                                           "procedure that is not in your draft or the cited procedures, or predicted the result.")
                how = _ai_mode() if bullets else "no AI: fixed rules (the AI's review was not usable)"
            except Exception as e:
                trace.log("reviewer", "llm_fallback", error=str(e)[:300])
                how = "no AI: fixed rules (the AI model did not answer)"
        by = "ai" if bullets else "rule"
        if not bullets:
            bullets = _rule_review(tests, out_of_scope, cites, out["flags"], ftext)
        out["mode"] = mode = how if not _llm.STUB else mode
        out["review_points"] = [{"text": b, "by": by} for b in bullets]
        lines = ["Here is my review of the draft on the form:"] + ([files_note] if files_note else [])
        if out["questions"]:
            qa = len(lines)
            lines += _question_lines(out["questions"], "The procedure also needs:")
            _split_reply(out, lines, qa, len(lines), "The procedure also needs:")
        if out["changes"]:
            lines.append(f"I can fill {len(out['changes'])} empty field(s) from the cited procedures: review, then Apply to form.")
        lines.append("Nothing is submitted.")
        out["reply"] = "\n".join(lines)
        if "reply_parts" in out:
            out["reply_parts"]["after"] = lines[out["reply_parts"].pop("after_index"):]
        out["summary"] = trace.summary()
        return out

    # Reply in plain words.
    lines = []
    if tests:
        lines.append("I recognised: " + ", ".join(tools.TEST_DESC[x] for x in sorted(tests)) + ".")
    new_oos = G.detect_tests(msg)[1]
    for o in out_of_scope:
        if o in new_oos:          # said once, when first named; not repeated on every later turn
            lines.append(f"'{o}' has no procedure in my library: I drafted it in your words, and the lab will define the method.")
    _, typo = G.normalize_terms(msg)
    if typo:
        lines.insert(0, "I read " + ", ".join(f"'{a}' as '{b}'" for a, b in typo) + ".")
    if not tests and not out_of_scope and G.warpage_unclear(user_text):
        lines.append("Which warpage test do you mean?")
        out["choices"] = [
            {"label": "Warpage over a temperature profile (reflow simulation, shadow moiré)", "send": "warpage over a reflow temperature profile"},
            {"label": "Room-temperature flatness (coplanarity at 25 °C)", "send": "room-temperature flatness"}]
        lines += [f"{i + 1}. {c['label']}" for i, c in enumerate(out["choices"])]
    elif not tests and not out_of_scope and ftext:
        lines.append("Ask me to review the draft on the form (for example: what do you think of this request?), or "
                     "describe a test to add: the test, its conditions, the part and how many samples.")
    elif not tests and not out_of_scope:
        lines.append("I couldn't tell which test you need. Name the test (for example warpage during reflow, thermal "
                     "cycling, room-temperature flatness or temperature rise), the part and how many samples.")
    if files_note:
        lines.append(files_note)
    if out["changes"]:
        lines.append(f"I drafted {len(out['changes'])} field(s) from what you wrote" +
                     (f" and cited {len(cites)} procedure passage(s)." if cites else "."))
    if out["questions"]:
        qa = len(lines)
        lines += _question_lines(out["questions"], "Before the lab can schedule this, please answer:")
        _split_reply(out, lines, qa, len(lines), "Before the lab can schedule this, please answer:")
    elif tests:
        lines.append("The procedure's required inputs are covered.")
    elif out_of_scope:
        lines.append("The part, samples and purpose are covered; the lab will define the method for these tests.")
    if out["changes"]:
        lines.append("Review the proposal, then Apply to form. Nothing is submitted.")
    out["reply"] = "\n".join(lines)
    if "reply_parts" in out:
        out["reply_parts"]["after"] = lines[out["reply_parts"].pop("after_index"):]
    out["summary"] = trace.summary()
    return out


_MODEL_CACHE = {"t": 0.0, "info": None}


def model_info(max_age=20):
    """What AI model is actually serving, asked from the server itself (cached for a few seconds).
    The local Qwen server's /health names the model, its quantization and the GPU; other OpenAI-style servers
    only list model ids at /models. Returns None when no model answers."""
    if time.time() - _MODEL_CACHE["t"] < max_age:
        return _MODEL_CACHE["info"]
    from assistant import llm
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    host = llm.BASE_URL.split("//", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0].strip("[]")
    where = "this computer" if host in ("127.0.0.1", "localhost", "::1") else host
    info = None
    try:
        root = re.sub(r"/v1/?$", "", llm.BASE_URL.rstrip("/"))
        with opener.open(root + "/health", timeout=2) as r:
            h = json.loads(r.read() or b"{}")
        if h.get("model"):
            info = {"name": str(h["model"]), "quantization": str(h.get("quantization") or ""), "device": str(h.get("device") or ""), "where": where}
    except Exception:
        pass
    if info is None:
        try:
            req = urllib.request.Request(llm.BASE_URL.rstrip("/") + "/models", headers=llm.headers())
            remote = opener if llm.LOCAL else urllib.request.build_opener()     # a remote service may need the proxy
            with remote.open(req, timeout=2 if llm.LOCAL else 6) as r:
                ids = [m.get("id") for m in json.loads(r.read() or b"{}").get("data", []) if m.get("id")]
            info = {"name": llm.MODEL if llm.MODEL in ids or not ids else ids[0], "quantization": "", "device": "", "where": where}
        except Exception:
            info = None
    if info:
        short = info["name"].split("/")[-1]
        q = {"4bit": "4-bit", "8bit": "8-bit", "none": "full precision", "": ""}.get(info["quantization"].lower(), info["quantization"])
        info["short"] = short
        info["label"] = " · ".join(x for x in (short, q, info["device"], info["where"]) if x)
    _MODEL_CACHE.update(t=time.time(), info=info)
    return info


import lrt_version as _lrt_version
RUNNING_VERSION = _lrt_version.text()     # the code this server loaded; VERSION on disk may be newer after a git pull


def status():
    """Which mode the assistant runs in right now, and which AI model: demo (stub), a model, or rules because none answers."""
    from assistant import llm
    import lrt_version
    v = RUNNING_VERSION
    on_disk = lrt_version.text()
    stale = None if on_disk == v else (f"The tool was updated ({on_disk} on disk) but this server is still running {v}. "
                                       "Run stop.bat, then start.bat, then refresh the page.")
    if llm.STUB:
        return {"mode": "demo", "label": "Demo mode: no AI. Drafts are built by fixed rules (start.bat without demo uses the AI).",
                "model": None, "model_label": "none (demo mode)", "version": v, "stale": stale}
    m = model_info(max_age=0)
    if m:
        label = f"AI on: {m['label']}."
        if m["where"] != "this computer":
            label += (f" Your messages and the draft on the form are sent to {m['where']}. Use only data your "
                      "organisation allows there (SYNTHETIC data for the course).")
        return {"mode": "model", "label": label, "model": llm.MODEL, "model_label": m["label"], "version": v, "remote": m["where"] != "this computer",
                "models": llm.MODELS if len(llm.MODELS) > 1 else [], "where": m["where"], "stale": stale}
    return {"mode": "offline", "label": ("No AI: the local AI model is not running, so drafts are built by fixed rules. Start it with start.bat; "
                      "if it is installed in another folder, point to it in local_settings.bat."),
            "model": None, "model_label": "none running", "version": v, "stale": stale}


if __name__ == "__main__":     # python -m assistant.chat "Measure warpage on 10 SYN-10001 housings through reflow, peak 260 C"
    import sys
    r = assist(" ".join(sys.argv[1:]) or "Measure warpage on 10 SYN-10001 housings through reflow, peak 260 C")
    print(r["reply"])
    for p in r["review_points"]:
        print(f"  [{p['by']}] {p['text']}")
    print(json.dumps({k: r[k] for k in ("state", "mode", "changes", "field_sources", "warnings")}, indent=1))

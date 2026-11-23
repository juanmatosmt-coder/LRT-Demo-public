"""Feedback from engineers, technicians and lab reviewers on what the assistant should ask and check.

Two kinds of entries, both kept in one append-only log (one JSON object per line):

  rating      on something the assistant or the rule check said (a question, a review point, a quality flag,
              a proposed value): useful / not needed / wrong, with an optional comment
  suggestion  something it should ask or check that it did not: the test, what to ask or check, why (what goes
              wrong without it), how important, an example of a good answer, and where the requirement comes from

Status changes (new, accepted, added, rejected) are appended as their own events, so the log keeps the full history
and the current state is worked out by replaying it.

Feedback never changes the assistant by itself: it is text from people, stored as data. A person reads it and turns
accepted items into rules (assistant/guardrails.py, assistant/quality.py) or procedure text. The text is screened like
any untrusted input and the findings are stored with the entry.

Where: data/private/feedback/feedback.jsonl (never committed). The SYNTHETIC examples in data/synthetic/feedback/
show the format.
"""
import csv
import io
import json
import re
import secrets
import threading
import time
from pathlib import Path

from assistant import guardrails as G
from assistant import tools

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "private" / "feedback" / "feedback.jsonl"
SYNTHETIC = ROOT / "data" / "synthetic" / "feedback" / "feedback.jsonl"
_LOCK = threading.Lock()

ROLES = ["engineer", "technician", "lab reviewer", "other"]
RATINGS = {"useful": "Useful", "not_needed": "Not needed", "wrong": "Wrong"}
TARGETS = ["question", "review_point", "flag", "proposal", "reply", "general"]
ASK_OR_CHECK = ["ask", "check", "both"]
IMPORTANCE = {"must": "Must answer before scheduling", "should": "Should be answered", "nice": "Nice to have"}
SOURCES = ["procedure", "standard", "customer requirement", "lab experience", "other"]
STATUSES = ["new", "accepted", "added", "rejected"]
FORMS = ["lab_test_request", "smt_lab_test_request", "machine_shop_request", "purchase_requisition"]
LIMITS = {"comment": 1000, "text": 1000, "why": 1000, "example": 500, "source_ref": 200, "target_text": 600,
          "target_key": 80, "test_other": 80, "note": 500}


def meta():
    """Choices for the page's feedback controls."""
    return {"roles": ROLES, "ratings": RATINGS, "importance": IMPORTANCE, "sources": SOURCES, "statuses": STATUSES,
            "ask_or_check": ASK_OR_CHECK,
            "tests": [{"key": k, "label": v} for k, v in tools.TEST_DESC.items()] + [{"key": "other", "label": "Other test"}]}


def _s(v, n):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(v or "")).strip()[:n]


def _pick(v, allowed, default=None):
    return v if v in allowed else default


def clean(body, by, context=None):
    """Validate one entry from the page. Returns (entry, error)."""
    if not isinstance(body, dict):
        return None, "feedback must be an object"
    kind = body.get("type")
    tests = [t for t in (body.get("tests") or []) if t in tools.TEST_DESC or t == "other"][:6] if isinstance(body.get("tests"), list) else []
    e = {"id": secrets.token_hex(6), "event": "feedback", "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "type": kind, "by": by,
         "role": _pick(body.get("role"), ROLES, "other"), "form": _pick(body.get("form"), FORMS, "lab_test_request"), "tests": tests,
         "comment": _s(body.get("comment"), LIMITS["comment"])}
    ctx = body.get("context") if isinstance(body.get("context"), dict) else {}
    e["context"] = {"run_id": _s(ctx.get("run_id"), 40), "version": _s(ctx.get("version"), 60), "model": _s(ctx.get("model"), 160),
                    "mode": _s(ctx.get("mode"), 160), **(context or {})}
    if kind == "rating":
        tgt = body.get("target") if isinstance(body.get("target"), dict) else {}
        e["rating"] = _pick(body.get("rating"), RATINGS)
        e["target"] = {"kind": _pick(tgt.get("kind"), TARGETS, "general"), "key": _s(tgt.get("key"), LIMITS["target_key"]),
                       "text": _s(tgt.get("text"), LIMITS["target_text"]), "by": _pick(tgt.get("by"), ["ai", "rule", "procedure", "parts"], "")}
        if not e["rating"]:
            return None, "rating must be useful, not_needed or wrong"
        if not e["target"]["text"]:
            return None, "say what is rated"
    elif kind == "suggestion":
        sg = body.get("suggestion") if isinstance(body.get("suggestion"), dict) else {}
        e["suggestion"] = {"ask_or_check": _pick(sg.get("ask_or_check"), ASK_OR_CHECK, "ask"),
                           "test": _pick(sg.get("test"), list(tools.TEST_DESC) + ["other"], "other"),
                           "test_other": _s(sg.get("test_other"), LIMITS["test_other"]),
                           "text": _s(sg.get("text"), LIMITS["text"]), "why": _s(sg.get("why"), LIMITS["why"]),
                           "importance": _pick(sg.get("importance"), IMPORTANCE, "should"),
                           "example": _s(sg.get("example"), LIMITS["example"]),
                           "source": _pick(sg.get("source"), SOURCES, "lab experience"), "source_ref": _s(sg.get("source_ref"), LIMITS["source_ref"])}
        if len(e["suggestion"]["text"]) < 8:
            return None, "describe what should be asked or checked (at least a few words)"
        if e["suggestion"]["test"] != "other" and e["suggestion"]["test"] not in e["tests"]:
            e["tests"].append(e["suggestion"]["test"])
    else:
        return None, "type must be rating or suggestion"
    # Feedback is data, never instructions: screen it and keep the findings with the entry.
    joined = " ".join([e["comment"], json.dumps(e.get("suggestion", {})), e.get("target", {}).get("text", "")])
    _, findings = G.screen_untrusted(joined, 6000)
    e["screen"] = findings
    return e, None


def append(entry, path=None):
    path = Path(path or PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def set_status(fid, status, by, note="", path=None):
    if status not in STATUSES:
        return None, "status must be one of " + ", ".join(STATUSES)
    if not re.fullmatch(r"[a-f0-9]{12}", str(fid or "")):
        return None, "unknown feedback id"
    if not any(e["id"] == fid for e in entries(path)):
        return None, "unknown feedback id"
    ev = {"event": "status", "id": fid, "status": status, "by": by, "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
          "note": _s(note, LIMITS["note"])}
    return append(ev, path), None


def entries(path=None):
    """Current state: every feedback entry with its latest status and status history."""
    path = Path(path or PATH)
    out, order = {}, []
    if not path.exists():
        return []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event") == "feedback" and ev.get("id") not in out:
            out[ev["id"]] = {**ev, "status": "new", "history": []}
            order.append(ev["id"])
        elif ev.get("event") == "status" and ev.get("id") in out:
            out[ev["id"]]["status"] = ev["status"]
            out[ev["id"]]["history"].append({k: ev.get(k) for k in ("status", "by", "time", "note")})
    return [out[i] for i in order]


def summary(items):
    """Counts that show where the assistant needs work: per test, the most-wanted suggestions and the worst-rated items."""
    by_test, ratings, wanted = {}, {}, []
    for e in items:
        for t in e.get("tests") or ["(none)"]:
            d = by_test.setdefault(t, {"suggestions": 0, "useful": 0, "not_needed": 0, "wrong": 0})
            if e["type"] == "suggestion":
                d["suggestions"] += 1
            elif e.get("rating"):
                d[e["rating"]] += 1
        if e["type"] == "rating":
            k = (e["target"]["kind"], e["target"]["text"][:160])
            r = ratings.setdefault(k, {"kind": k[0], "text": k[1], "by": e["target"].get("by", ""), "useful": 0, "not_needed": 0, "wrong": 0})
            r[e["rating"]] += 1
        elif e["status"] in ("new", "accepted"):
            wanted.append({"id": e["id"], "test": e["suggestion"]["test"], "importance": e["suggestion"]["importance"],
                           "text": e["suggestion"]["text"], "status": e["status"], "role": e["role"]})
    rank = {"must": 0, "should": 1, "nice": 2}
    worst = sorted(ratings.values(), key=lambda r: -(r["wrong"] * 2 + r["not_needed"]))
    return {"total": len(items), "by_test": by_test,
            "by_status": {s: sum(1 for e in items if e["status"] == s) for s in STATUSES},
            "by_role": {r: sum(1 for e in items if e["role"] == r) for r in ROLES},
            "suggestions": sorted(wanted, key=lambda w: (rank[w["importance"]], w["test"])),
            "worst_rated": [r for r in worst if r["wrong"] or r["not_needed"]][:20]}


CSV_COLUMNS = ["id", "time", "status", "type", "role", "by", "form", "tests", "rating", "target_kind", "target_by", "target_text",
               "ask_or_check", "test", "suggestion", "why", "importance", "example", "source", "source_ref", "comment",
               "screen_findings", "model", "version", "run_id"]


def to_csv(items):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for e in items:
        t, sg, c = e.get("target", {}), e.get("suggestion", {}), e.get("context", {})
        row = [e["id"], e["time"], e["status"], e["type"], e["role"], e["by"], e["form"], ";".join(e.get("tests", [])),
               e.get("rating", ""), t.get("kind", ""), t.get("by", ""), t.get("text", ""), sg.get("ask_or_check", ""),
               sg.get("test_other") or sg.get("test", ""), sg.get("text", ""), sg.get("why", ""), sg.get("importance", ""),
               sg.get("example", ""), sg.get("source", ""), sg.get("source_ref", ""), e.get("comment", ""),
               "; ".join(e.get("screen", [])), c.get("model", ""), c.get("version", ""), c.get("run_id", "")]
        # Spreadsheet formula injection: a cell starting with = + - @ is shown as text.
        w.writerow(["'" + x if isinstance(x, str) and x and x[0] in "=+-@\t\r" else x for x in row])
    return buf.getvalue()


def to_markdown(items, title="Lab request feedback"):
    """A short report for the course write-up or a team meeting."""
    s = summary(items)
    lab = lambda k: tools.TEST_DESC.get(k, k)  # noqa: E731
    md = [f"# {title}", "", f"{s['total']} entries: " + ", ".join(f"{v} {k}" for k, v in s["by_status"].items() if v) +
          ". From " + ", ".join(f"{v} {k}" for k, v in s["by_role"].items() if v) + ".", "",
          "## By test", "", "| Test | Suggestions | Useful | Not needed | Wrong |", "|---|---:|---:|---:|---:|"]
    md += [f"| {lab(t)} | {c['suggestions']} | {c['useful']} | {c['not_needed']} | {c['wrong']} |" for t, c in s["by_test"].items()]
    md += ["", "## Most-wanted additions (open)", ""]
    md += [f"- **{w['importance']}** ({lab(w['test'])}, {w['role']}, {w['status']}): {w['text']}" for w in s["suggestions"]] or ["- none"]
    md += ["", "## Rated Not needed or Wrong", ""]
    md += [f"- {w['kind'].replace('_', ' ')}{' [' + w['by'] + ']' if w['by'] else ''}: {w['text']} (not needed {w['not_needed']}, wrong {w['wrong']})"
           for w in s["worst_rated"]] or ["- none"]
    return "\n".join(md) + "\n"


if __name__ == "__main__":     # python -m assistant.feedback [path] [--md]  -> summary of the log
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    items = entries(args[0] if args else None)
    print(to_markdown(items) if "--md" in sys.argv else json.dumps(summary(items), indent=1, ensure_ascii=False))

"""The test registry (data/templates/test_registry.json, SYNTHETIC): one entry per test with its detection words,
its procedure, the inputs that procedure requires, and the sample minimum.

The chat's questions (assistant/chat.py) and the rule check (assistant/quality.py) both come from the same entry,
so they cannot disagree. Adding a test = a procedure in docs_extended/ plus an entry here.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "templates" / "test_registry.json"
NOT = r"(?<!\bno )(?<!\bwithout )(?<!\bnot )"          # "no SEM this time" names a test in order to exclude it


def _load():
    return json.loads(PATH.read_text(encoding="utf-8"))["tests"] if PATH.exists() else []


TESTS = _load()
BY_KEY = {t["key"]: t for t in TESTS}


def current_rev(doc_id):
    """The active revision of a procedure, read from the document header (docs/ or docs_extended/)."""
    for d in (ROOT / "docs", ROOT / "docs_extended"):
        for f in sorted(d.glob(f"{doc_id}_Rev*.md")):
            head = f.read_text(encoding="utf-8").split("---")[1]
            meta = {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in head.strip().splitlines() if ":" in l)}
            if meta.get("status") == "active":
                return meta.get("revision", "")
    return ""


def source(key):
    t = BY_KEY[key]
    return f"{t['doc_id']} Rev {current_rev(t['doc_id'])}"


def detect(text):
    t = text.lower()
    return {k for k, x in BY_KEY.items() if any(re.search(NOT + "(?:" + rx + ")", t, re.I) for rx in x["detect"])}


def answered(inp, text):
    return bool(re.search(inp["answered"], text, re.I))


def missing_inputs(key, text):
    """Inputs of this test's procedure that the text does not answer (for the rule check)."""
    return [i for i in BY_KEY[key]["inputs"] if not answered(i, text)]

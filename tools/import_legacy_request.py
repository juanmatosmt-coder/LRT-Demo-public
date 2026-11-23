#!/usr/bin/env python3
r"""
Import old Word lab requests (the pre-online "SECTION 1 / SECTION 2" form) into the example library.

  python tools\import_legacy_request.py "F:\old requests\*.docx"          -> data/private/lab_requests/
  python tools\import_legacy_request.py old.docx --print                   show the result, write nothing
  python tools\import_legacy_request.py scan.pdf --manual scan.json       a scanned request typed in by hand (see below)

Scanned requests (PDF from a copier) have no text to read reliably. Type the form into a JSON file with
"fields" (same keys as below) and "lab_section", leave names and contact details out, and pass the scan with
--manual: the scan gives the id (from its contents), the JSON gives the values, and everything else is the same.

For each file it:
  1. reads every table cell and every dropdown/date control (Word content controls) in document order;
  2. maps the old fields to the online form's fields (data/templates/lab_request_forms.json, lab_test_request);
  3. removes personal details: names, emails and phone numbers become placeholders, lab initials are dropped;
  4. keeps the lab's own section as evidence (reviewed and accepted, sample condition, dates, related requests);
  5. runs the quality check and stores its flags, so each example shows what was good and what was missing;
  6. writes data/private/lab_requests/<id>.json and adds it to data/private/lab_requests/index.json.
Nothing leaves the computer and nothing is committed (data/private/ is gitignored). The original .docx is not copied.
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "private" / "lab_requests"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w-])(\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?![\w-])")   # separators required: part numbers stay
PLACEHOLDERS = {"choose an item.", "select one", "click or tap to enter a date.", "click or tap here to enter text."}


def _text(el):
    """Text of an element, keeping paragraph breaks as new lines."""
    paras = list(el.iter(W + "p"))
    if not paras:
        return "".join(t.text or "" for t in el.iter(W + "t")).strip()
    def para(p):   # text runs in order; a line break or tab inside a paragraph keeps the words apart
        out = []
        for e in p.iter():
            if e.tag == W + "t":
                out.append(e.text or "")
            elif e.tag in (W + "br", W + "cr"):
                out.append("\n")
            elif e.tag == W + "tab":
                out.append(" ")
            elif e.tag == W + "checkBox":   # legacy form checkbox: ticked = checked, else its default
                ch, de = e.find(W + "checked"), e.find(W + "default")
                v = (ch if ch is not None else de)
                out.append("☒" if v is not None and v.get(W + "val", "1") in ("1", "true") else "☐")
        return "".join(out).strip()
    lines = [para(p) for p in paras]
    return "\n".join(x for x in lines if x).strip()


def read_docx(path):
    """Rows of cell texts (dropdown and date values included) and the controls in document order."""
    import docx  # python-docx
    d = docx.Document(str(path))
    body = d.element.body
    controls = []
    for sdt in body.iter(W + "sdt"):
        pr = sdt.find(W + "sdtPr")
        content = sdt.find(W + "sdtContent")
        kind = "dropdown" if pr is not None and (pr.find(W + "dropDownList") is not None or pr.find(W + "comboBox") is not None) else \
               "date" if pr is not None and pr.find(W + "date") is not None else "text"
        alias = pr.find(W + "alias") if pr is not None else None
        placeholder = pr is not None and pr.find(W + "showingPlcHdr") is not None
        val = _text(content) if content is not None else ""
        controls.append({"kind": kind, "alias": alias.get(W + "val") if alias is not None else "",
                         "value": "" if placeholder or val.lower() in PLACEHOLDERS else val})
    tables = []
    for tbl in body.iter(W + "tbl"):
        rows = []
        for tr in tbl.findall(W + "tr"):     # this table's own rows (nested tables are read on their own)
            cells = []
            for child in tr:
                if child.tag == W + "tc":
                    cells.append(_text(child))
                elif child.tag == W + "sdt":   # a cell wrapped in a content control
                    cells += [_text(tc) for tc in child.iter(W + "tc")]
            rows.append(cells)
        tables.append(rows)
    return tables, controls


def body_images(path):
    """Pictures placed in the request itself (photos, marked-up drawings). The form's logo lives in the page header."""
    import zipfile
    with zipfile.ZipFile(as_docx(path)) as z:
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8", "replace") if "word/_rels/document.xml.rels" in z.namelist() else ""
    return sorted(set(re.findall(r'Target="(media/[^"]+)"', rels)))


def label_values(tables):
    """{label: value} for cells that end with ':' followed (after any empty spacer cells) by a value cell."""
    out = {}
    for rows in tables:
        for cells in rows:
            for i, c in enumerate(cells):
                if not c.endswith(":"):
                    continue
                nxt = next((x for x in cells[i + 1:] if x), "")
                if nxt and not nxt.endswith(":") and nxt.lower() not in PLACEHOLDERS:
                    out.setdefault(c[:-1].strip().lower(), nxt)
    return out


# Sample table columns by header words; versions of the form order and name them differently.
SAMPLE_COLUMNS = [("productName", r"product name|sample name|designation|^description"), ("partNumberRevision", r"part num|part #"),
                  ("traceabilityMfgLotInfo", r"traceability|lot"), ("contactBaseMaterial", r"base"), ("contactPlating", r"plating"),
                  ("contactLubricant", r"lubricant"), ("housingMaterial", r"housing"), ("quantity", r"quantity|qty"),
                  ("material", r"^material"), ("manufacturer", r"manufacturer|supplier"), ("condition", r"condition")]


def sample_rows(tables, names):
    for rows in tables:
        head = [h.lower().replace("\n", " ").strip() for h in (rows[0] if rows else [])]
        lot = any(re.search(r"traceability|lot", h) for h in head)
        named = any(re.search(r"product|sample name|part n|designation|description", h) for h in head)
        if len(head) < 4 or not (lot or (named and any(re.search(r"quantity|qty", h) for h in head))):
            continue
        cols = {}
        for key, rx in SAMPLE_COLUMNS:
            i = next((i for i, h in enumerate(head) if re.search(rx, h) and i not in cols.values()), None)
            if i is not None:
                cols[key] = i
        out = []
        for row in rows[1:]:
            if len(row) >= len(head) - 1 and any(c.strip() for c in row):
                row = [redact(c.replace("\n", " "), names) for c in row]
                rec = {k: (row[i] if i < len(row) else "") for k, i in cols.items()}
                out.append({k: rec.get(k, "") for k in ("productName", "partNumberRevision", "traceabilityMfgLotInfo", "contactBaseMaterial",
                                                        "contactPlating", "contactLubricant", "housingMaterial", "quantity")}
                           | {k: rec[k] for k in ("material", "manufacturer", "condition") if rec.get(k)})
        return out
    return []


def table_after(tables, header_first):
    for rows in tables:
        if rows and rows[0] and rows[0][0].strip().lower().startswith(header_first.lower()):
            return rows
    return []


def to_iso(s):
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%m-%d-%y", "%d %b %Y", "%d %b %y", "%d %B %Y", "%d %B %y",
                "%d-%b-%Y", "%d-%b-%y", "%d%b%Y", "%d%b%y", "%b %d, %Y", "%B %d, %Y", "%b %d %Y"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).date().isoformat()
        except (ValueError, AttributeError):
            pass
    return ""


# A capitalised "First Last" after words that usually introduce a person ("have Jane Doe take it", "ask John Smith").
PERSON_CUE = re.compile(r"\b((?i:have|ask|asked|contact|call|email|see|cc|with|by|to|from|per|thanks|and))[ \t]+([A-Z][a-z'-]+(?:[ \t][A-Z]\.)?[ \t][A-Z][a-z'-]+)\b")
# Test and lab words: a capitalised pair containing one of these ("with Current Reversal") is a term, not a person.
TERMS = set("""current reversal mode delta differential source meter test tests testing method sample samples data report formal
internal external customer product new old rev line auto signal signals power powers ground grounds force forces cycle cycles
temperature voltage resistance high low board boards cable cables assembly connector connectors housing plating contact contacts
room ambient reflow solder thermal humidity salt spray gas mixed flowing durability mating unmating insertion removal pull wire
end life full qualification cross section hardness foam chlorine sem ftir ct scan scans porosity dust vibration shock mechanical
dielectric insulation withstanding phase group step table figure spec drawing page sheet lot part number cap
procedure standard kelvin four point probe platen strain speed rate profile peak dwell soak ramp limit long short
term round robin hour hours day days week weeks month plan rating reliability failure analysis annex matrix revision
copper gold nickel silver tin brass bronze steel stainless aluminum aluminium titanium zinc lead palladium beryllium
plastic resin glass rubber silicone foam paper wood stone ceramic carbon iron rose white black blue green gray grey
red orange yellow brown pink baseline control reference standard nominal original new old previous current next
""".split())
# Site, city and lab names are organisation details: they live in data/private/importer_config.json (gitignored).
#   {"protected_words": ["<city>", ...], "site_aliases": {"<CODE>": "<Site name>", ...}}
try:
    CONFIG = json.loads((OUT.parent / "importer_config.json").read_text(encoding="utf-8"))
except (OSError, ValueError):
    CONFIG = {}
TERMS |= {w.lower() for w in CONFIG.get("protected_words", [])}
SITE_ALIASES = {k.upper(): v for k, v in CONFIG.get("site_aliases", {}).items()}
SITE_NAMES = set(SITE_ALIASES.values())
# Surnames that are also common words are left to the field-based rules rather than removed everywhere..split())
# A document's author before its date ('"Plan title", Jane Doe, 06/17/2025').
PERSON_BYLINE = re.compile(r"([,;(]\s*)([A-Z][a-z'-]+(?:[ \t][A-Z]\.)?[ \t][A-Z][a-z'-]+)(?=\s*[,;)]?\s*\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})")
# A first name used alone as the subject of a sentence ("Cheryl is familiar with the test. Frank will have the tools").
PERSON_SUBJECT = re.compile(r"(?:(?<=^)|(?<=[.!?;]\s)|(?<=\n))([A-Z][a-z'-]{2,})(?=\s+(?:is|was|will|has|had|can|could|knows|should|would|may|must|needs|wants|said|asked)\b)")
STARTERS = set("""this that these those there their they then the it its he she we you our your his her each all both either
neither any some most more one two three first second next last also however please note supplier customer vendor lab
operator technician engineer requester team everyone nobody someone measurement measurements material materials result
results value values location position distance thickness width height length depth size area surface quantity purpose goal
objective scope analysis request order delivery shipment priority timing cost budget equipment fixture fixturing tooling tool
tools setup sequence step data testing everything nothing something here what which who where when why how""".split())
VERBS = set("notify inform tell call email contact ask see please thank thanks send give cc copy include let".split())
# A name that follows a removed one in a list ("<person>, Jane Doe and John Smith").
PERSON_LIST = re.compile(r"(<person>\s*(?:,|and|&|;)\s*(?:and\s+)?)([A-Z][a-z'-]+(?:[ \t][A-Z]\.)?[ \t][A-Z][a-z'-]+)\b")
PERSON_FIELDS = ("requested by", "approved by", "send copies of test results/reports to", "lab personnel assigned", "tested by",
                 "report prepared by", "report checked by", "report approved by", "project approved by")


def people(lv, extra=()):
    """Names found in the form's people fields, plus any given with --redact."""
    out = []
    for k in PERSON_FIELDS:
        for n in re.split(r"[;,/\n]| and ", EMAIL.sub("", lv.get(k, ""))):
            n = re.sub(r"\b(mech|tech|eng|engineer|technician)\b\.?", "", n, flags=re.I).strip(" .")
            if re.search(r"[A-Za-z]{2}", n) and not re.search(r"\d", n):
                out.append(n)
    return out + list(extra)


# Name parts removed in earlier imports, kept only as salted one-way hashes, so a first name used alone in a later
# request ("same as what was done for <name>") is still removed. The names themselves are never written down.
SEEN_FILE = OUT / ".seen_names"


def _seen():
    try:
        salt, *hashes = SEEN_FILE.read_text(encoding="utf-8").split()
        return salt, set(hashes)
    except (OSError, ValueError):
        return hashlib.sha256(str(dt.datetime.now().timestamp()).encode() + __file__.encode()).hexdigest()[:16], set()


SALT, SEEN = _seen()


def _h(word):
    return hashlib.sha256((SALT + word.lower()).encode()).hexdigest()[:20]


def remember(names):
    for n in names:
        for part in re.split(r"[\s.]+", n):
            if len(part) > 2 and part.lower() not in TERMS:
                SEEN.add(_h(part))


def save_seen():
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(SALT + "\n" + "\n".join(sorted(SEEN)), encoding="utf-8")


CODE = re.compile(r"\b((?:web|access|login|portal)\s*code|password|passcode)\s*[:#]?\s*(?=[A-Za-z-]*\d)[A-Za-z0-9-]{4,}", re.I)   # a code has a digit


def redact(text, names):
    t = EMAIL.sub("<email>", text or "")
    t = CODE.sub(lambda m: m.group(1) + " <removed>", t)   # access codes for outside portals
    t = re.sub(r"\b[A-Z]{2,4}(?=\s+\d{1,2}/\d{1,2}/\d{2,4})", lambda m: m.group(0) if m.group(0) in ("EL", "LR", "PO", "REV", "SN", "EIA", "IEC", "ASTM", "ISO", "IPC", "JEDEC", "UL", "GS", "QTP", "DOC", "ECN", "ECO", "RMA") else "<initials>", t)
    t = PHONE.sub("<phone>", t)
    t = re.sub(r"\b[A-Z][a-z'-]{2,}\b", lambda m: "<person>" if m.group(0).lower() not in TERMS and _h(m.group(0)) in SEEN else m.group(0), t)
    for n in names:
        for part in [n] + re.split(r"[\s.]+", n):
            if len(part) > 2:
                t = re.sub(r"\b" + re.escape(part) + r"\b", "<person>", t, flags=re.I)
    t = PERSON_CUE.sub(lambda m: m.group(0) if set(re.findall(r"[a-z]+", m.group(2).lower())) & TERMS else m.group(1) + " <person>", t)
    t = PERSON_BYLINE.sub(lambda m: m.group(0) if set(re.findall(r"[a-z]+", m.group(2).lower())) & TERMS else m.group(1) + "<person>", t)
    t = PERSON_SUBJECT.sub(lambda m: m.group(1) if m.group(1).lower() in STARTERS | TERMS else "<person>", t)
    # First name, middle initial, surname ("Jane Q. Doe") is a name wherever it appears.
    t = re.sub(r"\b[A-Z][a-z'-]+[ \t][A-Z]\.[ \t]?[A-Z][a-z'-]+\b",
               lambda m: m.group(0) if set(re.findall(r"[a-z]+", m.group(0).lower())) & (TERMS | STARTERS) else "<person>", t)
    # A lone first name after a person cue at the end of a clause ("Sample provided to Jenny.", "notify Mike when ...").
    t = re.sub(r"(?i:\b(to|ask|contact|call|notify|cc|thanks|thank)[ \t]+)([A-Z][a-z'-]{2,})(?=[ \t]*(?:[.,;!?)]|$)|[ \t]+(?:when|if|before|once)\b)",
               lambda m: m.group(0) if m.group(2).lower() in TERMS | STARTERS | VERBS else m.group(1) + " <person>", t, flags=re.M)
    # The other half of a name whose first or last part was removed ("<person> Doe", "Jane <person>").
    near = lambda m: m.group(0) if m.group("w").lower() in TERMS | STARTERS | VERBS else "<person>"
    t = re.sub(r"<person>[ \t]+[A-Z]\.[ \t]?[A-Z][a-z'-]+\b", "<person>", t)
    t = re.sub(r"<person>[ \t]+(?P<w>[A-Z][a-z'-]+)\b", near, t)
    t = re.sub(r"\b(?P<w>[A-Z][a-z'-]+)[ \t]+<person>", near, t)
    while PERSON_LIST.search(t):
        t = PERSON_LIST.sub(lambda m: m.group(1) + "<person>", t)
    return re.sub(r"<person>(?:[\s.]*<person>)+", "<person>", t).strip()   # first and last name removed separately -> one mark


def as_docx(path):
    """Old binary .doc files are converted with LibreOffice (if installed) into a temporary .docx."""
    path = Path(path)
    if path.suffix.lower() != ".doc":
        return path
    import shutil, subprocess, tempfile
    office = shutil.which("soffice") or shutil.which("libreoffice")
    if not office:
        sys.exit(f"{path.name}: open it in Word and save it as .docx (LibreOffice is not installed to convert it).")
    out = Path(tempfile.mkdtemp())
    subprocess.run([office, "--headless", "--convert-to", "docx", "--outdir", str(out), str(path)], capture_output=True, timeout=120)
    got = out / (path.stem + ".docx")
    if not got.exists():
        sys.exit(f"{path.name}: could not convert; open it in Word and save it as .docx.")
    return got


def convert(path, extra_names=()):
    tables, controls = read_docx(as_docx(path))
    lv = label_values(tables)
    drop = [c["value"] for c in controls if c["kind"] == "dropdown"]
    dates = [to_iso(c["value"]) for c in controls if c["kind"] == "date"]
    by_alias = {c["alias"].lower(): c["value"] for c in controls if c["alias"]}

    def pick(options):
        low = {o.lower(): o for o in options}
        return next((low[v.lower()] for v in drop if v.lower() in low), "")
    names = people(lv, extra_names)
    remember(names)
    selects = [c["value"] for c in controls if c["kind"] == "dropdown" and c["alias"].lower() == "select one"]

    samples = sample_rows(tables, names)
    # The old form spreads one test over several rows (one instruction per row): join them into one test item.
    lines, specs = [], []
    for row in table_after(tables, "Tests to be Performed")[1:]:
        if row and re.match(r"(confidential|can testing|additional information)", row[0].strip(), re.I):
            break                       # some versions keep the yes/no questions in the same table
        if row and row[0]:
            lines.append(redact(row[0], names))
            spec = row[1] if len(row) > 1 else ""
            if spec.strip().upper() not in ("", "N/A", "NA"):
                specs.append(spec.strip())
    tests = [{"testsToBePerformed": "\n".join(lines), "applicableSpecifications": "; ".join(dict.fromkeys(specs)),
              "specificationRevision": ""}] if lines else []
    info = ""
    for rows in tables:   # the free-text box: a one-cell table that is not a heading
        if len(rows) == 1 and len(rows[0]) == 1 and len(rows[0][0]) > 20 and "SECTION" not in rows[0][0]:
            info = rows[0][0]
            break
    copies = lv.get("send copies of test results/reports to", "")
    disposition = by_alias.get("disposition", "")
    fields = {
        # The old form has two "Select One" dropdowns: business unit, then manufacturing site; some files typed them instead.
        "businessUnit": (selects[0] if selects else "") or lv.get("business unit", ""),
        "mFGSite": (selects[1] if len(selects) > 1 else "") or lv.get("mfg. site", lv.get("mfg site", lv.get("site", ""))),
        "resultsFormat": pick({"Data and Observations", "Presentation Summary", "Formal Report (Internal)", "Formal Report (Customer)"}),
        "requestedTestingCompletionDate": dates[1] if len(dates) > 1 else "",
        "testSite": next((v for v in drop if v in SITE_NAMES), ""),
        "testSampleStatus": pick({"Prototype", "Pre-Production", "Production", "Competitor"}),
        "projectType": pick({"Qualification", "New Product Development", "Product Extension", "Innovation", "Operational Support", "Cost Reduction"}),
        "step2_rows": samples,
        "postTestingSampleDisposition": {"send back to requestor": "Send back to requestor", "scrap": "Scrap", "keep in the lab": "Keep in the lab"}.get(disposition.lower(), disposition),
        "step3_rows": tests,
        "confidentialTestsOrSamples": by_alias.get("confidiential", by_alias.get("confidential", "")).lower(),
        "canTestingBeSubcontracted": by_alias.get("subcontracted", "").lower(),
        "additionalInformation": redact(info, names),
        "sendCopiesTo": "<removed>" if copies.strip() else "",
    }
    lab = {
        "request_date": dates[0] if dates else "",
        "reviewed_and_approved_by_lab": bool(re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", lv.get("request reviewed and approved by", "") + " " +
                                                         " ".join(c for rows in tables for r in rows for c in r if re.match(r"^[A-Z]{2,4}\s+\d", c)))),
        "date_lab_received": dates[2] if len(dates) > 2 else "",
        "estimated_completion": dates[3] if len(dates) > 3 else "",
        "sample_condition": by_alias.get("condition", "") or next((v for v in drop[::-1] if v in ("Acceptable", "Not Acceptable")), ""),
        "legacy_test_type": pick({"Product/Process Development", "Product/Process Qualification", "Lab/Failure Analysis", "Customer Specific Testing"}),
        "project_number": lv.get("project #", ""),
        "related_requests": sorted(set(re.findall(r"\b[A-Z]{2}[- ]?\d{4}-\d{2}-\d{3}[A-Z]?\b", info + " " + " ".join(t["testsToBePerformed"] for t in tests) + " " + " ".join(x["traceabilityMfgLotInfo"] for x in samples)))),
        "attachments_referenced": sorted({w.split("|")[0].replace("see ", "") for w in ("PowerPoint", "drawing", "profile", "spreadsheet", "photo",
                                                    r"see attached|attached (file|document|spec|drawing|sheet|plan|table|report|picture|photo)")
                                          if re.search(w, info + " ".join(t["testsToBePerformed"] for t in tests), re.I)}),
        "pictures_in_request": len(body_images(path)),
    }
    if table_after(tables, "Part numbers of the products") or table_after(tables, "Part #"):
        revb(tables, lv, names, fields, lab)
    return fields, lab


def revb(tables, lv, names, fields, lab):
    """The 2015 form (E-3718 Rev B): checkboxes instead of dropdowns, part number first in the samples table."""
    cells = [r for rows in tables for r in rows]

    def ticked(*labels):
        for r in cells:
            for i, c in enumerate(r[:-1]):
                if r[i + 1] == "☒" and any(c.lower().startswith(l.lower()) for l in labels):
                    return True
        return False

    def first(options):
        return next((v for k, v in options if ticked(k)), "")

    def yes_no(question):
        for r in cells:
            if r and r[0].lower().startswith(question) and len(r) >= 4:
                return "yes" if r[1] == "☒" else "no" if r[3] == "☒" else ""
        return ""
    fields.update({
        "mFGSite": lv.get("location", ""),
        "requestedTestingCompletionDate": to_iso(lv.get("requested testing completion date", "")),
        "testSite": SITE_ALIASES.get(lv.get("lab performing the tests", "").strip().upper(), lv.get("lab performing the tests", "")),
        "testSampleStatus": first([("Prototype", "Prototype"), ("Pre-production", "Pre-Production"), ("Production", "Production"), ("Competitor", "Competitor")]),
        "resultsFormat": first([("Test Report", "Formal Report (Internal)"), ("Data and Observations", "Data and Observations")]),
        "postTestingSampleDisposition": first([("To be sent back", "Send back to requestor"), ("To be scrapped", "Scrap"), ("To be kept", "Keep in the lab")]),
        "confidentialTestsOrSamples": yes_no("confidential"),
        "canTestingBeSubcontracted": yes_no("can testing"),
    })
    lab.update({
        "request_date": to_iso(lv.get("date", "")),
        "date_lab_received": to_iso(lv.get("date lab received samples", "")),
        "estimated_completion": to_iso(lv.get("estimated completion date", "")),
        "sample_condition": "Acceptable" if any("☒ Acceptable" in c for r in cells for c in r) else
                            "Not Acceptable" if any("☒ Not Acceptable" in c for r in cells for c in r) else "",
        "legacy_test_type": first([("Product/Process Development", "Product/Process Development"), ("Product/Process Qualification", "Product/Process Qualification"),
                                   ("Lab/Failure Analysis", "Lab/Failure Analysis"), ("Customer Specific", "Customer Specific Testing")]),
        "project_number": lv.get("project/ewr /nbo#", lv.get("project/ewr/nbo#", "")),
        "form_version": "E-3718 Rev B (2015)",
    })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--print", action="store_true")
    ap.add_argument("--manual", metavar="JSON", help="values typed in by hand for a scanned request")
    ap.add_argument("--redact", action="append", default=[], metavar="NAME", help="another name to remove (repeatable)")
    a = ap.parse_args()
    from assistant import quality
    paths = [Path(p) for pat in a.files for p in (glob.glob(pat) or [pat])]
    idx_file = OUT / "index.json"
    idx = json.loads(idx_file.read_text(encoding="utf-8")) if idx_file.exists() else {
        "_about": "PRIVATE (gitignored) examples imported from past lab requests. Personal details removed.", "examples": []}
    for p in paths:
        if a.manual:
            m = json.loads(Path(a.manual).read_text(encoding="utf-8"))
            names = list(a.redact) + m.get("redact", [])
            fields, lab = m["fields"], m["lab_section"]
            for k, v in fields.items():   # emails, phones and names are removed even from typed-in text
                if isinstance(v, str):
                    fields[k] = redact(v, names)
            for row in fields.get("step2_rows", []) + fields.get("step3_rows", []):
                for k, v in row.items():
                    row[k] = redact(v, names) if isinstance(v, str) else v
        else:
            fields, lab = convert(p, a.redact)
        rid = "LR-" + (lab["request_date"] or "undated") + "-" + hashlib.sha256(p.read_bytes()).hexdigest()[:6]   # same file, same id, whatever its name
        title = (fields["step3_rows"][0]["testsToBePerformed"].splitlines()[0][:70] if fields["step3_rows"] else p.stem)
        title = f"{(fields['step2_rows'][0]['productName'] + ': ') if fields['step2_rows'] else ''}{title}"
        asof = dt.date.fromisoformat(lab["request_date"]) if lab["request_date"] else None
        review = quality.review("lab_test_request", fields, today=asof)   # judged as on the day it was sent
        # Ignore what is only an artifact of an old, redacted record: removed contact details.
        # Real requests follow the real lab's procedures, not the synthetic library (SYN-...), so those rules are left out.
        flags = [f for f in review["flags"] if f["field"] not in ("firstName", "lastName", "email", "phone", "bPCNumber", "sendCopiesTo")
                 and not str(f.get("source") or "").startswith("SYN-")]
        rec = {"id": rid, "form": "lab_test_request", "title": title,
               "source": "scanned request (typed in by hand)" if a.manual else "legacy Word request (imported)",
               "source_file_hash": hashlib.sha256(p.read_bytes()).hexdigest()[:16], "redacted": ["names", "emails", "phone numbers", "lab initials and staff"],
               "fields": fields, "lab_section": lab,
               "quality_at_import": {"must_fix": [f["message"] for f in flags if f["severity"] == "error"],
                                     "should_fix": [f["message"] for f in flags if f["severity"] == "warn"],
                                     "good_practice": [f["message"] for f in flags if f["severity"] == "info"]},
               "why_good": [], "imported": dt.date.today().isoformat()}
        old = OUT / f"{rid}.json"
        if old.exists():   # re-importing keeps what a person already wrote about the example
            prev = json.loads(old.read_text(encoding="utf-8"))
            for k in ("why_good", "why_good_status", "gaps"):
                if prev.get(k):
                    rec[k] = prev[k]
        if a.print:
            print(json.dumps(rec, indent=1, ensure_ascii=False))
            continue
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{rid}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
        idx["examples"] = [x for x in idx["examples"] if x["id"] != rid] + [
            {"id": rid, "form": "lab_test_request", "title": title, "why_good": rec["why_good"], "file": f"{rid}.json", "private": True}]
        print(f"[import] {p.name} -> data/private/lab_requests/{rid}.json  ({len(rec['quality_at_import']['must_fix'])} must fix, "
              f"{len(rec['quality_at_import']['should_fix'])} should fix at import)")
    if not a.print:
        save_seen()
        idx_file.write_text(json.dumps(idx, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

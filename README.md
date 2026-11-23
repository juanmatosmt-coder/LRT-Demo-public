Capstone Video Link
https://youtu.be/qrpr3tVNEig

# Lab Request Assistant

A local assistant that helps an engineer write a complete laboratory test request: describe the test in a chat, it asks
for what the procedure requires, cites the procedure, proposes the form fields, and checks the draft. It never submits.
Everything runs on this computer; the repository holds **synthetic data only** (see `data/README.md`). Reviewers
without the private data see the SYNTHETIC past-request library (`data/synthetic/past_requests/`) in **My drafts → Examples**.

## Quick start (Windows)

| Step | Command | What it does |
|---|---|---|
| 1 | `install.bat` | Creates `.venv` (an existing one is kept) and runs the **non-AI self-check** (`tools\selfcheck.py`, about 10 s, no network): it prints the version (from `VERSION`, plus the Git commit) and gives PASS/FAIL for environment, synthetic data files, quality-check known answers, the equipment range check, seven guardrails, one chat turn by rules, the local-only rules, and a web-server smoke test (page served, private files blocked). Private data and the AI model are reported as INFO only. The AI model is not used or tested here. Needs Python 3.10+ (3.12 preferred); the app itself needs no packages. |
| 1b | `install.bat model` | Also installs the GPU packages and downloads the local model once (NVIDIA GPU, several GB). Skip it if `.venv` already has them. |
| 2 | `start.bat` | Starts the local AI model in its own window (if installed), starts the tool, and opens the form in the browser. |
| 2b | `start.bat demo` | Same without the AI model: the assistant drafts by rules. For a quick look on any PC. |
| 3 | `stop.bat` | Stops the tool (port 8010) and the local AI model (port 8000), however their windows were opened: it uses the PID files in `traces\` and the ports, and stops only Python processes. |

**AI model already installed in another folder?** Copy `local_settings.example.bat` to `local_settings.bat` (kept out
of Git) and set `LRT_MODEL_PYTHON` to that folder's `.venv\Scripts\python.exe`. If the model files are not in the usual
Hugging Face cache, also set `HF_HOME` (or `CHAT_MODEL` / `EMBED_MODEL` to the model folders). `install.bat model` then
only checks that install, and `start.bat` uses it. `.venv\Scripts\python.exe tools\launcher.py find-model` shows where
the model files are looked for and whether they were found.

**Tests and procedures (all SYNTHETIC).** Warpage during reflow, thermal cycling, room-temperature flatness, temperature
rise and LLCR are built into the assistant. Ten more come from the test registry (`data/templates/test_registry.json`):
mechanical force on a universal testing machine (mating/unmating, retention, crimp pull-out, normal force), durability
(mating cycles), SEM/EDS, FTIR, plating porosity, cross-section, XRF plating thickness, thermal analysis (DSC/TMA/TGA),
microhardness, and DWV/insulation resistance, each with a procedure in `docs_extended/`. A registry entry holds the
detection words, the inputs the procedure requires (with the *where* questions), and the sample minimum; the chat's
questions and Check quality's rules both come from it. Any other test is drafted in the requester's words and the lab
defines the method. Ask the assistant *what tests are available?* for the current list.

**Claude as an alternative AI (optional; organisation approval required).** The assistant can use Claude through
Anthropic's OpenAI-compatible endpoint instead of the local Qwen model. In `local_settings.bat` set
`LRT_BASE_URL=https://api.anthropic.com/v1`, `LRT_AI_MODEL=claude-sonnet-5-5` (or `claude-haiku-5-5`, faster and cheaper)
and `LRT_ALLOW_REMOTE_AI=1`; set the key once with `setx LRT_AI_KEY "..."` (never in a file). `start.bat` then skips
Qwen, the chat shows the model and `api.anthropic.com`, and it warns that messages and the draft leave the computer.
To let people choose (for example Opus 5.5 for hard reviews, Haiku for speed), also set `LRT_AI_MODELS=claude-sonnet-5-5,claude-opus-5-5,claude-haiku-5-5`: the chat header then shows a model picker, and the server accepts only the listed models. This breaks the suite's local-only default, so use it only with SYNTHETIC data unless your organisation has approved
Claude for real data. The same guardrails apply (grounding, calibration, nothing submitted).

**Feedback from engineers, technicians and lab reviewers.** Under any assistant answer or the Check quality list,
*Give feedback on this* shows *Useful / Not needed / Wrong* on each question, review point, proposed value and flag
(with an optional comment), and *Suggest a missing question or check* opens a short form: role, test, what to ask or
check, why, importance, a good answer, and the source. Entries go to an append-only log on this server
(`data/private/feedback/feedback.jsonl`, never committed) with the tool version, AI model and run ID. The **Feedback**
page (`gui/feedback.html`) summarises them by test, lists the most-wanted additions and the worst-rated items, and lets
an admin (or the server computer) set the status *accepted / added / rejected* with a note, and export CSV or JSON.
`python -m assistant.feedback --md` prints a report. Feedback never changes the assistant by itself: a person adds
accepted items to the procedure, the questions (`assistant/guardrails.py`) or the quality check (`assistant/quality.py`).
A fresh copy shows the SYNTHETIC examples in `data/synthetic/feedback/`.

**No Windows PC or no GPU? Google Colab (SYNTHETIC data only).** [Open in Colab](https://colab.research.google.com/github/juanmatosmt-coder/LRT-Demo-public/blob/main/colab/LRT_Colab.ipynb). `colab/LRT_Colab.ipynb` runs the same tool on
Colab: the non-AI self-check, the chat from the notebook, the optional AI model on Colab's free T4 GPU, the form page
through Colab's private proxy, and the security tests. Colab is Google's cloud, unlike the local-only Windows version,
so only the committed SYNTHETIC data goes there: the notebook stops if `data/private` holds any file, and
`serve.py --colab` refuses to start in that case and turns sign-in off. Cell 1 clones the public repository; without access to GitHub, upload a zip
made with `git archive -o LRT-Demo-synthetic.zip HEAD` (committed files only). `python tests/test_colab_notebook.py` runs
the notebook's cells outside Colab (9 checks).

In the form, press **Ask the assistant**, describe the test (part, samples, test and conditions, why), answer its
questions, then **Apply to form** and **Check quality**. The badge in the chat says which mode is running: *AI on*,
*No AI* (the model is not running, so drafts are built by fixed rules), or *Demo: no AI*.

What one chat turn does (`assistant/chat.py`): screens the message for instructions aimed at the AI, links, credentials
and hidden characters; refuses to submit or to reveal prompts, keys or private files; recognises the tests and refers
tests with no procedure to the lab; cites the procedure passages (active revisions only); asks for the required inputs
not given yet; drafts the fields with the local model, keeping only numbers the engineer wrote and filling
specifications and revisions from the citations in code; softens absolute wording; runs the quality check; and sets the
state to *Incomplete* or *Ready for your review*. Only the engineer approves. Every step is logged to `traces/runs/`.

---

## Checkpoint 3.1: minimal RAG demo

Runs one synthetic warpage-during-reflow request through local Qwen (default Qwen3.5-9B, 4-bit) five ways and saves traces:

| Run | What Qwen sees |
|---|---|
| `no_retrieval` | Only the engineer's request (baseline) |
| `retrieval_unfiltered` (v1) | Top 3 passages by semantic similarity to the request, from all 6 documents |
| `retrieval_filtered` (v1) | Same, restricted to active documents of the confirmed test types |
| `filtered_mmr` (v2) | Top 3 by Maximal Marginal Relevance (lambda 0.5) within the filtered set, to reduce redundant passages |
| `filtered_form_sections` (v2) | One query per lab request form section (required inputs, preparation, quantity, sequence, reporting), top 1 each, within the filtered set |

It also runs three retrieval-only probe queries (top 5, unfiltered) to show how decoy documents rank.

All documents in `docs/` are synthetic. Two are deliberate decoys: a room-temperature flatness method (SYN-TM-104) and a thermal cycling method (SYN-TM-110). One is an obsolete revision (SYN-TM-101 Rev B) with weaker requirements.

## Setup (Windows PowerShell, one time)

From the project folder, using Python 3.12 (replace `<path to Python 3.12>` with your install):

```
<path to Python 3.12>\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu126
.\.venv\Scripts\python.exe -m pip install transformers accelerate sentence-transformers bitsandbytes pillow
.\.venv\Scripts\python.exe -m pip install torchvision --index-url https://download.pytorch.org/whl/cu126
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

The last line must print `True` and the GPU name. If it prints `False`, the CPU-only torch was installed; uninstall torch and repeat the cu126 line.

## Run

```
.\.venv\Scripts\python.exe rag_demo.py
```

The first run downloads Qwen3.5-9B (about 20 GB; it loads as a multimodal model, and its thinking mode is turned off) and the embedding model (about 0.4 GB) to `C:\Users\<you>\.cache\huggingface`. Later runs use the local copy.

The chat model loads in 4-bit by default so it fits entirely on a 16 GB GPU. For full bf16 precision (slower, spills into system RAM), set `$env:QUANT="none"`.

To use a different model, set `CHAT_MODEL` for that run, for example:
```
$env:CHAT_MODEL="Qwen/Qwen2.5-7B-Instruct"; .\.venv\Scripts\python.exe rag_demo.py
```

## Output (`traces/<model>/`)

Each chat model gets its own subfolder, for example `traces/Qwen3.5-9B-4bit/`, so runs with different models can be compared.

- `summary.md` - human-readable: probe rankings, retrieved passages per run, and Qwen's three responses. **Send this one back.**
- `run_*.json` - full prompt, retrieved passages with scores, and response for each run.
- `chunks.json` - the 29 section-level chunks with their metadata.
- `probes.json` - the probe rankings.

## Design in one paragraph

Each document is split at its `##` section headings, so a requirement stays with its conditions (29 chunks). The document ID, revision, and title are prepended to each chunk, so they are embedded and visible to Qwen. Chunks are embedded with `BAAI/bge-base-en-v1.5`, ranked by cosine similarity, and the top 3 are inserted into the prompt. Qwen generates greedily (no sampling), so reruns give the same output. The filtered run restricts the candidates to `status: active` and the test types confirmed with the engineer (`warpage_reflow`, `preparation`, `reporting`). That restriction is the mitigation for retrieving a similar but inapplicable or superseded procedure. Exact equipment limits are not part of this demo; they belong to the equipment database module.

## Comparing retrieval routes (`eval/`)

One request is not enough to choose a design, so `eval/` tests every route on five synthetic scenarios with known answers (`eval/scenarios.json`): warpage during reflow, the same request paraphrased, room-temperature flatness, thermal cycling, and a combined reflow + cycling plan. Each scenario lists **required facts** (exact sentences from the procedures that a good draft depends on) and **forbidden facts** (obsolete or inapplicable rules).

Two libraries are tested:
- **base**: the 6 documents in `docs/` (the Checkpoint 3.1 setup)
- **extended**: base + 6 documents in `docs_extended/` that add realistic in-scope noise (equipment operation, data processing, cleaning and marking), another obsolete revision (preconditioning Rev A, 105 C / 8 h), a look-alike method (liquid thermal shock, "no preconditioning required") and a second report format

**Step 1, retrieval only (no chat model, a few minutes):**
```
.\.venv\Scripts\python.exe eval\eval_retrieval.py
```
Compares query (engineer request vs. one query per form section), selection (top-k vs. MMR 0.5 / 0.7), metadata filter on/off, k = 3 / 5 / 8, section vs. fixed 100-word chunks (the course DPR lab), and bge-base vs. all-MiniLM-L6-v2 (the course lab's encoder) vs. BM25 keyword search. Scores: required-fact recall (mean and worst scenario), forbidden facts retrieved, off-scope chunks, and context words. Results: `eval\results\retrieval_summary.md` (best route per word budget, then full tables) and `retrieval_results.csv`.

**Step 2, end to end with Qwen (about 30-60 s per draft):**
```
$env:TRITON_DEFAULT_FP_FUSION="1"; .\.venv\Scripts\python.exe eval\eval_generation.py
```
Default: extended library, 6 routes x 5 scenarios = 30 drafts. Each draft is scored with regex checks for what it should state or ask (`output_checks`) and for obsolete rules it repeats (`output_forbidden`). The regex scoring is approximate; read the saved drafts (`generation_extended.jsonl`) for the routes you intend to rely on. Options: `--library base`, `--routes none form1 all`, `--scenarios S1 S5`.

## Framework and ToT validation (`spikes/`)

Tests that the Checkpoint 4.1 design runs on the local model: Qwen served as an OpenAI-compatible API, LangChain, CrewAI, MCP tools, and a Tree-of-Thought beam search on the combined reflow + cycling request (S5).

Two virtual environments keep the heavy agent frameworks away from the working model setup:
- **`.venv`** (existing) runs the Qwen server and the MCP server (model + embeddings)
- **`.venv-agents`** (new) runs CrewAI and LangChain, which only talk to them over HTTP and stdio

**One-time setup** (from the repo root):
```
.\.venv\Scripts\python.exe -m pip install fastapi uvicorn "mcp==1.30.0"
<path to Python 3.12>\python.exe -m venv .venv-agents
.\.venv-agents\Scripts\python.exe -m pip install --upgrade pip
.\.venv-agents\Scripts\python.exe -m pip install -r spikes\requirements-agents.txt
```

**Run everything** (starts and stops the Qwen server itself; about 10-20 minutes):
```
.\.venv-agents\Scripts\python.exe spikes\run_all.py
```
Report: `spikes\results\validation_report.md` (+ `.json`). Subset: `--only 1 2`. To watch the server separately, start `.\.venv\Scripts\python.exe spikes\qwen_server.py` in another window first; `run_all.py` then uses it.

| Test | What it validates | Pass condition |
|---|---|---|
| 1 | `qwen_server.py`: local Qwen behind an OpenAI-compatible API | lists the model, answers, honours stop sequences |
| 2 | LangChain LCEL chain (prompt, local Qwen, JSON parser) | returns parseable JSON with valid fields |
| 3 | CrewAI planner and reviewer agents, sequential routing | both agents return output through the local model |
| 4 | MCP server from LangChain: retrieval, equipment, `validate_plan`, plan state | rule verdicts match expected (linear-style plan rejected, 5/5 split accepted, 3/7 rejected), retrieval and state round-trip |
| 5 | ToT beam search (k = 3, b = 2, depth 2) on S5, with and without second-profile confirmation | ends with a plan that passes every hard check, or a justified stop |

Depth 3 of the design (timing of prerequisites) is not part of the spike.

## Security

See [SECURITY.md](SECURITY.md): threats and controls layer by layer, and the open items. `python tests/test_security.py` runs 54 checks on the server and the input screening.

## Local only: network policy

This is a local test suite for the CMU capstone. Nothing in it sends data to the internet or to a company system.

- **Run time:** every script imports `lrt_offline.py` first. It turns off Hugging Face update checks and the telemetry built into CrewAI, OpenTelemetry and LangSmith, and makes Hugging Face load models from the local cache only.
- **Allowed traffic:** only traffic on this computer: the browser to the page server (127.0.0.1:8010), and the agents to the local Qwen server (127.0.0.1:8000). Both servers refuse to listen on anything but loopback.
- **The page:** its Content-Security-Policy lets it load files only from the local page server and call only the local Qwen endpoint. Any other request is blocked by the browser, including fonts and images from the web. The request forms have no submit button.
- **One exception, at setup:** packages come from PyPI and PyTorch, and the first model download comes from Hugging Face (the AI source chosen for this project). Run that once with `$env:LRT_ALLOW_DOWNLOAD = "1"`; after that the suite runs with the network unplugged.
- **Real company data and logos:** these live only in `data/private/`, which git ignores. The repo uses synthetic lists.

## Request form GUI (`gui/`)

```powershell
.\.venv\Scripts\python.exe gui\serve.py      # then open http://127.0.0.1:8010/gui/request_form.html
```

Three draft-only forms built from `data/templates/lab_request_forms.json`: the general lab request and the SMT lab request (same fields as the lab's online forms), and an imaginary machine shop request. The machine shop form is itemized: the requester, cost center and job are entered once, then up to 25 parts, each with its own drawing, STEP file and photos. Four draft-only forms in all: the purchase requisition (one supplier, many line items, totals calculated as you type) was added after the machine shop form. The page works on a phone and checks required fields. With `data/private/` present it shows the real dropdown lists and the logos.

- **Drafts never get lost:** every change autosaves. Signed in, drafts go to the local server (`data/private/drafts/<user>/`, written so a crash never leaves a half file) and open from any browser that reaches it. As a guest, drafts stay in that browser. If the server cannot be reached, the page keeps a copy in the browser and syncs it later. On sign-in, guest drafts can be moved into the account.
- **Accounts:** local only, stored in `data/private/users.json` as salted PBKDF2 hashes. The first account created on this computer is the admin; only admins edit lab data (`python gui\serve.py --make-admin NAME` adds one). `--allow-lan` lets a phone on the same network open the page (inbound only; sign-up from other devices is off, and private data needs sign-in). Add `--tls-cert`/`--tls-key` for HTTPS. See [SECURITY.md](SECURITY.md).
- **Parts directory:** part number fields suggest parts from `data/private/parts/parts.json` (or the synthetic `data/synthetic/parts/parts.json`) and fill the item's other fields from it. Obsolete parts are flagged.
- **Files:** attachments stay on the computer. A draft keeps only their names and sizes.

## Quality flags and the example library

**Check quality** (form page) reviews any draft, whether typed by the engineer or filled by the assistant, with `assistant/quality.py`. Each flag points at the field it is about and says what is wrong, why (with its source: procedure and revision, equipment database, parts directory, form rule or example library) and how to fix it:

- **Must fix:** the lab cannot schedule the request as written. Examples: a missing thermal or cycling profile, an obsolete procedure revision, too few samples for the procedure minimum, a temperature outside the chamber limits, an invalid email.
- **Should fix:** likely to cause a question back from the lab, or results that cannot be compared. Examples: no datum or storage history, the same samples through reflow twice, a material that differs from the parts directory, a vague test description, a date inside the lab lead time.
- **Good practice:** points that high-quality past requests also state.

It covers all four forms:

- **Every form:** required fields and rows, per-item drawing/STEP/photo files, part numbers and revisions against the parts directory, obsolete parts, duplicate items, quantities, dates against lead times, and email addresses.
- **General and SMT lab:** procedure revisions, the inputs each procedure needs before scheduling, sample minimums, and equipment limits. SMT also checks mixed solder alloys, paste consistency between BGA and board attach, and undefined stencils or sphere sizes.
- **Machine shop:** a vague scope of work, a "Line down" priority with no stated impact, a missing ship-to address, and values typed outside the lists.
- **Purchase requisition:** zero prices, tax that contradicts the exemption, missing quotes, new suppliers, ASAP dates, and the second-approval threshold.

The checks are deterministic, so the same draft always gets the same flags and each one traces to its rule. `python -m assistant.quality <draft.json>` runs the same check from the command line.

`data/synthetic/lab_requests/` holds synthetic examples of high-quality past requests, with a note on why each is good. They are optional: nothing depends on them. They show the thinking behind a good request, open as a copy from **My drafts**, and all pass the quality check with no flags. Real examples go in `data/private/lab_requests/` (gitignored) with the same format. To add old Word requests:

```powershell
python tools\import_legacy_request.py "F:\old requests\*.docx"              # writes data\private\lab_requests\
python tools\import_legacy_request.py old.docx --print                         # preview, writes nothing
python tools\import_legacy_request.py scan.pdf --manual scan.json             # a copier scan, typed in by hand
```

The importer reads every table cell and Word dropdown, maps them to the online form, removes names, emails, phone numbers and lab staff (add `--redact "Name"` for anyone else), stores the lab's own section and the quality flags as of the day the request was sent, and never copies the file or its pictures. Each example gets a "why it is good" and "what it missed" note to confirm; re-importing keeps those notes. Real requests name customers and programs, so they stay out of the repo, the report and the video. `data/synthetic/drafts/` has one weak demo draft per form with typical mistakes, for trying the check. All six examples pass with no flags; the four demos fail with 4 to 7 must-fix flags each.

## Lab equipment database (`equipment_db.py`)

`data/<LRT_DATA>/equipment/lab_equipment.json` lists every instrument with its area, count, model, status (planned units marked), the test methods and standards it serves, and its limits in named units. The test method catalogue links each test to its equipment. The real lab's database is in `data/private/` (from the lab capability deck); the repo has a synthetic one with the same structure.

```powershell
python equipment_db.py --data private find "thermal shock"          # or a standard: "EIA 364-70"
python equipment_db.py --data private check VG-ENV-TS --temp -65 150 # fits / problems / unknown
python equipment_db.py --data private gaps                           # values the deck does not give
```

A check never assumes: a limit missing from the database comes back as "unknown", so the assistant asks the lab instead of approving the plan. The agents reach the same functions as MCP tools (`find_equipment`, `check_equipment`); set `LRT_DATA=private` to use the real data.

## Data (`data/`)

Synthetic equipment (shadow moire + reflow chamber, thermal cycling chamber, Instron universal tester with load cells from 50 g to 100 lb), templates for equipment records and lab request fields, and a gitignored `data/private/` for real company data. See `data/README.md`.

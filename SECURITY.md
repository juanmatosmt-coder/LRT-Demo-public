# Security and data protection

The Lab Request Assistant is a local test suite. It runs on one computer, uses only synthetic data in this repository, keeps real company data in a gitignored folder, and never submits anything. This page lists what could go wrong, what stops it, and what is still open. `python tests/test_security.py` checks the server, chat and input protections (76 checks).

## What is protected

| Asset | Where it lives | Who can reach it |
|---|---|---|
| Real lists, logos, equipment database, parts directory, example requests | `data/private/` (never committed) | The server computer; other devices only after sign-in |
| Accounts | `data/private/users.json`: salted PBKDF2 hashes (240,000 rounds), no passwords | Nobody over the web |
| Saved drafts | `data/private/drafts/<user>/` | Only the signed-in owner |
| Feedback (`data/private/feedback/feedback.jsonl`) | Append-only log on the server, never committed | Anyone trusted may add; this computer and admins see all and set status; other signed-in users see their own; network guests nothing. Validated, size-limited, rate-limited (200/hour/device), screened for text aimed at the AI and stored as data only (never sent to the model); CSV export escapes formula cells |
| Google Colab version (`colab/LRT_Colab.ipynb`) | Google's cloud | SYNTHETIC data only: the notebook and `serve.py --colab` refuse to run if `data/private` holds files; the server listens on 127.0.0.1 and is reached only through Colab's per-user proxy; sign-in is off |
| Run logs (request text, model replies) | `traces/` (never committed, never served) | Only on the computer; `LRT_TRACE_TEXT=0` keeps timings and counts but drops the text |
| AI key for an approved remote AI service | The `LRT_AI_KEY` environment variable only | Never written to logs or files |

## Threats and controls, layer by layer (MAESTRO)

| Layer | Threat | Control | Tested |
|---|---|---|---|
| **Model** | Hallucinated values or rules | Code checks every plan (`spikes/plan_rules.py`), every equipment condition (`equipment_db.check`) and every draft (`assistant/quality.py`). Numbers the model extracts must appear in the request (grounding check). | Real Qwen run; quality tests |
| **Model** | Model files running code when loaded | No `trust_remote_code` and no pickle loading; weights load as safetensors from the local cache | Code review |
| **Data and memory** | Real data leaking into the repo | `data/private/*`, `traces/` and `history/` are gitignored; the repo uses synthetic data only | `git check-ignore` |
| **Data and memory** | Obsolete or wrong procedures used | Search only returns active revisions of documents in scope; quality flags obsolete revisions | Route evals: 0 obsolete rules in 30 drafts |
| **Agent framework** | Tool misuse by the model | The model never chooses or calls tools; the code calls them and the model only proposes or ranks | Design |
| **Agent framework** | Runaway loops or cost | Budget of 12 model calls for the tree search and 14 per run; stop and ask the engineer | Real Qwen run (test 5) |
| **Deployment** | Other devices reading files | The server serves an allowlist only (`gui/`, `data/templates/`, `data/synthetic/`, five private paths). It never serves `.git`, traces, source code, hidden files or directory listings. | 19 path checks, including `..` and encoded traversal |
| **Deployment** | Private data on the network | Private files and private data APIs go only to the server computer or signed-in users | Checked from a second network address |
| **Deployment** | A web page in the browser reading the local server (DNS rebinding) | Requests whose Host is not this computer or an IP address are refused (421) | Yes |
| **Deployment** | Cross-site request forgery | Writes must be JSON from the same origin (`Origin` and `Sec-Fetch-Site` are checked); cookie is `SameSite=Strict` and `HttpOnly` | Yes |
| **Deployment** | Password guessing | 5 failed sign-ins lock that account from that device for 15 minutes; at most 5 new accounts per device per hour | Yes |
| **Deployment** | Strangers creating accounts or editing data | With `--allow-lan`, sign-up works only on the server computer. Only admins edit lab data: the first account made on the server computer, or `--make-admin NAME`. Each edit is validated and the previous version is kept in `history/`. | Yes |
| **Deployment** | Stolen session | Signing out ends every session of that account; tokens are HMAC-signed and expire after 30 days | Yes |
| **Deployment** | Traffic sniffed on the network | `--tls-cert/--tls-key` serves HTTPS and marks the cookie `Secure`; the server warns when it is on the network without TLS | Manual |
| **Deployment** | The model server reachable by others | The Qwen server listens on 127.0.0.1 only. Opened to the network, it refuses to start without `LRT_SERVER_KEY` (24+ characters) and checks it on every call. | Yes (401 without or with a wrong key) |
| **Evaluation and observability** | Silent failures | Every model call, tool call, guardrail event and escalation is written to `traces/runs/<run>.jsonl` | Unit level |
| **Inputs** | Prompt injection in a request or document | `screen_untrusted()` removes hidden and direction-control characters, caps the length, and flags instructions aimed at the AI, role changes, "submit without review", credentials, links and encoded blocks. Untrusted text is fenced in the prompt as data. Whatever the model writes still goes through the code checks and the engineer. | 6 cases |
| **Inputs** | The chat used to submit, approve, or leak data | `/api/assistant` runs for this computer or signed-in users only, one turn at a time. It refuses to show prompts, keys, accounts, other users' drafts or private files; it never submits, and never sets a draft to approved. Numbers the model writes that the engineer did not give are dropped; specifications and revisions come from the retrieved passages, not the model. | 5 checks |
| **Inputs** | Script injection in the pages | Every value is inserted as text (no `innerHTML` or `eval`); Content-Security-Policy allows scripts only from the server itself | Code review; the CSP blocks outside requests |
| **Ecosystem** | Data leaving the computer | Telemetry is off (CrewAI, OpenTelemetry, LangSmith, Hugging Face); models load offline; local traffic never goes through a proxy (`NO_PROXY`). The page may contact only itself and the local model. A remote AI service needs `LRT_ALLOW_REMOTE_AI=1` and https. | Browser: only 127.0.0.1 contacted; client tests |
| **Ecosystem** | Malicious packages | The agent environment is pinned (`spikes/requirements-agents.txt`) | Partly: see open items |

## Open items

1. **Model environment not pinned.** On the laptop, run `.venv\Scripts\pip freeze > requirements-model.lock.txt` once and commit it.
2. **Commit history** still contains a personal email address and session links. Rewrite it (needs a force push) before the repository is made public.
3. **Drafts and logs are plain files.** Anyone signed in to the same Windows account can read them. Use BitLocker, and keep the laptop account private.
4. **No HTTPS by default.** Use `--tls-cert/--tls-key`, or keep `--allow-lan` to trusted networks.
5. **Uploaded documents** are not read by the model yet. When they are, pass them through `screen_untrusted()` like requests.

## Reporting

This is a course project. Report a problem to the repository owner by email or as a private GitHub issue. Do not include real company data.

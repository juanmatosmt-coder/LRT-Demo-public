# Data

**Everything committed under `data/` is SYNTHETIC** (invented for the CMU/Emeritus capstone). Real company data lives
only in `data/private/`, which is gitignored and never committed.

| Folder | Contents | In Git? |
|---|---|---|
| `templates/` | Blank equipment record and lab request field list (the field list is a placeholder until the online form's schema is captured) | yes |
| `synthetic/equipment/` | Synthetic equipment database module: shadow moire + reflow chamber (SM-1), thermal cycling chamber (TC-2), Instron universal tester (INSTRON-1) with load cells from 50 g to 100 lb | yes |
| `synthetic/lab_requests/` | SYNTHETIC model requests (EX-01 to EX-06) that pass the quality check with no flags | yes |
| `synthetic/past_requests/` | SYNTHETIC library of 30 past requests (27 good, 3 "what to avoid"), mirroring the patterns of the private library of real requests; each with why it is good, what it missed, and the quality flags. Built by `tools/make_synthetic_library.py` | yes |
| `synthetic/drafts/` | SYNTHETIC weak drafts, one per form, for trying Check quality | yes |
| `synthetic/parts/` | SYNTHETIC parts directory (`SYN-` part numbers) | yes |
| `private/` | Real company data: procedures, legacy `.docx` requests, form exports, equipment records. Same sub-folders as `synthetic/` | **never** (gitignored) |

The synthetic procedures stay in `docs/` and `docs_extended/` so the Checkpoint 3.1 evidence keeps matching.

**Switching to real data:** set `LRT_DATA=private` (PowerShell: `$env:LRT_DATA="private"`). Code reads `data/synthetic/` by default.

**Equipment rule (synthetic):** a load cell is usable when the expected peak force is between 10% and 90% of its capacity; the smallest such cell is selected (`select_load_cell` MCP tool). Edit `_rules` in the equipment file to match your lab.

Use only public, synthetic or anonymized information in anything committed or submitted for the course.

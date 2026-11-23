# SYNTHETIC past lab requests

**Everything in this folder is synthetic.** SYNTHETIC: invented for the CMU/Emeritus capstone. Not a real request; no real names, customers, programs, part numbers, lots, documents or results.

These 30 requests mirror the patterns of a private library of real past requests kept outside the repository
(`data/private/`, gitignored): the mix of test types, what good requests state (objective, method, pass criteria,
sample groups, traceability, pictures of the feature) and what they typically leave out (revisions, lots, limits,
plans in attachments, same-day dates). Use them to see what a good request looks like and what the quality check flags.

- `SYN-LR-NNN.json`: one request, in the form's own field names, with `why_good`, `gaps`, and the quality check's
  flags as of its request date (`quality_at_request_date`).
- `kind`: *good example*, or *contrast example (what to avoid)*.
- Part numbers are `SYN-`, internal specifications `SYN-GS-`, sites and units `SITE-A` / `BU-A`, customers
  "Customer A/B". Public standards (EIA-364, ASTM, IEC) are cited by number only.

Rebuild with `python tools/make_synthetic_library.py`.

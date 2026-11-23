# SYNTHETIC feedback (format example)

**SYNTHETIC.** Invented for the CMU/Emeritus capstone to show the format; not from real people.

`feedback.jsonl` is an append-only log: one JSON object per line. `event: feedback` lines are ratings
(Useful / Not needed / Wrong on a question, review point, quality flag or proposed value) or suggestions (what the
assistant should ask or check, why, how important, a good answer, and the source). `event: status` lines record review
decisions (accepted, added, rejected) with a note. See `assistant/feedback.py`.

Real feedback is written by the local server to `data/private/feedback/feedback.jsonl`, which is never committed.

    python -m assistant.feedback data/synthetic/feedback/feedback.jsonl --md

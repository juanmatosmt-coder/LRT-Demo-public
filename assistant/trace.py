"""Structured run log: one JSON line per event in traces/runs/<run_id>.jsonl, plus counters for the run summary.

Every agent step, model call, tool call, guardrail event and escalation is logged, so a run can be replayed,
inspected in the GUI, and aggregated into metrics (calls, seconds, escalations per run)."""
import json
import os
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "traces" / "runs"


class Trace:
    def __init__(self, run_id=None, on_event=None, write=True):
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.t0 = time.time()
        self.events = []
        self.on_event = on_event
        self.counters = {"llm_calls": 0, "llm_seconds": 0.0, "tool_calls": 0, "guardrail_events": 0}
        self.path = RUN_DIR / f"{self.run_id}.jsonl" if write else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, node, event, **data):
        if os.environ.get("LRT_TRACE_TEXT", "1") == "0":   # keep counts and timings, drop request and model text
            for k in ("reply", "request", "text"):
                if k in data:
                    data[k] = f"<redacted {len(str(data[k]))} chars>"
        e = {"t": round(time.time() - self.t0, 3), "run_id": self.run_id, "node": node, "event": event, **data}
        self.events.append(e)
        if event == "llm_call":
            self.counters["llm_calls"] += 1
            self.counters["llm_seconds"] += data.get("seconds", 0)
        elif event == "tool_call":
            self.counters["tool_calls"] += 1
        elif event.startswith("guardrail"):
            self.counters["guardrail_events"] += 1
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
        if self.on_event:
            try:
                self.on_event(e)
            except Exception:
                pass
        return e

    def summary(self):
        return {**self.counters, "llm_seconds": round(self.counters["llm_seconds"], 1),
                "total_seconds": round(time.time() - self.t0, 1), "trace_file": str(self.path.relative_to(ROOT)) if self.path else None}

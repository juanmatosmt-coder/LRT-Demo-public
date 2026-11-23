# Evidence: results from runs on the laptop

All runs use only the synthetic documents and data in this repository. Hardware: NVIDIA RTX 5000 Ada Laptop GPU (16 GB), Windows 11, Python 3.12.

| Folder | Produced by | Run | Used in |
|---|---|---|---|
| `checkpoint_3_1/` | `rag_demo.py` | 2026-11-02 | Checkpoint 3.1 appendix (the 4-bit run) |
| `route_comparison/` | `eval/eval_generation.py` (extended library, 5 scenarios x 6 routes, Qwen3.5-9B 4-bit) | 2026-11-03 | Checkpoint 4.1, Appendix A3-A5 |
| `validation/` | `spikes/run_all.py` (tests 1-3 and 4-5 were run separately) | 2026-11-03 | Checkpoint 4.1, Appendix A8 |

`checkpoint_3_1/`: one request through no retrieval, filtered and unfiltered retrieval, MMR and form-section retrieval, for Qwen2.5-7B, Qwen3.5-9B and Qwen3.5-9B 4-bit.

`route_comparison/generation_extended.jsonl` holds every draft in full, with the passages each route retrieved.

`validation/`: test 1-3 report (local OpenAI-compatible server, LangChain, CrewAI: all pass) and test 4-5 report (MCP tools: pass; Tree-of-Thought beam search: fail at depth 2, with raw model replies).

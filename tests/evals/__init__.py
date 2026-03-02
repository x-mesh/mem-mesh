"""DX Eval framework for mem-mesh.

3-Tier evaluation:
  Tier 1 — Deterministic: pytest logic checks (CI)
  Tier 2 — Simulated: scenario + analysis pipeline (CI)
  Tier 3 — LLM-Judged: claude CLI subprocess (manual/scheduled)
"""

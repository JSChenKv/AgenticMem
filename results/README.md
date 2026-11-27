# Shared experiment results

Current protocol: `sustained_native_v8`: five tasks from the AgentDojo banking and workspace suites whose real fact is itself a change or depends on context (`banking_2`, `banking_13`, `banking_6`, `workspace_25`, `workspace_2`; see the main README). Runs record their own protocol version; never pool across versions or extractor configurations. Raw logs and databases remain local.

No v8 run has been published yet. `scripts/export_results.py` exports runs from `data/agentdojo_runs` into `runs/`, and `scripts/analyze_pipeline.py` writes the five-stage analysis into `analysis/`.

The v1–v7 runs (all on the earlier workspace tasks 14, 15, 17, 18 and 30, including the teammate-run aditya v3 trial) were removed on 2026-11-27 when v8 replaced the tasks. They remain in git history: the last commit that contains them is `2ea5e3e`.

Native utility and semantic attack adoption are separate. Automatic labels remain provisional.
Local web history reads data/agentdojo_runs; these exports do not populate it.

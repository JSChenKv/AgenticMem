# Experiment results

No results are currently included. Obsolete experiment data and reports were removed on 2026-11-21.

The active protocol is `sustained_native_v1`: Clean, polluted with memory, and polluted without memory. Every condition runs S1, S2, S3 and the original AgentDojo task at Final. Both polluted conditions retain the payload through Final.

Start an experiment from the web or CLI. Export selected evidence with `python scripts/export_results.py`, then analyze it with `python scripts/analyze_pipeline.py`.

Native task utility, automatic semantic classification and human review are separate outcomes. Review generated text before publishing. Raw logs and memory databases stay local.

The local web reads `data/agentdojo_runs`. Git history is retained; cleanup does not erase previous commits or published GitHub history.

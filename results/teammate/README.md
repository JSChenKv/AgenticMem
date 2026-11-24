# Teammate-branch experiment results

These results were produced by the unmodified `aditya` snapshot at [c2d5bf1](https://github.com/JSChenKv/AgenticMem/commit/c2d5bf1), not by the current main-branch runner. Its `sustained_native_v3` protocol is distinct from main's historical protocol with the same version string. Use the source commit and recorded configuration to identify the design; do not pool these runs with main-branch results.

| Run | Configuration | Status |
| --- | --- | --- |
| [Hawaii findings](runs/dojo_20261123_233945_db1f1e/findings.md) | Codex task agent; Qwen extractor; Qwen and Codex memory-only answers; one repeat | completed |

[Full report](runs/dojo_20261123_233945_db1f1e/report.md) · [Structured evidence](runs/dojo_20261123_233945_db1f1e/summary.json) · [Branch-specific analysis](runs/dojo_20261123_233945_db1f1e/analysis.json) · [Validation](runs/dojo_20261123_233945_db1f1e/validation.json) · [Execution context](runs/dojo_20261123_233945_db1f1e/execution-context.json)

The analysis uses the teammate's `pipeline-stages-v4` and `asserted-values-v3`. Automatic labels remain provisional. These exports are stored separately so main's older analysis runner does not silently reinterpret the different result structure. Since the v6 merge, `scripts/analyze_pipeline.py` also reads this directory, and [the shared analysis](../analysis/pipeline_stages.md) includes this run with `pipeline-stages-v5`. Raw logs, databases, credentials and local paths are excluded.

[Main-branch results](../README.md)

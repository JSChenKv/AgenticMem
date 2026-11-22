# AgenticMem

## Active protocol

Only `sustained_native_v1` is supported. Keep the web interface and documentation in English.

- One clean S0 task creates the shared seed for the two memory-on branches.
- Conditions: `clean`, `polluted_memory_on`, `polluted_memory_off`.
- S1, S2, S3 and Final use the same fixed payload in both polluted conditions. Clean sources stay clean.
- Every session has fresh agent context and autonomously chooses memory, email and file searches.
- Memory off disables reads, writes and extraction throughout and starts with an empty store.
- Final uses the original AgentDojo task prompt and native strict utility. It has no required JSON or unknown option and never writes memory.
- Extraction follows the task agent by default. An independent extractor is an explicit optional control.
- No automatic attack search, extra schedules, synthetic reminder/plan probes, or reused controls.

## Memory and isolation invariants

Mem0 is pinned to 2.2.1 and AgentDojo to 0.1.35 (workspace v1.2.2). Do not upgrade them implicitly.
Writes use Mem0.add with the actual user question and final assistant answer. The automatic path is ADD-only; seed IDs must remain present. Explicit update/delete methods are not used by task agents.
Mem0 extraction history persists across fresh agent sessions and is included in cloned state. This is part of the mechanism, not a cleared conversation buffer.
CLI calls use an empty temporary working directory with project instructions, automatic memory and unrelated tools disabled. Task agents receive no research labels, targets, scores or condition metadata. Tools expose only simulated workspace reads and public memory id/text.
Keep local credentials, .env, raw logs and data out of Git. Shareable exports use field allowlists and still require review before publication.

## Analysis

`lab/values.py` is the current conservative asserted-value classifier derived from aditya/8183c91. The teammate has not pushed the proposed replacement yet; do not change classification methodology without a separate request.
`lab/pipeline.py` records five stages: seen, repeated in answer, saved, retrieved, adopted. Native utility, automatic semantic labels and human review stay separate. Automatic labels are provisional; missing or ambiguous answers are not DELETE outcomes. Per-query ranks are recorded at execution time.
Human annotations live in analysis-reviews.json, tied to source SHA-256, classifier version and row ID. They never overwrite original answers or scores.
Polluted sources remain available at Final, so the comparison does not isolate a memory-only causal effect or establish aggregate AgentDojo ASR.

## Development

Run `.venv/Scripts/python.exe -m pytest -q` and `node --check lab/web/benchmark.js` after relevant changes. Use mocked model calls for routine tests. New live model experiments require an explicit user request.
`lab/sessions.py` owns autonomous tool execution; `lab/sustained.py` owns the three-condition sequence; `lab/dojo.py` owns the CLI and evidence archive; `lab/benchmark.py` owns web subprocess jobs.
Obsolete runners and old experimental data were removed on 2026-11-21. Do not restore them implicitly. Git history remains available without populating active web history.

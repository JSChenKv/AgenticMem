# Pipeline analysis versions

- `pipeline_stages.json` and `pipeline_stages.md`: teammate's original v1 analysis from aditya/8183c91, preserved unchanged. Its labels were not hand-checked. The classifier and schema limitations found during integration mean these labels are not validated outcomes.
- `pipeline_stages_v2.json` and `pipeline_stages_v2.md`: separate, provisional reanalysis of saved exports using the integrated classifier and all workflow adapters. Missing evidence remains unknown; ranks are assigned only when an actual query ordering is recorded. Each session stays associated with its original run and protocol.

Do not pool historical workflows or count reused controls as new trials. Native task utility, automatic semantic screening and human review are distinct. The web interface analyzes full local run summaries and stores annotations in separate versioned sidecars; therefore it may have more retrieval evidence than a selected public export.

Reproduce with `python scripts/analyze_pipeline.py`. No model calls are made and source summaries are never rewritten.

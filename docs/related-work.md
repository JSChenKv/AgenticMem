# Related work and positioning

Notes for writing the paper. Each entry says what we took from the work and how this study differs. Verify every claim against the paper itself before citing it.

## Closest designs

- **MemoryDojo** ([arXiv 2611.09721](https://arxiv.org/abs/2611.09721)). It measures effects "where the poison can only act through memory": the later session has no access to the source, and the harness fixes retrieval. Our memory-only Final follows this design. The harness is our own; it is not derived from MemoryDojo's code. MemoryDojo uses an LLM judge.
- **Sleeper Memory Poisoning** ([arXiv 2605.15338](https://arxiv.org/abs/2605.15338)). It removes the poisoned document so that "only persistent memory can carry the attack forward". Our single-exposure schedule plays the same role, with clean sources after S1. **Must-read** before writing the persistence section.
- **MINJA** ([arXiv 2503.03704](https://arxiv.org/abs/2503.03704)). Memory injection in which the harness, not the agent, runs the memory search at answer time.
- **MemTxn**. **Must-read**; not yet summarized here. Add its citation and design notes after reading it.

## Measurement pitfalls we design around

- **Injection-Execution Dissociation** ([arXiv 2605.08442](https://arxiv.org/abs/2605.08442)). When the source stays reachable, agents re-read it: 1,480 of 2,520 attack runs re-read the source. Success there can be source-mediated rather than memory-mediated. Our v1 run showed the same thing: no native Final searched memory. That is why we added the memory-only Final and the single-exposure native Final.
- **MemSecBench** ([arXiv 2607.27080](https://arxiv.org/abs/2607.27080)). Quoting attacker content in order to reject it "does not constitute Adoption". This is why the pipeline separates *attacker content (any framing)* from *saved / asserted as fact*. Its LLM judge reached about 90% agreement with humans, which motivates our gold-set threshold: keep the rule-based classifier only if it agrees with hand labels on at least about 90%.

## What this study adds

1. **ADD-only memory as it ships today.** Mem0 2.2.1 cannot overwrite or delete through its automatic path, so tampering is functional: the real record stays in the store, and we measure whether retrieval and answers behave as if it were overwritten or ignored.
2. **Persistence after the attacker is gone**: sustained exposure versus a single exposure, with memory-only Finals at checkpoints after S1 and after S3.
3. **The same poisoned state answered by different LLMs.** Cross-model answering separates the state a model built from how each model reads it.
4. **Realistic stores.** Scripted unrelated memories and a related distractor make retrieval a real ranking, and a pre-registered design check rules out a broken seed.

## Stealth claim (paper note)

In ADD-only memory the attacker's records do exist, so "tampering leaves no malicious entry" does not hold as stated. Use the split between *saved as fact* and *attacker content* to discuss how hard attacker records are to spot: in the v1 run, Codex saved the claim only as a quoted, unconfirmed note.

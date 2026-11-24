# Mem0 2.2.1 internals that shape the mechanism

Read from the mem0ai 2.2.1 wheel source in November 2026. Re-check against the installed package before you write paper text or change extraction or retrieval code; line-level details can differ between builds.

## Write path (`Memory.add`)

- `add()` calls `_add_to_vector_store` with the additive extraction prompt (`ADDITIVE_EXTRACTION_PROMPT`). It only ever emits `ADD` events.
- `Memory.update()` and `Memory.delete()` exist but are never called by `add()`. Our task agents never call them either. An attacker therefore cannot overwrite or delete the real record through the automatic path. Tampering has to work at retrieval and answer time, which is why this study measures it there.
- Extraction input:
  - the last 10 messages, through `get_last_messages`, from the message log described below;
  - the 10 existing memories most similar to the new messages;
  - an instruction that the extractor "MUST capture the transition" when facts change.
- The extractor is asked for *Contradiction* links between new and existing facts. Mem0 2.2.1 then discards them: nothing stores or surfaces them at retrieval. This is the main defense direction for the paper's discussion section; defenses themselves are out of scope.
- `parse_messages` drops `role=tool` messages from the extraction input, but `save_messages` still stores them in the message log.
- `PAST_MESSAGE_TRUNCATION_LIMIT` is 300 characters. Older messages enter the extraction prompt truncated.

## Message log

- The log keeps 10 rows. Older rows are evicted.
- It lives in `history.db`. It is included in cloned branch state and persists across fresh agent sessions. It is part of the mechanism, not a cleared conversation buffer.
- Consequence for v3: an S2 extraction in a single-exposure branch still sees S1's question and answer through the log. A new attacker-value record after S1 is therefore not, by itself, proof that the agent repeated the claim. Check that session's own answer (`repeated_in_answer`) alongside `attacker_fact_records_added`.
- Consequence for the scripted seed: S0's extraction sees the scripted conversations in its last-10 window.

## Retrieval (`Memory.search`)

- Ranking is vector similarity only. There is no recency term, so a newer attacker record does not outrank an older real record merely by being newer.
- Scope is `user_id` only. Every session of a branch uses `researcher`.
- `Lab.search` uses the SDK defaults `top_k=20`, `threshold=0.1`, `explain=False` (`SEARCH` in `lab/core.py`, passed explicitly). `score` is still returned with `explain=False` (main v5 runs record it). Task agents see only the public `id` and `memory` fields.

## Our configuration (lab/core.py)

- Extractor: Ollama, `temperature 0`, `top_p 1`. `TracedClient` adds `num_ctx` and the `SEED` environment variable. In protocol v3 the extractor is fixed (local Qwen) for every task model.
- Embeddings: `bge-m3` through Ollama. Store: local Qdrant plus SQLite `history.db`.
- `Memory.close()` in 2.2.1 does not close the local Qdrant client; `Lab.close()` closes it explicitly.

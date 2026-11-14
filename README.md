# AgenticMem

A research platform for studying persistent agent memory with Mem0, AgentDojo, and Ollama, Codex CLI, or Claude Code. It includes an English web interface for chat and controlled memory experiments.

## Task agents and memory extraction

Select **Task agent** and **Memory extraction** in Chat's **Experiment settings** or the Benchmark sidebar. The default is **Follow task agent**: Codex extracts with Codex, Claude with Claude, and Ollama with the selected Ollama model. A task model override also applies to extraction. Mem0 invokes extraction independently inside `add()`; it does not reuse the CLI session that performed the task. Mem0's existing prompts, recent extraction history, ADD-only writes, and retrieval flow remain in place.

Choose **Independent** for mixed-model controls, such as Codex for tasks and Ollama/Qwen for extraction, or different models on the same backend. An empty independent extraction model override uses that backend's default. Follow mode does not accept a separate extraction model override. Invocation and format errors are reported directly, with no automatic fallback to Qwen. Embeddings continue to use the local `EMBED_MODEL`; Qdrant and SQLite storage remain local.

Codex and Claude use the installed CLIs' existing logins without requiring an API key. Inference runs on their respective providers' servers. When a CLI handles extraction, the conversation, relevant existing facts, and recent extraction context assembled by Mem0 are sent to that provider. Each write records its actual configuration in `trace.jsonl` under `memory_input.extraction`; memory metadata also records the extraction backend and model. Experiment `protocol.json`, `summary.json`, web details, and reports include `extraction`. An experiment's original `manifest.json.config.llm` describes SDK initialization; consult the trace for the actual extractor used by each write.

Changing Chat's extraction settings preserves existing memories. Use a new **Experiment space** for a clean comparison. Benchmark creates isolated spaces automatically. Historical runs labeled **legacy fixed extractor** should be interpreted using their original Ollama extraction configuration.

### CLI configuration

- Codex: install the CLI and run `codex login` before starting the web service.
- Claude Code: run `claude auth login`. A desktop app login does not necessarily authenticate the standalone CLI.
- If a CLI is not on PATH, set `CODEX_CLI_PATH` or `CLAUDE_CLI_PATH` in `.env` to its absolute executable path, then restart the web service. Do not paste tokens or passwords into the web interface.
- Leave **Model override** empty to use the CLI default, or specify a model available to your account. Explicit model names are recommended for reproducibility. `CODEX_MODEL` and `CLAUDE_MODEL` configure server-side defaults. Each CLI call has a default timeout of 300 seconds, adjustable with `AGENT_TIMEOUT_SECONDS`.
- `/agents` returns installation, version, and login status without exposing credentials. Login status is cached for up to 30 seconds.

In **Agent-selected tool calls** mode, Codex and Claude invoke `search_emails` and `search_files` through native MCP. An isolated stdio bridge executes the actual AgentDojo read-only tools. Shell access, file access, browsers, other connectors, and workspace write tools are unavailable. Each CLI manages its own tool loop. The existing Qwen search-recovery reminders, limited to two attempts, apply only to Ollama; the runners should not be treated as identical execution policies.

In **Controlled reference reads** mode, the platform first executes the official reference calls, then passes the actual user task and tool outputs to the selected CLI for an answer. The CLI receives a serialized conversation and cannot search again. The task model is not given the ground-truth answer.

### Task context isolation (`task_only_v1`)

Each CLI invocation uses a fresh session in a randomly named, empty working directory outside the project. It does not resume a previous task. Codex ignores user configuration and disables project-instruction and host-skill discovery. Claude disables built-in tools, automatic memory, hooks, and slash commands, restricts MCP configuration, and excludes user/project `CLAUDE.md` and `AGENTS.md` files. The official CLIs handle existing authentication; the platform does not copy credentials.

Task agents receive ordinary assistant instructions, the user task, necessary tool descriptions, and tool outputs. Memory-based questions expose only `{id, memory}`, stripping source, experiment names, task IDs, scores, and other research metadata. Full records remain available to the research pipeline. System prompts do not identify the agent as a research assistant or disclose the experimental stage, attack objective, or clean/poisoned condition. Models are not asked to pretend to be unaware. They may still infer the experimental setting from task content or CLI context, and provider or organization policies may add system-level context.

`cli_input` records the system prompt, task input, and tool definitions supplied by the platform. `cli_output` records CLI responses and errors for auditing inputs, tool calls, and failures. These logs are not the providers' complete internal model requests. New experiment protocols record CLI versions, requested models, and context policies. CLI defaults may change over time. Historical experiments remain accessible, but their earlier prompts and full metadata differ from this protocol and should not be pooled without annotation.

On the development machine, Codex has been verified with autonomous email retrieval through native MCP and a complete single-case memory pipeline. The Claude executable path is configured, but standalone CLI login was not completed during setup, so live Claude inference remains unverified. After login, run `python scripts/check_cli_agent.py claude` to verify an official read-only task.

## Runtime

The setup uses native Windows Python 3.12, Mem0 OSS **2.2.1**, and Ollama **0.40.6**. The default Ollama chat model is `qwen2.5:7b`. Multilingual embeddings use `bge-m3:latest` with 1,024 dimensions. Storage uses persistent Qdrant local and SQLite. BM25 runs through local fastembed; entity extraction uses Mem0's English spaCy model. Tasks run serially, with an 8K context for local Ollama. CLI model settings and context are managed by the respective CLIs.

Version references used during setup: [PyPI](https://pypi.org/project/mem0ai/), [Mem0 configuration](https://docs.mem0.ai/open-source/configuration), and [Ollama releases](https://github.com/ollama/ollama/releases). Stable versions were checked at installation and pinned to prevent upgrades from changing experiment behavior. Full dependencies are recorded in `requirements.lock.txt`; each experiment records model digests, prompts, and configuration in `manifest.json`.

## Getting started

### Web interface

The recommended entry point is the English **Chat + Benchmark** interface. Double-click `start-web.cmd` in the project root, or run:

```powershell
cd D:\AgenticMem
.\start-web.cmd
```

Open [Chat](http://127.0.0.1:8000/). The page provides messaging, **New session**, stored memories, and expandable **Experiment settings**. New session clears the current conversation context while preserving long-term memory. The default mode is **Read and save memories**. The web interface defaults to the `web` experiment space; the CLI defaults to `default`. Change spaces in the experiment settings. Only one process can open a space at a time, so close any CLI session using that space first. Chat history is held in page memory: refreshing clears short-term context while database memories persist.

Click **Benchmark** to open the [AgentDojo experiment page](http://127.0.0.1:8000/benchmark). Select **Family reunion** or **Hawaii itinerary**, then click **Run selected cases**. The default policy is **Controlled reference reads**; **Agent-selected tool calls** is also available. The page shows progress and compares **Clean memory**, **Poisoned memory**, and **Memory off**. Expand cards to inspect retrieved records, citation IDs, saved memories, and the source-to-summary process. **Run history** opens previous CLI or web experiments. Results are downloadable as JSON evidence and Markdown reports.

Experiments run in separate background Python processes, so refreshing or leaving the page does not stop them. The web service allows one experiment at a time and suspends chat and memory APIs during a run to avoid model contention. Gracefully stopping the web service also stops experiment subprocesses it started, retaining partial results and logs. Completed failures, controlled results, autonomous baseline failures, and process errors are shown separately rather than combined into an overall attack success rate (ASR).

| Endpoint | Purpose |
| --- | --- |
| `GET /benchmarks` | Run history |
| `POST /benchmarks` | Start a run |
| `GET /benchmarks/{run_id}` | Run status and results |
| `GET /benchmarks/{run_id}/evidence` | Download JSON evidence |
| `GET /benchmarks/{run_id}/report` | Download the report |

Example start request: `{"tasks":["user_task_14"],"exposure_policy":"reference"}`. Within a web run's directory, `web-job.json` stores process status, `progress.json` stores the current stage, and `console.log` stores process logs.

Press `Ctrl+C` in the server window to stop the web service gracefully and release its databases. The Ollama model service can continue running. The `start-web.cmd` entry point does not require executing a PowerShell script.

### Command-line chat

In PowerShell:

```powershell
cd D:\AgenticMem
.\scripts\start.ps1
```

Enter `/new` to clear the current conversation context while retaining persistent memory, or `/exit` to quit. Chat mode passes user messages to Mem0 for fact extraction.

Non-interactive commands (each `ask` starts a new session and reads memory by default):

```powershell
.\.venv\Scripts\python.exe -m lab --experiment demo --user alice remember "My project codename is Cedar. I prefer Python."
.\.venv\Scripts\python.exe -m lab --experiment demo --user alice ask "What is my project codename?"
.\.venv\Scripts\python.exe -m lab --experiment demo --user alice list
.\.venv\Scripts\python.exe -m lab --experiment demo --user alice ingest clean.txt
```

`ask --mode none` disables persistent memory; `--mode read` retrieves without writing; `--mode write` retrieves and extracts user facts. The API service and CLI cannot open the same experiment's local database simultaneously.

### REST API

```powershell
.\scripts\start.ps1 -Api
```

Open the [API documentation](http://127.0.0.1:8000/docs). `/chat`, `/memories`, `/search`, and `/ingest` accept `experiment`, `user`, and `text`; `/chat` also accepts `mode`. Each `/chat` request starts a separate short-term session. For example:

```powershell
$body = @{experiment='demo'; user='alice'; text='What is my project codename?'; mode='read'} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/chat -Method Post -ContentType application/json -Body $body
```

## Research scope and boundaries

This project retains the pinned Mem0 version's default ADD-only automatic extraction and does not expose explicit UPDATE/DELETE tools to agents. It supports research on false-fact insertion, conflicting retrieval, and persistent effects across sessions. Results should not be described as reproducing older automatic CRUD decisions. TAP search, gradient-based surrogates, and graph memory are future work and are not implemented.

The controlled external-content path is:

```text
fixtures/*.txt
  -> read_document tool output
  -> agent summary
  -> Mem0 input with the assistant role
  -> persistent memory
  -> retrieval and answering in a new session
```

Raw tool content is not presented as a user message. This is a **custom integration policy** that explicitly allows agent summaries into memory while retaining document provenance and SHA-256 hashes. It should not be treated as the default behavior of every Mem0 application.

`trace.jsonl` records model requests and raw responses, external documents, actual extraction inputs, records before and after writes, SDK events, retrieved records, and final answers. Returned record IDs establish the retrieval path; model-generated citations alone do not establish causality. Empty extractions, parsing failures, and runtime errors must be counted separately and do not automatically constitute attack success.

Each `--experiment` has separate Qdrant storage, SQLite history, a manifest, and a trace. Changing only the user ID is not a substitute for experiment isolation. Mem0's recent extraction history persists in SQLite; starting a new session clears the agent's short-term conversation, not that history.

## Clean and poisoned state comparisons

Close every CLI/API process using the `seed` experiment, then clone the same complete state:

```powershell
.\.venv\Scripts\python.exe -m lab --experiment seed clone clean_trial
.\.venv\Scripts\python.exe -m lab --experiment seed clone treatment_trial
```

Cloning includes databases, history, and logs. It refuses to overwrite an existing destination and checks Qdrant's exclusive lock. Introduce the test document only into the treatment branch, then run identical follow-up tasks in both branches. The local setup uses seed 42 and temperature 0, but GPU inference and SDK internals still do not guarantee bit-for-bit reproducibility.

State lives in `data/`, logs in `logs/`, and portable runtimes in `.tools/`. Local databases permit only one process at a time; use a Qdrant server when scaling concurrency. The service listens on `127.0.0.1` by default. With the Ollama backend, inference, embeddings, and BM25 run locally; Codex and Claude inference uses their providers as described above. Mem0 telemetry is disabled. Initial installation requires network access to download dependencies and models.

## Installation and verification

An existing deployment can be started directly. For a fresh installation, run `scripts/setup.ps1`. To rebuild with the fully pinned dependencies:

```powershell
python -m venv --without-pip .venv
python -m pip --python .venv\Scripts\python.exe install -r requirements.lock.txt
```

Run the checks:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\smoke_test.py
```

The smoke test uses real models and an isolated experiment directory to check fact extraction, retrieval and answering after reopening on-disk storage, user isolation, and document provenance. Its report is written to `logs/smoke-report.json`.

Development-machine verification on 2026-10-18 passed seven path-boundary checks, `pip check`, the live-model smoke test, and REST API checks for Chinese-language questions and answers, user isolation, and rejection of disallowed document paths. The API report is stored in `logs/api-report.json`. Retrieved results included nonzero BM25 and entity-enhanced scores. An RTX 4080 Laptop GPU used approximately 9 GB of total VRAM with both models loaded; this is an observation from that run, not a general requirement.

## AgentDojo memory pilot

The optional dependency is pinned to `agentdojo==0.1.35`. The pilot uses two native read-only tasks from workspace **v1.2.2**: `user_task_14` (family reunion email) and `user_task_30` (Hawaii itinerary document). Native tasks use actual tool calls and AgentDojo's official utility checks. The follow-up memory questions across sessions are an extension implemented by this project.

Install the optional dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-benchmark.txt
```

Double-click `run-benchmark.cmd`, or run:

```powershell
.\run-benchmark.cmd
```

To run a single task:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m lab.dojo --tasks user_task_14
```

The latest report is written to `reports/agentdojo-mini-latest.md`. Complete records for each independent run are stored in `data/agentdojo_runs/`; databases use isolated `data/experiments/dojo_*` spaces. The pilot does not use personal memories from web or CLI chat.

### Experiment flow

1. Complete the normal tool task and form initial memories from a clean summary.
2. Clone the full state into two branches and compare database hashes.
3. Give the control branch clean content and expose the treatment branch to a fixed attack at the official injection entry point.
4. Pass the original user task and the agent's assistant answer to Mem0.
5. Close and reopen the databases.
6. Ask the same follow-up question using clean memory, poisoned memory, and no memory.

Only the official read-only simulated tools `search_emails` and `search_files` are exposed; no real mailbox or cloud drive is connected. The normal baseline uses model-selected tools. Clean/poisoned exposure defaults to the **reference policy**: fixed official reference reads keep the tool traces identical across branches, changing only the text at the official injection entry point. The selected agent then generates its answer without receiving the ground truth. This separates memory-path effects from retrieval-planning errors. Use `--exposure-policy agent` for autonomous tool calls and report the two policies separately.

Default extraction following the task agent:

```powershell
python -m lab.dojo --agent-backend codex --tasks user_task_14
```

Mixed-model control:

```powershell
python -m lab.dojo --agent-backend codex --memory-backend ollama --memory-model qwen2.5:7b --tasks user_task_14
```

The corresponding web/API fields are `agent_backend`, `agent_model`, `memory_backend` (default: `follow`), and `memory_model`.

### Interpreting results

Attacks can modify only the official injection placeholder; initial correct facts are not directly rewritten in the database. The follow-up stage has access only to memory queries and cannot reread the original email, document, or attack conversation. Model requests and responses, tool outputs, memory changes, retrieval, and structured answers are logged. For Ollama, if an overly long search query yields no results, the framework can issue up to two reminders to try shorter terms. Recovery attempts remain in the logs.

If the native task fails its utility check, the `agent` policy stops that task. The `reference` policy may still run a controlled **memory-layer diagnostic**, labeled `completed_controlled_only`, which is excluded from end-to-end attack conclusions. Report these capabilities separately: successful fixed reads do not demonstrate successful autonomous tool use. A clean/poisoned follow-up comparison is valid only if the clean-memory answer is correct. All stages preserve the initial correct memories and verify that their IDs have not been deleted.

Under the reference policy, **attack exposure in both tasks is a controlled memory experiment**. Passing the normal autonomous baseline does not establish a completed autonomous attack rollout. The raw JSON field `end_to_end_eligible` indicates only that the normal task baseline passed; it is not an end-to-end attack success metric.

Failed integration and debugging runs are retained in separate run directories. The latest report corresponds to the most recent fixed-protocol run; successful runs are not selected from failures to calculate an attack success rate.

This is a **pipeline pilot with two fixed tasks and a single manual attack per task**. Target-text appearance, adoption of an incorrect answer, and model/tool errors are counted separately. Results are not native AgentDojo aggregate scores and cannot estimate overall ASR. Repeated trials, independent task splits, and automated attack search remain future work.

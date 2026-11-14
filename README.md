# 本地 Mem0 研究环境

## Task agent：Ollama / Codex CLI / Claude Code

Chat 的 Experiment settings 和 Benchmark 左侧都可以选择 **Task agent** 与 **Memory extraction**。默认 **Follow task agent**：Codex 用 Codex 提取，Claude 用 Claude 提取，Ollama 用所选 Ollama 模型提取，任务模型的 override 也会一起跟随。提取是 Mem0 在 `add()` 中发起的独立调用，不复用执行任务的 CLI 会话。Mem0 原有的提示词、近期提取历史、ADD-only 写入与检索流程保持不变。

**Independent** 选项用于混用对照，例如任务 Codex + 提取 Ollama/Qwen，或者同一后端的两个不同模型。独立提取模型 override 留空时使用该后端默认模型；跟随模式不接受单独的提取模型 override。调用或格式错误会直接报告，不会自动回退到 Qwen。embedding 继续使用本地 `EMBED_MODEL`，Qdrant 与 SQLite 存储留在本机。

Codex 和 Claude 使用已安装 CLI 的登录，不要求 API key；推理在各自服务端进行。选用 CLI 提取时，Mem0 组织的问答、相关既有事实和近期提取上下文会发送给对应服务。各次写入在 `trace.jsonl` 的 `memory_input.extraction` 中记录实际配置，记忆 metadata 也记录提取后端和模型。实验 `protocol.json`、`summary.json`、网页详情和报告均记录 `extraction`。实验空间的原始 `manifest.json.config.llm` 是 SDK 初始化配置，实际每次提取以 trace 中的配置为准。

修改 Chat 的提取配置不会删除已有记忆。若要做干净对照，请使用新的 Experiment space；Benchmark 每次自动创建独立空间。历史运行显示 **legacy fixed extractor**，仍按当时的 Ollama 提取配置解释。

- Codex：`codex login`；网页启动前应已安装并登录。
- Claude Code：`claude auth login`。桌面应用登录不一定等于独立 CLI 登录。
- CLI 不在 PATH 时，在 `.env` 配置 `CODEX_CLI_PATH` / `CLAUDE_CLI_PATH` 为实际可执行文件的绝对路径，重启网页服务。不要把 token 或密码粘贴到网页。
- Model override 可留空使用 CLI 默认模型，也可指定该账号可用的模型名。复现实验建议显式填写模型。`CODEX_MODEL` / `CLAUDE_MODEL` 可设服务端默认值。默认每次 CLI 调用超时为 300 秒，可用 `AGENT_TIMEOUT_SECONDS` 调整。
- `/agents` 仅返回安装、版本和登录状态，不返回凭据。登录状态最多缓存 30 秒。

在 **Agent-selected tool calls** 模式，Codex / Claude 使用原生 MCP 调用 `search_emails`、`search_files`；通过隔离的 stdio bridge 执行真实 AgentDojo 只读工具。未开放 shell、文件访问、浏览器、其他连接器或工作区写工具。CLI 自己完成工具循环；Qwen 原有的最多两次搜索恢复提醒仅用于 Ollama，不能把不同运行器视为完全相同的执行策略。

在 **Controlled reference reads** 模式，程序先执行官方参考调用，再把实际用户任务和工具结果交给所选 CLI 生成回答。CLI 使用序列化会话作为输入，没有重新搜索工具。没有向任务模型提供标准答案。

### 任务上下文隔离（task_only_v1）

每次 CLI 调用都使用项目目录之外、随机命名的空工作目录与新会话，不 resume 之前的任务。Codex 忽略用户配置、禁用项目指令发现及宿主技能发现；Claude 禁用内置工具、自动记忆、hooks、slash commands，限制 MCP 配置并排除用户/项目 CLAUDE.md 与 AGENTS.md。已有认证仍由官方 CLI 自己处理，平台不复制凭据。

任务 agent 收到的是普通助手指令、用户任务、必要工具描述和工具结果。记忆问答只传 `{id, memory}`，剥离 source、实验名称、task_id、评分和其他研究元数据；研究端仍保存完整记录。系统提示不再把 agent 称作 research assistant，也不告诉它实验阶段、攻击目标或是否属于干净/污染组。没有要求模型“假装不知道”，也不能保证模型无法从任务内容或 CLI 自身上下文推断实验性质。供应商与组织管理策略仍可能添加系统级上下文。

`cli_input` 记录平台传入的实际系统提示、任务输入与工具定义；`cli_output` 记录 CLI 返回和错误，供核对输入、工具调用与运行异常。它们不等于供应商完整的内部模型请求。CLI 的版本、请求模型和上下文策略写入新实验协议；CLI 默认模型可能随供应商变化。历史实验仍可查看，但旧提示/完整 metadata 与新协议有差异，不应无标注混合比较。

本机已验证 Codex 原生 MCP 自主邮件检索及单案例完整记忆闭环。Claude 内核路径已配置，但当前尚未完成独立 CLI 登录，因此未验证 Claude 的真实模型调用。完成登录后可运行 `python scripts/check_cli_agent.py claude` 验证官方只读任务。

Windows 原生 Python 3.12 + Mem0 OSS **2.2.1** + Ollama **0.40.6**。Ollama 默认聊天模型是 `qwen2.5:7b`，多语言向量使用 `bge-m3:latest`（1024 维），数据库为磁盘持久化 Qdrant local + SQLite。BM25 使用本地 fastembed；实体提取使用 Mem0 的 spaCy 英文模型。任务串行运行，本地 Ollama 使用 8K 上下文；CLI 的模型设置与上下文由各 CLI 管理。

版本核验来源：[PyPI](https://pypi.org/project/mem0ai/)、[Mem0 配置](https://docs.mem0.ai/open-source/configuration)、[Ollama 发布](https://github.com/ollama/ollama/releases)。安装时核验最新稳定版后固定版本，防止实验过程中升级改变行为。完整依赖在 `requirements.lock.txt`，每个实验的模型 digest、提示词和配置在 `manifest.json`。

## 开始使用

**推荐：英文网页界面（Chat + Benchmark）。** 双击项目根目录的 `start-web.cmd`，或者在 PowerShell 运行：

```powershell
cd D:\AgenticMem
.\start-web.cmd
```

打开 [Chat 页面](http://127.0.0.1:8000/)。网页提供发送消息、New session、实际记忆以及可展开的 Experiment settings。New session 清除当前聊天上下文并保留长期记忆；默认 Read and save memories。网页默认使用独立的 `web` 实验空间，命令行默认使用 `default`，可在实验设置里切换。同一空间只能由一个进程打开，切换前请先退出使用该空间的命令行聊天。当前网页聊天记录只保存在页面内存中，刷新页面会清除短期上下文，数据库记忆保留。

点击顶部 **Benchmark** 进入 [AgentDojo 实验页](http://127.0.0.1:8000/benchmark)。选择 Family reunion 或 Hawaii itinerary，再点击 **Run selected cases**。默认 Controlled reference reads；也可选择 Agent-selected tool calls。页面显示当前任务阶段，并列对比 Clean memory / Poisoned memory / Memory off。展开卡片可查看实际检索记录、引用 ID、保存的记忆和源内容到摘要的过程。Run history 可以打开过去的 CLI 或网页实验；结果 JSON 和 Markdown 报告可以下载。

实验使用独立的后台 Python 进程，刷新或离开页面不会停止实验。网页同一时间只启动一个实验，并在实验运行期间暂停聊天及记忆 API，避免争抢模型。正常关闭网页服务会停止它启动的实验子进程，保留部分结果与日志。实验完成后的失败、受控结果、自主基线失败和进程错误分别显示，不合并成总体 ASR。

新增接口：`GET /benchmarks`（历史）、`POST /benchmarks`（启动）、`GET /benchmarks/{run_id}`（状态/结果）、`GET /benchmarks/{run_id}/evidence`（JSON 下载）、`GET /benchmarks/{run_id}/report`（报告下载）。启动请求示例：`{"tasks":["user_task_14"],"exposure_policy":"reference"}`。网页运行目录内的 `web-job.json` 保存进程状态，`progress.json` 保存阶段，`console.log` 保存进程日志。

窗口中按 `Ctrl+C` 可正常停止网页服务并释放数据库，Ollama 模型服务可以继续运行。此入口无需执行 PowerShell 脚本。

在 PowerShell 中：

```powershell
cd D:\AgenticMem
.\scripts\start.ps1
```

聊天输入 `/new` 清除当前对话上下文并保留持久记忆，`/exit` 退出。聊天模式会把用户消息交给 Mem0 提取事实。

非交互命令（每条 `ask` 都是新会话，默认只读记忆）：

```powershell
.\.venv\Scripts\python.exe -m lab --experiment demo --user alice remember "My project codename is Cedar. I prefer Python."
.\.venv\Scripts\python.exe -m lab --experiment demo --user alice ask "What is my project codename?"
.\.venv\Scripts\python.exe -m lab --experiment demo --user alice list
.\.venv\Scripts\python.exe -m lab --experiment demo --user alice ingest clean.txt
```

`ask --mode none` 禁用持久记忆；`--mode read` 检索但不写入；`--mode write` 检索并提取用户事实。API 服务与 CLI 不能同时打开同一个实验的本地数据库。

REST API：

```powershell
.\scripts\start.ps1 -Api
```

打开 [API 文档](http://127.0.0.1:8000/docs)。`/chat`、`/memories`、`/search`、`/ingest` 接受 `experiment`、`user`、`text`，`/chat` 还接受 `mode`。每个 `/chat` 请求独立开始短期会话。示例：

```powershell
$body = @{experiment='demo'; user='alice'; text='What is my project codename?'; mode='read'} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/chat -Method Post -ContentType application/json -Body $body
```

## 与 proposal 对齐的边界

本项目保留最新 Mem0 的默认 ADD-only 自动提取，未给 agent 开放显式 UPDATE/DELETE。它适用于虚假事实写入、冲突检索、跨会话持续影响的研究；不能把实验结果描述为旧版自动 CRUD 决策的复现。TAP 搜索、梯度 surrogate 和图记忆属于后续实验，当前未实现。

受控外部内容路径：`fixtures/*.txt → read_document 工具结果 → agent 总结 → assistant 角色的 Mem0 输入 → 持久记忆 → 新会话检索/回答`。工具原文不会伪装成用户消息。此路径是**自定义集成策略**：它明确允许 agent 总结进入记忆，并保留文档来源和 SHA-256；不能等同于所有 Mem0 应用的默认行为。

`trace.jsonl` 记录实际模型请求与原始响应、外部文档、实际提取输入、写入前后记录、SDK 返回事件、检索记录及最终回答。返回记录 ID 证明检索路径，模型输出的 citation 不单独作为因果证据。空提取、解析失败和运行错误应独立统计，不能自动记为攻击成功。

每个 `--experiment` 都有独立 Qdrant、SQLite 历史、manifest 和 trace；仅更换 user ID 不替代实验隔离。Mem0 自身的近期提取历史会持久保存在 SQLite 中；新会话只清除 agent 的短期聊天，不清除该历史。

## 干净/污染状态对照

关闭使用 `seed` 实验的全部 CLI/API 进程后，从同一份完整状态复制：

```powershell
.\.venv\Scripts\python.exe -m lab --experiment seed clone clean_trial
.\.venv\Scripts\python.exe -m lab --experiment seed clone treatment_trial
```

复制包含数据库、历史和日志；拒绝覆盖目标目录，并检查 Qdrant 独占锁。之后只在 treatment 中引入测试文档，两组运行相同后续任务。种子设为 42、温度 0，但 GPU 推理和 SDK 内部处理仍不保证位级可重复。

所有状态在 `data/`，日志在 `logs/`，便携运行时在 `.tools/`。数据库限制为单进程访问；扩展并发时应切换 Qdrant 服务端。默认只监听本机 `127.0.0.1`，模型推理、embedding、BM25 均在本机，Mem0 遥测关闭。首次安装需联网下载依赖和模型。

## 安装与验证

已部署环境可直接启动；重新安装运行 `scripts/setup.ps1`。使用锁定的完整依赖重建可执行：

```powershell
python -m venv --without-pip .venv
python -m pip --python .venv\Scripts\python.exe install -r requirements.lock.txt
```

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\smoke_test.py
```

Smoke test 使用真实模型和独立实验目录，检查事实提取、磁盘关闭重开后的检索/回答、user 隔离和文档来源。报告：`logs/smoke-report.json`。

2026-10-18 本机验证：7 项路径边界检查通过；`pip check` 通过；真实模型 smoke test 通过；REST API 中文问答、user 隔离和文档路径拒绝检查通过。API 报告在 `logs/api-report.json`。实际检索结果包含非零 BM25 和实体增强分数。RTX 4080 Laptop 两个模型同时加载时观察到约 9GB 总显存占用；这只是本次运行观察值。

## AgentDojo 小规模记忆实验

可选依赖固定为 `agentdojo==0.1.35`，使用 workspace **v1.2.2** 的两个原生只读任务：`user_task_14`（家庭聚会邮件）和 `user_task_30`（夏威夷行程文档）。原生任务用真实 Ollama 工具调用和官方 utility 检查；后续跨会话记忆问答属于本项目扩展。

首次安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-benchmark.txt
```

双击 `run-benchmark.cmd` 或执行：

```powershell
.\run-benchmark.cmd
```

也可只跑一个任务：

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m lab.dojo --tasks user_task_14
```

结果见 `reports/agentdojo-mini-latest.md`；每次独立运行的完整记录在 `data/agentdojo_runs/`，数据库在独立的 `data/experiments/dojo_*` 空间中，不使用网页/命令行的个人记忆。

流程：正常工具任务 → 正常摘要形成初始记忆 → 完整克隆为两个分支并核对数据库哈希 → 对照分支继续接收正常摘要、处理分支接触官方入口中的固定攻击 → 原始用户任务＋agent 的 assistant 回答交给 Mem0 → 关闭重开数据库 → 相同问题分别使用干净记忆、污染记忆、关闭记忆回答。

实验只开放 `search_emails`、`search_files` 两个官方只读模拟工具，未连接真实邮箱或云盘。正常基线由模型自主选择工具；默认的干净/污染暴露阶段使用 **reference 策略**：固定官方参考读取调用，两组工具轨迹一致，只改变官方入口中的文本，随后由所选 agent 生成回答，不向模型提供标准答案。这样先隔离记忆路径与检索规划错误。`--exposure-policy agent` 可另跑自主工具调用版本，两种策略应分别报告。

CLI 示例：默认跟随 `python -m lab.dojo --agent-backend codex --tasks user_task_14`；混用对照 `python -m lab.dojo --agent-backend codex --memory-backend ollama --memory-model qwen2.5:7b --tasks user_task_14`。网页/API 对应字段是 `agent_backend`、`agent_model`、`memory_backend`（默认 `follow`）和 `memory_model`。

攻击只能修改官方 injection placeholder；初始正确事实不直接从数据库改写。后续阶段只提供记忆查询，无法重新读取原邮件/文档或攻击对话。模型请求和响应、工具结果、记忆变化、检索与结构化答案均有日志。搜索词过长导致无结果时，框架最多两次提醒模型尝试短词，恢复过程保留在日志中。

原生任务 utility 未通过时，`agent` 策略停止该任务；`reference` 策略仍可执行受控读取的**记忆层诊断**，标记为 `completed_controlled_only`，不进入端到端攻击结论。两种能力分别报告，不能用固定工具读取成功替代自主工具调用成功。只有干净记忆阶段答对，后续干净/污染对照才有效。所有阶段都保留初始正确记忆，并校验其 ID 未被删除。

reference 策略下，**两个任务的攻击暴露阶段都是受控记忆实验**；正常自主基线通过也不等于完成自主攻击 rollout。原始 JSON 的 `end_to_end_eligible` 只表示正常任务基线通过这一前提，不能当作端到端攻击成功指标。

接入调试中的失败运行也保存在独立运行目录中；最新报告对应最后一次固定协议运行，并非从失败运行中挑选成功结果计算攻击成功率。

这是**两个固定任务、单次人工攻击的 pipeline pilot**。目标文本出现、错误答案被采用、模型/工具错误分别统计；不作为原生 AgentDojo 总分，不可据此估计总体 ASR。重复试验、独立任务划分和自动攻击搜索仍需后续扩展。

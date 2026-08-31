# Local Coding Agent Design

## 1. 项目目标与范围

本项目从零实现一个 Windows 优先、Python 编写的本地 Coding Agent。用户通过一次性 CLI 命令提交编程任务，Agent 默认调用 OpenAI 官方 Responses API，也可显式选择 OpenAI-compatible Chat Completions endpoint；Agent 自主检查工作区、读取和修改文本文件、执行受控命令、验证修改，并以明确的终止状态结束。

概念命令如下：

```text
coding-agent "修复当前项目中的失败测试" --workspace <path> --verify "pytest -q"
```

`--verify` 是可选参数：

- 用户提供时，该命令是最终强制验证门槛。只有它在最后一次文件修改之后执行且退出码为 `0`，Agent 才能报告成功。
- 用户未提供时，Agent 优先接受模型通过安全策略选择的可信验证命令；若当前修改链没有模型或用户验证证据，则可退回确定性的本地文件完整性验证。已有真实验证因后续修改而过期时不得降级。完整性验证只证明变更文件仍位于工作区、大小合规、可按 UTF-8 读取，并对 Python、JSON、TOML 做语法解析，不声称测试、编译或程序运行成功。
- 最终报告始终展示真实执行的验证命令、来源、退出码、标准输出、标准错误、超时状态和截断状态。

首版的主要特色是修改后的自动验证和失败后迭代修复；辅助特色是结构化上下文压缩。最终演示使用带失败测试的小型 Python 项目，并固定传入 `--verify "pytest -q"`。

## 2. 考核边界与核心自研逻辑

项目不得使用任何 Agent 框架或 Agent SDK，不得封装现成 Agent 产品，也不得使用 API 服务端托管的文件或代码执行工具。只允许使用官方 OpenAI Python 模型客户端和模型 endpoint 的原生函数调用接口。

以下逻辑必须由本项目在本地自行实现：

- Agent 主循环与状态迁移。
- 对话历史和上下文预算管理。
- 上下文压缩范围选择、摘要校验和降级策略。
- 内部消息、工具调用和工具结果格式。
- 工具定义、注册、参数校验、安全授权与本地执行。
- Responses 与 Chat Completions 模型输出解析和内部格式转换。
- 文件修改账本和验证证据时效管理。
- 重试、错误分类、重复调用检测和终止条件。
- JSONL 事件日志、脱敏和最终报告。

## 3. 技术选择

- 语言：Python。
- 运行平台：Windows 优先，不承诺首版跨平台支持。
- 交互方式：一次性任务输入，Agent 自主运行至终止；不提供聊天式 REPL。
- 模型接口：默认使用 OpenAI 官方 Responses API；可显式选择标准 OpenAI-compatible Chat Completions endpoint。
- API 模式：`--api-mode` 只接受 `responses` 和 `chat-completions`，默认 `responses`。
- Endpoint 配置：`responses` 禁止 `--base-url` 并继续使用官方默认地址；`chat-completions` 必须显式提供合法的 HTTPS `--base-url`，项目不硬编码或自动探测供应商。
- 模型配置：通过 `--model` 或 `OPENAI_MODEL` 指定；两者都不存在时以配置错误退出。
- 运行预算：每个 run 显式选择 `standard` 或 `deep`，默认 `standard`；档位在 run 创建后不可变。
- 凭据：Responses 只读取 `OPENAI_API_KEY`，Chat Completions 只读取 `CHAT_COMPLETIONS_API_KEY`；两者不互相回退，也不提供 API Key CLI 参数。
- 运行依赖：使用已批准的 `openai`、`fastapi` 和 `uvicorn`，其余功能优先使用标准库。
- 测试依赖：使用已批准的 `pytest` 和 `httpx`。
- 包布局：生产代码放在 `src/coding_agent/`，测试放在 `tests/`。

## 4. 整体架构

```text
CLI / Config
    |
    v
AgentRunner <------> ModelClient
    |                    |
    |                    +------> OpenAIResponsesClient ------> OpenAI Responses API
    |                    +------> ChatCompletionsModelClient -> compatible Chat Completions API
    |
    +------> ProgressLedger
    +------> Layered ModelCallBudget
    +------> ContextManager
    +------> TerminationPolicy
    +------> VerificationGate
    |
    v
ToolRegistry -> SchemaValidator -> SafetyPolicy -> Local Executor
    |
    v
AgentState -> JSONL EventLogger -> FinalReport
```

核心边界如下：

- 模型只能输出文本或结构化工具调用，不能直接执行任何动作。
- `AgentRunner` 是唯一负责主循环和顶层状态迁移的组件。
- `ToolRegistry` 是所有本地能力的唯一入口。
- `SafetyPolicy` 使用确定性代码裁决，不接受模型覆盖。
- `VerificationGate` 独立于模型文本决定是否允许成功。
- `ModelClient` 将 Agent 核心与 OpenAI SDK 及 endpoint 形状隔离；SDK 类型不得进入 Agent、消息或工具层。
- `EventLogger` 只记录经过脱敏的执行事实，不记录隐藏推理内容。

## 5. 模块职责与接口

计划中的模块位于 `src/coding_agent/`：

| 模块 | 职责 | 主要依赖 |
| --- | --- | --- |
| `cli.py` | 解析一次性任务、工作区、模型、API 模式、base URL 和验证参数；映射退出码 | `config.py`, `agent.py` |
| `config.py` | 读取模式专用凭据、归一化配置并在联网前验证 mode/URL 组合 | 标准库 |
| `messages.py` | 定义供应商无关的消息、工具调用和结果类型 | 标准库 |
| `state.py` | 定义 `AgentState` 和验证、终止枚举 | `messages.py` |
| `model.py` | 定义 `ModelClient` 协议、请求响应类型和 `FakeModelClient` | `messages.py` |
| `budget.py` | 定义运行预算档位和不可变的分层预算参数 | 标准库 |
| `progress.py` | 定义执行阶段、进度账本、决策检查点和无进展判定 | `messages.py`, `budget.py` |
| `openai_client.py` | 在内部类型和 OpenAI Responses API 之间转换 | `model.py`, `openai` |
| `chat_completions_client.py` | 在内部类型和 OpenAI-compatible Chat Completions API 之间转换 | `model.py`, `openai` |
| `agent.py` | 执行显式 Agent 主循环 | 上述核心接口 |
| `context.py` | 判断压缩、选择完整历史前缀、生成并校验摘要、执行降级 | `model.py`, `state.py` |
| `verification.py` | 维护验证时效并判定成功资格 | `state.py`, `tools` |
| `termination.py` | 轮次、工具数、时间、重复和连续失败判定 | `state.py` |
| `safety.py` | 工作区路径、链接逃逸和命令策略 | 标准库 |
| `tools/base.py` | 工具协议、schema 和统一结果 | `messages.py` |
| `tools/registry.py` | 工具注册、分派、校验、授权和执行流水线 | `tools/base.py` |
| `tools/filesystem.py` | 目录列举、文件读取、精确替换和新文件创建 | `safety.py` |
| `tools/shell.py` | Windows 命令解析、受控执行、超时和输出截断 | `safety.py` |
| `tools/java.py` | 严格发现 Java 源码和黑盒用例，编译、运行、比较并产生安全结构化结果 | `safety.py`, `tools/shell.py` |
| `logging.py` | 脱敏 JSONL 事件日志 | `state.py`, `messages.py` |
| `report.py` | 生成面向用户的最终证据摘要 | `state.py` |

核心接口保持小而明确：

```text
ModelClient.complete(ModelRequest) -> ModelResponse
ToolRegistry.execute(ToolCall, ExecutionContext) -> ToolResult
ContextManager.prepare(AgentState) -> PreparedContext
VerificationGate.evaluate(AgentState) -> VerificationDecision
TerminationPolicy.check(AgentState, monotonic_time) -> TerminationDecision
```

## 6. Agent 主循环

Agent 使用同步、显式的 `while` 循环。每轮按以下顺序执行：

1. 检查用户取消、内部不变量、已有终止条件和 `ProgressLedger` 的决策。
2. 让 `ContextManager` 构建本轮活动上下文；达到高水位时先压缩到低水位。
3. 同步摘要产生的分层预算计数，并重新检查时间、主调用和 provider 硬限制。
4. 在不可变基础指令后追加只含阶段、剩余预算和检查点的确定性运行控制段。
5. 通过 `ModelClient` 调用主模型并将输出解析为内部 `ModelResponse`。
6. 如果存在工具调用，按响应中的顺序逐个执行：
   - 验证工具存在且 `call_id` 未重复；
   - 校验 JSON 参数和工具 schema；
   - 执行路径或命令安全授权；
   - 执行本地工具并捕获统一结果；
   - 将 `ToolResult` 加入历史、日志和状态。
7. 工具完成后更新弱/强进展、执行阶段、错误计数、修改账本和验证证据。
8. 文件工具成功修改内容时增加 `mutation_index`，记录文件，并把现有验证标记为 `STALE`。
9. 如果模型返回完成文本且没有工具调用，零修改、零验证的运行可在 `modify` 或 `read_only` 下进入 `ANSWERED`；这里的 `modify` 是能力边界，不代表本次运行必须修改。存在修改时，该文本只是完成候选并进入 `VerificationGate`。
10. 修改后的新鲜验证通过时进入 `SUCCESS`；实际执行过但失败或因后续修改而过期的模型/用户验证不会被完整性兜底覆盖。当前修改链没有这类证据且未提供强制 `--verify` 时，可运行确定性的本地完整性验证。`ANSWERED` 与完整性验证都不等同于测试或编译成功。
11. 任何预算耗尽、检查点后的持续无进展或不可恢复错误都进入带原因的 `FAILED`，不得死循环。

普通决策检查点生效后，`standard` 只允许最后 1 个尝试读取的响应批次，`deep` 允许 2 个；也就是 **Standard 1 / Deep 2**。整轮只有重复读取时直接关闭读取而不获得该额度。额度耗尽后的只读调用返回配对的 `agent_rejected:decision_required`，不执行工具；同一模型响应中的合法修改调用仍按顺序执行，因此门控不会拆散多文件修改批次。第一次决策无进展后，在硬预算允许时保证一次纠正响应，第二次仍无行动才终止。

`AgentState.has_unverified_changes` 是由修改序号与最新验证证据派生的只读事实。存在未验证修改时，只允许精确的可信验证调用；安全策略拒绝命令后，Agent 收到不包含原命令的有界纠正说明。模型直接声明完成且没有当前验证证据时，Agent 可执行本地完整性验证；完整性失败或已经存在当前失败验证时继续保持未验证状态，文件保留且不得进入 `SUCCESS`。

工具调用首版顺序执行，不实现并行。`AgentState` 保存简短的 `current_goal` 和 `open_issues`，但不引入独立 Planner。

## 7. 消息与工具调用格式

内部消息不暴露 OpenAI SDK 对象。逻辑结构如下：

```json
{
  "kind": "tool_call",
  "id": "call_123",
  "name": "read_file",
  "arguments": {
    "path": "src/example.py",
    "start_line": 1,
    "end_line": 200
  }
}
```

```json
{
  "kind": "tool_result",
  "call_id": "call_123",
  "tool_name": "read_file",
  "status": "ok",
  "output": "...",
  "error": null,
  "metadata": {
    "exit_code": null,
    "timed_out": false,
    "truncated": false,
    "duration_ms": 8,
    "changed_paths": []
  }
}
```

`status` 只能是 `ok`、`error` 或 `rejected`。工具调用和结果必须通过 `call_id` 一一对应。任何可空字段都显式使用 `null`，不靠字段缺失表达含义。

`ModelRequest.instructions` 是独立于消息历史的可空运行指令字段。`RunInstructionBuilder` 在每次应用运行开始时只构建一次不可变 `RunInstructionSnapshot`，顺序固定为内置基础指令、工作区根目录 `AGENTS.md`、可选的已选择 Skill 指令。根 `AGENTS.md` 和 Skill 指令分别限制为 65,536 个 UTF-8 字节；根文件使用 `PathGuard` 拒绝 reparse/symlink 逃逸，只接受 UTF-8（可带 BOM），并统一换行。快照正文不进入 repr、日志、工具或 FinalReport，只把 SHA-256 和字符数作为可安全比较的元数据。

`ModelResponse` 包含：

- 可空文本。
- 有序 `ToolCall` 列表。
- 可空用量信息。
- 可空供应商响应 ID。
- 当前适配器需要的 opaque continuation items。

Responses 的 opaque continuation items 仅驻留内存，用于正确续接 Responses 输出；不写日志、不暴露给工具、不作为项目自己的语义状态，压缩后会被丢弃。Chat Completions 不使用 continuation，始终返回空值，并在每次请求中发送 `ContextManager` 准备的完整内部历史。

## 8. 模型调用层

两个生产适配器都实现既有 `ModelClient.complete(ModelRequest) -> ModelResponse` 边界，使用官方 SDK 作为 HTTP 客户端，但不让 SDK 类型越过各自适配层。Agent、消息、工具、上下文、验证和报告层不感知 API 模式。

`StreamingModelClient` 是加法式、可选的 provider-neutral 协议；它不会改变 `ModelClient.complete` 的公共签名。主模型调用在配置了内存回调时通过 `invoke_model_stream` 发送 `TEXT_DELTA`、`RESPONSE_COMPLETED` 或 `RESPONSE_DISCARDED`。没有回调时保持原有同步路径；上下文摘要始终使用同步调用并且不接收运行指令或流事件。结构化“不支持流式”只允许在首个 provider delta 前回退到同步请求，且流式尝试与回退共享同一次 logical call 和 run-scoped provider attempt 预算。

`OpenAIResponsesClient` 的既有行为保持不变：

- 请求设置 `store=False`。
- 流式路径额外设置 `stream=True`，只接受明确列入 allowlist 的 Responses 生命周期事件；普通文本 delta 对外发送，函数参数、reasoning 和 encrypted content 只在适配器内校验且不外发。
- 不使用 `conversation` 或 `previous_response_id` 代替本地历史。
- 将本地消息和 strict function schemas 转成 Responses API 输入。
- 保存当前响应中续接所需的 `response.output` 项。
- 把本地工具结果转换成具有匹配 `call_id` 的 `function_call_output`。
- 上下文压缩后，用结构化摘要和最近消息开启新的无状态上下文段。
- 默认最大输出为 4096 tokens，并计入真实用量日志。
- 不记录认证头、隐藏推理或加密推理载荷。

`ChatCompletionsModelClient` 是独立、加法式适配器：

- 只在显式 `chat-completions` 模式下构造，要求用户提供绝对 HTTPS base URL；URL 解析前拒绝 C0/DEL 控制字符、内部空白和反斜杠；不根据 URL 或响应自动猜测模式。
- 将每次 `ModelRequest` 中的完整内部历史映射为 user、assistant、assistant `tool_calls` 和带 `tool_call_id` 的 tool 消息。
- assistant 工具调用消息必须紧邻并按顺序匹配其全部工具结果；适配器在 SDK 调用前重新验证该不变量，包括压缩后的历史。
- 将 strict function schemas 映射为 Chat Completions function tools，使用 `max_tokens` 传递输出上限。
- 直接检查 `choice.message.tool_calls`，不依赖 `finish_reason` 判断工具调用；允许文本与工具调用共存，也允许供应商在有工具调用时返回 `finish_reason="stop"`。
- 只接受恰好一个 choice、标准 function tool calls、唯一非空 call ID 和 JSON object arguments；`finish_reason` 只允许 `stop` 或 `tool_calls`，截断、内容过滤、空或未知完成原因及空响应均作为稳定的无效响应错误。
- `usage` 若存在，必须完整提供非负的 prompt、completion 和 total token；非空响应 ID 只以哈希形式进入观察日志。
- SDK 在返回对象前抛出的 `APIResponseValidationError` 或 `json.JSONDecodeError` 与解析器拒绝一样归为非致命 `invalid_model_response`，不重试，并丢弃异常文本、响应体和 JSON doc。
- 不使用服务端 conversation、`previous_response_id` 或其他持久状态；`ModelResponse.continuation` 始终为空。
- 流式路径使用 `stream=True`，按 tool index 聚合可交错的函数调用参数片段，保持 call ID、名称、类型和响应 ID 稳定，再复用同步解析器生成内部响应。

配置组合在任何 SDK 构造或网络请求前验证：Responses 使用官方默认 endpoint 且拒绝 `--base-url`；Chat Completions 要求合法 HTTPS `--base-url`。两种模式使用互不回退的环境变量凭据。可配置 base URL 不代表任意服务兼容，目标 endpoint 还必须正确实现标准 Chat Completions 函数工具调用、call ID 和 tool result 语义。

模型错误分为：

- 瞬时错误：网络超时、429、5xx。使用短指数退避，最多重试两次。
- 致命错误：密钥缺失、认证失败、模型不存在或请求配置非法。立即失败，不重试。
- 不完整或不可解析响应：记录错误并进入连续失败计数，必要时把简洁错误反馈给下一轮。

两个生产适配器都关闭 SDK 内建重试，由本地适配器执行 0.25 秒和 0.50 秒的最多两次重试。每次真实 provider 尝试都领取共享 `ModelCallBudget`；预算不足时不发请求。外部异常统一转换为稳定、脱敏的本地错误，不输出密钥、Authorization header、原始响应体或 SDK exception repr。

流式请求只在首个文本或函数参数 delta 到达前允许上述瞬时错误重试。任何 delta 到达后发生中断都丢弃本轮部分文本、禁止重试和同步回退，并产生稳定的 `StreamInterruptedError`。适配器总会尽力关闭流；清理失败不能覆盖已经存在的主异常或 `BaseException`。

`FakeModelClient` 接收预设的响应序列，记录收到的请求，并在序列耗尽时明确报错，以支持完全离线、确定性的主循环测试。

## 9. 工具定义与本地执行

所有工具使用 strict JSON schema，所有属性明确声明，`additionalProperties` 为 `false`。API schema 只提高输出可靠性，本地仍执行完整校验。

### `list_directory`

- 参数：`path`、`recursive`、`max_depth`、`max_entries`。
- `path` 必须是工作区相对目录。
- `max_depth` 范围为 1 至 3，`max_entries` 范围为 1 至 500。
- 输出按稳定顺序排列，并在达到限制时标记截断。

### `read_file`

- 参数：`path`、`start_line`、`end_line`。
- 只读取 UTF-8 文本。
- `start_line` 从 1 开始；`end_line` 可以为 `null`。
- 单次最多读取 256 KiB，返回实际行号和截断状态。

### `replace_text`

- 参数：`path`、`old_text`、`new_text`、`expected_count`。
- `expected_count` 必须为正整数。
- 实际匹配次数不等于预期时零修改并返回错误。
- 成功后记录文件路径并使旧验证失效。

### `write_file`

- 参数：`path`、`content`。
- 只创建不存在的 UTF-8 文本文件，不覆盖现有文件。
- 单次写入最多 512 KiB。
- 首版不提供删除、移动或权限修改。

### `run_command`

- 参数：`command`、`purpose`。
- `purpose` 只能是 `inspect`、`test` 或 `verification`。
- 命令字符串先按 Windows 命令行规则解析为参数数组，再以 `shell=False` 执行。
- 捕获命令、工作目录、退出码、stdout、stderr、耗时、超时和截断状态。

### `run_java_tests`

- 参数：`source_root`、`main_class`、`tests_directory`、`purpose`。
- `purpose` 只能是 `test` 或 `verification`；只有后者可形成最终验证证据。
- 最多稳定发现 500 个 `.java` 源文件和 200 对 `.in`/`.out` 黑盒用例。
- 输入上限为 256 KiB，期望输出上限为 64 KiB；期望输出只接受 UTF-8。
- 使用可信系统 `javac.exe`/`java.exe`、`shell=False`、显式 classpath 和 `-proc:none`，不允许模型提供可执行文件或 Java 命令字符串。
- 编译和全部用例共享最长 60 秒单调时钟期限；实际输出沿用每流 64 KiB 上限。
- 期望与实际输出只归一化换行，然后精确比较。
- 该工具适用于可信工作区，不是操作系统沙箱，也不是 Maven、Gradle 或 JUnit runner。

统一执行流水线是：`Dispatch -> Validate -> Authorize -> Execute -> Observe`。任何阶段失败都产生统一 `ToolResult`，不会抛出未处理异常退出主循环。

## 10. 数据流

1. CLI 将任务、工作区、模型、可选验证命令和限制转换成 `RunConfig`。
2. `AgentRunner` 创建 `AgentState`、事件日志和首条用户消息。
3. `ContextManager` 根据本地历史构建 `ModelRequest`。
4. `ModelClient` 返回文本和工具调用。
5. `ToolRegistry` 校验、安全授权并执行工具。
6. 工具结果同时进入消息历史、结构化状态和脱敏日志。
7. 文件修改更新修改账本并使验证状态失效。
8. 模型完成候选触发最终验证。
9. 验证失败结果返回上下文；验证成功或终止策略触发后生成最终报告。

日志默认写入工作区的 `.coding-agent/logs/<run_id>.jsonl`。`.coding-agent/` 是内部保留目录，模型文件工具不得读取或修改；未来项目骨架需将其加入 `.gitignore`。

## 11. 上下文管理策略

上下文继续使用确定性的 JSON 序列化字符数和消息项数量，不增加 tokenizer 依赖。字符硬上限为 60,000，48,000 时触发压缩，目标不高于 33,000；消息项硬上限为 24，20 项时触发压缩，目标不高于 12 项。字符数或消息项任一达到高水位都触发，压缩结果必须同时满足两项目标，避免刚压到硬上限下方后立即再次压缩。

压缩以完整 turn 为边界，绝不拆开 assistant tool call 与对应 tool results。初始用户目标始终保留，最近完整交互优先保留；为达到低水位可以继续扩大被移除的最旧前缀，必要时可把最后一个已完成 turn 纳入摘要。若仅初始目标和受限摘要仍超过硬预算，则以 `context_budget_exhausted` 安全终止。

结构化摘要包含：

- `goal`
- `established_facts`
- `files_examined`
- `changes_made`
- `commands_and_results`
- `unresolved_errors`
- `open_issues`
- `verification_state`
- `avoid_repeating`

以下事实由本地状态强制合并进摘要，不信任模型自行保留：原始任务、工作区相对边界、修改文件、最近修改序号、验证命令及来源、退出码、验证序号和终止计数。摘要不得包含宿主机绝对工作区路径。

语义摘要通过一次无工具、无 continuation、无运行指令的 `ModelClient` 调用生成，只消耗摘要专用逻辑预算。输出必须是字段完整且受大小限制的 JSON；解析器只接受裸 JSON，或外围仅包含空白和单一 `json` 代码围栏的 JSON，围栏外正文、多对象、缺少字段和类型错误仍属于非法摘要。每个新 run 初始允许模型摘要；普通 `ModelError`、非法摘要或摘要专用额度耗尽时，当前压缩立即使用确定性本地摘要，并把本 run 锁定为本地摘要。后续压缩不再请求模型；下一次新 run 重新获得一次模型摘要机会。致命模型错误、全局 provider 预算耗尽、内部不变量和 `BaseException` 不降级。

确定性 fallback 在摘要字符上限内按首次出现顺序保留尽可能多的去重、安全、工作区相对检查目标，不再只保留固定数量的最新路径。它不复制成功工具的正文，也不包含宿主机绝对路径、凭据、continuation 或 provider payload；较新的完整工具 turn 继续提供实际内容，路径清单只负责维持导航连续性。

没有压缩时 continuation 原样透传；压缩成功时在完整新消息序列通过校验后同时替换活动历史并清空 continuation。摘要响应产生的 continuation 永远丢弃，continuation、encrypted reasoning 和 provider payload 不进入摘要、日志、报告、Session 或 GUI。

字符数是 token 数的保守近似。首版不引入额外 tokenizer 依赖。

## 12. 错误处理

错误按下列方式处理：

| 类型 | 行为 |
| --- | --- |
| 模型瞬时错误 | 指数退避，最多重试两次；仍失败则记一次连续错误 |
| 模型致命错误 | 立即 `FAILED` |
| 未知工具或坏参数 | 不执行，返回 `rejected` 或 `error` 给模型 |
| 文件不存在或替换不匹配 | 返回可恢复 `ToolResult` |
| 命令非零退出 | 返回完整结果，允许模型修复 |
| 命令超时 | 终止子进程树，返回 `timed_out=true` |
| 安全拒绝 | 不执行，记录稳定错误码和简洁原因 |
| 验证失败 | 作为任务证据回流，不视为程序崩溃 |
| 摘要普通错误或非法结构 | 本次压缩使用确定性降级摘要，并为当前 run 熔断后续模型摘要 |
| 日志写入失败 | 向 stderr 报告并停止运行，避免产生不可审计执行 |
| 用户中断 | 尽力刷新日志，以退出码 130 结束 |

成功的不同工具调用、不同结果、文件修改或新的验证结果都会重置“无进展重复”计数。普通工具错误不会抹除此前真实执行事实。

## 13. 安全限制

### 文件系统

- 文件工具只接受相对路径。
- 拒绝绝对路径、空路径、NUL 字符和 `..` 父级跳转。
- 使用规范化绝对路径和 `commonpath` 检查工作区包含关系。
- 检查现有路径组件的符号链接、junction 和 reparse point；解析后落在工作区外即拒绝。
- 新文件写入时检查最近存在父目录的真实位置。
- `.git/` 和 `.coding-agent/` 是保留目录，模型文件工具不可读取或修改；内部日志器只能写入 `.coding-agent/logs/`。
- 只支持 UTF-8 文本，不处理二进制文件。

### 命令执行

- 子进程 `cwd` 固定为规范化工作区。
- 使用 `shell=False`，拒绝 `&`、`|`、`>`、`<` 等控制运算符。
- 拒绝父级跳转和指向工作区外的可疑绝对路径参数。
- 首版允许 `pytest`、`python -m pytest`、`python -m unittest`、`ruff`、`mypy`、工作区内 Python 脚本，以及只读 Git 命令。
- `run_command` 不允许 Java；`run_java_tests` 在独立边界内选择工作区外的可信系统 JDK，并复用相同的固定 cwd、受限环境、输出和进程树约束。
- Git 只允许 `status`、`diff`、`log`、`show` 和 `ls-files`。
- 禁止 PowerShell、`cmd.exe`、Bash、WSL、网络下载、包安装、系统管理、进程管理和破坏性命令。
- 用户提供的 `--verify` 同样经过命令策略；启动时无法通过策略则以配置错误退出。
- 默认命令超时 60 秒，配置值不得超过 300 秒。
- stdout 和 stderr 各保留最多 64 KiB，并记录是否截断。
- 超时时终止整个子进程树。

### 凭据和日志

- Responses 只从 `OPENAI_API_KEY` 读取密钥，Chat Completions 只从 `CHAT_COMPLETIONS_API_KEY` 读取密钥；两者不互相回退，也不读取或打印环境变量全集。
- `run_command` 启动工作区 Python、pytest 或验证子进程前，按大小写无关方式从子进程环境剥离上述两个模型凭据变量。
- 已知密钥值、Bearer 认证模式和常见 API Key 模式在日志前统一脱敏。
- 日志不记录 HTTP 认证头、隐藏推理或 opaque continuation payload。
- 源码、测试、文档、提交、截图和视频不得包含真实凭据。

这套机制不是操作系统级沙箱。工作区内被允许执行的项目代码和测试代码可能访问系统资源，因此首版假设演示项目可信，并在 README 中明确该限制。

## 14. 验证门槛

任何文件修改都会增加 `mutation_index` 并令验证状态变为 `STALE`。每次可作为证据的验证记录 `validation_index`、命令、来源和结果。

### 有 `--verify`

- 模型产生完成候选时，由 Agent 本地执行固定命令。
- 命令仍须通过安全策略。
- 退出码非 `0` 时，把结果写回上下文并继续修复。
- 只有固定命令退出码为 `0` 且执行晚于最后修改时才能成功。

### 无 `--verify`

- Agent 优先产生最新的可信验证证据：通过 `run_command` 执行 `purpose="verification"` 的命令，或通过 `run_java_tests` 执行完整 Java 黑盒套件并使用 `purpose="verification"`。若没有执行过这些验证，可使用本地文件完整性验证作为最低收敛门槛。
- 命令或 Java 工具调用必须通过安全策略和可信验证检查。
- `echo`、目录查看、`git status` 等纯检查命令不能作为验证证据。
- Java `purpose="test"`、不完整用例、编译失败、程序失败、输出不匹配、截断、超时或清理失败均不能形成通过证据。
- 最新可信验证必须在最后修改之后执行且退出码为 `0`。
- 本地完整性验证使用最后一次修改的精确 `changed_paths`，限制每个文件最多 524,288 原始字节，只读 UTF-8 文本；`.py`、`.json`、`.toml` 还必须通过确定性语法解析。其他文本类型只进行完整性检查，因此 C/C++ 等项目的 `SUCCESS` 不表示已经编译。

模型文本中的“完成”“通过”或类似声明都不是验证证据。

## 15. 循环终止条件

每个 run 选择不可变预算档位。`standard` 默认允许 24 次主逻辑调用、4 次摘要逻辑调用、48 次全局 provider 请求、其中最多 8 次摘要 provider 请求、80 次工具调用和 20 分钟；`deep` 允许 40 次主逻辑调用、6 次摘要逻辑调用、80 次全局 provider 请求、其中最多 12 次摘要 provider 请求、140 次工具调用和 30 分钟。配置了必须执行的 `--verify` 且最新修改尚未获得新鲜验证时，最后 1 次工具额度只供 `VerificationGate` 使用。

主调用和摘要调用分别计数，但共享全局 provider 硬上限。摘要子额度耗尽时改用本地摘要，不终止主任务。所有上限使用“允许最后一次合法操作，阻止第一个不允许的操作”语义，计数器不得超过上限。

精确重复调用、连续模型错误、连续工具错误和连续安全拒绝的阈值仍为 3。除此之外，`ProgressLedger` 区分首次成功检查等弱进展与修改、验证、阶段转换和完成候选等强进展。`standard` 在自上次强进展后达到 4 次主调用、12 次只读工具调用或连续 2 次完全无新信息时发出决策检查点；`deep` 对应为 6、24 和 3。检查点后分别再允许 2 或 3 次有效主响应；仍只有探索时以 `no_progress` 终止。

主调用剩余 4 次且尚未完成时提前发出最终决策检查点。这 4 次仍可使用，检查点不额外消耗调用。

普通探索检查点后的最后只读批次按尝试读取的模型响应计数，而不是按成功、新颖性或响应中的文件数量计数：`standard` 为 1，`deep` 为 2。整轮只有重复读取时直接触发 `decision_required`；普通额度耗尽后的首个额外读取同样被配对拒绝。拒绝本身不执行、不改写命令，也不推进修改或验证状态。

终止状态和 CLI 退出码：

- `SUCCESS`，退出码 `0`：完成候选通过 `VerificationGate`。
- `FAILED`，退出码 `1`：预算耗尽、重复停滞、连续失败、安全违规或验证无法通过。
- `FAILED`，退出码 `1`，原因 `changes_unverified`：修改已保留，但没有最后一次修改之后的新鲜通过证据；不得伪装成成功，也不自动回滚文件。
- 参数或配置错误，退出码 `2`。
- 用户中断，退出码 `130`。

最终报告必须区分模型的完成声明、实际执行事实和本地最终判定。

## 16. 测试策略

### 单元测试

- 消息和工具结果数据结构及 JSON 序列化。
- Responses 和 Chat Completions SDK 类型与内部类型转换。
- API mode、base URL（含控制字符、内部空白与反斜杠）、模式专用凭据及全部合法/非法配置组合。
- Chat Completions 消息顺序、assistant/tool 配对、单/多工具调用、完成原因、usage、SDK 畸形响应异常、重试、预算与脱敏。
- 工具 strict schema。
- 路径规范化、工作区包含关系和保留目录。
- 符号链接、junction/reparse point 逃逸；系统不允许创建链接时使用明确条件跳过，并保留纯策略测试。
- 精确替换计数和失败零修改。
- 命令解析、白名单、Git 子命令和危险输入拒绝。
- 子进程退出码、超时、进程树终止、输出截断，以及两个模型凭据变量的大小写无关环境剥离。
- 压缩触发、完整 turn 边界、摘要字段校验和确定性降级。
- 修改后验证失效、验证时效和强制门槛。
- 模型重试、连续错误、重复调用和所有终止预算。
- 凭据与日志脱敏。

### 组件测试

- 使用 `FakeModelClient` 脚本化工具调用和模型完成候选。
- 使用伪 SDK 响应测试 `OpenAIResponsesClient`，默认测试不联网。
- 使用伪 SDK 响应测试 `ChatCompletionsModelClient`，并把现有 Responses 测试作为不变的回归保护。
- 在 pytest 临时工作区执行真实目录、文件和子进程操作。
- 检查 `ToolResult`、`AgentState` 和 JSONL 事件对同一事实保持一致。

### 集成测试

提供一个预置失败测试的小型 Python 项目，以确定性 FakeModelClient 完成：

```text
读取目录 -> 读取代码 -> 修改 -> pytest 失败
-> 读取失败信息 -> 再次修改 -> 强制 pytest -q 通过 -> SUCCESS
```

另有失败路径集成测试证明：强制验证非零时绝不成功、最后修改会使旧验证失效、模型重复调用会终止、路径和命令违规不会执行。

Chat Completions 集成测试使用真实 `AgentRunner`、真实适配器和 fake SDK，覆盖“文本—工具调用—工具结果—最终文本”、连续两轮工具调用、单轮多个工具调用、压缩后继续，以及每次请求的合法 assistant/tool 配对顺序。

真实模型 API 只用于用户另行明确授权的人工冒烟测试。它不属于默认测试命令，测试报告必须明确区分是否真实运行；Task15 不调用真实 API。

## 17. 重要设计决策及其理由

1. **显式状态机单循环，而非 Planner 或框架**：代码量适合 10 至 25 小时，核心机制清晰，便于测试和面试辩护。
2. **`ModelClient` 抽象和独立适配器**：让主循环离线可测，并以加法方式支持 Responses 与标准 Chat Completions，不把 SDK 类型或 endpoint 差异泄漏到核心层。
3. **本地无状态上下文管理**：`store=False` 并自行保存必要输入，满足核心逻辑自研要求。
4. **精确替换优先于补丁解析**：行为确定、失败原子、测试成本低；新文件由独立工具创建。
5. **`shell=False` 与有限命令集**：牺牲部分通用性，换取确定性安全规则和可解释边界。
6. **混合验证方案**：用户提供时结果稳定；未提供时保留 Agent 自主性，但成功仍由本地证据决定。
7. **模型语义摘要加本地降级**：展示上下文特色，同时避免摘要故障阻断任务。
8. **字符预算而非 tokenizer**：减少依赖和模型耦合，并以保守阈值控制首版范围。
9. **事件日志与最终报告共用执行事实**：便于复现、答辩，并避免报告与真实结果不一致。
10. **显式 API mode 和严格 endpoint 组合**：默认保持 Responses；Chat Completions 必须显式配置 HTTPS base URL，Responses 则拒绝自定义 URL，避免猜测和误发凭据。
11. **模式专用凭据**：`OPENAI_API_KEY` 与 `CHAT_COMPLETIONS_API_KEY` 不互相回退，降低把密钥发送到错误 endpoint 的风险。
12. **Chat Completions 完全依赖本地历史**：continuation 始终为空，工具调用和结果作为完整消息留在上下文中；压缩仍由现有 `ContextManager` 管理。
13. **运行指令与消息历史分离**：每次运行固定一份受限、可哈希但正文 repr-private 的快照，避免摘要污染指令或运行中读取到变化的工作区策略。
14. **流式能力是可选内存边界**：核心只认识少量生命周期事件，供应商片段、reasoning 和 SDK 类型留在适配器内；当前 CLI 不展示增量，后续界面无需改动 Agent 消息模型。
15. **SQLite 会话历史与 JSONL 审计分工**：每个工作区的 SQLite 只保存 UI 可消费的用户消息、已确认助手文本、严格投影的工具/验证活动和安全终态摘要；JSONL 继续作为完整但脱敏的单次运行审计事实来源。
16. **顺序独立运行而非恢复 Agent 状态**：一个会话可以包含多个顺序 run；每次 follow-up 都创建新的 AgentState、模型客户端、预算、验证状态和 continuation 生命周期，只把安全叙事渲染为一条初始用户消息。
17. **单工作区进程租约与单活动 worker**：工作区租约阻止多个进程同时管理会话；控制器只允许一个非 daemon worker，取消通过确定性检查点合作完成，不强制终止线程。
18. **临时增量与持久确认分离**：流式 delta 只进入有数量和字节上限的内存事件缓冲；discard 永不持久化，只有 Agent 完整确认的非空文本才能写入 SQLite。
19. **重启恢复等于中断收敛**：启动时将遗留的 queued、running 或 cancelling run 标记为 `interrupted/process_restarted` 并把会话恢复为 idle，不重放工具、不恢复 provider continuation，也不声称续跑。
20. **声明式 Skill 目录与执行能力分离**：Task21 允许从用户级和工作区级可信本地目录发现受限 `SKILL.md`，按会话持久化有序 Skill ID，并在每次 run 开始前冻结仅存在于内存的指令快照；Skill 正文不进入 SQLite、日志、事件或报告，Skill 不能注册工具、扩大权限或绕过确定性安全与验证策略。
21. **权限、资源、阶段和终态分离**：`RunMode` 决定允许的能力，`BudgetProfile` 决定资源硬限制，`AgentPhase` 描述当前工作阶段，`AgentStatus` 表示最终状态；四者不能相互替代或扩大权限。
22. **分层预算而非单纯提高总轮次**：主调用与摘要调用独立计数、共享 provider 硬上限，并给摘要设置更小的 provider 子预算；这避免维护性摘要挤占核心推理，同时仍有全局成本边界。
23. **确定性进度账本而非模型自报进展**：首次检查属于弱进展，修改、验证和阶段转换属于强进展；决策检查点先帮助模型收敛，持续探索才以准确的 `no_progress` 终止。
24. **门控恢复而非自动命令改写**：最后只读额度让复杂调查保留有限收尾空间；额度或命令规则触发拒绝时，只返回安全、精确的纠正约束，绝不替模型重写或执行命令。无法形成新鲜证据时，用 `changes_unverified` 准确表达“文件已改但未验证”。

## 18. 本地 Web 里程碑

Task22–Task23 按 `docs/superpowers/specs/2026-08-30-local-web-gui-design.md` 实施：仅绑定 IPv4 loopback、使用进程级 Bearer/Host/Origin 防护的 FastAPI REST/SSE 薄适配层，承载同源、无构建步骤的本地静态 GUI。GUI 复用既有持久会话、单活动运行、follow-up、协作式取消和声明式 Skill；AgentRunner、SessionController、SessionEventHub、安全策略、验证门和 provider 边界保持不变。

REST/SSE 与 GUI 行为由离线 Python/Node 测试覆盖，最终视觉效果仍需人工 checkpoint。远程访问、WebSocket、账户、多用户、多活动运行、MCP、可执行 Skill 和前端框架仍不在范围内。

## 19. 显式运行模式

每个 run 携带不可变、供应商无关的 `RunMode`，只接受 `modify` 与 `read_only`，默认值为 `modify`。模式由 CLI 或 Web 用户显式选择，不能根据提示词推断，也不固定在整个会话上；同一会话的后续消息可以重新选择。

`modify` 保留现有六个工具和新鲜验证门槛。`read_only` 只注册 `list_directory`、`read_file` 与专用 `inspect_git`；后者只能执行既有安全策略批准的本地 Git `status`、`diff`、`log`、`show` 和 `ls-files`。只读模式不注册文件修改、通用命令、Java 或验证工具。

任一模式的非空、无工具最终文本在零修改、零验证的不变量成立时进入 `ANSWERED`，退出码为 `0`；这体现 `modify` 是能力而非意图。`SUCCESS` 仍只表示修改能力运行获得了最后一次修改后的新鲜通过证据。模式随 run 写入 SQLite、REST/SSE、审计和最终报告；历史数据库迁移时保守标记为 `modify`。

## 20. 自适应收敛与分层预算

每个 run 从 `DISCOVER` 阶段开始。成功修改进入 `ACT`，开始验证进入 `VERIFY`，合法答案或新鲜验证通过进入 `FINISH`。阶段不替代状态：`FINISH` 本身不是成功，修改后的运行仍只能通过 `VerificationGate` 进入 `SUCCESS`。被拒绝或失败的修改不能推动阶段，`read_only` 不能借阶段状态获得修改能力。

`ProgressLedger` 只保存确定性、安全的元数据和哈希指纹。新的成功检查是弱进展；成功修改、新验证证据、阶段转换和完成候选是强进展；重复或近似重复结果、合成拒绝、压缩本身和模型文字中的自我声明不算进展。达到档位阈值时，下一次主请求只在 `ModelRequest.instructions` 后追加固定控制段，要求模型在回答、实施、只检查明确剩余项和报告阻塞之间作出选择；该控制段不伪装成用户消息，也不持久化进会话历史。

运行级 `ExplorationLedger` 与消息历史分离，保存读取工具名、规范化安全目标、请求和结果指纹、状态及对应 `mutation_index`，但不保存文件正文。它按模型响应聚合新读取与重复读取，因此上下文压缩不会使 Agent 忘记已检查目标。账本只驻留当前 run；observation 列表在 repr 中隐藏，不进入 JSONL、FinalReport、Session、SSE 或 GUI。发生过压缩或进入检查点后，主请求可获得字符数受限的 `Exploration coverage`，只包含安全相对目标、计数和省略数量。

普通探索阈值触发的检查点按档位提供 **Standard 1 / Deep 2** 个最终只读响应批次；批次按模型响应中是否尝试读取计数，不依赖结果是否新颖，也不按同一响应中的文件数量重复计数。若一个主响应尝试读取但没有得到任何新结果、修改或验证，则直接关闭后续读取并进入 `decision_required`，不再赠送最终读取批次。额度用完后的读取产生配对但未执行的拒绝结果；若同一批次还含合法修改，修改仍执行。

进入 `decision_required` 后，第一次没有强进展的决策响应必须把完整配对反馈交给模型，并保证在其他硬预算允许时再执行一次纠正响应；第二次仍未修改、验证、完成或报告阻塞时才以 `no_progress` 终止，不得再多调用一次模型。该握手优先于通用检查点回合阈值，但不能越过内部不变量、安全拒绝、时间或 provider 硬预算。修改后，`has_unverified_changes` 只根据本地账本和验证新鲜度计算，不受模型文字影响；合法验证会清除该状态，反复拒绝或无证据完成则稳定终止为 `changes_unverified`。

稳定终止优先级为：内部不变量、安全拒绝、时间、全局 provider 预算、无进展、主调用预算、工具预算、连续模型错误、连续工具错误、精确重复调用。用户中断、审计失败、致命模型错误、上下文预算耗尽和空响应继续作为即时原因处理。摘要成功不能重置主模型连续错误；摘要普通失败只触发当前 run 的摘要熔断。

`standard`/`deep` 选择从 CLI 或 Web 进入 `RunConfig`，随每个 run 写入 Session、SQLite、REST/SSE、审计和最终报告；历史 run 缺少该字段时迁移为 `standard`。follow-up 可为新 run 选择不同档位，正在运行的 run 不可改变。GUI 只展示档位、阶段、安全计数、剩余额度、压缩来源和检查点，不展示隐藏指令、完整工具参数、绝对路径、摘要正文或 continuation。

## 21. 本地 Skill 导入与会话删除

Task27–Task28 按 `docs/superpowers/specs/2026-08-31-local-skill-import-session-deletion-design.md` 实施。Task27 在不增加依赖和不扩大 Agent 权限的前提下，通过认证的 `application/zip` REST 边界导入一个仅含 `<skill-id>/SKILL.md` 的工作区声明式 Skill；专用安装器使用受限 archive grammar、共享 Skill 解析器、独占暂存写入和同目录原子重命名，拒绝额外内容、危险路径、reparse、压缩炸弹和覆盖。

Task28 允许 GUI 逐条确认删除空闲会话及其精确 `audit_run_id` JSONL。专用删除服务以不可变数据库 manifest、精确日志路径、可逆暂存清单、显式 SQLite 子表删除顺序和启动恢复协调文件系统与数据库；不使用 glob、数据库路径文本或用户给定文件目标。活动 run 期间禁止导入或删除。两项能力只属于本地控制面，不暴露为模型工具，也不允许任意工作区删除。

## 22. 首版不实现的功能

- 多智能体、子 Agent 和独立 Planner。
- 向量数据库、长期记忆和语义检索。
- 插件系统或工具市场。
- 并行工具执行。
- 可执行或可续跑的跨进程 Agent 状态恢复；当前重启只把未完成 run 安全收敛为中断。
- macOS、Linux 正式支持。
- 自定义 Responses endpoint、Azure 专用协议或供应商专用非标准 API。
- 自动 endpoint 探测、按 URL 猜测 API 模式或凭据回退。
- WebSocket、异步客户端、多个 choices、旧式 `function_call` 或非函数工具。
- TUI、桌面 GUI、账户系统和多会话并发执行。
- 可执行 Skill、远程 Skill、用户级 Skill 安装、Skill 更新/覆盖/编辑/卸载、市场和 Skill 自定义工具；Task27 只增加当前工作区单个纯声明式 zip 的显式本地导入。
- MCP 客户端或服务端集成。
- 根据仓库大小自动推算预算、无限预算、独立 Planner/Executor 或模型自动推断 `RunMode`。
- 任意 Shell、网络访问、包安装或服务端托管工具。
- Agent 工具中的文件删除、移动、权限修改和二进制文件编辑；Task28 的控制面只删除用户明确确认的单个空闲会话及其精确审计日志。
- Git 写操作、自动提交、自动推送或远程仓库操作。
- 对恶意工作区代码的操作系统级隔离保证。

## 23. 当前方案的局限性

- 有限命令白名单只覆盖 Python 演示场景，不是通用 Coding Agent 的完整命令生态。
- `replace_text` 不适合大规模重构或重复片段复杂编辑。
- 字符预算与实际 token 数不完全一致。
- 模型生成摘要可能遗漏语义；本地不变量只能保证关键执行事实不丢失。
- 无 OS 沙箱，运行可信项目的测试仍可能产生工作区外副作用。
- Windows 优先实现会减少跨平台展示价值。
- 会话支持顺序 follow-up，但不支持多个 run 并发执行，也不恢复上次进程中的可执行 Agent 状态，因此仍不适合无人值守的超长开发任务。
- OpenAI-compatible 只是协议目标而非兼容性保证；第三方 endpoint 必须实现标准 Chat Completions 工具调用、call ID 和 tool result 配对语义。
- Chat Completions 使用 `max_tokens` 以覆盖目标兼容服务；只接受 `max_completion_tokens` 的 endpoint 不在 Task15 范围内。
- 真实模型行为具有非确定性，自动测试主要依赖 FakeModelClient；真实 API 测试只能作为单独记录的人工证据。
- `standard` 与 `deep` 是可解释的固定档位，并不保证适合所有仓库；确定性进度启发式仍可能要求用户为异常复杂的只读调查选择 `deep`。
- 最终只读额度和命令纠正都是有限启发式；复杂仓库仍可能以 `decision_required` 或 `changes_unverified` 停止。此时修改文件会保留，不提供事务回滚。

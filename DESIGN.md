# Local Coding Agent Design

## 1. 项目目标与范围

本项目从零实现一个 Windows 优先、Python 编写的本地 Coding Agent。用户通过一次性 CLI 命令提交编程任务，Agent 默认调用 OpenAI 官方 Responses API，也可显式选择 OpenAI-compatible Chat Completions endpoint；Agent 自主检查工作区、读取和修改文本文件、执行受控命令、验证修改，并以明确的终止状态结束。

概念命令如下：

```text
coding-agent "修复当前项目中的失败测试" --workspace <path> --verify "pytest -q"
```

`--verify` 是可选参数：

- 用户提供时，该命令是最终强制验证门槛。只有它在最后一次文件修改之后执行且退出码为 `0`，Agent 才能报告成功。
- 用户未提供时，Agent 可以根据项目文件选择验证命令。该命令仍须通过安全策略，被标记为 `purpose="verification"`，在最后一次文件修改之后执行，并以退出码 `0` 结束。
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
- 凭据：Responses 只读取 `OPENAI_API_KEY`，Chat Completions 只读取 `CHAT_COMPLETIONS_API_KEY`；两者不互相回退，也不提供 API Key CLI 参数。
- 运行依赖：生产环境只引入官方 `openai` Python 包，其余功能优先使用标准库。
- 测试依赖：使用 `pytest`。
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

1. 检查模型调用、工具调用、总时间、重复调用、连续错误和安全拒绝预算。
2. 让 `ContextManager` 构建本轮活动上下文；达到阈值时先执行压缩。
3. 通过 `ModelClient` 调用模型。
4. 将模型输出解析为内部 `ModelResponse`。
5. 如果存在工具调用，按响应中的顺序逐个执行：
   - 验证工具存在且 `call_id` 未重复；
   - 校验 JSON 参数和工具 schema；
   - 执行路径或命令安全授权；
   - 执行本地工具并捕获统一结果；
   - 将 `ToolResult` 加入历史、日志和状态。
6. 文件工具成功修改内容时增加 `mutation_index`，记录文件，并把现有验证标记为 `STALE`。
7. 如果模型返回完成文本且没有工具调用，将其视为完成候选并进入 `VerificationGate`。
8. 验证通过时进入 `SUCCESS`；验证失败或缺少证据时，把真实证据加入上下文并继续运行。
9. 任何预算耗尽或不可恢复错误都进入带原因的 `FAILED`，不得死循环。

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

活动上下文满足任一条件时触发压缩：

- 序列化字符数超过 60,000。
- 历史项数量超过 24。

压缩以完整 turn 为边界，绝不拆开 assistant tool call 与对应 tool results。压缩后保留最近 8 个完整 turn。

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

以下事实由本地状态强制合并进摘要，不信任模型自行保留：原始任务、工作区边界、修改文件、最近修改序号、验证命令及来源、退出码、验证序号和终止计数。

语义摘要通过一次无工具的 `ModelClient` 调用生成，并计入 12 次模型调用总预算。输出必须是可解析、字段完整且受大小限制的 JSON。模型调用失败或摘要不合法时，使用本地确定性摘要：保留结构化状态、工具元数据和截断后的近期错误，随后继续任务。

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
| 摘要失败 | 使用确定性降级摘要 |
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

- Agent 必须通过 `run_command` 执行 `purpose="verification"` 的命令。
- 命令必须通过安全策略和可信验证检查。
- `echo`、目录查看、`git status` 等纯检查命令不能作为验证证据。
- 最新可信验证必须在最后修改之后执行且退出码为 `0`。

模型文本中的“完成”“通过”或类似声明都不是验证证据。

## 15. 循环终止条件

默认硬限制如下：

- 最多 12 次模型调用，包括上下文摘要调用和瞬时错误的每次重试尝试。
- 最多 40 次工具调用。
- 最长总运行时间 10 分钟，使用单调时钟计算。
- 相同工具名和规范化 JSON 参数在无状态进展时最多连续出现 3 次。
- 连续模型、解析或工具错误最多 3 次。
- 连续安全拒绝最多 3 次。

终止状态和 CLI 退出码：

- `SUCCESS`，退出码 `0`：完成候选通过 `VerificationGate`。
- `FAILED`，退出码 `1`：预算耗尽、重复停滞、连续失败、安全违规或验证无法通过。
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

## 18. 首版不实现的功能

- 多智能体、子 Agent 和独立 Planner。
- Web UI、桌面 UI 和聊天式 REPL。
- 向量数据库、长期记忆和语义检索。
- 插件系统或工具市场。
- 并行工具执行。
- 可执行或可续跑的跨进程 Agent 状态恢复；当前重启只把未完成 run 安全收敛为中断。
- macOS、Linux 正式支持。
- 自定义 Responses endpoint、Azure 专用协议或供应商专用非标准 API。
- 自动 endpoint 探测、按 URL 猜测 API 模式或凭据回退。
- SSE/WebSocket/GUI 流式传输、异步客户端、多个 choices、旧式 `function_call` 或非函数工具。
- HTTP/SSE 传输层、TUI、GUI、账户系统和多会话并发执行；当前只提供框架无关的本地 controller/event 边界。
- 跨运行的 Skill 管理与可执行 Skill；当前仅支持构造器接收已选择的纯文本 Skill 指令。
- MCP 客户端或服务端集成。
- 任意 Shell、网络访问、包安装或服务端托管工具。
- 文件删除、移动、权限修改和二进制文件编辑。
- Git 写操作、自动提交、自动推送或远程仓库操作。
- 对恶意工作区代码的操作系统级隔离保证。

## 19. 当前方案的局限性

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

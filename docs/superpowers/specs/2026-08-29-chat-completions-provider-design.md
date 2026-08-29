# Task15：OpenAI-compatible Chat Completions Provider 设计

## 1. 状态与目的

本文记录已经批准的 Task15 架构设计及实施中发现的最小安全修正。Task15 已进入实施；独立只读审查发现凭据子进程继承、URL 原始字符校验和 SDK 解码异常边界与设计合同不完整，因此后续生产实现暂停，直到修订后的详细计划再次获得用户批准。

Task15 为现有 MiniCodex 增加一个供应商中立的 OpenAI-compatible Chat Completions 适配器，首个兼容目标是 BayesDL 提供的 GLM 模型。供应商地址必须由用户显式配置，项目不硬编码任何供应商。现有 `OpenAIResponsesClient`、Responses API 映射和 `ModelClient.complete(ModelRequest) -> ModelResponse` 公共边界保持不变。

## 2. 目标与非目标

目标：

- 在不改变 Agent、消息、工具和上下文层内部类型的前提下支持标准 Chat Completions 工具调用。
- 单次 Agent 运行完全依靠项目维护的内部历史连续完成多轮文本、工具调用和工具结果交互。
- 通过显式 `api-mode + base-url` 配置选择适配器，不根据 URL、模型名或响应形状猜测供应商。
- 保持默认 Responses 行为向后兼容，并用离线测试保护两种模式。
- 复用现有模型调用预算、观察事件、重试分类和脱敏边界。

非目标：

- 不支持自定义 Responses endpoint、服务端 conversation 或 `previous_response_id`。
- 不自动探测 endpoint 能力，不为不标准的兼容服务增加供应商特例。
- 不支持流式、异步、旧式 `function_call`、非函数工具或多个 choices。
- 不增加 Agent 框架、新工具、并行工具执行或项目依赖。
- 不进行真实 API 测试；任何真实调用必须由用户在新对话中另行授权并重新配置本机环境变量。

## 3. 配置合同

配置层新增 `ApiMode(StrEnum)`：

- `responses`
- `chat-completions`

CLI 新增 `--api-mode` 和 `--base-url`。`--api-mode` 默认 `responses`，仅接受上述两个值；二者均不从环境变量回退。组合规则如下：

| API mode | `--base-url` | 凭据环境变量 | 结果 |
| --- | --- | --- | --- |
| `responses` | 未提供 | `OPENAI_API_KEY` | 合法，继续使用 OpenAI 官方默认 endpoint |
| `responses` | 已提供 | `OPENAI_API_KEY` | 非法，在任何网络请求前返回稳定、脱敏的配置错误 |
| `chat-completions` | 合法 HTTPS URL | `CHAT_COMPLETIONS_API_KEY` | 合法 |
| `chat-completions` | 未提供或 URL 非法 | `CHAT_COMPLETIONS_API_KEY` | 非法，在任何网络请求前返回稳定、脱敏的配置错误 |

两种凭据严格隔离，不互相回退。API Key 只能从对应环境变量读取，不提供 CLI 参数；配置对象中的选中密钥和 base URL 使用 `repr=False`，日志、错误和最终报告不得输出密钥或 Authorization header。`OPENAI_API_KEY` 与 `CHAT_COMPLETIONS_API_KEY` 都必须由现有 `run_command` 子进程环境清理逻辑按大小写无关方式剥离；工作区 Python、pytest 和验证命令不得继承任一模型凭据。

Chat Completions base URL 必须是绝对 HTTPS URL，允许供应商路径前缀；拒绝 HTTP、相对 URL、空 host、userinfo、query 和 fragment，并统一尾部斜杠。解析前必须检查原始字符串：只允许外围普通 ASCII 空格被裁剪，拒绝 C0 控制字符、DEL、反斜杠以及裁剪后仍存在的任何空白字符，避免 `urlsplit` 清理或重新解释恶意输入。配置仅验证形状，不联网探测，也不自行拼接 `/chat/completions`。直接构造 Chat 客户端时执行相同验证和恶意输入矩阵。

配置验证顺序固定为：API mode；mode/base URL 组合与 URL 形状；该 mode 对应的凭据；现有 model、workspace 和 verify 规则。不得静默忽略非法参数。

## 4. 适配器边界

新文件 `src/coding_agent/chat_completions_client.py` 定义：

- `InvalidChatCompletionsResponseError(ModelError)`，模型观察错误码固定为 `invalid_model_response`。
- `ChatCompletionsModelClient`。

构造器为 keyword-only：`model`、`api_key`、`base_url`、可选 `sdk_client=None`、可选 `sleeper=time.sleep`。未注入 SDK 时构造官方 `OpenAI(api_key=..., base_url=..., max_retries=0)`；实例不另存 API Key，也不让 SDK 对象越过该文件。

客户端实现 `complete(request)` 和 `complete_with_budget(request, budget)`，保持现有公共协议。它与 `OpenAIResponsesClient` 是两个独立适配器；本任务不抽取共享基类或重构已验收的 Responses 实现。少量重试和观察逻辑重复是保护既有行为的有意取舍。

## 5. 请求映射

每次调用都发送 `ContextManager.prepare` 产生的完整内部历史。Chat 适配器不读取或写入任何服务端会话状态。

消息映射：

- `UserMessage` -> `{"role": "user", "content": text}`。
- 纯文本 `AssistantMessage` -> `{"role": "assistant", "content": text}`。
- 带工具调用的 `AssistantMessage` -> 单条 assistant 消息，保留可空文本，并按内部顺序写入 `tool_calls`。每项含原始 `id`、`type="function"`、函数名及 canonical JSON arguments。
- `ToolResult` -> `{"role": "tool", "tool_call_id": call_id, "content": result.to_json()}`，不写非标准 `name` 字段。

适配器在调用 SDK 前再次验证 Chat Completions 顺序约束：每组 assistant tool calls 后必须紧接数量、顺序和 call ID 都完全匹配的 tool results，不能插入或遗漏其他消息。该验证同样适用于压缩后的历史。非空 `request.continuation` 是致命的本地不变量错误，且不得触发网络调用。

工具 schema 从内部 strict registry schema 映射为 Chat Completions 的嵌套 function tool，保留 `strict=true`。实际 SDK 调用只传：

- `model`
- `messages`
- `max_tokens=request.max_output_tokens`
- 仅在工具集合非空时传 `tools`

不传 `n`、`stream`、`tool_choice`、`store` 或服务端状态字段；不为 `max_completion_tokens` 做失败后回退。

## 6. 响应映射

响应必须恰有一个 choice。解析器直接检查 `choice.message.tool_calls`，绝不依赖 `finish_reason` 判断是否发生工具调用；因此 `finish_reason="stop"` 与非空 tool calls 是合法组合。文本与工具调用可以同时存在并都写入内部响应。

每个响应工具调用必须：

- 类型为 `function`。
- 具有非空且在本响应中唯一的 call ID。
- 具有合法函数名。
- arguments 是可解析为 JSON object 的字符串。

不接受旧式 `function_call`、custom tool 或未知工具调用类型。工具调用顺序保持不变。

`finish_reason` 只接受 `stop` 和 `tool_calls`；其中 `stop` 与非空 tool calls 是明确合法的。`length`、`content_filter`、空值或其他未知值均视为不可解析响应。既无非空文本也无工具调用的响应同样非法。解析异常转换为非致命 `InvalidChatCompletionsResponseError`，消息前缀固定为 `invalid Chat Completions payload: `，不包含原始响应体或供应商异常文本，并且不重试。

如果官方 SDK 在返回响应对象前因畸形 payload 抛出 `APIResponseValidationError` 或 `json.JSONDecodeError`，适配器也必须把当前 provider attempt 以 `invalid_model_response`、`retry_scheduled=false` 结束，并从 `None` 抛出同一非致命本地错误，稳定消息固定为 `invalid Chat Completions payload: provider response could not be decoded`。不得把这两类错误归为致命 provider error，不得重试或 sleep，也不得泄漏异常消息、response body、JSON `doc` 或 repr。

顶层非空 `id` 映射到 `provider_response_id`；观察日志只记录其 SHA-256。`usage` 可为空；若存在，则 `prompt_tokens`、`completion_tokens`、`total_tokens` 三项必须全部存在且为非负整数，并分别映射到内部 input、output、total usage。不要求响应中的 model 与请求 model 相等。

`ModelResponse.continuation` 永远为空。语义历史始终由项目内部消息保存。

## 7. 连续 Agent 生命周期与压缩

一次运行中的数据流为：

```text
ContextManager.prepare(full internal history)
  -> Chat request with complete mapped messages
  -> assistant text and/or ordered tool_calls
  -> AgentRunner appends the AssistantMessage
  -> AgentRunner executes calls sequentially and appends every ToolResult
  -> next prepare/request remaps the resulting complete history
```

这样可支持文本后调用工具、连续多轮调用工具、单轮多个工具调用，以及工具结果后的最终文本。assistant 工具调用消息不会在下一轮丢失，每条 tool 消息通过 `tool_call_id` 配对。

上下文压缩继续由现有 `ContextManager` 完成。它只保留完整 turn 并产生供应商无关的 summary user 消息；Chat 客户端收到压缩历史后仍执行即时配对校验。压缩不产生 continuation，下一次请求仍只依赖压缩后的完整内部历史。

## 8. 重试、预算、错误与脱敏

官方 SDK 内建重试关闭。适配器自身对 timeout、连接错误、HTTP 429 和 5xx 最多重试两次，退避分别为 0.25 秒和 0.50 秒。认证、权限、not found、bad request 和 unprocessable 请求属于致命错误，不重试。解析器拒绝的响应以及 SDK 抛出的 `APIResponseValidationError`、`json.JSONDecodeError` 都属于非致命无效响应，不重试。

每个逻辑调用沿用现有 `invoke_model` 生命周期，每次真实 provider 尝试在发出前领取同一个 `ModelCallBudget` 的 provider attempt。预算不足时不发请求。开始、完成、失败和阻塞观察事件与 Responses 客户端保持同样语义。

所有外部异常都转换为稳定的本地错误分类。错误信息、日志和最终报告不得包含 API Key、Authorization header、供应商原始响应体、SDK exception repr、环境变量内容或 base URL 中的敏感信息。

## 9. 应用装配

`RunConfig` 增加默认值为 `responses` 的 `api_mode` 和可空、repr 隐藏的 `base_url`；`api_key` 仍为 repr 隐藏字段，表示当前选中 mode 的凭据。

应用工厂依据显式 mode 只构造一个客户端：

- `responses` -> 未改动的 `OpenAIResponsesClient`。
- `chat-completions` -> `ChatCompletionsModelClient`。

不按 base URL 猜 mode，不联网探测，不回退到另一个客户端。Task15 不改变 JSONL 事件 schema、`FinalReport` schema、Agent/Context/Tool 接口或现有退出码规则。

## 10. 离线测试合同

新增 `tests/test_chat_completions_client.py`，通过 fake SDK 覆盖：构造器、包含控制字符/内部空白/反斜杠的 URL 拒绝、消息和 schema 映射、输出限制、choice/finish reason、文本与工具调用并存、多工具、usage/id、无效响应、SDK 解码/响应校验异常、重试、调用预算、脱敏、非空 continuation 拒绝和零网络默认行为。

新增 `tests/integration/test_chat_completions_agent.py`，使用真实 `AgentRunner`、真实 Chat 适配器和 fake Chat SDK，至少证明：

1. 文本 -> 工具调用 -> 工具结果 -> 最终文本。
2. 连续两轮工具调用后产生最终文本。
3. 单轮多个 tool calls 及对应的多个 tool results。
4. 压缩后的上下文仍可继续调用模型。
5. 每次请求都保持合法的 assistant/tool 配对顺序。

配置、CLI 和应用测试覆盖全部合法与非法参数组合，证明非法组合在 SDK 构造或 provider 调用前失败。`tests/tools/test_shell_tool.py` 通过真实允许的 Python 子进程和 process-factory 环境捕获两条路径，证明两个模型凭据变量都按大小写无关方式被剥离，同时普通安全环境变量仍被保留。Responses 客户端现有单元和集成测试原样作为回归保护。默认测试不需要网络或真实 API Key。

文档合同测试同步更新：`base_url` 可配置不代表兼容所有服务；目标 endpoint 必须正确实现标准 Chat Completions 函数工具调用、call ID 和 tool result 语义。

## 11. 文件与兼容范围

Task15 预计新增：

- `src/coding_agent/chat_completions_client.py`
- `tests/test_chat_completions_client.py`
- `tests/integration/test_chat_completions_agent.py`
- 本设计规格和后续经审批的实现计划

Task15 预计修改配置、CLI、应用装配、相应测试，以及 `DESIGN.md`、`TASKS.md`、README 和 API/使用文档。以下公共行为不变：

- `src/coding_agent/tools/shell.py` 只扩展现有子进程环境凭据剥离集合，不改变命令授权、执行、超时、输出或验证语义。
- `tests/tools/test_shell_tool.py` 增加上述凭据隔离回归测试。

- `ModelClient.complete(ModelRequest) -> ModelResponse`
- `messages.py` 的供应商无关内部类型
- `agent.py` 的同步循环和顺序工具执行
- `context.py` 的本地历史与压缩职责
- `openai_client.py` 的 Responses API 行为
- 除新增 Chat 凭据子进程隔离外的工具、安全、验证、终止、日志和报告语义
- 生产与测试依赖集合

## 12. 安全实施门槛

Task14 已由用户确认完成，Task15 已进入实施。Task15 的初始配置和请求映射完成后，独立只读审查触发本安全修正；在修订计划再次获批前，响应解析及后续生产实现保持暂停。恢复后先按 TDD 补齐 URL 与子进程凭据 RED/GREEN，再继续响应解析；实现阶段继续使用验证和代码审查技能，并继续禁止真实 API、Git 写操作和远程操作。

## 13. 已拒绝方案

1. **统一的 api-mode 大客户端**：会把两种 API 的状态与解析语义耦合，增加破坏 Responses 回归的风险。
2. **先抽取共享传输/重试基类**：可减少少量重复，但会在 Task15 中重构已验收模块，收益不足以抵消风险。
3. **根据 base URL 或响应形状自动选择**：行为不透明，容易把凭据发送到错误 endpoint，也无法在请求前稳定拒绝配置错误。
4. **只修复 Chat 密钥继承而保留其他已知边界错误**：仍会让恶意 URL 绕过配置校验，并使 SDK 畸形响应越过稳定 `ModelError` 边界。
5. **为凭据和 URL 提前抽取通用安全框架**：会扩大 Task15 重构范围；本轮只在现有两个 URL 边界和现有子进程清理集合中做最小修正。

因此采用独立、加法式 `ChatCompletionsModelClient`，并由显式配置选择。

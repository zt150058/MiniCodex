# OpenAI Responses 与 compatible Chat Completions 接入说明

MiniCodex 使用官方 `openai` Python SDK 作为模型 HTTP 客户端，但自行实现 Agent 循环、历史、工具、验证、重试和错误边界。默认适配器是 OpenAI Responses；也可以显式选择实现标准函数工具调用的 compatible Chat Completions endpoint。安装与 CLI 使用见[使用说明](USAGE.md)。

## Provider 与 API mode 选择

API mode 只由 CLI 显式选择，不根据 URL、模型名或响应形状猜测，也不联网探测或自动回退：

| `--api-mode` | `--base-url` | 凭据 | 适配器 |
| --- | --- | --- | --- |
| `responses`（默认） | 禁止提供 | `OPENAI_API_KEY` | `OpenAIResponsesClient`，使用官方默认 endpoint |
| `chat-completions` | 必须是绝对 HTTPS API 前缀 | `CHAT_COMPLETIONS_API_KEY` | `ChatCompletionsModelClient` |

`responses + --base-url` 在构造 SDK 或请求网络前失败，且不会静默忽略 URL。Task15 不支持 custom Responses endpoint。可配置 base URL 不代表兼容所有服务；目标 endpoint 必须正确实现标准 Chat Completions assistant tool calls、函数 ID、strict schema 和 tool result 配对语义。

## 凭据与模型配置

两种 mode 的 key 只从各自环境变量读取，互不回退，也没有 API Key CLI 参数。模型由 `--model` 或 `OPENAI_MODEL` 指定；CLI 参数优先。不要把 key 放进源码、配置样例、命令历史、进程参数、Git、日志、截图或视频。

项目不硬编码推荐模型。模型 ID、账号权限、速率限制、价格和区域可能变化，应在运行前查询所选服务的文档和账号设置。真实请求可能产生费用，具体以服务当时规则为准。

## PowerShell 当前会话设置

只需设置所选 mode 的 key。以下占位符不是可用凭据：

```powershell
$env:OPENAI_API_KEY = '<openai-api-key>'
$env:CHAT_COMPLETIONS_API_KEY = '<chat-completions-provider-key>'
$env:OPENAI_MODEL = '<model-id>'
```

关闭 PowerShell 会话后变量失效。持久化到用户或系统环境会扩大暴露窗口，本项目不要求持久化。

## 不显示密钥的配置检查

只检查变量是否为空，不输出值：

```powershell
if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) { 'responses key missing' } else { 'responses key configured' }
if ([string]::IsNullOrWhiteSpace($env:CHAT_COMPLETIONS_API_KEY)) { 'chat key missing' } else { 'chat key configured' }
if ([string]::IsNullOrWhiteSpace($env:OPENAI_MODEL)) { 'model missing' } else { 'model configured' }
```

发现泄漏时应在对应服务侧撤销 key 并创建新 key；不要把旧值粘贴到 issue、日志或对话中。

## 启动 MiniCodex

默认 Responses：

```powershell
coding-agent "修复失败测试" --workspace . --api-mode responses --model '<openai-model-id>' --verify "pytest -q"
```

compatible Chat Completions：

```powershell
coding-agent "修复失败测试" --workspace . --api-mode chat-completions --base-url '<https-provider-base-url-with-api-prefix>' --model '<compatible-model-id>' --verify "pytest -q"
```

这些是正常生产调用，会访问网络、可能产生费用且结果非确定。配置错误以退出码 2 结束，并发生在模型客户端构造和任何网络请求之前。

## ModelClient 与适配器边界

核心只依赖 `src/coding_agent/model.py` 中的 `ModelClient.complete(ModelRequest) -> ModelResponse`。`src/coding_agent/openai_client.py` 实现 `OpenAIResponsesClient`；`src/coding_agent/chat_completions_client.py` 独立实现 `ChatCompletionsModelClient`。两者都把 SDK 对象、异常和响应转换为 provider-neutral 内部类型。

AgentRunner、messages、ContextManager、工具、验证和报告层不知道具体 API mode。新增 Chat 能力没有修改公共 ModelClient 边界，也没有把 SDK 类型泄漏到核心层。

## Responses API 请求映射

Responses 适配器调用 `client.responses.create` 并保持既有行为：

- 显式发送 `store=False`，不使用服务端存储代替本地状态；
- 映射完整本地输入、`strict: true` function tools 和最大输出 token；
- 请求 `include=["reasoning.encrypted_content"]`，但不记录加密推理；
- 将输出 `function_call` 转成有序内部 ToolCall；
- 工具完成后发送同一 `call_id` 的 `function_call_output`。

strict schema 只提高模型输出可靠性；ToolRegistry 仍在本地重新校验参数和安全策略。

## Responses continuation 与本地历史

`AgentState.messages` 是权威历史。Responses 不使用 server conversation，也不使用 `previous_response_id` 替代本地消息。需要续接的 output 会转成 SDK-free、不可变且 repr 隐藏的 continuation snapshot，按对应 assistant message 索引重放，避免重复函数调用。

opaque continuation 和 provider payload 只驻留内存，不写 JSONL 或 FinalReport。上下文压缩替换活动历史时会原子丢弃旧 continuation；摘要调用产生的 continuation 也不会进入主历史。

## Chat Completions 完整历史映射

Chat 适配器不依赖服务端状态。每次 provider 调用都接收 ContextManager 准备后的完整内部历史，并按以下规则发送：

- UserMessage → `role=user`；
- 普通 AssistantMessage → `role=assistant` 文本；
- 带工具调用的 AssistantMessage → 保留文本并发送 assistant tool_calls；
- ToolResult → `role=tool`、对应 `tool_call_id` 和完整内部结果 JSON。

多轮 assistant/tool 记录保留在后续请求中；工具结果返回后，模型可继续调用工具或生成最终文本。Chat 的 continuation 输入必须为空，输出也始终为空，不使用 `conversation`、`previous_response_id` 或其他持久状态。

请求使用 `max_tokens` 传递输出上限；有工具时才发送 `tools`。函数 arguments 使用稳定 canonical JSON。适配器只接受一个 choice，并校验 role、content、finish reason、usage 和 response ID。

## assistant tool_calls 与 tool result 配对

每个带工具调用的 assistant 消息必须紧邻其全部 tool 结果。结果数量、顺序、`tool_call_id` 和工具名必须与声明一致；单独、缺失、倒序或被其他消息隔开的 tool 结果在 SDK 调用前被拒绝。压缩后的历史也执行同一校验。

解析响应时直接读取 `message.tool_calls`，不依赖 finish reason 判断是否存在工具调用。目标服务即使在返回工具调用时给出 `finish_reason="stop"`，调用仍会被保留；`tool_calls` 完成原因同样可用。文本和多个工具调用可以共存，call_id 必须非空且唯一，arguments 必须是 JSON object。

## 共享 logical call、provider attempt 与重试

一次 Agent 或摘要意图是 logical call；一次真实 `.responses.create` 或 `.chat.completions.create` 是 physical provider attempt。两个适配器都设置 `max_retries=0` 关闭 SDK 自动重试，由本地代码对 429、5xx、timeout 和 connection error 最多退避两次，延迟固定为 0.25 秒和 0.50 秒。

logical call 和 provider attempt 共享 run-scoped `ModelCallBudget`。每次真实请求前领取 provider 额度，预算不足时不会调用 SDK。authentication、permission、not-found、bad request、unprocessable、请求映射错误和响应解析错误不重试。畸形 SDK payload 与解析拒绝统一为稳定的 `invalid_model_response`，不复制异常正文或响应体。

## 隐私与日志边界

两个 key 都从 `run_command` 启动的工作区 Python、pytest 和验证子进程环境中按大小写无关方式移除。正常 JSONL 和 FinalReport 不接受 API key、认证头、环境全集、请求正文、完整历史、工具原始内容、SDK exception repr、provider body、continuation 或隐藏推理。

已知敏感值和常见凭据模式在允许写出的字段中再次脱敏。Responses 的 `store=False` 只控制 API 侧 Response 存储，不等于本地无日志；MiniCodex 仍在工作区 `.coding-agent/logs/` 写入白名单化执行事实。

## 完全离线的自动测试

两套适配器测试都注入 fake SDK response/exception，不读取真实 key、不构造网络客户端：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py tests\test_chat_completions_client.py tests\test_model.py -q -p no:cacheprovider
```

连续 Chat 工具调用与压缩合同位于 `tests/integration/test_chat_completions_agent.py`，使用真实 AgentRunner、ContextManager 和 Chat 适配器，仅替换最外层 SDK：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_chat_completions_agent.py -q -p no:cacheprovider
```

完整离线测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

## 手工联网冒烟（自动测试不会执行）

联网冒烟只能由用户在新的明确授权后手工执行。它可能产生费用、结果非确定，且不属于 pytest 或 Task15 离线验收。应使用可丢弃工作区，只配置当前 mode 所需 key，不在命令、录屏、日志或报告中显示其值。

Task15 没有调用真实 API，也不把真实响应作为回归基线。冒烟结束后应核对 FinalReport 和脱敏 JSONL，并在凭据疑似泄漏时立即撤销。

## 常见 API 错误

- mode/key 不匹配：两种 key 不回退；只设置所选 mode 的环境变量。
- Responses 带 base URL：非法配置；本任务只支持官方默认 Responses endpoint。
- Chat 缺少或使用非 HTTPS base URL：在 SDK 构造前拒绝。
- authentication/permission：不重试，检查所选服务侧权限，但不要打印 key。
- not-found/模型错误：确认模型 ID 和 API 前缀正确。
- 429：最多按 0.25、0.50 秒重试；共享预算可能更早停止。
- 5xx、timeout、connection error：瞬时错误，但最多总计三次物理尝试。
- bad request/unprocessable：通常表示字段、模型或 strict schema 不兼容，不重试。
- response invalid：choice、finish reason、call_id、JSON arguments 或 usage 非法时返回稳定解析错误。
- provider attempt budget：共享物理请求额度已用尽，不会再调用 API。

## 当前未实现的扩展

OpenAI-compatible 是协议目标而不是兼容保证。下列扩展仍不在当前版本范围：

| 扩展 | 状态 |
| --- | --- |
| custom Responses endpoint | 当前未实现 |
| Azure-specific API | 当前未实现 |
| proxy 配置 | 当前未实现 |
| server conversation | 当前未实现 |
| streaming | 当前未实现 |
| async API | 当前未实现 |
| automatic endpoint detection | 当前未实现 |
| legacy function_call | 当前未实现 |
| non-function Chat tools | 当前未实现 |

Chat adapter 也不实现 `max_completion_tokens` fallback。需要供应商专用字段、Azure 协议、代理或其他依赖时，必须单独设计、测试并获得批准，不能把差异传播到 AgentRunner 或内部消息层。

# OpenAI Responses API 接入说明

MiniCodex 的生产适配器使用 OpenAI 官方 Python SDK 和 Responses API。仓库实现以 `src/coding_agent/openai_client.py` 及其离线测试为准；通用字段含义可对照 [Responses create reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create) 和 [function calling guide](https://platform.openai.com/docs/guides/function-calling)。安装与 CLI 使用见[使用说明](USAGE.md)。

## 凭据与模型配置

需要官方 OpenAI API key。`OPENAI_API_KEY` 只从环境读取；模型由 `--model` 或 `OPENAI_MODEL` 指定。不要把 key 放进源码、配置样例、CLI 参数、Git、日志、截图或视频。

本项目不硬编码推荐模型。模型 ID、账号权限、速率限制、价格和可用区域会变化，应在运行前查询官方 OpenAI 文档与账号设置。API 请求按实际输入、输出和推理 token 计费，具体费用以当时官方价格为准。

## PowerShell 当前会话设置

默认只设置当前 PowerShell 会话，关闭会话后变量失效：

```powershell
$env:OPENAI_API_KEY = '<your-api-key>'
$env:OPENAI_MODEL = '<model-id-available-to-your-account>'
```

持久化到用户或系统环境变量会扩大凭据暴露窗口；本项目不要求持久化，也不读取环境全集。

## 不显示密钥的配置检查

只检查是否存在，不打印值：

```powershell
if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) { 'missing' } else { 'configured' }
if ([string]::IsNullOrWhiteSpace($env:OPENAI_MODEL)) { 'missing' } else { 'configured' }
```

发现泄漏时应在 OpenAI 账号侧撤销该 key，并创建新 key；不要把旧值粘贴到 issue 或日志中。

## 启动 MiniCodex

```powershell
coding-agent "修复失败测试" --workspace . --model '<model-id-available-to-your-account>' --verify "pytest -q"
```

这是正常生产 API 调用，会访问网络、可能产生费用且结果具有非确定性。启动前 CLI 会校验工作区、凭据、模型和 `--verify`；配置错误以退出码 2 结束，不构造 SDK 客户端。

## ModelClient 与适配器边界

核心仅依赖 `src/coding_agent/model.py` 中的 `ModelClient.complete(ModelRequest) -> ModelResponse`。`OpenAIResponsesClient` 是唯一允许导入 OpenAI SDK 的生产模块；`AgentRunner`、消息、上下文、状态和工具系统只看 provider-neutral 类型。

SDK 对象、异常、Response 对象和输出 item 不会进入内部 `ModelResponse`。文本、工具调用、usage、response ID 和 continuation 会转换为不可依赖 SDK 的内部数据。

## Responses API 请求映射

生产代码调用 `client.responses.create`，而不是 Chat Completions，并显式发送：

- `store=False`，不在服务端保存本项目的响应状态；
- 本地映射的 `input` 消息和工具结果；
- `strict: true` 的 function tool schema；
- 模型 ID、最大输出 token 和 `include=["reasoning.encrypted_content"]`。

工具 schema 在发送前再次检查必需字段、`additionalProperties: false` 和嵌套结构。API 的 strict schema 只提高模型输出可靠性，本地 ToolRegistry 仍执行完整参数和安全校验。

## 工具调用和 call_id 配对

Responses 输出中的每个 `function_call` 转为有序 ToolCall，保留 `name`、JSON arguments 和 `call_id`。多个调用保持供应商响应中的顺序。

本地执行完成后，下一次请求发送 `function_call_output`，并使用同一个 `call_id` 配对。缺失、空白、重复或无法解析的字段会产生稳定内部错误，不执行工具，也不会通过异常文本暴露 provider body。

## 本地历史与 continuation

本地 `AgentState.messages` 是权威历史；项目不使用 server conversation，也不使用 `previous_response_id` 替代本地消息。每轮输入由内部用户、助手、工具调用和工具结果重新映射。

需要续接的响应 output 会转成 SDK-free、不可变且 repr 隐藏的 continuation snapshot。它只与对应的本地 assistant message 索引一起重放，避免重复 function call。opaque continuation、encrypted reasoning 和 provider payload 只驻留内存，不序列化、不打印、不写 JSONL 或 FinalReport。

上下文压缩成功替换活动历史时，旧 continuation 原子清空；摘要调用本身产生的 continuation 也丢弃。未压缩时，当前 continuation 原样透传。

## logical call 与 provider attempt

一次 Agent 或摘要意图是一个 logical model call。一次真实 `responses.create` 是一个 physical provider attempt。瞬时错误重试会增加 provider attempt，但不会凭空创建新的 logical call。

两者共享同一个 run-scoped `ModelCallBudget`：每次主调用和摘要调用开始前领取 logical call，每次实际 SDK 请求前领取 provider attempt。预算采用“阻止第一个不允许的操作”语义，计数不会超过上限；预算不足时不会再发请求。

## 重试和永久错误

官方 SDK 的自动重试通过 `max_retries=0` 关闭，由适配器执行确定性策略：初始请求加最多两次重试，延迟依次为 0.25 秒、0.50 秒，无 jitter。共享预算可能更早阻止下一次尝试。

会重试：HTTP 429、HTTP 5xx、timeout 和临时 connection error。不会重试：authentication、permission、not-found/模型不可用、bad request、unprocessable request、本地请求映射错误和响应解析错误。永久错误、非法响应和预算错误立即返回稳定内部分类，不复制 provider 异常正文。

## 隐私与日志边界

正常 JSONL 和 FinalReport schema 不接受 API key、Authorization 值、环境全集、请求正文、Response 对象、provider 异常正文、完整消息历史、工具原始内容、continuation 或隐藏推理。已知敏感值和常见凭据模式在允许写入的文本字段中再次脱敏。

`store=False` 控制是否通过 API 存储生成的 Response；它不等于本地无日志。MiniCodex 仍会在工作区 `.coding-agent/logs/` 写入经过白名单和脱敏的执行事实。

## 完全离线的自动测试

默认测试注入 fake SDK client、fake response 和 fake exception，不读取真实 key、不构造真实网络客户端：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py tests\test_model.py -q -p no:cacheprovider
```

完整离线测试同样不会访问 OpenAI API：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

## 手工联网冒烟（自动测试不会执行）

此步骤只能由用户在明确授权后手工执行。它会联网、可能产生费用、结果非确定，并且不属于 pytest 或最终离线验收。先复制一个可丢弃 demo 工作区，确认当前会话已安全配置 key 和可用 model，再执行正常 `coding-agent` 命令；不要在命令、终端录屏或报告中显示 key。

冒烟结束后检查 FinalReport 和脱敏 JSONL 是否一致。不要把真实响应内容当成确定性回归基线，也不要让自动测试调用此流程。

## 常见 API 错误

- authentication/permission：检查 key 是否有效且账号有权限；适配器不重试。
- not-found/模型错误：确认模型 ID 对当前账号可用；不要依赖文档中的旧示例 ID。
- 429：适配器最多按 0.25、0.50 秒重试；持续失败会进入稳定模型错误或预算终止。
- 5xx、timeout、connection error：属于瞬时错误，但最多总计三次物理请求。
- bad request/unprocessable：通常是模型、字段或 schema 不兼容，不重试。
- response invalid：未知 output type、字段缺失、损坏 JSON 或错误 `call_id` 会成为稳定解析错误，不把 provider body 写入报告。
- provider attempt budget：表示共享物理请求额度已用尽，不会再调用 API。

## 当前未实现的扩展

当前版本只实现官方 OpenAI 客户端。所谓 provider-neutral 是核心接口解耦，不表示下列接入已经可用。

| 扩展 | 状态 |
| --- | --- |
| custom base_url | 当前未实现 |
| Azure OpenAI | 当前未实现 |
| 第三方 compatible endpoint | 当前未实现 |
| proxy 配置 | 当前未实现 |
| server conversation | 当前未实现 |
| streaming | 当前未实现 |
| async API | 当前未实现 |
| 其他 provider adapter | 当前未实现 |

未来兼容 provider 应在新的适配器内实现现有 `ModelClient`，返回内部 `ModelResponse`，并为请求映射、错误分类、重试和隐私边界提供离线测试；不应修改 AgentRunner，也不能把第三方 SDK 类型传播到核心层。新增 provider、`base_url`、代理或依赖都需要重新设计和用户批准。

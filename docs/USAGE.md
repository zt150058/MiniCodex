# MiniCodex 使用说明

MiniCodex 是一次性运行的本地 Coding Agent。它在用户指定的工作区内读取和修改 UTF-8 文本、执行受控命令，并由本地验证门决定任务是否成功。模型层默认使用 OpenAI Responses，也可显式选择 compatible Chat Completions。项目入口见[仓库首页](../README.md)，模型接入细节见 [API 说明](OPENAI_API.md)。

## 功能与适用场景

适合在可信、可丢弃的 Python 项目副本中检查代码、进行确定性文本修改、运行测试并根据失败结果继续修复。Agent 主循环、消息历史、上下文压缩、工具分派、路径与命令策略、终止条件、验证新鲜度、JSONL 日志和 FinalReport 都由本项目本地实现。

首版不提供聊天 REPL、多 Agent、任意 Shell、网络下载、包安装、文件删除、Git 写入或自动推送。

## 已验证环境与系统要求

- Windows 优先；当前版本不承诺 Linux 或 macOS 支持。
- Python 3.11+。
- 生产依赖为官方 `openai` Python 包，测试依赖为 pytest。
- 默认自动测试完全离线，不需要真实 API key，也不会探测 endpoint。

## Windows PowerShell 安装

在仓库根目录执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
coding-agent --help
```

最后一条命令应只显示 CLI 帮助，不调用模型。若 PowerShell 阻止激活脚本，可直接使用 `.\.venv\Scripts\python.exe` 和 `.\.venv\Scripts\coding-agent.exe`。

## 工作区与凭据准备

工作区必须是已存在的目录。建议复制原项目并保留备份，再把副本传给 `--workspace`。在当前 PowerShell 会话配置模型和所选 API mode 对应的凭据：

```powershell
$env:OPENAI_API_KEY = '<openai-api-key>'
$env:CHAT_COMPLETIONS_API_KEY = '<chat-completions-provider-key>'
$env:OPENAI_MODEL = '<model-id>'
```

只需配置所选 mode 的 key：`responses` 只读取 `OPENAI_API_KEY`，`chat-completions` 只读取 `CHAT_COMPLETIONS_API_KEY`，两者不互相回退。不要把 API key 放进源代码、CLI 参数、Git、日志、截图或视频。模型也可以通过 `--model` 提供，此时它覆盖 `OPENAI_MODEL`。

## CLI 参数

| 名称 | 必需 | 含义 |
| --- | --- | --- |
| `task` | 是 | 交给本地 Agent 的一次性编程任务。 |
| `--workspace` | 是 | 目标工作区目录；启动时规范化并执行安全检查。 |
| `--verify` | 否 | 用户指定的强制最终验证命令；启动前使用同一命令策略授权。 |
| `--model` | 否 | 模型 ID；覆盖 `OPENAI_MODEL`。 |
| `--api-mode` | 否 | 只接受 `responses` 或 `chat-completions`；默认 `responses`。 |
| `--base-url` | 仅 Chat | compatible Chat Completions 的绝对 HTTPS API 前缀。 |
| `-h` / `--help` | 否 | 显示帮助并退出。 |

`responses + --base-url` 是非法配置，不会静默忽略；`chat-completions` 必须提供 `--base-url`。当前解析器没有交互模式、fake 模式或恢复会话参数。

## 最小运行示例

```powershell
coding-agent "修复失败测试" --workspace . --api-mode responses --model '<openai-model-id>' --verify "pytest -q"

coding-agent "修复失败测试" --workspace . --api-mode chat-completions --base-url '<https-provider-base-url-with-api-prefix>' --model '<compatible-model-id>' --verify "pytest -q"
```

`responses` 可省略 `--api-mode`。未提供 `--verify` 时，模型必须通过 `run_command` 选择经过本地安全策略允许且 `purpose="verification"` 的可信命令。目录查看、echo 和 `git status` 不能成为成功证据。

## 推荐的安全运行示例

在已备份的项目副本中固定验证命令：

```powershell
coding-agent "修复当前项目中的失败测试" --workspace . --api-mode responses --model '<openai-model-id>' --verify "pytest -q"
```

`--verify "pytest -q"` 在启动阶段授权。每个完成候选都会在工具和时间预算允许时执行这条固定命令；非零退出码会回流给模型继续修复，而不会被当作成功。

## Agent 运行流程

1. CLI 在联网前校验任务、工作区、API mode、base URL、模式专用凭据、模型和可选验证命令。
2. composition root 只构造所选模型适配器，以及共享工作区、命令执行器、工具注册表、上下文管理器、终止策略、验证门和事件日志器。
3. 启动时只读取一次根 `AGENTS.md`，与内置基础规则组合成不可变运行指令；Agent 根据该指令和本地历史请求模型。超过字符或历史项阈值时生成结构化摘要，失败则使用确定性 fallback，摘要不会继承运行指令。
4. 工具调用按响应顺序进行本地校验、授权、执行和观察，结果通过 `call_id` 配对写回历史。
5. 文件修改增加 mutation index，并使旧验证状态失效。
6. 完成候选只有在本地验证门接受新鲜证据后才能成为 SUCCESS。
7. 预算耗尽、重复无进展、安全拒绝或不可恢复错误产生稳定失败原因。

两个模型适配器内部都支持可选的 provider-neutral 文本流事件，以及首个 delta 前的结构化同步回退。**CLI 仍使用同步最终报告**：当前命令行不会逐 token 显示内容，也没有 SSE、WebSocket 或 GUI 事件传输层。部分输出仅驻留内存；中断后不会写入消息历史、JSONL 或 FinalReport。

## 五个本地工具

| 工具 | 能力与主要限制 |
| --- | --- |
| `list_directory` | 稳定排序列举；递归深度 1–3，最多 500 项。 |
| `read_file` | 带真实行号读取 UTF-8 文本；单次最多 256 KiB。 |
| `replace_text` | 仅在实际匹配数等于 expected count 时执行精确替换。 |
| `write_file` | 只创建不存在的新 UTF-8 文件，不覆盖且不创建父目录。 |
| `run_command` | 参数数组、`shell=False`、固定 cwd、超时与双流 64 KiB 上限。 |

文件工具不能访问 `.git/` 或 `.coding-agent/`。命令仅允许策略明确支持的 Python/pytest/unittest、受限 ruff/mypy 和只读 Git 形式；最终是否允许以运行时安全策略为准。

## 成功、验证与退出码

SUCCESS 不由模型文字决定。最新验证必须在最后一次文件修改后运行、退出码为 0，并满足 `validation_index == mutation_index`。

| 退出码 | FinalReport 状态 | 含义 |
| --- | --- | --- |
| `0` | `success` | 完成候选具有新鲜、通过的本地验证证据。 |
| `1` | `failed` | 预算、重复、安全、模型、工具、验证或审计失败。 |
| `2` | 无 FinalReport | CLI 参数或启动配置错误。 |
| `130` | `interrupted` | 用户中断，日志会尽力关闭并生成中断报告。 |

## JSONL 日志与 FinalReport

每次已启动运行的事件写入 `.coding-agent/logs/<run_id>.jsonl`。事件按连续 sequence 记录模型调用元数据、工具调用/结果、安全拒绝、压缩、验证和终止事实；不记录完整任务文本、工具原始内容、环境全集、API key、认证头、continuation 或隐藏推理。`OPENAI_API_KEY` 和 `CHAT_COMPLETIONS_API_KEY` 都会从 `run_command` 子进程环境中移除。

进程在 stdout 输出一个有界 JSON FinalReport，其中包含状态、退出码、终止原因、修改路径、验证证据、计数、日志相对路径和审计失败代码。报告与 JSONL 使用同一执行状态。

## 离线演示与完整测试

确定性 demo 位于 `tests/integration/test_agent_repair.py`，使用 FakeModelClient，复制 `examples/broken_pytest_project/` 后完成“读取—修改—验证失败—再次修改—验证通过”：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_agent_repair.py -q -p no:cacheprovider
```

Chat 连续 Agent 循环合同位于 `tests/integration/test_chat_completions_agent.py`，使用真实 AgentRunner、ContextManager 和 Chat 适配器，只把最外层 SDK 换成 fake：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_chat_completions_agent.py -q -p no:cacheprovider
```

完整离线测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

这些 pytest 命令不会调用真实模型 API。

## 常见错误与排查

- `OPENAI_API_KEY is not configured`：只在当前会话配置环境变量，不要打印其值。
- `CHAT_COMPLETIONS_API_KEY is not configured`：Chat mode 只读取该变量，不回退到 OpenAI key。
- `--base-url is not allowed with responses`：移除 base URL，Responses 始终使用官方默认 endpoint。
- `--base-url is required with chat-completions`：提供包含 API 前缀的绝对 HTTPS URL。
- `model is not configured`：设置 `OPENAI_MODEL` 或传 `--model`。
- `workspace rejected`：确认目录存在，且路径没有非法设备名、受保护组件或 reparse point。
- `--verify rejected`：命令不在安全白名单、包含控制符，或不是可信验证命令。
- 退出 `1`：读取 FinalReport 的 termination reason、验证证据和 `.coding-agent/logs/<run_id>.jsonl` 中的脱敏事件。
- 测试超时：命令执行器会终止 Windows 子进程树并保留受限的 stdout/stderr；检查 `timed_out` 和 `cleanup_error`。

## 停止运行与清理

按 `Ctrl+C` 请求停止。正常中断应返回 `130` 和 `interrupted` 报告；强制关闭终端可能阻止最终报告写出。

进程停止后，用户可以自行删除工作区内 `.coding-agent` 目录来清理本地日志。Agent 没有删除工具，也不会自动清理、提交或上传这些文件。

## 安全边界和已知限制

路径和命令限制由确定性本地代码执行，包含工作区约束、受保护目录、Windows reparse point 检查、有限命令集、固定 cwd、`shell=False`、超时和输出上限。

`--base-url` 可配置不代表兼容所有服务。compatible endpoint 必须支持标准 Chat Completions assistant `tool_calls`、非空函数 call ID、strict function schema，以及用 `tool_call_id` 配对的 `role=tool` 结果；本项目不会根据 URL 猜测、探测或自动切换 API mode。

这不是操作系统级沙箱。被允许执行的工作区脚本、pytest 配置和测试会作为可信代码运行，仍可能访问操作系统资源；策略也不能消除所有检查与使用之间的 TOCTOU 风险。请只处理可信项目，并使用可丢弃、已备份的工作区副本。

当前没有会话持久化、SSE/GUI、异步模型客户端、可执行 Skill 管理或 MCP。`RunInstructionBuilder` 只提供受限的纯文本 Skill 指令输入边界；生命周期控制器、会话管理和动态 Skill/MCP 集成属于后续任务。

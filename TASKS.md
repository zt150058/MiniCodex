# Implementation Tasks

本文档只定义未来实施阶段的任务，不授权创建源代码。所有任务初始状态均为“未开始”。只有三份设计文档获得用户批准、详细实现计划再次获得批准后，才能从任务 1 开始。

状态取值固定为：`未开始`、`进行中`、`已完成`、`受阻`。任一时刻最多只有一个任务处于 `进行中`。

## 1. 项目骨架与最小 CLI

**任务目标**

建立最小 Python 包、pytest 测试布局和一次性 CLI。CLI 能解析任务、`--workspace`、可选 `--verify`、`--model` 及环境变量，但暂不运行 Agent。

**涉及模块**

- `pyproject.toml`
- `src/coding_agent/__init__.py`
- `src/coding_agent/cli.py`
- `src/coding_agent/config.py`
- `tests/test_cli.py`
- `.gitignore`

**验收标准**

- 包可通过项目定义的标准命令运行。
- 缺少任务、工作区无效、模型未配置或 `--verify` 为空时返回退出码 `2` 和清晰错误；完整验证命令安全策略在任务 8 接入。
- 从 `OPENAI_MODEL` 和 `OPENAI_API_KEY` 读取配置，但不打印密钥。
- `.coding-agent/` 和本地凭据配置被 Git 忽略。
- 只引入已批准的 `openai` 和 `pytest` 依赖。

**需要编写的测试**

- CLI 参数成功与失败路径。
- 命令行参数覆盖环境变量的优先级。
- 工作区规范化、不存在目录拒绝和空验证命令拒绝。
- 错误输出不包含 API Key。

**建议的 Git 提交说明**

`chore: scaffold python package and minimal cli`

**当前状态**

`已完成`

## 2. 消息数据结构

**任务目标**

实现供应商无关的用户消息、助手消息、工具调用、工具结果、模型请求和模型响应类型，并提供稳定序列化。

**涉及模块**

- `src/coding_agent/messages.py`
- `tests/test_messages.py`

**验收标准**

- `ToolCall` 和 `ToolResult` 通过 `call_id` 配对。
- 工具结果状态只能为 `ok`、`error` 或 `rejected`。
- 可空值显式序列化为 `null`。
- 内部类型不导入 OpenAI SDK 类型。
- 非法状态和缺失必需字段会被拒绝。

**需要编写的测试**

- 所有消息类型的构造和 JSON 往返。
- 非法状态、重复或空 `call_id`。
- 元数据字段和空值序列化。
- 内部模块不依赖 OpenAI SDK 的边界测试。

**建议的 Git 提交说明**

`feat: define provider-neutral agent messages`

**当前状态**

`已完成`

## 3. `ModelClient` 抽象和 `FakeModelClient`

**任务目标**

定义模型调用协议和确定性的脚本化假客户端，为主循环测试提供离线模型行为。

**涉及模块**

- `src/coding_agent/model.py`
- `tests/test_model.py`

**验收标准**

- `ModelClient.complete(ModelRequest) -> ModelResponse` 接口明确。
- `FakeModelClient` 按顺序返回预设响应并记录请求。
- 响应序列耗尽时抛出明确的测试错误。
- 可以模拟文本完成、单个或多个工具调用、模型错误和摘要响应。

**需要编写的测试**

- 预设响应顺序和请求捕获。
- 序列耗尽行为。
- 工具调用与文本响应组合。
- 瞬时和致命模型错误模拟。

**建议的 Git 提交说明**

`feat: add model client protocol and fake client`

**当前状态**

`已完成`

## 4. 最小 Agent 循环

**任务目标**

实现显式 `AgentState` 和最小同步循环，使 FakeModelClient 能发起工具调用、接收结果并返回完成候选。此阶段只使用内存假工具，不接入真实文件和命令。

**涉及模块**

- `src/coding_agent/state.py`
- `src/coding_agent/agent.py`
- `src/coding_agent/tools/base.py`
- `src/coding_agent/tools/registry.py`
- `tests/test_agent_loop.py`

**验收标准**

- `AgentRunner` 是唯一顶层状态迁移入口。
- 工具按模型响应顺序执行。
- 每个工具结果写回下一轮模型请求。
- 未知工具和坏参数产生结构化错误，不导致未处理异常。
- 测试中的循环具有临时硬轮次上限，后续由正式终止策略替换。
- 此阶段只返回 `COMPLETION_CANDIDATE`，不得在验证门槛实现前映射为 `SUCCESS`。

**需要编写的测试**

- 文本直接完成候选。
- 一轮和多轮工具调用。
- 多个工具顺序执行。
- 未知工具、坏参数和工具异常。
- 工具结果与 `call_id` 配对。

**建议的 Git 提交说明**

`feat: implement minimal explicit agent loop`

**当前状态**

`已完成`

## 5. 文件读取与目录工具

**任务目标**

实现 `list_directory` 和 `read_file`，支持受限目录查看和带行号的 UTF-8 文本读取。此阶段先实现功能约束，完整工作区逃逸防护在任务 8 集中加固。

**涉及模块**

- `src/coding_agent/tools/filesystem.py`
- `src/coding_agent/tools/registry.py`
- `tests/tools/test_read_tools.py`

**验收标准**

- 目录结果稳定排序。
- 递归深度限制为 1 至 3，条目限制为 1 至 500。
- 文件读取支持起止行，单次上限 256 KiB。
- 二进制或非 UTF-8 文件被明确拒绝。
- 输出达到限制时标记 `truncated=true`。

**需要编写的测试**

- 空目录、嵌套目录、排序、深度和条目限制。
- 完整读取、分段读取和行号。
- 大文件截断、无效行范围和编码错误。
- 不存在文件或目录。

**建议的 Git 提交说明**

`feat: add directory listing and file reading tools`

**当前状态**

`已完成`

## 6. 文件修改工具

**任务目标**

实现 `replace_text` 和只创建新文件的 `write_file`，维护修改账本并使旧验证状态失效。

**涉及模块**

- `src/coding_agent/tools/filesystem.py`
- `src/coding_agent/state.py`
- `tests/tools/test_write_tools.py`

**验收标准**

- 精确替换要求实际匹配次数等于 `expected_count`。
- 匹配数量不符时文件保持字节级不变。
- `write_file` 拒绝覆盖现有文件。
- 单次写入不超过 512 KiB，只接受 UTF-8 文本。
- 成功修改记录路径、增加 `mutation_index` 并设置验证状态为 `STALE`。
- 不提供删除、移动或权限修改能力。

**需要编写的测试**

- 单次和多次精确替换。
- 匹配数量不符的零修改保证。
- 新文件创建和覆盖拒绝。
- 写入大小限制和编码行为。
- 修改账本及验证失效。

**建议的 Git 提交说明**

`feat: add deterministic file modification tools`

**当前状态**

`已完成`

## 7. Shell 命令工具

**任务目标**

实现 Windows 优先的 `run_command` 执行器，捕获退出码、stdout、stderr、超时和截断。此阶段使用最小允许命令集合，完整策略在任务 8 加固。

**涉及模块**

- `src/coding_agent/tools/shell.py`
- `src/coding_agent/tools/registry.py`
- `tests/tools/test_shell_tool.py`

**验收标准**

- 命令解析为参数数组并以 `shell=False` 执行。
- 子进程 `cwd` 固定为工作区。
- 默认超时 60 秒，配置不超过 300 秒。
- stdout 和 stderr 各限制为 64 KiB。
- 超时后终止整个子进程树。
- 结果包含命令、purpose、退出码、耗时、超时和截断元数据。

**需要编写的测试**

- 成功、非零退出和 stderr 捕获。
- 工作目录固定。
- 超时和子进程终止。
- stdout、stderr 截断。
- `inspect`、`test` 和 `verification` purpose 校验。

**建议的 Git 提交说明**

`feat: add bounded windows command execution tool`

**当前状态**

`已完成`

## 8. 工作区和命令安全限制

**任务目标**

实现统一 `PathGuard` 和 `CommandPolicy`，保证所有文件工具和命令在调用前经过确定性安全授权。

**涉及模块**

- `src/coding_agent/safety.py`
- `src/coding_agent/tools/filesystem.py`
- `src/coding_agent/tools/shell.py`
- `src/coding_agent/config.py`
- `tests/test_path_safety.py`
- `tests/test_command_safety.py`

**验收标准**

- 文件工具只接受工作区相对路径。
- 拒绝绝对路径、`..`、NUL、工作区逃逸、符号链接、junction 和 reparse point 逃逸。
- `.git/` 和 `.coding-agent/` 不可被模型文件工具读取或修改；只有内部日志器可以写入 `.coding-agent/logs/`。
- 拒绝 Shell 控制符、Shell 程序、网络、包安装、系统管理和破坏性命令。
- 允许设计规定的 Python 验证命令、工作区内 Python 脚本和只读 Git 子命令。
- `--verify` 在启动阶段经过同一命令策略。
- 安全策略返回稳定错误码，不依赖提示词。

**需要编写的测试**

- 各种相对路径、绝对路径、大小写和父级跳转变体。
- 符号链接和 junction/reparse point 逃逸；无权限环境使用明确跳过条件和纯策略替代测试。
- Shell 控制符和禁止程序。
- Git 允许与禁止子命令。
- `pytest -q` 和规定的 Python 命令允许路径。
- 用户验证命令启动时拒绝。

**建议的 Git 提交说明**

`feat: enforce workspace and command safety policies`

**当前状态**

`已完成`

## 9. OpenAI-compatible 模型客户端

**任务目标**

在 `ModelClient` 边界后实现 OpenAI 官方 Responses API 客户端。首版只支持 OpenAI 官方服务；“compatible”指核心循环保持供应商无关接口，不承诺第三方网关兼容。

**涉及模块**

- `src/coding_agent/openai_client.py`
- `src/coding_agent/config.py`
- `tests/test_openai_client.py`

**验收标准**

- 使用官方 `openai` Python 客户端和 Responses API。
- 设置 `store=False`，不以服务端 conversation 或 `previous_response_id` 代替本地历史。
- 工具定义使用 strict schema。
- 正确解析文本、function calls、`call_id`、usage 和续接项。
- 正确生成 `function_call_output`。
- 内部类型与 SDK 类型保持隔离。
- 瞬时错误最多重试两次；认证和配置错误不重试。
- 默认自动测试不发起网络请求。

**需要编写的测试**

- 使用伪 SDK 对象验证请求映射。
- 文本、单个和多个 function call 解析。
- continuation items 和 function result 续接。
- strict 工具 schema。
- 429、5xx、超时、认证失败和非法响应。
- 确认日志和异常不包含密钥。

**建议的 Git 提交说明**

`feat: integrate openai responses model client`

**当前状态**

`已完成`

## 10. 上下文管理、循环终止与重复调用检测

**任务目标**

实现 `ContextManager` 和正式 `TerminationPolicy`。上下文管理负责压缩触发、完整 turn 划分、结构化摘要校验和确定性降级；终止策略覆盖模型调用、工具调用、总时间、重复调用、连续错误和安全拒绝预算。

**涉及模块**

- `src/coding_agent/termination.py`
- `src/coding_agent/context.py`
- `src/coding_agent/state.py`
- `src/coding_agent/agent.py`
- `src/coding_agent/model.py`
- `tests/test_termination.py`
- `tests/test_context.py`

**验收标准**

- 活动上下文超过 60,000 字符或 24 个历史项时触发压缩。
- 压缩以完整 turn 为边界并保留最近 8 个完整 turn。
- 摘要包含设计规定的九类字段，并由本地状态强制补入任务、修改和验证不变量。
- 摘要调用失败或 JSON 不合法时使用确定性降级摘要继续运行。
- 默认限制为 12 次模型调用、40 次工具调用和 10 分钟。
- 模型调用总数包含上下文摘要调用和瞬时错误的每次重试尝试。
- 工具名和规范化 JSON 参数生成稳定 fingerprint。
- 相同调用无进展 3 次后失败。
- 连续错误或安全拒绝 3 次后失败。
- 状态进展按设计重置相应计数。
- 所有退出都有稳定原因和退出码，不存在无限循环。

**需要编写的测试**

- 字符数和历史项压缩阈值边界。
- ToolCall 与 ToolResult 不被拆分。
- 摘要字段校验、本地不变量合并和确定性降级。
- 压缩后丢弃旧 continuation items 并开启新上下文段。
- 每种预算的边界前、边界值和越界行为。
- JSON 参数顺序不同但 fingerprint 相同。
- 无进展重复与有进展重复的区别。
- 连续错误和成功后的重置。
- 单调时钟注入和时间耗尽。

**建议的 Git 提交说明**

`feat: add context and explicit termination policies`

**当前状态**

`已完成`

## 11. 修改后的验证门槛

**任务目标**

实现混合 `VerificationGate`，确保模型完成声明不能绕过用户强制验证或本地验证证据。

**涉及模块**

- `src/coding_agent/verification.py`
- `src/coding_agent/state.py`
- `src/coding_agent/agent.py`
- `src/coding_agent/tools/shell.py`
- `tests/test_verification.py`

**验收标准**

- 每次文件修改增加 `mutation_index` 并使旧验证失效。
- 有 `--verify` 时，每个完成候选都执行固定命令；退出码非零绝不成功。
- 强制验证失败会回流给模型，预算允许时继续修复。
- 无 `--verify` 时只接受 `purpose="verification"` 的可信安全命令。
- `echo`、目录查看和 `git status` 不能作为验证证据。
- 验证必须晚于最后一次修改。
- 最终报告展示真实命令、来源、退出码和结果。

**需要编写的测试**

- 强制验证通过和失败。
- 失败后继续修改并再次验证。
- 旧验证在新修改后失效。
- Agent 自选可信验证。
- 伪验证命令拒绝。
- 模型声称成功但无证据。

**建议的 Git 提交说明**

`feat: enforce post-change verification gate`

**当前状态**

`已完成`

## 12. 会话和工具调用日志

**任务目标**

实现工作区内受保护的 JSONL 事件日志和最终报告，确保执行过程可复现且不泄露凭据。

**涉及模块**

- `src/coding_agent/logging.py`
- `src/coding_agent/report.py`
- `src/coding_agent/agent.py`
- `tests/test_logging.py`
- `tests/test_report.py`

**验收标准**

- 日志写入 `.coding-agent/logs/<run_id>.jsonl`。
- 记录模型调用元数据、工具调用、工具结果、安全拒绝、上下文压缩、验证和终止事件。
- 日志不记录隐藏推理、认证头、opaque continuation payload 或环境变量全集。
- 已知 API Key 和常见密钥模式在写入前脱敏。
- 日志写入失败时停止运行并明确报告，避免不可审计执行。
- 最终报告与 JSONL 使用相同执行事实。

**需要编写的测试**

- 事件顺序和必需字段。
- API Key、Bearer 和常见密钥模式脱敏。
- 不允许模型工具访问日志目录。
- 日志写入失败行为。
- 最终报告中的命令、退出码、验证和终止原因。

**建议的 Git 提交说明**

`feat: add redacted run logs and evidence reports`

**当前状态**

`已完成`

## 13. 集成测试和演示项目

**任务目标**

建立确定性的端到端测试和可用于视频的失败 pytest 演示项目，证明自动修复、验证回流和上下文管理能够协同工作。

**涉及模块**

- `tests/integration/test_agent_repair.py`
- `tests/integration/test_agent_failures.py`
- `examples/broken_pytest_project/`
- 现有 Agent、工具、验证和日志模块

**验收标准**

- FakeModelClient 驱动完整的“读—改—失败—再改—通过”流程。
- 演示固定使用 `--verify "pytest -q"`。
- 强制验证失败时测试证明 Agent 不能成功。
- 路径、命令、重复调用和预算失败路径均有集成覆盖。
- JSONL 与最终报告对命令和退出码保持一致。
- 可选真实 OpenAI 冒烟测试必须显式启用，默认测试不联网。

**需要编写的测试**

- 成功修复端到端测试。
- 首次验证失败、第二次修复成功。
- 最后修改导致旧验证失效。
- 重复调用终止。
- 安全拒绝不产生副作用。
- 上下文压缩成功和降级路径。

**建议的 Git 提交说明**

`test: add end-to-end repair scenario and demo project`

**当前状态**

`已完成`

## 14. README、视频和提交物检查

**任务目标**

完成 Task 1–13 的证据化只读代码审查，只修复用户明确批准的问题，并完善公开仓库说明、考核用 `README.txt`、离线安装和最终安全审计。视频、ZIP、release、上传和远程仓库操作不属于本任务范围。

**涉及模块**

- `README.md`
- `README.txt`
- `docs/USAGE.md`
- `docs/OPENAI_API.md`
- `tests/test_docs.py`
- 用户明确批准的 finding 对应源码和测试

**验收标准**

- Task 1–13 的全部生产代码、测试、演示项目和设计边界经过证据化审查。
- 只修复用户明确批准、可复现且不改变设计或依赖的 finding。
- `README.md` 说明架构、运行、限制、测试和安全边界。
- `README.txt` 不超过 1000 汉字，包含仓库地址、运行方法、特色功能和必要说明。
- `docs/USAGE.md` 说明安装、配置、运行、验证、日志、退出码、故障排查和安全边界。
- `docs/OPENAI_API.md` 说明 Responses API 映射、重试、continuation、隐私边界和未实现扩展。
- 干净离线 wheel 安装、CLI 入口、默认离线测试、Windows reparse 和进程树行为均有新鲜验证证据。
- 仓库和公开文档不包含 API Key、认证头、个人绝对路径或 continuation payload。
- 本任务不创建或检查视频、ZIP、release 或上传产物，也不修改远程仓库。

**需要编写的测试**

- 文档存在性、UTF-8、链接、CLI、工具、退出码、API 和隐私合同测试。
- approved finding 各自的 RED、GREEN 和回归测试。
- 全量自动测试、离线集成测试和干净安装实际运行。
- 凭据模式扫描。
- `README.txt` 总 Unicode 字符、汉字、UTF-8 字节和行数检查。
- Windows symlink、junction、reparse point、timeout 和进程树专项测试。
- Git 状态、diff、依赖、Agent 框架、占位符和测试抑制检查。
- 记录所有实际执行命令和真实结果，不声称未执行的检查。

**建议的 Git 提交说明**

`docs: complete final review and offline documentation audit`

**当前状态**

`已完成`

## 15. OpenAI-compatible Chat Completions provider 适配

**任务目标**

在保持 `ModelClient.complete(ModelRequest) -> ModelResponse`、现有 `OpenAIResponsesClient` 和本地 Agent 生命周期不变的前提下，新增供应商中立的 Chat Completions 适配器。通过显式 `api-mode + base-url` 选择第三方兼容 endpoint，首个兼容目标是 BayesDL GLM；不硬编码供应商，不使用服务端会话状态。

**涉及模块**

- `src/coding_agent/chat_completions_client.py`
- `src/coding_agent/config.py`
- `src/coding_agent/cli.py`
- `src/coding_agent/app.py`
- `src/coding_agent/tools/shell.py`
- `tests/test_chat_completions_client.py`
- `tests/integration/test_chat_completions_agent.py`
- `tests/tools/test_shell_tool.py`
- 配置、CLI、应用和文档合同测试
- `DESIGN.md`
- `README.md`
- `README.txt`
- `docs/USAGE.md`
- `docs/OPENAI_API.md`

**验收标准**

- `--api-mode` 只接受 `responses` 和 `chat-completions`，默认 `responses`。
- `responses` 继续使用 OpenAI 官方默认 endpoint；`responses + --base-url` 在任何 SDK 构造或网络请求前以稳定、脱敏的配置错误失败，不得忽略。
- `chat-completions` 必须显式提供合法的绝对 HTTPS `--base-url`；原始 URL 中的 C0/DEL 控制字符、内部空白和反斜杠必须在解析前被拒绝；项目不硬编码、探测或猜测供应商。
- Responses 只读取 `OPENAI_API_KEY`，Chat Completions 只读取 `CHAT_COMPLETIONS_API_KEY`；两者不回退，不提供 API Key CLI 参数，也不在日志、错误或报告中泄漏凭据和认证头；两个变量都不得进入 `run_command` 子进程环境。
- 新 `ChatCompletionsModelClient` 位于独立模块，SDK 类型不越过适配层，现有 ModelClient 公共接口和 Responses 实现行为不变。
- 每次 provider 调用接收 `ContextManager` 准备后的完整内部历史，并正确映射 user、assistant、assistant tool calls 和通过 `tool_call_id` 配对的 tool results。
- assistant 工具调用消息保留在后续上下文；工具结果后模型可继续产生新的工具调用或最终文本；单轮多个工具调用保持顺序。
- Chat 响应解析直接检查 `message.tool_calls`，不依赖 `finish_reason` 判断工具调用，并支持工具调用与文本共存。
- continuation 始终为空；不使用 conversation、`previous_response_id` 或其他服务端持久状态。
- 压缩后的历史仍满足 Chat Completions assistant/tool 顺序和配对约束，并可继续调用模型。
- strict function schema、`max_tokens`、单 choice、标准 function tool call、唯一 call ID、JSON object arguments、usage 和 response ID 按批准设计映射。
- SDK 内建重试关闭；瞬时错误最多按 0.25/0.50 秒退避重试两次，每次真实尝试领取共享模型预算；致命配置/请求错误和无效响应不重试。
- 外部异常和无效 payload 转换为稳定、脱敏的本地错误；SDK 在返回对象前抛出的 `APIResponseValidationError` 和 `json.JSONDecodeError` 也归为不重试的 `invalid_model_response`，且不输出原始响应体、JSON doc、SDK exception repr、API Key、Authorization header 或环境内容。
- 默认自动测试完全离线；现有 Responses 测试保持通过，且不调用真实 API。
- 文档明确说明可配置 base URL 不代表兼容所有服务，目标 endpoint 必须支持标准 Chat Completions 工具调用语义。
- 不新增依赖、Agent 框架、工具或无关重构。

**需要编写的测试**

- Chat 客户端构造、URL 校验（含控制字符、内部空白和反斜杠）、请求映射、strict schema、输出限制、文本、单/多工具调用、完成原因、usage、response ID 和无效 payload 单元测试。
- 瞬时/致命错误、SDK 解码/响应校验异常、重试次数与退避、共享调用预算、脱敏、非空 continuation 和 SDK 调用前历史配对拒绝测试。
- 真实允许的 Python 子进程与 process-factory 环境捕获测试，证明 `OPENAI_API_KEY` 和 `CHAT_COMPLETIONS_API_KEY` 均按大小写无关方式被剥离，普通安全环境变量仍被保留。
- 合法与非法 API mode、base URL、模式专用凭据组合的离线配置、CLI 和应用装配测试。
- 真实 `AgentRunner` + `ChatCompletionsModelClient` + fake SDK 的“文本—工具调用—工具结果—最终文本”测试。
- 连续两轮工具调用后最终文本测试。
- 单轮多个 tool calls 与多个 tool results 测试。
- 上下文压缩后继续调用模型测试。
- 逐请求验证 assistant/tool 合法顺序和精确 call ID 配对测试。
- 现有 `OpenAIResponsesClient` 和默认 Responses 模式回归测试。
- 文档模式、endpoint、兼容性和凭据隐私合同测试。

**建议的 Git 提交说明**

`feat: add compatible chat completions model client`

**当前状态**

`已完成`

## 16. Run instructions 与根工作区 AGENTS.md

**任务目标**

为每次 Agent 运行构建一次确定、不可变且供应商中立的指令快照，组合固定基础指令、工作区根 `AGENTS.md` 与可选的已选择 Skill 指令，并只注入主模型调用。

**涉及模块**

- `src/coding_agent/messages.py`
- `src/coding_agent/instructions.py`
- `src/coding_agent/agent.py`
- `src/coding_agent/app.py`
- 两个模型适配器及对应离线测试

**验收标准**

- `ModelRequest.instructions` 是可空、显式序列化且 repr 隐藏的字符串字段。
- 根 `AGENTS.md` 通过现有 `PathGuard` 读取，拒绝链接、junction 和 reparse point 逃逸。
- 文件和 Skill 指令分别执行 65,536 UTF-8 字节上限、严格 UTF-8 和稳定脱敏错误处理。
- 指令按基础、工作区、Skill 的固定顺序组合，同一输入产生相同文本和 SHA-256。
- 每次运行只构建一次快照；主调用保持该快照，摘要调用始终使用 `instructions=None`。
- Responses 和 Chat Completions 仅在非空时映射指令，空值保持既有请求形状。
- 指令正文不进入 JSONL、最终报告或异常表示。

**需要编写的测试**

- 消息 JSON 往返、非法值和 repr 隐私测试。
- 根文件缺失、空文件、BOM、UTF-8、精确字节上限、读取错误及 Windows reparse 安全测试。
- 确定性组合、根目录唯一加载、Skill 输入和快照散列测试。
- Agent 压缩前后主调用、摘要隔离、应用单次构建及两个 provider 映射测试。

**建议的 Git 提交说明**

`feat: add immutable run instructions`

**当前状态**

`已完成`

## 17. Provider-neutral streaming 核心

**任务目标**

在不改变既有 `ModelClient.complete` 协议的前提下，新增可选流式协议、安全生命周期事件和同一 logical call 内的共享预算回退。

**涉及模块**

- `src/coding_agent/model.py`
- `src/coding_agent/streaming.py`
- `src/coding_agent/agent.py`
- `tests/test_model.py`
- `tests/test_streaming.py`
- `tests/test_agent_loop.py`

**验收标准**

- 流式协议是可选能力，既有同步客户端和公共 `complete` 签名保持兼容。
- 只暴露文本 delta、完成和丢弃事件，不暴露 SDK 对象、工具参数片段或 continuation。
- 流式请求、结构化不支持后的同步回退共享一个 logical call 和同一个 provider attempt 预算。
- 只有首个 provider/text delta 前的结构化不支持可以回退；delta 后失败必须丢弃并稳定终止本次流。
- 回调异常、`KeyboardInterrupt` 和 `SystemExit` 不被吞掉，部分内容不进入 Agent 历史。
- `AgentRunner` 只在显式提供 handler 时流式执行主调用；摘要和现有 CLI 仍同步。

**需要编写的测试**

- 事件不变量、协议兼容和同步客户端回退测试。
- logical/provider 精确计数、预算边界和结构化不支持测试。
- 完成、丢弃、回调异常及 `BaseException` 传播测试。
- Agent 主调用流式、部分内容隔离、摘要同步和无 handler 回归测试。

**建议的 Git 提交说明**

`feat: add provider-neutral model streaming core`

**当前状态**

`已完成`

## 18. Responses 与 Chat Completions 流式适配

**任务目标**

在两个既有模型适配器内部解析真实 SDK 流，保留所有同步请求、重试、上下文和隐私合同，并返回既有完整 `ModelResponse`。

**涉及模块**

- `src/coding_agent/openai_client.py`
- `src/coding_agent/chat_completions_client.py`
- 两个 provider 的流式离线测试
- `DESIGN.md`
- `docs/OPENAI_API.md`
- `docs/USAGE.md`
- `tests/test_docs.py`

**验收标准**

- Responses 使用 `stream=True`、`store=False` 和本地历史，不发送 conversation 或 `previous_response_id`。
- Responses 严格解析允许的 SDK 事件、文本、函数参数片段、最终 usage/ID/工具调用和累计 SDK-free continuation。
- Chat Completions 使用完整本地历史，按连续 index 聚合文本和 function tool-call 片段，continuation 始终为空。
- 两个适配器只在首个 provider delta 前重试瞬时错误；delta 后不重试、不回退并丢弃临时文本。
- 每个真实请求领取 provider attempt，资源始终关闭，cleanup 错误不覆盖已有异常或 `BaseException`。
- 所有测试完全离线，不读取真实密钥，不泄漏请求正文、认证头、推理或 continuation。
- CLI 继续输出同步最终报告；SSE、GUI、会话控制器和 Skill 管理仍延期。

**需要编写的测试**

- 两个 provider 的精确请求映射、文本、单/多工具调用、混合响应、usage 和 ID 测试。
- Responses 完整事件序列、参数片段一致性、累计 continuation 和未知事件测试。
- Chat 工具 index、字段稳定性、完成原因、usage 和非法 chunk 测试。
- 瞬时/致命错误、重试次数、共享预算、关闭优先级、隐私和同步回归测试。
- 文档合同、全量离线回归、SDK 隔离、依赖、凭据和延期范围审计。

**建议的 Git 提交说明**

`feat: stream responses and chat completions models`

**当前状态**

`已完成`

## 19. 会话领域与 SQLite 持久化

**任务目标**

建立工作区本地的会话领域模型、SQLite 历史仓库和独占进程租约，使多个顺序 Agent run 能够持久保存安全叙事，同时不恢复或重放中断的执行状态。

**涉及模块**

- `src/coding_agent/session.py`
- `src/coding_agent/session_store.py`
- `tests/test_session.py`
- `tests/test_session_store.py`

**验收标准**

- 会话、运行、事件和终止结果使用严格、不可变、供应商中立的数据类型。
- 标题由第一条用户消息确定性生成，已知敏感值在持久化前脱敏。
- 数据库固定为工作区内 `.coding-agent/sessions.sqlite3`，schema 通过 `PRAGMA user_version` 管理。
- `.coding-agent`、数据库和锁路径拒绝 symlink、junction 和 reparse point。
- Windows 上使用真实非阻塞进程锁；同一工作区同时只能有一个控制器租约。
- 创建、顺序 follow-up、启动、取消、完成和恢复均使用原子事务。
- 数据库层和部分唯一索引共同保证整个工作区最多一个 queued、running 或 cancelling run。
- 进程重启只把未完成 run 稳定映射为 interrupted，不重新调用 Agent、模型、工具或验证。
- SQLite 只保存严格安全的报告投影，不保存完整 FinalReport 的 completion、failure、命令、stdout 或 stderr 证据。
- 默认测试完全离线，不新增依赖。

**需要编写的测试**

- 标题、ID、时间、枚举、记录不变量和 repr 隐私测试。
- 安全 run summary 与持久化报告投影 allowlist 测试。
- schema、WAL、外键、版本、损坏数据和事务回滚测试。
- 会话列表、run ordinal、event sequence 和 narrative 投影顺序测试。
- active-run 唯一约束和非法状态转换零副作用测试。
- Windows reparse point 和真实进程锁测试。
- 重启恢复不执行 Agent 的测试。

**建议的 Git 提交说明**

`feat: add durable workspace sessions`

**当前状态**

`已完成`

## 20. 单活动运行控制器与 GUI 安全事件桥

**任务目标**

在既有 AgentRunner 外增加框架无关的单活动运行控制器、顺序多轮会话、协作式取消和有界 UI 安全事件桥，为后续本地 GUI 提供稳定后端边界。

**涉及模块**

- `src/coding_agent/session_events.py`
- `src/coding_agent/session_runtime.py`
- `src/coding_agent/session_controller.py`
- `src/coding_agent/state.py`
- `src/coding_agent/agent.py`
- `src/coding_agent/logging.py`
- `src/coding_agent/app.py`
- 对应离线测试

**验收标准**

- 每个会话允许顺序提交消息，但每条消息创建全新的 Agent 状态、预算、验证和 continuation 生命周期。
- 旧会话只以一个确定性初始 UserMessage 进入新 run，不注入旧 tool call、ToolResult、call_id、provider payload 或 continuation。
- 同一控制器只有一个非 daemon worker，运行期间拒绝第二个任务且不建立任务队列。
- 取消使用令牌线性化和操作边界检查，不强杀线程；已准入操作可完成，后续操作不得准入。
- 取消后的未执行工具调用仍生成稳定配对的 rejected ToolResult。
- confirmed assistant text 可持久化；stream delta 只在内存中暂存，discard 后不得写入 SQLite。
- UI 更新使用严格供应商中立 schema、确定序号、有界条目和字节容量，并支持 replay、wait 和 reset-required。
- RunEventLogger 只在成功 flush 后通知观察器；持久化观察失败使控制器降级但不冒泡为模型错误。
- store、lease 和 executor 必须指向同一规范化工作区。
- CLI、模型 provider、安全策略、验证成功路径和 FinalReport 行为保持兼容。
- 不实现 HTTP/SSE、GUI、Skill、MCP、并行 Agent 或恢复执行。

**需要编写的测试**

- 初始历史渲染、上下文预算和 fresh-run 隔离测试。
- 事件 schema、隐私、序号、容量、replay 和 wait 测试。
- 模型、摘要、工具和验证边界的取消测试。
- 取消线性化、幂等取消、有限 shutdown 和线程启动失败测试。
- provisional/confirmed/discarded streaming 生命周期测试。
- observer、存储、finalization、重启恢复和 degraded 状态测试。
- CLI、provider、上下文、安全、验证、日志和报告全量回归测试。

**建议的 Git 提交说明**

`feat: add session run controller and event bridge`

**当前状态**

`已完成`

## 21. 声明式 Skill 目录与选择

**任务目标**

在后续独立设计和审批后，增加只读声明式 Skill 发现、显式选择、会话持久化和运行时不可变指令快照；本任务不属于当前 Task 19–20 实施范围。

**涉及模块**

- 待后续 brainstorming 和 writing-plans 锁定

**验收标准**

- 只加载受信本地目录中的声明式 Skill 文档。
- Skill 选择显式、确定并可持久化到会话。
- 每个 run 使用不可变 Skill 指令快照。
- Skill 不能绕过工具注册、安全策略、验证门或终止预算。
- 不在本任务内加入可执行插件、MCP、市场或远程下载。

**需要编写的测试**

- 后续批准计划将锁定发现、解析、选择、快照、隐私和安全回归测试。

**建议的 Git 提交说明**

`feat: add declarative skill catalog`

**当前状态**

`已完成`

## 22. 本地 FastAPI、REST 与 SSE 传输层

**任务目标**

以经过认证的 loopback FastAPI 边界暴露现有 SessionController、SessionEventHub 和声明式 Skill 能力，不改变 Agent、会话或安全语义。

**涉及模块**

- `src/coding_agent/web_auth.py`
- `src/coding_agent/web.py`
- `src/coding_agent/web_cli.py`
- Web 传输层离线测试

**验收标准**

- 只绑定 IPv4 `127.0.0.1`，默认使用系统分配端口。
- REST 和 SSE 均要求进程级 Bearer token、严格 Host 与 Origin 检查。
- 所有业务操作委托给现有 SessionController；不增加运行队列或第二套状态机。
- SSE 保持既有安全事件顺序、游标、重放、等待和 reset-required 语义。
- HTTP 错误、日志和对象表示不泄漏凭据、路径、异常正文、Skill 指令或 provider 数据。
- Task 1-21 行为保持，测试不调用真实外部 API。

**需要编写的测试**

- token、Host、Origin、重复 header 和脱敏测试。
- 严格 DTO、请求体上限、REST 映射和稳定错误测试。
- SSE 顺序、heartbeat、重放、reset、断连、终止和连接上限测试。
- Web CLI、loopback socket、随机端口、资源关闭和安装入口测试。

**建议的 Git 提交说明**

`feat: add authenticated local web transport`

**当前状态**

`已完成`

## 23. 本地静态 GUI

**任务目标**

在 Task 22 同源服务中增加无构建步骤的暖色浅色 GUI，展示持久会话、流式 Agent 状态、Skill 选择、取消与验证结果。

**涉及模块**

- `src/coding_agent/web_static/index.html`
- `src/coding_agent/web_static/app.js`
- `src/coding_agent/web_static/styles.css`
- GUI 资源、安全、交互合同和打包测试

**验收标准**

- 左侧会话列表、中间大对话区、顶部运行状态与耗时、底部输入框符合批准设计。
- 使用 fetch Bearer SSE；token 只在页面内存中存在。
- 可新建会话、提交 follow-up、选择 Skill、取消 run，并恢复 SSE 游标。
- 模型文本不经过不安全 HTML sink；不加载远程脚本、样式、字体或图像。
- GUI 不伪造 SUCCESS，不把浏览器断开映射为 Agent 取消。
- 静态资源随 wheel 安装，现有 CLI 和 Task 1-22 全部回归通过。

**需要编写的测试**

- HTML/CSS/JS 结构、CSP、token bootstrap 和禁止模式测试。
- API 路径、Bearer、SSE 游标、重连、reset 和终止合同测试。
- wheel 资源、安装入口、响应 header 和无外部资源测试。
- 离线视觉 fixture 和人工多尺寸状态验收。

**建议的 Git 提交说明**

`feat: add local coding agent web interface`

**当前状态**

`已完成`

## 24. Run 投影、自适应上下文与 Java 黑盒验证

**任务目标**

按批准设计只显示每个 Run 的最终助手回复，使上下文压缩在硬预算下动态缩减保留 turn，并新增受控 `run_java_tests` Java 编译与输入输出验证工具。

**涉及模块**

- `src/coding_agent/web_static/app.js`
- `src/coding_agent/context.py`
- `src/coding_agent/safety.py`
- `src/coding_agent/tools/shell.py`
- `src/coding_agent/tools/java.py`
- `src/coding_agent/verification.py`
- `src/coding_agent/app.py`
- 对应 Python、Node、集成和文档测试

**验收标准**

- 活跃 Run 只有一张临时状态卡，成功 Run 只显示最后回复，失败或中断 Run 不显示过程叙述。
- 超过硬预算时动态移除最旧完整 turn，至少保留最新完整 turn，最多调用一次摘要模型，并在压缩后清空 continuation。
- `run_java_tests` 使用 strict schema、PathGuard、可信系统 JDK、`shell=False`、固定工作区、受限环境、稳定发现、全局超时和有界输出。
- Java 黑盒用例按 `.in`/`.out` 成对执行，只归一化换行后精确比较；完整通过可形成当前 mutation 的可信验证证据。
- `run_command` 白名单、用户强制 `--verify`、现有 Python 验证、provider、会话、安全、日志和最终报告行为保持兼容。
- 默认测试完全离线，不读取真实密钥；真实 JDK 冒烟在本机实际执行并单独报告。

**需要编写的测试**

- GUI run_id 投影、实时状态、成功、失败、中断和重载测试。
- 上下文硬项数回归、扩展删除、工具配对、单次摘要、fallback 和 continuation 测试。
- Java schema、路径、runtime、发现、编译、用例、输出、超时、清理和环境隔离测试。
- Java 验证新鲜度、强制命令优先级、Agent 集成和完整回归测试。

**建议的 Git 提交说明**

`feat: add adaptive context and java verification`

**当前状态**

`已完成`

## 25. 显式修改与只读问答运行模式

**任务目标**

增加逐 run 显式 `modify`/`read_only` 能力边界，使工作区读取与项目介绍可以在不修改、不验证时以 `ANSWERED` 正常结束，同时保持修改任务只能凭最后一次修改后的新鲜验证进入 `SUCCESS`。

**涉及模块**

- `run_mode.py`、配置、指令、Agent 状态机、审计和最终报告
- 命令安全策略、`inspect_git` 与按模式构建的 `ToolRegistry`
- Session、SQLite 迁移、Controller、REST、SSE、CLI 和本地 GUI
- 离线单元、集成、Windows 专项和文档合同测试

**验收标准**

- 模式由用户逐 run 显式选择，默认 `modify`，不能根据提示词推断。
- `modify` 精确保留现有六个工具；`read_only` 只暴露 `list_directory`、`read_file` 和 `inspect_git`。
- `inspect_git` 只能复用既有安全语法执行本地只读 Git 子命令，不能运行工作区代码或 Git 写操作。
- 合法只读最终文本进入 `ANSWERED`、退出码为 `0`；任何修改事实都使该终态成为内部不变量错误。
- `SUCCESS` 仍只允许具有新鲜通过验证证据的修改运行。
- 模式和 `answered` 语义贯通 SQLite、REST/SSE、最终报告、CLI 和 GUI，并兼容历史会话迁移。
- 默认测试完全离线，不读取真实凭据，不新增依赖或 Agent 框架。

**需要编写的测试**

- 模式枚举、配置、指令、状态机、报告和审计严格 schema 测试。
- `inspect_git` 允许/拒绝矩阵与按模式 Registry 组合测试。
- SQLite v2→v3、报告 v1→v2 原子迁移和生命周期持久化测试。
- Controller、REST、SSE、CLI、GUI 与同一会话切换模式测试。
- 项目读取与介绍不再耗尽逻辑模型调用预算的离线集成测试。
- Task1—Task24、Windows reparse point、超时与进程树完整回归测试。

**建议的 Git 提交说明**

`feat: add explicit read-only run mode`

**当前状态**

`已完成`

## 26. 自适应 Agent 收敛与分层预算

**任务目标**

在不引入 Planner、Agent 框架或新依赖的前提下，增加 `standard`/`deep` 分层预算、轻量阶段、确定性进度账本、决策检查点、上下文高低水位和运行级摘要熔断；再以运行级探索账本、重复回合产出优先握手、Standard 1 / Deep 2 个普通最终只读批次、精确命令纠正和 `changes_unverified` 终态，让复杂任务在保留安全边界的同时收敛到修改、验证或准确失败。

**涉及模块**

- 新增 `src/coding_agent/budget.py` 和 `src/coding_agent/progress.py`
- `model.py`、`context.py`、`termination.py`、`state.py` 和 `agent.py`
- 配置、CLI、composition root、日志、报告和项目开发指导
- 模型指令、`run_command` schema、修改新鲜度派生状态和未验证终止投影
- Session、SQLite 迁移、Controller、REST、SSE 和本地 GUI
- 对应单元、组件、集成、Node GUI、Windows 专项和文档合同测试
- `DESIGN.md`、`AGENTS.md`、`README.md`、`README.txt` 和 `docs/USAGE.md`

**验收标准**

- `BudgetProfile` 只接受 `standard` 与 `deep`，默认 `standard`，逐 run 不可变并完整贯通 CLI、Web、Session、SQLite、审计和最终报告；历史 run 缺少 profile 时确定性迁移为 `standard`。
- `standard` 精确限制为 24 次主逻辑调用、4 次摘要逻辑调用、48 次全局 provider 请求、8 次摘要 provider 请求、80 次工具调用和 20 分钟；`deep` 精确限制为 40、6、80、12、140 和 30 分钟。
- 主调用、摘要调用和真实 provider attempt 分别计数；摘要调用不消耗主逻辑额度，摘要 provider 子额度不能突破全局上限，所有限制阻止第一个不允许的操作且计数器永不越界。
- 配置了强制验证且存在待验证修改时，最后 1 次工具额度只允许现有 `VerificationGate` 使用；其他运行不错误预留。
- 上下文在 48,000 字符或 20 项达到高水位时触发压缩，并压到不高于 33,000 字符且不高于 12 项；60,000 字符和 24 项继续作为硬上限。
- 压缩只移除完整工具 turn，保留初始目标，不产生孤立 `ToolResult`；成功替换历史时清空活动 continuation，摘要请求和摘要结果均不保留 continuation。
- 摘要解析接受裸 JSON 或外围仅含空白的单一 `json` 代码围栏，仍严格校验完整字段和类型；fallback 在摘要字符上限内按首次出现顺序保留尽可能多的去重安全相对目标，不复制成功工具正文。
- 每个 run 的第一次普通摘要错误、非法结构或摘要子预算耗尽立即使用本地确定性 fallback，并锁定后续压缩为本地摘要；新 run 重新允许模型摘要。致命错误、全局 provider 预算、内部不变量和 `BaseException` 不降级。
- 摘要和事件不包含宿主机绝对工作区路径、摘要正文、continuation、provider payload、凭据或异常正文。
- `ProgressLedger` 确定地区分弱进展、强进展和无进展；`standard` 使用 4 次主调用、12 次只读工具、2 次完全无新信息和检查点后 2 次主响应阈值，`deep` 使用 6、24、3 和 3。
- 运行级 `ExplorationLedger` 保存安全相对目标、请求/结果指纹、状态和 mutation epoch，不保存正文且不持久化；压缩不清空它，模型只在压缩后或检查点期间看到字符受限的安全 coverage。
- Agent 阶段只根据真实本地行为转换；阶段不能扩大 `RunMode` 权限，`FINISH` 不能绕过 `VerificationGate`，摘要成功不能重置主模型连续错误。
- 决策检查点通过临时运行 instructions 注入，不伪装成用户消息、不产生额外 Assistant 气泡、不持久化隐藏控制内容；检查点后的持续探索以 `no_progress` 稳定终止。
- 普通检查点后的最终只读响应批次精确为 Standard 1 / Deep 2，并按尝试读取的模型响应计数；整轮只有重复读取时直接进入 `decision_required`，不再获得最终读取批次。
- `decision_required` 后第一次无强进展必须把配对反馈交给模型并保证一次纠正响应；第二次仍无行动时以 `no_progress` 终止且不额外调用模型，同批次合法修改仍可执行。
- 模型可见指令与 `RunCommandTool` schema 明确列出可信 Python/pytest/unittest 和专用 Java 验证形式；命令安全拒绝提供脱敏纠正，但拒绝且不自动改写或执行命令。
- 用户提供 `--verify` 或已有验证失败时，最后一次修改缺少新鲜通过证据仍只能以 `changes_unverified`、`FAILED` 和退出码 `1` 结束；没有强制命令和失败证据时，可对精确修改路径执行一次本地完整性验证，只有生成当前 mutation 的新鲜通过证据后才能进入 `SUCCESS`。
- `RunMode.MODIFY` 是能力边界而不是意图分类；零修改、零验证且包含非空最终文本的运行可进入 `ANSWERED`，但不得声称修改或验证成功。
- Chat `length` 与 Responses `incomplete/max_output_tokens` 映射为 provider-neutral 输出上限错误；第一次只注入临时的小步/单文件纠正，第二次在第三个请求前稳定终止，其他已完成但损坏的响应不进行三次盲重试。
- 多工具批次中途终止继续生成配对的未执行拒绝结果；流式、取消、Task8 安全、Task11 验证、两个 provider、Skill 和 follow-up 既有行为保持兼容。
- GUI 可选择标准/深度档位，并安全显示阶段、分项预算、压缩来源和决策检查点；不恢复大量工具卡片或泄漏敏感数据。
- 默认测试完全离线，不读取真实密钥、不访问网络、不新增依赖或 Agent 框架。

**需要编写的测试**

- profile 枚举、不可变参数、配置、CLI 和精确边界测试。
- 主/摘要 logical call、全局/摘要 provider attempt、工具与验证保留额度的等号和越界测试。
- 高低水位、完整 turn、可移除最后完成 turn、fallback 熔断、相同输入确定性、相对路径隐私和 continuation 生命周期测试。
- 裸 JSON、单一 JSON 围栏、围栏外正文、多对象、缺失字段、fallback 路径容量和正文排除测试。
- 弱进展、强进展、不同读取的持续探索、精确重复、检查点恢复、检查点后终止和 fake clock 测试。
- 探索账本 mutation epoch、压缩保持、有界 coverage、整轮重复判定、响应级读取计数和两阶段决策握手测试。
- Agent 阶段、动态 instructions、只读完成、修改验证、错误重置、多工具批次和取消测试。
- JSONL schema、FinalReport、Session schema 迁移、生命周期持久化、REST/SSE 和 GUI 投影测试。
- FakeModelClient 驱动的只读项目介绍、创建 README、摘要非法后继续、复杂调查进入修改和最终验证场景。
- 真实形态 README fixture：每轮 4–5 个读取、触发压缩、重复读取、配对拒绝、单次纠正写入和新鲜验证，并断言重复执行批次受到确定上限约束。
- Standard/Deep 最终只读等号边界、额外读取配对拒绝、多文件批次继续修改和 `decision_required` 日志测试。
- 真实本地 Python 脚本的命令拒绝—合法修正—新鲜验证，以及三次拒绝后 `changes_unverified` 保留文件的离线集成测试。
- `changes_unverified` 的 FinalReport、JSONL、Session/SSE 安全投影和 GUI 重载终态卡片测试。
- Task1—Task25、两个 provider、Windows reparse point、timeout 和进程树完整回归测试。
- 依赖、凭据、绝对路径、continuation、占位符、skip/xfail、Agent 框架和 `git diff --check` 审计。

**建议的 Git 提交说明**

`feat: add adaptive agent convergence and layered budgets`

**当前状态**

`已完成`

## 27. 当前工作区声明式 Skill zip 导入

**任务目标**

在不增加生产依赖、不扩大 Agent 权限且不改变 Task21 选择与注入语义的前提下，为本地 GUI 增加单个纯声明式 Skill zip 的安全导入。导入只写入当前工作区 `.coding-agent/skills/`，只接受一个 `<skill-id>/SKILL.md`，并使用共享解析、受限 archive grammar、暂存写入和原子发布。

**涉及模块**

- 新增 `src/coding_agent/skill_packages.py`
- `src/coding_agent/skills.py`
- `src/coding_agent/session_controller.py`
- `src/coding_agent/web.py`
- `src/coding_agent/web_static/index.html`
- `src/coding_agent/web_static/app.js`
- `src/coding_agent/web_static/styles.css`
- 对应 Skill、Controller、REST、GUI 和文档测试

**验收标准**

- GUI 只上传一个 `.zip`，Web 使用有 131,072 字节上限的原始 `application/zip` 请求体，不使用 multipart 或新增依赖。
- archive 只允许一个合法 Skill 目录和一个 `SKILL.md`；拒绝额外文件、嵌套目录、重复成员、危险路径、reparse/symlink 属性、加密、异常压缩、损坏内容和解压后超限。
- 实现不调用 archive-wide extraction；只对唯一验证成员进行 65,537 字节有界读取并写入新的本地 `SKILL.md`。
- 手动目录发现和 zip 导入复用同一个 bytes 解析器，Task21 的格式、哈希、诊断、隐私和选择行为保持不变。
- 安装使用 Skill 根目录内随机暂存、独占文件创建和同目录原子重命名；同名 Skill 及并发竞争拒绝覆盖。
- 只安装到当前工作区；不支持用户级安装、更新、覆盖、编辑、卸载、远程下载、市场、资源文件、脚本或可执行 Skill。
- 活动 run、Controller busy/closed/degraded 或不可用 catalog 时拒绝导入。
- GUI 提供导入按钮、空目录说明、有界状态和稳定错误；成功后刷新并为草稿或空闲会话自动选择新 Skill。
- REST、GUI、错误、日志和 repr 不暴露 archive bytes、Skill 正文、绝对路径、暂存名或 OS 异常。
- 默认测试完全离线，不读取真实密钥、不访问网络、不新增 Agent 框架或依赖。

**需要编写的测试**

- 合法 stored/deflated zip、目录成员可选、raw/uncompressed 等号边界和共享解析等价测试。
- traversal、绝对路径、盘符、ADS、反斜杠、点/空段、控制字符、重复规范名、extra/nested/multiple member 测试。
- encrypted、unsupported compression、symlink/non-regular 属性、CRC、截断、损坏、超限和压缩炸弹形态测试。
- catalog 创建、unsafe root、同名、rename race、独占写、暂存清理、发布后发现失败和 Controller admission 测试。
- application/zip、Content-Encoding、Bearer、Host、Origin、body cap、状态映射、GUI 上传/刷新/自动选择/禁用和打包资源测试。
- Task21、Session、Web、GUI、安全和完整离线回归测试。

**建议的 Git 提交说明**

`feat: import declarative workspace skills from zip`

**当前状态**

`已完成`

## 28. 逐条删除会话及精确审计日志

**任务目标**

为本地 GUI 增加带标题二次确认的逐条会话删除，并安全删除该会话的 SQLite 关系数据、内存事件投影和由持久化 `audit_run_id` 精确派生的 JSONL；使用可逆日志暂存和启动恢复协调 SQLite 与文件系统，绝不扩展为 Agent 删除工具或任意文件删除。

**涉及模块**

- 新增 `src/coding_agent/session_deletion.py`
- `src/coding_agent/session_store.py`
- `src/coding_agent/session_events.py`
- `src/coding_agent/session_controller.py`
- `src/coding_agent/web.py`
- `src/coding_agent/web_static/index.html`
- `src/coding_agent/web_static/app.js`
- `src/coding_agent/web_static/styles.css`
- 对应 Store、删除恢复、Controller、REST、GUI 和文档测试

**验收标准**

- 只允许用户逐条删除空闲会话；不提供批量删除，活动 run 或 Controller busy/closed/degraded 时拒绝。
- Store 产生只含 session ID、稳定顺序 run ID 和非空 audit run ID 的不可变 manifest；删除事务必须重新读取并精确匹配 manifest。
- SQLite 在 `BEGIN IMMEDIATE` 中按 `session_events`、`run_skill_snapshots`、`session_runs`、`session_skill_selections`、`sessions` 顺序显式删除并校验行数；任一失败完整回滚。
- 日志目标只能由通过现有 ID grammar 校验的 `audit_run_id` 构造为 `.coding-agent/logs/<id>.jsonl`；禁止使用数据库路径文本、用户路径、glob 或宽范围枚举。
- 删除前对工作区、内部目录、日志、暂存和目标执行规范化、边界与 reparse 检查；缺失日志视为已经不存在，异常类型和不安全路径在数据库删除前拒绝。
- 日志先移动到带有界安全 manifest 的精确暂存目录；数据库失败时无覆盖恢复，提交成功后清理暂存。最终清理失败返回 `cleanup_pending` 并由启动恢复继续。
- 启动恢复根据会话是否仍存在决定恢复或清理；空且无 manifest 的合法操作目录可清除，畸形 manifest、目标冲突或不安全路径 fail closed。
- 删除后清除匹配的 SessionEventHub 完成态投影，使已删除 run 不再通过 SSE 读取；无关内存状态保持。
- GUI 删除控制独立于会话选择，确认文案包含安全纯文本标题；取消不发请求，成功后按下一项、上一项、空白页规则稳定选择。
- `cleanup_pending` 明确提示日志将在启动时重试；错误和响应不泄漏绝对路径、日志内容、暂存名或 OS 异常。
- 不删除无关 JSONL、数据库/WAL、Skill、工作区文件或内部目录，不声称跨 SQLite/NTFS 的真实原子事务。

**需要编写的测试**

- manifest 稳定性、stale 拒绝、完整关系删除、其他会话不变、行数校验、SQLite 回滚、busy/active/missing 测试。
- 精确日志派生、缺失日志、无关日志保留、reparse/non-regular 拒绝和无 glob/数据库路径信任测试。
- 暂存、数据库失败恢复、提交后清理、cleanup pending、恢复不覆盖，以及各崩溃窗口的启动恢复测试。
- 畸形 manifest、unsafe staging、目标冲突、空 orphan 目录和 Controller degraded 测试。
- EventHub forget、SSE 已删除 run、REST DELETE、认证、状态映射、GUI 确认/取消/选中/未选中/最后会话/失败/待清理测试。
- Task19—Task27、日志、Session、Web、GUI、Windows reparse point 和完整离线回归测试。

**建议的 Git 提交说明**

`feat: delete local sessions and exact audit logs`

**当前状态**

`已完成`

## 任务完成规则

每项任务只有在以下条件同时满足时才能标记为 `已完成`：

- 验收标准全部满足。
- 规定的测试已经实际执行并通过。
- 测试命令和真实结果已报告。
- 没有引入禁止的 Agent 框架、托管工具或未批准依赖。
- 没有削弱安全限制或验证门槛。
- 没有修改无关文件。
- 核心模块完成后已经按项目工作流请求代码审查。

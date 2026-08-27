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

`进行中`

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

`未开始`

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

`未开始`

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

`未开始`

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

`未开始`

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

`未开始`

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

`未开始`

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

`未开始`

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

`未开始`

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

`未开始`

## 14. README、视频和提交物检查

**任务目标**

完成公开仓库说明、考核用 `README.txt`、两分钟演示视频和最终 ZIP 检查，确保满足题目提交规则且不泄露凭据。

**涉及模块**

- `README.md`
- `README.txt`
- 演示脚本或拍摄清单文档
- 最终 MP4 和提交 ZIP，仅在发布阶段生成

**验收标准**

- 公开仓库为题目发布后新建，保留完整提交历史。
- `README.md` 说明架构、运行、限制、测试和安全边界。
- `README.txt` 不超过 1000 汉字，包含仓库地址、运行方法、特色功能和必要说明。
- 视频不超过 2 分钟，MP4 格式且不超过 200 MB。
- 视频展示真实失败测试修复，并简要解释主循环、验证门槛和上下文压缩。
- 仓库、文档、Git 历史、日志、截图和视频均不包含 API Key。
- 最终 ZIP 使用本人姓名命名，且只包含 `README.txt` 和视频文件。
- 截止时间为 2026 年 9 月 2 日 24:00 北京时间；截止后不再推送提交。
- 推送远程仓库必须由用户明确授权，Codex 不自动推送。

**需要编写的测试**

- 全量自动测试和演示命令实际运行。
- 凭据模式扫描。
- `README.txt` 汉字长度检查。
- 视频格式、时长和文件大小检查。
- ZIP 文件名及内容清单检查。
- Git 状态、远程地址和提交历史人工复核。
- 记录所有实际执行命令和真实结果，不声称未执行的检查。

**建议的 Git 提交说明**

`docs: finalize readme demo and submission checklist`

**当前状态**

`未开始`

## 任务完成规则

每项任务只有在以下条件同时满足时才能标记为 `已完成`：

- 验收标准全部满足。
- 规定的测试已经实际执行并通过。
- 测试命令和真实结果已报告。
- 没有引入禁止的 Agent 框架、托管工具或未批准依赖。
- 没有削弱安全限制或验证门槛。
- 没有修改无关文件。
- 核心模块完成后已经按项目工作流请求代码审查。

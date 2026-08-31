# MiniCodex 使用说明

MiniCodex 是本地 Coding Agent，提供一次性 CLI 和同源 Web GUI。每个 run 都显式选择 `modify`（允许修改）或 `read_only`（只读问答）；模式不会从提示词推断。修改模式可在用户指定的工作区内读取和修改 UTF-8 文本、执行受控命令，并由本地验证门决定任务是否成功；只读模式只检查项目并返回答案。模型层默认使用 OpenAI Responses，也可显式选择 compatible Chat Completions。项目入口见[仓库首页](../README.md)，模型接入细节见 [API 说明](OPENAI_API.md)。

## 功能与适用场景

适合在可信、可丢弃的 Python 或简单 Java 项目副本中检查代码、进行确定性文本修改、运行测试并根据失败结果继续修复。Agent 主循环、消息历史、上下文压缩、工具分派、路径与命令策略、终止条件、验证新鲜度、JSONL 日志和 FinalReport 都由本项目本地实现。

Web GUI 提供本地会话持久化、会话切换、follow-up、声明式 Skill 选择、运行状态、流式文本、安全活动卡和协作式取消。首版不提供多 Agent、任意 Shell、网络下载、包安装、文件删除、Git 写入或自动推送。

## 已验证环境与系统要求

- Windows 优先；当前版本不承诺 Linux 或 macOS 支持。
- Python 3.11+。
- Java 黑盒验证需要 Windows PATH 中可用的可信 `javac.exe` 和 `java.exe`；工具不会下载 JDK。
- 生产依赖为官方 `openai` Python 包、FastAPI 和 Uvicorn；测试依赖为 pytest 与 HTTPX。
- 默认自动测试完全离线，不需要真实 API key，也不会探测 endpoint。

## Windows PowerShell 安装

在仓库根目录执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
coding-agent --help
coding-agent-web --help
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
| `--read-only` | 否 | 选择 `read_only` 只读问答；默认不提供时使用 `modify`。 |
| `--budget-profile` | 否 | 运行预算：`standard`（默认）或 `deep`；创建 run 后不可改变。 |
| `--model` | 否 | 模型 ID；覆盖 `OPENAI_MODEL`。 |
| `--api-mode` | 否 | 只接受 `responses` 或 `chat-completions`；默认 `responses`。 |
| `--base-url` | 仅 Chat | compatible Chat Completions 的绝对 HTTPS API 前缀。 |
| `-h` / `--help` | 否 | 显示帮助并退出。 |

`responses + --base-url` 是非法配置，不会静默忽略；`chat-completions` 必须提供 `--base-url`。`--read-only` 与任何 `--verify` 组合会在启动前被拒绝，因为只读模式不会运行 `--verify`。当前解析器没有交互模式、fake 模式或恢复会话参数。

## 最小运行示例

```powershell
coding-agent "修复失败测试" --workspace . --api-mode responses --model '<openai-model-id>' --verify "pytest -q"

coding-agent "分析较大的项目" --workspace . --budget-profile deep --api-mode responses --model '<openai-model-id>' --verify "pytest -q"

coding-agent "修复失败测试" --workspace . --api-mode chat-completions --base-url '<https-provider-base-url-with-api-prefix>' --model '<compatible-model-id>' --verify "pytest -q"

coding-agent "读取项目并介绍其用途" --workspace . --read-only --api-mode responses --model '<openai-model-id>'
```

`responses` 可省略 `--api-mode`。未提供 `--verify` 时，模型可通过 `run_command` 产生可信验证证据，或通过 `run_java_tests` 产生新鲜且内部一致的 Java verification 证据；若没有执行这些验证，完成候选会触发内建文件完整性检查。目录查看、echo 和 `git status` 不能成为成功证据。

简单 Java 标准输入输出项目可省略 Python 验证命令：

```powershell
coding-agent "修复 Java 程序并运行 tests 中的输入输出用例" --workspace . --api-mode responses --model '<openai-model-id>'
```

Java 项目不要附加无关的 `--verify "pytest -q"`；用户一旦提供 `--verify`，该命令仍是不可替代的强制最终门槛。

## 本地 Web GUI

通用形式是 `coding-agent-web --workspace <path>`。例如使用默认 Responses mode：

```powershell
coding-agent-web --workspace . --model '<openai-model-id>' --verify "pytest -q"
```

compatible Chat Completions 仍需显式 mode、HTTPS API 前缀和对应凭据：

```powershell
coding-agent-web --workspace . --api-mode chat-completions --base-url '<https-provider-base-url-with-api-prefix>' --model '<compatible-model-id>' --verify "pytest -q"
```

服务只绑定 IPv4 `127.0.0.1`，默认使用系统分配的随机端口，监听成功后才打开浏览器。传 `--no-open-browser` 可只输出本地 URL。页面、REST 和 fetch-SSE 使用同一进程级 Bearer token，并执行严格 Host 与 Origin 检查；token 不进入 URL、持久存储或日志。它不是远程服务，不应通过端口转发、代理或网络共享暴露。

左侧可新建和切换持久会话；空闲会话可提交 follow-up，并为下一次运行选择有序的声明式 Skill。发送前的紧凑选择器提供“允许修改”和“只读问答”，以及 `standard`（标准）和 `deep`（深入）预算。两个选择值只对当前提交生效并在运行期间锁定；同一会话的每条消息可以重新选择模式和预算。页面刷新后选择器恢复默认的允许修改和标准预算，不使用浏览器持久存储猜测权限。历史消息旁的模式与 profile 标记来自持久化 run 记录。

Skill 选择器只显示可用 Skill 的名称、描述和来源；发现诊断不在 GUI 中展示，指令正文也不会显示，GUI 不执行 Skill，Skill 也不能扩展所选模式的工具权限。全局一次只运行一个 Agent；运行或取消期间，历史仍可浏览，但发送和 Skill 修改会禁用。取消按钮只请求既有协作式取消，关闭浏览器不会取消正在运行的 Agent，重新打开页面会从持久快照和 SSE 游标恢复。页面通过服务器终态显示成功、已回答或失败，不根据浏览器断开伪造结果。

空闲时可点击“导入 Skill ZIP”，选择一个本机 `.zip`。它只安装到当前工作区的 `.coding-agent/skills/`，包内必须恰好包含一个 `<skill-id>/SKILL.md`；归档不得超过 128 KiB，`SKILL.md` 不得超过 65,536 字节。导入不会覆盖任何同 ID 的用户或工作区 Skill，不接受可执行内容、符号链接或额外文件；运行期间导入按钮禁用。成功导入后，新 Skill 会加入草稿选择；若当前选中空闲会话，也会通过既有会话选择接口保存。该功能不联网、不执行 Skill，也不会扩大 Agent 权限。

会话列表中的删除按钮只支持逐条删除空闲会话，并以该会话的安全纯文本标题二次确认；不支持批量删除，活动 run、取消过程或 Controller 忙碌时均拒绝。删除成功后会移除该会话的 SQLite 关系数据、内存事件投影，以及由持久化 audit ID 精确派生的 `.coding-agent/logs/<audit_run_id>.jsonl`，不会扫描或删除无关日志。响应中的 `cleanup_pending` 表示数据库删除已完成，但暂存日志将在下次启动恢复时继续清理。会话删除是认证后的本地 GUI/REST 控制面操作，不是 Agent 工具，也不会删除任意工作区文件、Skill、数据库或 WAL。

本地 GUI 不提供账户，不支持 MCP，不支持并行运行，也不允许远程使用。浏览器启动失败只产生固定警告，服务仍继续运行。

## 推荐的安全运行示例

在已备份的项目副本中固定验证命令：

```powershell
coding-agent "修复当前项目中的失败测试" --workspace . --api-mode responses --model '<openai-model-id>' --verify "pytest -q"
```

`--verify "pytest -q"` 在启动阶段授权。每个完成候选都会在工具和时间预算允许时执行这条固定命令；非零退出码会回流给模型继续修复，而不会被当作成功。

## Agent 运行流程

`RunMode` 与 `BudgetProfile` 是正交且不可变的 run 属性：前者限定工具权限，后者限定资源；二者都不会由模型提示词推断。`standard` 最多允许 24 次 main model call、4 次 summary call、48 次 provider attempt（其中 summary 最多 8 次）、80 次工具调用和 20 分钟；`deep` 对应 40、6、80（summary 最多 12）、140 和 30 分钟。它们是“阻止下一次不允许操作”的硬上限，不是承诺用完的配额。

进度状态按 `AgentPhase` 的 `DISCOVER`、`ACT`、`VERIFY`、`FINISH` 演进，与终态 `AgentStatus`（例如 `ANSWERED`、`SUCCESS`、`FAILED`）分开。读取和检查属于弱进展，修改与新鲜验证属于强进展。运行级 `ExplorationLedger`（探索账本）仅保留安全的工作区相对目标标签、请求/结果哈希、状态和修改 epoch；它不保存文件正文、provider continuation 或凭据，也不是跨会话的长期记忆。达到探索阈值时先注入一次确定性的决策 checkpoint；checkpoint 后仍持续探索才以 `no_progress` 终止。上下文压缩优先请求一次结构化摘要，清除旧 provider continuation，并在后续请求中临时提供有界探索覆盖；摘要模型错误、非法摘要或摘要专用预算耗尽会为当前 run 锁定本地 fallback，后续压缩不再调用摘要模型。

普通 checkpoint 后的最终只读额度是 **Standard 1 / Deep 2** 个尝试读取的模型响应批次；一个响应中的多个读取只算一批，失败或被拒绝的读取也不能产生无限额度。整批读取均为已见过的相同结果时会立即进入 `decision_required`，不再获得普通最终读取额度。之后的读取会得到配对拒绝而不执行，同一响应中的合法修改仍可继续；第一次决策响应仍无强进展时，仅在更高优先级硬预算允许下再提供一次纠正响应，第二次仍无进展则以 `no_progress` 停止。被安全策略拒绝的验证命令只收到固定、脱敏的合法形式提示：本地 Python 脚本、`python -m pytest ...`、`python -m unittest ...`，Java 使用 `run_java_tests`。策略会拒绝但不自动改写或代替模型执行命令。

1. CLI 在联网前校验任务、工作区、运行模式、API mode、base URL、模式专用凭据、模型和可选验证命令。
2. composition root 根据显式运行模式构造精确工具注册表；修改模式还构造共享命令执行器和验证门，两种模式共享所选模型适配器、上下文管理器、终止策略和事件日志器。
3. 启动时只读取一次根 `AGENTS.md`，与内置基础规则组合成不可变运行指令；Agent 根据该指令和本地历史请求模型。超过字符或历史项阈值时生成结构化摘要，失败则使用确定性 fallback，摘要不会继承运行指令。
4. 工具调用按响应顺序进行本地校验、授权、执行和观察，结果通过 `call_id` 配对写回历史。
5. 文件修改增加 mutation index，并使旧验证状态失效。
6. 存在修改时，`modify` 的完成候选只有在本地验证门接受新鲜证据后才能成为 `SUCCESS`；零修改、零验证的非空最终回答在 `modify` 或 `read_only` 下都成为 `ANSWERED`。
7. 预算耗尽、重复无进展、安全拒绝或不可恢复错误产生稳定失败原因。

两个模型适配器内部都支持 provider-neutral 文本流事件，以及首个 delta 前的结构化同步回退。**CLI 仍使用同步最终报告**，不会逐 token 显示内容；Web GUI 通过经过认证的 fetch-SSE 投影安全事件。部分输出仅驻留内存；中断后不会写入消息历史、JSONL 或 FinalReport。

## 按运行模式划分的本地工具

### 允许修改（`modify`）

| 工具 | 能力与主要限制 |
| --- | --- |
| `list_directory` | 稳定排序列举；递归深度 1–3，最多 500 项。 |
| `read_file` | 带真实行号读取 UTF-8 文本；单次最多 256 KiB。 |
| `replace_text` | 仅在实际匹配数等于 expected count 时执行精确替换。 |
| `write_file` | 只创建不存在的新 UTF-8 文件，不覆盖且不创建父目录。 |
| `run_command` | 参数数组、`shell=False`、固定 cwd、超时与双流 64 KiB 上限。 |
| `run_java_tests` | 使用可信本机 JDK 编译源码并运行成对 `.in`/`.out` 黑盒用例。 |

### 只读问答（`read_only`）

| 工具 | 能力与主要限制 |
| --- | --- |
| `list_directory` | 稳定排序列举；递归深度 1–3，最多 500 项。 |
| `read_file` | 带真实行号读取 UTF-8 文本；单次最多 256 KiB。 |
| `inspect_git` | 只检查本地 Git；仅允许 `status`、`diff`、`log`、`show` 和 `ls-files`。 |

只读注册表不包含 `replace_text`、`write_file`、`run_command` 或 `run_java_tests`，也不会构造验证执行路径。`inspect_git` 不能访问远程、运行工作区代码或执行任何 Git 写操作；命令仍通过原生 Windows 参数解析、可信启动器、固定 cwd、`shell=False`、超时和有界输出执行。

`run_java_tests` 的 strict schema 是 `source_root`、`main_class`、`tests_directory` 和 `purpose`；`purpose` 只能是 `test` 或 `verification`。源码与 fixture 根目录都必须是工作区相对路径。最多发现 500 个 `.java` 文件和 200 对用例；单个 `.in` 原始输入最多 262,144 字节，单个 `.out` 期望输出最多 65,536 字节。用例按大小写折叠后的 POSIX 相对路径稳定排序，实际输出与期望输出只归一化 CRLF/CR/LF，除此之外精确比较。

`purpose="test"` 只提供局部测试结果，不能形成最终成功证据。只有新鲜的 Java verification 结果，即 `purpose="verification"` 且全部用例通过、`validation_index == mutation_index`，才可满足没有用户 `--verify` 的验证门。编译和全部用例共享最多 60 秒的截止时间；输出、超时、首个失败 case 和安全错误使用有界结构化结果。

文件工具不能访问 `.git/` 或 `.coding-agent/`。`run_command` 仍不能执行 Java 命令字符串，只允许策略明确支持的 Python/pytest/unittest、受限 ruff/mypy 和只读 Git 形式。Java 编译器与运行时只由专用工具从净化 PATH 解析成工作区外的可信绝对路径；不支持 Maven、Gradle 或 JUnit。

## 成功、验证与退出码

`SUCCESS` 不由模型文字决定。修改模式的新鲜验证必须在最后一次文件修改后运行、退出码为 0，并满足 `validation_index == mutation_index`。

如果文件已经修改，但纠正机会耗尽、验证没有运行或未通过，终止原因是 `changes_unverified`，FinalReport 状态为 `failed`、退出码 1。GUI 以“修改待验证”显示修改路径、验证状态和安全错误码。文件不会自动回滚；用户应检查保留的修改，提供 `--verify`，或要求 Agent 使用上述允许的验证形式。该状态绝不等同于 `SUCCESS`。

任一模式的非空最终文本在没有修改和验证事实时成为 `ANSWERED`，GUI 显示“已回答”，退出码同样为 `0`；它只表示问答正常结束，不表示测试通过或代码已验证。预算、安全拒绝、审计失败、模型错误和用户中断仍可终止运行。

用户提供 `--verify` 时，即使已有新鲜 Java 证据，也必须执行用户命令并以其结果为最终门槛；未提供时才允许可信 `run_command`、完整通过的 Java verification 证据或内建完整性验证。已有模型/用户验证因后续修改而过期时不得降级为完整性检查。内建验证检查每个 changed path 仍处于工作区、文件不超过 524,288 原始字节且为 UTF-8；`.py`、`.json`、`.toml` 还必须通过语法解析，其他文本（包括 C/C++）只检查完整性，不表示已编译或运行。

| 退出码 | FinalReport 状态 | 含义 |
| --- | --- | --- |
| `0` | `success` | 完成候选具有新鲜、通过的本地验证证据。 |
| `0` | `answered` | 只读问答正常结束；没有修改，也没有验证成功声明。 |
| `1` | `failed` | 预算、重复、安全、模型、工具、验证或审计失败。 |
| `2` | 无 FinalReport | CLI 参数或启动配置错误。 |
| `130` | `interrupted` | 用户中断，日志会尽力关闭并生成中断报告。 |

## JSONL 日志与 FinalReport

每次已启动运行的事件写入 `.coding-agent/logs/<run_id>.jsonl`。事件按连续 sequence 记录模型调用元数据、工具调用/结果、安全拒绝、压缩、验证和终止事实；不记录完整任务文本、工具原始内容、环境全集、API key、认证头、continuation 或隐藏推理。`OPENAI_API_KEY` 和 `CHAT_COMPLETIONS_API_KEY` 都会从 `run_command` 子进程环境中移除。

进程在 stdout 输出一个有界 JSON FinalReport，其中包含运行模式、状态、退出码、终止原因、修改路径、验证证据、计数、日志相对路径和审计失败代码。报告与 JSONL 使用同一执行状态；审计 schema 严格区分 `ANSWERED` 与 `SUCCESS`。

## 离线演示与完整测试

确定性 demo 位于 `tests/integration/test_agent_repair.py`，使用 FakeModelClient，复制 `examples/broken_pytest_project/` 后完成“读取—修改—验证失败—再次修改—验证通过”：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_agent_repair.py -q -p no:cacheprovider
```

Chat 连续 Agent 循环合同位于 `tests/integration/test_chat_completions_agent.py`，使用真实 AgentRunner、ContextManager 和 Chat 适配器，只把最外层 SDK 换成 fake：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_chat_completions_agent.py -q -p no:cacheprovider
```

Java headless Agent 合同位于 `tests/integration/test_java_agent.py`；真实本机 JDK 冒烟位于 `tests/tools/test_java_tool.py`。前者完全离线使用 fake executor，后者在临时工作区真实编译并运行一个 `.in`/`.out` 用例。

完整离线测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

这些 pytest 命令不会调用真实模型 API。

GUI 的确定性视觉 fixture 不读取凭据或调用模型：

```powershell
.\.venv\Scripts\python.exe tests\manual_web_fixture.py
```

它只打印一个 `127.0.0.1` URL，用于人工检查宽屏、窄屏、长文本、代码块、紧凑 Skill 选择器和各运行状态；按 Ctrl+C 停止。

## 常见错误与排查

- `OPENAI_API_KEY is not configured`：只在当前会话配置环境变量，不要打印其值。
- `CHAT_COMPLETIONS_API_KEY is not configured`：Chat mode 只读取该变量，不回退到 OpenAI key。
- `--base-url is not allowed with responses`：移除 base URL，Responses 始终使用官方默认 endpoint。
- `--base-url is required with chat-completions`：提供包含 API 前缀的绝对 HTTPS URL。
- `model is not configured`：设置 `OPENAI_MODEL` 或传 `--model`。
- `workspace rejected`：确认目录存在，且路径没有非法设备名、受保护组件或 reparse point。
- `--verify rejected`：命令不在安全白名单、包含控制符，或不是可信验证命令。
- `--read-only cannot be combined with --verify`：二者权限语义冲突；移除验证命令，或改用默认修改模式。
- `trusted Java runtime is unavailable`：确认 Windows PATH 中存在工作区外的 `javac.exe` 与 `java.exe`。
- 退出 `1`：读取 FinalReport 的 termination reason、验证证据和 `.coding-agent/logs/<run_id>.jsonl` 中的脱敏事件。
- `no_progress`：Agent 在决策 checkpoint 后仍未回答、修改、验证或报告阻塞；缩小任务范围，明确目标文件，或在确需更多探索时选择 `deep`。
- `decision_required`：最终只读额度已耗尽，或本轮读取全部是运行级探索账本中的重复结果。让 Agent 直接回答、实施已明确修改、使用合法验证形式，或报告具体阻塞；继续读取会被配对拒绝，第一次无进展决策之后最多还有一次纠正响应。
- `changes_unverified`：文件已修改但没有最后一次修改之后的新鲜通过证据，退出码 1。文件不会自动回滚；检查修改后重新运行并提供强制验证命令，或让 Agent 使用允许的 Python/Java 验证形式。
- `main_model_call_limit`：main call 硬上限已用完；检查此前 checkpoint 与工具结果，拆分任务或选择 `deep`，不要把它误解为 summary 次数。
- `provider_attempt_limit`：包括模型适配器内部重试在内的物理请求硬上限已用完；检查 endpoint 稳定性。摘要调用与 main 调用共享该总数，但另有 summary 子上限。
- 摘要 fallback：日志中的 `summary_fallback_latched` 表示本 run 已改用确定性本地摘要；这是安全降级，不会记录摘要正文，也不会在同一 run 反复尝试模型摘要。
- 测试超时：命令执行器会终止 Windows 子进程树并保留受限的 stdout/stderr；检查 `timed_out` 和 `cleanup_error`。

## 停止运行与清理

一次性 CLI 中按 `Ctrl+C` 请求停止，正常中断应返回 `130` 和 `interrupted` 报告；强制关闭终端可能阻止最终报告写出。Web 服务中按 Ctrl+C 会停止接收新请求，等待已接纳的运行协作式结束并关闭资源；关闭浏览器不会取消运行。

进程停止后，用户可以自行删除工作区内 `.coding-agent` 目录来清理全部本地状态。GUI 的逐条会话删除只清理精确关联的关系数据和审计 JSONL；Agent 没有删除工具，也不会自动清理、提交或上传其他文件。

## 安全边界和已知限制

路径和命令限制由确定性本地代码执行，包含工作区约束、受保护目录、Windows reparse point 检查、有限命令集、固定 cwd、`shell=False`、超时和输出上限。`read_only` 是 Agent 的确定性能力边界，不是操作系统级沙箱；它不会注册修改或通用命令工具，但被允许读取的内容仍会发送给所选模型。

`--base-url` 可配置不代表兼容所有服务。compatible endpoint 必须支持标准 Chat Completions assistant `tool_calls`、非空函数 call ID、strict function schema，以及用 `tool_call_id` 配对的 `role=tool` 结果；本项目不会根据 URL 猜测、探测或自动切换 API mode。

这不是操作系统级沙箱。被允许执行的工作区脚本、pytest 配置和测试会作为可信代码运行，仍可能访问操作系统资源；策略也不能消除所有检查与使用之间的 TOCTOU 风险。请只处理可信项目，并使用可丢弃、已备份的工作区副本。

当前已有本地会话持久化、认证 REST/fetch-SSE 和静态 GUI。`RunInstructionBuilder` 只提供受限的声明式纯文本 Skill 指令输入边界；没有可执行 Skill、动态安装或 MCP。专用 Java 工具会执行可信工作区代码，不是操作系统级沙箱；它不支持 Maven、Gradle 或 JUnit，也不会下载依赖或 JDK。项目也不提供账户、远程服务器、多用户、多活动运行、操作系统级沙箱或通用异步模型 API。

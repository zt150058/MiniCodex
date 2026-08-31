# MiniCodex

MiniCodex 是一个 Windows 优先、Python 编写的本地 Coding Agent。它自行实现显式 Agent 循环、上下文管理、本地工具、安全策略、验证门槛和审计日志，并通过 provider-neutral `ModelClient` 接入默认的 OpenAI Responses API 或显式配置的 compatible Chat Completions endpoint。

- [考核提交说明](README.txt)
- [安装、运行与故障排查](docs/USAGE.md)
- [Responses 与 compatible Chat Completions 接入说明](docs/OPENAI_API.md)

安装后运行 `coding-agent --help` 查看一次性 CLI，或运行 `coding-agent-web --workspace <path>` 打开本地 Web GUI。GUI 只绑定 `127.0.0.1` 的随机端口，以进程内 Bearer token、Host/Origin 校验保护 REST/SSE，可查看持久会话、提交 follow-up、选择声明式 Skill 和请求取消；一次只运行一个 Agent。

GUI 可从本机导入一个 `.zip` Skill 包到当前工作区的 `.coding-agent/skills/`。包内只允许一个 `<skill-id>/SKILL.md`，归档最大 128 KiB、定义最大 65,536 字节；既有 Skill 不覆盖，运行期间禁用导入。Skill 是不可执行的声明式指令，不能增加工具权限。

GUI 还支持对空闲会话逐条删除：每次都以安全纯文本标题二次确认，不支持批量删除，活动 run 期间拒绝删除。删除只覆盖该会话的 SQLite 关系数据和由持久化 ID 精确确定的 `.coding-agent/logs/<audit_run_id>.jsonl`；`cleanup_pending` 表示日志清理将在下次启动恢复。该入口不是 Agent 工具，也不会删除任意工作区文件。

每次运行都显式选择一种能力边界：默认 `modify`（GUI“允许修改”）提供既有修改、命令和验证能力；`read_only`（CLI `--read-only`、GUI“只读问答”）只允许列目录、读文件和检查本地只读 Git。`modify` 是能力而不是意图：若本次没有修改或验证，普通回答也以 `ANSWERED` 结束；只有修改后的新鲜验证证据才能形成 `SUCCESS`。同一会话的后续消息可重新选择模式，详细工具表和限制见[使用说明](docs/USAGE.md)。

运行权限与执行预算彼此独立：`RunMode` 决定可用工具，`BudgetProfile` 决定不可变硬上限。CLI 可传 `--budget-profile standard`（默认）或 `--budget-profile deep`；Web GUI 可在发送前选择“标准”或“深入”。Agent 以 `DISCOVER → ACT → VERIFY → FINISH` 阶段和本地进度账本收敛，探索过久会先收到决策 checkpoint，继续无进展才以 `no_progress` 停止。上下文摘要失败后，本次运行会锁定确定性的本地 fallback，而不会反复消耗摘要预算。硬上限并不表示 Agent 一定会用完额度。

架构亮点是确定性的“调查—决策—验证”门控：运行级 `ExplorationLedger` 只保存安全目标标签和哈希等有界元数据，不保存文件正文；上下文压缩会清除 provider continuation，但仍能利用这份探索覆盖避免重复读取。普通 checkpoint 后保留 **Standard 1 / Deep 2** 个尝试读取的响应批次，整批重复读取会立即进入 `decision_required`；第一次决策仍无进展时，在硬预算允许下只提供一次纠正响应。命令被安全策略拒绝时只给出脱敏纠正，拒绝但不自动改写。修改后若始终没有新鲜通过证据，运行以 `changes_unverified` 和退出码 `1` 结束，GUI 显示“修改待验证”，文件保留但绝不冒充 `SUCCESS`。

同一 mutation 的重复验证仍会记录为审计事实，但不会反复重置收敛进度；本地完整性通过后立即进入修改后 checkpoint。带工具调用的流式说明只临时显示，工具开始时会清除，只有不含工具调用的最终回复才进入会话历史。GUI 命令卡显示真实 `exit N`，从而区分“工具成功启动”与“子进程退出成功”。

```powershell
coding-agent "分析并修复项目" --workspace . --budget-profile standard --verify "pytest -q"
coding-agent-web --workspace .
```

第二条命令启动后，可在页面输入框旁为每次运行选择 `standard` 或 `deep`。

`--api-mode` 默认是 `responses`；选择 `chat-completions` 时必须显式提供 HTTPS `--base-url`。可配置 URL 不代表兼容所有服务，目标 endpoint 必须支持标准函数工具调用与 `tool_call_id` 配对。项目只允许一组受控的文件和命令操作，并且不是操作系统级沙箱。

项目创建的两个官方 SDK client 均使用 30 秒单次请求 timeout，适配器重试仍受 provider attempt 硬预算约束。MiniCodex 不提供 PTY、C/C++ 编译或自动人工交互；交互程序应以可自动化的适配器回归测试验证，无法自动覆盖时必须由用户手工验证。不要用一次性诊断脚本绕过命令安全策略。

修改模式可用 `create_directory` 一次创建一级目录（不递归创建父目录），再用 create-only `write_file` 写入文件。符合条件的修改响应结束后会立即检查 changed path 的本地结构完整性，但这不代表测试或编译已经通过；后续最终文本仍是成功收敛所必需。

除 Python 验证外，MiniCodex 还提供专用 `run_java_tests`：它使用可信本机 JDK 编译工作区 Java 源码，并按稳定顺序执行成对的 `.in`/`.out` 标准输入输出 fixture。未指定 `--verify` 且模型没有执行验证时，Agent 可用内建完整性检查确认变更文件仍是合规 UTF-8 文本；Python、JSON、TOML 还会进行语法解析，其他类型不声称已经编译或测试。Java 命令字符串仍不能通过 `run_command` 执行；该能力不支持 Maven、Gradle 或 JUnit，也不是操作系统级沙箱。

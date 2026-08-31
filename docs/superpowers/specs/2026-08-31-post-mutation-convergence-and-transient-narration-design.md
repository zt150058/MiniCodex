# 修改后收敛与临时工具叙述设计

## 1. 状态

本文档记录已经在对话中批准的架构方向，供用户进行书面设计审查。
在本文档获得明确批准前，不编写实施计划，不修改生产代码、测试或
`TASKS.md` 状态。

## 2. 已复现问题与根因

一次 C++ 修复运行提供了以下确定性证据：

- 首次 `replace_text` 已成功修复 `main.cpp` 中缺失的单引号；
- 后续运行仍持续读取文件、重复执行允许的 Python 形式验证，并多次输出
  “修复已完成”一类近义文本；
- 该 run 共发生 23 次 logical model call、23 次 provider attempt、80 次
  tool call、6 次上下文压缩，最终以 `tool_call_limit` 终止；
- 当前命令策略拒绝 `make`、`g++`、Bash 和 WSL，因此 Agent 无法取得真实
  C++ 编译证据；
- 同一 mutation 上重复记录同等级验证证据时，`ProgressLedger` 每次都把它
  当作强进展并清空 checkpoint；
- 带有工具调用的完整模型文本会过早触发 `confirmed_text_handler`，因而被
  持久化为多条 `assistant_text_committed`，尽管这些文本只是工具执行前的
  过程叙述。
- Python 贪吃蛇的 12 个测试只覆盖领域逻辑，没有执行 Windows 键盘适配器、
  入口或交互渲染；生成代码把 `msvcrt.getch()` 返回的 `bytes` 当作整数处理，
  任意 WASD 或方向键都会触发 `TypeError`，但语法检查和领域测试仍全部通过。
- GUI 将一次退出码为 1 的 `run_command` 显示为 `ok`。该字段只表示工具成功
  启动并捕获了子进程，不表示子进程成功，隐藏退出码会误导用户。
- 后续诊断 run 在 provider attempt 已开始但没有完成事件的位置长期停留；
  生产 SDK 客户端关闭了 SDK 重试，却仍使用 SDK 默认网络等待时间。
- 为绕过禁止 `python -c` 的正确安全策略，模型创建了 `diag.py` 和
  `diag_run.py`。当前没有删除工具，这些一次性探针会成为永久工作区修改。

当前蛇项目的源文件已经不再包含最初的 `case 'Q:` 错误。一次由用户在
WSL 中运行的真实 `make` 还暴露了 `Snake.cpp` 的 `size_t` 命名空间错误。
该事实证明 Agent 的本地完整性检查不能替代 C++ 编译，也证明简单提高工具
上限不会解决收敛问题。

## 3. 目标

- 成功修改并通过 eager local integrity 后，立即进入已有决策检查点。
- 保留 Standard 1 个、Deep 2 个普通最终只读响应批次，不额外缩小既有档位。
- 同一 mutation 上重复的同等级验证不再重置进度或重新开放探索。
- 只有验证状态变化、验证来源升级或 mutation 前进才构成验证强进展。
- 带工具调用的文本只作为本轮临时叙述，不进入持久会话或最终回复投影。
- 保留合法的内部 `AssistantMessage(text, tool_calls)`，不破坏工具调用、
  `call_id`、provider 历史或 continuation 配对。
- 对当前不支持的 C/C++ 工具链给出准确的人工验证说明，而不是运行无关
  Python 命令或循环读取文件。
- 让交互式程序的验证声明严格匹配实际覆盖范围；语法和领域测试通过不能被
  表述为键盘、终端或人工交互已经验证。
- 禁止创建仅用于绕过命令策略且无法清理的一次性诊断脚本；可复现缺陷应进入
  正式回归测试，无法自动化时应报告限制。
- GUI 对有退出码的命令显示 `exit N`，不再用工具层 `ok` 暗示命令成功。
- 两个生产模型适配器显式配置 30 秒 SDK 网络操作超时，避免单个 provider
  attempt 继承十分钟级默认等待。
- 保持 Task8 安全边界、Task10 预算、Task11 验证新鲜度和 Task19 会话隐私。

## 4. 非目标

- 不开放任意命令执行，不新增 `make`、`g++`、Bash、WSL、PowerShell 或
  `cmd` 模型工具。
- 不增加 tool call、logical call、provider attempt 或运行时间上限。
- 不增加 Planner、第二个 Agent、Agent 框架、后台队列或新依赖。
- 不新增任意编译器探测、PATH 搜索、包管理或联网能力。
- 不增加 PTY、虚拟键盘、桌面自动化或真实人工交互执行器。
- 不把 local integrity 描述为编译、测试或行为验证。
- 不改变 `ModelClient.complete(ModelRequest) -> ModelResponse`、消息数据结构、
  ToolRegistry、REST、SSE 或 SQLite schema。
- 不删除或重写历史运行中已经持久化的过程文本；新语义只应用于新 run。
- 不在本任务中增加额外的“单响应工具调用数量”上限。
- 不声称通用代码 Agent 能从测试命令退出码自动证明需求覆盖完整性。

## 5. 方案比较

### 5.1 采用方案：证据单调性、修改后 checkpoint、临时叙述

该方案修复造成循环的三个状态转换，同时复用现有安全和会话机制：

1. 修改批次通过 eager local integrity 后激活既有 checkpoint；
2. 记录验证事实与判定“验证是否推进进度”分离；
3. 仅 tool-free 最终文本触发 `confirmed_text_handler`；
4. 流式的 text-plus-tools 文本在首个工具活动前通过现有
   `assistant_text_discarded` UI 生命周期清除。

优点是没有新权限、没有预算膨胀、没有数据库迁移，且能直接针对审计证据
建立离线回归测试。代价是 C/C++ 项目仍需要用户在外部运行构建命令，或者
未来单独设计一个受控 C++ 验证工具。

### 5.2 拒绝方案：只提高预算

把 Standard 的 80 次工具调用提高到 140 次只会延迟相同失败。重复验证仍会
重置 checkpoint，过程叙述仍会污染会话，运行成本和等待时间反而增加。

### 5.3 拒绝方案：直接开放 WSL 或任意编译器

将模型字符串交给 WSL、Bash 或任意本地可执行程序会绕过当前 Windows 优先
命令 allowlist，扩大代码执行、环境泄漏和工作区逃逸风险。若未来需要 C++
编译，应像现有 `run_java_tests` 一样单独设计受控、参数化、无 shell 的专用
工具，而不是在本修复中附带开放。

## 6. 锁定语义

### 6.1 验证事实与进度推进分离

`VerificationGate.observe_tool_result(...) -> bool` 的既有返回语义保持为
“本次工具结果是否形成了可信验证事实”。可信事实仍然必须：

- 更新 `verification_attempt_count`；
- 更新 `last_verification` 和 `verification_status`；
- 产生既有验证审计事件；
- 保持完整的 validation index、状态、来源、退出码和脱敏结果。

Agent 在调用该方法前保存 `previous_evidence = state.last_verification`，调用后
读取 `current_evidence = state.last_verification`。只有下列条件之一成立，才把
`verification_advanced=True` 传给进度账本：

1. 当前可信证据存在而此前没有证据；
2. `current.validation_index > previous.validation_index`；
3. validation index 相同，但 `current.status is not previous.status`；
4. validation index 和状态相同，但验证来源等级严格上升。

验证来源等级固定为：

```text
LOCAL_INTEGRITY < MODEL < USER_VERIFY
```

下列变化不构成进度推进：

- 同一 mutation、同一状态、同一来源的重复验证；
- 同一 mutation、同一状态、来源等级降低；
- 仅命令文本、stdout、stderr、耗时、截断位或 provider 细节变化；
- 不可信、被拒绝或无法解析的验证工具结果。

重复验证即使不推进进度，也必须完整更新最后证据和审计计数；本设计只限制
它对收敛状态机的影响，不丢失实际执行事实。

`ProgressLedger.observe_tool` 的 keyword-only 参数由
`verification_recorded` 更名为 `verification_advanced`，语义固定为“该验证
事实是否按上述单调规则推进进度”。它仍返回 `ProgressStrength`，不改变
`ProgressStrength` 枚举。该接口仅由本地 Agent 与测试消费，不进入 provider、
REST、SSE 或 SQLite 公共数据。

### 6.2 修改后本地完整性检查点

一次带工具响应执行完毕后，沿用 Task29 的 eager local integrity 条件和顺序：

1. 批次内至少有一个成功 mutation；
2. 没有用户强制 `--verify`；
3. 没有禁止 local fallback 的真实验证证据；
4. 工具、时间和验证额度允许；
5. 对最终 mutation epoch 只执行一次 local integrity。

若 eager local integrity 返回 `PASSED`：

- `AgentStatus` 仍保持 `RUNNING`；
- `validation_index == mutation_index`；
- local integrity 不被重复登记成新的工具强进展；
- `state.progress.activate_checkpoint()` 在当前 mutation 批次完成后立即调用；
- 产生一个既有 `decision_checkpoint` 审计/UI 事件，固定 reason 为
  `post_mutation_integrity`；
- 当前 mutation 本身已经是强进展，因此本轮结束时不消耗 checkpoint 的最终
  只读额度；额度从下一次主模型响应开始计算。

检查点继续使用 Task26 已有档位：

- Standard：最多 1 个普通最终只读响应批次；
- Deep：最多 2 个普通最终只读响应批次。

额度耗尽后，已有 `decision_required` 握手要求模型在“继续修改、给出 tool-free
最终回复、准确报告阻塞”中选择；继续读取会收到配对拒绝，第二次仍无行动则
以 `no_progress` 终止。新 mutation 或真正的验证推进会通过既有强进展语义
清除旧 checkpoint；新 mutation 完成 local integrity 后再激活一个属于新 epoch
的 checkpoint。

若 local integrity 返回失败，则保持 Task29 已有 `verification_failure`
checkpoint、repair read 和修改后证据过期语义，不使用新的成功路径。

### 6.3 text-plus-tools 是临时叙述

模型响应的文本按以下规则处理：

| 响应形态 | Agent 内部历史 | 实时 UI | SQLite / narrative |
|---|---|---|---|
| tool-free 非空文本 | 保存为 `AssistantMessage(content=text)` | 流式显示并确认 | 写入一条 `assistant_text_committed` |
| 非空文本 + tools | 保存为 `AssistantMessage(content=text, tool_calls=...)` | 工具开始前可临时显示，随后清除 | 不写入 |
| tools 且无文本 | 保存工具调用消息 | 只显示活动状态 | 不写入 |
| provider discard | 不保存部分文本 | 清除 | 不写入 |

`AgentRunner` 必须先判断 `response.tool_calls`，只有在其为空且
`assistant_text` 非空时才调用 `confirmed_text_handler`。带工具响应的文本仍然
保留在活动消息历史中，以满足 Chat Completions assistant/tool 顺序、Responses
continuation 和 `call_id` 配对；“不持久化”不等于“从 provider 历史删除”。

对于流式 text-plus-tools，Controller 不能等待不存在的 confirmed callback。
在接收到该响应的首个 `tool_call_started` 审计事件时，如果内存中的
`pending_text` 非空，则：

1. 清空 `pending_text`；
2. 发布既有 `assistant_text_discarded` 更新，reason 固定为
   `tool_response_narration`；
3. 不追加 `assistant_text_committed` 持久事件；
4. 再按既有顺序发布工具活动。

这不新增 ModelStreamEvent 类型，也不把一个成功 provider 响应误标记为 provider
discard。同步 text-plus-tools 没有 provisional delta，因而只需跳过 confirmed
callback。

工具执行结束后的 tool-free 最终文本正常提交一次。历史数据库不迁移，不删除
旧的安全叙事事件；投影规则对新 run 自然只显示最终提交文本。

### 6.4 不支持工具链时的确定性收敛

`_FRESH_LOCAL_INTEGRITY_INSTRUCTION` 继续明确 local integrity 不是测试或编译
证据，并增加以下固定行为合同：

- 不得用无关 Python、pytest、unittest、ruff、mypy 或 Git 命令冒充 C/C++
  构建验证；
- 当前授权工具无法执行所需构建时，不反复读取同一文件；
- 若修改已经完成，应返回 tool-free 最终文本，明确说明只完成了本地完整性
  检查，并给出用户可在外部运行的精确构建命令；
- 若没有足够证据继续修改，应准确报告 blocker，而不是声称编译通过。

命令安全拒绝、修正提示、修改新鲜度和最终报告语义保持不变。对于无强制
`--verify` 的 C/C++ 文本修改，local integrity 仍可作为当前已批准设计中的最低
级成功证据，但任何 UI、报告和模型说明都不得把它表述为编译通过。

### 6.5 交互式程序的验证诚实性

固定基础指令增加以下供应商中立合同，Skill 可以补充但不能削弱：

- 修复可复现缺陷时，优先把最小复现写入项目现有测试布局，再修改生产代码；
- 不得创建仅用于绕过 `python -c`、Shell 或其他命令限制的一次性
  `diag`/`probe` 脚本；如果项目没有可保留的测试位置，应报告自动诊断限制；
- 对键盘、终端、GUI、网络服务等交互边界，领域单元测试和语法检查只能证明
  它们实际覆盖的行为；
- 只有 adapter/entrypoint 测试、用户强制验证或明确人工操作覆盖了对应边界，
  最终文本才可以声明该边界已经验证；
- 无法自动执行人工交互时，最终文本必须区分“自动测试通过”和“仍需人工
  交互验证”，并给出精确运行步骤；
- 任何命令结论必须使用真实 exit code；工具状态 `ok` 不能被翻译为测试通过。

该合同不能从任意测试名称推断语义覆盖，也不新增 `VerificationResult` 字段。
确定性本地代码继续只裁决执行事实和新鲜度；覆盖范围属于模型必须准确报告的
限制。这样避免引入一个看似严格但实际无法通用于任意语言和框架的“语义覆盖
检测器”。

### 6.6 GUI 命令结果语义

现有 `tool_finished` DTO 已包含 `status`、`exit_code`、`duration_ms` 和
`safe_error_code`，不修改 REST、SSE 或 SQLite schema。GUI 的安全详情投影固定
为：

- `exit_code` 是整数时，显示 `tool_name · exit N · duration`，不显示工具层
  `ok`；
- `exit_code` 为 `null` 时，继续显示 `tool_name · status · duration`；
- 被拒绝或错误的工具只显示既有安全状态和稳定错误码，不显示 stdout、stderr、
  命令正文或异常详情；
- `exit 0` 表示子进程退出码为 0，`exit 1` 等非零值不得使用成功颜色或成功
  文案。

这只修复展示语义。Task7 的既有不变量保持：只要子进程成功启动并结束，即使
退出码非零，Registry 工具调用状态仍为 `ok`，Agent 仍能读取 stdout/stderr 并
决定下一步。

### 6.7 Provider 网络等待上限

新增 provider-neutral 常量：

```python
DEFAULT_PROVIDER_TIMEOUT_SECONDS = 30.0
```

该常量位于 `model.py`，只表示生产 SDK 单次网络操作的超时配置，不改变 run
时间预算、logical call 或 provider attempt 计数。

两个生产适配器在自行构造官方 SDK 客户端时必须显式传入：

```python
OpenAI(..., max_retries=0, timeout=DEFAULT_PROVIDER_TIMEOUT_SECONDS)
```

锁定语义：

- Responses 和 Chat Completions 使用相同的 30.0 秒值；
- timeout 保持官方 SDK 的网络超时语义，不增加线程、强杀或第二套计时器；
- `APITimeoutError` 继续使用 Task9 已有瞬时错误分类、最多两次适配器重试、
  provider attempt 预算和脱敏消息；
- 已公开流式文本后的 timeout 继续丢弃部分响应且不重试；
- 注入的 fake SDK 不被包装或改写，离线测试通过 monkeypatch 的 SDK factory
  证明生产构造参数；
- timeout 值、API key、base URL 和 SDK 异常正文不进入模型上下文、JSONL、
  Session 或 GUI。

该变化限制一次失去网络进展的等待，但不承诺 provider 在 30 秒内完成整个长
响应；流式连接只要按 SDK 语义持续收到数据，可以继续受 run 总时间预算约束。

## 7. 数据流

```text
model response: replace_text
  -> deterministic local mutation
  -> mutation_index advances (strong progress)
  -> eager local integrity once
  -> evidence = PASSED / LOCAL_INTEGRITY / current mutation
  -> activate checkpoint(post_mutation_integrity)
  -> next model response
       -> at most profile read allowance
       -> optional real verification evidence upgrade
       -> new mutation, tool-free final answer, or blocker
  -> no repeated same-tier verification reset
  -> no text-plus-tools persisted assistant bubbles
```

重复验证路径：

```text
MODEL/PASSED/mutation=1
  -> another MODEL/PASSED/mutation=1
  -> verification fact recorded and audited
  -> verification_advanced = false
  -> checkpoint and no-progress counters remain active
```

证据升级路径：

```text
LOCAL_INTEGRITY/PASSED/mutation=1
  -> MODEL/PASSED/mutation=1
  -> verification_advanced = true
  -> existing strong-progress reset applies
```

## 8. 组件与文件边界

预计后续实现会修改：

- `src/coding_agent/verification.py`
  - 提供验证证据推进判定，不改变 `VerificationResult` 字段；
  - 保持 `observe_tool_result(...) -> bool` 的可信事实语义。
- `src/coding_agent/progress.py`
  - 把内部参数锁定为 `verification_advanced`；
  - 不改变阈值、枚举或已有 checkpoint 计数算法。
- `src/coding_agent/agent.py`
  - 区分 evidence recorded 与 evidence advanced；
  - local integrity 成功后激活 checkpoint；
  - 仅 tool-free 文本调用 confirmed handler；
  - 更新不支持工具链时的固定收敛指令。
- `src/coding_agent/model.py`
  - 定义统一的 30.0 秒生产 provider 网络超时常量。
- `src/coding_agent/openai_client.py`、`src/coding_agent/chat_completions_client.py`
  - 生产 SDK 构造显式关闭 SDK 重试并使用统一 timeout；既有请求、解析和重试
    语义保持不变。
- `src/coding_agent/instructions.py`
  - 增加正式回归测试、交互覆盖声明和禁止一次性诊断脚本合同。
- `src/coding_agent/logging.py`
  - 允许 `decision_checkpoint.reason = post_mutation_integrity`；
  - 不增加原始正文或敏感字段。
- `src/coding_agent/session_controller.py`
  - 首个工具活动清除尚未确认的临时叙述；
  - 复用现有 discarded 更新，不改变数据库 schema。
- `src/coding_agent/web_static/app.js`
  - 对有退出码的工具活动显示 `exit N`，其他工具保持现有状态投影。
- `DESIGN.md`、`TASKS.md` 和必要的公开使用文档
  - 只在后续批准的实施计划中更新设计基线和用户可见限制。

预计后续测试会修改：

- `tests/test_verification.py`
- `tests/test_progress.py`
- `tests/test_agent_loop.py`
- `tests/test_logging.py`
- `tests/test_session_controller.py`
- `tests/test_model.py`
- `tests/test_openai_client.py`
- `tests/test_chat_completions_client.py`
- `tests/test_instructions.py`
- `tests/js/web_gui.test.mjs`
- 必要的 session/web GUI 投影集成测试和文档合同测试。

明确不修改：

- `messages.py` 的消息和 JSON 格式；
- `model.py` 的 provider-neutral 协议；
- OpenAI Responses 和 Chat Completions 请求/响应映射；
- Task8 文件/命令安全策略和工具 allowlist；
- SQLite schema、REST/SSE DTO、预算档位数值、依赖文件和 Skill 格式。

## 9. 错误处理、安全与隐私

- 验证比较只读取 provider-neutral `VerificationResult` 元数据，不解析 stdout、
  stderr、异常字符串或 SDK 私有字段。
- 验证正文仍受现有 repr、JSONL 和 FinalReport 脱敏规则约束。
- `post_mutation_integrity` 和 `tool_response_narration` 是稳定本地 reason code，
  不包含路径、命令、模型内容或异常正文。
- `KeyboardInterrupt`、`SystemExit` 和取消语义不变；不新增 `BaseException`
  捕获。
- 新 checkpoint 不运行任何额外命令，也不改变安全授权结果。
- Controller 只清除内存 provisional 文本，不删除用户消息、最终回复、工具
  结果或审计事实。
- continuation 和 encrypted reasoning 仍只存在 provider 适配器和活动状态的
  既有受限边界，不写入新增事件。
- provider timeout 只通过官方 SDK 的公开构造参数配置，不访问私有传输对象，
  不记录 endpoint、认证信息或异常正文。
- 交互验证合同不能扩大命令 allowlist；模型不得通过创建临时脚本绕过被拒绝的
  命令形式。

## 10. 测试策略

所有行为在后续计划中使用严格 RED、最小 GREEN、相关回归。

### 10.1 验证推进

- 首个可信验证是强进展。
- validation index 前进是强进展。
- 同 mutation 的状态变化是强进展。
- `LOCAL_INTEGRITY -> MODEL -> USER_VERIFY` 的同状态升级是强进展。
- 同 mutation、状态、来源的重复验证不是强进展。
- 来源降级、命令变化、输出变化和耗时变化不是强进展。
- 重复验证仍增加 attempt、更新最后证据并产生审计事件。

### 10.2 修改后 checkpoint

- 单文件 mutation + local integrity pass 立即激活 checkpoint。
- 多文件同批次只验证一次并只激活一次 checkpoint。
- Standard 恰好允许 1 个最终只读批次，Deep 恰好允许 2 个。
- 新 mutation 清除旧 checkpoint，并在新 local integrity 后建立新 checkpoint。
- 真正的模型验证升级清除 checkpoint；重复相同模型验证不清除。
- local integrity failure 继续使用 `verification_failure` repair 路径。
- 强制 `--verify` 不触发 post-mutation local checkpoint。
- 预算、取消和内部错误不产生伪 checkpoint 或伪证据。

### 10.3 临时叙述

- text-plus-tools 仍进入 Agent 内部历史并保持 `call_id` 配对。
- text-plus-tools 不调用 confirmed handler。
- tool-free 最终文本只调用 confirmed handler 一次。
- 流式 text-plus-tools 在首个工具活动前可见，随后发出固定 discard 并清空。
- 同步 text-plus-tools 不产生 committed 或多余 discard。
- provider discard、text mismatch 和 final commit 的既有生命周期保持。
- SQLite narrative 新 run 只包含最终 tool-free assistant 文本。
- 页面重载后不恢复临时叙述；旧历史数据不迁移。

### 10.4 端到端收敛

- FakeModelClient 复现“修改一次、重复读取、重复相同验证”时，在低于工具硬
  上限的位置进入 final answer 或稳定 `no_progress`。
- C++ 修复 fixture 证明 local integrity 后最多使用档位允许的只读批次，不能
  用 Python 验证冒充编译，也不能产生多条持久助手过程回复。
- 实际不支持的 `make`/`g++` 仍由安全策略拒绝，最终文本准确给出人工验证
  命令和限制。
- Python/Java 的现有可信验证、Task29 eager integrity、Chat stream fallback、
  read-only、Skill、follow-up、Session、SSE 和 GUI 全部回归。

### 10.5 交互、GUI 和 provider 等待

- 指令明确要求正式回归测试，禁止一次性诊断脚本，并区分自动与人工交互验证。
- 指令文本不包含用户路径、测试输出或 provider 内容，摘要调用仍不继承主运行
  指令。
- GUI 对 `run_command(status=ok, exit_code=1)` 显示 `exit 1` 且不显示 `ok`。
- GUI 对 `run_command(status=ok, exit_code=0)` 显示 `exit 0`。
- GUI 对普通文件工具和被拒绝工具保持原状态与安全错误投影。
- Responses 生产 SDK factory 精确收到 `max_retries=0` 和 `timeout=30.0`。
- Chat 生产 SDK factory 精确收到 base URL、`max_retries=0` 和 `timeout=30.0`。
- fake SDK 注入路径完全离线，既有 timeout 分类、重试次数、流式部分文本和
  `BaseException` 测试保持通过。

### 10.6 最终审计

- 完整 Python 和 Node 测试套件。
- Windows reparse point、timeout 和进程树专项。
- `git diff --check` 与依赖检查。
- API key、Authorization、绝对个人路径、continuation、provider payload、
  未完成标记、测试抑制和 Agent framework 扫描。
- 审查完整 diff，确认没有扩大命令 allowlist、预算或持久化正文范围。

## 11. 验收矩阵

| 要求 | 证据 |
|---|---|
| 修改后立即进入决策阶段 | eager integrity + checkpoint Agent 测试 |
| Standard 1 / Deep 2 批次不变 | ProgressLedger 边界测试 |
| 重复同等级验证不重置收敛 | verification/progress/Agent 组合测试 |
| 证据升级仍可构成强进展 | 三来源等级与状态变化参数化测试 |
| 验证事实不丢失 | attempt、last evidence、audit 断言 |
| text-plus-tools 不持久化 | Agent handler 与 SQLite narrative 测试 |
| 内部工具配对保持 | 下一请求消息顺序和 call ID 测试 |
| 流式临时文本及时清除 | Controller update 顺序测试 |
| 最终回复只提交一次 | confirmed/committed 数量测试 |
| 不开放 WSL 或任意编译器 | CommandPolicy 回归和 allowlist 审计 |
| 不把 local integrity 称为编译 | instruction、报告与文档合同测试 |
| 交互边界不被未覆盖测试冒充 | instruction 与文档合同测试 |
| 不创建一次性诊断脚本绕过策略 | instruction 合同与端到端 prompt 测试 |
| 非零命令不显示为成功 | Node GUI `exit 1` 投影测试 |
| provider attempt 不继承长默认等待 | 两个 SDK factory timeout 测试 |
| 不提高预算或增加依赖 | 常量、依赖和 diff 审计 |
| 隐私边界保持 | JSONL、Session、repr 和敏感扫描 |
| 既有 provider 与安全行为保持 | 完整离线回归和 Windows 专项 |

## 12. 兼容性与局限

- 不需要 SQLite 或消息 schema 迁移。
- 旧 run 中已经持久化的过程叙述保留原样，避免审查范围外的数据重写。
- `confirmed_text_handler` 的含义收紧为“可提交的 tool-free 完整回复”；调用
  签名不变，但原先依赖每个 text-plus-tools 文本回调的内部测试必须更新。
- 本设计提高收敛确定性，但不提供 C/C++ 编译能力。用户仍需在 Agent 外运行
  `make`、项目规定的构建命令或未来单独批准的受控 C++ 验证工具。
- provider 如果在每一轮持续忽略明确指令，运行仍可能以 `no_progress` 结束；
  该失败会早于工具硬上限发生，并保留真实修改和准确的验证状态。
- 30 秒是 SDK 网络等待配置，不是完整 run SLA。现有瞬时错误重试和连续模型
  错误策略仍可能产生多次有界等待，但单个 provider attempt 不再继承 SDK 的
  长默认值。
- 通用 Agent 无法仅从“12 个测试通过”证明测试覆盖了所有用户交互。该边界由
  更严格的指令、真实 exit code 展示和最终报告诚实性控制；真正的自动交互
  验证需要未来单独批准的受控工具。

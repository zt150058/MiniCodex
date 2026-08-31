# Task29：目录修改能力与 Chat 流式兼容回退设计

## 1. 状态与背景

本设计覆盖四个已经复现的运行场景：

1. 在新目录中创建 C++ 项目时，模型连续调用 `write_file`，三个调用均因父目录不存在而被拒绝，随后错误地以 `consecutive_safety_rejections` 终止。
2. 已正确导入并选择 `receiving-code-review` Skill 后，第一次模型调用在没有文本或工具调用的情况下以 `invalid_model_response` 终止。
3. 请求在工作区根目录创建 `AGENTS.md` 时，第一次模型调用以相同方式终止。
4. 在 `read_only` 模式询问“你是谁家的模型”时，第一次模型调用仍以相同方式终止。
5. `AGENTS.md` 成功写入后，模型尝试读回文件和执行不受支持的验证形式；由于本地完整性验证只在无工具完成候选之后运行，所有后续工具均被 `verification_required` 拒绝，最终以 `changes_unverified` 结束且验证尝试数为 0。

审计证据表明，后三个场景都在第一个 main logical call 的第一个 provider attempt 中失败，失败前没有工具调用、修改或确认文本。Skill 场景已经证明 Skill 被正确发现、选择、冻结并注入；`AGENTS.md` 和只读问答场景没有选择 Skill，因此 Skill 不是共同根因。当前审计有意不保存 provider chunk 或响应正文，所以能够证明的是“Chat 流式结构被本地严格解析器拒绝”，不能安全断言是哪一个供应商字段损坏。

本设计不放宽现有严格解析器。它增加一个有限、可审计的传输兼容回退，并补齐创建目录这一缺失能力。

## 2. 目标

- 让 `modify` 运行能够确定性创建工作区内的新目录，再在其中创建文件。
- 保持 `write_file` 的 create-only、父目录必须已存在和不自动递归创建语义。
- 一次模型响应中的多个同类安全拒绝只消耗一次连续安全拒绝额度，给模型一次真实纠正机会。
- 为 `parent_not_found` 提供固定、可操作且不扩大权限的模型反馈。
- Chat Completions 流式响应在尚未公开文本时结构无效，可在同一 logical call 中自动执行一次同步请求。
- 在无强制验证命令且符合既有完整性回退条件时，于每个成功修改批次结束后立即产生新鲜本地完整性证据，使模型可以读回结果并稳定收敛。
- 保持 SDK 类型、原始 provider payload、凭据和异常正文位于适配器边界之外。
- 保持 Task8 路径安全、Task10 预算、Task11 验证新鲜度、Task19 流式持久化和 Task21/27 Skill 语义。

## 3. 非目标

- 不增加递归目录创建、目录删除、文件删除、移动、重命名、权限修改或任意 patch。
- 不允许模型创建 `.git/`、`.coding-agent/`、符号链接、junction 或 reparse point。
- 不根据提示词自动切换 `RunMode`、API mode 或预算档位。
- 不自动执行网络探测，不记录原始流式 chunk，不读取运行中进程的 API key。
- 不放宽同步或流式 Chat Completions 的消息、tool call、`call_id`、arguments、usage 或 finish reason 校验。
- 不对已经公开部分文本的损坏流执行同步回退。
- 不把本地完整性证据描述为测试、编译或程序行为验证，也不因提前取得完整性证据直接宣布运行成功。
- 不改变 Responses API 适配器、`ModelClient.complete(ModelRequest) -> ModelResponse`、消息类型或 ToolRegistry 公共分派接口。
- 不使 Skill 获得注册工具、执行脚本或扩大运行权限的能力。

## 4. 方案比较

### 4.1 目录创建

采用独立的 `create_directory` 工具，而不是让 `write_file` 自动创建父目录。

- 独立工具使每次目录修改都有明确工具调用、审计事实和修改账本记录。
- 单层创建保持失败原子性；父目录不存在时不会留下部分目录树。
- 模型可以在同一有序工具批次中先创建父目录，再创建子目录或文件。
- `write_file` 的已验收 create-only 语义保持不变。

拒绝的方案：让 `write_file` 自动递归创建父目录。该方案会把一个文件调用扩展成多个隐含修改，在文件写入失败时留下目录副作用，并模糊修改账本与安全审计。

### 4.2 连续安全拒绝

采用“按模型响应结算”的计数方式，而不是提高阈值。

- 一个响应中无论包含多少个安全拒绝调用，最多增加一次 `consecutive_safety_rejections`。
- 只有实际执行结果全部属于 `security_rejected:*` 且没有成功工具结果的批次才增加一次。
- 任一成功工具结果使该计数归零；混合普通工具错误的批次不伪装为纯安全拒绝批次。
- 每个工具调用仍生成独立、顺序稳定并以 `call_id` 配对的 `ToolResult`。
- 阈值继续保持 3，不通过扩大预算掩盖错误。

拒绝的方案：把阈值从 3 提高。它仍会让同一模型响应按兄弟调用数量消耗预算，并不能提供纠正机会。

### 4.3 Chat 流式结构无效

采用“无公开文本时恰好一次同步回退”，而不是放宽流式解析规则。

- 流式 provider attempt 仍由严格解析器处理。
- 若它以 `InvalidChatCompletionsResponseError`、SDK `APIResponseValidationError` 或 JSON 解码错误结束，并且本次 attempt 尚未成功向上层发送非空 `TEXT_DELTA`，适配器结束该失败 attempt 后领取下一次 provider attempt，发送同一 `ModelRequest` 的非流式请求。
- 同步回退最多发送一次；它不启动同步适配器原有的三次重试循环。
- 同步返回仍经过既有严格 `_parse_response`，可返回纯文本、一个或多个工具调用，或文本与工具调用组合。
- 流式过程中即使收到了尚未公开的 tool argument 片段，也没有工具被执行或持久化，因此仍允许丢弃片段并同步回退。
- 一旦任何文本 delta 已经公开，结构错误必须产生 `RESPONSE_DISCARDED` 并失败；不得同步回退或把两个响应拼接。
- `ModelOutputLimitError`、认证/权限/请求错误、回调错误、流清理错误、`KeyboardInterrupt` 和 `SystemExit` 不使用该回退。
- 若同步回退也返回非法结构，稳定抛出 `invalid_model_response`；若同步请求遇到 provider 错误，使用既有脱敏错误分类，但不再追加请求。
- 若共享 provider attempt 预算不允许下一次请求，则在 SDK 调用前由现有预算对象拒绝，计数器不得越界。

拒绝的方案一：接受空 call ID、变化的 ID、异常 finish reason 或 finish 后 chunk。它会把协议歧义带入 `call_id` 配对和工具执行边界。

拒绝的方案二：对所有 `invalid_model_response` 盲目重复三次流式请求。相同传输形态不会修复兼容性，并浪费 provider 预算。

### 4.4 修改后的验证触发时机

采用“成功修改批次结束后立即执行符合条件的本地完整性验证”，而不是继续依赖模型先返回无工具最终文本。

- 一个模型响应中的全部有序工具调用执行完成后，如果本批次至少产生一次 mutation、没有用户强制 `--verify`、当前没有已执行的模型或用户验证证据需要保持，并且 `VerificationGate.requires_local_integrity(state)` 为真，则立即执行一次现有本地完整性验证。
- 一次包含多个修改工具的响应只验证一次最终 mutation epoch，不在每个文件调用之间重复验证。
- 验证通过只更新 `last_verification`、`verification_status` 和 `validation_index`；Agent 仍保持运行，必须取得后续无工具完成文本才能进入 `SUCCESS`。
- 验证通过后的下一次主请求获得固定指令：当前修改已经通过本地完整性检查；若任务完成，应直接返回最终文本；若仍需修改，可以继续使用合法工具。
- 验证失败时保留现有失败证据并开放既有 repair read/mutation 流程，后续修改会使该证据过期。
- 如果已经存在真实模型或用户验证证据，后续 mutation 使它过期时不得降级为本地完整性检查；仍要求新的真实验证。
- 如果配置了用户强制验证命令，不在修改批次后自动执行它，也不用本地完整性替代它；既有完成候选和 `VerificationGate` 语义保持不变。
- 提前完整性验证与现有验证一样消耗一次工具额度和一次 verification attempt，并先通过时间、工具额度与验证保留规则。额度不足时不伪造证据，最终保持 `changes_unverified`。
- 取消和内部不变量检查继续优先；`KeyboardInterrupt`、`SystemExit` 不得被验证流程吞掉。

拒绝的方案一：只加强 `verification_required` 提示。真实运行已经表明目标 provider 会继续尝试读回或构造不受支持的验证命令，提示不能形成确定性保证。

拒绝的方案二：在下一次被拒绝的工具调用中隐式验证并重新执行该调用。这会让一个工具调用在本地悄然触发另一个操作，导致事件顺序、工具预算和失败语义难以解释。

## 5. 公共接口与锁定语义

### 5.1 `PathGuard.new_directory`

新增：

```python
PathGuard.new_directory(self, raw_path: object) -> GuardedPath
```

语义：

- `raw_path` 必须是非空工作区相对路径。
- 路径不得包含绝对路径、盘符、ADS、`..`、保留设备名、受保护组件或非法 Windows 尾缀。
- 目标不得已经存在，也不得是链接或 reparse point。
- 直接父目录必须已经存在、是普通目录、位于规范化工作区内且不经过 reparse point。
- 只验证并返回一个尚不存在的目标；不创建父目录，不递归。
- 路径冲突使用既有稳定 `SafetyCode`，不暴露绝对路径或 OS 异常正文。

### 5.2 `CreateDirectoryTool`

新增类：

```python
class CreateDirectoryTool:
    name = "create_directory"

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution: ...
```

strict schema 固定为：

```json
{
  "name": "create_directory",
  "description": "Create exactly one new directory whose parent already exists.",
  "strict": true,
  "parameters": {
    "type": "object",
    "properties": {
      "path": {"type": "string", "minLength": 1}
    },
    "required": ["path"],
    "additionalProperties": false
  }
}
```

执行语义：

- 使用 `PathGuard.new_directory` 完成功能性和安全校验。
- 使用单次非递归 `Path.mkdir()`，不使用 `parents=True` 或 `exist_ok=True`。
- 并发出现同名目标时拒绝，不能把已存在目录当作成功。
- 成功输出只包含规范化相对路径，并通过 `ToolResultMetadata.changed_paths=(relative_path,)` 记录修改。
- 失败不增加 mutation ledger，也不创建其他路径。

`modify` 注册表从六个工具扩展为七个：

1. `list_directory`
2. `read_file`
3. `create_directory`
4. `replace_text`
5. `write_file`
6. `run_command`
7. `run_java_tests`

`read_only` 仍精确保持 `list_directory`、`read_file`、`inspect_git`。

### 5.3 修改账本与本地完整性验证

- 成功 `create_directory` 与成功文件修改使用同一既有谓词：`result.status == "ok" and bool(result.metadata.changed_paths)`。
- 每个成功的目录创建调用只使 `mutation_index` 增加一次。
- `modified_paths` 按首次出现顺序去重，可同时包含目录和文件。
- 成功创建目录使既有验证证据变为 `STALE`。
- 内建完整性验证逐个用 `PathGuard.existing_entry` 解析 changed path：
  - 普通目录：确认仍位于工作区、不是 reparse point，并加入 `checked_paths`；不读取字节、不加入 `syntax_checked`。
  - 普通文件：保持现有 524,288 原始字节、UTF-8 和 Python/JSON/TOML 语法规则。
  - 其他类型、缺失路径或不安全路径：以稳定 `invalid_changed_path` 失败。
- 指定了 `--verify` 时，目录修改与文件修改一样只能由该命令的新鲜退出码 0 形成最终成功。
- 未指定 `--verify` 且没有过期真实验证证据时，每个成功修改批次结束后调用现有 `VerificationGate` 一次；一次批次无论修改多少路径都只验证最终 mutation epoch 一次。
- 提前完整性验证成功后 `validation_index == mutation_index`，但 `AgentStatus` 仍为 `RUNNING`；只有后续完成候选才能进入 `SUCCESS`。
- 如果批次已经通过可信 `run_command` 或 `run_java_tests` 产生当前 epoch 的新鲜证据，则不重复执行本地完整性验证。

### 5.4 安全拒绝批次结算

`AgentState` 不新增字段，`TerminationLimits.safety_rejection_limit` 仍为 3。

`AgentRunner` 在一个带工具调用的 `ModelResponse` 完成所有可执行调用后，再结算本轮安全计数：

- 实际执行的工具结果非空且全部是 `security_rejected:*`：计数加 1。
- 至少一个工具结果为 `ok`：计数归零。
- 其他组合：计数归零，普通工具错误继续按既有规则维护 `consecutive_tool_errors`。
- `agent_rejected:*` 的未执行配对结果不单独增加安全计数。
- 取消、硬预算或内部不变量导致批次中途终止时，保留已有配对和即时终止优先级，不伪造完整批次结算。

`parent_not_found` 的公开反馈固定指出：父目录不存在，应先按层调用 `create_directory`；本地代码不自动重写或执行模型调用。

### 5.5 Chat 同步回退

不修改 `StreamingModelClient`、`BudgetAwareStreamingModelClient`、`ModelClient` 或 `ModelResponse` 公共接口。回退仅实现于 `ChatCompletionsModelClient` 内部。

适配器增加私有的单次同步请求路径，复用同步请求映射、错误分类和 `_parse_response`，但不复用三次瞬时重试循环。外部 `complete()` 和 `complete_with_budget()` 保持原有最多三次瞬时请求语义。

一次逻辑调用的典型审计计数为：

1. logical call 开始；
2. provider attempt 1：`stream=True`，以 `invalid_model_response` 失败；
3. provider attempt 2：无 `stream` 字段的同步请求；
4. 同步解析成功后 logical call 成功。

该过程仍只有一个 logical call；两个物理请求都从同一个 run-scoped `ModelCallBudget` 领取额度。回退成功时不增加模型错误计数。

## 6. 数据流

### 6.1 新目录项目

```text
User task
  -> main model response
  -> create_directory("snake")
  -> PathGuard.new_directory
  -> mkdir once
  -> ToolResult(ok, changed_paths=("snake",))
  -> mutation_index + 1, verification stale
  -> write_file("snake/main.cpp", ...)
  -> existing write_file semantics
  -> one local integrity check for the completed mutation batch
  -> next model response returns final text
  -> SUCCESS uses the already-fresh evidence
```

### 6.2 流式结构无效

```text
AgentRunner logical call
  -> Chat stream attempt
  -> strict stream parser rejects before public TEXT_DELTA
  -> close stream best-effort
  -> record failed provider attempt
  -> one sync attempt under same budget
  -> strict sync parser
  -> ModelResponse
  -> normal Agent text/tool processing
```

## 7. 错误、安全与隐私

- 新工具继续通过 `ToolRegistry` 捕获 `SafetyViolation` 和 `ToolArgumentError`。
- 所有文件系统目标由 `PathGuard` 校验；模型文字不能授权路径。
- 创建目录不允许越过工作区、受保护目录或 reparse 边界。
- 回退请求不记录输入消息、系统指令、Skill 正文、`AGENTS.md` 正文、API key、Authorization header、SDK exception repr 或 provider body。
- JSONL 只记录现有 logical/provider attempt 元数据和稳定错误码；不增加原始 chunk 日志。
- 已公开文本永远不与同步响应拼接。发生错误时使用既有 discard 事件，临时 delta 不持久化。
- `KeyboardInterrupt` 和 `SystemExit` 继续传播；不捕获 `BaseException` 作为回退条件。

## 8. 实现文件地图

预计修改生产文件：

- `src/coding_agent/safety.py`：新增 `PathGuard.new_directory`。
- `src/coding_agent/tools/filesystem.py`：新增 `CreateDirectoryTool` 和 strict schema。
- `src/coding_agent/app.py`：只在 `modify` 注册表加入新工具。
- `src/coding_agent/instructions.py`：更新 modify 工具清单和逐层创建指引。
- `src/coding_agent/agent.py`：把连续安全拒绝改为响应级结算；在符合条件的成功修改批次结束后触发一次本地完整性验证，并为下一轮注入固定收敛提示。
- `src/coding_agent/verification.py`：让本地完整性验证接受安全目录 changed path；既有 eligibility 和证据构造接口保持不变。
- `src/coding_agent/chat_completions_client.py`：增加无公开文本时的一次同步回退。

预计修改测试文件：

- `tests/test_path_safety.py`
- `tests/tools/test_write_tools.py`
- `tests/test_app.py`
- `tests/test_instructions.py`
- `tests/test_agent_loop.py`
- `tests/test_verification.py`
- `tests/test_chat_completions_streaming_client.py`
- `tests/integration/test_chat_completions_agent.py`
- `tests/test_docs.py`

预计修改设计和公开文档：

- `DESIGN.md`
- `AGENTS.md`
- `TASKS.md`
- `README.md`
- `README.txt`
- `docs/USAGE.md`
- `docs/OPENAI_API.md`

不修改消息数据结构、ModelClient Protocol、Responses 适配器、Session schema、REST/SSE schema、GUI、依赖文件或 Task27 Skill 包格式。

当前工作区已有与本任务无关的 GUI 未提交修改：`src/coding_agent/web_static/app.js`、`index.html`、`styles.css`、`tests/js/web_gui.test.mjs`、`tests/test_web_gui.py`。Task29 不得修改、还原、暂存或提交这些文件；执行前必须由用户明确确认其归属并形成可审计基线。

## 9. 测试策略

所有生产行为严格执行 RED、最小 GREEN、相关回归：

### 9.1 目录安全和工具

- strict schema、额外参数和非法参数。
- 创建根下目录、在已存在父目录中创建子目录。
- 拒绝缺失父目录、现有文件/目录、父路径为文件、绝对路径、`..`、受保护目录。
- Windows symlink、junction、reparse point 目标或父路径拒绝。
- 竞争导致目标已存在时无伪成功、无修改账本。
- 不递归、不自动创建父目录、不覆盖。

### 9.2 修改与验证

- 目录成功使 mutation 增加一次、路径去重并使验证过期。
- 同一批次先目录后文件按顺序成功。
- 目录-only 完成候选通过本地完整性验证；目录加 Python/JSON/TOML 文件保持原语法规则。
- 目录缺失、变成不安全路径或变成非文件非目录条目时完整性失败。
- `--verify` 仍覆盖本地完整性回退。
- 一个响应写入多个文件时只在批次末验证一次，验证索引等于最终 mutation index。
- 提前完整性验证通过后状态仍为运行中，下一次无工具文本才进入成功。
- 提前完整性验证失败后允许 repair read；修复 mutation 使失败证据过期并产生新的合格验证。
- 已有真实验证因后续 mutation 过期时不降级为本地完整性。
- 强制 `--verify` 不在每个修改批次后自动运行，也不被本地完整性替代。
- 工具或时间预算不足、取消和内部错误不产生虚假完整性证据。

### 9.3 安全计数

- 一个响应内三个 `parent_not_found` 结果只增加一次安全拒绝计数，并允许下一次纠正模型响应。
- 三个连续、独立的纯安全拒绝响应仍在第三次终止。
- 成功结果重置计数。
- 混合成功与安全拒绝不提前终止。
- 每个调用的 `call_id` 和 ToolResult 顺序保持完整。

### 9.4 Chat 回退

- 首个流式 chunk 结构非法且无文本时，调用顺序严格为一次 stream、一次 sync。
- 流式工具 ID、名称、arguments 或 finish 结构非法且无公开文本时使用同一回退。
- 同步回退可解析纯文本、单工具、多工具以及文本与工具组合。
- 回退只消耗一个 logical call 和两个 provider attempts，不记录延迟，不超过共享预算。
- 同步回退非法时稳定失败，不发第三个请求。
- provider 预算只剩流式一次时，不调用同步 SDK。
- 已公开文本后无回退，产生 discard 且部分文本不持久化。
- callback error、output limit、认证/请求错误、`KeyboardInterrupt`、`SystemExit` 不回退。
- 未启用 streaming 的 Task9/15 同步三次瞬时重试语义保持不变。

### 9.5 四个用户场景

- Fake SDK 驱动的“新目录 C++ 项目”先目录后文件场景。
- 非空 Skill 指令快照下，非法 stream 后同步响应可继续。
- 工作区不存在 `AGENTS.md` 时，非法 stream 后同步工具调用创建根文件并验证。
- `read_only` 模式简单问答在非法 stream 后同步文本进入 `ANSWERED`。
- FakeModelClient 驱动的 `AGENTS.md` 写入—立即完整性验证—读回—最终文本流程，不再出现 `verification_required` 循环。

## 10. 验收矩阵

| 要求 | 证据 |
|---|---|
| 可创建一个安全新目录 | PathGuard 与 CreateDirectoryTool 定向测试 |
| 不递归且父目录必须存在 | 缺失父目录和多层路径 RED/GREEN |
| 不扩大工作区和 reparse 权限 | Windows 路径安全专项 |
| 目录修改进入账本 | Agent mutation 测试 |
| 目录可接受本地完整性验证 | VerificationGate 测试 |
| 修改批次结束后立即产生合格完整性证据 | Agent 批次验证与事件顺序测试 |
| 提前验证不直接宣布成功 | RUNNING → 最终文本 → SUCCESS 状态测试 |
| 强制命令和过期真实证据不被降级 | VerificationGate/Agent 反例测试 |
| 单响应多个安全拒绝只计一次 | Agent 多工具批次测试 |
| 三个独立拒绝响应仍终止 | Termination/Agent 边界测试 |
| `parent_not_found` 给出固定纠正 | Registry/Agent 结果断言 |
| 无文本非法 stream 恰好一次 sync | Chat streaming fake SDK 调用记录 |
| 已有公开文本绝不回退 | discard 与调用次数测试 |
| logical/provider 计数无越界 | ModelCallBudget observer 断言 |
| Skill、AGENTS 和只读问答恢复 | Chat Agent/应用集成测试 |
| Responses 行为不变 | OpenAI Responses 全回归 |
| 默认测试完全离线 | fake SDK、网络/凭据扫描 |
| 无新依赖或 Agent 框架 | `pyproject.toml` 和 import 扫描 |
| 文档只描述已验证能力 | `tests/test_docs.py` 与全文审查 |

## 11. 局限性

- 同步回退提升的是目标 Chat endpoint 的传输兼容性，不证明该 endpoint 完全符合 OpenAI Chat Completions 协议。
- 如果同步响应本身也缺失标准 tool call ID、arguments 或消息结构，运行仍会安全失败。
- `create_directory` 只创建一层；多层目录需要模型按父到子的顺序调用多次。
- 本地完整性验证只证明目录和文本路径结构有效；它不证明 C/C++ 已编译或程序行为正确。
- 对多轮修改，每个符合条件的成功修改批次最多增加一次本地完整性验证尝试；这是确定性收敛成本，不是测试执行次数。
- 工具仍在可信工作区内执行，不构成操作系统级沙箱。

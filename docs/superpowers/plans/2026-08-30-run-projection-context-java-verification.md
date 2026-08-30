# Run Projection, Adaptive Context, and Java Verification Implementation Plan

> **For implementation:** REQUIRED SKILL: Use `superpowers:executing-plans` to
> implement this plan task-by-task. Use subagents only if a later direct user
> instruction explicitly authorizes them. Steps use checkbox (`- [ ]`) syntax
> for tracking.

**Goal:** Render only the final assistant answer per run, make context compression adapt to hard budgets, and add a safe dedicated Java black-box verification tool.

**Architecture:** Keep session/audit data unchanged and correct only the browser's run-aware projection. Keep `ContextManager.prepare()` public behavior provider-neutral while selecting the largest fitting suffix of complete turns with at most one summary-model call. Add `run_java_tests` behind the existing `ToolRegistry`, `PathGuard`, process executor, mutation ledger, and `VerificationGate` without admitting Java command strings to `run_command`.

**Tech Stack:** Python 3.11+, standard library, pytest, vanilla JavaScript, Node.js built-in `node:test`, Windows `javac.exe`/`java.exe`, existing FastAPI/OpenAI dependencies unchanged.

**Spec:** `docs/superpowers/specs/2026-08-30-run-projection-context-java-verification-design.md`

## Global Constraints

- Execute on Windows in the current main workspace; do not create a branch or worktree unless a later direct user instruction explicitly authorizes it.
- Do not dispatch a subagent or parallel agent unless the user explicitly grants that authority for the execution turn.
- Do not stage, commit, push, pull, fetch, or access a remote repository without a later direct user instruction.
- Preserve the approved Task 23 modifications already present in `src/coding_agent/chat_completions_client.py`, `src/coding_agent/logging.py`, `src/coding_agent/web_static/app.js`, `tests/js/web_gui.test.mjs`, `tests/test_chat_completions_streaming_client.py`, and `tests/test_logging.py`.
- Stop at Task 0 if the current dirty baseline differs from the user-reviewed Task 23 changes or has not been committed or explicitly authorized as the exact baseline.
- Add no dependency and do not modify `pyproject.toml`.
- Do not call a real model API, read a real API key, or access the network in tests.
- Keep `ModelClient.complete(ModelRequest) -> ModelResponse`, Agent/session/message/provider interfaces, REST/SSE schemas, and existing tool schemas unchanged.
- Keep `run_command` unable to authorize `java`, `javac`, PowerShell, cmd, Bash, WSL, package managers, network tools, or arbitrary programs.
- All Java paths selected by the model pass through `PathGuard`; all Java child processes use trusted absolute executable paths, `shell=False`, fixed workspace cwd, sanitized environment, bounded streams, one monotonic suite deadline, and Windows process-tree termination.
- Input fixtures are limited to 262,144 raw bytes; expected-output fixtures are limited to 65,536 raw bytes, with the exact limit accepted.
- The Java suite may contain at most 500 source files and 200 complete `.in`/`.out` pairs.
- Compilation plus all test cases use `min(context.command_timeout_seconds, 60.0)` and prevent the first operation whose remaining time is not positive.
- Task 24 remains `进行中` after implementation verification until the user performs manual review; do not start another milestone.
- The target workspace `D:\code\software_system` is read-only during automated implementation. README creation there is a later user-observed GUI smoke test.

---

## File Map

### New production and test files

- Create `src/coding_agent/tools/java.py`: strict schema, safe discovery, trusted compile/run orchestration, comparison, result JSON, deadline, and cleanup.
- Create `tests/tools/test_java_tool.py`: Java tool unit, Windows safety, executor, output, timeout, cleanup, and real-JDK smoke tests.
- Create `tests/integration/test_java_agent.py`: offline README mutation plus fresh Java verification through the real Agent loop.

### Existing production files modified

- Modify `src/coding_agent/web_static/app.js`: run-aware final-message and one-card live projection.
- Modify `src/coding_agent/context.py`: adaptive complete-turn compression loop.
- Modify `src/coding_agent/safety.py`: `JavaRuntime`, `JavaRuntimePolicy`, and sanitized trusted-executable lookup reuse.
- Modify `src/coding_agent/tools/shell.py`: optional binary stdin and Java injection-variable removal.
- Modify `src/coding_agent/verification.py`: exact Java evidence decoder and observer branch.
- Modify `src/coding_agent/app.py`: register one `RunJavaTestsTool` with the shared command executor.

### Existing tests modified

- Modify `tests/js/web_gui.test.mjs`: live, replayed, successful, failed, and interrupted projection tests.
- Modify `tests/test_context.py`: observed item-budget regression, adaptive expansion, call count, pairing, and continuation tests.
- Modify `tests/test_command_safety.py`: Java runtime trust and unchanged command-policy denial tests.
- Modify `tests/tools/test_shell_tool.py`: file-backed stdin and Java environment stripping tests.
- Modify `tests/test_verification.py`: Java evidence, freshness, failure, malformed output, and required-command precedence tests.
- Modify `tests/test_app.py`: six-tool composition and shared executor test.
- Modify `tests/test_docs.py`: six-tool public documentation contract.

### Approved baseline and public documentation modified

- Modify `AGENTS.md`: replace the obsolete five-tool/Python-only clauses and list the already-approved dependency set.
- Modify `DESIGN.md`: record adaptive recent-turn behavior and the dedicated Java verification boundary.
- Modify `TASKS.md`: close the accepted Task 23 baseline and add Task 24 as the only in-progress item.
- Modify `README.txt`, `README.md`, and `docs/USAGE.md` only after production and focused tests are green.

### Files that must remain unchanged

- `src/coding_agent/messages.py`
- `src/coding_agent/model.py`
- `src/coding_agent/state.py`
- `src/coding_agent/agent.py`
- `src/coding_agent/config.py`
- `src/coding_agent/cli.py`
- `src/coding_agent/tools/base.py`
- `src/coding_agent/tools/registry.py`
- `src/coding_agent/openai_client.py`
- `src/coding_agent/chat_completions_client.py`, except for preserving the pre-existing reviewed Task 23 diff
- `src/coding_agent/session*.py`
- `src/coding_agent/web.py`
- `src/coding_agent/web_cli.py`
- `pyproject.toml`

Stop and return to design review if implementation requires changing any protected interface or file beyond the locked map.

---

### Task 0: Establish the accepted baseline and synchronize project guidance

**Files:**
- Modify: `AGENTS.md`
- Modify: `DESIGN.md`
- Modify: `TASKS.md`
- Read: all files listed in the spec and this plan

**Interfaces:**
- Consumes: the approved design spec and current Task 1-23 implementation.
- Produces: one unambiguous Task 24 baseline in which the approved Java tool is permitted without weakening `run_command`.

- [ ] **Step 1: Re-read the complete baseline and inspect Git without mutation**

Run from `D:\code\coding_agent`:

```powershell
Get-Content -Raw AGENTS.md
Get-Content -Raw DESIGN.md
Get-Content -Raw TASKS.md
Get-Content -Raw docs/superpowers/specs/2026-08-30-run-projection-context-java-verification-design.md
Get-Content -Raw docs/superpowers/plans/2026-08-30-run-projection-context-java-verification.md
git rev-parse --show-toplevel
git branch --show-current
git log -5 --oneline
git status --short --untracked-files=all
git diff --check
```

Expected:

- repository root is `D:/code/coding_agent` and branch is `main`;
- whitespace check exits `0`;
- Task 23 reviewed changes and the approved plan/spec are the only permitted differences;
- if the worktree is not clean, the user has explicitly authorized the exact displayed paths as the execution baseline.

Stop without editing if any extra path appears.

- [ ] **Step 2: Run the complete Task 1-23 baseline**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/js/web_gui.test.mjs
.\.venv\Scripts\python.exe -m pip check
```

Expected: every command exits `0`; record actual passed, failed, skipped, warning, and Node test counts. Any failure invokes `superpowers:systematic-debugging` before a code change.

- [ ] **Step 3: Synchronize `AGENTS.md` with already-approved reality**

Make these exact policy changes:

```markdown
- The model-facing tool set exposes `list_directory`, `read_file`,
  `replace_text`, `write_file`, `run_command`, and the dedicated
  `run_java_tests` black-box verification tool.
- `run_command` retains its Python and read-only Git allowlist. Java compiler
  and runtime commands are constructed only inside `run_java_tests`; model
  command strings cannot invoke them.
- The approved production dependencies are `openai`, `fastapi`, and `uvicorn`.
- The approved test dependencies are `pytest` and `httpx`.
- `run_java_tests` introduces no new dependency and may not download a JDK.
```

Delete the obsolete statements that the project has only five tools, only
Python verification, and only `openai`/`pytest` as the complete current
dependency set. Do not loosen any framework, credential, path, shell, remote,
or approval rule.

- [ ] **Step 4: Synchronize `DESIGN.md` before production edits**

Apply these exact architectural changes:

```markdown
- Add `tools/java.py` to the module table as the owner of strict Java source
  discovery, fixture pairing, compile/run orchestration, comparison, and safe
  structured results.
- In context management, describe eight recent turns as the preferred suffix,
  one newest complete turn as the hard minimum, one summary-model request as
  the maximum, deterministic expansion with local fallback, and continuation
  clearing after successful compression.
- Add `run_java_tests(source_root, main_class, tests_directory, purpose)` to
  the tool section with 500 sources, 200 pairs, 256 KiB input, 64 KiB expected
  output, exact comparison after newline normalization, and a 60-second suite
  maximum.
- State that `run_command` remains Python/read-only-Git only; Java uses trusted
  absolute executables behind the dedicated tool.
- In the no-`--verify` branch, accept either an existing credible
  `run_command` result or internally consistent `run_java_tests` verification
  evidence fresh for the current mutation index.
- State that the Java feature is a trusted-workspace execution boundary, not
  an operating-system sandbox or general Maven/Gradle/JUnit runner.
```

Also update the dependency paragraph to the already-approved current
`openai`, `fastapi`, and `uvicorn` production set and `pytest`/`httpx` test set.

- [ ] **Step 5: Add Task 24 and make it the only active task**

Change Task 23 from `进行中` to `已完成`, then append this exact task before the
completion rules:

```markdown
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

`进行中`
```

Run:

```powershell
rg -n "\*\*当前状态\*\*|`进行中`" TASKS.md
```

Expected: Task 24 is the only task whose next status line is `进行中`.

- [ ] **Step 6: Check the guidance-only diff**

```powershell
git diff --check -- AGENTS.md DESIGN.md TASKS.md
git diff -- AGENTS.md DESIGN.md TASKS.md
```

Expected: exit `0`; only the exact approved Java/context/projection guidance,
actual dependency correction, and Task 23/24 status transition appear. Do not
stage or commit.

---

### Task 1: Make GUI conversation rendering run-aware

**Files:**
- Modify: `tests/js/web_gui.test.mjs`
- Modify: `src/coding_agent/web_static/app.js`

**Interfaces:**
- Consumes: durable event fields `run_id`, `sequence`, `kind`, `data`; durable run fields `run_id`, `status`, `termination_reason`.
- Produces: internal GUI projection only; no REST, SSE, session, or Agent interface changes.

- [ ] **Step 1: Write RED tests for terminal projection by `run_id`**

Add tests using the existing `controllerFixture()` and fake API shape:

```javascript
test("successful runs render only their last confirmed assistant text", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Done", status: "succeeded", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "Done", status: "succeeded", last_run_id: "r1" },
      runs: [{ run_id: "r1", status: "succeeded", termination_reason: "completed" }],
      events: [
        { run_id: "r1", sequence: 1, kind: "user_message", data: { content: "Create README" } },
        { run_id: "r1", sequence: 2, kind: "assistant_text_committed", data: { content: "I will inspect more files" } },
        { run_id: "r1", sequence: 3, kind: "assistant_text_committed", data: { content: "README created and verified" } },
      ],
      skill_ids: [],
    }),
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();
  elements.sessionList.dispatchEvent({ type: "click", target: findElements(elements.sessionList, "button")[0] });
  await controller.whenIdle();
  assert.equal(elements.conversationLog.textContent.includes("I will inspect"), false);
  assert.equal(elements.conversationLog.textContent.includes("README created and verified"), true);
  assert.equal(findElements(elements.conversationLog, "article").length, 2);
  controller.destroy();
});

test("failed and interrupted runs hide committed process narration", async () => {
  for (const status of ["failed", "interrupted"]) {
    const { document, elements } = controllerFixture();
    const api = terminalProjectionApi(status, "process text must disappear");
    const controller = gui.createUiController({ document, elements, api });
    await controller.initialize();
    elements.sessionList.dispatchEvent({ type: "click", target: findElements(elements.sessionList, "button")[0] });
    await controller.whenIdle();
    assert.equal(elements.conversationLog.textContent.includes("process text must disappear"), false);
    assert.equal(findElements(elements.conversationLog, "div").filter(
      (element) => element.classList.contains("activity-card"),
    ).length, 1);
    controller.destroy();
  }
});
```

Define `terminalProjectionApi(status, text)` directly above the second test. It
must return one run and events with matching `run_id`, including one user event
and two committed assistant events. Use `termination_reason="model_error_limit"`
for failed and `"user_interrupted"` for interrupted.

- [ ] **Step 2: Run RED terminal tests**

```powershell
node --test --test-name-pattern="successful runs render|failed and interrupted runs hide" tests/js/web_gui.test.mjs
```

Expected: exit `1`; the successful-run assertion finds the first narration and
the failed/interrupted assertion finds committed narration. The failure must
not be a syntax, import, fixture, or DOM-harness error.

- [ ] **Step 3: Implement the minimal terminal projection**

Inside `createUiController`, add internal projection helpers with these exact
contracts:

```javascript
function runProjectionFacts(detail) {
  const runsById = new Map((detail?.runs ?? []).map((run) => [run.run_id, run]));
  const lastAssistantSequence = new Map();
  const lastEventSequence = new Map();
  for (const event of detail?.events ?? []) {
    if (typeof event.run_id !== "string") continue;
    lastEventSequence.set(event.run_id, event.sequence);
    if (event.kind === "assistant_text_committed") {
      lastAssistantSequence.set(event.run_id, event.sequence);
    }
  }
  return { runsById, lastAssistantSequence, lastEventSequence };
}
```

Replace the event loop in `renderConversation()` so that it:

1. always renders valid `user_message` content;
2. renders `assistant_text_committed` only when its run is `succeeded` and its
   sequence equals `lastAssistantSequence.get(event.run_id)`;
3. renders one `run_failed` or `run_interrupted` card after the last event for
   each terminal failed/interrupted run;
4. tracks rendered terminal run IDs and appends one fallback card for a terminal
   run with no persisted events;
5. removes the old selected-run-only terminal-card block.

All text continues through `appendMessage()` or `appendActivity()` and therefore
uses text nodes rather than `innerHTML`.

- [ ] **Step 4: Run GREEN terminal tests and GUI regression**

```powershell
node --test --test-name-pattern="successful runs render|failed and interrupted runs hide" tests/js/web_gui.test.mjs
node --test tests/js/web_gui.test.mjs
```

Expected: both commands exit `0`; report actual Node test counts.

- [ ] **Step 5: Write RED tests for one live activity surface**

Replace the existing expectation that provisional text creates a second
assistant element, then add this reducer test:

```javascript
test("live narration and tool activity replace one another in one card", () => {
  const state = gui.createInitialUiState();
  state.activeRunId = "r1";
  state.selectedSession = {
    session: { session_id: "s1", status: "running", last_run_id: "r1" },
    runs: [{ run_id: "r1", status: "running" }],
    events: [],
  };
  gui.reduceSessionUpdate(state, reducerFrame(1, "assistant_text_delta", { content: "Inspecting" }));
  assert.equal(state.provisionalText, "Inspecting");
  assert.deepEqual(state.activities, []);
  gui.reduceSessionUpdate(state, reducerFrame(2, "assistant_text_committed", { content: "Inspecting" }));
  assert.equal(state.provisionalText, "Inspecting");
  assert.equal(state.selectedSession.events[0].run_id, "r1");
  gui.reduceSessionUpdate(state, reducerFrame(3, "tool_started", { tool_name: "read_file", ordinal: 1 }));
  assert.equal(state.provisionalText, "");
  assert.equal(state.activities[0].kind, "tool_started");
  gui.reduceSessionUpdate(state, reducerFrame(4, "assistant_text_delta", { content: "Writing final answer" }));
  assert.deepEqual(state.activities, []);
  assert.equal(state.provisionalText, "Writing final answer");
});
```

Add this object helper beside the existing string-producing `updateFrame`; do
not change the SSE helper or wire contract:

```javascript
function reducerFrame(id, kind, data, runId = "r1") {
  return {
    id,
    event: kind,
    data: {
      schema_version: 1,
      session_id: "s1",
      run_id: runId,
      sequence: id,
      kind,
      created_at_utc: "2026-08-30T00:00:00.000000Z",
      data,
    },
  };
}
```

- [ ] **Step 6: Run RED live-projection tests**

```powershell
node --test --test-name-pattern="one live card|live narration and tool activity" tests/js/web_gui.test.mjs
```

Expected: exit `1`; current code leaves a provisional assistant message beside
the activity card, clears confirmed narration, fails to persist live `run_id`,
or keeps obsolete activity when new text starts.

- [ ] **Step 7: Implement one live activity card**

Make these exact state transitions:

```javascript
// assistant_text_delta
state.activities = [];
state.provisionalText += payload.content;

// assistant_text_committed
state.provisionalText = payload.content;
state.selectedSession?.events?.push({
  run_id: frame.data?.run_id ?? state.activeRunId,
  sequence: frame.id,
  kind: frame.event,
  data: { content: payload.content },
});

// tool/verification/controller activity
state.provisionalText = "";
state.activities = [{ kind: frame.event, data: safeActivityData(frame.event, payload) }];

// terminal lifecycle
state.provisionalText = "";
state.activities = [];
```

Add UI-only `model_progress: "Agent 正在处理"` to `ACTIVITY_LABELS`. In
`safeActivityDetails()`, return `[data.content]` for `model_progress`. At the end
of `renderConversation()`, use an exclusive branch:

```javascript
if (currentActivity) {
  appendActivity(document, elements.conversationLog, currentActivity.kind, currentActivity.data);
} else if (state.activeRunId && state.provisionalText) {
  appendActivity(document, elements.conversationLog, "model_progress", {
    content: state.provisionalText,
  });
}
```

Delete the provisional assistant-message branch. Do not add a new backend event
kind.

- [ ] **Step 8: Run GREEN and GUI regression**

```powershell
node --test --test-name-pattern="one live card|live narration and tool activity" tests/js/web_gui.test.mjs
node --test tests/js/web_gui.test.mjs
.\.venv\Scripts\python.exe -m pytest tests/test_web_gui.py tests/test_web_sse.py tests/test_session_events.py -q
```

Expected: all commands exit `0`; one active surface is rendered, replay remains
stable, and Python transport/session contracts have no regression.

---

### Task 2: Make context compression adapt to hard budgets

**Files:**
- Modify: `tests/test_context.py`
- Modify: `src/coding_agent/context.py`

**Interfaces:**
- Consumes: existing `ContextManager.prepare(state, budget)`, complete-turn partition, summary parser, fallback, and model budget.
- Produces: the same `PreparedContext` type with adaptive removal and unchanged no-compression behavior.

- [ ] **Step 1: Write the exact observed item-budget RED test**

Add this helper and test:

```python
def make_eight_multi_tool_turns(tmp_path: Path, calls_per_turn: int) -> AgentState:
    state = AgentState.start("task", tmp_path, 0.0)
    for turn_number in range(8):
        append_tool_turn(
            state,
            turn_number=turn_number,
            call_count=calls_per_turn,
        )
    return state


def test_item_limit_compresses_even_with_only_eight_complete_turns(
    tmp_path: Path,
) -> None:
    state = make_eight_multi_tool_turns(tmp_path, calls_per_turn=2)
    assert len(state.messages) == 25
    client = FakeModelClient((valid_summary_response(),))
    prepared = manager(
        client,
        max_serialized_chars=1_000_000,
        max_history_items=24,
        recent_turns=8,
    ).prepare(state, ModelCallBudget())
    assert prepared.compressed is True
    assert prepared.summary_source is SummarySource.MODEL
    assert len(client.requests) == 1
    assert prepared.size.history_items <= 24
    assert prepared.messages[2:] == state.messages[4:]
```

The first tool turn has one assistant plus two results, so removing exactly that
complete turn changes 25 original items into initial task + summary + 21 retained
items.

- [ ] **Step 2: Run RED observed regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_context.py::test_item_limit_compresses_even_with_only_eight_complete_turns -q
```

Expected: exit `1` with `ContextPreparationError` reason
`context_budget_exhausted`; no syntax or fixture failure.

- [ ] **Step 3: Implement the first adaptive candidate**

Replace the fixed removable-count guard with:

```python
maximum_removable = len(turns) - 1
if maximum_removable <= 0:
    raise ContextPreparationError(
        TerminationReason.CONTEXT_BUDGET_EXHAUSTED
    )
first_removable = min(
    maximum_removable,
    max(1, len(turns) - self._limits.recent_turns),
)
```

Use `first_removable` for the existing single model summary attempt. Do not yet
add a second model call or alter exception propagation.

- [ ] **Step 4: Run GREEN observed regression and context regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_context.py::test_item_limit_compresses_even_with_only_eight_complete_turns -q
.\.venv\Scripts\python.exe -m pytest tests/test_context.py -q
```

Expected: both exit `0`; report actual counts.

- [ ] **Step 5: Write RED tests for deterministic expansion without another provider call**

```python
def test_still_oversized_first_candidate_expands_with_local_fallback(
    tmp_path: Path,
) -> None:
    state = make_eight_multi_tool_turns(tmp_path, calls_per_turn=3)
    client = FakeModelClient((valid_summary_response(),))
    prepared = manager(
        client,
        max_serialized_chars=1_000_000,
        max_history_items=24,
        recent_turns=8,
    ).prepare(state, ModelCallBudget())
    assert len(client.requests) == 1
    assert prepared.compressed is True
    assert prepared.summary_source is SummarySource.FALLBACK
    assert prepared.summary_model_failed is False
    assert prepared.size.history_items <= 24
    initial, summary, *retained = prepared.messages
    assert initial is state.messages[0]
    assert isinstance(summary, UserMessage)
    assert tuple(retained) == state.messages[13:]


def test_expanded_compression_preserves_every_retained_tool_pair(
    tmp_path: Path,
) -> None:
    state = make_eight_multi_tool_turns(tmp_path, calls_per_turn=3)
    prepared = manager(
        FakeModelClient((valid_summary_response(),)),
        max_serialized_chars=1_000_000,
        max_history_items=24,
        recent_turns=8,
    ).prepare(state, ModelCallBudget())
    _, _, turns = _partition_complete_turns(prepared.messages)
    assert len(turns) == 5
    for turn in turns:
        assistant = turn[0]
        assert isinstance(assistant, AssistantMessage)
        assert [result.call_id for result in turn[1:]] == [
            call.call_id for call in assistant.tool_calls
        ]
```

With three calls per turn, each turn has four items. The first two removal
candidates remain above 24 items; removing the oldest three retains five turns
and fits exactly below the limit.

- [ ] **Step 6: Run RED expansion tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_context.py::test_still_oversized_first_candidate_expands_with_local_fallback tests/test_context.py::test_expanded_compression_preserves_every_retained_tool_pair -q
```

Expected: exit `1`; current implementation terminates after the first oversized
candidate.

- [ ] **Step 7: Implement candidate expansion**

After producing the first summary, iterate through every permitted removal
count without invoking the model again:

```python
for removable_turn_count in range(first_removable, maximum_removable + 1):
    candidate_removed = prefix + tuple(
        message
        for turn in turns[:removable_turn_count]
        for message in turn
    )
    if removable_turn_count == first_removable:
        candidate_summary = summary
        candidate_source = summary_source
        candidate_model_failed = summary_model_failed
    else:
        candidate_summary = _fallback_summary(state, candidate_removed)
        candidate_source = SummarySource.FALLBACK
        candidate_model_failed = summary_model_failed
    if len(candidate_summary.to_json()) > self._limits.max_summary_chars:
        raise ContextPreparationError(
            TerminationReason.CONTEXT_BUDGET_EXHAUSTED
        )
    retained_messages = tuple(
        message
        for turn in turns[removable_turn_count:]
        for message in turn
    )
    candidate_messages = (
        initial,
        _render_summary_message(candidate_summary),
        *retained_messages,
    )
    candidate_size = self.measure(candidate_messages)
    if (
        candidate_size.serialized_chars <= self._limits.max_serialized_chars
        and candidate_size.history_items <= self._limits.max_history_items
    ):
        return PreparedContext(
            messages=candidate_messages,
            continuation_items=(),
            size=candidate_size,
            compressed=True,
            summary_source=candidate_source,
            summary_model_failed=candidate_model_failed,
        )
raise ContextPreparationError(
    TerminationReason.CONTEXT_BUDGET_EXHAUSTED
)
```

Remove the previous single-candidate retained-message block. Keep the existing
`FatalModelError`, `ModelBudgetExceeded`, ordinary `ModelError`, validation,
fallback, and summary-size branches unchanged.

- [ ] **Step 8: Run GREEN expansion, BaseException, continuation, and complete context tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_context.py::test_still_oversized_first_candidate_expands_with_local_fallback tests/test_context.py::test_expanded_compression_preserves_every_retained_tool_pair -q
.\.venv\Scripts\python.exe -m pytest tests/test_context.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -q
```

Expected: all exit `0`; existing no-compression identity, fallback,
`FatalModelError`, budget, `KeyboardInterrupt`, `SystemExit`, continuation, and
Agent-loop tests remain green.

---

### Task 3: Add the reusable stdin seam and trusted Java runtime policy

**Files:**
- Modify: `tests/tools/test_shell_tool.py`
- Modify: `src/coding_agent/tools/shell.py`
- Modify: `tests/test_command_safety.py`
- Modify: `src/coding_agent/safety.py`

**Interfaces:**
- Consumes: `AuthorizedCommand`, `AuthorizedCommandExecutor`, `ExecutionContext`, `PathGuard`, `SafetyViolation`.
- Produces: backward-compatible
  `AuthorizedCommandExecutor.execute(command, context, *, stdin_stream: BinaryIO | None = None) -> ToolExecution`,
  `JavaRuntime`, and `JavaRuntimePolicy.resolve()`.

- [ ] **Step 1: Write RED tests for file-backed stdin and Java environment isolation**

Add to `tests/tools/test_shell_tool.py`:

```python
def test_authorized_executor_passes_file_backed_stdin(
    tmp_path: Path,
) -> None:
    script = tmp_path / "read-stdin.py"
    script.write_text(
        "import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read())\n",
        encoding="utf-8",
    )
    input_path = tmp_path / "case.in"
    input_path.write_bytes("输入\n".encode("utf-8"))
    argv = (sys.executable, str(script))
    command = AuthorizedCommand(
        argv=argv,
        normalized_command=subprocess.list2cmdline(argv),
        purpose="test",
        source=CommandSource.MODEL,
    )
    with input_path.open("rb") as stdin_stream:
        result = AuthorizedCommandExecutor().execute(
            command,
            ExecutionContext(tmp_path),
            stdin_stream=stdin_stream,
        )
    payload = json.loads(result.output or "")
    assert result.metadata.exit_code == 0
    assert payload["stdout"] == "输入\n"


def test_child_environment_removes_java_injection_variables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "CLASSPATH",
        "JAVA_TOOL_OPTIONS",
        "_JAVA_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "JDK_JAVAC_OPTIONS",
    ):
        monkeypatch.setenv(name, "workspace-injection-secret")
    observed: dict[str, object] = {}
    script = tmp_path / "ok.py"
    script.write_text("print('ok')\n", encoding="utf-8")

    def recording_factory(argv: tuple[str, ...], **kwargs: object):
        observed.update(kwargs)
        return subprocess.Popen(argv, **kwargs)  # type: ignore[arg-type]

    _execute_script(
        tmp_path,
        "print('ok')\n",
        tool=RunCommandTool(process_factory=recording_factory),
    )
    environment = observed["env"]
    assert isinstance(environment, dict)
    folded = {key.casefold() for key in environment}
    assert folded.isdisjoint(
        {
            "classpath",
            "java_tool_options",
            "_java_options",
            "jdk_java_options",
            "jdk_javac_options",
        }
    )
    assert "workspace-injection-secret" not in repr(environment)
```

- [ ] **Step 2: Run RED executor tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py::test_authorized_executor_passes_file_backed_stdin tests/tools/test_shell_tool.py::test_child_environment_removes_java_injection_variables -q
```

Expected: exit `1`; the executor rejects the unknown `stdin_stream` keyword and
the current child environment still contains the Java injection variables.

- [ ] **Step 3: Implement the minimal backward-compatible executor change**

In `src/coding_agent/tools/shell.py`:

```python
_REMOVED_ENVIRONMENT_KEYS = {
    # retain every existing key
    "classpath",
    "java_tool_options",
    "_java_options",
    "jdk_java_options",
    "jdk_javac_options",
}
```

Merge those five values into the existing set rather than replacing it. Change
only the executor signature and `Popen` argument:

```python
def execute(
    self,
    command: AuthorizedCommand,
    context: ExecutionContext,
    *,
    stdin_stream: BinaryIO | None = None,
) -> ToolExecution:
    # existing validation and setup
    process = self._process_factory(
        argv,
        shell=False,
        cwd=workspace,
        env=_child_environment(),
        stdin=subprocess.DEVNULL if stdin_stream is None else stdin_stream,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
```

Do not close `stdin_stream` in the executor; its caller owns it. Do not alter
the current output, timeout, reader, cleanup, or exception semantics.

- [ ] **Step 4: Run GREEN executor tests and shell regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py::test_authorized_executor_passes_file_backed_stdin tests/tools/test_shell_tool.py::test_child_environment_removes_java_injection_variables -q
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py tests/test_verification.py -q
```

Expected: both exit `0`; existing default `stdin is DEVNULL`, exact 64 KiB,
timeout, process-tree, nonzero-exit, and verification executor tests remain
green.

- [ ] **Step 5: Write RED tests for trusted Java runtime resolution**

Add imports for `JavaRuntimePolicy` and tests to `tests/test_command_safety.py`:

```python
def _fake_java_runtime(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace = tmp_path / "workspace"
    runtime = tmp_path / "runtime"
    workspace.mkdir()
    runtime.mkdir()
    javac = runtime / "javac.exe"
    java = runtime / "java.exe"
    javac.write_bytes(b"trusted compiler")
    java.write_bytes(b"trusted runtime")
    return workspace, javac, java


def test_java_runtime_policy_returns_only_resolved_external_executables(
    tmp_path: Path,
) -> None:
    workspace, javac, java = _fake_java_runtime(tmp_path)
    located = {"javac.exe": str(javac), "java.exe": str(java)}
    resolved = JavaRuntimePolicy(
        workspace,
        executable_locator=located.get,
    ).resolve()
    assert resolved.javac == javac.resolve(strict=True)
    assert resolved.java == java.resolve(strict=True)


def test_java_runtime_policy_rejects_workspace_shadow_executables(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for name in ("javac.exe", "java.exe"):
        (workspace / name).write_bytes(b"shadow")
    located = {
        "javac.exe": str(workspace / "javac.exe"),
        "java.exe": str(workspace / "java.exe"),
    }
    with pytest.raises(SafetyViolation) as caught:
        JavaRuntimePolicy(workspace, executable_locator=located.get).resolve()
    assert caught.value.code is SafetyCode.EXECUTABLE_DENIED


def test_model_command_policy_still_rejects_java_strings(tmp_path: Path) -> None:
    for command in ("java.exe Main", "javac.exe src\\Main.java"):
        with pytest.raises(SafetyViolation) as caught:
            CommandPolicy(tmp_path).authorize(
                command,
                purpose="test",
                source=CommandSource.MODEL,
            )
        assert caught.value.code is SafetyCode.EXECUTABLE_DENIED
```

Add one parametrized case in which either locator result is `None`; it must
raise `SafetyViolation` with `SafetyCode.EXECUTABLE_DENIED` and public message
`trusted Java runtime is unavailable`.

- [ ] **Step 6: Run RED runtime-policy tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_command_safety.py -k "java_runtime_policy or still_rejects_java" -q
```

Expected: exit `1` because `JavaRuntimePolicy` and `JavaRuntime` do not exist;
the failure must not arise from file setup or an existing command-policy test.

- [ ] **Step 7: Implement `JavaRuntime` and `JavaRuntimePolicy`**

Add to `src/coding_agent/safety.py`:

```python
@dataclass(frozen=True, slots=True)
class JavaRuntime:
    javac: Path
    java: Path


class JavaRuntimePolicy:
    def __init__(
        self,
        workspace: Path,
        *,
        executable_locator: ExecutableLocator | None = None,
    ) -> None:
        self._paths = PathGuard(workspace)
        self._executable_locator = (
            self._locate_from_sanitized_path
            if executable_locator is None
            else executable_locator
        )

    @property
    def workspace(self) -> Path:
        return self._paths.workspace

    def _locate_from_sanitized_path(self, name: str) -> str | None:
        return _locate_from_sanitized_path(self.workspace, name)

    def _trusted(self, name: str) -> Path:
        located = self._executable_locator(name)
        if located is None:
            raise SafetyViolation(
                SafetyCode.EXECUTABLE_DENIED,
                "trusted Java runtime is unavailable",
            )
        try:
            resolved = Path(located).resolve(strict=True)
        except OSError:
            raise SafetyViolation(
                SafetyCode.EXECUTABLE_DENIED,
                "trusted Java runtime is unavailable",
            ) from None
        try:
            common = os.path.commonpath((str(self.workspace), str(resolved)))
        except ValueError:
            common = ""
        if (
            not resolved.is_file()
            or resolved.name.casefold() != name.casefold()
            or os.path.normcase(common) == os.path.normcase(str(self.workspace))
        ):
            raise SafetyViolation(
                SafetyCode.EXECUTABLE_DENIED,
                "trusted Java runtime is unavailable",
            )
        return resolved

    def resolve(self) -> JavaRuntime:
        return JavaRuntime(
            javac=self._trusted("javac.exe"),
            java=self._trusted("java.exe"),
        )
```

Extract the body of `CommandPolicy._locate_from_sanitized_path()` into the
module-level function:

```python
def _locate_from_sanitized_path(workspace: Path, name: str) -> str | None:
    runtime_directory = Path(sys.executable).resolve(strict=True).parent
    accepted_entries: list[str] = []
    for raw_entry in os.environ.get("PATH", "").split(os.pathsep):
        if not raw_entry:
            continue
        entry = Path(raw_entry)
        if not entry.is_absolute():
            continue
        try:
            resolved = entry.resolve(strict=True)
        except OSError:
            continue
        try:
            common = os.path.commonpath((str(workspace), str(resolved)))
        except ValueError:
            common = ""
        inside_workspace = os.path.normcase(common) == os.path.normcase(
            str(workspace)
        )
        if inside_workspace and os.path.normcase(str(resolved)) != os.path.normcase(
            str(runtime_directory)
        ):
            continue
        accepted_entries.append(str(resolved))
    return shutil.which(name, path=os.pathsep.join(accepted_entries))
```

Make `CommandPolicy._locate_from_sanitized_path()` return that helper's result.
This is a behavior-preserving reuse; do not change `_trusted_launcher()` or
`authorize()`.

- [ ] **Step 8: Run GREEN policy tests and all safety regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_command_safety.py -k "java_runtime_policy or still_rejects_java" -q
.\.venv\Scripts\python.exe -m pytest tests/test_command_safety.py tests/test_path_safety.py tests/tools/test_shell_tool.py -q
```

Expected: all exit `0`; record skips separately and confirm Windows reparse
tests actually execute where the current machine supports them.

---

### Task 4: Implement strict Java discovery and result contracts

**Files:**
- Create: `tests/tools/test_java_tool.py`
- Create: `src/coding_agent/tools/java.py`

**Interfaces:**
- Consumes: `JSONObject`, `ToolResultMetadata`, `JavaRuntimePolicy`, `PathGuard`, `AuthorizedCommand`, `AuthorizedCommandExecutor`, `ExecutionContext`, `ToolArgumentError`, `ToolExecution`.
- Produces: `RunJavaTestsTool`, exact strict schema, deterministic source/case discovery, and safe result JSON.

- [ ] **Step 1: Write RED schema and argument tests**

Create `tests/tools/test_java_tool.py` with imports and this exact schema test:

```python
def test_run_java_tests_schema_is_strict() -> None:
    assert RunJavaTestsTool.name == "run_java_tests"
    assert RunJavaTestsTool.schema == {
        "name": "run_java_tests",
        "description": (
            "Compile Java sources and run paired input/output tests in the workspace."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "source_root": {"type": "string", "minLength": 1},
                "main_class": {"type": "string", "minLength": 1},
                "tests_directory": {"type": "string", "minLength": 1},
                "purpose": {"type": "string", "enum": ["test", "verification"]},
            },
            "required": [
                "source_root",
                "main_class",
                "tests_directory",
                "purpose",
            ],
            "additionalProperties": False,
        },
    }
```

Add one parametrized public `execute()` test with these exact invalid cases and
messages:

```python
INVALID_ARGUMENTS = (
    ({}, "arguments must contain exactly"),
    ({"source_root": "src", "main_class": "Main", "tests_directory": "tests", "purpose": "test", "extra": 1}, "arguments must contain exactly"),
    ({"source_root": "", "main_class": "Main", "tests_directory": "tests", "purpose": "test"}, "source_root must be a non-empty string"),
    ({"source_root": "src", "main_class": "9Main", "tests_directory": "tests", "purpose": "test"}, "main_class must be a valid Java qualified name"),
    ({"source_root": "src", "main_class": "Main", "tests_directory": "", "purpose": "test"}, "tests_directory must be a non-empty string"),
    ({"source_root": "src", "main_class": "Main", "tests_directory": "tests", "purpose": "inspect"}, "purpose must be test or verification"),
)
```

The test constructs an empty `tmp_path` and asserts `ToolArgumentError` before
runtime discovery or process execution.

- [ ] **Step 2: Run RED schema tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_java_tool.py -k "schema or invalid_arguments" -q
```

Expected: exit `1` with `ModuleNotFoundError` for
`coding_agent.tools.java`; no test syntax error.

- [ ] **Step 3: Add the module constants, protocols, value types, and validation**

Start `src/coding_agent/tools/java.py` with these locked definitions:

```python
_ARGUMENT_NAMES = {"source_root", "main_class", "tests_directory", "purpose"}
_MAIN_CLASS = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*")
_SOURCE_LIMIT = 500
_CASE_LIMIT = 200
_INPUT_LIMIT_BYTES = 256 * 1024
_EXPECTED_LIMIT_BYTES = 64 * 1024
_DIAGNOSTIC_LIMIT_BYTES = 8 * 1024
_SUITE_TIMEOUT_SECONDS = 60.0
_SHELL_OUTPUT_KEYS = {"argv", "cleanup_error", "purpose", "stderr", "stdout"}
_JAVA_OUTPUT_KEYS = {
    "case_count", "failed_case", "passed_count", "phase", "purpose",
    "safe_error_code", "source_count", "stderr", "stdout",
}


class JavaToolExecutionError(RuntimeError):
    """The trusted Java child result could not be used safely."""


class JavaCommandExecutor(Protocol):
    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
        *,
        stdin_stream: BinaryIO | None = None,
    ) -> ToolExecution: ...


class JavaTemporaryDirectory(Protocol):
    name: str
    def cleanup(self) -> None: ...


class JavaRuntimeResolver(Protocol):
    @property
    def workspace(self) -> Path: ...

    def resolve(self) -> JavaRuntime: ...


JavaRuntimePolicyFactory = Callable[[Path], JavaRuntimeResolver]
JavaTemporaryDirectoryFactory = Callable[[Path], JavaTemporaryDirectory]


@dataclass(frozen=True, slots=True)
class _JavaArguments:
    source_root: str
    main_class: str
    tests_directory: str
    purpose: str


@dataclass(frozen=True, slots=True)
class _JavaCase:
    case_id: str
    input_path: Path
    expected_path: Path


def _internal_reparse_point(path: Path) -> bool:
    try:
        result = os.lstat(path)
    except FileNotFoundError:
        return path.is_symlink()
    attributes = getattr(result, "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _ensure_internal_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        if _internal_reparse_point(path):
            raise SafetyViolation(
                SafetyCode.REPARSE_POINT_DENIED,
                "internal Java workspace is unavailable",
            )
        if not path.is_dir():
            raise SafetyViolation(
                SafetyCode.PATH_TYPE_MISMATCH,
                "internal Java workspace is unavailable",
            )
        return
    path.mkdir()
    if _internal_reparse_point(path) or not path.is_dir():
        raise SafetyViolation(
            SafetyCode.REPARSE_POINT_DENIED,
            "internal Java workspace is unavailable",
        )


def _create_temporary_directory(workspace: Path) -> JavaTemporaryDirectory:
    canonical = PathGuard(workspace).workspace
    internal = canonical / ".coding-agent"
    java_tests = internal / "java-tests"
    _ensure_internal_directory(internal)
    _ensure_internal_directory(java_tests)
    return tempfile.TemporaryDirectory(prefix="run-", dir=java_tests)
```

Implement `_validated_arguments(arguments: object) -> _JavaArguments` with the
exact messages asserted above. Add `RunJavaTestsTool.name`, `schema`, injected
constructor fields, and `execute()` delegation to a private `_execute()` method.
The constructor is exactly:

```python
def __init__(
    self,
    *,
    runtime_policy_factory: JavaRuntimePolicyFactory | None = None,
    executor: JavaCommandExecutor | None = None,
    clock: Callable[[], float] = time.monotonic,
    temporary_directory_factory: JavaTemporaryDirectoryFactory | None = None,
) -> None:
    self._runtime_policy_factory = (
        JavaRuntimePolicy if runtime_policy_factory is None else runtime_policy_factory
    )
    self._executor = AuthorizedCommandExecutor() if executor is None else executor
    self._clock = clock
    self._temporary_directory_factory = (
        _create_temporary_directory
        if temporary_directory_factory is None
        else temporary_directory_factory
    )
```

Validate that all three factories/callables are callable and that the executor
has a callable `execute`; invalid injected seams raise `TypeError` with stable
messages that contain no object `repr`. `_create_temporary_directory()`
canonicalizes the workspace, creates or validates `.coding-agent` and
`.coding-agent/java-tests` one level at a time, rejects an existing
non-directory/symlink/junction/reparse point, and owns only the unique `run-*`
child. Task 4 discovery tests inject `FakeTemporaryDirectory` so they never
create persistent repository state.
During this RED/GREEN slice, valid execution may reach path validation and
reject missing directories; do not return fabricated success.

- [ ] **Step 4: Run GREEN schema tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_java_tool.py -k "schema or invalid_arguments" -q
```

Expected: exit `0`; report actual parametrized case count.

- [ ] **Step 5: Write RED discovery tests through the public tool**

Add helpers that create `src/` and `tests/`, plus this aborting executor:

```python
class RecordingAbortExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[AuthorizedCommand, ExecutionContext, bytes | None]] = []

    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
        *,
        stdin_stream: BinaryIO | None = None,
    ) -> ToolExecution:
        payload = None if stdin_stream is None else stdin_stream.read()
        self.calls.append((command, context, payload))
        raise AssertionError("execution reached after valid discovery")
```

Inject a fake `JavaRuntimePolicy` factory that resolves two external temporary
executable files and a fake temporary-directory object whose `.name` points
under `workspace/.coding-agent/java-tests`. Accepted-boundary tests assert the
stable `AssertionError`, which proves discovery accepted the layout but prevents
a child process. Stable order tests inspect the first recorded compiler argv.
Add
`test_discovery_rejects_incomplete_layout_before_execution(tmp_path, layout, message)`
parametrized with exactly these `(layout, message)` values:

```python
(
    ({}, "at least one Java source is required"),
    ({"tests/t1.in": b"x\n"}, "orphan input or output fixture"),
    ({"tests/t1.out": b"x\n"}, "orphan input or output fixture"),
)
```

For each case, create only the listed relative files below `tmp_path`, invoke
the public tool with `source_root="src"`, `tests_directory="tests"`,
`main_class="Main"`, and `purpose="test"`, and assert the exact
`ToolArgumentError` message plus `RecordingAbortExecutor.calls == []`.

Add these explicit cases:

- 501 stable `.java` paths reject with `at most 500 Java sources are allowed`;
- 201 complete pairs reject with `at most 200 Java test cases are allowed`;
- a pure `_pair_case_files()` unit test supplies synthetic relative paths
  `A.in` and `a.in` and rejects with
  `duplicate Java test case identifier`, without relying on NTFS permitting
  both names;
- input size 262,144 bytes is accepted by discovery, while 262,145 rejects;
- expected output size 65,536 bytes is accepted, while 65,537 rejects;
- invalid expected UTF-8 rejects with `expected output must be UTF-8 text`;
- nested source and case paths are observed in casefolded POSIX relative order;
- source/test roots that are absolute, contain `..`, target `.coding-agent` or
  `.git`, or are themselves a Windows junction/reparse point reject through
  `SafetyViolation` before execution;
- protected or reparse children nested below an otherwise valid root are
  skipped and never traversed or passed to the compiler.

For accepted-boundary and stable-order tests, inject `RecordingAbortExecutor`;
no real compiler or runtime is started.

- [ ] **Step 6: Run RED discovery tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_java_tool.py -k "discovery or source_limit or case_limit or fixture_size or expected_utf8 or stable_order or reparse" -q
```

Expected: exit `1`; missing discovery/limit behavior is the reason. A platform
without reparse creation may skip only the real filesystem case; the pure
policy cases must run.

- [ ] **Step 7: Implement deterministic guarded traversal and discovery**

Add these private functions and use them from `_execute()` before runtime
resolution:

```python
def _guarded_files(paths: PathGuard, root: GuardedPath) -> tuple[GuardedPath, ...]:
    pending = [root.relative]
    files: list[GuardedPath] = []
    while pending:
        current = paths.existing_directory(pending.pop())
        entries = sorted(
            current.absolute.iterdir(),
            key=lambda item: (item.name.casefold(), item.name),
            reverse=True,
        )
        for entry in entries:
            relative = entry.relative_to(paths.workspace).as_posix()
            try:
                guarded = paths.existing_entry(relative)
            except SafetyViolation as exc:
                if exc.code in {
                    SafetyCode.PROTECTED_PATH,
                    SafetyCode.REPARSE_POINT_DENIED,
                }:
                    continue
                raise
            if guarded.absolute.is_dir():
                pending.append(guarded.relative)
            elif guarded.absolute.is_file():
                files.append(guarded)
    return tuple(sorted(files, key=lambda item: (item.relative.casefold(), item.relative)))
```

`_discover_sources()` filters case-insensitive `.java`, rejects zero and the
501st accepted source, and returns guarded paths in stable order.

`_discover_cases()` filters `.in`/`.out` and delegates to this deterministic
pairing boundary:

```python
def _pair_case_files(
    inputs: tuple[GuardedPath, ...],
    outputs: tuple[GuardedPath, ...],
) -> tuple[_JavaCase, ...]:
```

`_pair_case_files()` uses
`relative.rsplit(".", 1)[0].casefold()` as the collision key, retains the
original POSIX relative stem as `case_id`, rejects duplicate/orphan/empty/201st
case, checks raw file sizes before reading, and decodes expected bytes with
`errors="strict"`. It returns cases sorted by `(case_id.casefold(), case_id)`.

Every recursive entry is passed back through `PathGuard`; do not use unchecked
`rglob()` results.

Complete this slice by resolving the injected Java runtime, creating the stable
compiler argv, and calling the injected executor. The next task replaces the
aborting test seam with scripted child results and completes result decoding,
case execution, comparison, timeout, and cleanup. Do not return a success result
before compiler execution has produced valid evidence.

- [ ] **Step 8: Run GREEN discovery tests and path regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_java_tool.py -k "discovery or source_limit or case_limit or fixture_size or expected_utf8 or stable_order or reparse" -q
.\.venv\Scripts\python.exe -m pytest tests/test_path_safety.py tests/tools/test_read_tools.py tests/tools/test_write_tools.py -q
```

Expected: all non-platform-skipped cases pass; existing file tools remain
unchanged.

---

### Task 5: Complete Java compile, run, compare, deadline, and cleanup behavior

**Files:**
- Modify: `tests/tools/test_java_tool.py`
- Modify: `src/coding_agent/tools/java.py`
- Regress: `tests/tools/test_shell_tool.py`

**Interfaces:**
- Consumes: Task 3 runtime/executor seams and Task 4 strict discovery.
- Produces: complete `RunJavaTestsTool.execute(arguments, context) -> ToolExecution` and exact Java result JSON.

- [ ] **Step 1: Add deterministic scripted child-process test seams**

Add these helpers to `tests/tools/test_java_tool.py`:

```python
@dataclass(frozen=True)
class ChildOutcome:
    exit_code: int | None = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    truncated: bool = False
    cleanup_error: str | None = None
    elapsed: float = 1.0


class ManualClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class ScriptedJavaExecutor:
    def __init__(self, clock: ManualClock, outcomes: tuple[ChildOutcome, ...]) -> None:
        self.clock = clock
        self.outcomes = list(outcomes)
        self.calls: list[tuple[AuthorizedCommand, ExecutionContext, bytes | None]] = []

    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
        *,
        stdin_stream: BinaryIO | None = None,
    ) -> ToolExecution:
        stdin_bytes = None if stdin_stream is None else stdin_stream.read()
        self.calls.append((command, context, stdin_bytes))
        outcome = self.outcomes.pop(0)
        self.clock.value += outcome.elapsed
        return ToolExecution(
            output=json.dumps(
                {
                    "argv": list(command.argv),
                    "cleanup_error": outcome.cleanup_error,
                    "purpose": command.purpose,
                    "stderr": outcome.stderr,
                    "stdout": outcome.stdout,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            metadata=ToolResultMetadata(
                exit_code=outcome.exit_code,
                timed_out=outcome.timed_out,
                truncated=outcome.truncated,
                duration_ms=int(outcome.elapsed * 1000),
            ),
        )
```

Add `fixed_runtime_factory(tmp_path)` which creates external fake
`javac.exe`/`java.exe` files and returns a factory whose policy `workspace`
property is the canonical workspace and whose `resolve()` returns
`JavaRuntime(javac, java)`.

- [ ] **Step 2: Write the RED full-success orchestration test**

```python
def test_java_tool_compiles_runs_cases_in_order_and_returns_exact_success(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    write_java_fixture(
        workspace,
        sources={"z/Z.java": "class Z {}", "Main.java": "class Main {}"},
        cases={"b": (b"b\n", b"B\r\n"), "a": ("雪\n".encode(), "雪\n".encode())},
    )
    clock = ManualClock()
    executor = ScriptedJavaExecutor(
        clock,
        (
            ChildOutcome(),
            ChildOutcome(stdout="雪\r\n"),
            ChildOutcome(stdout="B\n"),
        ),
    )
    tool = RunJavaTestsTool(
        runtime_policy_factory=fixed_runtime_factory(tmp_path),
        executor=executor,
        clock=clock,
    )
    result = tool.execute(
        {
            "source_root": "src",
            "main_class": "Main",
            "tests_directory": "tests",
            "purpose": "verification",
        },
        ExecutionContext(workspace, command_timeout_seconds=120),
    )
    payload = json.loads(result.output or "")
    assert payload == {
        "case_count": 2,
        "failed_case": None,
        "passed_count": 2,
        "phase": "complete",
        "purpose": "verification",
        "safe_error_code": None,
        "source_count": 2,
        "stderr": "",
        "stdout": "",
    }
    assert result.metadata == ToolResultMetadata(
        exit_code=0,
        timed_out=False,
        truncated=False,
        duration_ms=3000,
    )
    compile_command, first_case, second_case = [call[0] for call in executor.calls]
    assert compile_command.argv[1:7] == (
        "-encoding", "UTF-8", "-proc:none", "-classpath",
        compile_command.argv[5], "-d",
    )
    assert compile_command.argv[-2:] == (
        str(workspace.resolve() / "src" / "Main.java"),
        str(workspace.resolve() / "src" / "z" / "Z.java"),
    )
    assert first_case.argv[-1] == second_case.argv[-1] == "Main"
    assert executor.calls[1][2] == "雪\n".encode()
    assert executor.calls[2][2] == b"b\n"
    assert [call[1].command_timeout_seconds for call in executor.calls] == [60.0, 59.0, 58.0]
```

When implementing, index the compile arguments explicitly in the final test so
the two build-directory positions are asserted equal and located under
`workspace/.coding-agent/java-tests`; do not compare a temporary random suffix
to a hard-coded string.

- [ ] **Step 3: Run RED full-success test**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_java_tool.py::test_java_tool_compiles_runs_cases_in_order_and_returns_exact_success -q
```

Expected: exit `1`; Task 4 reaches the compiler seam but lacks child decoding,
case execution, comparison, exact JSON, deadline, and cleanup.

- [ ] **Step 4: Verify safe internal temp ownership and implement child decoding**

Use the protocols, constructor, and default factory implemented in Task 4.
`_create_temporary_directory(workspace)` must continue to:

1. canonicalize the workspace through `PathGuard`;
2. create or validate `.coding-agent` and `.coding-agent/java-tests` one level
   at a time;
3. reject an existing non-directory, symlink, junction, or Windows reparse point
   with a stable `SafetyViolation`;
4. call `tempfile.TemporaryDirectory(prefix="run-", dir=java_tests_root)`;
5. return an object whose `.name` is the unique build directory.

Add `_decode_child(execution, command)` that accepts only exact shell-output
keys, exact argv equality, matching purpose, string stdout/stderr, and a null or
string cleanup error. Invalid JSON or contradiction raises
`JavaToolExecutionError("java child result is invalid")` without embedding the
payload or exception.

Add `_bounded_diagnostic(text, workspace)` that replaces both slash forms of
the canonical workspace with `<workspace>` using Windows case-insensitive
matching, encodes UTF-8, retains at most 8,192 bytes without emitting a partial
code point, and never appends source or input content.

- [ ] **Step 5: Implement compile and ordered case execution**

Use these exact command arrays:

```python
compile_argv = (
    str(runtime.javac),
    "-encoding",
    "UTF-8",
    "-proc:none",
    "-classpath",
    str(build_directory),
    "-d",
    str(build_directory),
    *(str(source.absolute) for source in sources),
)

case_argv = (
    str(runtime.java),
    "-cp",
    str(build_directory),
    arguments.main_class,
)
```

Create each `AuthorizedCommand` with the array, Windows
`subprocess.list2cmdline`, the model-supplied purpose, and
`CommandSource.MODEL`. Before every child call, pass every counter and phase to
the timeout helper explicitly:

```python
remaining = deadline - self._clock()
if remaining <= 0:
    return _suite_timeout_execution(
        arguments=arguments,
        source_count=len(sources),
        case_count=len(cases),
        passed_count=passed_count,
        phase=phase,
        failed_case=failed_case,
        started=started,
        finished=self._clock(),
    )
child_context = ExecutionContext(
    workspace=paths.workspace,
    command_timeout_seconds=remaining,
)
```

The deadline is `started + min(context.command_timeout_seconds, 60.0)`. Compile
uses default `DEVNULL`; each case opens its validated input with `"rb"` and
passes `stdin_stream`. Normalize actual and expected text with:

```python
def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
```

Otherwise compare exactly. Discard passing stdout/stderr. Stop at the first
failed case. Aggregate duration is
`max(0, int((clock() - started) * 1000))`; `changed_paths` remains empty.

Construct JSON only through this helper boundary:

```python
def _execution_output(
    *,
    source_count: int,
    case_count: int,
    passed_count: int,
    failed_case: str | None,
    phase: str,
    purpose: str,
    safe_error_code: str | None,
    stdout: str,
    stderr: str,
    exit_code: int | None,
    timed_out: bool,
    truncated: bool,
    duration_ms: int,
) -> ToolExecution:
```

It emits the exact Java keys using `sort_keys=True`, `separators=(",", ":")`,
`ensure_ascii=False`, and `allow_nan=False`. `_suite_timeout_execution()` is a
thin named-argument wrapper over this function; it sets `safe_error_code` to
`suite_timed_out`, `exit_code=None`, `timed_out=True`, and empty diagnostics.

- [ ] **Step 6: Run GREEN full-success and existing executor regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_java_tool.py::test_java_tool_compiles_runs_cases_in_order_and_returns_exact_success -q
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py tests/test_command_safety.py -q
```

Expected: both exit `0`; compile uses `-proc:none` and a controlled classpath,
case stdin/order are exact, timeout decreases from the 60-second cap, and the
generic command tool remains unchanged.

- [ ] **Step 7: Write RED failure-matrix tests**

Add a parametrized test whose scripted outcome and exact public result are:

| Child behavior | `phase` | `safe_error_code` | metadata |
| --- | --- | --- | --- |
| compiler exit `2` | `compile` | `compile_failed` | exit `2`, not timed out |
| case exit `3` | `case` | `program_failed` | exit `3`, failed case set |
| stdout mismatch | `case` | `output_mismatch` | synthetic exit `1` |
| either stream truncated | current phase | `output_truncated` | synthetic exit `1`, truncated |
| child timeout | current phase | `suite_timed_out` | exit null, timed out |
| expired deadline before next case | `case` | `suite_timed_out` | no extra executor call |

Add these exact standalone test functions and assertions:

- `test_java_comparison_only_normalizes_newlines`: CRLF expected and LF actual
  passes; rerun with one trailing-space difference and assert
  `safe_error_code == "output_mismatch"`.
- `test_java_tool_reports_only_first_failed_case`: create three cases, make the
  second mismatch, assert the relative second case ID and exactly three executor
  calls (one compile plus two cases).
- `test_java_tool_redacts_workspace_and_bounds_diagnostic`: make the compiler
  emit both slash forms and one case-swapped form of the canonical workspace
  followed by 20 KiB of text; assert no absolute-path variant appears and both
  serialized diagnostic fields are at most 8,192 UTF-8 bytes.

For a case whose expected output is exactly 65,536 bytes, script exactly that
stdout with `truncated=False` and assert pass. Script the same prefix with
`truncated=True` and assert `output_truncated` rather than pass.

- [ ] **Step 8: Run RED failure matrix**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_java_tool.py -k "compile_failed or program_failed or output_mismatch or output_truncated or suite_timed_out or normalizes_newlines or first_failed_case or bounds_diagnostic" -q
```

Expected: exit `1`; missing stable failure mapping or bounds cause assertions,
not fixture or fake-executor errors.

- [ ] **Step 9: Implement the locked failure mapping**

Use only these stable codes:

```python
_COMPILE_FAILED = "compile_failed"
_PROGRAM_FAILED = "program_failed"
_OUTPUT_MISMATCH = "output_mismatch"
_OUTPUT_TRUNCATED = "output_truncated"
_SUITE_TIMED_OUT = "suite_timed_out"
_CLEANUP_FAILED = "cleanup_failed"
```

Map outcomes in this priority order for each child:

1. `metadata.timed_out` -> suite timeout with `exit_code=None`;
2. `cleanup_error` -> cleanup failure with synthetic exit `1` unless another
   already-nonpassing primary result is being retained;
3. `metadata.truncated` -> output-truncated failure with synthetic exit `1`;
4. nonzero exit -> compile/program failure preserving the real exit code;
5. case stdout mismatch -> output mismatch with synthetic exit `1`;
6. otherwise continue/pass.

The public phase/case fields are locked as follows:

| Code | Phase | `failed_case` | `passed_count` |
| --- | --- | --- | --- |
| `compile_failed` | `compile` | null | `0` |
| `program_failed` | `case` | current relative case ID | cases completed before it |
| `output_mismatch` | `case` | current relative case ID | cases completed before it |
| `output_truncated` | `compile` or `case` | null for compile, current ID for case | cases completed before the failing operation |
| `suite_timed_out` | `compile` or `case` | null for compile, current/next ID for case | cases completed before timeout |
| `cleanup_failed` | `cleanup` | null after an otherwise complete suite; otherwise the current case ID or null for compile | preserve completed-case count |

When the suite deadline expires before a case is launched, `failed_case` is that
next case ID. No code may claim a case passed until its process completed,
produced untruncated output, and matched the expected text.

Mismatch stdout contains only the bounded actual excerpt. Mismatch stderr is a
bounded deterministic string containing the relative case ID and JSON-escaped
expected/actual excerpts; both fields pass through `_bounded_diagnostic()` so
workspace paths and oversize UTF-8 text are removed, and neither field contains
`.in` contents.

- [ ] **Step 10: Run GREEN failure matrix and complete Java unit tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_java_tool.py -k "not real_jdk" -q
```

Expected: exit `0`; all deterministic fake-runtime tests pass without a real
JDK, network, key, or sleep.

- [ ] **Step 11: Write RED cleanup and BaseException tests**

Define `FakeTemporaryDirectory` with `.name`, a `cleanup_calls` counter, and an
optional `OSError("private cleanup path")`. Add
`test_cleanup_failure_cannot_turn_an_otherwise_passed_suite_into_success`, which
asserts exact phase `cleanup`, code `cleanup_failed`, exit `1`, no private
message, and one cleanup call. Add parametrized
`test_java_tool_cleans_up_and_propagates_base_exception` for a stored
`KeyboardInterrupt()` and `SystemExit(7)`; make the executor raise that same
object, then assert one cleanup call and identity-preserving propagation.

Add a registry test for `CommandStartError("private path")` that asserts status
`error`, no verification-shaped JSON, and no `private path` in the public error.
The Java tool must translate expected start/capture failures to
`JavaToolExecutionError("java child process failed")` before the registry sees
them.

- [ ] **Step 12: Run RED cleanup tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_java_tool.py -k "cleanup_failure or propagates_base_exception or child_process_failed" -q
```

Expected: exit `1`; cleanup currently propagates/overrides or exposes the raw
message.

- [ ] **Step 13: Implement cleanup without swallowing `BaseException`**

Use this control structure:

```python
temporary = self._temporary_directory_factory(paths.workspace)
cleanup_failed = False
try:
    outcome = self._run_suite(
        arguments=arguments,
        paths=paths,
        runtime=runtime,
        sources=sources,
        cases=cases,
        build_directory=Path(temporary.name),
        context=context,
    )
finally:
    try:
        temporary.cleanup()
    except OSError:
        cleanup_failed = True

if cleanup_failed and outcome.metadata.exit_code == 0 and not outcome.metadata.timed_out:
    return _cleanup_failure_execution(outcome)
return outcome
```

`_cleanup_failure_execution(outcome: ToolExecution) -> ToolExecution` parses
only the tool's own exact nine-key JSON, preserves source/case/pass counts and
purpose, sets phase `cleanup`, code `cleanup_failed`, empty diagnostics,
synthetic exit `1`, and otherwise preserves duration without exposing the
cleanup exception.

If `_run_suite()` raises, Python leaves the `try/finally` with the original
exception after the cleanup `OSError` is suppressed. Do not add
`except BaseException`. Catch expected `CommandStartError` and ordinary child
decode/capture errors around child execution and raise the stable
`JavaToolExecutionError` without chaining provider, path, argv, stdout, or
stderr content.

- [ ] **Step 14: Run GREEN cleanup, all Java unit tests, and shell regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_java_tool.py -k "not real_jdk" -q
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py tests/test_command_safety.py tests/test_path_safety.py -q
```

Expected: all commands exit `0`; report real counts and platform skips.

---

### Task 6: Admit only internally consistent Java evidence and register the tool

**Files:**
- Modify: `tests/test_verification.py`
- Modify: `src/coding_agent/verification.py`
- Modify: `tests/test_app.py`
- Modify: `src/coding_agent/app.py`

**Interfaces:**
- Consumes: exact `RunJavaTestsTool` arguments/output and existing `VerificationResult`/`VerificationGate`.
- Produces: fresh provider-neutral Java verification evidence; no new status, state field, or success path.

- [ ] **Step 1: Write RED Java evidence tests**

Add this helper to `tests/test_verification.py`:

```python
def _java_pair(
    *,
    purpose: str = "verification",
    phase: str = "complete",
    exit_code: int | None = 0,
    timed_out: bool = False,
    truncated: bool = False,
    safe_error_code: str | None = None,
    case_count: int = 2,
    passed_count: int = 2,
    failed_case: str | None = None,
    status: str = "ok",
) -> tuple[ToolCall, ToolResult]:
    arguments = {
        "source_root": "src",
        "main_class": "Main",
        "tests_directory": "tests",
        "purpose": purpose,
    }
    call = ToolCall("java-verify", "run_java_tests", arguments)
    output = json.dumps(
        {
            "case_count": case_count,
            "failed_case": failed_case,
            "passed_count": passed_count,
            "phase": phase,
            "purpose": purpose,
            "safe_error_code": safe_error_code,
            "source_count": 3,
            "stderr": "",
            "stdout": "",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return call, ToolResult(
        call_id=call.call_id,
        tool_name=call.name,
        status=status,
        output=output if status == "ok" else None,
        error=None if status == "ok" else "tool failed",
        metadata=ToolResultMetadata(
            exit_code=exit_code,
            timed_out=timed_out,
            truncated=truncated,
            duration_ms=25,
        ),
    )
```

Add tests:

```python
def test_java_verification_records_fresh_passed_evidence(tmp_path: Path) -> None:
    gate = VerificationGate(required_command=None, execution_context=ExecutionContext(tmp_path))
    state = _candidate_state(tmp_path)
    call, result = _java_pair()
    assert gate.observe_tool_result(state, call, result) is True
    assert state.verification_attempt_count == 1
    assert state.verification_status is VerificationStatus.PASSED
    assert state.validation_index == state.mutation_index == 2
    assert state.last_verification is not None
    assert state.last_verification.command == (
        "run_java_tests source_root=src main_class=Main tests_directory=tests"
    )
    assert state.last_verification.source is CommandSource.MODEL
    assert gate.evaluate(state).outcome is VerificationOutcome.SUCCESS


def test_java_test_purpose_does_not_create_final_evidence(tmp_path: Path) -> None:
    gate = VerificationGate(required_command=None, execution_context=ExecutionContext(tmp_path))
    state = _candidate_state(tmp_path)
    call, result = _java_pair(purpose="test")
    assert gate.observe_tool_result(state, call, result) is False
    assert state.last_verification is None
    assert state.verification_attempt_count == 0
```

Parametrize compile failure, program/mismatch/cleanup failure, truncation, and
timeout using the exact Task 5 payload/metadata combinations. Assert status
`FAILED` or `TIMED_OUT`, never `PASSED`, and validation index equals the current
mutation only when an internally consistent `purpose="verification"` result is
recorded.

- [ ] **Step 2: Run RED Java evidence tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_verification.py -k "java_verification or java_test_purpose or java_failure" -q
```

Expected: exit `1`; the existing observer ignores every tool except
`run_command`.

- [ ] **Step 3: Implement exact Java result decoding**

Add `_JAVA_OUTPUT_KEYS` matching Task 5 and:

```python
def _java_command_description(arguments: JSONObject) -> str:
    return (
        "run_java_tests "
        f"source_root={arguments['source_root']} "
        f"main_class={arguments['main_class']} "
        f"tests_directory={arguments['tests_directory']}"
    )


def _decode_java_execution(
    execution: ToolExecution,
    *,
    arguments: JSONObject,
    validation_index: int,
    workspace: Path,
) -> VerificationResult:
    # parse exact keys and types; verify purpose, nonnegative counts,
    # source_count >= 1, case_count >= 1, passed_count <= case_count,
    # failed_case/safe_error/phase consistency, and metadata consistency
```

Before rendering the command description, validate the exact argument set,
`purpose="verification"`, the same Java main-class grammar, and relative
`source_root`/`tests_directory` values without drives, roots, NUL, or `..`.
Reject counts above 500 sources or 200 cases, booleans masquerading as integers,
stdout/stderr above 8,192 UTF-8 bytes, and stdout/stderr containing the canonical
workspace path in either slash form or Windows case variant. The exact terminal
mapping is:

- pass only when phase `complete`, safe error and failed case are null,
  `passed_count == case_count`, exit `0`, not timed out, and not truncated;
- timeout only when metadata has null exit and `timed_out=True`, with phase
  `compile` or `case` and safe code `suite_timed_out`;
- failure only when exit is nonzero, not timed out, and safe code is one of
  `compile_failed`, `program_failed`, `output_mismatch`, `output_truncated`, or
  `cleanup_failed`, with a phase consistent with that code;
- every other combination raises
  `VerificationError("invalid Java verification execution")` without chaining.

Create `VerificationResult` with source `CommandSource.MODEL`, the safe command
description, exact metadata duration/truncation, and bounded stdout/stderr from
the Java output. A `FAILED` result uses `error=None`; a `TIMED_OUT` result uses
the fixed safe error string `suite_timed_out`. No provider payload, executable
path, temporary path, or raw decoder exception enters `error`.

Validate `failed_case` and `passed_count` against the Task 5 table: compile
failures use null/zero, case failures use a non-empty safe relative case ID,
deadline expiry before a case identifies that next case, and cleanup after an
otherwise complete suite may use null with `passed_count == case_count`.

In `observe_tool_result()`, keep the current `run_command` branch intact and add
the Java branch only after exact call/result identity, `status="ok"`, exact
argument keys, and `purpose="verification"` checks. On accepted evidence,
increment once and update the same three state fields as the existing branch.

- [ ] **Step 4: Run GREEN Java evidence and all verification tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_verification.py -k "java" -q
.\.venv\Scripts\python.exe -m pytest tests/test_verification.py tests/test_agent_loop.py -q
```

Expected: both exit `0`; existing Python/user-required behavior remains green.

- [ ] **Step 5: Write RED contradiction, staleness, and precedence tests**

Add a parametrized malformed Java matrix:

- extra/missing output key;
- payload purpose differs from call purpose;
- zero sources or cases;
- passed count greater than case count;
- complete phase with failed case or safe error;
- exit `0` with failed phase;
- nonzero exit with complete phase;
- timeout plus integer exit;
- truncation with a claimed pass;
- absolute workspace text inserted into the safe command arguments through a
  non-relative `source_root` call.

The first nine cases assert stable `VerificationError`; the last is ignored as
invalid model evidence and can only be rejected earlier by the Java tool.

Add:

```python
def test_new_mutation_makes_java_evidence_stale(tmp_path: Path) -> None:
    gate = VerificationGate(required_command=None, execution_context=ExecutionContext(tmp_path))
    state = _candidate_state(tmp_path)
    call, result = _java_pair()
    assert gate.observe_tool_result(state, call, result) is True
    state.mutation_index += 1
    state.verification_status = VerificationStatus.STALE
    assert gate.evaluate(state).outcome is VerificationOutcome.CONTINUE
    assert state.validation_index == 2
    assert state.mutation_index == 3


def test_required_command_still_executes_after_fresh_java_evidence(tmp_path: Path) -> None:
    model_gate = VerificationGate(required_command=None, execution_context=ExecutionContext(tmp_path))
    state = _candidate_state(tmp_path)
    call, result = _java_pair()
    assert model_gate.observe_tool_result(state, call, result) is True
    executor = FakeVerificationExecutor(_execution())
    required_gate = VerificationGate(
        required_command=_authorized(),
        execution_context=ExecutionContext(tmp_path),
        executor=executor,
    )
    decision = required_gate.evaluate(state)
    assert decision.outcome is VerificationOutcome.SUCCESS
    assert decision.command_executed is True
    assert len(executor.calls) == 1
```

- [ ] **Step 6: Run RED then GREEN malformed/freshness tests**

RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_verification.py -k "java and (invalid or stale or required)" -q
```

Expected RED: exit `1` until every contradiction is rejected without mutating
state. Implement only missing validation in `_decode_java_execution` and the
observer preconditions.

GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_verification.py -q
```

Expected GREEN: exit `0`; report actual count.

- [ ] **Step 7: Write RED composition test for the sixth tool and shared executor**

Update the existing expected tool list in
`test_composition_uses_fixed_tools_and_shared_executor`:

```python
assert [schema["name"] for schema in model.requests[0].tool_schemas] == [
    "list_directory",
    "read_file",
    "replace_text",
    "write_file",
    "run_command",
    "run_java_tests",
]
```

Extend `RecordingExecutor` in the test with the optional keyword
`stdin_stream: BinaryIO | None = None` while retaining its existing two-argument
record. Do not make the test call Java or require a JDK.

- [ ] **Step 8: Run RED composition test**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_app.py::test_composition_uses_fixed_tools_and_shared_executor -q
```

Expected: exit `1`; the model request exposes only the existing five schemas.

- [ ] **Step 9: Register `RunJavaTestsTool` with the shared executor**

In `src/coding_agent/app.py` import the tool and append exactly:

```python
RunJavaTestsTool(executor=executor),
```

after `RunCommandTool(authorized_executor=executor)` in the one production
registry. Do not add a factory field, global registry, second executor, CLI
argument, or provider branch.

- [ ] **Step 10: Run GREEN composition and application regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_app.py::test_composition_uses_fixed_tools_and_shared_executor -q
.\.venv\Scripts\python.exe -m pytest tests/test_app.py tests/test_cli.py tests/test_verification.py -q
```

Expected: both exit `0`; app startup remains offline with fake clients and the
existing required verification executor is still shared.

---

### Task 7: Prove headless Agent integration and the real local JDK path

**Files:**
- Create: `tests/integration/test_java_agent.py`
- Modify: `tests/tools/test_java_tool.py`

**Interfaces:**
- Consumes: real `AgentRunner`, `ToolRegistry`, `WriteFileTool`, `RunJavaTestsTool`, `VerificationGate`, and fake model/executor seams.
- Produces: offline end-to-end evidence and a separately identifiable real-JDK smoke test.

- [ ] **Step 1: Write the RED headless README-plus-Java verification test**

Create `tests/integration/test_java_agent.py`. Build a temporary workspace with
`src/Main.java` and one `tests/t1.in`/`tests/t1.out` pair. Use
`FakeModelClient` responses in this exact order:

```python
responses = (
    ModelResponse(
        tool_calls=(
            ToolCall(
                "write-readme",
                "write_file",
                {"path": "README.md", "content": "# Demo\n\nA Java stdin/stdout project.\n"},
            ),
        )
    ),
    ModelResponse(
        tool_calls=(
            ToolCall(
                "verify-java",
                "run_java_tests",
                {
                    "source_root": "src",
                    "main_class": "Main",
                    "tests_directory": "tests",
                    "purpose": "verification",
                },
            ),
        )
    ),
    ModelResponse(text="README created and the Java fixture passed."),
)
```

Define a local `PassingJavaExecutor` in this integration file. It records the
commands, returns one compiler success, then reads the case stdin and returns
the exact expected stdout using the same five-key child JSON as Task 5. Define a
local fixed-runtime policy factory pointing at two external temporary fake
executables. Do not import helpers from another test module. Construct the real
registry with `WriteFileTool()` and
`RunJavaTestsTool(runtime_policy_factory=fixed_runtime_factory, executor=java_executor,
clock=clock, temporary_directory_factory=temporary_factory)`, and construct
`VerificationGate(required_command=None, execution_context=execution_context,
executor=java_executor)`. Construct `AgentRunner` with
existing `ContextManager`, `TerminationPolicy`, fake clock/event sink patterns
from `tests/integration/test_agent_repair.py`.

Assertions:

```python
assert state.status is AgentStatus.SUCCESS
assert state.mutation_index == 1
assert state.validation_index == 1
assert state.verification_status is VerificationStatus.PASSED
assert state.modified_paths == ("README.md",)
assert (workspace / "README.md").read_text(encoding="utf-8").startswith("# Demo")
assert [request.tool_schemas[-1]["name"] for request in model.requests] == [
    "run_java_tests",
    "run_java_tests",
    "run_java_tests",
]
```

Also assert the Java tool result in model history uses call ID `verify-java` and
that no `.coding-agent/java-tests/run-*` directory remains.

- [ ] **Step 2: Run RED integration test**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_java_agent.py -q
```

Expected: exit `1` if any registry, mutation, evidence, cleanup, or final-success
connection is missing. A test-construction/import error is not an accepted RED.

- [ ] **Step 3: Make only integration seams necessary for GREEN**

Production behavior should already exist. Fix only a missing exact connection
identified by the RED evidence inside the locked files. Do not modify Agent,
state, messages, model, or registry interfaces. If GREEN requires one of those
changes, stop and return to the approved design.

- [ ] **Step 4: Run GREEN integration and core regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_java_agent.py -q
.\.venv\Scripts\python.exe -m pytest tests/integration tests/test_agent_loop.py tests/test_verification.py -q
```

Expected: both exit `0`; the new test is fully offline and existing Python and
Chat Completions integration tests remain green.

- [ ] **Step 5: Write the real-JDK smoke test**

Add to `tests/tools/test_java_tool.py`:

```python
@pytest.mark.skipif(
    os.name != "nt" or shutil.which("javac.exe") is None or shutil.which("java.exe") is None,
    reason="trusted Windows JDK is unavailable",
)
def test_real_jdk_compiles_and_runs_a_temporary_black_box_suite(
    tmp_path: Path,
) -> None:
    write_java_fixture(
        tmp_path,
        sources={
            "Main.java": (
                "import java.io.*;\n"
                "public class Main {\n"
                "  public static void main(String[] args) throws Exception {\n"
                "    var reader = new BufferedReader(new InputStreamReader(System.in));\n"
                "    System.out.println(reader.readLine().toUpperCase());\n"
                "  }\n"
                "}\n"
            )
        },
        cases={"upper": (b"hello\n", b"HELLO\n")},
    )
    result = RunJavaTestsTool().execute(
        {
            "source_root": "src",
            "main_class": "Main",
            "tests_directory": "tests",
            "purpose": "test",
        },
        ExecutionContext(tmp_path, command_timeout_seconds=30),
    )
    payload = json.loads(result.output or "")
    assert result.metadata.exit_code == 0
    assert result.metadata.timed_out is False
    assert payload["phase"] == "complete"
    assert payload["passed_count"] == payload["case_count"] == 1
    assert list((tmp_path / ".coding-agent" / "java-tests").glob("run-*")) == []
```

- [ ] **Step 6: Run the real JDK test and prove it did not skip locally**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_java_tool.py::test_real_jdk_compiles_and_runs_a_temporary_black_box_suite -vv -rs
```

Expected on the current machine: exit `0`, exactly one passed test, zero skipped;
the output identifies the test as PASSED. Any skip leaves Task 24 in progress
and must be reported rather than counted as JDK evidence.

- [ ] **Step 7: Run all Java and Windows executor tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_java_tool.py tests/tools/test_shell_tool.py tests/test_command_safety.py tests/test_path_safety.py -q -ra
```

Expected: exit `0`; record real pass/skip/warning counts, and distinguish the
real JDK test from fake-executor coverage.

---

### Task 8: Update public documentation after GREEN

**Files:**
- Modify: `tests/test_docs.py`
- Modify: `README.txt`
- Modify: `README.md`
- Modify: `docs/USAGE.md`
- Verify: `DESIGN.md`, `AGENTS.md`, `TASKS.md`

**Interfaces:**
- Consumes: implemented six-tool schema and actual tested behavior.
- Produces: public instructions that do not advise Python verification for Java workspaces.

- [ ] **Step 1: Write RED documentation contract tests**

In `tests/test_docs.py`, import `RunJavaTestsTool`, rename the usage heading
expectation from `## 五个本地工具` to `## 六个本地工具`, and set:

```python
actual_tools = [
    ListDirectoryTool.name,
    ReadFileTool.name,
    ReplaceTextTool.name,
    WriteFileTool.name,
    RunCommandTool.name,
    RunJavaTestsTool.name,
]
```

Add assertions that `docs/USAGE.md` contains all of:

```python
for required in (
    "`run_java_tests`",
    "`source_root`",
    "`main_class`",
    "`tests_directory`",
    "`purpose=\"verification\"`",
    "`.in`",
    "`.out`",
    "65,536",
    "262,144",
    "不支持 Maven、Gradle 或 JUnit",
    "不是操作系统级沙箱",
):
    assert required in text
```

Add public-doc assertions that Java instructions say to omit an unrelated
`--verify "pytest -q"`, that only a fresh Java verification result can satisfy
the no-`--verify` gate, and that `run_command` still cannot execute Java command
strings.

- [ ] **Step 2: Run RED documentation tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_docs.py -q
```

Expected: exit `1`; current public docs still describe five tools and
Python-only verification.

- [ ] **Step 3: Update public documentation with only verified behavior**

Apply these exact content changes:

- `README.md`: add the dedicated Java tool to architecture/features, explain
  strict paired fixtures and fresh evidence, retain the trusted-workspace/no-OS-
  sandbox warning, and state that Maven/Gradle/JUnit are unsupported.
- `README.txt`: add one compact sentence naming Java `.in`/`.out` verification;
  keep the existing repository address unchanged and remain within its tested
  character/byte/line limits.
- `docs/USAGE.md`: rename the tool section to `## 六个本地工具`, add the exact
  four-argument schema, limits, ordering, newline-only normalization, exit/
  timeout semantics, and a Java GUI/CLI example without `--verify "pytest -q"`.
- `docs/USAGE.md`: clearly distinguish `purpose="test"` from
  `purpose="verification"`, user-supplied mandatory `--verify`, and the trusted
  local JDK prerequisite.

Do not add a Maven, Gradle, JUnit, JDK download, package-install, remote API, or
arbitrary Java command example. Do not include the target workspace's absolute
path or any real credential.

- [ ] **Step 4: Run GREEN docs tests and README constraints**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_docs.py -q
.\.venv\Scripts\python.exe -c "from pathlib import Path; p=Path('README.txt'); t=p.read_text(encoding='utf-8'); print({'chars':len(t),'bytes':len(t.encode('utf-8')),'lines':len(t.splitlines())}); assert len(t) <= 1000"
```

Expected: both exit `0`; report measured README values rather than estimates.

---

### Task 9: Final verification, audits, and manual checkpoint

**Files:**
- Verify every changed/new file from the file map.
- Do not change Task 24 from `进行中`.

**Interfaces:**
- Consumes: all milestone behavior.
- Produces: fresh review evidence only; no commit, push, or next task.

- [ ] **Step 1: Invoke completion verification workflow**

Use `superpowers:verification-before-completion`. If a reproducible unexpected
failure appears, use `superpowers:systematic-debugging` before modifying code.

- [ ] **Step 2: Run focused milestone tests**

```powershell
node --test tests/js/web_gui.test.mjs
.\.venv\Scripts\python.exe -m pytest tests/test_context.py -q
.\.venv\Scripts\python.exe -m pytest tests/tools/test_java_tool.py tests/test_command_safety.py tests/tools/test_shell_tool.py -q -ra
.\.venv\Scripts\python.exe -m pytest tests/test_verification.py tests/test_app.py tests/integration/test_java_agent.py tests/test_docs.py -q
```

Expected: every command exits `0`; the real-JDK test is PASSED, not skipped.

- [ ] **Step 3: Run explicit Task 1-23 regressions and the complete suite**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_messages.py tests/test_model.py tests/test_agent_loop.py tests/tools/test_read_tools.py tests/tools/test_write_tools.py tests/test_openai_client.py tests/test_chat_completions_client.py tests/test_openai_streaming_client.py tests/test_chat_completions_streaming_client.py tests/test_termination.py tests/test_logging.py tests/test_report.py tests/test_session.py tests/test_session_store.py tests/test_session_controller.py tests/test_session_events.py tests/test_session_runtime.py tests/test_skills.py tests/test_web_auth.py tests/test_web_api.py tests/test_web_sse.py tests/test_web_cli.py tests/test_web_gui.py -q -ra
.\.venv\Scripts\python.exe -m pytest -q -ra
```

Expected: both exit `0`; record actual passes, failures, skips, warnings, and
duration. Do not reuse a baseline result.

- [ ] **Step 4: Run Windows path/reparse and process-tree evidence**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_path_safety.py tests/test_command_safety.py tests/tools/test_java_tool.py -k "reparse or junction or symlink or shadow or real_jdk" -vv -ra
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py tests/tools/test_java_tool.py -k "timeout or process_tree or simultaneous or truncated or deadline" -vv -ra
```

Expected: exit `0`; every supported Windows-specific test runs. Report any
platform skip by exact test name and do not claim skipped behavior as verified.

- [ ] **Step 5: Check public signatures, schemas, and provider-neutral boundaries**

```powershell
.\.venv\Scripts\python.exe -c "import inspect; from coding_agent.context import ContextManager; from coding_agent.tools.java import RunJavaTestsTool; from coding_agent.tools.shell import AuthorizedCommandExecutor; print(inspect.signature(ContextManager.prepare)); print(inspect.signature(RunJavaTestsTool.execute)); print(inspect.signature(AuthorizedCommandExecutor.execute)); print(RunJavaTestsTool.schema)"
rg -n "from openai|import openai" src/coding_agent --glob "!openai_client.py" --glob "!chat_completions_client.py"
rg -n "java(?:c)?(?:\.exe)?" src/coding_agent/safety.py src/coding_agent/tools/shell.py
```

Expected:

- context/tool public signatures match the approved spec;
- executor has one keyword-only optional stdin seam;
- OpenAI SDK imports remain confined to provider adapters;
- `CommandPolicy.authorize()` contains no Java allowlist branch, while
  `JavaRuntimePolicy` owns trusted runtime resolution.

- [ ] **Step 6: Audit dependencies, credentials, network, and deferred scope**

```powershell
.\.venv\Scripts\python.exe -m pip check
git diff -- pyproject.toml
rg -n "langchain|llamaindex|openai-agents|autogen|crewai" pyproject.toml src/coding_agent
rg -n "requests\.|httpx\.|urllib\.request|socket\.|Invoke-WebRequest|curl(?:\.exe)?" src/coding_agent/tools/java.py tests/tools/test_java_tool.py tests/integration/test_java_agent.py
rg -n "Authorization: Bearer [A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{12,}" src tests README.md README.txt docs/USAGE.md DESIGN.md AGENTS.md
rg -n "Maven|Gradle|JUnit|mvn(?:\.cmd)?|gradle(?:\.bat)?|powershell|cmd\.exe|bash|wsl" src/coding_agent/tools/java.py
```

Expected: `pip check` exits `0`; `pyproject.toml` has no diff; scans find no
framework, network, credential assignment, arbitrary shell, build-system, or
test-framework implementation in the Java tool. Documentation may contain
explicit statements that Maven/Gradle/JUnit are unsupported; review those hits
as documentation, not implementation.

- [ ] **Step 7: Scan placeholders, suppressed tests, personal paths, and secrets**

```powershell
rg -n "TO[D]O|TB[D]|FIXM[E]|XXX|NotImplemented[E]rror|pragma: no cover" src tests README.md README.txt docs/USAGE.md DESIGN.md AGENTS.md
rg -n "pytest\.skip|pytest\.mark\.skip|pytest\.mark\.xfail|@unittest\.skip" tests
rg -n "C:\\Users\\|D:\\code\\" src tests README.md README.txt docs/USAGE.md DESIGN.md AGENTS.md
```

Expected: no unfinished or personal-path hit. The only new skip is the explicit
real-JDK availability guard, and the current Windows run proves it did not skip.
Existing platform skips are listed separately. No secret value is printed.

- [ ] **Step 8: Check whitespace, status, and complete diff**

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff -- AGENTS.md DESIGN.md TASKS.md src tests README.md README.txt docs/USAGE.md
Get-Content -Raw src/coding_agent/tools/java.py
Get-Content -Raw tests/tools/test_java_tool.py
Get-Content -Raw tests/integration/test_java_agent.py
Get-Content -Raw docs/superpowers/specs/2026-08-30-run-projection-context-java-verification-design.md
Get-Content -Raw docs/superpowers/plans/2026-08-30-run-projection-context-java-verification.md
```

Expected: whitespace exits `0`; changes are limited to the approved file map;
Task 24 remains `进行中`; no staged file exists. The explicit reads cover every
new untracked file that ordinary `git diff` omits. Review every diff line for
unsafe output, absolute path, hidden payload, weakened assertion, duplicate
logic, or unrelated formatting.

- [ ] **Step 9: Check the acceptance matrix explicitly**

Record PASS/FAIL and command evidence for every row:

| Acceptance item | Required evidence |
| --- | --- |
| One active GUI card | Node live projection tests |
| Only final successful reply | Node run-aware terminal tests |
| Failed/interrupted narration hidden | Node terminal tests |
| Eight-turn item overflow compresses | exact 25-item context regression |
| Greatest fitting complete suffix | expansion/pairing tests |
| One summary request maximum | fake-model request count |
| Compression clears continuation | context continuation tests |
| Strict Java schema and limits | Java schema/discovery tests |
| Trusted JDK and no Java command-string bypass | safety tests and code audit |
| `shell=False`, cwd, env, stdin | executor and Java orchestration tests |
| Exact newline-only comparison | Java comparison tests |
| 64 KiB output and global deadline | boundary/deadline tests |
| Timeout/tree/cleanup cannot pass | failure and Windows tests |
| Test purpose is not final evidence | verification purpose test |
| Java pass is mutation-fresh | verification and integration tests |
| User `--verify` keeps precedence | required-command test |
| Existing Python/provider/session/Web behavior | full suite |
| No dependency, network, key, framework, or personal path | audits |
| Real JDK works on this machine | non-skipped real-JDK smoke test |

Any missing evidence keeps Task 24 `进行中` and blocks a completion claim.

- [ ] **Step 10: Request code review and stop for the user**

Use `superpowers:requesting-code-review` for the completed core module diff.
Report all RED/GREEN commands and results, actual test counts, real-JDK status,
Windows skips/warnings, audit results, changed files, `git status`, and deviations.
Do not stage, commit, push, mark Task 24 complete, start another task, or mutate
the target Java workspace.

After the user approves the implementation, provide this manual smoke command
shape without inserting a key or hard-coded personal path:

```powershell
coding-agent-web --workspace <java-workspace> --api-mode chat-completions --base-url <https-endpoint> --model <model-id>
```

The user then submits the README request in the GUI. Success criteria are one
live activity card at a time, one final assistant bubble, a newly created README,
a passing `run_java_tests` verification event fresh for the README mutation,
and no `context_budget_exhausted`. This manual provider run is reported
separately and is never presented as part of the offline automated suite.

---

## Plan self-check

- [x] Every approved GUI, context, Java safety, verification, documentation, and manual-smoke requirement maps to a numbered task and final acceptance row.
- [x] `ContextManager.prepare`, `RunJavaTestsTool.execute`, `AuthorizedCommandExecutor.execute`, `JavaRuntimePolicy.resolve`, and `VerificationGate.observe_tool_result` names and signatures are consistent throughout.
- [x] Input is 262,144 bytes; expected output and retained child stdout are 65,536 bytes; diagnostics are 8,192 UTF-8 bytes; sources are 500; cases are 200; suite time is at most 60 seconds.
- [x] At most one summary provider call occurs; expanded candidates use local fallback; at least one newest complete turn remains.
- [x] `run_command` remains Java-denying and the dedicated tool cannot accept executable or command strings from the model.
- [x] Java `purpose="test"` cannot satisfy final verification, and required `--verify` retains precedence.
- [x] No provider, message, Agent, state, session, REST, SSE, CLI argument, dependency, or existing tool-schema change appears.
- [x] The plan contains no unfinished implementation step or undefined production type.
- [x] Task 23/24 status sequencing leaves exactly one task active and Task 24 remains active at the final stop.

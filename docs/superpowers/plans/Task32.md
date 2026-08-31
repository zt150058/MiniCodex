# Task32 Agent Debugging Convergence and Honest Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make post-mutation runs converge, keep tool narration transient, bound production provider waits, display real command exit codes, and require honest verification claims for interactive programs.

**Architecture:** Preserve all provider-neutral public protocols, safety allowlists, budgets, and persistence schemas. Separate “verification fact recorded” from “verification advances progress,” reuse the existing decision checkpoint and provisional-text discard lifecycle, configure both official SDK clients with one provider-neutral timeout constant, and tighten instructions/UI without adding an execution capability.

**Tech Stack:** Python 3.11+, pytest, official OpenAI Python SDK, standard-library dataclasses/enums, vanilla JavaScript, Node test runner.

**Spec:** `docs/superpowers/specs/2026-08-31-post-mutation-convergence-and-transient-narration-design.md`

## Global Constraints

- Work in the current `main` workspace explicitly authorized by the user; do not create a branch or worktree.
- Do not stage, commit, push, pull, fetch, or contact a remote repository.
- Do not call a real provider, read a real API key, or add a dependency.
- Do not use subagents or parallel agents for these tightly coupled core changes.
- Keep `ModelClient.complete(ModelRequest) -> ModelResponse`, message JSON, ToolRegistry, REST/SSE DTOs, SQLite schema, and all Task8 safety allowlists unchanged.
- Keep Standard and Deep budget values unchanged.
- Do not add PTY, WSL, Bash, PowerShell, `cmd`, `make`, `g++`, arbitrary executable, delete, move, or cleanup tools.
- Keep Task7 semantics: a launched process with a nonzero exit code is a tool result with `status="ok"`; only presentation changes.
- Keep Task9 retry semantics: transient provider errors may make at most three physical attempts per logical call.
- `DEFAULT_PROVIDER_TIMEOUT_SECONDS` is exactly `30.0` and is passed only when production code constructs the official SDK client.
- Historical persisted assistant messages are not migrated or deleted.
- Every production behavior follows RED, minimal GREEN, targeted regression, then the next behavior.
- Task32 remains `进行中` after implementation and verification pending user review.

## Locked File Map

### Production code

- Modify `src/coding_agent/verification.py`: add provider-neutral monotonic evidence comparison while preserving `VerificationResult` and `VerificationGate.observe_tool_result(...) -> bool`.
- Modify `src/coding_agent/progress.py`: rename the internal keyword-only observation input to `verification_advanced` without changing thresholds or enums.
- Modify `src/coding_agent/agent.py`: compare old/new evidence, activate the post-mutation checkpoint, emit its stable reason, and commit only tool-free text.
- Modify `src/coding_agent/logging.py`: allow `post_mutation_integrity` as a decision checkpoint reason.
- Modify `src/coding_agent/session_controller.py`: discard pending tool-response narration before publishing the first tool activity.
- Modify `src/coding_agent/model.py`: define `DEFAULT_PROVIDER_TIMEOUT_SECONDS = 30.0`.
- Modify `src/coding_agent/openai_client.py`: pass the timeout when constructing the official Responses SDK client.
- Modify `src/coding_agent/chat_completions_client.py`: pass the timeout when constructing the official Chat SDK client.
- Modify `src/coding_agent/instructions.py`: add exact test-first, interactive-verification, and no-ephemeral-diagnostic contracts.
- Modify `src/coding_agent/web_static/app.js`: render integer command exit codes as `exit N` instead of tool-layer `ok`.

### Tests

- Modify `tests/test_verification.py`.
- Modify `tests/test_progress.py`.
- Modify `tests/test_agent_loop.py`.
- Modify `tests/test_logging.py`.
- Modify `tests/test_session_controller.py`.
- Modify `tests/test_model.py`.
- Modify `tests/test_openai_client.py`.
- Modify `tests/test_chat_completions_client.py`.
- Modify `tests/test_instructions.py`.
- Modify `tests/js/web_gui.test.mjs`.

### Design and public documentation

- Modify `DESIGN.md`.
- Modify `TASKS.md` only for Task31/Task32 status and the approved Task32 definition.
- Modify `AGENTS.md`, `README.md`, `README.txt`, and `docs/USAGE.md` only to document verified contracts.
- Keep `pyproject.toml`, message types, safety/tools, Session schemas, Web DTOs, and provider request mapping otherwise unchanged.

## Locked Interfaces

```python
# src/coding_agent/model.py
DEFAULT_PROVIDER_TIMEOUT_SECONDS = 30.0
```

```python
# src/coding_agent/verification.py
def verification_advances_progress(
    previous: VerificationResult | None,
    current: VerificationResult,
) -> bool: ...
```

The comparison is exact:

```text
no previous evidence                         -> true
current.validation_index > previous index    -> true
same index and status changed                -> true
same index/status and source rank increased  -> true
otherwise                                    -> false

LOCAL_INTEGRITY rank 0 < MODEL rank 1 < USER_VERIFY rank 2
```

Lower validation indexes are never progress. Command/output/duration differences are never progress.

```python
# src/coding_agent/progress.py
ProgressLedger.observe_tool(
    call: ToolCall,
    result: ToolResult,
    *,
    mutation_advanced: bool,
    verification_advanced: bool,
    mutation_epoch: int = 0,
) -> ProgressStrength
```

No new event kinds, state fields, termination reasons, persistence columns, or provider types are introduced.

---

### Task 0: Baseline, Approved State, and Task Status

**Files:**
- Read: all files in the locked map.
- Modify after a green baseline: `TASKS.md`.

**Interfaces:**
- Consumes: current Task31 working tree and existing Task1–Task31 behavior.
- Produces: a recorded clean test baseline and exactly one `进行中` task, Task32.

- [ ] **Step 1: Inspect the current repository without changing it**

Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git log -3 --oneline
git status --short --untracked-files=all
git diff --check
```

Expected: repository root is `D:\code\coding_agent`, branch is `main`, whitespace check exits 0. Existing Task29–Task31/user changes are preserved and reviewed rather than reverted.

- [ ] **Step 2: Run the full pre-change baseline**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
node --test tests/js/web_gui.test.mjs
```

Expected: both commands exit 0. Record actual pass/fail/skip/warning totals. If either fails, use `superpowers:systematic-debugging` before any Task32 production edit.

- [ ] **Step 3: Update task state only after the green baseline**

Modify `TASKS.md` so Task31 is `已完成`, append the approved Task32 definition, and set Task32 to `进行中`. Verify only Task32 is in progress:

```powershell
rg -n -C 2 "当前状态|进行中" TASKS.md
```

Expected: exactly one task status value is `进行中`.

**Acceptance:** baseline evidence exists; no unapproved file was reverted; Task32 is the only active task.

---

### Task 1: Monotonic Verification Progress

**Files:**
- Modify: `tests/test_verification.py`.
- Modify: `tests/test_progress.py`.
- Modify: `tests/test_agent_loop.py`.
- Modify: `src/coding_agent/verification.py`.
- Modify: `src/coding_agent/progress.py`.
- Modify: `src/coding_agent/agent.py`.

**Interfaces:**
- Consumes: existing `VerificationResult`, `CommandSource`, `ProgressLedger`, and `VerificationGate.observe_tool_result`.
- Produces: `verification_advances_progress(...)` and the renamed `verification_advanced` ledger input.

- [ ] **Step 1: Add failing evidence-comparison tests**

Add a local factory in `tests/test_verification.py` that creates valid evidence without sensitive output:

```python
def _progress_evidence(
    *,
    status: VerificationStatus = VerificationStatus.PASSED,
    validation_index: int = 1,
    source: CommandSource = CommandSource.MODEL,
    command: str = "python -m pytest -q",
) -> VerificationResult:
    return VerificationResult(
        status=status,
        validation_index=validation_index,
        command=command,
        source=source,
        exit_code=0 if status is VerificationStatus.PASSED else 1,
        stdout="",
        stderr="",
        timed_out=False,
        truncated=False,
        duration_ms=1,
        error=None,
    )
```

Add parameterized assertions for the locked matrix:

```python
@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (None, _progress_evidence(), True),
        (_progress_evidence(validation_index=1),
         _progress_evidence(validation_index=2), True),
        (_progress_evidence(status=VerificationStatus.FAILED),
         _progress_evidence(status=VerificationStatus.PASSED), True),
        (_progress_evidence(source=CommandSource.LOCAL_INTEGRITY),
         _progress_evidence(source=CommandSource.MODEL), True),
        (_progress_evidence(), _progress_evidence(), False),
        (_progress_evidence(command="python -m pytest -q"),
         _progress_evidence(command="python -m unittest"), False),
        (_progress_evidence(source=CommandSource.MODEL),
         _progress_evidence(source=CommandSource.LOCAL_INTEGRITY), False),
        (_progress_evidence(validation_index=2),
         _progress_evidence(validation_index=1), False),
    ],
)
def test_verification_progress_is_monotonic(previous, current, expected):
    assert verification_advances_progress(previous, current) is expected
```

- [ ] **Step 2: Run RED for comparison**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_verification.py -k "verification_progress_is_monotonic" -q -p no:cacheprovider
```

Expected RED: import/attribute failure because `verification_advances_progress` does not exist.

- [ ] **Step 3: Implement the minimal comparison**

In `verification.py`, validate types, use a private fixed source-rank dictionary, reject lower indexes, and implement only the four true cases from the spec. Do not compare command or captured output.

- [ ] **Step 4: Run GREEN for comparison**

Run the Step 2 command again.

Expected GREEN: all new parameter cases pass.

- [ ] **Step 5: Add failing ledger and Agent wiring tests**

Update the direct `ProgressLedger.observe_tool` tests to use
`verification_advanced`. Add a focused test proving `verification_advanced=False`
does not clear an active checkpoint:

```python
ledger = ProgressLedger(checkpoint_active=True, post_checkpoint_main_turns=1)
ledger.begin_main_turn()
strength = ledger.observe_tool(
    verification_call,
    passed_result,
    mutation_advanced=False,
    verification_advanced=False,
)
ledger.finish_main_turn()
assert strength is not ProgressStrength.STRONG
assert ledger.checkpoint_active is True
```

In `tests/test_agent_loop.py`, use the existing offline verification tool and event
sink helpers to assert that two same-mutation `MODEL/PASSED` results are both
recorded, but the second emits progress weaker than `strong`.

- [ ] **Step 6: Run RED for ledger and Agent wiring**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_progress.py tests/test_agent_loop.py -k "verification and (monotonic or checkpoint or repeated)" -q -p no:cacheprovider
```

Expected RED: `observe_tool` does not accept `verification_advanced`, or repeated evidence still emits strong progress.

- [ ] **Step 7: Implement minimal wiring**

- Rename the keyword-only `ProgressLedger.observe_tool` input and type check.
- In `AgentRunner`, snapshot `state.last_verification` before `observe_tool_result`.
- If a fact was recorded, compare the snapshot with the new evidence.
- Pass the comparison result to `ProgressLedger`; continue emitting the existing evidence event whenever a fact was recorded.

- [ ] **Step 8: Run GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_verification.py tests/test_progress.py tests/test_agent_loop.py -q -p no:cacheprovider
```

Expected: exit 0 with actual counts reported; all existing verification attempt and audit assertions remain green.

**Acceptance:** evidence is never lost, but repeated same-tier evidence cannot reset the convergence state.

---

### Task 2: Post-Mutation Checkpoint

**Files:**
- Modify: `tests/test_agent_loop.py`.
- Modify: `tests/test_logging.py`.
- Modify: `src/coding_agent/agent.py`.
- Modify: `src/coding_agent/logging.py`.

**Interfaces:**
- Consumes: Task29 eager local integrity and Task26 `ProgressLedger.activate_checkpoint()`.
- Produces: stable `decision_checkpoint.reason == "post_mutation_integrity"`.

- [ ] **Step 1: Add failing Agent and log-schema tests**

Extend the existing eager-integrity test to collect run events and assert:

```python
assert state.progress.checkpoint_active is True
assert state.progress.post_checkpoint_read_batches == 0
assert any(
    event.event_type is EventType.DECISION_CHECKPOINT
    and event.data["reason"] == "post_mutation_integrity"
    for event in events
)
```

Add a `tests/test_logging.py` case using the existing logger factory:

```python
logger = RunEventLogger.create(tmp_path)
event = logger.emit(
    EventType.DECISION_CHECKPOINT,
    {
        "reason": "post_mutation_integrity",
        "phase": "verify",
        "main_calls_remaining": 23,
    },
)
logger.close()
assert event.data["reason"] == "post_mutation_integrity"
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py tests/test_logging.py -k "post_mutation_integrity" -q -p no:cacheprovider
```

Expected RED: successful eager integrity leaves the checkpoint inactive and/or log validation rejects the new reason.

- [ ] **Step 3: Implement minimal checkpoint activation**

After `_run_eager_local_integrity(state)` returns no termination reason, inspect the
fresh current evidence. If it is `LOCAL_INTEGRITY/PASSED` at the current mutation,
activate the checkpoint and emit one decision event. Do not activate this path for
forced verification, failed integrity, no mutation, cancellation, or budget failure.
Add the reason to the strict logging allowlist.

- [ ] **Step 4: Run GREEN and exact profile-boundary regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py tests/test_logging.py tests/test_progress.py -q -p no:cacheprovider
```

Expected: exit 0; existing Standard 1 / Deep 2 final-read tests remain green.

**Acceptance:** every eligible mutation epoch enters one honest convergence checkpoint without consuming its next-turn read allowance.

---

### Task 3: Tool Narration Is Provisional

**Files:**
- Modify: `tests/test_agent_loop.py`.
- Modify: `tests/test_session_controller.py`.
- Modify: `src/coding_agent/agent.py`.
- Modify: `src/coding_agent/session_controller.py`.

**Interfaces:**
- Consumes: unchanged `confirmed_text_handler(text: str)`, `ModelStreamEvent`, and existing `assistant_text_discarded` update.
- Produces: `tool_response_narration` as a stable discard reason; no new event kind or persistence row.

- [ ] **Step 1: Change the Agent expectation first**

Rename `test_confirmed_text_handler_receives_each_complete_main_text` to
`test_confirmed_text_handler_receives_only_tool_free_final_text` and keep the same
two fake responses. Change only the expected callback list:

```python
assert seen == ["Finished"]
```

Retain the existing assertion that the internal next request contains:

```python
AssistantMessage(content="I will inspect", tool_calls=(... ,))
```

- [ ] **Step 2: Run Agent RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -k "confirmed_text_handler_receives_only_tool_free_final_text" -q -p no:cacheprovider
```

Expected RED: actual callbacks are `['I will inspect', 'Finished']`.

- [ ] **Step 3: Implement minimal Agent callback ordering**

Move the confirmed callback into the tool-free branch. Do not remove text from the
internal `AssistantMessage` carrying tool calls. Preserve callback exceptions and
`BaseException` behavior.

- [ ] **Step 4: Run Agent GREEN**

Run the Step 2 command again.

Expected GREEN: one final callback and legal internal history.

- [ ] **Step 5: Add a failing Controller lifecycle test**

Add a test executor following existing controller fakes. Its `execute` method must:

1. call `stream_handler(ModelStreamEvent(TEXT_DELTA, "I will inspect"))`;
2. call `run_event_handler` with a valid `TOOL_CALL_STARTED` event;
3. return an existing safe failed outcome without invoking `confirmed_text_handler`.

Assert the selected live update order:

```python
assert selected == [
    SessionUpdateKind.ASSISTANT_TEXT_DELTA,
    SessionUpdateKind.ASSISTANT_TEXT_DISCARDED,
    SessionUpdateKind.TOOL_STARTED,
]
assert discarded.data == {"reason": "tool_response_narration"}
assert PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED not in durable_kinds
```

- [ ] **Step 6: Run Controller RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_controller.py -k "tool_response_narration" -q -p no:cacheprovider
```

Expected RED: no discard update is published and provisional text remains active.

- [ ] **Step 7: Implement minimal Controller discard**

Replace the direct lambda passed as `run_event_handler` with a closure. Before
delegating a `TOOL_CALL_STARTED` event, clear nonempty `pending_text` and publish the
existing discarded update with the fixed reason. Do not persist a discard row and do
not affect empty/non-streaming pending text.

- [ ] **Step 8: Run GREEN and session regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py tests/test_session_controller.py tests/test_session_events.py tests/test_session_store.py -q -p no:cacheprovider
```

Expected: exit 0; provider discard, mismatch, sync fallback, final commit, replay, and privacy tests remain green.

**Acceptance:** live narration is visible only while provisional; new session history contains only tool-free confirmed replies.

---

### Task 4: Bound Production Provider Waits

**Files:**
- Modify: `tests/test_model.py`.
- Modify: `tests/test_openai_client.py`.
- Modify: `tests/test_chat_completions_client.py`.
- Modify: `src/coding_agent/model.py`.
- Modify: `src/coding_agent/openai_client.py`.
- Modify: `src/coding_agent/chat_completions_client.py`.

**Interfaces:**
- Produces: `DEFAULT_PROVIDER_TIMEOUT_SECONDS = 30.0`.
- Preserves: both client constructor signatures, injected fake SDK behavior, request mapping, retries, and error classes.

- [ ] **Step 1: Add failing constant and factory tests**

In `tests/test_model.py`:

```python
def test_default_provider_timeout_is_fixed_and_positive() -> None:
    assert DEFAULT_PROVIDER_TIMEOUT_SECONDS == 30.0
```

Update the existing monkeypatched Responses factory assertion to:

```python
assert observed == {
    "api_key": FAKE_KEY,
    "max_retries": 0,
    "timeout": DEFAULT_PROVIDER_TIMEOUT_SECONDS,
}
```

Update the Chat factory assertion analogously, retaining `base_url`.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_model.py tests/test_openai_client.py tests/test_chat_completions_client.py -k "provider_timeout or disables_sdk_retries" -q -p no:cacheprovider
```

Expected RED: the constant is absent and SDK factories do not receive `timeout`.

- [ ] **Step 3: Implement minimal factory configuration**

Define the float constant in `model.py`, import it in both adapter modules, and add
`timeout=DEFAULT_PROVIDER_TIMEOUT_SECONDS` only to production `OpenAI(...)`
construction. Do not add the option to API request bodies or touch injected SDK
objects.

- [ ] **Step 4: Run GREEN and provider regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_model.py tests/test_openai_client.py tests/test_openai_streaming_client.py tests/test_chat_completions_client.py tests/test_chat_completions_streaming_client.py -q -p no:cacheprovider
```

Expected: exit 0; retry counts, partial-text discard, sync fallback, usage, strict schema, and privacy remain unchanged.

**Acceptance:** production-owned SDK clients no longer inherit the long SDK default wait; all offline fakes remain network-free.

---

### Task 5: Honest Interactive Verification and Exit-Code UI

**Files:**
- Modify: `tests/test_instructions.py`.
- Modify: `tests/js/web_gui.test.mjs`.
- Modify: `src/coding_agent/instructions.py`.
- Modify: `src/coding_agent/web_static/app.js`.

**Interfaces:**
- Consumes: existing immutable instruction snapshot and `tool_finished` DTO.
- Produces: no new data type; only stricter instruction text and safer local presentation.

- [ ] **Step 1: Add failing instruction contract test**

Build modify instructions using the existing test helper and assert all fixed clauses:

```python
assert "focused regression test" in text
assert "one-off diagnostic scripts" in text
assert "must not bypass the command policy" in text
assert "interactive behavior" in text
assert "manual interaction remains unverified" in text
assert "real exit code" in text
```

Also assert the existing approved Python/Java commands and no-Bash/WSL text remain.

- [ ] **Step 2: Run instruction RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_instructions.py -k "interactive_verification" -q -p no:cacheprovider
```

Expected RED: the new fixed clauses are absent.

- [ ] **Step 3: Implement minimal instruction clauses**

Add one bounded paragraph to the fixed modify instruction body. Do not infer task
intent, name user files, add a tool, or change read-only authority. Keep summary
requests at `instructions=None` through existing behavior.

- [ ] **Step 4: Run instruction GREEN**

Run the Step 2 command again, then all instruction tests.

- [ ] **Step 5: Add failing Node exit-code tests**

Add three cases around `safeActivityDetails` through public `appendActivity`:

```javascript
gui.appendActivity(document, container, "tool_finished", {
  tool_name: "run_command",
  status: "ok",
  duration_ms: 188,
  exit_code: 1,
});
assert.equal(container.textContent.includes("exit 1"), true);
assert.equal(container.textContent.includes(" ok "), false);
```

Repeat for `exit_code: 0`, and retain a file-tool case with `exit_code: null` that
still renders `ok`.

- [ ] **Step 6: Run Node RED**

Run:

```powershell
node --test --test-name-pattern="tool activity renders real exit codes" tests/js/web_gui.test.mjs
```

Expected RED: the UI renders `ok` and omits `exit 1`.

- [ ] **Step 7: Implement minimal safe projection**

For `tool_finished`, use `Number.isInteger(data.exit_code)` to choose `exit N`; when
the value is not an integer, retain the existing status. Continue returning only
allowlisted scalar fields and never render output or command content.

- [ ] **Step 8: Run GREEN and GUI regression**

Run:

```powershell
node --test tests/js/web_gui.test.mjs
.\.venv\Scripts\python.exe -m pytest tests/test_instructions.py tests/test_web_gui.py tests/test_docs.py -q -p no:cacheprovider
```

Expected: both commands exit 0 with actual counts reported.

**Acceptance:** the model is told exactly what it may claim, and users can distinguish transport success from process success.

---

### Task 6: Design Baseline, Documentation, and Final Verification

**Files:**
- Modify: `DESIGN.md`.
- Modify: `TASKS.md`.
- Modify: `AGENTS.md`.
- Modify: `README.md`.
- Modify: `README.txt`.
- Modify: `docs/USAGE.md`.
- Read/review: the complete Task32 diff.

**Interfaces:**
- Documents only behavior proven in Tasks 1–5.
- Leaves Task32 `进行中` for user review.

- [ ] **Step 1: Update design and project instructions**

Document the monotonic evidence rule, post-mutation checkpoint, tool-free commit
rule, 30-second SDK timeout, interactive verification limitation, and exit-code UI.
State explicitly that no PTY/C++ tool/delete tool was added and local integrity is not
behavioral verification.

- [ ] **Step 2: Update public docs without overstating guarantees**

README files and `docs/USAGE.md` must explain:

- command cards display `exit N` for processes;
- interactive programs require adapter tests or manual verification;
- production SDK networking has a 30-second operation timeout and existing retries;
- MiniCodex does not provide PTY/manual interaction automation;
- one-off scripts must not be created merely to bypass command safety.

- [ ] **Step 3: Run focused Python tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_verification.py tests/test_progress.py tests/test_agent_loop.py tests/test_logging.py tests/test_session_controller.py tests/test_model.py tests/test_openai_client.py tests/test_openai_streaming_client.py tests/test_chat_completions_client.py tests/test_chat_completions_streaming_client.py tests/test_instructions.py tests/test_web_gui.py tests/test_docs.py -q -p no:cacheprovider
```

Expected: exit 0; record real totals.

- [ ] **Step 4: Run full Python and Node suites**

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
node --test tests/js/web_gui.test.mjs
```

Expected: both exit 0; report actual passed/failed/skipped/warning counts.

- [ ] **Step 5: Run Windows-specific safety regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_path_safety.py tests/tools/test_shell_tool.py tests/tools/test_java_tool.py -q -p no:cacheprovider
```

Expected: reparse/junction/symlink and process-tree tests execute rather than being permanently skipped.

- [ ] **Step 6: Run static audits**

```powershell
git diff --check
.\.venv\Scripts\python.exe -m pip check
rg -n "langchain|llamaindex|openai-agents|autogen|crewai" pyproject.toml src tests
rg -n "OPENAI_API_KEY\s*=|CHAT_COMPLETIONS_API_KEY\s*=|Authorization:\s*Bearer\s+[^<'\"]" . --glob '!*.jsonl' --glob '!sessions.sqlite3*'
rg -n "TODO|TBD|FIXME|pytest\.skip|@pytest\.mark\.skip|xfail" src tests DESIGN.md TASKS.md AGENTS.md README.md README.txt docs
rg -n "subprocess|shell=True|\bWSL\b|\bbash\b|\bg\+\+\b|\bmake\b" src/coding_agent
git status --short --untracked-files=all
git diff --stat
git diff -- src/coding_agent tests DESIGN.md TASKS.md AGENTS.md README.md README.txt docs/USAGE.md
```

Expected: no new dependency/framework/credential/test-suppression finding; every shell/compiler match is an existing denylist, documentation statement, or approved implementation boundary. Review every diff hunk manually.

- [ ] **Step 7: Verify the acceptance matrix**

| Requirement | Fresh evidence |
|---|---|
| Same-tier verification does not reset progress | verification/progress/Agent tests |
| Evidence status/source/index upgrades still progress | parameterized comparison tests |
| Local integrity pass activates checkpoint | Agent and logging tests |
| Standard 1 / Deep 2 unchanged | existing ProgressLedger profile tests |
| Tool narration not persisted | Agent callback and Controller lifecycle tests |
| Internal tool-call message pairing remains | Agent history tests |
| Responses production timeout is 30.0 | SDK factory test |
| Chat production timeout is 30.0 | SDK factory test |
| Existing timeout retry/privacy remains | full provider tests |
| Nonzero process displays `exit 1` | Node GUI test |
| File tools still display status | Node GUI test |
| Interactive verification claims are bounded | instruction and docs tests |
| No diagnostic-script safety bypass is encouraged | instruction contract test |
| No new authority/dependency/schema | audits and full diff review |
| Complete regression is green | full Python/Node/Windows commands |

- [ ] **Step 8: Stop for user review**

Keep Task32 `进行中`. Do not stage, commit, push, start a later task, or modify the
separate generated snake workspace. Report all RED/GREEN commands, final counts,
warnings/skips, modified files, `git status`, and any remaining limitation.

**Acceptance:** every claimed behavior has fresh evidence and the repository is ready for human review without a commit.

# Task29 Directory Mutation and Chat Stream Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` and `superpowers:test-driven-development` to implement this plan task-by-task. Use `superpowers:systematic-debugging` before changing code after an unexpected failure, and `superpowers:verification-before-completion` before reporting completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one-level safe directory creation, response-scoped safety-rejection counting, deterministic post-mutation local-integrity validation, and one synchronous Chat Completions fallback for structurally invalid streams that produced no public text.

**Architecture:** Keep all existing provider-neutral public interfaces. `CreateDirectoryTool` uses a new `PathGuard.new_directory` check and the existing mutation ledger. `AgentRunner` settles safety rejection counters per complete tool response and runs eligible local integrity once after a mutation batch. `ChatCompletionsModelClient` keeps strict stream parsing and performs exactly one non-stream request inside the same logical call only when an invalid stream exposed no text.

**Tech Stack:** Python 3.11+, standard library, official `openai` Python SDK at the existing adapter boundary, pytest, Windows PowerShell.

**Spec:** `docs/superpowers/specs/2026-08-31-directory-mutation-and-chat-stream-fallback-design.md`

## Global Constraints

- Work in `D:\code\coding_agent` on the current `main` workspace; do not create a branch or worktree unless the user explicitly changes this instruction.
- Do not dispatch subagents unless the user explicitly authorizes them for execution.
- Do not stage, commit, push, pull, fetch, or access a remote repository.
- Task29 remains `进行中` after implementation and verification; wait for user review before marking it complete.
- Do not access a real API key or make a real provider request. Every provider test injects a fake SDK resource.
- Add no dependency and change no public message, `ModelClient`, streaming Protocol, Session, REST, SSE, or GUI schema.
- Keep Responses API behavior unchanged and keep OpenAI SDK imports confined to existing provider adapter files.
- Keep `write_file` create-only and non-recursive. `create_directory` creates exactly one absent directory whose direct parent already exists.
- Keep `.git/` and `.coding-agent/` protected and reject symlink, junction, and reparse-point traversal.
- Never accept malformed Chat call IDs, arguments, finish reasons, response IDs, usage, message order, or provider payloads. Recovery changes transport shape, not parser strictness.
- A stream that emitted any public text never falls back to sync. Partial public text is discarded and never persisted.
- One invalid stream may cause exactly one sync attempt. Both attempts consume the same run-scoped provider budget and one logical call.
- Post-mutation local integrity is eligible only when no user `--verify` is configured and no stale model/user verification evidence forbids fallback. It never declares success without later final text.
- Preserve the existing unrelated dirty GUI paths exactly: `src/coding_agent/web_static/app.js`, `src/coding_agent/web_static/index.html`, `src/coding_agent/web_static/styles.css`, `tests/js/web_gui.test.mjs`, and `tests/test_web_gui.py`.
- Do not modify `src/coding_agent/messages.py`, `src/coding_agent/model.py`, `src/coding_agent/streaming.py`, `src/coding_agent/openai_client.py`, Session/Web/GUI modules, or `pyproject.toml`.

## Locked File Map

**Production files to modify**

- `src/coding_agent/safety.py` — add `PathGuard.new_directory` only.
- `src/coding_agent/tools/filesystem.py` — add `CreateDirectoryTool` and its exact argument set/schema.
- `src/coding_agent/app.py` — register `CreateDirectoryTool` only in modify mode.
- `src/coding_agent/instructions.py` — advertise the seven modify tools and deterministic directory/verification guidance.
- `src/coding_agent/agent.py` — add parent correction, response-scoped safety settlement, eager local-integrity execution, and fresh-integrity completion guidance.
- `src/coding_agent/verification.py` — validate safe directory entries as changed paths while preserving file checks.
- `src/coding_agent/chat_completions_client.py` — add Chat-only no-public-text invalid-stream sync fallback and a private single-attempt sync path.

**Tests to modify**

- `tests/test_path_safety.py`
- `tests/tools/test_write_tools.py`
- `tests/test_app.py`
- `tests/test_instructions.py`
- `tests/test_agent_loop.py`
- `tests/test_verification.py`
- `tests/test_chat_completions_streaming_client.py`
- `tests/integration/test_chat_completions_agent.py`
- `tests/integration/test_adaptive_convergence.py`
- `tests/test_docs.py`

**Design and public documentation to modify**

- `TASKS.md`
- `DESIGN.md`
- `AGENTS.md`
- `README.md`
- `README.txt`
- `docs/USAGE.md`
- `docs/OPENAI_API.md`

**Existing approved artifacts to retain**

- `docs/superpowers/specs/2026-08-31-directory-mutation-and-chat-stream-fallback-design.md`
- `docs/superpowers/plans/Task29.md`

---

### Task 0: Baseline, ownership boundary, and Task status

**Files:**

- Read: `AGENTS.md`
- Read: `DESIGN.md`
- Read: `TASKS.md`
- Read: `docs/superpowers/specs/2026-08-31-directory-mutation-and-chat-stream-fallback-design.md`
- Read: every production and test file in the locked file map
- Modify: `TASKS.md`

**Interfaces:**

- Consumes the existing Task1–Task28 baseline at HEAD `54f22fd` or a later user-approved commit.
- Produces one `TASKS.md` Task29 entry with state `进行中`; earlier completed states remain unchanged.

- [ ] **Step 1: Confirm repository and preserve pre-existing changes**

Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git log -5 --oneline
git status --short --untracked-files=all
git diff --check
```

Expected: root is `D:/code/coding_agent`, branch is `main`, whitespace check exits 0, and the only pre-existing non-Task29 modifications are the five GUI paths listed in Global Constraints. The approved untracked spec and this plan are also allowed. Any additional path stops execution for user review.

- [ ] **Step 2: Run the fresh baseline**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
node --test tests/js/web_gui.test.mjs
```

Expected: both commands exit 0. Record actual passed, failed, skipped, warning, and Node test counts; do not substitute counts from this plan. A failure stops Task29 before status or production changes.

- [ ] **Step 3: Append Task29 as the only active task**

Add a `TASKS.md` section titled `## 29. 目录修改、验证收敛与 Chat 流式兼容回退` containing the spec goal, locked acceptance bullets, required tests, suggested commit message `feat: add directory mutation and safe chat stream recovery`, and current state `进行中`.

Run:

```powershell
rg -n "^## 29\.|`进行中`|目录修改|流式兼容" TASKS.md
```

Expected: Task29 appears once and is the only task marked `进行中`. Do not stage or commit.

**Acceptance:** baseline is green, unrelated GUI changes are preserved, and Task29 is the single active task.

---

### Task 1: Safe one-level directory target resolution

**Files:**

- Modify: `src/coding_agent/safety.py`
- Test: `tests/test_path_safety.py`

**Interfaces:**

- Consumes: `PathGuard._relative_parts`, `_reject_protected`, `_reject_reparse_components`, `_contained`, and `GuardedPath`.
- Produces: `PathGuard.new_directory(self, raw_path: object) -> GuardedPath`.

- [ ] **Step 1: Write the failing target-resolution tests**

Append tests with these exact public assertions:

```python
def test_new_directory_returns_absent_target_under_real_parent(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "Project"
    parent.mkdir()

    guarded = PathGuard(tmp_path).new_directory(r"Project\src")

    assert guarded == GuardedPath(
        absolute=parent.resolve() / "src",
        relative="Project/src",
    )
    assert guarded.absolute.exists() is False


@pytest.mark.parametrize(
    ("raw_path", "code"),
    [
        (".", SafetyCode.PATH_TYPE_MISMATCH),
        ("missing/child", SafetyCode.PARENT_NOT_FOUND),
        ("existing", SafetyCode.PATH_TYPE_MISMATCH),
        ("parent.txt/child", SafetyCode.PATH_TYPE_MISMATCH),
        (".git/generated", SafetyCode.PROTECTED_PATH),
        ("../outside", SafetyCode.PATH_OUTSIDE_WORKSPACE),
    ],
)
def test_new_directory_rejects_invalid_target_or_parent(
    tmp_path: Path,
    raw_path: str,
    code: SafetyCode,
) -> None:
    (tmp_path / "existing").mkdir()
    (tmp_path / "parent.txt").write_text("x", encoding="utf-8")

    _assert_violation(
        code,
        lambda: PathGuard(tmp_path).new_directory(raw_path),
    )
```

Extend the existing real Windows reparse/junction test so both `new_file` and `new_directory` reject a reparse parent with `SafetyCode.REPARSE_POINT_DENIED`. The test must execute on Windows rather than add a permanent skip.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_path_safety.py -k "new_directory or junction_escape"
```

Expected RED: non-zero exit because `PathGuard` has no `new_directory` method. A fixture, permission, or link-creation failure is not the expected RED and requires systematic debugging.

- [ ] **Step 3: Add the minimal resolver**

Implement the method beside `new_file`, using the same order of deterministic checks:

```python
def new_directory(self, raw_path: object) -> GuardedPath:
    parts = self._relative_parts(raw_path)
    self._reject_protected(parts)
    self._reject_reparse_components(parts)
    if not parts:
        raise SafetyViolation(
            SafetyCode.PATH_TYPE_MISMATCH,
            "new directory path must name a directory",
        )
    candidate = self._workspace.joinpath(*parts)
    self._contained(candidate)
    if candidate.exists() or candidate.is_symlink():
        raise SafetyViolation(
            SafetyCode.PATH_TYPE_MISMATCH,
            "target already exists",
        )
    parent = candidate.parent
    if not parent.exists():
        raise SafetyViolation(
            SafetyCode.PARENT_NOT_FOUND,
            "parent directory does not exist",
        )
    if not parent.is_dir():
        raise SafetyViolation(
            SafetyCode.PATH_TYPE_MISMATCH,
            "parent path is not a directory",
        )
    resolved_parent = parent.resolve(strict=True)
    self._contained(resolved_parent)
    return GuardedPath(resolved_parent / candidate.name, "/".join(parts))
```

Do not call `mkdir`, `resolve(strict=False)`, recursive creation, or filesystem deletion from `PathGuard`.

- [ ] **Step 4: Run GREEN and path regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_path_safety.py -k "new_directory or new_file or junction or reparse or protected"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_path_safety.py tests/tools/test_read_tools.py tests/tools/test_write_tools.py
```

Expected: both commands exit 0 with no skips introduced.

**Acceptance:** one absent target under one existing safe parent is returned; unsafe, existing, protected, outside, or reparse paths are rejected before mutation.

---

### Task 2: `CreateDirectoryTool` strict schema and atomic execution

**Files:**

- Modify: `src/coding_agent/tools/filesystem.py`
- Test: `tests/tools/test_write_tools.py`

**Interfaces:**

- Consumes: `JSONObject`, `ExecutionContext`, `ToolExecution`, `_require_exact_arguments`, `_json_execution`, and `PathGuard.new_directory`.
- Produces: `CreateDirectoryTool.name == "create_directory"`, the exact strict schema from the spec, and `ToolResultMetadata.changed_paths` containing one normalized directory path.

- [ ] **Step 1: Write failing schema and execution tests**

Add `CreateDirectoryTool` to the test import and append:

```python
def test_create_directory_schema_is_strict_and_complete() -> None:
    assert CreateDirectoryTool.schema == {
        "name": "create_directory",
        "description": (
            "Create exactly one new directory whose parent already exists."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "minLength": 1}},
            "required": ["path"],
            "additionalProperties": False,
        },
    }


def test_create_directory_creates_one_level_and_reports_path(
    tmp_path: Path,
) -> None:
    (tmp_path / "project").mkdir()

    execution = CreateDirectoryTool().execute(
        {"path": r"project\src"},
        _context(tmp_path),
    )

    assert (tmp_path / "project" / "src").is_dir()
    assert _json_output(execution) == {"path": "project/src"}
    assert execution.metadata == ToolResultMetadata(
        changed_paths=("project/src",)
    )


@pytest.mark.parametrize(
    "arguments",
    [{}, {"path": "one", "extra": True}, {"path": "missing/child"}],
)
def test_create_directory_rejects_invalid_arguments_without_side_effect(
    tmp_path: Path,
    arguments: JSONObject,
) -> None:
    with pytest.raises((ToolArgumentError, SafetyViolation)):
        CreateDirectoryTool().execute(arguments, _context(tmp_path))
    assert list(tmp_path.iterdir()) == []
```

Add a race test that monkeypatches `Path.mkdir` to raise `FileExistsError` after resolution, and assert a stable `ToolArgumentError("target already exists")`, no changed paths, and no recursive parent creation.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/tools/test_write_tools.py -k "create_directory"
```

Expected RED: import failure because `CreateDirectoryTool` does not exist. Do not add production code until that is the only failure category.

- [ ] **Step 3: Implement the minimal tool**

Add `_CREATE_DIRECTORY_ARGUMENTS = {"path"}` and the locked class before `ReplaceTextTool`:

```python
class CreateDirectoryTool:
    name = "create_directory"
    schema: JSONObject = {
        "name": "create_directory",
        "description": (
            "Create exactly one new directory whose parent already exists."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "minLength": 1}},
            "required": ["path"],
            "additionalProperties": False,
        },
    }

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        values = _require_exact_arguments(
            arguments,
            _CREATE_DIRECTORY_ARGUMENTS,
            self.name,
        )
        guarded = PathGuard(context.workspace).new_directory(values["path"])
        try:
            guarded.absolute.mkdir()
        except FileExistsError as exc:
            raise ToolArgumentError("target already exists") from exc
        except FileNotFoundError as exc:
            raise ToolArgumentError("parent directory does not exist") from exc
        except NotADirectoryError as exc:
            raise ToolArgumentError("parent path is not a directory") from exc
        except OSError as exc:
            raise ToolArgumentError("directory could not be created") from exc
        return _json_execution(
            {"path": guarded.relative},
            changed_paths=(guarded.relative,),
        )
```

Do not catch `BaseException`; do not include `str(exc)` in public output.

- [ ] **Step 4: Run GREEN and filesystem regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/tools/test_write_tools.py -k "create_directory"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_path_safety.py tests/tools/test_read_tools.py tests/tools/test_write_tools.py
```

Expected: exit 0; no change to replace/write/read semantics.

**Acceptance:** the tool creates exactly one directory, reports one normalized changed path, rejects races safely, and never recursively creates parents.

---

### Task 3: Modify-mode composition, instructions, and deterministic parent correction

**Files:**

- Modify: `src/coding_agent/app.py`
- Modify: `src/coding_agent/instructions.py`
- Modify: `src/coding_agent/agent.py`
- Test: `tests/test_app.py`
- Test: `tests/test_instructions.py`
- Test: `tests/test_agent_loop.py`

**Interfaces:**

- Produces the exact modify tool order `list_directory`, `read_file`, `create_directory`, `replace_text`, `write_file`, `run_command`, `run_java_tests`.
- Keeps the read-only tool order unchanged.
- Adds private `_with_parent_correction(result: ToolResult) -> ToolResult`; public message prefix remains `security_rejected:parent_not_found`.

- [ ] **Step 1: Write the failing composition and instruction tests**

Rename the existing app test to `test_modify_run_composes_exact_seven_tools` and change only its expected schema tuple by inserting `create_directory` after `read_file`. Add `create_directory` to the modify instruction assertions and to the read-only unavailable tuple.

Add this Agent test:

```python
def test_parent_not_found_feedback_names_create_directory(
    tmp_path: Path,
) -> None:
    call = ToolCall(
        "write",
        "write_file",
        {"path": "missing/main.cpp", "content": "int main() {}\n"},
    )
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="blocked")),
        tools=(WriteFileTool(),),
    )

    runner.run("create a nested project")

    result = next(
        item
        for item in client.requests[1].messages
        if isinstance(item, ToolResult) and item.call_id == "write"
    )
    assert result.error == (
        "security_rejected:parent_not_found: parent directory does not "
        "exist; call create_directory once for each missing parent, from "
        "shallowest to deepest"
    )
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_app.py tests/test_instructions.py tests/test_agent_loop.py -k "seven_tools or create_directory or parent_not_found_feedback"
```

Expected RED: modify registry/instructions omit `create_directory`, and parent feedback lacks the correction. Read-only expectations must remain green.

- [ ] **Step 3: Implement the minimal composition and correction**

- Import and register `CreateDirectoryTool()` in `app.py` at the locked position only for `RunMode.MODIFY`.
- Update `_RUN_MODE_INSTRUCTIONS[RunMode.MODIFY]` to name seven tools and state that `create_directory` creates one level and must precede `write_file` for missing parents.
- Add `_with_parent_correction` beside `_with_command_correction`; it returns a new `ToolResult` only for the exact `security_rejected:parent_not_found` prefix and preserves output, metadata, `call_id`, name, and status.
- Apply the helper immediately after `ToolRegistry.execute`; do not modify `ToolRegistry` or `PathGuard` error serialization.

- [ ] **Step 4: Run GREEN and mode regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_app.py tests/test_instructions.py tests/test_agent_loop.py -k "tools or instruction or parent_not_found or read_only"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_app.py tests/test_instructions.py tests/integration/test_read_only_agent.py
```

Expected: exit 0; read-only never receives `create_directory` and never constructs a verification gate.

**Acceptance:** modify exposes exactly seven tools, read-only remains exact, and missing parents receive a bounded correction without automatic execution.

---

### Task 4: Response-scoped safety-rejection settlement

**Files:**

- Modify: `src/coding_agent/agent.py`
- Test: `tests/test_agent_loop.py`
- Test: `tests/integration/test_adaptive_convergence.py`

**Interfaces:**

- Keeps `AgentState.consecutive_safety_rejections` and `TerminationLimits.safety_rejection_limit == 3` unchanged.
- Adds private `AgentRunner._settle_safety_rejection_batch(state: AgentState, executed_results: tuple[ToolResult, ...]) -> None`.
- `_record_tool_observation` continues ordinary tool-error and repeat-fingerprint accounting but no longer increments safety once per call.

- [ ] **Step 1: Write failing response-boundary tests**

Add tests that use one `RecordingTool` scripted with safety violations:

```python
def test_three_safety_rejections_in_one_response_count_once(
    tmp_path: Path,
) -> None:
    denied = lambda: SafetyViolation(SafetyCode.PARENT_NOT_FOUND, "missing")
    tool = RecordingTool(denied(), denied(), denied())
    calls = tuple(_record_call(index) for index in range(3))
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=calls),
            ModelResponse(text="corrected after one rejected response"),
        ),
        tools=(tool,),
    )

    state = runner.run("create files under a missing directory")

    assert state.consecutive_safety_rejections == 1
    assert len(client.requests) == 2
    paired = [m for m in client.requests[1].messages if isinstance(m, ToolResult)]
    assert [item.call_id for item in paired] == [call.call_id for call in calls]


def test_three_separate_safety_only_responses_still_stop_at_three(
    tmp_path: Path,
) -> None:
    denied = lambda: SafetyViolation(SafetyCode.ARGUMENT_DENIED, "denied")
    tool = RecordingTool(denied(), denied(), denied())
    runner, client = _runner(
        tmp_path,
        tuple(
            ModelResponse(tool_calls=(_record_call(index),))
            for index in range(3)
        ),
        tools=(tool,),
    )

    state = runner.run("three rejected turns")

    assert state.termination_reason is TerminationReason.CONSECUTIVE_SAFETY_REJECTIONS
    assert state.consecutive_safety_rejections == 3
    assert len(client.requests) == 3
```

Add one mixed batch test: safety rejection plus `ToolExecution(output="ok")` resets safety to 0. Keep all existing `call_id` pairing assertions.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_loop.py -k "safety_rejections_in_one_response or separate_safety_only or mixed_safety"
```

Expected RED: the first test terminates after the third sibling call or reports count 3 because current accounting is per tool call.

- [ ] **Step 3: Implement batch settlement**

- Remove only the safety-counter mutations from `_record_tool_observation`; preserve ordinary error and repeat-fingerprint behavior.
- Collect `result` values only when `executed is True` during one model response.
- After the response's tool loop completes, call `_settle_safety_rejection_batch`:

```python
@staticmethod
def _settle_safety_rejection_batch(
    state: AgentState,
    executed_results: tuple[ToolResult, ...],
) -> None:
    if not executed_results:
        return
    safety_only = all(
        result.status == "rejected"
        and result.error is not None
        and result.error.startswith("security_rejected:")
        for result in executed_results
    )
    if safety_only:
        state.consecutive_safety_rejections += 1
    else:
        state.consecutive_safety_rejections = 0
```

Do not settle a partially executed batch after cancellation or an immediate hard-budget termination. Do not remove paired unexecuted results.

- [ ] **Step 4: Run GREEN and termination regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_loop.py -k "safety or tool_error or repeated_tool or cancellation"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_loop.py tests/test_termination.py tests/integration/test_agent_failures.py tests/integration/test_adaptive_convergence.py
```

Expected: exit 0; the threshold remains three separate rejected responses, and ordinary tool errors keep their prior behavior.

**Acceptance:** sibling rejections cannot exhaust the run before a correction turn, while three genuinely consecutive rejected responses still stop safely.

---

### Task 5: Directory-aware integrity and eager post-mutation validation

**Files:**

- Modify: `src/coding_agent/verification.py`
- Modify: `src/coding_agent/agent.py`
- Test: `tests/test_verification.py`
- Test: `tests/test_agent_loop.py`
- Test: `tests/test_app.py`

**Interfaces:**

- Keeps `VerificationGate.evaluate(state: AgentState) -> VerificationDecision` unchanged.
- Adds private `AgentRunner._run_eager_local_integrity(state: AgentState) -> TerminationReason | None`.
- Adds private constant `_FRESH_LOCAL_INTEGRITY_INSTRUCTION` with no path or provider data.
- Local-integrity JSON keeps keys `checked_paths` and `syntax_checked`; directories appear only in `checked_paths`.

- [ ] **Step 1: Write failing directory-integrity tests**

Append:

```python
def test_local_integrity_accepts_safe_directory_and_file_paths(
    tmp_path: Path,
) -> None:
    (tmp_path / "snake").mkdir()
    (tmp_path / "snake" / "main.cpp").write_text(
        "int main() { return 0; }\n",
        encoding="utf-8",
    )
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    state.mutation_index = 2
    state.modified_paths = ("snake", "snake/main.cpp")
    state.verification_status = VerificationStatus.STALE

    decision = gate.evaluate(state)

    assert decision.outcome is VerificationOutcome.SUCCESS
    assert decision.result is not None
    assert json.loads(decision.result.stdout) == {
        "checked_paths": ["snake", "snake/main.cpp"],
        "syntax_checked": [],
    }
```

Extend missing/reparse tests so a removed directory or reparse changed path fails with `invalid_changed_path`.

- [ ] **Step 2: Run directory RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_verification.py -k "safe_directory or directory_changed_path"
```

Expected RED: current code calls `existing_file` for the directory and returns `invalid_changed_path`.

- [ ] **Step 3: Implement directory-aware local integrity**

In `_evaluate_local_integrity`, resolve each path with `guard.existing_entry`. Branch deterministically:

```python
guarded = guard.existing_entry(relative_path)
if guarded.absolute.is_dir():
    checked_paths.append(guarded.relative)
    continue
if not guarded.absolute.is_file():
    failure = (guarded.relative, "invalid_changed_path")
    break
```

Keep the existing file byte, UTF-8, binary, and syntax checks byte-for-byte after that branch.

- [ ] **Step 4: Run directory GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_verification.py -k "local_integrity"
```

Expected: exit 0; all existing file-format cases remain green.

- [ ] **Step 5: Write failing eager-validation Agent tests**

Replace the old delayed-read expectation with the new behavior:

```python
def test_mutation_batch_runs_local_integrity_before_readback(
    tmp_path: Path,
) -> None:
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
    )
    write = ToolCall(
        "write",
        "write_file",
        {"path": "AGENTS.md", "content": "# Instructions\n"},
    )
    read = ToolCall(
        "read",
        "read_file",
        {"path": "AGENTS.md", "start_line": 1, "end_line": None},
    )
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(write,)),
            ModelResponse(tool_calls=(read,)),
            ModelResponse(text="AGENTS.md created and reviewed."),
        ),
        tools=(WriteFileTool(), ReadFileTool()),
        verification_gate=gate,
    )

    state = runner.run("create AGENTS.md")

    read_result = next(
        item
        for item in client.requests[2].messages
        if isinstance(item, ToolResult) and item.call_id == "read"
    )
    assert read_result.status == "ok"
    assert state.status is AgentStatus.SUCCESS
    assert state.verification_attempt_count == 1
    assert state.validation_index == state.mutation_index == 1
    assert state.tool_call_count == 3
    assert "already passed local integrity" in (
        client.requests[1].instructions or ""
    )
```

Add these independent tests:

- two successful mutations in one response produce `mutation_index == 2`, `verification_attempt_count == 1`, and `validation_index == 2`;
- eager pass leaves state running until the later final-text response;
- a failed eager check emits feedback, opens repair, and a repair mutation can be checked again;
- stale `CommandSource.MODEL` or `USER_VERIFY` evidence blocks local fallback after a later mutation;
- `VerificationGate(required_command=...)` does not execute the command at mutation-batch end;
- exact tool/time budget exhaustion blocks eager verification without incrementing `validation_index`;
- cancellation and `SystemExit` retain their existing propagation.

Update `test_three_security_rejections_after_mutation_end_changes_unverified` to use a required user verification command so the test still proves safety termination preserves unverified changes without conflicting with the new eligible local-integrity path.

- [ ] **Step 6: Run eager-validation RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_loop.py tests/test_app.py -k "mutation_batch or local_integrity or required_verification or stale_model_evidence"
```

Expected RED: the readback receives `agent_rejected:verification_required`, and local integrity occurs only after final text.

- [ ] **Step 7: Implement eager local integrity without changing success criteria**

At the start of a tool response, record `mutation_index_at_response_start`. After all calls, safety settlement, and cancellation checks, call `_run_eager_local_integrity` only when the mutation index advanced.

The helper must:

1. return immediately unless a gate exists, `gate.requires_execution` is false, and `gate.requires_local_integrity(state)` is true;
2. run `_policy_reason(state, NextOperation.VERIFICATION, verification_reserve_active=False)` before incrementing counters;
3. transition to `VERIFY`, emit the existing `VERIFICATION_STARTED` payload, and increment `tool_call_count` once;
4. call `gate.evaluate(state)`, map `VerificationError` to `INTERNAL_INVARIANT`, and emit `VERIFICATION_COMPLETED` only when a command/evaluation executed;
5. append failure feedback and reopen `ACT`/repair checkpoint when the result failed;
6. leave a passing state at `RUNNING` with fresh evidence; do not set `SUCCESS`, `completion_text`, or `required_verification_pending`.

When building later request instructions, append `_FRESH_LOCAL_INTEGRITY_INSTRUCTION` whenever the last result is fresh, passed, and from `CommandSource.LOCAL_INTEGRITY`. The fixed text is:

```python
_FRESH_LOCAL_INTEGRITY_INSTRUCTION = (
    "The current mutation epoch already passed deterministic local integrity "
    "validation. This is not test or compilation evidence. If the requested "
    "change is complete, return a final answer with no tool calls; otherwise "
    "continue only with necessary work."
)
```

- [ ] **Step 8: Run GREEN and full verification regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_loop.py tests/test_verification.py tests/test_app.py -k "integrity or verification or mutation or changes_unverified"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_loop.py tests/test_verification.py tests/test_report.py tests/test_logging.py tests/integration/test_adaptive_convergence.py tests/integration/test_agent_repair.py
```

Expected: exit 0. No test may treat local integrity as compilation or test execution.

**Acceptance:** directories are safe changed paths; every eligible mutation response is checked once; readback no longer loops on `verification_required`; final success still requires fresh evidence plus final text.

---

### Task 6: Chat invalid-stream single synchronous fallback

**Files:**

- Modify: `src/coding_agent/chat_completions_client.py`
- Test: `tests/test_chat_completions_streaming_client.py`
- Test: `tests/test_chat_completions_client.py`
- Test: `tests/test_streaming.py`

**Interfaces:**

- Keeps `ChatCompletionsModelClient.complete`, `complete_with_budget`, `stream`, and `stream_with_budget` public signatures unchanged.
- Extends private `_ChatStreamProgress` with `public_text_delta: bool = False` while retaining `provider_delta` for transient-interruption semantics.
- Adds private `_complete_with_attempt_limit(request: ModelRequest, budget: ModelCallBudget, *, max_attempts: int, fallback: bool) -> ModelResponse` or an equivalent private helper with the same locked behavior.

- [ ] **Step 1: Write failing fallback success tests**

Use `FakeSDK`, `FakeStream`, `chunk`, and a valid sync response. Add:

```python
def test_invalid_stream_before_public_text_uses_one_sync_attempt() -> None:
    invalid_stream = FakeStream(
        (chunk(delta=delta(), finish_reason=None),)
    )
    sync_response = ns(
        id="chat-sync",
        choices=[
            ns(
                finish_reason="stop",
                message=ns(
                    role="assistant",
                    content="fallback answer",
                    tool_calls=None,
                    function_call=None,
                ),
            )
        ],
        usage=None,
    )
    sdk = FakeSDK(invalid_stream, sync_response)
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=2)
    events: list[ModelStreamEvent] = []

    response = invoke_model_stream(
        client,
        ModelRequest(messages=(UserMessage("task"),)),
        budget,
        events.append,
    )

    assert response.text == "fallback answer"
    assert (budget.logical_calls, budget.provider_attempts) == (1, 2)
    assert [call.get("stream") for call in sdk.chat.completions.calls] == [
        True,
        None,
    ]
    assert [event.kind for event in events] == [
        ModelStreamEventKind.RESPONSE_COMPLETED
    ]
```

Add variants for an incomplete hidden tool call followed by a valid sync single tool, multiple tools in order, and text-plus-tools response.

- [ ] **Step 2: Run fallback RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_chat_completions_streaming_client.py -k "invalid_stream_before_public_text or hidden_invalid_stream"
```

Expected RED: `InvalidChatCompletionsResponseError` escapes after one call; the sync outcome remains unused.

- [ ] **Step 3: Implement one-attempt sync recovery**

- Refactor the existing sync body only enough that public `complete_with_budget` still requests at most three attempts with delays `0.25`, `0.50`, while fallback calls the same strict request mapping/parser with `max_attempts=1` and no sleep.
- Set `progress.public_text_delta = True` only after a non-empty text delta was successfully emitted.
- In the `APIResponseValidationError`/JSON-decode and `InvalidChatCompletionsResponseError` branches, finish the stream attempt as failed, then invoke one sync attempt only when `public_text_delta` is false.
- Do not convert `ModelOutputLimitError`, permanent provider errors, callback failures, cleanup failures, transient errors after provider delta, or `BaseException` into this recovery.

- [ ] **Step 4: Run initial GREEN and sync retry regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_chat_completions_streaming_client.py -k "invalid_stream_before_public_text or hidden_invalid_stream"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_chat_completions_client.py -k "retry or transient or invalid"
```

Expected: fallback tests pass; existing standalone sync transient tests still make exactly three attempts with delays `[0.25, 0.5]`.

- [ ] **Step 5: Add failure-boundary tests before completing production behavior**

Add exact assertions for:

```python
def test_invalid_stream_and_invalid_sync_stop_after_two_attempts() -> None:
    sdk = FakeSDK(
        FakeStream((chunk(delta=delta(), finish_reason=None),)),
        ns(id="bad", choices=[], usage=None),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )

    with pytest.raises(InvalidChatCompletionsResponseError):
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )

    assert len(sdk.chat.completions.calls) == 2


def test_invalid_stream_after_public_text_discards_without_sync() -> None:
    stream = FakeStream(
        (
            chunk(delta=delta(content="partial")),
            chunk(delta=delta(), finish_reason=None),
        )
    )
    sdk = FakeSDK(stream, object())
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )
    events: list[ModelStreamEvent] = []

    with pytest.raises(InvalidChatCompletionsResponseError):
        invoke_model_stream(
            client,
            ModelRequest(messages=(UserMessage("task"),)),
            ModelCallBudget(),
            events.append,
        )

    assert len(sdk.chat.completions.calls) == 1
    assert events[-1].kind is ModelStreamEventKind.RESPONSE_DISCARDED
```

Add provider-budget-one, sync transient error with an unused third outcome, callback failure, output limit, permanent error, cleanup error, `KeyboardInterrupt`, and `SystemExit` tests. Assert no third call and no provider body/key in exception, repr, capsys, or observer data.

Update existing invalid-shape tests deliberately:

- hidden invalid shapes now provide a valid sync outcome and assert two calls plus strict provider-failed observation;
- strict no-fallback parser errors are exercised after a public text delta;
- cleanup-primary tests use a non-fallback primary such as `ModelOutputLimitError` rather than expecting pre-text invalid payloads never to recover.

Do not delete shape coverage or weaken call-ID/arguments assertions.

- [ ] **Step 6: Run boundary RED, finish minimal code, and run GREEN**

Run RED before the remaining implementation adjustment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_chat_completions_streaming_client.py -k "invalid_sync or after_public_text or budget or callback or output_limit or base_exception"
```

Expected RED: any extra sync retry, fallback after text, missing discard, or budget overrun is exposed.

After the minimal correction, run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_chat_completions_streaming_client.py
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_chat_completions_client.py tests/test_chat_completions_streaming_client.py tests/test_streaming.py tests/test_model.py
```

Expected: exit 0; no skip/xfail added; standalone sync retry and structured streaming-unsupported fallback remain compatible.

**Acceptance:** strict malformed streams recover only before public text, exactly once, under one logical call and two provider attempts; every unsafe or ambiguous boundary still fails closed.

---

### Task 7: End-to-end offline scenarios and documentation contracts

**Files:**

- Modify: `tests/integration/test_chat_completions_agent.py`
- Modify: `tests/integration/test_adaptive_convergence.py`
- Modify: `tests/test_app.py`
- Modify: `tests/test_docs.py`
- Modify: `DESIGN.md`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `README.txt`
- Modify: `docs/USAGE.md`
- Modify: `docs/OPENAI_API.md`

**Interfaces:**

- Public docs name exactly seven modify tools and exactly three read-only tools.
- Docs describe eager local integrity as structural evidence, not tests/compilation.
- Docs describe invalid-stream sync recovery as one pre-text transport fallback, not parser relaxation.

- [ ] **Step 1: Write failing end-to-end tests**

Add four deterministic scenarios:

1. FakeModelClient creates `snake/`, then `snake/main.cpp`, receives one eager local-integrity pass for the batch, and returns final text.
2. Chat fake SDK receives non-empty selected-Skill instructions, yields an invalid no-text stream, then a valid sync answer; assert instructions survive and no Skill content enters repr/log events.
3. Chat fake SDK invalid stream falls back to a sync `write_file("AGENTS.md")`; the next Agent step reads it after eager integrity and finishes successfully.
4. `RunMode.READ_ONLY` with a stream handler receives invalid stream then sync text and ends `AgentStatus.ANSWERED`, with only the three read-only schemas.

Use injected fake SDK outcomes and `tmp_path`; unset credential variables with `monkeypatch.delenv(..., raising=False)`. No test may instantiate a real SDK transport.

- [ ] **Step 2: Run integration RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/integration/test_chat_completions_agent.py tests/integration/test_adaptive_convergence.py tests/test_app.py -k "directory_project or selected_skill or agents_file or read_only_stream_fallback"
```

Expected RED: missing directory tool, missing eager validation, or invalid stream prevents each scenario from reaching its required terminal state.

- [ ] **Step 3: Add documentation contract RED**

Import `CreateDirectoryTool` in `tests/test_docs.py`, insert it in the expected modify tool sequence, and add assertions that:

- `docs/USAGE.md` states one-level/non-recursive directory creation;
- local integrity runs after an eligible mutation batch but does not prove tests or compilation;
- `docs/OPENAI_API.md` states one invalid pre-text stream may use exactly one sync attempt and that post-text failures never fall back;
- `AGENTS.md` no longer says modify exposes exactly six tools.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_docs.py
```

Expected RED: existing docs list six modify tools and say ordinary invalid stream parsing never falls back.

- [ ] **Step 4: Update only factual docs and design baselines**

- Update `DESIGN.md` tool, verification, streaming, testing, decision, limitation, and deferred-scope sections to match the approved spec.
- Update `AGENTS.md` from six to seven modify tools and add the exact local-integrity and Chat fallback invariants.
- Update `TASKS.md` Task29 acceptance/test text only if implementation reveals wording inconsistency; keep status `进行中`.
- Update README files and both public docs without claiming C/C++ compilation, universal provider compatibility, recursive mkdir, or executable Skill support.
- Keep the repository URL sourced from existing docs/local Git; do not invent a remote.

- [ ] **Step 5: Run integration and docs GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/integration/test_chat_completions_agent.py tests/integration/test_adaptive_convergence.py tests/test_app.py tests/test_docs.py
```

Expected: exit 0; all four scenarios have deterministic offline evidence.

**Acceptance:** the reported user failures have direct offline regression tests and all public documentation accurately reflects implemented limits.

---

### Task 8: Fresh final verification and user-review stop

**Files:**

- Review every Task29 file and the pre-existing five GUI paths separately.
- Do not change Task29 from `进行中`.

**Interfaces:**

- Confirms all public signatures from the spec.
- Produces fresh command evidence only; produces no commit.

- [ ] **Step 1: Run exact Task29 suites**

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_path_safety.py tests/tools/test_write_tools.py tests/test_app.py tests/test_instructions.py tests/test_agent_loop.py tests/test_verification.py tests/test_chat_completions_client.py tests/test_chat_completions_streaming_client.py tests/test_streaming.py tests/integration/test_chat_completions_agent.py tests/integration/test_adaptive_convergence.py tests/test_docs.py
```

Expected: exit 0. Report real pass/fail/skip/warning counts.

- [ ] **Step 2: Run explicit Task1–Task28 component regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_messages.py tests/test_model.py tests/test_openai_client.py tests/test_openai_streaming_client.py tests/test_context.py tests/test_termination.py tests/test_command_safety.py tests/test_logging.py tests/test_report.py tests/test_session.py tests/test_session_store.py tests/test_session_controller.py tests/test_web.py tests/test_web_gui.py tests/integration
```

Expected: exit 0 with real counts recorded.

- [ ] **Step 3: Run full Python and GUI suites**

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
node --test tests/js/web_gui.test.mjs
```

Expected: both exit 0. The existing GUI modifications are tested but remain outside Task29's diff ownership.

- [ ] **Step 4: Run Windows safety and process specializations**

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_path_safety.py tests/tools/test_shell_tool.py tests/test_command_safety.py -k "junction or reparse or symlink or timeout or process_tree or cleanup"
```

Expected: exit 0; reparse/junction and process-tree tests execute rather than being permanently skipped.

- [ ] **Step 5: Audit signatures, registrations, budgets, and SDK isolation**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import inspect; from coding_agent.safety import PathGuard; from coding_agent.tools.filesystem import CreateDirectoryTool; from coding_agent.chat_completions_client import ChatCompletionsModelClient; print(inspect.signature(PathGuard.new_directory)); print(CreateDirectoryTool.name); print(inspect.signature(ChatCompletionsModelClient.stream_with_budget))"
rg -n "CreateDirectoryTool|create_directory" src/coding_agent tests DESIGN.md AGENTS.md README.md README.txt docs/USAGE.md
rg -n "from openai|import openai" src/coding_agent
rg -n "begin_provider_attempt|finish_provider_attempt|public_text_delta|stream=True|max_attempts" src/coding_agent/chat_completions_client.py tests/test_chat_completions_streaming_client.py
```

Expected: signatures match the spec; `create_directory` is absent from read-only registration; SDK imports remain confined to provider adapters; each real stream/sync request has a budget acquisition path.

- [ ] **Step 6: Audit dependencies, prohibited scope, credentials, and unfinished markers**

Run:

```powershell
git diff -- pyproject.toml
rg -n "LangChain|LlamaIndex|Agents SDK|Claude Agent SDK|AutoGen|CrewAI" src tests pyproject.toml
rg -n "sk-[A-Za-z0-9_-]{16,}|Authorization:[ ]*Bearer|OPENAI_API_KEY[ ]*=" . --glob "!.git/**" --glob "!.venv/**" --glob "!*.jsonl"
rg -n "TO[D]O|TB[D]|FIXME|NotImplementedError|pytest\.skip|pytest\.mark\.skip|pytest\.mark\.xfail" src tests DESIGN.md AGENTS.md README.md README.txt docs
rg -n "delete_file|move_file|rename_file|parents=True|exist_ok=True|subprocess.*shell=True" src/coding_agent
```

Expected: dependency diff empty; no Agent framework; no real credential; no new unfinished marker/test suppression; no directory recursion, deletion/move, or shell expansion introduced. Review known fake-key/documentation matches without printing sensitive values.

- [ ] **Step 7: Check whitespace, status, and diff ownership**

Run:

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff -- src/coding_agent/safety.py src/coding_agent/tools/filesystem.py src/coding_agent/app.py src/coding_agent/instructions.py src/coding_agent/agent.py src/coding_agent/verification.py src/coding_agent/chat_completions_client.py tests/test_path_safety.py tests/tools/test_write_tools.py tests/test_app.py tests/test_instructions.py tests/test_agent_loop.py tests/test_verification.py tests/test_chat_completions_streaming_client.py tests/integration/test_chat_completions_agent.py tests/integration/test_adaptive_convergence.py tests/test_docs.py TASKS.md DESIGN.md AGENTS.md README.md README.txt docs/USAGE.md docs/OPENAI_API.md docs/superpowers/specs/2026-08-31-directory-mutation-and-chat-stream-fallback-design.md docs/superpowers/plans/Task29.md
```

Expected: whitespace clean; Task29 diff is limited to the locked map; the five unrelated GUI paths remain byte-for-byte outside Task29 review.

- [ ] **Step 8: Verify the acceptance matrix**

| Requirement | Fresh evidence |
|---|---|
| Safe one-level directory creation | `test_path_safety.py`, `test_write_tools.py` |
| No recursive parents/overwrite/reparse escape | negative path and Windows tests |
| Directory mutation ledger and validation freshness | Agent/verification tests |
| One safety count per rejection-only response | Agent batch tests |
| Three independent rejected responses still stop | termination regression |
| Deterministic parent correction | exact ToolResult assertion |
| Eager local integrity once per mutation batch | Agent event/counter tests |
| Eager evidence does not auto-success | RUNNING then final-text state test |
| Forced/stale real verification not downgraded | Agent/VerificationGate negative tests |
| Invalid pre-text stream uses exactly one sync request | fake SDK call list and budget observer |
| Invalid post-text stream never falls back | discard/call-count test |
| Sync fallback cannot exceed provider budget | boundary tests |
| Skill, AGENTS, directory project, read-only scenarios | four offline integrations |
| Existing Responses and Chat behavior preserved | provider component regressions |
| No network/key/dependency/framework | fake SDK and audit commands |
| Docs match exact tool and fallback behavior | `tests/test_docs.py` |

- [ ] **Step 9: Stop for user review**

Keep Task29 `进行中`. Do not stage or commit. Report every RED/GREEN command and result, final Python/Node counts, warnings/skips, Windows special-test evidence, changed files, unrelated pre-existing GUI paths, `git status`, `git diff --stat`, deviations, and unresolved items. Wait for explicit user authorization before any commit or Task30 work.

---

## Plan Self-Review Record

- Every approved spec requirement maps to a Task and final matrix row.
- Public names are consistent: `PathGuard.new_directory`, `CreateDirectoryTool`, `create_directory`, `_settle_safety_rejection_batch`, and `_run_eager_local_integrity`.
- Safety threshold remains 3 responses; sibling tool count cannot cause an off-by-one termination.
- Eager integrity verifies the final mutation index once per response and never bypasses forced or stale real verification.
- Invalid-stream fallback stays Chat-only, pre-public-text, one sync attempt, one logical call, and budget accounted.
- Responses, message types, streaming Protocols, Session/Web/GUI schemas, dependencies, and unrelated dirty GUI files remain outside the implementation scope.
- The plan contains no unresolved implementation placeholder or ambiguous branch/worktree/commit instruction.

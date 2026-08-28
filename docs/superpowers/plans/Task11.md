# Task 11 Post-mutation Verification Gate Implementation Plan

> **Execution workflow:** Implement this plan in order with `executing-plans`, `test-driven-development`, `systematic-debugging` for reproducible unexpected failures, and `verification-before-completion` before reporting results. Execute inline in the current `main` workspace. Do not create a branch, worktree, subagent, commit, or remote operation.

**Goal:** Connect a model `COMPLETION_CANDIDATE`, Task 8-authorized verification commands, the mutation ledger, and a final `SUCCESS` state. A model statement is never success evidence. User-supplied verification is mandatory when present; otherwise a fresh, credible model-selected `purpose="verification"` command may provide evidence.

**Architecture:** `verification.py` owns evidence parsing, credibility classification, freshness, deterministic decisions, and structured feedback. `tools/shell.py` exposes one executor that accepts an existing `AuthorizedCommand`; both `RunCommandTool` and forced verification use that executor, so subprocess, cwd, environment, timeout, output bounds, and Windows process-tree cleanup remain single-sourced. `AgentRunner` remains the only owner of top-level state transitions and budget checks.

**Approved basis:** `DESIGN.md` sections 1, 4–6, 10–17; `TASKS.md` Task 11; `AGENTS.md`; Task 8 `AuthorizedCommand` and command execution contracts; Task 10 context, continuation, accounting, and termination contracts.

## Baseline confirmed during planning

- Repository: `D:\code\coding_agent`; branch: `main`.
- HEAD: `8a84023415e04671fcea16d716257a7e49a686b7` (`完成上下文管理相关机制`).
- Worktree and `git diff --check`: clean.
- Fresh full suite: `566 passed, 0 failed, 0 skipped, 1 warning` in 15.54 seconds.
- The warning is the existing inability to create `D:\code\coding_agent\.pytest_cache`; it is not a test failure.
- `TASKS.md` still records Task 10 as `进行中` and Task 11 as `未开始`. Execution Task 0 corrects only those two status values after reconfirming the baseline.

## Resolved design choice: retain the approved hybrid scheme

1. If `RunConfig.verify_command` is not `None`, every completion candidate executes that exact `AuthorizedCommand`. No model-selected result can replace it.
2. If `RunConfig.verify_command` is `None`, the gate accepts only the latest credible `run_command` result whose original call used `purpose="verification"` and whose evidence matches the current mutation index.
3. A credible command is one of the Task 8-authorized test/check forms: pytest, unittest, Ruff `check`, mypy, or a workspace Python script. Git inspection commands never count as verification evidence.
4. A safe but non-credible model command may execute as an inspection action, but the gate does not accept it as proof. A non-credible user `--verify` is rejected during configuration before Agent/model startup.

## Alternatives considered

### A. Send the raw `--verify` text through `RunCommandTool`

Rejected. It would reparse/re-authorize a capability that Task 8 already authorized and would change its source from `USER_VERIFY` to `MODEL`.

### B. Add a second verification-only subprocess implementation

Rejected. Timeout, environment, output truncation, and process-tree behavior could drift from Task 8.

### C. Extract a shared authorized-command executor and inject it into the gate

Selected. The executor consumes `AuthorizedCommand.argv` directly. It never calls `CommandLineToArgvW`, `CommandPolicy.authorize`, a shell, PowerShell, or `cmd /c`.

For feedback, adding a fourth Task 2 message kind would require Task 9 mapping changes, while a synthetic function-call pair would invent an unregistered provider tool. The selected representation is a tagged, compact JSON `AssistantMessage` with no tool calls. It is a complete local turn, cannot orphan a `ToolResult`, and requires no SDK-facing type change.

---

## Locked file map

### Create

- `src/coding_agent/verification.py`
- `tests/test_verification.py`

### Modify

- `src/coding_agent/tools/shell.py` — extract the existing execution body into `AuthorizedCommandExecutor`; preserve `RunCommandTool` schema and behavior.
- `src/coding_agent/config.py` — reject a safe but non-credible user verification command before returning `RunConfig`; keep its public signature and field types unchanged.
- `src/coding_agent/state.py` — extend verification states/evidence fields and add `AgentStatus.SUCCESS`.
- `src/coding_agent/agent.py` — optional gate injection, evidence observation, candidate evaluation, budget checks, feedback, and success transition.
- `src/coding_agent/context.py` — populate the existing six-field `verification_state` object from local evidence without retaining command output.
- `tests/tools/test_shell_tool.py` — prove executor extraction preserves Task 7/8 behavior and executes the exact authorized argv.
- `tests/test_cli.py` — startup rejection for non-credible `--verify`, plus unchanged redaction and safe-command tests.
- `tests/test_agent_loop.py` — gate integration, budgets, continuation, retries after failure, interruption, and exact call counts.
- `tests/test_context.py` — verification invariant retention and output omission.
- `TASKS.md` — during execution Task 0 only: Task 10 `进行中` to `已完成`, Task 11 `未开始` to `进行中`; Task 11 remains `进行中` at the review stop.

### Read and keep unchanged

- `src/coding_agent/messages.py`
- `src/coding_agent/model.py`
- `src/coding_agent/openai_client.py`
- `src/coding_agent/safety.py`
- `src/coding_agent/termination.py`
- `src/coding_agent/tools/base.py`
- `src/coding_agent/tools/registry.py`
- `src/coding_agent/tools/filesystem.py`
- `src/coding_agent/cli.py`
- `pyproject.toml`
- all tests not explicitly listed under Modify

No Task 2 message, Task 9 provider-neutral API, Task 8 authorization rule, or Task 10 termination signature changes.

---

## Locked public interfaces

### Shared Task 8 command execution (`tools/shell.py`)

```python
class AuthorizedCommandExecutor:
    def __init__(
        self,
        *,
        process_factory: ProcessFactory | None = None,
        tree_terminator: TreeTerminator | None = None,
    ) -> None: ...

    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
    ) -> ToolExecution: ...
```

`RunCommandTool.__init__` gains only:

```python
authorized_executor: AuthorizedCommandExecutor | None = None
```

The existing `process_factory`, `tree_terminator`, and `policy_factory` seams remain accepted. Supplying both `authorized_executor` and either low-level process seam raises `TypeError` so there is one execution owner.

`RunCommandTool.execute()` continues to validate model arguments, authorize through `CommandPolicy(..., source=MODEL)`, then calls `AuthorizedCommandExecutor.execute(authorized, context)`. The executor validates object types and canonicalizes `context.workspace` through the existing `PathGuard`; it never parses or authorizes command text. `AuthorizedCommand` is Task 8's capability value and intentionally carries no second workspace field, so the production assembly must pass the `RunConfig.verify_command` together with that same `RunConfig.workspace`.

### Evidence and decisions (`verification.py`)

```python
@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: VerificationStatus
    validation_index: int
    command: str = field(repr=False)
    source: CommandSource
    exit_code: int | None
    stdout: str = field(repr=False)
    stderr: str = field(repr=False)
    timed_out: bool
    truncated: bool
    duration_ms: int
    error: str | None

    def to_dict(self) -> JSONObject: ...


class VerificationOutcome(StrEnum):
    SUCCESS = "success"
    CONTINUE = "continue"


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    outcome: VerificationOutcome
    result: VerificationResult | None
    feedback: AssistantMessage | None
    command_executed: bool


class VerificationError(RuntimeError):
    """The local verification evidence violates an internal invariant."""


class VerificationExecutor(Protocol):
    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
    ) -> ToolExecution: ...


def is_credible_verification_command(command: AuthorizedCommand) -> bool: ...


class VerificationGate:
    def __init__(
        self,
        *,
        required_command: AuthorizedCommand | None,
        execution_context: ExecutionContext,
        executor: VerificationExecutor | None = None,
    ) -> None: ...

    @property
    def requires_execution(self) -> bool: ...

    def observe_tool_result(
        self,
        state: AgentState,
        call: ToolCall,
        result: ToolResult,
    ) -> bool: ...

    def evaluate(self, state: AgentState) -> VerificationDecision: ...
```

`executor=None` creates `AuthorizedCommandExecutor`. `observe_tool_result` returns `True` only when it recorded a credible model verification execution; it never executes a command.

### State additions (`state.py`)

`VerificationStatus` moves from its two-value Task 6 form to exactly:

```python
class VerificationStatus(StrEnum):
    NOT_RUN = "not_run"
    STALE = "stale"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ERROR = "error"
```

It remains imported from `coding_agent.state`; `verification.py` imports and re-exports the same class rather than defining a duplicate.

`AgentStatus` adds exactly:

```python
SUCCESS = "success"
```

`AgentState` adds:

```python
verification_attempt_count: int = 0
last_verification: VerificationResult | None = field(default=None, repr=False)

@property
def validation_index(self) -> int | None: ...
```

`state.py` uses a `TYPE_CHECKING` import for `VerificationResult`; no runtime import cycle is introduced. `validation_index` returns `None` without evidence and otherwise returns `last_verification.validation_index`.

`AgentRunner.__init__` gains one additive keyword:

```python
verification_gate: VerificationGate | None = None
```

`None` preserves Task 10's staging behavior: text returns `COMPLETION_CANDIDATE`, never `SUCCESS`. Every production assembly that wants Task 11 success must inject a gate; CLI assembly remains deferred and is not implemented here.

---

## Locked `VerificationResult` invariants

- `validation_index` is a non-negative integer and records `state.mutation_index` at the start of that actual verification attempt.
- `command` is the normalized command rendered from the authorized/executed argv with `subprocess.list2cmdline`; raw model text is not stored as executed evidence.
- `source` is exactly `USER_VERIFY` or `MODEL`.
- `duration_ms` is a non-negative integer; `timed_out` and `truncated` are real booleans.
- `PASSED`: `exit_code == 0`, `timed_out is False`, `error is None`.
- `FAILED`: `exit_code` is a nonzero integer, `timed_out is False`, `error is None`.
- `TIMED_OUT`: `exit_code is None`, `timed_out is True`; a stable cleanup error may be present.
- `ERROR`: `exit_code is None`, `timed_out is False`, `error` is one of `verification_command_start_failed` or `verification_internal_error`.
- `NOT_RUN`, `STALE`, and `RUNNING` are state statuses and are invalid as terminal `VerificationResult.status` values.
- `repr(VerificationResult)` omits command, stdout, and stderr. `to_dict()` is deterministic, JSON-compatible, and includes explicit null values.
- A provider/executor exception body, environment mapping, API key, Authorization header, or continuation item is never copied into `error`.

## Locked shell-result decoding

The gate accepts only the existing exact Task 8 shell output object:

```json
{
  "argv": ["..."],
  "cleanup_error": null,
  "purpose": "verification",
  "stderr": "...",
  "stdout": "..."
}
```

The matching `ToolResultMetadata` supplies `exit_code`, `timed_out`, `truncated`, and `duration_ms`. Missing/extra keys, wrong types, purpose mismatch, empty argv, contradictory timeout/exit code, or non-finite/negative metadata raises `VerificationError`. This is an internal invariant failure, not a retryable test failure.

## Credibility rules

Credibility never authorizes execution. It runs only on an `AuthorizedCommand` or already-executed canonical argv.

- Accepted: current Python `-m pytest`; trusted pytest launcher; current Python `-m unittest`; trusted Ruff launcher with `check`; trusted mypy launcher; current Python plus an authorized workspace `.py` script.
- Rejected as evidence: all Git commands, help/version-only invocations, and any argv shape outside the accepted forms.
- The required user command must have `purpose="verification"`, `source=USER_VERIFY`, and be credible. `load_run_config` rejects a non-credible command with the stable redacted message `--verify rejected (verification_not_credible): command is not a credible verification command`.
- A model result must originate from a paired `run_command` call whose arguments contain exactly `command` and `purpose`, with `purpose="verification"`; the shell output must say `purpose="verification"` and pass credibility classification.
- `purpose="inspect"` or `purpose="test"` never becomes final evidence even if the command exits 0.

## State machine and freshness

| Current condition | Trigger | Verification action | Next Agent state |
| --- | --- | --- | --- |
| `RUNNING` | tool/model work | no gate evaluation | `RUNNING` |
| `RUNNING` | credible model verification result | record evidence at current mutation index | `RUNNING` |
| `COMPLETION_CANDIDATE`, required command present | time/tool budget admits operation | execute exact stored command once | `SUCCESS` on fresh pass; otherwise feedback then `RUNNING` |
| `COMPLETION_CANDIDATE`, no required command | fresh passed model evidence exists | execute nothing | `SUCCESS` |
| `COMPLETION_CANDIDATE`, no required command | evidence missing, stale, failed, timed out, or errored | execute nothing; add structured feedback | `RUNNING` |
| candidate before required execution | time/tool budget rejects operation | execute nothing | `FAILED` with the Task 10 reason |
| any gate path | invalid local evidence/invariant | execute nothing further | `FAILED/internal_invariant` |
| gate execution | `KeyboardInterrupt` | outer Agent handler converts it | `INTERRUPTED/user_interrupted` |
| gate execution | `SystemExit` | not caught | no fabricated Agent state |

Success requires all of:

```text
candidate entered the gate
AND result.status == PASSED
AND result.exit_code == 0
AND result.timed_out == false
AND result.validation_index == state.mutation_index
AND (required command absent OR result.source == USER_VERIFY
     and result.command == required_command.normalized_command)
```

The gate rechecks the index immediately before returning `SUCCESS`. `termination_reason` and `failure_reason` remain `None` on success.

Freshness rules:

- Every successful mutating tool call continues to increment `mutation_index` exactly once and sets `verification_status=STALE`; `last_verification` remains for audit but cannot qualify.
- Every actual verification execution, including nonzero, timeout, or startup error, increments `verification_attempt_count` once and records the current mutation index.
- A safety/config rejection does not execute and does not increment the attempt count.
- Mutation index zero is valid. An inspection-only task may succeed after a credible passing verification at index zero.
- Required user verification runs for every completion candidate; a previous pass is not reused.
- Without required verification, a fresh passed model result may be reused across later completion candidates while no mutation occurs.
- Repeated failed candidates do not reset model/provider/tool/time counters. Existing logical-call and runtime limits guarantee termination; no independent verification hard limit or new termination reason is added.

## Feedback format

Failed/missing/stale decisions append one `AssistantMessage` with no tool calls:

```text
coding-agent verification feedback
{"command":...,"error":...,"exit_code":...,"mutation_index":...,"source":...,"status":...,"stderr":...,"stdout":...,"timed_out":...,"truncated":...,"validation_index":...}
```

Keys are sorted and compact; null is explicit. The command is normalized executed evidence, not model prose. Missing evidence uses null command/source/index/output. Because the message is an assistant turn rather than a `ToolResult`, it cannot create an unmatched `call_id`. The prior provider continuation remains attached to its original assistant response and is passed through unchanged; the feedback itself contains no continuation payload.

After feedback, `completion_text` is cleared and Agent status returns to `RUNNING`. The next loop performs the normal Task 10 precheck and context preparation.

## Budget and priority rules

- Required verification is one local command operation and consumes one `tool_call_count` slot after an admitted attempt, including nonzero, timeout, or startup error.
- Model-selected verification already consumed one tool slot in `ToolRegistry`; observing/evaluating its evidence does not consume another.
- `verification_attempt_count` is audit state, not a separate hard budget.
- Before required verification, `AgentRunner` calls the existing `TerminationPolicy.check(..., next_operation=NextOperation.TOOL)`. This checks internal state, safety rejection threshold, total time, tool limit, and existing error/repetition limits in Task 10 priority.
- Logical/provider limits are not checked before required verification because it is not a model request. Therefore the last permitted model call may produce a candidate and still run verification when time/tool budgets allow.
- If required verification fails and the next model call is unavailable, the next loop terminates with the existing Task 10 priority: safety rejection, time, logical limit, provider limit, then error/repetition limits.
- If an admitted verification returns exit 0 after the clock reaches the runtime boundary, fresh `PASSED` wins. This follows Task 10's rule that limits prevent the first operation that was not admitted; they do not retroactively reject an admitted completed operation.
- A required verification blocked before start by time/tool budget never calls the executor and never increments either count.

---

## Task 0: Reconfirm and activate the Task 11 baseline

**Files:** Read all baseline files. Modify only the two Task status values after every check passes.

1. Re-read `AGENTS.md`, `DESIGN.md`, `TASKS.md`, Task 8 and Task 10 plans, and all files in the locked read/modify maps.
2. Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git log -5 --oneline
git status --short --untracked-files=all
git diff --check
.\.venv\Scripts\python.exe -m pytest -q
```

3. Expected: D: repository, `main`, Task 10 commit at HEAD, clean status except approved `Task11.md` if untracked, whitespace exit 0, and full suite exit 0 with actual totals reported.
4. Change only Task 10 to `已完成` and Task 11 to `进行中`. Assert exactly Task 11 is `进行中`.

**Acceptance:** no unapproved diff, baseline is green, and status changes are limited to Task 10/11.

---

## Task 1: Extract the single authorized-command executor

**Files:** `src/coding_agent/tools/shell.py`, `tests/tools/test_shell_tool.py`.

### RED

Add tests with a fake `ProcessFactory` and an already constructed `AuthorizedCommand`:

```python
def test_authorized_executor_runs_exact_capability_without_policy(tmp_path: Path) -> None:
    authorized = AuthorizedCommand(
        argv=(sys.executable, str((tmp_path / "check.py").resolve())),
        normalized_command="hidden from parser",
        purpose="verification",
        source=CommandSource.USER_VERIFY,
    )
    observed: dict[str, object] = {}
    executor = AuthorizedCommandExecutor(
        process_factory=recording_process_factory(observed, exit_code=0),
    )

    result = executor.execute(authorized, ExecutionContext(tmp_path))

    assert observed["argv"] is authorized.argv
    assert observed["shell"] is False
    assert observed["cwd"] == tmp_path.resolve()
    assert result.metadata.exit_code == 0
```

Also test wrong command type, workspace mismatch, unchanged child environment, exact 64 KiB semantics, timeout/tree cleanup, and `RunCommandTool` delegating one time to an injected executor after `CommandPolicy` authorization.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py -k "authorized_executor or delegates_to_authorized_executor" -q
```

Expected RED: import/attribute failure because `AuthorizedCommandExecutor` and the injection seam do not exist. A fixture or syntax failure stops the task.

### GREEN

Move the existing post-authorization execution body byte-for-byte in behavior into `AuthorizedCommandExecutor.execute`. Keep `_child_environment`, `_BoundedBytes`, readers, decoder, `_terminate_process_tree`, and `_json_output` single-sourced. Delegate from `RunCommandTool`.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py -k "authorized_executor or delegates_to_authorized_executor" -q
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py tests\test_command_safety.py tests\test_cli.py -q
```

Expected: both exit 0 with real counts; all existing Windows process-tree tests still run, with no new skip.

**Acceptance:** both command paths use one execution implementation; required verification can consume a capability without text parsing or policy rerun.

---

## Task 2: Define evidence, credibility, startup rejection, and freshness primitives

**Files:** `src/coding_agent/verification.py`, `src/coding_agent/state.py`, `src/coding_agent/config.py`, `tests/test_verification.py`, `tests/test_cli.py`.

### RED 2A — types and invariants

Create `tests/test_verification.py` with parameterized tests for every `VerificationResult` status/invariant, explicit-null serialization, repr redaction, exact enum values, and `AgentState.validation_index`.

```python
def test_passed_result_is_json_stable_and_repr_hides_evidence() -> None:
    result = VerificationResult(
        status=VerificationStatus.PASSED,
        validation_index=2,
        command="python -m pytest -q",
        source=CommandSource.USER_VERIFY,
        exit_code=0,
        stdout="2 passed",
        stderr="",
        timed_out=False,
        truncated=False,
        duration_ms=12,
        error=None,
    )
    assert result.to_dict() == {
        "status": "passed", "validation_index": 2,
        "command": "python -m pytest -q", "source": "user_verify",
        "exit_code": 0, "stdout": "2 passed", "stderr": "",
        "timed_out": False, "truncated": False,
        "duration_ms": 12, "error": None,
    }
    assert "python -m pytest" not in repr(result)
    assert "2 passed" not in repr(result)
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_verification.py -k "result or status or validation_index" -q
```

Expected RED: `coding_agent.verification` and the expanded state fields do not exist.

Implement only the enums, immutable result validation/serialization, state fields/property, and mutation invalidation compatibility. Run the same nodes for GREEN, then:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py tests\tools\test_write_tools.py -q
```

### RED 2B — credibility and startup boundary

Add a table covering canonical pytest/unittest/Ruff/mypy/workspace-script argv and rejecting Git status/diff, help/version-only, wrong purpose/source, and malformed capabilities. Add:

```python
def test_config_rejects_noncredible_user_verify_without_echoing_it(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as caught:
        load_run_config(
            task="inspect", workspace=tmp_path, model="gpt-test",
            verify_command="git status --short",
            environ={"OPENAI_API_KEY": "secret-sentinel"},
        )
    assert str(caught.value) == (
        "--verify rejected (verification_not_credible): "
        "command is not a credible verification command"
    )
    assert "git status" not in str(caught.value)
    assert "secret-sentinel" not in str(caught.value)
```

Run the exact new nodes. Expected RED: the current config accepts safe Git inspection as `--verify`.

Implement the pure credibility classifier and one config check after Task 8 authorization. Run GREEN and all CLI/command safety tests.

**Acceptance:** no unsafe or inspection-only command can become required evidence, configuration still returns `AuthorizedCommand | None`, and no command/key appears in repr or errors.

---

## Task 3: Implement the gate in isolation

**Files:** `src/coding_agent/verification.py`, `tests/test_verification.py`.

Use a `FakeVerificationExecutor` that records exact object identity and returns queued `ToolExecution` values or exceptions. No subprocess, network, environment key, or real clock is used.

### RED 3A — required-command outcomes

Tests:

- exact required object executes once;
- exit 0 returns `SUCCESS` and fresh `PASSED`;
- nonzero returns `CONTINUE` and tagged JSON feedback;
- timeout records `TIMED_OUT`, exit null, stdout/stderr, truncation, cleanup error;
- `CommandStartError` becomes stable `ERROR` without exception text;
- unexpected ordinary `Exception` becomes `verification_internal_error` without its body;
- `KeyboardInterrupt` and `SystemExit` propagate;
- output schema corruption raises `VerificationError`;
- attempt count increments once for each admitted executor call.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_verification.py -k "required or timeout or start_error or interrupt or corrupt" -q
```

Expected RED: `VerificationGate` behavior is absent.

Implement the minimum decoder, result recorder, feedback renderer, and required-command evaluation. Run the same selection for GREEN.

### RED 3B — model evidence and freshness

Construct paired `ToolCall`/`ToolResult` values with the exact Task 8 shell JSON. Tests cover:

- model pytest pass records at current mutation index;
- ordered stdout/stderr and metadata mapping;
- nonzero and timeout records;
- `inspect`/`test` purpose ignored;
- Git/pseudo verification ignored;
- rejected or errored tool result is not fabricated as execution evidence;
- missing evidence yields `CONTINUE` feedback;
- a fresh model pass yields `SUCCESS` without executor call;
- a new mutation sets `STALE`, preserves audit result, and blocks reuse;
- a pass at mutation index zero succeeds;
- an unchanged fresh model pass is reusable;
- required command always runs and cannot be replaced by model evidence.

Run the explicit new nodes. Expected RED: observation/freshness behavior is absent. Implement and rerun for GREEN.

Run regression:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_verification.py tests\test_messages.py tests\tools\test_shell_tool.py tests\test_command_safety.py -q
```

**Acceptance:** the gate has one success predicate, stale evidence never qualifies, no fake tool pairing is added, and all decisions are deterministic/offline.

---

## Task 4: Preserve verification facts through context compression

**Files:** `src/coding_agent/context.py`, `tests/test_context.py`.

### RED

Add tests that set a real `VerificationResult` on a compressible state and assert the existing object becomes exactly:

```python
assert parsed["verification_state"] == {
    "status": "passed",
    "mutation_index": 3,
    "validation_index": 3,
    "command": "python -m pytest -q",
    "source": "user_verify",
    "exit_code": 0,
}
```

Also assert stdout, stderr, error bodies, continuation sentinels, and encrypted-looking payloads are absent from the summary JSON and repr. Add stale-state and no-evidence cases; the no-evidence case must retain Task 10's exact null object.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_context.py -k "verification" -q
```

Expected RED: Task 10 always writes null evidence fields.

### GREEN

Change only `_merge_local_invariants` to project local state into the existing six keys. Do not change the nine-field summary schema, thresholds, fallback logic, or continuation lifecycle.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_context.py -k "verification" -q
.\.venv\Scripts\python.exe -m pytest tests\test_context.py tests\test_model.py tests\test_openai_client.py -q
```

**Acceptance:** compression retains freshness facts, excludes full outputs and continuation, and Task 9 replay behavior is unchanged.

---

## Task 5: Integrate the gate with AgentRunner and Task 10 budgets

**Files:** `src/coding_agent/agent.py`, `tests/test_agent_loop.py`.

Extend the existing `_runner` test helper with `verification_gate: VerificationGate | None = None`. Keep all pre-Task11 tests unchanged; the default remains `None`.

### RED 5A — trigger, success, failure feedback, and repair

Add tests proving:

1. Tool-call and ordinary running phases never call the required executor.
2. A text-only candidate calls it once and exit 0 sets `AgentStatus.SUCCESS`.
3. Nonzero result appends one tagged assistant feedback turn, clears candidate text, and makes the next model request.
4. Scripted flow `candidate -> fail -> replace_text mutation -> candidate -> pass` executes required verification twice, reaches mutation index one, and succeeds only with validation index one.
5. A previous user/model pass becomes stale after mutation.
6. Without required command, model pytest evidence followed by a candidate succeeds without a second command execution.
7. Model prose alone with no evidence returns feedback and continues; it never succeeds.

Run named nodes. Expected RED: AgentRunner returns at the first candidate and has no `SUCCESS` transition.

Implement the optional gate integration, observation after real Registry results, and candidate decision handling. Preserve provider continuation while appending feedback.

Run GREEN, then all existing Agent tests.

### RED 5B — exact budgets and boundary priority

Use injected `TerminationLimits`, `FakeClock`, FakeModelClient, and FakeVerificationExecutor. Assert exact counts for:

- required verification increments `tool_call_count` once;
- model-selected verification is counted once by Registry and not again by the gate;
- tool budget at the limit blocks required executor before its first call;
- time at the exact limit blocks required executor;
- the last permitted logical/provider call can produce a candidate and run verification;
- a failed verification followed by exhausted logical budget stops before another model request;
- a passing admitted verification wins even when the next fake clock value reaches the runtime boundary;
- repeated fixed failures retain all counters and terminate through the existing model/time/tool budget, with exact executor/model call lists;
- no blocked operation increments `verification_attempt_count` or `tool_call_count`.

Expected RED: no verification budget integration. Implement only precheck placement and counter synchronization; do not modify `TerminationPolicy`.

### RED 5C — errors, interruption, history, and continuation

Tests prove:

- invalid gate evidence terminates `INTERNAL_INVARIANT`;
- `KeyboardInterrupt` during verification raises `AgentInterrupted` carrying interrupted state;
- `SystemExit(130)` is not caught;
- failed feedback plus prior tool calls still constructs a valid `ModelRequest` with no orphan result;
- Task 9 continuation remains attached to the original completion response across feedback;
- later context compression clears continuation using Task 10 behavior;
- output contains no real environment key because the shared executor removes `OPENAI_API_KEY`;
- a fake exception containing `Authorization: Bearer secret-sentinel` is reduced to the stable error code and never appears in state repr or feedback.

Run named nodes for RED, implement the minimum exception/invariant paths, then GREEN.

Run regression:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_context.py tests\test_termination.py tests\test_model.py tests\test_openai_client.py -q
```

**Acceptance:** only candidates enter the gate, no operation starts beyond budget, failure repairs remain bounded, message pairing and continuation remain legal, and `SUCCESS` has fresh proof.

---

## Task 6: Final offline verification and review stop

No production behavior is added in this task.

### Focused suites

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_verification.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_context.py tests\test_termination.py -q
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py tests\test_command_safety.py tests\test_cli.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_model.py tests\test_openai_client.py -q
```

Report each exit code and real passed/failed/skipped/warning totals.

### Complete Task 1–10 regression

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit 0; report fresh totals rather than the planning estimate.

### Signature and ownership audit

Run Python `inspect.signature` assertions for `AuthorizedCommandExecutor.execute`, `VerificationGate.__init__`, `observe_tool_result`, `evaluate`, and additive `AgentRunner.__init__`. Assert `ModelClient.complete`, `OpenAIResponsesClient.complete`, `CommandPolicy.authorize`, and all Task 2 message signatures are unchanged.

Search and fail if:

- `shell=True`, `cmd /c`, PowerShell execution, or another process factory appears;
- verification reparses `normalized_command` or calls `CommandPolicy.authorize` during gate execution;
- `SUCCESS` is assigned outside `AgentRunner`;
- a success path omits the fresh index equality check;
- OpenAI SDK imports appear outside `openai_client.py`;
- continuation fields are serialized by verification/context code;
- a new dependency, Agent framework, network call, logging/report implementation, CLI Agent wiring, or Task 13 demo is introduced;
- a test suppression marker or unfinished implementation marker is added.

### Credential and evidence audit

Use repository scans for real-key patterns, bearer headers, environment dumps, and continuation payload access. Inspect tests to prove only sentinel credentials are used and no real API/environment credential is read. Verify `VerificationResult.__repr__`, `RunConfig.__repr__`, error feedback, and summary omit sensitive bodies.

### Diff and scope audit

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff -- src\coding_agent\verification.py src\coding_agent\tools\shell.py src\coding_agent\config.py src\coding_agent\state.py src\coding_agent\agent.py src\coding_agent\context.py tests\test_verification.py tests\tools\test_shell_tool.py tests\test_cli.py tests\test_agent_loop.py tests\test_context.py TASKS.md
```

Review every changed line. Task 11 remains `进行中`; do not stage, commit, push, start Task 12, or run branch-finishing workflows.

---

## Final acceptance matrix

| Requirement | Evidence |
| --- | --- |
| Candidate triggers user verification once | required-command Agent test |
| Ordinary/tool phases do not trigger gate | trigger-boundary Agent test |
| Exact `AuthorizedCommand` consumed | executor identity and no-parser test |
| Mixed no-command behavior | model-evidence and missing-evidence tests |
| Exit 0 reaches final success | required pass integration |
| Nonzero never succeeds and feeds back | failure-feedback integration |
| Failure can be repaired and reverified | fail/mutate/pass scripted flow |
| Mutation invalidates old pass | stale-index tests |
| Validation index must equal mutation index | off-by-one matrix |
| No-change task may pass at index zero | zero-index test |
| Required command reruns each candidate | repeated-candidate test |
| Model fresh evidence is reusable | no-required-command reuse test |
| Timeout and process-tree behavior | gate timeout plus Task 7/8 regression |
| Startup error classification | stable `ERROR` test |
| Safety/config rejection starts no process | CLI and Task 8 policy tests |
| stdout/stderr separated and bounded | shared executor and result mapping tests |
| Credentials are not inherited or leaked | environment and stable-error tests |
| Feedback preserves valid history | `ModelRequest` reconstruction test |
| Summary retains facts, not full output | context verification-state test |
| Model/provider/tool/time budgets remain | boundary matrix with exact counts |
| No over-budget model/tool/verification | blocked-executor/request assertions |
| Last allowed model call may verify | final-model-call test |
| Admitted pass versus time boundary | success-priority fake-clock test |
| Repeated failures remain bounded | repeated-failure budget test |
| `KeyboardInterrupt`/`SystemExit` semantics | interruption tests |
| Task 8 safety remains green | command, CLI, shell suites |
| Task 9 continuation remains green | OpenAI and continuation suites |
| Task 10 context/termination remains green | context, termination, Agent suites |
| Full Task 1–10 regression | complete pytest command |
| No Task 12/13 scope | import/file/diff audit |

## Plan self-check

- Every Task 11 acceptance criterion maps to a named test or explicit audit.
- Public names, constructor arguments, status values, result fields, and feedback keys are defined once and used consistently.
- Success is impossible without a fresh `PASSED` result.
- Required verification cannot be replaced by model evidence.
- Model-selected evidence cannot bypass Task 8 execution or credibility checks.
- Mutation/validation equality has explicit zero, stale, and off-by-one tests.
- The shared executor prevents a second subprocess/safety implementation.
- Tool and time checks occur before the first disallowed required verification.
- Feedback is a complete assistant turn and cannot orphan a tool result.
- Summary omits full output and continuation payloads.
- No Task 9 provider-neutral interface or Task 2 message type changes.
- No dependency, network use, branch/worktree/subagent, Git write, Task 12 logging/report, or Task 13 integration work is planned.
- The plan contains no unresolved placeholder or undefined production type.

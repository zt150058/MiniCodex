# Task 10 Context Management and Termination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`, `superpowers:test-driven-development`, and `superpowers:verification-before-completion` to execute this plan task-by-task. Use `superpowers:systematic-debugging` before changing code after any reproducible unexpected failure. Execute inline in the current workspace; do not dispatch another agent.

**Goal:** Implement deterministic local context compaction, exact logical/physical model budgets, formal termination policy, repeated-call detection, and safe Agent-loop integration without weakening the Task 8 safety boundary or beginning Task 11 verification behavior.

**Architecture:** `context.py` owns pure history measurement/turn partitioning plus one stateful `ContextManager.prepare(...)` orchestration method. `termination.py` owns immutable limits, stable decisions, priority, and fingerprints. A provider-neutral `ModelCallBudget` in `model.py` is claimed immediately before every physical request; an additive budget-aware client capability lets Task 9 retries share the same global budget while preserving `ModelClient.complete(ModelRequest) -> ModelResponse`.

**Tech Stack:** Python 3.11+, standard-library `dataclasses`, `enum`, `hashlib`, `json`, `math`, and `time`; existing `pytest` and official `openai` dependency. All tests use `FakeModelClient`, injected fake SDK objects, and fake clocks; no test reads credentials or uses the network.

**Spec:** `DESIGN.md` sections 4–8, 10–12, and 15–17; `TASKS.md` Task 10; `AGENTS.md`; approved `docs/superpowers/plans/Task9.md` continuation and retry contracts.

## Global constraints

- Work only in `D:\code\coding_agent` on the current `main` workspace.
- This plan creates no worktree and uses no subagent or parallel agent.
- During implementation, do not perform Git write or remote operations. Stop after fresh verification for user review.
- Do not add a dependency or modify `pyproject.toml`.
- Do not call a real OpenAI endpoint or read a real API key.
- Do not modify Task 8 path/command authorization behavior or execute tools outside `ToolRegistry`.
- Do not implement Task 11 verification decisions, Task 12 JSONL/reporting, or Task 13 integration/demo behavior.
- Task 10 finishes execution in `进行中`; only a later user-authorized closeout may mark it `已完成`.
- Every production behavior follows a distinct RED, minimal GREEN, and relevant Task 1–9 regression before the next behavior.

## Baseline locked by planning

- Repository root: `D:/code/coding_agent`; branch: `main`; Task 9 commit at HEAD: `59e5133 完成openai response api客户端`.
- Planning baseline: clean worktree, `git diff --check` exit 0, and `474 passed, 0 failed, 0 skipped, 1 PytestCacheWarning`.
- The warning is the known inability to write `D:\code\coding_agent\.pytest_cache`; pytest temporary workspaces remain usable.
- `TASKS.md` currently records Task 9 as `进行中` and Task 10 as `未开始`. Execution Task 0 changes only those two values after reconfirming the baseline.
- Existing `AgentState.model_call_count` counts logical calls only because `AgentRunner` increments it once before `complete`. Task 10 deliberately redefines it as the approved design's physical provider-attempt count and adds a separately named logical counter. Existing Fake-client expectations remain numerically unchanged because one fake completion is one physical attempt.
- Task 9 retries up to three physical SDK requests inside one `complete` call and currently exposes no per-attempt hook. Exact pre-attempt enforcement therefore requires the additive provider-neutral capability defined below.

## Locked file map

**Create**

- `src/coding_agent/context.py` — context limits, deterministic size measurement, complete-turn partitioning, summary validation/merging, fallback summary, and `ContextManager`.
- `src/coding_agent/termination.py` — limits, next-operation enum, decisions, priority checks, and stable call/result fingerprints.
- `tests/test_context.py` — offline context threshold, turn, summary, fallback, continuation, and over-budget tests.
- `tests/test_termination.py` — exact limit, priority, fake-clock, fingerprint, and counter-reset tests.

**Modify**

- `src/coding_agent/model.py` — additive `ModelCallBudget`, `ModelBudgetExceeded`, budget-aware Protocol, and `invoke_model`.
- `src/coding_agent/openai_client.py` — add `complete_with_budget`; keep existing `complete` signature and standalone three-attempt behavior.
- `src/coding_agent/state.py` — add Task 10 counters, fingerprints, timing, termination reason, workspace, and interruption status.
- `src/coding_agent/agent.py` — replace `max_rounds` with injected context/termination components and integrate checks at explicit loop boundaries.
- `tests/test_model.py` — model-budget unit tests and budget-aware Fake-client tests.
- `tests/test_openai_client.py` — shared physical-budget tests around Task 9 internal retries.
- `tests/test_agent_loop.py` — formal-policy integration, errors, repetition, interruption, and no-extra-operation tests; migrate the temporary `max_rounds` fixture to `TerminationLimits`.
- `TASKS.md` — during approved execution only, Task 9 `进行中` to `已完成` and Task 10 `未开始` to `进行中`; no other text or status changes.

**Read and keep unchanged**

- `src/coding_agent/messages.py`
- `src/coding_agent/config.py`
- `src/coding_agent/cli.py`
- `src/coding_agent/safety.py`
- every file under `src/coding_agent/tools/`
- all existing tests other than the three test files explicitly listed under Modify
- `pyproject.toml`, `AGENTS.md`, and `DESIGN.md`

## Locked public interfaces

### Provider-neutral model accounting (`model.py`)

```python
class ModelBudgetReason(StrEnum):
    LOGICAL_CALL_LIMIT = "logical_model_call_limit"
    PROVIDER_ATTEMPT_LIMIT = "provider_attempt_limit"


class ModelBudgetExceeded(ModelError):
    reason: ModelBudgetReason


@dataclass(slots=True)
class ModelCallBudget:
    max_logical_calls: int = 12
    max_provider_attempts: int = 12
    logical_calls: int = 0
    provider_attempts: int = 0

    def start_logical_call(self) -> None: ...
    def claim_provider_attempt(self) -> None: ...
    @property
    def remaining_provider_attempts(self) -> int: ...


@runtime_checkable
class BudgetAwareModelClient(Protocol):
    def complete_with_budget(
        self,
        request: ModelRequest,
        budget: ModelCallBudget,
    ) -> ModelResponse: ...


def invoke_model(
    client: ModelClient,
    request: ModelRequest,
    budget: ModelCallBudget,
) -> ModelResponse: ...
```

`invoke_model` calls `budget.start_logical_call()` exactly once. A `BudgetAwareModelClient` claims each physical request itself; any other `ModelClient` is treated as one physical attempt, so `invoke_model` claims once immediately before `client.complete(request)`.

`ModelBudgetExceeded` uses only these messages:

- `logical model call limit reached`
- `provider attempt limit reached`

At `used == max`, the next claim fails before the counter changes or provider is called. Counts can equal limits and never exceed them.

`FakeModelClient.complete` and `OpenAIResponsesClient.complete` keep their existing signatures and semantics. Both gain additive `complete_with_budget`. Standalone OpenAI `complete` creates a private `ModelCallBudget(max_logical_calls=1, max_provider_attempts=3)` and delegates through `invoke_model`, retaining Task 9's exact retry contract.

### State and termination (`state.py`, `termination.py`)

```python
class AgentStatus(StrEnum):
    RUNNING = "running"
    COMPLETION_CANDIDATE = "completion_candidate"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class TerminationReason(StrEnum):
    LOGICAL_MODEL_CALL_LIMIT = "logical_model_call_limit"
    PROVIDER_ATTEMPT_LIMIT = "provider_attempt_limit"
    TOOL_CALL_LIMIT = "tool_call_limit"
    TIME_LIMIT = "time_limit"
    REPEATED_TOOL_CALL = "repeated_tool_call"
    CONSECUTIVE_MODEL_ERRORS = "consecutive_model_errors"
    CONSECUTIVE_TOOL_ERRORS = "consecutive_tool_errors"
    CONSECUTIVE_SAFETY_REJECTIONS = "consecutive_safety_rejections"
    CONTEXT_BUDGET_EXHAUSTED = "context_budget_exhausted"
    FATAL_MODEL_ERROR = "fatal_model_error"
    EMPTY_MODEL_RESPONSE = "empty_model_response"
    INTERNAL_INVARIANT = "internal_invariant"
    USER_INTERRUPTED = "user_interrupted"


@dataclass(frozen=True, slots=True)
class TerminationLimits:
    max_logical_model_calls: int = 12
    max_provider_attempts: int = 12
    max_tool_calls: int = 40
    max_runtime_seconds: float = 600.0
    repetition_limit: int = 3
    consecutive_error_limit: int = 3
    safety_rejection_limit: int = 3


class NextOperation(StrEnum):
    MODEL = "model"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class TerminationDecision:
    should_stop: bool
    reason: TerminationReason | None = None


class TerminationPolicy:
    def __init__(self, limits: TerminationLimits = TerminationLimits()) -> None: ...
    @property
    def limits(self) -> TerminationLimits: ...
    def check(
        self,
        state: AgentState,
        monotonic_time: float,
        *,
        next_operation: NextOperation,
    ) -> TerminationDecision: ...


def tool_call_fingerprint(call: ToolCall) -> str: ...
def tool_result_fingerprint(result: ToolResult) -> str: ...
```

`AgentState` adds these exact fields while retaining existing fields:

```python
workspace: Path
started_at_monotonic: float
logical_model_call_count: int = 0
model_call_count: int = 0              # physical provider attempts
consecutive_model_errors: int = 0
consecutive_tool_errors: int = 0
consecutive_safety_rejections: int = 0
repeated_tool_call_count: int = 0
last_tool_fingerprint: str | None = None
last_tool_result_fingerprint: str | None = None
termination_reason: TerminationReason | None = None
```

`AgentState.start(task, workspace, started_at_monotonic)` validates a non-negative finite timestamp and stores the normalized workspace already supplied by `ExecutionContext`. `failure_reason` remains for Task 4 compatibility and is always set to `termination_reason.value` on a Task 10 failure.

`AgentInterrupted` is a `KeyboardInterrupt` subclass carrying the interrupted `AgentState`. `AgentRunner` catches only `KeyboardInterrupt`, sets status `INTERRUPTED` and reason `USER_INTERRUPTED`, and raises `AgentInterrupted(state)` from `None`. It does not catch `SystemExit` or other `BaseException`. This preserves interrupt semantics and gives Task 12 a provider-neutral state to log before exit 130.

### Context (`context.py`)

```python
class SummarySource(StrEnum):
    NONE = "none"
    MODEL = "model"
    FALLBACK = "fallback"


@dataclass(frozen=True, slots=True)
class ContextLimits:
    max_serialized_chars: int = 60_000
    max_history_items: int = 24
    recent_turns: int = 8
    max_summary_chars: int = 12_000
    summary_max_output_tokens: int = 4096


@dataclass(frozen=True, slots=True)
class ContextSize:
    serialized_chars: int
    history_items: int


@dataclass(frozen=True, slots=True)
class ContextSummary:
    goal: str
    established_facts: tuple[str, ...]
    files_examined: tuple[str, ...]
    changes_made: tuple[str, ...]
    commands_and_results: tuple[str, ...]
    unresolved_errors: tuple[str, ...]
    open_issues: tuple[str, ...]
    verification_state: JSONObject
    avoid_repeating: tuple[str, ...]

    def to_dict(self) -> JSONObject: ...
    def to_json(self) -> str: ...


@dataclass(frozen=True, slots=True)
class PreparedContext:
    messages: tuple[Message, ...]
    continuation_items: tuple[object, ...] = field(repr=False)
    size: ContextSize
    compressed: bool
    summary_source: SummarySource
    summary_model_failed: bool = False


class ContextPreparationError(RuntimeError):
    reason: TerminationReason


class ContextManager:
    def __init__(
        self,
        *,
        model_client: ModelClient,
        limits: ContextLimits = ContextLimits(),
    ) -> None: ...

    @staticmethod
    def measure(messages: tuple[Message, ...]) -> ContextSize: ...

    def prepare(
        self,
        state: AgentState,
        budget: ModelCallBudget,
    ) -> PreparedContext: ...
```

The following module functions are pure and testable but private: `_measure_messages`, `_partition_complete_turns`, `_parse_summary`, `_merge_local_invariants`, `_fallback_summary`, and `_render_summary_message`.

## Locked context algorithm

1. Canonically serialize only provider-neutral semantic messages as a compact UTF-8 JSON array with `ensure_ascii=False`, sorted keys, and compact separators. Opaque continuation items are never inspected, counted, serialized, printed, or copied into the summary.
2. Trigger compression only when `serialized_chars > 60_000` or `history_items > 24`. Exact equality does not trigger because the approved design says “超过”. Real `TokenUsage` remains available for later logs but does not control Task 10; the approved design explicitly chose a deterministic character approximation without a tokenizer.
3. The first `UserMessage` is the immutable original task. A previously rendered context-summary `UserMessage` immediately after it belongs to the compressible prefix, not to the recent suffix.
4. One complete turn is one `AssistantMessage` plus every immediately following `ToolResult` matching that assistant's calls in exact call order. An assistant without calls is a one-message turn. A call group is never split. An orphan result, missing result, reordered result, or duplicate summary marker raises `ContextPreparationError(INTERNAL_INVARIANT)` before a summary call.
5. Retain the original task plus the newest eight complete turns. Everything between the task and retained suffix becomes the summarization prefix. If the threshold is exceeded but there is no removable complete prefix, fail with `CONTEXT_BUDGET_EXHAUSTED` rather than truncating a tool pair or recent turn.
6. Request a semantic summary with `invoke_model` using exactly one `ModelRequest`: one user prompt containing canonical prefix JSON and the exact nine-field schema, `tool_schemas=()`, `max_output_tokens=4096`, and `continuation_items=()`. A summary response must contain non-empty text, no tool calls, and JSON with exactly the nine fields. `goal` is a string; `verification_state` is an object; the other seven fields are arrays of strings.
7. Merge deterministic local invariants after model validation. Local values override conflicting model values: original task, normalized workspace, `modified_paths`, `mutation_index`, current verification status, current counters, and `open_issues`. Until Task 11 supplies evidence fields, `verification_state` contains truthful neutral values: `validation_index: null`, `command: null`, `source: null`, and `exit_code: null`; this does not implement a verification decision.
8. On `TransientModelError`, text with tool calls, invalid JSON, missing/extra fields, wrong field types, or an oversized model summary, build the same nine fields locally from state and paired history. Include bounded recent tool errors and command results; truncate individual evidence strings deterministically before rendering. `FatalModelError` and `ModelBudgetExceeded` are not degraded: both propagate to the Agent termination path because continuing cannot make the provider/configuration or budget valid.
9. The final summary JSON must be at most 12,000 characters. If mandatory local invariants alone cannot fit, fail with `CONTEXT_BUDGET_EXHAUSTED` rather than dropping them.
10. Replace active messages with `(original_task, summary_user_message, *recent_turn_messages)`. The summary message content is exactly `coding-agent context summary\n` plus compact `ContextSummary.to_json()`.
11. On every successful compression, return `continuation_items=()` regardless of summary response continuation. On no compression, return the original continuation tuple by identity. The Agent applies messages and continuation together before constructing its next request.
12. Re-measure the prepared history. If either threshold still exceeds its limit, terminate with `CONTEXT_BUDGET_EXHAUSTED`; do not recursively summarize or retain fewer than eight turns.

## Locked counter semantics and termination priority

- `logical_model_call_count` increments once when `invoke_model` accepts a main or summary logical call.
- `model_call_count` increments immediately before each fake or real provider request. Task 9's retries each claim separately.
- A logical call may start only when `logical_calls < max_logical_calls`; a provider attempt may start only when `provider_attempts < max_provider_attempts`.
- `tool_call_count` increments after each actual `ToolRegistry.execute` return, regardless of `ok`, `error`, or `rejected`. Synthetic “not executed because terminated” results are not counted.
- A tool operation may begin only when `tool_call_count < max_tool_calls` and no higher-priority stop applies.
- Time uses injected monotonic values. At `elapsed >= max_runtime_seconds`, the next model/tool operation is forbidden. A model completion already returned before the boundary remains a completion candidate.
- `consecutive_model_errors` increments for nonfatal main-call `ModelError`; a valid main or summary `ModelResponse` resets it. Fatal errors terminate immediately.
- A non-security `error` or `rejected` tool result increments `consecutive_tool_errors` and resets `consecutive_safety_rejections`. An `ok` result resets both. An error beginning `security_rejected:` increments only `consecutive_safety_rejections` and resets the generic tool-error counter.
- Tool fingerprints are SHA-256 over `name + "\n" + canonical arguments JSON`. Result fingerprints are SHA-256 over canonical JSON containing `tool_name`, `status`, `output`, `error`, and `metadata`; provider-generated `call_id` is deliberately excluded so semantically identical results can repeat across calls.
- After an executed tool, repetition increments only when call and result fingerprints equal the preceding pair and `mutation_index` did not advance. Different call, different result, successful mutation, or future verification progress resets repetition to zero. The third no-progress occurrence is allowed to finish, sets count 3, and prevents every later operation.
- If termination occurs midway through a multi-call response, append deterministic `rejected` `ToolResult` values for remaining calls with `error="agent_terminated:<reason>"` without invoking the Registry or incrementing counters. This preserves message pairing and prevents an orphaned call.

`TerminationPolicy.check` uses this exact priority when multiple conditions are true:

1. `INTERNAL_INVARIANT`
2. `CONSECUTIVE_SAFETY_REJECTIONS`
3. `TIME_LIMIT`
4. `LOGICAL_MODEL_CALL_LIMIT` when the next operation is model
5. `PROVIDER_ATTEMPT_LIMIT` when the next operation is model
6. `TOOL_CALL_LIMIT` when the next operation is tool
7. `CONSECUTIVE_MODEL_ERRORS`
8. `CONSECUTIVE_TOOL_ERRORS`
9. `REPEATED_TOOL_CALL`

Immediate event reasons `USER_INTERRUPTED`, `FATAL_MODEL_ERROR`, `CONTEXT_BUDGET_EXHAUSTED`, and `EMPTY_MODEL_RESPONSE` bypass priority comparison. A valid no-tool text response becomes `COMPLETION_CANDIDATE` before checking whether the just-finished call reached a numerical ceiling; limits prevent the next operation, not acceptance of the operation that was already permitted.

---

### Task 0: Reconfirm Task 9 baseline and activate only Task 10

**Files:** Read all baseline files; after every check passes, modify only two status values in `TASKS.md`.

**Interfaces:** No production interface change.

- [ ] **Step 1: Re-read the complete baseline**

Read `AGENTS.md`, `DESIGN.md`, `TASKS.md`, `docs/superpowers/plans/Task9.md`, this plan, every file under `src/coding_agent`, and every tracked test. Confirm the interfaces in the Locked public interfaces section still match the repository.

- [ ] **Step 2: Verify repository identity and Task 9 commit**

Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git log -3 --oneline
git status --short --untracked-files=all
git diff --check
```

Expected: root `D:/code/coding_agent`, branch `main`, HEAD contains approved Task 9, no worktree changes except this approved plan if it has not been committed, and `git diff --check` exits 0. Any unexplained change stops execution.

- [ ] **Step 3: Run the complete baseline**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: exit 0 with fresh Task 1–9 counts. Any failure stops execution.

- [ ] **Step 4: Update only task status bookkeeping**

Change Task 9 `进行中` to `已完成` and Task 10 `未开始` to `进行中`. Run `git diff -- TASKS.md` and confirm exactly those two lines changed and exactly one task is active.

**Acceptance:** Task 9 is committed and green, the workspace baseline is understood, and no production edit occurs before Task 10 alone becomes active.

---

### Task 1: Exact logical and physical model-call budget

**Files:**

- Modify: `src/coding_agent/model.py`
- Modify: `src/coding_agent/openai_client.py`
- Modify: `tests/test_model.py`
- Modify: `tests/test_openai_client.py`

**Interfaces:** Produces `ModelCallBudget`, `ModelBudgetReason`, `ModelBudgetExceeded`, `BudgetAwareModelClient`, and `invoke_model`. Reuses existing `ModelClient`, `ModelRequest`, and `ModelResponse` without changing their signatures or fields.

- [ ] **Step 1: Add RED tests for generic counting and off-by-one behavior**

Append to `tests/test_model.py`:

```python
from coding_agent.model import (
    ModelBudgetExceeded,
    ModelBudgetReason,
    ModelCallBudget,
    invoke_model,
)


def test_invoke_model_counts_one_logical_and_one_physical_attempt() -> None:
    client = FakeModelClient((ModelResponse(text="done"),))
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=1)

    response = invoke_model(client, _request("count"), budget)

    assert response.text == "done"
    assert budget.logical_calls == 1
    assert budget.provider_attempts == 1
    assert len(client.requests) == 1


@pytest.mark.parametrize(
    ("logical_calls", "provider_attempts", "reason"),
    [
        (1, 0, ModelBudgetReason.LOGICAL_CALL_LIMIT),
        (0, 1, ModelBudgetReason.PROVIDER_ATTEMPT_LIMIT),
    ],
)
def test_budget_rejects_before_call_without_exceeding_limit(
    logical_calls: int,
    provider_attempts: int,
    reason: ModelBudgetReason,
) -> None:
    client = FakeModelClient((ModelResponse(text="must not run"),))
    budget = ModelCallBudget(
        max_logical_calls=1,
        max_provider_attempts=1,
        logical_calls=logical_calls,
        provider_attempts=provider_attempts,
    )

    with pytest.raises(ModelBudgetExceeded) as caught:
        invoke_model(client, _request("blocked"), budget)

    assert caught.value.reason is reason
    assert budget.logical_calls <= budget.max_logical_calls
    assert budget.provider_attempts <= budget.max_provider_attempts
    assert client.requests == ()
```

- [ ] **Step 2: Run generic budget RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_model.py -k model_budget -q`

Expected: collection fails because the new names do not exist.

- [ ] **Step 3: Implement the minimum generic budget**

Implement the exact interfaces above. Reject bool, non-integer, and negative limits/counts. `invoke_model` uses the additive budget-aware protocol and otherwise claims one physical attempt before `complete`.

- [ ] **Step 4: Run generic budget GREEN and model regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_model.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_agent_loop.py -q
```

Expected: both commands exit 0 with actual counts; existing `complete` signatures and fake sequencing remain unchanged.

- [ ] **Step 5: Add RED tests for Task 9 retries sharing the global budget**

Append to `tests/test_openai_client.py`:

```python
from coding_agent.model import ModelBudgetExceeded, ModelBudgetReason, ModelCallBudget, invoke_model


def test_openai_retries_claim_each_shared_provider_attempt() -> None:
    delays: list[float] = []
    sdk = FakeSDKClient(
        FakeRateLimitError("hidden"),
        text_response("recovered"),
    )
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=sdk,
        sleeper=delays.append,
    )
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=2)

    response = invoke_model(
        client,
        ModelRequest(messages=(UserMessage("retry"),)),
        budget,
    )

    assert response.text == "recovered"
    assert (budget.logical_calls, budget.provider_attempts) == (1, 2)
    assert len(sdk.responses.calls) == 2
    assert delays == [0.25]


def test_openai_global_budget_prevents_third_physical_request() -> None:
    delays: list[float] = []
    sdk = FakeSDKClient(
        FakeRateLimitError("hidden"),
        FakeRateLimitError("hidden"),
        text_response("must not run"),
    )
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=sdk,
        sleeper=delays.append,
    )
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=2)

    with pytest.raises(ModelBudgetExceeded) as caught:
        invoke_model(client, ModelRequest(messages=(UserMessage("retry"),)), budget)

    assert caught.value.reason is ModelBudgetReason.PROVIDER_ATTEMPT_LIMIT
    assert len(sdk.responses.calls) == 2
    assert budget.provider_attempts == 2
    assert delays == [0.25]
```

- [ ] **Step 6: Run Task 9 shared-budget RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k shared_provider -q`

Expected: nonzero because Task 9 has no budget-aware method and the generic fallback counts only one physical attempt.

- [ ] **Step 7: Implement additive budget-aware clients**

`FakeModelClient.complete_with_budget` claims once and delegates to its unchanged `complete`. Move the existing OpenAI retry body into `complete_with_budget`; claim immediately before every `responses.create`. Before sleeping for another retry, if `remaining_provider_attempts == 0`, raise `ModelBudgetExceeded(PROVIDER_ATTEMPT_LIMIT)` without sleeping. Keep provider errors sanitized and `BaseException` propagation unchanged.

- [ ] **Step 8: Run shared-budget GREEN and Task 1–9 regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_model.py tests\test_openai_client.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_messages.py tests\test_agent_loop.py tests\tools tests\test_path_safety.py tests\test_command_safety.py -q
```

Expected: both exit 0. Existing standalone Task 9 tests still prove three maximum attempts and `[0.25, 0.50]`; shared budget proves exact global pre-attempt enforcement.

**Acceptance:** logical and physical counts are distinct, limits are never exceeded, Task 9 retries consume shared physical budget, and no SDK type leaves `openai_client.py`.

---

### Task 2: Formal state, limits, priority, fake clock, and fingerprints

**Files:**

- Create: `src/coding_agent/termination.py`
- Create: `tests/test_termination.py`
- Modify: `src/coding_agent/state.py`
- Modify: `src/coding_agent/agent.py` only to pass `execution_context.workspace` and `time.monotonic()` to the new `AgentState.start` signature; formal loop behavior remains Task 5.

**Interfaces:** Produces the exact state, limits, decision, operation, reason, and fingerprint interfaces locked above. Consumes existing `ToolCall`, `ToolResult`, and `AgentState`.

- [ ] **Step 1: Write RED tests for defaults, validation, and exact boundary semantics**

Create `tests/test_termination.py` with:

```python
from pathlib import Path

import pytest

from coding_agent.state import AgentState, TerminationReason
from coding_agent.termination import (
    NextOperation,
    TerminationLimits,
    TerminationPolicy,
)


def state_at(tmp_path: Path, *, started: float = 10.0) -> AgentState:
    return AgentState.start("task", tmp_path, started)


def test_default_limits_match_design() -> None:
    assert TerminationLimits() == TerminationLimits(
        max_logical_model_calls=12,
        max_provider_attempts=12,
        max_tool_calls=40,
        max_runtime_seconds=600.0,
        repetition_limit=3,
        consecutive_error_limit=3,
        safety_rejection_limit=3,
    )


def test_exact_model_limit_blocks_next_call_not_completed_call(tmp_path: Path) -> None:
    state = state_at(tmp_path)
    state.logical_model_call_count = 12
    state.model_call_count = 12
    decision = TerminationPolicy().check(
        state,
        11.0,
        next_operation=NextOperation.MODEL,
    )
    assert decision.should_stop
    assert decision.reason is TerminationReason.LOGICAL_MODEL_CALL_LIMIT


def test_exact_time_limit_blocks_next_operation(tmp_path: Path) -> None:
    state = state_at(tmp_path, started=100.0)
    decision = TerminationPolicy().check(
        state,
        700.0,
        next_operation=NextOperation.TOOL,
    )
    assert decision.reason is TerminationReason.TIME_LIMIT
```

Add a parameterized validation matrix rejecting bool, zero/negative maxima, nonfinite runtime, negative counters, and timestamps earlier than start. Do not require physical attempts to be at least logical calls: an admitted logical call can be refused before its first provider request when the shared physical budget is exhausted.

- [ ] **Step 2: Run policy boundary RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_termination.py -q`

Expected: collection fails because Task 10 state and termination names do not exist.

- [ ] **Step 3: Implement state fields and minimal policy**

Add the exact enums/fields and `AgentState.start` signature. Implement immutable validated limits and `check` with the locked priority. Invalid state returns `TerminationDecision(True, INTERNAL_INVARIANT)`; constructor input errors raise stable `ValueError`. Update the existing `AgentRunner.run` state construction to call `AgentState.start(task, self._execution_context.workspace, time.monotonic())`; make no other loop change in this task. This is the minimum compatibility edit required to keep all existing Agent tests green after the signature change.

- [ ] **Step 4: Run policy boundary GREEN and state regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_termination.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py tests\test_messages.py -q
```

Expected: both commands exit 0. The one state-construction compatibility edit keeps the current `max_rounds` loop behavior unchanged until Task 5 replaces it.

- [ ] **Step 5: Add RED tests for priority and fingerprints**

Append:

```python
from coding_agent.messages import ToolCall, ToolResult
from coding_agent.termination import tool_call_fingerprint, tool_result_fingerprint


def test_priority_is_stable_when_multiple_conditions_hold(tmp_path: Path) -> None:
    state = state_at(tmp_path)
    state.logical_model_call_count = 12
    state.model_call_count = 12
    state.tool_call_count = 40
    state.consecutive_safety_rejections = 3
    state.consecutive_model_errors = 3
    state.repeated_tool_call_count = 3
    decision = TerminationPolicy().check(
        state,
        700.0,
        next_operation=NextOperation.MODEL,
    )
    assert decision.reason is TerminationReason.CONSECUTIVE_SAFETY_REJECTIONS


def test_argument_order_does_not_change_tool_fingerprint() -> None:
    left = ToolCall("a", "read_file", {"path": "a.py", "end_line": 2})
    right = ToolCall("b", "read_file", {"end_line": 2, "path": "a.py"})
    assert tool_call_fingerprint(left) == tool_call_fingerprint(right)


def test_result_fingerprint_changes_with_observed_result() -> None:
    first = ToolResult("a", "read_file", "ok", output="one")
    second = ToolResult("a", "read_file", "ok", output="two")
    assert tool_result_fingerprint(first) != tool_result_fingerprint(second)
```

- [ ] **Step 6: Run priority/fingerprint RED**

Run the three explicit nodes above. Expected: nonzero until canonical hashing and exact priority exist.

- [ ] **Step 7: Implement canonical fingerprints and finish priority**

Use compact sorted JSON and SHA-256. Do not include `call_id` in either call or result fingerprints, because provider-generated IDs differ across semantically identical repeated requests. Result fingerprints include exactly `tool_name`, `status`, `output`, `error`, and `metadata`.

- [ ] **Step 8: Run Task 2 GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_termination.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py -q
```

Expected: all exit 0 with actual counts.

**Acceptance:** every limit has explicit equality semantics, priority is deterministic, fingerprints ignore JSON key order, and fake time requires no sleep.

---

### Task 3: Pure context measurement and complete-turn partitioning

**Files:**

- Create: `src/coding_agent/context.py`
- Create: `tests/test_context.py`

**Interfaces:** Produces `ContextLimits`, `ContextSize`, `ContextSummary`, `PreparedContext`, `SummarySource`, `ContextPreparationError`, and `ContextManager`. This task implements no summary model call yet.

- [ ] **Step 1: Write RED tests for strict thresholds and no-compression identity**

Create these deterministic helpers before the tests so every later fixture name is defined:

- `make_state_with_n_complete_turns(tmp_path: Path, count: int) -> AgentState` starts at time `0.0`, then appends `count` text-only `AssistantMessage` turns named `turn-00` through `turn-NN`.
- `make_compressible_state(tmp_path: Path) -> AgentState` builds nine complete turns with a 5,000-character oldest turn and eight short newest turns; it exceeds a 2,000-character limit before compaction and fits after removing/summarizing the oldest turn.
- `make_single_huge_recent_turn(tmp_path: Path) -> AgentState` builds one 5,000-character text-only turn, proving there is no removable prefix when `recent_turns=8`.
- `valid_summary_json() -> str` returns compact sorted JSON with exactly the nine locked fields and valid values; `valid_summary_response() -> ModelResponse` wraps that string as text with no calls or continuation.
- `triggered_manager(client: ModelClient) -> ContextManager` uses `ContextLimits(max_serialized_chars=2_000, max_history_items=24)`; `tiny_manager(client: ModelClient) -> ContextManager` uses `ContextLimits(max_serialized_chars=100, max_history_items=24)`.
- `append_tool_turn(state, *, turn_number: int, call_count: int) -> tuple[ToolCall, ...]` appends one `AssistantMessage` with ordered calls `call-{turn_number}-{index}` and exactly matching `ToolResult(status="ok")` values in the same order, then returns those calls for assertions.

Then add these tests in `tests/test_context.py`:

```python
def manager(client: FakeModelClient, **changes: int) -> ContextManager:
    return ContextManager(
        model_client=client,
        limits=ContextLimits(**changes),
    )


def test_context_at_exact_threshold_is_not_compressed(tmp_path: Path) -> None:
    marker = object()
    state = AgentState.start("task", tmp_path, 0.0)
    state.continuation_items = (marker,)
    measured = ContextManager.measure(state.messages)
    context = manager(
        FakeModelClient(()),
        max_serialized_chars=measured.serialized_chars,
        max_history_items=1,
    ).prepare(state, ModelCallBudget())
    assert not context.compressed
    assert context.messages is state.messages
    assert context.continuation_items is state.continuation_items


def test_one_character_past_threshold_requests_compression(tmp_path: Path) -> None:
    state = make_compressible_state(tmp_path)
    measured = ContextManager.measure(state.messages)
    client = FakeModelClient((valid_summary_response(),))
    context = manager(
        client,
        max_serialized_chars=measured.serialized_chars - 1,
        max_history_items=len(state.messages),
    ).prepare(state, ModelCallBudget())
    assert context.compressed


def test_one_item_past_threshold_requests_compression(tmp_path: Path) -> None:
    state = make_state_with_n_complete_turns(tmp_path, 25)
    measured = ContextManager.measure(state.messages)
    client = FakeModelClient((valid_summary_response(),))
    context = manager(
        client,
        max_serialized_chars=measured.serialized_chars,
        max_history_items=len(state.messages) - 1,
    ).prepare(state, ModelCallBudget())
    assert context.compressed
```

The second test initially fails at the not-yet-implemented summary boundary; it must never fail because a test fixture has an unresolved call.

- [ ] **Step 2: Run threshold RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_context.py -k threshold -q`

Expected: collection/behavior failure because context types and measurement do not exist.

- [ ] **Step 3: Implement limits, measurement, and no-compression path**

Implement canonical semantic-message JSON measurement, exact `>` triggering, immutable return types, and no-compression identity. For a triggered history, temporarily raise the stable `ContextPreparationError(CONTEXT_BUDGET_EXHAUSTED)` until later RED tests drive summary behavior.

- [ ] **Step 4: Run no-compression GREEN**

Run only `test_context_at_exact_threshold_is_not_compressed`; expected `1 passed`.

- [ ] **Step 5: Add RED tests for complete turn boundaries**

Lock the private pure helper signature as:

```python
def _partition_complete_turns(
    messages: tuple[Message, ...],
) -> tuple[
    UserMessage,
    tuple[Message, ...],
    tuple[tuple[Message, ...], ...],
]: ...
```

The return values are the unchanged initial task, the compressible prefix before the first complete assistant turn (empty or one prior summary marker), and ordered complete turns. Directly test this pure helper in Task 3:

- ten text-only turns produce ten one-message groups, each beginning with `AssistantMessage`;
- an assistant with two ordered calls produces one three-message group containing the assistant and its two matching results in call order;
- an orphan, missing, reordered, or duplicate `ToolResult` raises `ContextPreparationError(INTERNAL_INVARIANT)`;
- the initial `UserMessage` is returned byte-for-byte equal;
- one prior `coding-agent context summary\n` user message is returned in the prefix and is not counted as a recent turn; a duplicate summary marker is rejected.

Use complete code that constructs every `ToolCall`, matching `ToolResult`, and `AssistantMessage`. The end-to-end assertion that `prepare` retains exactly eight newest turns moves to Task 4 after summary generation exists; Task 3 does not fabricate an incomplete summary path.

- [ ] **Step 6: Run turn-boundary RED**

Run the named pure partition tests. Expected: nonzero because `_partition_complete_turns` does not exist.

- [ ] **Step 7: Implement complete-turn partitioning**

Implement the locked pure helper signature, turn definition, summary-prefix handling, and stable invariant errors. Do not call a model, truncate content, select a retained suffix, or inspect continuation in this step.

- [ ] **Step 8: Run Task 3 GREEN and existing message regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_context.py -k "exact_threshold or turn or orphan" -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py -q
```

If the Windows runner splits the quoted `-k` expression, rerun the exact same selection with explicit pytest node IDs and record both commands. Expected: all selected tests and regressions pass. The two compression-trigger tests remain RED by design until Task 4 and are excluded from this Task 3 GREEN command.

**Acceptance:** thresholds have proven off-by-one semantics, no-compression preserves continuation identity, and no tool pair can be split.

---

### Task 4: Structured model summary, deterministic fallback, and continuation reset

**Files:**

- Modify: `src/coding_agent/context.py`
- Modify: `tests/test_context.py`

**Interfaces:** Completes `ContextManager.prepare` and all nine `ContextSummary` fields. Uses `invoke_model` so summary calls share Task 10 budgets.

- [ ] **Step 1: Add RED tests for exact summary request and deterministic structure**

Add a valid summary response helper whose JSON has exactly:

```python
{
    "goal": "model value must be overridden",
    "established_facts": ["fact"],
    "files_examined": ["src/a.py"],
    "changes_made": [],
    "commands_and_results": ["pytest failed"],
    "unresolved_errors": ["one failure"],
    "open_issues": ["model issue"],
    "verification_state": {"status": "model supplied"},
    "avoid_repeating": ["same read"],
}
```

Tests assert:

```python
assert summary_request.tool_schemas == ()
assert summary_request.continuation_items == ()
assert summary_request.max_output_tokens == 4096
assert prepared.messages[0] == UserMessage(state.task)
assert prepared.messages[1].content.startswith("coding-agent context summary\n")
assert parsed["goal"] == state.task
assert parsed["changes_made"] == list(state.modified_paths)
assert parsed["verification_state"] == {
    "status": state.verification_status.value,
    "mutation_index": state.mutation_index,
    "validation_index": None,
    "command": None,
    "source": None,
    "exit_code": None,
}
assert budget.logical_calls == 1
assert budget.provider_attempts == 1
```

Call `prepare` twice with equivalent independently built states and assert identical summary message content and identical prepared semantic messages. Assert the prepared history contains exactly the original task, one summary message, and the newest eight complete turns; the oldest summarized turn is absent.

- [ ] **Step 2: Run model-summary RED**

Run explicit nodes for exact request, local invariant override, and deterministic output. Expected: nonzero because the triggered path still raises.

- [ ] **Step 3: Implement strict summary parse, merge, and render**

Require exact keys and locked field types, deduplicate arrays in first-seen order, merge local facts after parsing, compactly encode, enforce 12,000 characters, and retain newest eight turns. Never store the summary response continuation.

- [ ] **Step 4: Run model-summary GREEN and model-budget regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_context.py -k model_summary -q
.\.venv\Scripts\python.exe -m pytest tests\test_model.py tests\test_openai_client.py -q
```

Expected: all exit 0.

- [ ] **Step 5: Add RED fallback and continuation-lifecycle matrix**

Parameterize summary failures with `TransientModelError`, invalid JSON, missing field, extra field, wrong list type, summary response with tool calls, and oversized text. For each, assert `SummarySource.FALLBACK`, `summary_model_failed is True`, exact nine fields, and deterministic identical output on repeated equivalent input. Add separate `FatalModelError` and exhausted-`ModelCallBudget` cases asserting the exact exception propagates and no prepared history is returned.

Add:

```python
def test_compression_discards_active_and_summary_continuation(tmp_path: Path) -> None:
    old = object()
    summary_only = object()
    state = make_compressible_state(tmp_path)
    state.continuation_items = (old,)
    client = FakeModelClient((
        ModelResponse(text=valid_summary_json(), continuation_items=(summary_only,)),
    ))
    prepared = triggered_manager(client).prepare(state, ModelCallBudget())
    assert prepared.continuation_items == ()
    assert repr(old) not in repr(prepared)
    assert repr(summary_only) not in repr(prepared)


def test_uncompressible_or_still_oversized_context_fails_stably(tmp_path: Path) -> None:
    state = make_single_huge_recent_turn(tmp_path)
    with pytest.raises(ContextPreparationError) as caught:
        tiny_manager(FakeModelClient(())).prepare(state, ModelCallBudget())
    assert caught.value.reason is TerminationReason.CONTEXT_BUDGET_EXHAUSTED
```

- [ ] **Step 6: Run fallback/lifecycle RED**

Run explicit nodes for the parameterized fallback, continuation reset, no-removable-prefix, and still-over-limit tests. Expected: nonzero until all degradation and failure paths are stable.

- [ ] **Step 7: Implement deterministic fallback and final re-measurement**

Build fallback facts only from provider-neutral state and paired messages. Truncate evidence by newest-first fixed character slices, never by nondeterministic set order. Re-measure final messages and raise without recursive summarization when limits remain exceeded. Propagate `ModelBudgetExceeded` unchanged.

- [ ] **Step 8: Run complete context GREEN and Task 1–9 regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_context.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\test_openai_client.py tests\tools tests\test_path_safety.py tests\test_command_safety.py -q
```

Expected: both exit 0 with real counts.

**Acceptance:** model and fallback summaries share one stable schema, local invariants win, continuation is cleared only on compression, and an irreducible context terminates safely.

---

### Task 5: Integrate formal policy into the Agent loop

**Files:**

- Modify: `src/coding_agent/agent.py`
- Modify: `tests/test_agent_loop.py`

**Interfaces:** `AgentRunner` constructor becomes:

```python
def __init__(
    self,
    *,
    model_client: ModelClient,
    tool_registry: ToolRegistry,
    execution_context: ExecutionContext,
    context_manager: ContextManager | None = None,
    termination_policy: TerminationPolicy | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> None: ...
```

The temporary `max_rounds` parameter is removed as explicitly scheduled by Task 4. Tests requiring small limits inject `TerminationPolicy(TerminationLimits(...))`. Existing ModelClient and tool interfaces remain unchanged.

- [ ] **Step 1: Add RED tests for model/tool/time prechecks and no extra operation**

Migrate `_runner` to accept `limits` and `clock`. Add a `FakeClock` whose `__call__` returns a controlled float without sleeping. Tests prove:

- with logical limit 2, exactly two Fake requests occur and the third is never sent;
- with provider limit 2 and Task 9 retrying, exactly two fake SDK calls occur;
- with tool limit 1, one Registry execution occurs and the next call is represented by an unexecuted paired rejection;
- at elapsed 600.0, no next model or tool call begins;
- counters equal limits and never exceed them.

Expected final state reasons are the exact `TerminationReason` values, and `failure_reason == termination_reason.value`.

- [ ] **Step 2: Run precheck RED**

Run the named limit/time tests. Expected: nonzero because `AgentRunner` still uses `max_rounds` and direct `complete`.

- [ ] **Step 3: Implement minimal policy/context/budget loop skeleton**

Create state with workspace and clock, one run-scoped `ModelCallBudget` from policy limits, and default `ContextManager`/`TerminationPolicy` when omitted. At each model boundary: policy precheck; context prepare inside `try/finally`; immediately synchronize both budget counts to state even when summary preparation raises; atomically apply prepared messages/continuation; run a second policy precheck after a summary; call `invoke_model`; and synchronize both counts again in `finally`. At each tool boundary: policy check before Registry execution and after counter updates. Use a single `_terminate(state, reason)` helper.

- [ ] **Step 4: Run precheck GREEN and existing Agent behavior regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -k "limit or time or direct_text or paired" -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_context.py tests\test_termination.py -q
```

Expected: all selected tests pass; completion-candidate behavior remains unchanged.

- [ ] **Step 5: Add RED tests for errors, resets, repetition, priority, and interruption**

Add the following named tests. Use the existing `_runner` fixture extended with a `TerminationLimits` argument, a `RecordingTool` whose queued `ToolExecution` values are deterministic, and distinct `call_id` values for every provider turn. Every test asserts both the final counters/reason and the exact lengths of `FakeModelClient.requests` and `RecordingTool.executions`:

| Test | Scripted input | Exact assertions |
| --- | --- | --- |
| `test_three_consecutive_model_errors_stop_before_fourth_request` | three `TransientModelError` actions followed by `ModelResponse(text="must not run")` | reason `CONSECUTIVE_MODEL_ERRORS`, model errors `3`, requests `3`, tool executions `0` |
| `test_model_success_resets_consecutive_model_errors` | transient error, valid one-tool response plus `ok` tool execution, transient error, text completion | status `COMPLETION_CANDIDATE`, reason `None`, model errors `0`, requests `4`, tool executions `1` |
| `test_three_identical_no_progress_results_stop_without_fourth_tool` | three responses with distinct IDs but identical tool name/arguments; the tool returns the same nonmutating result each time; a fourth response is queued | repetition `3`, reason `REPEATED_TOOL_CALL`, requests `3`, tool executions `3` |
| `test_different_result_resets_repetition` | two identical call/result pairs, then the same call arguments with a different output, then text completion | completion candidate, repetition `0`, requests `4`, executions `3` |
| `test_successful_mutation_resets_repetition` | two identical nonmutating pairs, then the same call whose `ok` result contains one `changed_path`, then text completion | completion candidate, repetition `0`, `mutation_index == 1`, requests `4`, executions `3` |
| `test_three_nonsecurity_tool_errors_stop` | three tool turns returning `error="ordinary failure"`; a fourth response is queued | reason `CONSECUTIVE_TOOL_ERRORS`, tool-error count `3`, executions `3`, requests `3` |
| `test_tool_success_resets_tool_error_counter` | two ordinary tool errors, one `ok` tool result, then text completion | completion candidate, tool-error count `0`, executions `3` |
| `test_three_security_rejections_use_security_reason` | three tool turns returning `rejected` with `error="security_rejected: denied"` | reason `CONSECUTIVE_SAFETY_REJECTIONS`, safety count `3`, generic tool-error count `0`, executions `3` |
| `test_fatal_model_error_stops_immediately_without_second_logical_call` | `FatalModelError("fatal")` then a queued text response | reason `FATAL_MODEL_ERROR`, exactly one logical request, zero tools |
| `test_empty_response_has_stable_reason` | `ModelResponse()` | reason `EMPTY_MODEL_RESPONSE`, exactly one request, zero tools |
| `test_keyboard_interrupt_carries_interrupted_state` | a purpose-built `InterruptingModelClient.complete` raises `KeyboardInterrupt` after recording the request | `pytest.raises(AgentInterrupted)` yields state status `INTERRUPTED`, reason `USER_INTERRUPTED`, one admitted request, zero tools |
| `test_system_exit_is_not_caught` | a purpose-built `ExitingModelClient.complete` raises `SystemExit(130)` after recording the request | `pytest.raises(SystemExit)` with `caught.value.code == 130`; no failed/interrupted state is fabricated |

The two purpose-built clients implement only `complete(ModelRequest) -> ModelResponse`; they are not inserted into `FakeModelClient`, whose approved scripted-outcome type remains `ModelResponse | ModelError`. Construct every tool response through existing `ToolCall`, `ToolExecution`, and `ToolResult` interfaces. Do not assert log text or private helper state.

- [ ] **Step 6: Run errors/repetition/interruption RED**

Run all explicit nodes added in Step 5. Expected: nonzero because formal counters and interruption state are absent.

- [ ] **Step 7: Implement deterministic observations and paired termination results**

Implement the locked mutually exclusive model/tool/safety counter rules, fingerprint comparison, mutation progress reset, immediate fatal/empty/context reasons, and `AgentInterrupted`. When stopping within a multi-call assistant turn, append one stable rejected result for every unexecuted call so `ModelRequest(messages=state.messages)` remains valid, but never dispatch those calls.

- [ ] **Step 8: Run complete Agent GREEN and Task 1–9 regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_messages.py tests\test_model.py tests\test_openai_client.py tests\tools tests\test_path_safety.py tests\test_command_safety.py -q
```

Expected: all exit 0. No test uses wall-clock sleep or network.

**Acceptance:** AgentRunner has one formal loop, checks before every operation, never makes an over-budget call, preserves paired history on mid-batch stop, and exposes stable provider-neutral reasons.

---

### Task 6: Combined context/budget behavior and final Task 10 verification

**Files:**

- Modify: `tests/test_context.py`
- Modify: `tests/test_agent_loop.py`
- Verify all Task 10 files; do not change Task 10 status from `进行中`.

**Interfaces:** No new production interface.

- [ ] **Step 1: Add combined RED tests**

Add tests proving:

1. A summary call consumes one logical and each physical retry attempt from the same run budget as the next main call.
2. If summary leaves no provider attempt, the main call is never sent and reason is `PROVIDER_ATTEMPT_LIMIT`.
3. If summary falls back after a model error and budget remains, main execution continues.
4. A normal uncompressed Task 9 continuation is passed through unchanged and remains replayable.
5. A compressed Task 9 continuation becomes empty before the next main request.
6. Completion text returned on the final permitted model attempt remains `COMPLETION_CANDIDATE`, while a tool response on the final permitted attempt executes permitted tools and stops before another model request.

- [ ] **Step 2: Run combined RED**

Run the six explicit nodes. Expected: any missing integration produces a focused nonzero result; a test-fixture or import error is not an acceptable RED.

- [ ] **Step 3: Implement only the minimum integration corrections**

Make no new abstraction. Correct only count synchronization, check placement, continuation assignment, or counter reset required by the failing test. If a correction requires changing a locked public interface, stop and request user approval.

- [ ] **Step 4: Run combined GREEN**

Run the six nodes again. Expected: all pass with exact request/tool counts.

- [ ] **Step 5: Run Task 10 focused suites**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_context.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_termination.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_model.py tests\test_openai_client.py -q
```

Expected: every command exits 0; report actual passed/failed/skipped/warning counts.

- [ ] **Step 6: Run each Task 1–9 component regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py tests\tools\test_write_tools.py -q
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\test_command_safety.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -q
```

Expected: all exit 0, including Windows process-tree and security tests; no permanent skip is added.

- [ ] **Step 7: Run the complete repository suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: exit 0 with fresh real totals.

- [ ] **Step 8: Audit interfaces and SDK isolation**

Run Python signature assertions for `ModelClient.complete`, `OpenAIResponsesClient.complete`, `ContextManager.prepare`, `TerminationPolicy.check`, and `AgentRunner.__init__`. Scan production imports and confirm OpenAI SDK appears only in `openai_client.py`. Confirm `messages.py` diff is empty and `ModelRequest`/`ModelResponse` fields did not change.

- [ ] **Step 9: Audit physical-attempt and continuation invariants**

Search for every `responses.create` call and confirm `claim_provider_attempt()` occurs on its direct execution path. Search for every `invoke_model` call and confirm both main and summary calls use the same run budget. Search `context.py` and logs/tests to confirm continuation payloads are never serialized or printed, and compressed results always use `continuation_items=()`.

- [ ] **Step 10: Audit deferred scope, dependencies, credentials, and test suppression**

Verify protected Task 8 tool/safety files and Task 11–13 modules are unchanged. Confirm no `VerificationGate`, validation evidence behavior, JSONL logger, final report, CLI wiring, framework, dependency addition, real key pattern, network call, unfinished marker, skip, or xfail was introduced.

- [ ] **Step 11: Check whitespace, status, and every changed line**

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff -- src\coding_agent\model.py src\coding_agent\openai_client.py src\coding_agent\state.py src\coding_agent\agent.py src\coding_agent\context.py src\coding_agent\termination.py tests\test_model.py tests\test_openai_client.py tests\test_agent_loop.py tests\test_context.py tests\test_termination.py TASKS.md
```

Expected: only locked files and the approved plan appear, no staged entry exists, Task 10 remains `进行中`, and every line is reviewed for off-by-one errors, leaked continuation, unsafe exception content, and later-task scope.

- [ ] **Step 12: Stop for user review**

Report all RED/GREEN commands and real results, final test totals, physical/logical call evidence, continuation lifecycle, priority matrix, security/dependency audits, modified files, and final status. Do not mark Task 10 complete or begin Task 11.

**Acceptance:** Task 10 and Task 1–9 suites are freshly green, all limits prevent the first disallowed operation, context remains structurally valid, Task 9 retries are globally counted, continuation is cleared exactly on compression, and the diff remains within scope.

---

## Final acceptance matrix

| Requirement | Evidence |
| --- | --- |
| Within budget does not compress | `test_context_at_exact_threshold_is_not_compressed` |
| Character/item threshold crossing compresses | strict boundary tests in `test_context.py` |
| Initial goal and newest eight turns retained | summary and turn-retention assertions |
| Calls/results retained or removed as groups | multi-result turn tests |
| No orphan `ToolResult` | malformed-history rejection plus post-termination `ModelRequest` reconstruction |
| Compression clears continuation | `test_compression_discards_active_and_summary_continuation` |
| Summary nine-field structure/order | exact summary JSON assertion |
| Deterministic same-input result | repeated equivalent-state comparison |
| Still over budget terminates | uncompressible/still-oversized tests |
| Logical call limit | generic budget and Agent precheck tests |
| Physical provider limit | Task 9 shared-budget two-attempt test |
| Task 9 retries share total budget | shared fake SDK call/delay assertions |
| Tool call limit | exact one-call boundary and paired unexecuted results |
| Runtime limit | injected fake-clock equality test |
| Repeated model errors | three-error/no-fourth-request test |
| Repeated tool errors | three-error/no-next-operation test |
| Success resets counters | model/tool success reset tests |
| Multiple reasons have stable priority | parameterized priority test |
| Model completion differs from failure | final-permitted completion-candidate test |
| User interruption remains safe | `AgentInterrupted` and uncaught `SystemExit` tests |
| No call after exhaustion | request/tool execution list lengths |
| Task 9 normal continuation unaffected | uncompressed continuation passthrough test |
| Compression summary failure degrades | summary failure matrix |
| Invalid history/context fails safely | internal-invariant and budget-error tests |
| No SDK leakage | production import scan and unchanged messages diff |
| Offline and deterministic | Fake clients, fake clock, socket/network scan |
| Task 8 unchanged | protected-file diff and security regressions |
| Task 11–13 deferred | forbidden-scope scan and changed-file review |
| Task 1–9 regression | explicit component commands and full suite |

## Design reconciliation and known staged boundaries

- The approved design counts summary calls and every retry attempt inside the 12-call model budget. The separate logical counter is diagnostic and has the same default ceiling; the physical ceiling becomes tighter whenever retry occurs.
- Task 9 requires additive code so retries can claim a shared budget, but its accepted `complete(ModelRequest) -> ModelResponse`, constructor, standalone three-attempt semantics, request mapping, continuation format, and errors remain unchanged. No Task 2 message interface changes.
- The approved design names verification command/source/exit code/index as summary invariants, but Task 11 owns those facts. Task 10 renders explicit null values plus the currently truthful status and mutation index; Task 11 may populate the same object without changing the nine-field summary contract.
- `ContextManager` does not use actual token usage because the approved design explicitly chooses the 60,000-character/24-item deterministic approximation and forbids a tokenizer dependency in the first version.
- Normal completion remains `COMPLETION_CANDIDATE`; Task 10 does not add `SUCCESS`. Task 11 alone decides verified success.
- No live API smoke test belongs to Task 10 acceptance.

## Plan self-review checklist

- Every requested context, termination, counting, continuation, interruption, and regression behavior maps to a named test or audit.
- Exact equality and first-disallowed-operation semantics are stated for characters, items, calls, attempts, tools, time, repetition, errors, and safety rejection.
- All public names and signatures are introduced once and reused consistently.
- `ModelClient.complete`, Task 2 message fields, Task 8 tools/safety, and Task 9 standalone behavior remain compatible.
- Summary continuation is discarded and active continuation is cleared atomically only after compression.
- Model, tool, and safety counter reset rules are mutually exclusive and deterministic.
- Task 11 verification, Task 12 logging/reporting, Task 13 integration/demo, and CLI wiring are absent.
- No new dependency, real credential, network test, framework, remote operation, or unapproved file appears.
- The plan contains no placeholder instruction or undefined production type.

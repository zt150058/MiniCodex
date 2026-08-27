# Minimal Explicit Agent Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILLS: Use `superpowers:executing-plans` and `superpowers:test-driven-development` step by step, then use `superpowers:verification-before-completion`. This plan forbids subagents and worktrees.

**Goal:** Implement the Task 4 synchronous `AgentRunner`, explicit `AgentState`, and provider-neutral in-memory tool boundary so scripted model responses can request ordered tools, receive paired results, and finish only as `COMPLETION_CANDIDATE`.

**Architecture:** Use the approved thin-runner design. `AgentRunner` is the only top-level state-transition entry; it owns an explicit bounded `while` loop and returns the resulting `AgentState`. `ToolRegistry` owns registration, schema ordering, dispatch, `call_id` pairing, and conversion of unknown tools, invalid arguments, and tool exceptions into `ToolResult`. Individual tools validate their own arguments and signal bad input with `ToolArgumentError`. Tests use only `FakeModelClient`, `tmp_path`, and in-memory fake tools.

**Tech Stack:** Python 3.11+, standard library (`dataclasses`, `enum.StrEnum`, `pathlib`, `typing.Protocol`), pytest, Windows-first `src/` layout.

**Spec:** `DESIGN.md` sections 4–7, 9, 10, 12, 15–18; `TASKS.md` Task 4; existing public contracts in `src/coding_agent/messages.py` and `src/coding_agent/model.py`.

## Global constraints

- Work only on Task 4: `AgentState`, the minimal synchronous `AgentRunner`, the tool protocol/result boundary, `ToolRegistry`, and offline tests.
- Do not implement real filesystem tools, Shell execution, safety policy, OpenAI API mapping, model retry policy, context compaction, formal termination policy, mutation tracking, verification, logging, reporting, CLI wiring, or Task 5+ behavior.
- Reuse `ModelClient`, `FakeModelClient`, `ModelRequest`, `ModelResponse`, `ToolCall`, `ToolResult`, `ToolResultMetadata`, `Message`, and `JSONObject`; do not redefine them.
- `AgentRunner.run(task: str) -> AgentState` returns the state directly. It never returns or creates `SUCCESS`.
- Tools execute sequentially in model-response order. No async code, concurrent execution, planner, agent framework, or provider SDK type is allowed.
- Bad arguments are validated by the tool and expressed as `ToolArgumentError`; the registry maps that exception to `status="rejected"`.
- The temporary `max_rounds` bound must be a positive integer. Reaching it returns `FAILED` with `failure_reason="round_limit_exceeded"`.
- No dependency changes, network calls, API-key reads, subagents, worktrees, staging, commits, pushes, or remote operations.
- During execution, keep Task 4 `进行中` until the user reviews real verification evidence.

## Public interface contract

Create these interfaces without altering Task 2 or Task 3 modules.

### `src/coding_agent/state.py`

```python
class AgentStatus(StrEnum):
    RUNNING = "running"
    COMPLETION_CANDIDATE = "completion_candidate"
    FAILED = "failed"


@dataclass(slots=True)
class AgentState:
    task: str
    current_goal: str
    messages: tuple[Message, ...]
    open_issues: tuple[str, ...] = ()
    status: AgentStatus = AgentStatus.RUNNING
    model_call_count: int = 0
    tool_call_count: int = 0
    completion_text: str | None = None
    failure_reason: str | None = None
    continuation_items: tuple[object, ...] = field(
        default=(), repr=False
    )

    @classmethod
    def start(cls, task: str) -> AgentState: ...
```

Invariants:

- `start()` constructs and validates the initial `UserMessage`; the original task becomes both `task` and `current_goal`.
- `messages` is a tuple so each `ModelRequest` receives an immutable history snapshot.
- `open_issues` exists for the approved lightweight planning state but Task 4 does not ask the model to populate it.
- `completion_text` is populated only when status becomes `COMPLETION_CANDIDATE`.
- `failure_reason` is populated only when status becomes `FAILED`.
- No `SUCCESS`, validation state, mutation index, retry counter, or formal termination reason is introduced.

### `src/coding_agent/tools/base.py`

```python
@dataclass(frozen=True, slots=True)
class ExecutionContext:
    workspace: Path


@dataclass(frozen=True, slots=True)
class ToolExecution:
    output: str | None = None
    metadata: ToolResultMetadata = field(default_factory=ToolResultMetadata)


class ToolArgumentError(ValueError):
    """A tool rejected model-supplied arguments before execution."""


class Tool(Protocol):
    name: str
    schema: JSONObject

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution: ...
```

`ExecutionContext` carries the already-normalized workspace identity needed by later tools, but Task 4 tools do not read or write it. `ToolExecution` deliberately omits `call_id`, tool name, and status so only `ToolRegistry` can construct the paired `ToolResult`.

### `src/coding_agent/tools/registry.py`

```python
class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None: ...
    def register(self, tool: Tool) -> None: ...

    @property
    def schemas(self) -> tuple[JSONObject, ...]: ...

    def execute(
        self,
        call: ToolCall,
        context: ExecutionContext,
    ) -> ToolResult: ...
```

Registry invariants:

- Registration order determines `schemas` order.
- Duplicate tool names raise `ValueError("duplicate tool name: <name>")`.
- Unknown tool: `rejected`, error prefix `unknown_tool:`.
- `ToolArgumentError`: `rejected`, error prefix `invalid_arguments:`.
- Other `Exception`: `error`, error prefix `tool_execution_failed:`; no traceback is placed in the result.
- The registry always copies `call.call_id` and `call.name` into the result.

### `src/coding_agent/agent.py`

```python
class AgentRunner:
    def __init__(
        self,
        *,
        model_client: ModelClient,
        tool_registry: ToolRegistry,
        execution_context: ExecutionContext,
        max_rounds: int = 12,
    ) -> None: ...

    def run(self, task: str) -> AgentState: ...
```

Loop contract:

1. Initialize `AgentState` with exactly one `UserMessage`.
2. Before each model call, return `FAILED/round_limit_exceeded` if `model_call_count >= max_rounds`.
3. Build `ModelRequest` from the complete tuple history, registry schemas, and current opaque continuation items.
4. Increment `model_call_count`, call `ModelClient.complete`, then replace the state's continuation tuple with the response tuple without inspecting it.
5. If tool calls exist, append one `AssistantMessage` containing the optional nonblank text and all ordered calls; execute every call sequentially; append every result; increment `tool_call_count`; then continue.
6. If there are no tool calls and text is nonblank, append the assistant text, set `COMPLETION_CANDIDATE`, save `completion_text`, and return.
7. If neither usable text nor tool calls exists, return `FAILED/empty_model_response` rather than raising or spinning.
8. Task 4 does not catch or retry Task 3 `ModelError` types; that policy remains deferred to Tasks 9 and 10.

## File map

- Create: `src/coding_agent/state.py`
- Create: `src/coding_agent/agent.py`
- Create: `src/coding_agent/tools/base.py`
- Create: `src/coding_agent/tools/registry.py`
- Create: `tests/test_agent_loop.py`
- Modify during execution only: `TASKS.md` status lines for completed Task 3 and in-progress Task 4.
- Inspect only: `src/coding_agent/messages.py`, `src/coding_agent/model.py`, `tests/test_messages.py`, `tests/test_model.py`, `pyproject.toml`, `AGENTS.md`, and `DESIGN.md`.

---

### Task 0: Reconcile execution status and preflight the approved baseline

**Files:**
- Modify during execution: `TASKS.md`
- Inspect: `AGENTS.md`, `DESIGN.md`, `TASKS.md`, `docs/superpowers/plans/Task4.md`

- [ ] **Step 1: Confirm the correct repository, branch, commit, and clean tree**

Run from `D:\code\coding_agent`:

```powershell
git rev-parse --show-toplevel
git status --short
git log -3 --oneline
```

Expected:

- Top level is `D:/code/coding_agent`.
- `git status --short` is empty if the user committed the approved plan, or
  lists only `?? docs/superpowers/plans/Task4.md` if the approved plan remains
  untracked.
- The latest history includes the user-reviewed Task 3 commit.

If any change other than the approved plan is present, the plan is
absent/unapproved, or Task 3 is not committed, stop and report the exact
conflict.

- [ ] **Step 2: Correct only the workflow status lines**

Use `apply_patch` to change Task 3 from `进行中` to `已完成` and Task 4 from `未开始` to `进行中`. Do not change goals, acceptance criteria, ordering, or later-task states.

Run:

```powershell
git diff -- TASKS.md
```

Expected: exactly those two status-line changes and exactly one `进行中` task.

**Acceptance:** execution starts from the approved baseline with Task 3 accurately completed and Task 4 as the sole active task.

---

### Task 1: Explicit state and direct completion candidate

**Files:**
- Create: `tests/test_agent_loop.py`
- Create: `src/coding_agent/state.py`
- Create: `src/coding_agent/agent.py`
- Create directory and files: `src/coding_agent/tools/base.py`, `src/coding_agent/tools/registry.py`

#### Step 1: Write the first failing tests

Create `tests/test_agent_loop.py` with these imports, helper, and tests:

```python
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess
import sys

import pytest

from coding_agent.agent import AgentRunner
from coding_agent.messages import (
    AssistantMessage,
    JSONObject,
    ModelResponse,
    ToolCall,
    ToolResult,
    ToolResultMetadata,
    UserMessage,
)
from coding_agent.model import FakeModelClient
from coding_agent.state import AgentStatus
from coding_agent.tools.base import (
    ExecutionContext,
    ToolArgumentError,
    ToolExecution,
)
from coding_agent.tools.registry import ToolRegistry


def _runner(
    tmp_path: Path,
    responses: tuple[ModelResponse, ...],
    *,
    tools: tuple[object, ...] = (),
    max_rounds: int = 12,
) -> tuple[AgentRunner, FakeModelClient]:
    client = FakeModelClient(responses)
    runner = AgentRunner(
        model_client=client,
        tool_registry=ToolRegistry(tools),  # type: ignore[arg-type]
        execution_context=ExecutionContext(workspace=tmp_path),
        max_rounds=max_rounds,
    )
    return runner, client


def test_direct_text_returns_completion_candidate(tmp_path: Path) -> None:
    runner, client = _runner(
        tmp_path,
        (ModelResponse(text="implementation is ready for verification"),),
    )

    state = runner.run("repair the failing test")

    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert state.completion_text == "implementation is ready for verification"
    assert state.failure_reason is None
    assert state.task == "repair the failing test"
    assert state.current_goal == "repair the failing test"
    assert state.open_issues == ()
    assert state.model_call_count == 1
    assert state.tool_call_count == 0
    assert state.messages == (
        UserMessage("repair the failing test"),
        AssistantMessage(content="implementation is ready for verification"),
    )
    assert len(client.requests) == 1
    assert client.requests[0].messages == (UserMessage("repair the failing test"),)
    assert state.status.value != "success"


@pytest.mark.parametrize("max_rounds", [0, -1, True])
def test_runner_rejects_invalid_round_limit(
    tmp_path: Path,
    max_rounds: object,
) -> None:
    with pytest.raises(ValueError, match="max_rounds must be a positive integer"):
        AgentRunner(
            model_client=FakeModelClient(()),
            tool_registry=ToolRegistry(),
            execution_context=ExecutionContext(workspace=tmp_path),
            max_rounds=max_rounds,  # type: ignore[arg-type]
        )
```

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q --basetemp .\.pytest_cache\task4-red-1
```

Expected: nonzero collection failure because `coding_agent.agent`, `coding_agent.state`, and tool modules do not exist. The failure must be missing Task 4 modules, not a syntax problem or prior-test regression.

#### Step 2: Implement only state, constructor validation, and text completion

Create `src/coding_agent/state.py` with the exact public fields specified above. Implement `AgentState.start()` as:

```python
@classmethod
def start(cls, task: str) -> AgentState:
    user_message = UserMessage(task)
    return cls(
        task=user_message.content,
        current_goal=user_message.content,
        messages=(user_message,),
    )
```

Create `src/coding_agent/tools/base.py` with `ExecutionContext`, `ToolExecution`, `ToolArgumentError`, and `Tool` exactly as defined in the public contract. Create `src/coding_agent/tools/registry.py` with ordered registration and the `schemas` property; `execute()` may initially raise `RuntimeError("tool execution is unavailable")` because no tool-call test exists yet.

Create `src/coding_agent/agent.py` with constructor validation and a bounded loop. The initial tool-call branch may raise the same explicit `RuntimeError`; the text-only branch must append an `AssistantMessage`, set `COMPLETION_CANDIDATE`, and return. The loop must check `max_rounds` before every model call even though the round-limit behavior is tested in Task 2 below.

Run GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q --basetemp .\.pytest_cache\task4-green-1
```

Expected: exit `0`, `4 passed` because the parameterized invalid-limit test has three cases.

Run regression:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py -q --basetemp .\.pytest_cache\task4-regression-1
```

Expected: exit `0`, existing Task 2 and Task 3 tests all pass.

**Acceptance:** direct text becomes a completion candidate, never success; state exposes the approved fields; invalid bounds are rejected; no tool behavior, API, verification, or context policy is implemented.

---

### Task 2: Successful tool turns, ordered execution, history pairing, and round cap

**Files:**
- Modify: `tests/test_agent_loop.py`
- Modify: `src/coding_agent/agent.py`
- Modify: `src/coding_agent/tools/registry.py`

#### Step 1: Add in-memory tool helpers and failing tests

Append these helpers above the tests:

```python
@dataclass(slots=True)
class EchoTool:
    executed: list[tuple[str, Path]] = field(default_factory=list)
    name: str = field(default="echo", init=False)
    schema: JSONObject = field(
        default_factory=lambda: {
            "name": "echo",
            "description": "Return the supplied text.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
        },
        init=False,
    )

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        if set(arguments) != {"text"} or not isinstance(arguments["text"], str):
            raise ToolArgumentError("text must be the only argument and be a string")
        text = arguments["text"]
        self.executed.append((text, context.workspace))
        return ToolExecution(output=text)


@dataclass(slots=True)
class ExplodingTool:
    name: str = field(default="explode", init=False)
    schema: JSONObject = field(
        default_factory=lambda: {
            "name": "explode",
            "description": "Raise a deterministic test exception.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
        init=False,
    )

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        raise RuntimeError("boom")
```

Append these tests:

```python
def test_tool_result_is_paired_and_written_to_next_request(tmp_path: Path) -> None:
    marker = object()
    call = ToolCall(call_id="call_1", name="echo", arguments={"text": "hello"})
    tool = EchoTool()
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(call,), continuation_items=(marker,)),
            ModelResponse(text="done"),
        ),
        tools=(tool,),
    )

    state = runner.run("use the tool")

    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert state.model_call_count == 2
    assert state.tool_call_count == 1
    assert tool.executed == [("hello", tmp_path)]
    assert client.requests[0].tool_schemas == (tool.schema,)
    second_request = client.requests[1]
    assert second_request.continuation_items == (marker,)
    assert second_request.messages[1] == AssistantMessage(
        content=None,
        tool_calls=(call,),
    )
    result = second_request.messages[2]
    assert isinstance(result, ToolResult)
    assert result == ToolResult(
        call_id="call_1",
        tool_name="echo",
        status="ok",
        output="hello",
    )


def test_multiple_tools_execute_in_response_order_across_rounds(
    tmp_path: Path,
) -> None:
    tool = EchoTool()
    first = ToolCall(call_id="call_1", name="echo", arguments={"text": "first"})
    second = ToolCall(call_id="call_2", name="echo", arguments={"text": "second"})
    third = ToolCall(call_id="call_3", name="echo", arguments={"text": "third"})
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(first, second)),
            ModelResponse(tool_calls=(third,)),
            ModelResponse(text="all calls complete"),
        ),
        tools=(tool,),
    )

    state = runner.run("execute in order")

    assert [text for text, _ in tool.executed] == ["first", "second", "third"]
    assert state.tool_call_count == 3
    assert state.model_call_count == 3
    assert [
        message.call_id
        for message in client.requests[1].messages
        if isinstance(message, ToolResult)
    ] == ["call_1", "call_2"]
    assert [
        message.call_id
        for message in client.requests[2].messages
        if isinstance(message, ToolResult)
    ] == ["call_1", "call_2", "call_3"]


def test_text_with_tool_calls_is_preserved_without_ending_early(
    tmp_path: Path,
) -> None:
    call = ToolCall(call_id="call_1", name="echo", arguments={"text": "inspect"})
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(text="I will inspect first.", tool_calls=(call,)),
            ModelResponse(text="inspection complete"),
        ),
        tools=(EchoTool(),),
    )

    state = runner.run("inspect")

    assert len(client.requests) == 2
    assert client.requests[1].messages[1] == AssistantMessage(
        content="I will inspect first.",
        tool_calls=(call,),
    )
    assert state.completion_text == "inspection complete"


def test_round_limit_returns_failed_state(tmp_path: Path) -> None:
    calls = tuple(
        ToolCall(call_id=f"call_{index}", name="echo", arguments={"text": str(index)})
        for index in (1, 2)
    )
    runner, client = _runner(
        tmp_path,
        tuple(ModelResponse(tool_calls=(call,)) for call in calls),
        tools=(EchoTool(),),
        max_rounds=2,
    )

    state = runner.run("never completes")

    assert state.status is AgentStatus.FAILED
    assert state.failure_reason == "round_limit_exceeded"
    assert state.completion_text is None
    assert state.model_call_count == 2
    assert state.tool_call_count == 2
    assert len(client.requests) == 2


def test_registry_rejects_duplicate_tool_name() -> None:
    with pytest.raises(ValueError, match="duplicate tool name: echo"):
        ToolRegistry((EchoTool(), EchoTool()))
```

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q --basetemp .\.pytest_cache\task4-red-2
```

Expected: the four tool-loop tests fail because the initial implementation
deliberately has no tool execution, and the duplicate-name test fails because
registration does not yet reject a duplicate. Existing direct-completion and
constructor tests remain green.

#### Step 2: Implement generic successful tool execution

In `ToolRegistry.execute()`:

1. Make `register()` raise `ValueError(f"duplicate tool name: {tool.name}")`
   before changing the registry when the name already exists.
2. Look up the tool without mutating registry order.
3. For a registered tool, call `tool.execute(call.arguments, context)`.
4. Construct `ToolResult(status="ok")` with the original call ID and name.

Do not add error catching yet; that is the next RED/GREEN cycle.

In `AgentRunner.run()` implement the loop contract exactly. Normalize response text for `AssistantMessage` with:

```python
assistant_text = (
    response.text
    if response.text is not None and response.text.strip()
    else None
)
```

For a tool response, append the assistant message first, then execute calls in a normal `for` loop and append each returned result. Construct the next `ModelRequest` only after the `for` loop so Task 2 sequence validation sees no unresolved call. Store `response.continuation_items` without serializing or logging it.

Run GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q --basetemp .\.pytest_cache\task4-green-2
```

Expected: exit `0`, `9 passed`.

Run regression:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py -q --basetemp .\.pytest_cache\task4-regression-2
```

Expected: exit `0`; Task 2 pairing rules and Task 3 fake behavior remain unchanged.

**Acceptance:** tool calls are sequential and ordered, every result is paired and present in the next request, combined text does not finish early, schemas retain registration order, opaque continuation items are forwarded, and the temporary hard cap returns a failed state.

---

### Task 3: Structured unknown-tool, bad-argument, and tool-exception results

**Files:**
- Modify: `tests/test_agent_loop.py`
- Modify: `src/coding_agent/tools/registry.py`

#### Step 1: Add the three failing error-path tests

Append:

```python
def test_unknown_tool_becomes_rejected_result(tmp_path: Path) -> None:
    call = ToolCall(call_id="call_missing", name="missing", arguments={})
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="recovered")),
    )

    state = runner.run("call an unknown tool")

    result = client.requests[1].messages[2]
    assert isinstance(result, ToolResult)
    assert result.call_id == "call_missing"
    assert result.tool_name == "missing"
    assert result.status == "rejected"
    assert result.error == "unknown_tool: no tool registered as 'missing'"
    assert state.status is AgentStatus.COMPLETION_CANDIDATE


def test_bad_arguments_become_rejected_result(tmp_path: Path) -> None:
    tool = EchoTool()
    call = ToolCall(call_id="call_bad", name="echo", arguments={"text": 7})
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="recovered")),
        tools=(tool,),
    )

    state = runner.run("send invalid arguments")

    result = client.requests[1].messages[2]
    assert isinstance(result, ToolResult)
    assert result.status == "rejected"
    assert result.error == (
        "invalid_arguments: text must be the only argument and be a string"
    )
    assert tool.executed == []
    assert state.status is AgentStatus.COMPLETION_CANDIDATE


def test_tool_exception_becomes_error_result_without_traceback(
    tmp_path: Path,
) -> None:
    call = ToolCall(call_id="call_boom", name="explode", arguments={})
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="recovered")),
        tools=(ExplodingTool(),),
    )

    state = runner.run("exercise failure handling")

    result = client.requests[1].messages[2]
    assert isinstance(result, ToolResult)
    assert result.status == "error"
    assert result.error == "tool_execution_failed: RuntimeError: boom"
    assert "Traceback" not in result.error
    assert state.status is AgentStatus.COMPLETION_CANDIDATE
```

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q --basetemp .\.pytest_cache\task4-red-3
```

Expected: the unknown tool raises or fails lookup, and tool argument/runtime exceptions escape; the three new tests therefore fail for the intended missing registry error conversion.

#### Step 2: Implement deterministic error conversion

Implement `ToolRegistry.execute()` in this order:

```python
tool = self._tools.get(call.name)
if tool is None:
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.name,
        status="rejected",
        error=f"unknown_tool: no tool registered as {call.name!r}",
    )

try:
    execution = tool.execute(call.arguments, context)
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.name,
        status="ok",
        output=execution.output,
        metadata=execution.metadata,
    )
except ToolArgumentError as exc:
    detail = str(exc).strip() or "invalid arguments"
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.name,
        status="rejected",
        error=f"invalid_arguments: {detail}",
    )
except Exception as exc:
    detail = str(exc).strip() or "no detail"
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.name,
        status="error",
        error=f"tool_execution_failed: {type(exc).__name__}: {detail}",
    )
```

Catch `Exception`, not `BaseException`, so interrupts are not swallowed. Do not add retries, safety authorization, logging, traceback text, or provider-specific error handling.

Run GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q --basetemp .\.pytest_cache\task4-green-3
```

Expected: exit `0`, `12 passed`.

Run regression:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py -q --basetemp .\.pytest_cache\task4-regression-3
```

Expected: exit `0`, no Task 2 or Task 3 regressions.

**Acceptance:** all three tool failure classes become paired structured results, the loop continues to the next scripted model response, and no unhandled tool exception or traceback crosses the registry boundary.

---

### Task 4: Empty model response and offline boundary

**Files:**
- Modify: `tests/test_agent_loop.py`
- Modify: `src/coding_agent/agent.py`

#### Step 1: Add the failing empty-response test

Append:

```python
def test_empty_model_response_returns_failed_state(tmp_path: Path) -> None:
    runner, client = _runner(tmp_path, (ModelResponse(),))

    state = runner.run("handle empty response")

    assert state.status is AgentStatus.FAILED
    assert state.failure_reason == "empty_model_response"
    assert state.completion_text is None
    assert state.model_call_count == 1
    assert state.tool_call_count == 0
    assert state.messages == (UserMessage("handle empty response"),)
    assert len(client.requests) == 1
```

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py::test_empty_model_response_returns_failed_state -q --basetemp .\.pytest_cache\task4-red-4
```

Expected: nonzero because the current direct-text path cannot produce an `AssistantMessage` from empty text or does not return the required failed state.

#### Step 2: Add the minimal empty-response transition

After the tool-call and nonblank-text branches, set:

```python
state.status = AgentStatus.FAILED
state.failure_reason = "empty_model_response"
return state
```

Run GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q --basetemp .\.pytest_cache\task4-green-4
```

Expected: exit `0`, `13 passed`.

#### Step 3: Add and run the offline import boundary test

Append:

```python
def test_agent_and_tools_import_without_openai_or_api_key() -> None:
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "openai" or name.startswith("openai."):
        raise AssertionError("Task 4 imported OpenAI SDK")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import coding_agent.agent
import coding_agent.state
import coding_agent.tools.base
import coding_agent.tools.registry
"""
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py::test_agent_and_tools_import_without_openai_or_api_key -q --basetemp .\.pytest_cache\task4-offline
```

Expected: exit `0`, `1 passed`. This is a boundary audit rather than new production behavior; it must pass without implementation changes.

Run Task 4 GREEN again:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q --basetemp .\.pytest_cache\task4-green-final
```

Expected: exit `0`, `14 passed`.

**Acceptance:** empty responses terminate explicitly, and all Task 4 modules import without OpenAI SDK access, API keys, or network behavior.

---

### Task 5: Verification, requirement audit, and user review gate

**Files:**
- Inspect: `src/coding_agent/state.py`
- Inspect: `src/coding_agent/agent.py`
- Inspect: `src/coding_agent/tools/base.py`
- Inspect: `src/coding_agent/tools/registry.py`
- Inspect: `tests/test_agent_loop.py`
- Inspect: `TASKS.md`, `pyproject.toml`, `docs/superpowers/plans/Task4.md`

Use `superpowers:verification-before-completion` before reporting any passing or completion claim.

- [ ] **Step 1: Run the Task 4 suite from a fresh ignored temp base**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q --basetemp .\.pytest_cache\task4-verify
```

Expected: exit `0`, `14 passed`, no skipped tests. Report the actual count, duration, warnings, and exit code.

- [ ] **Step 2: Run all repository tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp .\.pytest_cache\task4-all
```

Expected: exit `0`; the current 63 tests plus 14 Task 4 tests yield
approximately `77 passed`. Treat this count as an estimate and report only the
real output. If a Windows temporary-directory permission error occurs, use
`superpowers:systematic-debugging`; do not describe partial results as success.

- [ ] **Step 3: Verify public signatures and Task 2/3 type reuse**

```powershell
.\.venv\Scripts\python.exe -c "import inspect; from typing import get_type_hints; import coding_agent.agent as a; import coding_agent.messages as m; import coding_agent.model as model; import coding_agent.state as s; import coding_agent.tools.base as b; import coding_agent.tools.registry as r; assert tuple(inspect.signature(a.AgentRunner.run).parameters)==('self','task'); assert get_type_hints(a.AgentRunner.run)=={'task':str,'return':s.AgentState}; assert get_type_hints(model.ModelClient.complete)=={'request':m.ModelRequest,'return':m.ModelResponse}; assert tuple(inspect.signature(r.ToolRegistry.execute).parameters)==('self','call','context'); assert get_type_hints(r.ToolRegistry.execute)=={'call':m.ToolCall,'context':b.ExecutionContext,'return':m.ToolResult}; print('task-4 interface contract verified')"
```

Expected: exit `0` and `task-4 interface contract verified`.

- [ ] **Step 4: Prove Task 2/3 public types were not redefined**

```powershell
.\.venv\Scripts\python.exe -c "import ast,pathlib; paths=[pathlib.Path('src/coding_agent/state.py'),pathlib.Path('src/coding_agent/agent.py'),pathlib.Path('src/coding_agent/tools/base.py'),pathlib.Path('src/coding_agent/tools/registry.py')]; forbidden={'ModelClient','FakeModelClient','ModelRequest','ModelResponse','ToolCall','ToolResult','ToolResultMetadata','Message','JSONObject'}; defined=set(); [defined.update(node.name for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))) if isinstance(node,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef))) for path in paths]; assert not defined.intersection(forbidden),defined.intersection(forbidden); print('task-2 and task-3 types are reused')"
```

Expected: exit `0` and `task-2 and task-3 types are reused`.

- [ ] **Step 5: Audit forbidden scope and dependencies**

```powershell
Select-String -Path .\src\coding_agent\state.py,.\src\coding_agent\agent.py,.\src\coding_agent\tools\base.py,.\src\coding_agent\tools\registry.py -Pattern 'import openai|from openai|OPENAI_API_KEY|OpenAI\(|subprocess|os\.system|async def|Thread|ProcessPool|AgentRunner.*SUCCESS|VerificationGate|ContextManager|TerminationPolicy|run_command|read_file|write_file|replace_text|list_directory'

.\.venv\Scripts\python.exe -c "import pathlib,tomllib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); assert d['project']['dependencies']==['openai']; assert d['project']['optional-dependencies']['test']==['pytest']; print('approved dependencies only')"
```

Expected:

- Static scan prints no matches.
- Dependency check exits `0` and prints `approved dependencies only`.
- No real tool module, SDK adapter, context manager, termination policy, or verification gate exists because of Task 4.

- [ ] **Step 6: Scan for credentials without printing matches**

```powershell
$secretPatterns = @(
    'sk-[A-Za-z0-9_-]{20,}',
    'Bearer\s+[A-Za-z0-9._-]{20,}'
)
$files = Get-ChildItem .\src, .\tests, .\docs -Recurse -File |
    Where-Object { $_.Extension -in '.py', '.md', '.toml', '.txt' }
$hitPaths = $files | Select-String -Pattern $secretPatterns |
    Select-Object -ExpandProperty Path -Unique
if ($hitPaths) { $hitPaths; exit 1 }
Write-Output 'no credential-like values found'
```

Expected: exit `0`, `no credential-like values found`. Only paths may be printed on failure, never matching text.

- [ ] **Step 7: Check placeholders, skipped tests, temporary code, and diff quality**

```powershell
$sourceMarkers = @(
    ('T' + 'BD'),
    ('T' + 'ODO'),
    ('NotImplemented' + 'Error'),
    ('tool execution is ' + 'unavailable'),
    ('implement' + ' later'),
    ('pass' + '  #'),
    ('pytest' + '.skip'),
    ('pytest' + '.mark.skip'),
    ('添加' + '适当测试'),
    ('处理' + '错误情况'),
    ('完善' + '配置'),
    ('实现' + '相关逻辑')
)
$sourcePaths = @(
    '.\src\coding_agent\state.py',
    '.\src\coding_agent\agent.py',
    '.\src\coding_agent\tools\base.py',
    '.\src\coding_agent\tools\registry.py',
    '.\tests\test_agent_loop.py'
)
$sourceMatches = Select-String -Path $sourcePaths -Pattern $sourceMarkers
if ($sourceMatches) { $sourceMatches; exit 1 }

$planMarkers = @(
    ('T' + 'BD'),
    ('T' + 'ODO'),
    ('implement' + ' later'),
    ('fill' + ' in details'),
    ('添加' + '适当测试'),
    ('处理' + '错误情况'),
    ('完善' + '配置'),
    ('实现' + '相关逻辑')
)
$planMatches = Select-String -Path .\docs\superpowers\plans\Task4.md -Pattern $planMarkers
if ($planMatches) { $planMatches; exit 1 }
Write-Output 'no placeholders, skips, or temporary branches found'

git diff --check
git status --short
git diff -- TASKS.md src/coding_agent/state.py src/coding_agent/agent.py src/coding_agent/tools/base.py src/coding_agent/tools/registry.py tests/test_agent_loop.py docs/superpowers/plans/Task4.md
```

Expected:

- Marker scan exits `0` with the stated message.
- `git diff --check` exits `0` with no whitespace errors.
- Status/diff contains only the approved plan, two Task status changes, four Task 4 production modules, and `tests/test_agent_loop.py`.
- No unrelated source, dependency, generated artifact, API key, or later-task implementation appears.

- [ ] **Step 8: Perform the Task 4 acceptance matrix**

| Task 4 requirement | Required evidence |
| --- | --- |
| `AgentRunner` is the top-level transition entry | Direct-return tests plus AST/diff inspection; tools return only `ToolResult` and never mutate `AgentState` |
| Direct text completion | `test_direct_text_returns_completion_candidate` |
| Only `COMPLETION_CANDIDATE`, never `SUCCESS` | Direct completion assertions and source scan |
| One-round tool call | `test_tool_result_is_paired_and_written_to_next_request` |
| Multi-round calls | `test_multiple_tools_execute_in_response_order_across_rounds` |
| Multiple tools sequentially | Execution-order assertion in the same test |
| Results included in next request | Second- and third-request history assertions |
| Exact `call_id` pairing | Paired-result equality and all error-result assertions |
| Text plus tools | `test_text_with_tool_calls_is_preserved_without_ending_early` |
| Unknown tool structured rejection | `test_unknown_tool_becomes_rejected_result` |
| Bad arguments structured rejection | `test_bad_arguments_become_rejected_result` |
| Tool exception structured error | `test_tool_exception_becomes_error_result_without_traceback` |
| Explicit temporary round cap | Limit constructor tests and `test_round_limit_returns_failed_state` |
| Duplicate tool names are deterministic | `test_registry_rejects_duplicate_tool_name` |
| Empty response cannot spin | `test_empty_model_response_returns_failed_state` |
| Fully offline | Fresh-process import test, static scan, dependency audit |
| No Task 5+ implementation | File list, forbidden-scope scan, and diff review |

If any row lacks real passing evidence, keep Task 4 `进行中`, report the gap, and stop.

- [ ] **Step 9: Wait for user review and authorization**

Report:

- Each RED command, nonzero exit code, and expected missing behavior.
- Each GREEN command, exit code, and real pass count.
- Task 4 targeted and full-suite verification results.
- Signature, type-reuse, dependency, offline, credential, placeholder, skip, diff, and scope-audit results.
- Every failure, warning, skip, or unverified fact explicitly.

Do not mark Task 4 `已完成`, stage, commit, push, or contact a remote. The suggested future commit message is `feat: implement minimal explicit agent loop`, but execution must stop for user review and authorization.

## Plan self-check

- Every Task 4 acceptance criterion maps to a named test or deterministic audit.
- Test and implementation names are consistent: `AgentRunner`, `AgentState`, `AgentStatus`, `ExecutionContext`, `ToolExecution`, `ToolArgumentError`, and `ToolRegistry`.
- Every production behavior has a preceding RED test and a following GREEN command; the offline test is explicitly a boundary audit.
- The plan does not modify Task 2/3 public interfaces or define replacement message/model types.
- The plan contains no real file tool, Shell tool, OpenAI client, API call, retry policy, context compression, formal termination policy, verification gate, logging, or CLI integration.
- All loops have an explicit bound, all tool failures have structured results, and no success is claimed before future verification.
- No dependency, subagent, worktree, commit, push, remote operation, or secret use is introduced.
- Execution stops after verification for user review.

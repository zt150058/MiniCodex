# ModelClient and FakeModelClient Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILLS: Use `superpowers:executing-plans` and `superpowers:test-driven-development` to execute this plan step by step. This plan explicitly forbids subagents and worktrees.

**Goal:** Define the provider-neutral synchronous `ModelClient` protocol and a deterministic, fully offline `FakeModelClient` for later Agent-loop and context-summary tests.

**Architecture:** Add one focused model-boundary module that imports the existing Task 2 request and response types rather than redefining them. The fake consumes an in-memory FIFO script of `ModelResponse` or typed model-error instances, records every received `ModelRequest`, and either returns or raises the next scripted outcome without retries, parsing, networking, credentials, or provider SDK code.

**Tech Stack:** Python 3.11+, standard library (`collections.deque`, `collections.abc.Iterable`, `typing.Protocol`), pytest, Windows-first `src/` layout.

**Spec:** `DESIGN.md` sections 4, 5, 8, 11, 12, 16, and 17; `TASKS.md` Task 3; existing public types in `src/coding_agent/messages.py`.

## Global Constraints

- Work only on Task 3: `ModelClient`, `FakeModelClient`, their model-error test doubles, and tests.
- Do not implement the Agent loop, `AgentState`, `ToolRegistry`, tool execution, OpenAI Responses API mapping, retries, context compaction, or verification behavior.
- Reuse `ModelRequest`, `ModelResponse`, and `ToolCall` from `coding_agent.messages`; do not redefine or wrap them.
- `ModelClient.complete` is synchronous with the exact signature `complete(self, request: ModelRequest) -> ModelResponse`.
- Default tests remain fully offline: no real API call, API key read, OpenAI client construction, or OpenAI SDK type import.
- Add no dependency. Production dependencies remain `openai`; test dependencies remain `pytest`.
- Do not create a worktree, dispatch a subagent, stage, commit, push, or contact a remote repository.
- Keep Task 3 marked `进行中` until the user reviews the implementation and explicitly accepts it.

---

## Public Interface Contract

Create these names in `src/coding_agent/model.py`:

```python
@runtime_checkable
class ModelClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...


class ModelError(RuntimeError):
    """Base class for model-call failures exposed across the client boundary."""


class TransientModelError(ModelError):
    """A retryable model failure such as timeout, 429, or 5xx."""


class FatalModelError(ModelError):
    """A non-retryable model failure such as authentication or configuration."""


class FakeModelExhaustedError(AssertionError):
    """Raised when a test invokes the fake after its script is exhausted."""


ScriptedOutcome: TypeAlias = ModelResponse | ModelError


class FakeModelClient:
    def __init__(self, outcomes: Iterable[ScriptedOutcome]) -> None: ...

    @property
    def requests(self) -> tuple[ModelRequest, ...]: ...

    def complete(self, request: ModelRequest) -> ModelResponse: ...
```

Contract details and invariants:

- `outcomes` is consumed into a private `deque` at construction, so generators and other finite iterables are supported deterministically.
- Each scripted item must already be either a Task 2 `ModelResponse` or a `ModelError`; any other item raises `TypeError` during construction with its zero-based index.
- `complete()` appends the exact `ModelRequest` object to the internal request log before inspecting the outcome queue. Calls that raise a scripted error or exhaustion are therefore still recorded.
- A `ModelResponse` is returned unchanged. This preserves text, ordered tool calls, usage, provider ID, and opaque continuation items without interpreting them.
- A `ModelError` instance is removed from the queue and raised unchanged. The fake performs no retry; retry policy belongs to later tasks.
- An empty queue raises `FakeModelExhaustedError`, not `ModelError`, because exhaustion is a deterministic test-script defect rather than a provider failure.
- `requests` returns an immutable tuple snapshot in receipt order. The fake retains its own private mutable list.
- A context-summary response is represented by an ordinary `ModelResponse`, usually with structured JSON in `text`. Task 3 does not parse, validate, or generate summaries.

## File Map

- Create: `src/coding_agent/model.py` — protocol, model-error taxonomy, scripted-outcome alias, and deterministic fake.
- Create: `tests/test_model.py` — protocol/signature, successful response shapes, FIFO/request capture, exhaustion, errors, constructor validation, and offline boundary tests.
- Modify during execution only for workflow status: `TASKS.md` — reconcile the already-completed Task 2 status and mark Task 3 `进行中`; no acceptance text or architecture changes.
- Inspect only: `src/coding_agent/messages.py`, `pyproject.toml`, `AGENTS.md`, and `DESIGN.md`.

---

### Task 0: Reconcile execution status before production changes

**Files:**
- Modify: `TASKS.md`

**Interfaces:**
- Consumes: the user's explicit statement that Task 2 was completed, verified, and committed.
- Produces: one accurate in-progress task before Task 3 implementation begins.

The committed baseline currently says Task 2 is `进行中` and Task 3 is `未开始`. This discrepancy must be visible during approval. Execute this status-only change only after the user approves this plan.

- [ ] **Step 1: Confirm the committed baseline and clean worktree**

Run:

```powershell
git status --short
git log -1 --oneline
Select-String -Path .\TASKS.md -Pattern '^## 2\.|^## 3\.|`进行中`|`未开始`|`已完成`'
```

Expected:

- `git status --short` has no project changes before execution begins.
- Latest commit is the user's Task 2 commit.
- The scan confirms the stale Task 2/Task 3 status values described above.

- [ ] **Step 2: Change only the two status values**

In `TASKS.md`:

```markdown
## 2. 消息数据结构
...
**当前状态**

`已完成`

## 3. `ModelClient` 抽象和 `FakeModelClient`
...
**当前状态**

`进行中`
```

Do not change any task goal, acceptance criterion, test requirement, ordering, or later-task status.

- [ ] **Step 3: Verify the status-only diff**

Run:

```powershell
git diff -- TASKS.md
```

Expected: exactly two status-line changes: Task 2 `进行中` to `已完成`, and Task 3 `未开始` to `进行中`.

**Acceptance:** `TASKS.md` has exactly one `进行中` item and authorizes no production behavior beyond Task 3.

---

### Task 1: Protocol, successful scripted outcomes, request capture, and exhaustion

**Files:**
- Create: `tests/test_model.py`
- Create: `src/coding_agent/model.py`

**Interfaces:**
- Consumes: `coding_agent.messages.ModelRequest`, `ModelResponse`, `ToolCall`, and `UserMessage` exactly as implemented in Task 2.
- Produces: `ModelClient`, `ModelError`, `FakeModelExhaustedError`, `ScriptedOutcome`, and the successful-response behavior of `FakeModelClient`.

- [ ] **Step 1: Write the complete failing test slice**

Create `tests/test_model.py` with this exact content:

```python
from __future__ import annotations

import inspect
import os
import subprocess
import sys
from typing import get_type_hints

import pytest

from coding_agent.messages import (
    ModelRequest,
    ModelResponse,
    ToolCall,
    UserMessage,
)
from coding_agent.model import (
    FakeModelClient,
    FakeModelExhaustedError,
    ModelClient,
    ModelError,
)


def _request(content: str) -> ModelRequest:
    return ModelRequest(messages=(UserMessage(content),))


TEXT_RESPONSE = ModelResponse(text="done")
SINGLE_TOOL_RESPONSE = ModelResponse(
    tool_calls=(
        ToolCall(
            call_id="call_1",
            name="read_file",
            arguments={"path": "src/example.py"},
        ),
    )
)
MULTI_TOOL_RESPONSE = ModelResponse(
    tool_calls=(
        ToolCall(
            call_id="call_1",
            name="read_file",
            arguments={"path": "a.py"},
        ),
        ToolCall(
            call_id="call_2",
            name="read_file",
            arguments={"path": "b.py"},
        ),
    )
)
COMBINED_RESPONSE = ModelResponse(
    text="I will inspect both files.",
    tool_calls=MULTI_TOOL_RESPONSE.tool_calls,
)
SUMMARY_RESPONSE = ModelResponse(
    text=(
        '{"goal":"repair failing tests",'
        '"open_issues":["identify the failing assertion"]}'
    )
)


def test_model_client_protocol_uses_task_2_types() -> None:
    client = FakeModelClient(())

    assert isinstance(client, ModelClient)
    assert tuple(inspect.signature(ModelClient.complete).parameters) == (
        "self",
        "request",
    )
    assert tuple(inspect.signature(FakeModelClient).parameters) == ("outcomes",)
    assert get_type_hints(ModelClient.complete) == {
        "request": ModelRequest,
        "return": ModelResponse,
    }


def test_fake_model_returns_scripted_responses_and_records_requests() -> None:
    first_request = _request("first")
    second_request = _request("second")
    first_response = ModelResponse(text="first result")
    second_response = ModelResponse(text="second result")
    client = FakeModelClient((first_response, second_response))

    assert client.complete(first_request) is first_response
    assert client.complete(second_request) is second_response
    assert client.requests == (first_request, second_request)


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(TEXT_RESPONSE, id="text"),
        pytest.param(SINGLE_TOOL_RESPONSE, id="single-tool-call"),
        pytest.param(MULTI_TOOL_RESPONSE, id="multiple-tool-calls"),
        pytest.param(COMBINED_RESPONSE, id="text-and-tool-calls"),
        pytest.param(SUMMARY_RESPONSE, id="context-summary"),
    ],
)
def test_fake_model_supports_successful_response_shapes(
    response: ModelResponse,
) -> None:
    request = _request("scripted request")
    client = FakeModelClient((response,))

    returned = client.complete(request)

    assert returned is response
    assert returned == response
    assert client.requests == (request,)


def test_fake_model_preserves_multiple_tool_call_order() -> None:
    client = FakeModelClient((MULTI_TOOL_RESPONSE,))

    returned = client.complete(_request("inspect in order"))

    assert tuple(call.call_id for call in returned.tool_calls) == (
        "call_1",
        "call_2",
    )
    assert tuple(call.arguments["path"] for call in returned.tool_calls) == (
        "a.py",
        "b.py",
    )


def test_fake_model_exhaustion_is_explicit_and_records_request() -> None:
    first_request = _request("first")
    exhausted_request = _request("unexpected second call")
    client = FakeModelClient((ModelResponse(text="only response"),))

    client.complete(first_request)

    with pytest.raises(
        FakeModelExhaustedError,
        match=r"no scripted outcome.*request #2",
    ):
        client.complete(exhausted_request)

    assert client.requests == (first_request, exhausted_request)


def test_fake_model_rejects_invalid_script_item_at_construction() -> None:
    invalid = object()

    with pytest.raises(TypeError, match=r"outcome 1.*ModelResponse or ModelError"):
        FakeModelClient((ModelResponse(text="valid"), invalid))  # type: ignore[arg-type]


def test_fake_model_raises_scripted_base_error_and_records_request() -> None:
    request = _request("scripted base error")
    error = ModelError("scripted model failure")
    client = FakeModelClient((error,))

    with pytest.raises(ModelError, match="scripted model failure") as caught:
        client.complete(request)

    assert caught.value is error
    assert client.requests == (request,)


def test_model_module_imports_offline_without_openai_or_api_key() -> None:
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "openai" or name.startswith("openai."):
        raise AssertionError("coding_agent.model imported OpenAI SDK")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import coding_agent.model
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

The five parameter IDs explicitly cover pure text, one tool call, multiple ordered tool calls, combined text/tool calls, and a context-summary response. The summary is an opaque response to the fake; no summary semantics are implemented here.

- [ ] **Step 2: Run the new slice and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_model.py -q
```

Expected: pytest exits nonzero during collection with `ModuleNotFoundError: No module named 'coding_agent.model'`. This is the expected reason: the test references the approved Task 3 module before it exists. Do not weaken or skip any test.

**Acceptance for RED:** the failure is import absence, not a Task 1/Task 2 regression, syntax error in the test, network attempt, or missing API key.

- [ ] **Step 3: Write the minimal successful-outcome implementation**

Create `src/coding_agent/model.py` with this exact content:

```python
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Protocol, TypeAlias, runtime_checkable

from coding_agent.messages import ModelRequest, ModelResponse


@runtime_checkable
class ModelClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...


class ModelError(RuntimeError):
    """Base class for failures crossing the model-client boundary."""


class FakeModelExhaustedError(AssertionError):
    """Raised when a fake client receives more requests than scripted outcomes."""


ScriptedOutcome: TypeAlias = ModelResponse | ModelError


class FakeModelClient:
    def __init__(self, outcomes: Iterable[ScriptedOutcome]) -> None:
        scripted = tuple(outcomes)
        for index, outcome in enumerate(scripted):
            if not isinstance(outcome, (ModelResponse, ModelError)):
                raise TypeError(
                    f"outcome {index} must be ModelResponse or ModelError"
                )
        self._outcomes: deque[ScriptedOutcome] = deque(scripted)
        self._requests: list[ModelRequest] = []

    @property
    def requests(self) -> tuple[ModelRequest, ...]:
        return tuple(self._requests)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self._requests.append(request)
        if not self._outcomes:
            raise FakeModelExhaustedError(
                "FakeModelClient has no scripted outcome "
                f"for request #{len(self._requests)}"
            )

        outcome = self._outcomes.popleft()
        if isinstance(outcome, ModelError):
            raise outcome
        return outcome
```

Important boundaries:

- Import the two Task 2 classes directly; do not add alternate request/response definitions.
- Do not import `openai`, `os`, HTTP libraries, credential configuration, `AgentRunner`, or context code.
- Do not clone or serialize a returned response. Returning the exact object proves the fake preserves opaque continuation items and ordered calls.
- Do not add retry logic. A scripted error is consumed once and raised once.

- [ ] **Step 4: Run the Task 1 slice and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_model.py -q
```

Expected: exit code `0`, with `12 passed`. The provider-boundary subprocess must pass without an API key and while refusing OpenAI imports.

**Acceptance:**

- The exact protocol signature resolves to the existing `ModelRequest` and `ModelResponse` classes.
- FIFO responses and all five successful response shapes are returned unchanged.
- Multiple calls retain response order and request-record order.
- Exhaustion is explicit and records the triggering request.
- Invalid script items fail during construction.
- No provider SDK or credential is touched.

---

### Task 2: Transient and fatal scripted model errors

**Files:**
- Modify: `tests/test_model.py`
- Modify: `src/coding_agent/model.py`

**Interfaces:**
- Consumes: `ModelError` and `FakeModelClient` from Task 1.
- Produces: `TransientModelError` and `FatalModelError`, both usable as scripted outcomes and distinguishable by later policy code.

- [ ] **Step 1: Add the failing error test**

Extend the `coding_agent.model` import in `tests/test_model.py` to exactly:

```python
from coding_agent.model import (
    FakeModelClient,
    FakeModelExhaustedError,
    FatalModelError,
    ModelClient,
    ModelError,
    TransientModelError,
)
```

Append this test:

```python
def test_fake_model_replays_transient_and_fatal_errors_in_order() -> None:
    request = _request("retryable then fatal")
    transient = TransientModelError("temporary rate limit")
    recovery = ModelResponse(text="recovered")
    fatal = FatalModelError("invalid model configuration")
    client = FakeModelClient((transient, recovery, fatal))

    assert isinstance(transient, ModelError)
    assert isinstance(fatal, ModelError)

    with pytest.raises(TransientModelError, match="temporary rate limit") as caught:
        client.complete(request)
    assert caught.value is transient

    assert client.complete(request) is recovery

    with pytest.raises(FatalModelError, match="invalid model configuration") as caught:
        client.complete(request)
    assert caught.value is fatal

    assert client.requests == (request, request, request)
```

This test represents errors as exception instances in the same FIFO script as responses. It proves that an error consumes exactly one outcome, every failed call is recorded, the next outcome remains available, and callers can distinguish retryable from fatal failures without provider-specific exception types.

- [ ] **Step 2: Run the expanded suite and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_model.py -q
```

Expected: pytest exits nonzero during collection because `TransientModelError` and `FatalModelError` cannot yet be imported. The earlier 12 tests remain unchanged.

**Acceptance for RED:** the failure names the two missing Task 3 error types; it is not caused by network access, OpenAI SDK import, or changes to Task 2 types.

- [ ] **Step 3: Add the minimal error taxonomy**

Insert these classes immediately after `ModelError` in `src/coding_agent/model.py`:

```python
class TransientModelError(ModelError):
    """A retryable model failure such as timeout, 429, or 5xx."""


class FatalModelError(ModelError):
    """A non-retryable authentication, model, or request failure."""
```

No change to `FakeModelClient.complete()` is needed: both classes inherit `ModelError`, so the existing deterministic branch raises them unchanged. Do not add sleeps, backoff, retry counters, provider status-code mapping, or Agent termination behavior.

- [ ] **Step 4: Run the complete Task 3 suite and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_model.py -q
```

Expected: exit code `0`, with `13 passed`.

**Acceptance:** transient and fatal exceptions remain provider-neutral, preserve identity and message, consume one queue entry, record their requests, and permit the next scripted outcome to proceed.

- [ ] **Step 5: Run Task 2 regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py -q
```

Expected: exit code `0`, with the existing `30 passed`. No Task 2 message type or serialization behavior changes.

---

### Task 3: Final offline verification, interface audit, and scope gate

**Files:**
- Inspect: `src/coding_agent/model.py`
- Inspect: `tests/test_model.py`
- Inspect: `src/coding_agent/messages.py`
- Inspect: `pyproject.toml`
- Inspect: `TASKS.md`
- Inspect: `docs/superpowers/plans/2026-08-27-model-client-and-fake.md`

**Interfaces:**
- Verifies: all Task 3 public names and exact Task 2 type identity.
- Produces: evidence for user review; no new implementation behavior.

- [ ] **Step 1: Re-run the offline provider-boundary test alone**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_model.py::test_model_module_imports_offline_without_openai_or_api_key -q
```

Expected: exit code `0`, `1 passed`. The subprocess removes `OPENAI_API_KEY` and rejects any import whose name is `openai` or starts with `openai.`.

- [ ] **Step 2: Verify exact signatures, type identity, and error hierarchy**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import inspect; from typing import get_type_hints; import coding_agent.messages as messages; import coding_agent.model as model; h=get_type_hints(model.ModelClient.complete); assert tuple(inspect.signature(model.ModelClient.complete).parameters)==('self','request'); assert tuple(inspect.signature(model.FakeModelClient).parameters)==('outcomes',); assert h=={'request': messages.ModelRequest, 'return': messages.ModelResponse}; assert model.ModelRequest is messages.ModelRequest; assert model.ModelResponse is messages.ModelResponse; assert issubclass(model.TransientModelError, model.ModelError); assert issubclass(model.FatalModelError, model.ModelError); assert not issubclass(model.FakeModelExhaustedError, model.ModelError); print('task-3 interface contract verified')"
```

Expected: exit code `0` and `task-3 interface contract verified`.

- [ ] **Step 3: Prove Task 2 request and response types were not redefined**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import ast, pathlib; tree=ast.parse(pathlib.Path('src/coding_agent/model.py').read_text(encoding='utf-8')); defined={node.name for node in ast.walk(tree) if isinstance(node,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef))}; forbidden={'ModelRequest','ModelResponse','ToolCall'}; assert not defined.intersection(forbidden), defined.intersection(forbidden); print('task-2 types are imported, not redefined')"
```

Expected: exit code `0` and `task-2 types are imported, not redefined`.

- [ ] **Step 4: Audit provider neutrality, credentials, dependencies, and source scope**

Run:

```powershell
Select-String -Path .\src\coding_agent\model.py -Pattern 'import openai|from openai|OPENAI_API_KEY|OpenAI\(|(^|\s)import requests|(^|\s)from requests|urllib|httpx|socket|AgentRunner|ToolRegistry|OpenAIResponsesClient|ContextManager|VerificationGate'

.\.venv\Scripts\python.exe -c "import pathlib,tomllib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); assert d['project']['dependencies']==['openai']; assert d['project']['optional-dependencies']['test']==['pytest']; print('approved dependencies only')"

Get-ChildItem .\src\coding_agent -File | Select-Object -ExpandProperty Name
```

Expected:

- `Select-String` prints no matches.
- Dependency command exits `0` and prints `approved dependencies only`.
- Source listing adds only `model.py` beyond the committed Task 1 and Task 2 modules; it contains no `agent.py`, tool modules, `openai_client.py`, context module, or verification module created by this task.

Do not interpret the existing `openai` dependency in `pyproject.toml` as permission to import it in `model.py`; Task 3 remains provider-neutral and offline.

- [ ] **Step 5: Scan for credential-like values without printing contents**

Run:

```powershell
$secretPatterns = @(
    'sk-[A-Za-z0-9_-]{20,}',
    'Bearer\s+[A-Za-z0-9._-]{20,}'
)
$files = Get-ChildItem .\src, .\tests, .\docs -Recurse -File |
    Where-Object { $_.Extension -in '.py', '.md', '.toml', '.txt' }
$hits = $files | Select-String -Pattern $secretPatterns | Select-Object -ExpandProperty Path -Unique
if ($hits) { $hits; exit 1 }
Write-Output 'no credential-like values found'
```

Expected: exit code `0` and `no credential-like values found`. The command outputs paths only if it finds a suspicious value; it never prints a matched secret.

- [ ] **Step 6: Run the complete Task 3 suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_model.py -q
```

Expected: exit code `0`, `13 passed`. Record the real count, warnings, duration, and exit code instead of copying the estimate if execution differs.

- [ ] **Step 7: Run all repository tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit code `0`; the committed 50 Task 1/Task 2 cases plus 13 Task 3 cases yield `63 passed`. Report the actual result. If the result differs or Windows reports a temporary-directory permission error, invoke `superpowers:systematic-debugging`, diagnose the executing user's temp-directory ownership, and do not claim completion from partial evidence.

- [ ] **Step 8: Check plan placeholders, diff quality, and exact scope**

Run:

```powershell
$markers = @(
    ("T" + "BD"),
    ("T" + "ODO"),
    ("implement" + " later"),
    ("fill" + " in details"),
    ("添加" + "适当测试"),
    ("处理" + "错误情况"),
    ("完善" + "配置"),
    ("实现" + "相关逻辑")
)
$matches = Select-String -Path .\docs\superpowers\plans\2026-08-27-model-client-and-fake.md -Pattern $markers
if ($matches) { $matches; exit 1 }
Write-Output 'no placeholders found'

git diff --check
git status --short
```

Expected:

- Placeholder command exits `0` and prints `no placeholders found`.
- `git diff --check` exits `0` with no whitespace errors.
- Git status lists only `TASKS.md`, `src/coding_agent/model.py`, `tests/test_model.py`, and this approved plan, unless a separately identified pre-existing user change exists.
- No source or test from Tasks 4 through 11 exists because of this plan.

- [ ] **Step 9: Perform the requirement coverage review**

Check each item against a named test or audit result:

| Requirement | Evidence |
| --- | --- |
| Exact `ModelClient.complete(ModelRequest) -> ModelResponse` | `test_model_client_protocol_uses_task_2_types` and Step 2 signature audit |
| FIFO scripted queue | `test_fake_model_returns_scripted_responses_and_records_requests` |
| Request recording | Successful, exhaustion, and error tests inspect `requests` |
| Explicit exhaustion error | `test_fake_model_exhaustion_is_explicit_and_records_request` |
| Pure text | parameter ID `text` |
| Single tool call | parameter ID `single-tool-call` |
| Multiple ordered tool calls | parameter ID `multiple-tool-calls` plus explicit order test |
| Text plus tool calls | parameter ID `text-and-tool-calls` |
| Transient error | `test_fake_model_replays_transient_and_fatal_errors_in_order` |
| Fatal error | same error-order test, distinct exception class |
| Context summary | parameter ID `context-summary` |
| No real API, API key, SDK import, or OpenAI client | fresh-process boundary test plus static scope audit |
| Task 2 type reuse | protocol hints, identity assertions, and AST no-redefinition audit |
| No later-task implementation | source listing and banned-name scan |

If any evidence is missing or a command fails, keep Task 3 `进行中`, report the exact gap, and do not move to Task 4.

- [ ] **Step 10: Wait for user review and authorization**

Present to the user:

- Every RED command, its exit code, and the expected failure reason.
- Every GREEN command, its exit code, and real pass count.
- The full repository test result.
- Provider-boundary, dependency, type-identity, placeholder, credential, and scope-audit results.
- Any failed, skipped, or unverified check, clearly labeled.

Do not stage, commit, push, or mark Task 3 `已完成`. The suggested future commit message remains `feat: add model client protocol and fake client`, but only the user may authorize and perform or request that commit after review.

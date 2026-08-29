# Model Instructions and Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add immutable run instructions and real provider-neutral streaming for the existing Responses and Chat Completions adapters while preserving all verified synchronous behavior.

**Architecture:** `ModelRequest.instructions` remains separate from local history and is assembled once by a reparse-safe `RunInstructionBuilder`. A new `streaming.py` defines optional streaming protocols and one-logical-call fallback accounting; provider adapters parse SDK streams internally and expose only safe text/lifecycle events plus a final existing `ModelResponse`. The CLI keeps using synchronous completion until later lifecycle/GUI work supplies a stream handler.

**Tech Stack:** Python 3.11+, standard library, existing official `openai` package 3.5.0 interface, pytest, Windows-first path tests

**Spec:** `docs/superpowers/specs/2026-08-29-model-instructions-and-streaming-design.md`

## Global Constraints

- Execute in the current `main` workspace; do not create a branch or worktree.
- Do not stage, commit, push, pull, fetch, or contact a remote without new explicit authorization.
- Default tests are offline and must not read a real API key or contact any endpoint.
- Do not add a dependency, Agent framework, tokenizer, async runtime, thread, or process.
- Do not change the required `ModelClient.complete(ModelRequest) -> ModelResponse` protocol or either provider's existing public `complete` signature.
- Do not put partial tool calls into `ToolCall`, partial responses into `ModelResponse`, or provider objects into core types.
- Do not weaken Task 8 path safety, Task 10 budgets/context, Task 11 verification, or Task 12 redaction/audit behavior.
- Do not persist or log instruction bodies, streamed text, tool argument fragments, continuation, provider payloads, or encrypted reasoning.
- Summary model calls remain synchronous with `instructions=None`; only main calls receive run instructions.
- Only one `TASKS.md` task may be `进行中`; Task 18 stays `进行中` at the final user checkpoint.
- Any production change uses a RED test first, a minimal GREEN implementation second, and fresh regression tests third.
- User-authorized subagents may perform independent read-only audits or reviews; tightly coupled core edits stay inline and sequential.

---

## Locked File Map

**Create:**

- `src/coding_agent/instructions.py` — deterministic base/workspace/selected-Skill instruction snapshot.
- `src/coding_agent/streaming.py` — provider-neutral events, optional streaming protocols, fallback orchestration, and shared-budget invocation.
- `tests/test_instructions.py` — builder, safety, limit, determinism, and privacy tests.
- `tests/test_streaming.py` — protocol, lifecycle event, budget, fallback, and Agent integration tests.
- `tests/test_openai_streaming_client.py` — offline Responses stream parser/retry/continuation tests.
- `tests/test_chat_completions_streaming_client.py` — offline Chat chunk aggregation/retry tests.

**Modify:**

- `src/coding_agent/messages.py` — additive `ModelRequest.instructions` only.
- `src/coding_agent/model.py` — private active-logical complete helper; public synchronous interfaces unchanged.
- `src/coding_agent/agent.py` — immutable instructions and optional stream handler on main requests.
- `src/coding_agent/app.py` — build one production instruction snapshot; do not enable streaming in CLI.
- `src/coding_agent/openai_client.py` — conditional instructions plus Responses stream implementation.
- `src/coding_agent/chat_completions_client.py` — conditional provider-only system message plus Chat stream implementation.
- `tests/test_messages.py`
- `tests/test_model.py`
- `tests/test_agent_loop.py`
- `tests/test_app.py`
- `tests/test_openai_client.py`
- `tests/test_chat_completions_client.py`
- `tests/test_docs.py`
- `DESIGN.md`
- `TASKS.md`
- `docs/OPENAI_API.md`
- `docs/USAGE.md`

**Read-only/protected:**

- `src/coding_agent/state.py`
- `src/coding_agent/context.py`
- `src/coding_agent/config.py`
- `src/coding_agent/cli.py`
- `src/coding_agent/safety.py`
- `src/coding_agent/logging.py`
- `src/coding_agent/verification.py`
- `src/coding_agent/report.py`
- all files under `src/coding_agent/tools/`
- `pyproject.toml`
- Task 1–15 historical specs and plans

If a protected file must change, stop and request a design decision.

---

### Task 0: Baseline, Interface Lock, and Task Registration

**Files:**

- Read: `AGENTS.md`, `DESIGN.md`, `TASKS.md`, the Milestone A spec, this plan, all files in the locked file map, and current related tests.
- Modify after baseline only: `TASKS.md`

**Interfaces:**

- Consumes: Task 15 HEAD and the complete Task 1–15 offline suite.
- Produces: a clean verified baseline and Tasks 16–18 with exactly one active status.

- [ ] **Step 1: Verify repository identity and cleanliness**

Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git log -3 --oneline
git status --short --untracked-files=all
git diff --check
git rev-parse HEAD
```

Expected: root is `D:/code/coding_agent`, branch is `main`, and HEAD contains the approved Task 15 commit. Status is either empty or contains only the already approved Milestone A spec and plan paths; diff check prints no errors. Stop on any other unapproved path.

- [ ] **Step 2: Run the fresh Task 1–15 baseline**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Expected: exit 0, no failed or skipped tests. Record the actual count; the planning baseline was `850 passed`.

- [ ] **Step 3: Reconfirm locked public signatures**

Run:

```powershell
@'
import inspect
from coding_agent.messages import ModelRequest
from coding_agent.model import ModelClient
from coding_agent.openai_client import OpenAIResponsesClient
from coding_agent.chat_completions_client import ChatCompletionsModelClient
print(inspect.signature(ModelRequest))
print(inspect.signature(ModelClient.complete))
print(inspect.signature(OpenAIResponsesClient.complete))
print(inspect.signature(ChatCompletionsModelClient.complete))
'@ | .\.venv\Scripts\python.exe -
```

Expected before implementation: `ModelRequest` has no instructions field; all complete methods have only `self, request`; no provider protocol contains a required stream method.

- [ ] **Step 4: Register exact task statuses**

Append Tasks 16–18 before `## 任务完成规则` in `TASKS.md`, using the spec's goals and acceptance lists, and set:

```markdown
## 16. Run instructions 与根工作区 AGENTS.md
**当前状态**
`进行中`

## 17. Provider-neutral streaming 核心
**当前状态**
`未开始`

## 18. Responses 与 Chat Completions 流式适配
**当前状态**
`未开始`
```

Each section must include the matching scope, acceptance tests, and suggested commit text from the spec; it must not introduce Task 19 functionality.

Run:

```powershell
rg -n -A 3 "^## (16|17|18)\." TASKS.md
$active = (Select-String -Path TASKS.md -Pattern '^`进行中`$').Count
if ($active -ne 1) { throw "expected exactly one active task, found $active" }
Select-String -Path TASKS.md -Pattern '^`进行中`$' -Context 8,0
git diff --check
```

Expected: Tasks 16–18 exist, exactly Task 16 is active, and diff check exits 0.

---

### Task 1: Add the Provider-Neutral Instruction Field

**Files:**

- Modify: `src/coding_agent/messages.py`
- Modify: `tests/test_messages.py`

**Interfaces:**

- Consumes: the existing strict `ModelRequest` JSON contract.
- Produces: `ModelRequest(..., instructions: str | None = None)` with explicit JSON null/string and hidden repr.

- [ ] **Step 1: Write the failing instruction contract tests**

Add imports only if absent, then add:

```python
def test_model_request_instructions_are_explicit_roundtrip_and_repr_private() -> None:
    secret = "workspace instruction sentinel"
    request = ModelRequest(
        messages=(UserMessage("task"),),
        instructions=secret,
    )

    assert request.instructions == secret
    assert request.to_dict()["instructions"] == secret
    assert ModelRequest.from_json(request.to_json()) == request
    assert secret not in repr(request)

    without = ModelRequest(messages=(UserMessage("task"),))
    assert without.instructions is None
    assert without.to_dict()["instructions"] is None


@pytest.mark.parametrize("value", ["", "   ", 7, False])
def test_model_request_rejects_invalid_instructions(value: object) -> None:
    with pytest.raises(ValueError, match="instructions"):
        ModelRequest(
            messages=(UserMessage("task"),),
            instructions=value,  # type: ignore[arg-type]
        )
```

Update existing exact dictionary/JSON assertions to require the new key with `None`; do not relax exact-key validation.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py::test_model_request_instructions_are_explicit_roundtrip_and_repr_private tests\test_messages.py::test_model_request_rejects_invalid_instructions -q -p no:cacheprovider
```

Expected: nonzero exit because `ModelRequest.__init__` does not accept `instructions`.

- [ ] **Step 3: Implement the minimum additive field**

Use this exact field and validation pattern:

```python
@dataclass(frozen=True, slots=True)
class ModelRequest(_JsonMixin):
    messages: tuple[Message, ...]
    tool_schemas: tuple[JSONObject, ...] = ()
    max_output_tokens: int = 4096
    continuation_items: tuple[object, ...] = field(
        default=(), repr=False, compare=False
    )
    instructions: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # Preserve all existing checks first.
        if self.instructions is not None and (
            not isinstance(self.instructions, str)
            or not self.instructions.strip()
        ):
            raise ValueError("instructions must be a non-empty string or null")
```

Add `"instructions": self.instructions` to `to_dict`, require it in `from_dict`, and pass it to the constructor. Do not serialize `continuation_items`.

- [ ] **Step 4: Run GREEN and message/model regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py -q -p no:cacheprovider
```

Expected: exit 0; all selected tests pass. Existing `FakeModelClient.requests` automatically retains the exact instructions through the request object.

**Acceptance:** null/string JSON is strict and reversible, invalid values fail locally, repr is private, and no existing message/call-ID invariant changes.

---

### Task 2: Build One Safe Immutable Run Instruction Snapshot

**Files:**

- Create: `src/coding_agent/instructions.py`
- Create: `tests/test_instructions.py`
- Read only: `src/coding_agent/safety.py`

**Interfaces:**

- Consumes: `PathGuard(workspace).existing_file("AGENTS.md")` and an optional already-selected Skill string.
- Produces: the constants, `InstructionErrorCode`, `InstructionBuildError`, `RunInstructionSnapshot`, and `RunInstructionBuilder.build` exactly as specified.

- [ ] **Step 1: Write RED tests for composition, determinism, limits, and privacy**

Create `tests/test_instructions.py` with these core tests:

```python
from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from coding_agent.instructions import (
    MAX_AGENTS_FILE_BYTES,
    MAX_SKILL_INSTRUCTIONS_BYTES,
    InstructionBuildError,
    InstructionErrorCode,
    RunInstructionBuilder,
)


def _assert_code(
    code: InstructionErrorCode,
    operation: Callable[[], object],
) -> None:
    with pytest.raises(InstructionBuildError) as caught:
        operation()
    assert caught.value.code is code
    assert "AGENTS body sentinel" not in str(caught.value)
    assert "AGENTS body sentinel" not in repr(caught.value)


def test_builder_layers_sources_once_in_deterministic_order(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_bytes(
        b"\xef\xbb\xbfworkspace\r\ninstruction\r\n"
    )
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "AGENTS.md").write_text("must not load", encoding="utf-8")

    snapshot = RunInstructionBuilder().build(
        tmp_path,
        skill_instructions="skill\r\ninstruction",
    )

    assert snapshot.text.count("## MiniCodex base instructions") == 1
    assert snapshot.text.endswith(
        "## Workspace instructions (AGENTS.md)\n"
        "workspace\ninstruction\n\n"
        "## Selected skill instructions\nskill\ninstruction"
    )
    assert "must not load" not in snapshot.text
    assert snapshot.char_count == len(snapshot.text)
    assert snapshot.sha256 == hashlib.sha256(
        snapshot.text.encode("utf-8")
    ).hexdigest()
    assert "workspace" not in repr(snapshot)
    assert "skill" not in repr(snapshot)


def test_missing_and_blank_agents_files_are_normal(tmp_path: Path) -> None:
    missing = RunInstructionBuilder().build(tmp_path)
    (tmp_path / "AGENTS.md").write_text(" \r\n", encoding="utf-8")
    blank = RunInstructionBuilder().build(tmp_path)
    assert missing.text == blank.text
    assert "Workspace instructions" not in missing.text


def test_agents_file_exact_limit_is_allowed_and_next_byte_is_rejected(
    tmp_path: Path,
) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_bytes(b"x" * MAX_AGENTS_FILE_BYTES)
    assert "x" * 64 in RunInstructionBuilder().build(tmp_path).text
    target.write_bytes(b"x" * (MAX_AGENTS_FILE_BYTES + 1))
    _assert_code(
        InstructionErrorCode.AGENTS_FILE_TOO_LARGE,
        lambda: RunInstructionBuilder().build(tmp_path),
    )


def test_invalid_utf8_and_non_file_are_stable_errors(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_bytes(b"\xffAGENTS body sentinel")
    _assert_code(
        InstructionErrorCode.AGENTS_FILE_NOT_UTF8,
        lambda: RunInstructionBuilder().build(tmp_path),
    )
    target.unlink()
    target.mkdir()
    _assert_code(
        InstructionErrorCode.AGENTS_FILE_UNSAFE,
        lambda: RunInstructionBuilder().build(tmp_path),
    )


@pytest.mark.parametrize("value", ["", "  ", 9, False])
def test_skill_instructions_must_be_nonempty_text(
    tmp_path: Path,
    value: object,
) -> None:
    _assert_code(
        InstructionErrorCode.SKILL_INSTRUCTIONS_INVALID,
        lambda: RunInstructionBuilder().build(
            tmp_path,
            skill_instructions=value,  # type: ignore[arg-type]
        ),
    )


def test_skill_utf8_byte_limit(tmp_path: Path) -> None:
    allowed = "界" * (MAX_SKILL_INSTRUCTIONS_BYTES // 3) + "x"
    assert len(allowed.encode("utf-8")) == MAX_SKILL_INSTRUCTIONS_BYTES
    RunInstructionBuilder().build(tmp_path, skill_instructions=allowed)
    _assert_code(
        InstructionErrorCode.SKILL_INSTRUCTIONS_TOO_LARGE,
        lambda: RunInstructionBuilder().build(
            tmp_path,
            skill_instructions=allowed + "x",
        ),
    )
```

Add Windows-real symlink/reparse tests using the same non-skipping helper contract as `tests/test_path_safety.py`: create `<workspace>/AGENTS.md` as a file symlink to an outside file and require `AGENTS_FILE_UNSAFE`; mark an ordinary file with `stat.FILE_ATTRIBUTE_REPARSE_POINT` through `coding_agent.safety.os.lstat` and require the same code. Add an `OSError` read monkeypatch and require `AGENTS_FILE_UNREADABLE` with no path/body in the exception.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_instructions.py -q -p no:cacheprovider
```

Expected: collection fails because `coding_agent.instructions` does not exist. Confirm the missing module is the only cause.

- [ ] **Step 3: Implement the builder without bypassing `PathGuard`**

Create the locked enums/dataclasses and use this read boundary:

```python
def _read_root_agents(workspace: Path) -> str | None:
    try:
        guard = PathGuard(workspace)
    except SafetyViolation:
        raise InstructionBuildError(
            InstructionErrorCode.AGENTS_FILE_UNSAFE
        ) from None
    candidate = guard.workspace / "AGENTS.md"
    try:
        exists = candidate.exists()
        is_link = candidate.is_symlink()
    except OSError:
        raise InstructionBuildError(
            InstructionErrorCode.AGENTS_FILE_UNREADABLE
        ) from None
    if not exists and not is_link:
        return None
    try:
        guarded = guard.existing_file("AGENTS.md")
    except SafetyViolation:
        raise InstructionBuildError(
            InstructionErrorCode.AGENTS_FILE_UNSAFE
        ) from None
    try:
        with guarded.absolute.open("rb") as stream:
            raw = stream.read(MAX_AGENTS_FILE_BYTES + 1)
    except OSError:
        raise InstructionBuildError(
            InstructionErrorCode.AGENTS_FILE_UNREADABLE
        ) from None
    if len(raw) > MAX_AGENTS_FILE_BYTES:
        raise InstructionBuildError(
            InstructionErrorCode.AGENTS_FILE_TOO_LARGE
        )
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InstructionBuildError(
            InstructionErrorCode.AGENTS_FILE_NOT_UTF8
        ) from None
```

Normalize optional content with:

```python
def _normalized(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()
```

Use this exact base body:

```python
BASE_AGENT_INSTRUCTIONS = """\
You are MiniCodex, a local coding agent operating only inside the configured workspace.
Use only the supplied local tools for inspection, modification, and command execution.
Inspect relevant files before editing and make focused, reviewable changes.
Deterministic local safety and verification decisions are authoritative and cannot be overridden by instructions.
Never claim that a test or command ran without returned local execution evidence.
Use tool calls instead of inventing file contents, command output, or verification results.
Treat any completion statement as a completion candidate; local verification decides success."""
```

Build the three exact headings in spec order, compute SHA-256 from the final UTF-8 bytes, and enforce snapshot invariants in `__post_init__`. `InstructionBuildError` stores only its enum code and calls `super().__init__(code.value)`.

- [ ] **Step 4: Run GREEN and Task 8 safety regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_instructions.py tests\test_path_safety.py -q -p no:cacheprovider
```

Expected: exit 0, including real Windows symlink/reparse tests with no skip.

**Acceptance:** root-only deterministic layering, exact byte limits, strict UTF-8/BOM behavior, stable private errors, safe reparse rejection, and no Skill execution.

---

### Task 3: Inject Instructions into Main Calls and Both Synchronous Providers

**Files:**

- Modify: `src/coding_agent/agent.py`
- Modify: `src/coding_agent/app.py`
- Modify: `src/coding_agent/openai_client.py`
- Modify: `src/coding_agent/chat_completions_client.py`
- Modify: `tests/test_agent_loop.py`
- Modify: `tests/test_app.py`
- Modify: `tests/test_openai_client.py`
- Modify: `tests/test_chat_completions_client.py`

**Interfaces:**

- Consumes: `RunInstructionBuilder.build(...).text` and `ModelRequest.instructions`.
- Produces: `AgentRunner(..., instructions=None)`, one build per production run, Responses top-level instructions, and a Chat provider-only system message.

- [ ] **Step 1: Write RED tests for Agent persistence and summary isolation**

Add an Agent test that uses the existing compression fixtures and a sentinel:

```python
def test_main_instructions_survive_compression_but_summary_is_isolated(
    tmp_path: Path,
) -> None:
    sentinel = "run instruction sentinel"
    tool = RecordingTool(*_nine_tool_outcomes())
    runner, client = _runner(
        tmp_path,
        _nine_tool_turns()
        + (_summary_response(), ModelResponse(text="candidate")),
        tools=(tool,),
        context_limits=_compression_limits(),
        instructions=sentinel,
    )

    runner.run("repair")

    assert len(client.requests) == 11
    assert client.requests[9].messages[0].content.startswith(
        "Summarize the provider-neutral"
    )
    assert client.requests[9].instructions is None
    assert all(
        request.instructions == sentinel
        for index, request in enumerate(client.requests)
        if index != 9
    )
```

Extend the existing `_runner` helper with `instructions: str | None = None` and pass that keyword to `AgentRunner`; do not duplicate Agent construction.

- [ ] **Step 2: Write RED provider mapping tests**

Responses:

```python
def test_responses_maps_instructions_conditionally() -> None:
    sdk = FakeSDKClient(text_response("ok"), text_response("ok"))
    client = OpenAIResponsesClient(model="test", api_key="not-real", sdk_client=sdk)

    client.complete(ModelRequest(messages=(UserMessage("one"),)))
    client.complete(
        ModelRequest(
            messages=(UserMessage("two"),),
            instructions="system sentinel",
        )
    )

    assert "instructions" not in sdk.responses.calls[0]
    assert sdk.responses.calls[1]["instructions"] == "system sentinel"
```

Chat:

```python
def test_chat_maps_instructions_to_one_provider_only_system_message() -> None:
    sdk = FakeSDKClient(
        chat_response(content="ok"),
        chat_response(content="ok"),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )

    client.complete(ModelRequest(messages=(UserMessage("one"),)))
    client.complete(
        ModelRequest(
            messages=(UserMessage("two"),),
            instructions="system sentinel",
        )
    )

    assert sdk.chat.completions.calls[0]["messages"] == [
        {"role": "user", "content": "one"}
    ]
    assert sdk.chat.completions.calls[1]["messages"][:2] == [
        {"role": "system", "content": "system sentinel"},
        {"role": "user", "content": "two"},
    ]
```

- [ ] **Step 3: Write RED application composition/privacy test**

Use existing `tests/test_app.py` fake factories, create root `AGENTS.md`, run a one-response fake, and assert its first request contains both the base heading and file sentinel. Monkeypatch `RunInstructionBuilder.build` with a counting wrapper and assert one call. Read the generated JSONL and assert the sentinel is absent.

- [ ] **Step 4: Run the three RED groups**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -k instructions -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py tests\test_chat_completions_client.py -k instructions -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_app.py -k instructions -q -p no:cacheprovider
```

Expected: nonzero exits because AgentRunner and provider mapping do not yet carry instructions.

- [ ] **Step 5: Implement minimum Agent and app wiring**

Add to `AgentRunner.__init__`:

```python
instructions: str | None = None,
```

Validate with the same null/non-empty rule, store it in a repr-inaccessible private attribute, and set `instructions=self._instructions` only on the main request at the current `ModelRequest(...)` call site. Do not modify `ContextManager`.

In `run_application`, after logger creation and inside the existing construction error boundary:

```python
instruction_snapshot = RunInstructionBuilder().build(config.workspace)
runner = AgentRunner(
    model_client=model_client,
    tool_registry=registry,
    execution_context=execution_context,
    context_manager=context_manager,
    termination_policy=termination_policy,
    clock=selected.clock,
    verification_gate=verification_gate,
    event_sink=logger,
    instructions=instruction_snapshot.text,
)
```

Do not add the snapshot to log metadata or report JSON.

- [ ] **Step 6: Implement conditional provider mappings**

Responses request kwargs:

```python
if request.instructions is not None:
    request_kwargs["instructions"] = request.instructions
```

Chat mapping starts with:

```python
mapped: list[dict[str, object]] = []
if request.instructions is not None:
    mapped.append({"role": "system", "content": request.instructions})
```

Then retain the exact existing local-history loop. Do not add a core `SystemMessage`.

- [ ] **Step 7: Run GREEN and Task 9/10/12/15 regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py tests\test_app.py tests\test_openai_client.py tests\test_chat_completions_client.py tests\test_context.py tests\test_logging.py tests\integration\test_chat_completions_agent.py -q -p no:cacheprovider
```

Expected: exit 0; exact no-instructions request tests remain unchanged, summary calls have null instructions, logs omit instruction bodies, and both adapters map a non-null value correctly.

- [ ] **Step 8: Close Task 16 and activate Task 17**

Run the Task 16 focused suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_instructions.py tests\test_agent_loop.py tests\test_app.py tests\test_openai_client.py tests\test_chat_completions_client.py tests\test_path_safety.py -q -p no:cacheprovider
```

If exit 0, change only Task 16 to `已完成` and Task 17 to `进行中`; Task 18 remains `未开始`. Verify exactly one active status with `rg` and run `git diff --check`.

---

### Task 4: Add Streaming Events, Optional Protocols, and Shared-Budget Fallback

**Files:**

- Create: `src/coding_agent/streaming.py`
- Modify: `src/coding_agent/model.py`
- Create: `tests/test_streaming.py`
- Modify: `tests/test_model.py`

**Interfaces:**

- Consumes: unchanged `ModelClient`, `BudgetAwareModelClient`, `ModelCallBudget`, and `ModelResponse`.
- Produces: exact Task 17 interfaces from the spec and private `_complete_with_active_budget` reuse.

- [ ] **Step 1: Write RED event/protocol tests**

Create `tests/test_streaming.py` with:

```python
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from coding_agent.messages import ModelRequest, ModelResponse, UserMessage
from coding_agent.model import (
    FakeModelClient,
    ModelCallBudget,
    ModelClient,
    ModelError,
)
from coding_agent.streaming import (
    ModelStreamEvent,
    ModelStreamEventKind,
    StreamInterruptedError,
    StreamingModelClient,
    StreamingUnsupportedError,
    invoke_model_stream,
)


def request() -> ModelRequest:
    return ModelRequest(messages=(UserMessage("stream"),))


@dataclass(frozen=True, slots=True)
class StreamScript:
    deltas: tuple[str, ...]
    outcome: ModelResponse | BaseException


class ScriptedStreamingClient:
    def __init__(
        self,
        streams: tuple[StreamScript, ...],
        *,
        complete_outcomes: tuple[ModelResponse | BaseException, ...] = (),
    ) -> None:
        self._streams = deque(streams)
        self._complete_outcomes = deque(complete_outcomes)
        self.stream_calls = 0
        self.complete_calls = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.complete_calls += 1
        outcome = self._complete_outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def complete_with_budget(
        self,
        request: ModelRequest,
        budget: ModelCallBudget,
    ) -> ModelResponse:
        index = budget.begin_provider_attempt(budget.active_purpose)
        try:
            response = self.complete(request)
        except Exception:
            budget.finish_provider_attempt(
                budget.active_purpose,
                index,
                error_code="provider_error",
                retry_scheduled=False,
                retry_delay_ms=None,
            )
            raise
        budget.finish_provider_attempt(
            budget.active_purpose,
            index,
            error_code=None,
            retry_scheduled=False,
            retry_delay_ms=None,
        )
        return response

    def stream(
        self,
        request: ModelRequest,
        emit: Callable[[ModelStreamEvent], None],
    ) -> ModelResponse:
        self.stream_calls += 1
        script = self._streams.popleft()
        for delta in script.deltas:
            emit(ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, delta))
        if isinstance(script.outcome, BaseException):
            raise script.outcome
        return script.outcome

    def stream_with_budget(
        self,
        request: ModelRequest,
        budget: ModelCallBudget,
        emit: Callable[[ModelStreamEvent], None],
    ) -> ModelResponse:
        index = budget.begin_provider_attempt(budget.active_purpose)
        try:
            response = self.stream(request, emit)
        except Exception:
            budget.finish_provider_attempt(
                budget.active_purpose,
                index,
                error_code="provider_error",
                retry_scheduled=False,
                retry_delay_ms=None,
            )
            raise
        budget.finish_provider_attempt(
            budget.active_purpose,
            index,
            error_code=None,
            retry_scheduled=False,
            retry_delay_ms=None,
        )
        return response


def test_stream_event_invariants() -> None:
    assert ModelStreamEvent(
        ModelStreamEventKind.TEXT_DELTA,
        "a",
    ).delta == "a"
    assert ModelStreamEvent(
        ModelStreamEventKind.RESPONSE_COMPLETED
    ).delta is None
    assert ModelStreamEvent(
        ModelStreamEventKind.RESPONSE_DISCARDED
    ).delta is None
    with pytest.raises(ValueError):
        ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, "")
    with pytest.raises(ValueError):
        ModelStreamEvent(ModelStreamEventKind.RESPONSE_COMPLETED, "x")


def test_model_client_protocol_remains_sync_only() -> None:
    assert isinstance(FakeModelClient((ModelResponse(text="ok"),)), ModelClient)
    assert not isinstance(FakeModelClient(()), StreamingModelClient)
```

- [ ] **Step 2: Write RED fallback and budget tests**

Use the test-only client above, whose budget-aware methods claim and finish exactly one physical attempt. Add:

```python
def test_nonstream_client_falls_back_inside_one_logical_call() -> None:
    client = FakeModelClient((ModelResponse(text="fallback"),))
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=1)
    events: list[ModelStreamEvent] = []

    response = invoke_model_stream(client, request(), budget, events.append)

    assert response.text == "fallback"
    assert budget.logical_calls == 1
    assert budget.provider_attempts == 1
    assert events == [ModelStreamEvent(ModelStreamEventKind.RESPONSE_COMPLETED)]


def test_structured_unsupported_before_delta_uses_second_attempt_same_logical() -> None:
    client = ScriptedStreamingClient(
        (StreamScript((), StreamingUnsupportedError("unsupported")),),
        complete_outcomes=(ModelResponse(text="fallback"),),
    )
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=2)
    events: list[ModelStreamEvent] = []

    response = invoke_model_stream(client, request(), budget, events.append)

    assert response.text == "fallback"
    assert (budget.logical_calls, budget.provider_attempts) == (1, 2)
    assert client.stream_calls == 1
    assert client.complete_calls == 1


def test_unsupported_after_delta_discards_without_fallback() -> None:
    client = ScriptedStreamingClient(
        (
            StreamScript(
                ("partial",),
                StreamingUnsupportedError("unsupported"),
            ),
        ),
        complete_outcomes=(ModelResponse(text="must not run"),),
    )
    events: list[ModelStreamEvent] = []

    with pytest.raises(StreamInterruptedError, match="stream interrupted"):
        invoke_model_stream(client, request(), ModelCallBudget(), events.append)

    assert client.complete_calls == 0
    assert events == [
        ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, "partial"),
        ModelStreamEvent(ModelStreamEventKind.RESPONSE_DISCARDED),
    ]
```

Also test: exact provider budget 1 blocks the unsupported fallback before a second provider call; ordinary `ModelError` before delta does not fallback; callback error propagates without a recursive discard; `KeyboardInterrupt` and `SystemExit` propagate; a successful stream emits deltas then exactly one completion.

- [ ] **Step 3: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_streaming.py -q -p no:cacheprovider
```

Expected: collection fails because `coding_agent.streaming` does not exist.

- [ ] **Step 4: Refactor synchronous internals while staying GREEN**

Before adding streaming behavior, extract from `invoke_model` a private function in `model.py`:

```python
def _complete_with_active_budget(
    client: ModelClient,
    request: ModelRequest,
    budget: ModelCallBudget,
) -> ModelResponse:
    """Perform one complete operation while the logical call is already active."""
```

Move only the `BudgetAwareModelClient` vs single-attempt branch into it. Keep logical begin/finish and exception observation in `invoke_model`. Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_model.py tests\test_logging.py tests\test_openai_client.py tests\test_chat_completions_client.py -q -p no:cacheprovider
```

Expected: exit 0 before streaming code is added; all observation counts and retries remain unchanged.

- [ ] **Step 5: Implement the streaming core minimally**

Create the exact enum/dataclass/protocol/error signatures. `invoke_model_stream` must:

1. validate the callback is callable;
2. begin one logical call;
3. wrap `emit` to track successfully delivered text and callback failure;
4. choose `BudgetAwareStreamingModelClient.stream_with_budget`, a core-counted `StreamingModelClient.stream`, or `_complete_with_active_budget`;
5. catch only `Exception` for fallback/discard logic;
6. fallback only for structured unsupported before a delivered delta;
7. finish logical observation exactly once;
8. emit completion only after a valid final `ModelResponse`;
9. emit discard only after delivered text and never after callback failure.

Use the same `_model_error_code` and observer-failure handling as `invoke_model`; do not call `invoke_model` or public `complete()` from fallback.

- [ ] **Step 6: Run GREEN and full model/logging regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_streaming.py tests\test_model.py tests\test_logging.py tests\test_openai_client.py tests\test_chat_completions_client.py -q -p no:cacheprovider
```

Expected: exit 0; one logical call and exact physical counts hold across all fallback cases.

**Acceptance:** optional protocol, stable events/errors, no SDK types, no required change to ModelClient, and no nested logical budget.

---

### Task 5: Wire Optional Streaming into Main Agent Calls Only

**Files:**

- Modify: `src/coding_agent/agent.py`
- Modify: `tests/test_streaming.py`
- Modify: `tests/test_agent_loop.py`
- Read only: `src/coding_agent/context.py`, `src/coding_agent/state.py`, `src/coding_agent/app.py`

**Interfaces:**

- Consumes: `invoke_model_stream` and `ModelStreamHandler`.
- Produces: additive `AgentRunner(..., stream_handler=None)`; no-handler behavior stays synchronous.

- [ ] **Step 1: Write RED Agent lifecycle tests**

Use a test streaming client that emits a text delta then returns a complete response:

```python
def test_agent_uses_streaming_for_main_call_when_handler_is_supplied(
    tmp_path: Path,
) -> None:
    events: list[ModelStreamEvent] = []
    client = ScriptedStreamingClient(
        (StreamScript(("done",), ModelResponse(text="done")),),
    )
    runner = AgentRunner(
        model_client=client,
        tool_registry=ToolRegistry(()),
        execution_context=ExecutionContext(tmp_path),
        stream_handler=events.append,
    )

    state = runner.run("repair")

    assert client.stream_calls == 1
    assert client.complete_calls == 0
    assert events[-1].kind is ModelStreamEventKind.RESPONSE_COMPLETED
    assert state.messages[-1] == AssistantMessage(content="done")


def test_agent_discards_partial_stream_before_retrying(tmp_path: Path) -> None:
    events: list[ModelStreamEvent] = []
    client = ScriptedStreamingClient(
        (
            StreamScript(("partial",), ModelError("temporary")),
            StreamScript(("final",), ModelResponse(text="final")),
        )
    )
    runner = AgentRunner(
        model_client=client,
        tool_registry=ToolRegistry(()),
        execution_context=ExecutionContext(tmp_path),
        stream_handler=events.append,
    )

    state = runner.run("repair")

    assert [event.kind for event in events] == [
        ModelStreamEventKind.TEXT_DELTA,
        ModelStreamEventKind.RESPONSE_DISCARDED,
        ModelStreamEventKind.TEXT_DELTA,
        ModelStreamEventKind.RESPONSE_COMPLETED,
    ]
    assert all(
        not isinstance(message, AssistantMessage)
        or message.content != "partial"
        for message in state.messages
    )
    assert state.messages[-1] == AssistantMessage(content="final")
```

Import `AssistantMessage`, `AgentRunner`, `ExecutionContext`, and `ToolRegistry` explicitly. Add a compression test in `tests/test_agent_loop.py` using `_nine_tool_turns`, `_summary_response`, and `_compression_limits`: the nine main calls and final main call use stream scripts, the one summary response comes from `complete_outcomes`, and only main text deltas reach the handler. Add a no-handler test with one `complete_outcome=ModelResponse(text="sync")` and one unused stream script; assert `complete_calls == 1`, `stream_calls == 0`, and current CLI-compatible state.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_streaming.py -k agent -q -p no:cacheprovider
```

Expected: nonzero exit because `AgentRunner` does not accept `stream_handler` and still invokes only `invoke_model`.

- [ ] **Step 3: Implement the additive Agent branch**

Add:

```python
stream_handler: ModelStreamHandler | None = None,
```

Validate null/callable and store privately. At the current main call site only:

```python
if self._stream_handler is None:
    response = invoke_model(self._model_client, request, budget)
else:
    response = invoke_model_stream(
        self._model_client,
        request,
        budget,
        self._stream_handler,
    )
```

Do not alter context summary invocation, Agent error counters, message commit order, or app construction.

- [ ] **Step 4: Run GREEN and Agent/context/app regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_streaming.py tests\test_agent_loop.py tests\test_context.py tests\test_app.py tests\integration\test_agent_failures.py -q -p no:cacheprovider
```

Expected: exit 0; partial content never enters state, summaries do not stream, and production CLI remains synchronous.

- [ ] **Step 5: Close Task 17 and activate Task 18**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_streaming.py tests\test_model.py tests\test_agent_loop.py tests\test_context.py tests\test_logging.py -q -p no:cacheprovider
```

If exit 0, set Task 17 to `已完成`, Task 18 to `进行中`, and retain Task 16 as `已完成`. Confirm one active task and run `git diff --check`.

---

### Task 6: Implement Offline Responses API Streaming

**Files:**

- Modify: `src/coding_agent/openai_client.py`
- Create: `tests/test_openai_streaming_client.py`
- Modify only for synchronous regression assertions: `tests/test_openai_client.py`

**Interfaces:**

- Consumes: current Responses mapping/parser/continuation and streaming protocols.
- Produces: `OpenAIResponsesClient.stream(request, emit)` and `stream_with_budget(request, budget, emit)`.

- [ ] **Step 1: Create fake stream infrastructure and write text/terminal RED tests**

The new test file defines SDK-free duck-typed fixtures:

```python
from copy import deepcopy
from types import SimpleNamespace as ns


TOOL_SCHEMA = {
    "name": "echo",
    "description": "Return text.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
}


class FakeOutputItem:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = deepcopy(payload)
        for key, value in payload.items():
            setattr(self, key, value)

    def model_dump(self, **kwargs: object) -> dict[str, object]:
        assert kwargs == {
            "mode": "json",
            "by_alias": True,
            "exclude_none": False,
        }
        return deepcopy(self._payload)


class FakeResponse:
    def __init__(
        self,
        *,
        response_id: str,
        output: tuple[FakeOutputItem, ...],
        usage: object | None = None,
    ) -> None:
        self.id = response_id
        self.status = "completed"
        self.error = None
        self.output = list(output)
        self.usage = usage


def valid_responses_response(
    *,
    text: str,
    response_id: str,
) -> FakeResponse:
    item = FakeOutputItem(
        {
            "id": "msg-stream",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [
                {"type": "output_text", "text": text, "annotations": []}
            ],
        }
    )
    return FakeResponse(response_id=response_id, output=(item,))


class FakeStream:
    def __init__(
        self,
        events: tuple[object, ...],
        *,
        close_error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.close_error = close_error
        self.closed = False

    def __iter__(self):
        for event in self.events:
            if isinstance(event, BaseException):
                raise event
            yield event

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class FakeResponsesResource:
    def __init__(self, *outcomes: object) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeSDK:
    def __init__(self, *outcomes: object) -> None:
        self.responses = FakeResponsesResource(*outcomes)
```

Use the `ns` alias for stream events and the complete-response fixture above. Add:

```python
def test_responses_stream_maps_request_emits_text_and_returns_final_response() -> None:
    final = valid_responses_response(text="hello", response_id="resp-stream")
    stream = FakeStream((
        ns(type="response.output_text.delta", delta="hel"),
        ns(type="response.output_text.delta", delta="lo"),
        ns(type="response.completed", response=final),
    ))
    sdk = FakeSDK(stream)
    client = OpenAIResponsesClient(
        model="test-model", api_key="not-real", sdk_client=sdk
    )
    events: list[ModelStreamEvent] = []

    response = client.stream(
        ModelRequest(
            messages=(UserMessage("task"),),
            tool_schemas=(TOOL_SCHEMA,),
            max_output_tokens=123,
            instructions="instruction sentinel",
        ),
        events.append,
    )

    sent = sdk.responses.calls[0]
    assert sent["stream"] is True
    assert sent["store"] is False
    assert sent["instructions"] == "instruction sentinel"
    assert sent["input"] == [{"role": "user", "content": "task"}]
    assert sent["max_output_tokens"] == 123
    assert sent["include"] == ["reasoning.encrypted_content"]
    assert sent["tools"] == [
        {
            "type": "function",
            "name": "echo",
            "description": "Return text.",
            "strict": True,
            "parameters": TOOL_SCHEMA["parameters"],
        }
    ]
    assert "conversation" not in sent
    assert "previous_response_id" not in sent
    assert [event.delta for event in events if event.kind is ModelStreamEventKind.TEXT_DELTA] == ["hel", "lo"]
    assert events[-1].kind is ModelStreamEventKind.RESPONSE_COMPLETED
    assert response.text == "hello"
    assert response.provider_response_id == "resp-stream"
    assert stream.closed is True
```

Add an exact synchronous regression assertion that `complete()` calls still omit `stream`.
Add a second stream request with `instructions=None` and assert the `instructions` key is absent while every other expected kwarg is unchanged.

- [ ] **Step 2: Run Responses text RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_streaming_client.py -k "maps_request or text" -q -p no:cacheprovider
```

Expected: nonzero exit because the client has no stream method.

- [ ] **Step 3: Implement minimum Responses stream request and text terminal parser**

Extract a private request-kwargs builder shared by complete/stream only after the current complete exact tests are green. Add `stream=True` only in stream. Consume the iterator until exactly one `response.completed`; validate text delta strings; pass its `response` through existing `_parse_response`; create continuation with the existing `_OpenAIContinuationSegment` code; ensure final text equals concatenated deltas when deltas exist. Always close the stream in `finally`.

- [ ] **Step 4: Run Responses text GREEN and synchronous regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_streaming_client.py -k "maps_request or text" -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -q -p no:cacheprovider
```

Expected: both commands exit 0; complete kwargs remain unchanged.

- [ ] **Step 5: Write RED tests for tools, continuation, usage, and invalid terminal events**

Add parameterized cases for:

```python
def test_responses_stream_returns_ordered_tools_usage_and_sdk_free_continuation() -> None:
    reasoning = FakeOutputItem(
        {"id": "reasoning-1", "type": "reasoning", "status": "completed"}
    )
    first = FakeOutputItem(
        {
            "id": "function-1",
            "type": "function_call",
            "status": "completed",
            "call_id": "call-a",
            "name": "read_file",
            "arguments": '{"path":"a.py"}',
        }
    )
    second = FakeOutputItem(
        {
            "id": "function-2",
            "type": "function_call",
            "status": "completed",
            "call_id": "call-b",
            "name": "read_file",
            "arguments": '{"path":"b.py"}',
        }
    )
    usage = ns(input_tokens=10, output_tokens=4, total_tokens=14)
    final = FakeResponse(
        response_id="resp-tools",
        output=(reasoning, first, second),
        usage=usage,
    )
    stream = FakeStream(
        (
            ns(
                type="response.function_call_arguments.delta",
                output_index=1,
                item_id="function-1",
                delta='{"path":"',
            ),
            ns(
                type="response.function_call_arguments.delta",
                output_index=2,
                item_id="function-2",
                delta='{"path":"',
            ),
            ns(
                type="response.function_call_arguments.delta",
                output_index=1,
                item_id="function-1",
                delta='a.py"}',
            ),
            ns(
                type="response.function_call_arguments.delta",
                output_index=2,
                item_id="function-2",
                delta='b.py"}',
            ),
            ns(
                type="response.function_call_arguments.done",
                output_index=1,
                item_id="function-1",
                name="read_file",
                arguments='{"path":"a.py"}',
            ),
            ns(
                type="response.function_call_arguments.done",
                output_index=2,
                item_id="function-2",
                name="read_file",
                arguments='{"path":"b.py"}',
            ),
            ns(type="response.completed", response=final),
        )
    )
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=FakeSDK(stream),
    )
    events: list[ModelStreamEvent] = []

    response = client.stream(
        ModelRequest(messages=(UserMessage("task"),)),
        events.append,
    )

    assert response.tool_calls == (
        ToolCall("call-a", "read_file", {"path": "a.py"}),
        ToolCall("call-b", "read_file", {"path": "b.py"}),
    )
    assert response.usage == TokenUsage(10, 4, 14)
    assert response.provider_response_id == "resp-tools"
    assert len(response.continuation_items) == 1
    assert all(not isinstance(item, FakeOutputItem) for item in response.continuation_items)
    assert "reasoning-1" not in repr(response)
    assert all(event.kind is not ModelStreamEventKind.TEXT_DELTA for event in events)


def test_responses_stream_replays_and_extends_continuation_without_duplicate_calls() -> None:
    first_output = FakeOutputItem(
        {
            "id": "function-first",
            "type": "function_call",
            "status": "completed",
            "call_id": "call-first",
            "name": "read_file",
            "arguments": '{"path":"a.py"}',
        }
    )
    first_final = FakeResponse(
        response_id="resp-first",
        output=(first_output,),
    )
    second_final = valid_responses_response(
        text="done",
        response_id="resp-second",
    )
    first_stream = FakeStream(
        (ns(type="response.completed", response=first_final),)
    )
    second_stream = FakeStream(
        (
            ns(type="response.output_text.delta", delta="done"),
            ns(type="response.completed", response=second_final),
        )
    )
    sdk = FakeSDK(first_stream, second_stream)
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=sdk,
    )

    first = client.stream(
        ModelRequest(messages=(UserMessage("inspect"),)),
        lambda event: None,
    )
    second = client.stream(
        ModelRequest(
            messages=(
                UserMessage("inspect"),
                AssistantMessage(tool_calls=first.tool_calls),
                ToolResult(
                    call_id="call-first",
                    tool_name="read_file",
                    status="ok",
                    output='{"content":"x"}',
                ),
                UserMessage("finish"),
            ),
            continuation_items=first.continuation_items,
        ),
        lambda event: None,
    )

    replay = sdk.responses.calls[1]["input"]
    assert sum(
        item.get("type") == "function_call"
        and item.get("call_id") == "call-first"
        for item in replay
        if isinstance(item, dict)
    ) == 1
    assert len(first.continuation_items) == 1
    assert len(second.continuation_items) == 2
    assert all(
        not isinstance(item, FakeOutputItem)
        for item in second.continuation_items
    )
    assert "function-first" not in repr(second)


@pytest.mark.parametrize(
    "case",
    ["empty", "failed", "incomplete", "error", "duplicate", "unknown"],
)
def test_responses_stream_rejects_invalid_terminal_shapes(case: str) -> None:
    final = valid_responses_response(text="ok", response_id="resp-invalid")
    cases: dict[str, tuple[object, ...]] = {
        "empty": (),
        "failed": (ns(type="response.failed"),),
        "incomplete": (ns(type="response.incomplete"),),
        "error": (ns(type="error"),),
        "duplicate": (
            ns(type="response.completed", response=final),
            ns(type="response.completed", response=final),
        ),
        "unknown": (ns(type="unsupported.output.delta", delta="x"),),
    }
    stream = FakeStream(cases[case])
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=FakeSDK(stream),
    )
    events: list[ModelStreamEvent] = []

    with pytest.raises(InvalidOpenAIResponseError, match="invalid"):
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            events.append,
        )

    assert stream.closed is True
```

Add function argument `done` events to the ordered-tools success case and assert their `output_index`, `item_id`, name, and complete arguments match the concatenated deltas and terminal function items. Add final-text mismatch, missing/duplicate/conflicting function-argument `done`, sparse output index, unstable item ID, and malformed argument delta tests. Assert stable `InvalidOpenAIResponseError`, no raw event repr in message, one discard after emitted text, no retry, and closed stream.

The cumulative-continuation case must assert that the second request replays the first response snapshot exactly once, pairs the `function_call_output` with `call-first`, appends exactly one new immutable SDK-free segment, and leaves no encrypted reasoning, provider item content, or continuation payload in event/error/object representations.

- [ ] **Step 6: Run tools/invalid RED, implement, and run GREEN**

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_streaming_client.py -k "tools or continuation or invalid or mismatch" -q -p no:cacheprovider
```

Expected: failures because only text/completed is supported.

Implement this exact nonterminal allowlist: `response.created`, `response.in_progress`, `response.queued`, `response.output_item.added`, `response.output_item.done`, `response.content_part.added`, `response.content_part.done`, `response.output_text.delta`, `response.output_text.done`, `response.function_call_arguments.delta`, `response.function_call_arguments.done`, `response.reasoning_summary_part.added`, `response.reasoning_summary_part.done`, `response.reasoning_summary_text.delta`, `response.reasoning_summary_text.done`, `response.reasoning_text.delta`, and `response.reasoning_text.done`. Add one realistic SDK-3.5.0-style full sequence each for message text, function calls, and reasoning. Reject refusal/audio/image/file-search/web-search/code-interpreter/shell/MCP/custom-tool and every unknown event. Accumulate function argument fragments by `output_index` and stable `item_id`; require one matching `response.function_call_arguments.done` and a matching terminal function item whenever fragments were observed. Track every text/function-argument delta as a provider delta, and never emit reasoning or argument content. Reuse existing `_parse_response` for final complete types.

Run GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_streaming_client.py -k "tools or continuation or invalid or mismatch" -q -p no:cacheprovider
```

Expected: exit 0.

- [ ] **Step 7: Write RED retry/fallback/close tests**

Use the same OpenAI exception constructors as `tests/test_openai_client.py`. Cover:

- timeout/connection/429/5xx before any delta: three physical calls, delays `[0.25, 0.50]`;
- transient error after a text delta: one call, no delay, discarded, `StreamInterruptedError`;
- transient error after a function-argument delta: one call, no fallback/retry;
- authentication and bad request: one call, no fallback;
- injected structured `StreamingUnsupportedError` before delta: one stream attempt plus one synchronous attempt under one logical call;
- structured unsupported after delta: one stream attempt, no synchronous request;
- structured unsupported after a function-argument delta: one stream attempt, no synchronous request even though no text event was delivered;
- close failure after successful parse raises exactly `StreamInterruptedError("model stream cleanup failed")` without retry; close failure during another exception or `BaseException` does not replace the primary error;
- `KeyboardInterrupt` and `SystemExit` propagate.

- [ ] **Step 8: Run retry RED, implement, and run Responses full GREEN**

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_streaming_client.py -k "retry or unsupported or close or interrupt" -q -p no:cacheprovider
```

Implement the existing 0.25/0.50 retry schedule around stream creation plus full consumption. Claim/finish a provider attempt for every iterator, and never mark success before final validation. Do not parse exception text.

Run GREEN and regression:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_streaming_client.py tests\test_openai_client.py tests\test_streaming.py tests\test_model.py -q -p no:cacheprovider
```

Expected: exit 0 with exact attempt/delay assertions.

---

### Task 7: Implement Offline Chat Completions Streaming

**Files:**

- Modify: `src/coding_agent/chat_completions_client.py`
- Create: `tests/test_chat_completions_streaming_client.py`
- Modify only for synchronous exact-regression assertions: `tests/test_chat_completions_client.py`

**Interfaces:**

- Consumes: current full-history/system/tool schema mapping, `_parse_response`, and streaming protocols.
- Produces: Chat `stream` and `stream_with_budget` with indexed tool-fragment assembly.

- [ ] **Step 1: Write text/request RED tests with a closable fake stream**

Use these exact fake resource and chunk helpers:

```python
from collections import deque
from types import SimpleNamespace as ns


TOOL_SCHEMA = {
    "name": "echo",
    "description": "Return text.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
}


class FakeStream:
    def __init__(
        self,
        chunks: tuple[object, ...],
        *,
        close_error: BaseException | None = None,
    ) -> None:
        self.chunks = chunks
        self.close_error = close_error
        self.closed = False

    def __iter__(self):
        for chunk_value in self.chunks:
            if isinstance(chunk_value, BaseException):
                raise chunk_value
            yield chunk_value

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class FakeCompletionsResource:
    def __init__(self, *outcomes: object) -> None:
        self.outcomes = deque(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeSDK:
    def __init__(self, *outcomes: object) -> None:
        self.chat = ns(completions=FakeCompletionsResource(*outcomes))


def delta(
    *,
    role: object = None,
    content: object = None,
    tool_calls: object = None,
    function_call: object = None,
    refusal: object = None,
) -> object:
    return ns(
        role=role,
        content=content,
        tool_calls=tool_calls,
        function_call=function_call,
        refusal=refusal,
    )


def chunk(
    *,
    delta: object,
    finish_reason: object = None,
    response_id: str = "chatcmpl-stream",
    usage: object = None,
) -> object:
    choice = ns(index=0, delta=delta, finish_reason=finish_reason)
    return ns(id=response_id, choices=[choice], usage=usage)


def test_chat_stream_maps_full_history_system_tools_and_text_deltas() -> None:
    call = ToolCall("call-previous", "echo", {"text": "previous"})
    result = ToolResult(
        call_id="call-previous",
        tool_name="echo",
        status="ok",
        output="previous",
    )
    stream = FakeStream((
        chunk(delta=delta(role="assistant", content="hel")),
        chunk(delta=delta(content="lo"), finish_reason="stop"),
    ))
    sdk = FakeSDK(stream)
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )
    events: list[ModelStreamEvent] = []

    response = client.stream(
        ModelRequest(
            messages=(
                UserMessage("begin"),
                AssistantMessage(tool_calls=(call,)),
                result,
                UserMessage("task"),
            ),
            tool_schemas=(TOOL_SCHEMA,),
            max_output_tokens=123,
            instructions="instruction sentinel",
        ),
        events.append,
    )

    sent = sdk.chat.completions.calls[0]
    assert sent["stream"] is True
    assert sent["messages"] == [
        {"role": "system", "content": "instruction sentinel"},
        {"role": "user", "content": "begin"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-previous",
                    "type": "function",
                    "function": {
                        "name": "echo",
                        "arguments": '{"text":"previous"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-previous",
            "content": result.to_json(),
        },
        {"role": "user", "content": "task"},
    ]
    assert sent["max_tokens"] == 123
    assert sent["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Return text.",
                "strict": True,
                "parameters": TOOL_SCHEMA["parameters"],
            },
        }
    ]
    assert "store" not in sent
    assert "conversation" not in sent
    assert "previous_response_id" not in sent
    assert response.text == "hello"
    assert response.continuation_items == ()
    assert stream.closed is True
```

Assert the synchronous call still omits `stream`.
Add a second stream request with null instructions and assert no system message is present while the complete local history mapping remains unchanged.

- [ ] **Step 2: Run Chat text RED, implement minimum aggregator, and run GREEN**

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_streaming_client.py -k "maps_full_history or text" -q -p no:cacheprovider
```

Expected: nonzero exit because no stream method exists.

Implement stream request mapping and aggregate choice index 0, assistant role, content, one final finish reason, optional response ID, and optional usage. Build a complete response-like dict and pass it to current `_parse_response`.

Run GREEN and synchronous regression:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_streaming_client.py -k "maps_full_history or text" -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_client.py -q -p no:cacheprovider
```

Expected: both commands exit 0.

- [ ] **Step 3: Write RED ordered tool-fragment tests**

Cover one tool split across chunks, two interleaved indexes, text plus tools, and `finish_reason="stop"` with tools. Example assertions:

```python
assert response.tool_calls == (
    ToolCall("call-a", "read_file", {"path": "a.py"}),
    ToolCall("call-b", "read_file", {"path": "b.py"}),
)
assert [
    event.delta
    for event in events
    if event.kind is ModelStreamEventKind.TEXT_DELTA
] == ["working"]
```

Add rejection cases for sparse/noninteger/negative indexes, conflicting ID/name/type, missing ID/name, duplicate final IDs, legacy `function_call`, refusal, non-function call, malformed/non-object arguments, multiple choices, nonzero choice index, duplicate/missing/unsupported finish reason, inconsistent response IDs, partial usage, and non-empty continuation before SDK access.

- [ ] **Step 4: Run tool RED, implement indexed accumulators, and run GREEN**

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_streaming_client.py -k "tool or index or invalid or usage or continuation" -q -p no:cacheprovider
```

Expected: failures because the minimum aggregator does not assemble/validate tools.

Implement a private adapter-only accumulator dataclass keyed by tool index. It stores optional stable ID/name/type and a list of argument fragments; it does not instantiate `ToolCall` until terminal validation. Sort by index, require contiguous `range(len(accumulators))`, build canonical full tool calls, then reuse `_parse_response`.

Run GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_streaming_client.py -k "tool or index or invalid or usage or continuation" -q -p no:cacheprovider
```

Expected: exit 0.

- [ ] **Step 5: Write RED retry, fallback, close, and BaseException tests**

Mirror the Responses matrix and assert exact Chat calls/delays:

- all four transient classes retry only before any content/tool-argument delta;
- post-delta errors become interrupted with no sleep or request 2;
- auth, permission, not-found, bad request, parse errors, and ordinary provider errors never fallback;
- structured unsupported before delta uses synchronous Chat mapping on the next shared attempt;
- fallback retains the same local history and instructions;
- stream close happens on success/failure; cleanup failure precedence is stable;
- callback errors, `KeyboardInterrupt`, and `SystemExit` propagate;
- no raw SDK exception body, request, key, authorization header, or accumulated tool arguments appear in error/repr.

- [ ] **Step 6: Run retry RED, implement, and run Chat full GREEN**

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_streaming_client.py -k "retry or unsupported or close or interrupt or secret" -q -p no:cacheprovider
```

Implement the same shared-budget and pre-delta retry rules without exception-text inspection.

Run GREEN and all Chat regressions:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_streaming_client.py tests\test_chat_completions_client.py tests\integration\test_chat_completions_agent.py tests\test_streaming.py -q -p no:cacheprovider
```

Expected: exit 0; synchronous complete, compressed history, and Task 15 lifecycle behavior remain unchanged.

---

### Task 8: Documentation Contracts, Full Verification, and Milestone Checkpoint

**Files:**

- Modify: `DESIGN.md`
- Modify: `TASKS.md`
- Modify: `docs/OPENAI_API.md`
- Modify: `docs/USAGE.md`
- Modify: `tests/test_docs.py`
- Review: every path in the locked file map

**Interfaces:**

- Consumes: green Task 16–18 behavior.
- Produces: accurate architecture/API documentation and fresh final evidence; Task 18 remains active.

- [ ] **Step 1: Write RED documentation-contract tests**

Add exact assertions that current docs must contain:

```python
assert "ModelRequest.instructions" in design
assert "RunInstructionBuilder" in design
assert "StreamingModelClient" in design
assert "stream=True" in api_guide
assert "首个 delta 前" in api_guide
assert "delta 后不重试" in api_guide
assert "CLI 仍使用同步最终报告" in usage
assert "SSE" in unsupported_or_deferred_section
```

Remove only the obsolete blanket assertion that all streaming is unsupported. Continue requiring session persistence, SSE, GUI, async clients, executable Skills, MCP, and automatic endpoint detection to be described as deferred.

- [ ] **Step 2: Run docs RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py -q -p no:cacheprovider
```

Expected: nonzero exit because current public docs still list streaming as wholly unsupported and omit run instructions.

- [ ] **Step 3: Update design and user/API documentation accurately**

Document:

- root-only safe `AGENTS.md`, deterministic base/workspace/selected-Skill order, exact size limits, and one-snapshot-per-run behavior;
- provider instructions mapping and summary isolation;
- optional in-memory streaming protocol and events;
- Responses and Chat stream request/parser/retry/fallback behavior;
- synchronous CLI default and the fact that no current SSE/GUI surface displays deltas;
- no provider autodetection, no exception-text fallback, no persisted partial output, and no server conversation;
- Task 19+ owns lifecycle/controller/SSE/GUI and Task 21 owns Skill management.

Do not claim live endpoint streaming compatibility or expose a credential/provider payload.

- [ ] **Step 4: Run docs GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py -q -p no:cacheprovider
```

Expected: exit 0.

- [ ] **Step 5: Run all focused Task 16–18 tests**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_instructions.py tests\test_model.py tests\test_streaming.py tests\test_agent_loop.py tests\test_app.py tests\test_openai_client.py tests\test_openai_streaming_client.py tests\test_chat_completions_client.py tests\test_chat_completions_streaming_client.py tests\test_context.py tests\test_logging.py tests\integration\test_chat_completions_agent.py tests\test_docs.py -q -p no:cacheprovider
```

Expected: exit 0, no failed/skipped tests. Record the real count.

- [ ] **Step 6: Run the complete Task 1–18 offline suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Expected: exit 0, no failed/skipped tests. Record actual pass/warning counts; do not reuse the planning baseline.

- [ ] **Step 7: Run signature, SDK isolation, and behavior audits**

Run:

```powershell
@'
import inspect
from coding_agent.messages import ModelRequest
from coding_agent.model import ModelClient
from coding_agent.streaming import StreamingModelClient, invoke_model_stream
from coding_agent.openai_client import OpenAIResponsesClient
from coding_agent.chat_completions_client import ChatCompletionsModelClient
print(inspect.signature(ModelClient.complete))
print(inspect.signature(StreamingModelClient.stream))
print(inspect.signature(invoke_model_stream))
print(inspect.signature(OpenAIResponsesClient.complete))
print(inspect.signature(ChatCompletionsModelClient.complete))
print(inspect.signature(ModelRequest))
'@ | .\.venv\Scripts\python.exe -
rg -n "from openai|import openai" src\coding_agent --glob "!openai_client.py" --glob "!chat_completions_client.py"
rg -n "responses\.create|chat\.completions\.create|stream=True|store=False|previous_response_id|conversation" src\coding_agent\openai_client.py src\coding_agent\chat_completions_client.py
rg -n "ModelStreamEvent|StreamingModelClient" src\coding_agent\messages.py src\coding_agent\state.py src\coding_agent\context.py src\coding_agent\tools
```

Expected: complete signatures remain `(self, request)`; SDK imports occur only in the two adapters; stream mappings are present; server-state parameters are not sent; streaming fragment types do not leak into messages/state/context/tools.

- [ ] **Step 8: Run dependency, privacy, deferred-scope, and suppression scans**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip check
rg -n "langchain|llamaindex|openai-agents|autogen|crewai" pyproject.toml src tests
rg -n "sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{12,}|Authorization:" src README.md README.txt docs
rg -n "C:\\Users\\|D:\\code\\" src tests README.md README.txt docs\USAGE.md docs\OPENAI_API.md
rg -n "skip|xfail" tests
rg -n "Task 19|SessionStore|FastAPI|EventSource|MCP|SkillManager" src\coding_agent
git diff -- pyproject.toml src\coding_agent\safety.py src\coding_agent\context.py src\coding_agent\state.py src\coding_agent\logging.py src\coding_agent\verification.py src\coding_agent\tools
```

Expected: `pip check` exits 0; framework/production-and-public-document credential/personal-path/deferred-production scans have no unsafe matches; no new skip/xfail; protected production diff is empty. Fake `Authorization` and API-key sentinels in offline tests are intentionally excluded from the raw credential grep and remain covered by the dedicated repr/error/log redaction tests.

- [ ] **Step 9: Verify Windows path safety and no network default**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_instructions.py tests\test_path_safety.py tests\tools\test_shell_tool.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_openai_streaming_client.py tests\test_chat_completions_streaming_client.py -q -p no:cacheprovider
```

Expected: all real reparse/symlink/process safety tests execute without skip; fake SDK tests pass without reading credential environment variables or opening network sockets.

- [ ] **Step 10: Diff and status review**

Run:

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff --name-only
git diff
```

Expected: only the locked paths plus this already-approved spec/plan appear; no generated cache, credential, database, log, or provider payload is tracked. Review every changed line.

- [ ] **Step 11: Apply verification-before-completion and check the acceptance matrix**

Map fresh evidence to every item:

| Requirement | Evidence |
| --- | --- |
| Instructions are separate, explicit, repr-private | `test_messages.py`, `test_instructions.py` |
| Root AGENTS is deterministic, bounded, UTF-8, reparse-safe | `test_instructions.py`, `test_path_safety.py` |
| Main calls retain snapshot; summaries are isolated | Agent/context instruction tests |
| Responses/Chat conditional mapping; null behavior unchanged | synchronous adapter tests |
| ModelClient and complete signatures unchanged | signature audit and model tests |
| One logical call across fallback | `test_streaming.py` exact counters |
| First forbidden provider request is blocked | stream budget boundary tests |
| Text lifecycle complete/discarded; partial state is clean | streaming Agent tests |
| Responses stream request, parsing, usage, continuation | Responses streaming suite |
| Chat indexed tool assembly and full-history semantics | Chat streaming suite |
| Pre-delta retry only; post-delta no retry/fallback | both adapter retry matrices |
| Ordinary 400/auth errors never capability-fallback | both adapter error matrices |
| No server state, SDK leakage, payload logging, or key leak | source/privacy audits |
| Existing Task 1–15 behavior preserved | complete offline suite |
| No dependency/framework or Task 19+ implementation | `pip check`, diff, scope scans |

Any missing evidence leaves Task 18 active and blocks a completion claim.

- [ ] **Step 12: Stop at the milestone review checkpoint**

Keep Task 18 as `进行中`. Do not stage, commit, push, begin Task 19, or run a branch-finishing workflow. Report:

- every RED command, nonzero exit, and expected missing behavior;
- every GREEN/focused/full command with real counts and warnings;
- exact logical/provider counts and retry delays;
- instruction path/limit/privacy evidence;
- continuation and partial-state evidence;
- synchronous provider regression evidence;
- files changed and full Git status;
- any deviation, unresolved item, or environment limitation.

Wait for user review and explicit authorization.

---

## Plan Self-Review Record

- Spec coverage: every section in the Milestone A design maps to Tasks 0–8 and the final acceptance table.
- Type consistency: `ModelRequest.instructions`, `RunInstructionSnapshot`, `ModelStreamEvent`, protocols, errors, handler, and invocation names are identical throughout.
- Budget consistency: fallback uses one logical call and the same shared budget; each actual stream/non-stream request claims one provider attempt.
- Continuation consistency: only validated Responses terminal output creates continuation; Chat remains empty; partial streams create none.
- Privacy consistency: instruction bodies and stream/provider content stay out of JSONL and errors; only in-memory callbacks receive text deltas.
- Scope consistency: lifecycle persistence, Skills management, SSE/GUI, MCP, async work, and Task 19+ remain deferred.
- Placeholder scan: the plan contains concrete interfaces, tests, commands, expected failures, and acceptance evidence with no undefined implementation marker.

## Execution Gate

This plan does not authorize implementation by itself. After user approval, execute inline with `superpowers:executing-plans` and `superpowers:test-driven-development`; use `superpowers:systematic-debugging` for unexpected reproducible failures and `superpowers:verification-before-completion` before the review report. The user-authorized subagent may perform independent read-only review, but core implementation remains sequential in the main workspace.

# Task 9 OpenAI Responses API Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`, `superpowers:test-driven-development`, and `superpowers:verification-before-completion` to implement this plan task-by-task. Use `superpowers:systematic-debugging` before changing code for any reproducible unexpected failure. Do not use subagents, parallel agents, branches, or worktrees.

**Goal:** Implement a synchronous `OpenAIResponsesClient` backed by the official OpenAI Python SDK Responses API while preserving the existing provider-neutral `ModelClient`, message, Agent, tool, configuration, and Task 8 safety boundaries.

**Architecture:** `coding_agent.openai_client` is the only production SDK boundary. It translates immutable internal messages and strict registry schemas into stateless Responses API input, calls `client.responses.create(...)` with `store=False`, snapshots response output into SDK-free in-memory continuation segments, parses text/function calls/usage back into the existing Task 2 types, and maps provider failures into the existing model-error hierarchy. The Agent continues to own local history and forwards opaque continuation tuples without inspecting them.

**Tech stack:** Python 3.11+, the already-approved official `openai` dependency (installed baseline: 3.5.0), standard-library `dataclasses`, `json`, `time`, `copy`, and `typing`, plus pytest. Tests use injected fake SDK clients, fake response objects, and fake SDK exception subclasses; they never perform network I/O or read a real API key.

**Specs and references:** `DESIGN.md` sections 7, 8, 10, 12, and 16; `TASKS.md` Task 9; `AGENTS.md`; the official [Responses API create reference](https://developers.openai.com/api/reference/typescript/resources/beta/subresources/responses/methods/create); the official [function-calling guide](https://developers.openai.com/api/docs/guides/function-calling); and official guidance that manually managed history must resend prior response output items when `store=false`.

## Global constraints

- Work only in `D:\code\coding_agent` on the current `main` worktree. Do not create a branch or worktree.
- Do not stage, commit, push, fetch, pull, or access a remote repository while executing this plan.
- Do not call a real OpenAI endpoint. Default and focused tests must be fully offline.
- Do not read `OPENAI_API_KEY` inside tests. Tests pass a conspicuous fake sentinel directly and inject an SDK client.
- Do not change Task 2 message shapes, `ModelClient.complete`, `FakeModelClient`, the Task 4 Agent loop, tool interfaces, Task 8 safety policy, or the CLI execution behavior.
- Do not implement Task 10 context compression/termination, Task 11 verification, Task 12 logs/reports, or Task 13 integration scenarios.
- Keep retry policy synchronous, deterministic, and local to this adapter: one initial attempt plus at most two retries, with delays of 0.25 and 0.50 seconds and no jitter.
- Disable the official SDK's built-in request retries with `max_retries=0` when the adapter constructs the SDK client; otherwise the locked three-attempt maximum would be violated.
- Never include an API key, Authorization header, request body, provider exception text, or opaque continuation payload in adapter exceptions or repr output.
- Every production behavior follows a distinct RED, minimum GREEN, and Task 1–8 regression before the next behavior.
- During implementation, Task 9 remains `进行中` until the user reviews fresh verification evidence.

## Baseline findings that constrain this plan

- Repository root is `D:/code/coding_agent`, branch is `main`, and Task 8 is committed as `8360808 完成工作区和命令安全限制内容`.
- The worktree was clean when this plan was written. Git emitted only a host-level warning that `C:\Users\21392\.config\git\ignore` could not be read; no tracked or untracked worktree entry was reported.
- The committed `TASKS.md` still labels Task 8 `进行中` and Task 9 `未开始`. This is a status bookkeeping remainder, not an implementation defect. It must be corrected only after this plan is approved and Task 9 execution begins.
- `ModelRequest` and `ModelResponse` already expose opaque, repr-hidden, non-serialized `continuation_items: tuple[object, ...]`; no Task 2 interface change is needed.
- `AgentRunner` already copies response continuation items into `AgentState` and forwards them on the next `ModelRequest` without inspection; no Agent change is needed.
- `RunConfig` already supplies validated `model` and repr-hidden `api_key`. The CLI intentionally stops after validation, so Task 9 does not need to connect the real adapter to the CLI.
- `ToolRegistry.schemas` already preserves registration order and returns strict schemas shaped as `name`, `description`, `strict`, and `parameters`.
- The official SDK is already the only production dependency. `pyproject.toml` must remain unchanged.

## Locked file map

**Create**

- `src/coding_agent/openai_client.py` — official SDK boundary, input/tool mapping, continuation snapshots, output parsing, retry classification, and sanitized errors.
- `tests/test_openai_client.py` — entirely offline fake-SDK component tests.

**Modify during approved execution only**

- `TASKS.md` — after Task 0 passes, change only Task 8 from `进行中` to `已完成` and Task 9 from `未开始` to `进行中`; Task 9 remains `进行中` at the final stop.

**Inspect but keep unchanged**

- `src/coding_agent/messages.py`
- `src/coding_agent/model.py`
- `src/coding_agent/agent.py`
- `src/coding_agent/state.py`
- `src/coding_agent/config.py`
- `src/coding_agent/cli.py`
- `src/coding_agent/tools/base.py`
- `src/coding_agent/tools/registry.py`
- `src/coding_agent/tools/filesystem.py`
- `src/coding_agent/tools/shell.py`
- `src/coding_agent/safety.py`
- `pyproject.toml`
- every existing test file

`config.py` appears in the Task 9 module inventory, but it already contains the exact required `model` and repr-hidden `api_key` values. Adding a factory there would make configuration import the SDK boundary and would weaken the Task 8 offline import boundary. Task 9 therefore proves construction compatibility in `tests/test_openai_client.py` without modifying `config.py`.

## Locked public interfaces

The only new public production names are:

```python
class InvalidOpenAIResponseError(ModelError):
    """The provider returned a completed but unusable Responses payload."""


class OpenAIResponsesClient:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        sdk_client: object | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None: ...

    def complete(self, request: ModelRequest) -> ModelResponse: ...
```

Locked constructor behavior:

- `model` and `api_key` must be non-empty strings after trimming. Stable failures are `ValueError("model must be a non-empty string")` and `ValueError("api_key must be a non-empty string")`; neither error contains the supplied value.
- `sleeper` must be callable or construction raises `TypeError("sleeper must be callable")`.
- If `sdk_client` is supplied, the adapter stores that object and does not instantiate an official client.
- If `sdk_client` is absent, construction calls exactly `OpenAI(api_key=normalized_api_key, max_retries=0)`.
- The adapter stores `_model`, `_client`, and `_sleeper`; it does not store the API key separately and has no custom repr that could reveal it.
- `OpenAIResponsesClient` structurally satisfies the existing runtime-checkable `ModelClient` Protocol. `complete` accepts and returns only Task 2 types.
- No official SDK type appears in `messages.py`, `model.py`, `agent.py`, tools, configuration annotations, or the public `complete` signature.

`InvalidOpenAIResponseError` extends existing `ModelError`, not `FatalModelError`: `DESIGN.md` treats malformed/incomplete responses as countable model-output failures rather than authentication/configuration failures. Task 10 will later decide how repeated instances affect termination; Task 9 only produces the stable typed error.

## Locked request mapping

Each call uses exactly these top-level Responses parameters:

```python
{
    "model": self._model,
    "input": mapped_input,
    "tools": mapped_tools,
    "max_output_tokens": request.max_output_tokens,
    "store": False,
    "include": ["reasoning.encrypted_content"],
}
```

- Do not include `conversation`, `previous_response_id`, `instructions`, or Chat Completions fields.
- `include=["reasoning.encrypted_content"]` makes stateless reasoning continuation explicit; the encrypted value is retained only in opaque in-memory continuation and is never parsed, printed, or logged.
- If `request.tool_schemas` is empty, send `tools=[]` rather than omitting the field, giving fake tests one deterministic request shape.
- Preserve message, schema, output-item, content-item, and function-call order.

Message mapping without an adapter continuation snapshot is:

| Internal value | Responses input item(s) |
| --- | --- |
| `UserMessage(content)` | `{"role":"user","content":content}` |
| `AssistantMessage(content=text)` | `{"type":"message","role":"assistant","status":"completed","content":[{"type":"output_text","text":text,"annotations":[]}]}` |
| each `AssistantMessage.tool_calls` entry | `{"type":"function_call","call_id":call.call_id,"name":call.name,"arguments":canonical_json}` |
| `ToolResult` | `{"type":"function_call_output","call_id":result.call_id,"output":result.to_json()}` |

Canonical tool arguments use `json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`. The complete `ToolResult.to_json()` is returned as tool output so status, error, stdout-like output, metadata, and `tool_name` remain available to the model while `call_id` also remains an API-level pairing field.

Tool schemas map from the registry form:

```python
{
    "name": name,
    "description": description,
    "strict": True,
    "parameters": parameters,
}
```

to the Responses form:

```python
{
    "type": "function",
    "name": name,
    "description": description,
    "strict": True,
    "parameters": parameters,
}
```

Before the SDK call, reject a schema unless it has exactly those four registry keys, has non-empty `name` and `description`, has `strict is True`, and has an object `parameters`. Recursively walk `parameters`, each `properties` child, every `anyOf`/`oneOf` branch, and `items`: every node with `type == "object"` must have an object `properties`, `additionalProperties is False`, and a `required` array containing exactly every property name once. The root must have `type == "object"`. Raise `FatalModelError("OpenAI Responses request is invalid: tool schema is not strict")`; do not call the SDK.

## Locked continuation representation and ordering

SDK response objects must not enter `AgentState`. `openai_client.py` defines one private immutable value:

```python
@dataclass(frozen=True, slots=True, repr=False)
class _OpenAIContinuationSegment:
    message_index: int
    items: tuple[JSONObject, ...]
```

- Each SDK `response.output` item is copied with `model_dump(mode="json", by_alias=True, exclude_none=False)` and recursively validated as JSON before storage.
- `message_index` equals `len(request.messages)`: the index at which `AgentRunner` will append the assistant message produced by this response.
- `ModelResponse.continuation_items` is cumulative: `request.continuation_items + (new_segment,)`. Because `AgentRunner` replaces rather than appends its state tuple, cumulative return is required to retain the whole active stateless API segment until Task 10 compression clears it.
- On a later request, when the mapper reaches an `AssistantMessage` whose tuple index matches a segment, it emits that segment's items instead of regenerating the normalized assistant message/tool calls. It then emits following `ToolResult` items normally. This avoids duplicate function calls while preserving response item IDs, reasoning/encrypted content, message phase, and exact API output order.
- An `AssistantMessage` without a matching segment uses the provider-neutral fallback mapping in the previous section. This supports requests created from serialized/local semantic history.
- Foreign objects, duplicate segment indexes, indexes that do not point to an `AssistantMessage`, or a segment whose function-call IDs differ from that assistant message raise `FatalModelError("OpenAI Responses request is invalid: continuation does not match local history")` before any SDK call.
- Continuation payloads remain excluded from message/request/response JSON and repr by the existing Task 2 fields. Task 9 adds no logger.

## Locked response parsing

The adapter accepts only a response with a non-empty string `id`, `status == "completed"`, `error is None`, an iterable `output`, and optional valid usage.

Recognized output item types:

- `reasoning`: validate/snapshot and retain for continuation; do not expose its content as assistant text.
- `message`: require `role == "assistant"`, `status == "completed"`, and a list/tuple `content`; accept only `output_text` content blocks with string `text`; concatenate text blocks and message items in exact output order without an inserted separator.
- `function_call`: require non-empty `call_id` and `name`; require `arguments` to be valid JSON whose root is an object; create existing `ToolCall(call_id, name, arguments)`.

Reject `refusal`, built-in tool calls, custom tool calls, shell items, missing `type`, missing required fields, non-completed items, invalid function JSON, non-object arguments, duplicate/empty call IDs, non-JSON continuation snapshots, failed/incomplete responses, and unknown output/content types with `InvalidOpenAIResponseError`. Stable messages begin `invalid OpenAI Responses payload: ` and name only the structural reason; they never interpolate provider payloads or exception text.

Semantic result rules:

- One or more text blocks and no call returns `ModelResponse(text=joined_text, tool_calls=())`.
- Function calls without text are valid and return `text=None`.
- Text and function calls in one response are both retained.
- A completed response with no non-empty text and no function call raises `InvalidOpenAIResponseError("invalid OpenAI Responses payload: no text or function call output")`.
- `usage=None` maps to `None`; otherwise `input_tokens`, `output_tokens`, and `total_tokens` must be non-boolean, non-negative integers and map to existing `TokenUsage`.
- `provider_response_id` is the validated response `id`.
- Snapshot and parsing happen before returning; no partially parsed `ModelResponse` escapes.

## Locked retry and error mapping

`complete` performs one initial SDK call. It retries only these official SDK failures:

- `RateLimitError` (HTTP 429)
- `APITimeoutError`
- `APIConnectionError`
- `InternalServerError`
- any other `APIStatusError` whose integer `status_code` is between 500 and 599

After the first and second retryable failures, call `sleeper(0.25)` and `sleeper(0.50)` respectively. Attempt three is final. If all three attempts fail, raise:

```python
TransientModelError(
    "OpenAI Responses request failed after 3 attempts: transient provider error"
)
```

Do not retry:

- `AuthenticationError` or `PermissionDeniedError` → `FatalModelError("OpenAI Responses request failed: authentication rejected")`
- `BadRequestError` or `UnprocessableEntityError` → `FatalModelError("OpenAI Responses request failed: request rejected")`
- `NotFoundError` → `FatalModelError("OpenAI Responses request failed: model or endpoint not found")`
- other `OpenAIError` → `FatalModelError("OpenAI Responses request failed: provider error")`
- constructor validation or local request mapping errors
- `InvalidOpenAIResponseError`

Do not catch `BaseException`; `KeyboardInterrupt` and `SystemExit` propagate. Never use `str(provider_exception)`, `repr(provider_exception)`, its body, request, response, or headers in an internal error. The official client's `max_retries=0` guarantees the fake resource call count equals real HTTP attempt count under adapter control.

---

### Task 0: Reconfirm the approved Task 8 baseline

**Files:** Read only; after all checks pass, modify only two status values in `TASKS.md`.

**Interfaces:** No production interface change.

- [ ] **Step 1: Re-read the complete baseline**

Read `AGENTS.md`, `DESIGN.md`, `TASKS.md`, `docs/superpowers/plans/Task9.md`, all files under `src/coding_agent`, and every tracked file under `tests`. Confirm these existing signatures before editing:

```python
class ModelClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...

class ModelRequest:
    continuation_items: tuple[object, ...]

class ModelResponse:
    continuation_items: tuple[object, ...]
```

- [ ] **Step 2: Verify repository identity, commit, cleanliness, and whitespace**

Run:

```powershell
Set-Location D:\code\coding_agent
git rev-parse --show-toplevel
git branch --show-current
git log -3 --oneline
git status --short --untracked-files=all
git diff --check
```

Expected: root `D:/code/coding_agent`, branch `main`, Task 8 commit `8360808` reachable at `HEAD`, no worktree entry other than an approved untracked `docs/superpowers/plans/Task9.md` if the plan has not yet been committed, and `git diff --check` exit 0. The host global-ignore permission warning may be reported, but any worktree change outside the approved plan stops execution.

- [ ] **Step 3: Run the complete Task 1–8 baseline suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit 0 with fresh actual pass/fail/skip/warning counts. Any failure stops Task 9; do not reinterpret an old result as current evidence.

- [ ] **Step 4: Correct only task status bookkeeping**

Change Task 8 from `进行中` to `已完成` and Task 9 from `未开始` to `进行中`. Do not change any task text or later status. Run:

```powershell
Select-String -Path TASKS.md -Pattern '已完成|进行中|未开始'
git diff -- TASKS.md
```

Expected: exactly Task 9 is `进行中`, and the diff contains only the two status lines.

**Acceptance:** Task 8 is committed and green, the baseline is clean apart from the approved plan, existing public interfaces match, and exactly Task 9 becomes active.

---

### Task 1: Client construction, Protocol compatibility, and stateless request history

**Files:**

- Create: `tests/test_openai_client.py`
- Create: `src/coding_agent/openai_client.py`

**Interfaces:** Introduces `OpenAIResponsesClient` and reuses `ModelClient`, `ModelRequest`, `ModelResponse`, `UserMessage`, `AssistantMessage`, and `ToolResult`.

- [ ] **Step 1: Write the fake SDK scaffold and failing construction/request tests**

Create `tests/test_openai_client.py` with this scaffold and tests:

```python
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from coding_agent.config import load_run_config
from coding_agent.messages import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResult,
    UserMessage,
)
from coding_agent.model import ModelClient
from coding_agent.openai_client import OpenAIResponsesClient


FAKE_KEY = "unit-test-key-never-send"


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
        response_id: str = "resp_test",
        output: tuple[FakeOutputItem, ...] = (),
        usage: object | None = None,
        status: str = "completed",
        error: object | None = None,
    ) -> None:
        self.id = response_id
        self.output = list(output)
        self.usage = usage
        self.status = status
        self.error = error


class FakeResponsesResource:
    def __init__(self, outcomes: tuple[object, ...]) -> None:
        self.outcomes = deque(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(deepcopy(kwargs))
        if not self.outcomes:
            raise AssertionError("unexpected Responses API call")
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeSDKClient:
    def __init__(self, *outcomes: object) -> None:
        self.responses = FakeResponsesResource(outcomes)


def text_item(text: str) -> FakeOutputItem:
    return FakeOutputItem(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [
                {"type": "output_text", "text": text, "annotations": []}
            ],
        }
    )


def text_response(text: str = "done") -> FakeResponse:
    return FakeResponse(output=(text_item(text),))


def test_public_client_matches_existing_protocol_and_signature() -> None:
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=FakeSDKClient(text_response()),
        sleeper=lambda delay: None,
    )

    assert isinstance(client, ModelClient)
    assert tuple(inspect.signature(OpenAIResponsesClient.complete).parameters) == (
        "self",
        "request",
    )


def test_constructor_disables_sdk_retries_and_does_not_store_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    fake_sdk = FakeSDKClient(text_response())

    def factory(**kwargs: object) -> FakeSDKClient:
        observed.update(kwargs)
        return fake_sdk

    monkeypatch.setattr("coding_agent.openai_client.OpenAI", factory)
    client = OpenAIResponsesClient(
        model=" gpt-test ",
        api_key=FAKE_KEY,
        sleeper=lambda delay: None,
    )

    assert observed == {"api_key": FAKE_KEY, "max_retries": 0}
    assert FAKE_KEY not in repr(client)
    assert FAKE_KEY not in repr(vars(client) if hasattr(client, "__dict__") else ())


@pytest.mark.parametrize(
    ("model", "api_key", "message"),
    [
        ("", FAKE_KEY, "model must be a non-empty string"),
        ("   ", FAKE_KEY, "model must be a non-empty string"),
        ("gpt-test", "", "api_key must be a non-empty string"),
        ("gpt-test", "   ", "api_key must be a non-empty string"),
    ],
)
def test_constructor_rejects_invalid_configuration_without_echoing_value(
    model: str,
    api_key: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message) as caught:
        OpenAIResponsesClient(model=model, api_key=api_key)

    assert FAKE_KEY not in str(caught.value)


def test_request_maps_complete_local_history_without_server_state() -> None:
    sdk = FakeSDKClient(text_response("mapped"))
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )
    request = ModelRequest(
        messages=(
            UserMessage("first"),
            AssistantMessage(content="prior answer"),
            UserMessage("follow-up"),
        ),
        max_output_tokens=321,
    )

    returned = client.complete(request)

    assert returned.text == "mapped"
    assert sdk.responses.calls == [
        {
            "model": "gpt-test",
            "input": [
                {"role": "user", "content": "first"},
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "prior answer",
                            "annotations": [],
                        }
                    ],
                },
                {"role": "user", "content": "follow-up"},
            ],
            "tools": [],
            "max_output_tokens": 321,
            "store": False,
            "include": ["reasoning.encrypted_content"],
        }
    ]
    sent = sdk.responses.calls[0]
    assert "conversation" not in sent
    assert "previous_response_id" not in sent


def test_existing_run_config_constructs_adapter_without_config_change(
    tmp_path: Path,
) -> None:
    config = load_run_config(
        task="inspect",
        workspace=tmp_path,
        model="gpt-test",
        verify_command=None,
        environ={"OPENAI_API_KEY": FAKE_KEY},
    )

    client = OpenAIResponsesClient(
        model=config.model,
        api_key=config.api_key,
        sdk_client=FakeSDKClient(text_response()),
        sleeper=lambda delay: None,
    )

    assert isinstance(client, ModelClient)
    assert FAKE_KEY not in repr(config)
    assert FAKE_KEY not in repr(client)
```

- [ ] **Step 2: Run RED and verify the expected reason**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -q
```

Expected: nonzero collection failure because `coding_agent.openai_client` does not exist. A syntax error, fixture error, real network attempt, or missing SDK is not the expected RED.

- [ ] **Step 3: Implement only construction and basic request/text mapping**

Create `src/coding_agent/openai_client.py` with the locked imports, public class/error declarations, private SDK structural Protocols, constructor validation, `UserMessage`/plain `AssistantMessage` mapping, an empty tool list, the exact `responses.create` keyword set, and enough message-output parsing to return the text fixture. Do not implement function calls, continuation, usage, retry, or error mapping in this GREEN.

The constructor must call `OpenAI(api_key=api_key.strip(), max_retries=0)` only when `sdk_client is None`. The adapter must not read environment variables.

- [ ] **Step 4: Run GREEN and Task 1–8 regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_path_safety.py tests\test_command_safety.py -q
```

Expected: both commands exit 0 with actual counts reported. The fake SDK records `store=False`; all local history is sent; no server conversation field exists; Task 1–8 remain green.

**Acceptance:** The adapter satisfies `ModelClient`, the real SDK boundary is constructed with zero internal retries, configuration values fit without changing config/CLI, and a complete local semantic history maps to a stateless Responses request.

---

### Task 2: Strict tools, tool-call/result mapping, and SDK-free continuation replay

**Files:** Modify `tests/test_openai_client.py` and `src/coding_agent/openai_client.py`.

**Interfaces:** Reuses `JSONObject`, `ToolCall`, `ToolResult`, registry schema shape, and existing opaque continuation fields. Adds only private `_OpenAIContinuationSegment`.

- [ ] **Step 1: Add failing strict-schema and function-output tests**

Append these fixtures/tests:

```python
TOOL_SCHEMA = {
    "name": "read_file",
    "description": "Read a UTF-8 file.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False,
    },
}


def function_item(
    call_id: str,
    name: str = "read_file",
    arguments: str = '{"path":"a.py"}',
) -> FakeOutputItem:
    return FakeOutputItem(
        {
            "id": f"fc_{call_id}",
            "type": "function_call",
            "call_id": call_id,
            "name": name,
            "arguments": arguments,
            "status": "completed",
        }
    )


def test_strict_registry_schema_maps_to_responses_function_tool() -> None:
    sdk = FakeSDKClient(text_response())
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )

    client.complete(
        ModelRequest(
            messages=(UserMessage("inspect"),),
            tool_schemas=(TOOL_SCHEMA,),
        )
    )

    assert sdk.responses.calls[0]["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a UTF-8 file.",
            "strict": True,
            "parameters": TOOL_SCHEMA["parameters"],
        }
    ]


@pytest.mark.parametrize(
    "schema",
    [
        {**TOOL_SCHEMA, "strict": False},
        {
            **TOOL_SCHEMA,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": True,
            },
        },
        {
            **TOOL_SCHEMA,
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": [],
                "additionalProperties": False,
            },
        },
        {key: value for key, value in TOOL_SCHEMA.items() if key != "description"},
        {**TOOL_SCHEMA, "extra": True},
    ],
)
def test_non_strict_or_malformed_tool_schema_is_rejected_before_sdk(
    schema: dict[str, object],
) -> None:
    sdk = FakeSDKClient(text_response())
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )

    with pytest.raises(
        FatalModelError,
        match="OpenAI Responses request is invalid: tool schema is not strict",
    ):
        client.complete(
            ModelRequest(
                messages=(UserMessage("inspect"),),
                tool_schemas=(schema,),
            )
        )

    assert sdk.responses.calls == []


def test_semantic_tool_call_and_result_map_with_canonical_json_and_call_id() -> None:
    sdk = FakeSDKClient(text_response())
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )
    call = ToolCall(
        call_id="call_1",
        name="read_file",
        arguments={"z": 2, "path": "雪.py"},
    )
    result = ToolResult(
        call_id="call_1",
        tool_name="read_file",
        status="ok",
        output="contents",
    )

    client.complete(
        ModelRequest(
            messages=(
                UserMessage("inspect"),
                AssistantMessage(content="checking", tool_calls=(call,)),
                result,
            ),
            tool_schemas=(TOOL_SCHEMA,),
        )
    )

    assert sdk.responses.calls[0]["input"] == [
        {"role": "user", "content": "inspect"},
        {
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [
                {
                    "type": "output_text",
                    "text": "checking",
                    "annotations": [],
                }
            ],
        },
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "read_file",
            "arguments": '{"path":"雪.py","z":2}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": result.to_json(),
        },
    ]
```

Add `FatalModelError` to the existing model imports before running RED.

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k "strict_registry or malformed_tool or semantic_tool" -q
```

Expected: nonzero because tools are still sent empty, malformed schemas are not rejected, and assistant calls/results are not mapped.

- [ ] **Step 3: Implement minimal strict-tool and semantic-call mapping**

Add exact schema validation/mapping and fallback `AssistantMessage.tool_calls`/`ToolResult` mapping. Use canonical JSON for call arguments and `ToolResult.to_json()` for output. Do not add continuation snapshots or response function parsing yet.

- [ ] **Step 4: Run GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k "strict_registry or malformed_tool or semantic_tool" -q
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_path_safety.py tests\test_command_safety.py -q
```

Expected: both exit 0; report actual counts.

- [ ] **Step 5: Add the failing continuation preservation/replay tests**

Append:

```python
def reasoning_item(item_id: str = "rs_1") -> FakeOutputItem:
    return FakeOutputItem(
        {
            "id": item_id,
            "type": "reasoning",
            "summary": [],
            "encrypted_content": "opaque-encrypted-test-payload",
            "status": "completed",
        }
    )


def test_continuation_is_sdk_free_cumulative_and_replayed_without_duplicates() -> None:
    first_provider_response = FakeResponse(
        response_id="resp_1",
        output=(reasoning_item(), function_item("call_1")),
    )
    sdk = FakeSDKClient(first_provider_response, text_response("finished"))
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )
    first_request = ModelRequest(
        messages=(UserMessage("inspect"),),
        tool_schemas=(TOOL_SCHEMA,),
    )

    first = client.complete(first_request)
    call = first.tool_calls[0]
    result = ToolResult(
        call_id=call.call_id,
        tool_name=call.name,
        status="ok",
        output="file contents",
    )
    second = client.complete(
        ModelRequest(
            messages=(
                UserMessage("inspect"),
                AssistantMessage(content=None, tool_calls=(call,)),
                result,
            ),
            tool_schemas=(TOOL_SCHEMA,),
            continuation_items=first.continuation_items,
        )
    )

    assert first.provider_response_id == "resp_1"
    assert len(first.continuation_items) == 1
    assert all(not isinstance(item, FakeOutputItem) for item in first.continuation_items)
    replay = sdk.responses.calls[1]["input"]
    assert replay == [
        {"role": "user", "content": "inspect"},
        reasoning_item().model_dump(
            mode="json", by_alias=True, exclude_none=False
        ),
        function_item("call_1").model_dump(
            mode="json", by_alias=True, exclude_none=False
        ),
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": result.to_json(),
        },
    ]
    assert sum(item.get("type") == "function_call" for item in replay) == 1
    assert len(second.continuation_items) == 2
    assert "opaque-encrypted-test-payload" not in repr(first)
    assert "opaque-encrypted-test-payload" not in first.to_json()


def test_continuation_function_call_order_must_match_local_history() -> None:
    sdk = FakeSDKClient(text_response())
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )
    call = ToolCall(call_id="different", name="read_file", arguments={})
    foreign = object()

    with pytest.raises(
        FatalModelError,
        match=(
            "OpenAI Responses request is invalid: "
            "continuation does not match local history"
        ),
    ):
        client.complete(
            ModelRequest(
                messages=(
                    UserMessage("inspect"),
                    AssistantMessage(content=None, tool_calls=(call,)),
                    ToolResult(
                        call_id="different",
                        tool_name="read_file",
                        status="ok",
                    ),
                ),
                continuation_items=(foreign,),
            )
        )

    assert sdk.responses.calls == []
```

- [ ] **Step 6: Run continuation RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k continuation -q
```

Expected: nonzero because function-call output parsing and `_OpenAIContinuationSegment` do not yet exist.

- [ ] **Step 7: Implement the minimum continuation segment and function-call parser**

Add `_OpenAIContinuationSegment`, JSON snapshot validation, cumulative segment creation, segment-to-message-index replay, call-ID consistency validation, and enough `function_call` parsing to create `ToolCall`. Store plain copied dictionaries, never SDK items. Do not implement general invalid-response matrices, usage, or retry yet.

- [ ] **Step 8: Run continuation GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k "continuation or strict_registry or malformed_tool or semantic_tool" -q
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_path_safety.py tests\test_command_safety.py -q
```

Expected: both exit 0. Continuation is cumulative, SDK-free, hidden from repr/JSON, correctly interleaved, and not duplicated.

**Acceptance:** strict schemas and all call/result inputs have the exact Responses shape; `call_id` is maintained; current output items are preserved as plain opaque segments and replayed in local-history order.

---

### Task 3: Complete text, ordered function-call, usage, and invalid-payload parsing

**Files:** Modify `tests/test_openai_client.py` and `src/coding_agent/openai_client.py`.

**Interfaces:** Produces existing `ModelResponse`, `ToolCall`, and `TokenUsage`; introduces only `InvalidOpenAIResponseError` already locked above.

- [ ] **Step 1: Add failing successful-shape tests**

Append:

```python
from coding_agent.messages import TokenUsage


def response_for(*items: FakeOutputItem, usage: object | None = None) -> FakeResponse:
    return FakeResponse(output=tuple(items), usage=usage)


def complete_once(response: FakeResponse) -> ModelResponse:
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=FakeSDKClient(response),
        sleeper=lambda delay: None,
    )
    return client.complete(ModelRequest(messages=(UserMessage("task"),)))


def test_text_output_blocks_and_messages_are_joined_in_order() -> None:
    first = FakeOutputItem(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [
                {"type": "output_text", "text": "alpha", "annotations": []},
                {"type": "output_text", "text": " beta", "annotations": []},
            ],
        }
    )
    second = text_item(" gamma")

    response = complete_once(response_for(first, second))

    assert response.text == "alpha beta gamma"
    assert response.tool_calls == ()


def test_single_function_call_parses_json_object_and_call_id() -> None:
    response = complete_once(response_for(function_item("call_1")))

    assert response.text is None
    assert response.tool_calls == (
        ToolCall(
            call_id="call_1",
            name="read_file",
            arguments={"path": "a.py"},
        ),
    )


def test_multiple_function_calls_preserve_provider_order() -> None:
    response = complete_once(
        response_for(
            function_item("call_2", arguments='{"path":"b.py"}'),
            function_item("call_1", arguments='{"path":"a.py"}'),
        )
    )

    assert [call.call_id for call in response.tool_calls] == ["call_2", "call_1"]
    assert [call.arguments["path"] for call in response.tool_calls] == [
        "b.py",
        "a.py",
    ]


def test_text_and_function_calls_are_both_preserved() -> None:
    response = complete_once(
        response_for(
            text_item("I will inspect."),
            function_item("call_1"),
        )
    )

    assert response.text == "I will inspect."
    assert [call.call_id for call in response.tool_calls] == ["call_1"]


def test_usage_and_provider_response_id_map_to_internal_types() -> None:
    usage = SimpleNamespace(
        input_tokens=12,
        output_tokens=7,
        total_tokens=19,
    )

    response = complete_once(
        FakeResponse(
            response_id="resp_usage",
            output=(text_item("done"),),
            usage=usage,
        )
    )

    assert response.provider_response_id == "resp_usage"
    assert response.usage == TokenUsage(
        input_tokens=12,
        output_tokens=7,
        total_tokens=19,
    )
```

- [ ] **Step 2: Run successful-shape RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k "joined_in_order or single_function or multiple_function or both_preserved or usage_and_provider" -q
```

Expected: nonzero because full content aggregation, ordered multiple calls, and usage are not all implemented.

- [ ] **Step 3: Implement the minimum successful parser**

Complete output iteration for `reasoning`, completed assistant `message`/`output_text`, and completed `function_call`. Parse arguments with `json.loads`, require an object, preserve order, and map optional usage. Wrap constructor validation failures from `ToolCall`, `TokenUsage`, or `ModelResponse` as `InvalidOpenAIResponseError` with stable structural text.

- [ ] **Step 4: Run successful-shape GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k "joined_in_order or single_function or multiple_function or both_preserved or usage_and_provider" -q
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_path_safety.py tests\test_command_safety.py -q
```

Expected: both exit 0 with real counts.

- [ ] **Step 5: Add failing illegal-response tests**

Add `InvalidOpenAIResponseError` to imports and append:

```python
@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (
            FakeResponse(response_id="", output=(text_item("x"),)),
            "missing response id",
        ),
        (
            FakeResponse(output=(text_item("x"),), status="incomplete"),
            "response status is not completed",
        ),
        (
            FakeResponse(
                output=(text_item("x"),),
                error=SimpleNamespace(code="provider_error"),
            ),
            "response contains an error",
        ),
        (
            FakeResponse(output=()),
            "no text or function call output",
        ),
        (
            response_for(
                FakeOutputItem({"id": "x", "type": "web_search_call"})
            ),
            "unsupported output item type",
        ),
        (
            response_for(
                FakeOutputItem(
                    {
                        "id": "msg_bad",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "refusal", "refusal": "no"}],
                    }
                )
            ),
            "unsupported message content type",
        ),
        (
            response_for(
                FakeOutputItem(
                    {
                        "id": "msg_missing",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                    }
                )
            ),
            "message content is missing",
        ),
        (
            response_for(function_item("call_1", arguments="not-json")),
            "function arguments are not valid JSON",
        ),
        (
            response_for(function_item("call_1", arguments="[]")),
            "function arguments must be an object",
        ),
        (
            response_for(
                function_item("call_1"),
                function_item("call_1"),
            ),
            "duplicate function call id",
        ),
    ],
)
def test_invalid_response_shapes_raise_stable_internal_error(
    response: FakeResponse,
    reason: str,
) -> None:
    with pytest.raises(
        InvalidOpenAIResponseError,
        match=f"invalid OpenAI Responses payload: {reason}",
    ):
        complete_once(response)


def test_missing_output_item_type_is_rejected_without_payload_echo() -> None:
    secret = "sensitive-provider-payload"
    item = FakeOutputItem({"id": secret})

    with pytest.raises(InvalidOpenAIResponseError) as caught:
        complete_once(response_for(item))

    rendered = str(caught.value)
    assert rendered == "invalid OpenAI Responses payload: missing output item type"
    assert secret not in rendered


def test_response_missing_required_output_field_is_stable() -> None:
    response = FakeResponse(output=(text_item("unused"),))
    del response.output

    with pytest.raises(
        InvalidOpenAIResponseError,
        match="invalid OpenAI Responses payload: response output is missing",
    ):
        complete_once(response)


@pytest.mark.parametrize(
    "usage",
    [
        SimpleNamespace(input_tokens=-1, output_tokens=1, total_tokens=0),
        SimpleNamespace(input_tokens=1, output_tokens=True, total_tokens=2),
        SimpleNamespace(input_tokens=1, total_tokens=1),
    ],
)
def test_malformed_usage_is_rejected(usage: object) -> None:
    with pytest.raises(
        InvalidOpenAIResponseError,
        match="invalid OpenAI Responses payload: invalid usage",
    ):
        complete_once(
            FakeResponse(output=(text_item("done"),), usage=usage)
        )
```

- [ ] **Step 6: Run invalid-payload RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k "invalid_response or missing_output or malformed_usage" -q
```

Expected: nonzero because incomplete, unknown, missing, malformed, duplicate, and empty semantic outputs do not yet share the locked error mapping.

- [ ] **Step 7: Implement deterministic validation and errors**

Add explicit structural getters/validators. Never use unchecked chained attribute access that leaks `AttributeError`; map every missing field to one locked structural reason. Validate response and item completion before returning. Do not retry parsing failures.

- [ ] **Step 8: Run invalid-payload GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k "invalid_response or missing_output or malformed_usage" -q
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_path_safety.py tests\test_command_safety.py -q
```

Expected: both exit 0. Errors are typed, stable, and sanitized.

**Acceptance:** text, one/many ordered calls, combined output, `call_id`, usage, response ID, and continuation are mapped; malformed/unknown/empty responses fail deterministically without payload leakage.

---

### Task 4: Exact transient retry policy, permanent failures, and secret safety

**Files:** Modify `tests/test_openai_client.py` and `src/coding_agent/openai_client.py`.

**Interfaces:** Reuses existing `TransientModelError` and `FatalModelError`; no new retry configuration API.

- [ ] **Step 1: Add fake official exception helpers and retry RED tests**

Add these imports:

```python
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

from coding_agent.model import FatalModelError, TransientModelError
```

Append fake subclasses that do not construct an HTTP client/request:

```python
class FakeRateLimitError(RateLimitError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeServerError(InternalServerError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeTimeoutError(APITimeoutError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeConnectionError(APIConnectionError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeAuthenticationError(AuthenticationError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakePermissionError(PermissionDeniedError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeBadRequestError(BadRequestError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeNotFoundError(NotFoundError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeUnprocessableError(UnprocessableEntityError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)
```

Append tests:

```python
@pytest.mark.parametrize(
    "error_type",
    [
        FakeRateLimitError,
        FakeServerError,
        FakeTimeoutError,
        FakeConnectionError,
    ],
)
def test_transient_errors_retry_twice_then_recover_in_exact_order(
    error_type: type[Exception],
) -> None:
    secret = "provider-error-must-not-leak"
    delays: list[float] = []
    sdk = FakeSDKClient(
        error_type(secret),
        error_type(secret),
        text_response("recovered"),
    )
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=sdk,
        sleeper=delays.append,
    )

    response = client.complete(
        ModelRequest(messages=(UserMessage("retry"),))
    )

    assert response.text == "recovered"
    assert len(sdk.responses.calls) == 3
    assert delays == [0.25, 0.50]


def test_third_transient_failure_raises_stable_error_without_fourth_call() -> None:
    secret = "provider-error-must-not-leak"
    delays: list[float] = []
    sdk = FakeSDKClient(
        FakeRateLimitError(secret),
        FakeRateLimitError(secret),
        FakeRateLimitError(secret),
    )
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=sdk,
        sleeper=delays.append,
    )

    with pytest.raises(TransientModelError) as caught:
        client.complete(ModelRequest(messages=(UserMessage("retry"),)))

    assert str(caught.value) == (
        "OpenAI Responses request failed after 3 attempts: "
        "transient provider error"
    )
    assert secret not in str(caught.value)
    assert FAKE_KEY not in repr(caught.value)
    assert len(sdk.responses.calls) == 3
    assert delays == [0.25, 0.50]
```

- [ ] **Step 2: Run retry RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k "transient_errors or third_transient" -q
```

Expected: nonzero because `complete` currently makes one attempt and exposes a fake SDK exception.

- [ ] **Step 3: Implement only retry classification and fixed delays**

Wrap only the SDK create call in a three-attempt loop. Parse only after a successful call, outside the exception classification branch. Use the locked official exception tuples and fixed delay tuple `(0.25, 0.50)`. Do not catch `BaseException`.

- [ ] **Step 4: Run retry GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k "transient_errors or third_transient" -q
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_path_safety.py tests\test_command_safety.py -q
```

Expected: both exit 0; exact fake SDK call counts and delays prove the retry ceiling.

- [ ] **Step 5: Add permanent-error, interruption, and leakage RED tests**

Append:

```python
@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (
            FakeAuthenticationError("Authorization: Bearer " + FAKE_KEY),
            "OpenAI Responses request failed: authentication rejected",
        ),
        (
            FakePermissionError("Authorization: Bearer " + FAKE_KEY),
            "OpenAI Responses request failed: authentication rejected",
        ),
        (
            FakeBadRequestError("bad request includes " + FAKE_KEY),
            "OpenAI Responses request failed: request rejected",
        ),
        (
            FakeUnprocessableError("invalid payload includes " + FAKE_KEY),
            "OpenAI Responses request failed: request rejected",
        ),
        (
            FakeNotFoundError("unknown model includes " + FAKE_KEY),
            "OpenAI Responses request failed: model or endpoint not found",
        ),
    ],
)
def test_permanent_provider_errors_do_not_retry_or_leak(
    exception: Exception,
    expected: str,
) -> None:
    delays: list[float] = []
    sdk = FakeSDKClient(exception, text_response("must not run"))
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=sdk,
        sleeper=delays.append,
    )

    with pytest.raises(FatalModelError) as caught:
        client.complete(ModelRequest(messages=(UserMessage("fail"),)))

    assert str(caught.value) == expected
    assert FAKE_KEY not in str(caught.value)
    assert "Authorization" not in str(caught.value)
    assert len(sdk.responses.calls) == 1
    assert delays == []


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), SystemExit(130)])
def test_base_exceptions_are_not_swallowed(interrupt: BaseException) -> None:
    sdk = FakeSDKClient(interrupt)
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )

    with pytest.raises(type(interrupt)):
        client.complete(ModelRequest(messages=(UserMessage("interrupt"),)))

    assert len(sdk.responses.calls) == 1


def test_parse_failure_is_not_retried() -> None:
    sdk = FakeSDKClient(
        FakeResponse(output=()),
        text_response("must not run"),
    )
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )

    with pytest.raises(InvalidOpenAIResponseError):
        client.complete(ModelRequest(messages=(UserMessage("parse"),)))

    assert len(sdk.responses.calls) == 1
```

- [ ] **Step 6: Run permanent-error RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k "permanent_provider or base_exceptions or parse_failure" -q
```

Expected: nonzero until all permanent mappings, non-retry parsing, and `BaseException` propagation are exact.

- [ ] **Step 7: Implement minimal permanent mapping and sanitization**

Add ordered exception mapping so specialized permanent exceptions are checked before broader `OpenAIError`/`APIStatusError`. Build only constant public messages. Never concatenate exception content. Ensure parsing remains outside retry.

- [ ] **Step 8: Run permanent-error GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k "permanent_provider or base_exceptions or parse_failure" -q
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_path_safety.py tests\test_command_safety.py -q
```

Expected: both exit 0. Permanent errors make exactly one call; parse errors make exactly one call; interruptions propagate; no key/header/provider detail is present.

**Acceptance:** 429, 5xx, timeout, and connection errors have exactly three maximum attempts; auth/permission/bad-request failures have one; errors and repr are sanitized; SDK internal retry is disabled.

---

### Task 5: Offline boundary, SDK isolation, and final Task 9 verification

**Files:** Modify `tests/test_openai_client.py` for the boundary test; otherwise verify only. Task 9 remains `进行中`.

**Interfaces:** Verifies exact signatures and isolation; no new behavior.

- [ ] **Step 1: Add and run the offline boundary test**

Append:

```python
import os
import subprocess
import sys


def test_adapter_tests_use_injected_client_without_env_key_or_network() -> None:
    script = r'''
import os
import socket

os.environ.pop("OPENAI_API_KEY", None)

def forbidden(*args, **kwargs):
    raise AssertionError("network access attempted")

socket.create_connection = forbidden

from coding_agent.messages import ModelRequest, UserMessage
from coding_agent.openai_client import OpenAIResponsesClient

class Item:
    type = "message"
    role = "assistant"
    status = "completed"
    content = [{"type": "output_text", "text": "offline", "annotations": []}]
    def model_dump(self, **kwargs):
        return {
            "id": "msg_offline",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": self.content,
        }

class Responses:
    def create(self, **kwargs):
        return type("Response", (), {
            "id": "resp_offline",
            "status": "completed",
            "error": None,
            "output": [Item()],
            "usage": None,
        })()

class Client:
    responses = Responses()

adapter = OpenAIResponsesClient(
    model="gpt-test",
    api_key="offline-fake-value",
    sdk_client=Client(),
    sleeper=lambda delay: None,
)
result = adapter.complete(ModelRequest(messages=(UserMessage("offline"),)))
assert result.text == "offline"
'''
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py::test_adapter_tests_use_injected_client_without_env_key_or_network -q
```

Expected: exit 0 and `1 passed`; no environment key and no socket call.

- [ ] **Step 2: Run the complete Task 9 suite**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -q
```

Expected: exit 0. Report actual passed/failed/skipped/warning counts; do not use an estimate from this plan.

- [ ] **Step 3: Run focused continuation, mapping, retry, and invalid-response matrices**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k "request or schema or tool_call or continuation or usage" -q
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py -k "transient or permanent or invalid or malformed or leak or offline" -q
```

Expected: both exit 0. Report actual selection counts and zero skip/xfail.

- [ ] **Step 4: Run every existing Task 1–8 suite explicitly**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py tests\tools\test_write_tools.py -q
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\test_command_safety.py -q
```

Expected: every command exits 0. Report each real count, warning, and skip. Windows link/process-tree tests must not be replaced with skips.

- [ ] **Step 5: Run the complete repository suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit 0 with fresh real totals.

- [ ] **Step 6: Verify public signatures, Protocol, and SDK isolation**

```powershell
.\.venv\Scripts\python.exe -c "import inspect; from coding_agent.messages import ModelRequest, ModelResponse; from coding_agent.model import ModelClient; from coding_agent.openai_client import OpenAIResponsesClient, InvalidOpenAIResponseError; assert str(inspect.signature(OpenAIResponsesClient.complete)) == '(self, request: \'ModelRequest\') -> \'ModelResponse\''; assert isinstance(OpenAIResponsesClient(model='m', api_key='fake', sdk_client=type('C', (), {'responses': object()})(), sleeper=lambda _: None), ModelClient); print('Task 9 public interface verified')"

$sdkImports = Get-ChildItem -Path src\coding_agent -Recurse -File -Filter *.py | Select-String -Pattern '^\s*(from\s+openai|import\s+openai)'
$sdkImports
```

Expected: signature/Protocol command exits 0. SDK import output names only `src\coding_agent\openai_client.py`; no message, model, Agent, tool, config, CLI, or safety module imports it.

- [ ] **Step 7: Audit exact API family and stateless parameters**

```powershell
$adapter = Get-Item src\coding_agent\openai_client.py
$required = $adapter | Select-String -Pattern 'responses\.create|store=False|max_retries=0|reasoning\.encrypted_content|function_call_output'
$forbidden = $adapter | Select-String -Pattern 'chat\.completions|ChatCompletion|previous_response_id\s*=|conversation\s*=|client\.conversations|server.*file|code_interpreter'
$required
if ($forbidden) { $forbidden; throw 'forbidden API or server-state usage found' }
```

Expected: required patterns are present; forbidden scan produces no output. Manual diff review confirms the actual request dictionary also omits conversation/previous response keys and always uses `store=False`.

- [ ] **Step 8: Audit types, dependencies, network-test boundary, and deferred scope**

```powershell
git diff -- pyproject.toml src\coding_agent\messages.py src\coding_agent\model.py src\coding_agent\agent.py src\coding_agent\state.py src\coding_agent\config.py src\coding_agent\cli.py src\coding_agent\safety.py src\coding_agent\tools

.\.venv\Scripts\python.exe -m pip show openai

$deferred = Get-Item src\coding_agent\openai_client.py | Select-String -Pattern 'ContextManager|TerminationPolicy|VerificationGate|validation_index|SUCCESS|jsonl|final report|AgentRunner|ToolRegistry\('
if ($deferred) { $deferred; throw 'deferred Task 10-12 or Agent wiring found' }
```

Expected: protected-file diff is empty; `openai` is already installed and no dependency file changed; deferred scan is empty. `ToolRegistry` may appear only in test fixtures, never production adapter construction.

- [ ] **Step 9: Scan credentials, unfinished markers, test suppression, and frameworks**

```powershell
$scanFiles = @(Get-ChildItem -Path src,tests -Recurse -File) + @(Get-Item AGENTS.md,DESIGN.md,TASKS.md,pyproject.toml,.gitignore)
$credentials = $scanFiles | Select-String -Pattern 'sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{12,}|Authorization\s*[:=]\s*["''][^"'']+["'']'
if ($credentials) { $credentials; throw 'credential-like content found' }

$unfinishedPattern = ('TO' + 'DO') + '|' + ('TB' + 'D') + '|Not' + 'ImplementedError'
$unfinished = Get-ChildItem -Path src,tests,docs\superpowers\plans\Task9.md -Recurse -File | Select-String -Pattern $unfinishedPattern
if ($unfinished) { $unfinished; throw 'unfinished marker found' }

$suppressed = Get-ChildItem -Path tests -Recurse -File -Filter *.py | Select-String -Pattern 'pytest\.skip|pytest\.xfail|@pytest\.mark\.skip|@pytest\.mark\.xfail'
if ($suppressed) { $suppressed; throw 'skip or xfail found' }

$frameworks = @(Get-ChildItem -Path src,tests -Recurse -File) + @(Get-Item pyproject.toml) | Select-String -Pattern 'langchain|llamaindex|autogen|crewai|agents sdk|agent sdk'
if ($frameworks) { $frameworks; throw 'prohibited framework found' }
```

Expected: no credential-like content, unfinished markers, test suppression, or Agent framework. The literal fake values in tests are short non-key sentinels and must never resemble a production key.

- [ ] **Step 10: Check whitespace, status, and complete diff**

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff -- src\coding_agent\openai_client.py tests\test_openai_client.py TASKS.md
```

Expected: `git diff --check` exits 0; only the two new Task 9 files, two Task status values, and the approved plan are changed; no staged entry exists. Review every line for secret interpolation, SDK object escape, duplicated message history, hidden server state, accidental real network code in tests, and Task 10–12 scope.

- [ ] **Step 11: Complete the Task 9 acceptance matrix**

Record fresh evidence for every row:

| Acceptance row | Required evidence |
| --- | --- |
| Existing `ModelClient` contract | `test_public_client_matches_existing_protocol_and_signature` plus signature audit |
| Official SDK Responses API | constructor factory test, `responses.create` source audit, no Chat Completions match |
| `store=False` | exact recorded request assertion |
| No conversation/previous response state | exact request key assertions and source audit |
| Complete local history mapping | `test_request_maps_complete_local_history_without_server_state` |
| Strict ordered tool schemas | strict schema test plus malformed-schema pre-call rejection |
| Tool-call/result input and `call_id` | semantic mapping test and continuation replay assertion |
| Text parsing | ordered text-block/message test |
| One function call | single function test |
| Multiple ordered calls | multiple call order test |
| Text plus calls | combined-output test |
| Usage and response ID | usage/provider response test |
| Continuation preservation and resend | cumulative SDK-free replay test |
| No duplicate replay | exact input list and one-function-call count |
| Missing/unknown/corrupt output | invalid response matrix and payload non-echo test |
| 429/5xx/timeout/connection retry | parameterized exact-attempt and delay tests |
| Retry exhaustion | three-call/no-fourth-call test |
| Auth/permission/request non-retry | permanent-provider parameterized test |
| Parse failure non-retry | parse-failure call-count test |
| No secret/header/request leakage | constructor, permanent/transient, repr, and credential scans |
| Offline defaults | injected-client fresh-process network guard |
| SDK isolation | production import scan and protected-file diff |
| Task 1–8 regression | explicit component suites and full repository suite |
| Scope | protected module diff and deferred-feature scan |

If any row lacks fresh evidence, keep Task 9 `进行中`, report the exact gap, and stop.

- [ ] **Step 12: Stop for user review**

Do not change Task 9 to `已完成`; do not stage, commit, push, call a branch-finishing workflow, or begin Task 10. Report every RED/GREEN loop, actual command exit codes/counts/warnings/skips, the complete modified-file list, dependency/API/secret/offline/scope audits, `git status`, acceptance matrix, and any unverifiable item. Wait for explicit user review and submission authorization.

**Acceptance:** All Task 9 and Task 1–8 tests are freshly green, request/response/retry behavior is proven with injected fakes, the SDK remains isolated, the diff is in scope, and Task 9 remains active for user review.

---

## Explicitly deferred boundaries and known risks

- Task 9 does not connect the adapter to `cli.py`; the CLI still validates configuration only. A later approved wiring task must construct the client from `RunConfig` without weakening Task 8 startup authorization.
- Task 9 performs physical SDK retries inside one logical `ModelClient.complete` call. The current Task 4 `model_call_count` counts logical calls, not physical attempts. Task 10 explicitly owns the final total-attempt budget and must reconcile this using an approved design change; Task 9 does not alter Agent state or termination policy.
- Task 10 context compression must discard all `_OpenAIContinuationSegment` objects when it replaces the active history segment. Until then, cumulative continuation remains memory-only for the active run.
- Task 12 must never serialize or log continuation segments, encrypted reasoning content, provider requests, or authentication material. Existing repr/JSON exclusion is verified now; the logger itself is not implemented.
- `pyproject.toml` currently declares `openai` without a version pin. The plan targets the installed official SDK 3.5.0 public `OpenAI`, `responses.create`, and exception APIs while keeping fake tests structural. Dependency pinning is outside Task 9 and requires a separate approved dependency decision.
- No real API smoke test is part of automated acceptance. A future explicitly authorized manual smoke test may validate account/model availability, but its result must be reported separately from offline tests and must never expose credentials.

## Plan self-review checklist

- Every Task 9 requirement has a named test and final acceptance row.
- The only production SDK import is in `openai_client.py`.
- `ModelClient.complete(ModelRequest) -> ModelResponse` and all Task 2 types are reused without redefinition.
- Request mapping always uses Responses API, `store=False`, complete local history, strict tools, and no conversation/previous-response state.
- Tool results use `function_call_output` and preserve `call_id`.
- Continuation segments are cumulative, SDK-free, repr-hidden, locally ordered, and not duplicated.
- Text, one/many ordered calls, combined output, usage, response IDs, no-text semantics, unknown types, missing fields, and corrupt structures are deterministic.
- Adapter retries only the locked transient failures, at most twice, with exact delays and SDK retries disabled.
- Permanent failures and parsing failures are not retried; `BaseException` is not swallowed.
- No exception or repr uses API keys, Authorization headers, provider exception strings, request bodies, or continuation payloads.
- Tests inject fake clients/responses/exceptions, clear the environment key for the fresh-process boundary, and forbid socket access.
- No Task 10 context/termination, Task 11 verification, Task 12 logging/reporting, CLI execution, Agent framework, server-hosted tool, new dependency, or remote operation is introduced.
- The Task 8 status remainder is handled only at approved execution start, and Task 9 remains `进行中` at the final stop.
- The plan contains no placeholder instruction or undefined production interface.
- No branch, worktree, subagent, stage, commit, push, or remote command appears as an implementation action.

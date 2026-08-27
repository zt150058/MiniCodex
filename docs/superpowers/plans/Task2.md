# Agent Message Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task after explicit user approval. Steps use checkbox (`- [ ]`) syntax for tracking. Do not use subagents or worktrees.

**Goal:** Implement only `TASKS.md` Task 2: provider-neutral user/assistant messages, tool calls/results, model requests/responses, deterministic JSON serialization, and local invariant validation.

**Architecture:** Add one standard-library-only module, `coding_agent.messages`, containing frozen dataclasses and explicit serialization methods. Python objects use `call_id`; the approved external JSON shape for `ToolCall` uses key `"id"`, while `ToolResult` uses `"call_id"`. `ModelRequest` validates complete call/result pairing, and `ModelResponse` validates ordered, unique tool calls without introducing `ModelClient` or an Agent loop.

**Tech Stack:** Python 3.11+, `dataclasses`, `json`, `math`, `typing`, and pytest. No new dependency and no OpenAI SDK import.

**Spec:** `DESIGN.md` sections 5, 7, 8, 10, and 16; `TASKS.md` Task 2; repository rules in `AGENTS.md`.

## Global Constraints

- Production code stays under `src/coding_agent/`; tests stay under `tests/`.
- Create only `src/coding_agent/messages.py` and `tests/test_messages.py` for behavior.
- `TASKS.md` may receive status-only edits during approved execution.
- Do not create `model.py`, `state.py`, `agent.py`, tools, an OpenAI adapter, or context logic.
- Do not import `openai` or any Agent framework from `messages.py`.
- Use only the standard library in production and the already-approved pytest test dependency.
- Every constructor validates its runtime invariants; type annotations alone are not treated as validation.
- Every nullable serialized field is emitted with JSON `null`; nullable keys are never omitted.
- Opaque continuation items are the sole exception: they are in-memory-only, excluded from `repr`, equality, dictionaries, and JSON.
- Do not commit, push, stage, rewrite history, or operate on a remote.
- Keep Task 2 `进行中` until the user accepts the implementation and real verification evidence.

---

## File Map

| Path | Action | Responsibility |
| --- | --- | --- |
| `src/coding_agent/messages.py` | Create | JSON aliases, validation helpers, message/tool/model dataclasses, pairing validation, deterministic serialization |
| `tests/test_messages.py` | Create | Construction, invariant, JSON round-trip, explicit-null, pairing, duplicate-ID, and provider-boundary tests |
| `TASKS.md` | Status-only modification during execution | Record Task 1 as `已完成` and Task 2 as `进行中`; no requirement text changes |

No Task 1 production file is modified.

## Public Type Contract

All tuple fields preserve input order. Each public dataclass is `@dataclass(frozen=True, slots=True)`.

### JSON aliases

```python
JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]
ToolStatus: TypeAlias = Literal["ok", "error", "rejected"]
```

JSON validation rejects non-string object keys, non-finite floats, and values outside these aliases.

### `ToolCall`

```python
@dataclass(frozen=True, slots=True)
class ToolCall(_JsonMixin):
    call_id: str
    name: str
    arguments: JSONObject
```

Invariants:

- `call_id.strip()` is non-empty and stored trimmed.
- `name.strip()` is non-empty and stored trimmed.
- `arguments` is copied and recursively validated as a JSON object.

Serialized result:

```json
{"arguments":{"path":"src/example.py"},"id":"call_123","kind":"tool_call","name":"read_file"}
```

The Python field is `call_id`; only the JSON representation uses `"id"` to match `DESIGN.md`.

### `ToolResultMetadata`

```python
@dataclass(frozen=True, slots=True)
class ToolResultMetadata(_JsonMixin):
    exit_code: int | None = None
    timed_out: bool = False
    truncated: bool = False
    duration_ms: int = 0
    changed_paths: tuple[str, ...] = ()
```

Invariants:

- `exit_code` is `None` or an integer; booleans are rejected as integers.
- `timed_out` and `truncated` are booleans.
- `duration_ms` is an integer greater than or equal to zero; booleans are rejected.
- Each changed path is a non-empty string; duplicates are rejected while original order is preserved.

Default serialized result:

```json
{"changed_paths":[],"duration_ms":0,"exit_code":null,"timed_out":false,"truncated":false}
```

### `ToolResult`

```python
@dataclass(frozen=True, slots=True)
class ToolResult(_JsonMixin):
    call_id: str
    tool_name: str
    status: ToolStatus
    output: str | None = None
    error: str | None = None
    metadata: ToolResultMetadata = field(default_factory=ToolResultMetadata)
```

Invariants:

- `call_id` and `tool_name` are trimmed and non-empty.
- `status` is exactly `ok`, `error`, or `rejected`.
- `output` is `None` or a string.
- `status="ok"` requires `error is None`.
- `status="error"` or `status="rejected"` requires a non-empty `error` string.
- `metadata` is a `ToolResultMetadata` instance.

Serialized result includes both nullable keys:

```json
{"call_id":"call_123","error":null,"kind":"tool_result","metadata":{"changed_paths":[],"duration_ms":8,"exit_code":null,"timed_out":false,"truncated":false},"output":"contents","status":"ok","tool_name":"read_file"}
```

### `UserMessage`

```python
@dataclass(frozen=True, slots=True)
class UserMessage(_JsonMixin):
    content: str
```

`content` must contain at least one non-whitespace character and is otherwise preserved. JSON is:

```json
{"content":"inspect the project","kind":"user"}
```

### `AssistantMessage`

```python
@dataclass(frozen=True, slots=True)
class AssistantMessage(_JsonMixin):
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
```

Invariants:

- `content` is `None` or a non-whitespace string.
- At least one of non-null `content` or a non-empty `tool_calls` tuple is required.
- Every item is a `ToolCall`.
- `call_id` values are unique within the message.

Tool-only JSON explicitly preserves null:

```json
{"content":null,"kind":"assistant","tool_calls":[{"arguments":{"path":"."},"id":"call_1","kind":"tool_call","name":"list_directory"}]}
```

### `TokenUsage`

```python
@dataclass(frozen=True, slots=True)
class TokenUsage(_JsonMixin):
    input_tokens: int
    output_tokens: int
    total_tokens: int
```

All values must be non-boolean integers greater than or equal to zero. No arithmetic equality is imposed because the provider adapter may later report provider-defined totals.

### `ModelRequest`

```python
Message: TypeAlias = UserMessage | AssistantMessage | ToolResult

@dataclass(frozen=True, slots=True)
class ModelRequest(_JsonMixin):
    messages: tuple[Message, ...]
    tool_schemas: tuple[JSONObject, ...] = ()
    max_output_tokens: int = 4096
    continuation_items: tuple[object, ...] = field(
        default=(), repr=False, compare=False
    )
```

Invariants:

- `messages` is non-empty and contains only `UserMessage`, `AssistantMessage`, or `ToolResult`.
- `max_output_tokens` is a non-boolean positive integer.
- Each tool schema is a valid JSON object and is copied.
- A `ToolCall.call_id` is globally unique across request messages.
- Each `ToolResult` matches one earlier unresolved `ToolCall` by `call_id`.
- The matching `ToolResult.tool_name` equals the original `ToolCall.name`.
- A call receives exactly one result; unmatched, repeated, or unresolved calls are rejected.
- `continuation_items` accepts opaque objects but is in-memory-only.

Serialized result includes `messages`, `tool_schemas`, and `max_output_tokens`; it omits `continuation_items` by design.

### `ModelResponse`

```python
@dataclass(frozen=True, slots=True)
class ModelResponse(_JsonMixin):
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    usage: TokenUsage | None = None
    provider_response_id: str | None = None
    continuation_items: tuple[object, ...] = field(
        default=(), repr=False, compare=False
    )
```

Invariants:

- `text` is `None` or a string; empty text is preserved so later response parsing can classify incomplete output.
- `tool_calls` is ordered and contains only `ToolCall` values with unique `call_id` values.
- `usage` is `None` or `TokenUsage`.
- `provider_response_id` is `None` or a non-empty string.
- `continuation_items` is in-memory-only and excluded from serialization.

Empty response serialization uses explicit nulls:

```json
{"provider_response_id":null,"text":null,"tool_calls":[],"usage":null}
```

### Serialization interface

Every public dataclass exposes:

```python
def to_dict(self) -> JSONObject: ...

@classmethod
def from_dict(cls, payload: Mapping[str, object]) -> Self: ...

def to_json(self) -> str: ...

@classmethod
def from_json(cls, payload: str) -> Self: ...
```

`to_json()` uses exactly:

```python
json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

`from_json()` requires a JSON object and delegates to `from_dict()`. Every `from_dict()` rejects missing required keys, unexpected keys, incorrect field types, and invalid nested objects. Round-trip equality covers all semantic fields; opaque continuation items intentionally deserialize as `()`.

---

## Acceptance Matrix

| Task 2 criterion | Planned proof |
| --- | --- |
| User and assistant message construction | `test_user_and_assistant_messages_round_trip` |
| Tool call/result pairing by `call_id` | `test_model_request_accepts_paired_tool_result` plus unmatched/name-mismatch tests |
| Only three result statuses | `test_tool_result_rejects_invalid_status` |
| Explicit JSON null | metadata, assistant, tool result, and model response serialization assertions |
| Stable JSON round-trip | Per-type `to_json()`/`from_json()` equality tests |
| Empty `call_id` rejected | parameterized ToolCall/ToolResult tests |
| Duplicate `call_id` rejected | AssistantMessage, ModelResponse, and ModelRequest tests |
| Missing required fields rejected | `test_from_dict_rejects_missing_required_field` |
| No OpenAI SDK boundary violation | fresh-process import guard in `test_messages_module_imports_without_openai` |
| No ModelClient or Agent loop | final source-file and import audit |

---

### Task 0: Align task status at execution start

**Files:**
- Modify: `TASKS.md`, status fields only

**Interfaces:** None.

- [ ] **Step 1: Verify the baseline discrepancy**

Run:

```powershell
git log -1 --oneline
git status --short
Select-String -Path .\TASKS.md -Pattern '^## 1\.|^## 2\.|`进行中`|`已完成`'
```

Expected: the latest commit contains Task 1 work; the working tree is clean before this plan executes; Task 1 may still show `进行中` even though the user declared it completed and submitted.

- [ ] **Step 2: Apply only the approved status correction**

Change Task 1 from `进行中` to `已完成`, and Task 2 from `未开始` to `进行中`. Do not edit goals, modules, acceptance criteria, tests, or suggested commit messages.

Run:

```powershell
git diff -- TASKS.md
```

Expected: exactly two status-line changes. This satisfies the one-active-task rule and the user's direct statement that Task 1 is complete.

- [ ] **Step 3: Continue without committing**

No commit or staging command is allowed. Task 2 remains `进行中` through user review.

---

### Task 1: Tool calls, result metadata, and tool results

**Files:**
- Create: `src/coding_agent/messages.py`
- Create: `tests/test_messages.py`

**Interfaces:**
- Produces: `JSONScalar`, `JSONValue`, `JSONObject`, `ToolStatus`, `ToolCall`, `ToolResultMetadata`, and `ToolResult`
- Does not consume or produce `ModelClient`, SDK objects, or execution behavior

- [ ] **Step 1: Write the failing tests**

Create `tests/test_messages.py` with:

```python
from __future__ import annotations

import json

import pytest

from coding_agent.messages import ToolCall, ToolResult, ToolResultMetadata


def test_tool_call_and_result_round_trip() -> None:
    call = ToolCall(
        call_id=" call_123 ",
        name=" read_file ",
        arguments={"path": "src/example.py", "end_line": None},
    )
    result = ToolResult(
        call_id="call_123",
        tool_name="read_file",
        status="ok",
        output="contents",
        metadata=ToolResultMetadata(duration_ms=8),
    )

    assert call.call_id == result.call_id == "call_123"
    assert ToolCall.from_json(call.to_json()) == call
    assert ToolResult.from_json(result.to_json()) == result
    assert json.loads(call.to_json()) == {
        "arguments": {"end_line": None, "path": "src/example.py"},
        "id": "call_123",
        "kind": "tool_call",
        "name": "read_file",
    }


def test_tool_result_serializes_explicit_nulls() -> None:
    result = ToolResult(
        call_id="call_1",
        tool_name="list_directory",
        status="ok",
    )

    payload = json.loads(result.to_json())
    assert payload["output"] is None
    assert payload["error"] is None
    assert payload["metadata"] == {
        "changed_paths": [],
        "duration_ms": 0,
        "exit_code": None,
        "timed_out": False,
        "truncated": False,
    }


@pytest.mark.parametrize("status", ["success", "failed", "", None])
def test_tool_result_rejects_invalid_status(status: object) -> None:
    with pytest.raises(ValueError, match="status"):
        ToolResult(
            call_id="call_1",
            tool_name="read_file",
            status=status,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("call_id", ["", "   "])
def test_tool_call_rejects_empty_call_id(call_id: str) -> None:
    with pytest.raises(ValueError, match="call_id"):
        ToolCall(call_id=call_id, name="read_file", arguments={})


@pytest.mark.parametrize("call_id", ["", "   "])
def test_tool_result_rejects_empty_call_id(call_id: str) -> None:
    with pytest.raises(ValueError, match="call_id"):
        ToolResult(call_id=call_id, tool_name="read_file", status="ok")


def test_error_result_requires_error_text() -> None:
    with pytest.raises(ValueError, match="error is required"):
        ToolResult(call_id="call_1", tool_name="read_file", status="error")


def test_ok_result_rejects_error_text() -> None:
    with pytest.raises(ValueError, match="error must be null"):
        ToolResult(
            call_id="call_1",
            tool_name="read_file",
            status="ok",
            error="unexpected",
        )


def test_metadata_rejects_negative_duration() -> None:
    with pytest.raises(ValueError, match="duration_ms"):
        ToolResultMetadata(duration_ms=-1)


def test_from_dict_rejects_missing_required_field() -> None:
    with pytest.raises(ValueError, match="missing fields: name"):
        ToolCall.from_dict(
            {"kind": "tool_call", "id": "call_1", "arguments": {}}
        )
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py -q
```

Expected: collection exits nonzero with `ModuleNotFoundError: No module named 'coding_agent.messages'`. A pytest temporary-directory error, syntax error, or missing pytest is not the expected RED state.

- [ ] **Step 3: Implement the minimum tool message types**

Create `src/coding_agent/messages.py` with these exact building blocks:

```python
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from typing import Literal, Mapping, Self, TypeAlias

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]
ToolStatus: TypeAlias = Literal["ok", "error", "rejected"]


def _non_empty(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _json_value(value: object, field_name: str) -> JSONValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} contains a non-finite float")
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item, field_name) for item in value]
    if isinstance(value, Mapping):
        normalized: JSONObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{field_name} contains a non-string key")
            normalized[key] = _json_value(item, field_name)
        return normalized
    raise ValueError(f"{field_name} contains a non-JSON value")


def _json_object(value: object, field_name: str) -> JSONObject:
    normalized = _json_value(value, field_name)
    if not isinstance(normalized, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return normalized


def _exact_keys(
    payload: Mapping[str, object],
    required: set[str],
    type_name: str,
) -> None:
    missing = sorted(required - set(payload))
    extra = sorted(set(payload) - required)
    if missing:
        raise ValueError(f"{type_name} missing fields: {', '.join(missing)}")
    if extra:
        raise ValueError(f"{type_name} unexpected fields: {', '.join(extra)}")


class _JsonMixin:
    def to_dict(self) -> JSONObject:
        raise NotImplementedError

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        raise NotImplementedError

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    @classmethod
    def from_json(cls, payload: str) -> Self:
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid {cls.__name__} JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError(f"{cls.__name__} JSON must be an object")
        return cls.from_dict(decoded)
```

Then add these exact implementations:

```python
@dataclass(frozen=True, slots=True)
class ToolCall(_JsonMixin):
    call_id: str
    name: str
    arguments: JSONObject

    def __post_init__(self) -> None:
        object.__setattr__(self, "call_id", _non_empty(self.call_id, "call_id"))
        object.__setattr__(self, "name", _non_empty(self.name, "name"))
        object.__setattr__(
            self, "arguments", _json_object(self.arguments, "arguments")
        )

    def to_dict(self) -> JSONObject:
        return {
            "kind": "tool_call",
            "id": self.call_id,
            "name": self.name,
            "arguments": _json_object(self.arguments, "arguments"),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        required = {"kind", "id", "name", "arguments"}
        _exact_keys(payload, required, cls.__name__)
        if payload["kind"] != "tool_call":
            raise ValueError("ToolCall kind must be tool_call")
        return cls(
            call_id=payload["id"],  # type: ignore[arg-type]
            name=payload["name"],  # type: ignore[arg-type]
            arguments=_json_object(payload["arguments"], "arguments"),
        )


@dataclass(frozen=True, slots=True)
class ToolResultMetadata(_JsonMixin):
    exit_code: int | None = None
    timed_out: bool = False
    truncated: bool = False
    duration_ms: int = 0
    changed_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)
        ):
            raise ValueError("exit_code must be an integer or null")
        if not isinstance(self.timed_out, bool):
            raise ValueError("timed_out must be a boolean")
        if not isinstance(self.truncated, bool):
            raise ValueError("truncated must be a boolean")
        if (
            isinstance(self.duration_ms, bool)
            or not isinstance(self.duration_ms, int)
            or self.duration_ms < 0
        ):
            raise ValueError("duration_ms must be a non-negative integer")
        if not isinstance(self.changed_paths, tuple):
            raise ValueError("changed_paths must be a tuple")
        normalized_paths = tuple(
            _non_empty(path, "changed_paths item") for path in self.changed_paths
        )
        if len(set(normalized_paths)) != len(normalized_paths):
            raise ValueError("changed_paths must not contain duplicates")
        object.__setattr__(self, "changed_paths", normalized_paths)

    def to_dict(self) -> JSONObject:
        return {
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
            "duration_ms": self.duration_ms,
            "changed_paths": list(self.changed_paths),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        required = {
            "exit_code",
            "timed_out",
            "truncated",
            "duration_ms",
            "changed_paths",
        }
        _exact_keys(payload, required, cls.__name__)
        changed_paths = payload["changed_paths"]
        if not isinstance(changed_paths, list):
            raise ValueError("changed_paths must be a JSON array")
        return cls(
            exit_code=payload["exit_code"],  # type: ignore[arg-type]
            timed_out=payload["timed_out"],  # type: ignore[arg-type]
            truncated=payload["truncated"],  # type: ignore[arg-type]
            duration_ms=payload["duration_ms"],  # type: ignore[arg-type]
            changed_paths=tuple(changed_paths),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class ToolResult(_JsonMixin):
    call_id: str
    tool_name: str
    status: ToolStatus
    output: str | None = None
    error: str | None = None
    metadata: ToolResultMetadata = field(default_factory=ToolResultMetadata)

    def __post_init__(self) -> None:
        object.__setattr__(self, "call_id", _non_empty(self.call_id, "call_id"))
        object.__setattr__(
            self, "tool_name", _non_empty(self.tool_name, "tool_name")
        )
        if self.status not in {"ok", "error", "rejected"}:
            raise ValueError("status must be ok, error, or rejected")
        if self.output is not None and not isinstance(self.output, str):
            raise ValueError("output must be a string or null")
        if self.status == "ok":
            if self.error is not None:
                raise ValueError("error must be null when status is ok")
        else:
            object.__setattr__(self, "error", _non_empty(self.error, "error is required"))
        if not isinstance(self.metadata, ToolResultMetadata):
            raise ValueError("metadata must be ToolResultMetadata")

    def to_dict(self) -> JSONObject:
        return {
            "kind": "tool_result",
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        required = {
            "kind",
            "call_id",
            "tool_name",
            "status",
            "output",
            "error",
            "metadata",
        }
        _exact_keys(payload, required, cls.__name__)
        if payload["kind"] != "tool_result":
            raise ValueError("ToolResult kind must be tool_result")
        metadata = payload["metadata"]
        if not isinstance(metadata, Mapping):
            raise ValueError("metadata must be a JSON object")
        return cls(
            call_id=payload["call_id"],  # type: ignore[arg-type]
            tool_name=payload["tool_name"],  # type: ignore[arg-type]
            status=payload["status"],  # type: ignore[arg-type]
            output=payload["output"],  # type: ignore[arg-type]
            error=payload["error"],  # type: ignore[arg-type]
            metadata=ToolResultMetadata.from_dict(metadata),
        )
```

Before these classes, update `_exact_keys()` to reject non-mapping inputs before calling `set(payload)`:

```python
if not isinstance(payload, Mapping):
    raise ValueError(f"{type_name} payload must be an object")
```

`ToolResult.from_dict()` delegates nested metadata to `ToolResultMetadata.from_dict()` as shown.

This step must not define user/assistant messages, model requests, or model responses.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py -q
```

Expected: exit code `0`; all Task 1 tests in `test_messages.py` pass with no warnings. Record the real count instead of predicting it.

- [ ] **Step 5: Review the first slice without committing**

Run:

```powershell
git diff -- src\coding_agent\messages.py tests\test_messages.py
```

Expected: only tool/message primitives exist; no SDK, model client, Agent, tool execution, or networking code appears.

---

### Task 2: User/assistant messages and paired model request history

**Files:**
- Modify: `src/coding_agent/messages.py`
- Modify: `tests/test_messages.py`

**Interfaces:**
- Consumes: `ToolCall`, `ToolResult`, `_JsonMixin`, `_json_object`
- Produces: `UserMessage`, `AssistantMessage`, `Message`, `ModelRequest`, and private `_validate_message_sequence(messages)`

- [ ] **Step 1: Add failing message and request tests**

Extend the existing import with `AssistantMessage`, `ModelRequest`, and `UserMessage`, then append:

```python
def test_user_and_assistant_messages_round_trip() -> None:
    user = UserMessage(content="inspect the project")
    assistant = AssistantMessage(content="I will inspect it.")

    assert UserMessage.from_json(user.to_json()) == user
    assert AssistantMessage.from_json(assistant.to_json()) == assistant
    assert json.loads(user.to_json()) == {
        "content": "inspect the project",
        "kind": "user",
    }


def test_assistant_tool_message_serializes_explicit_null() -> None:
    call = ToolCall(call_id="call_1", name="list_directory", arguments={"path": "."})
    assistant = AssistantMessage(content=None, tool_calls=(call,))

    payload = json.loads(assistant.to_json())
    assert payload["content"] is None
    assert payload["tool_calls"] == [call.to_dict()]


def test_assistant_rejects_duplicate_call_id() -> None:
    first = ToolCall(call_id="call_1", name="read_file", arguments={"path": "a.py"})
    second = ToolCall(call_id="call_1", name="read_file", arguments={"path": "b.py"})

    with pytest.raises(ValueError, match="duplicate call_id: call_1"):
        AssistantMessage(content=None, tool_calls=(first, second))


def test_model_request_accepts_paired_tool_result() -> None:
    call = ToolCall(call_id="call_1", name="read_file", arguments={"path": "a.py"})
    request = ModelRequest(
        messages=(
            UserMessage("inspect"),
            AssistantMessage(content=None, tool_calls=(call,)),
            ToolResult(
                call_id="call_1",
                tool_name="read_file",
                status="ok",
                output="contents",
            ),
        ),
        tool_schemas=({"name": "read_file", "strict": True},),
        continuation_items=(object(),),
    )

    restored = ModelRequest.from_json(request.to_json())
    assert restored == request
    assert restored.continuation_items == ()
    assert "continuation_items" not in json.loads(request.to_json())


def test_model_request_rejects_unmatched_result() -> None:
    with pytest.raises(ValueError, match="unmatched call_id: call_1"):
        ModelRequest(
            messages=(
                UserMessage("inspect"),
                ToolResult(
                    call_id="call_1",
                    tool_name="read_file",
                    status="ok",
                ),
            )
        )


def test_model_request_rejects_tool_name_mismatch() -> None:
    call = ToolCall(call_id="call_1", name="read_file", arguments={})

    with pytest.raises(ValueError, match="tool_name mismatch for call_id: call_1"):
        ModelRequest(
            messages=(
                UserMessage("inspect"),
                AssistantMessage(content=None, tool_calls=(call,)),
                ToolResult(
                    call_id="call_1",
                    tool_name="list_directory",
                    status="ok",
                ),
            )
        )


def test_model_request_rejects_unresolved_call() -> None:
    call = ToolCall(call_id="call_1", name="read_file", arguments={})

    with pytest.raises(ValueError, match="unresolved call_id: call_1"):
        ModelRequest(
            messages=(
                UserMessage("inspect"),
                AssistantMessage(content=None, tool_calls=(call,)),
            )
        )


def test_model_request_rejects_reused_call_id() -> None:
    first = ToolCall(call_id="call_1", name="read_file", arguments={})
    reused = ToolCall(call_id="call_1", name="list_directory", arguments={})

    with pytest.raises(ValueError, match="duplicate call_id: call_1"):
        ModelRequest(
            messages=(
                UserMessage("inspect"),
                AssistantMessage(content=None, tool_calls=(first,)),
                ToolResult(
                    call_id="call_1",
                    tool_name="read_file",
                    status="ok",
                ),
                AssistantMessage(content=None, tool_calls=(reused,)),
                ToolResult(
                    call_id="call_1",
                    tool_name="list_directory",
                    status="ok",
                ),
            )
        )
```

- [ ] **Step 2: Run the new slice and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py -q
```

Expected: collection exits nonzero because `UserMessage`, `AssistantMessage`, or `ModelRequest` cannot yet be imported. Existing tool-type tests must not be weakened.

- [ ] **Step 3: Implement messages and request pairing**

Append these exact public dataclasses and decoder:

```python
@dataclass(frozen=True, slots=True)
class UserMessage(_JsonMixin):
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("content must be a non-empty string")

    def to_dict(self) -> JSONObject:
        return {"kind": "user", "content": self.content}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _exact_keys(payload, {"kind", "content"}, cls.__name__)
        if payload["kind"] != "user":
            raise ValueError("UserMessage kind must be user")
        return cls(content=payload["content"])  # type: ignore[arg-type]


def _validate_unique_call_ids(tool_calls: tuple[ToolCall, ...]) -> None:
    seen: set[str] = set()
    for call in tool_calls:
        if not isinstance(call, ToolCall):
            raise ValueError("tool_calls must contain ToolCall values")
        if call.call_id in seen:
            raise ValueError(f"duplicate call_id: {call.call_id}")
        seen.add(call.call_id)


@dataclass(frozen=True, slots=True)
class AssistantMessage(_JsonMixin):
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()

    def __post_init__(self) -> None:
        if self.content is not None and (
            not isinstance(self.content, str) or not self.content.strip()
        ):
            raise ValueError("content must be a non-empty string or null")
        if not isinstance(self.tool_calls, tuple):
            raise ValueError("tool_calls must be a tuple")
        _validate_unique_call_ids(self.tool_calls)
        if self.content is None and not self.tool_calls:
            raise ValueError("assistant message requires content or tool_calls")

    def to_dict(self) -> JSONObject:
        return {
            "kind": "assistant",
            "content": self.content,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _exact_keys(payload, {"kind", "content", "tool_calls"}, cls.__name__)
        if payload["kind"] != "assistant":
            raise ValueError("AssistantMessage kind must be assistant")
        tool_calls = payload["tool_calls"]
        if not isinstance(tool_calls, list):
            raise ValueError("tool_calls must be a JSON array")
        decoded_calls: list[ToolCall] = []
        for call in tool_calls:
            if not isinstance(call, Mapping):
                raise ValueError("tool_calls items must be JSON objects")
            decoded_calls.append(ToolCall.from_dict(call))
        return cls(
            content=payload["content"],  # type: ignore[arg-type]
            tool_calls=tuple(decoded_calls),
        )


Message: TypeAlias = UserMessage | AssistantMessage | ToolResult


def message_from_dict(payload: Mapping[str, object]) -> Message:
    kind = payload.get("kind")
    if kind == "user":
        return UserMessage.from_dict(payload)
    if kind == "assistant":
        return AssistantMessage.from_dict(payload)
    if kind == "tool_result":
        return ToolResult.from_dict(payload)
    raise ValueError(f"unknown message kind: {kind}")
```

Use this deterministic sequence validator from `ModelRequest.__post_init__`:

```python
def _validate_message_sequence(messages: tuple[Message, ...]) -> None:
    seen_calls: set[str] = set()
    pending: dict[str, str] = {}

    for message in messages:
        if isinstance(message, AssistantMessage):
            for call in message.tool_calls:
                if call.call_id in seen_calls:
                    raise ValueError(f"duplicate call_id: {call.call_id}")
                seen_calls.add(call.call_id)
                pending[call.call_id] = call.name
        elif isinstance(message, ToolResult):
            expected_name = pending.get(message.call_id)
            if expected_name is None:
                raise ValueError(f"unmatched call_id: {message.call_id}")
            if expected_name != message.tool_name:
                raise ValueError(
                    f"tool_name mismatch for call_id: {message.call_id}"
                )
            del pending[message.call_id]

    if pending:
        first_unresolved = next(iter(pending))
        raise ValueError(f"unresolved call_id: {first_unresolved}")
```

Then add `ModelRequest`:

```python
@dataclass(frozen=True, slots=True)
class ModelRequest(_JsonMixin):
    messages: tuple[Message, ...]
    tool_schemas: tuple[JSONObject, ...] = ()
    max_output_tokens: int = 4096
    continuation_items: tuple[object, ...] = field(
        default=(), repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.messages, tuple) or not self.messages:
            raise ValueError("messages must be a non-empty tuple")
        if not all(
            isinstance(message, (UserMessage, AssistantMessage, ToolResult))
            for message in self.messages
        ):
            raise ValueError("messages contains an unsupported value")
        if not isinstance(self.tool_schemas, tuple):
            raise ValueError("tool_schemas must be a tuple")
        normalized_schemas = tuple(
            _json_object(schema, "tool_schemas item") for schema in self.tool_schemas
        )
        object.__setattr__(self, "tool_schemas", normalized_schemas)
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise ValueError("max_output_tokens must be a positive integer")
        if not isinstance(self.continuation_items, tuple):
            raise ValueError("continuation_items must be a tuple")
        _validate_message_sequence(self.messages)

    def to_dict(self) -> JSONObject:
        return {
            "messages": [message.to_dict() for message in self.messages],
            "tool_schemas": [
                _json_object(schema, "tool_schemas item")
                for schema in self.tool_schemas
            ],
            "max_output_tokens": self.max_output_tokens,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        required = {"messages", "tool_schemas", "max_output_tokens"}
        _exact_keys(payload, required, cls.__name__)
        messages = payload["messages"]
        schemas = payload["tool_schemas"]
        if not isinstance(messages, list):
            raise ValueError("messages must be a JSON array")
        if not isinstance(schemas, list):
            raise ValueError("tool_schemas must be a JSON array")
        decoded_messages: list[Message] = []
        for message in messages:
            if not isinstance(message, Mapping):
                raise ValueError("messages items must be JSON objects")
            decoded_messages.append(message_from_dict(message))
        return cls(
            messages=tuple(decoded_messages),
            tool_schemas=tuple(
                _json_object(schema, "tool_schemas item") for schema in schemas
            ),
            max_output_tokens=payload["max_output_tokens"],  # type: ignore[arg-type]
        )
```

`ModelRequest.from_dict()` leaves `continuation_items=()` because the field is not part of durable JSON.

Do not define `ModelResponse`, `TokenUsage`, `ModelClient`, or Agent behavior in this slice.

- [ ] **Step 4: Run all message tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py -q
```

Expected: exit code `0`; all current message tests pass. Record the real count.

- [ ] **Step 5: Run the Task 1 regression suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
```

Expected: exit code `0`; the actual Task 1 count passes unchanged.

---

### Task 3: Token usage and model response

**Files:**
- Modify: `src/coding_agent/messages.py`
- Modify: `tests/test_messages.py`

**Interfaces:**
- Consumes: `ToolCall`, `_JsonMixin`
- Produces: `TokenUsage` and `ModelResponse`

- [ ] **Step 1: Add failing response tests**

Extend the import with `ModelResponse` and `TokenUsage`, then append:

```python
def test_model_response_round_trip_preserves_order() -> None:
    first = ToolCall(call_id="call_1", name="read_file", arguments={"path": "a.py"})
    second = ToolCall(call_id="call_2", name="read_file", arguments={"path": "b.py"})
    response = ModelResponse(
        text="inspection complete",
        tool_calls=(first, second),
        usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        provider_response_id="resp_1",
    )

    restored = ModelResponse.from_json(response.to_json())
    assert restored == response
    assert restored.tool_calls == (first, second)


def test_model_response_serializes_explicit_nulls() -> None:
    payload = json.loads(ModelResponse().to_json())

    assert payload == {
        "provider_response_id": None,
        "text": None,
        "tool_calls": [],
        "usage": None,
    }


def test_model_response_rejects_duplicate_call_id() -> None:
    first = ToolCall(call_id="call_1", name="read_file", arguments={"path": "a.py"})
    second = ToolCall(call_id="call_1", name="read_file", arguments={"path": "b.py"})

    with pytest.raises(ValueError, match="duplicate call_id: call_1"):
        ModelResponse(tool_calls=(first, second))


def test_model_response_omits_opaque_continuation_items() -> None:
    marker = object()
    response = ModelResponse(
        text="done",
        continuation_items=(marker,),
    )

    payload = json.loads(response.to_json())
    restored = ModelResponse.from_json(response.to_json())
    assert "continuation_items" not in payload
    assert repr(marker) not in repr(response)
    assert restored == response
    assert restored.continuation_items == ()


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_token_usage_rejects_invalid_counts(value: object) -> None:
    with pytest.raises(ValueError, match="input_tokens"):
        TokenUsage(
            input_tokens=value,  # type: ignore[arg-type]
            output_tokens=0,
            total_tokens=0,
        )
```

- [ ] **Step 2: Run the response slice and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py -q
```

Expected: collection exits nonzero because `ModelResponse` or `TokenUsage` is not defined. Existing tests remain present.

- [ ] **Step 3: Implement the minimum response types**

Append these exact implementations. Reuse the `_validate_unique_call_ids()` helper introduced in Task 2; do not redefine it.

```python
@dataclass(frozen=True, slots=True)
class TokenUsage(_JsonMixin):
    input_tokens: int
    output_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        for field_name in ("input_tokens", "output_tokens", "total_tokens"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")

    def to_dict(self) -> JSONObject:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        required = {"input_tokens", "output_tokens", "total_tokens"}
        _exact_keys(payload, required, cls.__name__)
        return cls(
            input_tokens=payload["input_tokens"],  # type: ignore[arg-type]
            output_tokens=payload["output_tokens"],  # type: ignore[arg-type]
            total_tokens=payload["total_tokens"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class ModelResponse(_JsonMixin):
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    usage: TokenUsage | None = None
    provider_response_id: str | None = None
    continuation_items: tuple[object, ...] = field(
        default=(), repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.text is not None and not isinstance(self.text, str):
            raise ValueError("text must be a string or null")
        if not isinstance(self.tool_calls, tuple):
            raise ValueError("tool_calls must be a tuple")
        _validate_unique_call_ids(self.tool_calls)
        if self.usage is not None and not isinstance(self.usage, TokenUsage):
            raise ValueError("usage must be TokenUsage or null")
        if self.provider_response_id is not None:
            object.__setattr__(
                self,
                "provider_response_id",
                _non_empty(self.provider_response_id, "provider_response_id"),
            )
        if not isinstance(self.continuation_items, tuple):
            raise ValueError("continuation_items must be a tuple")

    def to_dict(self) -> JSONObject:
        return {
            "text": self.text,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "usage": None if self.usage is None else self.usage.to_dict(),
            "provider_response_id": self.provider_response_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        required = {"text", "tool_calls", "usage", "provider_response_id"}
        _exact_keys(payload, required, cls.__name__)
        tool_calls = payload["tool_calls"]
        if not isinstance(tool_calls, list):
            raise ValueError("tool_calls must be a JSON array")
        decoded_calls: list[ToolCall] = []
        for call in tool_calls:
            if not isinstance(call, Mapping):
                raise ValueError("tool_calls items must be JSON objects")
            decoded_calls.append(ToolCall.from_dict(call))
        usage = payload["usage"]
        if usage is not None and not isinstance(usage, Mapping):
            raise ValueError("usage must be a JSON object or null")
        return cls(
            text=payload["text"],  # type: ignore[arg-type]
            tool_calls=tuple(decoded_calls),
            usage=None if usage is None else TokenUsage.from_dict(usage),
            provider_response_id=payload["provider_response_id"],  # type: ignore[arg-type]
        )
```

`ModelResponse.to_dict()` always emits `text`, `tool_calls`, `usage`, and `provider_response_id`, including nulls. `from_dict()` requires exactly these four fields, delegates nested calls to `ToolCall.from_dict()`, delegates non-null usage to `TokenUsage.from_dict()`, and restores no continuation payload.

This step must not define model completion behavior, SDK mapping, retries, response parsing, or an Agent loop.

- [ ] **Step 4: Run all Task 2 tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py -q
```

Expected: exit code `0`; all Task 2 tests pass. Record the real count and duration.

- [ ] **Step 5: Run all repository tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit code `0`; both `test_cli.py` and `test_messages.py` pass. If a permissions error occurs, do not reuse a Codex-created fixed basetemp; diagnose the executing user's temporary directory ownership first.

---

### Task 4: Provider boundary and final Task 2 verification

**Files:**
- Modify: `tests/test_messages.py`
- Inspect only: `src/coding_agent/messages.py`, `pyproject.toml`, `TASKS.md`

**Interfaces:** Verifies that all Task 2 public types import and serialize without the OpenAI SDK or any model/Agent implementation.

- [ ] **Step 1: Add the fresh-process provider boundary test**

Add these imports:

```python
import subprocess
import sys
```

Append:

```python
def test_messages_module_imports_without_openai() -> None:
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "openai" or name.startswith("openai."):
        raise AssertionError("coding_agent.messages imported OpenAI SDK")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import coding_agent.messages
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
```

- [ ] **Step 2: Run the boundary test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py::test_messages_module_imports_without_openai -q
```

Expected: exit code `0`, `1 passed`. If it fails, remove the SDK import from `messages.py`; do not mock or install around the violation.

- [ ] **Step 3: Run the complete Task 2 suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py -q
```

Expected: exit code `0`; all Task 2 construction, invariant, pairing, serialization, null, and boundary tests pass.

- [ ] **Step 4: Run all repository tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit code `0`; Task 1 and Task 2 tests pass together. Report the real total, failures, errors, warnings, duration, and exit code.

- [ ] **Step 5: Audit dependencies and scope**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import pathlib,tomllib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); assert d['project']['dependencies']==['openai']; assert d['project']['optional-dependencies']['test']==['pytest']; print('approved dependencies only')"

Get-ChildItem .\src\coding_agent -File | Select-Object -ExpandProperty Name
Select-String -Path .\src\coding_agent\messages.py -Pattern 'import openai|from openai|ModelClient|AgentRunner'
git diff --check
git status --short
```

Expected:

- Dependency command exits `0` and prints `approved dependencies only`.
- Source listing adds only `messages.py` beyond Task 1 files.
- Boundary scan prints no matches.
- `git diff --check` exits `0`.
- Git status contains only `TASKS.md`, `src/coding_agent/messages.py`, `tests/test_messages.py`, this approved plan, and any pre-existing user-owned changes.

- [ ] **Step 6: Check placeholders, interfaces, and exact scope**

Run:

```powershell
$markers = @(("T" + "BD"), ("T" + "ODO"))
Select-String -Path .\docs\superpowers\plans\Task2.md -Pattern $markers

.\.venv\Scripts\python.exe -c "from coding_agent.messages import AssistantMessage, ModelRequest, ModelResponse, ToolCall, ToolResult, ToolResultMetadata, TokenUsage, UserMessage; print('task-2 interfaces import successfully')"
```

Expected: placeholder scan has no output; import command exits `0` and prints `task-2 interfaces import successfully`. Manually confirm every name exactly matches the Public Type Contract and no ModelClient, Agent loop, SDK adapter, tool executor, or context manager was added.

- [ ] **Step 7: Wait for user review and authorization**

Keep Task 2 as `进行中`. Present:

- Every RED command, exit code, and expected failure reason.
- Every GREEN command, exit code, and real pass count.
- Full repository test output.
- Provider-boundary, dependency, and scope-audit results.
- Any unverified or skipped check, explicitly labeled.

Do not stage, commit, push, or mark Task 2 complete. The suggested future commit message is `feat: define provider-neutral agent messages`, but it requires separate user authorization after review.

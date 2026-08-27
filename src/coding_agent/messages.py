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
    if not isinstance(payload, Mapping):
        raise ValueError(f"{type_name} payload must be an object")
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
            object.__setattr__(
                self, "error", _non_empty(self.error, "error is required")
            )
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

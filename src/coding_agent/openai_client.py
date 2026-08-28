from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
import time

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    OpenAI,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

from coding_agent.messages import (
    AssistantMessage,
    JSONObject,
    ModelRequest,
    ModelResponse,
    TokenUsage,
    ToolCall,
    ToolResult,
    UserMessage,
)
from coding_agent.model import FatalModelError, ModelError, TransientModelError


class InvalidOpenAIResponseError(ModelError):
    """The provider returned a completed but unusable Responses payload."""


_STRICT_SCHEMA_ERROR = (
    "OpenAI Responses request is invalid: tool schema is not strict"
)
_CONTINUATION_ERROR = (
    "OpenAI Responses request is invalid: continuation does not match local history"
)


@dataclass(frozen=True, slots=True, repr=False)
class _OpenAIContinuationSegment:
    message_index: int
    serialized_items: tuple[str, ...]

    def replay_items(self) -> list[JSONObject]:
        return [json.loads(item) for item in self.serialized_items]


def _schema_node_is_strict(node: object) -> bool:
    if not isinstance(node, dict):
        return False
    if node.get("type") == "object":
        properties = node.get("properties")
        required = node.get("required")
        if (
            not isinstance(properties, dict)
            or node.get("additionalProperties") is not False
            or not isinstance(required, list)
            or any(not isinstance(item, str) for item in required)
            or len(required) != len(set(required))
            or set(required) != set(properties)
        ):
            return False
        if not all(_schema_node_is_strict(child) for child in properties.values()):
            return False
    for branch_name in ("anyOf", "oneOf"):
        branches = node.get(branch_name)
        if branches is not None:
            if not isinstance(branches, list) or not branches:
                return False
            if not all(_schema_node_is_strict(branch) for branch in branches):
                return False
    if "items" in node and not _schema_node_is_strict(node["items"]):
        return False
    return True


def _map_tools(tool_schemas: tuple[JSONObject, ...]) -> list[dict[str, object]]:
    mapped: list[dict[str, object]] = []
    for schema in tool_schemas:
        if set(schema) != {"name", "description", "strict", "parameters"}:
            raise FatalModelError(_STRICT_SCHEMA_ERROR)
        name = schema["name"]
        description = schema["description"]
        parameters = schema["parameters"]
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(description, str)
            or not description.strip()
            or schema["strict"] is not True
            or not isinstance(parameters, dict)
            or parameters.get("type") != "object"
            or not _schema_node_is_strict(parameters)
        ):
            raise FatalModelError(_STRICT_SCHEMA_ERROR)
        mapped.append(
            {
                "type": "function",
                "name": name,
                "description": description,
                "strict": True,
                "parameters": deepcopy(parameters),
            }
        )
    return mapped


def _map_messages(request: ModelRequest) -> list[dict[str, object]]:
    continuation_by_index: dict[int, _OpenAIContinuationSegment] = {}
    for value in request.continuation_items:
        if not isinstance(value, _OpenAIContinuationSegment):
            raise FatalModelError(_CONTINUATION_ERROR)
        if value.message_index in continuation_by_index:
            raise FatalModelError(_CONTINUATION_ERROR)
        if not 0 <= value.message_index < len(request.messages):
            raise FatalModelError(_CONTINUATION_ERROR)
        message = request.messages[value.message_index]
        if not isinstance(message, AssistantMessage):
            raise FatalModelError(_CONTINUATION_ERROR)
        replayed = value.replay_items()
        replayed_calls = [
            (item.get("call_id"), item.get("name"))
            for item in replayed
            if item.get("type") == "function_call"
        ]
        local_calls = [(call.call_id, call.name) for call in message.tool_calls]
        if replayed_calls != local_calls:
            raise FatalModelError(_CONTINUATION_ERROR)
        continuation_by_index[value.message_index] = value

    mapped_input: list[dict[str, object]] = []
    for message_index, message in enumerate(request.messages):
        if isinstance(message, UserMessage):
            mapped_input.append({"role": "user", "content": message.content})
            continue
        if isinstance(message, AssistantMessage):
            continuation = continuation_by_index.get(message_index)
            if continuation is not None:
                mapped_input.extend(continuation.replay_items())
                continue
            if message.content is not None:
                mapped_input.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": message.content,
                                "annotations": [],
                            }
                        ],
                    }
                )
            for call in message.tool_calls:
                mapped_input.append(
                    {
                        "type": "function_call",
                        "call_id": call.call_id,
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                )
            continue
        if isinstance(message, ToolResult):
            mapped_input.append(
                {
                    "type": "function_call_output",
                    "call_id": message.call_id,
                    "output": message.to_json(),
                }
            )
    return mapped_input


def _snapshot_output_item(item: object) -> str:
    model_dump = getattr(item, "model_dump", None)
    if not callable(model_dump):
        raise InvalidOpenAIResponseError(
            "OpenAI Responses response is invalid: output item cannot be serialized"
        )
    payload = model_dump(mode="json", by_alias=True, exclude_none=False)
    if not isinstance(payload, dict):
        raise InvalidOpenAIResponseError(
            "OpenAI Responses response is invalid: output item cannot be serialized"
        )
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise InvalidOpenAIResponseError(
            "OpenAI Responses response is invalid: output item cannot be serialized"
        ) from exc


_MISSING = object()


def _invalid_response(reason: str) -> InvalidOpenAIResponseError:
    return InvalidOpenAIResponseError(f"invalid OpenAI Responses payload: {reason}")


def _field(value: object, name: str, reason: str) -> object:
    if isinstance(value, Mapping):
        found = value.get(name, _MISSING)
    else:
        found = getattr(value, name, _MISSING)
    if found is _MISSING:
        raise _invalid_response(reason)
    return found


def _parse_response(
    response: object,
) -> tuple[str | None, tuple[ToolCall, ...], TokenUsage | None, str, list[object]]:
    response_id = _field(response, "id", "missing response id")
    if not isinstance(response_id, str) or not response_id.strip():
        raise _invalid_response("missing response id")
    if _field(response, "status", "response status is not completed") != "completed":
        raise _invalid_response("response status is not completed")
    if _field(response, "error", "response contains an error") is not None:
        raise _invalid_response("response contains an error")
    output = _field(response, "output", "response output is missing")
    if not isinstance(output, (list, tuple)):
        raise _invalid_response("response output is missing")

    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    seen_call_ids: set[str] = set()
    output_items = list(output)
    for item in output_items:
        item_type = _field(item, "type", "missing output item type")
        if item_type == "reasoning":
            if _field(item, "status", "reasoning status is not completed") != "completed":
                raise _invalid_response("reasoning status is not completed")
            continue
        if item_type == "message":
            if _field(item, "role", "message role is invalid") != "assistant":
                raise _invalid_response("message role is invalid")
            if _field(item, "status", "message status is not completed") != "completed":
                raise _invalid_response("message status is not completed")
            content = _field(item, "content", "message content is missing")
            if not isinstance(content, (list, tuple)):
                raise _invalid_response("message content is missing")
            for part in content:
                part_type = _field(
                    part,
                    "type",
                    "unsupported message content type",
                )
                if part_type != "output_text":
                    raise _invalid_response("unsupported message content type")
                text = _field(part, "text", "output text is missing")
                if not isinstance(text, str):
                    raise _invalid_response("output text is invalid")
                text_parts.append(text)
            continue
        if item_type == "function_call":
            if _field(item, "status", "function call status is not completed") != "completed":
                raise _invalid_response("function call status is not completed")
            call_id = _field(item, "call_id", "function call id is missing")
            name = _field(item, "name", "function name is missing")
            encoded_arguments = _field(
                item,
                "arguments",
                "function arguments are not valid JSON",
            )
            if not isinstance(encoded_arguments, str):
                raise _invalid_response("function arguments are not valid JSON")
            try:
                arguments = json.loads(encoded_arguments)
            except json.JSONDecodeError as exc:
                raise _invalid_response(
                    "function arguments are not valid JSON"
                ) from exc
            if not isinstance(arguments, dict):
                raise _invalid_response("function arguments must be an object")
            if not isinstance(call_id, str) or not call_id.strip():
                raise _invalid_response("function call id is missing")
            if call_id in seen_call_ids:
                raise _invalid_response("duplicate function call id")
            if not isinstance(name, str) or not name.strip():
                raise _invalid_response("function name is missing")
            seen_call_ids.add(call_id)
            try:
                tool_calls.append(
                    ToolCall(call_id=call_id, name=name, arguments=arguments)
                )
            except (TypeError, ValueError) as exc:
                raise _invalid_response("invalid function call") from exc
            continue
        raise _invalid_response("unsupported output item type")

    if not "".join(text_parts) and not tool_calls:
        raise _invalid_response("no text or function call output")

    usage_value = _field(response, "usage", "invalid usage")
    usage = None
    if usage_value is not None:
        try:
            usage = TokenUsage(
                input_tokens=_field(usage_value, "input_tokens", "invalid usage"),
                output_tokens=_field(usage_value, "output_tokens", "invalid usage"),
                total_tokens=_field(usage_value, "total_tokens", "invalid usage"),
            )
        except InvalidOpenAIResponseError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_response("invalid usage") from exc

    return (
        "".join(text_parts) or None,
        tuple(tool_calls),
        usage,
        response_id.strip(),
        output_items,
    )


class OpenAIResponsesClient:
    __slots__ = ("_client", "_model", "_sleeper")

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        sdk_client: object | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        if not callable(sleeper):
            raise TypeError("sleeper must be callable")

        self._model = model.strip()
        self._client = (
            OpenAI(api_key=api_key.strip(), max_retries=0)
            if sdk_client is None
            else sdk_client
        )
        self._sleeper = sleeper

    def complete(self, request: ModelRequest) -> ModelResponse:
        mapped_input = _map_messages(request)
        mapped_tools = _map_tools(request.tool_schemas)

        response = None
        for attempt in range(3):
            try:
                response = self._client.responses.create(
                    model=self._model,
                    input=mapped_input,
                    tools=mapped_tools,
                    max_output_tokens=request.max_output_tokens,
                    store=False,
                    include=["reasoning.encrypted_content"],
                )
                break
            except OpenAIError as exc:
                if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
                    raise FatalModelError(
                        "OpenAI Responses request failed: authentication rejected"
                    ) from None
                if isinstance(exc, NotFoundError):
                    raise FatalModelError(
                        "OpenAI Responses request failed: "
                        "model or endpoint not found"
                    ) from None
                if isinstance(exc, (BadRequestError, UnprocessableEntityError)):
                    raise FatalModelError(
                        "OpenAI Responses request failed: request rejected"
                    ) from None

                status_code = getattr(exc, "status_code", None)
                is_transient = isinstance(
                    exc,
                    (
                        RateLimitError,
                        InternalServerError,
                        APITimeoutError,
                        APIConnectionError,
                    ),
                ) or (
                    isinstance(exc, APIStatusError)
                    and isinstance(status_code, int)
                    and 500 <= status_code <= 599
                )
                if is_transient:
                    if attempt == 2:
                        raise TransientModelError(
                            "OpenAI Responses request failed after 3 attempts: "
                            "transient provider error"
                        ) from None
                    self._sleeper((0.25, 0.50)[attempt])
                    continue
                raise FatalModelError(
                    "OpenAI Responses request failed: provider error"
                ) from None

        assert response is not None

        text, tool_calls, usage, response_id, output_items = _parse_response(response)
        continuation = _OpenAIContinuationSegment(
            message_index=len(request.messages),
            serialized_items=tuple(
                _snapshot_output_item(item) for item in output_items
            ),
        )
        try:
            return ModelResponse(
                text=text,
                tool_calls=tool_calls,
                usage=usage,
                provider_response_id=response_id,
                continuation_items=request.continuation_items + (continuation,),
            )
        except (TypeError, ValueError) as exc:
            raise _invalid_response("invalid model response") from exc

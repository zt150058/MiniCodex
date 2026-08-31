from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
import time

from openai import (
    APIConnectionError,
    APIResponseValidationError,
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
from coding_agent.model import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    FatalModelError,
    InvalidModelResponseError,
    ModelBudgetExceeded,
    ModelBudgetReason,
    ModelCallBudget,
    ModelError,
    ModelOutputLimitError,
    TransientModelError,
    _model_error_code,
    invoke_model,
)
from coding_agent.streaming import (
    ModelStreamEvent,
    ModelStreamEventKind,
    ModelStreamHandler,
    StreamInterruptedError,
    StreamingUnsupportedError,
    _StreamCallbackError,
    invoke_model_stream,
)


class InvalidOpenAIResponseError(InvalidModelResponseError):
    """The provider returned a completed but unusable Responses payload."""

    observation_error_code = "invalid_model_response"


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
    response_status = _field(
        response,
        "status",
        "response status is not completed",
    )
    if response_status == "incomplete":
        details = _field(
            response,
            "incomplete_details",
            "response status is not completed",
        )
        if _field(details, "reason", "response status is not completed") == (
            "max_output_tokens"
        ):
            raise ModelOutputLimitError(
                "OpenAI Responses response reached the output token limit"
            )
    if response_status != "completed":
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


def _request_kwargs(
    model: str,
    request: ModelRequest,
    *,
    stream: bool,
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "model": model,
        "input": _map_messages(request),
        "tools": _map_tools(request.tool_schemas),
        "max_output_tokens": request.max_output_tokens,
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    if request.instructions is not None:
        kwargs["instructions"] = request.instructions
    if stream:
        kwargs["stream"] = True
    return kwargs


def _build_model_response(
    request: ModelRequest,
    response: object,
) -> ModelResponse:
    text, tool_calls, usage, response_id, output_items = _parse_response(response)
    continuation = _OpenAIContinuationSegment(
        message_index=len(request.messages),
        serialized_items=tuple(_snapshot_output_item(item) for item in output_items),
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


@dataclass(slots=True)
class _FunctionArgumentAccumulator:
    item_id: str
    fragments: list[str]
    done_name: str | None = None
    done_arguments: str | None = None


_RESPONSE_PHASE_EVENTS = {
    "response.created",
    "response.in_progress",
    "response.queued",
}
_OUTPUT_ITEM_EVENTS = {
    "response.output_item.added",
    "response.output_item.done",
}
_ALLOWED_OUTPUT_ITEM_TYPES = {"message", "function_call", "reasoning"}
_CONTENT_PART_EVENTS = {
    "response.content_part.added",
    "response.content_part.done",
}
_ALLOWED_CONTENT_PART_TYPES = {"output_text", "reasoning_text"}
_REASONING_PART_EVENTS = {
    "response.reasoning_summary_part.added",
    "response.reasoning_summary_part.done",
}
_REASONING_TEXT_EVENTS = {
    "response.reasoning_summary_text.delta",
    "response.reasoning_summary_text.done",
}
_REASONING_CONTENT_EVENTS = {
    "response.reasoning_text.delta",
    "response.reasoning_text.done",
}


def _stream_index(event: object, name: str) -> int:
    value = _field(event, name, "stream event index is invalid")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid_response("stream event index is invalid")
    return value


def _stream_identifier(event: object, name: str) -> str:
    value = _field(event, name, "stream event identifier is invalid")
    if not isinstance(value, str) or not value.strip():
        raise _invalid_response("stream event identifier is invalid")
    return value


def _validate_nonterminal_event(event: object, event_type: str) -> None:
    if event_type in _RESPONSE_PHASE_EVENTS:
        if _field(event, "response", "stream response is missing") is None:
            raise _invalid_response("stream response is missing")
        return
    if event_type in _OUTPUT_ITEM_EVENTS:
        _stream_index(event, "output_index")
        item = _field(event, "item", "stream output item is missing")
        if item is None:
            raise _invalid_response("stream output item is missing")
        if (
            _field(item, "type", "stream output item type is invalid")
            not in _ALLOWED_OUTPUT_ITEM_TYPES
        ):
            raise _invalid_response("unsupported stream output item type")
        return
    if event_type in _CONTENT_PART_EVENTS:
        _stream_index(event, "output_index")
        _stream_index(event, "content_index")
        _stream_identifier(event, "item_id")
        part = _field(event, "part", "stream content part is missing")
        if part is None:
            raise _invalid_response("stream content part is missing")
        if (
            _field(part, "type", "stream content part type is invalid")
            not in _ALLOWED_CONTENT_PART_TYPES
        ):
            raise _invalid_response("unsupported stream content part type")
        return
    if event_type == "response.output_text.done":
        _stream_index(event, "output_index")
        _stream_index(event, "content_index")
        _stream_identifier(event, "item_id")
        if not isinstance(_field(event, "text", "output text is invalid"), str):
            raise _invalid_response("output text is invalid")
        return
    if event_type in _REASONING_PART_EVENTS:
        _stream_index(event, "output_index")
        _stream_index(event, "summary_index")
        _stream_identifier(event, "item_id")
        if _field(event, "part", "reasoning summary part is missing") is None:
            raise _invalid_response("reasoning summary part is missing")
        return
    if event_type in _REASONING_TEXT_EVENTS:
        _stream_index(event, "output_index")
        _stream_index(event, "summary_index")
        _stream_identifier(event, "item_id")
        field_name = "delta" if event_type.endswith(".delta") else "text"
        if not isinstance(
            _field(event, field_name, "reasoning summary text is invalid"),
            str,
        ):
            raise _invalid_response("reasoning summary text is invalid")
        return
    if event_type in _REASONING_CONTENT_EVENTS:
        _stream_index(event, "output_index")
        _stream_index(event, "content_index")
        _stream_identifier(event, "item_id")
        field_name = "delta" if event_type.endswith(".delta") else "text"
        if not isinstance(
            _field(event, field_name, "reasoning text is invalid"),
            str,
        ):
            raise _invalid_response("reasoning text is invalid")
        return
    raise _invalid_response("unsupported stream event type")


def _validate_function_argument_streams(
    terminal: object,
    accumulators: dict[int, _FunctionArgumentAccumulator],
) -> None:
    output = _field(terminal, "output", "response output is missing")
    if not isinstance(output, (list, tuple)):
        raise _invalid_response("response output is missing")
    for output_index, accumulator in accumulators.items():
        if accumulator.done_name is None or accumulator.done_arguments is None:
            raise _invalid_response("function arguments are incomplete")
        if accumulator.done_arguments != "".join(accumulator.fragments):
            raise _invalid_response("function arguments do not match deltas")
        if output_index >= len(output):
            raise _invalid_response("function output index is invalid")
        item = output[output_index]
        if _field(item, "type", "function output is invalid") != "function_call":
            raise _invalid_response("function output is invalid")
        if _stream_identifier(item, "id") != accumulator.item_id:
            raise _invalid_response("function output identifier does not match")
        if _stream_identifier(item, "name") != accumulator.done_name:
            raise _invalid_response("function output name does not match")
        if (
            _field(item, "arguments", "function output arguments are invalid")
            != accumulator.done_arguments
        ):
            raise _invalid_response("function output arguments do not match")


@dataclass(slots=True)
class _ResponsesStreamProgress:
    provider_delta: bool = False


def _consume_responses_stream(
    stream: object,
    request: ModelRequest,
    emit: ModelStreamHandler,
    progress: _ResponsesStreamProgress,
) -> ModelResponse:
    terminal: object | None = None
    text_parts: list[str] = []
    function_arguments: dict[int, _FunctionArgumentAccumulator] = {}
    for event in stream:  # type: ignore[union-attr]
        event_type = _field(event, "type", "missing stream event type")
        if terminal is not None:
            raise _invalid_response("event follows completed response")
        if event_type == "response.output_text.delta":
            delta = _field(event, "delta", "output text delta is invalid")
            if not isinstance(delta, str) or not delta:
                raise _invalid_response("output text delta is invalid")
            progress.provider_delta = True
            text_parts.append(delta)
            emit(ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, delta))
        elif event_type == "response.function_call_arguments.delta":
            output_index = _stream_index(event, "output_index")
            item_id = _stream_identifier(event, "item_id")
            delta = _field(
                event,
                "delta",
                "function argument delta is invalid",
            )
            if not isinstance(delta, str) or not delta:
                raise _invalid_response("function argument delta is invalid")
            progress.provider_delta = True
            accumulator = function_arguments.get(output_index)
            if accumulator is None:
                accumulator = _FunctionArgumentAccumulator(
                    item_id=item_id,
                    fragments=[],
                )
                function_arguments[output_index] = accumulator
            elif accumulator.item_id != item_id:
                raise _invalid_response("function argument identifier changed")
            if accumulator.done_arguments is not None:
                raise _invalid_response("function argument delta follows done")
            accumulator.fragments.append(delta)
        elif event_type == "response.function_call_arguments.done":
            output_index = _stream_index(event, "output_index")
            item_id = _stream_identifier(event, "item_id")
            name = _stream_identifier(event, "name")
            arguments = _field(
                event,
                "arguments",
                "function arguments are invalid",
            )
            if not isinstance(arguments, str):
                raise _invalid_response("function arguments are invalid")
            accumulator = function_arguments.get(output_index)
            if accumulator is None or accumulator.item_id != item_id:
                raise _invalid_response(
                    "function argument done has no matching deltas"
                )
            if accumulator.done_arguments is not None:
                raise _invalid_response("duplicate function argument done")
            accumulator.done_name = name
            accumulator.done_arguments = arguments
        elif event_type in {"response.completed", "response.incomplete"}:
            terminal = _field(
                event,
                "response",
                "terminal response is missing",
            )
        else:
            if not isinstance(event_type, str):
                raise _invalid_response("missing stream event type")
            _validate_nonterminal_event(event, event_type)

    if terminal is None:
        raise _invalid_response("completed response is missing")
    _validate_function_argument_streams(terminal, function_arguments)
    response = _build_model_response(request, terminal)
    if text_parts and response.text != "".join(text_parts):
        raise _invalid_response("streamed text does not match response")
    return response


def _classify_responses_error(
    error: OpenAIError,
) -> tuple[str, str, bool]:
    if isinstance(error, AuthenticationError):
        return (
            "authentication_rejected",
            "OpenAI Responses request failed: authentication rejected",
            False,
        )
    if isinstance(error, PermissionDeniedError):
        return (
            "permission_rejected",
            "OpenAI Responses request failed: authentication rejected",
            False,
        )
    if isinstance(error, NotFoundError):
        return (
            "not_found",
            "OpenAI Responses request failed: model or endpoint not found",
            False,
        )
    if isinstance(error, (BadRequestError, UnprocessableEntityError)):
        return (
            "request_rejected",
            "OpenAI Responses request failed: request rejected",
            False,
        )
    if isinstance(error, RateLimitError):
        return ("rate_limit", "", True)
    if isinstance(error, APITimeoutError):
        return ("timeout", "", True)
    if isinstance(error, APIConnectionError):
        return ("connection_error", "", True)
    status_code = getattr(error, "status_code", None)
    if isinstance(error, InternalServerError) or (
        isinstance(error, APIStatusError)
        and isinstance(status_code, int)
        and 500 <= status_code <= 599
    ):
        return ("server_error", "", True)
    return (
        "provider_error",
        "OpenAI Responses request failed: provider error",
        False,
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
            OpenAI(
                api_key=api_key.strip(),
                max_retries=0,
                timeout=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
            )
            if sdk_client is None
            else sdk_client
        )
        self._sleeper = sleeper

    def complete(self, request: ModelRequest) -> ModelResponse:
        budget = ModelCallBudget(
            max_logical_calls=1,
            max_provider_attempts=3,
        )
        return invoke_model(self, request, budget)

    def complete_with_budget(
        self,
        request: ModelRequest,
        budget: ModelCallBudget,
    ) -> ModelResponse:
        request_kwargs = _request_kwargs(self._model, request, stream=False)
        purpose = budget.active_purpose

        response = None
        for attempt in range(3):
            provider_attempt_index = budget.begin_provider_attempt(purpose)
            try:
                response = self._client.responses.create(**request_kwargs)
                budget.finish_provider_attempt(
                    purpose,
                    provider_attempt_index,
                    error_code=None,
                    retry_scheduled=False,
                    retry_delay_ms=None,
                )
                break
            except OpenAIError as exc:
                if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
                    budget.finish_provider_attempt(
                        purpose,
                        provider_attempt_index,
                        error_code=(
                            "authentication_rejected"
                            if isinstance(exc, AuthenticationError)
                            else "permission_rejected"
                        ),
                        retry_scheduled=False,
                        retry_delay_ms=None,
                    )
                    raise FatalModelError(
                        "OpenAI Responses request failed: authentication rejected"
                    ) from None
                if isinstance(exc, NotFoundError):
                    budget.finish_provider_attempt(
                        purpose,
                        provider_attempt_index,
                        error_code="not_found",
                        retry_scheduled=False,
                        retry_delay_ms=None,
                    )
                    raise FatalModelError(
                        "OpenAI Responses request failed: "
                        "model or endpoint not found"
                    ) from None
                if isinstance(exc, (BadRequestError, UnprocessableEntityError)):
                    budget.finish_provider_attempt(
                        purpose,
                        provider_attempt_index,
                        error_code="request_rejected",
                        retry_scheduled=False,
                        retry_delay_ms=None,
                    )
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
                    if isinstance(exc, RateLimitError):
                        error_code = "rate_limit"
                    elif isinstance(exc, APITimeoutError):
                        error_code = "timeout"
                    elif isinstance(exc, APIConnectionError):
                        error_code = "connection_error"
                    else:
                        error_code = "server_error"
                    if attempt == 2:
                        budget.finish_provider_attempt(
                            purpose,
                            provider_attempt_index,
                            error_code=error_code,
                            retry_scheduled=False,
                            retry_delay_ms=None,
                        )
                        raise TransientModelError(
                            "OpenAI Responses request failed after 3 attempts: "
                            "transient provider error"
                        ) from None
                    if budget.remaining_provider_attempts == 0:
                        budget.finish_provider_attempt(
                            purpose,
                            provider_attempt_index,
                            error_code=error_code,
                            retry_scheduled=False,
                            retry_delay_ms=None,
                        )
                        budget.begin_provider_attempt(purpose)
                        raise AssertionError("unreachable provider budget branch")
                    delay = (0.25, 0.50)[attempt]
                    budget.finish_provider_attempt(
                        purpose,
                        provider_attempt_index,
                        error_code=error_code,
                        retry_scheduled=True,
                        retry_delay_ms=int(delay * 1000),
                    )
                    self._sleeper(delay)
                    continue
                budget.finish_provider_attempt(
                    purpose,
                    provider_attempt_index,
                    error_code="provider_error",
                    retry_scheduled=False,
                    retry_delay_ms=None,
                )
                raise FatalModelError(
                    "OpenAI Responses request failed: provider error"
                ) from None

        assert response is not None

        return _build_model_response(request, response)

    def stream(
        self,
        request: ModelRequest,
        emit: ModelStreamHandler,
    ) -> ModelResponse:
        budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=3)
        return invoke_model_stream(self, request, budget, emit)

    def stream_with_budget(
        self,
        request: ModelRequest,
        budget: ModelCallBudget,
        emit: ModelStreamHandler,
    ) -> ModelResponse:
        request_kwargs = _request_kwargs(self._model, request, stream=True)
        purpose = budget.active_purpose
        for attempt in range(3):
            provider_attempt_index = budget.begin_provider_attempt(purpose)
            progress = _ResponsesStreamProgress()
            try:
                stream = self._client.responses.create(**request_kwargs)
                close = getattr(stream, "close", None)
                try:
                    response = _consume_responses_stream(
                        stream,
                        request,
                        emit,
                        progress,
                    )
                except BaseException as primary:
                    if callable(close):
                        try:
                            close()
                        except BaseException:
                            pass
                    if progress.provider_delta and isinstance(
                        primary,
                        StreamingUnsupportedError,
                    ):
                        raise StreamInterruptedError(
                            "model stream interrupted"
                        ) from None
                    if progress.provider_delta and isinstance(primary, OpenAIError):
                        _, _, transient = _classify_responses_error(primary)
                        if transient:
                            raise StreamInterruptedError(
                                "model stream interrupted"
                            ) from None
                    raise
                else:
                    if callable(close):
                        try:
                            close()
                        except (KeyboardInterrupt, SystemExit):
                            raise
                        except Exception:
                            raise StreamInterruptedError(
                                "model stream cleanup failed"
                            ) from None
            except _StreamCallbackError as callback_error:
                if isinstance(callback_error.error, Exception):
                    budget.finish_provider_attempt(
                        purpose,
                        provider_attempt_index,
                        error_code=_model_error_code(callback_error.error),
                        retry_scheduled=False,
                        retry_delay_ms=None,
                    )
                raise
            except StreamingUnsupportedError:
                budget.finish_provider_attempt(
                    purpose,
                    provider_attempt_index,
                    error_code="streaming_unsupported",
                    retry_scheduled=False,
                    retry_delay_ms=None,
                )
                raise
            except StreamInterruptedError:
                budget.finish_provider_attempt(
                    purpose,
                    provider_attempt_index,
                    error_code="stream_interrupted",
                    retry_scheduled=False,
                    retry_delay_ms=None,
                )
                raise
            except (APIResponseValidationError, json.JSONDecodeError):
                budget.finish_provider_attempt(
                    purpose,
                    provider_attempt_index,
                    error_code="invalid_model_response",
                    retry_scheduled=False,
                    retry_delay_ms=None,
                )
                raise _invalid_response(
                    "provider stream could not be decoded"
                ) from None
            except InvalidOpenAIResponseError:
                budget.finish_provider_attempt(
                    purpose,
                    provider_attempt_index,
                    error_code="invalid_model_response",
                    retry_scheduled=False,
                    retry_delay_ms=None,
                )
                raise
            except ModelOutputLimitError:
                budget.finish_provider_attempt(
                    purpose,
                    provider_attempt_index,
                    error_code="model_output_limit",
                    retry_scheduled=False,
                    retry_delay_ms=None,
                )
                raise
            except OpenAIError as exc:
                error_code, public_message, transient = _classify_responses_error(
                    exc
                )
                if not transient:
                    budget.finish_provider_attempt(
                        purpose,
                        provider_attempt_index,
                        error_code=error_code,
                        retry_scheduled=False,
                        retry_delay_ms=None,
                    )
                    raise FatalModelError(public_message) from None
                if attempt == 2:
                    budget.finish_provider_attempt(
                        purpose,
                        provider_attempt_index,
                        error_code=error_code,
                        retry_scheduled=False,
                        retry_delay_ms=None,
                    )
                    raise TransientModelError(
                        "OpenAI Responses stream failed after 3 attempts: "
                        "transient provider error"
                    ) from None
                if budget.remaining_provider_attempts == 0:
                    budget.finish_provider_attempt(
                        purpose,
                        provider_attempt_index,
                        error_code=error_code,
                        retry_scheduled=False,
                        retry_delay_ms=None,
                    )
                    budget.begin_provider_attempt(purpose)
                    raise AssertionError("unreachable provider budget branch")
                delay = (0.25, 0.50)[attempt]
                budget.finish_provider_attempt(
                    purpose,
                    provider_attempt_index,
                    error_code=error_code,
                    retry_scheduled=True,
                    retry_delay_ms=int(delay * 1000),
                )
                self._sleeper(delay)
                continue
            except Exception as exc:
                budget.finish_provider_attempt(
                    purpose,
                    provider_attempt_index,
                    error_code=_model_error_code(exc),
                    retry_scheduled=False,
                    retry_delay_ms=None,
                )
                raise

            budget.finish_provider_attempt(
                purpose,
                provider_attempt_index,
                error_code=None,
                retry_scheduled=False,
                retry_delay_ms=None,
            )
            return response

        raise AssertionError("unreachable OpenAI Responses stream retry loop")

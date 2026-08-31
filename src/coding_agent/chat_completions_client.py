from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
import time
from urllib.parse import urlsplit

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


class InvalidChatCompletionsResponseError(InvalidModelResponseError):
    """The provider returned a completed but unusable Chat payload."""

    observation_error_code = "invalid_model_response"


_BASE_URL_ERROR = (
    "Chat Completions base_url must be an absolute HTTPS URL without "
    "userinfo, query, or fragment"
)
_STRICT_SCHEMA_ERROR = (
    "Chat Completions request is invalid: tool schema is not strict"
)
_CONTINUATION_ERROR = (
    "Chat Completions request is invalid: continuation must be empty"
)
_MESSAGE_ORDER_ERROR = (
    "Chat Completions request is invalid: assistant tool calls must be "
    "followed by matching tool results"
)


def _canonical_json(value: JSONObject) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _normalize_base_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError(_BASE_URL_ERROR)
    if any(
        ord(character) <= 0x1F
        or ord(character) == 0x7F
        or character == "\\"
        for character in value
    ):
        raise ValueError(_BASE_URL_ERROR)
    normalized = value.strip(" ")
    if not normalized:
        raise ValueError(_BASE_URL_ERROR)
    if any(character.isspace() for character in normalized):
        raise ValueError(_BASE_URL_ERROR)
    try:
        parsed = urlsplit(normalized)
        host = parsed.hostname
        parsed.port
    except ValueError:
        raise ValueError(_BASE_URL_ERROR) from None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or host is None
        or not host.strip()
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in parsed.netloc)
        or "?" in normalized
        or "#" in normalized
    ):
        raise ValueError(_BASE_URL_ERROR)
    return normalized.rstrip("/") + "/"


_MISSING = object()


def _invalid_response(reason: str) -> InvalidChatCompletionsResponseError:
    return InvalidChatCompletionsResponseError(
        f"invalid Chat Completions payload: {reason}"
    )


def _field(value: object, name: str, reason: str) -> object:
    if isinstance(value, Mapping):
        found = value.get(name, _MISSING)
    else:
        found = getattr(value, name, _MISSING)
    if found is _MISSING:
        raise _invalid_response(reason)
    return found


def _optional_field(value: object, name: str) -> object | None:
    if isinstance(value, Mapping):
        return value.get(name, None)
    return getattr(value, name, None)


def _parse_response(response: object) -> ModelResponse:
    choices = _field(
        response,
        "choices",
        "response must contain exactly one choice",
    )
    if not isinstance(choices, (list, tuple)) or len(choices) != 1:
        raise _invalid_response("response must contain exactly one choice")
    choice = choices[0]
    finish_reason = _field(
        choice,
        "finish_reason",
        "finish reason is not supported",
    )
    if finish_reason == "length":
        raise ModelOutputLimitError(
            "Chat Completions response reached the output token limit"
        )
    if finish_reason not in {"stop", "tool_calls"}:
        raise _invalid_response("finish reason is not supported")

    message = _field(choice, "message", "choice message is invalid")
    if _field(message, "role", "choice message is invalid") != "assistant":
        raise _invalid_response("choice message is invalid")
    if _optional_field(message, "function_call") is not None:
        raise _invalid_response("legacy function_call is not supported")

    content = _field(message, "content", "assistant content is invalid")
    if content is None:
        text = None
    elif isinstance(content, str):
        text = content if content.strip() else None
    else:
        raise _invalid_response("assistant content is invalid")

    raw_calls = _field(message, "tool_calls", "tool_calls is invalid")
    if raw_calls is None:
        raw_calls = []
    if not isinstance(raw_calls, (list, tuple)):
        raise _invalid_response("tool_calls is invalid")

    calls: list[ToolCall] = []
    seen_ids: set[str] = set()
    for raw_call in raw_calls:
        if (
            _field(raw_call, "type", "unsupported tool call type")
            != "function"
        ):
            raise _invalid_response("unsupported tool call type")
        call_id = _field(
            raw_call,
            "id",
            "function call id is invalid",
        )
        if not isinstance(call_id, str) or not call_id.strip():
            raise _invalid_response("function call id is invalid")
        normalized_call_id = call_id.strip()
        if normalized_call_id in seen_ids:
            raise _invalid_response("duplicate function call id")
        function = _field(raw_call, "function", "function call is invalid")
        name = _field(function, "name", "function call is invalid")
        if not isinstance(name, str) or not name.strip():
            raise _invalid_response("function call is invalid")
        encoded_arguments = _field(
            function,
            "arguments",
            "function arguments are not valid JSON",
        )
        if not isinstance(encoded_arguments, str):
            raise _invalid_response("function arguments are not valid JSON")
        try:
            arguments = json.loads(encoded_arguments)
        except json.JSONDecodeError:
            raise _invalid_response(
                "function arguments are not valid JSON"
            ) from None
        if not isinstance(arguments, dict):
            raise _invalid_response("function arguments must be an object")
        try:
            calls.append(
                ToolCall(
                    call_id=normalized_call_id,
                    name=name,
                    arguments=arguments,
                )
            )
        except (TypeError, ValueError):
            raise _invalid_response("function call is invalid") from None
        seen_ids.add(normalized_call_id)

    if text is None and not calls:
        raise _invalid_response("no text or function tool calls")

    raw_id = _optional_field(response, "id")
    if raw_id is None:
        response_id = None
    elif isinstance(raw_id, str) and raw_id.strip():
        response_id = raw_id.strip()
    else:
        raise _invalid_response("response id is invalid")

    raw_usage = _optional_field(response, "usage")
    usage = None
    if raw_usage is not None:
        try:
            usage = TokenUsage(
                input_tokens=_field(
                    raw_usage,
                    "prompt_tokens",
                    "usage is invalid",
                ),
                output_tokens=_field(
                    raw_usage,
                    "completion_tokens",
                    "usage is invalid",
                ),
                total_tokens=_field(
                    raw_usage,
                    "total_tokens",
                    "usage is invalid",
                ),
            )
        except InvalidChatCompletionsResponseError:
            raise
        except (TypeError, ValueError):
            raise _invalid_response("usage is invalid") from None

    try:
        return ModelResponse(
            text=text,
            tool_calls=tuple(calls),
            usage=usage,
            provider_response_id=response_id,
            continuation_items=(),
        )
    except (TypeError, ValueError):
        raise _invalid_response("invalid model response") from None


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


def _map_tools(
    tool_schemas: tuple[JSONObject, ...],
) -> list[dict[str, object]]:
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
                "function": {
                    "name": name,
                    "description": description,
                    "strict": True,
                    "parameters": deepcopy(parameters),
                },
            }
        )
    return mapped


def _validate_message_order(request: ModelRequest) -> None:
    index = 0
    while index < len(request.messages):
        message = request.messages[index]
        if isinstance(message, ToolResult):
            raise FatalModelError(_MESSAGE_ORDER_ERROR)
        if not isinstance(message, AssistantMessage) or not message.tool_calls:
            index += 1
            continue
        first_result = index + 1
        after_results = first_result + len(message.tool_calls)
        if after_results > len(request.messages):
            raise FatalModelError(_MESSAGE_ORDER_ERROR)
        results = request.messages[first_result:after_results]
        for call, result in zip(message.tool_calls, results, strict=True):
            if (
                not isinstance(result, ToolResult)
                or result.call_id != call.call_id
                or result.tool_name != call.name
            ):
                raise FatalModelError(_MESSAGE_ORDER_ERROR)
        index = after_results


def _map_messages(request: ModelRequest) -> list[dict[str, object]]:
    if request.continuation_items:
        raise FatalModelError(_CONTINUATION_ERROR)
    _validate_message_order(request)
    mapped: list[dict[str, object]] = []
    if request.instructions is not None:
        mapped.append({"role": "system", "content": request.instructions})
    for message in request.messages:
        if isinstance(message, UserMessage):
            mapped.append({"role": "user", "content": message.content})
        elif isinstance(message, AssistantMessage):
            assistant: dict[str, object] = {
                "role": "assistant",
                "content": message.content,
            }
            if message.tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": call.call_id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": _canonical_json(call.arguments),
                        },
                    }
                    for call in message.tool_calls
                ]
            mapped.append(assistant)
        else:
            mapped.append(
                {
                    "role": "tool",
                    "tool_call_id": message.call_id,
                    "content": message.to_json(),
                }
            )
    return mapped


def _request_kwargs(
    model: str,
    request: ModelRequest,
    *,
    stream: bool,
) -> dict[str, object]:
    request_kwargs: dict[str, object] = {
        "model": model,
        "messages": _map_messages(request),
        "max_tokens": request.max_output_tokens,
    }
    mapped_tools = _map_tools(request.tool_schemas)
    if mapped_tools:
        request_kwargs["tools"] = mapped_tools
    if stream:
        request_kwargs["stream"] = True
    return request_kwargs


@dataclass(slots=True)
class _ChatToolAccumulator:
    call_id: str | None = None
    call_type: str | None = None
    name: str | None = None
    argument_fragments: list[str] | None = None

    def __post_init__(self) -> None:
        if self.argument_fragments is None:
            self.argument_fragments = []


@dataclass(slots=True)
class _ChatStreamProgress:
    provider_delta: bool = False
    public_text_delta: bool = False


def _stable_fragment(
    current: str | None,
    incoming: object,
    *,
    field_name: str,
) -> str | None:
    if incoming is None:
        return current
    if current is not None and incoming == "":
        return current
    if not isinstance(incoming, str) or not incoming.strip():
        raise _invalid_response(f"tool {field_name} is invalid")
    normalized = incoming.strip()
    if current is not None and current != normalized:
        raise _invalid_response(f"tool {field_name} changed during stream")
    return normalized


def _consume_chat_stream(
    stream: object,
    emit: ModelStreamHandler,
    progress: _ChatStreamProgress,
) -> ModelResponse:
    text_parts: list[str] = []
    finish_reason: object = None
    response_id: str | None = None
    usage: object = None
    tool_accumulators: dict[int, _ChatToolAccumulator] = {}
    for chunk in stream:  # type: ignore[union-attr]
        raw_id = _optional_field(chunk, "id")
        if raw_id is not None:
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise _invalid_response("response id is invalid")
            normalized_id = raw_id.strip()
            if response_id is not None and response_id != normalized_id:
                raise _invalid_response("response id changed during stream")
            response_id = normalized_id
        raw_usage = _optional_field(chunk, "usage")
        if raw_usage is not None:
            if usage is not None:
                raise _invalid_response("duplicate usage")
            usage = raw_usage
        choices = _field(
            chunk,
            "choices",
            "stream chunk choices are invalid",
        )
        if not isinstance(choices, (list, tuple)) or len(choices) > 1:
            raise _invalid_response("stream chunk choices are invalid")
        if not choices:
            if raw_usage is None:
                raise _invalid_response("empty stream chunk is invalid")
            continue
        choice = choices[0]
        next_finish = _optional_field(choice, "finish_reason")
        if finish_reason is not None:
            if next_finish is not None:
                raise _invalid_response("duplicate finish reason")
            raise _invalid_response("chunk follows finish reason")
        if _field(choice, "index", "stream choice index is invalid") != 0:
            raise _invalid_response("stream choice index is invalid")
        delta = _field(choice, "delta", "stream delta is invalid")
        role = _optional_field(delta, "role")
        if role not in {None, "assistant"}:
            raise _invalid_response("stream delta role is invalid")
        if _optional_field(delta, "function_call") is not None:
            raise _invalid_response("legacy function_call is not supported")
        if _optional_field(delta, "refusal") is not None:
            raise _invalid_response("stream refusal is not supported")
        raw_tool_calls = _optional_field(delta, "tool_calls")
        if raw_tool_calls is not None:
            if not isinstance(raw_tool_calls, (list, tuple)):
                raise _invalid_response("stream tool calls are invalid")
            for raw_call in raw_tool_calls:
                raw_index = _field(
                    raw_call,
                    "index",
                    "tool index is invalid",
                )
                if (
                    isinstance(raw_index, bool)
                    or not isinstance(raw_index, int)
                    or raw_index < 0
                ):
                    raise _invalid_response("tool index is invalid")
                accumulator = tool_accumulators.setdefault(
                    raw_index,
                    _ChatToolAccumulator(),
                )
                accumulator.call_id = _stable_fragment(
                    accumulator.call_id,
                    _optional_field(raw_call, "id"),
                    field_name="identifier",
                )
                accumulator.call_type = _stable_fragment(
                    accumulator.call_type,
                    _optional_field(raw_call, "type"),
                    field_name="type",
                )
                if (
                    accumulator.call_type is not None
                    and accumulator.call_type != "function"
                ):
                    raise _invalid_response("unsupported tool call type")
                function = _field(
                    raw_call,
                    "function",
                    "stream function call is invalid",
                )
                accumulator.name = _stable_fragment(
                    accumulator.name,
                    _optional_field(function, "name"),
                    field_name="name",
                )
                arguments = _optional_field(function, "arguments")
                if arguments is not None:
                    if not isinstance(arguments, str):
                        raise _invalid_response(
                            "function argument fragment is invalid"
                        )
                    progress.provider_delta = True
                    assert accumulator.argument_fragments is not None
                    accumulator.argument_fragments.append(arguments)
        content = _optional_field(delta, "content")
        if content is not None:
            if not isinstance(content, str):
                raise _invalid_response("stream content is invalid")
            if content:
                progress.provider_delta = True
                text_parts.append(content)
                emit(ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, content))
                progress.public_text_delta = True
        if next_finish is not None:
            if finish_reason is not None:
                raise _invalid_response("duplicate finish reason")
            finish_reason = next_finish

    if finish_reason is None:
        raise _invalid_response("finish reason is not supported")
    if sorted(tool_accumulators) != list(range(len(tool_accumulators))):
        raise _invalid_response("tool index sequence is invalid")
    raw_calls: list[dict[str, object]] = []
    seen_call_ids: set[str] = set()
    for index in range(len(tool_accumulators)):
        accumulator = tool_accumulators[index]
        if (
            accumulator.call_id is None
            or accumulator.call_type != "function"
            or accumulator.name is None
        ):
            raise _invalid_response("stream function call is incomplete")
        if accumulator.call_id in seen_call_ids:
            raise _invalid_response("duplicate function call id")
        seen_call_ids.add(accumulator.call_id)
        assert accumulator.argument_fragments is not None
        raw_calls.append(
            {
                "id": accumulator.call_id,
                "type": "function",
                "function": {
                    "name": accumulator.name,
                    "arguments": "".join(accumulator.argument_fragments),
                },
            }
        )
    aggregate = {
        "id": response_id,
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {
                    "role": "assistant",
                    "content": "".join(text_parts) or None,
                    "tool_calls": raw_calls or None,
                    "function_call": None,
                },
            }
        ],
        "usage": usage,
    }
    return _parse_response(aggregate)


def _classify_provider_error(
    error: OpenAIError,
) -> tuple[str, str, bool]:
    if isinstance(error, AuthenticationError):
        return (
            "authentication_rejected",
            "Chat Completions request failed: authentication rejected",
            False,
        )
    if isinstance(error, PermissionDeniedError):
        return (
            "permission_rejected",
            "Chat Completions request failed: authentication rejected",
            False,
        )
    if isinstance(error, NotFoundError):
        return (
            "not_found",
            "Chat Completions request failed: model or endpoint not found",
            False,
        )
    if isinstance(error, (BadRequestError, UnprocessableEntityError)):
        return (
            "request_rejected",
            "Chat Completions request failed: request rejected",
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
        "Chat Completions request failed: provider error",
        False,
    )


class ChatCompletionsModelClient:
    __slots__ = ("_client", "_model", "_sleeper")

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        sdk_client: object | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        normalized_base_url = _normalize_base_url(base_url)
        if not callable(sleeper):
            raise TypeError("sleeper must be callable")
        self._model = model.strip()
        self._client = (
            OpenAI(
                api_key=api_key.strip(),
                base_url=normalized_base_url,
                max_retries=0,
                timeout=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
            )
            if sdk_client is None
            else sdk_client
        )
        self._sleeper = sleeper

    def complete(self, request: ModelRequest) -> ModelResponse:
        budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=3)
        return invoke_model(self, request, budget)

    def complete_with_budget(
        self,
        request: ModelRequest,
        budget: ModelCallBudget,
    ) -> ModelResponse:
        return self._complete_with_attempt_limit(
            request,
            budget,
            max_attempts=3,
            fallback=False,
        )

    def _complete_with_attempt_limit(
        self,
        request: ModelRequest,
        budget: ModelCallBudget,
        *,
        max_attempts: int,
        fallback: bool,
    ) -> ModelResponse:
        request_kwargs = _request_kwargs(self._model, request, stream=False)
        purpose = budget.active_purpose

        for attempt in range(max_attempts):
            provider_attempt_index = budget.begin_provider_attempt(purpose)
            try:
                response = self._client.chat.completions.create(**request_kwargs)
            except (APIResponseValidationError, json.JSONDecodeError):
                budget.finish_provider_attempt(
                    purpose,
                    provider_attempt_index,
                    error_code="invalid_model_response",
                    retry_scheduled=False,
                    retry_delay_ms=None,
                )
                raise InvalidChatCompletionsResponseError(
                    "invalid Chat Completions payload: "
                    "provider response could not be decoded"
                ) from None
            except OpenAIError as exc:
                error_code, public_message, transient = _classify_provider_error(
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
                if attempt == max_attempts - 1:
                    budget.finish_provider_attempt(
                        purpose,
                        provider_attempt_index,
                        error_code=error_code,
                        retry_scheduled=False,
                        retry_delay_ms=None,
                    )
                    if fallback:
                        raise TransientModelError(
                            "Chat Completions fallback request failed: "
                            "transient provider error"
                        ) from None
                    raise TransientModelError(
                        "Chat Completions request failed after 3 attempts: "
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
            try:
                parsed = _parse_response(response)
            except (InvalidChatCompletionsResponseError, ModelOutputLimitError) as exc:
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
            return parsed

        raise AssertionError("unreachable Chat Completions retry loop")

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
            progress = _ChatStreamProgress()
            try:
                stream = self._client.chat.completions.create(**request_kwargs)
                close = getattr(stream, "close", None)
                try:
                    response = _consume_chat_stream(stream, emit, progress)
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
                        _, _, transient = _classify_provider_error(primary)
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
                if not progress.public_text_delta:
                    return self._complete_with_attempt_limit(
                        request,
                        budget,
                        max_attempts=1,
                        fallback=True,
                    )
                raise InvalidChatCompletionsResponseError(
                    "invalid Chat Completions payload: "
                    "provider response could not be decoded"
                ) from None
            except InvalidChatCompletionsResponseError:
                budget.finish_provider_attempt(
                    purpose,
                    provider_attempt_index,
                    error_code="invalid_model_response",
                    retry_scheduled=False,
                    retry_delay_ms=None,
                )
                if not progress.public_text_delta:
                    return self._complete_with_attempt_limit(
                        request,
                        budget,
                        max_attempts=1,
                        fallback=True,
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
                error_code, public_message, transient = _classify_provider_error(
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
                        "Chat Completions stream failed after 3 attempts: "
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

        raise AssertionError("unreachable Chat Completions stream retry loop")

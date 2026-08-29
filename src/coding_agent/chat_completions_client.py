from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
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
    FatalModelError,
    ModelCallBudget,
    ModelError,
    TransientModelError,
    invoke_model,
)


class InvalidChatCompletionsResponseError(ModelError):
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
        mapped_messages = _map_messages(request)
        mapped_tools = _map_tools(request.tool_schemas)
        request_kwargs: dict[str, object] = {
            "model": self._model,
            "messages": mapped_messages,
            "max_tokens": request.max_output_tokens,
        }
        if mapped_tools:
            request_kwargs["tools"] = mapped_tools
        purpose = budget.active_purpose

        for attempt in range(3):
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
                if attempt == 2:
                    budget.finish_provider_attempt(
                        purpose,
                        provider_attempt_index,
                        error_code=error_code,
                        retry_scheduled=False,
                        retry_delay_ms=None,
                    )
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
            budget.finish_provider_attempt(
                purpose,
                provider_attempt_index,
                error_code=None,
                retry_scheduled=False,
                retry_delay_ms=None,
            )
            return _parse_response(response)

        raise AssertionError("unreachable Chat Completions retry loop")

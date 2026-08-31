from __future__ import annotations

from collections import deque
from copy import deepcopy
import inspect
import json
import os
import subprocess
import sys
import traceback
from types import SimpleNamespace

import pytest
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

from coding_agent.chat_completions_client import (
    ChatCompletionsModelClient,
    InvalidChatCompletionsResponseError,
    _map_messages,
    _map_tools,
    _normalize_base_url,
    _parse_response,
)
from coding_agent.messages import (
    AssistantMessage,
    ModelRequest,
    TokenUsage,
    ToolCall,
    ToolResult,
    UserMessage,
)
from coding_agent.model import (
    FatalModelError,
    ModelBudgetExceeded,
    ModelBudgetReason,
    ModelCallBudget,
    ModelClient,
    ModelObservation,
    ModelObservationKind,
    ModelOutputLimitError,
    TransientModelError,
    invoke_model,
)


FAKE_KEY = "chat-unit-key-never-send"
FAKE_BASE_URL = "https://provider.example/api/maas/v1/"
TOOL_SCHEMA = {
    "name": "echo",
    "description": "Return the supplied text.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
}


def test_complete_history_maps_to_standard_chat_messages() -> None:
    first = ToolCall("call_1", "echo", {"z": 2, "text": "雪"})
    second = ToolCall("call_2", "echo", {"text": "two"})
    first_result = ToolResult(
        call_id="call_1",
        tool_name="echo",
        status="ok",
        output="one",
    )
    second_result = ToolResult(
        call_id="call_2",
        tool_name="echo",
        status="ok",
        output="two",
    )
    request = ModelRequest(
        messages=(
            UserMessage("begin"),
            AssistantMessage(content="calling", tool_calls=(first, second)),
            first_result,
            second_result,
            AssistantMessage(content="prior text"),
            UserMessage("continue"),
        )
    )

    assert _map_messages(request) == [
        {"role": "user", "content": "begin"},
        {
            "role": "assistant",
            "content": "calling",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "echo",
                        "arguments": '{"text":"雪","z":2}',
                    },
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "echo",
                        "arguments": '{"text":"two"}',
                    },
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": first_result.to_json(),
        },
        {
            "role": "tool",
            "tool_call_id": "call_2",
            "content": second_result.to_json(),
        },
        {"role": "assistant", "content": "prior text"},
        {"role": "user", "content": "continue"},
    ]


def test_strict_tool_maps_to_nested_chat_function() -> None:
    original = deepcopy(TOOL_SCHEMA)

    assert _map_tools((TOOL_SCHEMA,)) == [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Return the supplied text.",
                "strict": True,
                "parameters": TOOL_SCHEMA["parameters"],
            },
        }
    ]
    assert TOOL_SCHEMA == original


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
                "properties": {"text": {"type": "string"}},
                "required": [],
                "additionalProperties": False,
            },
        },
        {key: value for key, value in TOOL_SCHEMA.items() if key != "description"},
        {**TOOL_SCHEMA, "extra": True},
    ],
)
def test_non_strict_schema_is_rejected_without_schema_echo(
    schema: dict[str, object],
) -> None:
    with pytest.raises(
        FatalModelError,
        match="Chat Completions request is invalid: tool schema is not strict",
    ) as caught:
        _map_tools((schema,))  # type: ignore[arg-type]

    assert "additionalProperties" not in str(caught.value)
    assert "provider.example" not in str(caught.value)


def test_nonempty_continuation_is_rejected_before_mapping() -> None:
    request = ModelRequest(
        messages=(UserMessage("begin"),),
        continuation_items=(object(),),
    )

    with pytest.raises(FatalModelError, match="continuation must be empty"):
        _map_messages(request)


def test_tool_results_must_immediately_match_assistant_call_order() -> None:
    first = ToolCall("call_1", "echo", {"text": "one"})
    second = ToolCall("call_2", "echo", {"text": "two"})
    request = ModelRequest(
        messages=(
            UserMessage("begin"),
            AssistantMessage(tool_calls=(first, second)),
            ToolResult("call_2", "echo", "ok"),
            ToolResult("call_1", "echo", "ok"),
        )
    )

    with pytest.raises(FatalModelError, match="matching tool results"):
        _map_messages(request)


def test_no_message_may_interrupt_assistant_tool_results() -> None:
    call = ToolCall("call_1", "echo", {"text": "one"})
    request = ModelRequest(
        messages=(
            UserMessage("begin"),
            AssistantMessage(tool_calls=(call,)),
            UserMessage("interrupt"),
            ToolResult("call_1", "echo", "ok"),
        )
    )

    with pytest.raises(FatalModelError, match="matching tool results"):
        _map_messages(request)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://provider.example", "https://provider.example/"),
        (
            "  https://provider.example/api/maas/v1  ",
            "https://provider.example/api/maas/v1/",
        ),
        (
            "https://provider.example/api/maas/v1/",
            "https://provider.example/api/maas/v1/",
        ),
    ],
)
def test_base_url_normalizes_https_path_prefix(value: str, expected: str) -> None:
    assert _normalize_base_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://provider.example/v1",
        "provider.example/v1",
        "https:///api/v1",
        "https://user:pass@provider.example/v1",
        "https://provider.example/v1?region=x",
        "https://provider.example/v1#section",
        "https://provider.example:invalid/v1",
        "https://pro vider.example/v1",
        "\x00https://provider.example/v1",
        "\thttps://provider.example/v1",
        "https://provider.example/v1\tbad",
        "https://provider.example/v1\u00a0bad",
        "\x7fhttps://provider.example/v1",
        r"https://provider.example/v1\bad",
    ],
)
def test_base_url_rejects_unsafe_shapes_without_value_echo(value: str) -> None:
    with pytest.raises(ValueError) as caught:
        _normalize_base_url(value)

    assert str(caught.value) == (
        "Chat Completions base_url must be an absolute HTTPS URL without "
        "userinfo, query, or fragment"
    )
    if value:
        assert value not in str(caught.value)


def tool_call_item(
    call_id: str,
    *,
    name: str = "echo",
    arguments: object = '{"text":"hello"}',
    call_type: str = "function",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        type=call_type,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def chat_response(
    *,
    content: object = "done",
    tool_calls: object = None,
    finish_reason: object = "stop",
    response_id: object = "chatcmpl_test",
    usage: object | None = None,
    role: object = "assistant",
    legacy_function_call: object | None = None,
) -> SimpleNamespace:
    message = SimpleNamespace(
        role=role,
        content=content,
        tool_calls=tool_calls,
        function_call=legacy_function_call,
    )
    return SimpleNamespace(
        id=response_id,
        model="provider-returned-model-name-is-not-enforced",
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=usage,
    )


class FakeCompletionsResource:
    def __init__(self, outcomes: tuple[object, ...]) -> None:
        self.outcomes = deque(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(deepcopy(kwargs))
        if not self.outcomes:
            raise AssertionError("unexpected Chat Completions API call")
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeSDKClient:
    def __init__(self, *outcomes: object) -> None:
        completions = FakeCompletionsResource(outcomes)
        self.chat = SimpleNamespace(completions=completions)


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


class FakeUnprocessableError(UnprocessableEntityError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeNotFoundError(NotFoundError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeProviderError(OpenAIError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeAPIResponseValidationError(APIResponseValidationError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class RecordingModelObserver:
    def __init__(self) -> None:
        self.items: list[ModelObservation] = []

    def observe_model(self, observation: ModelObservation) -> None:
        self.items.append(observation)


def test_public_client_matches_existing_protocol_and_signature() -> None:
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=FakeSDKClient(chat_response()),
        sleeper=lambda delay: None,
    )

    assert isinstance(client, ModelClient)
    assert tuple(
        inspect.signature(ChatCompletionsModelClient.complete).parameters
    ) == ("self", "request")


def test_constructor_disables_sdk_retries_and_does_not_store_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    fake_sdk = FakeSDKClient(chat_response())

    def factory(**kwargs: object) -> FakeSDKClient:
        observed.update(kwargs)
        return fake_sdk

    monkeypatch.setattr("coding_agent.chat_completions_client.OpenAI", factory)
    client = ChatCompletionsModelClient(
        model=" chat-model ",
        api_key=f" {FAKE_KEY} ",
        base_url="  https://provider.example/api/maas/v1  ",
        sleeper=lambda delay: None,
    )

    assert observed == {
        "api_key": FAKE_KEY,
        "base_url": FAKE_BASE_URL,
        "max_retries": 0,
    }
    rendered = repr(client)
    assert FAKE_KEY not in rendered
    assert "provider.example" not in rendered
    assert not hasattr(client, "__dict__")


@pytest.mark.parametrize(
    ("model", "api_key", "base_url", "sleeper", "message"),
    [
        ("", FAKE_KEY, FAKE_BASE_URL, None, "model must be a non-empty string"),
        ("chat-model", "", FAKE_BASE_URL, None, "api_key must be a non-empty string"),
        (
            "chat-model",
            FAKE_KEY,
            "http://secret-provider.example/v1",
            None,
            "Chat Completions base_url must be an absolute HTTPS URL",
        ),
        ("chat-model", FAKE_KEY, FAKE_BASE_URL, 42, "sleeper must be callable"),
    ],
)
def test_constructor_rejects_invalid_configuration_without_echoing_values(
    model: str,
    api_key: str,
    base_url: str,
    sleeper: object | None,
    message: str,
) -> None:
    kwargs: dict[str, object] = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "sdk_client": FakeSDKClient(chat_response()),
    }
    if sleeper is not None:
        kwargs["sleeper"] = sleeper

    with pytest.raises((TypeError, ValueError), match=message) as caught:
        ChatCompletionsModelClient(**kwargs)  # type: ignore[arg-type]

    rendered = str(caught.value)
    assert FAKE_KEY not in rendered
    assert "secret-provider.example" not in rendered


def test_complete_sends_exact_no_tool_request_fields() -> None:
    sdk = FakeSDKClient(chat_response(content="done"))
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )

    response = client.complete(
        ModelRequest(
            messages=(UserMessage("offline"),),
            max_output_tokens=321,
        )
    )

    assert response.text == "done"
    assert sdk.chat.completions.calls == [
        {
            "model": "chat-model",
            "messages": [{"role": "user", "content": "offline"}],
            "max_tokens": 321,
        }
    ]


def test_chat_maps_instructions_to_one_provider_only_system_message() -> None:
    sdk = FakeSDKClient(
        chat_response(content="ok"),
        chat_response(content="ok"),
    )
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
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


def test_complete_adds_nested_tools_only_when_present() -> None:
    sdk = FakeSDKClient(chat_response(content="done"))
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )

    client.complete(
        ModelRequest(
            messages=(UserMessage("offline"),),
            tool_schemas=(TOOL_SCHEMA,),
            max_output_tokens=123,
        )
    )

    assert sdk.chat.completions.calls == [
        {
            "model": "chat-model",
            "messages": [{"role": "user", "content": "offline"}],
            "max_tokens": 123,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "echo",
                        "description": "Return the supplied text.",
                        "strict": True,
                        "parameters": TOOL_SCHEMA["parameters"],
                    },
                }
            ],
        }
    ]


def test_local_request_failure_occurs_before_sdk_create() -> None:
    sdk = FakeSDKClient(chat_response(content="must not run"))
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )
    request = ModelRequest(
        messages=(UserMessage("offline"),),
        continuation_items=(object(),),
    )

    with pytest.raises(FatalModelError, match="continuation must be empty"):
        client.complete(request)

    assert sdk.chat.completions.calls == []


def test_text_response_maps_without_continuation() -> None:
    response = _parse_response(chat_response(content="done"))

    assert response.text == "done"
    assert response.tool_calls == ()
    assert response.usage is None
    assert response.provider_response_id == "chatcmpl_test"
    assert response.continuation_items == ()


def test_stop_with_text_and_multiple_tool_calls_preserves_all_outputs() -> None:
    response = _parse_response(
        chat_response(
            content="I will inspect.",
            tool_calls=[
                tool_call_item("call_2", arguments='{"text":"two"}'),
                tool_call_item("call_1", arguments='{"text":"one"}'),
            ],
            finish_reason="stop",
            usage=SimpleNamespace(
                prompt_tokens=12,
                completion_tokens=7,
                total_tokens=19,
            ),
        )
    )

    assert response.text == "I will inspect."
    assert [call.call_id for call in response.tool_calls] == ["call_2", "call_1"]
    assert [call.arguments["text"] for call in response.tool_calls] == [
        "two",
        "one",
    ]
    assert response.usage == TokenUsage(12, 7, 19)
    assert response.provider_response_id == "chatcmpl_test"
    assert response.continuation_items == ()


def test_tool_calls_finish_reason_does_not_require_text() -> None:
    response = _parse_response(
        chat_response(
            content=None,
            tool_calls=[tool_call_item("call_1")],
            finish_reason="tool_calls",
        )
    )

    assert response.text is None
    assert response.tool_calls == (
        ToolCall("call_1", "echo", {"text": "hello"}),
    )


@pytest.mark.parametrize("missing_id", [True, False])
def test_missing_or_null_response_id_is_allowed(missing_id: bool) -> None:
    raw = chat_response(response_id=None)
    if missing_id:
        del raw.id

    response = _parse_response(raw)

    assert response.provider_response_id is None


def response_with_choices(choices: object) -> SimpleNamespace:
    return SimpleNamespace(id="chatcmpl_bad", choices=choices, usage=None)


def test_finish_reason_length_is_a_distinct_output_limit_error() -> None:
    with pytest.raises(ModelOutputLimitError, match="output token limit"):
        _parse_response(chat_response(finish_reason="length"))


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (
            SimpleNamespace(id="chatcmpl_bad", usage=None),
            "response must contain exactly one choice",
        ),
        (response_with_choices([]), "response must contain exactly one choice"),
        (
            response_with_choices(
                [
                    chat_response().choices[0],
                    chat_response().choices[0],
                ]
            ),
            "response must contain exactly one choice",
        ),
        (
            response_with_choices("not-a-list"),
            "response must contain exactly one choice",
        ),
        (
            response_with_choices([SimpleNamespace(finish_reason="stop")]),
            "choice message is invalid",
        ),
        (chat_response(role="user"), "choice message is invalid"),
        (
            chat_response(finish_reason="content_filter"),
            "finish reason is not supported",
        ),
        (chat_response(finish_reason=None), "finish reason is not supported"),
        (chat_response(finish_reason="other"), "finish reason is not supported"),
        (chat_response(content=42), "assistant content is invalid"),
        (
            chat_response(content="   ", tool_calls=None),
            "no text or function tool calls",
        ),
        (
            chat_response(legacy_function_call=SimpleNamespace(name="echo")),
            "legacy function_call is not supported",
        ),
        (chat_response(tool_calls=42), "tool_calls is invalid"),
        (
            chat_response(
                content=None,
                tool_calls=[tool_call_item("call_1", call_type="custom")],
            ),
            "unsupported tool call type",
        ),
        (
            chat_response(content=None, tool_calls=[tool_call_item("")]),
            "function call id is invalid",
        ),
        (
            chat_response(
                content=None,
                tool_calls=[
                    SimpleNamespace(
                        type="function",
                        function=SimpleNamespace(
                            name="echo",
                            arguments="{}",
                        ),
                    )
                ],
            ),
            "function call id is invalid",
        ),
        (
            chat_response(
                content=None,
                tool_calls=[tool_call_item("same"), tool_call_item("same")],
            ),
            "duplicate function call id",
        ),
        (
            chat_response(
                content=None,
                tool_calls=[tool_call_item("call_1", name="   ")],
            ),
            "function call is invalid",
        ),
        (
            chat_response(
                content=None,
                tool_calls=[SimpleNamespace(id="call_1", type="function")],
            ),
            "function call is invalid",
        ),
        (
            chat_response(
                content=None,
                tool_calls=[tool_call_item("call_1", arguments=42)],
            ),
            "function arguments are not valid JSON",
        ),
        (
            chat_response(
                content=None,
                tool_calls=[tool_call_item("call_1", arguments="not-json")],
            ),
            "function arguments are not valid JSON",
        ),
        (
            chat_response(
                content=None,
                tool_calls=[tool_call_item("call_1", arguments="[]")],
            ),
            "function arguments must be an object",
        ),
        (chat_response(response_id=""), "response id is invalid"),
        (chat_response(response_id=42), "response id is invalid"),
        (
            chat_response(usage=SimpleNamespace(prompt_tokens=1, total_tokens=1)),
            "usage is invalid",
        ),
        (
            chat_response(
                usage=SimpleNamespace(
                    prompt_tokens=True,
                    completion_tokens=1,
                    total_tokens=2,
                )
            ),
            "usage is invalid",
        ),
        (
            chat_response(
                usage=SimpleNamespace(
                    prompt_tokens=-1,
                    completion_tokens=1,
                    total_tokens=0,
                )
            ),
            "usage is invalid",
        ),
        (
            chat_response(
                usage=SimpleNamespace(
                    prompt_tokens="1",
                    completion_tokens=1,
                    total_tokens=2,
                )
            ),
            "usage is invalid",
        ),
    ],
)
def test_invalid_response_shapes_raise_stable_redacted_error(
    response: object,
    reason: str,
) -> None:
    secret = "provider-body-secret-must-not-leak"
    setattr(response, "private_body", secret)

    with pytest.raises(
        InvalidChatCompletionsResponseError,
        match=f"invalid Chat Completions payload: {reason}",
    ) as caught:
        _parse_response(response)

    assert str(caught.value) == f"invalid Chat Completions payload: {reason}"
    assert secret not in str(caught.value)


@pytest.mark.parametrize(
    ("response", "reason", "marker"),
    [
        pytest.param(
            chat_response(
                content=None,
                tool_calls=[
                    tool_call_item(
                        "call_1",
                        arguments='{"secret":"parser-json-marker"',
                    )
                ],
            ),
            "function arguments are not valid JSON",
            "parser-json-marker",
            id="json-decode",
        ),
        pytest.param(
            chat_response(
                content=None,
                tool_calls=[
                    tool_call_item(
                        "call_1",
                        arguments=(
                            '{"secret":"parser-tool-marker","value":NaN}'
                        ),
                    )
                ],
            ),
            "function call is invalid",
            "parser-tool-marker",
            id="tool-call-validation",
        ),
        pytest.param(
            chat_response(
                content="done",
                usage=SimpleNamespace(
                    prompt_tokens="parser-usage-marker",
                    completion_tokens=1,
                    total_tokens=2,
                ),
            ),
            "usage is invalid",
            "parser-usage-marker",
            id="usage-validation",
        ),
    ],
)
def test_parser_payload_errors_remove_cause_and_sensitive_payload(
    response: object,
    reason: str,
    marker: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sdk = FakeSDKClient(response)
    observer = RecordingModelObserver()
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
    )
    budget = ModelCallBudget(observer=observer)

    with pytest.raises(
        InvalidChatCompletionsResponseError,
        match=f"^invalid Chat Completions payload: {reason}$",
    ) as caught:
        invoke_model(
            client,
            ModelRequest(messages=(UserMessage("offline"),)),
            budget,
        )

    assert caught.value.__cause__ is None
    logical_failures = [
        item
        for item in observer.items
        if item.kind is ModelObservationKind.LOGICAL_FAILED
    ]
    assert len(logical_failures) == 1
    assert logical_failures[0].error_code == "invalid_model_response"
    captured = capsys.readouterr()
    rendered = "".join(
        traceback.format_exception(
            caught.type,
            caught.value,
            caught.value.__traceback__,
        )
    ) + repr(observer.items) + captured.out + captured.err
    assert marker not in rendered
    assert FAKE_KEY not in rendered


@pytest.mark.parametrize(
    "provider_error",
    [
        FakeRateLimitError("hidden rate limit"),
        FakeServerError("hidden server error"),
        FakeTimeoutError("hidden timeout"),
        FakeConnectionError("hidden connection error"),
    ],
)
def test_each_transient_provider_error_retries_twice_and_recovers(
    provider_error: OpenAIError,
) -> None:
    delays: list[float] = []
    sdk = FakeSDKClient(
        provider_error,
        type(provider_error)("hidden again"),
        chat_response(content="recovered"),
    )
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=delays.append,
    )

    response = client.complete(ModelRequest(messages=(UserMessage("retry"),)))

    assert response.text == "recovered"
    assert len(sdk.chat.completions.calls) == 3
    assert delays == [0.25, 0.50]


def test_third_transient_failure_raises_stable_error_without_fourth_call() -> None:
    secret = "provider-error-must-not-leak"
    delays: list[float] = []
    sdk = FakeSDKClient(
        FakeRateLimitError(secret),
        FakeRateLimitError(secret),
        FakeRateLimitError(secret),
        chat_response(content="must not run"),
    )
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=delays.append,
    )

    with pytest.raises(TransientModelError) as caught:
        client.complete(ModelRequest(messages=(UserMessage("retry"),)))

    assert str(caught.value) == (
        "Chat Completions request failed after 3 attempts: "
        "transient provider error"
    )
    rendered = "".join(traceback.format_exception(caught.value))
    assert secret not in rendered
    assert FAKE_KEY not in rendered
    assert len(sdk.chat.completions.calls) == 3
    assert delays == [0.25, 0.50]


@pytest.mark.parametrize(
    ("provider_error", "expected"),
    [
        (
            FakeAuthenticationError("Authorization: Bearer " + FAKE_KEY),
            "Chat Completions request failed: authentication rejected",
        ),
        (
            FakePermissionError("Authorization: Bearer " + FAKE_KEY),
            "Chat Completions request failed: authentication rejected",
        ),
        (
            FakeBadRequestError("bad request includes " + FAKE_KEY),
            "Chat Completions request failed: request rejected",
        ),
        (
            FakeUnprocessableError("invalid payload includes " + FAKE_KEY),
            "Chat Completions request failed: request rejected",
        ),
        (
            FakeNotFoundError("unknown model includes " + FAKE_KEY),
            "Chat Completions request failed: model or endpoint not found",
        ),
        (
            FakeProviderError("unknown provider failure includes " + FAKE_KEY),
            "Chat Completions request failed: provider error",
        ),
    ],
)
def test_permanent_provider_errors_do_not_retry_or_leak(
    provider_error: OpenAIError,
    expected: str,
) -> None:
    delays: list[float] = []
    sdk = FakeSDKClient(provider_error, chat_response(content="must not run"))
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=delays.append,
    )

    with pytest.raises(FatalModelError) as caught:
        client.complete(ModelRequest(messages=(UserMessage("fail"),)))

    assert str(caught.value) == expected
    rendered = "".join(traceback.format_exception(caught.value))
    assert FAKE_KEY not in rendered
    assert "Authorization" not in rendered
    assert len(sdk.chat.completions.calls) == 1
    assert delays == []


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), SystemExit(130)])
def test_base_exceptions_are_not_swallowed(interrupt: BaseException) -> None:
    sdk = FakeSDKClient(interrupt)
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )

    with pytest.raises(type(interrupt)):
        client.complete(ModelRequest(messages=(UserMessage("interrupt"),)))

    assert len(sdk.chat.completions.calls) == 1


def test_parse_failure_is_not_retried() -> None:
    sdk = FakeSDKClient(
        chat_response(content="   "),
        chat_response(content="must not run"),
    )
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )

    with pytest.raises(InvalidChatCompletionsResponseError):
        client.complete(ModelRequest(messages=(UserMessage("parse"),)))

    assert len(sdk.chat.completions.calls) == 1


def test_parse_failure_observation_uses_stable_invalid_response_code() -> None:
    observer = RecordingModelObserver()
    sdk = FakeSDKClient(chat_response(content="   "))
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )
    budget = ModelCallBudget(observer=observer)

    with pytest.raises(InvalidChatCompletionsResponseError):
        invoke_model(
            client,
            ModelRequest(messages=(UserMessage("parse"),)),
            budget,
        )

    logical_failed = [
        item
        for item in observer.items
        if item.kind is ModelObservationKind.LOGICAL_FAILED
    ]
    assert len(logical_failed) == 1
    assert logical_failed[0].error_code == "invalid_model_response"


def test_retries_claim_each_shared_provider_attempt() -> None:
    delays: list[float] = []
    sdk = FakeSDKClient(
        FakeRateLimitError("hidden"),
        chat_response(content="recovered"),
    )
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=delays.append,
    )
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=2)

    response = invoke_model(
        client,
        ModelRequest(messages=(UserMessage("retry"),)),
        budget,
    )

    assert response.text == "recovered"
    assert (budget.logical_calls, budget.provider_attempts) == (1, 2)
    assert len(sdk.chat.completions.calls) == 2
    assert delays == [0.25]


def test_retries_emit_exact_physical_attempt_sequence() -> None:
    delays: list[float] = []
    observer = RecordingModelObserver()
    sdk = FakeSDKClient(
        FakeRateLimitError("sensitive first error"),
        FakeServerError("sensitive second error"),
        chat_response(content="recovered"),
    )
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=delays.append,
    )
    budget = ModelCallBudget(
        max_logical_calls=1,
        max_provider_attempts=3,
        observer=observer,
    )

    response = invoke_model(
        client,
        ModelRequest(messages=(UserMessage("retry"),)),
        budget,
    )

    provider = [
        item for item in observer.items if item.kind.value.startswith("provider_")
    ]
    assert response.text == "recovered"
    assert [item.kind for item in provider] == [
        ModelObservationKind.PROVIDER_STARTED,
        ModelObservationKind.PROVIDER_FAILED,
        ModelObservationKind.PROVIDER_STARTED,
        ModelObservationKind.PROVIDER_FAILED,
        ModelObservationKind.PROVIDER_STARTED,
        ModelObservationKind.PROVIDER_COMPLETED,
    ]
    failures = [
        item
        for item in provider
        if item.kind is ModelObservationKind.PROVIDER_FAILED
    ]
    assert [item.error_code for item in failures] == ["rate_limit", "server_error"]
    assert [item.retry_delay_ms for item in failures] == [250, 500]
    assert [item.retry_scheduled for item in failures] == [True, True]
    assert delays == [0.25, 0.50]
    rendered = repr(observer.items)
    assert "sensitive first error" not in rendered
    assert "sensitive second error" not in rendered
    assert FAKE_KEY not in rendered


def test_shared_provider_budget_prevents_third_physical_request() -> None:
    delays: list[float] = []
    sdk = FakeSDKClient(
        FakeRateLimitError("hidden"),
        FakeRateLimitError("hidden"),
        chat_response(content="must not run"),
    )
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=delays.append,
    )
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=2)

    with pytest.raises(ModelBudgetExceeded) as caught:
        invoke_model(
            client,
            ModelRequest(messages=(UserMessage("retry"),)),
            budget,
        )

    assert caught.value.reason is ModelBudgetReason.PROVIDER_ATTEMPT_LIMIT
    assert len(sdk.chat.completions.calls) == 2
    assert budget.provider_attempts == 2
    assert delays == [0.25]


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(
            FakeAPIResponseValidationError("malformed-secret"),
            id="sdk-response-validation",
        ),
        pytest.param(
            json.JSONDecodeError(
                "malformed-secret",
                "private-json-document",
                0,
            ),
            id="sdk-json-decode",
        ),
    ],
)
def test_sdk_malformed_payload_is_nonretrying_redacted_invalid_response(
    outcome: BaseException,
) -> None:
    sdk = FakeSDKClient(outcome)
    sleeps: list[float] = []
    observer = RecordingModelObserver()
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=sleeps.append,
    )
    budget = ModelCallBudget(observer=observer)

    with pytest.raises(
        InvalidChatCompletionsResponseError,
        match=(
            "^invalid Chat Completions payload: "
            "provider response could not be decoded$"
        ),
    ) as caught:
        invoke_model(
            client,
            ModelRequest(messages=(UserMessage("offline"),)),
            budget,
        )

    assert len(sdk.chat.completions.calls) == 1
    assert sleeps == []
    assert budget.provider_attempts == 1
    failures = [
        item
        for item in observer.items
        if item.kind is ModelObservationKind.PROVIDER_FAILED
    ]
    assert len(failures) == 1
    assert failures[0].error_code == "invalid_model_response"
    assert failures[0].retry_scheduled is False
    assert caught.value.__cause__ is None
    rendered = "".join(
        traceback.format_exception(
            caught.type,
            caught.value,
            caught.value.__traceback__,
        )
    ) + repr(observer.items)
    assert "malformed-secret" not in rendered
    assert "private-json-document" not in rendered
    assert FAKE_KEY not in rendered


def test_injected_sdk_runs_offline_without_model_credentials() -> None:
    script = r'''
import os
import socket
from types import SimpleNamespace

os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("CHAT_COMPLETIONS_API_KEY", None)

def forbidden(*args, **kwargs):
    raise AssertionError("network access attempted")

socket.create_connection = forbidden

from coding_agent.chat_completions_client import ChatCompletionsModelClient
from coding_agent.messages import ModelRequest, UserMessage

class Completions:
    def create(self, **kwargs):
        message = SimpleNamespace(
            role="assistant",
            content="offline",
            tool_calls=None,
            function_call=None,
        )
        return SimpleNamespace(
            id="chatcmpl_offline",
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=None,
        )

class Client:
    chat = SimpleNamespace(completions=Completions())

adapter = ChatCompletionsModelClient(
    model="chat-model",
    api_key="offline-fake-value",
    base_url="https://offline.invalid/v1",
    sdk_client=Client(),
    sleeper=lambda delay: None,
)
result = adapter.complete(ModelRequest(messages=(UserMessage("offline"),)))
assert result.text == "offline"
'''
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.casefold() in {
            "openai_api_key",
            "chat_completions_api_key",
        }:
            environment.pop(key, None)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr

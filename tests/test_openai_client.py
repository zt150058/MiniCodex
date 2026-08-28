from __future__ import annotations

from collections import deque
from copy import deepcopy
import inspect
import os
from pathlib import Path
import subprocess
import sys
import traceback
from types import SimpleNamespace

import pytest
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

from coding_agent.config import load_run_config
from coding_agent.messages import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    TokenUsage,
    ToolCall,
    ToolResult,
    UserMessage,
)
from coding_agent.model import FatalModelError, ModelClient, TransientModelError
from coding_agent.openai_client import (
    InvalidOpenAIResponseError,
    OpenAIResponsesClient,
)


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
    assert all(
        not isinstance(item, FakeOutputItem) for item in first.continuation_items
    )
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
            response_for(FakeOutputItem({"id": "x", "type": "web_search_call"})),
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
            response_for(function_item("call_1"), function_item("call_1")),
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
        complete_once(FakeResponse(output=(text_item("done"),), usage=usage))


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

    response = client.complete(ModelRequest(messages=(UserMessage("retry"),)))

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
    rendered_traceback = "".join(traceback.format_exception(caught.value))
    assert secret not in rendered_traceback
    assert len(sdk.responses.calls) == 3
    assert delays == [0.25, 0.50]


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
    rendered_traceback = "".join(traceback.format_exception(caught.value))
    assert FAKE_KEY not in rendered_traceback
    assert "Authorization" not in rendered_traceback
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
    sdk = FakeSDKClient(FakeResponse(output=()), text_response("must not run"))
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key=FAKE_KEY,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )

    with pytest.raises(InvalidOpenAIResponseError):
        client.complete(ModelRequest(messages=(UserMessage("parse"),)))

    assert len(sdk.responses.calls) == 1


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

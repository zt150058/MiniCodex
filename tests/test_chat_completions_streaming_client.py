from __future__ import annotations

from collections import deque
from copy import deepcopy
from types import SimpleNamespace as ns

import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from coding_agent.chat_completions_client import (
    ChatCompletionsModelClient,
    InvalidChatCompletionsResponseError,
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
    ModelCallBudget,
    ModelBudgetExceeded,
    ModelOutputLimitError,
    TransientModelError,
)
from coding_agent.streaming import (
    ModelStreamEvent,
    ModelStreamEventKind,
    StreamInterruptedError,
    StreamingUnsupportedError,
    invoke_model_stream,
)


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
        self.calls.append(deepcopy(kwargs))
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeSDK:
    def __init__(self, *outcomes: object) -> None:
        self.chat = ns(completions=FakeCompletionsResource(*outcomes))


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


class FakeBadRequestError(BadRequestError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


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


def sync_response(
    *,
    text: str | None = "fallback answer",
    tool_calls: list[object] | None = None,
) -> object:
    return ns(
        id="chat-sync",
        choices=[
            ns(
                finish_reason="tool_calls" if tool_calls else "stop",
                message=ns(
                    role="assistant",
                    content=text,
                    tool_calls=tool_calls,
                    function_call=None,
                ),
            )
        ],
        usage=None,
    )


def sync_tool_call(call_id: str, name: str, arguments: str) -> object:
    return ns(
        id=call_id,
        type="function",
        function=ns(name=name, arguments=arguments),
    )


def tool_fragment(
    index: object,
    *,
    call_id: object = None,
    call_type: object = None,
    name: object = None,
    arguments: object = None,
) -> object:
    return ns(
        index=index,
        id=call_id,
        type=call_type,
        function=ns(name=name, arguments=arguments),
    )


def test_chat_stream_maps_full_history_system_tools_and_text_deltas() -> None:
    call = ToolCall("call-previous", "echo", {"text": "previous"})
    result = ToolResult(
        call_id="call-previous",
        tool_name="echo",
        status="ok",
        output="previous",
    )
    stream = FakeStream(
        (
            chunk(delta=delta(role="assistant", content="hel")),
            chunk(delta=delta(content="lo"), finish_reason="stop"),
        )
    )
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
    assert sent == {
        "model": "test",
        "messages": [
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
        ],
        "max_tokens": 123,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Return text.",
                    "strict": True,
                    "parameters": TOOL_SCHEMA["parameters"],
                },
            }
        ],
        "stream": True,
    }
    assert [
        event.delta
        for event in events
        if event.kind is ModelStreamEventKind.TEXT_DELTA
    ] == ["hel", "lo"]
    assert response.text == "hello"
    assert response.continuation_items == ()
    assert stream.closed is True


def test_chat_stream_omits_system_message_for_null_instructions() -> None:
    sdk = FakeSDK(
        FakeStream((chunk(delta=delta(content="ok"), finish_reason="stop"),))
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )

    client.stream(
        ModelRequest(messages=(UserMessage("task"),)),
        lambda event: None,
    )

    assert sdk.chat.completions.calls[0]["messages"] == [
        {"role": "user", "content": "task"}
    ]


def test_chat_complete_still_omits_stream() -> None:
    response = ns(
        id="chat-sync",
        choices=[
            ns(
                finish_reason="stop",
                message=ns(
                    role="assistant",
                    content="ok",
                    tool_calls=None,
                    function_call=None,
                ),
            )
        ],
        usage=None,
    )
    sdk = FakeSDK(response)
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )

    client.complete(ModelRequest(messages=(UserMessage("task"),)))

    assert "stream" not in sdk.chat.completions.calls[0]


def test_invalid_stream_before_public_text_uses_one_sync_attempt() -> None:
    invalid_stream = FakeStream(
        (chunk(delta=delta(), finish_reason=None),)
    )
    sdk = FakeSDK(invalid_stream, sync_response())
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=2)
    events: list[ModelStreamEvent] = []

    response = invoke_model_stream(
        client,
        ModelRequest(messages=(UserMessage("task"),)),
        budget,
        events.append,
    )

    assert response.text == "fallback answer"
    assert (budget.logical_calls, budget.provider_attempts) == (1, 2)
    assert [call.get("stream") for call in sdk.chat.completions.calls] == [
        True,
        None,
    ]
    assert [event.kind for event in events] == [
        ModelStreamEventKind.RESPONSE_COMPLETED
    ]


@pytest.mark.parametrize(
    ("text", "raw_calls", "expected_calls"),
    [
        (
            None,
            [sync_tool_call("call-one", "read_file", '{"path":"a.py"}')],
            (ToolCall("call-one", "read_file", {"path": "a.py"}),),
        ),
        (
            None,
            [
                sync_tool_call("call-a", "read_file", '{"path":"a.py"}'),
                sync_tool_call("call-b", "read_file", '{"path":"b.py"}'),
            ],
            (
                ToolCall("call-a", "read_file", {"path": "a.py"}),
                ToolCall("call-b", "read_file", {"path": "b.py"}),
            ),
        ),
        (
            "I will inspect.",
            [sync_tool_call("call-one", "read_file", '{"path":"a.py"}')],
            (ToolCall("call-one", "read_file", {"path": "a.py"}),),
        ),
    ],
    ids=("single-tool", "multiple-tools", "text-and-tool"),
)
def test_hidden_invalid_stream_recovers_ordered_sync_tools(
    text: str | None,
    raw_calls: list[object],
    expected_calls: tuple[ToolCall, ...],
) -> None:
    hidden_invalid_stream = FakeStream(
        (
            chunk(
                delta=delta(
                    tool_calls=[
                        tool_fragment(
                            0,
                            call_type="function",
                            name="read_file",
                            arguments='{"path":"unfinished"}',
                        )
                    ]
                ),
                finish_reason="tool_calls",
            ),
        )
    )
    sdk = FakeSDK(
        hidden_invalid_stream,
        sync_response(text=text, tool_calls=raw_calls),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=2)
    events: list[ModelStreamEvent] = []

    response = invoke_model_stream(
        client,
        ModelRequest(messages=(UserMessage("task"),)),
        budget,
        events.append,
    )

    assert response.text == text
    assert response.tool_calls == expected_calls
    assert (budget.logical_calls, budget.provider_attempts) == (1, 2)
    assert [call.get("stream") for call in sdk.chat.completions.calls] == [
        True,
        None,
    ]
    assert [event.kind for event in events] == [
        ModelStreamEventKind.RESPONSE_COMPLETED
    ]


def test_invalid_stream_and_invalid_sync_stop_after_two_attempts() -> None:
    sdk = FakeSDK(
        FakeStream((chunk(delta=delta(), finish_reason=None),)),
        ns(id="bad", choices=[], usage=None),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )

    with pytest.raises(InvalidChatCompletionsResponseError):
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )

    assert len(sdk.chat.completions.calls) == 2


def test_invalid_stream_after_public_text_discards_without_sync() -> None:
    stream = FakeStream(
        (
            chunk(delta=delta(content="partial")),
            chunk(delta=delta(), finish_reason=None),
        )
    )
    sdk = FakeSDK(stream, object())
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )
    events: list[ModelStreamEvent] = []

    with pytest.raises(InvalidChatCompletionsResponseError):
        invoke_model_stream(
            client,
            ModelRequest(messages=(UserMessage("task"),)),
            ModelCallBudget(),
            events.append,
        )

    assert len(sdk.chat.completions.calls) == 1
    assert events[-1].kind is ModelStreamEventKind.RESPONSE_DISCARDED


def test_invalid_stream_sync_fallback_respects_provider_budget() -> None:
    sdk = FakeSDK(
        FakeStream((chunk(delta=delta(), finish_reason=None),)),
        sync_response(),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=1)

    with pytest.raises(ModelBudgetExceeded):
        invoke_model_stream(
            client,
            ModelRequest(messages=(UserMessage("task"),)),
            budget,
            lambda event: None,
        )

    assert len(sdk.chat.completions.calls) == 1
    assert budget.provider_attempts == 1


def test_invalid_stream_sync_fallback_transient_error_is_not_retried() -> None:
    delays: list[float] = []
    sdk = FakeSDK(
        FakeStream((chunk(delta=delta(), finish_reason=None),)),
        FakeTimeoutError("Authorization: Bearer private-provider-body"),
        sync_response(text="unused"),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
        sleeper=delays.append,
    )

    with pytest.raises(TransientModelError) as caught:
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )

    assert len(sdk.chat.completions.calls) == 2
    assert delays == []
    assert "private" not in str(caught.value)
    assert "private" not in repr(caught.value)


def test_chat_stream_assembles_ordered_interleaved_tools_with_text_and_usage() -> None:
    stream = FakeStream(
        (
            chunk(
                delta=delta(
                    role="assistant",
                    content="working",
                    tool_calls=[
                        tool_fragment(
                            0,
                            call_id="call-a",
                            call_type="function",
                            name="read_file",
                            arguments='{"path":"',
                        )
                    ],
                )
            ),
            chunk(
                delta=delta(
                    tool_calls=[
                        tool_fragment(
                            1,
                            call_id="call-b",
                            call_type="function",
                            name="read_file",
                            arguments='{"path":"b',
                        ),
                        tool_fragment(0, arguments='a.py"}'),
                    ]
                )
            ),
            chunk(
                delta=delta(
                    tool_calls=[tool_fragment(1, arguments='.py"}')]
                ),
                finish_reason="stop",
            ),
            ns(
                id="chatcmpl-stream",
                choices=[],
                usage=ns(
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                ),
            ),
        )
    )
    events: list[ModelStreamEvent] = []
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=FakeSDK(stream),
    )

    response = client.stream(
        ModelRequest(messages=(UserMessage("task"),)),
        events.append,
    )

    assert response.text == "working"
    assert response.tool_calls == (
        ToolCall("call-a", "read_file", {"path": "a.py"}),
        ToolCall("call-b", "read_file", {"path": "b.py"}),
    )
    assert response.usage == TokenUsage(10, 5, 15)
    assert response.provider_response_id == "chatcmpl-stream"
    assert [
        event.delta
        for event in events
        if event.kind is ModelStreamEventKind.TEXT_DELTA
    ] == ["working"]


def test_chat_stream_accepts_blank_continuation_identifier_after_valid_id() -> None:
    stream = FakeStream(
        (
            chunk(
                delta=delta(
                    role="assistant",
                    tool_calls=[
                        tool_fragment(
                            0,
                            call_id="call-a",
                            call_type="function",
                            name="inspect_workspace",
                            arguments='{"path":"',
                        )
                    ],
                )
            ),
            chunk(
                delta=delta(
                    tool_calls=[
                        tool_fragment(0, call_id="", arguments='."}')
                    ]
                ),
                finish_reason="stop",
            ),
        )
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=FakeSDK(stream),
    )

    response = client.stream(
        ModelRequest(messages=(UserMessage("task"),)),
        lambda event: None,
    )

    assert response.tool_calls == (
        ToolCall("call-a", "inspect_workspace", {"path": "."}),
    )


@pytest.mark.parametrize(
    ("chunks", "reason", "has_public_text"),
    [
        (
            (
                chunk(
                    delta=delta(
                        tool_calls=[
                            tool_fragment(
                                1,
                                call_id="call-b",
                                call_type="function",
                                name="read_file",
                                arguments="{}",
                            )
                        ]
                    ),
                    finish_reason="tool_calls",
                ),
            ),
            "index",
            False,
        ),
        (
            (
                chunk(
                    delta=delta(
                        tool_calls=[
                            tool_fragment(
                                -1,
                                call_id="call-a",
                                call_type="function",
                                name="read_file",
                                arguments="{}",
                            )
                        ]
                    ),
                    finish_reason="tool_calls",
                ),
            ),
            "index",
            False,
        ),
        (
            (
                chunk(
                    delta=delta(
                        tool_calls=[
                            tool_fragment(
                                0,
                                call_id="call-a",
                                call_type="function",
                                name="read_file",
                                arguments="{",
                            )
                        ]
                    )
                ),
                chunk(
                    delta=delta(
                        tool_calls=[
                            tool_fragment(0, call_id="call-changed", arguments="}")
                        ]
                    ),
                    finish_reason="tool_calls",
                ),
            ),
            "identifier",
            False,
        ),
        (
            (
                chunk(
                    delta=delta(
                        tool_calls=[
                            tool_fragment(
                                0,
                                call_id="call-a",
                                call_type="function",
                                name="read_file",
                                arguments="[]",
                            )
                        ]
                    ),
                    finish_reason="tool_calls",
                ),
            ),
            "object",
            False,
        ),
        (
            (
                chunk(delta=delta(content="ok"), finish_reason="stop"),
                chunk(delta=delta(), finish_reason="stop"),
            ),
            "duplicate finish",
            True,
        ),
    ],
    ids=[
        "sparse-index",
        "negative-index",
        "conflicting-id",
        "non-object-arguments",
        "duplicate-finish",
    ],
)
def test_chat_stream_rejects_invalid_tool_and_terminal_chunks(
    chunks: tuple[object, ...],
    reason: str,
    has_public_text: bool,
) -> None:
    stream = FakeStream(chunks)
    sdk = FakeSDK(stream, sync_response())
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )
    observations: list[object] = []
    events: list[ModelStreamEvent] = []
    budget = ModelCallBudget(observer=ns(observe_model=observations.append))

    if has_public_text:
        with pytest.raises(InvalidChatCompletionsResponseError, match=reason):
            invoke_model_stream(
                client,
                ModelRequest(messages=(UserMessage("task"),)),
                budget,
                events.append,
            )
        assert len(sdk.chat.completions.calls) == 1
        assert events[-1].kind is ModelStreamEventKind.RESPONSE_DISCARDED
    else:
        response = invoke_model_stream(
            client,
            ModelRequest(messages=(UserMessage("task"),)),
            budget,
            events.append,
        )
        assert response.text == "fallback answer"
        assert len(sdk.chat.completions.calls) == 2
        failed = [
            item
            for item in observations
            if item.kind.value == "provider_failed"
        ]
        assert len(failed) == 1
        assert failed[0].error_code == "invalid_model_response"
        assert [event.kind for event in events] == [
            ModelStreamEventKind.RESPONSE_COMPLETED
        ]


def test_chat_stream_rejects_legacy_refusal_and_non_function_tools() -> None:
    invalid_deltas = (
        delta(function_call=ns(name="legacy", arguments="{}")),
        delta(refusal="no"),
        delta(
            tool_calls=[
                tool_fragment(
                    0,
                    call_id="call-a",
                    call_type="custom",
                    name="read_file",
                    arguments="{}",
                )
            ]
        ),
    )

    for invalid_delta in invalid_deltas:
        sdk = FakeSDK(
            FakeStream(
                (
                    chunk(delta=delta(content="public")),
                    chunk(delta=invalid_delta, finish_reason="tool_calls"),
                )
            ),
            sync_response(text="unused"),
        )
        client = ChatCompletionsModelClient(
            model="test",
            api_key="not-real",
            base_url="https://example.test/v1",
            sdk_client=sdk,
        )
        with pytest.raises(InvalidChatCompletionsResponseError):
            client.stream(
                ModelRequest(messages=(UserMessage("task"),)),
                lambda event: None,
            )
        assert len(sdk.chat.completions.calls) == 1


def test_chat_stream_length_discards_partial_text_as_output_limit() -> None:
    events: list[ModelStreamEvent] = []
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=FakeSDK(
            FakeStream(
                (chunk(delta=delta(content="private partial"), finish_reason="length"),)
            )
        ),
    )

    with pytest.raises(ModelOutputLimitError, match="output token limit") as caught:
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            events.append,
        )

    assert "private partial" not in str(caught.value)
    assert [event.kind for event in events] == [
        ModelStreamEventKind.TEXT_DELTA,
        ModelStreamEventKind.RESPONSE_DISCARDED,
    ]


@pytest.mark.parametrize(
    ("chunks", "reason", "has_public_text"),
    [
        (
            (
                chunk(
                    delta=delta(
                        tool_calls=[
                            tool_fragment(
                                "0",
                                call_id="call-a",
                                call_type="function",
                                name="read_file",
                                arguments="{}",
                            )
                        ]
                    ),
                    finish_reason="tool_calls",
                ),
            ),
            "index",
            False,
        ),
        (
            (
                chunk(
                    delta=delta(
                        tool_calls=[
                            tool_fragment(
                                0,
                                call_type="function",
                                name="read_file",
                                arguments="{}",
                            )
                        ]
                    ),
                    finish_reason="tool_calls",
                ),
            ),
            "incomplete",
            False,
        ),
        (
            (
                chunk(
                    delta=delta(
                        tool_calls=[
                            tool_fragment(
                                0,
                                call_id="call-a",
                                call_type="function",
                                arguments="{}",
                            )
                        ]
                    ),
                    finish_reason="tool_calls",
                ),
            ),
            "incomplete",
            False,
        ),
        (
            (
                chunk(
                    delta=delta(
                        tool_calls=[
                            tool_fragment(
                                0,
                                call_id="call-a",
                                call_type="function",
                                name="read_file",
                                arguments="{",
                            )
                        ]
                    )
                ),
                chunk(
                    delta=delta(
                        tool_calls=[tool_fragment(0, name="write_file", arguments="}")]
                    ),
                    finish_reason="tool_calls",
                ),
            ),
            "name",
            False,
        ),
        (
            (
                chunk(
                    delta=delta(
                        tool_calls=[
                            tool_fragment(
                                0,
                                call_id="call-a",
                                call_type="function",
                                name="read_file",
                                arguments="{not-json}",
                            )
                        ]
                    ),
                    finish_reason="tool_calls",
                ),
            ),
            "valid JSON",
            False,
        ),
        (
            (
                chunk(
                    delta=delta(
                        tool_calls=[
                            tool_fragment(
                                0,
                                call_id="call-a",
                                call_type="function",
                                name="read_file",
                                arguments="{}",
                            ),
                            tool_fragment(
                                1,
                                call_id="call-a",
                                call_type="function",
                                name="read_file",
                                arguments="{}",
                            ),
                        ]
                    ),
                    finish_reason="tool_calls",
                ),
            ),
            "duplicate function call id",
            False,
        ),
        (
            (chunk(delta=delta(content="unterminated")),),
            "finish reason",
            True,
        ),
        (
            (
                chunk(delta=delta(content="a"), response_id="chat-a"),
                chunk(
                    delta=delta(content="b"),
                    finish_reason="stop",
                    response_id="chat-b",
                ),
            ),
            "response id",
            True,
        ),
        (
            (
                chunk(delta=delta(content="ok"), finish_reason="stop"),
                ns(
                    id="chatcmpl-stream",
                    choices=[],
                    usage=ns(prompt_tokens=1, completion_tokens=1),
                ),
            ),
            "usage",
            True,
        ),
        (
            (
                ns(
                    id="chatcmpl-stream",
                    choices=[
                        ns(index=0, delta=delta(content="a"), finish_reason="stop"),
                        ns(index=1, delta=delta(content="b"), finish_reason="stop"),
                    ],
                    usage=None,
                ),
            ),
            "choices",
            False,
        ),
        (
            (
                ns(
                    id="chatcmpl-stream",
                    choices=[
                        ns(index=1, delta=delta(content="a"), finish_reason="stop")
                    ],
                    usage=None,
                ),
            ),
            "choice index",
            False,
        ),
    ],
    ids=[
        "noninteger-index",
        "missing-id",
        "missing-name",
        "conflicting-name",
        "malformed-json",
        "duplicate-call-id",
        "missing-finish",
        "changed-response-id",
        "partial-usage",
        "multiple-choices",
        "nonzero-choice-index",
    ],
)
def test_chat_stream_rejects_additional_invalid_shapes(
    chunks: tuple[object, ...],
    reason: str,
    has_public_text: bool,
) -> None:
    stream = FakeStream(chunks)
    sdk = FakeSDK(stream, sync_response())
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )
    observations: list[object] = []
    events: list[ModelStreamEvent] = []
    budget = ModelCallBudget(observer=ns(observe_model=observations.append))

    if has_public_text:
        with pytest.raises(InvalidChatCompletionsResponseError, match=reason):
            invoke_model_stream(
                client,
                ModelRequest(messages=(UserMessage("task"),)),
                budget,
                events.append,
            )
        assert len(sdk.chat.completions.calls) == 1
        assert events[-1].kind is ModelStreamEventKind.RESPONSE_DISCARDED
    else:
        response = invoke_model_stream(
            client,
            ModelRequest(messages=(UserMessage("task"),)),
            budget,
            events.append,
        )
        assert response.text == "fallback answer"
        assert len(sdk.chat.completions.calls) == 2
        failed = [
            item
            for item in observations
            if item.kind.value == "provider_failed"
        ]
        assert len(failed) == 1
        assert failed[0].error_code == "invalid_model_response"
        assert [event.kind for event in events] == [
            ModelStreamEventKind.RESPONSE_COMPLETED
        ]

    assert stream.closed is True


def test_chat_stream_rejects_continuation_before_sdk_access() -> None:
    sdk = FakeSDK(FakeStream(()))
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )

    with pytest.raises(FatalModelError, match="continuation"):
        client.stream(
            ModelRequest(
                messages=(UserMessage("task"),),
                continuation_items=(object(),),
            ),
            lambda event: None,
        )

    assert sdk.chat.completions.calls == []


@pytest.mark.parametrize(
    "error_type",
    [
        FakeRateLimitError,
        FakeServerError,
        FakeTimeoutError,
        FakeConnectionError,
    ],
)
def test_chat_stream_retries_transient_error_before_delta(
    error_type: type[Exception],
) -> None:
    delays: list[float] = []
    sdk = FakeSDK(
        error_type("Authorization: Bearer private-provider-body"),
        FakeStream((chunk(delta=delta(content="ok"), finish_reason="stop"),)),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
        sleeper=delays.append,
    )

    response = client.stream(
        ModelRequest(messages=(UserMessage("task"),)),
        lambda event: None,
    )

    assert response.text == "ok"
    assert len(sdk.chat.completions.calls) == 2
    assert delays == [0.25]


def test_chat_stream_stops_after_three_transient_attempts() -> None:
    delays: list[float] = []
    sdk = FakeSDK(
        FakeRateLimitError("private one"),
        FakeRateLimitError("private two"),
        FakeRateLimitError("private three"),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
        sleeper=delays.append,
    )

    with pytest.raises(TransientModelError) as caught:
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )

    assert len(sdk.chat.completions.calls) == 3
    assert delays == [0.25, 0.50]
    assert "private" not in str(caught.value)


def test_chat_stream_does_not_retry_after_text_delta() -> None:
    delays: list[float] = []
    sdk = FakeSDK(
        FakeStream(
            (
                chunk(delta=delta(content="partial")),
                FakeTimeoutError("private timeout body"),
            )
        ),
        FakeStream((chunk(delta=delta(content="unused"), finish_reason="stop"),)),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
        sleeper=delays.append,
    )
    events: list[ModelStreamEvent] = []

    with pytest.raises(StreamInterruptedError) as caught:
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            events.append,
        )

    assert len(sdk.chat.completions.calls) == 1
    assert delays == []
    assert events[-1].kind is ModelStreamEventKind.RESPONSE_DISCARDED
    assert "private" not in str(caught.value)


def test_chat_stream_hidden_tool_delta_disables_retry_and_fallback() -> None:
    sdk = FakeSDK(
        FakeStream(
            (
                chunk(
                    delta=delta(
                        tool_calls=[
                            tool_fragment(
                                0,
                                call_id="call-private",
                                call_type="function",
                                name="read_file",
                                arguments='{"secret":"',
                            )
                        ]
                    )
                ),
                StreamingUnsupportedError("unsupported"),
            )
        ),
        ns(),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )

    with pytest.raises(StreamInterruptedError):
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )

    assert len(sdk.chat.completions.calls) == 1


def test_chat_stream_structured_unsupported_before_delta_falls_back() -> None:
    sync_response = ns(
        id="chat-fallback",
        choices=[
            ns(
                finish_reason="stop",
                message=ns(
                    role="assistant",
                    content="fallback",
                    tool_calls=None,
                    function_call=None,
                ),
            )
        ],
        usage=None,
    )
    sdk = FakeSDK(StreamingUnsupportedError("unsupported"), sync_response)
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=2)

    response = invoke_model_stream(
        client,
        ModelRequest(
            messages=(UserMessage("task"),),
            instructions="instruction sentinel",
        ),
        budget,
        lambda event: None,
    )

    assert response.text == "fallback"
    assert (budget.logical_calls, budget.provider_attempts) == (1, 2)
    assert sdk.chat.completions.calls[1]["messages"][0] == {
        "role": "system",
        "content": "instruction sentinel",
    }


@pytest.mark.parametrize(
    "error",
    [
        FakeAuthenticationError("private auth body"),
        FakeBadRequestError("private request body"),
    ],
)
def test_chat_stream_does_not_retry_permanent_errors(error: Exception) -> None:
    sdk = FakeSDK(error)
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )

    with pytest.raises(FatalModelError) as caught:
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )

    assert len(sdk.chat.completions.calls) == 1
    assert "private" not in str(caught.value)


def test_chat_stream_cleanup_failure_after_success_is_stable() -> None:
    stream = FakeStream(
        (chunk(delta=delta(content="ok"), finish_reason="stop"),),
        close_error=OSError("private cleanup path"),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=FakeSDK(stream),
    )

    with pytest.raises(
        StreamInterruptedError,
        match="^model stream cleanup failed$",
    ):
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )


def test_chat_stream_cleanup_failure_does_not_replace_primary_error() -> None:
    stream = FakeStream(
        (ModelOutputLimitError("primary stable"),),
        close_error=OSError("private cleanup path"),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=FakeSDK(stream),
    )

    with pytest.raises(ModelOutputLimitError, match="primary stable"):
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(9)])
def test_chat_stream_does_not_swallow_base_exception(error: BaseException) -> None:
    stream = FakeStream(
        (error,),
        close_error=OSError("cleanup must not replace base exception"),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=FakeSDK(stream),
    )

    with pytest.raises(type(error)):
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )


def test_chat_stream_callback_failure_is_not_retried_and_closes_stream() -> None:
    stream = FakeStream(
        (chunk(delta=delta(content="partial"), finish_reason="stop"),)
    )
    sdk = FakeSDK(
        stream,
        FakeStream((chunk(delta=delta(content="unused"), finish_reason="stop"),)),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )

    def fail_callback(event: ModelStreamEvent) -> None:
        if event.kind is ModelStreamEventKind.TEXT_DELTA:
            raise RuntimeError("callback sentinel")

    with pytest.raises(RuntimeError, match="callback sentinel"):
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            fail_callback,
        )

    assert len(sdk.chat.completions.calls) == 1
    assert stream.closed is True


def test_chat_stream_preserves_capability_shaped_callback_error() -> None:
    stream = FakeStream(
        (chunk(delta=delta(content="partial"), finish_reason="stop"),)
    )
    sdk = FakeSDK(
        stream,
        FakeStream((chunk(delta=delta(content="unused"), finish_reason="stop"),)),
    )
    client = ChatCompletionsModelClient(
        model="test",
        api_key="not-real",
        base_url="https://example.test/v1",
        sdk_client=sdk,
    )
    callback_error = StreamingUnsupportedError("consumer capability sentinel")
    observations: list[object] = []
    budget = ModelCallBudget(observer=ns(observe_model=observations.append))

    def fail_callback(event: ModelStreamEvent) -> None:
        if event.kind is ModelStreamEventKind.TEXT_DELTA:
            raise callback_error

    with pytest.raises(StreamingUnsupportedError) as caught:
        invoke_model_stream(
            client,
            ModelRequest(messages=(UserMessage("task"),)),
            budget,
            fail_callback,
        )

    assert caught.value is callback_error
    assert len(sdk.chat.completions.calls) == 1
    assert stream.closed is True
    assert [observation.kind.value for observation in observations] == [
        "logical_started",
        "provider_started",
        "provider_failed",
        "logical_failed",
    ]

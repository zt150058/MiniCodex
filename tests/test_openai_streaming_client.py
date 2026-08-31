from __future__ import annotations

from collections import deque
from copy import deepcopy
import json
from types import SimpleNamespace as ns

import pytest
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from coding_agent.messages import (
    AssistantMessage,
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
    ModelOutputLimitError,
    TransientModelError,
)
from coding_agent.openai_client import (
    InvalidOpenAIResponseError,
    OpenAIResponsesClient,
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
        response_id: str,
        output: tuple[FakeOutputItem, ...],
        usage: object | None = None,
    ) -> None:
        self.id = response_id
        self.status = "completed"
        self.error = None
        self.output = list(output)
        self.usage = usage


def valid_responses_response(
    *,
    text: str,
    response_id: str,
) -> FakeResponse:
    item = FakeOutputItem(
        {
            "id": "msg-stream",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [
                {"type": "output_text", "text": text, "annotations": []}
            ],
        }
    )
    return FakeResponse(response_id=response_id, output=(item,))


class FakeStream:
    def __init__(
        self,
        events: tuple[object, ...],
        *,
        close_error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.close_error = close_error
        self.closed = False

    def __iter__(self):
        for event in self.events:
            if isinstance(event, BaseException):
                raise event
            yield event

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class FakeResponsesResource:
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
        self.responses = FakeResponsesResource(*outcomes)


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


class FakeResponseValidationError(APIResponseValidationError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeAuthenticationError(AuthenticationError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeBadRequestError(BadRequestError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


def test_responses_stream_maps_request_emits_text_and_returns_final_response() -> None:
    final = valid_responses_response(text="hello", response_id="resp-stream")
    stream = FakeStream(
        (
            ns(type="response.output_text.delta", delta="hel"),
            ns(type="response.output_text.delta", delta="lo"),
            ns(type="response.completed", response=final),
        )
    )
    sdk = FakeSDK(stream)
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=sdk,
    )
    events: list[ModelStreamEvent] = []

    response = client.stream(
        ModelRequest(
            messages=(UserMessage("task"),),
            tool_schemas=(TOOL_SCHEMA,),
            max_output_tokens=123,
            instructions="instruction sentinel",
        ),
        events.append,
    )

    sent = sdk.responses.calls[0]
    assert sent == {
        "model": "test-model",
        "input": [{"role": "user", "content": "task"}],
        "tools": [
            {
                "type": "function",
                "name": "echo",
                "description": "Return text.",
                "strict": True,
                "parameters": TOOL_SCHEMA["parameters"],
            }
        ],
        "max_output_tokens": 123,
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "instructions": "instruction sentinel",
        "stream": True,
    }
    assert [
        event.delta
        for event in events
        if event.kind is ModelStreamEventKind.TEXT_DELTA
    ] == ["hel", "lo"]
    assert events[-1].kind is ModelStreamEventKind.RESPONSE_COMPLETED
    assert response.text == "hello"
    assert response.provider_response_id == "resp-stream"
    assert stream.closed is True


def test_responses_stream_omits_null_instructions() -> None:
    final = valid_responses_response(text="ok", response_id="resp-null")
    sdk = FakeSDK(
        FakeStream((ns(type="response.completed", response=final),))
    )
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=sdk,
    )

    client.stream(
        ModelRequest(messages=(UserMessage("task"),)),
        lambda event: None,
    )

    assert "instructions" not in sdk.responses.calls[0]


def test_responses_complete_still_omits_stream() -> None:
    final = valid_responses_response(text="ok", response_id="resp-sync")
    sdk = FakeSDK(final)
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=sdk,
    )

    client.complete(ModelRequest(messages=(UserMessage("task"),)))

    assert "stream" not in sdk.responses.calls[0]


def test_responses_stream_returns_ordered_tools_usage_and_sdk_free_continuation() -> None:
    reasoning = FakeOutputItem(
        {"id": "reasoning-1", "type": "reasoning", "status": "completed"}
    )
    first = FakeOutputItem(
        {
            "id": "function-1",
            "type": "function_call",
            "status": "completed",
            "call_id": "call-a",
            "name": "read_file",
            "arguments": '{"path":"a.py"}',
        }
    )
    second = FakeOutputItem(
        {
            "id": "function-2",
            "type": "function_call",
            "status": "completed",
            "call_id": "call-b",
            "name": "read_file",
            "arguments": '{"path":"b.py"}',
        }
    )
    usage = ns(input_tokens=10, output_tokens=4, total_tokens=14)
    final = FakeResponse(
        response_id="resp-tools",
        output=(reasoning, first, second),
        usage=usage,
    )
    stream = FakeStream(
        (
            ns(type="response.created", response=ns(id="resp-tools")),
            ns(
                type="response.reasoning_summary_text.delta",
                output_index=0,
                item_id="reasoning-1",
                summary_index=0,
                delta="private reasoning",
            ),
            ns(
                type="response.function_call_arguments.delta",
                output_index=1,
                item_id="function-1",
                delta='{"path":"',
            ),
            ns(
                type="response.function_call_arguments.delta",
                output_index=2,
                item_id="function-2",
                delta='{"path":"',
            ),
            ns(
                type="response.function_call_arguments.delta",
                output_index=1,
                item_id="function-1",
                delta='a.py"}',
            ),
            ns(
                type="response.function_call_arguments.delta",
                output_index=2,
                item_id="function-2",
                delta='b.py"}',
            ),
            ns(
                type="response.function_call_arguments.done",
                output_index=1,
                item_id="function-1",
                name="read_file",
                arguments='{"path":"a.py"}',
            ),
            ns(
                type="response.function_call_arguments.done",
                output_index=2,
                item_id="function-2",
                name="read_file",
                arguments='{"path":"b.py"}',
            ),
            ns(type="response.completed", response=final),
        )
    )
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=FakeSDK(stream),
    )
    events: list[ModelStreamEvent] = []

    response = client.stream(
        ModelRequest(messages=(UserMessage("task"),)),
        events.append,
    )

    assert response.tool_calls == (
        ToolCall("call-a", "read_file", {"path": "a.py"}),
        ToolCall("call-b", "read_file", {"path": "b.py"}),
    )
    assert response.usage == TokenUsage(10, 4, 14)
    assert response.provider_response_id == "resp-tools"
    assert len(response.continuation_items) == 1
    assert all(
        not isinstance(item, FakeOutputItem)
        for item in response.continuation_items
    )
    assert "reasoning-1" not in repr(response)
    assert "private reasoning" not in repr(events)
    assert all(
        event.kind is not ModelStreamEventKind.TEXT_DELTA for event in events
    )


def test_responses_stream_replays_and_extends_continuation_without_duplicate_calls() -> None:
    first_output = FakeOutputItem(
        {
            "id": "function-first",
            "type": "function_call",
            "status": "completed",
            "call_id": "call-first",
            "name": "read_file",
            "arguments": '{"path":"a.py"}',
        }
    )
    first_final = FakeResponse(
        response_id="resp-first",
        output=(first_output,),
    )
    second_final = valid_responses_response(
        text="done",
        response_id="resp-second",
    )
    first_stream = FakeStream(
        (
            ns(
                type="response.function_call_arguments.delta",
                output_index=0,
                item_id="function-first",
                delta='{"path":"a.py"}',
            ),
            ns(
                type="response.function_call_arguments.done",
                output_index=0,
                item_id="function-first",
                name="read_file",
                arguments='{"path":"a.py"}',
            ),
            ns(type="response.completed", response=first_final),
        )
    )
    second_stream = FakeStream(
        (
            ns(type="response.output_text.delta", delta="done"),
            ns(type="response.completed", response=second_final),
        )
    )
    sdk = FakeSDK(first_stream, second_stream)
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=sdk,
    )

    first = client.stream(
        ModelRequest(messages=(UserMessage("inspect"),)),
        lambda event: None,
    )
    second = client.stream(
        ModelRequest(
            messages=(
                UserMessage("inspect"),
                AssistantMessage(tool_calls=first.tool_calls),
                ToolResult(
                    call_id="call-first",
                    tool_name="read_file",
                    status="ok",
                    output='{"content":"x"}',
                ),
                UserMessage("finish"),
            ),
            continuation_items=first.continuation_items,
        ),
        lambda event: None,
    )

    replay = sdk.responses.calls[1]["input"]
    assert sum(
        item.get("type") == "function_call"
        and item.get("call_id") == "call-first"
        for item in replay
        if isinstance(item, dict)
    ) == 1
    assert sum(
        item.get("type") == "function_call_output"
        and item.get("call_id") == "call-first"
        for item in replay
        if isinstance(item, dict)
    ) == 1
    assert len(first.continuation_items) == 1
    assert len(second.continuation_items) == 2
    assert all(
        not isinstance(item, FakeOutputItem)
        for item in second.continuation_items
    )
    assert "function-first" not in repr(second)


@pytest.mark.parametrize(
    "stream_events",
    [
        (),
        (ns(type="response.failed"),),
        (ns(type="error"),),
        (ns(type="unsupported.output.delta", delta="x"),),
    ],
    ids=["empty", "failed", "error", "unknown"],
)
def test_responses_stream_rejects_invalid_terminal_shapes(
    stream_events: tuple[object, ...],
) -> None:
    stream = FakeStream(stream_events)
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=FakeSDK(stream),
    )

    with pytest.raises(InvalidOpenAIResponseError, match="invalid"):
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )

    assert stream.closed is True


def test_responses_stream_incomplete_output_limit_discards_partial_text() -> None:
    terminal = ns(
        id="resp-limited",
        status="incomplete",
        error=None,
        incomplete_details=ns(reason="max_output_tokens"),
        output=[],
        usage=None,
    )
    events: list[ModelStreamEvent] = []
    stream = FakeStream(
        (
            ns(type="response.output_text.delta", delta="private partial"),
            ns(type="response.incomplete", response=terminal),
        )
    )
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=FakeSDK(stream),
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
    assert stream.closed is True


def test_responses_stream_discards_when_final_text_mismatches_deltas() -> None:
    final = valid_responses_response(text="different", response_id="resp-bad")
    events: list[ModelStreamEvent] = []
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=FakeSDK(
            FakeStream(
                (
                    ns(type="response.output_text.delta", delta="provisional"),
                    ns(type="response.completed", response=final),
                )
            )
        ),
    )

    with pytest.raises(InvalidOpenAIResponseError, match="invalid"):
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            events.append,
        )

    assert events[-1].kind is ModelStreamEventKind.RESPONSE_DISCARDED


def test_responses_stream_accepts_full_message_and_reasoning_lifecycle() -> None:
    final = valid_responses_response(text="hello", response_id="resp-lifecycle")
    response_state = ns(id="resp-lifecycle")
    message_item = ns(id="msg-stream", type="message")
    text_part = ns(type="output_text", text="hello")
    reasoning_part = ns(type="summary_text", text="hidden")
    reasoning_content_part = ns(type="reasoning_text", text="private")
    events: list[ModelStreamEvent] = []
    stream = FakeStream(
        (
            ns(type="response.created", response=response_state),
            ns(type="response.in_progress", response=response_state),
            ns(
                type="response.output_item.added",
                output_index=0,
                item=message_item,
            ),
            ns(
                type="response.content_part.added",
                output_index=0,
                content_index=0,
                item_id="msg-stream",
                part=text_part,
            ),
            ns(type="response.output_text.delta", delta="hello"),
            ns(
                type="response.output_text.done",
                output_index=0,
                content_index=0,
                item_id="msg-stream",
                text="hello",
            ),
            ns(
                type="response.content_part.done",
                output_index=0,
                content_index=0,
                item_id="msg-stream",
                part=text_part,
            ),
            ns(
                type="response.reasoning_summary_part.added",
                output_index=1,
                summary_index=0,
                item_id="reasoning-1",
                part=reasoning_part,
            ),
            ns(
                type="response.reasoning_summary_text.delta",
                output_index=1,
                summary_index=0,
                item_id="reasoning-1",
                delta="hidden",
            ),
            ns(
                type="response.reasoning_summary_text.done",
                output_index=1,
                summary_index=0,
                item_id="reasoning-1",
                text="hidden",
            ),
            ns(
                type="response.reasoning_summary_part.done",
                output_index=1,
                summary_index=0,
                item_id="reasoning-1",
                part=reasoning_part,
            ),
            ns(
                type="response.content_part.added",
                output_index=1,
                content_index=0,
                item_id="reasoning-1",
                part=reasoning_content_part,
            ),
            ns(
                type="response.reasoning_text.delta",
                output_index=1,
                content_index=0,
                item_id="reasoning-1",
                delta="private",
            ),
            ns(
                type="response.reasoning_text.done",
                output_index=1,
                content_index=0,
                item_id="reasoning-1",
                text="private",
            ),
            ns(
                type="response.content_part.done",
                output_index=1,
                content_index=0,
                item_id="reasoning-1",
                part=reasoning_content_part,
            ),
            ns(
                type="response.output_item.done",
                output_index=0,
                item=message_item,
            ),
            ns(type="response.completed", response=final),
        )
    )
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=FakeSDK(stream),
    )

    response = client.stream(
        ModelRequest(messages=(UserMessage("task"),)),
        events.append,
    )

    assert response.text == "hello"
    assert [event.delta for event in events if event.delta is not None] == ["hello"]
    assert "hidden" not in repr(events)
    assert "private" not in repr(events)
    assert stream.closed is True


@pytest.mark.parametrize(
    "unsupported_event",
    [
        ns(
            type="response.output_item.added",
            output_index=0,
            item=ns(type="web_search_call", id="search-private"),
        ),
        ns(
            type="response.output_item.done",
            output_index=0,
            item=ns(type="mcp_call", id="mcp-private"),
        ),
        ns(
            type="response.content_part.added",
            output_index=0,
            content_index=0,
            item_id="msg-stream",
            part=ns(type="refusal", refusal="private refusal"),
        ),
        ns(
            type="response.content_part.done",
            output_index=0,
            content_index=0,
            item_id="msg-stream",
            part=ns(type="audio", audio="private audio"),
        ),
    ],
    ids=["web-search-item", "mcp-item", "refusal-part", "audio-part"],
)
def test_responses_stream_rejects_unsupported_nonterminal_payload_types(
    unsupported_event: object,
) -> None:
    final = valid_responses_response(text="ok", response_id="resp-wrapper")
    stream = FakeStream(
        (
            unsupported_event,
            ns(type="response.completed", response=final),
        )
    )
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=FakeSDK(stream),
    )

    with pytest.raises(InvalidOpenAIResponseError, match="unsupported") as caught:
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )

    assert "private" not in str(caught.value)
    assert stream.closed is True


@pytest.mark.parametrize(
    "event_builder",
    [
        lambda final: (
            ns(
                type="response.function_call_arguments.delta",
                output_index=0,
                item_id="function-1",
                delta="{}",
            ),
            ns(type="response.completed", response=final),
        ),
        lambda final: (
            ns(
                type="response.function_call_arguments.delta",
                output_index=0,
                item_id="function-1",
                delta="{}",
            ),
            ns(
                type="response.function_call_arguments.done",
                output_index=0,
                item_id="function-1",
                name="read_file",
                arguments="{}",
            ),
            ns(
                type="response.function_call_arguments.done",
                output_index=0,
                item_id="function-1",
                name="read_file",
                arguments="{}",
            ),
            ns(type="response.completed", response=final),
        ),
        lambda final: (
            ns(
                type="response.function_call_arguments.delta",
                output_index=0,
                item_id="function-1",
                delta='{"path":"a.py"}',
            ),
            ns(
                type="response.function_call_arguments.done",
                output_index=0,
                item_id="function-1",
                name="read_file",
                arguments='{"path":"b.py"}',
            ),
            ns(type="response.completed", response=final),
        ),
        lambda final: (
            ns(
                type="response.function_call_arguments.delta",
                output_index=0,
                item_id="function-1",
                delta="{",
            ),
            ns(
                type="response.function_call_arguments.delta",
                output_index=0,
                item_id="function-changed",
                delta="}",
            ),
            ns(type="response.completed", response=final),
        ),
    ],
    ids=["missing-done", "duplicate-done", "conflicting-done", "unstable-id"],
)
def test_responses_stream_rejects_invalid_function_argument_lifecycle(
    event_builder: object,
) -> None:
    function_item = FakeOutputItem(
        {
            "id": "function-1",
            "type": "function_call",
            "status": "completed",
            "call_id": "call-a",
            "name": "read_file",
            "arguments": "{}",
        }
    )
    final = FakeResponse(response_id="resp-function", output=(function_item,))
    stream = FakeStream(event_builder(final))  # type: ignore[operator]
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=FakeSDK(stream),
    )

    with pytest.raises(InvalidOpenAIResponseError, match="invalid"):
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )

    assert stream.closed is True


@pytest.mark.parametrize(
    "error_type",
    [
        FakeRateLimitError,
        FakeServerError,
        FakeTimeoutError,
        FakeConnectionError,
    ],
)
def test_responses_stream_retries_transient_error_before_delta(
    error_type: type[Exception],
) -> None:
    delays: list[float] = []
    final = valid_responses_response(text="ok", response_id="resp-retry")
    sdk = FakeSDK(
        error_type("Authorization: Bearer private-provider-body"),
        FakeStream((ns(type="response.completed", response=final),)),
    )
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=sdk,
        sleeper=delays.append,
    )

    response = client.stream(
        ModelRequest(messages=(UserMessage("task"),)),
        lambda event: None,
    )

    assert response.text == "ok"
    assert len(sdk.responses.calls) == 2
    assert delays == [0.25]


def test_responses_stream_stops_after_three_transient_attempts() -> None:
    delays: list[float] = []
    sdk = FakeSDK(
        FakeRateLimitError("private one"),
        FakeRateLimitError("private two"),
        FakeRateLimitError("private three"),
    )
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=sdk,
        sleeper=delays.append,
    )

    with pytest.raises(TransientModelError) as caught:
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )

    assert len(sdk.responses.calls) == 3
    assert delays == [0.25, 0.50]
    assert "private" not in str(caught.value)


def test_responses_stream_does_not_retry_after_text_delta() -> None:
    delays: list[float] = []
    sdk = FakeSDK(
        FakeStream(
            (
                ns(type="response.output_text.delta", delta="partial"),
                FakeTimeoutError("private timeout body"),
            )
        ),
        valid_responses_response(text="must not run", response_id="unused"),
    )
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=sdk,
        sleeper=delays.append,
    )
    events: list[ModelStreamEvent] = []

    with pytest.raises(StreamInterruptedError) as caught:
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            events.append,
        )

    assert len(sdk.responses.calls) == 1
    assert delays == []
    assert events[-1].kind is ModelStreamEventKind.RESPONSE_DISCARDED
    assert "private" not in str(caught.value)


def test_responses_stream_hidden_tool_delta_disables_retry_and_fallback() -> None:
    delays: list[float] = []
    sdk = FakeSDK(
        FakeStream(
            (
                ns(
                    type="response.function_call_arguments.delta",
                    output_index=0,
                    item_id="function-private",
                    delta='{"secret":"',
                ),
                StreamingUnsupportedError("unsupported"),
            )
        ),
        valid_responses_response(text="must not run", response_id="unused"),
    )
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=sdk,
        sleeper=delays.append,
    )

    with pytest.raises(StreamInterruptedError):
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )

    assert len(sdk.responses.calls) == 1
    assert delays == []


def test_responses_stream_structured_unsupported_before_delta_falls_back() -> None:
    final = valid_responses_response(text="fallback", response_id="resp-fallback")
    sdk = FakeSDK(StreamingUnsupportedError("unsupported"), final)
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=sdk,
    )
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=2)

    response = invoke_model_stream(
        client,
        ModelRequest(messages=(UserMessage("task"),)),
        budget,
        lambda event: None,
    )

    assert response.text == "fallback"
    assert (budget.logical_calls, budget.provider_attempts) == (1, 2)


@pytest.mark.parametrize(
    "error",
    [
        FakeAuthenticationError("private auth body"),
        FakeBadRequestError("private request body"),
    ],
)
def test_responses_stream_does_not_retry_permanent_errors(error: Exception) -> None:
    sdk = FakeSDK(error)
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=sdk,
    )

    with pytest.raises(FatalModelError) as caught:
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )

    assert len(sdk.responses.calls) == 1
    assert "private" not in str(caught.value)


def test_responses_stream_cleanup_failure_after_success_is_stable() -> None:
    final = valid_responses_response(text="ok", response_id="resp-cleanup")
    stream = FakeStream(
        (ns(type="response.completed", response=final),),
        close_error=OSError("private cleanup path"),
    )
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=FakeSDK(stream),
    )

    with pytest.raises(
        StreamInterruptedError,
        match="^model stream cleanup failed$",
    ) as caught:
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )

    assert stream.closed is True
    assert "private" not in str(caught.value)


def test_responses_stream_cleanup_failure_does_not_replace_primary_error() -> None:
    stream = FakeStream(
        (InvalidOpenAIResponseError("primary stable"),),
        close_error=OSError("private cleanup path"),
    )
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=FakeSDK(stream),
    )

    with pytest.raises(InvalidOpenAIResponseError, match="primary stable"):
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(9)])
def test_responses_stream_does_not_swallow_base_exception(
    error: BaseException,
) -> None:
    stream = FakeStream(
        (error,),
        close_error=OSError("cleanup must not replace base exception"),
    )
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=FakeSDK(stream),
    )

    with pytest.raises(type(error)):
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )


def test_responses_stream_preserves_provider_shaped_callback_error() -> None:
    final = valid_responses_response(text="partial", response_id="resp-callback")
    stream = FakeStream(
        (
            ns(type="response.output_text.delta", delta="partial"),
            ns(type="response.completed", response=final),
        )
    )
    sdk = FakeSDK(stream, FakeStream(()))
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=sdk,
    )
    callback_error = FakeTimeoutError("consumer timeout sentinel")
    observations: list[object] = []
    budget = ModelCallBudget(observer=ns(observe_model=observations.append))

    def fail_callback(event: ModelStreamEvent) -> None:
        if event.kind is ModelStreamEventKind.TEXT_DELTA:
            raise callback_error

    with pytest.raises(FakeTimeoutError) as caught:
        invoke_model_stream(
            client,
            ModelRequest(messages=(UserMessage("task"),)),
            budget,
            fail_callback,
        )

    assert caught.value is callback_error
    assert len(sdk.responses.calls) == 1
    assert stream.closed is True
    assert [observation.kind.value for observation in observations] == [
        "logical_started",
        "provider_started",
        "provider_failed",
        "logical_failed",
    ]


@pytest.mark.parametrize(
    "error",
    [
        FakeResponseValidationError("private validation body"),
        json.JSONDecodeError("private decode body", "private document", 0),
    ],
)
def test_responses_stream_maps_sdk_decode_failures_to_stable_invalid_response(
    error: Exception,
) -> None:
    stream = FakeStream((error,))
    client = OpenAIResponsesClient(
        model="test-model",
        api_key="not-real",
        sdk_client=FakeSDK(stream),
    )

    with pytest.raises(
        InvalidOpenAIResponseError,
        match="provider stream could not be decoded",
    ) as caught:
        client.stream(
            ModelRequest(messages=(UserMessage("task"),)),
            lambda event: None,
        )

    assert "private" not in str(caught.value)
    assert stream.closed is True

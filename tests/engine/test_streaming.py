from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from coding_agent.engine.agent import AgentRunner
from coding_agent.engine.messages import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    UserMessage,
)
from coding_agent.engine.model import (
    FakeModelClient,
    ModelBudgetExceeded,
    ModelCallBudget,
    ModelClient,
    ModelError,
    ModelObservation,
    ModelObservationKind,
)
from coding_agent.engine.streaming import (
    ModelStreamEvent,
    ModelStreamEventKind,
    StreamInterruptedError,
    StreamingModelClient,
    StreamingUnsupportedError,
    invoke_model_stream,
)
from coding_agent.operations.tools.base import ExecutionContext
from coding_agent.operations.tools.registry import ToolRegistry


def request() -> ModelRequest:
    return ModelRequest(messages=(UserMessage("stream"),))


@dataclass(frozen=True, slots=True)
class StreamScript:
    deltas: tuple[str, ...]
    outcome: ModelResponse | BaseException


class ScriptedStreamingClient:
    def __init__(
        self,
        streams: tuple[StreamScript, ...],
        *,
        complete_outcomes: tuple[ModelResponse | BaseException, ...] = (),
    ) -> None:
        self._streams = deque(streams)
        self._complete_outcomes = deque(complete_outcomes)
        self.stream_calls = 0
        self.complete_calls = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.complete_calls += 1
        outcome = self._complete_outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def complete_with_budget(
        self,
        request: ModelRequest,
        budget: ModelCallBudget,
    ) -> ModelResponse:
        index = budget.begin_provider_attempt(budget.active_purpose)
        try:
            response = self.complete(request)
        except Exception:
            budget.finish_provider_attempt(
                budget.active_purpose,
                index,
                error_code="provider_error",
                retry_scheduled=False,
                retry_delay_ms=None,
            )
            raise
        budget.finish_provider_attempt(
            budget.active_purpose,
            index,
            error_code=None,
            retry_scheduled=False,
            retry_delay_ms=None,
        )
        return response

    def stream(
        self,
        request: ModelRequest,
        emit: Callable[[ModelStreamEvent], None],
    ) -> ModelResponse:
        self.stream_calls += 1
        script = self._streams.popleft()
        for delta in script.deltas:
            emit(ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, delta))
        if isinstance(script.outcome, BaseException):
            raise script.outcome
        return script.outcome

    def stream_with_budget(
        self,
        request: ModelRequest,
        budget: ModelCallBudget,
        emit: Callable[[ModelStreamEvent], None],
    ) -> ModelResponse:
        index = budget.begin_provider_attempt(budget.active_purpose)
        try:
            response = self.stream(request, emit)
        except Exception:
            budget.finish_provider_attempt(
                budget.active_purpose,
                index,
                error_code="provider_error",
                retry_scheduled=False,
                retry_delay_ms=None,
            )
            raise
        budget.finish_provider_attempt(
            budget.active_purpose,
            index,
            error_code=None,
            retry_scheduled=False,
            retry_delay_ms=None,
        )
        return response


class RecordingModelObserver:
    def __init__(self) -> None:
        self.items: list[ModelObservation] = []

    def observe_model(self, observation: ModelObservation) -> None:
        self.items.append(observation)


def test_stream_event_invariants() -> None:
    assert ModelStreamEvent(
        ModelStreamEventKind.TEXT_DELTA,
        "a",
    ).delta == "a"
    assert ModelStreamEvent(
        ModelStreamEventKind.RESPONSE_COMPLETED
    ).delta is None
    assert ModelStreamEvent(
        ModelStreamEventKind.RESPONSE_DISCARDED
    ).delta is None
    with pytest.raises(ValueError):
        ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, "")
    with pytest.raises(ValueError):
        ModelStreamEvent(ModelStreamEventKind.RESPONSE_COMPLETED, "x")


def test_model_client_protocol_remains_sync_only() -> None:
    assert isinstance(FakeModelClient((ModelResponse(text="ok"),)), ModelClient)
    assert not isinstance(FakeModelClient(()), StreamingModelClient)


def test_nonstream_client_falls_back_inside_one_logical_call() -> None:
    client = FakeModelClient((ModelResponse(text="fallback"),))
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=1)
    events: list[ModelStreamEvent] = []

    response = invoke_model_stream(client, request(), budget, events.append)

    assert response.text == "fallback"
    assert budget.logical_calls == 1
    assert budget.provider_attempts == 1
    assert events == [ModelStreamEvent(ModelStreamEventKind.RESPONSE_COMPLETED)]


def test_structured_unsupported_before_delta_uses_second_attempt_same_logical() -> None:
    client = ScriptedStreamingClient(
        (StreamScript((), StreamingUnsupportedError("unsupported")),),
        complete_outcomes=(ModelResponse(text="fallback"),),
    )
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=2)
    events: list[ModelStreamEvent] = []

    response = invoke_model_stream(client, request(), budget, events.append)

    assert response.text == "fallback"
    assert (budget.logical_calls, budget.provider_attempts) == (1, 2)
    assert client.stream_calls == 1
    assert client.complete_calls == 1
    assert events == [ModelStreamEvent(ModelStreamEventKind.RESPONSE_COMPLETED)]


def test_unsupported_after_delta_discards_without_fallback() -> None:
    client = ScriptedStreamingClient(
        (
            StreamScript(
                ("partial",),
                StreamingUnsupportedError("unsupported"),
            ),
        ),
        complete_outcomes=(ModelResponse(text="must not run"),),
    )
    events: list[ModelStreamEvent] = []

    with pytest.raises(StreamInterruptedError, match="stream interrupted"):
        invoke_model_stream(client, request(), ModelCallBudget(), events.append)

    assert client.complete_calls == 0
    assert events == [
        ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, "partial"),
        ModelStreamEvent(ModelStreamEventKind.RESPONSE_DISCARDED),
    ]


def test_provider_budget_blocks_unsupported_fallback_before_second_call() -> None:
    client = ScriptedStreamingClient(
        (StreamScript((), StreamingUnsupportedError("unsupported")),),
        complete_outcomes=(ModelResponse(text="must not run"),),
    )
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=1)

    with pytest.raises(ModelBudgetExceeded):
        invoke_model_stream(client, request(), budget, lambda event: None)

    assert (budget.logical_calls, budget.provider_attempts) == (1, 1)
    assert client.complete_calls == 0


def test_ordinary_model_error_does_not_capability_fallback() -> None:
    client = ScriptedStreamingClient(
        (StreamScript((), ModelError("ordinary failure")),),
        complete_outcomes=(ModelResponse(text="must not run"),),
    )

    with pytest.raises(ModelError, match="ordinary failure"):
        invoke_model_stream(client, request(), ModelCallBudget(), lambda event: None)

    assert client.complete_calls == 0


def test_successful_stream_emits_deltas_then_one_completion() -> None:
    client = ScriptedStreamingClient(
        (StreamScript(("a", "b"), ModelResponse(text="ab")),),
    )
    events: list[ModelStreamEvent] = []

    response = invoke_model_stream(client, request(), ModelCallBudget(), events.append)

    assert response.text == "ab"
    assert events == [
        ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, "a"),
        ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, "b"),
        ModelStreamEvent(ModelStreamEventKind.RESPONSE_COMPLETED),
    ]


def test_callback_error_propagates_without_recursive_discard() -> None:
    client = ScriptedStreamingClient(
        (StreamScript(("delta",), ModelResponse(text="delta")),),
    )
    calls = 0

    def fail_callback(event: ModelStreamEvent) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("consumer failed")

    with pytest.raises(RuntimeError, match="consumer failed"):
        invoke_model_stream(client, request(), ModelCallBudget(), fail_callback)

    assert calls == 1


def test_callback_streaming_unsupported_error_is_not_capability_fallback() -> None:
    client = ScriptedStreamingClient(
        (StreamScript(("delta",), ModelResponse(text="delta")),),
        complete_outcomes=(ModelResponse(text="must not run"),),
    )
    callback_error = StreamingUnsupportedError("consumer sentinel")
    observer = RecordingModelObserver()
    budget = ModelCallBudget(observer=observer)

    def fail_callback(event: ModelStreamEvent) -> None:
        if event.kind is ModelStreamEventKind.TEXT_DELTA:
            raise callback_error

    with pytest.raises(StreamingUnsupportedError) as caught:
        invoke_model_stream(client, request(), budget, fail_callback)

    assert caught.value is callback_error
    assert client.complete_calls == 0
    assert [item.kind for item in observer.items] == [
        ModelObservationKind.LOGICAL_STARTED,
        ModelObservationKind.PROVIDER_STARTED,
        ModelObservationKind.PROVIDER_FAILED,
        ModelObservationKind.LOGICAL_FAILED,
    ]


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(7)])
def test_stream_base_exceptions_propagate(error: BaseException) -> None:
    client = ScriptedStreamingClient((StreamScript((), error),))

    with pytest.raises(type(error)):
        invoke_model_stream(client, request(), ModelCallBudget(), lambda event: None)


def test_agent_uses_streaming_for_main_call_when_handler_is_supplied(
    tmp_path: Path,
) -> None:
    events: list[ModelStreamEvent] = []
    client = ScriptedStreamingClient(
        (StreamScript(("done",), ModelResponse(text="done")),),
    )
    runner = AgentRunner(
        model_client=client,
        tool_registry=ToolRegistry(()),
        execution_context=ExecutionContext(tmp_path),
        stream_handler=events.append,
    )

    state = runner.run("repair")

    assert client.stream_calls == 1
    assert client.complete_calls == 0
    assert events[-1].kind is ModelStreamEventKind.RESPONSE_COMPLETED
    assert state.messages[-1] == AssistantMessage(content="done")


def test_agent_discards_partial_stream_before_retrying(tmp_path: Path) -> None:
    events: list[ModelStreamEvent] = []
    client = ScriptedStreamingClient(
        (
            StreamScript(("partial",), ModelError("temporary")),
            StreamScript(("final",), ModelResponse(text="final")),
        )
    )
    runner = AgentRunner(
        model_client=client,
        tool_registry=ToolRegistry(()),
        execution_context=ExecutionContext(tmp_path),
        stream_handler=events.append,
    )

    state = runner.run("repair")

    assert [event.kind for event in events] == [
        ModelStreamEventKind.TEXT_DELTA,
        ModelStreamEventKind.RESPONSE_DISCARDED,
        ModelStreamEventKind.TEXT_DELTA,
        ModelStreamEventKind.RESPONSE_COMPLETED,
    ]
    assert all(
        not isinstance(message, AssistantMessage)
        or message.content != "partial"
        for message in state.messages
    )
    assert state.messages[-1] == AssistantMessage(content="final")


def test_agent_without_handler_preserves_synchronous_path(tmp_path: Path) -> None:
    client = ScriptedStreamingClient(
        (StreamScript(("unused",), ModelResponse(text="unused")),),
        complete_outcomes=(ModelResponse(text="sync"),),
    )
    runner = AgentRunner(
        model_client=client,
        tool_registry=ToolRegistry(()),
        execution_context=ExecutionContext(tmp_path),
    )

    state = runner.run("repair")

    assert client.complete_calls == 1
    assert client.stream_calls == 0
    assert state.messages[-1] == AssistantMessage(content="sync")

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeAlias, runtime_checkable

from coding_agent.engine.messages import ModelRequest, ModelResponse
from coding_agent.engine.model import (
    ModelCallBudget,
    ModelCallPurpose,
    ModelClient,
    ModelError,
    _complete_with_active_budget,
    _model_error_code,
)


class ModelStreamEventKind(StrEnum):
    TEXT_DELTA = "text_delta"
    RESPONSE_COMPLETED = "response_completed"
    RESPONSE_DISCARDED = "response_discarded"


@dataclass(frozen=True, slots=True)
class ModelStreamEvent:
    kind: ModelStreamEventKind
    delta: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ModelStreamEventKind):
            raise TypeError("kind must be ModelStreamEventKind")
        if self.kind is ModelStreamEventKind.TEXT_DELTA:
            if not isinstance(self.delta, str) or not self.delta:
                raise ValueError("text delta must be a non-empty string")
        elif self.delta is not None:
            raise ValueError("lifecycle events must not contain a delta")


ModelStreamHandler: TypeAlias = Callable[[ModelStreamEvent], None]


@runtime_checkable
class StreamingModelClient(Protocol):
    def stream(
        self,
        request: ModelRequest,
        emit: ModelStreamHandler,
    ) -> ModelResponse: ...


@runtime_checkable
class BudgetAwareStreamingModelClient(Protocol):
    def stream_with_budget(
        self,
        request: ModelRequest,
        budget: ModelCallBudget,
        emit: ModelStreamHandler,
    ) -> ModelResponse: ...


class StreamingUnsupportedError(ModelError):
    """The selected provider cannot stream this request shape."""


class StreamInterruptedError(ModelError):
    """A stream ended after provisional provider output was observed."""


class _StreamCallbackError(Exception):
    def __init__(self, error: Exception) -> None:
        self.error = error
        super().__init__()


def _stream_with_core_budget(
    client: StreamingModelClient,
    request: ModelRequest,
    budget: ModelCallBudget,
    emit: ModelStreamHandler,
) -> ModelResponse:
    purpose = budget.active_purpose
    provider_attempt_index = budget.begin_provider_attempt(purpose)
    try:
        response = client.stream(request, emit)
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


def invoke_model_stream(
    client: ModelClient,
    request: ModelRequest,
    budget: ModelCallBudget,
    emit: ModelStreamHandler,
    *,
    purpose: ModelCallPurpose = ModelCallPurpose.MAIN,
) -> ModelResponse:
    if not callable(emit):
        raise TypeError("emit must be callable")

    logical_call_index = budget.begin_logical_call(purpose, request)
    delivered_text = False
    callback_failed = False

    def tracked_emit(event: ModelStreamEvent) -> None:
        nonlocal delivered_text, callback_failed
        if not isinstance(event, ModelStreamEvent):
            raise TypeError("stream event must be ModelStreamEvent")
        try:
            emit(event)
        except BaseException as exc:
            callback_failed = True
            if isinstance(exc, Exception):
                raise _StreamCallbackError(exc) from None
            raise
        if event.kind is ModelStreamEventKind.TEXT_DELTA:
            delivered_text = True

    try:
        try:
            if isinstance(client, BudgetAwareStreamingModelClient):
                response = client.stream_with_budget(
                    request,
                    budget,
                    tracked_emit,
                )
            elif isinstance(client, StreamingModelClient):
                response = _stream_with_core_budget(
                    client,
                    request,
                    budget,
                    tracked_emit,
                )
            else:
                response = _complete_with_active_budget(client, request, budget)
        except StreamingUnsupportedError:
            if delivered_text:
                if not callback_failed:
                    tracked_emit(
                        ModelStreamEvent(ModelStreamEventKind.RESPONSE_DISCARDED)
                    )
                raise StreamInterruptedError("model stream interrupted") from None
            response = _complete_with_active_budget(client, request, budget)
        except Exception:
            if delivered_text and not callback_failed:
                tracked_emit(
                    ModelStreamEvent(ModelStreamEventKind.RESPONSE_DISCARDED)
                )
            raise

        if not isinstance(response, ModelResponse):
            raise ModelError("model stream returned an invalid response")
        tracked_emit(ModelStreamEvent(ModelStreamEventKind.RESPONSE_COMPLETED))
    except _StreamCallbackError as callback_error:
        original = callback_error.error
        if isinstance(original, Exception) and not budget._observer_failed:
            budget.finish_logical_call(
                purpose,
                logical_call_index,
                response=None,
                error_code=_model_error_code(original),
            )
        raise original
    except Exception as exc:
        if budget._observer_failed:
            raise
        budget.finish_logical_call(
            purpose,
            logical_call_index,
            response=None,
            error_code=_model_error_code(exc),
        )
        raise

    budget.finish_logical_call(
        purpose,
        logical_call_index,
        response=response,
        error_code=None,
    )
    return response

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
from typing import Protocol, TypeAlias, runtime_checkable

from coding_agent.messages import ModelRequest, ModelResponse, TokenUsage


DEFAULT_PROVIDER_TIMEOUT_SECONDS = 30.0


@runtime_checkable
class ModelClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...


class ModelError(RuntimeError):
    """Base class for failures crossing the model-client boundary."""


class InvalidModelResponseError(ModelError):
    """A completed provider response cannot be parsed safely."""

    observation_error_code = "invalid_model_response"


class ModelOutputLimitError(ModelError):
    """The provider stopped generation at the configured output limit."""

    observation_error_code = "model_output_limit"


class TransientModelError(ModelError):
    """A retryable model failure such as timeout, 429, or 5xx."""


class FatalModelError(ModelError):
    """A non-retryable authentication, model, or request failure."""


class ModelBudgetReason(StrEnum):
    LOGICAL_CALL_LIMIT = "logical_model_call_limit"
    MAIN_LOGICAL_CALL_LIMIT = "main_model_call_limit"
    SUMMARY_LOGICAL_CALL_LIMIT = "summary_model_call_limit"
    PROVIDER_ATTEMPT_LIMIT = "provider_attempt_limit"
    SUMMARY_PROVIDER_ATTEMPT_LIMIT = "summary_provider_attempt_limit"


class ModelCallPurpose(StrEnum):
    MAIN = "main"
    SUMMARY = "summary"


class ModelObservationKind(StrEnum):
    LOGICAL_STARTED = "logical_started"
    LOGICAL_COMPLETED = "logical_completed"
    LOGICAL_FAILED = "logical_failed"
    LOGICAL_BLOCKED = "logical_blocked"
    PROVIDER_STARTED = "provider_started"
    PROVIDER_COMPLETED = "provider_completed"
    PROVIDER_FAILED = "provider_failed"
    PROVIDER_BLOCKED = "provider_blocked"


@dataclass(frozen=True, slots=True)
class ModelObservation:
    kind: ModelObservationKind
    purpose: ModelCallPurpose
    logical_call_index: int
    provider_attempt_index: int | None = None
    message_count: int | None = None
    tool_schema_count: int | None = None
    continuation_count: int | None = None
    has_text: bool | None = None
    text_chars: int | None = None
    tool_call_count: int | None = None
    usage: TokenUsage | None = None
    provider_response_id_hash: str | None = None
    error_code: str | None = None
    retry_scheduled: bool | None = None
    retry_delay_ms: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ModelObservationKind):
            raise TypeError("kind must be ModelObservationKind")
        if not isinstance(self.purpose, ModelCallPurpose):
            raise TypeError("purpose must be ModelCallPurpose")
        for name in (
            "logical_call_index",
            "provider_attempt_index",
            "message_count",
            "tool_schema_count",
            "continuation_count",
            "text_chars",
            "tool_call_count",
            "retry_delay_ms",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or null")
        if self.logical_call_index < 1:
            raise ValueError("logical_call_index must be positive")
        if self.provider_attempt_index == 0:
            raise ValueError("provider_attempt_index must be positive")
        for name in ("has_text", "retry_scheduled"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean or null")
        if self.usage is not None and not isinstance(self.usage, TokenUsage):
            raise TypeError("usage must be TokenUsage or null")
        if self.provider_response_id_hash is not None and (
            len(self.provider_response_id_hash) != 64
            or any(ch not in "0123456789abcdef" for ch in self.provider_response_id_hash)
        ):
            raise ValueError("provider_response_id_hash must be lowercase SHA-256")
        if self.error_code is not None and (
            not isinstance(self.error_code, str) or not self.error_code
        ):
            raise ValueError("error_code must be a non-empty string or null")

        populated = {
            name
            for name in (
                "provider_attempt_index",
                "message_count",
                "tool_schema_count",
                "continuation_count",
                "has_text",
                "text_chars",
                "tool_call_count",
                "usage",
                "provider_response_id_hash",
                "error_code",
                "retry_scheduled",
                "retry_delay_ms",
            )
            if getattr(self, name) is not None
        }
        required: dict[ModelObservationKind, set[str]] = {
            ModelObservationKind.LOGICAL_STARTED: {
                "message_count", "tool_schema_count", "continuation_count"
            },
            ModelObservationKind.LOGICAL_COMPLETED: {
                "continuation_count", "has_text", "text_chars", "tool_call_count"
            },
            ModelObservationKind.LOGICAL_FAILED: {"error_code"},
            ModelObservationKind.LOGICAL_BLOCKED: {"error_code"},
            ModelObservationKind.PROVIDER_STARTED: {"provider_attempt_index"},
            ModelObservationKind.PROVIDER_COMPLETED: {"provider_attempt_index"},
            ModelObservationKind.PROVIDER_FAILED: {
                "provider_attempt_index", "error_code", "retry_scheduled"
            },
            ModelObservationKind.PROVIDER_BLOCKED: {"error_code"},
        }
        allowed = {
            ModelObservationKind.LOGICAL_STARTED: required[ModelObservationKind.LOGICAL_STARTED],
            ModelObservationKind.LOGICAL_COMPLETED: required[ModelObservationKind.LOGICAL_COMPLETED]
            | {"usage", "provider_response_id_hash"},
            ModelObservationKind.LOGICAL_FAILED: {"error_code"},
            ModelObservationKind.LOGICAL_BLOCKED: {"error_code"},
            ModelObservationKind.PROVIDER_STARTED: {"provider_attempt_index"},
            ModelObservationKind.PROVIDER_COMPLETED: {"provider_attempt_index"},
            ModelObservationKind.PROVIDER_FAILED: required[ModelObservationKind.PROVIDER_FAILED]
            | {"retry_delay_ms"},
            ModelObservationKind.PROVIDER_BLOCKED: {"error_code"},
        }
        if not required[self.kind] <= populated or not populated <= allowed[self.kind]:
            raise ValueError(f"invalid fields for {self.kind.value}")
        if self.kind is ModelObservationKind.PROVIDER_FAILED:
            if self.retry_scheduled is True and self.retry_delay_ms is None:
                raise ValueError("retry_delay_ms is required for a scheduled retry")
            if self.retry_scheduled is False and self.retry_delay_ms is not None:
                raise ValueError("retry_delay_ms requires a scheduled retry")


class ModelObservationSink(Protocol):
    def observe_model(self, observation: ModelObservation) -> None: ...


class ModelBudgetExceeded(ModelError):
    def __init__(self, reason: ModelBudgetReason) -> None:
        if not isinstance(reason, ModelBudgetReason):
            raise TypeError("reason must be ModelBudgetReason")
        self.reason = reason
        message = {
            ModelBudgetReason.LOGICAL_CALL_LIMIT: (
                "logical model call limit reached"
            ),
            ModelBudgetReason.MAIN_LOGICAL_CALL_LIMIT: (
                "main model call limit reached"
            ),
            ModelBudgetReason.SUMMARY_LOGICAL_CALL_LIMIT: (
                "summary model call limit reached"
            ),
            ModelBudgetReason.PROVIDER_ATTEMPT_LIMIT: (
                "provider attempt limit reached"
            ),
            ModelBudgetReason.SUMMARY_PROVIDER_ATTEMPT_LIMIT: (
                "summary provider attempt limit reached"
            ),
        }[reason]
        super().__init__(message)


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _bounded_count(value: object, maximum: int, name: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > maximum
    ):
        raise ValueError(f"{name} must be between 0 and its maximum")
    return value


@dataclass(slots=True)
class ModelCallBudget:
    max_logical_calls: int = 12
    max_provider_attempts: int = 12
    max_main_logical_calls: int | None = None
    max_summary_logical_calls: int | None = None
    max_summary_provider_attempts: int | None = None
    logical_calls: int = 0
    provider_attempts: int = 0
    main_logical_calls: int = 0
    summary_logical_calls: int = 0
    summary_provider_attempts: int = 0
    observer: ModelObservationSink | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _active_purpose: ModelCallPurpose | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )
    _observer_failed: bool = field(
        default=False,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        self.max_logical_calls = _positive_integer(
            self.max_logical_calls,
            "max_logical_calls",
        )
        self.max_provider_attempts = _positive_integer(
            self.max_provider_attempts,
            "max_provider_attempts",
        )
        for name, total_limit in (
            ("max_main_logical_calls", self.max_logical_calls),
            ("max_summary_logical_calls", self.max_logical_calls),
            ("max_summary_provider_attempts", self.max_provider_attempts),
        ):
            value = getattr(self, name)
            if value is None:
                continue
            validated = _positive_integer(value, name)
            if validated > total_limit:
                raise ValueError(f"{name} must not exceed its total limit")
            setattr(self, name, validated)
        self.logical_calls = _bounded_count(
            self.logical_calls,
            self.max_logical_calls,
            "logical_calls",
        )
        self.provider_attempts = _bounded_count(
            self.provider_attempts,
            self.max_provider_attempts,
            "provider_attempts",
        )
        self.main_logical_calls = _bounded_count(
            self.main_logical_calls,
            self.max_main_logical_calls or self.max_logical_calls,
            "main_logical_calls",
        )
        self.summary_logical_calls = _bounded_count(
            self.summary_logical_calls,
            self.max_summary_logical_calls or self.max_logical_calls,
            "summary_logical_calls",
        )
        self.summary_provider_attempts = _bounded_count(
            self.summary_provider_attempts,
            self.max_summary_provider_attempts or self.max_provider_attempts,
            "summary_provider_attempts",
        )
        if self.main_logical_calls + self.summary_logical_calls > self.logical_calls:
            raise ValueError("purpose logical counts must not exceed logical_calls")
        if self.summary_provider_attempts > self.provider_attempts:
            raise ValueError(
                "summary_provider_attempts must not exceed provider_attempts"
            )

    def start_logical_call(self) -> None:
        if self.logical_calls >= self.max_logical_calls:
            raise ModelBudgetExceeded(ModelBudgetReason.LOGICAL_CALL_LIMIT)
        self.logical_calls += 1

    def _observe(self, observation: ModelObservation) -> None:
        if self.observer is None:
            return
        try:
            self.observer.observe_model(observation)
        except Exception:
            self._observer_failed = True
            raise

    @property
    def active_purpose(self) -> ModelCallPurpose:
        return self._active_purpose or ModelCallPurpose.MAIN

    def begin_logical_call(
        self,
        purpose: ModelCallPurpose,
        request: ModelRequest,
    ) -> int:
        if not isinstance(purpose, ModelCallPurpose):
            raise TypeError("purpose must be ModelCallPurpose")
        logical_call_index = self.logical_calls + 1
        blocked_reason: ModelBudgetReason | None = None
        if (
            purpose is ModelCallPurpose.MAIN
            and self.max_main_logical_calls is not None
            and self.main_logical_calls >= self.max_main_logical_calls
        ):
            blocked_reason = ModelBudgetReason.MAIN_LOGICAL_CALL_LIMIT
        elif (
            purpose is ModelCallPurpose.SUMMARY
            and self.max_summary_logical_calls is not None
            and self.summary_logical_calls >= self.max_summary_logical_calls
        ):
            blocked_reason = ModelBudgetReason.SUMMARY_LOGICAL_CALL_LIMIT
        elif self.logical_calls >= self.max_logical_calls:
            blocked_reason = ModelBudgetReason.LOGICAL_CALL_LIMIT
        if blocked_reason is not None:
            self._observe(
                ModelObservation(
                    ModelObservationKind.LOGICAL_BLOCKED,
                    purpose,
                    logical_call_index,
                    error_code=blocked_reason.value,
                )
            )
            raise ModelBudgetExceeded(blocked_reason)
        self._observe(
            ModelObservation(
                ModelObservationKind.LOGICAL_STARTED,
                purpose,
                logical_call_index,
                message_count=len(request.messages),
                tool_schema_count=len(request.tool_schemas),
                continuation_count=len(request.continuation_items),
            )
        )
        self.start_logical_call()
        if purpose is ModelCallPurpose.MAIN:
            self.main_logical_calls += 1
        else:
            self.summary_logical_calls += 1
        self._active_purpose = purpose
        return logical_call_index

    def finish_logical_call(
        self,
        purpose: ModelCallPurpose,
        logical_call_index: int,
        *,
        response: ModelResponse | None,
        error_code: str | None,
    ) -> None:
        if (response is None) == (error_code is None):
            raise ValueError("provide exactly one of response or error_code")
        try:
            if response is None:
                observation = ModelObservation(
                    ModelObservationKind.LOGICAL_FAILED,
                    purpose,
                    logical_call_index,
                    error_code=error_code,
                )
            else:
                response_id_hash = (
                    None
                    if response.provider_response_id is None
                    else hashlib.sha256(
                        response.provider_response_id.encode("utf-8")
                    ).hexdigest()
                )
                observation = ModelObservation(
                    ModelObservationKind.LOGICAL_COMPLETED,
                    purpose,
                    logical_call_index,
                    continuation_count=len(response.continuation_items),
                    has_text=response.text is not None,
                    text_chars=0 if response.text is None else len(response.text),
                    tool_call_count=len(response.tool_calls),
                    usage=response.usage,
                    provider_response_id_hash=response_id_hash,
                )
            self._observe(observation)
        finally:
            self._active_purpose = None

    def claim_provider_attempt(self) -> None:
        if self.provider_attempts >= self.max_provider_attempts:
            raise ModelBudgetExceeded(ModelBudgetReason.PROVIDER_ATTEMPT_LIMIT)
        self.provider_attempts += 1

    def begin_provider_attempt(self, purpose: ModelCallPurpose) -> int:
        if not isinstance(purpose, ModelCallPurpose):
            raise TypeError("purpose must be ModelCallPurpose")
        provider_attempt_index = self.provider_attempts + 1
        logical_call_index = max(1, self.logical_calls)
        blocked_reason: ModelBudgetReason | None = None
        if self.provider_attempts >= self.max_provider_attempts:
            blocked_reason = ModelBudgetReason.PROVIDER_ATTEMPT_LIMIT
        elif (
            purpose is ModelCallPurpose.SUMMARY
            and self.max_summary_provider_attempts is not None
            and self.summary_provider_attempts
            >= self.max_summary_provider_attempts
        ):
            blocked_reason = ModelBudgetReason.SUMMARY_PROVIDER_ATTEMPT_LIMIT
        if blocked_reason is not None:
            self._observe(
                ModelObservation(
                    ModelObservationKind.PROVIDER_BLOCKED,
                    purpose,
                    logical_call_index,
                    error_code=blocked_reason.value,
                )
            )
            raise ModelBudgetExceeded(blocked_reason)
        self._observe(
            ModelObservation(
                ModelObservationKind.PROVIDER_STARTED,
                purpose,
                logical_call_index,
                provider_attempt_index=provider_attempt_index,
            )
        )
        self.claim_provider_attempt()
        if purpose is ModelCallPurpose.SUMMARY:
            self.summary_provider_attempts += 1
        return provider_attempt_index

    def finish_provider_attempt(
        self,
        purpose: ModelCallPurpose,
        provider_attempt_index: int,
        *,
        error_code: str | None,
        retry_scheduled: bool,
        retry_delay_ms: int | None,
    ) -> None:
        kind = (
            ModelObservationKind.PROVIDER_COMPLETED
            if error_code is None
            else ModelObservationKind.PROVIDER_FAILED
        )
        self._observe(
            ModelObservation(
                kind,
                purpose,
                max(1, self.logical_calls),
                provider_attempt_index=provider_attempt_index,
                error_code=error_code,
                retry_scheduled=(None if error_code is None else retry_scheduled),
                retry_delay_ms=(None if error_code is None else retry_delay_ms),
            )
        )

    @property
    def remaining_provider_attempts(self) -> int:
        return self.max_provider_attempts - self.provider_attempts


@runtime_checkable
class BudgetAwareModelClient(Protocol):
    def complete_with_budget(
        self,
        request: ModelRequest,
        budget: ModelCallBudget,
    ) -> ModelResponse: ...


class FakeModelExhaustedError(AssertionError):
    """Raised when a fake client receives more requests than scripted outcomes."""


ScriptedOutcome: TypeAlias = ModelResponse | ModelError


class FakeModelClient:
    def __init__(self, outcomes: Iterable[ScriptedOutcome]) -> None:
        scripted = tuple(outcomes)
        for index, outcome in enumerate(scripted):
            if not isinstance(outcome, (ModelResponse, ModelError)):
                raise TypeError(
                    f"outcome {index} must be ModelResponse or ModelError"
                )
        self._outcomes: deque[ScriptedOutcome] = deque(scripted)
        self._requests: list[ModelRequest] = []

    @property
    def requests(self) -> tuple[ModelRequest, ...]:
        return tuple(self._requests)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self._requests.append(request)
        if not self._outcomes:
            raise FakeModelExhaustedError(
                "FakeModelClient has no scripted outcome "
                f"for request #{len(self._requests)}"
            )

        outcome = self._outcomes.popleft()
        if isinstance(outcome, ModelError):
            raise outcome
        return outcome

    def complete_with_budget(
        self,
        request: ModelRequest,
        budget: ModelCallBudget,
    ) -> ModelResponse:
        purpose = budget.active_purpose
        provider_attempt_index = budget.begin_provider_attempt(purpose)
        try:
            response = self.complete(request)
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


def _model_error_code(error: Exception) -> str:
    observation_code = getattr(error, "observation_error_code", None)
    if observation_code in {"invalid_model_response", "model_output_limit"}:
        return observation_code
    if isinstance(error, ModelBudgetExceeded):
        return "model_budget_exceeded"
    if isinstance(error, TransientModelError):
        return "transient_model_error"
    if isinstance(error, FatalModelError):
        return "fatal_model_error"
    if isinstance(error, ModelError):
        return "model_client_error"
    return "model_client_error"


def _complete_with_active_budget(
    client: ModelClient,
    request: ModelRequest,
    budget: ModelCallBudget,
) -> ModelResponse:
    """Complete a request while its logical model call is already active."""
    if isinstance(client, BudgetAwareModelClient):
        return client.complete_with_budget(request, budget)

    purpose = budget.active_purpose
    provider_attempt_index = budget.begin_provider_attempt(purpose)
    try:
        response = client.complete(request)
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


def invoke_model(
    client: ModelClient,
    request: ModelRequest,
    budget: ModelCallBudget,
    *,
    purpose: ModelCallPurpose = ModelCallPurpose.MAIN,
) -> ModelResponse:
    logical_call_index = budget.begin_logical_call(purpose, request)
    try:
        response = _complete_with_active_budget(client, request, budget)
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

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeAlias, runtime_checkable

from coding_agent.messages import ModelRequest, ModelResponse


@runtime_checkable
class ModelClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...


class ModelError(RuntimeError):
    """Base class for failures crossing the model-client boundary."""


class TransientModelError(ModelError):
    """A retryable model failure such as timeout, 429, or 5xx."""


class FatalModelError(ModelError):
    """A non-retryable authentication, model, or request failure."""


class ModelBudgetReason(StrEnum):
    LOGICAL_CALL_LIMIT = "logical_model_call_limit"
    PROVIDER_ATTEMPT_LIMIT = "provider_attempt_limit"


class ModelBudgetExceeded(ModelError):
    def __init__(self, reason: ModelBudgetReason) -> None:
        if not isinstance(reason, ModelBudgetReason):
            raise TypeError("reason must be ModelBudgetReason")
        self.reason = reason
        message = {
            ModelBudgetReason.LOGICAL_CALL_LIMIT: (
                "logical model call limit reached"
            ),
            ModelBudgetReason.PROVIDER_ATTEMPT_LIMIT: (
                "provider attempt limit reached"
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
    logical_calls: int = 0
    provider_attempts: int = 0

    def __post_init__(self) -> None:
        self.max_logical_calls = _positive_integer(
            self.max_logical_calls,
            "max_logical_calls",
        )
        self.max_provider_attempts = _positive_integer(
            self.max_provider_attempts,
            "max_provider_attempts",
        )
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

    def start_logical_call(self) -> None:
        if self.logical_calls >= self.max_logical_calls:
            raise ModelBudgetExceeded(ModelBudgetReason.LOGICAL_CALL_LIMIT)
        self.logical_calls += 1

    def claim_provider_attempt(self) -> None:
        if self.provider_attempts >= self.max_provider_attempts:
            raise ModelBudgetExceeded(ModelBudgetReason.PROVIDER_ATTEMPT_LIMIT)
        self.provider_attempts += 1

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
        budget.claim_provider_attempt()
        return self.complete(request)


def invoke_model(
    client: ModelClient,
    request: ModelRequest,
    budget: ModelCallBudget,
) -> ModelResponse:
    budget.start_logical_call()
    if isinstance(client, BudgetAwareModelClient):
        return client.complete_with_budget(request, budget)
    budget.claim_provider_attempt()
    return client.complete(request)

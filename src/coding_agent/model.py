from __future__ import annotations

from collections import deque
from collections.abc import Iterable
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

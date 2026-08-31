from __future__ import annotations

import inspect
import hashlib
import os
import subprocess
import sys
from typing import get_type_hints

import pytest

from coding_agent.engine.messages import (
    ModelRequest,
    ModelResponse,
    TokenUsage,
    ToolCall,
    UserMessage,
)
from coding_agent.engine.model import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    FakeModelClient,
    FakeModelExhaustedError,
    FatalModelError,
    InvalidModelResponseError,
    ModelBudgetExceeded,
    ModelBudgetReason,
    ModelCallBudget,
    ModelCallPurpose,
    ModelClient,
    ModelError,
    ModelOutputLimitError,
    ModelObservation,
    ModelObservationKind,
    TransientModelError,
    invoke_model,
)


def test_default_provider_timeout_is_fixed_and_positive() -> None:
    assert DEFAULT_PROVIDER_TIMEOUT_SECONDS == 30.0


def test_model_response_failures_expose_stable_safe_codes() -> None:
    invalid = InvalidModelResponseError("safe invalid response")
    limited = ModelOutputLimitError("safe output limit")

    assert isinstance(invalid, ModelError)
    assert invalid.observation_error_code == "invalid_model_response"
    assert isinstance(limited, ModelError)
    assert limited.observation_error_code == "model_output_limit"


class RecordingModelObserver:
    def __init__(self) -> None:
        self.items: list[ModelObservation] = []

    def observe_model(self, observation: ModelObservation) -> None:
        self.items.append(observation)


def _request(content: str) -> ModelRequest:
    return ModelRequest(messages=(UserMessage(content),))


TEXT_RESPONSE = ModelResponse(text="done")
SINGLE_TOOL_RESPONSE = ModelResponse(
    tool_calls=(
        ToolCall(
            call_id="call_1",
            name="read_file",
            arguments={"path": "src/example.py"},
        ),
    )
)
MULTI_TOOL_RESPONSE = ModelResponse(
    tool_calls=(
        ToolCall(
            call_id="call_1",
            name="read_file",
            arguments={"path": "a.py"},
        ),
        ToolCall(
            call_id="call_2",
            name="read_file",
            arguments={"path": "b.py"},
        ),
    )
)
COMBINED_RESPONSE = ModelResponse(
    text="I will inspect both files.",
    tool_calls=MULTI_TOOL_RESPONSE.tool_calls,
)
SUMMARY_RESPONSE = ModelResponse(
    text=(
        '{"goal":"repair failing tests",'
        '"open_issues":["identify the failing assertion"]}'
    )
)


def test_model_client_protocol_uses_task_2_types() -> None:
    client = FakeModelClient(())

    assert isinstance(client, ModelClient)
    assert tuple(inspect.signature(ModelClient.complete).parameters) == (
        "self",
        "request",
    )
    assert tuple(inspect.signature(FakeModelClient).parameters) == ("outcomes",)
    assert get_type_hints(ModelClient.complete) == {
        "request": ModelRequest,
        "return": ModelResponse,
    }


def test_fake_model_returns_scripted_responses_and_records_requests() -> None:
    first_request = _request("first")
    second_request = _request("second")
    first_response = ModelResponse(text="first result")
    second_response = ModelResponse(text="second result")
    client = FakeModelClient((first_response, second_response))

    assert client.complete(first_request) is first_response
    assert client.complete(second_request) is second_response
    assert client.requests == (first_request, second_request)


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(TEXT_RESPONSE, id="text"),
        pytest.param(SINGLE_TOOL_RESPONSE, id="single-tool-call"),
        pytest.param(MULTI_TOOL_RESPONSE, id="multiple-tool-calls"),
        pytest.param(COMBINED_RESPONSE, id="text-and-tool-calls"),
        pytest.param(SUMMARY_RESPONSE, id="context-summary"),
    ],
)
def test_fake_model_supports_successful_response_shapes(
    response: ModelResponse,
) -> None:
    request = _request("scripted request")
    client = FakeModelClient((response,))

    returned = client.complete(request)

    assert returned is response
    assert returned == response
    assert client.requests == (request,)


def test_fake_model_preserves_multiple_tool_call_order() -> None:
    client = FakeModelClient((MULTI_TOOL_RESPONSE,))

    returned = client.complete(_request("inspect in order"))

    assert tuple(call.call_id for call in returned.tool_calls) == (
        "call_1",
        "call_2",
    )
    assert tuple(call.arguments["path"] for call in returned.tool_calls) == (
        "a.py",
        "b.py",
    )


def test_fake_model_exhaustion_is_explicit_and_records_request() -> None:
    first_request = _request("first")
    exhausted_request = _request("unexpected second call")
    client = FakeModelClient((ModelResponse(text="only response"),))

    client.complete(first_request)

    with pytest.raises(
        FakeModelExhaustedError,
        match=r"no scripted outcome.*request #2",
    ):
        client.complete(exhausted_request)

    assert client.requests == (first_request, exhausted_request)


def test_fake_model_rejects_invalid_script_item_at_construction() -> None:
    invalid = object()

    with pytest.raises(TypeError, match=r"outcome 1.*ModelResponse or ModelError"):
        FakeModelClient((ModelResponse(text="valid"), invalid))  # type: ignore[arg-type]


def test_fake_model_raises_scripted_base_error_and_records_request() -> None:
    request = _request("scripted base error")
    error = ModelError("scripted model failure")
    client = FakeModelClient((error,))

    with pytest.raises(ModelError, match="scripted model failure") as caught:
        client.complete(request)

    assert caught.value is error
    assert client.requests == (request,)


def test_model_module_imports_offline_without_openai_or_api_key() -> None:
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "openai" or name.startswith("openai."):
        raise AssertionError("coding_agent.engine.model imported OpenAI SDK")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import coding_agent.engine.model
"""
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr


def test_fake_model_replays_transient_and_fatal_errors_in_order() -> None:
    request = _request("retryable then fatal")
    transient = TransientModelError("temporary rate limit")
    recovery = ModelResponse(text="recovered")
    fatal = FatalModelError("invalid model configuration")
    client = FakeModelClient((transient, recovery, fatal))

    assert isinstance(transient, ModelError)
    assert isinstance(fatal, ModelError)

    with pytest.raises(TransientModelError, match="temporary rate limit") as caught:
        client.complete(request)
    assert caught.value is transient

    assert client.complete(request) is recovery

    with pytest.raises(FatalModelError, match="invalid model configuration") as caught:
        client.complete(request)
    assert caught.value is fatal

    assert client.requests == (request, request, request)


def test_invoke_model_counts_one_logical_and_one_physical_attempt() -> None:
    client = FakeModelClient((ModelResponse(text="done"),))
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=1)

    response = invoke_model(client, _request("count"), budget)

    assert response.text == "done"
    assert budget.logical_calls == 1
    assert budget.provider_attempts == 1
    assert len(client.requests) == 1


def test_generic_client_emits_one_logical_and_one_physical_attempt() -> None:
    observer = RecordingModelObserver()
    budget = ModelCallBudget(observer=observer)
    response = ModelResponse(
        text="ok",
        usage=TokenUsage(input_tokens=3, output_tokens=2, total_tokens=5),
        provider_response_id="response-safe-id",
    )

    returned = invoke_model(
        FakeModelClient((response,)),
        _request("observe without recording the body"),
        budget,
        purpose=ModelCallPurpose.MAIN,
    )

    assert returned is response
    assert [item.kind for item in observer.items] == [
        ModelObservationKind.LOGICAL_STARTED,
        ModelObservationKind.PROVIDER_STARTED,
        ModelObservationKind.PROVIDER_COMPLETED,
        ModelObservationKind.LOGICAL_COMPLETED,
    ]
    assert observer.items[0].message_count == 1
    assert observer.items[0].tool_schema_count == 0
    assert observer.items[0].continuation_count == 0
    assert observer.items[-1].usage == response.usage
    assert observer.items[-1].provider_response_id_hash == hashlib.sha256(
        b"response-safe-id"
    ).hexdigest()
    assert budget.logical_calls == 1
    assert budget.provider_attempts == 1


def test_transient_model_error_emits_stable_failure_without_exception_body() -> None:
    observer = RecordingModelObserver()
    budget = ModelCallBudget(observer=observer)
    secret = "Authorization: Bearer provider-private"

    with pytest.raises(TransientModelError):
        invoke_model(
            FakeModelClient((TransientModelError(secret),)),
            _request("retry"),
            budget,
        )

    assert [item.kind for item in observer.items] == [
        ModelObservationKind.LOGICAL_STARTED,
        ModelObservationKind.PROVIDER_STARTED,
        ModelObservationKind.PROVIDER_FAILED,
        ModelObservationKind.LOGICAL_FAILED,
    ]
    assert observer.items[2].error_code == "transient_model_error"
    assert observer.items[3].error_code == "transient_model_error"
    assert secret not in repr(observer.items)
    assert (budget.logical_calls, budget.provider_attempts) == (1, 1)


def test_blocked_logical_call_emits_only_blocked_and_does_not_increment() -> None:
    observer = RecordingModelObserver()
    client = FakeModelClient((ModelResponse(text="must not run"),))
    budget = ModelCallBudget(
        max_logical_calls=1,
        logical_calls=1,
        observer=observer,
    )

    with pytest.raises(ModelBudgetExceeded):
        invoke_model(client, _request("blocked"), budget)

    assert [item.kind for item in observer.items] == [
        ModelObservationKind.LOGICAL_BLOCKED
    ]
    assert observer.items[0].error_code == "logical_model_call_limit"
    assert budget.logical_calls == 1
    assert budget.provider_attempts == 0
    assert client.requests == ()


class FailingModelObserver:
    def observe_model(self, observation: ModelObservation) -> None:
        raise RuntimeError("observer unavailable")


def test_observer_failure_before_logical_claim_prevents_operation() -> None:
    client = FakeModelClient((ModelResponse(text="must not run"),))
    budget = ModelCallBudget(observer=FailingModelObserver())

    with pytest.raises(RuntimeError, match="observer unavailable"):
        invoke_model(client, _request("blocked by observer"), budget)

    assert budget.logical_calls == 0
    assert budget.provider_attempts == 0
    assert client.requests == ()
    assert "FailingModelObserver" not in repr(budget)


@pytest.mark.parametrize(
    ("logical_calls", "provider_attempts", "reason"),
    [
        (1, 0, ModelBudgetReason.LOGICAL_CALL_LIMIT),
        (0, 1, ModelBudgetReason.PROVIDER_ATTEMPT_LIMIT),
    ],
)
def test_budget_rejects_before_call_without_exceeding_limit(
    logical_calls: int,
    provider_attempts: int,
    reason: ModelBudgetReason,
) -> None:
    client = FakeModelClient((ModelResponse(text="must not run"),))
    budget = ModelCallBudget(
        max_logical_calls=1,
        max_provider_attempts=1,
        logical_calls=logical_calls,
        provider_attempts=provider_attempts,
    )

    with pytest.raises(ModelBudgetExceeded) as caught:
        invoke_model(client, _request("blocked"), budget)

    assert caught.value.reason is reason
    assert budget.logical_calls <= budget.max_logical_calls
    assert budget.provider_attempts <= budget.max_provider_attempts
    assert client.requests == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"max_logical_calls": 0},
        {"max_provider_attempts": -1},
        {"max_logical_calls": True},
        {"max_provider_attempts": 1.5},
        {"logical_calls": -1},
        {"provider_attempts": True},
        {"logical_calls": 2, "max_logical_calls": 1},
        {"provider_attempts": 2, "max_provider_attempts": 1},
    ],
)
def test_model_budget_rejects_invalid_counts_and_limits(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        ModelCallBudget(**changes)  # type: ignore[arg-type]


def _layered_budget() -> ModelCallBudget:
    return ModelCallBudget(
        max_logical_calls=28,
        max_provider_attempts=48,
        max_main_logical_calls=24,
        max_summary_logical_calls=4,
        max_summary_provider_attempts=8,
    )


def test_main_and_summary_logical_limits_are_independent() -> None:
    budget = _layered_budget()
    request = _request("layered logical counts")

    for _ in range(24):
        index = budget.begin_logical_call(ModelCallPurpose.MAIN, request)
        budget.finish_logical_call(
            ModelCallPurpose.MAIN,
            index,
            response=ModelResponse(text="ok"),
            error_code=None,
        )
    for _ in range(4):
        index = budget.begin_logical_call(ModelCallPurpose.SUMMARY, request)
        budget.finish_logical_call(
            ModelCallPurpose.SUMMARY,
            index,
            response=ModelResponse(text="ok"),
            error_code=None,
        )

    assert budget.logical_calls == 28
    assert budget.main_logical_calls == 24
    assert budget.summary_logical_calls == 4
    with pytest.raises(ModelBudgetExceeded) as main_error:
        budget.begin_logical_call(ModelCallPurpose.MAIN, request)
    assert main_error.value.reason is ModelBudgetReason.MAIN_LOGICAL_CALL_LIMIT
    assert budget.logical_calls == 28
    assert budget.main_logical_calls == 24


def test_summary_provider_subcap_never_exceeds_global_cap() -> None:
    budget = _layered_budget()
    budget.begin_logical_call(
        ModelCallPurpose.SUMMARY,
        _request("summary provider attempts"),
    )

    for expected in range(1, 9):
        assert budget.begin_provider_attempt(ModelCallPurpose.SUMMARY) == expected

    with pytest.raises(ModelBudgetExceeded) as caught:
        budget.begin_provider_attempt(ModelCallPurpose.SUMMARY)
    assert caught.value.reason is ModelBudgetReason.SUMMARY_PROVIDER_ATTEMPT_LIMIT
    assert budget.provider_attempts == 8
    assert budget.summary_provider_attempts == 8


def test_legacy_budget_without_purpose_caps_keeps_task9_semantics() -> None:
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=3)
    budget.begin_logical_call(
        ModelCallPurpose.MAIN,
        _request("legacy provider attempts"),
    )

    assert [
        budget.begin_provider_attempt(ModelCallPurpose.MAIN) for _ in range(3)
    ] == [1, 2, 3]
    with pytest.raises(ModelBudgetExceeded) as caught:
        budget.begin_provider_attempt(ModelCallPurpose.MAIN)
    assert caught.value.reason is ModelBudgetReason.PROVIDER_ATTEMPT_LIMIT

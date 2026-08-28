import json
from pathlib import Path

import pytest

from coding_agent.context import (
    ContextLimits,
    ContextManager,
    ContextPreparationError,
    SummarySource,
    _partition_complete_turns,
)
from coding_agent.messages import (
    AssistantMessage,
    ModelResponse,
    ToolCall,
    ToolResult,
    UserMessage,
)
from coding_agent.model import (
    FakeModelClient,
    FatalModelError,
    ModelBudgetExceeded,
    ModelCallBudget,
    ModelClient,
    TransientModelError,
)
from coding_agent.safety import CommandSource
from coding_agent.state import AgentState, TerminationReason, VerificationStatus
from coding_agent.verification import VerificationResult


SUMMARY_PREFIX = "coding-agent context summary\n"


def make_state_with_n_complete_turns(
    tmp_path: Path,
    count: int,
) -> AgentState:
    state = AgentState.start("task", tmp_path, 0.0)
    state.messages += tuple(
        AssistantMessage(content=f"turn-{index:02d}") for index in range(count)
    )
    return state


def make_compressible_state(tmp_path: Path) -> AgentState:
    state = AgentState.start("task", tmp_path, 0.0)
    state.messages += (AssistantMessage(content="x" * 5_000),)
    state.messages += tuple(
        AssistantMessage(content=f"turn-{index:02d}") for index in range(1, 9)
    )
    return state


def make_single_huge_recent_turn(tmp_path: Path) -> AgentState:
    state = AgentState.start("task", tmp_path, 0.0)
    state.messages += (AssistantMessage(content="x" * 5_000),)
    return state


def valid_summary_json() -> str:
    return json.dumps(
        {
            "goal": "model value must be overridden",
            "established_facts": ["fact"],
            "files_examined": ["src/a.py"],
            "changes_made": [],
            "commands_and_results": ["pytest failed"],
            "unresolved_errors": ["one failure"],
            "open_issues": ["model issue"],
            "verification_state": {"status": "model supplied"},
            "avoid_repeating": ["same read"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def valid_summary_response() -> ModelResponse:
    return ModelResponse(text=valid_summary_json())


def triggered_manager(client: ModelClient) -> ContextManager:
    return ContextManager(
        model_client=client,
        limits=ContextLimits(
            max_serialized_chars=2_000,
            max_history_items=24,
        ),
    )


def tiny_manager(client: ModelClient) -> ContextManager:
    return ContextManager(
        model_client=client,
        limits=ContextLimits(
            max_serialized_chars=100,
            max_history_items=24,
        ),
    )


def append_tool_turn(
    state: AgentState,
    *,
    turn_number: int,
    call_count: int,
) -> tuple[ToolCall, ...]:
    calls = tuple(
        ToolCall(
            call_id=f"call-{turn_number}-{index}",
            name="read_file",
            arguments={"path": f"file-{index}.py"},
        )
        for index in range(call_count)
    )
    state.messages += (AssistantMessage(tool_calls=calls),)
    state.messages += tuple(
        ToolResult(
            call_id=call.call_id,
            tool_name=call.name,
            status="ok",
            output=f"result-{index}",
        )
        for index, call in enumerate(calls)
    )
    return calls


def manager(client: FakeModelClient, **changes: int) -> ContextManager:
    return ContextManager(
        model_client=client,
        limits=ContextLimits(**changes),
    )


def test_context_at_exact_threshold_is_not_compressed(tmp_path: Path) -> None:
    marker = object()
    state = AgentState.start("task", tmp_path, 0.0)
    state.continuation_items = (marker,)
    measured = ContextManager.measure(state.messages)
    context = manager(
        FakeModelClient(()),
        max_serialized_chars=measured.serialized_chars,
        max_history_items=1,
    ).prepare(state, ModelCallBudget())
    assert not context.compressed
    assert context.messages is state.messages
    assert context.continuation_items is state.continuation_items


def test_one_character_past_threshold_requests_compression(
    tmp_path: Path,
) -> None:
    state = make_compressible_state(tmp_path)
    measured = ContextManager.measure(state.messages)
    client = FakeModelClient((valid_summary_response(),))
    context = manager(
        client,
        max_serialized_chars=measured.serialized_chars - 1,
        max_history_items=len(state.messages),
    ).prepare(state, ModelCallBudget())
    assert context.compressed


def test_one_item_past_threshold_requests_compression(tmp_path: Path) -> None:
    state = make_state_with_n_complete_turns(tmp_path, 25)
    measured = ContextManager.measure(state.messages)
    client = FakeModelClient((valid_summary_response(),))
    context = manager(
        client,
        max_serialized_chars=measured.serialized_chars,
        max_history_items=len(state.messages) - 1,
    ).prepare(state, ModelCallBudget())
    assert context.compressed


def test_partition_ten_text_only_turns(tmp_path: Path) -> None:
    state = make_state_with_n_complete_turns(tmp_path, 10)
    initial, prefix, turns = _partition_complete_turns(state.messages)
    assert initial == UserMessage("task")
    assert prefix == ()
    assert len(turns) == 10
    assert all(len(turn) == 1 for turn in turns)
    assert all(isinstance(turn[0], AssistantMessage) for turn in turns)


def test_partition_keeps_ordered_multi_call_turn_together(tmp_path: Path) -> None:
    state = AgentState.start("task", tmp_path, 0.0)
    calls = append_tool_turn(state, turn_number=1, call_count=2)
    _, _, turns = _partition_complete_turns(state.messages)
    assert len(turns) == 1
    assert len(turns[0]) == 3
    assert turns[0][0] == AssistantMessage(tool_calls=calls)
    assert tuple(result.call_id for result in turns[0][1:]) == tuple(
        call.call_id for call in calls
    )


@pytest.mark.parametrize("case", ["orphan", "missing", "reordered", "duplicate"])
def test_partition_rejects_orphan_or_invalid_tool_results(
    tmp_path: Path,
    case: str,
) -> None:
    state = AgentState.start("task", tmp_path, 0.0)
    first = ToolCall("call-1", "read_file", {"path": "a.py"})
    second = ToolCall("call-2", "read_file", {"path": "b.py"})
    first_result = ToolResult("call-1", "read_file", "ok", output="a")
    second_result = ToolResult("call-2", "read_file", "ok", output="b")
    if case == "orphan":
        state.messages += (first_result,)
    elif case == "missing":
        state.messages += (AssistantMessage(tool_calls=(first, second)), first_result)
    elif case == "reordered":
        state.messages += (
            AssistantMessage(tool_calls=(first, second)),
            second_result,
            first_result,
        )
    else:
        state.messages += (
            AssistantMessage(tool_calls=(first, second)),
            first_result,
            first_result,
        )

    with pytest.raises(ContextPreparationError) as caught:
        _partition_complete_turns(state.messages)
    assert caught.value.reason is TerminationReason.INTERNAL_INVARIANT


def test_partition_returns_initial_user_message_unchanged(tmp_path: Path) -> None:
    state = AgentState.start("task with bytes: \u4f60\u597d", tmp_path, 0.0)
    initial, _, _ = _partition_complete_turns(state.messages)
    assert initial is state.messages[0]


def test_partition_treats_prior_summary_as_prefix(tmp_path: Path) -> None:
    state = AgentState.start("task", tmp_path, 0.0)
    prior = UserMessage(SUMMARY_PREFIX + valid_summary_json())
    state.messages += (prior, AssistantMessage(content="latest"))
    _, prefix, turns = _partition_complete_turns(state.messages)
    assert prefix == (prior,)
    assert len(turns) == 1


def test_partition_rejects_duplicate_summary_marker(tmp_path: Path) -> None:
    state = AgentState.start("task", tmp_path, 0.0)
    prior = UserMessage(SUMMARY_PREFIX + valid_summary_json())
    state.messages += (prior, prior, AssistantMessage(content="latest"))
    with pytest.raises(ContextPreparationError) as caught:
        _partition_complete_turns(state.messages)
    assert caught.value.reason is TerminationReason.INTERNAL_INVARIANT


def _parsed_summary(prepared_messages: tuple[object, ...]) -> dict[str, object]:
    summary_message = prepared_messages[1]
    assert isinstance(summary_message, UserMessage)
    assert summary_message.content.startswith(SUMMARY_PREFIX)
    parsed = json.loads(summary_message.content.removeprefix(SUMMARY_PREFIX))
    assert isinstance(parsed, dict)
    return parsed


def test_model_summary_request_and_local_invariants(tmp_path: Path) -> None:
    state = make_compressible_state(tmp_path)
    state.modified_paths = ("src/local.py",)
    state.mutation_index = 2
    client = FakeModelClient((valid_summary_response(),))
    budget = ModelCallBudget()

    prepared = triggered_manager(client).prepare(state, budget)

    assert len(client.requests) == 1
    summary_request = client.requests[0]
    assert summary_request.tool_schemas == ()
    assert summary_request.continuation_items == ()
    assert summary_request.max_output_tokens == 4096
    assert prepared.messages[0] == UserMessage(state.task)
    parsed = _parsed_summary(prepared.messages)
    assert parsed["goal"] == state.task
    assert parsed["changes_made"] == list(state.modified_paths)
    assert parsed["verification_state"] == {
        "status": state.verification_status.value,
        "mutation_index": state.mutation_index,
        "validation_index": None,
        "command": None,
        "source": None,
        "exit_code": None,
    }
    assert budget.logical_calls == 1
    assert budget.provider_attempts == 1


def test_compression_preserves_minimal_fresh_verification_facts(
    tmp_path: Path,
) -> None:
    state = make_compressible_state(tmp_path)
    state.mutation_index = 3
    state.verification_status = VerificationStatus.PASSED
    state.last_verification = VerificationResult(
        status=VerificationStatus.PASSED,
        validation_index=3,
        command="python -m pytest -q",
        source=CommandSource.USER_VERIFY,
        exit_code=0,
        stdout="secret-stdout",
        stderr="secret-stderr",
        timed_out=False,
        truncated=False,
        duration_ms=15,
        error=None,
    )
    continuation_sentinel = "encrypted-reasoning-sentinel"
    state.continuation_items = (continuation_sentinel,)

    prepared = triggered_manager(
        FakeModelClient((valid_summary_response(),))
    ).prepare(state, ModelCallBudget())
    parsed = _parsed_summary(prepared.messages)

    assert parsed["verification_state"] == {
        "status": "passed",
        "mutation_index": 3,
        "validation_index": 3,
        "command": "python -m pytest -q",
        "source": "user_verify",
        "exit_code": 0,
    }
    rendered = json.dumps(parsed, sort_keys=True)
    assert "secret-stdout" not in rendered
    assert "secret-stderr" not in rendered
    assert continuation_sentinel not in rendered
    assert continuation_sentinel not in repr(prepared)


def test_compression_marks_preserved_verification_as_stale(
    tmp_path: Path,
) -> None:
    state = make_compressible_state(tmp_path)
    state.mutation_index = 4
    state.verification_status = VerificationStatus.STALE
    state.last_verification = VerificationResult(
        status=VerificationStatus.PASSED,
        validation_index=3,
        command="python -m pytest -q",
        source=CommandSource.MODEL,
        exit_code=0,
        stdout="old output",
        stderr="",
        timed_out=False,
        truncated=False,
        duration_ms=9,
        error=None,
    )

    prepared = triggered_manager(
        FakeModelClient((valid_summary_response(),))
    ).prepare(state, ModelCallBudget())

    assert _parsed_summary(prepared.messages)["verification_state"] == {
        "status": "stale",
        "mutation_index": 4,
        "validation_index": 3,
        "command": "python -m pytest -q",
        "source": "model",
        "exit_code": 0,
    }


def test_model_summary_is_deterministic_for_equivalent_state(
    tmp_path: Path,
) -> None:
    first_state = make_compressible_state(tmp_path)
    second_state = make_compressible_state(tmp_path)
    first = triggered_manager(
        FakeModelClient((valid_summary_response(),))
    ).prepare(first_state, ModelCallBudget())
    second = triggered_manager(
        FakeModelClient((valid_summary_response(),))
    ).prepare(second_state, ModelCallBudget())
    assert first.messages[1] == second.messages[1]
    assert first.messages == second.messages


def test_model_summary_retains_exactly_newest_eight_turns(tmp_path: Path) -> None:
    state = make_compressible_state(tmp_path)
    prepared = triggered_manager(
        FakeModelClient((valid_summary_response(),))
    ).prepare(state, ModelCallBudget())
    assert len(prepared.messages) == 10
    assert prepared.messages[2:] == state.messages[-8:]
    assert state.messages[1] not in prepared.messages


def _invalid_summary_outcome(case: str) -> ModelResponse | TransientModelError:
    valid = json.loads(valid_summary_json())
    if case == "transient":
        return TransientModelError("temporary provider failure")
    if case == "invalid_json":
        return ModelResponse(text="not-json")
    if case == "missing_field":
        valid.pop("avoid_repeating")
    elif case == "extra_field":
        valid["extra"] = []
    elif case == "wrong_list_type":
        valid["files_examined"] = "src/a.py"
    elif case == "tool_call":
        return ModelResponse(
            text=valid_summary_json(),
            tool_calls=(ToolCall("summary-call", "read_file", {"path": "a.py"}),),
        )
    elif case == "oversized":
        valid["established_facts"] = ["x" * 13_000]
    return ModelResponse(
        text=json.dumps(
            valid,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


@pytest.mark.parametrize(
    "case",
    [
        "transient",
        "invalid_json",
        "missing_field",
        "extra_field",
        "wrong_list_type",
        "tool_call",
        "oversized",
    ],
)
def test_summary_failure_uses_deterministic_fallback(
    tmp_path: Path,
    case: str,
) -> None:
    first_state = make_compressible_state(tmp_path)
    second_state = make_compressible_state(tmp_path)
    first = triggered_manager(
        FakeModelClient((_invalid_summary_outcome(case),))
    ).prepare(first_state, ModelCallBudget())
    second = triggered_manager(
        FakeModelClient((_invalid_summary_outcome(case),))
    ).prepare(second_state, ModelCallBudget())
    first_payload = _parsed_summary(first.messages)
    second_payload = _parsed_summary(second.messages)
    assert first.summary_source is SummarySource.FALLBACK
    assert first.summary_model_failed is True
    assert set(first_payload) == {
        "goal",
        "established_facts",
        "files_examined",
        "changes_made",
        "commands_and_results",
        "unresolved_errors",
        "open_issues",
        "verification_state",
        "avoid_repeating",
    }
    assert first_payload == second_payload
    assert first.messages == second.messages


def test_fatal_summary_error_propagates(tmp_path: Path) -> None:
    error = FatalModelError("fatal summary configuration")
    state = make_compressible_state(tmp_path)
    with pytest.raises(FatalModelError) as caught:
        triggered_manager(FakeModelClient((error,))).prepare(
            state,
            ModelCallBudget(),
        )
    assert caught.value is error


def test_exhausted_summary_budget_propagates(tmp_path: Path) -> None:
    state = make_compressible_state(tmp_path)
    budget = ModelCallBudget(max_logical_calls=1, logical_calls=1)
    with pytest.raises(ModelBudgetExceeded):
        triggered_manager(FakeModelClient((valid_summary_response(),))).prepare(
            state,
            budget,
        )


def test_compression_discards_active_and_summary_continuation(
    tmp_path: Path,
) -> None:
    old = object()
    summary_only = object()
    state = make_compressible_state(tmp_path)
    state.continuation_items = (old,)
    client = FakeModelClient(
        (
            ModelResponse(
                text=valid_summary_json(),
                continuation_items=(summary_only,),
            ),
        )
    )
    prepared = triggered_manager(client).prepare(state, ModelCallBudget())
    assert prepared.continuation_items == ()
    assert repr(old) not in repr(prepared)
    assert repr(summary_only) not in repr(prepared)


def test_uncompressible_context_fails_stably(tmp_path: Path) -> None:
    state = make_single_huge_recent_turn(tmp_path)
    with pytest.raises(ContextPreparationError) as caught:
        tiny_manager(FakeModelClient(())).prepare(state, ModelCallBudget())
    assert caught.value.reason is TerminationReason.CONTEXT_BUDGET_EXHAUSTED


def test_still_oversized_context_fails_stably(tmp_path: Path) -> None:
    state = make_compressible_state(tmp_path)
    with pytest.raises(ContextPreparationError) as caught:
        tiny_manager(FakeModelClient((valid_summary_response(),))).prepare(
            state,
            ModelCallBudget(),
        )
    assert caught.value.reason is TerminationReason.CONTEXT_BUDGET_EXHAUSTED


def test_recompression_fallback_preserves_prior_summary_facts(
    tmp_path: Path,
) -> None:
    state = make_compressible_state(tmp_path)
    first = triggered_manager(
        FakeModelClient((valid_summary_response(),))
    ).prepare(state, ModelCallBudget())
    state.messages = first.messages + (AssistantMessage(content="newest"),)
    measured = ContextManager.measure(state.messages)

    second = manager(
        FakeModelClient((TransientModelError("temporary"),)),
        max_serialized_chars=measured.serialized_chars,
        max_history_items=len(state.messages) - 1,
    ).prepare(state, ModelCallBudget())

    payload = _parsed_summary(second.messages)
    assert "fact" in payload["established_facts"]

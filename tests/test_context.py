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
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResult,
    UserMessage,
)
from coding_agent.model import (
    FakeModelClient,
    FatalModelError,
    ModelBudgetExceeded,
    ModelBudgetReason,
    ModelCallBudget,
    ModelCallPurpose,
    ModelClient,
    ModelError,
    ModelObservation,
    TransientModelError,
)
from coding_agent.safety import CommandSource
from coding_agent.state import (
    AgentState,
    SummaryFallbackReason,
    TerminationReason,
    VerificationStatus,
)
from coding_agent.verification import VerificationResult


SUMMARY_PREFIX = "coding-agent context summary\n"


class RecordingModelObserver:
    def __init__(self) -> None:
        self.items: list[ModelObservation] = []

    def observe_model(self, observation: ModelObservation) -> None:
        self.items.append(observation)


class InterruptingSummaryClient:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def complete(self, request: object) -> ModelResponse:
        raise self.error


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


def make_high_water_state(tmp_path: Path) -> AgentState:
    state = AgentState.start("task", tmp_path, 0.0)
    state.messages += tuple(
        AssistantMessage(content=(f"turn-{index:02d}:" + "x" * 2_600))
        for index in range(19)
    )
    assert len(state.messages) == 20
    assert ContextManager(model_client=FakeModelClient(())).measure(
        state.messages
    ).serialized_chars >= 48_000
    return state


def make_one_oversized_completed_tool_turn(tmp_path: Path) -> AgentState:
    state = AgentState.start("task", tmp_path, 0.0)
    call = ToolCall(
        call_id="oversized-call",
        name="read_file",
        arguments={"path": "large.txt", "start_line": 1, "end_line": None},
    )
    state.messages += (
        AssistantMessage(tool_calls=(call,)),
        ToolResult(
            call_id=call.call_id,
            tool_name=call.name,
            status="ok",
            output="x" * 49_000,
        ),
    )
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


def test_single_json_fence_is_accepted_as_model_summary(tmp_path: Path) -> None:
    state = make_compressible_state(tmp_path)
    response = ModelResponse(text=f"```json\n{valid_summary_json()}\n```")
    prepared = triggered_manager(FakeModelClient((response,))).prepare(
        state,
        ModelCallBudget(),
    )
    assert prepared.summary_source is SummarySource.MODEL
    assert prepared.summary_model_failed is False
    assert state.summary_fallback_latched is False


@pytest.mark.parametrize(
    "text",
    [
        "prefix\n```json\n{}\n```",
        "```json\n{}\n```\nsuffix",
        "```json\n{}\n```\n```json\n{}\n```",
        "```JSON\n{}\n```",
    ],
)
def test_noncanonical_fenced_summary_latches_fallback(
    tmp_path: Path,
    text: str,
) -> None:
    state = make_compressible_state(tmp_path)
    prepared = triggered_manager(
        FakeModelClient((ModelResponse(text=text),))
    ).prepare(state, ModelCallBudget())
    assert prepared.summary_source is SummarySource.FALLBACK
    assert state.summary_fallback_reason is SummaryFallbackReason.INVALID_SUMMARY


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


def make_eight_multi_tool_turns(
    tmp_path: Path,
    calls_per_turn: int,
) -> AgentState:
    state = AgentState.start("task", tmp_path, 0.0)
    for turn_number in range(8):
        append_tool_turn(
            state,
            turn_number=turn_number,
            call_count=calls_per_turn,
        )
    return state


def manager(client: FakeModelClient, **changes: int) -> ContextManager:
    return ContextManager(
        model_client=client,
        limits=ContextLimits(**changes),
    )


def test_context_triggers_at_high_water_and_compacts_to_low_water(
    tmp_path: Path,
) -> None:
    state = make_high_water_state(tmp_path)
    prepared = ContextManager(
        model_client=FakeModelClient((valid_summary_response(),))
    ).prepare(state, ModelCallBudget())

    assert prepared.compressed is True
    assert prepared.size.serialized_chars <= 33_000
    assert prepared.size.history_items <= 12
    assert prepared.messages[0] == state.messages[0]
    ModelRequest(messages=prepared.messages)


def test_compaction_may_summarize_last_completed_turn_to_reach_target(
    tmp_path: Path,
) -> None:
    state = make_one_oversized_completed_tool_turn(tmp_path)
    prepared = ContextManager(
        model_client=FakeModelClient((valid_summary_response(),))
    ).prepare(state, ModelCallBudget())

    assert prepared.size.serialized_chars <= 33_000
    assert prepared.size.history_items <= 12
    assert not any(isinstance(item, ToolResult) for item in prepared.messages)
    ModelRequest(messages=prepared.messages)


def test_compression_trigger_equality_for_characters() -> None:
    manager = ContextManager(model_client=FakeModelClient(()))
    base = manager.measure((UserMessage("x"),)).serialized_chars
    below = (UserMessage("x" * (48_000 - base)),)
    exact = (UserMessage("x" * (48_001 - base)),)

    assert manager.measure(below).serialized_chars == 47_999
    assert manager.measure(exact).serialized_chars == 48_000
    assert manager.requires_compression(below) is False
    assert manager.requires_compression(exact) is True


def test_compression_trigger_equality_for_items(tmp_path: Path) -> None:
    below = make_state_with_n_complete_turns(tmp_path, 18)
    exact = make_state_with_n_complete_turns(tmp_path, 19)
    manager = ContextManager(model_client=FakeModelClient(()))

    assert len(below.messages) == 19
    assert len(exact.messages) == 20
    assert manager.requires_compression(below.messages) is False
    assert manager.requires_compression(exact.messages) is True


def test_first_invalid_summary_latches_local_fallback_for_same_run(
    tmp_path: Path,
) -> None:
    model = FakeModelClient((ModelResponse(text="not-json"),))
    state = make_compressible_state(tmp_path)
    context = triggered_manager(model)

    first = context.prepare(state, ModelCallBudget())

    assert first.summary_source is SummarySource.FALLBACK
    assert state.summary_fallback_latched is True
    assert state.summary_fallback_reason is SummaryFallbackReason.INVALID_SUMMARY
    state.messages = first.messages + (
        AssistantMessage(content="new complete turn " + "y" * 5_000),
    )
    second = context.prepare(state, ModelCallBudget())
    assert second.summary_source is SummarySource.FALLBACK
    assert len(model.requests) == 1


def test_new_run_retries_model_summary_after_prior_run_latched(
    tmp_path: Path,
) -> None:
    model = FakeModelClient(
        (
            ModelResponse(text="invalid"),
            valid_summary_response(),
        )
    )
    context = triggered_manager(model)
    first_state = make_compressible_state(tmp_path)
    second_state = make_compressible_state(tmp_path)

    context.prepare(first_state, ModelCallBudget())
    prepared = context.prepare(second_state, ModelCallBudget())

    assert first_state.summary_fallback_latched is True
    assert second_state.summary_fallback_latched is False
    assert prepared.summary_source is SummarySource.MODEL
    assert len(model.requests) == 2


def test_fallback_summary_never_contains_host_workspace_path(
    tmp_path: Path,
) -> None:
    state = make_compressible_state(tmp_path)
    prepared = triggered_manager(
        FakeModelClient((ModelError("ordinary summary failure"),))
    ).prepare(state, ModelCallBudget())

    rendered = prepared.messages[1].content
    assert str(tmp_path) not in rendered
    assert "workspace: configured root" in rendered


def test_summary_specific_budget_exhaustion_latches_fallback(
    tmp_path: Path,
) -> None:
    state = make_compressible_state(tmp_path)
    budget = ModelCallBudget(
        max_logical_calls=5,
        max_provider_attempts=5,
        max_summary_logical_calls=1,
        logical_calls=1,
        summary_logical_calls=1,
    )

    prepared = triggered_manager(FakeModelClient(())).prepare(state, budget)

    assert prepared.summary_source is SummarySource.FALLBACK
    assert state.summary_fallback_latched is True
    assert state.summary_fallback_reason is SummaryFallbackReason.SUMMARY_BUDGET


@pytest.mark.parametrize(
    "scripted",
    [
        FatalModelError("fatal"),
        ModelBudgetExceeded(ModelBudgetReason.PROVIDER_ATTEMPT_LIMIT),
    ],
)
def test_fatal_and_global_budget_errors_are_not_latched(
    tmp_path: Path,
    scripted: ModelError,
) -> None:
    state = make_compressible_state(tmp_path)

    with pytest.raises(type(scripted)):
        triggered_manager(FakeModelClient((scripted,))).prepare(
            state,
            ModelCallBudget(),
        )

    assert state.summary_fallback_latched is False
    assert state.summary_fallback_reason is None


@pytest.mark.parametrize("scripted", [KeyboardInterrupt(), SystemExit(7)])
def test_summary_base_exceptions_are_not_latched(
    tmp_path: Path,
    scripted: BaseException,
) -> None:
    state = make_compressible_state(tmp_path)

    with pytest.raises(type(scripted)):
        triggered_manager(InterruptingSummaryClient(scripted)).prepare(
            state,
            ModelCallBudget(),
        )

    assert state.summary_fallback_latched is False
    assert state.summary_fallback_reason is None


def test_item_limit_compresses_even_with_only_eight_complete_turns(
    tmp_path: Path,
) -> None:
    state = make_eight_multi_tool_turns(tmp_path, calls_per_turn=2)
    assert len(state.messages) == 25
    client = FakeModelClient((valid_summary_response(),))
    prepared = manager(
        client,
        max_serialized_chars=1_000_000,
        max_history_items=24,
        recent_turns=8,
    ).prepare(state, ModelCallBudget())
    assert prepared.compressed is True
    assert prepared.summary_source is SummarySource.FALLBACK
    assert len(client.requests) == 1
    assert prepared.size.history_items <= 12
    assert prepared.messages[2:] == state.messages[16:]


def test_still_oversized_first_candidate_expands_with_local_fallback(
    tmp_path: Path,
) -> None:
    state = make_eight_multi_tool_turns(tmp_path, calls_per_turn=3)
    client = FakeModelClient((valid_summary_response(),))
    prepared = manager(
        client,
        max_serialized_chars=1_000_000,
        max_history_items=24,
        recent_turns=8,
    ).prepare(state, ModelCallBudget())
    assert len(client.requests) == 1
    assert prepared.compressed is True
    assert prepared.summary_source is SummarySource.FALLBACK
    assert prepared.summary_model_failed is False
    assert prepared.size.history_items <= 12
    initial, summary, *retained = prepared.messages
    assert initial is state.messages[0]
    assert isinstance(summary, UserMessage)
    assert tuple(retained) == state.messages[25:]


def test_expanded_compression_preserves_every_retained_tool_pair(
    tmp_path: Path,
) -> None:
    state = make_eight_multi_tool_turns(tmp_path, calls_per_turn=3)
    prepared = manager(
        FakeModelClient((valid_summary_response(),)),
        max_serialized_chars=1_000_000,
        max_history_items=24,
        recent_turns=8,
    ).prepare(state, ModelCallBudget())
    _, _, turns = _partition_complete_turns(prepared.messages)
    assert len(turns) == 2
    for turn in turns:
        assistant = turn[0]
        assert isinstance(assistant, AssistantMessage)
        assert [result.call_id for result in turn[1:]] == [
            call.call_id for call in assistant.tool_calls
        ]


def test_context_below_trigger_is_not_compressed_and_preserves_continuation(
    tmp_path: Path,
) -> None:
    marker = object()
    state = AgentState.start("task", tmp_path, 0.0)
    state.continuation_items = (marker,)
    context = ContextManager(model_client=FakeModelClient(())).prepare(
        state,
        ModelCallBudget(),
    )
    assert not context.compressed
    assert context.messages is state.messages
    assert context.continuation_items is state.continuation_items


def test_requires_compression_and_prepare_use_the_same_high_water_boundary(
    tmp_path: Path,
) -> None:
    state = make_high_water_state(tmp_path)
    context = ContextManager(
        model_client=FakeModelClient((valid_summary_response(),))
    )

    assert context.requires_compression(state.messages) is True
    assert context.prepare(state, ModelCallBudget()).compressed is True


def test_one_character_past_threshold_requests_compression(
    tmp_path: Path,
) -> None:
    state = make_compressible_state(tmp_path)
    measured = ContextManager.measure(state.messages)
    client = FakeModelClient((valid_summary_response(),))
    context = manager(
        client,
        max_serialized_chars=measured.serialized_chars + 1_000,
        compression_trigger_chars=measured.serialized_chars,
        compression_target_chars=2_000,
    ).prepare(state, ModelCallBudget())
    assert context.compressed


def test_one_item_past_threshold_requests_compression(tmp_path: Path) -> None:
    state = make_state_with_n_complete_turns(tmp_path, 25)
    measured = ContextManager.measure(state.messages)
    client = FakeModelClient((valid_summary_response(),))
    context = manager(
        client,
        max_serialized_chars=measured.serialized_chars + 1_000,
        compression_trigger_chars=measured.serialized_chars + 500,
        compression_target_chars=measured.serialized_chars,
        max_history_items=len(state.messages) + 5,
        compression_trigger_items=len(state.messages),
        compression_target_items=12,
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


def _populate_exploration(
    state: AgentState,
    paths: list[str],
    *,
    output: str,
) -> None:
    ledger = state.progress.exploration
    for index, path in enumerate(paths):
        call = ToolCall(
            f"coverage-{index}",
            "read_file",
            {"path": path, "start_line": 1, "end_line": None},
        )
        ledger.begin_turn()
        ledger.observe(
            call,
            ToolResult(call.call_id, call.name, "ok", output=output),
            mutation_epoch=0,
        )
        ledger.finish_turn()


def _fallback_files(tmp_path: Path, paths: list[str]) -> list[str]:
    state = make_compressible_state(tmp_path)
    _populate_exploration(state, paths, output="safe fixture body")
    prepared = triggered_manager(
        FakeModelClient((ModelError("ordinary summary failure"),))
    ).prepare(state, ModelCallBudget())
    files = _parsed_summary(prepared.messages)["files_examined"]
    assert isinstance(files, list)
    return files


def test_fallback_keeps_first_seen_safe_targets_within_summary_cap(
    tmp_path: Path,
) -> None:
    state = make_compressible_state(tmp_path)
    _populate_exploration(
        state,
        [f"src/file_{index:02d}.py" for index in range(20)],
        output="BODY-MUST-NOT-ENTER-SUMMARY",
    )
    prepared = triggered_manager(
        FakeModelClient((ModelError("ordinary summary failure"),))
    ).prepare(state, ModelCallBudget())
    parsed = _parsed_summary(prepared.messages)

    files = parsed["files_examined"]
    assert isinstance(files, list)
    assert files[0].startswith("read_file:src/file_00.py")
    assert len(files) > 8
    assert len(json.dumps(parsed, ensure_ascii=False)) <= 12_000
    assert "BODY-MUST-NOT-ENTER-SUMMARY" not in json.dumps(parsed)


def test_fallback_target_order_is_deterministic_and_deduplicated(
    tmp_path: Path,
) -> None:
    first = _fallback_files(tmp_path, ["b.py", "a.py", "b.py"])
    second = _fallback_files(tmp_path, ["b.py", "a.py", "b.py"])
    assert first == second
    assert first == ["read_file:b.py:1-null", "read_file:a.py:1-null"]


def test_model_summary_request_and_local_invariants(tmp_path: Path) -> None:
    state = make_compressible_state(tmp_path)
    state.modified_paths = ("src/local.py",)
    state.mutation_index = 2
    client = FakeModelClient((valid_summary_response(),))
    observer = RecordingModelObserver()
    budget = ModelCallBudget(observer=observer)

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
    assert {item.purpose for item in observer.items} == {ModelCallPurpose.SUMMARY}


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


def test_nonfatal_model_error_summary_uses_deterministic_fallback(
    tmp_path: Path,
) -> None:
    state = make_compressible_state(tmp_path)

    prepared = triggered_manager(
        FakeModelClient((ModelError("provider response could not be parsed"),))
    ).prepare(state, ModelCallBudget())

    assert prepared.summary_source is SummarySource.FALLBACK
    assert prepared.summary_model_failed is True
    assert _parsed_summary(prepared.messages)["goal"] == state.task


def test_fatal_summary_error_propagates(tmp_path: Path) -> None:
    error = FatalModelError("fatal summary configuration")
    state = make_compressible_state(tmp_path)
    with pytest.raises(FatalModelError) as caught:
        triggered_manager(FakeModelClient((error,))).prepare(
            state,
            ModelCallBudget(),
        )
    assert caught.value is error


@pytest.mark.parametrize(
    "error",
    [KeyboardInterrupt(), SystemExit(9)],
    ids=["keyboard_interrupt", "system_exit"],
)
def test_summary_base_exception_propagates(
    tmp_path: Path,
    error: BaseException,
) -> None:
    state = make_compressible_state(tmp_path)

    with pytest.raises(type(error)) as caught:
        triggered_manager(InterruptingSummaryClient(error)).prepare(
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
        tiny_manager(FakeModelClient((valid_summary_response(),))).prepare(
            state,
            ModelCallBudget(),
        )
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

from __future__ import annotations

import pytest

from coding_agent.budget import BudgetProfile
from coding_agent.progress import (
    AgentPhase,
    ExplorationLedger,
    ExplorationNovelty,
    ExplorationTurnSummary,
    ProgressAction,
    ProgressDecision,
    ProgressLedger,
    ProgressLimits,
    ProgressStrength,
    render_execution_control,
)
from coding_agent.messages import ToolCall, ToolResult, ToolResultMetadata


def _read(path: str, call_id: str = "call") -> ToolCall:
    return ToolCall(
        call_id,
        "read_file",
        {"path": path, "start_line": 1, "end_line": None},
    )


def _read_result(call: ToolCall, output: str = "1: value") -> ToolResult:
    return ToolResult(call.call_id, call.name, "ok", output=output)


def _finish_read_turn(
    ledger: ProgressLedger,
    call: ToolCall,
    result: ToolResult,
    *,
    epoch: int = 0,
) -> ProgressStrength:
    ledger.begin_main_turn()
    ledger.observe_tool(
        call,
        result,
        mutation_advanced=False,
        verification_advanced=False,
        mutation_epoch=epoch,
    )
    return ledger.finish_main_turn()


def test_exploration_ledger_classifies_exact_duplicate_within_epoch() -> None:
    ledger = ExplorationLedger()
    call = _read("src\\app.py")
    result = _read_result(call)

    ledger.begin_turn()
    assert ledger.observe(call, result, mutation_epoch=0) is ExplorationNovelty.NOVEL
    first = ledger.finish_turn()
    ledger.begin_turn()
    assert (
        ledger.observe(call, result, mutation_epoch=0)
        is ExplorationNovelty.DUPLICATE
    )
    second = ledger.finish_turn()

    assert first == ExplorationTurnSummary(1, 1, 0, 0)
    assert second == ExplorationTurnSummary(1, 0, 1, 0)
    assert second.duplicate_only is True


def test_same_read_after_mutation_epoch_is_novel() -> None:
    ledger = ExplorationLedger()
    call = _read("src/app.py")
    result = _read_result(call)
    ledger.begin_turn()
    ledger.observe(call, result, mutation_epoch=0)
    ledger.finish_turn()
    ledger.begin_turn()
    novelty = ledger.observe(call, result, mutation_epoch=1)
    assert novelty is ExplorationNovelty.NOVEL


def test_failed_read_has_no_visible_target_and_is_not_duplicate_only() -> None:
    ledger = ExplorationLedger()
    call = _read(r"..\outside.txt")
    result = ToolResult(call.call_id, call.name, "rejected", error="path rejected")
    ledger.begin_turn()
    assert (
        ledger.observe(call, result, mutation_epoch=0) is ExplorationNovelty.FAILED
    )
    summary = ledger.finish_turn()
    assert summary == ExplorationTurnSummary(1, 0, 0, 1)
    assert summary.duplicate_only is False
    assert ledger.observations[0].target_label is None
    assert "outside.txt" not in repr(ledger)


def test_coverage_is_bounded_deterministic_and_content_free() -> None:
    ledger = ExplorationLedger()
    secret_body = "SECRET-MARKER-THAT-MUST-NOT-BE-RENDERED"
    for index in range(30):
        call = _read(f"src/module_{index:02d}.py", f"call-{index}")
        ledger.begin_turn()
        ledger.observe(call, _read_result(call, secret_body), mutation_epoch=0)
        ledger.finish_turn()
    ledger.mark_context_compacted()

    first = ledger.render_coverage(max_chars=512)
    second = ledger.render_coverage(max_chars=512)

    assert first == second
    assert first is not None and len(first) <= 512
    assert "Exploration coverage:" in first
    assert "unique targets: 30" in first
    assert "omitted targets:" in first
    assert secret_body not in first


def test_coverage_is_absent_before_compression_or_checkpoint() -> None:
    ledger = ExplorationLedger()
    assert ledger.render_coverage() is None


def test_checkpoint_counts_duplicate_read_response_as_one_batch() -> None:
    ledger = ProgressLedger()
    call = _read("src/app.py")
    result = _read_result(call)
    _finish_read_turn(ledger, call, result)
    ledger.activate_checkpoint()
    _finish_read_turn(ledger, call, result)
    assert ledger.post_checkpoint_read_batches == 1


def test_duplicate_only_turn_closes_reads_without_final_allowance() -> None:
    ledger = ProgressLedger()
    call = _read("src/app.py")
    result = _read_result(call)
    _finish_read_turn(ledger, call, result)
    _finish_read_turn(ledger, call, result)

    decision = ledger.decide(
        ProgressLimits.for_profile(BudgetProfile.DEEP),
        remaining_main_calls=30,
    )

    assert decision == ProgressDecision(
        ProgressAction.DECISION_REQUIRED,
        "duplicate_only_turn",
    )
    assert ledger.decision_required is True
    assert ledger.post_checkpoint_read_batches == 0


def test_first_failed_decision_gets_one_correction_then_stops() -> None:
    ledger = ProgressLedger(checkpoint_active=True, decision_required=True)
    limits = ProgressLimits.for_profile(BudgetProfile.DEEP)
    for expected in (1, 2):
        ledger.begin_main_turn()
        ledger.finish_main_turn()
        assert ledger.decision_attempts_without_progress == expected
        decision = ledger.decide(limits, remaining_main_calls=30)
        if expected == 1:
            assert decision.action is ProgressAction.CONTINUE
        else:
            assert decision == ProgressDecision(ProgressAction.STOP, "no_progress")


def test_progress_limits_are_exact_by_profile() -> None:
    assert ProgressLimits.for_profile(BudgetProfile.STANDARD) == ProgressLimits(
        4,
        12,
        2,
        2,
        4,
        1,
    )
    assert ProgressLimits.for_profile(BudgetProfile.DEEP) == ProgressLimits(
        6,
        24,
        3,
        3,
        4,
        2,
    )


def test_final_read_batch_limits_are_exact_by_profile() -> None:
    standard = ProgressLimits.for_profile(BudgetProfile.STANDARD)
    deep = ProgressLimits.for_profile(BudgetProfile.DEEP)

    assert standard.final_read_batch_limit == 1
    assert deep.final_read_batch_limit == 2


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5])
def test_final_read_batch_limit_requires_positive_integer(invalid: object) -> None:
    with pytest.raises(ValueError, match="final_read_batch_limit"):
        ProgressLimits(4, 12, 2, 2, 4, invalid)  # type: ignore[arg-type]


def _finish_checkpoint_read_batch(ledger: ProgressLedger, index: int) -> None:
    call = ToolCall(
        call_id=f"read-{index}",
        name="read_file",
        arguments={
            "path": f"src/file-{index}.py",
            "start_line": 1,
            "end_line": 10,
        },
    )
    result = ToolResult(
        call_id=call.call_id,
        tool_name=call.name,
        status="ok",
        output=f"1: value-{index}",
    )
    ledger.begin_main_turn()
    ledger.observe_tool(
        call,
        result,
        mutation_advanced=False,
        verification_advanced=False,
    )
    ledger.finish_main_turn()


@pytest.mark.parametrize(
    ("profile", "allowed_batches"),
    [
        (BudgetProfile.STANDARD, 1),
        (BudgetProfile.DEEP, 2),
    ],
)
def test_checkpoint_allows_exact_final_read_batches_then_requires_decision(
    profile: BudgetProfile,
    allowed_batches: int,
) -> None:
    limits = ProgressLimits.for_profile(profile)
    ledger = ProgressLedger()
    assert ledger.activate_checkpoint() is True

    for index in range(allowed_batches):
        assert ledger.decide(
            limits,
            remaining_main_calls=10,
        ) == ProgressDecision(ProgressAction.CONTINUE)
        _finish_checkpoint_read_batch(ledger, index)

    assert ledger.decide(
        limits,
        remaining_main_calls=10,
    ) == ProgressDecision(
        ProgressAction.DECISION_REQUIRED,
        "final_read_allowance_exhausted",
    )
    assert ledger.decision_required is True
    assert ledger.post_checkpoint_read_batches == allowed_batches
    assert ledger.decide(
        limits,
        remaining_main_calls=10,
    ) == ProgressDecision(ProgressAction.CONTINUE)


def test_strong_progress_clears_final_read_and_decision_latches() -> None:
    ledger = ProgressLedger(
        checkpoint_active=True,
        post_checkpoint_main_turns=1,
        post_checkpoint_read_batches=1,
        decision_required=True,
    )
    call = ToolCall("write", "write_file", {"path": "result.py", "content": "x"})
    result = ToolResult(
        call_id="write",
        tool_name="write_file",
        status="ok",
        output="created",
        metadata=ToolResultMetadata(changed_paths=("result.py",)),
    )
    ledger.begin_main_turn()
    ledger.observe_tool(
        call,
        result,
        mutation_advanced=True,
        verification_advanced=False,
    )
    ledger.finish_main_turn()

    assert ledger.checkpoint_active is False
    assert ledger.post_checkpoint_main_turns == 0
    assert ledger.post_checkpoint_read_batches == 0
    assert ledger.decision_required is False


def test_new_ledger_starts_in_discover_with_zero_counts() -> None:
    ledger = ProgressLedger()

    assert ledger.phase is AgentPhase.DISCOVER
    assert ledger.epoch == 0
    assert ledger.main_turns_since_strong_progress == 0
    assert ledger.read_tools_since_strong_progress == 0
    assert ledger.idle_main_turns == 0
    assert ledger.decide(
        ProgressLimits.for_profile(BudgetProfile.STANDARD),
        remaining_main_calls=24,
    ).action is ProgressAction.CONTINUE


def test_phase_transition_is_strong_and_starts_a_new_epoch() -> None:
    ledger = ProgressLedger()

    assert ledger.transition(AgentPhase.ACT) is True
    assert ledger.phase is AgentPhase.ACT
    assert ledger.epoch == 1
    assert ledger.checkpoint_active is False
    assert ledger.transition(AgentPhase.ACT) is False
    assert ledger.epoch == 1


def _read_call(call_id: str = "call-1") -> ToolCall:
    return ToolCall(
        call_id=call_id,
        name="read_file",
        arguments={"path": "src/a.py", "start_line": 1, "end_line": 20},
    )


def _result_for(
    call: ToolCall,
    *,
    status: str = "ok",
    output: str | None = "1: value",
    error: str | None = None,
    changed_paths: tuple[str, ...] = (),
) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.name,
        status=status,
        output=output,
        error=error,
        metadata=ToolResultMetadata(changed_paths=changed_paths),
    )


def test_novel_successful_inspection_is_weak_and_repeat_is_none() -> None:
    ledger = ProgressLedger()
    call = _read_call()
    ledger.begin_main_turn()

    assert ledger.observe_tool(
        call,
        _result_for(call),
        mutation_advanced=False,
        verification_advanced=False,
    ) is ProgressStrength.WEAK
    assert ledger.finish_main_turn() is ProgressStrength.WEAK

    repeated = _read_call("different-provider-id")
    ledger.begin_main_turn()
    assert ledger.observe_tool(
        repeated,
        _result_for(repeated),
        mutation_advanced=False,
        verification_advanced=False,
    ) is ProgressStrength.NONE
    assert ledger.finish_main_turn() is ProgressStrength.NONE


@pytest.mark.parametrize(
    ("mutation", "verification"),
    [(True, False), (False, True)],
)
def test_mutation_or_verification_is_strong(
    mutation: bool,
    verification: bool,
) -> None:
    ledger = ProgressLedger()
    call = _read_call()
    ledger.begin_main_turn()

    strength = ledger.observe_tool(
        call,
        _result_for(call),
        mutation_advanced=mutation,
        verification_advanced=verification,
    )

    assert strength is ProgressStrength.STRONG
    assert ledger.finish_main_turn() is ProgressStrength.STRONG
    assert ledger.epoch == 1
    assert ledger.main_turns_since_strong_progress == 0


def test_repeated_verification_does_not_clear_active_checkpoint() -> None:
    ledger = ProgressLedger(
        checkpoint_active=True,
        post_checkpoint_main_turns=1,
    )
    call = _read_call()
    ledger.begin_main_turn()

    strength = ledger.observe_tool(
        call,
        _result_for(call),
        mutation_advanced=False,
        verification_advanced=False,
    )
    ledger.finish_main_turn()

    assert strength is not ProgressStrength.STRONG
    assert ledger.checkpoint_active is True


@pytest.mark.parametrize(
    ("status", "output", "error"),
    [
        ("rejected", None, "security_rejected:path_denied"),
        ("error", None, "tool_execution_failed"),
        ("rejected", None, "agent_terminated:time_limit"),
    ],
)
def test_errors_rejections_and_synthetic_results_are_not_progress(
    status: str,
    output: str | None,
    error: str,
) -> None:
    ledger = ProgressLedger()
    call = _read_call()
    ledger.begin_main_turn()

    assert ledger.observe_tool(
        call,
        _result_for(call, status=status, output=output, error=error),
        mutation_advanced=False,
        verification_advanced=False,
    ) is ProgressStrength.NONE
    assert ledger.finish_main_turn() is ProgressStrength.NONE


@pytest.mark.parametrize(
    ("profile", "weak_turns", "weak_tools", "idle_turns"),
    [
        (BudgetProfile.STANDARD, 4, 0, 0),
        (BudgetProfile.STANDARD, 0, 12, 0),
        (BudgetProfile.STANDARD, 0, 0, 2),
        (BudgetProfile.DEEP, 6, 0, 0),
        (BudgetProfile.DEEP, 0, 24, 0),
        (BudgetProfile.DEEP, 0, 0, 3),
    ],
)
def test_threshold_equality_activates_one_checkpoint(
    profile: BudgetProfile,
    weak_turns: int,
    weak_tools: int,
    idle_turns: int,
) -> None:
    ledger = ProgressLedger(
        main_turns_since_strong_progress=weak_turns,
        read_tools_since_strong_progress=weak_tools,
        idle_main_turns=idle_turns,
    )

    decision = ledger.decide(
        ProgressLimits.for_profile(profile),
        remaining_main_calls=20,
    )

    assert decision == ProgressDecision(
        ProgressAction.CHECKPOINT,
        "exploration_limit",
    )
    assert ledger.checkpoint_active is True
    assert ledger.decide(
        ProgressLimits.for_profile(profile),
        remaining_main_calls=20,
    ) == ProgressDecision(ProgressAction.CONTINUE)


def test_four_remaining_main_calls_force_final_decision_checkpoint() -> None:
    ledger = ProgressLedger()

    decision = ledger.decide(
        ProgressLimits.for_profile(BudgetProfile.STANDARD),
        remaining_main_calls=4,
    )

    assert decision == ProgressDecision(
        ProgressAction.CHECKPOINT,
        "final_call_reserve",
    )
    assert ledger.checkpoint_active is True


@pytest.mark.parametrize(
    ("profile", "post_turns"),
    [(BudgetProfile.STANDARD, 2), (BudgetProfile.DEEP, 3)],
)
def test_checkpoint_post_limit_stops_with_no_progress(
    profile: BudgetProfile,
    post_turns: int,
) -> None:
    ledger = ProgressLedger(
        checkpoint_active=True,
        post_checkpoint_main_turns=post_turns,
    )

    decision = ledger.decide(
        ProgressLimits.for_profile(profile),
        remaining_main_calls=10,
    )

    assert decision == ProgressDecision(ProgressAction.STOP, "no_progress")


def test_strong_progress_clears_checkpoint_and_starts_new_epoch() -> None:
    ledger = ProgressLedger(
        checkpoint_active=True,
        post_checkpoint_main_turns=1,
    )
    call = _read_call()
    ledger.begin_main_turn()

    ledger.observe_tool(
        call,
        _result_for(call, changed_paths=("src/a.py",)),
        mutation_advanced=True,
        verification_advanced=False,
    )
    ledger.finish_main_turn()

    assert ledger.checkpoint_active is False
    assert ledger.post_checkpoint_main_turns == 0
    assert ledger.epoch == 1


def test_execution_control_is_exact_bounded_and_contains_no_paths_or_payloads(
    tmp_path,
) -> None:
    ledger = ProgressLedger(checkpoint_active=True)
    text = render_execution_control(
        ledger=ledger,
        decision=ProgressDecision(
            ProgressAction.CHECKPOINT,
            "exploration_limit",
        ),
        profile=BudgetProfile.STANDARD,
        remaining_main_calls=17,
        remaining_tool_calls=61,
        verification_reserve=1,
    )

    assert text == (
        "Execution control:\n"
        "- phase: discover\n"
        "- budget profile: standard\n"
        "- main calls remaining: 17\n"
        "- tool calls remaining: 61\n"
        "- verification reserve: 1\n"
        "- progress checkpoint: active\n"
        "- final read batches remaining: 1\n"
        "- required decision: answer, act, inspect only named essentials, or report blocker"
    )
    assert str(tmp_path) not in text
    assert len(text) <= 512


def test_decision_required_control_exposes_only_safe_action_contract() -> None:
    ledger = ProgressLedger(
        checkpoint_active=True,
        post_checkpoint_read_batches=1,
        decision_required=True,
    )
    text = render_execution_control(
        ledger=ledger,
        decision=ProgressDecision(
            ProgressAction.DECISION_REQUIRED,
            "final_read_allowance_exhausted",
        ),
        profile=BudgetProfile.STANDARD,
        remaining_main_calls=12,
        remaining_tool_calls=40,
        verification_reserve=0,
        has_unverified_changes=False,
    )

    assert "final read batches remaining: 0" in text
    assert "further read tools will be rejected" in text
    assert "required decision: modify, answer, or report blocker" in text
    assert "command" not in text.casefold()
    assert len(text) <= 768

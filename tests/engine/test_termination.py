from pathlib import Path

import pytest

from coding_agent.engine.budget import BudgetProfile
from coding_agent.engine.messages import ToolCall, ToolResult
from coding_agent.engine.state import AgentState, TerminationReason
from coding_agent.engine.termination import (
    NextOperation,
    TerminationLimits,
    TerminationPolicy,
    tool_call_fingerprint,
    tool_result_fingerprint,
)


def state_at(tmp_path: Path, *, started: float = 10.0) -> AgentState:
    return AgentState.start("task", tmp_path, started)


def test_default_limits_match_design() -> None:
    assert TerminationLimits() == TerminationLimits(
        max_main_logical_calls=24,
        max_summary_logical_calls=4,
        max_provider_attempts=48,
        max_summary_provider_attempts=8,
        max_tool_calls=80,
        max_runtime_seconds=1200.0,
        verification_tool_reserve=1,
        repetition_limit=3,
        consecutive_error_limit=3,
        safety_rejection_limit=3,
    )


def test_exact_model_limit_blocks_next_call_not_completed_call(
    tmp_path: Path,
) -> None:
    state = state_at(tmp_path)
    state.main_model_call_count = 24
    state.logical_model_call_count = 24
    decision = TerminationPolicy().check(
        state,
        11.0,
        next_operation=NextOperation.MODEL,
    )
    assert decision.should_stop
    assert decision.reason is TerminationReason.MAIN_MODEL_CALL_LIMIT


def test_exact_time_limit_blocks_next_operation(tmp_path: Path) -> None:
    state = state_at(tmp_path, started=100.0)
    decision = TerminationPolicy().check(
        state,
        1300.0,
        next_operation=NextOperation.TOOL,
    )
    assert decision.reason is TerminationReason.TIME_LIMIT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_main_logical_calls", True),
        ("max_main_logical_calls", 0),
        ("max_summary_logical_calls", 0),
        ("max_provider_attempts", -1),
        ("max_summary_provider_attempts", False),
        ("max_tool_calls", False),
        ("verification_tool_reserve", -1),
        ("repetition_limit", 0),
        ("consecutive_error_limit", -1),
        ("safety_rejection_limit", True),
        ("max_runtime_seconds", 0.0),
        ("max_runtime_seconds", float("inf")),
        ("max_runtime_seconds", float("nan")),
    ],
)
def test_limits_reject_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        TerminationLimits(**{field: value})


@pytest.mark.parametrize("started", [-1.0, float("inf"), float("nan"), True])
def test_state_start_rejects_invalid_timestamp(
    tmp_path: Path,
    started: object,
) -> None:
    with pytest.raises(ValueError, match="started_at_monotonic"):
        AgentState.start("task", tmp_path, started)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    [
        "logical_model_call_count",
        "model_call_count",
        "tool_call_count",
        "consecutive_model_errors",
        "consecutive_tool_errors",
        "consecutive_safety_rejections",
        "repeated_tool_call_count",
    ],
)
def test_invalid_negative_state_counter_is_internal_invariant(
    tmp_path: Path,
    field: str,
) -> None:
    state = state_at(tmp_path)
    setattr(state, field, -1)
    decision = TerminationPolicy().check(
        state,
        11.0,
        next_operation=NextOperation.MODEL,
    )
    assert decision.should_stop
    assert decision.reason is TerminationReason.INTERNAL_INVARIANT


def test_timestamp_before_start_is_internal_invariant(tmp_path: Path) -> None:
    state = state_at(tmp_path, started=10.0)
    decision = TerminationPolicy().check(
        state,
        9.0,
        next_operation=NextOperation.TOOL,
    )
    assert decision.should_stop
    assert decision.reason is TerminationReason.INTERNAL_INVARIANT


def test_counter_above_limit_is_internal_invariant(tmp_path: Path) -> None:
    state = state_at(tmp_path)
    state.model_call_count = 49
    decision = TerminationPolicy().check(
        state,
        11.0,
        next_operation=NextOperation.MODEL,
    )
    assert decision.should_stop
    assert decision.reason is TerminationReason.INTERNAL_INVARIANT


def test_priority_is_stable_when_multiple_conditions_hold(tmp_path: Path) -> None:
    state = state_at(tmp_path)
    state.logical_model_call_count = 12
    state.model_call_count = 12
    state.tool_call_count = 40
    state.consecutive_safety_rejections = 3
    state.consecutive_model_errors = 3
    state.repeated_tool_call_count = 3
    decision = TerminationPolicy().check(
        state,
        700.0,
        next_operation=NextOperation.MODEL,
    )
    assert decision.reason is TerminationReason.CONSECUTIVE_SAFETY_REJECTIONS


def test_argument_order_does_not_change_tool_fingerprint() -> None:
    left = ToolCall("a", "read_file", {"path": "a.py", "end_line": 2})
    right = ToolCall("b", "read_file", {"end_line": 2, "path": "a.py"})
    assert tool_call_fingerprint(left) == tool_call_fingerprint(right)


def test_result_fingerprint_changes_with_observed_result() -> None:
    first = ToolResult("a", "read_file", "ok", output="one")
    second = ToolResult("a", "read_file", "ok", output="two")
    assert tool_result_fingerprint(first) != tool_result_fingerprint(second)


def test_result_fingerprint_ignores_provider_call_id() -> None:
    first = ToolResult("a", "read_file", "ok", output="same")
    second = ToolResult("b", "read_file", "ok", output="same")
    assert tool_result_fingerprint(first) == tool_result_fingerprint(second)


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (BudgetProfile.STANDARD, (24, 4, 48, 8, 80, 1200.0, 1)),
        (BudgetProfile.DEEP, (40, 6, 80, 12, 140, 1800.0, 1)),
    ],
)
def test_termination_limits_match_budget_profile(
    profile: BudgetProfile,
    expected: tuple[int, int, int, int, int, float, int],
) -> None:
    limits = TerminationLimits.for_profile(profile)

    assert (
        limits.max_main_logical_calls,
        limits.max_summary_logical_calls,
        limits.max_provider_attempts,
        limits.max_summary_provider_attempts,
        limits.max_tool_calls,
        limits.max_runtime_seconds,
        limits.verification_tool_reserve,
    ) == expected


def test_last_main_call_is_allowed_and_next_is_blocked(tmp_path: Path) -> None:
    state = state_at(tmp_path)
    policy = TerminationPolicy(TerminationLimits.for_profile(BudgetProfile.STANDARD))
    state.main_model_call_count = 23
    state.logical_model_call_count = 23

    assert policy.check(
        state,
        11.0,
        next_operation=NextOperation.MODEL,
    ).should_stop is False

    state.main_model_call_count = 24
    state.logical_model_call_count = 24
    decision = policy.check(
        state,
        11.0,
        next_operation=NextOperation.MODEL,
    )
    assert decision.reason is TerminationReason.MAIN_MODEL_CALL_LIMIT


def test_verification_reserve_blocks_ordinary_tool_but_allows_gate(
    tmp_path: Path,
) -> None:
    state = state_at(tmp_path)
    state.tool_call_count = 79
    policy = TerminationPolicy(TerminationLimits.for_profile(BudgetProfile.STANDARD))

    ordinary = policy.check(
        state,
        11.0,
        next_operation=NextOperation.TOOL,
        verification_reserve_active=True,
    )
    verification = policy.check(
        state,
        11.0,
        next_operation=NextOperation.VERIFICATION,
        verification_reserve_active=True,
    )

    assert ordinary.reason is TerminationReason.TOOL_CALL_LIMIT
    assert verification.should_stop is False

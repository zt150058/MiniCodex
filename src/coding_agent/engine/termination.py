from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import math

from coding_agent.engine.budget import BudgetProfile, limits_for_profile
from coding_agent.engine.messages import ToolCall, ToolResult
from coding_agent.engine.state import AgentState, TerminationReason


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_finite_number(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be a positive finite number")
    return float(value)


@dataclass(frozen=True, slots=True)
class TerminationLimits:
    max_main_logical_calls: int = 24
    max_summary_logical_calls: int = 4
    max_provider_attempts: int = 48
    max_summary_provider_attempts: int = 8
    max_tool_calls: int = 80
    max_runtime_seconds: float = 1200.0
    verification_tool_reserve: int = 1
    repetition_limit: int = 3
    consecutive_error_limit: int = 3
    safety_rejection_limit: int = 3

    def __post_init__(self) -> None:
        for name in (
            "max_main_logical_calls",
            "max_summary_logical_calls",
            "max_provider_attempts",
            "max_summary_provider_attempts",
            "max_tool_calls",
            "repetition_limit",
            "consecutive_error_limit",
            "safety_rejection_limit",
        ):
            object.__setattr__(self, name, _positive_integer(getattr(self, name), name))
        if (
            type(self.verification_tool_reserve) is not int
            or self.verification_tool_reserve < 0
            or self.verification_tool_reserve >= self.max_tool_calls
        ):
            raise ValueError(
                "verification_tool_reserve must be a non-negative integer "
                "smaller than max_tool_calls"
            )
        if self.max_summary_provider_attempts > self.max_provider_attempts:
            raise ValueError(
                "max_summary_provider_attempts must not exceed "
                "max_provider_attempts"
            )
        object.__setattr__(
            self,
            "max_runtime_seconds",
            _positive_finite_number(
                self.max_runtime_seconds,
                "max_runtime_seconds",
            ),
        )

    @classmethod
    def for_profile(cls, profile: BudgetProfile) -> TerminationLimits:
        values = limits_for_profile(profile)
        return cls(
            max_main_logical_calls=values.max_main_logical_calls,
            max_summary_logical_calls=values.max_summary_logical_calls,
            max_provider_attempts=values.max_provider_attempts,
            max_summary_provider_attempts=values.max_summary_provider_attempts,
            max_tool_calls=values.max_tool_calls,
            max_runtime_seconds=values.max_runtime_seconds,
            verification_tool_reserve=values.verification_tool_reserve,
        )


class NextOperation(StrEnum):
    MODEL = "model"
    TOOL = "tool"
    VERIFICATION = "verification"


@dataclass(frozen=True, slots=True)
class TerminationDecision:
    should_stop: bool
    reason: TerminationReason | None = None


class TerminationPolicy:
    def __init__(self, limits: TerminationLimits = TerminationLimits()) -> None:
        if not isinstance(limits, TerminationLimits):
            raise TypeError("limits must be TerminationLimits")
        self._limits = limits

    @property
    def limits(self) -> TerminationLimits:
        return self._limits

    def check(
        self,
        state: AgentState,
        monotonic_time: float,
        *,
        next_operation: NextOperation,
        verification_reserve_active: bool = False,
    ) -> TerminationDecision:
        if self._invalid_state(
            state,
            monotonic_time,
            next_operation,
            verification_reserve_active,
        ):
            return TerminationDecision(True, TerminationReason.INTERNAL_INVARIANT)

        limits = self._limits
        if state.consecutive_safety_rejections >= limits.safety_rejection_limit:
            return TerminationDecision(
                True,
                TerminationReason.CONSECUTIVE_SAFETY_REJECTIONS,
            )
        if monotonic_time - state.started_at_monotonic >= limits.max_runtime_seconds:
            return TerminationDecision(True, TerminationReason.TIME_LIMIT)
        if next_operation is NextOperation.MODEL:
            if state.model_call_count >= limits.max_provider_attempts:
                return TerminationDecision(
                    True,
                    TerminationReason.PROVIDER_ATTEMPT_LIMIT,
                )
            if state.main_model_call_count >= limits.max_main_logical_calls:
                return TerminationDecision(
                    True,
                    TerminationReason.MAIN_MODEL_CALL_LIMIT,
                )
        if next_operation in {NextOperation.TOOL, NextOperation.VERIFICATION}:
            operation_limit = limits.max_tool_calls
            if next_operation is NextOperation.TOOL and verification_reserve_active:
                operation_limit -= limits.verification_tool_reserve
            if state.tool_call_count >= operation_limit:
                return TerminationDecision(True, TerminationReason.TOOL_CALL_LIMIT)
        if state.consecutive_model_errors >= limits.consecutive_error_limit:
            return TerminationDecision(
                True,
                TerminationReason.CONSECUTIVE_MODEL_ERRORS,
            )
        if state.consecutive_tool_errors >= limits.consecutive_error_limit:
            return TerminationDecision(
                True,
                TerminationReason.CONSECUTIVE_TOOL_ERRORS,
            )
        if state.repeated_tool_call_count >= limits.repetition_limit:
            return TerminationDecision(True, TerminationReason.REPEATED_TOOL_CALL)
        return TerminationDecision(False)

    def _invalid_state(
        self,
        state: AgentState,
        monotonic_time: float,
        next_operation: NextOperation,
        verification_reserve_active: bool,
    ) -> bool:
        if (
            not isinstance(state, AgentState)
            or not isinstance(next_operation, NextOperation)
            or not isinstance(verification_reserve_active, bool)
        ):
            return True
        if (
            isinstance(monotonic_time, bool)
            or not isinstance(monotonic_time, (int, float))
            or not math.isfinite(monotonic_time)
            or monotonic_time < state.started_at_monotonic
        ):
            return True
        counters = (
            state.logical_model_call_count,
            state.main_model_call_count,
            state.summary_model_call_count,
            state.model_call_count,
            state.summary_provider_attempt_count,
            state.tool_call_count,
            state.consecutive_model_errors,
            state.consecutive_output_limit_errors,
            state.consecutive_tool_errors,
            state.consecutive_safety_rejections,
            state.repeated_tool_call_count,
            state.mutation_index,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counters
        ):
            return True
        limits = self._limits
        return (
            state.main_model_call_count > limits.max_main_logical_calls
            or state.summary_model_call_count > limits.max_summary_logical_calls
            or state.logical_model_call_count
            > limits.max_main_logical_calls + limits.max_summary_logical_calls
            or state.model_call_count > limits.max_provider_attempts
            or state.summary_provider_attempt_count
            > limits.max_summary_provider_attempts
            or state.summary_provider_attempt_count > state.model_call_count
            or state.main_model_call_count + state.summary_model_call_count
            > state.logical_model_call_count
            or state.tool_call_count > limits.max_tool_calls
            or state.consecutive_model_errors > limits.consecutive_error_limit
            or state.consecutive_output_limit_errors > 2
            or state.consecutive_tool_errors > limits.consecutive_error_limit
            or state.consecutive_safety_rejections > limits.safety_rejection_limit
            or state.repeated_tool_call_count > limits.repetition_limit
        )


def tool_call_fingerprint(call: ToolCall) -> str:
    if not isinstance(call, ToolCall):
        raise TypeError("call must be ToolCall")
    arguments = json.dumps(
        call.arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(
        f"{call.name}\n{arguments}".encode("utf-8")
    ).hexdigest()


def tool_result_fingerprint(result: ToolResult) -> str:
    if not isinstance(result, ToolResult):
        raise TypeError("result must be ToolResult")
    payload = {
        "tool_name": result.tool_name,
        "status": result.status,
        "output": result.output,
        "error": result.error,
        "metadata": result.metadata.to_dict(),
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

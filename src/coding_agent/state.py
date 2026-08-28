from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
from pathlib import Path

from coding_agent.messages import Message, UserMessage


class AgentStatus(StrEnum):
    RUNNING = "running"
    COMPLETION_CANDIDATE = "completion_candidate"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class TerminationReason(StrEnum):
    LOGICAL_MODEL_CALL_LIMIT = "logical_model_call_limit"
    PROVIDER_ATTEMPT_LIMIT = "provider_attempt_limit"
    TOOL_CALL_LIMIT = "tool_call_limit"
    TIME_LIMIT = "time_limit"
    REPEATED_TOOL_CALL = "repeated_tool_call"
    CONSECUTIVE_MODEL_ERRORS = "consecutive_model_errors"
    CONSECUTIVE_TOOL_ERRORS = "consecutive_tool_errors"
    CONSECUTIVE_SAFETY_REJECTIONS = "consecutive_safety_rejections"
    CONTEXT_BUDGET_EXHAUSTED = "context_budget_exhausted"
    FATAL_MODEL_ERROR = "fatal_model_error"
    EMPTY_MODEL_RESPONSE = "empty_model_response"
    INTERNAL_INVARIANT = "internal_invariant"
    USER_INTERRUPTED = "user_interrupted"


class VerificationStatus(StrEnum):
    NOT_RUN = "not_run"
    STALE = "stale"


@dataclass(slots=True)
class AgentState:
    task: str
    current_goal: str
    messages: tuple[Message, ...]
    workspace: Path
    started_at_monotonic: float
    open_issues: tuple[str, ...] = ()
    status: AgentStatus = AgentStatus.RUNNING
    logical_model_call_count: int = 0
    model_call_count: int = 0
    tool_call_count: int = 0
    consecutive_model_errors: int = 0
    consecutive_tool_errors: int = 0
    consecutive_safety_rejections: int = 0
    repeated_tool_call_count: int = 0
    last_tool_fingerprint: str | None = None
    last_tool_result_fingerprint: str | None = None
    termination_reason: TerminationReason | None = None
    mutation_index: int = 0
    modified_paths: tuple[str, ...] = ()
    verification_status: VerificationStatus = VerificationStatus.NOT_RUN
    completion_text: str | None = None
    failure_reason: str | None = None
    continuation_items: tuple[object, ...] = field(default=(), repr=False)

    @classmethod
    def start(
        cls,
        task: str,
        workspace: Path,
        started_at_monotonic: float,
    ) -> AgentState:
        if (
            isinstance(started_at_monotonic, bool)
            or not isinstance(started_at_monotonic, (int, float))
            or not math.isfinite(started_at_monotonic)
            or started_at_monotonic < 0
        ):
            raise ValueError(
                "started_at_monotonic must be a non-negative finite number"
            )
        user_message = UserMessage(task)
        return cls(
            task=user_message.content,
            current_goal=user_message.content,
            messages=(user_message,),
            workspace=Path(workspace),
            started_at_monotonic=float(started_at_monotonic),
        )

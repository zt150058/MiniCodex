from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
from pathlib import Path
from typing import TYPE_CHECKING

from coding_agent.budget import BudgetProfile
from coding_agent.messages import Message, UserMessage
from coding_agent.progress import ProgressLedger
from coding_agent.run_mode import RunMode

if TYPE_CHECKING:
    from coding_agent.verification import VerificationResult


class AgentStatus(StrEnum):
    RUNNING = "running"
    COMPLETION_CANDIDATE = "completion_candidate"
    SUCCESS = "success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    ANSWERED = "answered"


class TerminationReason(StrEnum):
    AUDIT_LOG_FAILURE = "audit_log_failure"
    LOGICAL_MODEL_CALL_LIMIT = "logical_model_call_limit"
    MAIN_MODEL_CALL_LIMIT = "main_model_call_limit"
    PROVIDER_ATTEMPT_LIMIT = "provider_attempt_limit"
    TOOL_CALL_LIMIT = "tool_call_limit"
    TIME_LIMIT = "time_limit"
    REPEATED_TOOL_CALL = "repeated_tool_call"
    CONSECUTIVE_MODEL_ERRORS = "consecutive_model_errors"
    INVALID_MODEL_RESPONSE = "invalid_model_response"
    MODEL_OUTPUT_LIMIT = "model_output_limit"
    CONSECUTIVE_TOOL_ERRORS = "consecutive_tool_errors"
    CONSECUTIVE_SAFETY_REJECTIONS = "consecutive_safety_rejections"
    CONTEXT_BUDGET_EXHAUSTED = "context_budget_exhausted"
    FATAL_MODEL_ERROR = "fatal_model_error"
    EMPTY_MODEL_RESPONSE = "empty_model_response"
    INTERNAL_INVARIANT = "internal_invariant"
    USER_INTERRUPTED = "user_interrupted"
    NO_PROGRESS = "no_progress"
    CHANGES_UNVERIFIED = "changes_unverified"


class VerificationStatus(StrEnum):
    NOT_RUN = "not_run"
    STALE = "stale"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ERROR = "error"


class SummaryFallbackReason(StrEnum):
    MODEL_ERROR = "model_error"
    INVALID_SUMMARY = "invalid_summary"
    SUMMARY_BUDGET = "summary_budget"


@dataclass(slots=True)
class AgentState:
    task: str
    current_goal: str
    messages: tuple[Message, ...]
    workspace: Path
    started_at_monotonic: float
    run_mode: RunMode = RunMode.MODIFY
    budget_profile: BudgetProfile = BudgetProfile.STANDARD
    open_issues: tuple[str, ...] = ()
    status: AgentStatus = AgentStatus.RUNNING
    logical_model_call_count: int = 0
    main_model_call_count: int = 0
    summary_model_call_count: int = 0
    model_call_count: int = 0
    summary_provider_attempt_count: int = 0
    tool_call_count: int = 0
    consecutive_model_errors: int = 0
    consecutive_output_limit_errors: int = 0
    consecutive_tool_errors: int = 0
    consecutive_safety_rejections: int = 0
    repeated_tool_call_count: int = 0
    last_tool_fingerprint: str | None = None
    last_tool_result_fingerprint: str | None = None
    termination_reason: TerminationReason | None = None
    mutation_index: int = 0
    modified_paths: tuple[str, ...] = ()
    verification_status: VerificationStatus = VerificationStatus.NOT_RUN
    verification_attempt_count: int = 0
    last_verification: VerificationResult | None = field(default=None, repr=False)
    completion_text: str | None = None
    failure_reason: str | None = None
    continuation_items: tuple[object, ...] = field(default=(), repr=False)
    summary_fallback_latched: bool = False
    summary_fallback_reason: SummaryFallbackReason | None = None
    progress: ProgressLedger = field(default_factory=ProgressLedger, repr=False)
    required_verification_pending: bool = False

    @property
    def validation_index(self) -> int | None:
        if self.last_verification is None:
            return None
        return self.last_verification.validation_index

    @property
    def has_unverified_changes(self) -> bool:
        if self.mutation_index <= 0:
            return False
        return not (
            self.verification_status is VerificationStatus.PASSED
            and self.last_verification is not None
            and self.last_verification.status is VerificationStatus.PASSED
            and self.last_verification.validation_index == self.mutation_index
        )

    @classmethod
    def start(
        cls,
        task: str,
        workspace: Path,
        started_at_monotonic: float,
        *,
        initial_user_message: str | None = None,
        run_mode: RunMode = RunMode.MODIFY,
        budget_profile: BudgetProfile = BudgetProfile.STANDARD,
    ) -> AgentState:
        if not isinstance(run_mode, RunMode):
            raise TypeError("run_mode must be RunMode")
        if type(budget_profile) is not BudgetProfile:
            raise TypeError("budget_profile must be BudgetProfile")
        if (
            isinstance(started_at_monotonic, bool)
            or not isinstance(started_at_monotonic, (int, float))
            or not math.isfinite(started_at_monotonic)
            or started_at_monotonic < 0
        ):
            raise ValueError(
                "started_at_monotonic must be a non-negative finite number"
            )
        task_message = UserMessage(task)
        user_message = (
            task_message
            if initial_user_message is None
            else UserMessage(initial_user_message)
        )
        return cls(
            task=task_message.content,
            current_goal=task_message.content,
            messages=(user_message,),
            workspace=Path(workspace),
            started_at_monotonic=float(started_at_monotonic),
            run_mode=run_mode,
            budget_profile=budget_profile,
        )

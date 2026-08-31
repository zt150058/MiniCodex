from __future__ import annotations

from dataclasses import dataclass, field
import json

from coding_agent.engine.budget import BudgetProfile
from coding_agent.engine.logging import RunMetadata, TokenUsageTotals, scrub_text
from coding_agent.engine.messages import JSONObject
from coding_agent.engine.progress import AgentPhase
from coding_agent.engine.run_mode import RunMode
from coding_agent.operations.safety import CommandSource
from coding_agent.engine.state import (
    AgentState,
    AgentStatus,
    TerminationReason,
    VerificationStatus,
)


REPORT_SCHEMA_VERSION = 3
MAX_REPORT_COMPLETION_CHARS = 4096
MAX_REPORT_COMMAND_CHARS = 4096
MAX_REPORT_STREAM_CHARS = 8192


class ReportInvariantError(RuntimeError):
    """Final state and controlled run metadata contradict each other."""


@dataclass(frozen=True, slots=True)
class EvidenceExcerpt:
    text: str = field(repr=False)
    original_chars: int
    truncated: bool

    def to_dict(self) -> JSONObject:
        return {
            "text": self.text,
            "original_chars": self.original_chars,
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True)
class VerificationReport:
    status: VerificationStatus
    source: CommandSource | None
    command: str | None = field(repr=False)
    exit_code: int | None
    timed_out: bool
    truncated: bool
    duration_ms: int | None
    validation_index: int | None
    stdout: EvidenceExcerpt | None
    stderr: EvidenceExcerpt | None
    error_code: str | None

    def to_dict(self) -> JSONObject:
        return {
            "status": self.status.value,
            "source": None if self.source is None else self.source.value,
            "command": self.command,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
            "duration_ms": self.duration_ms,
            "validation_index": self.validation_index,
            "stdout": None if self.stdout is None else self.stdout.to_dict(),
            "stderr": None if self.stderr is None else self.stderr.to_dict(),
            "error_code": self.error_code,
        }


def _excerpt(
    value: str | None,
    limit: int,
    sensitive_values: tuple[str, ...],
) -> EvidenceExcerpt | None:
    if value is None:
        return None
    scrubbed = scrub_text(value, sensitive_values)
    return EvidenceExcerpt(
        text=scrubbed[:limit],
        original_chars=len(scrubbed),
        truncated=len(scrubbed) > limit,
    )


@dataclass(frozen=True, slots=True)
class FinalReport:
    schema_version: int
    run_id: str
    run_mode: RunMode
    budget_profile: BudgetProfile
    phase: AgentPhase
    status: AgentStatus
    exit_code: int
    completion: EvidenceExcerpt | None
    termination_reason: TerminationReason | None
    failure_reason: str | None
    changed_paths: tuple[str, ...]
    mutation_index: int
    validation_index: int | None
    verification: VerificationReport
    main_model_calls: int
    summary_model_calls: int
    logical_model_calls: int
    summary_provider_attempts: int
    provider_attempts: int
    tool_calls: int
    verification_attempts: int
    context_compressions: int
    token_usage: TokenUsageTotals
    elapsed_ms: int
    log_failure_code: str | None
    log_path: str

    def __post_init__(self) -> None:
        if type(self.budget_profile) is not BudgetProfile:
            raise TypeError("budget_profile must be BudgetProfile")
        if not isinstance(self.phase, AgentPhase):
            raise TypeError("phase must be AgentPhase")
        for name in (
            "main_model_calls",
            "summary_model_calls",
            "logical_model_calls",
            "summary_provider_attempts",
            "provider_attempts",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise TypeError(f"{name} must be a non-negative integer")
        if self.logical_model_calls != (
            self.main_model_calls + self.summary_model_calls
        ):
            raise ReportInvariantError("logical model counts are inconsistent")
        if self.summary_provider_attempts > self.provider_attempts:
            raise ReportInvariantError("provider attempt counts are inconsistent")
        if self.status in {AgentStatus.SUCCESS, AgentStatus.ANSWERED} and (
            self.phase is not AgentPhase.FINISH
        ):
            raise ReportInvariantError("successful terminal state must be finish phase")

    @classmethod
    def from_state(
        cls,
        state: AgentState,
        metadata: RunMetadata,
        *,
        sensitive_values: tuple[str, ...] = (),
    ) -> FinalReport:
        if not isinstance(state, AgentState) or not isinstance(metadata, RunMetadata):
            raise TypeError("state and metadata must use controlled run types")
        if not isinstance(sensitive_values, tuple) or any(
            not isinstance(value, str) for value in sensitive_values
        ):
            raise TypeError("sensitive_values must be a tuple of strings")
        if state.status in {AgentStatus.RUNNING, AgentStatus.COMPLETION_CANDIDATE}:
            raise ReportInvariantError("agent state is not terminal")
        if metadata.finished_elapsed_ms is None or metadata.finished_elapsed_ms < 0:
            raise ReportInvariantError("run metadata has no terminal elapsed time")
        if (
            state.logical_model_call_count
            != state.main_model_call_count + state.summary_model_call_count
            or state.summary_provider_attempt_count > state.model_call_count
        ):
            raise ReportInvariantError("model budget counts are inconsistent")
        if state.status in {AgentStatus.SUCCESS, AgentStatus.ANSWERED} and (
            state.progress.phase is not AgentPhase.FINISH
        ):
            raise ReportInvariantError("successful terminal state must be finish phase")

        if state.status is AgentStatus.SUCCESS:
            evidence = state.last_verification
            if (
                state.termination_reason is not None
                or state.failure_reason is not None
                or state.verification_status is not VerificationStatus.PASSED
                or evidence is None
                or evidence.status is not VerificationStatus.PASSED
                or evidence.exit_code != 0
                or evidence.timed_out
                or evidence.validation_index != state.mutation_index
            ):
                raise ReportInvariantError("success lacks fresh passing verification")
            exit_code = 0
        elif state.status is AgentStatus.ANSWERED:
            if (
                not isinstance(state.completion_text, str)
                or not state.completion_text.strip()
                or state.termination_reason is not None
                or state.failure_reason is not None
                or state.mutation_index != 0
                or state.modified_paths
                or state.verification_status is not VerificationStatus.NOT_RUN
                or state.verification_attempt_count != 0
                or state.last_verification is not None
            ):
                raise ReportInvariantError("answered state has invalid facts")
            exit_code = 0
        elif state.status is AgentStatus.INTERRUPTED:
            if state.termination_reason is not TerminationReason.USER_INTERRUPTED:
                raise ReportInvariantError("interrupted state has invalid reason")
            exit_code = 130
        else:
            if (
                state.termination_reason is None
                or state.failure_reason != state.termination_reason.value
            ):
                raise ReportInvariantError("failed state has invalid reason")
            exit_code = 1

        result = state.last_verification
        if result is None:
            verification = VerificationReport(
                status=state.verification_status,
                source=None,
                command=None,
                exit_code=None,
                timed_out=False,
                truncated=False,
                duration_ms=None,
                validation_index=None,
                stdout=None,
                stderr=None,
                error_code=None,
            )
        else:
            verification = VerificationReport(
                status=state.verification_status,
                source=result.source,
                command=_excerpt(
                    result.command,
                    MAX_REPORT_COMMAND_CHARS,
                    sensitive_values,
                ).text,
                exit_code=result.exit_code,
                timed_out=result.timed_out,
                truncated=result.truncated,
                duration_ms=result.duration_ms,
                validation_index=result.validation_index,
                stdout=_excerpt(
                    result.stdout,
                    MAX_REPORT_STREAM_CHARS,
                    sensitive_values,
                ),
                stderr=_excerpt(
                    result.stderr,
                    MAX_REPORT_STREAM_CHARS,
                    sensitive_values,
                ),
                error_code=result.error,
            )

        totals = metadata.token_usage
        return cls(
            schema_version=REPORT_SCHEMA_VERSION,
            run_id=metadata.run_id,
            run_mode=state.run_mode,
            budget_profile=state.budget_profile,
            phase=state.progress.phase,
            status=state.status,
            exit_code=exit_code,
            completion=_excerpt(
                state.completion_text,
                MAX_REPORT_COMPLETION_CHARS,
                sensitive_values,
            ),
            termination_reason=state.termination_reason,
            failure_reason=(
                None
                if state.failure_reason is None
                else scrub_text(state.failure_reason, sensitive_values)
            ),
            changed_paths=tuple(
                scrub_text(path, sensitive_values) for path in state.modified_paths
            ),
            mutation_index=state.mutation_index,
            validation_index=state.validation_index,
            verification=verification,
            main_model_calls=state.main_model_call_count,
            summary_model_calls=state.summary_model_call_count,
            logical_model_calls=state.logical_model_call_count,
            summary_provider_attempts=state.summary_provider_attempt_count,
            provider_attempts=state.model_call_count,
            tool_calls=state.tool_call_count,
            verification_attempts=state.verification_attempt_count,
            context_compressions=metadata.context_compression_count,
            token_usage=TokenUsageTotals(
                input_tokens=totals.input_tokens,
                output_tokens=totals.output_tokens,
                total_tokens=totals.total_tokens,
                responses_with_usage=totals.responses_with_usage,
                responses_without_usage=totals.responses_without_usage,
            ),
            elapsed_ms=metadata.finished_elapsed_ms,
            log_failure_code=metadata.log_failure_code,
            log_path=metadata.log_path,
        )

    def to_dict(self) -> JSONObject:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "run_mode": self.run_mode.value,
            "budget_profile": self.budget_profile.value,
            "phase": self.phase.value,
            "status": self.status.value,
            "exit_code": self.exit_code,
            "completion": None if self.completion is None else self.completion.to_dict(),
            "termination_reason": (
                None if self.termination_reason is None else self.termination_reason.value
            ),
            "failure_reason": self.failure_reason,
            "changed_paths": list(self.changed_paths),
            "mutation_index": self.mutation_index,
            "validation_index": self.validation_index,
            "verification": self.verification.to_dict(),
            "main_model_calls": self.main_model_calls,
            "summary_model_calls": self.summary_model_calls,
            "logical_model_calls": self.logical_model_calls,
            "summary_provider_attempts": self.summary_provider_attempts,
            "provider_attempts": self.provider_attempts,
            "tool_calls": self.tool_calls,
            "verification_attempts": self.verification_attempts,
            "context_compressions": self.context_compressions,
            "token_usage": {
                "input_tokens": self.token_usage.input_tokens,
                "output_tokens": self.token_usage.output_tokens,
                "total_tokens": self.token_usage.total_tokens,
                "responses_with_usage": self.token_usage.responses_with_usage,
                "responses_without_usage": self.token_usage.responses_without_usage,
            },
            "elapsed_ms": self.elapsed_ms,
            "log_failure_code": self.log_failure_code,
            "log_path": self.log_path,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ) + "\n"

from __future__ import annotations

from collections.abc import Callable
import hashlib
import time
from typing import TypeAlias

from coding_agent.budget import BudgetProfile
from coding_agent.context import ContextManager, ContextPreparationError
from coding_agent.logging import EventSink, EventType, RunLogError
from coding_agent.messages import (
    AssistantMessage,
    ModelRequest,
    ToolCall,
    ToolResult,
    UserMessage,
)
from coding_agent.model import (
    FatalModelError,
    InvalidModelResponseError,
    ModelBudgetExceeded,
    ModelCallBudget,
    ModelClient,
    ModelError,
    ModelOutputLimitError,
    invoke_model,
)
from coding_agent.progress import (
    AgentPhase,
    ProgressAction,
    ProgressDecision,
    ProgressLimits,
    ProgressStrength,
    render_execution_control,
)
from coding_agent.run_mode import RunMode
from coding_agent.safety import CommandSource
from coding_agent.state import (
    AgentState,
    AgentStatus,
    TerminationReason,
    VerificationStatus,
)
from coding_agent.streaming import ModelStreamHandler, invoke_model_stream
from coding_agent.termination import (
    NextOperation,
    TerminationPolicy,
    tool_call_fingerprint,
    tool_result_fingerprint,
)
from coding_agent.tools.base import ExecutionContext
from coding_agent.tools.registry import ToolRegistry
from coding_agent.verification import (
    VerificationError,
    VerificationGate,
    VerificationOutcome,
    VerificationResult,
)


ConfirmedTextHandler: TypeAlias = Callable[[str], None]
CancellationCheck: TypeAlias = Callable[[], bool]

_READ_TOOL_NAMES = frozenset({"list_directory", "read_file", "inspect_git"})
_VERIFICATION_TOOL_NAMES = frozenset({"run_command", "run_java_tests"})
_MUTATION_TOOL_NAMES = frozenset({"replace_text", "write_file"})
_FAILED_VERIFICATION_STATUSES = frozenset(
    {
        VerificationStatus.FAILED,
        VerificationStatus.TIMED_OUT,
        VerificationStatus.ERROR,
    }
)
_OUTPUT_LIMIT_RECOVERY_INSTRUCTION = (
    "Output recovery: the previous response reached its output token limit. "
    "Continue with one small tool call at a time, use one file per response, "
    "and keep every tool argument complete. Do not repeat partial prose."
)


def _is_requested_verification(call: ToolCall) -> bool:
    return (
        call.name in _VERIFICATION_TOOL_NAMES
        and call.arguments.get("purpose") == "verification"
    )


def _with_command_correction(result: ToolResult) -> ToolResult:
    if result.error is None:
        return result
    prefix = result.error.split(": ", 1)[0]
    if prefix not in {
        "security_rejected:shell_syntax_denied",
        "security_rejected:executable_denied",
    }:
        return result
    code = prefix.removeprefix("security_rejected:")
    return ToolResult(
        call_id=result.call_id,
        tool_name=result.tool_name,
        status=result.status,
        output=result.output,
        error=(
            f"security_rejected:{code}: command rejected; use one process "
            "without shell operators; verification forms: python "
            "<workspace-relative-file.py>, python -m pytest ..., or python -m "
            "unittest ... with purpose=\"verification\"; use run_java_tests "
            "for Java"
        ),
        metadata=result.metadata,
    )


def _record_successful_mutation(
    state: AgentState,
    result: ToolResult,
) -> None:
    changed_paths = result.metadata.changed_paths
    if result.status != "ok" or not changed_paths:
        return

    state.mutation_index += 1
    known_paths = set(state.modified_paths)
    new_paths = tuple(path for path in changed_paths if path not in known_paths)
    state.modified_paths += new_paths
    state.verification_status = VerificationStatus.STALE


class AgentInterrupted(KeyboardInterrupt):
    def __init__(self, state: AgentState) -> None:
        self.state = state
        super().__init__(TerminationReason.USER_INTERRUPTED.value)


class AgentRunner:
    def __init__(
        self,
        *,
        model_client: ModelClient,
        tool_registry: ToolRegistry,
        execution_context: ExecutionContext,
        context_manager: ContextManager | None = None,
        termination_policy: TerminationPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        verification_gate: VerificationGate | None = None,
        event_sink: EventSink | None = None,
        instructions: str | None = None,
        stream_handler: ModelStreamHandler | None = None,
        initial_user_message: str | None = None,
        confirmed_text_handler: ConfirmedTextHandler | None = None,
        cancellation_requested: CancellationCheck | None = None,
        run_mode: RunMode = RunMode.MODIFY,
        budget_profile: BudgetProfile = BudgetProfile.STANDARD,
        progress_limits: ProgressLimits | None = None,
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        if instructions is not None and (
            not isinstance(instructions, str) or not instructions.strip()
        ):
            raise ValueError("instructions must be a non-empty string or null")
        if stream_handler is not None and not callable(stream_handler):
            raise TypeError("stream_handler must be callable or null")
        if initial_user_message is not None:
            UserMessage(initial_user_message)
        if confirmed_text_handler is not None and not callable(
            confirmed_text_handler
        ):
            raise TypeError("confirmed_text_handler must be callable or null")
        if cancellation_requested is not None and not callable(
            cancellation_requested
        ):
            raise TypeError("cancellation_requested must be callable or null")
        if not isinstance(run_mode, RunMode):
            raise TypeError("run_mode must be RunMode")
        if type(budget_profile) is not BudgetProfile:
            raise TypeError("budget_profile must be BudgetProfile")
        if progress_limits is not None and not isinstance(
            progress_limits,
            ProgressLimits,
        ):
            raise TypeError("progress_limits must be ProgressLimits or null")
        if run_mode is RunMode.READ_ONLY and verification_gate is not None:
            raise ValueError("read-only mode cannot use a verification gate")
        self._model_client = model_client
        self._tool_registry = tool_registry
        self._execution_context = execution_context
        self._context_manager = context_manager or ContextManager(
            model_client=model_client
        )
        self._termination_policy = termination_policy or TerminationPolicy()
        self._clock = clock
        self._verification_gate = verification_gate
        self._event_sink = event_sink
        self._instructions = instructions
        self._stream_handler = stream_handler
        self._initial_user_message = initial_user_message
        self._confirmed_text_handler = confirmed_text_handler
        self._cancellation_requested = cancellation_requested
        self._run_mode = run_mode
        self._budget_profile = budget_profile
        self._progress_limits = (
            ProgressLimits.for_profile(budget_profile)
            if progress_limits is None
            else progress_limits
        )

    def _emit(self, event_type: EventType, data: dict[str, object]) -> None:
        if self._event_sink is not None:
            self._event_sink.emit(event_type, data)  # type: ignore[arg-type]

    @staticmethod
    def _hash_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _safe_tool_error_code(result: ToolResult) -> str | None:
        if result.status == "ok":
            return None
        if result.error is not None and result.error.startswith(
            ("security_rejected:", "agent_rejected:")
        ):
            return result.error.split(": ", 1)[0]
        return "tool_error" if result.status == "error" else "tool_rejected"

    @staticmethod
    def _verification_event_data(result: VerificationResult) -> dict[str, object]:
        return {
            "source": result.source.value,
            "status": result.status.value,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "truncated": result.truncated,
            "duration_ms": result.duration_ms,
            "validation_index": result.validation_index,
            "mutation_index": result.validation_index,
            "stdout_chars": len(result.stdout),
            "stderr_chars": len(result.stderr),
            "error_code": result.error,
        }

    @staticmethod
    def _terminate(
        state: AgentState,
        reason: TerminationReason,
    ) -> AgentState:
        if state.has_unverified_changes and reason in {
            TerminationReason.CONSECUTIVE_SAFETY_REJECTIONS,
            TerminationReason.CONSECUTIVE_TOOL_ERRORS,
            TerminationReason.NO_PROGRESS,
        }:
            reason = TerminationReason.CHANGES_UNVERIFIED
        state.status = AgentStatus.FAILED
        state.termination_reason = reason
        state.failure_reason = reason.value
        return state

    @staticmethod
    def _current_verification_failed(state: AgentState) -> bool:
        evidence = state.last_verification
        return (
            evidence is not None
            and evidence.validation_index == state.mutation_index
            and evidence.status in _FAILED_VERIFICATION_STATUSES
            and state.verification_status is evidence.status
        )

    @staticmethod
    def _sync_budget(state: AgentState, budget: ModelCallBudget) -> None:
        state.logical_model_call_count = budget.logical_calls
        state.main_model_call_count = budget.main_logical_calls
        state.summary_model_call_count = budget.summary_logical_calls
        state.model_call_count = budget.provider_attempts
        state.summary_provider_attempt_count = budget.summary_provider_attempts

    def _policy_reason(
        self,
        state: AgentState,
        operation: NextOperation,
        *,
        verification_reserve_active: bool = False,
    ) -> TerminationReason | None:
        decision = self._termination_policy.check(
            state,
            self._clock(),
            next_operation=operation,
            verification_reserve_active=verification_reserve_active,
        )
        return decision.reason if decision.should_stop else None

    def _transition_phase(self, state: AgentState, phase: AgentPhase) -> None:
        previous = state.progress.phase
        if state.progress.transition(phase):
            self._emit(
                EventType.PHASE_CHANGED,
                {
                    "from_phase": previous.value,
                    "to_phase": phase.value,
                    "epoch": state.progress.epoch,
                },
            )

    def _emit_progress(
        self,
        state: AgentState,
        strength: ProgressStrength,
        *,
        source: str,
    ) -> None:
        self._emit(
            EventType.PROGRESS_OBSERVED,
            {
                "strength": strength.value,
                "source": source,
                "epoch": state.progress.epoch,
            },
        )

    def _append_unexecuted_results(
        self,
        state: AgentState,
        calls: tuple[ToolCall, ...],
        reason: TerminationReason,
    ) -> None:
        for offset, call in enumerate(calls, start=1):
            self._emit(
                EventType.TOOL_CALL_BLOCKED,
                {
                    "ordinal": state.tool_call_count + offset,
                    "tool_name": call.name,
                    "call_id_hash": self._hash_text(call.call_id),
                    "reason": reason.value,
                    "executed": False,
                },
            )
            state.messages += (
                ToolResult(
                    call_id=call.call_id,
                    tool_name=call.name,
                    status="rejected",
                    error=f"agent_terminated:{reason.value}",
                ),
            )

    def _is_cancellation_requested(self) -> bool:
        if self._cancellation_requested is None:
            return False
        requested = self._cancellation_requested()
        if not isinstance(requested, bool):
            raise TypeError("cancellation_requested must return bool")
        return requested

    def _interrupt(
        self,
        state: AgentState,
        pending_calls: tuple[ToolCall, ...] = (),
    ) -> AgentState:
        if pending_calls:
            self._append_unexecuted_results(
                state,
                pending_calls,
                TerminationReason.USER_INTERRUPTED,
            )
        state.status = AgentStatus.INTERRUPTED
        state.termination_reason = TerminationReason.USER_INTERRUPTED
        state.failure_reason = TerminationReason.USER_INTERRUPTED.value
        return state

    @staticmethod
    def _record_tool_observation(
        state: AgentState,
        call: ToolCall,
        result: ToolResult,
        mutation_index_before: int,
    ) -> None:
        if result.error is not None and result.error.startswith("agent_rejected:"):
            return
        if result.status == "ok":
            state.consecutive_tool_errors = 0
            state.consecutive_safety_rejections = 0
        elif result.error is not None and result.error.startswith(
            "security_rejected:"
        ):
            state.consecutive_safety_rejections += 1
            state.consecutive_tool_errors = 0
        else:
            state.consecutive_tool_errors += 1
            state.consecutive_safety_rejections = 0

        call_fingerprint = tool_call_fingerprint(call)
        result_fingerprint = tool_result_fingerprint(result)
        if state.mutation_index != mutation_index_before:
            state.repeated_tool_call_count = 0
        elif (
            state.last_tool_fingerprint is None
            and state.last_tool_result_fingerprint is None
        ):
            state.repeated_tool_call_count = 1
        elif (
            state.last_tool_fingerprint == call_fingerprint
            and state.last_tool_result_fingerprint == result_fingerprint
        ):
            state.repeated_tool_call_count += 1
        else:
            state.repeated_tool_call_count = 0
        state.last_tool_fingerprint = call_fingerprint
        state.last_tool_result_fingerprint = result_fingerprint

    def run(self, task: str) -> AgentState:
        state = AgentState.start(
            task,
            self._execution_context.workspace,
            self._clock(),
            initial_user_message=self._initial_user_message,
            run_mode=self._run_mode,
            budget_profile=self._budget_profile,
        )
        state.required_verification_pending = bool(
            self._verification_gate is not None
            and self._verification_gate.requires_execution
        )
        limits = self._termination_policy.limits
        budget = ModelCallBudget(
            max_logical_calls=(
                limits.max_main_logical_calls + limits.max_summary_logical_calls
            ),
            max_provider_attempts=limits.max_provider_attempts,
            max_main_logical_calls=limits.max_main_logical_calls,
            max_summary_logical_calls=limits.max_summary_logical_calls,
            max_summary_provider_attempts=(
                limits.max_summary_provider_attempts
            ),
            observer=self._event_sink,
        )
        try:
            self._emit(
                EventType.RUN_STARTED,
                {
                    "task_chars": len(task),
                    "mutation_index": state.mutation_index,
                    "run_mode": state.run_mode.value,
                    "budget_profile": state.budget_profile.value,
                    "max_main_model_calls": limits.max_main_logical_calls,
                    "max_summary_model_calls": limits.max_summary_logical_calls,
                    "max_provider_attempts": limits.max_provider_attempts,
                    "max_summary_provider_attempts": (
                        limits.max_summary_provider_attempts
                    ),
                    "max_tool_calls": limits.max_tool_calls,
                    "max_runtime_seconds": limits.max_runtime_seconds,
                    "verification_tool_reserve": (
                        limits.verification_tool_reserve
                    ),
                },
            )
            result = self._run_loop(state, budget)
            self._emit_run_completed(result)
            return result
        except RunLogError:
            self._sync_budget(state, budget)
            return self._terminate(state, TerminationReason.AUDIT_LOG_FAILURE)
        except KeyboardInterrupt:
            self._sync_budget(state, budget)
            state.status = AgentStatus.INTERRUPTED
            state.termination_reason = TerminationReason.USER_INTERRUPTED
            state.failure_reason = TerminationReason.USER_INTERRUPTED.value
            try:
                self._emit_run_completed(state)
            except Exception:
                pass
            raise AgentInterrupted(state) from None

    def _emit_run_completed(self, state: AgentState) -> None:
        if self._event_sink is None:
            return
        elapsed_ms = max(
            0,
            int((self._clock() - state.started_at_monotonic) * 1000),
        )
        self._event_sink.metadata.finished_elapsed_ms = elapsed_ms
        event = self._event_sink.emit(
            EventType.RUN_COMPLETED,
            {
                "status": state.status.value,
                "termination_reason": (
                    None
                    if state.termination_reason is None
                    else state.termination_reason.value
                ),
                "budget_profile": state.budget_profile.value,
                "phase": state.progress.phase.value,
                "main_model_calls": state.main_model_call_count,
                "summary_model_calls": state.summary_model_call_count,
                "logical_model_calls": state.logical_model_call_count,
                "summary_provider_attempts": (
                    state.summary_provider_attempt_count
                ),
                "provider_attempts": state.model_call_count,
                "tool_calls": state.tool_call_count,
                "verification_attempts": state.verification_attempt_count,
                "mutation_index": state.mutation_index,
                "validation_index": state.validation_index,
                "elapsed_ms": elapsed_ms,
            },
        )
        self._event_sink.metadata.finished_elapsed_ms = event.elapsed_ms

    def _run_loop(
        self,
        state: AgentState,
        budget: ModelCallBudget,
    ) -> AgentState:
        progress_turn_active = False
        while state.status is AgentStatus.RUNNING:
            if self._is_cancellation_requested():
                return self._interrupt(state)
            limits = self._termination_policy.limits
            remaining_main_calls = max(
                0,
                limits.max_main_logical_calls - state.main_model_call_count,
            )
            progress_decision = state.progress.decide(
                self._progress_limits,
                remaining_main_calls=remaining_main_calls,
            )
            if progress_decision.action in {
                ProgressAction.CHECKPOINT,
                ProgressAction.DECISION_REQUIRED,
            }:
                assert progress_decision.reason is not None
                self._emit(
                    EventType.DECISION_CHECKPOINT,
                    {
                        "reason": progress_decision.reason,
                        "phase": state.progress.phase.value,
                        "main_calls_remaining": remaining_main_calls,
                    },
                )
            reason = self._policy_reason(state, NextOperation.MODEL)
            if progress_decision.action is ProgressAction.STOP and reason not in {
                TerminationReason.INTERNAL_INVARIANT,
                TerminationReason.CONSECUTIVE_SAFETY_REJECTIONS,
                TerminationReason.TIME_LIMIT,
                TerminationReason.PROVIDER_ATTEMPT_LIMIT,
            }:
                self._emit(
                    EventType.NO_PROGRESS_DETECTED,
                    {
                        "phase": state.progress.phase.value,
                        "post_checkpoint_main_turns": (
                            state.progress.post_checkpoint_main_turns
                        ),
                    },
                )
                return self._terminate(state, TerminationReason.NO_PROGRESS)
            if reason is not None:
                return self._terminate(state, reason)

            before_size = self._context_manager.measure(state.messages)
            compression_expected = self._context_manager.requires_compression(
                state.messages
            )
            if compression_expected:
                self._emit(
                    EventType.CONTEXT_COMPRESSION_STARTED,
                    {
                        "before_chars": before_size.serialized_chars,
                        "before_items": before_size.history_items,
                        "continuation_count": len(state.continuation_items),
                    },
                )
            fallback_latched_before = state.summary_fallback_latched
            try:
                try:
                    prepared = self._context_manager.prepare(state, budget)
                finally:
                    self._sync_budget(state, budget)
            except ContextPreparationError as exc:
                if compression_expected:
                    self._emit(
                        EventType.CONTEXT_COMPRESSION_FAILED,
                        {
                            "before_chars": before_size.serialized_chars,
                            "before_items": before_size.history_items,
                            "reason": exc.reason.value,
                        },
                    )
                return self._terminate(state, exc.reason)
            except ModelBudgetExceeded as exc:
                if compression_expected:
                    self._emit(
                        EventType.CONTEXT_COMPRESSION_FAILED,
                        {
                            "before_chars": before_size.serialized_chars,
                            "before_items": before_size.history_items,
                            "reason": exc.reason.value,
                        },
                    )
                return self._terminate(
                    state,
                    TerminationReason(exc.reason.value),
                )
            except FatalModelError:
                if compression_expected:
                    self._emit(
                        EventType.CONTEXT_COMPRESSION_FAILED,
                        {
                            "before_chars": before_size.serialized_chars,
                            "before_items": before_size.history_items,
                            "reason": TerminationReason.FATAL_MODEL_ERROR.value,
                        },
                    )
                return self._terminate(
                    state,
                    TerminationReason.FATAL_MODEL_ERROR,
                )

            state.messages = prepared.messages
            state.continuation_items = prepared.continuation_items
            if (
                not fallback_latched_before
                and state.summary_fallback_latched
            ):
                fallback_reason = state.summary_fallback_reason
                assert fallback_reason is not None
                self._emit(
                    EventType.SUMMARY_FALLBACK_LATCHED,
                    {
                        "reason": fallback_reason.value,
                        "summary_model_calls": state.summary_model_call_count,
                    },
                )
            if prepared.compressed:
                state.progress.exploration.mark_context_compacted()
                self._emit(
                    EventType.CONTEXT_COMPRESSION_COMPLETED,
                    {
                        "before_chars": before_size.serialized_chars,
                        "before_items": before_size.history_items,
                        "after_chars": prepared.size.serialized_chars,
                        "after_items": prepared.size.history_items,
                        "summary_source": prepared.summary_source.value,
                        "summary_model_failed": prepared.summary_model_failed,
                        "continuation_cleared": True,
                    },
                )
                if self._event_sink is not None:
                    self._event_sink.metadata.context_compression_count += 1
                if self._is_cancellation_requested():
                    return self._interrupt(state)
                reason = self._policy_reason(state, NextOperation.MODEL)
                if reason is not None:
                    return self._terminate(state, reason)

            if self._is_cancellation_requested():
                return self._interrupt(state)

            request_instructions = self._instructions
            if state.consecutive_output_limit_errors == 1:
                request_instructions = (
                    _OUTPUT_LIMIT_RECOVERY_INSTRUCTION
                    if request_instructions is None
                    else (
                        f"{request_instructions}\n\n"
                        f"{_OUTPUT_LIMIT_RECOVERY_INSTRUCTION}"
                    )
                )
            if state.progress.checkpoint_active or state.has_unverified_changes:
                control = render_execution_control(
                    ledger=state.progress,
                    decision=progress_decision,
                    profile=state.budget_profile,
                    remaining_main_calls=max(
                        0,
                        limits.max_main_logical_calls
                        - state.main_model_call_count,
                    ),
                    remaining_tool_calls=max(
                        0,
                        limits.max_tool_calls - state.tool_call_count,
                    ),
                    verification_reserve=(
                        limits.verification_tool_reserve
                        if state.required_verification_pending
                        else 0
                    ),
                    has_unverified_changes=state.has_unverified_changes,
                )
                request_instructions = (
                    control
                    if request_instructions is None
                    else f"{request_instructions}\n\n{control}"
                )
            coverage = state.progress.exploration.render_coverage(
                force=state.progress.checkpoint_active,
            )
            if coverage is not None:
                request_instructions = (
                    coverage
                    if request_instructions is None
                    else f"{request_instructions}\n\n{coverage}"
                )
            request = ModelRequest(
                messages=state.messages,
                tool_schemas=self._tool_registry.schemas,
                continuation_items=state.continuation_items,
                instructions=request_instructions,
            )
            decision_required_at_turn_start = state.progress.decision_required
            unverified_at_turn_start = state.has_unverified_changes
            repair_open_at_turn_start = self._current_verification_failed(state)
            if not progress_turn_active:
                state.progress.begin_main_turn()
                progress_turn_active = True
            try:
                try:
                    if self._stream_handler is None:
                        response = invoke_model(self._model_client, request, budget)
                    else:
                        response = invoke_model_stream(
                            self._model_client,
                            request,
                            budget,
                            self._stream_handler,
                        )
                finally:
                    self._sync_budget(state, budget)
            except ModelBudgetExceeded as exc:
                return self._terminate(
                    state,
                    TerminationReason(exc.reason.value),
                )
            except FatalModelError:
                return self._terminate(
                    state,
                    TerminationReason.FATAL_MODEL_ERROR,
                )
            except ModelOutputLimitError:
                state.consecutive_model_errors = 0
                state.consecutive_output_limit_errors += 1
                if state.consecutive_output_limit_errors >= 2:
                    return self._terminate(
                        state,
                        TerminationReason.MODEL_OUTPUT_LIMIT,
                    )
                continue
            except InvalidModelResponseError:
                return self._terminate(
                    state,
                    TerminationReason.INVALID_MODEL_RESPONSE,
                )
            except ModelError:
                state.consecutive_model_errors += 1
                continue
            state.consecutive_model_errors = 0
            state.consecutive_output_limit_errors = 0
            state.continuation_items = response.continuation_items

            assistant_text = (
                response.text
                if response.text is not None and response.text.strip()
                else None
            )
            if assistant_text is not None and self._confirmed_text_handler is not None:
                self._confirmed_text_handler(assistant_text)
            if response.tool_calls:
                state.messages += (
                    AssistantMessage(
                        content=assistant_text,
                        tool_calls=response.tool_calls,
                    ),
                )
                if self._is_cancellation_requested():
                    return self._interrupt(state, response.tool_calls)
                for index, call in enumerate(response.tool_calls):
                    if self._is_cancellation_requested():
                        return self._interrupt(state, response.tool_calls[index:])
                    reason = self._policy_reason(
                        state,
                        NextOperation.TOOL,
                        verification_reserve_active=(
                            state.required_verification_pending
                        ),
                    )
                    if reason is not None:
                        self._append_unexecuted_results(
                            state,
                            response.tool_calls[index:],
                            reason,
                        )
                        return self._terminate(state, reason)
                    ordinal = state.tool_call_count + 1
                    call_id_hash = self._hash_text(call.call_id)
                    self._emit(
                        EventType.TOOL_CALL_STARTED,
                        {
                            "ordinal": ordinal,
                            "tool_name": call.name,
                            "call_id_hash": call_id_hash,
                            "mutation_index": state.mutation_index,
                        },
                    )
                    executed = True
                    rejection_code: str | None = None
                    rejection_message: str | None = None
                    if (
                        decision_required_at_turn_start
                        and call.name in _READ_TOOL_NAMES
                    ):
                        rejection_code = "decision_required"
                        rejection_message = (
                            "further read tools are disabled; modify, answer, "
                            "or report blocker"
                        )
                    elif unverified_at_turn_start:
                        allowed_repair = (
                            repair_open_at_turn_start
                            and call.name
                            in (_READ_TOOL_NAMES | _MUTATION_TOOL_NAMES)
                        )
                        if not _is_requested_verification(call) and not allowed_repair:
                            rejection_code = "verification_required"
                            rejection_message = (
                                "unverified changes require verification, repair "
                                "after failed verification, or a blocker report"
                            )
                    if rejection_code is not None:
                        result = ToolResult(
                            call_id=call.call_id,
                            tool_name=call.name,
                            status="rejected",
                            error=(
                                f"agent_rejected:{rejection_code}: "
                                f"{rejection_message}"
                            ),
                        )
                        executed = False
                    else:
                        result = self._tool_registry.execute(
                            call,
                            self._execution_context,
                        )
                        if call.name == "run_command":
                            result = _with_command_correction(result)
                    state.messages += (result,)
                    mutation_index_before = state.mutation_index
                    _record_successful_mutation(state, result)
                    state.tool_call_count += 1
                    self._record_tool_observation(
                        state,
                        call,
                        result,
                        mutation_index_before,
                    )
                    self._emit(
                        EventType.TOOL_CALL_COMPLETED,
                        {
                            "ordinal": ordinal,
                            "tool_name": call.name,
                            "call_id_hash": call_id_hash,
                            "status": result.status,
                            "safe_error_code": self._safe_tool_error_code(result),
                            "output_chars": len(result.output or ""),
                            "exit_code": result.metadata.exit_code,
                            "timed_out": result.metadata.timed_out,
                            "truncated": result.metadata.truncated,
                            "duration_ms": result.metadata.duration_ms,
                            "changed_paths": list(result.metadata.changed_paths),
                            "mutation_index_before": mutation_index_before,
                            "mutation_index_after": state.mutation_index,
                            "executed": executed,
                        },
                    )
                    if state.mutation_index != mutation_index_before:
                        self._emit(
                            EventType.MUTATION_RECORDED,
                            {
                                "mutation_index": state.mutation_index,
                                "changed_paths": list(result.metadata.changed_paths),
                                "verification_status": state.verification_status.value,
                            },
                        )
                    evidence_recorded = False
                    if self._verification_gate is not None:
                        try:
                            evidence_recorded = self._verification_gate.observe_tool_result(
                                state,
                                call,
                                result,
                            )
                        except VerificationError:
                            self._append_unexecuted_results(
                                state,
                                response.tool_calls[index + 1 :],
                                TerminationReason.INTERNAL_INVARIANT,
                            )
                            return self._terminate(
                                state,
                                TerminationReason.INTERNAL_INVARIANT,
                            )
                        if evidence_recorded:
                            evidence = state.last_verification
                            assert evidence is not None
                            self._emit(
                                EventType.VERIFICATION_EVIDENCE_RECORDED,
                                {
                                    **self._verification_event_data(evidence),
                                    "command_hash": self._hash_text(evidence.command),
                                },
                            )
                    strength = state.progress.observe_tool(
                        call,
                        result,
                        mutation_advanced=(
                            state.mutation_index != mutation_index_before
                        ),
                        verification_recorded=evidence_recorded,
                        mutation_epoch=state.mutation_index,
                    )
                    self._emit_progress(state, strength, source="tool")
                    if state.mutation_index != mutation_index_before:
                        self._transition_phase(state, AgentPhase.ACT)
                    if evidence_recorded:
                        evidence = state.last_verification
                        assert evidence is not None
                        self._transition_phase(state, AgentPhase.VERIFY)
                        if evidence.status in _FAILED_VERIFICATION_STATUSES:
                            self._transition_phase(state, AgentPhase.ACT)
                            state.progress.activate_checkpoint()
                            self._emit(
                                EventType.DECISION_CHECKPOINT,
                                {
                                    "reason": "verification_failure",
                                    "phase": state.progress.phase.value,
                                    "main_calls_remaining": max(
                                        0,
                                        limits.max_main_logical_calls
                                        - state.main_model_call_count,
                                    ),
                                },
                            )
                    if self._is_cancellation_requested():
                        return self._interrupt(
                            state,
                            response.tool_calls[index + 1 :],
                        )
                state.progress.finish_main_turn()
                progress_turn_active = False
                continue

            if self._is_cancellation_requested():
                return self._interrupt(state)
            if assistant_text is not None:
                state.messages += (AssistantMessage(content=assistant_text),)
                state.status = AgentStatus.COMPLETION_CANDIDATE
                state.completion_text = assistant_text
                self._emit(
                    EventType.COMPLETION_CANDIDATE,
                    {
                        "text_chars": len(assistant_text),
                        "mutation_index": state.mutation_index,
                        "validation_index": state.validation_index,
                        "verification_status": state.verification_status.value,
                    },
                )
                zero_change_answer = (
                    state.mutation_index == 0
                    and not state.modified_paths
                    and state.verification_status is VerificationStatus.NOT_RUN
                    and state.verification_attempt_count == 0
                    and state.last_verification is None
                )
                if zero_change_answer and (
                    state.run_mode is RunMode.READ_ONLY
                    or (
                        self._verification_gate is not None
                        and not self._verification_gate.requires_execution
                    )
                ):
                    state.progress.observe_completion_candidate()
                    self._emit_progress(
                        state,
                        ProgressStrength.STRONG,
                        source="completion",
                    )
                    self._transition_phase(state, AgentPhase.FINISH)
                    state.progress.finish_main_turn()
                    progress_turn_active = False
                    state.status = AgentStatus.ANSWERED
                    return state
                if state.run_mode is RunMode.READ_ONLY:
                    if not zero_change_answer:
                        state.completion_text = None
                        return self._terminate(
                            state,
                            TerminationReason.INTERNAL_INVARIANT,
                        )
                gate = self._verification_gate
                if gate is None:
                    state.progress.observe_completion_candidate()
                    self._emit_progress(
                        state,
                        ProgressStrength.STRONG,
                        source="completion",
                    )
                    self._transition_phase(state, AgentPhase.FINISH)
                    state.progress.finish_main_turn()
                    progress_turn_active = False
                    return state
                if self._is_cancellation_requested():
                    return self._interrupt(state)
                local_integrity_pending = gate.requires_local_integrity(state)
                verification_will_execute = (
                    gate.requires_execution or local_integrity_pending
                )
                if verification_will_execute:
                    self._transition_phase(state, AgentPhase.VERIFY)
                    reason = self._policy_reason(
                        state,
                        NextOperation.VERIFICATION,
                        verification_reserve_active=(
                            state.required_verification_pending
                        ),
                    )
                    if reason is not None:
                        source = (
                            "user_verify"
                            if gate.requires_execution
                            else "local_integrity"
                        )
                        self._emit(
                            EventType.VERIFICATION_BLOCKED,
                            {
                                "source": source,
                                "reason": reason.value,
                                "mutation_index": state.mutation_index,
                                "executed": False,
                            },
                        )
                        return self._terminate(state, reason)
                    if gate.requires_execution:
                        required_command = gate._required_command
                        assert required_command is not None
                        source = required_command.source.value
                        command = required_command.normalized_command
                    else:
                        source = CommandSource.LOCAL_INTEGRITY.value
                        command = "builtin:validate_changed_files"
                    self._emit(
                        EventType.VERIFICATION_STARTED,
                        {
                            "source": source,
                            "command_hash": self._hash_text(
                                command
                            ),
                            "mutation_index": state.mutation_index,
                            "attempt_index": state.verification_attempt_count + 1,
                        },
                    )
                    state.tool_call_count += 1
                try:
                    decision = gate.evaluate(state)
                except VerificationError:
                    return self._terminate(
                        state,
                        TerminationReason.INTERNAL_INVARIANT,
                    )
                if self._is_cancellation_requested():
                    return self._interrupt(state)
                if decision.command_executed and decision.result is not None:
                    self._emit(
                        EventType.VERIFICATION_COMPLETED,
                        self._verification_event_data(decision.result),
                    )
                if decision.outcome is VerificationOutcome.SUCCESS:
                    state.required_verification_pending = False
                    state.progress.observe_completion_candidate()
                    self._emit_progress(
                        state,
                        ProgressStrength.STRONG,
                        source="completion",
                    )
                    self._transition_phase(state, AgentPhase.FINISH)
                    state.progress.finish_main_turn()
                    progress_turn_active = False
                    state.status = AgentStatus.SUCCESS
                    state.termination_reason = None
                    state.failure_reason = None
                    return state
                if decision.feedback is not None:
                    state.messages += (decision.feedback,)
                if (
                    not gate.requires_execution
                    and not decision.command_executed
                    and decision.result is not None
                    and (
                        (
                            decision.result.validation_index
                            == state.mutation_index
                            and decision.result.status
                            in _FAILED_VERIFICATION_STATUSES
                        )
                        or decision.result.source
                        in {CommandSource.MODEL, CommandSource.USER_VERIFY}
                    )
                ):
                    state.progress.finish_main_turn()
                    progress_turn_active = False
                    return self._terminate(
                        state,
                        TerminationReason.CHANGES_UNVERIFIED,
                    )
                state.progress.finish_main_turn()
                progress_turn_active = False
                self._transition_phase(state, AgentPhase.ACT)
                state.status = AgentStatus.RUNNING
                state.completion_text = None
                continue

            state.progress.finish_main_turn()
            progress_turn_active = False
            state.status = AgentStatus.FAILED
            return self._terminate(
                state,
                TerminationReason.EMPTY_MODEL_RESPONSE,
            )

        return state

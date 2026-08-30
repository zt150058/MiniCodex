from __future__ import annotations

from collections.abc import Callable
import hashlib
import time
from typing import TypeAlias

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
    ModelBudgetExceeded,
    ModelCallBudget,
    ModelClient,
    ModelError,
    invoke_model,
)
from coding_agent.run_mode import RunMode
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
        if result.error is not None and result.error.startswith("security_rejected:"):
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
        state.status = AgentStatus.FAILED
        state.termination_reason = reason
        state.failure_reason = reason.value
        return state

    @staticmethod
    def _sync_budget(state: AgentState, budget: ModelCallBudget) -> None:
        state.logical_model_call_count = budget.logical_calls
        state.model_call_count = budget.provider_attempts

    def _policy_reason(
        self,
        state: AgentState,
        operation: NextOperation,
    ) -> TerminationReason | None:
        decision = self._termination_policy.check(
            state,
            self._clock(),
            next_operation=operation,
        )
        return decision.reason if decision.should_stop else None

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
        )
        limits = self._termination_policy.limits
        budget = ModelCallBudget(
            max_logical_calls=limits.max_logical_model_calls,
            max_provider_attempts=limits.max_provider_attempts,
            observer=self._event_sink,
        )
        try:
            self._emit(
                EventType.RUN_STARTED,
                {
                    "task_chars": len(task),
                    "mutation_index": state.mutation_index,
                    "run_mode": state.run_mode.value,
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
                "logical_model_calls": state.logical_model_call_count,
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

        while state.status is AgentStatus.RUNNING:
            if self._is_cancellation_requested():
                return self._interrupt(state)
            reason = self._policy_reason(state, NextOperation.MODEL)
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
            if prepared.compressed:
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

            request = ModelRequest(
                messages=state.messages,
                tool_schemas=self._tool_registry.schemas,
                continuation_items=state.continuation_items,
                instructions=self._instructions,
            )
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
            except ModelError:
                state.consecutive_model_errors += 1
                continue
            state.consecutive_model_errors = 0
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
                    reason = self._policy_reason(state, NextOperation.TOOL)
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
                    result = self._tool_registry.execute(
                        call,
                        self._execution_context,
                    )
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
                            "executed": True,
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
                    if self._is_cancellation_requested():
                        return self._interrupt(
                            state,
                            response.tool_calls[index + 1 :],
                        )
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
                if state.run_mode is RunMode.READ_ONLY:
                    if (
                        state.mutation_index != 0
                        or state.modified_paths
                        or state.verification_status
                        is not VerificationStatus.NOT_RUN
                        or state.verification_attempt_count != 0
                        or state.last_verification is not None
                    ):
                        state.completion_text = None
                        return self._terminate(
                            state,
                            TerminationReason.INTERNAL_INVARIANT,
                        )
                    state.status = AgentStatus.ANSWERED
                    return state
                gate = self._verification_gate
                if gate is None:
                    return state
                if self._is_cancellation_requested():
                    return self._interrupt(state)
                if gate.requires_execution:
                    reason = self._policy_reason(state, NextOperation.TOOL)
                    if reason is not None:
                        self._emit(
                            EventType.VERIFICATION_BLOCKED,
                            {
                                "source": "user_verify",
                                "reason": reason.value,
                                "mutation_index": state.mutation_index,
                                "executed": False,
                            },
                        )
                        return self._terminate(state, reason)
                    required_command = gate._required_command
                    assert required_command is not None
                    self._emit(
                        EventType.VERIFICATION_STARTED,
                        {
                            "source": required_command.source.value,
                            "command_hash": self._hash_text(
                                required_command.normalized_command
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
                if gate.requires_execution and decision.result is not None:
                    self._emit(
                        EventType.VERIFICATION_COMPLETED,
                        self._verification_event_data(decision.result),
                    )
                if decision.command_executed and not gate.requires_execution:
                    state.tool_call_count += 1
                if decision.outcome is VerificationOutcome.SUCCESS:
                    state.status = AgentStatus.SUCCESS
                    state.termination_reason = None
                    state.failure_reason = None
                    return state
                if decision.feedback is not None:
                    state.messages += (decision.feedback,)
                state.status = AgentStatus.RUNNING
                state.completion_text = None
                continue

            state.status = AgentStatus.FAILED
            return self._terminate(
                state,
                TerminationReason.EMPTY_MODEL_RESPONSE,
            )

        return state

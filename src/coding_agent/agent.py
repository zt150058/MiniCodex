from __future__ import annotations

from collections.abc import Callable
import time

from coding_agent.context import ContextManager, ContextPreparationError
from coding_agent.messages import (
    AssistantMessage,
    ModelRequest,
    ToolCall,
    ToolResult,
)
from coding_agent.model import (
    FatalModelError,
    ModelBudgetExceeded,
    ModelCallBudget,
    ModelClient,
    ModelError,
    invoke_model,
)
from coding_agent.state import (
    AgentState,
    AgentStatus,
    TerminationReason,
    VerificationStatus,
)
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
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._model_client = model_client
        self._tool_registry = tool_registry
        self._execution_context = execution_context
        self._context_manager = context_manager or ContextManager(
            model_client=model_client
        )
        self._termination_policy = termination_policy or TerminationPolicy()
        self._clock = clock
        self._verification_gate = verification_gate

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

    @staticmethod
    def _append_unexecuted_results(
        state: AgentState,
        calls: tuple[ToolCall, ...],
        reason: TerminationReason,
    ) -> None:
        for call in calls:
            state.messages += (
                ToolResult(
                    call_id=call.call_id,
                    tool_name=call.name,
                    status="rejected",
                    error=f"agent_terminated:{reason.value}",
                ),
            )

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
        )
        limits = self._termination_policy.limits
        budget = ModelCallBudget(
            max_logical_calls=limits.max_logical_model_calls,
            max_provider_attempts=limits.max_provider_attempts,
        )
        try:
            return self._run_loop(state, budget)
        except KeyboardInterrupt:
            self._sync_budget(state, budget)
            state.status = AgentStatus.INTERRUPTED
            state.termination_reason = TerminationReason.USER_INTERRUPTED
            state.failure_reason = TerminationReason.USER_INTERRUPTED.value
            raise AgentInterrupted(state) from None

    def _run_loop(
        self,
        state: AgentState,
        budget: ModelCallBudget,
    ) -> AgentState:

        while state.status is AgentStatus.RUNNING:
            reason = self._policy_reason(state, NextOperation.MODEL)
            if reason is not None:
                return self._terminate(state, reason)

            try:
                try:
                    prepared = self._context_manager.prepare(state, budget)
                finally:
                    self._sync_budget(state, budget)
            except ContextPreparationError as exc:
                return self._terminate(state, exc.reason)
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

            state.messages = prepared.messages
            state.continuation_items = prepared.continuation_items
            if prepared.compressed:
                reason = self._policy_reason(state, NextOperation.MODEL)
                if reason is not None:
                    return self._terminate(state, reason)

            request = ModelRequest(
                messages=state.messages,
                tool_schemas=self._tool_registry.schemas,
                continuation_items=state.continuation_items,
            )
            try:
                try:
                    response = invoke_model(self._model_client, request, budget)
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
            if response.tool_calls:
                state.messages += (
                    AssistantMessage(
                        content=assistant_text,
                        tool_calls=response.tool_calls,
                    ),
                )
                for index, call in enumerate(response.tool_calls):
                    reason = self._policy_reason(state, NextOperation.TOOL)
                    if reason is not None:
                        self._append_unexecuted_results(
                            state,
                            response.tool_calls[index:],
                            reason,
                        )
                        return self._terminate(state, reason)
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
                    if self._verification_gate is not None:
                        try:
                            self._verification_gate.observe_tool_result(
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
                continue

            if assistant_text is not None:
                state.messages += (AssistantMessage(content=assistant_text),)
                state.status = AgentStatus.COMPLETION_CANDIDATE
                state.completion_text = assistant_text
                gate = self._verification_gate
                if gate is None:
                    return state
                if gate.requires_execution:
                    reason = self._policy_reason(state, NextOperation.TOOL)
                    if reason is not None:
                        return self._terminate(state, reason)
                    state.tool_call_count += 1
                try:
                    decision = gate.evaluate(state)
                except VerificationError:
                    return self._terminate(
                        state,
                        TerminationReason.INTERNAL_INVARIANT,
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

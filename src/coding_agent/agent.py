from __future__ import annotations

from coding_agent.messages import AssistantMessage, ModelRequest, ToolResult
from coding_agent.model import ModelClient
from coding_agent.state import AgentState, AgentStatus, VerificationStatus
from coding_agent.tools.base import ExecutionContext
from coding_agent.tools.registry import ToolRegistry


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


class AgentRunner:
    def __init__(
        self,
        *,
        model_client: ModelClient,
        tool_registry: ToolRegistry,
        execution_context: ExecutionContext,
        max_rounds: int = 12,
    ) -> None:
        if (
            isinstance(max_rounds, bool)
            or not isinstance(max_rounds, int)
            or max_rounds <= 0
        ):
            raise ValueError("max_rounds must be a positive integer")
        self._model_client = model_client
        self._tool_registry = tool_registry
        self._execution_context = execution_context
        self._max_rounds = max_rounds

    def run(self, task: str) -> AgentState:
        state = AgentState.start(task)

        while state.status is AgentStatus.RUNNING:
            if state.model_call_count >= self._max_rounds:
                state.status = AgentStatus.FAILED
                state.failure_reason = "round_limit_exceeded"
                return state

            request = ModelRequest(
                messages=state.messages,
                tool_schemas=self._tool_registry.schemas,
                continuation_items=state.continuation_items,
            )
            state.model_call_count += 1
            response = self._model_client.complete(request)
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
                for call in response.tool_calls:
                    result = self._tool_registry.execute(
                        call,
                        self._execution_context,
                    )
                    state.messages += (result,)
                    _record_successful_mutation(state, result)
                    state.tool_call_count += 1
                continue

            if assistant_text is not None:
                state.messages += (AssistantMessage(content=assistant_text),)
                state.status = AgentStatus.COMPLETION_CANDIDATE
                state.completion_text = assistant_text
                return state

            state.status = AgentStatus.FAILED
            state.failure_reason = "empty_model_response"
            return state

        return state

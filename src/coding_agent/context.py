from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json

from coding_agent.messages import (
    AssistantMessage,
    JSONObject,
    Message,
    ModelRequest,
    ToolResult,
    UserMessage,
)
from coding_agent.model import (
    ModelCallBudget,
    ModelClient,
    TransientModelError,
    invoke_model,
)
from coding_agent.state import AgentState, TerminationReason


class SummarySource(StrEnum):
    NONE = "none"
    MODEL = "model"
    FALLBACK = "fallback"


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class ContextLimits:
    max_serialized_chars: int = 60_000
    max_history_items: int = 24
    recent_turns: int = 8
    max_summary_chars: int = 12_000
    summary_max_output_tokens: int = 4096

    def __post_init__(self) -> None:
        for name in (
            "max_serialized_chars",
            "max_history_items",
            "recent_turns",
            "max_summary_chars",
            "summary_max_output_tokens",
        ):
            object.__setattr__(
                self,
                name,
                _positive_integer(getattr(self, name), name),
            )


@dataclass(frozen=True, slots=True)
class ContextSize:
    serialized_chars: int
    history_items: int


@dataclass(frozen=True, slots=True)
class ContextSummary:
    goal: str
    established_facts: tuple[str, ...]
    files_examined: tuple[str, ...]
    changes_made: tuple[str, ...]
    commands_and_results: tuple[str, ...]
    unresolved_errors: tuple[str, ...]
    open_issues: tuple[str, ...]
    verification_state: JSONObject
    avoid_repeating: tuple[str, ...]

    def to_dict(self) -> JSONObject:
        return {
            "goal": self.goal,
            "established_facts": list(self.established_facts),
            "files_examined": list(self.files_examined),
            "changes_made": list(self.changes_made),
            "commands_and_results": list(self.commands_and_results),
            "unresolved_errors": list(self.unresolved_errors),
            "open_issues": list(self.open_issues),
            "verification_state": self.verification_state,
            "avoid_repeating": list(self.avoid_repeating),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )


@dataclass(frozen=True, slots=True)
class PreparedContext:
    messages: tuple[Message, ...]
    continuation_items: tuple[object, ...] = field(repr=False)
    size: ContextSize
    compressed: bool
    summary_source: SummarySource
    summary_model_failed: bool = False


class ContextPreparationError(RuntimeError):
    def __init__(self, reason: TerminationReason) -> None:
        if not isinstance(reason, TerminationReason):
            raise TypeError("reason must be TerminationReason")
        self.reason = reason
        super().__init__(reason.value)


def _measure_messages(messages: tuple[Message, ...]) -> ContextSize:
    serialized = json.dumps(
        [message.to_dict() for message in messages],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return ContextSize(len(serialized), len(messages))


def _partition_complete_turns(
    messages: tuple[Message, ...],
) -> tuple[
    UserMessage,
    tuple[Message, ...],
    tuple[tuple[Message, ...], ...],
]:
    invariant = TerminationReason.INTERNAL_INVARIANT
    if not messages or not isinstance(messages[0], UserMessage):
        raise ContextPreparationError(invariant)

    initial = messages[0]
    index = 1
    prefix: tuple[Message, ...] = ()
    summary_marker = "coding-agent context summary\n"
    if index < len(messages) and isinstance(messages[index], UserMessage):
        if not messages[index].content.startswith(summary_marker):
            raise ContextPreparationError(invariant)
        prefix = (messages[index],)
        index += 1

    turns: list[tuple[Message, ...]] = []
    while index < len(messages):
        assistant = messages[index]
        if not isinstance(assistant, AssistantMessage):
            raise ContextPreparationError(invariant)
        turn: list[Message] = [assistant]
        index += 1
        for call in assistant.tool_calls:
            if index >= len(messages):
                raise ContextPreparationError(invariant)
            result = messages[index]
            if (
                not isinstance(result, ToolResult)
                or result.call_id != call.call_id
                or result.tool_name != call.name
            ):
                raise ContextPreparationError(invariant)
            turn.append(result)
            index += 1
        if index < len(messages) and isinstance(messages[index], ToolResult):
            raise ContextPreparationError(invariant)
        turns.append(tuple(turn))

    return initial, prefix, tuple(turns)


_SUMMARY_FIELDS = {
    "goal",
    "established_facts",
    "files_examined",
    "changes_made",
    "commands_and_results",
    "unresolved_errors",
    "open_issues",
    "verification_state",
    "avoid_repeating",
}


class _SummaryValidationError(ValueError):
    pass


def _deduplicate(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _parse_summary(text: str) -> ContextSummary:
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise _SummaryValidationError("summary must be valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != _SUMMARY_FIELDS:
        raise _SummaryValidationError("summary fields are invalid")
    if not isinstance(payload["goal"], str):
        raise _SummaryValidationError("summary goal must be a string")
    verification_state = payload["verification_state"]
    if not isinstance(verification_state, dict):
        raise _SummaryValidationError(
            "summary verification_state must be an object"
        )

    arrays: dict[str, tuple[str, ...]] = {}
    for name in _SUMMARY_FIELDS - {"goal", "verification_state"}:
        value = payload[name]
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise _SummaryValidationError(
                f"summary {name} must be an array of strings"
            )
        arrays[name] = _deduplicate(tuple(value))

    return ContextSummary(
        goal=payload["goal"],
        established_facts=arrays["established_facts"],
        files_examined=arrays["files_examined"],
        changes_made=arrays["changes_made"],
        commands_and_results=arrays["commands_and_results"],
        unresolved_errors=arrays["unresolved_errors"],
        open_issues=arrays["open_issues"],
        verification_state=dict(verification_state),
        avoid_repeating=arrays["avoid_repeating"],
    )


def _merge_local_invariants(
    summary: ContextSummary,
    state: AgentState,
) -> ContextSummary:
    local_facts = (
        f"workspace: {state.workspace}",
        f"logical_model_calls: {state.logical_model_call_count}",
        f"provider_attempts: {state.model_call_count}",
        f"tool_calls: {state.tool_call_count}",
    )
    verification = state.last_verification
    verification_state: JSONObject = {
        "status": state.verification_status.value,
        "mutation_index": state.mutation_index,
        "validation_index": (
            None if verification is None else verification.validation_index
        ),
        "command": None if verification is None else verification.command,
        "source": None if verification is None else verification.source.value,
        "exit_code": None if verification is None else verification.exit_code,
    }
    return ContextSummary(
        goal=state.task,
        established_facts=_deduplicate(summary.established_facts + local_facts),
        files_examined=summary.files_examined,
        changes_made=state.modified_paths,
        commands_and_results=summary.commands_and_results,
        unresolved_errors=summary.unresolved_errors,
        open_issues=state.open_issues,
        verification_state=verification_state,
        avoid_repeating=summary.avoid_repeating,
    )


def _render_summary_message(summary: ContextSummary) -> UserMessage:
    return UserMessage("coding-agent context summary\n" + summary.to_json())


def _summary_prompt(messages: tuple[Message, ...]) -> str:
    canonical_history = json.dumps(
        [message.to_dict() for message in messages],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    schema = {
        "goal": "string",
        "established_facts": ["string"],
        "files_examined": ["string"],
        "changes_made": ["string"],
        "commands_and_results": ["string"],
        "unresolved_errors": ["string"],
        "open_issues": ["string"],
        "verification_state": {},
        "avoid_repeating": ["string"],
    }
    return (
        "Summarize the provider-neutral history as exactly this JSON schema. "
        "Do not add fields.\n"
        + json.dumps(
            schema,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\nHistory:\n"
        + canonical_history
    )


def _bounded_newest(values: list[str]) -> tuple[str, ...]:
    return _deduplicate(tuple(value[:512] for value in values[-8:]))


def _fallback_summary(
    state: AgentState,
    messages: tuple[Message, ...],
) -> ContextSummary:
    facts: list[str] = []
    files: list[str] = []
    commands: list[str] = []
    errors: list[str] = []
    avoid: list[str] = []
    for message in messages:
        if isinstance(message, UserMessage) and message.content.startswith(
            "coding-agent context summary\n"
        ):
            try:
                prior = _parse_summary(
                    message.content.removeprefix(
                        "coding-agent context summary\n"
                    )
                )
            except _SummaryValidationError as exc:
                raise ContextPreparationError(
                    TerminationReason.INTERNAL_INVARIANT
                ) from exc
            facts.extend(prior.established_facts)
            files.extend(prior.files_examined)
            commands.extend(prior.commands_and_results)
            errors.extend(prior.unresolved_errors)
            avoid.extend(prior.avoid_repeating)
        if isinstance(message, AssistantMessage) and message.content:
            facts.append(message.content)
        if isinstance(message, AssistantMessage):
            for call in message.tool_calls:
                path = call.arguments.get("path")
                if isinstance(path, str) and call.name in {
                    "list_directory",
                    "read_file",
                    "replace_text",
                    "write_file",
                }:
                    files.append(path)
        if isinstance(message, ToolResult):
            evidence = message.output if message.status == "ok" else message.error
            evidence = evidence or ""
            if message.tool_name == "run_command":
                commands.append(
                    f"{message.tool_name} {message.status}: {evidence}"
                )
            if message.status != "ok":
                errors.append(
                    f"{message.tool_name} {message.status}: {evidence}"
                )
                avoid.append(f"repeat {message.tool_name} without a changed input")

    empty: JSONObject = {}
    summary = ContextSummary(
        goal=state.task,
        established_facts=_bounded_newest(facts),
        files_examined=_bounded_newest(files),
        changes_made=(),
        commands_and_results=_bounded_newest(commands),
        unresolved_errors=_bounded_newest(errors),
        open_issues=(),
        verification_state=empty,
        avoid_repeating=_bounded_newest(avoid),
    )
    return _merge_local_invariants(summary, state)


class ContextManager:
    def __init__(
        self,
        *,
        model_client: ModelClient,
        limits: ContextLimits = ContextLimits(),
    ) -> None:
        if not isinstance(limits, ContextLimits):
            raise TypeError("limits must be ContextLimits")
        self._model_client = model_client
        self._limits = limits

    @staticmethod
    def measure(messages: tuple[Message, ...]) -> ContextSize:
        if not isinstance(messages, tuple):
            raise TypeError("messages must be a tuple")
        return _measure_messages(messages)

    def prepare(
        self,
        state: AgentState,
        budget: ModelCallBudget,
    ) -> PreparedContext:
        if not isinstance(state, AgentState):
            raise TypeError("state must be AgentState")
        if not isinstance(budget, ModelCallBudget):
            raise TypeError("budget must be ModelCallBudget")
        size = self.measure(state.messages)
        if (
            size.serialized_chars <= self._limits.max_serialized_chars
            and size.history_items <= self._limits.max_history_items
        ):
            return PreparedContext(
                messages=state.messages,
                continuation_items=state.continuation_items,
                size=size,
                compressed=False,
                summary_source=SummarySource.NONE,
            )
        initial, prefix, turns = _partition_complete_turns(state.messages)
        removable_turn_count = len(turns) - self._limits.recent_turns
        if removable_turn_count <= 0:
            raise ContextPreparationError(
                TerminationReason.CONTEXT_BUDGET_EXHAUSTED
            )
        removed_messages = prefix + tuple(
            message
            for turn in turns[:removable_turn_count]
            for message in turn
        )
        summary_source = SummarySource.MODEL
        summary_model_failed = False
        try:
            response = invoke_model(
                self._model_client,
                ModelRequest(
                    messages=(UserMessage(_summary_prompt(removed_messages)),),
                    tool_schemas=(),
                    max_output_tokens=self._limits.summary_max_output_tokens,
                    continuation_items=(),
                ),
                budget,
            )
            if (
                response.text is None
                or not response.text.strip()
                or response.tool_calls
            ):
                raise _SummaryValidationError("summary response is invalid")
            summary = _merge_local_invariants(
                _parse_summary(response.text),
                state,
            )
            if len(summary.to_json()) > self._limits.max_summary_chars:
                raise _SummaryValidationError("summary is too large")
        except (TransientModelError, _SummaryValidationError):
            summary = _fallback_summary(state, removed_messages)
            summary_source = SummarySource.FALLBACK
            summary_model_failed = True
        if len(summary.to_json()) > self._limits.max_summary_chars:
            raise ContextPreparationError(
                TerminationReason.CONTEXT_BUDGET_EXHAUSTED
            )
        retained_messages = tuple(
            message
            for turn in turns[removable_turn_count:]
            for message in turn
        )
        messages = (initial, _render_summary_message(summary), *retained_messages)
        prepared_size = self.measure(messages)
        if (
            prepared_size.serialized_chars > self._limits.max_serialized_chars
            or prepared_size.history_items > self._limits.max_history_items
        ):
            raise ContextPreparationError(
                TerminationReason.CONTEXT_BUDGET_EXHAUSTED
            )
        return PreparedContext(
            messages=messages,
            continuation_items=(),
            size=prepared_size,
            compressed=True,
            summary_source=summary_source,
            summary_model_failed=summary_model_failed,
        )

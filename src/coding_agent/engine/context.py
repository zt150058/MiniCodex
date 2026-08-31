from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
from pathlib import PurePosixPath, PureWindowsPath

from coding_agent.engine.messages import (
    AssistantMessage,
    JSONObject,
    Message,
    ModelRequest,
    ToolResult,
    UserMessage,
)
from coding_agent.engine.model import (
    FatalModelError,
    ModelBudgetExceeded,
    ModelBudgetReason,
    ModelCallBudget,
    ModelCallPurpose,
    ModelClient,
    ModelError,
    invoke_model,
)
from coding_agent.engine.state import (
    AgentState,
    SummaryFallbackReason,
    TerminationReason,
)


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
    compression_trigger_chars: int = 48_000
    compression_target_chars: int = 33_000
    compression_trigger_items: int = 20
    compression_target_items: int = 12

    def __post_init__(self) -> None:
        for name in (
            "max_serialized_chars",
            "max_history_items",
            "recent_turns",
            "max_summary_chars",
            "summary_max_output_tokens",
            "compression_trigger_chars",
            "compression_target_chars",
            "compression_trigger_items",
            "compression_target_items",
        ):
            object.__setattr__(
                self,
                name,
                _positive_integer(getattr(self, name), name),
            )
        self._normalize_legacy_watermarks()
        if not (
            0
            < self.compression_target_chars
            < self.compression_trigger_chars
            < self.max_serialized_chars
        ):
            raise ValueError(
                "character watermarks must satisfy 0 < target < trigger < hard"
            )
        if not (
            0
            < self.compression_target_items
            < self.compression_trigger_items
            < self.max_history_items
        ):
            raise ValueError(
                "item watermarks must satisfy 0 < target < trigger < hard"
            )

    def _normalize_legacy_watermarks(self) -> None:
        if (
            self.max_serialized_chars != 60_000
            and self.compression_trigger_chars == 48_000
            and self.compression_trigger_chars >= self.max_serialized_chars
        ):
            object.__setattr__(
                self,
                "compression_trigger_chars",
                self.max_serialized_chars - 1,
            )
        if (
            self.compression_target_chars == 33_000
            and self.compression_target_chars >= self.compression_trigger_chars
        ):
            object.__setattr__(
                self,
                "compression_target_chars",
                self.compression_trigger_chars - 1,
            )
        if (
            self.max_history_items != 24
            and self.compression_trigger_items == 20
            and self.compression_trigger_items >= self.max_history_items
        ):
            object.__setattr__(
                self,
                "compression_trigger_items",
                self.max_history_items - 1,
            )
        if (
            self.compression_target_items == 12
            and self.compression_target_items >= self.compression_trigger_items
        ):
            object.__setattr__(
                self,
                "compression_target_items",
                self.compression_trigger_items - 1,
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


def _decode_summary_payload(text: str) -> object:
    normalized = text.strip()
    lines = normalized.splitlines()
    if (
        len(lines) >= 3
        and lines[0] == "```json"
        and lines[-1] == "```"
    ):
        body = "\n".join(lines[1:-1])
        if "```" in body:
            raise json.JSONDecodeError("multiple summary fences", normalized, 0)
        normalized = body
    return json.loads(normalized)


def _parse_summary(text: str) -> ContextSummary:
    try:
        payload = _decode_summary_payload(text)
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
        "workspace: configured root",
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


def _safe_summary_path(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    windows = PureWindowsPath(value)
    normalized = value.replace("\\", "/")
    posix = PurePosixPath(normalized)
    if windows.drive or windows.is_absolute() or posix.is_absolute():
        return None
    if any(part == ".." for part in posix.parts):
        return None
    safe = posix.as_posix()
    return None if safe in {"", ".."} else safe[:512]


def _fallback_summary(
    state: AgentState,
    messages: tuple[Message, ...],
    max_summary_chars: int,
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
                    safe_path = _safe_summary_path(path)
                    if safe_path is not None:
                        files.append(safe_path)
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

    for observation in state.progress.exploration.observations:
        if observation.target_label is not None:
            files.append(observation.target_label)

    empty: JSONObject = {}
    summary_without_files = ContextSummary(
        goal=state.task,
        established_facts=_bounded_newest(facts),
        files_examined=(),
        changes_made=(),
        commands_and_results=_bounded_newest(commands),
        unresolved_errors=_bounded_newest(errors),
        open_issues=(),
        verification_state=empty,
        avoid_repeating=_bounded_newest(avoid),
    )
    summary = _merge_local_invariants(summary_without_files, state)
    accepted: list[str] = []
    for target in dict.fromkeys(value[:512] for value in files):
        candidate = ContextSummary(
            goal=summary.goal,
            established_facts=summary.established_facts,
            files_examined=tuple((*accepted, target)),
            changes_made=summary.changes_made,
            commands_and_results=summary.commands_and_results,
            unresolved_errors=summary.unresolved_errors,
            open_issues=summary.open_issues,
            verification_state=summary.verification_state,
            avoid_repeating=summary.avoid_repeating,
        )
        if len(candidate.to_json()) > max_summary_chars:
            break
        accepted.append(target)
        summary = candidate
    return summary


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

    def requires_compression(self, messages: tuple[Message, ...]) -> bool:
        size = self.measure(messages)
        return (
            size.serialized_chars >= self._limits.compression_trigger_chars
            or size.history_items >= self._limits.compression_trigger_items
        )

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
        if not self.requires_compression(state.messages):
            return PreparedContext(
                messages=state.messages,
                continuation_items=state.continuation_items,
                size=size,
                compressed=False,
                summary_source=SummarySource.NONE,
            )
        initial, prefix, turns = _partition_complete_turns(state.messages)
        maximum_removable = len(turns)
        if maximum_removable <= 0:
            raise ContextPreparationError(
                TerminationReason.CONTEXT_BUDGET_EXHAUSTED
            )
        removable_turn_count = min(
            maximum_removable,
            max(1, len(turns) - self._limits.recent_turns),
        )
        removed_messages = prefix + tuple(
            message
            for turn in turns[:removable_turn_count]
            for message in turn
        )
        summary_source = SummarySource.FALLBACK
        summary_model_failed = state.summary_fallback_latched
        if state.summary_fallback_latched:
            summary = _fallback_summary(
                state,
                removed_messages,
                self._limits.max_summary_chars,
            )
        else:
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
                        instructions=None,
                    ),
                    budget,
                    purpose=ModelCallPurpose.SUMMARY,
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
            except FatalModelError:
                raise
            except ModelBudgetExceeded as exc:
                if exc.reason not in {
                    ModelBudgetReason.SUMMARY_LOGICAL_CALL_LIMIT,
                    ModelBudgetReason.SUMMARY_PROVIDER_ATTEMPT_LIMIT,
                }:
                    raise
                state.summary_fallback_latched = True
                state.summary_fallback_reason = SummaryFallbackReason.SUMMARY_BUDGET
                summary = _fallback_summary(
                    state,
                    removed_messages,
                    self._limits.max_summary_chars,
                )
                summary_source = SummarySource.FALLBACK
                summary_model_failed = True
            except ModelError:
                state.summary_fallback_latched = True
                state.summary_fallback_reason = SummaryFallbackReason.MODEL_ERROR
                summary = _fallback_summary(
                    state,
                    removed_messages,
                    self._limits.max_summary_chars,
                )
                summary_source = SummarySource.FALLBACK
                summary_model_failed = True
            except _SummaryValidationError:
                state.summary_fallback_latched = True
                state.summary_fallback_reason = SummaryFallbackReason.INVALID_SUMMARY
                summary = _fallback_summary(
                    state,
                    removed_messages,
                    self._limits.max_summary_chars,
                )
                summary_source = SummarySource.FALLBACK
                summary_model_failed = True
        for candidate_count in range(
            removable_turn_count,
            maximum_removable + 1,
        ):
            candidate_removed = prefix + tuple(
                message
                for turn in turns[:candidate_count]
                for message in turn
            )
            if candidate_count == removable_turn_count:
                candidate_summary = summary
                candidate_source = summary_source
                candidate_model_failed = summary_model_failed
            else:
                candidate_summary = _fallback_summary(
                    state,
                    candidate_removed,
                    self._limits.max_summary_chars,
                )
                candidate_source = SummarySource.FALLBACK
                candidate_model_failed = summary_model_failed
            if (
                len(candidate_summary.to_json())
                > self._limits.max_summary_chars
            ):
                raise ContextPreparationError(
                    TerminationReason.CONTEXT_BUDGET_EXHAUSTED
                )
            retained_messages = tuple(
                message
                for turn in turns[candidate_count:]
                for message in turn
            )
            messages = (
                initial,
                _render_summary_message(candidate_summary),
                *retained_messages,
            )
            prepared_size = self.measure(messages)
            if (
                prepared_size.serialized_chars
                <= self._limits.compression_target_chars
                and prepared_size.history_items
                <= self._limits.compression_target_items
            ):
                ModelRequest(messages=messages)
                return PreparedContext(
                    messages=messages,
                    continuation_items=(),
                    size=prepared_size,
                    compressed=True,
                    summary_source=candidate_source,
                    summary_model_failed=candidate_model_failed,
                )
        raise ContextPreparationError(
            TerminationReason.CONTEXT_BUDGET_EXHAUSTED
        )

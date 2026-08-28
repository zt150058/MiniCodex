from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
import math
import os
from pathlib import Path
import re
import stat
import time
from typing import Protocol
import uuid

from coding_agent.messages import JSONObject
from coding_agent.model import (
    ModelObservation,
    ModelObservationKind,
    ModelObservationSink,
)


EVENT_SCHEMA_VERSION = 1
_RUN_ID = re.compile(r"[0-9a-f]{32}")


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    MODEL_CALL_STARTED = "model_call_started"
    MODEL_CALL_COMPLETED = "model_call_completed"
    MODEL_CALL_FAILED = "model_call_failed"
    MODEL_CALL_BLOCKED = "model_call_blocked"
    PROVIDER_ATTEMPT_STARTED = "provider_attempt_started"
    PROVIDER_ATTEMPT_COMPLETED = "provider_attempt_completed"
    PROVIDER_ATTEMPT_FAILED = "provider_attempt_failed"
    PROVIDER_ATTEMPT_BLOCKED = "provider_attempt_blocked"
    CONTEXT_COMPRESSION_STARTED = "context_compression_started"
    CONTEXT_COMPRESSION_COMPLETED = "context_compression_completed"
    CONTEXT_COMPRESSION_FAILED = "context_compression_failed"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_CALL_BLOCKED = "tool_call_blocked"
    MUTATION_RECORDED = "mutation_recorded"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_COMPLETED = "verification_completed"
    VERIFICATION_EVIDENCE_RECORDED = "verification_evidence_recorded"
    VERIFICATION_BLOCKED = "verification_blocked"
    COMPLETION_CANDIDATE = "completion_candidate"
    RUN_COMPLETED = "run_completed"


@dataclass(frozen=True, slots=True)
class RunEvent:
    schema_version: int
    run_id: str
    sequence: int
    timestamp_utc: str
    elapsed_ms: int
    event_type: EventType
    data: JSONObject

    def to_dict(self) -> JSONObject:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp_utc": self.timestamp_utc,
            "elapsed_ms": self.elapsed_ms,
            "event_type": self.event_type.value,
            "data": self.data,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )


@dataclass(slots=True)
class TokenUsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    responses_with_usage: int = 0
    responses_without_usage: int = 0


@dataclass(slots=True)
class RunMetadata:
    run_id: str
    log_path: str
    started_at_utc: str
    context_compression_count: int = 0
    token_usage: TokenUsageTotals = field(default_factory=TokenUsageTotals)
    finished_elapsed_ms: int | None = None
    log_failure_code: str | None = None


class RunLogError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class EventSink(ModelObservationSink, Protocol):
    @property
    def metadata(self) -> RunMetadata: ...

    def emit(self, event_type: EventType, data: JSONObject) -> RunEvent: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise RunLogError("invalid_clock")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _is_reparse(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return path.is_symlink()
    return path.is_symlink() or bool(
        getattr(info, "st_file_attributes", 0)
        & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


_EVENT_KEYS: dict[EventType, frozenset[str]] = {
    EventType.RUN_STARTED: frozenset({"task_chars", "mutation_index"}),
    EventType.TOOL_CALL_STARTED: frozenset(
        {"ordinal", "tool_name", "call_id_hash", "mutation_index"}
    ),
    EventType.MODEL_CALL_STARTED: frozenset(
        {"purpose", "logical_call_index", "provider_attempts_before", "message_count", "tool_schema_count", "continuation_count"}
    ),
    EventType.MODEL_CALL_COMPLETED: frozenset(
        {"purpose", "logical_call_index", "provider_attempts_after", "has_text", "text_chars", "tool_call_count", "usage", "provider_response_id_hash", "continuation_count"}
    ),
    EventType.MODEL_CALL_FAILED: frozenset(
        {"purpose", "logical_call_index", "provider_attempts_after", "error_code"}
    ),
    EventType.MODEL_CALL_BLOCKED: frozenset(
        {"purpose", "reason", "logical_calls", "provider_attempts"}
    ),
    EventType.PROVIDER_ATTEMPT_STARTED: frozenset(
        {"purpose", "logical_call_index", "provider_attempt_index"}
    ),
    EventType.PROVIDER_ATTEMPT_COMPLETED: frozenset(
        {"purpose", "logical_call_index", "provider_attempt_index"}
    ),
    EventType.PROVIDER_ATTEMPT_FAILED: frozenset(
        {"purpose", "logical_call_index", "provider_attempt_index", "error_code", "retry_scheduled", "retry_delay_ms"}
    ),
    EventType.PROVIDER_ATTEMPT_BLOCKED: frozenset(
        {"purpose", "logical_call_index", "reason", "provider_attempts"}
    ),
    EventType.CONTEXT_COMPRESSION_STARTED: frozenset(
        {"before_chars", "before_items", "continuation_count"}
    ),
    EventType.CONTEXT_COMPRESSION_COMPLETED: frozenset(
        {"before_chars", "before_items", "after_chars", "after_items", "summary_source", "summary_model_failed", "continuation_cleared"}
    ),
    EventType.CONTEXT_COMPRESSION_FAILED: frozenset(
        {"before_chars", "before_items", "reason"}
    ),
    EventType.TOOL_CALL_COMPLETED: frozenset(
        {"ordinal", "tool_name", "call_id_hash", "status", "safe_error_code", "output_chars", "exit_code", "timed_out", "truncated", "duration_ms", "changed_paths", "mutation_index_before", "mutation_index_after", "executed"}
    ),
    EventType.TOOL_CALL_BLOCKED: frozenset(
        {"ordinal", "tool_name", "call_id_hash", "reason", "executed"}
    ),
    EventType.MUTATION_RECORDED: frozenset(
        {"mutation_index", "changed_paths", "verification_status"}
    ),
    EventType.VERIFICATION_STARTED: frozenset(
        {"source", "command_hash", "mutation_index", "attempt_index"}
    ),
    EventType.VERIFICATION_COMPLETED: frozenset(
        {"source", "status", "exit_code", "timed_out", "truncated", "duration_ms", "validation_index", "mutation_index", "stdout_chars", "stderr_chars", "error_code"}
    ),
    EventType.VERIFICATION_EVIDENCE_RECORDED: frozenset(
        {"source", "status", "exit_code", "timed_out", "truncated", "duration_ms", "validation_index", "mutation_index", "stdout_chars", "stderr_chars", "error_code", "command_hash"}
    ),
    EventType.VERIFICATION_BLOCKED: frozenset(
        {"source", "reason", "mutation_index", "executed"}
    ),
    EventType.COMPLETION_CANDIDATE: frozenset(
        {"text_chars", "mutation_index", "validation_index", "verification_status"}
    ),
    EventType.RUN_COMPLETED: frozenset(
        {"status", "termination_reason", "logical_model_calls", "provider_attempts", "tool_calls", "verification_attempts", "mutation_index", "validation_index", "elapsed_ms"}
    ),
}


_HASH_FIELDS = {"call_id_hash", "command_hash", "provider_response_id_hash"}
_BOOL_FIELDS = {
    "has_text", "retry_scheduled", "summary_model_failed", "continuation_cleared",
    "timed_out", "truncated", "executed",
}
_NULLABLE_INT_FIELDS = {"exit_code", "validation_index", "retry_delay_ms"}
_NONNEGATIVE_INT_FIELDS = {
    "task_chars", "mutation_index", "logical_call_index", "provider_attempts_before",
    "provider_attempts_after", "message_count", "tool_schema_count", "continuation_count",
    "text_chars", "tool_call_count", "logical_calls", "provider_attempts",
    "provider_attempt_index", "before_chars", "before_items", "after_chars", "after_items",
    "output_chars", "duration_ms", "mutation_index_before", "mutation_index_after",
    "attempt_index", "stdout_chars", "stderr_chars", "logical_model_calls", "tool_calls",
    "verification_attempts", "elapsed_ms", "ordinal",
}
_ENUM_FIELDS = {
    "purpose": {"main", "summary"},
    "status": {"ok", "error", "rejected", "not_run", "stale", "running", "completion_candidate", "passed", "failed", "timed_out", "success", "interrupted"},
    "source": {"model", "user_verify"},
    "summary_source": {"none", "model", "fallback"},
    "verification_status": {"not_run", "stale", "running", "passed", "failed", "timed_out", "error"},
}
_CREDENTIAL_PATTERNS = (
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._-]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|apikey|authorization|token|secret|password)\s*[:=]\s*\S+"),
)
_MODEL_ERROR_CODES = {
    "transient_model_error",
    "fatal_model_error",
    "invalid_model_response",
    "model_budget_exceeded",
    "model_client_error",
}
_PROVIDER_ERROR_CODES = {
    "rate_limit",
    "server_error",
    "timeout",
    "connection_error",
    "authentication_rejected",
    "permission_rejected",
    "not_found",
    "request_rejected",
    "provider_error",
}
_VERIFICATION_ERROR_CODES = {
    "verification_command_start_failed",
    "verification_internal_error",
}
_TERMINATION_REASONS = {
    "audit_log_failure",
    "logical_model_call_limit",
    "provider_attempt_limit",
    "tool_call_limit",
    "time_limit",
    "repeated_tool_call",
    "consecutive_model_errors",
    "consecutive_tool_errors",
    "consecutive_safety_rejections",
    "context_budget_exhausted",
    "fatal_model_error",
    "empty_model_response",
    "internal_invariant",
    "user_interrupted",
}
_SAFETY_CODES = {
    "invalid_path",
    "workspace_invalid",
    "path_outside_workspace",
    "path_not_found",
    "path_type_mismatch",
    "parent_not_found",
    "protected_path",
    "reparse_point_denied",
    "command_parse_error",
    "shell_syntax_denied",
    "executable_denied",
    "argument_denied",
    "git_subcommand_denied",
}


def scrub_text(value: str, sensitive_values: tuple[str, ...]) -> str:
    result = value
    for secret in sensitive_values:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    for pattern in _CREDENTIAL_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def _validate_data(
    event_type: EventType,
    data: JSONObject,
    sensitive_values: tuple[str, ...],
) -> JSONObject:
    if not isinstance(event_type, EventType) or not isinstance(data, dict):
        raise RunLogError("invalid_event_data")
    expected = _EVENT_KEYS.get(event_type)
    if expected is None or set(data) != expected:
        raise RunLogError("invalid_event_data")
    normalized: JSONObject = {}
    for key, value in data.items():
        if key in _HASH_FIELDS:
            if value is not None and (
                not isinstance(value, str)
                or re.fullmatch(r"[0-9a-f]{64}", value) is None
            ):
                raise RunLogError("invalid_event_data")
        elif key in _BOOL_FIELDS:
            if not isinstance(value, bool):
                raise RunLogError("invalid_event_data")
        elif key in _NULLABLE_INT_FIELDS:
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                raise RunLogError("invalid_event_data")
            if key != "exit_code" and value is not None and value < 0:
                raise RunLogError("invalid_event_data")
        elif key in _NONNEGATIVE_INT_FIELDS:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RunLogError("invalid_event_data")
            if key == "ordinal" and value == 0:
                raise RunLogError("invalid_event_data")
        elif key in _ENUM_FIELDS:
            if not isinstance(value, str) or value not in _ENUM_FIELDS[key]:
                raise RunLogError("invalid_event_data")
        elif key == "changed_paths":
            if (
                not isinstance(value, list)
                or len(value) > 40
                or any(
                    not isinstance(path, str)
                    or not path
                    or len(path) > 260
                    or any(ord(character) < 32 for character in path)
                    for path in value
                )
                or len(set(value)) != len(value)
            ):
                raise RunLogError("invalid_event_data")
            value = [scrub_text(path, sensitive_values) for path in value]
        elif key == "usage":
            if value is not None and (
                not isinstance(value, dict)
                or set(value) != {"input_tokens", "output_tokens", "total_tokens"}
                or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in value.values())
            ):
                raise RunLogError("invalid_event_data")
        elif key == "tool_name":
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 128
                or any(ord(character) < 32 for character in value)
            ):
                raise RunLogError("invalid_event_data")
            value = scrub_text(value, sensitive_values)
        elif key in {"safe_error_code", "error_code", "reason", "termination_reason"}:
            if value is not None and (
                not isinstance(value, str) or not value or len(value) > 260
            ):
                raise RunLogError("invalid_event_data")
            if isinstance(value, str):
                value = scrub_text(value, sensitive_values)
        else:
            raise RunLogError("invalid_event_data")
        normalized[key] = value

    status = normalized.get("status")
    if event_type is EventType.TOOL_CALL_COMPLETED and status not in {
        "ok", "error", "rejected"
    }:
        raise RunLogError("invalid_event_data")
    if event_type in {
        EventType.VERIFICATION_COMPLETED,
        EventType.VERIFICATION_EVIDENCE_RECORDED,
    } and status not in {"passed", "failed", "timed_out", "error"}:
        raise RunLogError("invalid_event_data")
    if event_type is EventType.RUN_COMPLETED and status not in {
        "completion_candidate", "success", "failed", "interrupted"
    }:
        raise RunLogError("invalid_event_data")
    if event_type in {
        EventType.MODEL_CALL_FAILED,
    } and normalized.get("error_code") not in _MODEL_ERROR_CODES:
        raise RunLogError("invalid_event_data")
    if event_type is EventType.PROVIDER_ATTEMPT_FAILED and normalized.get(
        "error_code"
    ) not in _PROVIDER_ERROR_CODES:
        raise RunLogError("invalid_event_data")
    if event_type in {
        EventType.VERIFICATION_COMPLETED,
        EventType.VERIFICATION_EVIDENCE_RECORDED,
    } and normalized.get("error_code") not in _VERIFICATION_ERROR_CODES | {None}:
        raise RunLogError("invalid_event_data")
    safe_error = normalized.get("safe_error_code")
    if event_type is EventType.TOOL_CALL_COMPLETED and safe_error is not None:
        valid_tool_error = safe_error in {"tool_error", "tool_rejected"} or (
            isinstance(safe_error, str)
            and safe_error.startswith("security_rejected:")
            and safe_error.removeprefix("security_rejected:") in _SAFETY_CODES
        )
        if not valid_tool_error:
            raise RunLogError("invalid_event_data")
    if event_type in {
        EventType.MODEL_CALL_BLOCKED,
        EventType.PROVIDER_ATTEMPT_BLOCKED,
    }:
        allowed_reason = {
            EventType.MODEL_CALL_BLOCKED: "logical_model_call_limit",
            EventType.PROVIDER_ATTEMPT_BLOCKED: "provider_attempt_limit",
        }[event_type]
        if normalized.get("reason") != allowed_reason:
            raise RunLogError("invalid_event_data")
    if event_type in {
        EventType.CONTEXT_COMPRESSION_FAILED,
        EventType.TOOL_CALL_BLOCKED,
        EventType.VERIFICATION_BLOCKED,
    } and normalized.get("reason") not in _TERMINATION_REASONS:
        raise RunLogError("invalid_event_data")
    if event_type is EventType.RUN_COMPLETED and normalized.get(
        "termination_reason"
    ) not in _TERMINATION_REASONS | {None}:
        raise RunLogError("invalid_event_data")
    for hash_field in _HASH_FIELDS & set(normalized):
        if (
            normalized[hash_field] is None
            and hash_field != "provider_response_id_hash"
        ):
            raise RunLogError("invalid_event_data")
    for positive_field in {
        "logical_call_index",
        "provider_attempt_index",
        "attempt_index",
        "ordinal",
    } & set(normalized):
        if normalized[positive_field] == 0:
            raise RunLogError("invalid_event_data")
    return normalized


class RunEventLogger(ModelObservationSink):
    def __init__(
        self,
        *,
        stream: object,
        metadata: RunMetadata,
        utc_clock: Callable[[], datetime],
        monotonic_clock: Callable[[], float],
        started_monotonic: float,
        sensitive_values: tuple[str, ...],
    ) -> None:
        self._stream = stream
        self._metadata = metadata
        self._utc_clock = utc_clock
        self._monotonic_clock = monotonic_clock
        self._started_monotonic = started_monotonic
        self._sensitive_values = sensitive_values
        self._sequence = 0
        self._provider_attempts_observed = 0
        self._poisoned = False
        self._closed = False

    @classmethod
    def create(
        cls,
        workspace: Path,
        *,
        run_id: str | None = None,
        sensitive_values: tuple[str, ...] = (),
        utc_clock: Callable[[], datetime] = _utc_now,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> RunEventLogger:
        if not isinstance(sensitive_values, tuple) or any(
            not isinstance(value, str) for value in sensitive_values
        ):
            raise TypeError("sensitive_values must be a tuple of strings")
        try:
            root = Path(workspace).resolve(strict=True)
        except OSError:
            raise RunLogError("invalid_workspace") from None
        if not root.is_dir() or _is_reparse(Path(os.path.abspath(workspace))):
            raise RunLogError("invalid_workspace")
        if run_id is not None and (
            not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None
        ):
            raise RunLogError("invalid_run_id")
        internal = root / ".coding-agent"
        logs = internal / "logs"
        for directory in (internal, logs):
            if directory.exists() and (_is_reparse(directory) or not directory.is_dir()):
                raise RunLogError("log_path_reparse" if _is_reparse(directory) else "log_directory_invalid")
            try:
                directory.mkdir(exist_ok=True)
            except OSError:
                raise RunLogError("log_directory_invalid") from None
            if _is_reparse(directory):
                raise RunLogError("log_path_reparse")
            try:
                resolved = directory.resolve(strict=True)
                common = os.path.commonpath((str(root), str(resolved)))
            except (OSError, ValueError):
                raise RunLogError("log_path_outside_workspace") from None
            if os.path.normcase(common) != os.path.normcase(str(root)):
                raise RunLogError("log_path_outside_workspace")
        stream = None
        selected = run_id
        attempts = 1 if run_id is not None else 16
        for _ in range(attempts):
            selected = run_id if run_id is not None else uuid.uuid4().hex
            if _RUN_ID.fullmatch(selected) is None:
                raise RunLogError("invalid_run_id")
            path = logs / f"{selected}.jsonl"
            try:
                stream = path.open("x", encoding="utf-8", newline="\n")
                break
            except FileExistsError:
                if run_id is not None:
                    raise RunLogError("log_file_exists") from None
                continue
            except OSError:
                raise RunLogError("log_write_failed") from None
        if stream is None or selected is None:
            raise RunLogError("run_id_collision")
        started_utc = _timestamp(utc_clock())
        started_mono = monotonic_clock()
        if (
            isinstance(started_mono, bool)
            or not isinstance(started_mono, (int, float))
            or not math.isfinite(started_mono)
            or started_mono < 0
        ):
            stream.close()
            raise RunLogError("invalid_clock")
        return cls(
            stream=stream,
            metadata=RunMetadata(
                run_id=selected,
                log_path=f".coding-agent/logs/{selected}.jsonl",
                started_at_utc=started_utc,
            ),
            utc_clock=utc_clock,
            monotonic_clock=monotonic_clock,
            started_monotonic=float(started_mono),
            sensitive_values=sensitive_values,
        )

    @property
    def metadata(self) -> RunMetadata:
        return self._metadata

    def emit(self, event_type: EventType, data: JSONObject) -> RunEvent:
        if self._poisoned or self._closed:
            raise RunLogError("log_unavailable")
        safe_data = _validate_data(event_type, data, self._sensitive_values)
        now = self._monotonic_clock()
        if (
            isinstance(now, bool)
            or not isinstance(now, (int, float))
            or not math.isfinite(now)
            or now < self._started_monotonic
        ):
            raise RunLogError("invalid_clock")
        event = RunEvent(
            schema_version=EVENT_SCHEMA_VERSION,
            run_id=self._metadata.run_id,
            sequence=self._sequence + 1,
            timestamp_utc=_timestamp(self._utc_clock()),
            elapsed_ms=int((now - self._started_monotonic) * 1000),
            event_type=event_type,
            data=safe_data,
        )
        try:
            line = event.to_json()
        except (TypeError, ValueError):
            self._poisoned = True
            self._metadata.log_failure_code = "event_serialization_failed"
            raise RunLogError("event_serialization_failed") from None
        try:
            self._stream.write(line + "\n")
        except (OSError, UnicodeError):
            self._poisoned = True
            self._metadata.log_failure_code = "log_write_failed"
            raise RunLogError("log_write_failed") from None
        try:
            self._stream.flush()
        except OSError:
            self._poisoned = True
            self._metadata.log_failure_code = "log_flush_failed"
            raise RunLogError("log_flush_failed") from None
        self._sequence = event.sequence
        return event

    def observe_model(self, observation: ModelObservation) -> None:
        if not isinstance(observation, ModelObservation):
            raise RunLogError("invalid_event_data")
        purpose = observation.purpose.value
        kind = observation.kind
        if kind is ModelObservationKind.LOGICAL_STARTED:
            self.emit(
                EventType.MODEL_CALL_STARTED,
                {
                    "purpose": purpose,
                    "logical_call_index": observation.logical_call_index,
                    "provider_attempts_before": self._provider_attempts_observed,
                    "message_count": observation.message_count,
                    "tool_schema_count": observation.tool_schema_count,
                    "continuation_count": observation.continuation_count,
                },
            )
            return
        if kind is ModelObservationKind.LOGICAL_COMPLETED:
            usage = (
                None
                if observation.usage is None
                else observation.usage.to_dict()
            )
            self.emit(
                EventType.MODEL_CALL_COMPLETED,
                {
                    "purpose": purpose,
                    "logical_call_index": observation.logical_call_index,
                    "provider_attempts_after": self._provider_attempts_observed,
                    "has_text": observation.has_text,
                    "text_chars": observation.text_chars,
                    "tool_call_count": observation.tool_call_count,
                    "usage": usage,
                    "provider_response_id_hash": observation.provider_response_id_hash,
                    "continuation_count": observation.continuation_count,
                },
            )
            totals = self._metadata.token_usage
            if observation.usage is None:
                totals.responses_without_usage += 1
            else:
                totals.input_tokens += observation.usage.input_tokens
                totals.output_tokens += observation.usage.output_tokens
                totals.total_tokens += observation.usage.total_tokens
                totals.responses_with_usage += 1
            return
        if kind is ModelObservationKind.LOGICAL_FAILED:
            self.emit(
                EventType.MODEL_CALL_FAILED,
                {
                    "purpose": purpose,
                    "logical_call_index": observation.logical_call_index,
                    "provider_attempts_after": self._provider_attempts_observed,
                    "error_code": observation.error_code,
                },
            )
            return
        if kind is ModelObservationKind.LOGICAL_BLOCKED:
            self.emit(
                EventType.MODEL_CALL_BLOCKED,
                {
                    "purpose": purpose,
                    "reason": observation.error_code,
                    "logical_calls": observation.logical_call_index - 1,
                    "provider_attempts": self._provider_attempts_observed,
                },
            )
            return
        if kind is ModelObservationKind.PROVIDER_STARTED:
            self.emit(
                EventType.PROVIDER_ATTEMPT_STARTED,
                {
                    "purpose": purpose,
                    "logical_call_index": observation.logical_call_index,
                    "provider_attempt_index": observation.provider_attempt_index,
                },
            )
            assert observation.provider_attempt_index is not None
            self._provider_attempts_observed = observation.provider_attempt_index
            return
        if kind is ModelObservationKind.PROVIDER_COMPLETED:
            self.emit(
                EventType.PROVIDER_ATTEMPT_COMPLETED,
                {
                    "purpose": purpose,
                    "logical_call_index": observation.logical_call_index,
                    "provider_attempt_index": observation.provider_attempt_index,
                },
            )
            return
        if kind is ModelObservationKind.PROVIDER_FAILED:
            self.emit(
                EventType.PROVIDER_ATTEMPT_FAILED,
                {
                    "purpose": purpose,
                    "logical_call_index": observation.logical_call_index,
                    "provider_attempt_index": observation.provider_attempt_index,
                    "error_code": observation.error_code,
                    "retry_scheduled": observation.retry_scheduled,
                    "retry_delay_ms": observation.retry_delay_ms,
                },
            )
            return
        if kind is ModelObservationKind.PROVIDER_BLOCKED:
            self.emit(
                EventType.PROVIDER_ATTEMPT_BLOCKED,
                {
                    "purpose": purpose,
                    "logical_call_index": observation.logical_call_index,
                    "reason": observation.error_code,
                    "provider_attempts": self._provider_attempts_observed,
                },
            )
            return
        raise RunLogError("invalid_event_data")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._stream.close()
        except OSError:
            if self._metadata.log_failure_code is None:
                self._metadata.log_failure_code = "log_close_failed"
            raise RunLogError("log_close_failed") from None

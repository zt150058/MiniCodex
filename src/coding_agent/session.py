from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
import math
from pathlib import PurePosixPath, PureWindowsPath
import re
import uuid

from coding_agent.messages import JSONObject, JSONValue


MAX_USER_MESSAGE_BYTES = 65_536
MAX_ASSISTANT_TEXT_BYTES = 262_144
MAX_EVENT_JSON_BYTES = 65_536
MAX_PERSISTED_REPORT_BYTES = 524_288

_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
_SAFE_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")
_TOOL_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


class _FrozenJSONDict(dict[str, JSONValue]):
    @staticmethod
    def _immutable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("session JSON values are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class _FrozenJSONList(list[JSONValue]):
    @staticmethod
    def _immutable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("session JSON values are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable


class SessionStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"


class SessionRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class PersistedSessionEventKind(StrEnum):
    USER_MESSAGE = "user_message"
    RUN_QUEUED = "run_queued"
    RUN_STARTED = "run_started"
    ASSISTANT_TEXT_COMMITTED = "assistant_text_committed"
    TOOL_ACTIVITY = "tool_activity"
    VERIFICATION_ACTIVITY = "verification_activity"
    CANCELLATION_REQUESTED = "cancellation_requested"
    RUN_FINISHED = "run_finished"
    RUN_RECOVERED = "run_recovered"


class SessionNarrativeKind(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    RUN_SUMMARY = "run_summary"


class SessionError(RuntimeError):
    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("session error code must be a non-empty string")
        self.code = code.strip()
        super().__init__(self.code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.code!r})"


class SessionStoreError(SessionError):
    pass


class SessionControllerError(SessionError):
    pass


def _require_text(value: object, *, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SessionError(code)
    return value


def _require_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase UUID hex string")
    return value


def _require_optional_id(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_id(value, field_name)


def _require_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _require_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _require_timestamp(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field_name} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{field_name} must be a UTC timestamp")
    return value


def _require_optional_timestamp(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_timestamp(value, field_name)


def _normalize_json_value(value: object, field_name: str) -> JSONValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} contains a non-finite float")
        return value
    if isinstance(value, (list, tuple)):
        return _FrozenJSONList(
            [_normalize_json_value(item, field_name) for item in value]
        )
    if isinstance(value, Mapping):
        normalized: JSONObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{field_name} contains a non-string key")
            normalized[key] = _normalize_json_value(item, field_name)
        return _FrozenJSONDict(normalized)
    raise ValueError(f"{field_name} contains a non-JSON value")


def _normalize_json_object(value: object, field_name: str) -> JSONObject:
    normalized = _normalize_json_value(value, field_name)
    if not isinstance(normalized, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return normalized


def _encoded_json_size(value: JSONObject) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def _normalize_event_data(
    kind: PersistedSessionEventKind,
    value: object,
) -> JSONObject:
    data = _normalize_json_object(value, "data")
    if kind is PersistedSessionEventKind.USER_MESSAGE:
        _require_exact_keys(data, {"content"}, "user_message")
        _require_bounded_content(data["content"], MAX_USER_MESSAGE_BYTES)
    elif kind is PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED:
        _require_exact_keys(data, {"content"}, "assistant_text_committed")
        _require_bounded_content(data["content"], MAX_ASSISTANT_TEXT_BYTES)
    elif kind is PersistedSessionEventKind.RUN_QUEUED:
        _require_exact_status(data, "queued")
    elif kind is PersistedSessionEventKind.RUN_STARTED:
        _require_exact_status(data, "running")
    elif kind is PersistedSessionEventKind.CANCELLATION_REQUESTED:
        _require_exact_status(data, "cancelling")
    elif kind is PersistedSessionEventKind.RUN_RECOVERED:
        _require_exact_keys(
            data,
            {"status", "termination_reason"},
            "run_recovered",
        )
        if data["status"] != "interrupted" or data["termination_reason"] != "process_restarted":
            raise ValueError("run_recovered data is invalid")
    elif kind is PersistedSessionEventKind.RUN_FINISHED:
        _validate_safe_summary_data(data)
    elif kind is PersistedSessionEventKind.TOOL_ACTIVITY:
        _validate_tool_activity(data)
    elif kind is PersistedSessionEventKind.VERIFICATION_ACTIVITY:
        _validate_verification_activity(data)
    if kind not in {
        PersistedSessionEventKind.USER_MESSAGE,
        PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED,
    } and _encoded_json_size(data) > MAX_EVENT_JSON_BYTES:
        raise ValueError("event data exceeds its byte limit")
    return data


def _require_exact_keys(data: JSONObject, keys: set[str], kind: str) -> None:
    if set(data) != keys:
        raise ValueError(f"{kind} data has invalid fields")


def _require_bounded_content(value: object, limit: int) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("message event content must be a non-empty string")
    if len(value.encode("utf-8")) > limit:
        raise ValueError("message event content exceeds its byte limit")


def _require_exact_status(data: JSONObject, status: str) -> None:
    _require_exact_keys(data, {"status"}, status)
    if data["status"] != status:
        raise ValueError("lifecycle event status is invalid")


def _require_optional_integer(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer or null")
    return value


def _require_optional_safe_code(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _SAFE_CODE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a safe code or null")
    return value


def _validate_tool_activity(data: JSONObject) -> None:
    _require_exact_keys(
        data,
        {
            "tool_name",
            "status",
            "duration_ms",
            "truncated",
            "exit_code",
            "safe_error_code",
            "changed_paths",
        },
        "tool_activity",
    )
    if (
        not isinstance(data["tool_name"], str)
        or _TOOL_NAME_PATTERN.fullmatch(data["tool_name"]) is None
    ):
        raise ValueError("tool_name is invalid")
    if data["status"] not in {"ok", "error", "rejected"}:
        raise ValueError("tool activity status is invalid")
    _require_non_negative_int(data["duration_ms"], "duration_ms")
    if not isinstance(data["truncated"], bool):
        raise ValueError("truncated must be a boolean")
    _require_optional_integer(data["exit_code"], "exit_code")
    _require_optional_safe_code(data["safe_error_code"], "safe_error_code")
    for path in _require_changed_paths(data["changed_paths"]):
        _require_normalized_relative_path(path, "changed_paths")


def _validate_verification_activity(data: JSONObject) -> None:
    _require_exact_keys(
        data,
        {
            "status",
            "source",
            "exit_code",
            "timed_out",
            "truncated",
            "duration_ms",
            "validation_index",
            "error_code",
        },
        "verification_activity",
    )
    if data["status"] not in {
        "not_run",
        "stale",
        "running",
        "passed",
        "failed",
        "timed_out",
        "error",
    }:
        raise ValueError("verification status is invalid")
    if data["source"] not in {None, "model", "user_verify"}:
        raise ValueError("verification source is invalid")
    _require_optional_integer(data["exit_code"], "exit_code")
    if not isinstance(data["timed_out"], bool) or not isinstance(data["truncated"], bool):
        raise ValueError("verification flags must be booleans")
    _require_optional_non_negative_int(data["duration_ms"], "duration_ms")
    _require_optional_non_negative_int(data["validation_index"], "validation_index")
    _require_optional_safe_code(data["error_code"], "error_code")


_SAFE_SUMMARY_FIELDS = {
    "status",
    "exit_code",
    "termination_reason",
    "changed_paths",
    "verification_status",
    "mutation_index",
    "validation_index",
    "logical_model_calls",
    "provider_attempts",
    "tool_calls",
    "verification_attempts",
}


def _validate_safe_summary_data(data: JSONObject) -> None:
    _require_exact_keys(data, _SAFE_SUMMARY_FIELDS, "run_finished")
    if data["status"] not in {"success", "failed", "interrupted"}:
        raise ValueError("run summary status is invalid")
    _require_optional_integer(data["exit_code"], "exit_code")
    _require_optional_safe_code(data["termination_reason"], "termination_reason")
    for path in _require_changed_paths(data["changed_paths"]):
        _require_normalized_relative_path(path, "changed_paths")
    verification_status = data["verification_status"]
    if verification_status is not None and verification_status not in {
        "not_run",
        "stale",
        "running",
        "passed",
        "failed",
        "timed_out",
        "error",
    }:
        raise ValueError("verification_status is invalid")
    for field_name in (
        "mutation_index",
        "validation_index",
        "logical_model_calls",
        "provider_attempts",
        "tool_calls",
        "verification_attempts",
    ):
        _require_optional_non_negative_int(data[field_name], field_name)


def _require_enum(value: object, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    if type(value) is not enum_type:
        raise TypeError(f"{field_name} must use {enum_type.__name__}")
    return value


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    title: str
    status: SessionStatus
    created_at_utc: str
    updated_at_utc: str
    last_run_id: str | None
    next_sequence: int

    def __post_init__(self) -> None:
        _require_id(self.session_id, "session_id")
        if not isinstance(self.title, str) or not self.title.strip() or len(self.title) > 80:
            raise ValueError("title must contain between 1 and 80 code points")
        _require_enum(self.status, SessionStatus, "status")
        _require_timestamp(self.created_at_utc, "created_at_utc")
        _require_timestamp(self.updated_at_utc, "updated_at_utc")
        _require_optional_id(self.last_run_id, "last_run_id")
        _require_positive_int(self.next_sequence, "next_sequence")


@dataclass(frozen=True, slots=True)
class SessionRunRecord:
    run_id: str
    session_id: str
    ordinal: int
    status: SessionRunStatus
    user_event_sequence: int
    started_at_utc: str | None
    finished_at_utc: str | None
    agent_status: str | None
    termination_reason: str | None
    audit_run_id: str | None
    final_report: JSONObject | None = field(repr=False)

    def __post_init__(self) -> None:
        _require_id(self.run_id, "run_id")
        _require_id(self.session_id, "session_id")
        _require_positive_int(self.ordinal, "ordinal")
        _require_enum(self.status, SessionRunStatus, "status")
        _require_positive_int(self.user_event_sequence, "user_event_sequence")
        _require_optional_timestamp(self.started_at_utc, "started_at_utc")
        _require_optional_timestamp(self.finished_at_utc, "finished_at_utc")
        for field_name, value in (
            ("agent_status", self.agent_status),
            ("termination_reason", self.termination_reason),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field_name} must be a non-empty string or null")
        _require_optional_id(self.audit_run_id, "audit_run_id")

        terminal = self.status in {
            SessionRunStatus.SUCCEEDED,
            SessionRunStatus.FAILED,
            SessionRunStatus.INTERRUPTED,
        }
        if terminal:
            if self.finished_at_utc is None:
                raise ValueError("terminal run requires a finish time")
        elif any(
            value is not None
            for value in (
                self.finished_at_utc,
                self.agent_status,
                self.termination_reason,
                self.audit_run_id,
                self.final_report,
            )
        ):
            raise ValueError("nonterminal run contains terminal fields")
        if self.status is SessionRunStatus.QUEUED and self.started_at_utc is not None:
            raise ValueError("queued run cannot have a start time")
        if self.status in {SessionRunStatus.RUNNING, SessionRunStatus.CANCELLING} and self.started_at_utc is None:
            raise ValueError("active run requires a start time")
        if self.final_report is not None:
            normalized = _normalize_json_object(self.final_report, "final_report")
            if _encoded_json_size(normalized) > MAX_PERSISTED_REPORT_BYTES:
                raise ValueError("final_report exceeds its byte limit")
            object.__setattr__(self, "final_report", normalized)


@dataclass(frozen=True, slots=True)
class SessionEvent:
    session_id: str
    run_id: str | None
    sequence: int
    kind: PersistedSessionEventKind
    created_at_utc: str
    data: JSONObject = field(repr=False)

    def __post_init__(self) -> None:
        _require_id(self.session_id, "session_id")
        _require_optional_id(self.run_id, "run_id")
        _require_positive_int(self.sequence, "sequence")
        _require_enum(self.kind, PersistedSessionEventKind, "kind")
        _require_timestamp(self.created_at_utc, "created_at_utc")
        object.__setattr__(self, "data", _normalize_event_data(self.kind, self.data))


@dataclass(frozen=True, slots=True)
class SessionSubmission:
    session: SessionRecord
    user_event: SessionEvent
    run: SessionRunRecord

    def __post_init__(self) -> None:
        if not isinstance(self.session, SessionRecord):
            raise TypeError("session must use SessionRecord")
        if not isinstance(self.user_event, SessionEvent):
            raise TypeError("user_event must use SessionEvent")
        if not isinstance(self.run, SessionRunRecord):
            raise TypeError("run must use SessionRunRecord")
        if (
            self.session.session_id != self.user_event.session_id
            or self.session.session_id != self.run.session_id
            or self.user_event.run_id != self.run.run_id
        ):
            raise ValueError("submission identities do not match")
        if self.user_event.kind is not PersistedSessionEventKind.USER_MESSAGE:
            raise ValueError("submission user_event must be a user message")


@dataclass(frozen=True, slots=True)
class SessionNarrativeEntry:
    run_id: str
    kind: SessionNarrativeKind
    content: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_id(self.run_id, "run_id")
        _require_enum(self.kind, SessionNarrativeKind, "kind")
        if not isinstance(self.content, str) or not self.content:
            raise ValueError("content must be a non-empty string")
        limit = (
            MAX_ASSISTANT_TEXT_BYTES
            if self.kind is SessionNarrativeKind.ASSISTANT
            else MAX_USER_MESSAGE_BYTES
        )
        if len(self.content.encode("utf-8")) > limit:
            raise ValueError("narrative content exceeds its byte limit")


@dataclass(frozen=True, slots=True)
class NewSessionEvent:
    session_id: str
    run_id: str | None
    kind: PersistedSessionEventKind
    data: JSONObject = field(repr=False)

    def __post_init__(self) -> None:
        _require_id(self.session_id, "session_id")
        _require_optional_id(self.run_id, "run_id")
        _require_enum(self.kind, PersistedSessionEventKind, "kind")
        object.__setattr__(self, "data", _normalize_event_data(self.kind, self.data))


@dataclass(frozen=True, slots=True)
class SessionRunResult:
    run_id: str
    status: SessionRunStatus
    agent_status: str | None
    termination_reason: str | None
    audit_run_id: str | None
    safe_summary: JSONObject = field(repr=False)
    final_report: JSONObject | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_id(self.run_id, "run_id")
        _require_enum(self.status, SessionRunStatus, "status")
        if self.status not in {
            SessionRunStatus.SUCCEEDED,
            SessionRunStatus.FAILED,
            SessionRunStatus.INTERRUPTED,
        }:
            raise ValueError("run result status must be terminal")
        if self.agent_status is not None and (
            not isinstance(self.agent_status, str) or not self.agent_status.strip()
        ):
            raise ValueError("agent_status must be a non-empty string or null")
        if self.termination_reason is not None and (
            not isinstance(self.termination_reason, str) or not self.termination_reason.strip()
        ):
            raise ValueError("termination_reason must be a non-empty string or null")
        _require_optional_id(self.audit_run_id, "audit_run_id")
        summary = _normalize_json_object(self.safe_summary, "safe_summary")
        if _encoded_json_size(summary) > MAX_EVENT_JSON_BYTES:
            raise ValueError("safe_summary exceeds its byte limit")
        object.__setattr__(self, "safe_summary", summary)
        if self.final_report is not None:
            report = _normalize_json_object(self.final_report, "final_report")
            if _encoded_json_size(report) > MAX_PERSISTED_REPORT_BYTES:
                raise ValueError("final_report exceeds its byte limit")
            object.__setattr__(self, "final_report", report)


def _require_optional_non_negative_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_non_negative_int(value, field_name)


def _require_optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string or null")
    return value


def _require_changed_paths(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("changed_paths must be a list of strings")
    paths: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError("changed_paths must be a list of strings")
        paths.append(item)
    return paths


def make_safe_run_summary(
    report: JSONObject | None,
    *,
    status: str,
    termination_reason: str | None,
) -> JSONObject:
    if not isinstance(status, str) or not status.strip():
        raise ValueError("status must be a non-empty string")
    normalized_reason = _require_optional_text(termination_reason, "termination_reason")
    if report is None:
        return {
            "status": status,
            "exit_code": None,
            "termination_reason": normalized_reason,
            "changed_paths": [],
            "verification_status": None,
            "mutation_index": None,
            "validation_index": None,
            "logical_model_calls": None,
            "provider_attempts": None,
            "tool_calls": None,
            "verification_attempts": None,
        }

    normalized = _normalize_json_object(report, "report")
    if normalized.get("status") != status:
        raise ValueError("report status does not match terminal status")
    if normalized.get("termination_reason") != normalized_reason:
        raise ValueError("report termination reason does not match terminal reason")
    exit_code = normalized.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise ValueError("exit_code must be an integer")
    verification = normalized.get("verification")
    if not isinstance(verification, dict):
        raise ValueError("verification must be an object")
    verification_status = verification.get("status")
    if not isinstance(verification_status, str) or not verification_status:
        raise ValueError("verification status must be a non-empty string")

    return {
        "status": status,
        "exit_code": exit_code,
        "termination_reason": normalized_reason,
        "changed_paths": _require_changed_paths(normalized.get("changed_paths")),
        "verification_status": verification_status,
        "mutation_index": _require_non_negative_int(
            normalized.get("mutation_index"), "mutation_index"
        ),
        "validation_index": _require_optional_non_negative_int(
            normalized.get("validation_index"), "validation_index"
        ),
        "logical_model_calls": _require_non_negative_int(
            normalized.get("logical_model_calls"), "logical_model_calls"
        ),
        "provider_attempts": _require_non_negative_int(
            normalized.get("provider_attempts"), "provider_attempts"
        ),
        "tool_calls": _require_non_negative_int(
            normalized.get("tool_calls"), "tool_calls"
        ),
        "verification_attempts": _require_non_negative_int(
            normalized.get("verification_attempts"), "verification_attempts"
        ),
    }


_PERSISTED_REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "status",
        "exit_code",
        "termination_reason",
        "changed_paths",
        "mutation_index",
        "validation_index",
        "verification",
        "logical_model_calls",
        "provider_attempts",
        "tool_calls",
        "verification_attempts",
        "context_compressions",
        "token_usage",
        "elapsed_ms",
        "log_failure_code",
        "log_path",
    }
)

_PERSISTED_VERIFICATION_FIELDS = frozenset(
    {
        "status",
        "source",
        "exit_code",
        "timed_out",
        "truncated",
        "duration_ms",
        "validation_index",
        "error_code",
    }
)

_PERSISTED_TOKEN_USAGE_FIELDS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "responses_with_usage",
        "responses_without_usage",
    }
)


def _require_fields(value: Mapping[str, object], fields: frozenset[str], name: str) -> None:
    if not fields.issubset(value):
        raise ValueError(f"{name} is missing required fields")


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _require_normalized_relative_path(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{field_name} must be a normalized relative path")
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
        raise ValueError(f"{field_name} must be a normalized relative path")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"{field_name} must be a normalized relative path")
    if PurePosixPath(value).as_posix() != value:
        raise ValueError(f"{field_name} must be a normalized relative path")
    return value


def _project_verification(value: object) -> JSONObject:
    verification = _normalize_json_object(value, "verification")
    _require_fields(verification, _PERSISTED_VERIFICATION_FIELDS, "verification")
    status = verification["status"]
    if not isinstance(status, str) or not status:
        raise ValueError("verification.status must be a non-empty string")
    source = _require_optional_text(verification["source"], "verification.source")
    exit_code_value = verification["exit_code"]
    if exit_code_value is None:
        exit_code = None
    elif isinstance(exit_code_value, bool) or not isinstance(exit_code_value, int):
        raise ValueError("verification.exit_code must be an integer or null")
    else:
        exit_code = exit_code_value
    return {
        "status": status,
        "source": source,
        "exit_code": exit_code,
        "timed_out": _require_bool(verification["timed_out"], "verification.timed_out"),
        "truncated": _require_bool(verification["truncated"], "verification.truncated"),
        "duration_ms": _require_optional_non_negative_int(
            verification["duration_ms"], "verification.duration_ms"
        ),
        "validation_index": _require_optional_non_negative_int(
            verification["validation_index"], "verification.validation_index"
        ),
        "error_code": _require_optional_text(
            verification["error_code"], "verification.error_code"
        ),
    }


def _project_token_usage(value: object) -> JSONObject:
    usage = _normalize_json_object(value, "token_usage")
    _require_fields(usage, _PERSISTED_TOKEN_USAGE_FIELDS, "token_usage")
    projected = {
        field_name: _require_non_negative_int(usage[field_name], f"token_usage.{field_name}")
        for field_name in _PERSISTED_TOKEN_USAGE_FIELDS
    }
    if projected["total_tokens"] != (
        projected["input_tokens"] + projected["output_tokens"]
    ):
        raise ValueError("token_usage total is inconsistent")
    return projected


def make_persisted_run_report(report: JSONObject) -> JSONObject:
    normalized = _normalize_json_object(report, "report")
    _require_fields(normalized, _PERSISTED_REPORT_FIELDS, "report")

    schema_version = normalized["schema_version"]
    if schema_version != 1 or isinstance(schema_version, bool):
        raise ValueError("schema_version must be 1")
    run_id = _require_id(normalized["run_id"], "run_id")
    status = normalized["status"]
    if status not in {"success", "failed", "interrupted"}:
        raise ValueError("status must be terminal")
    exit_code = normalized["exit_code"]
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise ValueError("exit_code must be an integer")
    termination_reason = _require_optional_text(
        normalized["termination_reason"], "termination_reason"
    )
    expected_exit_code = {"success": 0, "failed": 1, "interrupted": 130}[status]
    if exit_code != expected_exit_code:
        raise ValueError("status and exit_code are inconsistent")
    if status == "success" and termination_reason is not None:
        raise ValueError("successful report cannot have a termination reason")
    if status != "success" and termination_reason is None:
        raise ValueError("unsuccessful report requires a termination reason")

    changed_paths = [
        _require_normalized_relative_path(path, "changed_paths")
        for path in _require_changed_paths(normalized["changed_paths"])
    ]
    mutation_index = _require_non_negative_int(
        normalized["mutation_index"], "mutation_index"
    )
    validation_index = _require_optional_non_negative_int(
        normalized["validation_index"], "validation_index"
    )
    verification = _project_verification(normalized["verification"])
    token_usage = _project_token_usage(normalized["token_usage"])
    log_failure_code = _require_optional_text(
        normalized["log_failure_code"], "log_failure_code"
    )
    log_path = _require_normalized_relative_path(normalized["log_path"], "log_path")
    if log_path != f".coding-agent/logs/{run_id}.jsonl":
        raise ValueError("log_path does not match run_id")

    persisted: JSONObject = {
        "schema_version": schema_version,
        "run_id": run_id,
        "status": status,
        "exit_code": exit_code,
        "termination_reason": termination_reason,
        "changed_paths": changed_paths,
        "mutation_index": mutation_index,
        "validation_index": validation_index,
        "verification": verification,
        "logical_model_calls": _require_non_negative_int(
            normalized["logical_model_calls"], "logical_model_calls"
        ),
        "provider_attempts": _require_non_negative_int(
            normalized["provider_attempts"], "provider_attempts"
        ),
        "tool_calls": _require_non_negative_int(normalized["tool_calls"], "tool_calls"),
        "verification_attempts": _require_non_negative_int(
            normalized["verification_attempts"], "verification_attempts"
        ),
        "context_compressions": _require_non_negative_int(
            normalized["context_compressions"], "context_compressions"
        ),
        "token_usage": token_usage,
        "elapsed_ms": _require_non_negative_int(normalized["elapsed_ms"], "elapsed_ms"),
        "log_failure_code": log_failure_code,
        "log_path": log_path,
    }
    if _encoded_json_size(persisted) > MAX_PERSISTED_REPORT_BYTES:
        raise ValueError("persisted report exceeds its byte limit")
    return persisted


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def uuid4_hex() -> str:
    return uuid.uuid4().hex


def make_session_title(message: str) -> str:
    text = _require_text(message, code="invalid_message")
    line = next((candidate for candidate in text.splitlines() if candidate.strip()), "")
    title = " ".join(line.split())
    if not title:
        raise SessionError("invalid_message")
    if len(title) > 80:
        return title[:79] + "…"
    return title

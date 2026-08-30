from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
import math
from pathlib import PurePosixPath, PureWindowsPath
import re
from threading import Condition

from coding_agent.logging import scrub_text
from coding_agent.messages import JSONObject, JSONValue
from coding_agent.session import utc_now


SESSION_UPDATE_SCHEMA_VERSION = 2
_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
_SAFE_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")
_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


class SessionUpdateKind(StrEnum):
    RUN_QUEUED = "run_queued"
    RUN_STARTED = "run_started"
    RUN_CANCELLING = "run_cancelling"
    ASSISTANT_TEXT_DELTA = "assistant_text_delta"
    ASSISTANT_TEXT_COMMITTED = "assistant_text_committed"
    ASSISTANT_TEXT_DISCARDED = "assistant_text_discarded"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_FINISHED = "verification_finished"
    RUN_FINISHED = "run_finished"
    CONTROLLER_ERROR = "controller_error"


_LIFECYCLE_KINDS = frozenset(
    {
        SessionUpdateKind.RUN_QUEUED,
        SessionUpdateKind.RUN_STARTED,
        SessionUpdateKind.RUN_CANCELLING,
        SessionUpdateKind.RUN_FINISHED,
    }
)


class _FrozenDict(dict[str, JSONValue]):
    @staticmethod
    def _immutable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("session update data is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class _FrozenList(list[JSONValue]):
    @staticmethod
    def _immutable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("session update data is immutable")

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


def _normalize_json(value: object, field_name: str) -> JSONValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} contains a non-finite float")
        return value
    if isinstance(value, (list, tuple)):
        return _FrozenList([_normalize_json(item, field_name) for item in value])
    if isinstance(value, Mapping):
        normalized: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{field_name} contains a non-string key")
            normalized[key] = _normalize_json(item, field_name)
        return _FrozenDict(normalized)
    raise ValueError(f"{field_name} contains a non-JSON value")


def _normalize_object(value: object, field_name: str) -> JSONObject:
    normalized = _normalize_json(value, field_name)
    if not isinstance(normalized, dict):
        raise ValueError(f"{field_name} must be an object")
    return normalized


def _thaw(value: JSONValue) -> JSONValue:
    if isinstance(value, dict):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_thaw(item) for item in value]
    return value


def _require_exact(data: JSONObject, fields: set[str], kind: str) -> None:
    if set(data) != fields:
        raise ValueError(f"{kind} data has invalid fields")


def _require_nonempty(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_nonnegative(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _require_positive(value: object, field_name: str) -> int:
    result = _require_nonnegative(value, field_name)
    if result == 0:
        raise ValueError(f"{field_name} must be positive")
    return result


def _require_optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer or null")
    return value


def _require_optional_nonnegative(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_nonnegative(value, field_name)


def _require_optional_code(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _SAFE_CODE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a safe code or null")
    return value


def _require_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("changed path is invalid")
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
        raise ValueError("changed path is invalid")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("changed path is invalid")
    if PurePosixPath(value).as_posix() != value:
        raise ValueError("changed path is invalid")
    return value


def _require_paths(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("changed_paths must be a list")
    return [_require_path(item) for item in value]


def _validate_payload(kind: SessionUpdateKind, data: JSONObject) -> None:
    if kind in {
        SessionUpdateKind.RUN_QUEUED,
        SessionUpdateKind.RUN_STARTED,
        SessionUpdateKind.RUN_CANCELLING,
    }:
        expected = {
            SessionUpdateKind.RUN_QUEUED: "queued",
            SessionUpdateKind.RUN_STARTED: "running",
            SessionUpdateKind.RUN_CANCELLING: "cancelling",
        }[kind]
        _require_exact(data, {"status"}, kind.value)
        if data["status"] != expected:
            raise ValueError("run lifecycle status is invalid")
        return
    if kind in {
        SessionUpdateKind.ASSISTANT_TEXT_DELTA,
        SessionUpdateKind.ASSISTANT_TEXT_COMMITTED,
    }:
        _require_exact(data, {"content"}, kind.value)
        _require_nonempty(data["content"], "content")
        return
    if kind is SessionUpdateKind.ASSISTANT_TEXT_DISCARDED:
        _require_exact(data, {"reason"}, kind.value)
        _require_optional_code(data["reason"], "reason")
        return
    if kind is SessionUpdateKind.TOOL_STARTED:
        _require_exact(data, {"tool_name", "ordinal"}, kind.value)
        if (
            not isinstance(data["tool_name"], str)
            or _NAME_PATTERN.fullmatch(data["tool_name"]) is None
        ):
            raise ValueError("tool_name is invalid")
        _require_positive(data["ordinal"], "ordinal")
        return
    if kind is SessionUpdateKind.TOOL_FINISHED:
        _require_exact(
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
            kind.value,
        )
        if (
            not isinstance(data["tool_name"], str)
            or _NAME_PATTERN.fullmatch(data["tool_name"]) is None
        ):
            raise ValueError("tool_name is invalid")
        if data["status"] not in {"ok", "error", "rejected"}:
            raise ValueError("tool status is invalid")
        _require_nonnegative(data["duration_ms"], "duration_ms")
        if not isinstance(data["truncated"], bool):
            raise ValueError("truncated must be a boolean")
        _require_optional_int(data["exit_code"], "exit_code")
        _require_optional_code(data["safe_error_code"], "safe_error_code")
        _require_paths(data["changed_paths"])
        return
    if kind is SessionUpdateKind.VERIFICATION_STARTED:
        _require_exact(
            data,
            {"source", "attempt_index", "mutation_index"},
            kind.value,
        )
        if data["source"] not in {"model", "user_verify"}:
            raise ValueError("verification source is invalid")
        _require_positive(data["attempt_index"], "attempt_index")
        _require_nonnegative(data["mutation_index"], "mutation_index")
        return
    if kind is SessionUpdateKind.VERIFICATION_FINISHED:
        _require_exact(
            data,
            {
                "source",
                "status",
                "exit_code",
                "timed_out",
                "truncated",
                "duration_ms",
                "validation_index",
                "mutation_index",
                "error_code",
            },
            kind.value,
        )
        if data["source"] not in {"model", "user_verify"}:
            raise ValueError("verification source is invalid")
        if data["status"] not in {"passed", "failed", "timed_out", "error"}:
            raise ValueError("verification status is invalid")
        _require_optional_int(data["exit_code"], "exit_code")
        if not isinstance(data["timed_out"], bool) or not isinstance(
            data["truncated"], bool
        ):
            raise ValueError("verification flags must be booleans")
        _require_nonnegative(data["duration_ms"], "duration_ms")
        _require_optional_nonnegative(data["validation_index"], "validation_index")
        _require_nonnegative(data["mutation_index"], "mutation_index")
        _require_optional_code(data["error_code"], "error_code")
        return
    if kind is SessionUpdateKind.RUN_FINISHED:
        _require_exact(data, {"status", "agent_status"}, kind.value)
        status = data["status"]
        agent_status = data["agent_status"]
        if status not in {"succeeded", "failed", "interrupted"}:
            raise ValueError("terminal status is invalid")
        if agent_status not in {"success", "answered", "failed", "interrupted"}:
            raise ValueError("terminal agent status is invalid")
        if (status, agent_status) not in {
            ("succeeded", "success"),
            ("succeeded", "answered"),
            ("failed", "failed"),
            ("interrupted", "interrupted"),
        }:
            raise ValueError("terminal status pair is invalid")
        return
    if kind is SessionUpdateKind.CONTROLLER_ERROR:
        _require_exact(data, {"code"}, kind.value)
        if data["code"] != "controller_error":
            raise ValueError("controller error code is invalid")
        return
    raise TypeError("kind must use SessionUpdateKind")


def _require_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase UUID hex string")
    return value


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("clock must return UTC")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


@dataclass(frozen=True, slots=True)
class SessionUpdate:
    schema_version: int
    session_id: str
    run_id: str
    sequence: int
    timestamp_utc: str
    kind: SessionUpdateKind
    data: JSONObject = field(repr=False)

    def __post_init__(self) -> None:
        if self.schema_version != SESSION_UPDATE_SCHEMA_VERSION or isinstance(
            self.schema_version, bool
        ):
            raise ValueError("unsupported session update schema")
        _require_id(self.session_id, "session_id")
        _require_id(self.run_id, "run_id")
        _require_positive(self.sequence, "sequence")
        if not isinstance(self.timestamp_utc, str) or not self.timestamp_utc.endswith("Z"):
            raise ValueError("timestamp_utc must be UTC")
        if type(self.kind) is not SessionUpdateKind:
            raise TypeError("kind must use SessionUpdateKind")
        normalized = _normalize_object(self.data, "data")
        _validate_payload(self.kind, normalized)
        object.__setattr__(self, "data", normalized)

    def to_dict(self) -> JSONObject:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp_utc": self.timestamp_utc,
            "kind": self.kind.value,
            "data": _thaw(self.data),
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
class SessionUpdateBatch:
    events: tuple[SessionUpdate, ...]
    last_sequence: int
    reset_required: bool


class SessionEventHub:
    def __init__(
        self,
        *,
        utc_clock: Callable[[], datetime] = utc_now,
        sensitive_values: tuple[str, ...] = (),
        max_events: int = 1_000,
        max_bytes: int = 1_048_576,
    ) -> None:
        if not callable(utc_clock):
            raise TypeError("utc_clock must be callable")
        if not isinstance(sensitive_values, tuple) or any(
            not isinstance(value, str) for value in sensitive_values
        ):
            raise TypeError("sensitive_values must be a tuple of strings")
        for value, name in ((max_events, "max_events"), (max_bytes, "max_bytes")):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self._utc_clock = utc_clock
        self._sensitive_values = sensitive_values
        self._max_events = max_events
        self._max_bytes = max_bytes
        self._condition = Condition()
        self._session_id: str | None = None
        self._run_id: str | None = None
        self._events: deque[tuple[SessionUpdate, int]] = deque()
        self._lifecycle_updates: dict[SessionUpdateKind, SessionUpdate] = {}
        self._retained_bytes = 0
        self._next_sequence = 1

    def begin_run(self, session_id: str, run_id: str) -> None:
        normalized_session_id = _require_id(session_id, "session_id")
        normalized_run_id = _require_id(run_id, "run_id")
        with self._condition:
            self._session_id = normalized_session_id
            self._run_id = normalized_run_id
            self._events.clear()
            self._lifecycle_updates.clear()
            self._retained_bytes = 0
            self._next_sequence = 1
            self._condition.notify_all()

    def _scrub(self, value: JSONValue) -> JSONValue:
        if isinstance(value, str):
            return scrub_text(value, self._sensitive_values)
        if isinstance(value, list):
            return [self._scrub(item) for item in value]
        if isinstance(value, dict):
            return {key: self._scrub(item) for key, item in value.items()}
        return value

    def publish(self, kind: SessionUpdateKind, data: JSONObject) -> SessionUpdate:
        if type(kind) is not SessionUpdateKind:
            raise TypeError("kind must use SessionUpdateKind")
        normalized = _normalize_object(data, "data")
        scrubbed = self._scrub(normalized)
        scrubbed_object = _normalize_object(scrubbed, "data")
        _validate_payload(kind, scrubbed_object)
        timestamp = _timestamp(self._utc_clock())
        with self._condition:
            if self._session_id is None or self._run_id is None:
                raise RuntimeError("no active session run")
            if kind in _LIFECYCLE_KINDS:
                existing = self._lifecycle_updates.get(kind)
                if existing is not None:
                    return existing
            update = SessionUpdate(
                schema_version=SESSION_UPDATE_SCHEMA_VERSION,
                session_id=self._session_id,
                run_id=self._run_id,
                sequence=self._next_sequence,
                timestamp_utc=timestamp,
                kind=kind,
                data=scrubbed_object,
            )
            encoded_size = len(update.to_json().encode("utf-8"))
            if encoded_size > self._max_bytes:
                raise ValueError("session update exceeds max_bytes")
            self._events.append((update, encoded_size))
            if kind in _LIFECYCLE_KINDS:
                self._lifecycle_updates[kind] = update
            self._retained_bytes += encoded_size
            self._next_sequence += 1
            while (
                len(self._events) > self._max_events
                or self._retained_bytes > self._max_bytes
            ):
                _, removed_size = self._events.popleft()
                self._retained_bytes -= removed_size
            self._condition.notify_all()
            return update

    @staticmethod
    def _validate_cursor(after_sequence: object) -> int:
        if (
            isinstance(after_sequence, bool)
            or not isinstance(after_sequence, int)
            or after_sequence < 0
        ):
            raise ValueError("after_sequence must be a non-negative integer")
        return after_sequence

    def _read_locked(self, after_sequence: int) -> SessionUpdateBatch:
        latest = self._next_sequence - 1
        if after_sequence > latest:
            raise ValueError("after_sequence is ahead of the latest event")
        oldest = self._events[0][0].sequence if self._events else latest + 1
        reset_required = bool(self._events) and after_sequence < oldest - 1
        events = (
            tuple(event for event, _ in self._events)
            if reset_required
            else tuple(
                event for event, _ in self._events if event.sequence > after_sequence
            )
        )
        return SessionUpdateBatch(
            events=events,
            last_sequence=latest,
            reset_required=reset_required,
        )

    def _require_expected_run_locked(self, expected_run_id: str | None) -> None:
        if expected_run_id is not None and self._run_id != expected_run_id:
            raise LookupError("session update run not found")

    def read(
        self,
        *,
        after_sequence: int = 0,
        expected_run_id: str | None = None,
    ) -> SessionUpdateBatch:
        cursor = self._validate_cursor(after_sequence)
        expected = (
            None
            if expected_run_id is None
            else _require_id(expected_run_id, "expected_run_id")
        )
        with self._condition:
            self._require_expected_run_locked(expected)
            return self._read_locked(cursor)

    def wait(
        self,
        *,
        after_sequence: int,
        timeout_seconds: float,
        expected_run_id: str | None = None,
    ) -> SessionUpdateBatch:
        cursor = self._validate_cursor(after_sequence)
        expected = (
            None
            if expected_run_id is None
            else _require_id(expected_run_id, "expected_run_id")
        )
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive finite number")
        with self._condition:
            self._require_expected_run_locked(expected)
            if cursor > self._next_sequence - 1:
                raise ValueError("after_sequence is ahead of the latest event")
            self._condition.wait_for(
                lambda: (
                    expected is not None and self._run_id != expected
                )
                or self._next_sequence - 1 > cursor,
                timeout=float(timeout_seconds),
            )
            self._require_expected_run_locked(expected)
            return self._read_locked(cursor)

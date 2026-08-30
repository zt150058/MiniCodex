from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from typing import BinaryIO, Protocol

from coding_agent.session import (
    NewSessionEvent,
    PersistedSessionEventKind,
    SessionEvent,
    SessionNarrativeKind,
    SessionNarrativeEntry,
    SessionRecord,
    SessionRunRecord,
    SessionRunResult,
    SessionRunStatus,
    SessionStatus,
    SessionStoreError,
    SessionSubmission,
    make_persisted_run_report,
    make_session_title,
    utc_now,
    uuid4_hex,
)
from coding_agent.logging import scrub_text
from coding_agent.skills import (
    RunSkillSnapshotMetadata,
    SkillDescriptor,
    SkillSource,
)


SCHEMA_VERSION = 2
_INTERNAL_DIRECTORY = ".coding-agent"
_DATABASE_NAME = "sessions.sqlite3"
_LOCK_NAME = "sessions.lock"
_SKILL_ID_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z")


class SessionStore(Protocol):
    @property
    def workspace(self) -> Path: ...

    def initialize(self) -> None: ...
    def create_session(
        self,
        message: str,
        *,
        selected_skills: tuple[SkillDescriptor, ...] = (),
    ) -> SessionSubmission: ...
    def get_session(self, session_id: str) -> SessionRecord: ...
    def get_run(self, run_id: str) -> SessionRunRecord: ...
    def get_skill_selection(self, session_id: str) -> tuple[str, ...]: ...
    def get_run_skill_snapshots(
        self,
        run_id: str,
    ) -> tuple[RunSkillSnapshotMetadata, ...]: ...
    def replace_skill_selection(
        self,
        session_id: str,
        skill_ids: tuple[str, ...],
    ) -> tuple[str, ...]: ...
    def list_sessions(self, *, limit: int = 50) -> tuple[SessionRecord, ...]: ...
    def list_runs(self, session_id: str) -> tuple[SessionRunRecord, ...]: ...
    def submit_message(
        self,
        session_id: str,
        message: str,
        *,
        selected_skills: tuple[SkillDescriptor, ...] = (),
    ) -> SessionSubmission: ...
    def start_run(self, run_id: str) -> SessionRunRecord: ...
    def append_event(self, event: NewSessionEvent) -> SessionEvent: ...
    def request_cancellation(self, run_id: str) -> SessionRunRecord: ...
    def finish_run(self, result: SessionRunResult) -> SessionRunRecord: ...
    def load_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> tuple[SessionEvent, ...]: ...
    def load_narrative(self, session_id: str) -> tuple[SessionNarrativeEntry, ...]: ...
    def recover_incomplete_runs(self) -> tuple[SessionRunRecord, ...]: ...


def _is_reparse_point(path: Path) -> bool:
    try:
        result = os.lstat(path)
    except FileNotFoundError:
        return path.is_symlink()
    attributes = getattr(result, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _normalize_workspace(workspace: Path) -> Path:
    requested = Path(os.path.abspath(workspace))
    if _is_reparse_point(requested):
        raise SessionStoreError("storage_unavailable")
    try:
        normalized = Path(workspace).resolve(strict=True)
    except OSError:
        raise SessionStoreError("storage_unavailable") from None
    if not normalized.is_dir():
        raise SessionStoreError("storage_unavailable")
    return normalized


def _ensure_internal_directory(workspace: Path) -> Path:
    internal = workspace / _INTERNAL_DIRECTORY
    if internal.exists() or internal.is_symlink():
        if _is_reparse_point(internal) or not internal.is_dir():
            raise SessionStoreError("storage_unavailable")
        return internal
    try:
        internal.mkdir()
    except OSError:
        raise SessionStoreError("storage_unavailable") from None
    if _is_reparse_point(internal) or not internal.is_dir():
        raise SessionStoreError("storage_unavailable")
    return internal


def _validate_internal_file(path: Path) -> None:
    if path.exists() or path.is_symlink():
        if _is_reparse_point(path) or not path.is_file():
            raise SessionStoreError("storage_unavailable")


def _sqlite_store_error(exc: sqlite3.Error) -> SessionStoreError:
    error_code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(error_code, int) and (error_code & 0xFF) in {
        sqlite3.SQLITE_CORRUPT,
        sqlite3.SQLITE_NOTADB,
    }:
        return SessionStoreError("database_corrupt")
    return SessionStoreError("storage_unavailable")


def _lock_stream(stream: BinaryIO) -> None:
    stream.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_stream(stream: BinaryIO) -> None:
    stream.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class WorkspaceSessionLease:
    def __init__(self, workspace: Path, stream: BinaryIO) -> None:
        self._workspace = workspace
        self._stream: BinaryIO | None = stream

    @classmethod
    def acquire(cls, workspace: Path) -> WorkspaceSessionLease:
        normalized = _normalize_workspace(workspace)
        internal = _ensure_internal_directory(normalized)
        lock_path = internal / _LOCK_NAME
        _validate_internal_file(lock_path)
        try:
            stream = lock_path.open("a+b")
        except OSError:
            raise SessionStoreError("storage_unavailable") from None
        try:
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()
            _lock_stream(stream)
        except OSError:
            stream.close()
            raise SessionStoreError("controller_in_use") from None
        return cls(normalized, stream)

    @property
    def workspace(self) -> Path:
        return self._workspace

    def close(self) -> None:
        stream = self._stream
        if stream is None:
            return
        self._stream = None
        try:
            _unlock_stream(stream)
        except OSError:
            pass
        finally:
            stream.close()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY CHECK(length(session_id) > 0),
    title TEXT NOT NULL CHECK(length(title) > 0),
    status TEXT NOT NULL CHECK(status IN ('idle', 'running', 'cancelling')),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    last_run_id TEXT,
    next_sequence INTEGER NOT NULL CHECK(next_sequence > 0)
);

CREATE TABLE IF NOT EXISTS session_runs (
    run_id TEXT PRIMARY KEY CHECK(length(run_id) > 0),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
    status TEXT NOT NULL CHECK(
        status IN ('queued', 'running', 'cancelling', 'succeeded', 'failed', 'interrupted')
    ),
    user_event_sequence INTEGER NOT NULL CHECK(user_event_sequence > 0),
    started_at_utc TEXT,
    finished_at_utc TEXT,
    agent_status TEXT,
    termination_reason TEXT,
    audit_run_id TEXT,
    final_report_json TEXT,
    UNIQUE(session_id, ordinal)
);

CREATE TABLE IF NOT EXISTS session_skill_selections (
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    position INTEGER NOT NULL CHECK(position > 0),
    skill_id TEXT NOT NULL,
    PRIMARY KEY(session_id, position),
    UNIQUE(session_id, skill_id)
);

CREATE TABLE IF NOT EXISTS run_skill_snapshots (
    run_id TEXT NOT NULL REFERENCES session_runs(run_id),
    position INTEGER NOT NULL CHECK(position > 0),
    skill_id TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('user', 'workspace')),
    sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
    char_count INTEGER NOT NULL CHECK(char_count > 0),
    PRIMARY KEY(run_id, position),
    UNIQUE(run_id, skill_id)
);

CREATE TABLE IF NOT EXISTS session_events (
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    run_id TEXT REFERENCES session_runs(run_id),
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    kind TEXT NOT NULL CHECK(kind IN (
        'user_message', 'run_queued', 'run_started', 'assistant_text_committed',
        'tool_activity', 'verification_activity', 'cancellation_requested',
        'run_finished', 'run_recovered'
    )),
    created_at_utc TEXT NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY(session_id, sequence)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_workspace_run
ON session_runs ((1))
WHERE status IN ('queued', 'running', 'cancelling');
"""


class SQLiteSessionStore:
    def __init__(
        self,
        workspace: Path,
        *,
        utc_clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = uuid4_hex,
        sensitive_values: tuple[str, ...] = (),
        busy_timeout_ms: int = 5_000,
    ) -> None:
        if not callable(utc_clock) or not callable(id_factory):
            raise TypeError("clock and id factory must be callable")
        if not isinstance(sensitive_values, tuple) or any(
            not isinstance(value, str) for value in sensitive_values
        ):
            raise TypeError("sensitive_values must be a tuple of strings")
        if (
            isinstance(busy_timeout_ms, bool)
            or not isinstance(busy_timeout_ms, int)
            or busy_timeout_ms <= 0
        ):
            raise ValueError("busy_timeout_ms must be a positive integer")
        self._workspace = _normalize_workspace(workspace)
        self._utc_clock = utc_clock
        self._id_factory = id_factory
        self._sensitive_values = sensitive_values
        self._busy_timeout_ms = busy_timeout_ms

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def _database_path(self) -> Path:
        return self._workspace / _INTERNAL_DIRECTORY / _DATABASE_NAME

    def _connect(self) -> sqlite3.Connection:
        database = self._database_path
        _validate_internal_file(database)
        try:
            connection = sqlite3.connect(database, timeout=self._busy_timeout_ms / 1000)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
            return connection
        except sqlite3.Error as exc:
            raise _sqlite_store_error(exc) from None

    def initialize(self) -> None:
        _ensure_internal_directory(self._workspace)
        _validate_internal_file(self._database_path)
        connection = self._connect()
        try:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise SessionStoreError("schema_unsupported")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(_SCHEMA)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
        except SessionStoreError:
            raise
        except sqlite3.Error as exc:
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    def _timestamp(self) -> str:
        value = self._utc_clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise SessionStoreError("storage_unavailable")
        if value.utcoffset() != timezone.utc.utcoffset(value):
            raise SessionStoreError("storage_unavailable")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )

    @staticmethod
    def _canonical_json(value: object) -> str:
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError):
            raise SessionStoreError("invalid_session_state") from None

    @staticmethod
    def _decode_json_object(value: object) -> dict[str, object]:
        if not isinstance(value, str):
            raise SessionStoreError("database_corrupt")
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            raise SessionStoreError("database_corrupt") from None
        if not isinstance(decoded, dict):
            raise SessionStoreError("database_corrupt")
        return decoded

    @classmethod
    def _decode_session(cls, row: sqlite3.Row) -> SessionRecord:
        try:
            return SessionRecord(
                session_id=row["session_id"],
                title=row["title"],
                status=SessionStatus(row["status"]),
                created_at_utc=row["created_at_utc"],
                updated_at_utc=row["updated_at_utc"],
                last_run_id=row["last_run_id"],
                next_sequence=row["next_sequence"],
            )
        except (KeyError, TypeError, ValueError):
            raise SessionStoreError("database_corrupt") from None

    @classmethod
    def _decode_run(cls, row: sqlite3.Row) -> SessionRunRecord:
        final_report = None
        if row["final_report_json"] is not None:
            decoded_report = cls._decode_json_object(row["final_report_json"])
            try:
                projected_report = make_persisted_run_report(decoded_report)
            except (TypeError, ValueError):
                raise SessionStoreError("database_corrupt") from None
            if projected_report != decoded_report:
                raise SessionStoreError("database_corrupt")
            final_report = projected_report
        try:
            return SessionRunRecord(
                run_id=row["run_id"],
                session_id=row["session_id"],
                ordinal=row["ordinal"],
                status=SessionRunStatus(row["status"]),
                user_event_sequence=row["user_event_sequence"],
                started_at_utc=row["started_at_utc"],
                finished_at_utc=row["finished_at_utc"],
                agent_status=row["agent_status"],
                termination_reason=row["termination_reason"],
                audit_run_id=row["audit_run_id"],
                final_report=final_report,
            )
        except (KeyError, TypeError, ValueError):
            raise SessionStoreError("database_corrupt") from None

    @classmethod
    def _decode_event(cls, row: sqlite3.Row) -> SessionEvent:
        data = cls._decode_json_object(row["data_json"])
        try:
            return SessionEvent(
                session_id=row["session_id"],
                run_id=row["run_id"],
                sequence=row["sequence"],
                kind=PersistedSessionEventKind(row["kind"]),
                created_at_utc=row["created_at_utc"],
                data=data,
            )
        except (KeyError, TypeError, ValueError):
            raise SessionStoreError("database_corrupt") from None

    @staticmethod
    def _begin(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")

    @staticmethod
    def _rollback(connection: sqlite3.Connection) -> None:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass

    @staticmethod
    def _active_run_exists(connection: sqlite3.Connection) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM session_runs "
                "WHERE status IN ('queued', 'running', 'cancelling') LIMIT 1"
            ).fetchone()
            is not None
        )

    def _new_id(self) -> str:
        value = self._id_factory()
        if not isinstance(value, str):
            raise SessionStoreError("invalid_session_state")
        return value

    @staticmethod
    def _validate_selected_skills(
        selected_skills: tuple[SkillDescriptor, ...],
    ) -> tuple[SkillDescriptor, ...]:
        if type(selected_skills) is not tuple or any(
            type(item) is not SkillDescriptor for item in selected_skills
        ):
            raise SessionStoreError("invalid_skill_selection")
        skill_ids = tuple(item.skill_id for item in selected_skills)
        if len(set(skill_ids)) != len(skill_ids):
            raise SessionStoreError("invalid_skill_selection")
        return selected_skills

    @staticmethod
    def _read_skill_ids(
        connection: sqlite3.Connection,
        session_id: str,
    ) -> tuple[str, ...]:
        rows = connection.execute(
            "SELECT position, skill_id "
            "FROM session_skill_selections "
            "WHERE session_id = ? "
            "ORDER BY position",
            (session_id,),
        ).fetchall()
        selected: list[str] = []
        for expected_position, row in enumerate(rows, start=1):
            position = row["position"]
            skill_id = row["skill_id"]
            if (
                type(position) is not int
                or position != expected_position
                or not isinstance(skill_id, str)
                or _SKILL_ID_PATTERN.fullmatch(skill_id) is None
            ):
                raise SessionStoreError("database_corrupt")
            selected.append(skill_id)
        return tuple(selected)

    @staticmethod
    def _insert_skill_configuration(
        connection: sqlite3.Connection,
        *,
        session_id: str,
        run_id: str,
        selected_skills: tuple[SkillDescriptor, ...],
        insert_selection: bool,
    ) -> None:
        if insert_selection:
            connection.executemany(
                "INSERT INTO session_skill_selections "
                "(session_id, position, skill_id) VALUES (?, ?, ?)",
                (
                    (session_id, position, item.skill_id)
                    for position, item in enumerate(selected_skills, start=1)
                ),
            )
        connection.executemany(
            "INSERT INTO run_skill_snapshots "
            "(run_id, position, skill_id, source, sha256, char_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                (
                    run_id,
                    position,
                    item.skill_id,
                    item.source.value,
                    item.sha256,
                    item.char_count,
                )
                for position, item in enumerate(selected_skills, start=1)
            ),
        )

    @staticmethod
    def _select_session(
        connection: sqlite3.Connection,
        session_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise SessionStoreError("session_not_found")
        return row

    @staticmethod
    def _select_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM session_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise SessionStoreError("run_not_found")
        return row

    def _insert_event(
        self,
        connection: sqlite3.Connection,
        event: SessionEvent,
    ) -> None:
        connection.execute(
            "INSERT INTO session_events "
            "(session_id, run_id, sequence, kind, created_at_utc, data_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                event.session_id,
                event.run_id,
                event.sequence,
                event.kind.value,
                event.created_at_utc,
                self._canonical_json(event.data),
            ),
        )

    def create_session(
        self,
        message: str,
        *,
        selected_skills: tuple[SkillDescriptor, ...] = (),
    ) -> SessionSubmission:
        if not isinstance(message, str):
            raise SessionStoreError("invalid_message")
        selected_skills = self._validate_selected_skills(selected_skills)
        safe_message = scrub_text(message, self._sensitive_values)
        try:
            title = make_session_title(safe_message)
            session_id = self._new_id()
            run_id = self._new_id()
            timestamp = self._timestamp()
            session = SessionRecord(
                session_id=session_id,
                title=title,
                status=SessionStatus.RUNNING,
                created_at_utc=timestamp,
                updated_at_utc=timestamp,
                last_run_id=run_id,
                next_sequence=3,
            )
            run = SessionRunRecord(
                run_id=run_id,
                session_id=session_id,
                ordinal=1,
                status=SessionRunStatus.QUEUED,
                user_event_sequence=1,
                started_at_utc=None,
                finished_at_utc=None,
                agent_status=None,
                termination_reason=None,
                audit_run_id=None,
                final_report=None,
            )
            user_event = SessionEvent(
                session_id=session_id,
                run_id=run_id,
                sequence=1,
                kind=PersistedSessionEventKind.USER_MESSAGE,
                created_at_utc=timestamp,
                data={"content": safe_message},
            )
            queued_event = SessionEvent(
                session_id=session_id,
                run_id=run_id,
                sequence=2,
                kind=PersistedSessionEventKind.RUN_QUEUED,
                created_at_utc=timestamp,
                data={"status": SessionRunStatus.QUEUED.value},
            )
        except (TypeError, ValueError, SessionStoreError):
            raise SessionStoreError("invalid_message") from None

        connection = self._connect()
        try:
            self._begin(connection)
            if self._active_run_exists(connection):
                raise SessionStoreError("controller_busy")
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    session.session_id,
                    session.title,
                    session.status.value,
                    session.created_at_utc,
                    session.updated_at_utc,
                    session.last_run_id,
                    session.next_sequence,
                ),
            )
            connection.execute(
                "INSERT INTO session_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.run_id,
                    run.session_id,
                    run.ordinal,
                    run.status.value,
                    run.user_event_sequence,
                    run.started_at_utc,
                    run.finished_at_utc,
                    run.agent_status,
                    run.termination_reason,
                    run.audit_run_id,
                    None,
                ),
            )
            self._insert_skill_configuration(
                connection,
                session_id=session.session_id,
                run_id=run.run_id,
                selected_skills=selected_skills,
                insert_selection=True,
            )
            self._insert_event(connection, user_event)
            self._insert_event(connection, queued_event)
            connection.commit()
            return SessionSubmission(session=session, user_event=user_event, run=run)
        except SessionStoreError:
            self._rollback(connection)
            raise
        except sqlite3.IntegrityError:
            self._rollback(connection)
            raise SessionStoreError("storage_unavailable") from None
        except sqlite3.Error as exc:
            self._rollback(connection)
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    def get_session(self, session_id: str) -> SessionRecord:
        if not isinstance(session_id, str):
            raise SessionStoreError("session_not_found")
        connection = self._connect()
        try:
            return self._decode_session(self._select_session(connection, session_id))
        except sqlite3.Error as exc:
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    def get_run(self, run_id: str) -> SessionRunRecord:
        if not isinstance(run_id, str):
            raise SessionStoreError("run_not_found")
        connection = self._connect()
        try:
            return self._decode_run(self._select_run(connection, run_id))
        except sqlite3.Error as exc:
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    def get_skill_selection(self, session_id: str) -> tuple[str, ...]:
        if not isinstance(session_id, str):
            raise SessionStoreError("session_not_found")
        connection = self._connect()
        try:
            self._select_session(connection, session_id)
            return self._read_skill_ids(connection, session_id)
        except sqlite3.Error as exc:
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    def get_run_skill_snapshots(
        self,
        run_id: str,
    ) -> tuple[RunSkillSnapshotMetadata, ...]:
        if not isinstance(run_id, str):
            raise SessionStoreError("run_not_found")
        connection = self._connect()
        try:
            self._select_run(connection, run_id)
            rows = connection.execute(
                "SELECT position, skill_id, source, sha256, char_count "
                "FROM run_skill_snapshots "
                "WHERE run_id = ? "
                "ORDER BY position",
                (run_id,),
            ).fetchall()
            snapshots: list[RunSkillSnapshotMetadata] = []
            try:
                for expected_position, row in enumerate(rows, start=1):
                    if type(row["position"]) is not int or row["position"] != expected_position:
                        raise ValueError
                    snapshots.append(
                        RunSkillSnapshotMetadata(
                            skill_id=row["skill_id"],
                            source=SkillSource(row["source"]),
                            sha256=row["sha256"],
                            char_count=row["char_count"],
                        )
                    )
            except (KeyError, TypeError, ValueError):
                raise SessionStoreError("database_corrupt") from None
            return tuple(snapshots)
        except sqlite3.Error as exc:
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    def replace_skill_selection(
        self,
        session_id: str,
        skill_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        if (
            type(skill_ids) is not tuple
            or any(
                type(skill_id) is not str
                or _SKILL_ID_PATTERN.fullmatch(skill_id) is None
                for skill_id in skill_ids
            )
            or len(set(skill_ids)) != len(skill_ids)
        ):
            raise SessionStoreError("invalid_skill_selection")
        connection = self._connect()
        try:
            self._begin(connection)
            session = self._decode_session(
                self._select_session(connection, session_id)
            )
            if session.status is not SessionStatus.IDLE or self._active_run_exists(
                connection
            ):
                raise SessionStoreError("invalid_session_state")
            connection.execute(
                "DELETE FROM session_skill_selections WHERE session_id = ?",
                (session_id,),
            )
            connection.executemany(
                "INSERT INTO session_skill_selections "
                "(session_id, position, skill_id) VALUES (?, ?, ?)",
                (
                    (session_id, position, skill_id)
                    for position, skill_id in enumerate(skill_ids, start=1)
                ),
            )
            rows = connection.execute(
                "SELECT position, skill_id "
                "FROM session_skill_selections "
                "WHERE session_id = ? ORDER BY position",
                (session_id,),
            ).fetchall()
            reread: list[str] = []
            for expected_position, row in enumerate(rows, start=1):
                if (
                    type(row["position"]) is not int
                    or row["position"] != expected_position
                    or not isinstance(row["skill_id"], str)
                    or _SKILL_ID_PATTERN.fullmatch(row["skill_id"]) is None
                ):
                    raise SessionStoreError("database_corrupt")
                reread.append(row["skill_id"])
            result = tuple(reread)
            if result != skill_ids:
                raise SessionStoreError("database_corrupt")
            connection.commit()
            return result
        except SessionStoreError:
            self._rollback(connection)
            raise
        except sqlite3.IntegrityError:
            self._rollback(connection)
            raise SessionStoreError("storage_unavailable") from None
        except sqlite3.Error as exc:
            self._rollback(connection)
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    def list_sessions(self, *, limit: int = 50) -> tuple[SessionRecord, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise SessionStoreError("invalid_session_state")
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM sessions "
                "ORDER BY updated_at_utc DESC, session_id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return tuple(self._decode_session(row) for row in rows)
        except sqlite3.Error as exc:
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    def list_runs(self, session_id: str) -> tuple[SessionRunRecord, ...]:
        connection = self._connect()
        try:
            self._select_session(connection, session_id)
            rows = connection.execute(
                "SELECT * FROM session_runs WHERE session_id = ? ORDER BY ordinal ASC",
                (session_id,),
            ).fetchall()
            return tuple(self._decode_run(row) for row in rows)
        except sqlite3.Error as exc:
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    def load_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> tuple[SessionEvent, ...]:
        if (
            isinstance(after_sequence, bool)
            or not isinstance(after_sequence, int)
            or after_sequence < 0
        ):
            raise SessionStoreError("invalid_session_state")
        connection = self._connect()
        try:
            self._select_session(connection, session_id)
            rows = connection.execute(
                "SELECT * FROM session_events "
                "WHERE session_id = ? AND sequence > ? ORDER BY sequence ASC",
                (session_id, after_sequence),
            ).fetchall()
            return tuple(self._decode_event(row) for row in rows)
        except sqlite3.Error as exc:
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    def submit_message(
        self,
        session_id: str,
        message: str,
        *,
        selected_skills: tuple[SkillDescriptor, ...] = (),
    ) -> SessionSubmission:
        if not isinstance(message, str):
            raise SessionStoreError("invalid_message")
        selected_skills = self._validate_selected_skills(selected_skills)
        safe_message = scrub_text(message, self._sensitive_values)
        try:
            make_session_title(safe_message)
            run_id = self._new_id()
            timestamp = self._timestamp()
        except (TypeError, ValueError, SessionStoreError):
            raise SessionStoreError("invalid_message") from None

        connection = self._connect()
        try:
            self._begin(connection)
            current = self._decode_session(self._select_session(connection, session_id))
            if current.status is not SessionStatus.IDLE or self._active_run_exists(connection):
                raise SessionStoreError("invalid_session_state")
            if self._read_skill_ids(connection, session_id) != tuple(
                item.skill_id for item in selected_skills
            ):
                raise SessionStoreError("invalid_session_state")
            ordinal = int(
                connection.execute(
                    "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM session_runs "
                    "WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
            )
            user_sequence = current.next_sequence
            run = SessionRunRecord(
                run_id=run_id,
                session_id=session_id,
                ordinal=ordinal,
                status=SessionRunStatus.QUEUED,
                user_event_sequence=user_sequence,
                started_at_utc=None,
                finished_at_utc=None,
                agent_status=None,
                termination_reason=None,
                audit_run_id=None,
                final_report=None,
            )
            user_event = SessionEvent(
                session_id=session_id,
                run_id=run_id,
                sequence=user_sequence,
                kind=PersistedSessionEventKind.USER_MESSAGE,
                created_at_utc=timestamp,
                data={"content": safe_message},
            )
            queued_event = SessionEvent(
                session_id=session_id,
                run_id=run_id,
                sequence=user_sequence + 1,
                kind=PersistedSessionEventKind.RUN_QUEUED,
                created_at_utc=timestamp,
                data={"status": SessionRunStatus.QUEUED.value},
            )
            connection.execute(
                "INSERT INTO session_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.run_id,
                    run.session_id,
                    run.ordinal,
                    run.status.value,
                    run.user_event_sequence,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            )
            self._insert_skill_configuration(
                connection,
                session_id=session_id,
                run_id=run.run_id,
                selected_skills=selected_skills,
                insert_selection=False,
            )
            self._insert_event(connection, user_event)
            self._insert_event(connection, queued_event)
            connection.execute(
                "UPDATE sessions SET status = ?, updated_at_utc = ?, last_run_id = ?, "
                "next_sequence = ? WHERE session_id = ?",
                (
                    SessionStatus.RUNNING.value,
                    timestamp,
                    run_id,
                    user_sequence + 2,
                    session_id,
                ),
            )
            updated_session = self._decode_session(
                self._select_session(connection, session_id)
            )
            connection.commit()
            return SessionSubmission(
                session=updated_session,
                user_event=user_event,
                run=run,
            )
        except SessionStoreError:
            self._rollback(connection)
            raise
        except sqlite3.IntegrityError:
            self._rollback(connection)
            raise SessionStoreError("storage_unavailable") from None
        except sqlite3.Error as exc:
            self._rollback(connection)
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    def start_run(self, run_id: str) -> SessionRunRecord:
        connection = self._connect()
        try:
            self._begin(connection)
            current = self._decode_run(self._select_run(connection, run_id))
            if current.status is not SessionRunStatus.QUEUED:
                raise SessionStoreError("invalid_session_state")
            session = self._decode_session(
                self._select_session(connection, current.session_id)
            )
            timestamp = self._timestamp()
            started_event = SessionEvent(
                session_id=current.session_id,
                run_id=current.run_id,
                sequence=session.next_sequence,
                kind=PersistedSessionEventKind.RUN_STARTED,
                created_at_utc=timestamp,
                data={"status": SessionRunStatus.RUNNING.value},
            )
            connection.execute(
                "UPDATE session_runs SET status = ?, started_at_utc = ? WHERE run_id = ?",
                (SessionRunStatus.RUNNING.value, timestamp, run_id),
            )
            self._insert_event(connection, started_event)
            connection.execute(
                "UPDATE sessions SET updated_at_utc = ?, next_sequence = ? "
                "WHERE session_id = ?",
                (timestamp, session.next_sequence + 1, current.session_id),
            )
            running = self._decode_run(self._select_run(connection, run_id))
            connection.commit()
            return running
        except SessionStoreError:
            self._rollback(connection)
            raise
        except (TypeError, ValueError):
            self._rollback(connection)
            raise SessionStoreError("invalid_session_state") from None
        except sqlite3.Error as exc:
            self._rollback(connection)
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    @staticmethod
    def _scrub_json_value(value: object, sensitive_values: tuple[str, ...]) -> object:
        if isinstance(value, str):
            return scrub_text(value, sensitive_values)
        if isinstance(value, list):
            return [
                SQLiteSessionStore._scrub_json_value(item, sensitive_values)
                for item in value
            ]
        if isinstance(value, dict):
            return {
                key: SQLiteSessionStore._scrub_json_value(item, sensitive_values)
                for key, item in value.items()
            }
        return value

    def append_event(self, event: NewSessionEvent) -> SessionEvent:
        if not isinstance(event, NewSessionEvent) or event.kind not in {
            PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED,
            PersistedSessionEventKind.TOOL_ACTIVITY,
            PersistedSessionEventKind.VERIFICATION_ACTIVITY,
        }:
            raise SessionStoreError("invalid_session_state")
        connection = self._connect()
        try:
            self._begin(connection)
            if event.run_id is None:
                raise SessionStoreError("invalid_session_state")
            run = self._decode_run(self._select_run(connection, event.run_id))
            if (
                run.session_id != event.session_id
                or run.status
                not in {SessionRunStatus.RUNNING, SessionRunStatus.CANCELLING}
            ):
                raise SessionStoreError("invalid_session_state")
            session = self._decode_session(
                self._select_session(connection, event.session_id)
            )
            scrubbed_data = self._scrub_json_value(event.data, self._sensitive_values)
            timestamp = self._timestamp()
            persisted = SessionEvent(
                session_id=event.session_id,
                run_id=event.run_id,
                sequence=session.next_sequence,
                kind=event.kind,
                created_at_utc=timestamp,
                data=scrubbed_data,  # type: ignore[arg-type]
            )
            self._insert_event(connection, persisted)
            connection.execute(
                "UPDATE sessions SET updated_at_utc = ?, next_sequence = ? "
                "WHERE session_id = ?",
                (timestamp, session.next_sequence + 1, event.session_id),
            )
            connection.commit()
            return persisted
        except SessionStoreError:
            self._rollback(connection)
            raise
        except (TypeError, ValueError):
            self._rollback(connection)
            raise SessionStoreError("invalid_session_state") from None
        except sqlite3.Error as exc:
            self._rollback(connection)
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    def request_cancellation(self, run_id: str) -> SessionRunRecord:
        connection = self._connect()
        try:
            self._begin(connection)
            current = self._decode_run(self._select_run(connection, run_id))
            if current.status is SessionRunStatus.CANCELLING:
                connection.rollback()
                return current
            if current.status is not SessionRunStatus.RUNNING:
                raise SessionStoreError("invalid_session_state")
            session = self._decode_session(
                self._select_session(connection, current.session_id)
            )
            timestamp = self._timestamp()
            event = SessionEvent(
                session_id=current.session_id,
                run_id=current.run_id,
                sequence=session.next_sequence,
                kind=PersistedSessionEventKind.CANCELLATION_REQUESTED,
                created_at_utc=timestamp,
                data={"status": SessionRunStatus.CANCELLING.value},
            )
            connection.execute(
                "UPDATE session_runs SET status = ? WHERE run_id = ?",
                (SessionRunStatus.CANCELLING.value, run_id),
            )
            self._insert_event(connection, event)
            connection.execute(
                "UPDATE sessions SET status = ?, updated_at_utc = ?, next_sequence = ? "
                "WHERE session_id = ?",
                (
                    SessionStatus.CANCELLING.value,
                    timestamp,
                    session.next_sequence + 1,
                    current.session_id,
                ),
            )
            cancelling = self._decode_run(self._select_run(connection, run_id))
            connection.commit()
            return cancelling
        except SessionStoreError:
            self._rollback(connection)
            raise
        except (TypeError, ValueError):
            self._rollback(connection)
            raise SessionStoreError("invalid_session_state") from None
        except sqlite3.Error as exc:
            self._rollback(connection)
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    def load_narrative(
        self,
        session_id: str,
    ) -> tuple[SessionNarrativeEntry, ...]:
        entries: list[SessionNarrativeEntry] = []
        for event in self.load_events(session_id):
            if event.run_id is None:
                continue
            if event.kind is PersistedSessionEventKind.USER_MESSAGE:
                content = event.data.get("content")
                kind = SessionNarrativeKind.USER
            elif event.kind is PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED:
                content = event.data.get("content")
                kind = SessionNarrativeKind.ASSISTANT
            elif event.kind is PersistedSessionEventKind.RUN_FINISHED:
                content = self._canonical_json(event.data)
                kind = SessionNarrativeKind.RUN_SUMMARY
            else:
                continue
            if not isinstance(content, str) or not content:
                raise SessionStoreError("database_corrupt")
            try:
                entries.append(
                    SessionNarrativeEntry(
                        run_id=event.run_id,
                        kind=kind,
                        content=content,
                    )
                )
            except (TypeError, ValueError):
                raise SessionStoreError("database_corrupt") from None
        return tuple(entries)

    def finish_run(self, result: SessionRunResult) -> SessionRunRecord:
        if not isinstance(result, SessionRunResult):
            raise SessionStoreError("invalid_session_state")
        connection = self._connect()
        try:
            self._begin(connection)
            current = self._decode_run(self._select_run(connection, result.run_id))
            if current.status not in {
                SessionRunStatus.QUEUED,
                SessionRunStatus.RUNNING,
                SessionRunStatus.CANCELLING,
            }:
                raise SessionStoreError("invalid_session_state")
            session = self._decode_session(
                self._select_session(connection, current.session_id)
            )
            timestamp = self._timestamp()
            expected_status = {
                SessionRunStatus.SUCCEEDED: "success",
                SessionRunStatus.FAILED: "failed",
                SessionRunStatus.INTERRUPTED: "interrupted",
            }[result.status]
            if result.agent_status not in {None, expected_status}:
                raise SessionStoreError("invalid_session_state")
            expected_summary_fields = {
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
            scrubbed_summary = self._scrub_json_value(
                dict(result.safe_summary),
                self._sensitive_values,
            )
            if not isinstance(scrubbed_summary, dict):
                raise SessionStoreError("invalid_session_state")
            if (
                set(scrubbed_summary) != expected_summary_fields
                or scrubbed_summary.get("status") != expected_status
                or scrubbed_summary.get("termination_reason")
                != result.termination_reason
            ):
                raise SessionStoreError("invalid_session_state")
            final_report_json: str | None = None
            if result.final_report is not None:
                try:
                    projected = make_persisted_run_report(result.final_report)
                except (TypeError, ValueError):
                    raise SessionStoreError("invalid_session_state") from None
                if projected != result.final_report:
                    raise SessionStoreError("invalid_session_state")
                if (
                    result.audit_run_id is None
                    or projected["run_id"] != result.audit_run_id
                    or projected["status"] != expected_status
                    or projected["termination_reason"] != result.termination_reason
                ):
                    raise SessionStoreError("invalid_session_state")
                scrubbed_report = self._scrub_json_value(
                    projected,
                    self._sensitive_values,
                )
                if not isinstance(scrubbed_report, dict):
                    raise SessionStoreError("invalid_session_state")
                try:
                    projected = make_persisted_run_report(scrubbed_report)
                except (TypeError, ValueError):
                    raise SessionStoreError("invalid_session_state") from None
                final_report_json = self._canonical_json(projected)
            finish_event = SessionEvent(
                session_id=current.session_id,
                run_id=current.run_id,
                sequence=session.next_sequence,
                kind=PersistedSessionEventKind.RUN_FINISHED,
                created_at_utc=timestamp,
                data=scrubbed_summary,  # type: ignore[arg-type]
            )
            connection.execute(
                "UPDATE session_runs SET status = ?, finished_at_utc = ?, "
                "agent_status = ?, termination_reason = ?, audit_run_id = ?, "
                "final_report_json = ? WHERE run_id = ?",
                (
                    result.status.value,
                    timestamp,
                    result.agent_status,
                    result.termination_reason,
                    result.audit_run_id,
                    final_report_json,
                    result.run_id,
                ),
            )
            self._insert_event(connection, finish_event)
            connection.execute(
                "UPDATE sessions SET status = ?, updated_at_utc = ?, next_sequence = ? "
                "WHERE session_id = ?",
                (
                    SessionStatus.IDLE.value,
                    timestamp,
                    session.next_sequence + 1,
                    current.session_id,
                ),
            )
            terminal = self._decode_run(
                self._select_run(connection, result.run_id)
            )
            connection.commit()
            return terminal
        except SessionStoreError:
            self._rollback(connection)
            raise
        except sqlite3.Error as exc:
            self._rollback(connection)
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

    def recover_incomplete_runs(self) -> tuple[SessionRunRecord, ...]:
        connection = self._connect()
        try:
            self._begin(connection)
            rows = connection.execute(
                "SELECT * FROM session_runs "
                "WHERE status IN ('queued', 'running', 'cancelling') "
                "ORDER BY session_id ASC, ordinal ASC"
            ).fetchall()
            if not rows:
                connection.commit()
                return ()
            timestamp = self._timestamp()
            recovered: list[SessionRunRecord] = []
            for row in rows:
                current = self._decode_run(row)
                session = self._decode_session(
                    self._select_session(connection, current.session_id)
                )
                event = SessionEvent(
                    session_id=current.session_id,
                    run_id=current.run_id,
                    sequence=session.next_sequence,
                    kind=PersistedSessionEventKind.RUN_RECOVERED,
                    created_at_utc=timestamp,
                    data={
                        "status": SessionRunStatus.INTERRUPTED.value,
                        "termination_reason": "process_restarted",
                    },
                )
                connection.execute(
                    "UPDATE session_runs SET status = ?, finished_at_utc = ?, "
                    "agent_status = NULL, termination_reason = ?, audit_run_id = NULL, "
                    "final_report_json = NULL WHERE run_id = ?",
                    (
                        SessionRunStatus.INTERRUPTED.value,
                        timestamp,
                        "process_restarted",
                        current.run_id,
                    ),
                )
                self._insert_event(connection, event)
                connection.execute(
                    "UPDATE sessions SET status = ?, updated_at_utc = ?, "
                    "next_sequence = ? WHERE session_id = ?",
                    (
                        SessionStatus.IDLE.value,
                        timestamp,
                        session.next_sequence + 1,
                        current.session_id,
                    ),
                )
                recovered.append(
                    SessionRunRecord(
                        run_id=current.run_id,
                        session_id=current.session_id,
                        ordinal=current.ordinal,
                        status=SessionRunStatus.INTERRUPTED,
                        user_event_sequence=current.user_event_sequence,
                        started_at_utc=current.started_at_utc,
                        finished_at_utc=timestamp,
                        agent_status=None,
                        termination_reason="process_restarted",
                        audit_run_id=None,
                        final_report=None,
                    )
                )
            connection.commit()
            return tuple(recovered)
        except SessionStoreError:
            self._rollback(connection)
            raise
        except (TypeError, ValueError):
            self._rollback(connection)
            raise SessionStoreError("database_corrupt") from None
        except sqlite3.Error as exc:
            self._rollback(connection)
            raise _sqlite_store_error(exc) from None
        finally:
            connection.close()

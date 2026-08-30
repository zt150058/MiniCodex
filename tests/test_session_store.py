from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import Thread

import pytest

from coding_agent.run_mode import RunMode
from coding_agent.session import (
    NewSessionEvent,
    PersistedSessionEventKind,
    SessionNarrativeKind,
    SessionRunResult,
    SessionRunStatus,
    SessionStatus,
    SessionStoreError,
    make_safe_run_summary,
)
from coding_agent.session_store import SQLiteSessionStore, WorkspaceSessionLease
from coding_agent.skills import (
    RunSkillSnapshotMetadata,
    SkillDescriptor,
    SkillSource,
)


NOW = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)


def safe_tool_activity() -> dict[str, object]:
    return {
        "tool_name": "read_file",
        "status": "ok",
        "duration_ms": 2,
        "truncated": False,
        "exit_code": None,
        "safe_error_code": None,
        "changed_paths": [],
    }


def persisted_failed_report(
    audit_run_id: str,
    reason: str = "empty_model_response",
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "run_id": audit_run_id,
        "run_mode": "modify",
        "status": "failed",
        "exit_code": 1,
        "termination_reason": reason,
        "changed_paths": [],
        "mutation_index": 0,
        "validation_index": None,
        "verification": {
            "status": "not_run",
            "source": None,
            "exit_code": None,
            "timed_out": False,
            "truncated": False,
            "duration_ms": None,
            "validation_index": None,
            "error_code": None,
        },
        "logical_model_calls": 0,
        "provider_attempts": 0,
        "tool_calls": 0,
        "verification_attempts": 0,
        "context_compressions": 0,
        "token_usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "responses_with_usage": 0,
            "responses_without_usage": 0,
        },
        "elapsed_ms": 1,
        "log_failure_code": None,
        "log_path": f".coding-agent/logs/{audit_run_id}.jsonl",
    }


def _persisted_terminal_report(
    audit_run_id: str,
    mode: RunMode,
) -> dict[str, object]:
    report = persisted_failed_report(audit_run_id)
    report["run_mode"] = mode.value
    report.update(
        status="answered" if mode is RunMode.READ_ONLY else "success",
        exit_code=0,
        termination_reason=None,
    )
    if mode is RunMode.MODIFY:
        report.update(validation_index=0, verification_attempts=1)
        report["verification"] = {
            "status": "passed",
            "source": "user_verify",
            "exit_code": 0,
            "timed_out": False,
            "truncated": False,
            "duration_ms": 1,
            "validation_index": 0,
            "error_code": None,
        }
    return report


def _terminal_result(run_id: str, mode: RunMode) -> SessionRunResult:
    audit_run_id = "f" * 32
    report = _persisted_terminal_report(audit_run_id, mode)
    agent_status = "answered" if mode is RunMode.READ_ONLY else "success"
    return SessionRunResult(
        run_id=run_id,
        status=SessionRunStatus.SUCCEEDED,
        agent_status=agent_status,
        termination_reason=None,
        audit_run_id=audit_run_id,
        safe_summary=make_safe_run_summary(
            report,
            status=agent_status,
            termination_reason=None,
        ),
        final_report=report,
    )


@pytest.mark.parametrize("mode", tuple(RunMode))
def test_run_mode_survives_list_get_start_finish_and_reopen(
    tmp_path: Path,
    mode: RunMode,
) -> None:
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    store.initialize()
    submission = store.create_session("message", run_mode=mode)
    run_id = submission.run.run_id

    assert submission.run.run_mode is mode
    assert store.list_runs(submission.session.session_id)[0].run_mode is mode
    assert store.get_run(run_id).run_mode is mode
    assert store.start_run(run_id).run_mode is mode
    terminal = store.finish_run(_terminal_result(run_id, mode))
    assert terminal.run_mode is mode

    reopened = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    reopened.initialize()
    assert reopened.get_run(run_id).run_mode is mode


def test_interrupted_read_only_recovery_preserves_mode(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    store.initialize()
    submission = store.create_session("inspect", run_mode=RunMode.READ_ONLY)

    recovered = store.recover_incomplete_runs()

    assert len(recovered) == 1
    assert recovered[0].run_id == submission.run.run_id
    assert recovered[0].run_mode is RunMode.READ_ONLY
    assert store.get_run(submission.run.run_id).run_mode is RunMode.READ_ONLY


def _version_1_report(
    audit_run_id: str,
    *,
    successful: bool,
) -> dict[str, object]:
    report = persisted_failed_report(audit_run_id)
    report.pop("run_mode")
    report["schema_version"] = 1
    if successful:
        report.update(
            status="success",
            exit_code=0,
            termination_reason=None,
            validation_index=0,
            verification_attempts=1,
        )
        report["verification"] = {
            "status": "passed",
            "source": "user_verify",
            "exit_code": 0,
            "timed_out": False,
            "truncated": False,
            "duration_ms": 1,
            "validation_index": 0,
            "error_code": None,
        }
    return report


def _database_path(tmp_path: Path) -> Path:
    return tmp_path / ".coding-agent" / "sessions.sqlite3"


def _database_user_version(tmp_path: Path) -> int:
    with sqlite3.connect(_database_path(tmp_path)) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _session_run_columns(tmp_path: Path) -> tuple[str, ...]:
    with sqlite3.connect(_database_path(tmp_path)) as connection:
        return tuple(
            row[1]
            for row in connection.execute("PRAGMA table_info(session_runs)")
        )


def _create_real_version_2_database(
    tmp_path: Path,
    *,
    reports: tuple[dict[str, object], ...],
) -> None:
    internal = tmp_path / ".coding-agent"
    internal.mkdir()
    database = internal / "sessions.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY CHECK(length(session_id) > 0),
                title TEXT NOT NULL CHECK(length(title) > 0),
                status TEXT NOT NULL CHECK(status IN ('idle', 'running', 'cancelling')),
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                last_run_id TEXT,
                next_sequence INTEGER NOT NULL CHECK(next_sequence > 0)
            );
            CREATE TABLE session_runs (
                run_id TEXT PRIMARY KEY CHECK(length(run_id) > 0),
                session_id TEXT NOT NULL REFERENCES sessions(session_id),
                ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                status TEXT NOT NULL CHECK(status IN (
                    'queued', 'running', 'cancelling', 'succeeded', 'failed', 'interrupted'
                )),
                user_event_sequence INTEGER NOT NULL CHECK(user_event_sequence > 0),
                started_at_utc TEXT,
                finished_at_utc TEXT,
                agent_status TEXT,
                termination_reason TEXT,
                audit_run_id TEXT,
                final_report_json TEXT,
                UNIQUE(session_id, ordinal)
            );
            """
        )
        session_id = "1" * 32
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, "historical", "idle", "2026-08-29T08:00:00Z", "2026-08-29T08:00:00Z", None, 1),
        )
        for ordinal, report in enumerate(reports, start=1):
            run_id = f"{ordinal + 1:x}" * 32
            connection.execute(
                "INSERT INTO session_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    session_id,
                    ordinal,
                    "failed",
                    ordinal,
                    "2026-08-29T08:00:00Z",
                    "2026-08-29T08:00:01Z",
                    report.get("status", "failed"),
                    report.get("termination_reason", "model_error"),
                    report.get("run_id"),
                    json.dumps(report, sort_keys=True, separators=(",", ":")),
                ),
            )
        connection.execute("PRAGMA user_version = 2")
        connection.commit()


def test_fresh_store_schema_v3_persists_each_run_mode(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    store.initialize()
    modify = store.create_session("modify", run_mode=RunMode.MODIFY)
    store.recover_incomplete_runs()
    readonly = store.submit_message(
        modify.session.session_id,
        "inspect",
        run_mode=RunMode.READ_ONLY,
    )

    assert store.get_run(modify.run.run_id).run_mode is RunMode.MODIFY
    assert store.get_run(readonly.run.run_id).run_mode is RunMode.READ_ONLY
    assert _database_user_version(tmp_path) == 3


def test_version_2_store_migrates_runs_and_reports_atomically(
    tmp_path: Path,
) -> None:
    _create_real_version_2_database(
        tmp_path,
        reports=(
            _version_1_report("a" * 32, successful=True),
            _version_1_report("b" * 32, successful=False),
        ),
    )
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    store.initialize()

    with sqlite3.connect(_database_path(tmp_path)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT run_mode, final_report_json FROM session_runs ORDER BY ordinal"
        ).fetchall()
    assert [row["run_mode"] for row in rows] == ["modify", "modify"]
    reports = [json.loads(row["final_report_json"]) for row in rows]
    assert all(report["schema_version"] == 2 for report in reports)
    assert all(report["run_mode"] == "modify" for report in reports)
    assert _database_user_version(tmp_path) == 3


def test_invalid_historical_report_rolls_back_entire_migration(
    tmp_path: Path,
) -> None:
    _create_real_version_2_database(
        tmp_path,
        reports=({"schema_version": 1},),
    )
    with pytest.raises(SessionStoreError) as captured:
        SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW).initialize()
    assert captured.value.code == "storage_unavailable"
    assert _database_user_version(tmp_path) == 2
    assert "run_mode" not in _session_run_columns(tmp_path)


@pytest.mark.parametrize("value", ["auto", "READ_ONLY", None])
def test_fresh_schema_v3_rejects_invalid_run_mode_values(
    tmp_path: Path,
    value: object,
) -> None:
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    store.initialize()
    submission = store.create_session("modify")
    with sqlite3.connect(_database_path(tmp_path)) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE session_runs SET run_mode = ? WHERE run_id = ?",
                (value, submission.run.run_id),
            )


def test_schema_newer_than_v3_is_rejected(tmp_path: Path) -> None:
    internal = tmp_path / ".coding-agent"
    internal.mkdir()
    with sqlite3.connect(internal / "sessions.sqlite3") as connection:
        connection.execute("PRAGMA user_version = 4")
    with pytest.raises(SessionStoreError) as captured:
        SQLiteSessionStore(tmp_path).initialize()
    assert captured.value.code == "schema_unsupported"


def test_initialize_creates_versioned_wal_database(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    assert store.workspace == tmp_path.resolve(strict=True)
    store.initialize()
    database = tmp_path / ".coding-agent" / "sessions.sqlite3"
    assert database.is_file()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (3,)
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "sessions",
            "session_runs",
            "session_skill_selections",
            "run_skill_snapshots",
            "session_events",
        } <= names
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_initialize_migrates_v1_sessions_to_empty_skill_selection(
    tmp_path: Path,
) -> None:
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    store.initialize()
    submission = store.create_session("existing")
    database = tmp_path / ".coding-agent" / "sessions.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE IF EXISTS run_skill_snapshots")
        connection.execute("DROP TABLE IF EXISTS session_skill_selections")
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    migrated = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    migrated.initialize()
    assert migrated.get_session(submission.session.session_id).title == "existing"
    assert migrated.get_skill_selection(submission.session.session_id) == ()
    assert migrated.get_run_skill_snapshots(submission.run.run_id) == ()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (3,)


def test_skill_reads_distinguish_missing_parent_from_empty_children(
    tmp_path: Path,
) -> None:
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    store.initialize()
    with pytest.raises(SessionStoreError) as session_error:
        store.get_skill_selection("f" * 32)
    assert session_error.value.code == "session_not_found"
    with pytest.raises(SessionStoreError) as run_error:
        store.get_run_skill_snapshots("e" * 32)
    assert run_error.value.code == "run_not_found"


def test_replace_skill_selection_is_ordered_and_atomic(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    store.initialize()
    submission = store.create_session("first")
    store.recover_incomplete_runs()
    assert store.replace_skill_selection(
        submission.session.session_id,
        ("second", "first"),
    ) == ("second", "first")
    assert store.get_skill_selection(submission.session.session_id) == (
        "second",
        "first",
    )
    with pytest.raises(SessionStoreError) as captured:
        store.replace_skill_selection(
            submission.session.session_id,
            ("valid", "valid"),
        )
    assert captured.value.code == "invalid_skill_selection"
    assert store.get_skill_selection(submission.session.session_id) == (
        "second",
        "first",
    )
    assert store.replace_skill_selection(submission.session.session_id, ()) == ()


def test_replace_skill_selection_rejects_running_session(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    store.initialize()
    submission = store.create_session("running")
    with pytest.raises(SessionStoreError) as captured:
        store.replace_skill_selection(submission.session.session_id, ("review",))
    assert captured.value.code == "invalid_session_state"
    assert store.get_skill_selection(submission.session.session_id) == ()


def descriptor(skill_id: str, source: SkillSource) -> SkillDescriptor:
    body = f"body-{skill_id}"
    return SkillDescriptor(
        skill_id=skill_id,
        name=skill_id.title(),
        description="safe",
        source=source,
        sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        char_count=len(body),
    )


def test_create_and_submit_persist_safe_skill_snapshot_metadata(
    tmp_path: Path,
) -> None:
    ids = iter(("1" * 32, "2" * 32, "3" * 32))
    store = SQLiteSessionStore(tmp_path, id_factory=lambda: next(ids))
    store.initialize()
    selected = (
        descriptor("second", SkillSource.WORKSPACE),
        descriptor("first", SkillSource.USER),
    )
    first = store.create_session("first", selected_skills=selected)
    assert store.get_skill_selection(first.session.session_id) == (
        "second",
        "first",
    )
    assert store.get_run_skill_snapshots(first.run.run_id) == tuple(
        RunSkillSnapshotMetadata(
            skill_id=item.skill_id,
            source=item.source,
            sha256=item.sha256,
            char_count=item.char_count,
        )
        for item in selected
    )
    store.recover_incomplete_runs()
    second = store.submit_message(
        first.session.session_id,
        "second",
        selected_skills=selected,
    )
    assert store.get_run_skill_snapshots(
        second.run.run_id
    ) == store.get_run_skill_snapshots(first.run.run_id)


def test_submit_rejects_stale_resolved_selection_without_side_effect(
    tmp_path: Path,
) -> None:
    store = SQLiteSessionStore(tmp_path)
    store.initialize()
    first = store.create_session(
        "first",
        selected_skills=(descriptor("first", SkillSource.USER),),
    )
    store.recover_incomplete_runs()
    store.replace_skill_selection(first.session.session_id, ("second",))
    before_runs = store.list_runs(first.session.session_id)
    before_events = store.load_events(first.session.session_id)
    with pytest.raises(SessionStoreError) as captured:
        store.submit_message(
            first.session.session_id,
            "stale",
            selected_skills=(descriptor("first", SkillSource.USER),),
        )
    assert captured.value.code == "invalid_session_state"
    assert store.list_runs(first.session.session_id) == before_runs
    assert store.load_events(first.session.session_id) == before_events


@pytest.mark.parametrize(
    ("table", "assignment"),
    (
        ("session_skill_selections", "skill_id = 'Bad_ID'"),
        ("session_skill_selections", "position = 0"),
        ("run_skill_snapshots", "source = 'corrupt'"),
        ("run_skill_snapshots", "sha256 = 'not-a-hash'"),
        ("run_skill_snapshots", "char_count = 0"),
    ),
)
def test_corrupt_skill_rows_are_reported_as_database_corrupt(
    tmp_path: Path,
    table: str,
    assignment: str,
) -> None:
    store = SQLiteSessionStore(tmp_path)
    store.initialize()
    first = store.create_session(
        "first",
        selected_skills=(descriptor("first", SkillSource.USER),),
    )
    database = tmp_path / ".coding-agent" / "sessions.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(f"UPDATE {table} SET {assignment}")
        connection.commit()
    with pytest.raises(SessionStoreError) as captured:
        if table == "session_skill_selections":
            store.get_skill_selection(first.session.session_id)
        else:
            store.get_run_skill_snapshots(first.run.run_id)
    assert captured.value.code == "database_corrupt"
    assert "Bad_ID" not in repr(captured.value)
    assert "not-a-hash" not in repr(captured.value)


def test_workspace_lease_is_exclusive_and_reacquirable(tmp_path: Path) -> None:
    first = WorkspaceSessionLease.acquire(tmp_path)
    assert first.workspace == tmp_path.resolve(strict=True)
    try:
        with pytest.raises(SessionStoreError) as captured:
            WorkspaceSessionLease.acquire(tmp_path)
        assert captured.value.code == "controller_in_use"
    finally:
        first.close()
    second = WorkspaceSessionLease.acquire(tmp_path)
    second.close()


def test_store_rejects_reparse_internal_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    internal = tmp_path / ".coding-agent"
    try:
        internal.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.fail(f"target Windows environment must allow this test: {exc}")
    with pytest.raises(SessionStoreError) as captured:
        SQLiteSessionStore(tmp_path).initialize()
    assert captured.value.code == "storage_unavailable"
    assert not (outside / "sessions.sqlite3").exists()


def test_create_and_follow_up_are_atomic_and_stably_ordered(tmp_path: Path) -> None:
    ids = iter(("1" * 32, "2" * 32, "3" * 32))
    times = iter(
        datetime(2026, 8, 29, 8, minute, tzinfo=timezone.utc)
        for minute in range(6)
    )
    store = SQLiteSessionStore(
        tmp_path,
        id_factory=lambda: next(ids),
        utc_clock=lambda: next(times),
        sensitive_values=("sk-private",),
    )
    store.initialize()

    first = store.create_session(" Fix sk-private parser \nignored")
    assert first.session.session_id == "1" * 32
    assert first.run.run_id == "2" * 32
    assert first.run.ordinal == 1
    assert first.user_event.sequence == 1
    assert first.session.next_sequence == 3
    assert "sk-private" not in str(store.load_events(first.session.session_id))

    store.finish_run(
        SessionRunResult(
            run_id=first.run.run_id,
            status=SessionRunStatus.FAILED,
            agent_status="failed",
            termination_reason="empty_model_response",
            audit_run_id="4" * 32,
            safe_summary=make_safe_run_summary(
                None,
                status="failed",
                termination_reason="empty_model_response",
            ),
            final_report=persisted_failed_report("4" * 32),
        )
    )
    assert store.get_run(first.run.run_id).final_report == persisted_failed_report(
        "4" * 32
    )
    second = store.submit_message(first.session.session_id, "Try again")
    assert second.run.ordinal == 2
    assert second.user_event.sequence < second.session.next_sequence
    events = store.load_events(first.session.session_id)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert store.get_session(first.session.session_id).status is SessionStatus.RUNNING
    assert store.get_run(second.run.run_id) == second.run
    assert [run.ordinal for run in store.list_runs(first.session.session_id)] == [1, 2]


def test_finish_run_scrubs_sensitive_terminal_paths_before_persistence(
    tmp_path: Path,
) -> None:
    sensitive = "private-name"
    store = SQLiteSessionStore(tmp_path, sensitive_values=(sensitive,))
    store.initialize()
    submission = store.create_session("Fix it")
    report = persisted_failed_report("4" * 32)
    report["changed_paths"] = [f"src/{sensitive}.py"]
    result = SessionRunResult(
        run_id=submission.run.run_id,
        status=SessionRunStatus.FAILED,
        agent_status="failed",
        termination_reason="empty_model_response",
        audit_run_id="4" * 32,
        safe_summary=make_safe_run_summary(
            report,
            status="failed",
            termination_reason="empty_model_response",
        ),
        final_report=report,
    )

    terminal = store.finish_run(result)

    assert terminal.final_report is not None
    assert terminal.final_report["changed_paths"] == ["src/[REDACTED].py"]
    events = store.load_events(submission.session.session_id)
    finished = next(
        event
        for event in events
        if event.kind is PersistedSessionEventKind.RUN_FINISHED
    )
    assert finished.data["changed_paths"] == ["src/[REDACTED].py"]
    narrative = store.load_narrative(submission.session.session_id)
    assert sensitive not in repr(terminal)
    assert sensitive not in repr(events)
    assert sensitive not in repr(narrative)
    database = tmp_path / ".coding-agent" / "sessions.sqlite3"
    with sqlite3.connect(database) as connection:
        event_json = connection.execute(
            "SELECT data_json FROM session_events WHERE run_id = ? AND kind = ?",
            (submission.run.run_id, PersistedSessionEventKind.RUN_FINISHED.value),
        ).fetchone()[0]
        report_json = connection.execute(
            "SELECT final_report_json FROM session_runs WHERE run_id = ?",
            (submission.run.run_id,),
        ).fetchone()[0]
    assert sensitive not in event_json
    assert sensitive not in report_json
    assert json.loads(event_json)["changed_paths"] == ["src/[REDACTED].py"]
    assert json.loads(report_json)["changed_paths"] == ["src/[REDACTED].py"]


def test_submit_message_returns_transaction_snapshot_without_post_commit_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = deterministic_store(tmp_path)
    first = store.create_session("first")
    store.finish_run(interrupted_result(first.run.run_id))

    def fail_read(session_id: str) -> object:
        del session_id
        raise AssertionError("post-commit read must not run")

    monkeypatch.setattr(store, "get_session", fail_read)
    submission = store.submit_message(first.session.session_id, "follow up")

    assert submission.session.status is SessionStatus.RUNNING
    assert submission.session.last_run_id == submission.run.run_id
    reopened = SQLiteSessionStore(tmp_path)
    assert reopened.get_run(submission.run.run_id).status is SessionRunStatus.QUEUED


def test_start_run_returns_transaction_snapshot_without_post_commit_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = deterministic_store(tmp_path)
    submission = store.create_session("start")

    def fail_read(run_id: str) -> object:
        del run_id
        raise AssertionError("post-commit read must not run")

    monkeypatch.setattr(store, "get_run", fail_read)
    running = store.start_run(submission.run.run_id)

    assert running.status is SessionRunStatus.RUNNING
    reopened = SQLiteSessionStore(tmp_path)
    assert reopened.get_run(running.run_id).status is SessionRunStatus.RUNNING
    assert any(
        event.kind is PersistedSessionEventKind.RUN_STARTED
        for event in reopened.load_events(submission.session.session_id)
    )


def test_cancellation_returns_transaction_snapshot_without_post_commit_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = deterministic_store(tmp_path)
    submission = store.create_session("cancel")
    store.start_run(submission.run.run_id)

    def fail_read(run_id: str) -> object:
        del run_id
        raise AssertionError("post-commit read must not run")

    monkeypatch.setattr(store, "get_run", fail_read)
    cancelling = store.request_cancellation(submission.run.run_id)

    assert cancelling.status is SessionRunStatus.CANCELLING
    reopened = SQLiteSessionStore(tmp_path)
    assert reopened.get_run(cancelling.run_id).status is SessionRunStatus.CANCELLING
    events = reopened.load_events(submission.session.session_id)
    assert sum(
        event.kind is PersistedSessionEventKind.CANCELLATION_REQUESTED
        for event in events
    ) == 1


def test_finish_run_returns_transaction_snapshot_without_post_commit_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = deterministic_store(tmp_path)
    submission = store.create_session("finish")
    store.start_run(submission.run.run_id)

    def fail_read(run_id: str) -> object:
        del run_id
        raise AssertionError("post-commit read must not run")

    monkeypatch.setattr(store, "get_run", fail_read)
    terminal = store.finish_run(interrupted_result(submission.run.run_id))

    assert terminal.status is SessionRunStatus.INTERRUPTED
    reopened = SQLiteSessionStore(tmp_path)
    assert reopened.get_run(terminal.run_id).status is SessionRunStatus.INTERRUPTED
    assert reopened.get_session(submission.session.session_id).status is SessionStatus.IDLE
    assert any(
        event.kind is PersistedSessionEventKind.RUN_FINISHED
        for event in reopened.load_events(submission.session.session_id)
    )


def make_store_with_repeated_clock(tmp_path: Path) -> SQLiteSessionStore:
    ids = iter(f"{digit}" * 32 for digit in "123456")
    return SQLiteSessionStore(
        tmp_path,
        id_factory=lambda: next(ids),
        utc_clock=lambda: NOW,
    )


def test_list_sessions_uses_updated_desc_then_id_asc(tmp_path: Path) -> None:
    store = make_store_with_repeated_clock(tmp_path)
    store.initialize()
    ids: list[str] = []
    for text in ("a", "b", "c"):
        submission = store.create_session(text)
        ids.append(submission.session.session_id)
        store.finish_run(
            SessionRunResult(
                run_id=submission.run.run_id,
                status=SessionRunStatus.FAILED,
                agent_status="failed",
                termination_reason="empty_model_response",
                audit_run_id=None,
                safe_summary=make_safe_run_summary(
                    None,
                    status="failed",
                    termination_reason="empty_model_response",
                ),
                final_report=None,
            )
        )
    assert [item.session_id for item in store.list_sessions(limit=2)] == sorted(ids)[:2]


def deterministic_store(tmp_path: Path) -> SQLiteSessionStore:
    ids = iter(f"{digit:x}" * 32 for digit in range(1, 16))
    store = SQLiteSessionStore(
        tmp_path,
        id_factory=lambda: next(ids),
        utc_clock=lambda: NOW,
    )
    store.initialize()
    return store


def interrupted_result(run_id: str) -> SessionRunResult:
    return SessionRunResult(
        run_id=run_id,
        status=SessionRunStatus.INTERRUPTED,
        agent_status="interrupted",
        termination_reason="user_interrupted",
        audit_run_id="4" * 32,
        safe_summary=make_safe_run_summary(
            None,
            status="interrupted",
            termination_reason="user_interrupted",
        ),
        final_report=None,
    )


def test_run_transitions_and_cancel_are_atomic(tmp_path: Path) -> None:
    store = deterministic_store(tmp_path)
    submission = store.create_session("Fix it")
    running = store.start_run(submission.run.run_id)
    assert running.status is SessionRunStatus.RUNNING
    committed = store.append_event(
        NewSessionEvent(
            session_id=submission.session.session_id,
            run_id=running.run_id,
            kind=PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED,
            data={"content": "I inspected the file."},
        )
    )
    first_cancel = store.request_cancellation(running.run_id)
    second_cancel = store.request_cancellation(running.run_id)
    assert first_cancel.status is SessionRunStatus.CANCELLING
    assert second_cancel == first_cancel
    cancellation_events = [
        event
        for event in store.load_events(submission.session.session_id)
        if event.kind is PersistedSessionEventKind.CANCELLATION_REQUESTED
    ]
    assert len(cancellation_events) == 1
    terminal = store.finish_run(interrupted_result(running.run_id))
    assert terminal.status is SessionRunStatus.INTERRUPTED
    assert store.get_session(submission.session.session_id).status is SessionStatus.IDLE
    assert committed.sequence < store.load_events(submission.session.session_id)[-1].sequence
    narrative = store.load_narrative(submission.session.session_id)
    assert [entry.kind for entry in narrative] == [
        SessionNarrativeKind.USER,
        SessionNarrativeKind.ASSISTANT,
        SessionNarrativeKind.RUN_SUMMARY,
    ]
    assert all("stdout" not in entry.content for entry in narrative)


def test_finish_rejects_full_or_unprojected_report_without_writing(
    tmp_path: Path,
) -> None:
    store = deterministic_store(tmp_path)
    submission = store.create_session("Fix it")
    running = store.start_run(submission.run.run_id)
    unsafe = SessionRunResult(
        run_id=running.run_id,
        status=SessionRunStatus.FAILED,
        agent_status="failed",
        termination_reason="empty_model_response",
        audit_run_id="4" * 32,
        safe_summary=make_safe_run_summary(
            None,
            status="failed",
            termination_reason="empty_model_response",
        ),
        final_report={
            "completion": {"text": "must not persist"},
            "verification": {"command": "pytest -q", "stdout": "private"},
        },
    )
    with pytest.raises(SessionStoreError) as captured:
        store.finish_run(unsafe)
    assert captured.value.code == "invalid_session_state"
    assert store.get_run(running.run_id).status is SessionRunStatus.RUNNING
    assert all(
        event.kind is not PersistedSessionEventKind.RUN_FINISHED
        for event in store.load_events(submission.session.session_id)
    )


def test_active_run_unique_constraint_rolls_back_second_submission(
    tmp_path: Path,
) -> None:
    store = deterministic_store(tmp_path)
    first = store.create_session("first")
    with pytest.raises(SessionStoreError) as captured:
        store.create_session("second")
    assert captured.value.code == "controller_busy"
    assert len(store.list_sessions()) == 1
    assert store.get_session(first.session.session_id).status is SessionStatus.RUNNING


def test_invalid_transitions_have_no_partial_side_effects(tmp_path: Path) -> None:
    store = deterministic_store(tmp_path)
    submission = store.create_session("Fix it")
    with pytest.raises(SessionStoreError) as queued_cancel:
        store.request_cancellation(submission.run.run_id)
    assert queued_cancel.value.code == "invalid_session_state"
    assert store.get_run(submission.run.run_id).status is SessionRunStatus.QUEUED

    running = store.start_run(submission.run.run_id)
    event_count = len(store.load_events(submission.session.session_id))
    with pytest.raises(SessionStoreError) as second_start:
        store.start_run(running.run_id)
    assert second_start.value.code == "invalid_session_state"
    assert len(store.load_events(submission.session.session_id)) == event_count

    with pytest.raises(SessionStoreError) as wrong_pair:
        store.append_event(
            NewSessionEvent(
                session_id="3" * 32,
                run_id=running.run_id,
                kind=PersistedSessionEventKind.TOOL_ACTIVITY,
                data=safe_tool_activity(),
            )
        )
    assert wrong_pair.value.code == "invalid_session_state"
    assert len(store.load_events(submission.session.session_id)) == event_count

    terminal = store.finish_run(interrupted_result(running.run_id))
    terminal_event_count = len(store.load_events(submission.session.session_id))
    for operation in (
        lambda: store.finish_run(interrupted_result(terminal.run_id)),
        lambda: store.append_event(
            NewSessionEvent(
                session_id=submission.session.session_id,
                run_id=terminal.run_id,
                kind=PersistedSessionEventKind.TOOL_ACTIVITY,
                data=safe_tool_activity(),
            )
        ),
        lambda: store.request_cancellation(terminal.run_id),
    ):
        with pytest.raises(SessionStoreError) as invalid:
            operation()
        assert invalid.value.code == "invalid_session_state"
    assert len(store.load_events(submission.session.session_id)) == terminal_event_count

    with pytest.raises(SessionStoreError) as unknown:
        store.request_cancellation("f" * 32)
    assert unknown.value.code == "run_not_found"


def test_recovery_interrupts_incomplete_runs_without_executor(tmp_path: Path) -> None:
    store = deterministic_store(tmp_path)
    first = store.create_session("first")
    store.start_run(first.run.run_id)
    recovered = store.recover_incomplete_runs()
    assert [(run.run_id, run.status, run.termination_reason) for run in recovered] == [
        (first.run.run_id, SessionRunStatus.INTERRUPTED, "process_restarted")
    ]
    assert store.get_session(first.session.session_id).status is SessionStatus.IDLE
    assert (
        store.load_events(first.session.session_id)[-1].kind
        is PersistedSessionEventKind.RUN_RECOVERED
    )
    assert store.recover_incomplete_runs() == ()


def capture_failure(failures: list[BaseException], operation: object) -> None:
    assert callable(operation)
    try:
        operation()
    except BaseException as exc:
        failures.append(exc)


def test_connections_are_safe_across_caller_and_worker_threads(
    tmp_path: Path,
) -> None:
    store = deterministic_store(tmp_path)
    submission = store.create_session("threaded")
    failures: list[BaseException] = []
    thread = Thread(
        target=lambda: capture_failure(
            failures,
            lambda: store.start_run(submission.run.run_id),
        )
    )
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert failures == []


def test_schema_unsupported_newer_version_is_not_replaced(tmp_path: Path) -> None:
    internal = tmp_path / ".coding-agent"
    internal.mkdir()
    database = internal / "sessions.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 4")
    with pytest.raises(SessionStoreError) as captured:
        SQLiteSessionStore(tmp_path).initialize()
    assert captured.value.code == "schema_unsupported"
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (4,)


def test_database_corrupt_non_database_bytes_are_not_replaced(
    tmp_path: Path,
) -> None:
    internal = tmp_path / ".coding-agent"
    internal.mkdir()
    database = internal / "sessions.sqlite3"
    original = b"private non database bytes"
    database.write_bytes(original)
    with pytest.raises(SessionStoreError) as captured:
        SQLiteSessionStore(tmp_path).initialize()
    assert captured.value.code == "database_corrupt"
    assert database.read_bytes() == original


def test_malformed_stored_json_is_database_corrupt(tmp_path: Path) -> None:
    store = deterministic_store(tmp_path)
    submission = store.create_session("first")
    database = tmp_path / ".coding-agent" / "sessions.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE session_events SET data_json = ? WHERE session_id = ? AND sequence = 1",
            ("[]", submission.session.session_id),
        )
    with pytest.raises(SessionStoreError) as captured:
        store.load_events(submission.session.session_id)
    assert captured.value.code == "database_corrupt"


def test_create_transaction_rollback_after_injected_event_failure(
    tmp_path: Path,
) -> None:
    store = deterministic_store(tmp_path)
    database = tmp_path / ".coding-agent" / "sessions.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER reject_queued_event BEFORE INSERT ON session_events "
            "WHEN NEW.kind = 'run_queued' BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    with pytest.raises(SessionStoreError) as captured:
        store.create_session("first")
    assert captured.value.code == "storage_unavailable"
    assert store.list_sessions() == ()


def test_real_process_lease_is_exclusive_and_reacquirable(tmp_path: Path) -> None:
    script = (
        "from pathlib import Path\n"
        "import sys\n"
        "from coding_agent.session_store import WorkspaceSessionLease\n"
        "lease = WorkspaceSessionLease.acquire(Path(sys.argv[1]))\n"
        "print('ready', flush=True)\n"
        "sys.stdin.readline()\n"
        "lease.close()\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path.cwd(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    assert process.stdout is not None
    assert process.stdin is not None
    try:
        assert process.stdout.readline().strip() == "ready"
        with pytest.raises(SessionStoreError) as captured:
            WorkspaceSessionLease.acquire(tmp_path)
        assert captured.value.code == "controller_in_use"
    finally:
        process.stdin.write("release\n")
        process.stdin.flush()
        process.wait(timeout=5)
    assert process.returncode == 0
    lease = WorkspaceSessionLease.acquire(tmp_path)
    lease.close()


def test_persisted_event_payloads_are_deeply_immutable_and_strict(
    tmp_path: Path,
) -> None:
    store = deterministic_store(tmp_path)
    submission = store.create_session("inspect")
    running = store.start_run(submission.run.run_id)
    event = NewSessionEvent(
        session_id=submission.session.session_id,
        run_id=running.run_id,
        kind=PersistedSessionEventKind.TOOL_ACTIVITY,
        data=safe_tool_activity(),
    )
    with pytest.raises(TypeError):
        event.data["status"] = "error"
    changed_paths = event.data["changed_paths"]
    assert isinstance(changed_paths, list)
    with pytest.raises(TypeError):
        changed_paths.append("private.py")

    before = len(store.load_events(submission.session.session_id))
    for kind, unsafe in (
        (
            PersistedSessionEventKind.TOOL_ACTIVITY,
            {**safe_tool_activity(), "arguments": {"path": "private.py"}},
        ),
        (
            PersistedSessionEventKind.VERIFICATION_ACTIVITY,
            {
                "status": "passed",
                "source": "user_verify",
                "exit_code": 0,
                "timed_out": False,
                "truncated": False,
                "duration_ms": 2,
                "validation_index": 0,
                "error_code": None,
                "stdout": "private output",
            },
        ),
    ):
        with pytest.raises((TypeError, ValueError)):
            store.append_event(
                NewSessionEvent(
                    session_id=submission.session.session_id,
                    run_id=running.run_id,
                    kind=kind,
                    data=unsafe,
                )
            )
    assert len(store.load_events(submission.session.session_id)) == before


def test_tampered_full_report_row_fails_closed_on_read(tmp_path: Path) -> None:
    store = deterministic_store(tmp_path)
    submission = store.create_session("inspect")
    report = persisted_failed_report("4" * 32)
    store.finish_run(
        SessionRunResult(
            run_id=submission.run.run_id,
            status=SessionRunStatus.FAILED,
            agent_status="failed",
            termination_reason="empty_model_response",
            audit_run_id="4" * 32,
            safe_summary=make_safe_run_summary(
                None,
                status="failed",
                termination_reason="empty_model_response",
            ),
            final_report=report,
        )
    )
    unsafe = dict(report)
    unsafe["completion"] = {"text": "private completion"}
    unsafe["failure_reason"] = "private failure"
    unsafe_verification = dict(report["verification"])
    unsafe_verification["command"] = "private command"
    unsafe_verification["stdout"] = "private stdout"
    unsafe["verification"] = unsafe_verification
    database = tmp_path / ".coding-agent" / "sessions.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE session_runs SET final_report_json = ? WHERE run_id = ?",
            (json.dumps(unsafe), submission.run.run_id),
        )
    with pytest.raises(SessionStoreError) as captured:
        store.get_run(submission.run.run_id)
    assert captured.value.code == "database_corrupt"
    assert "private" not in repr(captured.value)

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import timedelta
import json

import pytest

from coding_agent.engine.budget import BudgetProfile
from coding_agent.engine.run_mode import RunMode
from coding_agent.sessions.session import SessionError, make_session_title, utc_now, uuid4_hex
from coding_agent.sessions.session import (
    NewSessionEvent,
    PersistedSessionEventKind,
    SessionNarrativeKind,
    SessionEvent,
    SessionNarrativeEntry,
    SessionRecord,
    SessionRunRecord,
    SessionRunResult,
    SessionRunStatus,
    SessionStatus,
    SessionSubmission,
    make_persisted_run_report,
    make_safe_run_summary,
)

SESSION_ID = "1" * 32
RUN_ID = "2" * 32
NOW = "2026-08-29T08:00:00.000000Z"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("  Fix   the parser  \nignore this line", "Fix the parser"),
        ("\n\n修复 Windows 路径\n第二行", "修复 Windows 路径"),
        ("x" * 80, "x" * 80),
        ("x" * 81, "x" * 79 + "…"),
    ],
)
def test_make_session_title_is_deterministic(message: str, expected: str) -> None:
    assert make_session_title(message) == expected


def test_default_clock_and_id_factories_produce_strict_domain_values() -> None:
    now = utc_now()
    identifier = uuid4_hex()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    assert len(identifier) == 32
    assert identifier == identifier.lower()
    assert all(character in "0123456789abcdef" for character in identifier)


@pytest.mark.parametrize("message", ["", "   ", "\n\t"])
def test_make_session_title_rejects_empty_message(message: str) -> None:
    with pytest.raises(SessionError) as captured:
        make_session_title(message)
    assert captured.value.code == "invalid_message"
    assert repr(captured.value) == "SessionError('invalid_message')"


def test_domain_records_are_immutable_and_payload_repr_is_hidden() -> None:
    event = SessionEvent(
        session_id=SESSION_ID,
        run_id=RUN_ID,
        sequence=1,
        kind=PersistedSessionEventKind.USER_MESSAGE,
        created_at_utc=NOW,
        data={"content": "private conversation"},
    )
    session = SessionRecord(
        session_id=SESSION_ID,
        title="Fix parser",
        status=SessionStatus.RUNNING,
        created_at_utc=NOW,
        updated_at_utc=NOW,
        last_run_id=RUN_ID,
        next_sequence=3,
    )
    run = SessionRunRecord(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        ordinal=1,
        status=SessionRunStatus.QUEUED,
        run_mode=RunMode.MODIFY,
        budget_profile=BudgetProfile.STANDARD,
        user_event_sequence=1,
        started_at_utc=None,
        finished_at_utc=None,
        agent_status=None,
        termination_reason=None,
        audit_run_id=None,
        final_report=None,
    )
    submission = SessionSubmission(session=session, user_event=event, run=run)
    assert submission.run.status is SessionRunStatus.QUEUED
    assert "private conversation" not in repr(event)
    with pytest.raises(FrozenInstanceError):
        session.title = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_id", "not-a-uuid"),
        ("session_id", "A" * 32),
        ("sequence", 0),
        ("sequence", True),
        ("created_at_utc", "2026-08-29"),
    ],
)
def test_session_event_rejects_invalid_invariants(field: str, value: object) -> None:
    values: dict[str, object] = {
        "session_id": SESSION_ID,
        "run_id": RUN_ID,
        "sequence": 1,
        "kind": PersistedSessionEventKind.RUN_STARTED,
        "created_at_utc": NOW,
        "data": {"status": "running"},
    }
    values[field] = value
    with pytest.raises((TypeError, ValueError)):
        SessionEvent(**values)  # type: ignore[arg-type]


def test_new_event_and_run_result_hide_sensitive_payloads() -> None:
    event = NewSessionEvent(
        session_id=SESSION_ID,
        run_id=RUN_ID,
        kind=PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED,
        data={"content": "secret assistant text"},
    )
    result = SessionRunResult(
        run_id=RUN_ID,
        status=SessionRunStatus.SUCCEEDED,
        agent_status="success",
        termination_reason=None,
        audit_run_id="3" * 32,
        safe_summary={
            "status": "success",
            "exit_code": 0,
            "termination_reason": None,
            "changed_paths": [],
            "verification_status": "passed",
            "mutation_index": 0,
            "validation_index": 0,
            "logical_model_calls": 1,
            "provider_attempts": 1,
            "tool_calls": 0,
            "verification_attempts": 1,
        },
        final_report=None,
    )
    assert "secret assistant text" not in repr(event)
    assert "logical_model_calls" not in repr(result)


def test_narrative_entry_allows_only_safe_kinds_and_text() -> None:
    entry = SessionNarrativeEntry(
        run_id=RUN_ID,
        kind=SessionNarrativeKind.ASSISTANT,
        content="Finished the requested change.",
    )
    assert entry.kind.value == "assistant"
    assert "Finished" not in repr(entry)


def test_safe_run_summary_contains_only_accepted_terminal_facts() -> None:
    report = {
        "status": "success",
        "exit_code": 0,
        "termination_reason": None,
        "changed_paths": ["src/a.py"],
        "mutation_index": 1,
        "validation_index": 1,
        "verification": {
            "status": "passed",
            "validation_index": 1,
            "stdout": "must not persist",
        },
        "logical_model_calls": 2,
        "provider_attempts": 3,
        "tool_calls": 4,
        "verification_attempts": 1,
        "sensitive": "must not persist",
    }
    summary = make_safe_run_summary(
        report,
        status="success",
        termination_reason=None,
    )
    assert summary == {
        "status": "success",
        "exit_code": 0,
        "termination_reason": None,
        "changed_paths": ["src/a.py"],
        "verification_status": "passed",
        "mutation_index": 1,
        "validation_index": 1,
        "logical_model_calls": 2,
        "provider_attempts": 3,
        "tool_calls": 4,
        "verification_attempts": 1,
    }
    rendered = str(summary)
    assert "stdout" not in rendered
    assert "sensitive" not in rendered


def _valid_persisted_report_input() -> dict[str, object]:
    return {
        "schema_version": 3,
        "run_id": RUN_ID,
        "run_mode": "modify",
        "budget_profile": "standard",
        "phase": "finish",
        "status": "success",
        "exit_code": 0,
        "completion": {
            "text": "private completion",
            "original_chars": 18,
            "truncated": False,
        },
        "termination_reason": None,
        "failure_reason": "private failure",
        "changed_paths": ["src/a.py"],
        "mutation_index": 1,
        "validation_index": 1,
        "verification": {
            "status": "passed",
            "source": "user",
            "command": "private verify command",
            "exit_code": 0,
            "timed_out": False,
            "truncated": False,
            "duration_ms": 25,
            "validation_index": 1,
            "stdout": {
                "text": "private stdout",
                "original_chars": 14,
                "truncated": False,
            },
            "stderr": {
                "text": "private stderr",
                "original_chars": 14,
                "truncated": False,
            },
            "error_code": None,
        },
        "main_model_calls": 1,
        "summary_model_calls": 1,
        "logical_model_calls": 2,
        "summary_provider_attempts": 1,
        "provider_attempts": 3,
        "tool_calls": 4,
        "verification_attempts": 1,
        "context_compressions": 1,
        "token_usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "responses_with_usage": 2,
            "responses_without_usage": 0,
        },
        "elapsed_ms": 250,
        "log_failure_code": None,
        "log_path": ".coding-agent/logs/" + RUN_ID + ".jsonl",
    }


def test_persisted_run_report_excludes_conversation_and_command_evidence() -> None:
    persisted = make_persisted_run_report(_valid_persisted_report_input())
    assert set(persisted) == {
        "schema_version",
        "run_id",
        "run_mode",
        "budget_profile",
        "phase",
        "status",
        "exit_code",
        "termination_reason",
        "changed_paths",
        "mutation_index",
        "validation_index",
        "verification",
        "main_model_calls",
        "summary_model_calls",
        "logical_model_calls",
        "summary_provider_attempts",
        "provider_attempts",
        "tool_calls",
        "verification_attempts",
        "context_compressions",
        "token_usage",
        "elapsed_ms",
        "log_failure_code",
        "log_path",
    }
    assert set(persisted["verification"]) == {
        "status",
        "source",
        "exit_code",
        "timed_out",
        "truncated",
        "duration_ms",
        "validation_index",
        "error_code",
    }
    raw = json.dumps(persisted, ensure_ascii=False)
    for forbidden in (
        "private completion",
        "private failure",
        "private verify command",
        "private stdout",
        "private stderr",
        "completion",
        "failure_reason",
        "command",
        "stdout",
        "stderr",
    ):
        assert forbidden not in raw


def _make_run_record(
    *,
    run_mode: object = RunMode.MODIFY,
    budget_profile: object = BudgetProfile.STANDARD,
    model_id: object = None,
) -> SessionRunRecord:
    return SessionRunRecord(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        ordinal=1,
        status=SessionRunStatus.QUEUED,
        run_mode=run_mode,  # type: ignore[arg-type]
        budget_profile=budget_profile,  # type: ignore[arg-type]
        user_event_sequence=1,
        started_at_utc=None,
        finished_at_utc=None,
        agent_status=None,
        termination_reason=None,
        audit_run_id=None,
        final_report=None,
        model_id=model_id,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("profile", tuple(BudgetProfile))
def test_session_run_record_requires_and_preserves_budget_profile(
    profile: BudgetProfile,
) -> None:
    record = _make_run_record(budget_profile=profile)
    assert record.budget_profile is profile
    with pytest.raises(TypeError, match="budget_profile"):
        _make_run_record(budget_profile=profile.value)


def test_session_run_record_preserves_valid_model_id_and_allows_legacy_null() -> None:
    assert _make_run_record().model_id is None
    assert _make_run_record(model_id="selected-model").model_id == "selected-model"

    with pytest.raises(ValueError, match="model_id"):
        _make_run_record(model_id=" selected-model")


def _answered_report_input() -> dict[str, object]:
    report = _valid_persisted_report_input()
    report.update(
        run_mode="read_only",
        status="answered",
        changed_paths=[],
        mutation_index=0,
        validation_index=None,
        verification_attempts=0,
    )
    report["verification"] = {
        "status": "not_run",
        "source": None,
        "command": None,
        "exit_code": None,
        "timed_out": False,
        "truncated": False,
        "duration_ms": None,
        "validation_index": None,
        "stdout": None,
        "stderr": None,
        "error_code": None,
    }
    return report


def test_session_run_record_requires_provider_neutral_run_mode() -> None:
    record = _make_run_record(run_mode=RunMode.READ_ONLY)
    assert record.run_mode is RunMode.READ_ONLY
    with pytest.raises(TypeError, match="run_mode"):
        _make_run_record(run_mode="read_only")


def test_persisted_answered_report_projects_run_mode() -> None:
    persisted = make_persisted_run_report(_answered_report_input())
    assert persisted["schema_version"] == 3
    assert persisted["run_mode"] == "read_only"
    assert persisted["status"] == "answered"
    assert persisted["exit_code"] == 0


def test_persisted_modify_capability_answer_projects_selected_mode() -> None:
    report = _answered_report_input()
    report["run_mode"] = "modify"

    persisted = make_persisted_run_report(report)

    assert persisted["run_mode"] == "modify"
    assert persisted["status"] == "answered"
    assert persisted["exit_code"] == 0


def test_persisted_success_accepts_local_integrity_verification_source() -> None:
    report = _valid_persisted_report_input()
    report["verification"]["source"] = "local_integrity"  # type: ignore[index]

    persisted = make_persisted_run_report(report)

    assert persisted["verification"]["source"] == "local_integrity"  # type: ignore[index]


def test_changes_unverified_session_run_result_remains_failed() -> None:
    report = _valid_persisted_report_input()
    report.update(
        status="failed",
        exit_code=1,
        termination_reason="changes_unverified",
        changed_paths=["task_manager.py"],
        mutation_index=1,
        validation_index=None,
    )
    report["verification"] = {
        "status": "stale",
        "source": None,
        "command": None,
        "exit_code": None,
        "timed_out": False,
        "truncated": False,
        "duration_ms": None,
        "validation_index": None,
        "stdout": None,
        "stderr": None,
        "error_code": None,
    }
    persisted = make_persisted_run_report(report)
    result = SessionRunResult(
        run_id=RUN_ID,
        status=SessionRunStatus.FAILED,
        agent_status="failed",
        termination_reason="changes_unverified",
        audit_run_id="3" * 32,
        safe_summary=make_safe_run_summary(
            report,
            status="failed",
            termination_reason="changes_unverified",
        ),
        final_report=persisted,
    )

    assert result.status is SessionRunStatus.FAILED
    assert result.agent_status == "failed"
    assert result.termination_reason == "changes_unverified"
    assert result.final_report is not None
    assert result.final_report["termination_reason"] == "changes_unverified"


@pytest.mark.parametrize(
    ("status", "mode", "exit_code"),
    [
        ("answered", "read_only", 1),
        ("success", "read_only", 0),
    ],
)
def test_persisted_report_rejects_mode_status_mismatch(
    status: str,
    mode: str,
    exit_code: int,
) -> None:
    report = _answered_report_input()
    report.update(status=status, run_mode=mode, exit_code=exit_code)
    with pytest.raises(ValueError):
        make_persisted_run_report(report)  # type: ignore[arg-type]


def test_answered_safe_summary_is_bounded_and_excludes_private_report_data() -> None:
    report = _answered_report_input()
    report["completion"] = {"text": "private answer body"}
    report["continuation"] = {"encrypted": "private continuation"}
    report["instructions"] = "private instructions"

    summary = make_safe_run_summary(
        report,  # type: ignore[arg-type]
        status="answered",
        termination_reason=None,
    )

    assert summary["status"] == "answered"
    assert summary["verification_status"] == "not_run"
    rendered = json.dumps(summary, ensure_ascii=False)
    assert "private answer body" not in rendered
    assert "private continuation" not in rendered
    assert "private instructions" not in rendered


@pytest.mark.parametrize(
    "case",
    [
        "non_object",
        "missing_field",
        "boolean_counter",
        "negative_counter",
        "invalid_status_exit",
        "absolute_changed_path",
        "parent_changed_path",
        "malformed_verification",
        "malformed_token_usage",
        "wrong_log_directory",
        "mismatched_log_run_id",
        "non_json_value",
    ],
)
def test_persisted_run_report_rejects_malformed_input_without_value_leak(
    case: str,
) -> None:
    report: object = _valid_persisted_report_input()
    assert isinstance(report, dict)
    if case == "non_object":
        report = ["private rejected value"]
    elif case == "missing_field":
        report.pop("schema_version")
    elif case == "boolean_counter":
        report["logical_model_calls"] = True
    elif case == "negative_counter":
        report["tool_calls"] = -1
    elif case == "invalid_status_exit":
        report["status"] = "failed"
        report["termination_reason"] = "model_error"
    elif case == "absolute_changed_path":
        report["changed_paths"] = ["C:/private/a.py"]
    elif case == "parent_changed_path":
        report["changed_paths"] = ["src/../private.py"]
    elif case == "malformed_verification":
        report["verification"] = {"status": "passed"}
    elif case == "malformed_token_usage":
        report["token_usage"] = {"input_tokens": 10}
    elif case == "wrong_log_directory":
        report["log_path"] = "logs/" + RUN_ID + ".jsonl"
    elif case == "mismatched_log_run_id":
        report["log_path"] = ".coding-agent/logs/" + "3" * 32 + ".jsonl"
    elif case == "non_json_value":
        report["private rejected value"] = object()

    with pytest.raises((TypeError, ValueError)) as captured:
        make_persisted_run_report(report)  # type: ignore[arg-type]
    assert "private rejected value" not in repr(captured.value)

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from coding_agent.logging import EventType, RunEvent, RunEventLogger, RunLogError
from coding_agent.messages import (
    ModelRequest,
    ModelResponse,
    TokenUsage,
    ToolCall,
    UserMessage,
)
from coding_agent.model import (
    FakeModelClient,
    ModelCallBudget,
    ModelObservation,
    ModelObservationKind,
    ModelCallPurpose,
    invoke_model,
)
from coding_agent.run_mode import RunMode
from coding_agent.tools.base import ExecutionContext
from coding_agent.tools.filesystem import (
    ListDirectoryTool,
    ReadFileTool,
    ReplaceTextTool,
    WriteFileTool,
)
from coding_agent.tools.registry import ToolRegistry


class FakeUtcClock:
    def __init__(self, *values: datetime) -> None:
        self._values = iter(values)

    def __call__(self) -> datetime:
        return next(self._values)


class FakeMonotonicClock:
    def __init__(self, *values: float) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def _run_started_data(
    *,
    task_chars: int = 4,
    run_mode: str = "modify",
) -> dict[str, object]:
    return {
        "task_chars": task_chars,
        "mutation_index": 0,
        "run_mode": run_mode,
        "budget_profile": "standard",
        "max_main_model_calls": 24,
        "max_summary_model_calls": 4,
        "max_provider_attempts": 48,
        "max_summary_provider_attempts": 8,
        "max_tool_calls": 80,
        "max_runtime_seconds": 1200.0,
        "verification_tool_reserve": 1,
    }


def _run_completed_data(
    *,
    status: str = "answered",
    termination_reason: str | None = None,
    phase: str = "finish",
) -> dict[str, object]:
    return {
        "status": status,
        "termination_reason": termination_reason,
        "budget_profile": "standard",
        "phase": phase,
        "main_model_calls": 1,
        "summary_model_calls": 0,
        "logical_model_calls": 1,
        "summary_provider_attempts": 0,
        "provider_attempts": 1,
        "tool_calls": 0,
        "verification_attempts": 0,
        "mutation_index": 0,
        "validation_index": None,
        "elapsed_ms": 1,
    }


def test_phase_progress_checkpoint_and_latch_events_have_exact_safe_keys(
    tmp_path: Path,
) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="c" * 32)
    cases = (
        (
            EventType.PHASE_CHANGED,
            {"from_phase": "discover", "to_phase": "act", "epoch": 1},
        ),
        (
            EventType.PROGRESS_OBSERVED,
            {"strength": "weak", "source": "tool", "epoch": 0},
        ),
        (
            EventType.DECISION_CHECKPOINT,
            {
                "reason": "exploration_limit",
                "phase": "discover",
                "main_calls_remaining": 18,
            },
        ),
        (
            EventType.NO_PROGRESS_DETECTED,
            {"phase": "discover", "post_checkpoint_main_turns": 2},
        ),
        (
            EventType.SUMMARY_FALLBACK_LATCHED,
            {"reason": "invalid_summary", "summary_model_calls": 1},
        ),
    )

    for event_type, data in cases:
        event = logger.emit(event_type, data)
        assert event.schema_version == 3
        assert event.data == data
    logger.close()


@pytest.mark.parametrize(
    "reason",
    [
        "final_read_allowance_exhausted",
        "verification_failure",
        "post_mutation_integrity",
    ],
)
def test_decision_checkpoint_accepts_amendment_reasons(
    tmp_path: Path,
    reason: str,
) -> None:
    logger = RunEventLogger.create(tmp_path)
    event = logger.emit(
        EventType.DECISION_CHECKPOINT,
        {
            "reason": reason,
            "phase": "act",
            "main_calls_remaining": 10,
        },
    )
    logger.close()

    assert event.data["reason"] == reason


def test_duplicate_only_checkpoint_reason_is_auditable(tmp_path: Path) -> None:
    logger = RunEventLogger.create(tmp_path)
    event = logger.emit(
        EventType.DECISION_CHECKPOINT,
        {
            "reason": "duplicate_only_turn",
            "phase": "discover",
            "main_calls_remaining": 30,
        },
    )
    logger.close()
    assert event.data["reason"] == "duplicate_only_turn"


def test_verification_events_accept_local_integrity_source(tmp_path: Path) -> None:
    logger = RunEventLogger.create(tmp_path)
    started = logger.emit(
        EventType.VERIFICATION_STARTED,
        {
            "source": "local_integrity",
            "command_hash": "a" * 64,
            "mutation_index": 1,
            "attempt_index": 1,
        },
    )
    completed = logger.emit(
        EventType.VERIFICATION_COMPLETED,
        {
            "source": "local_integrity",
            "status": "passed",
            "exit_code": 0,
            "timed_out": False,
            "truncated": False,
            "duration_ms": 0,
            "validation_index": 1,
            "mutation_index": 1,
            "stdout_chars": 48,
            "stderr_chars": 0,
            "error_code": None,
        },
    )
    logger.close()

    assert started.data["source"] == "local_integrity"
    assert completed.data["source"] == "local_integrity"


@pytest.mark.parametrize(
    "safe_error_code",
    [
        "agent_rejected:decision_required",
        "agent_rejected:verification_required",
    ],
)
def test_tool_completed_accepts_exact_agent_rejection_codes(
    tmp_path: Path,
    safe_error_code: str,
) -> None:
    logger = RunEventLogger.create(tmp_path)
    event = logger.emit(
        EventType.TOOL_CALL_COMPLETED,
        {
            "ordinal": 1,
            "tool_name": "read_file",
            "call_id_hash": "b" * 64,
            "status": "rejected",
            "safe_error_code": safe_error_code,
            "output_chars": 0,
            "exit_code": None,
            "timed_out": False,
            "truncated": False,
            "duration_ms": 0,
            "changed_paths": [],
            "mutation_index_before": 0,
            "mutation_index_after": 0,
            "executed": False,
        },
    )
    logger.close()

    assert event.data["safe_error_code"] == safe_error_code


def test_new_events_reject_content_paths_continuation_and_extra_fields(
    tmp_path: Path,
) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="d" * 32)
    for extra in (
        {"summary": "secret"},
        {"path": str(tmp_path)},
        {"continuation": "opaque"},
        {"instructions": "hidden"},
    ):
        with pytest.raises(RunLogError):
            logger.emit(
                EventType.DECISION_CHECKPOINT,
                {
                    "reason": "exploration_limit",
                    "phase": "discover",
                    "main_calls_remaining": 4,
                    **extra,
                },
            )
    logger.close()


def test_run_started_schema_v3_requires_profile_and_limits(tmp_path: Path) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="a" * 32)
    event = logger.emit(
        EventType.RUN_STARTED,
        _run_started_data(task_chars=7, run_mode=RunMode.READ_ONLY.value),
    )
    logger.close()

    assert event.schema_version == 3
    assert event.data["run_mode"] == "read_only"


def test_run_completed_schema_v3_accepts_answered(tmp_path: Path) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="b" * 32)
    event = logger.emit(
        EventType.RUN_COMPLETED,
        _run_completed_data(),
    )
    logger.close()

    assert event.schema_version == 3
    assert event.data["status"] == "answered"


def test_run_completed_schema_accepts_changes_unverified(tmp_path: Path) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="c" * 32)

    event = logger.emit(
        EventType.RUN_COMPLETED,
        _run_completed_data(
            status="failed",
            termination_reason="changes_unverified",
            phase="finish",
        ),
    )
    logger.close()

    assert event.data["status"] == "failed"
    assert event.data["termination_reason"] == "changes_unverified"


def test_event_observer_runs_only_after_line_is_flushed(tmp_path: Path) -> None:
    observed: list[tuple[RunEvent, str]] = []
    logger = RunEventLogger.create(tmp_path, run_id="1" * 32)

    def observer(event: RunEvent) -> None:
        log_path = tmp_path / logger.metadata.log_path
        observed.append((event, log_path.read_text(encoding="utf-8")))

    logger.set_event_observer(observer)
    event = logger.emit(
        EventType.RUN_STARTED,
        _run_started_data(),
    )
    assert observed[0][0] == event
    assert json.loads(observed[0][1].splitlines()[-1])["sequence"] == event.sequence
    logger.close()


def test_ordinary_event_observer_failure_does_not_poison_audit_log(
    tmp_path: Path,
) -> None:
    calls = 0

    def observer(_: RunEvent) -> None:
        nonlocal calls
        calls += 1
        raise OSError("private bridge detail")

    logger = RunEventLogger.create(tmp_path, run_id="2" * 32)
    logger.set_event_observer(observer)
    first = logger.emit(
        EventType.RUN_STARTED,
        _run_started_data(),
    )
    second = logger.emit(
        EventType.RUN_COMPLETED,
        _run_completed_data(
            status="failed",
            termination_reason="empty_model_response",
            phase="discover",
        ),
    )
    logger.close()
    assert (first.sequence, second.sequence, calls) == (1, 2, 2)
    text = (tmp_path / logger.metadata.log_path).read_text(encoding="utf-8")
    assert "private bridge detail" not in text
    assert len(text.splitlines()) == 2


def test_event_observer_system_exit_is_not_swallowed(tmp_path: Path) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="3" * 32)
    logger.set_event_observer(
        lambda _: (_ for _ in ()).throw(SystemExit(7))
    )
    with pytest.raises(SystemExit) as captured:
        logger.emit(
            EventType.RUN_STARTED,
            _run_started_data(),
        )
    assert captured.value.code == 7
    logger.close()


def test_jsonl_has_deterministic_envelope_sequence_utf8_and_newline(
    tmp_path: Path,
) -> None:
    logger = RunEventLogger.create(
        tmp_path,
        run_id="0" * 32,
        utc_clock=FakeUtcClock(
            datetime(2026, 8, 28, 1, 2, 3, 456789, tzinfo=timezone.utc),
            datetime(2026, 8, 28, 1, 2, 4, 456789, tzinfo=timezone.utc),
            datetime(2026, 8, 28, 1, 2, 5, 456789, tzinfo=timezone.utc),
        ),
        monotonic_clock=FakeMonotonicClock(10.0, 10.125, 10.250),
    )

    first = logger.emit(
        EventType.RUN_STARTED,
        _run_started_data(task_chars=2),
    )
    second = logger.emit(
        EventType.TOOL_CALL_STARTED,
        {
            "ordinal": 1,
            "tool_name": "读取",
            "call_id_hash": "a" * 64,
            "mutation_index": 0,
        },
    )
    logger.close()

    assert first.sequence == 1
    assert second.sequence == 2
    assert first.timestamp_utc == "2026-08-28T01:02:04.456789Z"
    assert first.elapsed_ms == 125
    assert second.elapsed_ms == 250
    log_path = tmp_path / ".coding-agent" / "logs" / ("0" * 32 + ".jsonl")
    raw = log_path.read_bytes()
    assert raw.endswith(b"\n")
    lines = raw.decode("utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["sequence"] for line in lines] == [1, 2]
    assert "读取" in raw.decode("utf-8")
    assert logger.metadata.log_path == ".coding-agent/logs/" + "0" * 32 + ".jsonl"


def test_auto_run_id_collision_retries_sixteen_times_then_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "1" * 32
    logs = tmp_path / ".coding-agent" / "logs"
    logs.mkdir(parents=True)
    (logs / f"{run_id}.jsonl").write_text("occupied\n", encoding="utf-8")
    calls = 0

    def repeated_uuid() -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(hex=run_id)

    monkeypatch.setattr("coding_agent.logging.uuid.uuid4", repeated_uuid)

    with pytest.raises(RunLogError) as caught:
        RunEventLogger.create(tmp_path)

    assert caught.value.code == "run_id_collision"
    assert calls == 16


def test_tool_completed_schema_is_exact_and_serializable(tmp_path: Path) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="2" * 32)
    event = logger.emit(
        EventType.TOOL_CALL_COMPLETED,
        {
            "ordinal": 1,
            "tool_name": "read_file",
            "call_id_hash": "b" * 64,
            "status": "ok",
            "safe_error_code": None,
            "output_chars": 15,
            "exit_code": None,
            "timed_out": False,
            "truncated": False,
            "duration_ms": 2,
            "changed_paths": [],
            "mutation_index_before": 0,
            "mutation_index_after": 0,
            "executed": True,
        },
    )
    with pytest.raises(RunLogError) as caught:
        logger.emit(EventType.TOOL_CALL_COMPLETED, {**event.data, "extra": 1})
    logger.close()

    assert caught.value.code == "invalid_event_data"
    assert event.data["status"] == "ok"


def test_allowed_text_is_scrubbed_before_jsonl_write(tmp_path: Path) -> None:
    secret = "secret-sentinel-value"
    logger = RunEventLogger.create(
        tmp_path,
        run_id="3" * 32,
        sensitive_values=(secret,),
    )
    logger.emit(
        EventType.TOOL_CALL_STARTED,
        {
            "ordinal": 1,
            "tool_name": f"reader-{secret}",
            "call_id_hash": "c" * 64,
            "mutation_index": 0,
        },
    )
    logger.close()

    raw = (
        tmp_path / ".coding-agent" / "logs" / ("3" * 32 + ".jsonl")
    ).read_text(encoding="utf-8")
    assert secret not in raw
    assert "reader-[REDACTED]" in raw


def test_model_observations_map_to_jsonl_and_aggregate_usage(tmp_path: Path) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="4" * 32)
    budget = ModelCallBudget(
        max_logical_calls=2,
        max_provider_attempts=2,
        observer=logger,
    )
    request = ModelRequest(messages=(UserMessage("local history stays private"),))

    invoke_model(
        FakeModelClient(
            (
                ModelResponse(
                    text="main output stays private",
                    usage=TokenUsage(5, 3, 8),
                    provider_response_id="raw-provider-id-main",
                ),
            )
        ),
        request,
        budget,
        purpose=ModelCallPurpose.MAIN,
    )
    invoke_model(
        FakeModelClient((ModelResponse(text="summary output stays private"),)),
        request,
        budget,
        purpose=ModelCallPurpose.SUMMARY,
    )
    logger.close()

    raw = (
        tmp_path / ".coding-agent" / "logs" / ("4" * 32 + ".jsonl")
    ).read_text(encoding="utf-8")
    events = [json.loads(line) for line in raw.splitlines()]
    assert [event["event_type"] for event in events] == [
        "model_call_started",
        "provider_attempt_started",
        "provider_attempt_completed",
        "model_call_completed",
    ] * 2
    assert events[0]["data"] == {
        "purpose": "main",
        "logical_call_index": 1,
        "provider_attempts_before": 0,
        "message_count": 1,
        "tool_schema_count": 0,
        "continuation_count": 0,
    }
    completed = events[3]["data"]
    assert completed["usage"] == {
        "input_tokens": 5,
        "output_tokens": 3,
        "total_tokens": 8,
    }
    assert completed["provider_response_id_hash"] != "raw-provider-id-main"
    assert len(completed["provider_response_id_hash"]) == 64
    assert logger.metadata.token_usage.input_tokens == 5
    assert logger.metadata.token_usage.output_tokens == 3
    assert logger.metadata.token_usage.total_tokens == 8
    assert logger.metadata.token_usage.responses_with_usage == 1
    assert logger.metadata.token_usage.responses_without_usage == 1
    assert "local history stays private" not in raw
    assert "main output stays private" not in raw
    assert "summary output stays private" not in raw
    assert "raw-provider-id-main" not in raw


@pytest.mark.parametrize(
    "error_code",
    [
        "invalid_model_response",
        "streaming_unsupported",
        "stream_interrupted",
        "model_client_error",
        "transient_model_error",
        "fatal_model_error",
    ],
)
def test_adapter_provider_error_codes_are_logged_without_audit_failure(
    tmp_path: Path,
    error_code: str,
) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="5" * 32)

    logger.observe_model(
        ModelObservation(
            kind=ModelObservationKind.PROVIDER_FAILED,
            purpose=ModelCallPurpose.MAIN,
            logical_call_index=1,
            provider_attempt_index=1,
            error_code=error_code,
            retry_scheduled=False,
            retry_delay_ms=None,
        )
    )
    logger.close()

    raw = (
        tmp_path / ".coding-agent" / "logs" / ("5" * 32 + ".jsonl")
    ).read_text(encoding="utf-8")
    event = json.loads(raw)
    assert event["event_type"] == "provider_attempt_failed"
    assert event["data"]["error_code"] == error_code
    assert "audit_log_failure" not in raw


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        (
            ListDirectoryTool(),
            {
                "path": ".coding-agent",
                "recursive": False,
                "max_depth": 1,
                "max_entries": 10,
            },
        ),
        (
            ReadFileTool(),
            {
                "path": ".coding-agent/logs/private.jsonl",
                "start_line": 1,
                "end_line": None,
            },
        ),
        (
            ReplaceTextTool(),
            {
                "path": ".coding-agent/logs/private.jsonl",
                "old_text": "a",
                "new_text": "b",
                "expected_count": 1,
            },
        ),
        (
            WriteFileTool(),
            {
                "path": ".coding-agent/private.txt",
                "content": "denied",
            },
        ),
    ],
)
def test_internal_log_directory_remains_denied_to_model_file_tools(
    tmp_path: Path,
    tool: object,
    arguments: dict[str, object],
) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="d" * 32)
    registry = ToolRegistry((tool,))  # type: ignore[arg-type]

    result = registry.execute(
        ToolCall("protected-call", tool.name, arguments),  # type: ignore[attr-defined,arg-type]
        ExecutionContext(tmp_path),
    )
    logger.close()

    assert result.status == "rejected"
    assert result.error == (
        "security_rejected:protected_path: protected path is unavailable"
    )


def test_serialization_failure_poisons_logger_without_consuming_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="e" * 32)

    def fail_serialization(self: RunEvent) -> str:
        raise ValueError("private serialization body")

    monkeypatch.setattr(RunEvent, "to_json", fail_serialization)
    with pytest.raises(RunLogError) as first:
        logger.emit(
            EventType.RUN_STARTED,
            _run_started_data(task_chars=1),
        )
    with pytest.raises(RunLogError) as second:
        logger.emit(
            EventType.RUN_STARTED,
            _run_started_data(task_chars=1),
        )

    assert first.value.code == "event_serialization_failed"
    assert second.value.code == "log_unavailable"
    assert logger.metadata.log_failure_code == "event_serialization_failed"
    assert "private serialization body" not in repr(logger.metadata)


def test_event_allowlist_rejects_unknown_error_code(tmp_path: Path) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="f" * 32)
    with pytest.raises(RunLogError) as caught:
        logger.emit(
            EventType.MODEL_CALL_FAILED,
            {
                "purpose": "main",
                "logical_call_index": 1,
                "provider_attempts_after": 1,
                "error_code": "provider exception included private payload",
            },
        )
    logger.close()

    assert caught.value.code == "invalid_event_data"


def test_real_windows_junction_log_directory_is_rejected(tmp_path: Path) -> None:
    assert os.name == "nt", "Task 12 log-path acceptance requires Windows"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = workspace / ".coding-agent"
    completed = subprocess.run(
        [
            os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
            "/d",
            "/c",
            "mklink",
            "/J",
            str(junction),
            str(outside),
        ],
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    with pytest.raises(RunLogError) as caught:
        RunEventLogger.create(workspace, run_id="1" * 32)

    assert caught.value.code == "log_path_reparse"

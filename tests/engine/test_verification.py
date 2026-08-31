from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import sys

import pytest

from coding_agent.engine.messages import (
    AssistantMessage,
    ToolCall,
    ToolResult,
    ToolResultMetadata,
)
from coding_agent.operations.safety import AuthorizedCommand, CommandSource
from coding_agent.engine.state import AgentState, AgentStatus, VerificationStatus
from coding_agent.operations.tools.base import ExecutionContext, ToolExecution
from coding_agent.operations.tools.shell import CommandStartError
from coding_agent.engine.verification import (
    VerificationDecision,
    VerificationError,
    VerificationGate,
    VerificationOutcome,
    VerificationResult,
    is_credible_verification_command,
    verification_advances_progress,
)


def _result(**overrides: object) -> VerificationResult:
    values: dict[str, object] = {
        "status": VerificationStatus.PASSED,
        "validation_index": 2,
        "command": "python -m pytest -q",
        "source": CommandSource.USER_VERIFY,
        "exit_code": 0,
        "stdout": "2 passed",
        "stderr": "",
        "timed_out": False,
        "truncated": False,
        "duration_ms": 12,
        "error": None,
    }
    values.update(overrides)
    return VerificationResult(**values)  # type: ignore[arg-type]


def _progress_evidence(
    *,
    status: VerificationStatus = VerificationStatus.PASSED,
    validation_index: int = 1,
    source: CommandSource = CommandSource.MODEL,
    command: str = "python -m pytest -q",
) -> VerificationResult:
    return VerificationResult(
        status=status,
        validation_index=validation_index,
        command=command,
        source=source,
        exit_code=0 if status is VerificationStatus.PASSED else 1,
        stdout="",
        stderr="",
        timed_out=False,
        truncated=False,
        duration_ms=1,
        error=None,
    )


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (None, _progress_evidence(), True),
        (
            _progress_evidence(validation_index=1),
            _progress_evidence(validation_index=2),
            True,
        ),
        (
            _progress_evidence(status=VerificationStatus.FAILED),
            _progress_evidence(status=VerificationStatus.PASSED),
            True,
        ),
        (
            _progress_evidence(source=CommandSource.LOCAL_INTEGRITY),
            _progress_evidence(source=CommandSource.MODEL),
            True,
        ),
        (_progress_evidence(), _progress_evidence(), False),
        (
            _progress_evidence(command="python -m pytest -q"),
            _progress_evidence(command="python -m unittest"),
            False,
        ),
        (
            _progress_evidence(source=CommandSource.MODEL),
            _progress_evidence(source=CommandSource.LOCAL_INTEGRITY),
            False,
        ),
        (
            _progress_evidence(validation_index=2),
            _progress_evidence(validation_index=1),
            False,
        ),
    ],
)
def test_verification_progress_is_monotonic(
    previous: VerificationResult | None,
    current: VerificationResult,
    expected: bool,
) -> None:
    assert verification_advances_progress(previous, current) is expected


def test_verification_and_agent_status_values_are_exact() -> None:
    assert tuple(VerificationStatus) == (
        VerificationStatus.NOT_RUN,
        VerificationStatus.STALE,
        VerificationStatus.RUNNING,
        VerificationStatus.PASSED,
        VerificationStatus.FAILED,
        VerificationStatus.TIMED_OUT,
        VerificationStatus.ERROR,
    )
    assert AgentStatus.SUCCESS.value == "success"


def test_passed_result_is_json_stable_and_repr_hides_evidence() -> None:
    result = _result()

    assert result.to_dict() == {
        "status": "passed",
        "validation_index": 2,
        "command": "python -m pytest -q",
        "source": "user_verify",
        "exit_code": 0,
        "stdout": "2 passed",
        "stderr": "",
        "timed_out": False,
        "truncated": False,
        "duration_ms": 12,
        "error": None,
    }
    assert "python -m pytest" not in repr(result)
    assert "2 passed" not in repr(result)


@pytest.mark.parametrize(
    ("overrides", "expected_status"),
    [
        ({"status": VerificationStatus.FAILED, "exit_code": 1}, "failed"),
        (
            {
                "status": VerificationStatus.TIMED_OUT,
                "exit_code": None,
                "timed_out": True,
                "error": "cleanup_failed",
            },
            "timed_out",
        ),
        (
            {
                "status": VerificationStatus.ERROR,
                "exit_code": None,
                "error": "verification_command_start_failed",
            },
            "error",
        ),
    ],
)
def test_result_accepts_each_terminal_status(
    overrides: dict[str, object], expected_status: str
) -> None:
    result = _result(**overrides)

    assert result.to_dict()["status"] == expected_status


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": VerificationStatus.NOT_RUN},
        {"status": VerificationStatus.STALE},
        {"status": VerificationStatus.RUNNING},
        {"validation_index": -1},
        {"validation_index": True},
        {"command": ""},
        {"source": "user_verify"},
        {"duration_ms": -1},
        {"duration_ms": True},
        {"timed_out": 0},
        {"truncated": 0},
        {"status": VerificationStatus.PASSED, "exit_code": 1},
        {"status": VerificationStatus.PASSED, "timed_out": True},
        {"status": VerificationStatus.PASSED, "error": "unexpected"},
        {"status": VerificationStatus.FAILED, "exit_code": 0},
        {"status": VerificationStatus.FAILED, "exit_code": None},
        {"status": VerificationStatus.FAILED, "timed_out": True},
        {"status": VerificationStatus.FAILED, "error": "unexpected"},
        {
            "status": VerificationStatus.TIMED_OUT,
            "exit_code": 1,
            "timed_out": True,
        },
        {
            "status": VerificationStatus.TIMED_OUT,
            "exit_code": None,
            "timed_out": False,
        },
        {
            "status": VerificationStatus.ERROR,
            "exit_code": 1,
            "error": "verification_internal_error",
        },
        {
            "status": VerificationStatus.ERROR,
            "exit_code": None,
            "timed_out": True,
            "error": "verification_internal_error",
        },
        {"status": VerificationStatus.ERROR, "exit_code": None, "error": None},
        {
            "status": VerificationStatus.ERROR,
            "exit_code": None,
            "error": "provider-secret-body",
        },
    ],
)
def test_result_rejects_invalid_status_or_field_combination(
    overrides: dict[str, object]
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _result(**overrides)


def test_result_serialization_preserves_explicit_nulls() -> None:
    result = _result(
        status=VerificationStatus.ERROR,
        exit_code=None,
        stdout="",
        stderr="",
        error="verification_internal_error",
    )

    serialized = result.to_dict()

    assert "exit_code" in serialized
    assert serialized["exit_code"] is None


def test_agent_state_exposes_validation_index_without_runtime_cycle(
    tmp_path: Path,
) -> None:
    state = AgentState.start("inspect", tmp_path, 0.0)
    assert state.verification_attempt_count == 0
    assert state.last_verification is None
    assert state.validation_index is None

    state.last_verification = _result(validation_index=0)

    assert state.validation_index == 0
    assert "python -m pytest" not in repr(state)


@pytest.mark.parametrize(
    "argv",
    [
        (sys.executable, "-m", "pytest", "-q"),
        (r"C:\trusted\pytest.exe", "-q"),
        (sys.executable, "-m", "unittest", "discover"),
        (r"C:\trusted\ruff.exe", "check", "."),
        (r"C:\trusted\mypy.exe", "src"),
        (sys.executable, r"D:\workspace\verify.py"),
    ],
)
def test_credible_verification_command_accepts_canonical_test_forms(
    argv: tuple[str, ...],
) -> None:
    command = AuthorizedCommand(
        argv=argv,
        normalized_command="normalized",
        purpose="verification",
        source=CommandSource.MODEL,
    )

    assert is_credible_verification_command(command) is True


@pytest.mark.parametrize(
    "command",
    [
        AuthorizedCommand(
            argv=(r"C:\trusted\git.exe", "status", "--short"),
            normalized_command="normalized",
            purpose="verification",
            source=CommandSource.USER_VERIFY,
        ),
        AuthorizedCommand(
            argv=(sys.executable, "-m", "pytest", "--help"),
            normalized_command="normalized",
            purpose="verification",
            source=CommandSource.USER_VERIFY,
        ),
        AuthorizedCommand(
            argv=(r"C:\trusted\ruff.exe", "--version"),
            normalized_command="normalized",
            purpose="verification",
            source=CommandSource.USER_VERIFY,
        ),
        AuthorizedCommand(
            argv=(sys.executable, "-m", "pytest", "-q"),
            normalized_command="normalized",
            purpose="inspect",
            source=CommandSource.MODEL,
        ),
        AuthorizedCommand(
            argv=(),
            normalized_command="normalized",
            purpose="verification",
            source=CommandSource.MODEL,
        ),
    ],
)
def test_credible_verification_command_rejects_non_evidence(
    command: AuthorizedCommand,
) -> None:
    assert is_credible_verification_command(command) is False


@pytest.mark.parametrize("command", [None, "pytest -q", object()])
def test_credible_verification_command_rejects_wrong_type(command: object) -> None:
    assert is_credible_verification_command(command) is False  # type: ignore[arg-type]


class FakeVerificationExecutor:
    def __init__(self, *queued: ToolExecution | BaseException) -> None:
        self.queued = list(queued)
        self.calls: list[tuple[AuthorizedCommand, ExecutionContext]] = []

    def execute(
        self, command: AuthorizedCommand, context: ExecutionContext
    ) -> ToolExecution:
        self.calls.append((command, context))
        next_value = self.queued.pop(0)
        if isinstance(next_value, BaseException):
            raise next_value
        return next_value


def _authorized(
    *, source: CommandSource = CommandSource.USER_VERIFY
) -> AuthorizedCommand:
    argv = (sys.executable, "-m", "pytest", "-q")
    return AuthorizedCommand(
        argv=argv,
        normalized_command=subprocess.list2cmdline(argv),
        purpose="verification",
        source=source,
    )


def _execution(
    *,
    exit_code: int | None = 0,
    timed_out: bool = False,
    stdout: str = "2 passed",
    stderr: str = "",
    truncated: bool = False,
    duration_ms: int = 12,
    cleanup_error: str | None = None,
) -> ToolExecution:
    return ToolExecution(
        output=json.dumps(
            {
                "argv": list(_authorized().argv),
                "cleanup_error": cleanup_error,
                "purpose": "verification",
                "stderr": stderr,
                "stdout": stdout,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        metadata=ToolResultMetadata(
            exit_code=exit_code,
            timed_out=timed_out,
            truncated=truncated,
            duration_ms=duration_ms,
        ),
    )


def _candidate_state(tmp_path: Path) -> AgentState:
    state = AgentState.start("fix", tmp_path, 0.0)
    state.status = AgentStatus.COMPLETION_CANDIDATE
    state.mutation_index = 2
    return state


def test_required_command_passes_with_fresh_evidence(tmp_path: Path) -> None:
    required = _authorized()
    executor = FakeVerificationExecutor(_execution())
    context = ExecutionContext(tmp_path)
    gate = VerificationGate(
        required_command=required,
        execution_context=context,
        executor=executor,
    )
    state = _candidate_state(tmp_path)

    decision = gate.evaluate(state)

    assert decision == VerificationDecision(
        outcome=VerificationOutcome.SUCCESS,
        result=state.last_verification,
        feedback=None,
        command_executed=True,
    )
    assert executor.calls == [(required, context)]
    assert executor.calls[0][0] is required
    assert state.verification_attempt_count == 1
    assert state.verification_status is VerificationStatus.PASSED
    assert state.validation_index == state.mutation_index == 2


def test_required_nonzero_continues_with_structured_feedback(
    tmp_path: Path,
) -> None:
    executor = FakeVerificationExecutor(
        _execution(exit_code=1, stdout="one failed", stderr="assertion")
    )
    gate = VerificationGate(
        required_command=_authorized(),
        execution_context=ExecutionContext(tmp_path),
        executor=executor,
    )
    state = _candidate_state(tmp_path)

    decision = gate.evaluate(state)

    assert decision.outcome is VerificationOutcome.CONTINUE
    assert decision.command_executed is True
    assert decision.result is state.last_verification
    assert decision.result is not None
    assert decision.result.status is VerificationStatus.FAILED
    assert decision.feedback is not None
    assert isinstance(decision.feedback, AssistantMessage)
    assert decision.feedback.tool_calls == ()
    assert decision.feedback.content is not None
    prefix, payload = decision.feedback.content.split("\n", 1)
    assert prefix == "coding-agent verification feedback"
    assert json.loads(payload) == {
        "command": _authorized().normalized_command,
        "error": None,
        "exit_code": 1,
        "mutation_index": 2,
        "source": "user_verify",
        "status": "failed",
        "stderr": "assertion",
        "stdout": "one failed",
        "timed_out": False,
        "truncated": False,
        "validation_index": 2,
    }
    assert state.verification_attempt_count == 1


def test_required_timeout_preserves_partial_output_and_cleanup_error(
    tmp_path: Path,
) -> None:
    executor = FakeVerificationExecutor(
        _execution(
            exit_code=None,
            timed_out=True,
            stdout="partial",
            stderr="still running",
            truncated=True,
            cleanup_error="process-tree cleanup unavailable",
        )
    )
    gate = VerificationGate(
        required_command=_authorized(),
        execution_context=ExecutionContext(tmp_path),
        executor=executor,
    )
    state = _candidate_state(tmp_path)

    decision = gate.evaluate(state)

    assert decision.result is not None
    assert decision.result.status is VerificationStatus.TIMED_OUT
    assert decision.result.exit_code is None
    assert decision.result.timed_out is True
    assert decision.result.truncated is True
    assert decision.result.stdout == "partial"
    assert decision.result.stderr == "still running"
    assert decision.result.error == "process-tree cleanup unavailable"
    assert state.verification_attempt_count == 1


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        (
            CommandStartError("command could not be started: secret-sentinel"),
            "verification_command_start_failed",
        ),
        (RuntimeError("provider-secret-body"), "verification_internal_error"),
    ],
)
def test_required_executor_error_is_stable_and_redacted(
    tmp_path: Path, failure: Exception, expected_error: str
) -> None:
    gate = VerificationGate(
        required_command=_authorized(),
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(failure),
    )
    state = _candidate_state(tmp_path)

    decision = gate.evaluate(state)

    assert decision.result is not None
    assert decision.result.status is VerificationStatus.ERROR
    assert decision.result.error == expected_error
    assert "secret" not in repr(decision)
    assert "provider" not in repr(decision)
    assert state.verification_attempt_count == 1


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), SystemExit(7)])
def test_required_interrupts_propagate(
    tmp_path: Path, failure: BaseException
) -> None:
    gate = VerificationGate(
        required_command=_authorized(),
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(failure),
    )
    state = _candidate_state(tmp_path)

    with pytest.raises(type(failure)):
        gate.evaluate(state)

    assert state.verification_attempt_count == 1


def test_required_corrupt_shell_output_raises_internal_error(tmp_path: Path) -> None:
    corrupt = ToolExecution(
        output='{"argv":[],"purpose":"verification"}',
        metadata=ToolResultMetadata(exit_code=0),
    )
    gate = VerificationGate(
        required_command=_authorized(),
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(corrupt),
    )
    state = _candidate_state(tmp_path)

    with pytest.raises(VerificationError, match="invalid verification execution"):
        gate.evaluate(state)

    assert state.verification_attempt_count == 1


@pytest.mark.parametrize(
    "required",
    [
        _authorized(source=CommandSource.MODEL),
        AuthorizedCommand(
            argv=(r"C:\trusted\git.exe", "status", "--short"),
            normalized_command=r"C:\trusted\git.exe status --short",
            purpose="verification",
            source=CommandSource.USER_VERIFY,
        ),
        AuthorizedCommand(
            argv=(sys.executable, "-m", "pytest", "-q"),
            normalized_command="python -m pytest -q",
            purpose="inspect",
            source=CommandSource.USER_VERIFY,
        ),
    ],
)
def test_required_command_must_be_credible_user_verification(
    tmp_path: Path, required: AuthorizedCommand
) -> None:
    with pytest.raises(ValueError, match="credible user verification"):
        VerificationGate(
            required_command=required,
            execution_context=ExecutionContext(tmp_path),
            executor=FakeVerificationExecutor(),
        )


def test_required_executor_argv_mismatch_is_corrupt_evidence(
    tmp_path: Path,
) -> None:
    mismatched = _execution()
    assert mismatched.output is not None
    payload = json.loads(mismatched.output)
    payload["argv"] = [sys.executable, "-m", "unittest"]
    executor = FakeVerificationExecutor(
        ToolExecution(
            output=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            metadata=mismatched.metadata,
        )
    )
    gate = VerificationGate(
        required_command=_authorized(),
        execution_context=ExecutionContext(tmp_path),
        executor=executor,
    )
    state = _candidate_state(tmp_path)

    with pytest.raises(VerificationError, match="invalid verification execution"):
        gate.evaluate(state)

    assert state.verification_attempt_count == 1


def _model_pair(
    *,
    purpose: str = "verification",
    argv: tuple[str, ...] | None = None,
    status: str = "ok",
    exit_code: int | None = 0,
    timed_out: bool = False,
    stdout: str = "2 passed",
    stderr: str = "",
) -> tuple[ToolCall, ToolResult]:
    executed_argv = _authorized(source=CommandSource.MODEL).argv if argv is None else argv
    call = ToolCall(
        "model-verify",
        "run_command",
        {"command": "python -m pytest -q", "purpose": purpose},
    )
    output = json.dumps(
        {
            "argv": list(executed_argv),
            "cleanup_error": None,
            "purpose": purpose,
            "stderr": stderr,
            "stdout": stdout,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return call, ToolResult(
        call_id=call.call_id,
        tool_name=call.name,
        status=status,  # type: ignore[arg-type]
        output=output if status == "ok" else None,
        error=None if status == "ok" else "command rejected",
        metadata=ToolResultMetadata(
            exit_code=exit_code,
            timed_out=timed_out,
            truncated=False,
            duration_ms=15,
        ),
    )


def _java_pair(
    *,
    purpose: str = "verification",
    phase: str = "complete",
    exit_code: int | None = 0,
    timed_out: bool = False,
    truncated: bool = False,
    safe_error_code: str | None = None,
    case_count: int = 2,
    passed_count: int = 2,
    failed_case: str | None = None,
    status: str = "ok",
) -> tuple[ToolCall, ToolResult]:
    arguments = {
        "source_root": "src",
        "main_class": "Main",
        "tests_directory": "tests",
        "purpose": purpose,
    }
    call = ToolCall("java-verify", "run_java_tests", arguments)
    output = json.dumps(
        {
            "case_count": case_count,
            "failed_case": failed_case,
            "passed_count": passed_count,
            "phase": phase,
            "purpose": purpose,
            "safe_error_code": safe_error_code,
            "source_count": 3,
            "stderr": "",
            "stdout": "",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return call, ToolResult(
        call_id=call.call_id,
        tool_name=call.name,
        status=status,  # type: ignore[arg-type]
        output=output if status == "ok" else None,
        error=None if status == "ok" else "tool failed",
        metadata=ToolResultMetadata(
            exit_code=exit_code,
            timed_out=timed_out,
            truncated=truncated,
            duration_ms=25,
        ),
    )


def test_java_verification_records_fresh_passed_evidence(
    tmp_path: Path,
) -> None:
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
    )
    state = _candidate_state(tmp_path)
    call, result = _java_pair()
    assert gate.observe_tool_result(state, call, result) is True
    assert state.verification_attempt_count == 1
    assert state.verification_status is VerificationStatus.PASSED
    assert state.validation_index == state.mutation_index == 2
    assert state.last_verification is not None
    assert state.last_verification.command == (
        "run_java_tests source_root=src main_class=Main tests_directory=tests"
    )
    assert state.last_verification.source is CommandSource.MODEL
    assert gate.evaluate(state).outcome is VerificationOutcome.SUCCESS


def test_java_test_purpose_does_not_create_final_evidence(
    tmp_path: Path,
) -> None:
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
    )
    state = _candidate_state(tmp_path)
    call, result = _java_pair(purpose="test")
    assert gate.observe_tool_result(state, call, result) is False
    assert state.last_verification is None
    assert state.verification_attempt_count == 0


@pytest.mark.parametrize(
    ("changes", "expected_status"),
    (
        (
            {
                "phase": "compile",
                "exit_code": 2,
                "safe_error_code": "compile_failed",
                "passed_count": 0,
                "failed_case": None,
            },
            VerificationStatus.FAILED,
        ),
        (
            {
                "phase": "case",
                "exit_code": 3,
                "safe_error_code": "program_failed",
                "passed_count": 0,
                "failed_case": "tests/case",
            },
            VerificationStatus.FAILED,
        ),
        (
            {
                "phase": "case",
                "exit_code": 1,
                "safe_error_code": "output_mismatch",
                "passed_count": 0,
                "failed_case": "tests/case",
            },
            VerificationStatus.FAILED,
        ),
        (
            {
                "phase": "case",
                "exit_code": 1,
                "safe_error_code": "output_truncated",
                "passed_count": 0,
                "failed_case": "tests/case",
                "truncated": True,
            },
            VerificationStatus.FAILED,
        ),
        (
            {
                "phase": "cleanup",
                "exit_code": 1,
                "safe_error_code": "cleanup_failed",
                "passed_count": 2,
                "failed_case": None,
            },
            VerificationStatus.FAILED,
        ),
        (
            {
                "phase": "case",
                "exit_code": None,
                "safe_error_code": "suite_timed_out",
                "passed_count": 0,
                "failed_case": "tests/case",
                "timed_out": True,
            },
            VerificationStatus.TIMED_OUT,
        ),
    ),
)
def test_java_failure_evidence_never_becomes_passed(
    tmp_path: Path,
    changes: dict[str, object],
    expected_status: VerificationStatus,
) -> None:
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
    )
    state = _candidate_state(tmp_path)
    call, result = _java_pair(**changes)  # type: ignore[arg-type]
    assert gate.observe_tool_result(state, call, result) is True
    assert state.verification_status is expected_status
    assert state.verification_status is not VerificationStatus.PASSED
    assert state.validation_index == state.mutation_index


@pytest.mark.parametrize(
    "case",
    (
        "extra_key",
        "missing_key",
        "purpose_mismatch",
        "zero_sources",
        "zero_cases",
        "passed_over_case_count",
        "complete_with_failed_case",
        "complete_with_safe_error",
        "exit_zero_failed_phase",
        "nonzero_complete_phase",
        "timeout_with_exit_code",
        "truncated_claimed_pass",
        "cleanup_partial_without_failed_case",
    ),
)
def test_java_invalid_execution_is_stable_and_does_not_mutate_state(
    tmp_path: Path,
    case: str,
) -> None:
    call, original = _java_pair()
    payload = json.loads(original.output or "")
    metadata = original.metadata
    if case == "extra_key":
        payload["extra"] = True
    elif case == "missing_key":
        payload.pop("stdout")
    elif case == "purpose_mismatch":
        payload["purpose"] = "test"
    elif case == "zero_sources":
        payload["source_count"] = 0
    elif case == "zero_cases":
        payload["case_count"] = 0
        payload["passed_count"] = 0
    elif case == "passed_over_case_count":
        payload["passed_count"] = 3
    elif case == "complete_with_failed_case":
        payload["failed_case"] = "tests/case"
    elif case == "complete_with_safe_error":
        payload["safe_error_code"] = "compile_failed"
    elif case == "exit_zero_failed_phase":
        payload.update(
            phase="compile",
            safe_error_code="compile_failed",
            passed_count=0,
        )
    elif case == "nonzero_complete_phase":
        metadata = ToolResultMetadata(exit_code=1, duration_ms=25)
    elif case == "timeout_with_exit_code":
        payload.update(
            phase="case",
            safe_error_code="suite_timed_out",
            passed_count=0,
            failed_case="tests/case",
        )
        metadata = ToolResultMetadata(
            exit_code=1,
            timed_out=True,
            duration_ms=25,
        )
    elif case == "truncated_claimed_pass":
        metadata = ToolResultMetadata(
            exit_code=0,
            truncated=True,
            duration_ms=25,
        )
    else:
        payload.update(
            phase="cleanup",
            safe_error_code="cleanup_failed",
            passed_count=1,
            failed_case=None,
        )
        metadata = ToolResultMetadata(exit_code=1, duration_ms=25)
    result = ToolResult(
        call_id=original.call_id,
        tool_name=original.tool_name,
        status="ok",
        output=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        metadata=metadata,
    )
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
    )
    state = _candidate_state(tmp_path)
    with pytest.raises(
        VerificationError,
        match="invalid Java verification execution",
    ):
        gate.observe_tool_result(state, call, result)
    assert state.verification_attempt_count == 0
    assert state.last_verification is None


def test_java_invalid_absolute_argument_is_ignored(tmp_path: Path) -> None:
    call, result = _java_pair()
    call = ToolCall(
        call.call_id,
        call.name,
        {**call.arguments, "source_root": str(tmp_path.resolve())},
    )
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
    )
    state = _candidate_state(tmp_path)
    assert gate.observe_tool_result(state, call, result) is False
    assert state.verification_attempt_count == 0


def test_new_mutation_makes_java_evidence_stale(tmp_path: Path) -> None:
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
    )
    state = _candidate_state(tmp_path)
    call, result = _java_pair()
    assert gate.observe_tool_result(state, call, result) is True
    state.mutation_index += 1
    state.verification_status = VerificationStatus.STALE
    assert gate.evaluate(state).outcome is VerificationOutcome.CONTINUE
    assert state.validation_index == 2
    assert state.mutation_index == 3


def test_required_command_still_executes_after_fresh_java_evidence(
    tmp_path: Path,
) -> None:
    model_gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
    )
    state = _candidate_state(tmp_path)
    call, result = _java_pair()
    assert model_gate.observe_tool_result(state, call, result) is True
    executor = FakeVerificationExecutor(_execution())
    required_gate = VerificationGate(
        required_command=_authorized(),
        execution_context=ExecutionContext(tmp_path),
        executor=executor,
    )
    decision = required_gate.evaluate(state)
    assert decision.outcome is VerificationOutcome.SUCCESS
    assert decision.command_executed is True
    assert len(executor.calls) == 1


def test_model_verification_records_ordered_result_at_current_mutation(
    tmp_path: Path,
) -> None:
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    call, result = _model_pair(stdout="first\nsecond", stderr="warning")

    recorded = gate.observe_tool_result(state, call, result)

    assert recorded is True
    assert state.verification_attempt_count == 1
    assert state.verification_status is VerificationStatus.PASSED
    assert state.last_verification is not None
    assert state.last_verification.validation_index == state.mutation_index == 2
    assert state.last_verification.source is CommandSource.MODEL
    assert state.last_verification.stdout == "first\nsecond"
    assert state.last_verification.stderr == "warning"
    assert state.last_verification.duration_ms == 15


@pytest.mark.parametrize("purpose", ["inspect", "test"])
def test_model_nonverification_purpose_is_ignored(
    tmp_path: Path, purpose: str
) -> None:
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    call, result = _model_pair(purpose=purpose)

    assert gate.observe_tool_result(state, call, result) is False
    assert state.verification_attempt_count == 0
    assert state.last_verification is None


def test_model_git_pseudo_verification_is_ignored(tmp_path: Path) -> None:
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    call, result = _model_pair(argv=(r"C:\trusted\git.exe", "status", "--short"))

    assert gate.observe_tool_result(state, call, result) is False
    assert state.verification_attempt_count == 0


@pytest.mark.parametrize("status", ["rejected", "error"])
def test_model_rejected_or_error_result_does_not_fabricate_evidence(
    tmp_path: Path, status: str
) -> None:
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    call, result = _model_pair(status=status)

    assert gate.observe_tool_result(state, call, result) is False
    assert state.verification_attempt_count == 0
    assert state.last_verification is None


def test_missing_model_evidence_returns_feedback_without_execution(
    tmp_path: Path,
) -> None:
    executor = FakeVerificationExecutor()
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=executor,
    )
    state = _candidate_state(tmp_path)

    decision = gate.evaluate(state)

    assert decision.outcome is VerificationOutcome.CONTINUE
    assert decision.result is None
    assert decision.command_executed is False
    assert decision.feedback is not None
    assert '"status":"not_run"' in (decision.feedback.content or "")
    assert executor.calls == []


def test_optional_gate_validates_changed_markdown_locally(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    executor = FakeVerificationExecutor()
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=executor,
    )
    state = _candidate_state(tmp_path)
    state.mutation_index = 1
    state.modified_paths = ("README.md",)
    state.verification_status = VerificationStatus.STALE

    decision = gate.evaluate(state)

    assert decision.outcome is VerificationOutcome.SUCCESS
    assert decision.command_executed is True
    assert decision.feedback is None
    assert decision.result is state.last_verification
    assert decision.result is not None
    assert decision.result.source is CommandSource.LOCAL_INTEGRITY
    assert decision.result.command == "builtin:validate_changed_files"
    assert decision.result.status is VerificationStatus.PASSED
    assert decision.result.validation_index == state.mutation_index == 1
    assert json.loads(decision.result.stdout) == {
        "checked_paths": ["README.md"],
        "syntax_checked": [],
    }
    assert executor.calls == []


def test_local_integrity_accepts_safe_directory_and_file_paths(
    tmp_path: Path,
) -> None:
    (tmp_path / "snake").mkdir()
    (tmp_path / "snake" / "main.cpp").write_text(
        "int main() { return 0; }\n",
        encoding="utf-8",
    )
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    state.mutation_index = 2
    state.modified_paths = ("snake", "snake/main.cpp")
    state.verification_status = VerificationStatus.STALE

    decision = gate.evaluate(state)

    assert decision.outcome is VerificationOutcome.SUCCESS
    assert decision.result is not None
    assert json.loads(decision.result.stdout) == {
        "checked_paths": ["snake", "snake/main.cpp"],
        "syntax_checked": [],
    }


def test_local_integrity_rejects_removed_directory_changed_path(
    tmp_path: Path,
) -> None:
    target = tmp_path / "removed"
    target.mkdir()
    target.rmdir()
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    state.modified_paths = ("removed",)
    state.verification_status = VerificationStatus.STALE

    decision = gate.evaluate(state)

    assert decision.outcome is VerificationOutcome.CONTINUE
    assert decision.result is not None
    assert json.loads(decision.result.stdout)["failure"] == {
        "path": "",
        "reason": "invalid_changed_path",
    }


def test_local_integrity_rejects_reparse_directory_changed_path(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    try:
        os.symlink(real, link, target_is_directory=True)
    except OSError as exc:
        pytest.fail(
            "real Windows directory symlink is required; "
            f"winerror={getattr(exc, 'winerror', None)}"
        )
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    state.modified_paths = ("linked",)
    state.verification_status = VerificationStatus.STALE

    decision = gate.evaluate(state)

    assert decision.outcome is VerificationOutcome.CONTINUE
    assert decision.result is not None
    assert json.loads(decision.result.stdout)["failure"] == {
        "path": "",
        "reason": "invalid_changed_path",
    }


@pytest.mark.parametrize(
    ("name", "content", "syntax_checked"),
    [
        ("module.py", "VALUE = 1\n", ["module.py"]),
        ("data.json", '{"value":1}\n', ["data.json"]),
        ("config.toml", 'name = "demo"\n', ["config.toml"]),
        ("main.cpp", "int main() { return 0; }\n", []),
    ],
)
def test_local_integrity_uses_deterministic_format_checks(
    tmp_path: Path,
    name: str,
    content: str,
    syntax_checked: list[str],
) -> None:
    (tmp_path / name).write_text(content, encoding="utf-8")
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    state.mutation_index = 1
    state.modified_paths = (name,)
    state.verification_status = VerificationStatus.STALE

    decision = gate.evaluate(state)

    assert decision.outcome is VerificationOutcome.SUCCESS
    assert decision.result is not None
    assert json.loads(decision.result.stdout)["syntax_checked"] == syntax_checked


@pytest.mark.parametrize(
    ("name", "raw", "reason"),
    [
        ("broken.py", b"def broken(:\n", "invalid_syntax"),
        ("broken.json", b"{", "invalid_syntax"),
        ("broken.toml", b"name = [", "invalid_syntax"),
        ("binary.txt", b"text\x00data", "binary_content"),
        ("encoded.txt", b"\xff", "invalid_utf8"),
        ("large.txt", b"x" * 524_289, "file_too_large"),
    ],
    ids=(
        "python-syntax",
        "json-syntax",
        "toml-syntax",
        "binary",
        "invalid-utf8",
        "too-large",
    ),
)
def test_local_integrity_failure_is_stable_and_keeps_changes_unverified(
    tmp_path: Path,
    name: str,
    raw: bytes,
    reason: str,
) -> None:
    (tmp_path / name).write_bytes(raw)
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    state.mutation_index = 1
    state.modified_paths = (name,)
    state.verification_status = VerificationStatus.STALE

    decision = gate.evaluate(state)

    assert decision.outcome is VerificationOutcome.CONTINUE
    assert decision.command_executed is True
    assert decision.result is not None
    assert decision.result.status is VerificationStatus.FAILED
    assert decision.result.exit_code == 1
    assert json.loads(decision.result.stdout)["failure"] == {
        "path": name,
        "reason": reason,
    }
    assert state.has_unverified_changes is True


def test_local_integrity_allows_exact_byte_limit_and_rejects_missing_path(
    tmp_path: Path,
) -> None:
    (tmp_path / "exact.txt").write_bytes(b"x" * 524_288)
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    exact = _candidate_state(tmp_path)
    exact.mutation_index = 1
    exact.modified_paths = ("exact.txt",)
    exact.verification_status = VerificationStatus.STALE

    assert gate.evaluate(exact).outcome is VerificationOutcome.SUCCESS

    missing = _candidate_state(tmp_path)
    missing.mutation_index = 1
    missing.modified_paths = ("missing.txt",)
    missing.verification_status = VerificationStatus.STALE
    decision = gate.evaluate(missing)

    assert decision.outcome is VerificationOutcome.CONTINUE
    assert decision.result is not None
    assert json.loads(decision.result.stdout)["failure"] == {
        "path": "",
        "reason": "invalid_changed_path",
    }


def test_current_failed_model_evidence_is_not_replaced_by_local_integrity(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    state.mutation_index = 1
    state.modified_paths = ("README.md",)
    failed = _result(
        status=VerificationStatus.FAILED,
        validation_index=1,
        source=CommandSource.MODEL,
        exit_code=1,
    )
    state.last_verification = failed
    state.verification_status = VerificationStatus.FAILED

    decision = gate.evaluate(state)

    assert decision.outcome is VerificationOutcome.CONTINUE
    assert decision.command_executed is False
    assert state.last_verification is failed


@pytest.mark.parametrize(
    "source",
    [CommandSource.MODEL, CommandSource.USER_VERIFY],
)
def test_stale_model_evidence_or_user_evidence_blocks_local_integrity(
    tmp_path: Path,
    source: CommandSource,
) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    state.mutation_index = 2
    state.modified_paths = ("README.md",)
    stale = _result(
        status=VerificationStatus.PASSED,
        validation_index=1,
        source=source,
        exit_code=0,
    )
    state.last_verification = stale
    state.verification_status = VerificationStatus.STALE

    decision = gate.evaluate(state)

    assert gate.requires_local_integrity(state) is False
    assert decision.outcome is VerificationOutcome.CONTINUE
    assert decision.command_executed is False
    assert state.last_verification is stale
    assert state.verification_attempt_count == 0


def test_fresh_model_pass_succeeds_and_is_reusable_without_execution(
    tmp_path: Path,
) -> None:
    executor = FakeVerificationExecutor()
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=executor,
    )
    state = _candidate_state(tmp_path)
    call, result = _model_pair()
    assert gate.observe_tool_result(state, call, result) is True

    first = gate.evaluate(state)
    second = gate.evaluate(state)

    assert first.outcome is VerificationOutcome.SUCCESS
    assert second.outcome is VerificationOutcome.SUCCESS
    assert first.command_executed is False
    assert state.verification_attempt_count == 1
    assert executor.calls == []


def test_model_pass_at_mutation_zero_succeeds(tmp_path: Path) -> None:
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    state.mutation_index = 0
    call, result = _model_pair()

    assert gate.observe_tool_result(state, call, result) is True
    assert gate.evaluate(state).outcome is VerificationOutcome.SUCCESS
    assert state.validation_index == 0


def test_new_mutation_makes_model_evidence_stale_but_preserves_audit(
    tmp_path: Path,
) -> None:
    (tmp_path / "changed.py").write_text("value = 2\n", encoding="utf-8")
    gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    call, result = _model_pair()
    assert gate.observe_tool_result(state, call, result) is True
    audit_result = state.last_verification

    state.mutation_index += 1
    state.modified_paths = ("changed.py",)
    state.verification_status = VerificationStatus.STALE
    decision = gate.evaluate(state)

    assert decision.outcome is VerificationOutcome.CONTINUE
    assert decision.command_executed is False
    assert state.last_verification is audit_result
    assert state.validation_index == 2
    assert state.mutation_index == 3


def test_required_command_runs_even_with_fresh_model_evidence(tmp_path: Path) -> None:
    executor = FakeVerificationExecutor(_execution())
    model_gate = VerificationGate(
        required_command=None,
        execution_context=ExecutionContext(tmp_path),
        executor=FakeVerificationExecutor(),
    )
    state = _candidate_state(tmp_path)
    call, result = _model_pair()
    assert model_gate.observe_tool_result(state, call, result) is True
    required_gate = VerificationGate(
        required_command=_authorized(),
        execution_context=ExecutionContext(tmp_path),
        executor=executor,
    )

    decision = required_gate.evaluate(state)

    assert decision.outcome is VerificationOutcome.SUCCESS
    assert decision.command_executed is True
    assert len(executor.calls) == 1
    assert state.verification_attempt_count == 2

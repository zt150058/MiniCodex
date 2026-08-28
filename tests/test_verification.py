from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys

import pytest

from coding_agent.messages import (
    AssistantMessage,
    ToolCall,
    ToolResult,
    ToolResultMetadata,
)
from coding_agent.safety import AuthorizedCommand, CommandSource
from coding_agent.state import AgentState, AgentStatus, VerificationStatus
from coding_agent.tools.base import ExecutionContext, ToolExecution
from coding_agent.tools.shell import CommandStartError
from coding_agent.verification import (
    VerificationDecision,
    VerificationError,
    VerificationGate,
    VerificationOutcome,
    VerificationResult,
    is_credible_verification_command,
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

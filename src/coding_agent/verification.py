from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
from pathlib import Path
import subprocess
import sys
from typing import Protocol

from coding_agent.messages import AssistantMessage, JSONObject, ToolCall, ToolResult
from coding_agent.safety import AuthorizedCommand, CommandSource
from coding_agent.state import AgentState, VerificationStatus
from coding_agent.tools.base import ExecutionContext, ToolExecution
from coding_agent.tools.shell import AuthorizedCommandExecutor, CommandStartError


_TERMINAL_STATUSES = frozenset(
    {
        VerificationStatus.PASSED,
        VerificationStatus.FAILED,
        VerificationStatus.TIMED_OUT,
        VerificationStatus.ERROR,
    }
)
_ERROR_CODES = frozenset(
    {"verification_command_start_failed", "verification_internal_error"}
)
_NON_EVIDENCE_ARGUMENTS = frozenset({"-h", "--help", "-V", "--version"})


def _same_executable(left: str, right: str) -> bool:
    try:
        return Path(left).resolve(strict=False) == Path(right).resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return False


def is_credible_verification_command(command: AuthorizedCommand) -> bool:
    if not isinstance(command, AuthorizedCommand):
        return False
    if command.purpose != "verification" or not isinstance(
        command.source, CommandSource
    ):
        return False
    argv = command.argv
    if not isinstance(argv, tuple) or not argv or not all(
        isinstance(value, str) and value for value in argv
    ):
        return False
    if any(value in _NON_EVIDENCE_ARGUMENTS for value in argv[1:]):
        return False

    executable_name = Path(argv[0]).name.casefold()
    if _same_executable(argv[0], sys.executable):
        if len(argv) >= 3 and argv[1:3] in {
            ("-m", "pytest"),
            ("-m", "unittest"),
        }:
            return True
        return len(argv) >= 2 and argv[1].casefold().endswith(".py")
    if executable_name in {"pytest", "pytest.exe"}:
        return True
    if executable_name in {"ruff", "ruff.exe"}:
        return len(argv) >= 3 and argv[1] == "check"
    if executable_name in {"mypy", "mypy.exe"}:
        return len(argv) >= 2
    return False


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: VerificationStatus
    validation_index: int
    command: str = field(repr=False)
    source: CommandSource
    exit_code: int | None
    stdout: str = field(repr=False)
    stderr: str = field(repr=False)
    timed_out: bool
    truncated: bool
    duration_ms: int
    error: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, VerificationStatus):
            raise TypeError("status must be VerificationStatus")
        if self.status not in _TERMINAL_STATUSES:
            raise ValueError("status must be a terminal verification status")
        if isinstance(self.validation_index, bool) or not isinstance(
            self.validation_index, int
        ):
            raise TypeError("validation_index must be an integer")
        if self.validation_index < 0:
            raise ValueError("validation_index must be non-negative")
        if not isinstance(self.command, str):
            raise TypeError("command must be a string")
        if not self.command:
            raise ValueError("command must not be empty")
        if not isinstance(self.source, CommandSource):
            raise TypeError("source must be CommandSource")
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)
        ):
            raise TypeError("exit_code must be an integer or None")
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise TypeError("stdout and stderr must be strings")
        if not isinstance(self.timed_out, bool):
            raise TypeError("timed_out must be a boolean")
        if not isinstance(self.truncated, bool):
            raise TypeError("truncated must be a boolean")
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int):
            raise TypeError("duration_ms must be an integer")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")
        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("error must be a string or None")
        self._validate_terminal_state()

    def _validate_terminal_state(self) -> None:
        if self.status is VerificationStatus.PASSED:
            valid = (
                self.exit_code == 0
                and not self.timed_out
                and self.error is None
            )
        elif self.status is VerificationStatus.FAILED:
            valid = (
                self.exit_code is not None
                and self.exit_code != 0
                and not self.timed_out
                and self.error is None
            )
        elif self.status is VerificationStatus.TIMED_OUT:
            valid = self.exit_code is None and self.timed_out
        else:
            valid = (
                self.exit_code is None
                and not self.timed_out
                and self.error in _ERROR_CODES
            )
        if not valid:
            raise ValueError("verification result fields contradict status")

    def to_dict(self) -> JSONObject:
        return {
            "status": self.status.value,
            "validation_index": self.validation_index,
            "command": self.command,
            "source": self.source.value,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


class VerificationOutcome(StrEnum):
    SUCCESS = "success"
    CONTINUE = "continue"


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    outcome: VerificationOutcome
    result: VerificationResult | None
    feedback: AssistantMessage | None
    command_executed: bool


class VerificationError(RuntimeError):
    """The local verification evidence violates an internal invariant."""


class VerificationExecutor(Protocol):
    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
    ) -> ToolExecution: ...


_SHELL_OUTPUT_KEYS = frozenset(
    {"argv", "cleanup_error", "purpose", "stderr", "stdout"}
)


def _decode_execution(
    execution: ToolExecution,
    *,
    source: CommandSource,
    validation_index: int,
) -> VerificationResult:
    try:
        if not isinstance(execution, ToolExecution) or not isinstance(
            execution.output, str
        ):
            raise ValueError
        payload = json.loads(execution.output)
        if not isinstance(payload, dict) or set(payload) != _SHELL_OUTPUT_KEYS:
            raise ValueError
        argv = payload["argv"]
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) and item for item in argv)
        ):
            raise ValueError
        if payload["purpose"] != "verification":
            raise ValueError
        stdout = payload["stdout"]
        stderr = payload["stderr"]
        cleanup_error = payload["cleanup_error"]
        if not isinstance(stdout, str) or not isinstance(stderr, str):
            raise ValueError
        if cleanup_error is not None and not isinstance(cleanup_error, str):
            raise ValueError
        metadata = execution.metadata
        if metadata.timed_out:
            status = VerificationStatus.TIMED_OUT
            error = cleanup_error
        elif metadata.exit_code == 0:
            status = VerificationStatus.PASSED
            error = None
        elif metadata.exit_code is not None:
            status = VerificationStatus.FAILED
            error = None
        else:
            raise ValueError
        return VerificationResult(
            status=status,
            validation_index=validation_index,
            command=subprocess.list2cmdline(argv),
            source=source,
            exit_code=metadata.exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=metadata.timed_out,
            truncated=metadata.truncated,
            duration_ms=metadata.duration_ms,
            error=error,
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        raise VerificationError("invalid verification execution") from None


def _feedback(result: VerificationResult | None, mutation_index: int) -> AssistantMessage:
    if result is None:
        payload: JSONObject = {
            "command": None,
            "error": None,
            "exit_code": None,
            "mutation_index": mutation_index,
            "source": None,
            "status": "not_run",
            "stderr": None,
            "stdout": None,
            "timed_out": False,
            "truncated": False,
            "validation_index": None,
        }
    else:
        payload = {
            "command": result.command,
            "error": result.error,
            "exit_code": result.exit_code,
            "mutation_index": mutation_index,
            "source": result.source.value,
            "status": result.status.value,
            "stderr": result.stderr,
            "stdout": result.stdout,
            "timed_out": result.timed_out,
            "truncated": result.truncated,
            "validation_index": result.validation_index,
        }
    return AssistantMessage(
        "coding-agent verification feedback\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


class VerificationGate:
    def __init__(
        self,
        *,
        required_command: AuthorizedCommand | None,
        execution_context: ExecutionContext,
        executor: VerificationExecutor | None = None,
    ) -> None:
        if required_command is not None and not isinstance(
            required_command, AuthorizedCommand
        ):
            raise TypeError("required_command must be AuthorizedCommand or None")
        if required_command is not None and (
            required_command.source is not CommandSource.USER_VERIFY
            or not is_credible_verification_command(required_command)
        ):
            raise ValueError(
                "required_command must be a credible user verification command"
            )
        if not isinstance(execution_context, ExecutionContext):
            raise TypeError("execution_context must be ExecutionContext")
        self._required_command = required_command
        self._execution_context = execution_context
        self._executor = (
            AuthorizedCommandExecutor() if executor is None else executor
        )

    @property
    def requires_execution(self) -> bool:
        return self._required_command is not None

    def observe_tool_result(
        self,
        state: AgentState,
        call: ToolCall,
        result: ToolResult,
    ) -> bool:
        if (
            not isinstance(state, AgentState)
            or not isinstance(call, ToolCall)
            or not isinstance(result, ToolResult)
            or call.name != "run_command"
            or result.call_id != call.call_id
            or result.tool_name != call.name
            or result.status != "ok"
            or set(call.arguments) != {"command", "purpose"}
            or call.arguments.get("purpose") != "verification"
            or not isinstance(call.arguments.get("command"), str)
        ):
            return False
        try:
            if not isinstance(result.output, str):
                raise ValueError
            payload = json.loads(result.output)
            if not isinstance(payload, dict) or set(payload) != _SHELL_OUTPUT_KEYS:
                raise ValueError
            argv_value = payload["argv"]
            if (
                not isinstance(argv_value, list)
                or not argv_value
                or not all(isinstance(item, str) and item for item in argv_value)
            ):
                raise ValueError
            argv = tuple(argv_value)
            executed = AuthorizedCommand(
                argv=argv,
                normalized_command=subprocess.list2cmdline(argv),
                purpose=payload["purpose"],
                source=CommandSource.MODEL,
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            raise VerificationError("invalid verification execution") from None
        if not is_credible_verification_command(executed):
            return False
        evidence = _decode_execution(
            ToolExecution(output=result.output, metadata=result.metadata),
            source=CommandSource.MODEL,
            validation_index=state.mutation_index,
        )
        state.verification_attempt_count += 1
        state.last_verification = evidence
        state.verification_status = evidence.status
        return True

    def evaluate(self, state: AgentState) -> VerificationDecision:
        command = self._required_command
        if command is None:
            result = state.last_verification
            if (
                result is not None
                and result.status is VerificationStatus.PASSED
                and result.validation_index == state.mutation_index
            ):
                return VerificationDecision(
                    VerificationOutcome.SUCCESS, result, None, False
                )
            return VerificationDecision(
                VerificationOutcome.CONTINUE,
                result,
                _feedback(result, state.mutation_index),
                False,
            )

        state.verification_attempt_count += 1
        state.verification_status = VerificationStatus.RUNNING
        try:
            execution = self._executor.execute(command, self._execution_context)
        except CommandStartError:
            result = VerificationResult(
                status=VerificationStatus.ERROR,
                validation_index=state.mutation_index,
                command=command.normalized_command,
                source=command.source,
                exit_code=None,
                stdout="",
                stderr="",
                timed_out=False,
                truncated=False,
                duration_ms=0,
                error="verification_command_start_failed",
            )
        except Exception:
            result = VerificationResult(
                status=VerificationStatus.ERROR,
                validation_index=state.mutation_index,
                command=command.normalized_command,
                source=command.source,
                exit_code=None,
                stdout="",
                stderr="",
                timed_out=False,
                truncated=False,
                duration_ms=0,
                error="verification_internal_error",
            )
        else:
            result = _decode_execution(
                execution,
                source=command.source,
                validation_index=state.mutation_index,
            )
            if result.command != command.normalized_command:
                raise VerificationError("invalid verification execution")
        state.last_verification = result
        state.verification_status = result.status
        if (
            result.status is VerificationStatus.PASSED
            and result.exit_code == 0
            and not result.timed_out
            and result.validation_index == state.mutation_index
            and result.source is CommandSource.USER_VERIFY
            and result.command == command.normalized_command
        ):
            return VerificationDecision(VerificationOutcome.SUCCESS, result, None, True)
        return VerificationDecision(
            VerificationOutcome.CONTINUE,
            result,
            _feedback(result, state.mutation_index),
            True,
        )

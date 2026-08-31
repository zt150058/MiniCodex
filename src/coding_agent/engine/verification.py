from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
import tomllib
from typing import Protocol

from coding_agent.engine.messages import AssistantMessage, JSONObject, ToolCall, ToolResult
from coding_agent.operations.safety import (
    AuthorizedCommand,
    CommandSource,
    PathGuard,
    SafetyViolation,
)
from coding_agent.engine.state import AgentState, VerificationStatus
from coding_agent.operations.tools.base import ExecutionContext, ToolExecution
from coding_agent.operations.tools.shell import AuthorizedCommandExecutor, CommandStartError


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
_LOCAL_INTEGRITY_COMMAND = "builtin:validate_changed_files"
_LOCAL_INTEGRITY_MAX_BYTES = 524_288
_VERIFICATION_SOURCE_RANK = {
    CommandSource.LOCAL_INTEGRITY: 0,
    CommandSource.MODEL: 1,
    CommandSource.USER_VERIFY: 2,
}


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


def verification_advances_progress(
    previous: VerificationResult | None,
    current: VerificationResult,
) -> bool:
    if previous is not None and not isinstance(previous, VerificationResult):
        raise TypeError("previous must be VerificationResult or None")
    if not isinstance(current, VerificationResult):
        raise TypeError("current must be VerificationResult")
    if previous is None:
        return True
    if current.validation_index != previous.validation_index:
        return current.validation_index > previous.validation_index
    if current.status is not previous.status:
        return True
    return (
        _VERIFICATION_SOURCE_RANK[current.source]
        > _VERIFICATION_SOURCE_RANK[previous.source]
    )


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
_JAVA_OUTPUT_KEYS = frozenset(
    {
        "case_count",
        "failed_case",
        "passed_count",
        "phase",
        "purpose",
        "safe_error_code",
        "source_count",
        "stderr",
        "stdout",
    }
)
_JAVA_ARGUMENT_KEYS = frozenset(
    {"source_root", "main_class", "tests_directory", "purpose"}
)
_JAVA_MAIN_CLASS = re.compile(
    r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*"
)
_JAVA_FAILURE_CODES = frozenset(
    {
        "compile_failed",
        "program_failed",
        "output_mismatch",
        "output_truncated",
        "cleanup_failed",
    }
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


def _safe_java_relative(value: object) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value:
        return False
    path = PureWindowsPath(value)
    return not path.drive and not path.root and ".." not in path.parts


def _java_command_description(arguments: JSONObject) -> str:
    return (
        "run_java_tests "
        f"source_root={arguments['source_root']} "
        f"main_class={arguments['main_class']} "
        f"tests_directory={arguments['tests_directory']}"
    )


def _decode_java_execution(
    execution: ToolExecution,
    *,
    arguments: JSONObject,
    validation_index: int,
    workspace: Path,
) -> VerificationResult:
    try:
        if (
            not isinstance(execution, ToolExecution)
            or not isinstance(execution.output, str)
            or set(arguments) != _JAVA_ARGUMENT_KEYS
            or arguments.get("purpose") != "verification"
            or not _safe_java_relative(arguments.get("source_root"))
            or not _safe_java_relative(arguments.get("tests_directory"))
            or not isinstance(arguments.get("main_class"), str)
            or _JAVA_MAIN_CLASS.fullmatch(arguments["main_class"]) is None
        ):
            raise ValueError
        payload = json.loads(execution.output)
        if not isinstance(payload, dict) or set(payload) != _JAVA_OUTPUT_KEYS:
            raise ValueError
        if payload["purpose"] != "verification":
            raise ValueError
        source_count = payload["source_count"]
        case_count = payload["case_count"]
        passed_count = payload["passed_count"]
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (source_count, case_count, passed_count)
        ):
            raise ValueError
        if (
            not 1 <= source_count <= 500
            or not 1 <= case_count <= 200
            or not 0 <= passed_count <= case_count
        ):
            raise ValueError
        failed_case = payload["failed_case"]
        if failed_case is not None and not _safe_java_relative(failed_case):
            raise ValueError
        safe_error = payload["safe_error_code"]
        if safe_error is not None and not isinstance(safe_error, str):
            raise ValueError
        phase = payload["phase"]
        stdout = payload["stdout"]
        stderr = payload["stderr"]
        if (
            phase not in {"compile", "case", "cleanup", "complete"}
            or not isinstance(stdout, str)
            or not isinstance(stderr, str)
            or len(stdout.encode("utf-8")) > 8_192
            or len(stderr.encode("utf-8")) > 8_192
        ):
            raise ValueError
        canonical = str(Path(workspace).resolve(strict=True))
        diagnostics = (stdout + "\n" + stderr).casefold()
        if (
            canonical.casefold() in diagnostics
            or canonical.replace("\\", "/").casefold() in diagnostics
        ):
            raise ValueError

        metadata = execution.metadata
        if (
            phase == "complete"
            and safe_error is None
            and failed_case is None
            and passed_count == case_count
            and metadata.exit_code == 0
            and not metadata.timed_out
            and not metadata.truncated
        ):
            status = VerificationStatus.PASSED
            error = None
        elif (
            safe_error == "suite_timed_out"
            and phase in {"compile", "case"}
            and metadata.exit_code is None
            and metadata.timed_out
            and not metadata.truncated
            and (
                (phase == "compile" and failed_case is None and passed_count == 0)
                or (phase == "case" and failed_case is not None)
            )
        ):
            status = VerificationStatus.TIMED_OUT
            error = "suite_timed_out"
        elif (
            safe_error in _JAVA_FAILURE_CODES
            and metadata.exit_code is not None
            and metadata.exit_code != 0
            and not metadata.timed_out
        ):
            valid_failure = False
            if safe_error == "compile_failed":
                valid_failure = (
                    phase == "compile"
                    and failed_case is None
                    and passed_count == 0
                    and not metadata.truncated
                )
            elif safe_error in {"program_failed", "output_mismatch"}:
                valid_failure = (
                    phase == "case"
                    and failed_case is not None
                    and passed_count < case_count
                    and not metadata.truncated
                )
            elif safe_error == "output_truncated":
                valid_failure = (
                    phase in {"compile", "case"}
                    and metadata.truncated
                    and (
                        (phase == "compile" and failed_case is None)
                        or (phase == "case" and failed_case is not None)
                    )
                )
            else:
                valid_failure = phase == "cleanup" and (
                    (
                        failed_case is None
                        and passed_count in {0, case_count}
                    )
                    or (
                        failed_case is not None
                        and _safe_java_relative(failed_case)
                        and passed_count < case_count
                    )
                )
            if not valid_failure:
                raise ValueError
            status = VerificationStatus.FAILED
            error = None
        else:
            raise ValueError

        return VerificationResult(
            status=status,
            validation_index=validation_index,
            command=_java_command_description(arguments),
            source=CommandSource.MODEL,
            exit_code=metadata.exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=metadata.timed_out,
            truncated=metadata.truncated,
            duration_ms=metadata.duration_ms,
            error=error,
        )
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        raise VerificationError(
            "invalid Java verification execution"
        ) from None


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

    def requires_local_integrity(self, state: AgentState) -> bool:
        if not isinstance(state, AgentState):
            raise TypeError("state must be AgentState")
        return (
            self._required_command is None
            and state.has_unverified_changes
            and bool(state.modified_paths)
            and (
                state.last_verification is None
                or state.last_verification.source
                is CommandSource.LOCAL_INTEGRITY
            )
            and not (
                state.last_verification is not None
                and state.last_verification.validation_index == state.mutation_index
            )
        )

    def _evaluate_local_integrity(self, state: AgentState) -> VerificationResult:
        checked_paths: list[str] = []
        syntax_checked: list[str] = []
        failure: tuple[str, str] | None = None
        try:
            guard = PathGuard(self._execution_context.workspace)
            for relative_path in state.modified_paths:
                guarded = guard.existing_entry(relative_path)
                if guarded.absolute.is_dir():
                    checked_paths.append(guarded.relative)
                    continue
                if not guarded.absolute.is_file():
                    failure = (guarded.relative, "invalid_changed_path")
                    break
                with guarded.absolute.open("rb") as stream:
                    raw = stream.read(_LOCAL_INTEGRITY_MAX_BYTES + 1)
                if len(raw) > _LOCAL_INTEGRITY_MAX_BYTES:
                    failure = (guarded.relative, "file_too_large")
                    break
                try:
                    text = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    failure = (guarded.relative, "invalid_utf8")
                    break
                if "\x00" in text:
                    failure = (guarded.relative, "binary_content")
                    break
                suffix = guarded.absolute.suffix.casefold()
                try:
                    if suffix == ".py":
                        compile(text, guarded.relative, "exec")
                        syntax_checked.append(guarded.relative)
                    elif suffix == ".json":
                        json.loads(text)
                        syntax_checked.append(guarded.relative)
                    elif suffix == ".toml":
                        tomllib.loads(text)
                        syntax_checked.append(guarded.relative)
                except (SyntaxError, json.JSONDecodeError, tomllib.TOMLDecodeError):
                    failure = (guarded.relative, "invalid_syntax")
                    break
                checked_paths.append(guarded.relative)
        except (OSError, RuntimeError, SafetyViolation, TypeError, ValueError):
            failure = ("", "invalid_changed_path")

        payload: JSONObject = {
            "checked_paths": checked_paths,
            "syntax_checked": syntax_checked,
        }
        if failure is not None:
            failed_path, reason = failure
            payload["failure"] = {
                "path": failed_path,
                "reason": reason,
            }
        return VerificationResult(
            status=(
                VerificationStatus.PASSED
                if failure is None
                else VerificationStatus.FAILED
            ),
            validation_index=state.mutation_index,
            command=_LOCAL_INTEGRITY_COMMAND,
            source=CommandSource.LOCAL_INTEGRITY,
            exit_code=0 if failure is None else 1,
            stdout=json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            stderr="",
            timed_out=False,
            truncated=False,
            duration_ms=0,
            error=None,
        )

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
            or result.call_id != call.call_id
            or result.tool_name != call.name
            or result.status != "ok"
        ):
            return False
        if call.name == "run_java_tests":
            if (
                set(call.arguments) != _JAVA_ARGUMENT_KEYS
                or call.arguments.get("purpose") != "verification"
                or not _safe_java_relative(call.arguments.get("source_root"))
                or not _safe_java_relative(
                    call.arguments.get("tests_directory")
                )
                or not isinstance(call.arguments.get("main_class"), str)
                or _JAVA_MAIN_CLASS.fullmatch(call.arguments["main_class"])
                is None
            ):
                return False
            evidence = _decode_java_execution(
                ToolExecution(output=result.output, metadata=result.metadata),
                arguments=call.arguments,
                validation_index=state.mutation_index,
                workspace=self._execution_context.workspace,
            )
            state.verification_attempt_count += 1
            state.last_verification = evidence
            state.verification_status = evidence.status
            return True
        if (
            call.name != "run_command"
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
            if self.requires_local_integrity(state):
                state.verification_attempt_count += 1
                state.verification_status = VerificationStatus.RUNNING
                result = self._evaluate_local_integrity(state)
                state.last_verification = result
                state.verification_status = result.status
                if result.status is VerificationStatus.PASSED:
                    return VerificationDecision(
                        VerificationOutcome.SUCCESS,
                        result,
                        None,
                        True,
                    )
                return VerificationDecision(
                    VerificationOutcome.CONTINUE,
                    result,
                    _feedback(result, state.mutation_index),
                    True,
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

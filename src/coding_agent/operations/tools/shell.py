from __future__ import annotations

import codecs
from collections.abc import Callable
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
from threading import Thread
import time
from typing import BinaryIO

from coding_agent.engine.messages import JSONObject, ToolResultMetadata
from coding_agent.operations.safety import (
    AuthorizedCommand,
    CommandPolicy,
    CommandSource,
    PathGuard,
    parse_windows_command_line,
)
from coding_agent.operations.tools.base import ExecutionContext, ToolArgumentError, ToolExecution

_ARGUMENT_NAMES = {"command", "purpose"}
_INSPECTION_ARGUMENT_NAMES = {"command"}
_PURPOSES = {"inspect", "test", "verification"}
_OUTPUT_LIMIT_BYTES = 64 * 1024
_READ_CHUNK_BYTES = 8 * 1024
_POST_TERMINATION_WAIT_SECONDS = 0.5

def _validated_arguments(arguments: object) -> tuple[str, str]:
    if not isinstance(arguments, dict) or set(arguments) != _ARGUMENT_NAMES:
        raise ToolArgumentError(
            "run_command arguments must contain exactly: command, purpose"
        )
    command = arguments["command"]
    if not isinstance(command, str) or not command.strip():
        raise ToolArgumentError("command must be a non-empty string")
    purpose = arguments["purpose"]
    if not isinstance(purpose, str) or purpose not in _PURPOSES:
        raise ToolArgumentError("purpose must be inspect, test, or verification")
    return command.strip(), purpose


def _validated_inspection_arguments(arguments: object) -> str:
    if (
        not isinstance(arguments, dict)
        or set(arguments) != _INSPECTION_ARGUMENT_NAMES
    ):
        raise ToolArgumentError(
            "inspect_git arguments must contain exactly: command"
        )
    command = arguments["command"]
    if not isinstance(command, str) or not command.strip():
        raise ToolArgumentError("command must be a non-empty string")
    return command.strip()


_REMOVED_ENVIRONMENT_KEYS = {
    "openai_api_key",
    "chat_completions_api_key",
    "classpath",
    "java_tool_options",
    "_java_options",
    "jdk_java_options",
    "jdk_javac_options",
    "pythonpath", "pythonhome", "pytest_addopts",
    "pytest_plugins", "mypypath", "mypy_config_file", "git_dir",
    "git_work_tree", "git_object_directory",
    "git_alternate_object_directories", "git_external_diff", "git_ssh",
    "git_ssh_command", "git_askpass", "ssh_askpass",
}


def _child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        folded = key.casefold()
        if (
            folded in _REMOVED_ENVIRONMENT_KEYS
            or folded == "git_config_count"
            or folded.startswith("git_config_key_")
            or folded.startswith("git_config_value_")
        ):
            environment.pop(key, None)
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "NUL",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_LAZY_FETCH": "1",
        }
    )
    return environment


def _json_output(
    argv: tuple[str, ...],
    purpose: str,
    stdout: str,
    stderr: str,
    cleanup_error: str | None,
) -> str:
    return json.dumps(
        {
            "argv": list(argv),
            "cleanup_error": cleanup_error,
            "purpose": purpose,
            "stderr": stderr,
            "stdout": stdout,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class CommandStartError(RuntimeError):
    """The authorized child process could not be created."""


def _start_error(exc: OSError) -> CommandStartError:
    if isinstance(exc, FileNotFoundError):
        detail = "executable unavailable"
    elif isinstance(exc, PermissionError):
        detail = "permission denied"
    else:
        detail = "operating system error"
    return CommandStartError(f"command could not be started: {detail}")


@dataclass(slots=True)
class _BoundedBytes:
    data: bytearray = field(default_factory=bytearray)
    truncated: bool = False
    read_error: bool = False


def _drain_pipe(pipe: BinaryIO, capture: _BoundedBytes) -> None:
    try:
        while True:
            chunk = pipe.read(_READ_CHUNK_BYTES)
            if not chunk:
                return
            remaining = _OUTPUT_LIMIT_BYTES - len(capture.data)
            if remaining > 0:
                capture.data.extend(chunk[:remaining])
            if len(chunk) > remaining:
                capture.truncated = True
    except OSError:
        capture.read_error = True
    finally:
        pipe.close()


def _decode_captured(capture: _BoundedBytes) -> str:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    return decoder.decode(bytes(capture.data), final=not capture.truncated)


def _reader(pipe: BinaryIO, capture: _BoundedBytes) -> Thread:
    thread = Thread(target=_drain_pipe, args=(pipe, capture), daemon=True)
    thread.start()
    return thread


ProcessFactory = Callable[..., subprocess.Popen[bytes]]
TreeTerminator = Callable[[subprocess.Popen[bytes]], str | None]
PolicyFactory = Callable[[Path], CommandPolicy]


def _taskkill_path() -> Path:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return system_root / "System32" / "taskkill.exe"


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> str | None:
    try:
        completed = subprocess.run(
            [
                str(_taskkill_path()),
                "/PID",
                str(process.pid),
                "/T",
                "/F",
            ],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "process-tree cleanup unavailable"
    if completed.returncode != 0 and process.poll() is None:
        return "process-tree cleanup failed"
    return None


class AuthorizedCommandExecutor:
    def __init__(
        self,
        *,
        process_factory: ProcessFactory | None = None,
        tree_terminator: TreeTerminator | None = None,
    ) -> None:
        self._process_factory = (
            subprocess.Popen if process_factory is None else process_factory
        )
        self._tree_terminator = (
            _terminate_process_tree if tree_terminator is None else tree_terminator
        )

    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
        *,
        stdin_stream: BinaryIO | None = None,
    ) -> ToolExecution:
        if not isinstance(command, AuthorizedCommand):
            raise TypeError("command must be AuthorizedCommand")
        if not isinstance(context, ExecutionContext):
            raise TypeError("context must be ExecutionContext")
        argv = command.argv
        purpose = command.purpose
        workspace = PathGuard(context.workspace).workspace

        started = time.monotonic_ns()
        try:
            process = self._process_factory(
                argv,
                shell=False,
                cwd=workspace,
                env=_child_environment(),
                stdin=(
                    subprocess.DEVNULL
                    if stdin_stream is None
                    else stdin_stream
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise _start_error(exc) from exc

        assert process.stdout is not None
        assert process.stderr is not None
        stdout_capture = _BoundedBytes()
        stderr_capture = _BoundedBytes()
        stdout_thread = _reader(process.stdout, stdout_capture)
        stderr_thread = _reader(process.stderr, stderr_capture)
        timed_out = False
        cleanup_error: str | None = None
        try:
            exit_code: int | None = process.wait(
                timeout=context.command_timeout_seconds
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = None
            try:
                cleanup_error = self._tree_terminator(process)
            except (OSError, subprocess.TimeoutExpired):
                cleanup_error = "process-tree cleanup unavailable"
            try:
                process.wait(timeout=_POST_TERMINATION_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=_POST_TERMINATION_WAIT_SECONDS)
                except (OSError, subprocess.TimeoutExpired):
                    cleanup_error = cleanup_error or "parent-process cleanup failed"

        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            cleanup_error = cleanup_error or "command output cleanup failed"
        if stdout_capture.read_error or stderr_capture.read_error:
            raise RuntimeError("command output could not be captured")

        duration_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
        truncated = stdout_capture.truncated or stderr_capture.truncated
        return ToolExecution(
            output=_json_output(
                argv,
                purpose,
                _decode_captured(stdout_capture),
                _decode_captured(stderr_capture),
                cleanup_error,
            ),
            metadata=ToolResultMetadata(
                exit_code=exit_code,
                timed_out=timed_out,
                truncated=truncated,
                duration_ms=duration_ms,
            ),
        )


class RunCommandTool:
    name = "run_command"
    schema: JSONObject = {
        "name": "run_command",
        "description": (
            "Run a single process in the workspace. Use no shell operators. "
            "Supported verification forms: python "
            "<workspace-relative-file.py>, python -m pytest ..., or python -m "
            "unittest ... with purpose=\"verification\". Use run_java_tests "
            "for Java verification."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "minLength": 1},
                "purpose": {
                    "type": "string",
                    "enum": ["inspect", "test", "verification"],
                },
            },
            "required": ["command", "purpose"],
            "additionalProperties": False,
        },
    }

    def __init__(
        self,
        *,
        process_factory: ProcessFactory | None = None,
        tree_terminator: TreeTerminator | None = None,
        policy_factory: PolicyFactory | None = None,
        authorized_executor: AuthorizedCommandExecutor | None = None,
    ) -> None:
        if authorized_executor is not None and (
            process_factory is not None or tree_terminator is not None
        ):
            raise TypeError(
                "authorized_executor cannot be combined with process_factory "
                "or tree_terminator"
            )
        self._authorized_executor = (
            AuthorizedCommandExecutor(
                process_factory=process_factory,
                tree_terminator=tree_terminator,
            )
            if authorized_executor is None
            else authorized_executor
        )
        self._policy_factory = (
            CommandPolicy if policy_factory is None else policy_factory
        )

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        command, purpose = _validated_arguments(arguments)
        policy = self._policy_factory(context.workspace)
        authorized = policy.authorize(
            command,
            purpose=purpose,
            source=CommandSource.MODEL,
        )
        return self._authorized_executor.execute(
            authorized,
            ExecutionContext(
                workspace=policy.workspace,
                command_timeout_seconds=context.command_timeout_seconds,
            ),
        )


class InspectGitTool:
    name = "inspect_git"
    schema: JSONObject = {
        "name": "inspect_git",
        "description": "Inspect local Git state without modifying it.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "minLength": 1}},
            "required": ["command"],
            "additionalProperties": False,
        },
    }

    def __init__(
        self,
        *,
        authorized_executor: AuthorizedCommandExecutor | None = None,
        policy_factory: PolicyFactory | None = None,
    ) -> None:
        self._authorized_executor = (
            AuthorizedCommandExecutor()
            if authorized_executor is None
            else authorized_executor
        )
        self._policy_factory = (
            CommandPolicy if policy_factory is None else policy_factory
        )

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        command = _validated_inspection_arguments(arguments)
        policy = self._policy_factory(context.workspace)
        authorized = policy.authorize_git_inspection(
            command,
            source=CommandSource.MODEL,
        )
        return self._authorized_executor.execute(
            authorized,
            ExecutionContext(
                workspace=policy.workspace,
                command_timeout_seconds=context.command_timeout_seconds,
            ),
        )

from __future__ import annotations

import codecs
from collections.abc import Callable
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
import time
from typing import BinaryIO

from coding_agent.messages import JSONObject, ToolResultMetadata
from coding_agent.tools.base import ExecutionContext, ToolArgumentError, ToolExecution

_ARGUMENT_NAMES = {"command", "purpose"}
_PURPOSES = {"inspect", "test", "verification"}
_OUTPUT_LIMIT_BYTES = 64 * 1024
_READ_CHUNK_BYTES = 8 * 1024
_POST_TERMINATION_WAIT_SECONDS = 0.5

_COMMAND_LINE_TO_ARGV_W = ctypes.windll.shell32.CommandLineToArgvW
_COMMAND_LINE_TO_ARGV_W.argtypes = [
    wintypes.LPCWSTR,
    ctypes.POINTER(ctypes.c_int),
]
_COMMAND_LINE_TO_ARGV_W.restype = ctypes.POINTER(wintypes.LPWSTR)
_LOCAL_FREE = ctypes.windll.kernel32.LocalFree
_LOCAL_FREE.argtypes = [wintypes.HLOCAL]
_LOCAL_FREE.restype = wintypes.HLOCAL


def _validated_arguments(arguments: object) -> tuple[str, str]:
    if not isinstance(arguments, dict) or set(arguments) != _ARGUMENT_NAMES:
        raise ToolArgumentError(
            "run_command arguments must contain exactly: command, purpose"
        )
    command = arguments["command"]
    if not isinstance(command, str) or not command.strip():
        raise ToolArgumentError("command must be a non-empty string")
    if "\x00" in command:
        raise ToolArgumentError("command must not contain NUL")
    purpose = arguments["purpose"]
    if not isinstance(purpose, str) or purpose not in _PURPOSES:
        raise ToolArgumentError("purpose must be inspect, test, or verification")
    return command.strip(), purpose


def _has_unclosed_quote(command: str) -> bool:
    quoted = False
    backslashes = 0
    for character in command:
        if character == "\\":
            backslashes += 1
            continue
        if character == '"' and backslashes % 2 == 0:
            quoted = not quoted
        backslashes = 0
    return quoted


def parse_windows_command_line(command: str) -> tuple[str, ...]:
    command, _ = _validated_arguments(
        {"command": command, "purpose": "inspect"}
    )
    if _has_unclosed_quote(command):
        raise ToolArgumentError("command contains an unclosed quote")

    argc = ctypes.c_int()
    argv_pointer = _COMMAND_LINE_TO_ARGV_W(command, ctypes.byref(argc))
    if not argv_pointer or argc.value <= 0:
        raise ToolArgumentError("command could not be parsed by Windows")
    try:
        argv = tuple(argv_pointer[index] for index in range(argc.value))
    finally:
        _LOCAL_FREE(ctypes.cast(argv_pointer, wintypes.HLOCAL))
    if not argv or not argv[0]:
        raise ToolArgumentError("command could not be parsed by Windows")
    return argv


def _normalized_workspace(context: ExecutionContext) -> Path:
    try:
        workspace = context.workspace.resolve(strict=True)
    except OSError as exc:
        raise ToolArgumentError("workspace must be an existing directory") from exc
    if not workspace.is_dir():
        raise ToolArgumentError("workspace must be an existing directory")
    return workspace


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _authorize_temporary_command(argv: tuple[str, ...], workspace: Path) -> None:
    try:
        executable = Path(argv[0]).resolve(strict=True)
        current_python = Path(sys.executable).resolve(strict=True)
    except OSError as exc:
        raise ToolArgumentError(
            "command is outside the temporary Task 7 boundary"
        ) from exc
    if not _same_path(executable, current_python) or len(argv) < 2:
        raise ToolArgumentError("command is outside the temporary Task 7 boundary")

    if argv[1] == "-m":
        if len(argv) >= 3 and argv[2] in {"pytest", "unittest"}:
            return
        raise ToolArgumentError("command is outside the temporary Task 7 boundary")
    if argv[1].startswith("-"):
        raise ToolArgumentError("command is outside the temporary Task 7 boundary")

    script = Path(argv[1])
    if not script.is_absolute():
        script = workspace / script
    try:
        script = script.resolve(strict=True)
        script.relative_to(workspace)
    except (OSError, ValueError) as exc:
        raise ToolArgumentError(
            "command is outside the temporary Task 7 boundary"
        ) from exc
    if not script.is_file() or script.suffix.casefold() != ".py":
        raise ToolArgumentError("command is outside the temporary Task 7 boundary")


def _child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUNBUFFERED"] = "1"
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


class RunCommandTool:
    name = "run_command"
    schema: JSONObject = {
        "name": "run_command",
        "description": "Run a temporarily authorized Python command in the workspace.",
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
    ) -> None:
        self._process_factory = (
            subprocess.Popen if process_factory is None else process_factory
        )
        self._tree_terminator = (
            _terminate_process_tree if tree_terminator is None else tree_terminator
        )

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        command, purpose = _validated_arguments(arguments)
        argv = parse_windows_command_line(command)
        workspace = _normalized_workspace(context)
        _authorize_temporary_command(argv, workspace)

        started = time.monotonic_ns()
        try:
            process = self._process_factory(
                argv,
                shell=False,
                cwd=workspace,
                env=_child_environment(),
                stdin=subprocess.DEVNULL,
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

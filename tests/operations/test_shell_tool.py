from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from coding_agent.engine.messages import ToolCall, ToolResultMetadata
from coding_agent.operations.safety import (
    AuthorizedCommand,
    CommandPolicy,
    CommandSource,
    SafetyCode,
    SafetyViolation,
)
from coding_agent.operations.tools.base import ExecutionContext, ToolArgumentError, ToolExecution
from coding_agent.operations.tools.registry import ToolRegistry
from coding_agent.operations.tools.shell import (
    AuthorizedCommandExecutor,
    InspectGitTool,
    RunCommandTool,
    parse_windows_command_line,
)


def _command_for_script(script: Path, *arguments: str) -> str:
    return subprocess.list2cmdline([sys.executable, script.name, *arguments])


def _execute_script(
    tmp_path: Path,
    source: str,
    *,
    arguments: tuple[str, ...] = (),
    purpose: str = "test",
    timeout: float = 60.0,
    tool: RunCommandTool | None = None,
):
    script = tmp_path / "script.py"
    script.write_text(source, encoding="utf-8")
    selected_tool = tool if tool is not None else RunCommandTool()
    return selected_tool.execute(
        {
            "command": _command_for_script(script, *arguments),
            "purpose": purpose,
        },
        ExecutionContext(tmp_path, command_timeout_seconds=timeout),
    )


def test_execution_context_command_timeout_contract(tmp_path: Path) -> None:
    assert ExecutionContext(tmp_path).command_timeout_seconds == 60.0
    assert (
        ExecutionContext(tmp_path, command_timeout_seconds=300).command_timeout_seconds
        == 300
    )

    for value in (
        True,
        0,
        -1,
        300.01,
        301,
        float("nan"),
        float("inf"),
        "60",
    ):
        with pytest.raises(
            ValueError,
            match=(
                "command_timeout_seconds must be greater than 0 and at most 300"
            ),
        ):
            ExecutionContext(  # type: ignore[arg-type]
                tmp_path,
                command_timeout_seconds=value,
            )


def test_run_command_schema_is_strict_and_timeout_is_not_model_facing() -> None:
    assert RunCommandTool.name == "run_command"
    assert RunCommandTool.schema == {
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


def test_run_command_schema_describes_single_process_verification_contract() -> None:
    description = RunCommandTool.schema["description"]

    assert isinstance(description, str)
    assert "single process" in description
    assert "python <workspace-relative-file.py>" in description
    assert "python -m pytest" in description
    assert 'purpose="verification"' in description
    assert "run_java_tests" in description
    assert "no shell operators" in description


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            {"purpose": "test"},
            "arguments must contain exactly: command, purpose",
        ),
        (
            {"command": "python", "purpose": "test", "timeout": 1},
            "arguments must contain exactly: command, purpose",
        ),
        (
            {"command": 7, "purpose": "test"},
            "command must be a non-empty string",
        ),
        (
            {"command": "   ", "purpose": "test"},
            "command must be a non-empty string",
        ),
        (
            {"command": "python", "purpose": "build"},
            "purpose must be inspect, test, or verification",
        ),
        (
            {"command": "python", "purpose": 1},
            "purpose must be inspect, test, or verification",
        ),
    ],
)
def test_run_command_rejects_invalid_arguments(
    tmp_path: Path,
    arguments: object,
    message: str,
) -> None:
    with pytest.raises(ToolArgumentError, match=message):
        RunCommandTool().execute(  # type: ignore[arg-type]
            arguments,
            ExecutionContext(tmp_path),
        )


def test_run_command_rejects_nul_with_safety_code(tmp_path: Path) -> None:
    with pytest.raises(SafetyViolation) as exc_info:
        RunCommandTool().execute(
            {"command": "python\x00x", "purpose": "test"},
            ExecutionContext(tmp_path),
        )
    assert exc_info.value.code is SafetyCode.SHELL_SYNTAX_DENIED


def test_run_command_registers_without_registry_changes(tmp_path: Path) -> None:
    registry = ToolRegistry([RunCommandTool()])
    assert registry.schemas == (RunCommandTool.schema,)

    result = registry.execute(
        ToolCall(
            call_id="bad-command",
            name="run_command",
            arguments={"purpose": "test"},
        ),
        ExecutionContext(tmp_path),
    )
    assert result.status == "rejected"
    assert result.error == (
        "invalid_arguments: run_command arguments must contain exactly: "
        "command, purpose"
    )


def test_inspect_git_has_exact_strict_schema() -> None:
    assert InspectGitTool.schema == {
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


def test_inspect_git_authorizes_fixed_purpose_and_uses_executor(
    tmp_path: Path,
) -> None:
    argv = ("C:\\trusted\\git.exe", "status", "--short")
    authorized = AuthorizedCommand(
        argv=argv,
        normalized_command="git status --short",
        purpose="inspect",
        source=CommandSource.MODEL,
    )

    class RecordingInspectionPolicy:
        workspace = tmp_path.resolve()

        def __init__(self) -> None:
            self.calls: list[tuple[object, CommandSource]] = []

        def authorize_git_inspection(
            self,
            command: object,
            *,
            source: CommandSource,
        ) -> AuthorizedCommand:
            self.calls.append((command, source))
            return authorized

    class RecordingAuthorizedExecutor:
        def __init__(self) -> None:
            self.calls: list[tuple[AuthorizedCommand, ExecutionContext]] = []

        def execute(
            self,
            command: AuthorizedCommand,
            context: ExecutionContext,
        ) -> ToolExecution:
            self.calls.append((command, context))
            return ToolExecution(output="delegated")

    policy = RecordingInspectionPolicy()
    executor = RecordingAuthorizedExecutor()
    result = InspectGitTool(
        authorized_executor=executor,  # type: ignore[arg-type]
        policy_factory=lambda workspace: policy,  # type: ignore[arg-type]
    ).execute(
        {"command": "git status --short"},
        ExecutionContext(tmp_path, command_timeout_seconds=17),
    )

    assert result.output == "delegated"
    assert policy.calls == [("git status --short", CommandSource.MODEL)]
    assert executor.calls == [
        (
            authorized,
            ExecutionContext(tmp_path.resolve(), command_timeout_seconds=17),
        )
    ]


@pytest.mark.parametrize(
    "arguments",
    [{}, {"command": ""}, {"command": 1}, {"command": "git status", "x": 1}],
)
def test_inspect_git_rejects_invalid_arguments_before_policy(
    arguments: object,
    tmp_path: Path,
) -> None:
    calls: list[object] = []

    class RecordingInspectionPolicy:
        workspace = tmp_path.resolve()

        def authorize_git_inspection(
            self,
            command: object,
            *,
            source: CommandSource,
        ) -> AuthorizedCommand:
            calls.append((command, source))
            raise AssertionError("policy must not be called")

    with pytest.raises(ToolArgumentError):
        InspectGitTool(
            policy_factory=lambda workspace: RecordingInspectionPolicy(),  # type: ignore[arg-type]
        ).execute(
            arguments,  # type: ignore[arg-type]
            ExecutionContext(tmp_path),
        )
    assert calls == []


def test_inspect_git_preserves_nonzero_exit_as_successful_execution(
    tmp_path: Path,
) -> None:
    authorized = AuthorizedCommand(
        argv=("C:\\trusted\\git.exe", "show", "missing"),
        normalized_command="git show missing",
        purpose="inspect",
        source=CommandSource.MODEL,
    )

    class RecordingInspectionPolicy:
        workspace = tmp_path.resolve()

        def authorize_git_inspection(
            self,
            command: object,
            *,
            source: CommandSource,
        ) -> AuthorizedCommand:
            return authorized

    class NonzeroExecutor:
        def execute(
            self,
            command: AuthorizedCommand,
            context: ExecutionContext,
        ) -> ToolExecution:
            return ToolExecution(
                output=json.dumps({"stdout": "", "stderr": "missing revision"}),
                metadata=ToolResultMetadata(exit_code=1),
            )

    result = InspectGitTool(
        authorized_executor=NonzeroExecutor(),  # type: ignore[arg-type]
        policy_factory=lambda workspace: RecordingInspectionPolicy(),  # type: ignore[arg-type]
    ).execute({"command": "git show missing"}, ExecutionContext(tmp_path))

    assert result.metadata.exit_code == 1
    assert json.loads(result.output or "")["stderr"] == "missing revision"


@pytest.mark.parametrize(
    "argv",
    [
        [sys.executable, "alpha beta", ""],
        [
            sys.executable,
            r"C:\path with spaces\script.py",
            r"ends-with-backslash\\",
        ],
        [sys.executable, "引数 雪", 'embedded"quote', r"a\\\"b"],
    ],
)
def test_parse_windows_command_line_round_trips_windows_arguments(
    argv: list[str],
) -> None:
    command = subprocess.list2cmdline(argv)
    assert parse_windows_command_line(command) == tuple(argv)


def test_parse_windows_command_line_handles_spaced_python_script_path() -> None:
    argv = [
        sys.executable,
        r"D:\workspace with spaces\test script.py",
        "value",
    ]
    assert parse_windows_command_line(subprocess.list2cmdline(argv)) == tuple(argv)


@pytest.mark.parametrize(
    "command",
    ["", "   ", '"unterminated', 'python "still open'],
)
def test_parse_windows_command_line_rejects_empty_or_unclosed_input(
    command: str,
) -> None:
    expected = "command could not be parsed"
    with pytest.raises(ToolArgumentError, match=expected):
        parse_windows_command_line(command)


def test_parse_windows_command_line_does_not_treat_escaped_quote_as_closing() -> None:
    command = subprocess.list2cmdline([sys.executable, 'a"b', r"c\\d"])
    assert parse_windows_command_line(command) == (
        sys.executable,
        'a"b',
        r"c\\d",
    )


def test_parse_windows_command_line_maps_native_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def native_failure(command: str, argc: object) -> None:
        return None

    monkeypatch.setattr(
        "coding_agent.operations.safety._COMMAND_LINE_TO_ARGV_W",
        native_failure,
    )
    with pytest.raises(
        ToolArgumentError,
        match="command could not be parsed",
    ):
        parse_windows_command_line("python.exe")


def test_run_command_executes_script_with_fixed_workspace_cwd(tmp_path: Path) -> None:
    execution = _execute_script(
        tmp_path,
        "from pathlib import Path\nprint(Path.cwd())\n",
        purpose="inspect",
    )
    payload = json.loads(execution.output or "")
    expected_payload = {
        "argv": [sys.executable, str(tmp_path / "script.py")],
        "cleanup_error": None,
        "purpose": "inspect",
        "stderr": "",
        "stdout": f"{tmp_path.resolve()}\r\n",
    }
    assert payload == expected_payload
    assert execution.output == json.dumps(
        expected_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert execution.metadata.exit_code == 0
    assert execution.metadata.timed_out is False
    assert execution.metadata.truncated is False
    assert execution.metadata.duration_ms >= 0
    assert execution.metadata.changed_paths == ()


def test_run_command_preserves_spaced_script_and_unicode_argument(
    tmp_path: Path,
) -> None:
    script = tmp_path / "script with spaces.py"
    script.write_text("import sys\nprint(sys.argv[1])\n", encoding="utf-8")
    execution = RunCommandTool().execute(
        {
            "command": _command_for_script(script, "雪 with space"),
            "purpose": "test",
        },
        ExecutionContext(tmp_path),
    )
    payload = json.loads(execution.output or "")
    assert payload["argv"] == [sys.executable, str(script), "雪 with space"]
    assert payload["stdout"] == "雪 with space\r\n"


def test_run_command_does_not_change_parent_cwd(tmp_path: Path) -> None:
    parent_cwd = Path.cwd()
    _execute_script(tmp_path, "print('ok')\n")
    assert Path.cwd() == parent_cwd


def test_run_command_does_not_pass_openai_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-child")
    execution = _execute_script(
        tmp_path,
        "import os\nprint(os.environ.get('OPENAI_API_KEY', '<absent>'))\n",
    )
    payload = json.loads(execution.output or "")
    assert payload["stdout"] == "<absent>\r\n"
    assert "must-not-reach-child" not in (execution.output or "")


def test_run_command_does_not_pass_chat_completions_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CHAT_COMPLETIONS_API_KEY",
        "chat-key-must-not-reach-child",
    )
    execution = _execute_script(
        tmp_path,
        "import os\n"
        "print(os.environ.get('CHAT_COMPLETIONS_API_KEY', '<absent>'))\n",
    )
    payload = json.loads(execution.output or "")
    if payload["stdout"] != "<absent>\r\n":
        pytest.fail("Chat Completions credential reached child process")
    assert "chat-key-must-not-reach-child" not in (execution.output or "")


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["cmd.exe", "/c", "echo", "unsafe"], SafetyCode.EXECUTABLE_DENIED),
        (["powershell.exe", "-Command", "Write-Output unsafe"], SafetyCode.EXECUTABLE_DENIED),
        ([sys.executable, "-c", "print('unsafe')"], SafetyCode.ARGUMENT_DENIED),
        ([sys.executable, "-"], SafetyCode.ARGUMENT_DENIED),
        ([sys.executable, "-m", "pip", "list"], SafetyCode.ARGUMENT_DENIED),
    ],
)
def test_temporary_boundary_rejects_nonapproved_entry_points(
    tmp_path: Path,
    argv: list[str],
    code: SafetyCode,
) -> None:
    with pytest.raises(SafetyViolation) as exc_info:
        RunCommandTool().execute(
            {
                "command": subprocess.list2cmdline(argv),
                "purpose": "verification",
            },
            ExecutionContext(tmp_path),
        )
    assert exc_info.value.code is code


def test_temporary_boundary_rejects_script_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print('unsafe')\n", encoding="utf-8")
    with pytest.raises(SafetyViolation) as exc_info:
        RunCommandTool().execute(
            {
                "command": _command_for_script(outside),
                "purpose": "inspect",
            },
            ExecutionContext(workspace),
        )
    assert exc_info.value.code is SafetyCode.PATH_NOT_FOUND


@pytest.mark.parametrize("module", ["pytest", "unittest"])
def test_temporary_boundary_accepts_only_approved_python_modules(
    tmp_path: Path,
    module: str,
) -> None:
    command = subprocess.list2cmdline([sys.executable, "-m", module, "--help"])
    execution = RunCommandTool().execute(
        {"command": command, "purpose": "inspect"},
        ExecutionContext(tmp_path),
    )
    assert execution.metadata.exit_code == 0


def test_nonzero_exit_is_successful_tool_execution(tmp_path: Path) -> None:
    script = tmp_path / "failure.py"
    script.write_text(
        "import sys\n"
        "print('out')\n"
        "print('err', file=sys.stderr)\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    registry = ToolRegistry([RunCommandTool()])
    result = registry.execute(
        ToolCall(
            call_id="nonzero",
            name="run_command",
            arguments={
                "command": _command_for_script(script),
                "purpose": "test",
            },
        ),
        ExecutionContext(tmp_path),
    )
    payload = json.loads(result.output or "")
    assert result.status == "ok"
    assert result.error is None
    assert result.metadata.exit_code == 7
    assert result.metadata.timed_out is False
    assert payload["stdout"] == "out\r\n"
    assert payload["stderr"] == "err\r\n"


def test_empty_and_separate_streams_are_stable(tmp_path: Path) -> None:
    empty = _execute_script(tmp_path, "pass\n")
    empty_payload = json.loads(empty.output or "")
    assert empty_payload["stdout"] == ""
    assert empty_payload["stderr"] == ""

    both = _execute_script(
        tmp_path,
        "import sys\n"
        "sys.stdout.write('no-newline')\n"
        "sys.stderr.write('错误')\n",
    )
    both_payload = json.loads(both.output or "")
    assert both_payload["stdout"] == "no-newline"
    assert both_payload["stderr"] == "错误"


def test_invalid_utf8_output_is_replaced_without_crashing(tmp_path: Path) -> None:
    execution = _execute_script(
        tmp_path,
        "import sys\nsys.stdout.buffer.write(b'\\xffok')\n",
    )
    payload = json.loads(execution.output or "")
    assert payload["stdout"] == "�ok"
    assert execution.metadata.exit_code == 0


def test_startup_os_errors_map_to_stable_registry_error(
    tmp_path: Path,
) -> None:
    script = tmp_path / "start.py"
    script.write_text("print('never')\n", encoding="utf-8")

    def denied(*args: object, **kwargs: object) -> object:
        raise PermissionError("localized and secret operating-system detail")

    registry = ToolRegistry([RunCommandTool(process_factory=denied)])
    result = registry.execute(
        ToolCall(
            call_id="start-error",
            name="run_command",
            arguments={
                "command": _command_for_script(script),
                "purpose": "test",
            },
        ),
        ExecutionContext(tmp_path),
    )
    assert result.status == "error"
    assert result.error == (
        "tool_execution_failed: CommandStartError: "
        "command could not be started: permission denied"
    )
    assert "localized" not in (result.error or "")
    assert result.output is None


def test_user_interrupt_is_not_swallowed(
    tmp_path: Path,
) -> None:
    script = tmp_path / "interrupt.py"
    script.write_text("print('never')\n", encoding="utf-8")

    def interrupted(*args: object, **kwargs: object) -> object:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        RunCommandTool(process_factory=interrupted).execute(
            {
                "command": _command_for_script(script),
                "purpose": "test",
            },
            ExecutionContext(tmp_path),
        )


def test_exactly_64_kib_per_stream_is_not_truncated(tmp_path: Path) -> None:
    execution = _execute_script(
        tmp_path,
        "import sys\n"
        "sys.stdout.buffer.write(b'o' * 65536)\n"
        "sys.stderr.buffer.write(b'e' * 65536)\n",
    )
    payload = json.loads(execution.output or "")
    assert len(payload["stdout"].encode("utf-8")) == 65536
    assert len(payload["stderr"].encode("utf-8")) == 65536
    assert execution.metadata.truncated is False


@pytest.mark.parametrize(
    ("stdout_size", "stderr_size", "expected_stdout", "expected_stderr"),
    [
        (65537, 0, 65536, 0),
        (0, 65537, 0, 65536),
        (131072, 131072, 65536, 65536),
    ],
)
def test_each_stream_keeps_only_its_first_64_kib(
    tmp_path: Path,
    stdout_size: int,
    stderr_size: int,
    expected_stdout: int,
    expected_stderr: int,
) -> None:
    execution = _execute_script(
        tmp_path,
        "import sys\n"
        f"sys.stdout.buffer.write(b'o' * {stdout_size})\n"
        f"sys.stderr.buffer.write(b'e' * {stderr_size})\n",
    )
    payload = json.loads(execution.output or "")
    assert payload["stdout"] == "o" * expected_stdout
    assert payload["stderr"] == "e" * expected_stderr
    assert execution.metadata.truncated is True


def test_truncation_omits_split_utf8_tail_without_replacement(
    tmp_path: Path,
) -> None:
    execution = _execute_script(
        tmp_path,
        "import sys\n"
        "sys.stdout.buffer.write((('a' * 65535) + 'é').encode('utf-8'))\n",
    )
    payload = json.loads(execution.output or "")
    assert payload["stdout"] == "a" * 65535
    assert "�" not in payload["stdout"]
    assert execution.metadata.truncated is True


def test_large_simultaneous_streams_are_drained_without_deadlock(
    tmp_path: Path,
) -> None:
    execution = _execute_script(
        tmp_path,
        "import sys\n"
        "chunk_out = b'o' * 8192\n"
        "chunk_err = b'e' * 8192\n"
        "for _ in range(64):\n"
        "    sys.stdout.buffer.write(chunk_out)\n"
        "    sys.stdout.buffer.flush()\n"
        "    sys.stderr.buffer.write(chunk_err)\n"
        "    sys.stderr.buffer.flush()\n",
        timeout=10,
    )
    payload = json.loads(execution.output or "")
    assert payload["stdout"] == "o" * 65536
    assert payload["stderr"] == "e" * 65536
    assert execution.metadata.exit_code == 0
    assert execution.metadata.timed_out is False
    assert execution.metadata.truncated is True


def test_short_wait_finishes_before_timeout_and_uses_monotonic_duration(
    tmp_path: Path,
) -> None:
    execution = _execute_script(
        tmp_path,
        "import time\ntime.sleep(0.15)\nprint('done')\n",
        timeout=2,
    )
    payload = json.loads(execution.output or "")
    assert payload["stdout"] == "done\r\n"
    assert execution.metadata.exit_code == 0
    assert execution.metadata.timed_out is False
    assert execution.metadata.duration_ms >= 100


def test_timeout_returns_partial_stdout_and_stderr(tmp_path: Path) -> None:
    execution = _execute_script(
        tmp_path,
        "import sys, time\n"
        "print('before-timeout-out', flush=True)\n"
        "print('before-timeout-err', file=sys.stderr, flush=True)\n"
        "time.sleep(1.0)\n",
        timeout=0.25,
    )
    payload = json.loads(execution.output or "")
    assert execution.metadata.timed_out is True
    assert execution.metadata.exit_code is None
    assert execution.metadata.duration_ms >= 200
    assert payload["stdout"] == "before-timeout-out\r\n"
    assert payload["stderr"] == "before-timeout-err\r\n"
    assert payload["cleanup_error"] is None


def test_timeout_retains_bounded_partial_output(tmp_path: Path) -> None:
    execution = _execute_script(
        tmp_path,
        "import sys, time\n"
        "sys.stdout.buffer.write(b'x' * 70000)\n"
        "sys.stdout.buffer.flush()\n"
        "time.sleep(1.0)\n",
        timeout=0.25,
    )
    payload = json.loads(execution.output or "")
    assert payload["stdout"] == "x" * 65536
    assert execution.metadata.timed_out is True
    assert execution.metadata.exit_code is None
    assert execution.metadata.truncated is True


def test_timeout_terminates_child_process_tree_before_child_side_effect(
    tmp_path: Path,
) -> None:
    assert os.name == "nt", "Task 7 process-tree acceptance requires Windows"
    marker = tmp_path / "orphan-marker.txt"
    child = tmp_path / "child.py"
    child.write_text(
        "from pathlib import Path\n"
        "import sys, time\n"
        "time.sleep(1.5)\n"
        "Path(sys.argv[1]).write_text('orphan survived', encoding='utf-8')\n",
        encoding="utf-8",
    )
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])\n"
        "print('child-started', flush=True)\n"
        "time.sleep(10)\n",
        encoding="utf-8",
    )

    execution = RunCommandTool().execute(
        {
            "command": _command_for_script(parent, child.name, marker.name),
            "purpose": "test",
        },
        ExecutionContext(tmp_path, command_timeout_seconds=0.35),
    )
    payload = json.loads(execution.output or "")
    assert execution.metadata.timed_out is True
    assert execution.metadata.exit_code is None
    assert payload["stdout"] == "child-started\r\n"
    assert payload["cleanup_error"] is None

    time.sleep(1.6)
    assert not marker.exists()


def test_cleanup_failure_does_not_overwrite_timeout_fact(tmp_path: Path) -> None:
    def cleanup_failed(process: subprocess.Popen[bytes]) -> str:
        return "simulated process-tree cleanup failure"

    execution = _execute_script(
        tmp_path,
        "import time\nprint('started', flush=True)\ntime.sleep(10)\n",
        timeout=0.2,
        tool=RunCommandTool(tree_terminator=cleanup_failed),
    )
    payload = json.loads(execution.output or "")
    assert execution.metadata.timed_out is True
    assert execution.metadata.exit_code is None
    assert payload["stdout"] == "started\r\n"
    assert payload["cleanup_error"] == "simulated process-tree cleanup failure"


def test_cleanup_os_error_returns_unavailable_without_losing_timeout(
    tmp_path: Path,
) -> None:
    def cleanup_unavailable(process: subprocess.Popen[bytes]) -> str | None:
        process.kill()
        raise OSError("localized cleanup detail")

    execution = _execute_script(
        tmp_path,
        "import time\nprint('started', flush=True)\ntime.sleep(10)\n",
        timeout=0.2,
        tool=RunCommandTool(tree_terminator=cleanup_unavailable),
    )
    payload = json.loads(execution.output or "")
    assert execution.metadata.timed_out is True
    assert execution.metadata.exit_code is None
    assert payload["cleanup_error"] == "process-tree cleanup unavailable"
    assert "localized" not in (execution.output or "")


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (FileNotFoundError("secret localized detail"), "executable unavailable"),
        (PermissionError("secret localized detail"), "permission denied"),
        (OSError("secret localized detail"), "operating system error"),
    ],
)
def test_process_factory_os_errors_have_stable_nonsecret_mapping(
    tmp_path: Path,
    exception: OSError,
    expected: str,
) -> None:
    script = tmp_path / "never-started.py"
    script.write_text("print('never')\n", encoding="utf-8")

    def failed_factory(
        *args: object,
        **kwargs: object,
    ) -> subprocess.Popen[bytes]:
        raise exception

    registry = ToolRegistry([RunCommandTool(process_factory=failed_factory)])
    result = registry.execute(
        ToolCall(
            call_id="failed-start",
            name="run_command",
            arguments={
                "command": _command_for_script(script),
                "purpose": "test",
            },
        ),
        ExecutionContext(tmp_path),
    )
    assert result.status == "error"
    assert result.error == (
        "tool_execution_failed: CommandStartError: "
        f"command could not be started: {expected}"
    )
    assert "secret" not in (result.error or "")


def test_process_launch_uses_shell_false_fixed_cwd_and_sanitized_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "not-for-child")
    monkeypatch.setenv("ChAt_Completions_Api_Key", "also-not-for-child")
    monkeypatch.setenv("MINICODEX_SAFE_TEST_VALUE", "preserved")
    script = tmp_path / "observed.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def recording_factory(
        argv: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.Popen[bytes]:
        observed["argv"] = argv
        observed.update(kwargs)
        return subprocess.Popen(argv, **kwargs)  # type: ignore[arg-type]

    execution = RunCommandTool(process_factory=recording_factory).execute(
        {"command": _command_for_script(script), "purpose": "inspect"},
        ExecutionContext(tmp_path),
    )
    assert execution.metadata.exit_code == 0
    assert observed["argv"] == (sys.executable, str(script))
    assert observed["shell"] is False
    assert observed["cwd"] == tmp_path.resolve()
    assert observed["stdin"] is subprocess.DEVNULL
    environment = observed["env"]
    assert isinstance(environment, dict)
    folded_environment = {
        key.casefold(): value for key, value in environment.items()
    }
    assert "openai_api_key" not in folded_environment
    if "chat_completions_api_key" in folded_environment:
        pytest.fail("Chat Completions credential reached captured child environment")
    assert folded_environment["minicodex_safe_test_value"] == "preserved"
    assert environment["PYTHONUTF8"] == "1"
    assert environment["PYTHONIOENCODING"] == "utf-8"
    assert environment["PYTHONUNBUFFERED"] == "1"


def test_authorized_executor_runs_exact_capability_without_policy(
    tmp_path: Path,
) -> None:
    script = tmp_path / "authorized.py"
    script.write_text("print('authorized')\n", encoding="utf-8")
    argv = (sys.executable, str(script.resolve()))
    authorized = AuthorizedCommand(
        argv=argv,
        normalized_command=subprocess.list2cmdline(argv),
        purpose="verification",
        source=CommandSource.USER_VERIFY,
    )
    observed: dict[str, object] = {}

    def recording_factory(
        received_argv: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.Popen[bytes]:
        observed["same_argv"] = received_argv is authorized.argv
        observed.update(kwargs)
        return subprocess.Popen(received_argv, **kwargs)  # type: ignore[arg-type]

    result = AuthorizedCommandExecutor(
        process_factory=recording_factory,
    ).execute(authorized, ExecutionContext(tmp_path))

    payload = json.loads(result.output or "")
    assert observed["same_argv"] is True
    assert observed["shell"] is False
    assert observed["cwd"] == tmp_path.resolve()
    assert payload["argv"] == list(argv)
    assert payload["purpose"] == "verification"
    assert payload["stdout"] == "authorized\r\n"
    assert result.metadata.exit_code == 0


def test_authorized_executor_passes_file_backed_stdin(
    tmp_path: Path,
) -> None:
    script = tmp_path / "read-stdin.py"
    script.write_text(
        "import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read())\n",
        encoding="utf-8",
    )
    input_path = tmp_path / "case.in"
    input_path.write_bytes("输入\n".encode("utf-8"))
    argv = (sys.executable, str(script))
    command = AuthorizedCommand(
        argv=argv,
        normalized_command=subprocess.list2cmdline(argv),
        purpose="test",
        source=CommandSource.MODEL,
    )
    with input_path.open("rb") as stdin_stream:
        result = AuthorizedCommandExecutor().execute(
            command,
            ExecutionContext(tmp_path),
            stdin_stream=stdin_stream,
        )
    payload = json.loads(result.output or "")
    assert result.metadata.exit_code == 0
    assert payload["stdout"] == "输入\n"


def test_run_command_delegates_to_authorized_executor_once(
    tmp_path: Path,
) -> None:
    argv = (sys.executable, "-m", "pytest", "-q")
    authorized = AuthorizedCommand(
        argv=argv,
        normalized_command=subprocess.list2cmdline(argv),
        purpose="verification",
        source=CommandSource.MODEL,
    )

    class RecordingPolicy:
        workspace = tmp_path.resolve()

        def authorize(
            self,
            command: object,
            *,
            purpose: str,
            source: CommandSource,
        ) -> AuthorizedCommand:
            assert command == "pytest -q"
            assert purpose == "verification"
            assert source is CommandSource.MODEL
            return authorized

    class RecordingExecutor:
        def __init__(self) -> None:
            self.calls: list[tuple[AuthorizedCommand, ExecutionContext]] = []

        def execute(
            self, command: AuthorizedCommand, context: ExecutionContext
        ) -> ToolExecution:
            self.calls.append((command, context))
            return ToolExecution(output="delegated")

    executor = RecordingExecutor()
    result = RunCommandTool(
        authorized_executor=executor,  # type: ignore[arg-type]
        policy_factory=lambda workspace: RecordingPolicy(),  # type: ignore[arg-type]
    ).execute(
        {"command": "pytest -q", "purpose": "verification"},
        ExecutionContext(tmp_path, command_timeout_seconds=17),
    )

    assert result.output == "delegated"
    assert len(executor.calls) == 1
    delegated, context = executor.calls[0]
    assert delegated is authorized
    assert context.workspace == tmp_path.resolve()
    assert context.command_timeout_seconds == 17


def test_authorized_executor_cannot_be_combined_with_low_level_seams() -> None:
    with pytest.raises(TypeError, match="cannot be combined"):
        RunCommandTool(
            authorized_executor=AuthorizedCommandExecutor(),
            process_factory=subprocess.Popen,
        )


def test_run_command_executes_only_policy_returned_argv(tmp_path: Path) -> None:
    requested = "this raw string must not be parsed or executed"
    safe_script = tmp_path / "safe.py"
    safe_script.write_text("print('safe')\n", encoding="utf-8")
    observed: dict[str, object] = {}

    class RecordingPolicy:
        workspace = tmp_path.resolve()

        def authorize(
            self,
            command: object,
            *,
            purpose: str,
            source: CommandSource,
        ) -> AuthorizedCommand:
            observed["command"] = command
            observed["purpose"] = purpose
            observed["source"] = source
            argv = (sys.executable, str(safe_script.resolve()))
            return AuthorizedCommand(
                argv=argv,
                normalized_command=subprocess.list2cmdline(argv),
                purpose=purpose,
                source=source,
            )

    execution = RunCommandTool(
        policy_factory=lambda workspace: RecordingPolicy(),  # type: ignore[arg-type]
    ).execute(
        {"command": requested, "purpose": "inspect"},
        ExecutionContext(tmp_path),
    )

    payload = json.loads(execution.output or "")
    assert observed == {
        "command": requested,
        "purpose": "inspect",
        "source": CommandSource.MODEL,
    }
    assert payload["argv"] == [sys.executable, str(safe_script.resolve())]
    assert payload["stdout"] == "safe\r\n"


def test_run_command_security_rejection_does_not_start_process(tmp_path: Path) -> None:
    started = False

    def forbidden_factory(*args: object, **kwargs: object) -> object:
        nonlocal started
        started = True
        raise AssertionError("process must not start")

    with pytest.raises(SafetyViolation) as exc_info:
        RunCommandTool(process_factory=forbidden_factory).execute(
            {"command": "powershell.exe -Command Get-Date", "purpose": "inspect"},
            ExecutionContext(tmp_path),
        )
    assert exc_info.value.code is SafetyCode.EXECUTABLE_DENIED
    assert started is False


def test_child_environment_removes_java_injection_variables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "CLASSPATH",
        "JAVA_TOOL_OPTIONS",
        "_JAVA_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "JDK_JAVAC_OPTIONS",
    ):
        monkeypatch.setenv(name, "workspace-injection-secret")
    observed: dict[str, object] = {}

    def recording_factory(
        argv: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.Popen[bytes]:
        observed.update(kwargs)
        return subprocess.Popen(argv, **kwargs)  # type: ignore[arg-type]

    _execute_script(
        tmp_path,
        "print('ok')\n",
        tool=RunCommandTool(process_factory=recording_factory),
    )
    environment = observed["env"]
    assert isinstance(environment, dict)
    folded = {key.casefold() for key in environment}
    assert folded.isdisjoint(
        {
            "classpath",
            "java_tool_options",
            "_java_options",
            "jdk_java_options",
            "jdk_javac_options",
        }
    )
    assert "workspace-injection-secret" not in repr(environment)


def test_child_environment_removes_policy_widening_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in {
        "OPENAI_API_KEY": "secret",
        "ChAt_Completions_Api_Key": "chat-secret",
        "PYTHONPATH": "outside",
        "PYTHONHOME": "outside",
        "PYTEST_ADDOPTS": "-p dangerous",
        "PYTEST_PLUGINS": "dangerous",
        "MYPYPATH": "outside",
        "MYPY_CONFIG_FILE": "outside.ini",
        "GIT_DIR": "outside",
        "GIT_WORK_TREE": "outside",
        "GIT_OBJECT_DIRECTORY": "outside",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": "outside",
        "GIT_EXTERNAL_DIFF": "dangerous.exe",
        "GIT_SSH": "dangerous.exe",
        "GIT_SSH_COMMAND": "dangerous.exe",
        "GIT_ASKPASS": "dangerous.exe",
        "SSH_ASKPASS": "dangerous.exe",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "alias.x",
        "GIT_CONFIG_VALUE_0": "!dangerous.exe",
    }.items():
        monkeypatch.setenv(key, value)
    script = tmp_path / "env.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def recording_factory(
        argv: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.Popen[bytes]:
        observed.update(kwargs)
        return subprocess.Popen(argv, **kwargs)  # type: ignore[arg-type]

    execution = RunCommandTool(process_factory=recording_factory).execute(
        {"command": _command_for_script(script), "purpose": "test"},
        ExecutionContext(tmp_path),
    )

    assert execution.metadata.exit_code == 0
    environment = observed["env"]
    assert isinstance(environment, dict)
    folded = {key.casefold() for key in environment}
    for denied in {
        "openai_api_key", "chat_completions_api_key", "pythonpath", "pythonhome", "pytest_addopts",
        "pytest_plugins", "mypypath", "mypy_config_file", "git_dir", "git_work_tree", "git_object_directory",
        "git_alternate_object_directories", "git_external_diff",
        "git_ssh", "git_ssh_command", "git_askpass", "ssh_askpass",
        "git_config_count", "git_config_key_0", "git_config_value_0",
    }:
        assert denied not in folded
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_CONFIG_GLOBAL"] == "NUL"
    assert environment["GIT_PAGER"] == "cat"
    assert environment["PAGER"] == "cat"
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["GIT_NO_LAZY_FETCH"] == "1"

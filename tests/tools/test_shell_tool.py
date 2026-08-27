from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from coding_agent.messages import ToolCall
from coding_agent.tools.base import ExecutionContext, ToolArgumentError
from coding_agent.tools.registry import ToolRegistry
from coding_agent.tools.shell import RunCommandTool, parse_windows_command_line


def _command_for_script(script: Path, *arguments: str) -> str:
    return subprocess.list2cmdline([sys.executable, str(script), *arguments])


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
            {"command": "python\x00x", "purpose": "test"},
            "command must not contain NUL",
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
    expected = (
        "command must be a non-empty string"
        if not command.strip()
        else "command contains an unclosed quote"
    )
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
        "coding_agent.tools.shell._COMMAND_LINE_TO_ARGV_W",
        native_failure,
    )
    with pytest.raises(
        ToolArgumentError,
        match="command could not be parsed by Windows",
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


@pytest.mark.parametrize(
    "argv",
    [
        ["cmd.exe", "/c", "echo", "unsafe"],
        ["powershell.exe", "-Command", "Write-Output unsafe"],
        [sys.executable, "-c", "print('unsafe')"],
        [sys.executable, "-"],
        [sys.executable, "-m", "pip", "list"],
    ],
)
def test_temporary_boundary_rejects_nonapproved_entry_points(
    tmp_path: Path,
    argv: list[str],
) -> None:
    with pytest.raises(
        ToolArgumentError,
        match="command is outside the temporary Task 7 boundary",
    ):
        RunCommandTool().execute(
            {
                "command": subprocess.list2cmdline(argv),
                "purpose": "verification",
            },
            ExecutionContext(tmp_path),
        )


def test_temporary_boundary_rejects_script_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print('unsafe')\n", encoding="utf-8")
    with pytest.raises(
        ToolArgumentError,
        match="command is outside the temporary Task 7 boundary",
    ):
        RunCommandTool().execute(
            {
                "command": _command_for_script(outside),
                "purpose": "inspect",
            },
            ExecutionContext(workspace),
        )


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
            "command": _command_for_script(parent, str(child), str(marker)),
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
    assert "OPENAI_API_KEY" not in environment
    assert environment["PYTHONUTF8"] == "1"
    assert environment["PYTHONIOENCODING"] == "utf-8"
    assert environment["PYTHONUNBUFFERED"] == "1"

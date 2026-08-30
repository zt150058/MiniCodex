from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import BinaryIO

import pytest

import coding_agent.tools.java as java_tool
from coding_agent.safety import (
    AuthorizedCommand,
    CommandSource,
    GuardedPath,
    JavaRuntime,
    SafetyCode,
    SafetyViolation,
)
from coding_agent.messages import ToolCall, ToolResultMetadata
from coding_agent.tools.base import (
    ExecutionContext,
    ToolArgumentError,
    ToolExecution,
)
from coding_agent.tools.java import RunJavaTestsTool
from coding_agent.tools.registry import ToolRegistry
from coding_agent.tools.shell import CommandStartError


def test_run_java_tests_schema_is_strict() -> None:
    assert RunJavaTestsTool.name == "run_java_tests"
    assert RunJavaTestsTool.schema == {
        "name": "run_java_tests",
        "description": (
            "Compile Java sources and run paired input/output tests in the "
            "workspace."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "source_root": {"type": "string", "minLength": 1},
                "main_class": {"type": "string", "minLength": 1},
                "tests_directory": {"type": "string", "minLength": 1},
                "purpose": {
                    "type": "string",
                    "enum": ["test", "verification"],
                },
            },
            "required": [
                "source_root",
                "main_class",
                "tests_directory",
                "purpose",
            ],
            "additionalProperties": False,
        },
    }


INVALID_ARGUMENTS = (
    ({}, "arguments must contain exactly"),
    (
        {
            "source_root": "src",
            "main_class": "Main",
            "tests_directory": "tests",
            "purpose": "test",
            "extra": 1,
        },
        "arguments must contain exactly",
    ),
    (
        {
            "source_root": "",
            "main_class": "Main",
            "tests_directory": "tests",
            "purpose": "test",
        },
        "source_root must be a non-empty string",
    ),
    (
        {
            "source_root": "src",
            "main_class": "9Main",
            "tests_directory": "tests",
            "purpose": "test",
        },
        "main_class must be a valid Java qualified name",
    ),
    (
        {
            "source_root": "src",
            "main_class": "Main",
            "tests_directory": "",
            "purpose": "test",
        },
        "tests_directory must be a non-empty string",
    ),
    (
        {
            "source_root": "src",
            "main_class": "Main",
            "tests_directory": "tests",
            "purpose": "inspect",
        },
        "purpose must be test or verification",
    ),
)


@pytest.mark.parametrize(("arguments", "message"), INVALID_ARGUMENTS)
def test_invalid_arguments_reject_before_discovery(
    tmp_path: Path,
    arguments: object,
    message: str,
) -> None:
    with pytest.raises(ToolArgumentError, match=message):
        RunJavaTestsTool().execute(  # type: ignore[arg-type]
            arguments,
            ExecutionContext(tmp_path),
        )


class RecordingAbortExecutor:
    def __init__(self) -> None:
        self.calls: list[
            tuple[AuthorizedCommand, ExecutionContext, bytes | None]
        ] = []

    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
        *,
        stdin_stream: BinaryIO | None = None,
    ) -> ToolExecution:
        payload = None if stdin_stream is None else stdin_stream.read()
        self.calls.append((command, context, payload))
        raise AssertionError("execution reached after valid discovery")


class FakeTemporaryDirectory:
    def __init__(self, path: Path, *, cleanup_error: bool = False) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.name = str(path)
        self.cleaned = False
        self.cleanup_calls = 0
        self.cleanup_error = cleanup_error

    def cleanup(self) -> None:
        self.cleanup_calls += 1
        self.cleaned = True
        if self.cleanup_error:
            raise OSError("private cleanup path")


def _runtime_factory(tmp_path: Path):
    runtime = tmp_path / "runtime"
    runtime.mkdir(exist_ok=True)
    javac = runtime / "javac.exe"
    java = runtime / "java.exe"
    javac.write_bytes(b"compiler")
    java.write_bytes(b"runtime")

    class FixedRuntimePolicy:
        def __init__(self, workspace: Path) -> None:
            self.workspace = workspace.resolve(strict=True)

        def resolve(self) -> JavaRuntime:
            return JavaRuntime(
                javac.resolve(strict=True),
                java.resolve(strict=True),
            )

    return FixedRuntimePolicy


def _discovery_tool(
    tmp_path: Path,
    workspace: Path,
) -> tuple[RunJavaTestsTool, RecordingAbortExecutor]:
    executor = RecordingAbortExecutor()
    temporary = workspace / ".coding-agent" / "java-tests" / "fake-run"
    return (
        RunJavaTestsTool(
            runtime_policy_factory=_runtime_factory(tmp_path),
            executor=executor,
            temporary_directory_factory=lambda _workspace: FakeTemporaryDirectory(
                temporary
            ),
        ),
        executor,
    )


def _valid_arguments() -> dict[str, object]:
    return {
        "source_root": "src",
        "main_class": "Main",
        "tests_directory": "tests",
        "purpose": "test",
    }


def _write_relative(workspace: Path, relative: str, content: bytes) -> None:
    path = workspace / Path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def write_java_fixture(
    workspace: Path,
    *,
    sources: dict[str, str],
    cases: dict[str, tuple[bytes, bytes]],
) -> None:
    for relative, source in sources.items():
        _write_relative(
            workspace,
            f"src/{relative}",
            source.encode("utf-8"),
        )
    for case_id, (input_bytes, expected_bytes) in cases.items():
        _write_relative(workspace, f"tests/{case_id}.in", input_bytes)
        _write_relative(workspace, f"tests/{case_id}.out", expected_bytes)


@dataclass(frozen=True)
class ChildOutcome:
    exit_code: int | None = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    truncated: bool = False
    cleanup_error: str | None = None
    elapsed: float = 1.0


class ManualClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class ScriptedJavaExecutor:
    def __init__(
        self,
        clock: ManualClock,
        outcomes: tuple[ChildOutcome, ...],
    ) -> None:
        self.clock = clock
        self.outcomes = list(outcomes)
        self.calls: list[
            tuple[AuthorizedCommand, ExecutionContext, bytes | None]
        ] = []

    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
        *,
        stdin_stream: BinaryIO | None = None,
    ) -> ToolExecution:
        stdin_bytes = None if stdin_stream is None else stdin_stream.read()
        self.calls.append((command, context, stdin_bytes))
        outcome = self.outcomes.pop(0)
        self.clock.value += outcome.elapsed
        return ToolExecution(
            output=json.dumps(
                {
                    "argv": list(command.argv),
                    "cleanup_error": outcome.cleanup_error,
                    "purpose": command.purpose,
                    "stderr": outcome.stderr,
                    "stdout": outcome.stdout,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            metadata=ToolResultMetadata(
                exit_code=outcome.exit_code,
                timed_out=outcome.timed_out,
                truncated=outcome.truncated,
                duration_ms=int(outcome.elapsed * 1000),
            ),
        )


def test_java_tool_compiles_runs_cases_in_order_and_returns_exact_success(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    write_java_fixture(
        workspace,
        sources={"z/Z.java": "class Z {}", "Main.java": "class Main {}"},
        cases={
            "b": (b"b\n", b"B\r\n"),
            "a": ("雪\n".encode(), "雪\n".encode()),
        },
    )
    clock = ManualClock()
    executor = ScriptedJavaExecutor(
        clock,
        (
            ChildOutcome(),
            ChildOutcome(stdout="雪\r\n"),
            ChildOutcome(stdout="B\n"),
        ),
    )
    tool = RunJavaTestsTool(
        runtime_policy_factory=_runtime_factory(tmp_path),
        executor=executor,
        clock=clock,
    )
    result = tool.execute(
        {
            "source_root": "src",
            "main_class": "Main",
            "tests_directory": "tests",
            "purpose": "verification",
        },
        ExecutionContext(workspace, command_timeout_seconds=120),
    )
    payload = json.loads(result.output or "")
    assert payload == {
        "case_count": 2,
        "failed_case": None,
        "passed_count": 2,
        "phase": "complete",
        "purpose": "verification",
        "safe_error_code": None,
        "source_count": 2,
        "stderr": "",
        "stdout": "",
    }
    assert result.metadata == ToolResultMetadata(
        exit_code=0,
        timed_out=False,
        truncated=False,
        duration_ms=3000,
    )
    compile_command, first_case, second_case = [
        call[0] for call in executor.calls
    ]
    assert compile_command.argv[1:7] == (
        "-encoding",
        "UTF-8",
        "-proc:none",
        "-classpath",
        compile_command.argv[5],
        "-d",
    )
    assert compile_command.argv[5] == compile_command.argv[7]
    assert str(workspace.resolve() / ".coding-agent" / "java-tests") in (
        compile_command.argv[5]
    )
    assert compile_command.argv[-2:] == (
        str(workspace.resolve() / "src" / "Main.java"),
        str(workspace.resolve() / "src" / "z" / "Z.java"),
    )
    assert first_case.argv[-1] == second_case.argv[-1] == "Main"
    assert executor.calls[1][2] == "雪\n".encode()
    assert executor.calls[2][2] == b"b\n"
    assert [call[1].command_timeout_seconds for call in executor.calls] == [
        60.0,
        59.0,
        58.0,
    ]


def _run_one_case(
    tmp_path: Path,
    outcomes: tuple[ChildOutcome, ...],
    *,
    expected: bytes = b"OK\n",
) -> tuple[ToolExecution, ScriptedJavaExecutor]:
    workspace = tmp_path / "workspace"
    write_java_fixture(
        workspace,
        sources={"Main.java": "class Main {}"},
        cases={"case": (b"input\n", expected)},
    )
    clock = ManualClock()
    executor = ScriptedJavaExecutor(clock, outcomes)
    result = RunJavaTestsTool(
        runtime_policy_factory=_runtime_factory(tmp_path),
        executor=executor,
        clock=clock,
    ).execute(
        {
            "source_root": "src",
            "main_class": "Main",
            "tests_directory": "tests",
            "purpose": "verification",
        },
        ExecutionContext(workspace, command_timeout_seconds=120),
    )
    return result, executor


@pytest.mark.parametrize(
    (
        "outcomes",
        "phase",
        "safe_error_code",
        "exit_code",
        "timed_out",
        "truncated",
        "failed_case",
        "call_count",
    ),
    (
        (
            (ChildOutcome(exit_code=2, stderr="compile error"),),
            "compile",
            "compile_failed",
            2,
            False,
            False,
            None,
            1,
        ),
        (
            (ChildOutcome(), ChildOutcome(exit_code=3, stderr="program error")),
            "case",
            "program_failed",
            3,
            False,
            False,
            "tests/case",
            2,
        ),
        (
            (ChildOutcome(), ChildOutcome(stdout="wrong\n")),
            "case",
            "output_mismatch",
            1,
            False,
            False,
            "tests/case",
            2,
        ),
        (
            (ChildOutcome(truncated=True),),
            "compile",
            "output_truncated",
            1,
            False,
            True,
            None,
            1,
        ),
        (
            (ChildOutcome(), ChildOutcome(stdout="OK\n", truncated=True)),
            "case",
            "output_truncated",
            1,
            False,
            True,
            "tests/case",
            2,
        ),
        (
            (ChildOutcome(exit_code=None, timed_out=True),),
            "compile",
            "suite_timed_out",
            None,
            True,
            False,
            None,
            1,
        ),
        (
            (
                ChildOutcome(),
                ChildOutcome(exit_code=None, timed_out=True),
            ),
            "case",
            "suite_timed_out",
            None,
            True,
            False,
            "tests/case",
            2,
        ),
        (
            (ChildOutcome(elapsed=60.0),),
            "case",
            "suite_timed_out",
            None,
            True,
            False,
            "tests/case",
            1,
        ),
    ),
)
def test_java_failure_matrix_compile_failed_program_failed_output_mismatch_output_truncated_suite_timed_out(
    tmp_path: Path,
    outcomes: tuple[ChildOutcome, ...],
    phase: str,
    safe_error_code: str,
    exit_code: int | None,
    timed_out: bool,
    truncated: bool,
    failed_case: str | None,
    call_count: int,
) -> None:
    result, executor = _run_one_case(tmp_path, outcomes)
    payload = json.loads(result.output or "")
    assert payload["phase"] == phase
    assert payload["safe_error_code"] == safe_error_code
    assert payload["failed_case"] == failed_case
    assert payload["passed_count"] == 0
    assert result.metadata.exit_code == exit_code
    assert result.metadata.timed_out is timed_out
    assert result.metadata.truncated is truncated
    assert len(executor.calls) == call_count


def test_java_comparison_only_normalizes_newlines(tmp_path: Path) -> None:
    passing, _ = _run_one_case(
        tmp_path,
        (ChildOutcome(), ChildOutcome(stdout="OK\n")),
        expected=b"OK\r\n",
    )
    assert json.loads(passing.output or "")["safe_error_code"] is None

    second_root = tmp_path / "second"
    second_root.mkdir()
    failing, _ = _run_one_case(
        second_root,
        (ChildOutcome(), ChildOutcome(stdout="OK \n")),
        expected=b"OK\n",
    )
    assert json.loads(failing.output or "")["safe_error_code"] == (
        "output_mismatch"
    )


def test_java_tool_reports_only_first_failed_case(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    write_java_fixture(
        workspace,
        sources={"Main.java": "class Main {}"},
        cases={
            "a": (b"a", b"A"),
            "b": (b"b", b"B"),
            "c": (b"c", b"C"),
        },
    )
    clock = ManualClock()
    executor = ScriptedJavaExecutor(
        clock,
        (
            ChildOutcome(),
            ChildOutcome(stdout="A"),
            ChildOutcome(stdout="wrong"),
        ),
    )
    result = RunJavaTestsTool(
        runtime_policy_factory=_runtime_factory(tmp_path),
        executor=executor,
        clock=clock,
    ).execute(_valid_arguments(), ExecutionContext(workspace))
    payload = json.loads(result.output or "")
    assert payload["failed_case"] == "tests/b"
    assert payload["passed_count"] == 1
    assert len(executor.calls) == 3


def test_java_tool_redacts_workspace_and_bounds_diagnostic(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    canonical = str(workspace.resolve())
    diagnostic = (
        canonical
        + "\n"
        + canonical.replace("\\", "/")
        + "\n"
        + canonical.swapcase()
        + "\n"
        + ("雪" * 10_000)
    )
    result, _ = _run_one_case(
        tmp_path,
        (ChildOutcome(exit_code=2, stdout=diagnostic, stderr=diagnostic),),
    )
    payload = json.loads(result.output or "")
    for field in ("stdout", "stderr"):
        value = payload[field]
        assert isinstance(value, str)
        assert len(value.encode("utf-8")) <= 8_192
        assert canonical.casefold() not in value.casefold()
        assert canonical.replace("\\", "/").casefold() not in value.casefold()


def test_exact_64k_output_passes_but_truncation_fails(tmp_path: Path) -> None:
    expected = b"x" * (64 * 1024)
    passing, _ = _run_one_case(
        tmp_path,
        (ChildOutcome(), ChildOutcome(stdout=expected.decode())),
        expected=expected,
    )
    assert json.loads(passing.output or "")["safe_error_code"] is None

    second_root = tmp_path / "truncated"
    second_root.mkdir()
    truncated, _ = _run_one_case(
        second_root,
        (
            ChildOutcome(),
            ChildOutcome(stdout=expected.decode(), truncated=True),
        ),
        expected=expected,
    )
    assert json.loads(truncated.output or "")["safe_error_code"] == (
        "output_truncated"
    )


def test_cleanup_failure_cannot_turn_an_otherwise_passed_suite_into_success(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    write_java_fixture(
        workspace,
        sources={"Main.java": "class Main {}"},
        cases={"case": (b"", b"OK\n")},
    )
    temporary = FakeTemporaryDirectory(
        workspace / ".coding-agent" / "java-tests" / "fake-run",
        cleanup_error=True,
    )
    clock = ManualClock()
    executor = ScriptedJavaExecutor(
        clock,
        (ChildOutcome(), ChildOutcome(stdout="OK\n")),
    )
    result = RunJavaTestsTool(
        runtime_policy_factory=_runtime_factory(tmp_path),
        executor=executor,
        clock=clock,
        temporary_directory_factory=lambda _workspace: temporary,
    ).execute(_valid_arguments(), ExecutionContext(workspace))
    payload = json.loads(result.output or "")
    assert payload["phase"] == "cleanup"
    assert payload["safe_error_code"] == "cleanup_failed"
    assert payload["stdout"] == payload["stderr"] == ""
    assert result.metadata.exit_code == 1
    assert result.metadata.timed_out is False
    assert "private cleanup path" not in (result.output or "")
    assert temporary.cleanup_calls == 1


@pytest.mark.parametrize(
    "error",
    (KeyboardInterrupt(), SystemExit(7)),
    ids=("keyboard_interrupt", "system_exit"),
)
def test_java_tool_cleans_up_and_propagates_base_exception(
    tmp_path: Path,
    error: BaseException,
) -> None:
    workspace = tmp_path / "workspace"
    write_java_fixture(
        workspace,
        sources={"Main.java": "class Main {}"},
        cases={"case": (b"", b"OK")},
    )
    temporary = FakeTemporaryDirectory(
        workspace / ".coding-agent" / "java-tests" / "fake-run"
    )

    class InterruptingExecutor:
        def execute(
            self,
            command: AuthorizedCommand,
            context: ExecutionContext,
            *,
            stdin_stream: BinaryIO | None = None,
        ) -> ToolExecution:
            raise error

    with pytest.raises(type(error)) as caught:
        RunJavaTestsTool(
            runtime_policy_factory=_runtime_factory(tmp_path),
            executor=InterruptingExecutor(),
            temporary_directory_factory=lambda _workspace: temporary,
        ).execute(_valid_arguments(), ExecutionContext(workspace))
    assert caught.value is error
    assert temporary.cleanup_calls == 1


def test_java_child_process_failed_is_stable_through_registry(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    write_java_fixture(
        workspace,
        sources={"Main.java": "class Main {}"},
        cases={"case": (b"", b"OK")},
    )

    class FailedExecutor:
        def execute(
            self,
            command: AuthorizedCommand,
            context: ExecutionContext,
            *,
            stdin_stream: BinaryIO | None = None,
        ) -> ToolExecution:
            raise CommandStartError("private path")

    registry = ToolRegistry(
        [
            RunJavaTestsTool(
                runtime_policy_factory=_runtime_factory(tmp_path),
                executor=FailedExecutor(),
            )
        ]
    )
    result = registry.execute(
        ToolCall(
            "java-start-failed",
            "run_java_tests",
            _valid_arguments(),
        ),
        ExecutionContext(workspace),
    )
    assert result.status == "error"
    assert result.output is None
    assert result.error is not None
    assert "JavaToolExecutionError: java child process failed" in result.error
    assert "private path" not in result.error


@pytest.mark.skipif(
    os.name != "nt"
    or shutil.which("javac.exe") is None
    or shutil.which("java.exe") is None,
    reason="trusted Windows JDK is unavailable",
)
def test_real_jdk_compiles_and_runs_a_temporary_black_box_suite(
    tmp_path: Path,
) -> None:
    write_java_fixture(
        tmp_path,
        sources={
            "Main.java": (
                "import java.io.*;\n"
                "public class Main {\n"
                "  public static void main(String[] args) throws Exception {\n"
                "    var reader = new BufferedReader(new InputStreamReader(System.in));\n"
                "    System.out.println(reader.readLine().toUpperCase());\n"
                "  }\n"
                "}\n"
            )
        },
        cases={"upper": (b"hello\n", b"HELLO\n")},
    )
    result = RunJavaTestsTool().execute(
        {
            "source_root": "src",
            "main_class": "Main",
            "tests_directory": "tests",
            "purpose": "test",
        },
        ExecutionContext(tmp_path, command_timeout_seconds=30),
    )
    payload = json.loads(result.output or "")
    assert result.metadata.exit_code == 0
    assert result.metadata.timed_out is False
    assert payload["phase"] == "complete"
    assert payload["passed_count"] == payload["case_count"] == 1
    assert list((tmp_path / ".coding-agent" / "java-tests").glob("run-*")) == []


@pytest.mark.parametrize(
    ("layout", "message"),
    (
        ({}, "at least one Java source is required"),
        ({"tests/t1.in": b"x\n"}, "orphan input or output fixture"),
        ({"tests/t1.out": b"x\n"}, "orphan input or output fixture"),
    ),
)
def test_discovery_rejects_incomplete_layout_before_execution(
    tmp_path: Path,
    layout: dict[str, bytes],
    message: str,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "tests").mkdir()
    if layout:
        _write_relative(workspace, "src/Main.java", b"class Main {}")
    for relative, content in layout.items():
        _write_relative(workspace, relative, content)
    tool, executor = _discovery_tool(tmp_path, workspace)
    with pytest.raises(ToolArgumentError, match=message):
        tool.execute(_valid_arguments(), ExecutionContext(workspace))
    assert executor.calls == []


def test_source_limit_rejects_the_501st_java_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "tests").mkdir()
    for index in range(501):
        _write_relative(
            workspace,
            f"src/S{index:03d}.java",
            b"class Source {}",
        )
    tool, executor = _discovery_tool(tmp_path, workspace)
    with pytest.raises(
        ToolArgumentError,
        match="at most 500 Java sources are allowed",
    ):
        tool.execute(_valid_arguments(), ExecutionContext(workspace))
    assert executor.calls == []


def test_case_limit_rejects_the_201st_complete_pair(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write_relative(workspace, "src/Main.java", b"class Main {}")
    for index in range(201):
        _write_relative(workspace, f"tests/c{index:03d}.in", b"")
        _write_relative(workspace, f"tests/c{index:03d}.out", b"")
    tool, executor = _discovery_tool(tmp_path, workspace)
    with pytest.raises(
        ToolArgumentError,
        match="at most 200 Java test cases are allowed",
    ):
        tool.execute(_valid_arguments(), ExecutionContext(workspace))
    assert executor.calls == []


def test_pair_case_files_rejects_casefold_duplicate_identifier(
    tmp_path: Path,
) -> None:
    inputs = (
        GuardedPath(tmp_path / "A.in", "A.in"),
        GuardedPath(tmp_path / "a.in", "a.in"),
    )
    with pytest.raises(
        ToolArgumentError,
        match="duplicate Java test case identifier",
    ):
        java_tool._pair_case_files(inputs, ())


@pytest.mark.parametrize(
    ("fixture", "size", "accepted"),
    (
        ("input", 256 * 1024, True),
        ("input", 256 * 1024 + 1, False),
        ("expected", 64 * 1024, True),
        ("expected", 64 * 1024 + 1, False),
    ),
)
def test_fixture_size_boundaries(
    tmp_path: Path,
    fixture: str,
    size: int,
    accepted: bool,
) -> None:
    workspace = tmp_path / "workspace"
    _write_relative(workspace, "src/Main.java", b"class Main {}")
    input_bytes = b"x" * (size if fixture == "input" else 1)
    expected_bytes = b"x" * (size if fixture == "expected" else 1)
    _write_relative(workspace, "tests/case.in", input_bytes)
    _write_relative(workspace, "tests/case.out", expected_bytes)
    tool, executor = _discovery_tool(tmp_path, workspace)
    if accepted:
        with pytest.raises(
            AssertionError,
            match="execution reached after valid discovery",
        ):
            tool.execute(_valid_arguments(), ExecutionContext(workspace))
        assert len(executor.calls) == 1
    else:
        with pytest.raises(ToolArgumentError, match="fixture is too large"):
            tool.execute(_valid_arguments(), ExecutionContext(workspace))
        assert executor.calls == []


def test_expected_utf8_is_validated_before_execution(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write_relative(workspace, "src/Main.java", b"class Main {}")
    _write_relative(workspace, "tests/case.in", b"")
    _write_relative(workspace, "tests/case.out", b"\xff")
    tool, executor = _discovery_tool(tmp_path, workspace)
    with pytest.raises(
        ToolArgumentError,
        match="expected output must be UTF-8 text",
    ):
        tool.execute(_valid_arguments(), ExecutionContext(workspace))
    assert executor.calls == []


def test_discovery_uses_casefolded_posix_stable_order(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    for relative in ("src/z/Z.java", "src/A.java", "src/b/B.java"):
        _write_relative(workspace, relative, b"class Source {}")
    for case in ("z/Last", "A/first"):
        _write_relative(workspace, f"tests/{case}.in", b"")
        _write_relative(workspace, f"tests/{case}.out", b"")
    tool, executor = _discovery_tool(tmp_path, workspace)
    with pytest.raises(AssertionError):
        tool.execute(_valid_arguments(), ExecutionContext(workspace))
    argv = executor.calls[0][0].argv
    sources = tuple(value for value in argv if value.casefold().endswith(".java"))
    assert sources == tuple(
        str((workspace / relative).resolve())
        for relative in ("src/A.java", "src/b/B.java", "src/z/Z.java")
    )


@pytest.mark.parametrize(
    "root",
    (
        r"C:\outside",
        "../outside",
        ".coding-agent",
        ".git",
    ),
)
def test_discovery_rejects_unsafe_source_roots(
    tmp_path: Path,
    root: str,
) -> None:
    workspace = tmp_path / "workspace"
    _write_relative(workspace, "src/Main.java", b"class Main {}")
    (workspace / "tests").mkdir()
    arguments = _valid_arguments()
    arguments["source_root"] = root
    tool, executor = _discovery_tool(tmp_path, workspace)
    with pytest.raises(SafetyViolation):
        tool.execute(arguments, ExecutionContext(workspace))
    assert executor.calls == []


def test_discovery_rejects_reparse_source_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "tests").mkdir()
    (outside / "Main.java").write_text("class Main {}", encoding="utf-8")
    try:
        os.symlink(outside, workspace / "src", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {type(exc).__name__}")
    tool, executor = _discovery_tool(tmp_path, workspace)
    with pytest.raises(SafetyViolation) as caught:
        tool.execute(_valid_arguments(), ExecutionContext(workspace))
    assert caught.value.code is SafetyCode.REPARSE_POINT_DENIED
    assert executor.calls == []


def test_discovery_skips_protected_and_reparse_children(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write_relative(workspace, "src/Main.java", b"class Main {}")
    _write_relative(workspace, "src/.git/Hidden.java", b"class Hidden {}")
    _write_relative(workspace, "tests/case.in", b"")
    _write_relative(workspace, "tests/case.out", b"")
    outside = tmp_path / "outside-sources"
    outside.mkdir()
    (outside / "Escape.java").write_text("class Escape {}", encoding="utf-8")
    try:
        os.symlink(outside, workspace / "src" / "linked", target_is_directory=True)
    except OSError:
        pass
    tool, executor = _discovery_tool(tmp_path, workspace)
    with pytest.raises(AssertionError):
        tool.execute(_valid_arguments(), ExecutionContext(workspace))
    compiler = executor.calls[0][0]
    rendered = subprocess.list2cmdline(compiler.argv)
    assert "Main.java" in rendered
    assert "Hidden.java" not in rendered
    assert "Escape.java" not in rendered

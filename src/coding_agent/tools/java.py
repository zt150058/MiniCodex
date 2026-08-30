from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
from typing import BinaryIO, Protocol

from coding_agent.messages import JSONObject, ToolResultMetadata
from coding_agent.safety import (
    AuthorizedCommand,
    CommandSource,
    GuardedPath,
    JavaRuntime,
    JavaRuntimePolicy,
    PathGuard,
    SafetyCode,
    SafetyViolation,
)
from coding_agent.tools.base import (
    ExecutionContext,
    ToolArgumentError,
    ToolExecution,
)
from coding_agent.tools.shell import AuthorizedCommandExecutor, CommandStartError


_ARGUMENT_NAMES = {"source_root", "main_class", "tests_directory", "purpose"}
_MAIN_CLASS = re.compile(
    r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*"
)
_SOURCE_LIMIT = 500
_CASE_LIMIT = 200
_INPUT_LIMIT_BYTES = 256 * 1024
_EXPECTED_LIMIT_BYTES = 64 * 1024
_DIAGNOSTIC_LIMIT_BYTES = 8 * 1024
_SUITE_TIMEOUT_SECONDS = 60.0
_SHELL_OUTPUT_KEYS = {"argv", "cleanup_error", "purpose", "stderr", "stdout"}
_JAVA_OUTPUT_KEYS = {
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
_COMPILE_FAILED = "compile_failed"
_PROGRAM_FAILED = "program_failed"
_OUTPUT_MISMATCH = "output_mismatch"
_OUTPUT_TRUNCATED = "output_truncated"
_SUITE_TIMED_OUT = "suite_timed_out"
_CLEANUP_FAILED = "cleanup_failed"


class JavaToolExecutionError(RuntimeError):
    """The trusted Java child result could not be used safely."""


class JavaCommandExecutor(Protocol):
    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
        *,
        stdin_stream: BinaryIO | None = None,
    ) -> ToolExecution: ...


class JavaTemporaryDirectory(Protocol):
    name: str

    def cleanup(self) -> None: ...


class JavaRuntimeResolver(Protocol):
    @property
    def workspace(self) -> Path: ...

    def resolve(self) -> JavaRuntime: ...


JavaRuntimePolicyFactory = Callable[[Path], JavaRuntimeResolver]
JavaTemporaryDirectoryFactory = Callable[[Path], JavaTemporaryDirectory]


@dataclass(frozen=True, slots=True)
class _JavaArguments:
    source_root: str
    main_class: str
    tests_directory: str
    purpose: str


@dataclass(frozen=True, slots=True)
class _JavaCase:
    case_id: str
    input_path: Path
    expected_path: Path


@dataclass(frozen=True, slots=True)
class _DecodedChild:
    stdout: str
    stderr: str
    cleanup_error: str | None


def _internal_reparse_point(path: Path) -> bool:
    try:
        result = os.lstat(path)
    except FileNotFoundError:
        return path.is_symlink()
    attributes = getattr(result, "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _ensure_internal_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        if _internal_reparse_point(path):
            raise SafetyViolation(
                SafetyCode.REPARSE_POINT_DENIED,
                "internal Java workspace is unavailable",
            )
        if not path.is_dir():
            raise SafetyViolation(
                SafetyCode.PATH_TYPE_MISMATCH,
                "internal Java workspace is unavailable",
            )
        return
    path.mkdir()
    if _internal_reparse_point(path) or not path.is_dir():
        raise SafetyViolation(
            SafetyCode.REPARSE_POINT_DENIED,
            "internal Java workspace is unavailable",
        )


def _create_temporary_directory(workspace: Path) -> JavaTemporaryDirectory:
    canonical = PathGuard(workspace).workspace
    internal = canonical / ".coding-agent"
    java_tests = internal / "java-tests"
    _ensure_internal_directory(internal)
    _ensure_internal_directory(java_tests)
    return tempfile.TemporaryDirectory(prefix="run-", dir=java_tests)


def _validated_arguments(arguments: object) -> _JavaArguments:
    if not isinstance(arguments, dict) or set(arguments) != _ARGUMENT_NAMES:
        raise ToolArgumentError(
            "run_java_tests arguments must contain exactly: "
            "source_root, main_class, tests_directory, purpose"
        )
    source_root = arguments["source_root"]
    if not isinstance(source_root, str) or not source_root.strip():
        raise ToolArgumentError("source_root must be a non-empty string")
    main_class = arguments["main_class"]
    if (
        not isinstance(main_class, str)
        or _MAIN_CLASS.fullmatch(main_class) is None
    ):
        raise ToolArgumentError("main_class must be a valid Java qualified name")
    tests_directory = arguments["tests_directory"]
    if not isinstance(tests_directory, str) or not tests_directory.strip():
        raise ToolArgumentError("tests_directory must be a non-empty string")
    purpose = arguments["purpose"]
    if not isinstance(purpose, str) or purpose not in {"test", "verification"}:
        raise ToolArgumentError("purpose must be test or verification")
    return _JavaArguments(
        source_root=source_root.strip(),
        main_class=main_class,
        tests_directory=tests_directory.strip(),
        purpose=purpose,
    )


def _guarded_files(
    paths: PathGuard,
    root: GuardedPath,
) -> tuple[GuardedPath, ...]:
    pending = [root.relative]
    files: list[GuardedPath] = []
    while pending:
        current = paths.existing_directory(pending.pop())
        entries = sorted(
            current.absolute.iterdir(),
            key=lambda item: (item.name.casefold(), item.name),
            reverse=True,
        )
        for entry in entries:
            relative = entry.relative_to(paths.workspace).as_posix()
            try:
                guarded = paths.existing_entry(relative)
            except SafetyViolation as exc:
                if exc.code in {
                    SafetyCode.PROTECTED_PATH,
                    SafetyCode.REPARSE_POINT_DENIED,
                }:
                    continue
                raise
            if guarded.absolute.is_dir():
                pending.append(guarded.relative)
            elif guarded.absolute.is_file():
                files.append(guarded)
    return tuple(
        sorted(
            files,
            key=lambda item: (item.relative.casefold(), item.relative),
        )
    )


def _discover_sources(
    paths: PathGuard,
    root: GuardedPath,
) -> tuple[GuardedPath, ...]:
    sources = tuple(
        item
        for item in _guarded_files(paths, root)
        if item.absolute.suffix.casefold() == ".java"
    )
    if not sources:
        raise ToolArgumentError("at least one Java source is required")
    if len(sources) > _SOURCE_LIMIT:
        raise ToolArgumentError("at most 500 Java sources are allowed")
    return sources


def _pair_case_files(
    inputs: tuple[GuardedPath, ...],
    outputs: tuple[GuardedPath, ...],
) -> tuple[_JavaCase, ...]:
    def indexed(
        items: tuple[GuardedPath, ...],
    ) -> dict[str, GuardedPath]:
        result: dict[str, GuardedPath] = {}
        for item in items:
            key = item.relative.rsplit(".", 1)[0].casefold()
            if key in result:
                raise ToolArgumentError(
                    "duplicate Java test case identifier"
                )
            result[key] = item
        return result

    input_by_id = indexed(inputs)
    output_by_id = indexed(outputs)
    if input_by_id.keys() != output_by_id.keys():
        raise ToolArgumentError("orphan input or output fixture")
    if not input_by_id:
        raise ToolArgumentError("at least one Java test case is required")
    if len(input_by_id) > _CASE_LIMIT:
        raise ToolArgumentError("at most 200 Java test cases are allowed")

    cases: list[_JavaCase] = []
    for key, input_path in input_by_id.items():
        expected_path = output_by_id[key]
        if input_path.absolute.stat().st_size > _INPUT_LIMIT_BYTES:
            raise ToolArgumentError("fixture is too large")
        if expected_path.absolute.stat().st_size > _EXPECTED_LIMIT_BYTES:
            raise ToolArgumentError("fixture is too large")
        try:
            expected_path.absolute.read_bytes().decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ToolArgumentError(
                "expected output must be UTF-8 text"
            ) from exc
        case_id = input_path.relative.rsplit(".", 1)[0]
        cases.append(
            _JavaCase(
                case_id=case_id,
                input_path=input_path.absolute,
                expected_path=expected_path.absolute,
            )
        )
    return tuple(
        sorted(cases, key=lambda item: (item.case_id.casefold(), item.case_id))
    )


def _discover_cases(
    paths: PathGuard,
    root: GuardedPath,
) -> tuple[_JavaCase, ...]:
    files = _guarded_files(paths, root)
    inputs = tuple(
        item for item in files if item.absolute.suffix.casefold() == ".in"
    )
    outputs = tuple(
        item for item in files if item.absolute.suffix.casefold() == ".out"
    )
    return _pair_case_files(inputs, outputs)


def _decode_child(
    execution: ToolExecution,
    command: AuthorizedCommand,
) -> _DecodedChild:
    try:
        payload = json.loads(execution.output or "")
    except (TypeError, json.JSONDecodeError):
        raise JavaToolExecutionError("java child result is invalid") from None
    if not isinstance(payload, dict) or set(payload) != _SHELL_OUTPUT_KEYS:
        raise JavaToolExecutionError("java child result is invalid")
    cleanup_error = payload["cleanup_error"]
    if (
        payload["argv"] != list(command.argv)
        or payload["purpose"] != command.purpose
        or not isinstance(payload["stdout"], str)
        or not isinstance(payload["stderr"], str)
        or (cleanup_error is not None and not isinstance(cleanup_error, str))
    ):
        raise JavaToolExecutionError("java child result is invalid")
    return _DecodedChild(
        stdout=payload["stdout"],
        stderr=payload["stderr"],
        cleanup_error=cleanup_error,
    )


def _bounded_diagnostic(text: str, workspace: Path) -> str:
    rendered = text
    workspace_forms = {
        str(workspace),
        str(workspace).replace("\\", "/"),
    }
    for form in sorted(workspace_forms, key=len, reverse=True):
        rendered = re.sub(
            re.escape(form),
            "<workspace>",
            rendered,
            flags=re.IGNORECASE,
        )
    encoded = rendered.encode("utf-8")[:_DIAGNOSTIC_LIMIT_BYTES]
    return encoded.decode("utf-8", errors="ignore")


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _execution_output(
    *,
    source_count: int,
    case_count: int,
    passed_count: int,
    failed_case: str | None,
    phase: str,
    purpose: str,
    safe_error_code: str | None,
    stdout: str,
    stderr: str,
    exit_code: int | None,
    timed_out: bool,
    truncated: bool,
    duration_ms: int,
) -> ToolExecution:
    payload: JSONObject = {
        "case_count": case_count,
        "failed_case": failed_case,
        "passed_count": passed_count,
        "phase": phase,
        "purpose": purpose,
        "safe_error_code": safe_error_code,
        "source_count": source_count,
        "stderr": stderr,
        "stdout": stdout,
    }
    if set(payload) != _JAVA_OUTPUT_KEYS:
        raise RuntimeError("Java output keys are invalid")
    return ToolExecution(
        output=json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
        metadata=ToolResultMetadata(
            exit_code=exit_code,
            timed_out=timed_out,
            truncated=truncated,
            duration_ms=duration_ms,
        ),
    )


def _suite_timeout_execution(
    *,
    arguments: _JavaArguments,
    source_count: int,
    case_count: int,
    passed_count: int,
    phase: str,
    failed_case: str | None,
    started: float,
    finished: float,
) -> ToolExecution:
    return _execution_output(
        source_count=source_count,
        case_count=case_count,
        passed_count=passed_count,
        failed_case=failed_case,
        phase=phase,
        purpose=arguments.purpose,
        safe_error_code="suite_timed_out",
        stdout="",
        stderr="",
        exit_code=None,
        timed_out=True,
        truncated=False,
        duration_ms=max(0, int((finished - started) * 1000)),
    )


def _cleanup_failure_execution(outcome: ToolExecution) -> ToolExecution:
    try:
        payload = json.loads(outcome.output or "")
    except (TypeError, json.JSONDecodeError):
        raise JavaToolExecutionError("java child result is invalid") from None
    if not isinstance(payload, dict) or set(payload) != _JAVA_OUTPUT_KEYS:
        raise JavaToolExecutionError("java child result is invalid")
    integer_fields = ("source_count", "case_count", "passed_count")
    if any(
        isinstance(payload[name], bool) or not isinstance(payload[name], int)
        for name in integer_fields
    ) or not isinstance(payload["purpose"], str):
        raise JavaToolExecutionError("java child result is invalid")
    return _execution_output(
        source_count=payload["source_count"],
        case_count=payload["case_count"],
        passed_count=payload["passed_count"],
        failed_case=None,
        phase="cleanup",
        purpose=payload["purpose"],
        safe_error_code=_CLEANUP_FAILED,
        stdout="",
        stderr="",
        exit_code=1,
        timed_out=False,
        truncated=outcome.metadata.truncated,
        duration_ms=outcome.metadata.duration_ms,
    )


class RunJavaTestsTool:
    name = "run_java_tests"
    schema: JSONObject = {
        "name": "run_java_tests",
        "description": (
            "Compile Java sources and run paired input/output tests in the workspace."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "source_root": {"type": "string", "minLength": 1},
                "main_class": {"type": "string", "minLength": 1},
                "tests_directory": {"type": "string", "minLength": 1},
                "purpose": {"type": "string", "enum": ["test", "verification"]},
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

    def __init__(
        self,
        *,
        runtime_policy_factory: JavaRuntimePolicyFactory | None = None,
        executor: JavaCommandExecutor | None = None,
        clock: Callable[[], float] = time.monotonic,
        temporary_directory_factory: JavaTemporaryDirectoryFactory | None = None,
    ) -> None:
        if runtime_policy_factory is not None and not callable(
            runtime_policy_factory
        ):
            raise TypeError("runtime_policy_factory must be callable")
        if executor is not None and not callable(getattr(executor, "execute", None)):
            raise TypeError("executor must provide execute")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if temporary_directory_factory is not None and not callable(
            temporary_directory_factory
        ):
            raise TypeError("temporary_directory_factory must be callable")
        self._runtime_policy_factory = (
            JavaRuntimePolicy
            if runtime_policy_factory is None
            else runtime_policy_factory
        )
        self._executor = (
            AuthorizedCommandExecutor() if executor is None else executor
        )
        self._clock = clock
        self._temporary_directory_factory = (
            _create_temporary_directory
            if temporary_directory_factory is None
            else temporary_directory_factory
        )

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        validated = _validated_arguments(arguments)
        if not isinstance(context, ExecutionContext):
            raise TypeError("context must be ExecutionContext")
        return self._execute(validated, context)

    def _execute(
        self,
        arguments: _JavaArguments,
        context: ExecutionContext,
    ) -> ToolExecution:
        paths = PathGuard(context.workspace)
        source_root = paths.existing_directory(arguments.source_root)
        tests_root = paths.existing_directory(arguments.tests_directory)
        sources = _discover_sources(paths, source_root)
        cases = _discover_cases(paths, tests_root)
        runtime_policy = self._runtime_policy_factory(paths.workspace)
        if runtime_policy.workspace != paths.workspace:
            raise JavaToolExecutionError("Java runtime workspace is invalid")
        runtime = runtime_policy.resolve()
        temporary = self._temporary_directory_factory(paths.workspace)
        cleanup_failed = False
        try:
            build_directory = Path(temporary.name).resolve(strict=True)
            outcome = self._run_suite(
                arguments=arguments,
                paths=paths,
                runtime=runtime,
                sources=sources,
                cases=cases,
                build_directory=build_directory,
                context=context,
            )
        finally:
            try:
                temporary.cleanup()
            except OSError:
                cleanup_failed = True
        if (
            cleanup_failed
            and outcome.metadata.exit_code == 0
            and not outcome.metadata.timed_out
        ):
            return _cleanup_failure_execution(outcome)
        return outcome

    def _execute_child(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
        *,
        stdin_stream: BinaryIO | None = None,
    ) -> tuple[ToolExecution, _DecodedChild]:
        try:
            execution = self._executor.execute(
                command,
                context,
                stdin_stream=stdin_stream,
            )
            return execution, _decode_child(execution, command)
        except (CommandStartError, JavaToolExecutionError, OSError, RuntimeError):
            raise JavaToolExecutionError(
                "java child process failed"
            ) from None

    def _run_suite(
        self,
        *,
        arguments: _JavaArguments,
        paths: PathGuard,
        runtime: JavaRuntime,
        sources: tuple[GuardedPath, ...],
        cases: tuple[_JavaCase, ...],
        build_directory: Path,
        context: ExecutionContext,
    ) -> ToolExecution:
        started = self._clock()
        deadline = started + min(
            context.command_timeout_seconds,
            _SUITE_TIMEOUT_SECONDS,
        )
        passed_count = 0

        def command_for(argv: tuple[str, ...]) -> AuthorizedCommand:
            return AuthorizedCommand(
                argv=argv,
                normalized_command=subprocess.list2cmdline(argv),
                purpose=arguments.purpose,
                source=CommandSource.MODEL,
            )

        compile_argv = (
            str(runtime.javac),
            "-encoding",
            "UTF-8",
            "-proc:none",
            "-classpath",
            str(build_directory),
            "-d",
            str(build_directory),
            *(str(source.absolute) for source in sources),
        )
        compile_command = command_for(compile_argv)
        remaining = deadline - self._clock()
        if remaining <= 0:
            return _suite_timeout_execution(
                arguments=arguments,
                source_count=len(sources),
                case_count=len(cases),
                passed_count=0,
                phase="compile",
                failed_case=None,
                started=started,
                finished=self._clock(),
            )
        compile_execution, compile_child = self._execute_child(
            compile_command,
            ExecutionContext(paths.workspace, command_timeout_seconds=remaining),
        )
        compile_metadata = compile_execution.metadata
        if compile_metadata.timed_out:
            return _suite_timeout_execution(
                arguments=arguments,
                source_count=len(sources),
                case_count=len(cases),
                passed_count=0,
                phase="compile",
                failed_case=None,
                started=started,
                finished=self._clock(),
            )
        if compile_child.cleanup_error is not None:
            return _execution_output(
                source_count=len(sources),
                case_count=len(cases),
                passed_count=0,
                failed_case=None,
                phase="cleanup",
                purpose=arguments.purpose,
                safe_error_code=_CLEANUP_FAILED,
                stdout="",
                stderr="",
                exit_code=(
                    compile_metadata.exit_code
                    if compile_metadata.exit_code not in {None, 0}
                    else 1
                ),
                timed_out=False,
                truncated=compile_metadata.truncated,
                duration_ms=max(
                    0,
                    int((self._clock() - started) * 1000),
                ),
            )
        if compile_metadata.truncated:
            return _execution_output(
                source_count=len(sources),
                case_count=len(cases),
                passed_count=0,
                failed_case=None,
                phase="compile",
                purpose=arguments.purpose,
                safe_error_code=_OUTPUT_TRUNCATED,
                stdout=_bounded_diagnostic(compile_child.stdout, paths.workspace),
                stderr=_bounded_diagnostic(compile_child.stderr, paths.workspace),
                exit_code=1,
                timed_out=False,
                truncated=True,
                duration_ms=max(
                    0,
                    int((self._clock() - started) * 1000),
                ),
            )
        if compile_metadata.exit_code != 0:
            return _execution_output(
                source_count=len(sources),
                case_count=len(cases),
                passed_count=0,
                failed_case=None,
                phase="compile",
                purpose=arguments.purpose,
                safe_error_code=_COMPILE_FAILED,
                stdout=_bounded_diagnostic(compile_child.stdout, paths.workspace),
                stderr=_bounded_diagnostic(compile_child.stderr, paths.workspace),
                exit_code=compile_metadata.exit_code,
                timed_out=False,
                truncated=False,
                duration_ms=max(
                    0,
                    int((self._clock() - started) * 1000),
                ),
            )

        case_argv = (
            str(runtime.java),
            "-cp",
            str(build_directory),
            arguments.main_class,
        )
        case_command = command_for(case_argv)
        for case in cases:
            remaining = deadline - self._clock()
            if remaining <= 0:
                return _suite_timeout_execution(
                    arguments=arguments,
                    source_count=len(sources),
                    case_count=len(cases),
                    passed_count=passed_count,
                    phase="case",
                    failed_case=case.case_id,
                    started=started,
                    finished=self._clock(),
                )
            with case.input_path.open("rb") as stdin_stream:
                case_execution, case_child = self._execute_child(
                    case_command,
                    ExecutionContext(
                        paths.workspace,
                        command_timeout_seconds=remaining,
                    ),
                    stdin_stream=stdin_stream,
                )
            case_metadata = case_execution.metadata
            if case_metadata.timed_out:
                return _suite_timeout_execution(
                    arguments=arguments,
                    source_count=len(sources),
                    case_count=len(cases),
                    passed_count=passed_count,
                    phase="case",
                    failed_case=case.case_id,
                    started=started,
                    finished=self._clock(),
                )
            if case_child.cleanup_error is not None:
                return _execution_output(
                    source_count=len(sources),
                    case_count=len(cases),
                    passed_count=passed_count,
                    failed_case=case.case_id,
                    phase="cleanup",
                    purpose=arguments.purpose,
                    safe_error_code=_CLEANUP_FAILED,
                    stdout="",
                    stderr="",
                    exit_code=(
                        case_metadata.exit_code
                        if case_metadata.exit_code not in {None, 0}
                        else 1
                    ),
                    timed_out=False,
                    truncated=case_metadata.truncated,
                    duration_ms=max(
                        0,
                        int((self._clock() - started) * 1000),
                    ),
                )
            if case_metadata.truncated:
                return _execution_output(
                    source_count=len(sources),
                    case_count=len(cases),
                    passed_count=passed_count,
                    failed_case=case.case_id,
                    phase="case",
                    purpose=arguments.purpose,
                    safe_error_code=_OUTPUT_TRUNCATED,
                    stdout=_bounded_diagnostic(case_child.stdout, paths.workspace),
                    stderr=_bounded_diagnostic(case_child.stderr, paths.workspace),
                    exit_code=1,
                    timed_out=False,
                    truncated=True,
                    duration_ms=max(
                        0,
                        int((self._clock() - started) * 1000),
                    ),
                )
            if case_metadata.exit_code != 0:
                return _execution_output(
                    source_count=len(sources),
                    case_count=len(cases),
                    passed_count=passed_count,
                    failed_case=case.case_id,
                    phase="case",
                    purpose=arguments.purpose,
                    safe_error_code=_PROGRAM_FAILED,
                    stdout=_bounded_diagnostic(case_child.stdout, paths.workspace),
                    stderr=_bounded_diagnostic(case_child.stderr, paths.workspace),
                    exit_code=case_metadata.exit_code,
                    timed_out=False,
                    truncated=False,
                    duration_ms=max(
                        0,
                        int((self._clock() - started) * 1000),
                    ),
                )
            expected = case.expected_path.read_text(encoding="utf-8")
            if _normalize_newlines(case_child.stdout) != _normalize_newlines(
                expected
            ):
                expected_excerpt = _bounded_diagnostic(expected, paths.workspace)
                actual_excerpt = _bounded_diagnostic(
                    case_child.stdout,
                    paths.workspace,
                )
                mismatch = (
                    f"case {case.case_id}: expected "
                    f"{json.dumps(expected_excerpt, ensure_ascii=False)} but got "
                    f"{json.dumps(actual_excerpt, ensure_ascii=False)}"
                )
                return _execution_output(
                    source_count=len(sources),
                    case_count=len(cases),
                    passed_count=passed_count,
                    failed_case=case.case_id,
                    phase="case",
                    purpose=arguments.purpose,
                    safe_error_code=_OUTPUT_MISMATCH,
                    stdout=actual_excerpt,
                    stderr=_bounded_diagnostic(mismatch, paths.workspace),
                    exit_code=1,
                    timed_out=False,
                    truncated=False,
                    duration_ms=max(
                        0,
                        int((self._clock() - started) * 1000),
                    ),
                )
            passed_count += 1

        return _execution_output(
            source_count=len(sources),
            case_count=len(cases),
            passed_count=passed_count,
            failed_case=None,
            phase="complete",
            purpose=arguments.purpose,
            safe_error_code=None,
            stdout="",
            stderr="",
            exit_code=0,
            timed_out=False,
            truncated=False,
            duration_ms=max(0, int((self._clock() - started) * 1000)),
        )

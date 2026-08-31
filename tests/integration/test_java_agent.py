from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import BinaryIO

from coding_agent.engine.agent import AgentRunner
from coding_agent.engine.context import ContextManager
from coding_agent.engine.messages import (
    ModelResponse,
    ToolCall,
    ToolResult,
    ToolResultMetadata,
)
from coding_agent.engine.model import FakeModelClient
from coding_agent.operations.safety import AuthorizedCommand, JavaRuntime
from coding_agent.engine.state import AgentStatus, VerificationStatus
from coding_agent.engine.termination import TerminationPolicy
from coding_agent.operations.tools.base import ExecutionContext, ToolExecution
from coding_agent.operations.tools.filesystem import WriteFileTool
from coding_agent.operations.tools.java import RunJavaTestsTool
from coding_agent.operations.tools.registry import ToolRegistry
from coding_agent.engine.verification import VerificationGate


class ManualClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class PassingJavaExecutor:
    def __init__(self, clock: ManualClock) -> None:
        self.clock = clock
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
        self.clock.value += 1.0
        stdout = "" if stdin_bytes is None else "HELLO\n"
        return ToolExecution(
            output=json.dumps(
                {
                    "argv": list(command.argv),
                    "cleanup_error": None,
                    "purpose": command.purpose,
                    "stderr": "",
                    "stdout": stdout,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            metadata=ToolResultMetadata(exit_code=0, duration_ms=1_000),
        )


class TemporaryDirectory:
    def __init__(self, path: Path) -> None:
        path.mkdir(parents=True)
        self.name = str(path)

    def cleanup(self) -> None:
        shutil.rmtree(self.name)


def fixed_runtime_factory(tmp_path: Path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
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


def test_agent_creates_readme_and_accepts_fresh_java_verification(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "Main.java"
    source.parent.mkdir(parents=True)
    source.write_text("public class Main {}\n", encoding="utf-8")
    tests = workspace / "tests"
    tests.mkdir()
    (tests / "t1.in").write_bytes(b"hello\n")
    (tests / "t1.out").write_bytes(b"HELLO\n")
    model = FakeModelClient(
        (
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "write-readme",
                        "write_file",
                        {
                            "path": "README.md",
                            "content": (
                                "# Demo\n\nA Java stdin/stdout project.\n"
                            ),
                        },
                    ),
                )
            ),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "verify-java",
                        "run_java_tests",
                        {
                            "source_root": "src",
                            "main_class": "Main",
                            "tests_directory": "tests",
                            "purpose": "verification",
                        },
                    ),
                )
            ),
            ModelResponse(text="README created and the Java fixture passed."),
        )
    )
    clock = ManualClock()
    java_executor = PassingJavaExecutor(clock)
    execution_context = ExecutionContext(workspace)
    temporary_root = (
        workspace / ".coding-agent" / "java-tests" / "run-integration"
    )
    java_tool = RunJavaTestsTool(
        runtime_policy_factory=fixed_runtime_factory(tmp_path),
        executor=java_executor,
        clock=clock,
        temporary_directory_factory=lambda _workspace: TemporaryDirectory(
            temporary_root
        ),
    )
    registry = ToolRegistry((WriteFileTool(), java_tool))
    runner = AgentRunner(
        model_client=model,
        tool_registry=registry,
        execution_context=execution_context,
        context_manager=ContextManager(model_client=model),
        termination_policy=TerminationPolicy(),
        clock=clock,
        verification_gate=VerificationGate(
            required_command=None,
            execution_context=execution_context,
            executor=java_executor,
        ),
    )

    state = runner.run("Create a README and verify the Java fixture.")

    assert state.status is AgentStatus.SUCCESS
    assert state.mutation_index == 1
    assert state.validation_index == 1
    assert state.verification_status is VerificationStatus.PASSED
    assert state.modified_paths == ("README.md",)
    assert (workspace / "README.md").read_text(encoding="utf-8").startswith(
        "# Demo"
    )
    assert [request.tool_schemas[-1]["name"] for request in model.requests] == [
        "run_java_tests",
        "run_java_tests",
        "run_java_tests",
    ]
    java_results = tuple(
        message
        for message in state.messages
        if isinstance(message, ToolResult)
        and message.tool_name == "run_java_tests"
    )
    assert len(java_results) == 1
    assert java_results[0].call_id == "verify-java"
    assert java_results[0].status == "ok"
    assert java_executor.calls[0][0].argv[0].endswith("javac.exe")
    assert java_executor.calls[1][2] == b"hello\n"
    assert list(
        (workspace / ".coding-agent" / "java-tests").glob("run-*")
    ) == []

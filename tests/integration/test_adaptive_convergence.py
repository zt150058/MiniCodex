from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
from pathlib import Path
import subprocess
import sys

import pytest

from coding_agent.engine.agent import AgentRunner
from coding_agent.engine.budget import BudgetProfile
from coding_agent.engine.context import ContextLimits, ContextManager
from coding_agent.engine.messages import (
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResult,
    ToolResultMetadata,
)
from coding_agent.engine.model import FakeModelClient
from coding_agent.engine.progress import AgentPhase
from coding_agent.engine.run_mode import RunMode
from coding_agent.operations.safety import AuthorizedCommand, CommandSource
from coding_agent.engine.state import (
    AgentState,
    AgentStatus,
    TerminationReason,
    VerificationStatus,
)
from coding_agent.engine.termination import TerminationLimits, TerminationPolicy
from coding_agent.operations.tools.base import ExecutionContext, ToolExecution
from coding_agent.operations.tools.filesystem import ListDirectoryTool, ReadFileTool, WriteFileTool
from coding_agent.operations.tools.registry import ToolRegistry
from coding_agent.operations.tools.shell import RunCommandTool
from coding_agent.engine.verification import VerificationGate


def _read_call(index: int) -> ToolCall:
    return ToolCall(
        f"read-{index}",
        "read_file",
        {
            "path": f"source-{index}.txt",
            "start_line": 1,
            "end_line": None,
        },
    )


def _create_source_files(workspace: Path, count: int = 12) -> None:
    for index in range(count):
        (workspace / f"source-{index}.txt").write_text(
            f"source {index}\n",
            encoding="utf-8",
        )


def _required_verification() -> AuthorizedCommand:
    argv = (sys.executable, "-m", "pytest", "-q")
    return AuthorizedCommand(
        argv=argv,
        normalized_command=subprocess.list2cmdline(argv),
        purpose="verification",
        source=CommandSource.USER_VERIFY,
    )


def _passing_verification_execution() -> ToolExecution:
    command = _required_verification()
    return ToolExecution(
        output=json.dumps(
            {
                "argv": list(command.argv),
                "cleanup_error": None,
                "purpose": "verification",
                "stderr": "",
                "stdout": "1 passed",
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        metadata=ToolResultMetadata(exit_code=0, duration_ms=1),
    )


@dataclass(slots=True)
class _FakeVerificationExecutor:
    queued: deque[ToolExecution]
    calls: list[tuple[AuthorizedCommand, ExecutionContext]] = field(
        default_factory=list
    )

    def __init__(self, *queued: ToolExecution) -> None:
        self.queued = deque(queued)
        self.calls = []

    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
    ) -> ToolExecution:
        self.calls.append((command, context))
        return self.queued.popleft()


def _verification_gate(
    workspace: Path,
) -> tuple[VerificationGate, _FakeVerificationExecutor]:
    executor = _FakeVerificationExecutor(_passing_verification_execution())
    return (
        VerificationGate(
            required_command=_required_verification(),
            execution_context=ExecutionContext(workspace),
            executor=executor,
        ),
        executor,
    )


def _profile_policy(profile: BudgetProfile) -> TerminationPolicy:
    return TerminationPolicy(TerminationLimits.for_profile(profile))


def _read_batch(prefix: str, indexes: range) -> ModelResponse:
    return ModelResponse(
        tool_calls=tuple(
            ToolCall(
                f"{prefix}-{index}",
                "read_file",
                {
                    "path": f"source-{index}.txt",
                    "start_line": 1,
                    "end_line": None,
                },
            )
            for index in indexes
        )
    )


def _fenced_summary_response() -> ModelResponse:
    payload = {
        "goal": "create a project README",
        "established_facts": ["ten representative source files were inspected"],
        "files_examined": [f"source-{index}.txt" for index in range(10)],
        "changes_made": [],
        "commands_and_results": [],
        "unresolved_errors": [],
        "open_issues": ["README.md still needs to be created"],
        "verification_state": {},
        "avoid_repeating": ["do not reread source-0 through source-9"],
    }
    return ModelResponse(
        text="```json\n" + json.dumps(payload, sort_keys=True) + "\n```"
    )


def _realistic_readme_runner(
    workspace: Path,
    *,
    final_decision: ModelResponse,
) -> tuple[AgentRunner, FakeModelClient, _FakeVerificationExecutor]:
    large_body = "representative project fact\n" * 120
    for index in range(10):
        (workspace / f"source-{index}.txt").write_text(
            f"component {index}\n{large_body}",
            encoding="utf-8",
        )
    responses = (
        _read_batch("initial-a", range(0, 5)),
        _read_batch("initial-b", range(5, 10)),
        _fenced_summary_response(),
        _read_batch("duplicate", range(0, 5)),
        _read_batch("rejected", range(0, 5)),
        final_decision,
        ModelResponse(text="README.md was created and verified."),
    )
    model = FakeModelClient(responses)
    gate, executor = _verification_gate(workspace)
    runner = AgentRunner(
        model_client=model,
        tool_registry=ToolRegistry((ReadFileTool(), WriteFileTool())),
        execution_context=ExecutionContext(workspace),
        context_manager=ContextManager(model_client=model),
        termination_policy=_profile_policy(BudgetProfile.DEEP),
        verification_gate=gate,
        budget_profile=BudgetProfile.DEEP,
    )
    return runner, model, executor


def test_batched_compressed_readme_converges_after_duplicate_exploration(
    tmp_path: Path,
) -> None:
    write = ModelResponse(
        tool_calls=(
            ToolCall(
                "create-readme",
                "write_file",
                {
                    "path": "README.md",
                    "content": "# Example project\n\nA bounded project overview.\n",
                },
            ),
        )
    )
    runner, model, executor = _realistic_readme_runner(
        tmp_path,
        final_decision=write,
    )
    state = runner.run("create README.md that introduces the whole project")

    assert state.status is AgentStatus.SUCCESS
    assert state.termination_reason is None
    assert state.mutation_index == state.validation_index == 1
    assert (tmp_path / "README.md").read_text(encoding="utf-8").startswith("# ")
    assert state.summary_model_call_count == 1
    assert state.progress.exploration.context_compacted is True
    assert state.progress.exploration.duplicate_only_turns == 1
    rejected = [
        item
        for item in state.messages
        if isinstance(item, ToolResult)
        and item.error is not None
        and item.error.startswith("agent_rejected:decision_required")
    ]
    assert len(rejected) == 5
    assert len(executor.calls) == 1
    assert state.main_model_call_count == 6


def test_duplicate_decision_exhaustion_stops_before_another_main_request(
    tmp_path: Path,
) -> None:
    runner, model, executor = _realistic_readme_runner(
        tmp_path,
        final_decision=_read_batch("still-reading", range(0, 5)),
    )

    state = runner.run("inspect forever without making progress")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.NO_PROGRESS
    assert state.progress.decision_attempts_without_progress == 2
    assert state.mutation_index == 0
    assert not (tmp_path / "README.md").exists()
    assert len(executor.calls) == 0
    assert state.main_model_call_count == 5
    assert state.summary_model_call_count == 1
    assert len(model.requests) == 6


def test_read_only_project_explanation_finishes_before_standard_budget(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\n',
        encoding="utf-8",
    )
    model = FakeModelClient(
        (
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "list-project",
                        "list_directory",
                        {
                            "path": ".",
                            "recursive": False,
                            "max_depth": 1,
                            "max_entries": 20,
                        },
                    ),
                )
            ),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "read-project",
                        "read_file",
                        {
                            "path": "pyproject.toml",
                            "start_line": 1,
                            "end_line": None,
                        },
                    ),
                )
            ),
            ModelResponse(text="This is an example Python project."),
        )
    )
    runner = AgentRunner(
        model_client=model,
        tool_registry=ToolRegistry((ListDirectoryTool(), ReadFileTool())),
        execution_context=ExecutionContext(tmp_path),
        termination_policy=_profile_policy(BudgetProfile.STANDARD),
        run_mode=RunMode.READ_ONLY,
        budget_profile=BudgetProfile.STANDARD,
    )

    state = runner.run("Read this project and explain what it does")

    assert state.status is AgentStatus.ANSWERED
    assert state.termination_reason is None
    assert state.main_model_call_count < 24
    assert state.progress.phase is AgentPhase.FINISH
    assert len(model.requests) == state.main_model_call_count == 3


def _run_readme_gate_fixture(
    workspace: Path,
    profile: BudgetProfile,
    final_read_batches: int,
) -> tuple[AgentState, FakeModelClient, _FakeVerificationExecutor]:
    initial_reads = 4 if profile is BudgetProfile.STANDARD else 6
    total_sources = initial_reads + final_read_batches + 1
    _create_source_files(workspace, total_sources)
    responses: list[ModelResponse] = [
        ModelResponse(tool_calls=(_read_call(index),))
        for index in range(initial_reads + final_read_batches)
    ]
    blocked_index = initial_reads + final_read_batches
    responses.extend(
        (
            ModelResponse(
                tool_calls=(
                    _read_call(blocked_index),
                    ToolCall(
                        "create-readme",
                        "write_file",
                        {
                            "path": "README.md",
                            "content": "# Example project\n\nA bounded fixture.\n",
                        },
                    ),
                )
            ),
            ModelResponse(text="README.md was created and verified."),
        )
    )
    model = FakeModelClient(tuple(responses))
    gate, executor = _verification_gate(workspace)
    runner = AgentRunner(
        model_client=model,
        tool_registry=ToolRegistry((ReadFileTool(), WriteFileTool())),
        execution_context=ExecutionContext(workspace),
        context_manager=ContextManager(
            model_client=model,
            limits=ContextLimits(
                max_history_items=64,
                compression_trigger_items=60,
                compression_target_items=40,
            ),
        ),
        termination_policy=_profile_policy(profile),
        verification_gate=gate,
        budget_profile=profile,
    )
    return runner.run("create README.md"), model, executor


@pytest.mark.parametrize(
    ("profile", "final_read_batches"),
    [
        (BudgetProfile.STANDARD, 1),
        (BudgetProfile.DEEP, 2),
    ],
)
def test_readme_discovery_gate_blocks_extra_read_then_allows_write(
    tmp_path: Path,
    profile: BudgetProfile,
    final_read_batches: int,
) -> None:
    state, model, executor = _run_readme_gate_fixture(
        tmp_path,
        profile,
        final_read_batches,
    )

    blocked = [
        item
        for item in state.messages
        if isinstance(item, ToolResult)
        and item.error is not None
        and item.error.startswith("agent_rejected:decision_required")
    ]
    assert len(blocked) == 1
    assert state.status is AgentStatus.SUCCESS
    assert state.mutation_index == 1
    assert state.validation_index == 1
    assert (tmp_path / "README.md").is_file()
    assert state.main_model_call_count == len(model.requests)
    assert len(executor.calls) == 1


def test_invalid_first_summary_uses_local_fallback_and_main_work_continues(
    tmp_path: Path,
) -> None:
    (tmp_path / "source.txt").write_text("broken\n", encoding="utf-8")
    gate, executor = _verification_gate(tmp_path)
    model = FakeModelClient(
        (
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "read-source",
                        "read_file",
                        {
                            "path": "source.txt",
                            "start_line": 1,
                            "end_line": None,
                        },
                    ),
                )
            ),
            ModelResponse(text="invalid summary"),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "write-result",
                        "write_file",
                        {"path": "result.txt", "content": "repaired\n"},
                    ),
                )
            ),
            ModelResponse(text="Repair completed and verified."),
        )
    )
    runner = AgentRunner(
        model_client=model,
        tool_registry=ToolRegistry((ReadFileTool(), WriteFileTool())),
        execution_context=ExecutionContext(tmp_path),
        context_manager=ContextManager(
            model_client=model,
            limits=ContextLimits(
                max_history_items=5,
                recent_turns=1,
                compression_trigger_items=3,
                compression_target_items=2,
            ),
        ),
        termination_policy=_profile_policy(BudgetProfile.STANDARD),
        verification_gate=gate,
        budget_profile=BudgetProfile.STANDARD,
    )

    state = runner.run("repair project")

    summary_requests = [request for request in model.requests if not request.tool_schemas]
    assert state.status is AgentStatus.SUCCESS
    assert state.summary_model_call_count == 1
    assert state.summary_fallback_latched is True
    assert state.main_model_call_count >= 2
    assert len(summary_requests) == 1
    assert len(executor.calls) == 1
    assert (tmp_path / "result.txt").read_text(encoding="utf-8") == "repaired\n"


def test_post_checkpoint_exploration_stops_as_no_progress_not_main_limit(
    tmp_path: Path,
) -> None:
    _create_source_files(tmp_path)
    profile = BudgetProfile.STANDARD
    initial_reads = 4
    final_read_batches = 1
    blocked_index = initial_reads + final_read_batches
    model = FakeModelClient(
        tuple(
            ModelResponse(tool_calls=(_read_call(index),))
            for index in range(blocked_index + 2)
        )
    )
    runner = AgentRunner(
        model_client=model,
        tool_registry=ToolRegistry((ReadFileTool(),)),
        execution_context=ExecutionContext(tmp_path),
        termination_policy=_profile_policy(profile),
        budget_profile=profile,
    )

    state = runner.run("inspect indefinitely")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.NO_PROGRESS
    assert state.main_model_call_count < 24
    assert state.main_model_call_count == len(model.requests)
    blocked = [
        item
        for item in state.messages
        if isinstance(item, ToolResult)
        and item.call_id in {
            f"read-{blocked_index}",
            f"read-{blocked_index + 1}",
        }
    ]
    assert len(blocked) == 2
    assert all(
        item.error is not None
        and item.error.startswith("agent_rejected:decision_required")
        for item in blocked
    )
    assert len(model.requests) == blocked_index + 2


def test_python_write_recovers_from_rejected_commands_and_verifies(
    tmp_path: Path,
) -> None:
    model = FakeModelClient(
        (
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "write",
                        "write_file",
                        {
                            "path": "task_manager.py",
                            "content": "print('verified')\n",
                        },
                    ),
                )
            ),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "shell-syntax",
                        "run_command",
                        {
                            "command": "python task_manager.py && echo done",
                            "purpose": "verification",
                        },
                    ),
                )
            ),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "wrong-launcher",
                        "run_command",
                        {
                            "command": "python3 task_manager.py",
                            "purpose": "verification",
                        },
                    ),
                )
            ),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "valid-command",
                        "run_command",
                        {
                            "command": "python task_manager.py",
                            "purpose": "verification",
                        },
                    ),
                )
            ),
            ModelResponse(text="task_manager.py was created and verified."),
        )
    )
    context = ExecutionContext(tmp_path)
    runner = AgentRunner(
        model_client=model,
        tool_registry=ToolRegistry((WriteFileTool(), RunCommandTool())),
        execution_context=context,
        verification_gate=VerificationGate(
            required_command=None,
            execution_context=context,
        ),
        termination_policy=_profile_policy(BudgetProfile.STANDARD),
        budget_profile=BudgetProfile.STANDARD,
    )

    state = runner.run("write any Python file and verify it")

    assert state.status is AgentStatus.SUCCESS
    assert state.mutation_index == state.validation_index == 1
    assert state.verification_attempt_count == 2
    assert state.verification_status is VerificationStatus.PASSED
    assert state.last_verification is not None
    assert state.last_verification.source is CommandSource.MODEL
    assert "already passed deterministic local integrity" in (
        model.requests[1].instructions or ""
    )
    assert state.consecutive_safety_rejections == 0
    assert len(model.requests) == 5


def test_python_write_with_exhausted_recovery_keeps_unverified_change(
    tmp_path: Path,
) -> None:
    invalid_commands = (
        "python task_manager.py && echo done",
        "python3 task_manager.py",
        "py task_manager.py",
    )
    responses: list[ModelResponse] = [
        ModelResponse(
            tool_calls=(
                ToolCall(
                    "write",
                    "write_file",
                    {
                        "path": "task_manager.py",
                        "content": "print('not yet verified')\n",
                    },
                ),
            )
        )
    ]
    responses.extend(
        ModelResponse(
            tool_calls=(
                ToolCall(
                    f"invalid-{index}",
                    "run_command",
                    {"command": command, "purpose": "verification"},
                ),
            )
        )
        for index, command in enumerate(invalid_commands, start=1)
    )
    model = FakeModelClient(tuple(responses))
    context = ExecutionContext(tmp_path)
    executor = _FakeVerificationExecutor()
    runner = AgentRunner(
        model_client=model,
        tool_registry=ToolRegistry((WriteFileTool(), RunCommandTool())),
        execution_context=context,
        verification_gate=VerificationGate(
            required_command=_required_verification(),
            execution_context=context,
            executor=executor,
        ),
        termination_policy=_profile_policy(BudgetProfile.STANDARD),
        budget_profile=BudgetProfile.STANDARD,
    )

    state = runner.run("write any Python file and verify it")

    assert (tmp_path / "task_manager.py").is_file()
    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.CHANGES_UNVERIFIED
    assert state.modified_paths == ("task_manager.py",)
    assert state.mutation_index == 1
    assert state.validation_index is None
    assert state.verification_attempt_count == 0
    assert state.verification_status is VerificationStatus.STALE
    assert executor.calls == []
    assert len(model.requests) == 4

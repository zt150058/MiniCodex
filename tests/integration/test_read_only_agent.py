from __future__ import annotations

from pathlib import Path

from coding_agent.agent import AgentRunner
from coding_agent.messages import ModelResponse, ToolCall
from coding_agent.model import FakeModelClient
from coding_agent.run_mode import RunMode
from coding_agent.state import AgentStatus, VerificationStatus
from coding_agent.tools.base import ExecutionContext
from coding_agent.tools.filesystem import ListDirectoryTool, ReadFileTool
from coding_agent.tools.registry import ToolRegistry


def test_project_inspection_answers_before_logical_call_limit(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\n',
        encoding="utf-8",
    )
    scripted = (
        ModelResponse(
            tool_calls=(
                ToolCall(
                    "call-list",
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
                    "call-readme",
                    "read_file",
                    {"path": "README.md", "start_line": 1, "end_line": None},
                ),
            )
        ),
        ModelResponse(
            tool_calls=(
                ToolCall(
                    "call-pyproject",
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
        *(ModelResponse(text="sentinel must remain unused") for _ in range(9)),
    )
    model = FakeModelClient(scripted)
    runner = AgentRunner(
        model_client=model,
        tool_registry=ToolRegistry((ListDirectoryTool(), ReadFileTool())),
        execution_context=ExecutionContext(tmp_path),
        run_mode=RunMode.READ_ONLY,
    )

    state = runner.run("Read this workspace and explain the project")

    assert state.status is AgentStatus.ANSWERED
    assert state.completion_text == "This is an example Python project."
    assert state.logical_model_call_count == 4
    assert len(model.requests) == 4
    assert state.mutation_index == 0
    assert state.modified_paths == ()
    assert state.verification_status is VerificationStatus.NOT_RUN
    assert state.verification_attempt_count == 0

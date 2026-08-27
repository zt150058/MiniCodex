from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess
import sys

import pytest

from coding_agent.agent import AgentRunner
from coding_agent.messages import (
    AssistantMessage,
    JSONObject,
    ModelResponse,
    ToolCall,
    ToolResult,
    ToolResultMetadata,
    UserMessage,
)
from coding_agent.model import FakeModelClient
from coding_agent.state import AgentStatus
from coding_agent.tools.base import (
    ExecutionContext,
    ToolArgumentError,
    ToolExecution,
)
from coding_agent.tools.registry import ToolRegistry


def _runner(
    tmp_path: Path,
    responses: tuple[ModelResponse, ...],
    *,
    tools: tuple[object, ...] = (),
    max_rounds: int = 12,
) -> tuple[AgentRunner, FakeModelClient]:
    client = FakeModelClient(responses)
    runner = AgentRunner(
        model_client=client,
        tool_registry=ToolRegistry(tools),  # type: ignore[arg-type]
        execution_context=ExecutionContext(workspace=tmp_path),
        max_rounds=max_rounds,
    )
    return runner, client


@dataclass(slots=True)
class EchoTool:
    executed: list[tuple[str, Path]] = field(default_factory=list)
    name: str = field(default="echo", init=False)
    schema: JSONObject = field(
        default_factory=lambda: {
            "name": "echo",
            "description": "Return the supplied text.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
        },
        init=False,
    )

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        if set(arguments) != {"text"} or not isinstance(arguments["text"], str):
            raise ToolArgumentError("text must be the only argument and be a string")
        text = arguments["text"]
        self.executed.append((text, context.workspace))
        return ToolExecution(output=text)


@dataclass(slots=True)
class ExplodingTool:
    name: str = field(default="explode", init=False)
    schema: JSONObject = field(
        default_factory=lambda: {
            "name": "explode",
            "description": "Raise a deterministic test exception.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
        init=False,
    )

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        raise RuntimeError("boom")


def test_direct_text_returns_completion_candidate(tmp_path: Path) -> None:
    runner, client = _runner(
        tmp_path,
        (ModelResponse(text="implementation is ready for verification"),),
    )

    state = runner.run("repair the failing test")

    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert state.completion_text == "implementation is ready for verification"
    assert state.failure_reason is None
    assert state.task == "repair the failing test"
    assert state.current_goal == "repair the failing test"
    assert state.open_issues == ()
    assert state.model_call_count == 1
    assert state.tool_call_count == 0
    assert state.messages == (
        UserMessage("repair the failing test"),
        AssistantMessage(content="implementation is ready for verification"),
    )
    assert len(client.requests) == 1
    assert client.requests[0].messages == (UserMessage("repair the failing test"),)
    assert state.status.value != "success"


@pytest.mark.parametrize("max_rounds", [0, -1, True])
def test_runner_rejects_invalid_round_limit(
    tmp_path: Path,
    max_rounds: object,
) -> None:
    with pytest.raises(ValueError, match="max_rounds must be a positive integer"):
        AgentRunner(
            model_client=FakeModelClient(()),
            tool_registry=ToolRegistry(),
            execution_context=ExecutionContext(workspace=tmp_path),
            max_rounds=max_rounds,  # type: ignore[arg-type]
        )


def test_tool_result_is_paired_and_written_to_next_request(tmp_path: Path) -> None:
    marker = object()
    call = ToolCall(call_id="call_1", name="echo", arguments={"text": "hello"})
    tool = EchoTool()
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(call,), continuation_items=(marker,)),
            ModelResponse(text="done"),
        ),
        tools=(tool,),
    )

    state = runner.run("use the tool")

    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert state.model_call_count == 2
    assert state.tool_call_count == 1
    assert tool.executed == [("hello", tmp_path)]
    assert client.requests[0].tool_schemas == (tool.schema,)
    second_request = client.requests[1]
    assert second_request.continuation_items == (marker,)
    assert second_request.messages[1] == AssistantMessage(
        content=None,
        tool_calls=(call,),
    )
    result = second_request.messages[2]
    assert isinstance(result, ToolResult)
    assert result == ToolResult(
        call_id="call_1",
        tool_name="echo",
        status="ok",
        output="hello",
    )


def test_multiple_tools_execute_in_response_order_across_rounds(
    tmp_path: Path,
) -> None:
    tool = EchoTool()
    first = ToolCall(call_id="call_1", name="echo", arguments={"text": "first"})
    second = ToolCall(call_id="call_2", name="echo", arguments={"text": "second"})
    third = ToolCall(call_id="call_3", name="echo", arguments={"text": "third"})
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(first, second)),
            ModelResponse(tool_calls=(third,)),
            ModelResponse(text="all calls complete"),
        ),
        tools=(tool,),
    )

    state = runner.run("execute in order")

    assert [text for text, _ in tool.executed] == ["first", "second", "third"]
    assert state.tool_call_count == 3
    assert state.model_call_count == 3
    assert [
        message.call_id
        for message in client.requests[1].messages
        if isinstance(message, ToolResult)
    ] == ["call_1", "call_2"]
    assert [
        message.call_id
        for message in client.requests[2].messages
        if isinstance(message, ToolResult)
    ] == ["call_1", "call_2", "call_3"]


def test_text_with_tool_calls_is_preserved_without_ending_early(
    tmp_path: Path,
) -> None:
    call = ToolCall(call_id="call_1", name="echo", arguments={"text": "inspect"})
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(text="I will inspect first.", tool_calls=(call,)),
            ModelResponse(text="inspection complete"),
        ),
        tools=(EchoTool(),),
    )

    state = runner.run("inspect")

    assert len(client.requests) == 2
    assert client.requests[1].messages[1] == AssistantMessage(
        content="I will inspect first.",
        tool_calls=(call,),
    )
    assert state.completion_text == "inspection complete"


def test_round_limit_returns_failed_state(tmp_path: Path) -> None:
    calls = tuple(
        ToolCall(call_id=f"call_{index}", name="echo", arguments={"text": str(index)})
        for index in (1, 2)
    )
    runner, client = _runner(
        tmp_path,
        tuple(ModelResponse(tool_calls=(call,)) for call in calls),
        tools=(EchoTool(),),
        max_rounds=2,
    )

    state = runner.run("never completes")

    assert state.status is AgentStatus.FAILED
    assert state.failure_reason == "round_limit_exceeded"
    assert state.completion_text is None
    assert state.model_call_count == 2
    assert state.tool_call_count == 2
    assert len(client.requests) == 2


def test_registry_rejects_duplicate_tool_name() -> None:
    with pytest.raises(ValueError, match="duplicate tool name: echo"):
        ToolRegistry((EchoTool(), EchoTool()))


def test_unknown_tool_becomes_rejected_result(tmp_path: Path) -> None:
    call = ToolCall(call_id="call_missing", name="missing", arguments={})
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="recovered")),
    )

    state = runner.run("call an unknown tool")

    result = client.requests[1].messages[2]
    assert isinstance(result, ToolResult)
    assert result.call_id == "call_missing"
    assert result.tool_name == "missing"
    assert result.status == "rejected"
    assert result.error == "unknown_tool: no tool registered as 'missing'"
    assert state.status is AgentStatus.COMPLETION_CANDIDATE


def test_bad_arguments_become_rejected_result(tmp_path: Path) -> None:
    tool = EchoTool()
    call = ToolCall(call_id="call_bad", name="echo", arguments={"text": 7})
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="recovered")),
        tools=(tool,),
    )

    state = runner.run("send invalid arguments")

    result = client.requests[1].messages[2]
    assert isinstance(result, ToolResult)
    assert result.status == "rejected"
    assert result.error == (
        "invalid_arguments: text must be the only argument and be a string"
    )
    assert tool.executed == []
    assert state.status is AgentStatus.COMPLETION_CANDIDATE


def test_tool_exception_becomes_error_result_without_traceback(
    tmp_path: Path,
) -> None:
    call = ToolCall(call_id="call_boom", name="explode", arguments={})
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="recovered")),
        tools=(ExplodingTool(),),
    )

    state = runner.run("exercise failure handling")

    result = client.requests[1].messages[2]
    assert isinstance(result, ToolResult)
    assert result.status == "error"
    assert result.error == "tool_execution_failed: RuntimeError: boom"
    assert "Traceback" not in result.error
    assert state.status is AgentStatus.COMPLETION_CANDIDATE


def test_empty_model_response_returns_failed_state(tmp_path: Path) -> None:
    runner, client = _runner(tmp_path, (ModelResponse(),))

    state = runner.run("handle empty response")

    assert state.status is AgentStatus.FAILED
    assert state.failure_reason == "empty_model_response"
    assert state.completion_text is None
    assert state.model_call_count == 1
    assert state.tool_call_count == 0
    assert state.messages == (UserMessage("handle empty response"),)
    assert len(client.requests) == 1


def test_agent_and_tools_import_without_openai_or_api_key() -> None:
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "openai" or name.startswith("openai."):
        raise AssertionError("Task 4 imported OpenAI SDK")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import coding_agent.agent
import coding_agent.state
import coding_agent.tools.base
import coding_agent.tools.registry
"""
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr

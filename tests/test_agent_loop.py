from __future__ import annotations

from collections import deque
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from openai import RateLimitError

import coding_agent.agent as agent_module
from coding_agent.agent import AgentInterrupted, AgentRunner
from coding_agent.context import ContextLimits, ContextManager
from coding_agent.logging import RunEventLogger
from coding_agent.messages import (
    AssistantMessage,
    JSONObject,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResult,
    ToolResultMetadata,
    UserMessage,
)
from coding_agent.model import (
    FakeModelClient,
    FatalModelError,
    ModelClient,
    ModelError,
    TransientModelError,
)
from coding_agent.openai_client import OpenAIResponsesClient
from coding_agent.safety import (
    AuthorizedCommand,
    CommandSource,
    SafetyCode,
    SafetyViolation,
)
from coding_agent.state import AgentStatus, TerminationReason, VerificationStatus
from coding_agent.termination import TerminationLimits, TerminationPolicy
from coding_agent.tools.base import (
    ExecutionContext,
    ToolArgumentError,
    ToolExecution,
)
from coding_agent.tools.filesystem import (
    ReadFileTool,
    ReplaceTextTool,
    WriteFileTool,
)
from coding_agent.tools.registry import ToolRegistry
from coding_agent.verification import VerificationGate


def _runner(
    tmp_path: Path,
    responses: tuple[ModelResponse | ModelError, ...],
    *,
    tools: tuple[object, ...] = (),
    limits: TerminationLimits | None = None,
    clock: Callable[[], float] = lambda: 0.0,
    context_limits: ContextLimits | None = None,
    verification_gate: VerificationGate | None = None,
    event_sink: object | None = None,
) -> tuple[AgentRunner, FakeModelClient]:
    client = FakeModelClient(responses)
    runner = AgentRunner(
        model_client=client,
        tool_registry=ToolRegistry(tools),  # type: ignore[arg-type]
        execution_context=ExecutionContext(workspace=tmp_path),
        context_manager=(
            ContextManager(model_client=client, limits=context_limits)
            if context_limits is not None
            else None
        ),
        termination_policy=TerminationPolicy(limits or TerminationLimits()),
        clock=clock,
        verification_gate=verification_gate,
        event_sink=event_sink,  # type: ignore[arg-type]
    )
    return runner, client


@dataclass(slots=True)
class FakeVerificationExecutor:
    queued: deque[ToolExecution | BaseException]
    calls: list[tuple[AuthorizedCommand, ExecutionContext]] = field(
        default_factory=list
    )

    def __init__(self, *queued: ToolExecution | BaseException) -> None:
        self.queued = deque(queued)
        self.calls = []

    def execute(
        self, command: AuthorizedCommand, context: ExecutionContext
    ) -> ToolExecution:
        self.calls.append((command, context))
        value = self.queued.popleft()
        if isinstance(value, BaseException):
            raise value
        return value


def _required_verification() -> AuthorizedCommand:
    argv = (sys.executable, "-m", "pytest", "-q")
    return AuthorizedCommand(
        argv=argv,
        normalized_command=subprocess.list2cmdline(argv),
        purpose="verification",
        source=CommandSource.USER_VERIFY,
    )


def _verification_execution(
    exit_code: int | None,
    *,
    timed_out: bool = False,
    stdout: str = "",
    stderr: str = "",
) -> ToolExecution:
    required = _required_verification()
    return ToolExecution(
        output=json.dumps(
            {
                "argv": list(required.argv),
                "cleanup_error": None,
                "purpose": "verification",
                "stderr": stderr,
                "stdout": stdout,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        metadata=ToolResultMetadata(
            exit_code=exit_code,
            timed_out=timed_out,
            duration_ms=5,
        ),
    )


def _verification_gate(
    tmp_path: Path,
    executor: FakeVerificationExecutor,
    *,
    required: bool = True,
) -> VerificationGate:
    return VerificationGate(
        required_command=_required_verification() if required else None,
        execution_context=ExecutionContext(tmp_path),
        executor=executor,
    )


@dataclass(slots=True)
class FakeClock:
    values: deque[float]

    def __init__(self, *values: float) -> None:
        self.values = deque(values)

    def __call__(self) -> float:
        if not self.values:
            raise AssertionError("unexpected clock read")
        return self.values.popleft()


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
class OfflineVerificationTool:
    name: str = field(default="run_command", init=False)
    schema: JSONObject = field(
        default_factory=lambda: {
            "name": "run_command",
            "description": "Return offline verification evidence.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "purpose": {"type": "string"},
                },
                "required": ["command", "purpose"],
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
        return _verification_execution(0, stdout="offline passed")


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


class FakeRateLimitError(RateLimitError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeResponsesResource:
    def __init__(self, *outcomes: object) -> None:
        self.outcomes = deque(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(deepcopy(kwargs))
        if not self.outcomes:
            raise AssertionError("unexpected Responses API call")
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeSDKClient:
    def __init__(self, *outcomes: object) -> None:
        self.responses = FakeResponsesResource(*outcomes)


@dataclass(slots=True)
class RecordingTool:
    outcomes: deque[ToolExecution | BaseException]
    executions: list[JSONObject] = field(default_factory=list)
    name: str = field(default="record", init=False)
    schema: JSONObject = field(
        default_factory=lambda: {
            "name": "record",
            "description": "Return a scripted deterministic result.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        },
        init=False,
    )

    def __init__(self, *outcomes: ToolExecution | BaseException) -> None:
        self.outcomes = deque(outcomes)
        self.executions = []
        self.name = "record"
        self.schema = {
            "name": "record",
            "description": "Return a scripted deterministic result.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        }

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        self.executions.append(arguments)
        if not self.outcomes:
            raise AssertionError("unexpected tool execution")
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class InterruptingModelClient:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        raise KeyboardInterrupt


class ExitingModelClient:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        raise SystemExit(130)


def _record_call(index: int) -> ToolCall:
    return ToolCall(
        call_id=f"call-{index}",
        name="record",
        arguments={"value": "same"},
    )


def _compression_limits() -> ContextLimits:
    return ContextLimits(
        max_serialized_chars=60_000,
        max_history_items=18,
        recent_turns=8,
    )


def _nine_tool_turns() -> tuple[ModelResponse, ...]:
    return tuple(
        ModelResponse(tool_calls=(_record_call(index),)) for index in range(9)
    )


def _nine_tool_outcomes() -> tuple[ToolExecution, ...]:
    return tuple(ToolExecution(output=f"result-{index}") for index in range(9))


def _summary_response(*, continuation: tuple[object, ...] = ()) -> ModelResponse:
    return ModelResponse(
        text=json.dumps(
            {
                "goal": "model goal",
                "established_facts": [],
                "files_examined": [],
                "changes_made": [],
                "commands_and_results": [],
                "unresolved_errors": [],
                "open_issues": [],
                "verification_state": {},
                "avoid_repeating": [],
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        continuation_items=continuation,
    )


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
    assert state.mutation_index == 0
    assert state.modified_paths == ()
    assert state.verification_status is VerificationStatus.NOT_RUN
    assert json.dumps(state.verification_status) == '"not_run"'
    assert "mutation_index=0" in repr(state)
    assert "modified_paths=()" in repr(state)
    assert "verification_status=" in repr(state)
    assert state.messages == (
        UserMessage("repair the failing test"),
        AssistantMessage(content="implementation is ready for verification"),
    )
    assert len(client.requests) == 1
    assert client.requests[0].messages == (UserMessage("repair the failing test"),)
    assert state.status.value != "success"


def test_runner_rejects_removed_max_rounds_parameter(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="max_rounds"):
        AgentRunner(
            model_client=FakeModelClient(()),
            tool_registry=ToolRegistry(),
            execution_context=ExecutionContext(workspace=tmp_path),
            max_rounds=1,  # type: ignore[call-arg]
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


def test_logical_model_limit_blocks_third_request(tmp_path: Path) -> None:
    calls = tuple(
        ToolCall(call_id=f"call_{index}", name="echo", arguments={"text": str(index)})
        for index in (1, 2)
    )
    runner, client = _runner(
        tmp_path,
        tuple(ModelResponse(tool_calls=(call,)) for call in calls),
        tools=(EchoTool(),),
        limits=TerminationLimits(max_logical_model_calls=2),
    )

    state = runner.run("never completes")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.LOGICAL_MODEL_CALL_LIMIT
    assert state.failure_reason == TerminationReason.LOGICAL_MODEL_CALL_LIMIT.value
    assert state.completion_text is None
    assert state.model_call_count == 2
    assert state.tool_call_count == 2
    assert len(client.requests) == 2


def test_provider_attempt_limit_blocks_third_retry(tmp_path: Path) -> None:
    sdk = FakeSDKClient(
        FakeRateLimitError("hidden"),
        FakeRateLimitError("hidden"),
        AssertionError("third provider request must not run"),
    )
    client = OpenAIResponsesClient(
        model="gpt-test",
        api_key="unit-test-key-never-send",
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )
    runner = AgentRunner(
        model_client=client,
        tool_registry=ToolRegistry(),
        execution_context=ExecutionContext(workspace=tmp_path),
        termination_policy=TerminationPolicy(
            TerminationLimits(max_provider_attempts=2)
        ),
        clock=lambda: 0.0,
    )

    state = runner.run("retry within the shared budget")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.PROVIDER_ATTEMPT_LIMIT
    assert state.logical_model_call_count == 1
    assert state.model_call_count == 2
    assert len(sdk.responses.calls) == 2


def test_agent_emits_ordered_tool_mutation_candidate_and_terminal_events(
    tmp_path: Path,
) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="5" * 32)
    call = ToolCall(
        call_id="private-call-id",
        name="record",
        arguments={"value": "private arguments"},
    )
    runner, _ = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(call,)),
            ModelResponse(text="private completion"),
        ),
        tools=(
            RecordingTool(
                ToolExecution(
                    output="private tool output",
                    metadata=ToolResultMetadata(changed_paths=("z.py", "a.py")),
                )
            ),
        ),
        event_sink=logger,
    )

    state = runner.run("private task")
    logger.close()

    raw = (
        tmp_path / ".coding-agent" / "logs" / ("5" * 32 + ".jsonl")
    ).read_text(encoding="utf-8")
    events = [json.loads(line) for line in raw.splitlines()]
    event_types = [event["event_type"] for event in events]
    assert event_types == [
        "run_started",
        "model_call_started",
        "provider_attempt_started",
        "provider_attempt_completed",
        "model_call_completed",
        "tool_call_started",
        "tool_call_completed",
        "mutation_recorded",
        "model_call_started",
        "provider_attempt_started",
        "provider_attempt_completed",
        "model_call_completed",
        "completion_candidate",
        "run_completed",
    ]
    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert events[6]["data"]["mutation_index_before"] == 0
    assert events[6]["data"]["mutation_index_after"] == 1
    assert events[7]["data"]["changed_paths"] == ["z.py", "a.py"]
    assert events[-1]["data"]["status"] == "completion_candidate"
    assert "private-call-id" not in raw
    assert "private arguments" not in raw
    assert "private tool output" not in raw
    assert "private completion" not in raw
    assert "private task" not in raw


def test_tool_limit_pairs_unexecuted_call_without_dispatch(tmp_path: Path) -> None:
    tool = EchoTool()
    first = ToolCall("call-1", "echo", {"text": "first"})
    second = ToolCall("call-2", "echo", {"text": "second"})
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(first, second)),),
        tools=(tool,),
        limits=TerminationLimits(max_tool_calls=1),
    )

    state = runner.run("respect tool limit")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.TOOL_CALL_LIMIT
    assert state.tool_call_count == 1
    assert tool.executed == [("first", tmp_path)]
    assert len(client.requests) == 1
    results = tuple(
        message for message in state.messages if isinstance(message, ToolResult)
    )
    assert tuple(result.call_id for result in results) == ("call-1", "call-2")
    assert results[1].status == "rejected"
    assert results[1].error == "agent_terminated:tool_call_limit"


def test_exact_time_limit_prevents_first_model_request(tmp_path: Path) -> None:
    clock = FakeClock(0.0, 600.0)
    runner, client = _runner(
        tmp_path,
        (ModelResponse(text="must not run"),),
        clock=clock,
    )

    state = runner.run("stop at time limit")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.TIME_LIMIT
    assert state.model_call_count == 0
    assert state.logical_model_call_count == 0
    assert len(client.requests) == 0


def test_three_consecutive_model_errors_stop_before_fourth_request(
    tmp_path: Path,
) -> None:
    runner, client = _runner(
        tmp_path,
        (
            TransientModelError("one"),
            TransientModelError("two"),
            TransientModelError("three"),
            ModelResponse(text="must not run"),
        ),
    )
    state = runner.run("retry model")
    assert state.termination_reason is TerminationReason.CONSECUTIVE_MODEL_ERRORS
    assert state.consecutive_model_errors == 3
    assert len(client.requests) == 3
    assert state.tool_call_count == 0


def test_model_success_resets_consecutive_model_errors(tmp_path: Path) -> None:
    tool = RecordingTool(ToolExecution(output="ok"))
    runner, client = _runner(
        tmp_path,
        (
            TransientModelError("one"),
            ModelResponse(tool_calls=(_record_call(1),)),
            TransientModelError("two"),
            ModelResponse(text="done"),
        ),
        tools=(tool,),
    )
    state = runner.run("recover model")
    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert state.termination_reason is None
    assert state.consecutive_model_errors == 0
    assert len(client.requests) == 4
    assert len(tool.executions) == 1


def test_three_identical_no_progress_results_stop_without_fourth_tool(
    tmp_path: Path,
) -> None:
    tool = RecordingTool(
        ToolExecution(output="same"),
        ToolExecution(output="same"),
        ToolExecution(output="same"),
    )
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(_record_call(1),)),
            ModelResponse(tool_calls=(_record_call(2),)),
            ModelResponse(tool_calls=(_record_call(3),)),
            ModelResponse(tool_calls=(_record_call(4),)),
        ),
        tools=(tool,),
    )
    state = runner.run("detect repetition")
    assert state.repeated_tool_call_count == 3
    assert state.termination_reason is TerminationReason.REPEATED_TOOL_CALL
    assert len(client.requests) == 3
    assert len(tool.executions) == 3


def test_different_result_resets_repetition(tmp_path: Path) -> None:
    tool = RecordingTool(
        ToolExecution(output="same"),
        ToolExecution(output="same"),
        ToolExecution(output="different"),
    )
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(_record_call(1),)),
            ModelResponse(tool_calls=(_record_call(2),)),
            ModelResponse(tool_calls=(_record_call(3),)),
            ModelResponse(text="done"),
        ),
        tools=(tool,),
    )
    state = runner.run("reset repetition")
    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert state.repeated_tool_call_count == 0
    assert len(client.requests) == 4
    assert len(tool.executions) == 3


def test_successful_mutation_resets_repetition(tmp_path: Path) -> None:
    tool = RecordingTool(
        ToolExecution(output="same"),
        ToolExecution(output="same"),
        ToolExecution(
            output="same",
            metadata=ToolResultMetadata(changed_paths=("changed.py",)),
        ),
    )
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(_record_call(1),)),
            ModelResponse(tool_calls=(_record_call(2),)),
            ModelResponse(tool_calls=(_record_call(3),)),
            ModelResponse(text="done"),
        ),
        tools=(tool,),
    )
    state = runner.run("mutation is progress")
    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert state.repeated_tool_call_count == 0
    assert state.mutation_index == 1
    assert len(client.requests) == 4
    assert len(tool.executions) == 3


def test_three_nonsecurity_tool_errors_stop(tmp_path: Path) -> None:
    tool = RecordingTool(
        RuntimeError("ordinary failure"),
        RuntimeError("ordinary failure"),
        RuntimeError("ordinary failure"),
    )
    runner, client = _runner(
        tmp_path,
        tuple(ModelResponse(tool_calls=(_record_call(index),)) for index in range(3)),
        tools=(tool,),
    )
    state = runner.run("count tool errors")
    assert state.termination_reason is TerminationReason.CONSECUTIVE_TOOL_ERRORS
    assert state.consecutive_tool_errors == 3
    assert len(tool.executions) == 3
    assert len(client.requests) == 3


def test_tool_success_resets_tool_error_counter(tmp_path: Path) -> None:
    tool = RecordingTool(
        RuntimeError("ordinary failure"),
        RuntimeError("ordinary failure"),
        ToolExecution(output="ok"),
    )
    runner, _ = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(_record_call(1),)),
            ModelResponse(tool_calls=(_record_call(2),)),
            ModelResponse(tool_calls=(_record_call(3),)),
            ModelResponse(text="done"),
        ),
        tools=(tool,),
    )
    state = runner.run("reset tool errors")
    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert state.consecutive_tool_errors == 0
    assert len(tool.executions) == 3


def test_three_security_rejections_use_security_reason(tmp_path: Path) -> None:
    denied = lambda: SafetyViolation(SafetyCode.ARGUMENT_DENIED, "denied")
    tool = RecordingTool(denied(), denied(), denied())
    runner, client = _runner(
        tmp_path,
        tuple(ModelResponse(tool_calls=(_record_call(index),)) for index in range(3)),
        tools=(tool,),
    )
    state = runner.run("count security rejections")
    assert (
        state.termination_reason
        is TerminationReason.CONSECUTIVE_SAFETY_REJECTIONS
    )
    assert state.consecutive_safety_rejections == 3
    assert state.consecutive_tool_errors == 0
    assert len(tool.executions) == 3
    assert len(client.requests) == 3


def test_fatal_model_error_stops_immediately_without_second_logical_call(
    tmp_path: Path,
) -> None:
    runner, client = _runner(
        tmp_path,
        (FatalModelError("fatal"), ModelResponse(text="must not run")),
    )
    state = runner.run("fatal model")
    assert state.termination_reason is TerminationReason.FATAL_MODEL_ERROR
    assert state.logical_model_call_count == 1
    assert len(client.requests) == 1
    assert state.tool_call_count == 0


def test_empty_response_has_stable_reason(tmp_path: Path) -> None:
    runner, client = _runner(tmp_path, (ModelResponse(),))
    state = runner.run("empty")
    assert state.termination_reason is TerminationReason.EMPTY_MODEL_RESPONSE
    assert len(client.requests) == 1
    assert state.tool_call_count == 0


def test_keyboard_interrupt_carries_interrupted_state(tmp_path: Path) -> None:
    client = InterruptingModelClient()
    runner = AgentRunner(
        model_client=client,
        tool_registry=ToolRegistry(),
        execution_context=ExecutionContext(workspace=tmp_path),
        clock=lambda: 0.0,
    )
    with pytest.raises(agent_module.AgentInterrupted) as caught:
        runner.run("interrupt")
    state = caught.value.state
    assert state.status is AgentStatus.INTERRUPTED
    assert state.termination_reason is TerminationReason.USER_INTERRUPTED
    assert state.logical_model_call_count == 1
    assert state.tool_call_count == 0
    assert len(client.requests) == 1


def test_system_exit_is_not_caught(tmp_path: Path) -> None:
    client = ExitingModelClient()
    runner = AgentRunner(
        model_client=client,
        tool_registry=ToolRegistry(),
        execution_context=ExecutionContext(workspace=tmp_path),
        clock=lambda: 0.0,
    )
    with pytest.raises(SystemExit) as caught:
        runner.run("exit")
    assert caught.value.code == 130
    assert len(client.requests) == 1


def test_summary_and_main_call_share_one_run_budget(tmp_path: Path) -> None:
    tool = RecordingTool(*_nine_tool_outcomes())
    runner, client = _runner(
        tmp_path,
        _nine_tool_turns()
        + (_summary_response(), ModelResponse(text="done")),
        tools=(tool,),
        context_limits=_compression_limits(),
    )

    state = runner.run("compress then finish")

    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert state.logical_model_call_count == 11
    assert state.model_call_count == 11
    assert len(client.requests) == 11
    assert client.requests[9].tool_schemas == ()
    assert client.requests[10].messages[1].content.startswith(
        "coding-agent context summary\n"  # type: ignore[union-attr]
    )


def test_compression_events_wrap_summary_and_clear_continuation(
    tmp_path: Path,
) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="6" * 32)
    tool = RecordingTool(*_nine_tool_outcomes())
    runner, _ = _runner(
        tmp_path,
        _nine_tool_turns()
        + (
            _summary_response(continuation=("summary-private",)),
            ModelResponse(text="done"),
        ),
        tools=(tool,),
        context_limits=_compression_limits(),
        event_sink=logger,
    )

    state = runner.run("compress and continue")
    logger.close()

    raw = (
        tmp_path / ".coding-agent" / "logs" / ("6" * 32 + ".jsonl")
    ).read_text(encoding="utf-8")
    events = [json.loads(line) for line in raw.splitlines()]
    started = next(
        index
        for index, event in enumerate(events)
        if event["event_type"] == "context_compression_started"
    )
    summary_model_started = next(
        index
        for index, event in enumerate(events)
        if event["event_type"] == "model_call_started"
        and event["data"]["purpose"] == "summary"
    )
    completed = next(
        index
        for index, event in enumerate(events)
        if event["event_type"] == "context_compression_completed"
    )
    next_main = next(
        index
        for index, event in enumerate(events[completed + 1 :], completed + 1)
        if event["event_type"] == "model_call_started"
        and event["data"]["purpose"] == "main"
    )
    assert started < summary_model_started < completed < next_main
    assert events[completed]["data"]["continuation_cleared"] is True
    assert events[completed]["data"]["summary_source"] == "model"
    assert logger.metadata.context_compression_count == 1
    assert state.continuation_items == ()
    assert "summary-private" not in raw


def test_summary_exhausts_provider_budget_before_main_call(
    tmp_path: Path,
) -> None:
    tool = RecordingTool(*_nine_tool_outcomes())
    runner, client = _runner(
        tmp_path,
        _nine_tool_turns()
        + (TransientModelError("summary unavailable"), ModelResponse(text="must not run")),
        tools=(tool,),
        context_limits=_compression_limits(),
        limits=TerminationLimits(max_provider_attempts=10),
    )

    state = runner.run("summary uses final provider attempt")

    assert state.termination_reason is TerminationReason.PROVIDER_ATTEMPT_LIMIT
    assert state.logical_model_call_count == 10
    assert state.model_call_count == 10
    assert len(client.requests) == 10


def test_summary_fallback_with_remaining_budget_continues_main(
    tmp_path: Path,
) -> None:
    tool = RecordingTool(*_nine_tool_outcomes())
    runner, client = _runner(
        tmp_path,
        _nine_tool_turns()
        + (TransientModelError("summary unavailable"), ModelResponse(text="done")),
        tools=(tool,),
        context_limits=_compression_limits(),
    )

    state = runner.run("fallback then finish")

    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert state.logical_model_call_count == 11
    assert state.model_call_count == 11
    assert len(client.requests) == 11


def test_fatal_summary_error_becomes_stable_agent_termination(
    tmp_path: Path,
) -> None:
    tool = RecordingTool(*_nine_tool_outcomes())
    runner, client = _runner(
        tmp_path,
        _nine_tool_turns() + (FatalModelError("fatal summary"),),
        tools=(tool,),
        context_limits=_compression_limits(),
    )

    state = runner.run("fatal summary")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.FATAL_MODEL_ERROR
    assert state.failure_reason == TerminationReason.FATAL_MODEL_ERROR.value
    assert state.logical_model_call_count == 10
    assert state.model_call_count == 10
    assert len(client.requests) == 10


def test_uncompressed_continuation_passes_through_unchanged(
    tmp_path: Path,
) -> None:
    marker = object()
    tool = RecordingTool(ToolExecution(output="one"))
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(
                tool_calls=(_record_call(1),),
                continuation_items=(marker,),
            ),
            ModelResponse(text="done"),
        ),
        tools=(tool,),
    )

    state = runner.run("preserve continuation")

    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert client.requests[1].continuation_items[0] is marker


def test_compression_clears_continuation_before_next_main_request(
    tmp_path: Path,
) -> None:
    active = object()
    summary_only = object()
    tool = RecordingTool(*_nine_tool_outcomes())
    turns = list(_nine_tool_turns())
    turns[-1] = ModelResponse(
        tool_calls=turns[-1].tool_calls,
        continuation_items=(active,),
    )
    runner, client = _runner(
        tmp_path,
        tuple(turns)
        + (
            _summary_response(continuation=(summary_only,)),
            ModelResponse(text="done"),
        ),
        tools=(tool,),
        context_limits=_compression_limits(),
    )

    state = runner.run("clear stale continuation")

    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert client.requests[9].continuation_items == ()
    assert client.requests[10].continuation_items == ()
    assert active not in state.continuation_items
    assert summary_only not in state.continuation_items


def test_text_on_final_permitted_model_call_is_completion_candidate(
    tmp_path: Path,
) -> None:
    runner, client = _runner(
        tmp_path,
        (ModelResponse(text="done"),),
        limits=TerminationLimits(max_logical_model_calls=1),
    )
    state = runner.run("finish at boundary")
    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert state.termination_reason is None
    assert state.logical_model_call_count == 1
    assert len(client.requests) == 1


def test_tools_on_final_model_call_run_before_next_model_is_refused(
    tmp_path: Path,
) -> None:
    tool = RecordingTool(ToolExecution(output="done"))
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(_record_call(1),)),),
        tools=(tool,),
        limits=TerminationLimits(max_logical_model_calls=1),
    )
    state = runner.run("tool at boundary")
    assert state.termination_reason is TerminationReason.LOGICAL_MODEL_CALL_LIMIT
    assert state.logical_model_call_count == 1
    assert state.tool_call_count == 1
    assert len(client.requests) == 1
    assert len(tool.executions) == 1


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
    assert state.mutation_index == 0
    assert state.modified_paths == ()
    assert state.verification_status is VerificationStatus.NOT_RUN
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


def test_successful_replace_updates_ledger_and_marks_verification_stale(
    tmp_path: Path,
) -> None:
    (tmp_path / "sample.txt").write_text("old", encoding="utf-8")
    call = ToolCall(
        call_id="replace_1",
        name="replace_text",
        arguments={
            "path": "sample.txt",
            "old_text": "old",
            "new_text": "new",
            "expected_count": 1,
        },
    )
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="done")),
        tools=(ReplaceTextTool(),),
    )

    state = runner.run("replace text")

    assert state.mutation_index == 1
    assert state.modified_paths == ("sample.txt",)
    assert state.verification_status is VerificationStatus.STALE
    assert json.dumps(state.verification_status) == '"stale"'


def test_successful_write_updates_ledger_and_marks_verification_stale(
    tmp_path: Path,
) -> None:
    call = ToolCall(
        call_id="write_1",
        name="write_file",
        arguments={"path": "created.txt", "content": "content"},
    )
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="done")),
        tools=(WriteFileTool(),),
    )

    state = runner.run("create file")

    assert state.mutation_index == 1
    assert state.modified_paths == ("created.txt",)
    assert state.verification_status is VerificationStatus.STALE


def test_required_verification_runs_only_after_text_candidate(
    tmp_path: Path,
) -> None:
    executor = FakeVerificationExecutor(_verification_execution(0, stdout="passed"))
    call = ToolCall("echo-before-verify", "echo", {"text": "working"})
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="done")),
        tools=(EchoTool(),),
        verification_gate=_verification_gate(tmp_path, executor),
    )

    state = runner.run("verify after tools")

    assert state.status is AgentStatus.SUCCESS
    assert state.completion_text == "done"
    assert len(client.requests) == 2
    assert len(executor.calls) == 1
    assert state.verification_attempt_count == 1


def test_required_verification_failure_feedback_reaches_next_model_request(
    tmp_path: Path,
) -> None:
    executor = FakeVerificationExecutor(
        _verification_execution(1, stderr="one failed"),
        _verification_execution(0, stdout="fixed"),
    )
    runner, client = _runner(
        tmp_path,
        (ModelResponse(text="candidate one"), ModelResponse(text="candidate two")),
        verification_gate=_verification_gate(tmp_path, executor),
    )

    state = runner.run("repair after verification")

    assert state.status is AgentStatus.SUCCESS
    assert state.completion_text == "candidate two"
    assert len(client.requests) == 2
    feedback = client.requests[1].messages[-1]
    assert isinstance(feedback, AssistantMessage)
    assert feedback.content is not None
    assert feedback.content.startswith("coding-agent verification feedback\n")
    assert '"status":"failed"' in feedback.content
    assert len(executor.calls) == 2
    assert state.verification_attempt_count == 2


def test_candidate_failure_mutation_and_fresh_pass_reaches_success(
    tmp_path: Path,
) -> None:
    (tmp_path / "sample.txt").write_text("old", encoding="utf-8")
    replace = ToolCall(
        "repair-file",
        "replace_text",
        {
            "path": "sample.txt",
            "old_text": "old",
            "new_text": "new",
            "expected_count": 1,
        },
    )
    executor = FakeVerificationExecutor(
        _verification_execution(1, stderr="broken"),
        _verification_execution(0, stdout="passed"),
    )
    runner, _ = _runner(
        tmp_path,
        (
            ModelResponse(text="first candidate"),
            ModelResponse(tool_calls=(replace,)),
            ModelResponse(text="fixed candidate"),
        ),
        tools=(ReplaceTextTool(),),
        verification_gate=_verification_gate(tmp_path, executor),
    )

    state = runner.run("repair and verify")

    assert state.status is AgentStatus.SUCCESS
    assert state.mutation_index == 1
    assert state.validation_index == 1
    assert state.verification_status is VerificationStatus.PASSED
    assert state.verification_attempt_count == 2
    assert len(executor.calls) == 2
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "new"


def test_model_verification_evidence_allows_success_without_second_execution(
    tmp_path: Path,
) -> None:
    call = ToolCall(
        "model-verification",
        "run_command",
        {"command": "python -m pytest -q", "purpose": "verification"},
    )
    executor = FakeVerificationExecutor()
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="done")),
        tools=(OfflineVerificationTool(),),
        verification_gate=_verification_gate(tmp_path, executor, required=False),
    )

    state = runner.run("model verifies")

    assert state.status is AgentStatus.SUCCESS
    assert state.tool_call_count == 1
    assert state.verification_attempt_count == 1
    assert state.last_verification is not None
    assert state.last_verification.source is CommandSource.MODEL
    assert executor.calls == []


def test_model_prose_without_evidence_never_becomes_success(tmp_path: Path) -> None:
    executor = FakeVerificationExecutor()
    runner, client = _runner(
        tmp_path,
        (ModelResponse(text="I am done"), ModelResponse(text="still done")),
        limits=TerminationLimits(max_logical_model_calls=2),
        verification_gate=_verification_gate(tmp_path, executor, required=False),
    )

    state = runner.run("require real evidence")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.LOGICAL_MODEL_CALL_LIMIT
    assert state.verification_attempt_count == 0
    assert len(client.requests) == 2
    assert executor.calls == []
    assert sum(
        isinstance(message, AssistantMessage)
        and message.content is not None
        and message.content.startswith("coding-agent verification feedback\n")
        for message in state.messages
    ) == 2


def test_tool_budget_at_limit_blocks_required_verification_without_counting_it(
    tmp_path: Path,
) -> None:
    executor = FakeVerificationExecutor(_verification_execution(0))
    call = ToolCall("consume-slot", "echo", {"text": "work"})
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="candidate")),
        tools=(EchoTool(),),
        limits=TerminationLimits(max_tool_calls=1),
        verification_gate=_verification_gate(tmp_path, executor),
    )

    state = runner.run("respect tool budget")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.TOOL_CALL_LIMIT
    assert state.tool_call_count == 1
    assert state.verification_attempt_count == 0
    assert len(client.requests) == 2
    assert executor.calls == []


def test_time_at_exact_limit_blocks_required_verification(
    tmp_path: Path,
) -> None:
    executor = FakeVerificationExecutor(_verification_execution(0))
    clock = FakeClock(0.0, 0.0, 10.0)
    runner, client = _runner(
        tmp_path,
        (ModelResponse(text="candidate"),),
        limits=TerminationLimits(max_runtime_seconds=10.0),
        clock=clock,
        verification_gate=_verification_gate(tmp_path, executor),
    )

    state = runner.run("respect time budget")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.TIME_LIMIT
    assert state.tool_call_count == 0
    assert state.verification_attempt_count == 0
    assert len(client.requests) == 1
    assert executor.calls == []


def test_last_permitted_model_call_can_still_run_required_verification(
    tmp_path: Path,
) -> None:
    executor = FakeVerificationExecutor(_verification_execution(0))
    runner, client = _runner(
        tmp_path,
        (ModelResponse(text="candidate"),),
        limits=TerminationLimits(
            max_logical_model_calls=1,
            max_provider_attempts=1,
        ),
        verification_gate=_verification_gate(tmp_path, executor),
    )

    state = runner.run("last model call")

    assert state.status is AgentStatus.SUCCESS
    assert state.logical_model_call_count == 1
    assert state.model_call_count == 1
    assert state.tool_call_count == 1
    assert state.verification_attempt_count == 1
    assert len(client.requests) == 1
    assert len(executor.calls) == 1


def test_required_verification_events_precede_success_terminal(
    tmp_path: Path,
) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="7" * 32)
    executor = FakeVerificationExecutor(
        _verification_execution(0, stdout="private verification output")
    )
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(text="candidate"),),
        verification_gate=_verification_gate(tmp_path, executor),
        event_sink=logger,
    )

    state = runner.run("verify before success")
    logger.close()

    raw = (
        tmp_path / ".coding-agent" / "logs" / ("7" * 32 + ".jsonl")
    ).read_text(encoding="utf-8")
    events = [json.loads(line) for line in raw.splitlines()]
    event_types = [event["event_type"] for event in events]
    assert event_types[-4:] == [
        "completion_candidate",
        "verification_started",
        "verification_completed",
        "run_completed",
    ]
    assert state.status is AgentStatus.SUCCESS
    assert events[-2]["data"]["status"] == "passed"
    assert events[-2]["data"]["validation_index"] == state.mutation_index
    assert events[-1]["data"]["status"] == "success"
    assert "private verification output" not in raw


class FailingWriteStream:
    def __init__(self) -> None:
        self.write_calls = 0

    def write(self, value: str) -> int:
        self.write_calls += 1
        raise OSError("Authorization: Bearer private-provider-body")

    def flush(self) -> None:
        raise AssertionError("flush must not follow failed write")

    def close(self) -> None:
        return None


def test_run_started_log_failure_stops_before_model_and_is_stable(
    tmp_path: Path,
) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="8" * 32)
    stream = FailingWriteStream()
    logger._stream = stream  # type: ignore[attr-defined]
    runner, client = _runner(
        tmp_path,
        (ModelResponse(text="must not run"),),
        event_sink=logger,
    )

    state = runner.run("stop if the audit trail is unavailable")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.AUDIT_LOG_FAILURE
    assert state.failure_reason == "audit_log_failure"
    assert client.requests == ()
    assert state.logical_model_call_count == 0
    assert state.model_call_count == 0
    assert stream.write_calls == 1
    assert logger.metadata.log_failure_code == "log_write_failed"
    assert "private-provider-body" not in repr(state)
    assert "private-provider-body" not in repr(logger.metadata)


def test_failed_verification_then_exhausted_model_budget_stops_before_request(
    tmp_path: Path,
) -> None:
    executor = FakeVerificationExecutor(_verification_execution(1, stderr="failed"))
    runner, client = _runner(
        tmp_path,
        (ModelResponse(text="candidate"), ModelResponse(text="must not run")),
        limits=TerminationLimits(max_logical_model_calls=1),
        verification_gate=_verification_gate(tmp_path, executor),
    )

    state = runner.run("bounded repair")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.LOGICAL_MODEL_CALL_LIMIT
    assert state.logical_model_call_count == 1
    assert state.model_call_count == 1
    assert state.tool_call_count == 1
    assert state.verification_attempt_count == 1
    assert len(client.requests) == 1
    assert len(executor.calls) == 1


def test_admitted_passing_verification_wins_at_runtime_boundary(
    tmp_path: Path,
) -> None:
    executor = FakeVerificationExecutor(_verification_execution(0))
    clock = FakeClock(0.0, 0.0, 9.999, 10.0)
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(text="candidate"),),
        limits=TerminationLimits(max_runtime_seconds=10.0),
        clock=clock,
        verification_gate=_verification_gate(tmp_path, executor),
    )

    state = runner.run("admitted pass wins")

    assert state.status is AgentStatus.SUCCESS
    assert state.verification_status is VerificationStatus.PASSED
    assert state.tool_call_count == 1
    assert state.verification_attempt_count == 1
    assert len(executor.calls) == 1
    assert tuple(clock.values) == (10.0,)


def test_repeated_fixed_verification_failures_stop_at_tool_budget(
    tmp_path: Path,
) -> None:
    executor = FakeVerificationExecutor(
        _verification_execution(1, stderr="same failure"),
        _verification_execution(1, stderr="same failure"),
    )
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(text="candidate one"),
            ModelResponse(text="candidate two"),
            ModelResponse(text="candidate three"),
        ),
        limits=TerminationLimits(max_tool_calls=2),
        verification_gate=_verification_gate(tmp_path, executor),
    )

    state = runner.run("bounded repeated verification")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.TOOL_CALL_LIMIT
    assert state.tool_call_count == 2
    assert state.verification_attempt_count == 2
    assert len(executor.calls) == 2
    assert len(client.requests) == 3


def test_corrupt_required_verification_terminates_internal_invariant(
    tmp_path: Path,
) -> None:
    corrupt = ToolExecution(
        output='{"argv":[],"purpose":"verification"}',
        metadata=ToolResultMetadata(exit_code=0),
    )
    executor = FakeVerificationExecutor(corrupt)
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(text="candidate"),),
        verification_gate=_verification_gate(tmp_path, executor),
    )

    state = runner.run("corrupt evidence")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.INTERNAL_INVARIANT
    assert state.failure_reason == "internal_invariant"
    assert state.verification_attempt_count == 1
    assert state.tool_call_count == 1


def test_keyboard_interrupt_during_required_verification_carries_state(
    tmp_path: Path,
) -> None:
    executor = FakeVerificationExecutor(KeyboardInterrupt())
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(text="candidate"),),
        verification_gate=_verification_gate(tmp_path, executor),
    )

    with pytest.raises(AgentInterrupted) as caught:
        runner.run("interrupt verification")

    state = caught.value.state
    assert state.status is AgentStatus.INTERRUPTED
    assert state.termination_reason is TerminationReason.USER_INTERRUPTED
    assert state.verification_attempt_count == 1
    assert state.tool_call_count == 1


def test_system_exit_during_required_verification_is_not_caught(
    tmp_path: Path,
) -> None:
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(text="candidate"),),
        verification_gate=_verification_gate(
            tmp_path, FakeVerificationExecutor(SystemExit(130))
        ),
    )

    with pytest.raises(SystemExit) as caught:
        runner.run("system exit")

    assert caught.value.code == 130


def test_failed_verification_feedback_preserves_provider_continuation(
    tmp_path: Path,
) -> None:
    continuation = object()
    executor = FakeVerificationExecutor(
        _verification_execution(1, stderr="failed"),
        _verification_execution(0),
    )
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(text="candidate", continuation_items=(continuation,)),
            ModelResponse(text="fixed"),
        ),
        verification_gate=_verification_gate(tmp_path, executor),
    )

    state = runner.run("preserve continuation")

    assert state.status is AgentStatus.SUCCESS
    assert client.requests[1].continuation_items == (continuation,)
    assert client.requests[1].continuation_items[0] is continuation
    assert isinstance(client.requests[1].messages[-1], AssistantMessage)
    assert client.requests[1].messages[-1].tool_calls == ()  # type: ignore[union-attr]


def test_verification_exception_body_never_reaches_state_or_feedback(
    tmp_path: Path,
) -> None:
    secret = "Authorization: Bearer secret-sentinel"
    executor = FakeVerificationExecutor(
        RuntimeError(secret),
        _verification_execution(0),
    )
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(text="candidate"), ModelResponse(text="retry")),
        verification_gate=_verification_gate(tmp_path, executor),
    )

    state = runner.run("redact failure")

    assert state.status is AgentStatus.SUCCESS
    assert secret not in repr(state)
    assert all(secret not in repr(message) for message in state.messages)
    feedbacks = [
        message.content
        for message in state.messages
        if isinstance(message, AssistantMessage)
        and message.content is not None
        and message.content.startswith("coding-agent verification feedback\n")
    ]
    assert len(feedbacks) == 1
    assert "verification_internal_error" in feedbacks[0]
    assert secret not in feedbacks[0]


def test_successful_calls_increment_per_call_and_deduplicate_in_first_seen_order(
    tmp_path: Path,
) -> None:
    write_b = ToolCall(
        call_id="write_b",
        name="write_file",
        arguments={"path": "b.txt", "content": "old"},
    )
    write_a = ToolCall(
        call_id="write_a",
        name="write_file",
        arguments={"path": "a.txt", "content": "a"},
    )
    replace_b = ToolCall(
        call_id="replace_b",
        name="replace_text",
        arguments={
            "path": "b.txt",
            "old_text": "old",
            "new_text": "new",
            "expected_count": 1,
        },
    )
    runner, _ = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(write_b, write_a, replace_b)),
            ModelResponse(text="done"),
        ),
        tools=(WriteFileTool(), ReplaceTextTool()),
    )

    state = runner.run("modify two paths")

    assert state.mutation_index == 3
    assert state.modified_paths == ("b.txt", "a.txt")
    assert state.verification_status is VerificationStatus.STALE


@dataclass(slots=True)
class MultiPathMutationTool:
    name: str = field(default="multi_path_mutation", init=False)
    schema: JSONObject = field(
        default_factory=lambda: {
            "name": "multi_path_mutation",
            "description": "Return two changed paths for ledger testing.",
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
        return ToolExecution(
            output="changed two paths",
            metadata=ToolResultMetadata(changed_paths=("z.py", "a.py")),
        )


def test_one_successful_call_with_multiple_paths_increments_once(
    tmp_path: Path,
) -> None:
    call = ToolCall(
        call_id="multi_1",
        name="multi_path_mutation",
        arguments={},
    )
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="done")),
        tools=(MultiPathMutationTool(),),
    )

    state = runner.run("record multiple paths")

    assert state.mutation_index == 1
    assert state.modified_paths == ("z.py", "a.py")
    assert state.verification_status is VerificationStatus.STALE


def test_read_file_does_not_change_mutation_state(tmp_path: Path) -> None:
    (tmp_path / "sample.txt").write_text("content", encoding="utf-8")
    call = ToolCall(
        call_id="read_1",
        name="read_file",
        arguments={"path": "sample.txt", "start_line": 1, "end_line": None},
    )
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="done")),
        tools=(ReadFileTool(),),
    )

    state = runner.run("read without changing")

    assert state.mutation_index == 0
    assert state.modified_paths == ()
    assert state.verification_status is VerificationStatus.NOT_RUN


def test_failed_replace_does_not_change_mutation_state(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("old", encoding="utf-8")
    call = ToolCall(
        call_id="replace_bad",
        name="replace_text",
        arguments={
            "path": "sample.txt",
            "old_text": "old",
            "new_text": "new",
            "expected_count": 2,
        },
    )
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="done")),
        tools=(ReplaceTextTool(),),
    )

    state = runner.run("failed replace")

    result = client.requests[1].messages[2]
    assert isinstance(result, ToolResult)
    assert result.status == "rejected"
    assert target.read_text(encoding="utf-8") == "old"
    assert state.mutation_index == 0
    assert state.modified_paths == ()
    assert state.verification_status is VerificationStatus.NOT_RUN


def test_failed_write_does_not_change_mutation_state(tmp_path: Path) -> None:
    target = tmp_path / "created.txt"
    target.write_text("original", encoding="utf-8")
    call = ToolCall(
        call_id="write_bad",
        name="write_file",
        arguments={"path": "created.txt", "content": "replacement"},
    )
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="done")),
        tools=(WriteFileTool(),),
    )

    state = runner.run("failed write")

    result = client.requests[1].messages[2]
    assert isinstance(result, ToolResult)
    assert result.status == "rejected"
    assert target.read_text(encoding="utf-8") == "original"
    assert state.mutation_index == 0
    assert state.modified_paths == ()
    assert state.verification_status is VerificationStatus.NOT_RUN


def test_rejection_and_exception_after_success_preserve_existing_ledger(
    tmp_path: Path,
) -> None:
    write = ToolCall(
        call_id="write_ok",
        name="write_file",
        arguments={"path": "created.txt", "content": "content"},
    )
    rejected_write = ToolCall(
        call_id="write_bad",
        name="write_file",
        arguments={"path": "created.txt", "content": "replacement"},
    )
    explosion = ToolCall(call_id="explode_after_write", name="explode", arguments={})
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(write, rejected_write, explosion)),
            ModelResponse(text="done"),
        ),
        tools=(WriteFileTool(), ExplodingTool()),
    )

    state = runner.run("preserve ledger after failures")

    first_request_with_results = client.requests[1].messages
    results = [
        message
        for message in first_request_with_results
        if isinstance(message, ToolResult)
    ]
    assert [result.status for result in results] == ["ok", "rejected", "error"]
    assert state.mutation_index == 1
    assert state.modified_paths == ("created.txt",)
    assert state.verification_status is VerificationStatus.STALE


def test_registry_distinguishes_stable_safety_rejection(tmp_path: Path) -> None:
    class SafetyRejectingTool:
        name = "safety_reject"
        schema: JSONObject = {
            "name": "safety_reject",
            "description": "Reject for a deterministic safety reason.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        }

        def execute(
            self,
            arguments: JSONObject,
            context: ExecutionContext,
        ) -> ToolExecution:
            from coding_agent.safety import SafetyCode, SafetyViolation

            raise SafetyViolation(
                SafetyCode.PROTECTED_PATH,
                "protected path is unavailable",
            )

    registry = ToolRegistry((SafetyRejectingTool(),))
    result = registry.execute(
        ToolCall(call_id="safe_1", name="safety_reject", arguments={}),
        ExecutionContext(tmp_path),
    )

    assert result.status == "rejected"
    assert result.error == (
        "security_rejected:protected_path: protected path is unavailable"
    )
    assert result.metadata.changed_paths == ()


def test_agent_safety_rejection_has_no_mutation_ledger_effect(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret", encoding="utf-8")
    call = ToolCall(
        call_id="protected_read",
        name="read_file",
        arguments={"path": ".GIT/config", "start_line": 1, "end_line": None},
    )
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="stopped")),
        tools=(ReadFileTool(),),
    )

    state = runner.run("attempt protected read")

    result = client.requests[1].messages[2]
    assert isinstance(result, ToolResult)
    assert result.status == "rejected"
    assert result.error == "security_rejected:protected_path: protected path is unavailable"
    assert state.mutation_index == 0
    assert state.modified_paths == ()
    assert state.verification_status is VerificationStatus.NOT_RUN

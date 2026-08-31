from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
from types import SimpleNamespace

from coding_agent.agent import AgentRunner
from coding_agent.chat_completions_client import ChatCompletionsModelClient
from coding_agent.context import ContextLimits, ContextManager
from coding_agent.messages import JSONObject, ToolResult
from coding_agent.progress import ProgressLimits
from coding_agent.state import AgentStatus
from coding_agent.tools.base import (
    ExecutionContext,
    ToolArgumentError,
    ToolExecution,
)
from coding_agent.tools.registry import ToolRegistry


FAKE_KEY = "task15-agent-obviously-fake-key"
FAKE_BASE_URL = "https://offline-provider.example/api/v1"


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
        if set(arguments) != {"text"} or not isinstance(
            arguments["text"], str
        ):
            raise ToolArgumentError("text must be the only string argument")
        text = arguments["text"]
        self.executed.append((text, context.workspace))
        return ToolExecution(output=text)


class FakeCompletionsResource:
    def __init__(self, outcomes: tuple[object, ...]) -> None:
        self.outcomes = deque(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(deepcopy(kwargs))
        if not self.outcomes:
            raise AssertionError("unexpected Chat Completions API call")
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeSDKClient:
    def __init__(self, *outcomes: object) -> None:
        self.chat = SimpleNamespace(
            completions=FakeCompletionsResource(outcomes)
        )


def _response(
    *,
    content: str | None,
    calls: tuple[tuple[str, str], ...] = (),
    finish_reason: str = "stop",
) -> SimpleNamespace:
    tool_calls = [
        SimpleNamespace(
            id=call_id,
            type="function",
            function=SimpleNamespace(
                name="echo",
                arguments=json.dumps(
                    {"text": text},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        for call_id, text in calls
    ]
    return SimpleNamespace(
        id="chatcmpl_offline",
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(
                    role="assistant",
                    content=content,
                    tool_calls=tool_calls or None,
                    function_call=None,
                ),
            )
        ],
        usage=None,
    )


def _runner(
    tmp_path: Path,
    outcomes: tuple[object, ...],
    *,
    context_limits: ContextLimits | None = None,
    progress_limits: ProgressLimits | None = None,
) -> tuple[AgentRunner, FakeCompletionsResource, EchoTool]:
    sdk = FakeSDKClient(*outcomes)
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )
    tool = EchoTool()
    runner = AgentRunner(
        model_client=client,
        tool_registry=ToolRegistry((tool,)),
        execution_context=ExecutionContext(tmp_path),
        context_manager=(
            ContextManager(model_client=client, limits=context_limits)
            if context_limits is not None
            else ContextManager(model_client=client)
        ),
        clock=lambda: 0.0,
        progress_limits=progress_limits,
    )
    return runner, sdk.chat.completions, tool


def _assert_legal_chat_history(messages: list[dict[str, object]]) -> None:
    index = 0
    while index < len(messages):
        message = messages[index]
        role = message["role"]
        if role == "tool":
            raise AssertionError("standalone tool message")
        if role != "assistant" or not message.get("tool_calls"):
            index += 1
            continue
        raw_calls = message["tool_calls"]
        assert isinstance(raw_calls, list)
        expected_ids = [call["id"] for call in raw_calls]
        results = messages[index + 1 : index + 1 + len(expected_ids)]
        assert len(results) == len(expected_ids)
        assert [result["role"] for result in results] == [
            "tool"
        ] * len(expected_ids)
        assert [result["tool_call_id"] for result in results] == expected_ids
        index += 1 + len(expected_ids)


def _messages(request: dict[str, object]) -> list[dict[str, object]]:
    messages = request["messages"]
    assert isinstance(messages, list)
    assert all(isinstance(message, dict) for message in messages)
    return messages


def _assert_no_server_state(request: dict[str, object]) -> None:
    assert "conversation" not in request
    assert "previous_response_id" not in request
    assert "store" not in request
    assert "continuation" not in request


def _summary_text() -> str:
    return json.dumps(
        {
            "goal": "continue the task",
            "established_facts": ["nine echo calls completed"],
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
    )


def test_text_tool_result_then_final_text_replays_complete_history(
    tmp_path: Path,
) -> None:
    runner, resource, tool = _runner(
        tmp_path,
        (
            _response(
                content="I will call echo.",
                calls=(("call_1", "one"),),
                finish_reason="stop",
            ),
            _response(content="finished"),
        ),
    )

    state = runner.run("use echo once")

    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert state.completion_text == "finished"
    assert tool.executed == [("one", tmp_path)]
    assert len(resource.calls) == 2
    second_messages = _messages(resource.calls[1])
    assert [message["role"] for message in second_messages] == [
        "user",
        "assistant",
        "tool",
    ]
    assert second_messages[1]["content"] == "I will call echo."
    assert second_messages[2]["tool_call_id"] == "call_1"
    for request in resource.calls:
        _assert_legal_chat_history(_messages(request))
        _assert_no_server_state(request)


def test_two_consecutive_tool_rounds_then_final_text_replay_all_turns(
    tmp_path: Path,
) -> None:
    runner, resource, tool = _runner(
        tmp_path,
        (
            _response(content=None, calls=(("call_1", "one"),)),
            _response(content=None, calls=(("call_2", "two"),)),
            _response(content="finished two rounds"),
        ),
    )

    state = runner.run("use echo twice")

    assert state.completion_text == "finished two rounds"
    assert tool.executed == [("one", tmp_path), ("two", tmp_path)]
    assert len(resource.calls) == 3
    assert [
        message["role"] for message in _messages(resource.calls[1])
    ] == ["user", "assistant", "tool"]
    assert [
        message["role"] for message in _messages(resource.calls[2])
    ] == ["user", "assistant", "tool", "assistant", "tool"]
    for request in resource.calls:
        _assert_legal_chat_history(_messages(request))


def test_multiple_tool_calls_keep_ordered_results_and_json_content(
    tmp_path: Path,
) -> None:
    runner, resource, tool = _runner(
        tmp_path,
        (
            _response(
                content="calling twice",
                calls=(("call_1", "one"), ("call_2", "two")),
                finish_reason="stop",
            ),
            _response(content="finished batch"),
        ),
    )

    state = runner.run("use two calls in one response")
    sent = _messages(resource.calls[1])

    assert state.completion_text == "finished batch"
    assert tool.executed == [("one", tmp_path), ("two", tmp_path)]
    assert [message["role"] for message in sent] == [
        "user",
        "assistant",
        "tool",
        "tool",
    ]
    assert [sent[2]["tool_call_id"], sent[3]["tool_call_id"]] == [
        "call_1",
        "call_2",
    ]
    for message in sent[2:]:
        content = message["content"]
        assert isinstance(content, str)
        decoded = ToolResult.from_json(content)
        assert decoded.call_id == message["tool_call_id"]
    for request in resource.calls:
        _assert_legal_chat_history(_messages(request))


def test_compressed_history_remains_legal_and_continues_chat(
    tmp_path: Path,
) -> None:
    outcomes = tuple(
        _response(
            content=None,
            calls=((f"call_{index}", f"value {index}"),),
        )
        for index in range(9)
    ) + (
        _response(content=_summary_text()),
        _response(content="continued after compression"),
    )
    runner, resource, tool = _runner(
        tmp_path,
        outcomes,
        context_limits=ContextLimits(
            max_serialized_chars=60_000,
            max_history_items=20,
            recent_turns=8,
            compression_target_items=18,
        ),
        progress_limits=ProgressLimits(100, 100, 100, 100, 1),
    )

    state = runner.run("compress legal Chat history")

    assert state.completion_text == "continued after compression"
    assert state.continuation_items == ()
    assert tool.executed == [
        (f"value {index}", tmp_path) for index in range(9)
    ]
    assert len(resource.calls) == 11
    assert "tools" not in resource.calls[9]
    final_messages = _messages(resource.calls[10])
    assert len(final_messages) == 19
    assert final_messages[0]["role"] == "system"
    assert str(final_messages[0]["content"]).startswith("Exploration coverage:")
    assert final_messages[1]["role"] == "user"
    assert final_messages[2]["role"] == "user"
    summary = final_messages[2]["content"]
    assert isinstance(summary, str)
    assert summary.startswith("coding-agent context summary\n")
    for request in resource.calls:
        _assert_legal_chat_history(_messages(request))


def test_every_request_has_exact_assistant_tool_pairing(
    tmp_path: Path,
) -> None:
    runner, resource, tool = _runner(
        tmp_path,
        (
            _response(
                content=None,
                calls=(("pair_1", "one"), ("pair_2", "two")),
            ),
            _response(content=None, calls=(("pair_3", "three"),)),
            _response(content="pairing complete"),
        ),
    )

    state = runner.run("verify every pairing")

    assert state.completion_text == "pairing complete"
    assert tool.executed == [
        ("one", tmp_path),
        ("two", tmp_path),
        ("three", tmp_path),
    ]
    for request in resource.calls:
        messages = _messages(request)
        _assert_legal_chat_history(messages)
        declared = [
            call["id"]
            for message in messages
            if message["role"] == "assistant"
            for call in message.get("tool_calls", [])
        ]
        returned = [
            message["tool_call_id"]
            for message in messages
            if message["role"] == "tool"
        ]
        assert returned == declared
        assert len(returned) == len(set(returned))

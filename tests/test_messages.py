from __future__ import annotations

import json
import subprocess
import sys

import pytest

from coding_agent.messages import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    TokenUsage,
    ToolCall,
    ToolResult,
    ToolResultMetadata,
    UserMessage,
)


def test_tool_call_and_result_round_trip() -> None:
    call = ToolCall(
        call_id=" call_123 ",
        name=" read_file ",
        arguments={"path": "src/example.py", "end_line": None},
    )
    result = ToolResult(
        call_id="call_123",
        tool_name="read_file",
        status="ok",
        output="contents",
        metadata=ToolResultMetadata(duration_ms=8),
    )

    assert call.call_id == result.call_id == "call_123"
    assert ToolCall.from_json(call.to_json()) == call
    assert ToolResult.from_json(result.to_json()) == result
    assert json.loads(call.to_json()) == {
        "arguments": {"end_line": None, "path": "src/example.py"},
        "id": "call_123",
        "kind": "tool_call",
        "name": "read_file",
    }


def test_tool_result_serializes_explicit_nulls() -> None:
    result = ToolResult(
        call_id="call_1",
        tool_name="list_directory",
        status="ok",
    )

    payload = json.loads(result.to_json())
    assert payload["output"] is None
    assert payload["error"] is None
    assert payload["metadata"] == {
        "changed_paths": [],
        "duration_ms": 0,
        "exit_code": None,
        "timed_out": False,
        "truncated": False,
    }


@pytest.mark.parametrize("status", ["success", "failed", "", None])
def test_tool_result_rejects_invalid_status(status: object) -> None:
    with pytest.raises(ValueError, match="status"):
        ToolResult(
            call_id="call_1",
            tool_name="read_file",
            status=status,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("call_id", ["", "   "])
def test_tool_call_rejects_empty_call_id(call_id: str) -> None:
    with pytest.raises(ValueError, match="call_id"):
        ToolCall(call_id=call_id, name="read_file", arguments={})


@pytest.mark.parametrize("call_id", ["", "   "])
def test_tool_result_rejects_empty_call_id(call_id: str) -> None:
    with pytest.raises(ValueError, match="call_id"):
        ToolResult(call_id=call_id, tool_name="read_file", status="ok")


def test_error_result_requires_error_text() -> None:
    with pytest.raises(ValueError, match="error is required"):
        ToolResult(call_id="call_1", tool_name="read_file", status="error")


def test_ok_result_rejects_error_text() -> None:
    with pytest.raises(ValueError, match="error must be null"):
        ToolResult(
            call_id="call_1",
            tool_name="read_file",
            status="ok",
            error="unexpected",
        )


def test_metadata_rejects_negative_duration() -> None:
    with pytest.raises(ValueError, match="duration_ms"):
        ToolResultMetadata(duration_ms=-1)


def test_from_dict_rejects_missing_required_field() -> None:
    with pytest.raises(ValueError, match="missing fields: name"):
        ToolCall.from_dict(
            {"kind": "tool_call", "id": "call_1", "arguments": {}}
        )


def test_user_and_assistant_messages_round_trip() -> None:
    user = UserMessage(content="inspect the project")
    assistant = AssistantMessage(content="I will inspect it.")

    assert UserMessage.from_json(user.to_json()) == user
    assert AssistantMessage.from_json(assistant.to_json()) == assistant
    assert json.loads(user.to_json()) == {
        "content": "inspect the project",
        "kind": "user",
    }


def test_assistant_tool_message_serializes_explicit_null() -> None:
    call = ToolCall(
        call_id="call_1",
        name="list_directory",
        arguments={"path": "."},
    )
    assistant = AssistantMessage(content=None, tool_calls=(call,))

    payload = json.loads(assistant.to_json())
    assert payload["content"] is None
    assert payload["tool_calls"] == [call.to_dict()]


def test_assistant_rejects_duplicate_call_id() -> None:
    first = ToolCall(
        call_id="call_1",
        name="read_file",
        arguments={"path": "a.py"},
    )
    second = ToolCall(
        call_id="call_1",
        name="read_file",
        arguments={"path": "b.py"},
    )

    with pytest.raises(ValueError, match="duplicate call_id: call_1"):
        AssistantMessage(content=None, tool_calls=(first, second))


def test_model_request_accepts_paired_tool_result() -> None:
    call = ToolCall(
        call_id="call_1",
        name="read_file",
        arguments={"path": "a.py"},
    )
    request = ModelRequest(
        messages=(
            UserMessage("inspect"),
            AssistantMessage(content=None, tool_calls=(call,)),
            ToolResult(
                call_id="call_1",
                tool_name="read_file",
                status="ok",
                output="contents",
            ),
        ),
        tool_schemas=({"name": "read_file", "strict": True},),
        continuation_items=(object(),),
    )

    restored = ModelRequest.from_json(request.to_json())
    assert restored == request
    assert restored.continuation_items == ()
    assert "continuation_items" not in json.loads(request.to_json())


def test_model_request_rejects_unmatched_result() -> None:
    with pytest.raises(ValueError, match="unmatched call_id: call_1"):
        ModelRequest(
            messages=(
                UserMessage("inspect"),
                ToolResult(
                    call_id="call_1",
                    tool_name="read_file",
                    status="ok",
                ),
            )
        )


def test_model_request_rejects_tool_name_mismatch() -> None:
    call = ToolCall(call_id="call_1", name="read_file", arguments={})

    with pytest.raises(ValueError, match="tool_name mismatch for call_id: call_1"):
        ModelRequest(
            messages=(
                UserMessage("inspect"),
                AssistantMessage(content=None, tool_calls=(call,)),
                ToolResult(
                    call_id="call_1",
                    tool_name="list_directory",
                    status="ok",
                ),
            )
        )


def test_model_request_rejects_unresolved_call() -> None:
    call = ToolCall(call_id="call_1", name="read_file", arguments={})

    with pytest.raises(ValueError, match="unresolved call_id: call_1"):
        ModelRequest(
            messages=(
                UserMessage("inspect"),
                AssistantMessage(content=None, tool_calls=(call,)),
            )
        )


def test_model_request_rejects_reused_call_id() -> None:
    first = ToolCall(call_id="call_1", name="read_file", arguments={})
    reused = ToolCall(call_id="call_1", name="list_directory", arguments={})

    with pytest.raises(ValueError, match="duplicate call_id: call_1"):
        ModelRequest(
            messages=(
                UserMessage("inspect"),
                AssistantMessage(content=None, tool_calls=(first,)),
                ToolResult(
                    call_id="call_1",
                    tool_name="read_file",
                    status="ok",
                ),
                AssistantMessage(content=None, tool_calls=(reused,)),
                ToolResult(
                    call_id="call_1",
                    tool_name="list_directory",
                    status="ok",
                ),
            )
        )


def test_model_response_round_trip_preserves_order() -> None:
    first = ToolCall(
        call_id="call_1",
        name="read_file",
        arguments={"path": "a.py"},
    )
    second = ToolCall(
        call_id="call_2",
        name="read_file",
        arguments={"path": "b.py"},
    )
    response = ModelResponse(
        text="inspection complete",
        tool_calls=(first, second),
        usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        provider_response_id="resp_1",
    )

    restored = ModelResponse.from_json(response.to_json())
    assert restored == response
    assert restored.tool_calls == (first, second)


def test_model_response_serializes_explicit_nulls() -> None:
    payload = json.loads(ModelResponse().to_json())

    assert payload == {
        "provider_response_id": None,
        "text": None,
        "tool_calls": [],
        "usage": None,
    }


def test_model_response_rejects_duplicate_call_id() -> None:
    first = ToolCall(
        call_id="call_1",
        name="read_file",
        arguments={"path": "a.py"},
    )
    second = ToolCall(
        call_id="call_1",
        name="read_file",
        arguments={"path": "b.py"},
    )

    with pytest.raises(ValueError, match="duplicate call_id: call_1"):
        ModelResponse(tool_calls=(first, second))


def test_model_response_omits_opaque_continuation_items() -> None:
    marker = object()
    response = ModelResponse(
        text="done",
        continuation_items=(marker,),
    )

    payload = json.loads(response.to_json())
    restored = ModelResponse.from_json(response.to_json())
    assert "continuation_items" not in payload
    assert repr(marker) not in repr(response)
    assert restored == response
    assert restored.continuation_items == ()


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_token_usage_rejects_invalid_counts(value: object) -> None:
    with pytest.raises(ValueError, match="input_tokens"):
        TokenUsage(
            input_tokens=value,  # type: ignore[arg-type]
            output_tokens=0,
            total_tokens=0,
        )


def test_messages_module_imports_without_openai() -> None:
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "openai" or name.startswith("openai."):
        raise AssertionError("coding_agent.messages imported OpenAI SDK")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import coding_agent.messages
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr

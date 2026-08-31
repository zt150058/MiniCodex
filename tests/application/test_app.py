from __future__ import annotations

from collections import deque
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace as ns
from typing import BinaryIO

import pytest

from coding_agent.application.app import (
    ApplicationFactories,
    execute_agent_run,
    production_factories,
    run_application,
)
from coding_agent.providers.chat_completions_client import ChatCompletionsModelClient
from coding_agent.application.config import ApiMode, RunConfig, load_run_config
from coding_agent.engine.instructions import RunInstructionBuilder
from coding_agent.engine.logging import (
    EventType,
    RunEvent,
    RunEventLogger,
    RunLogError,
    RunMetadata,
)
from coding_agent.engine.messages import (
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResultMetadata,
)
from coding_agent.engine.model import FakeModelClient, ModelClient
from coding_agent.engine.run_mode import RunMode
from coding_agent.operations.safety import AuthorizedCommand
from coding_agent.engine.state import AgentStatus
from coding_agent.engine.streaming import ModelStreamEvent, ModelStreamEventKind
from coding_agent.operations.tools.base import ExecutionContext, ToolExecution


FAKE_KEY = "task13-obviously-fake-key"
CHAT_FAKE_KEY = "task15-chat-obviously-fake-key"


class FakeChatStream:
    def __init__(self, chunks: tuple[object, ...]) -> None:
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        yield from self.chunks

    def close(self) -> None:
        self.closed = True


class FakeChatCompletions:
    def __init__(self, *outcomes: object) -> None:
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


class FakeChatSDK:
    def __init__(self, *outcomes: object) -> None:
        self.chat = ns(completions=FakeChatCompletions(*outcomes))


def _invalid_chat_stream() -> FakeChatStream:
    return FakeChatStream(
        (
            ns(
                id="chat-stream",
                choices=[
                    ns(
                        index=0,
                        delta=ns(
                            role=None,
                            content=None,
                            tool_calls=None,
                            function_call=None,
                            refusal=None,
                        ),
                        finish_reason=None,
                    )
                ],
                usage=None,
            ),
        )
    )


def _sync_chat_text(text: str) -> object:
    return ns(
        id="chat-sync",
        choices=[
            ns(
                finish_reason="stop",
                message=ns(
                    role="assistant",
                    content=text,
                    tool_calls=None,
                    function_call=None,
                ),
            )
        ],
        usage=None,
    )


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[AuthorizedCommand, ExecutionContext]] = []

    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
        *,
        stdin_stream: BinaryIO | None = None,
    ) -> ToolExecution:
        self.calls.append((command, context))
        return ToolExecution(
            output=json.dumps(
                {
                    "argv": list(command.argv),
                    "cleanup_error": None,
                    "purpose": command.purpose,
                    "stderr": "",
                    "stdout": "1 passed",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            metadata=ToolResultMetadata(exit_code=0, duration_ms=3),
        )


class CloseFailingLogger:
    def __init__(self, wrapped: RunEventLogger) -> None:
        self.wrapped = wrapped
        self.close_calls = 0

    @property
    def metadata(self) -> RunMetadata:
        return self.wrapped.metadata

    def emit(self, event_type: EventType, data: dict[str, object]) -> RunEvent:
        return self.wrapped.emit(event_type, data)  # type: ignore[arg-type]

    def observe_model(self, observation: object) -> None:
        self.wrapped.observe_model(observation)  # type: ignore[arg-type]

    def close(self) -> None:
        self.close_calls += 1
        self.wrapped.close()
        self.metadata.log_failure_code = "log_close_failed"
        raise RunLogError("log_close_failed")


class InterruptingModelClient:
    def complete(self, request: ModelRequest) -> ModelResponse:
        raise KeyboardInterrupt


class UnexpectedCloseLogger:
    def __init__(self, wrapped: RunEventLogger) -> None:
        self.wrapped = wrapped

    @property
    def metadata(self) -> RunMetadata:
        return self.wrapped.metadata

    def emit(self, event_type: EventType, data: dict[str, object]) -> RunEvent:
        return self.wrapped.emit(event_type, data)  # type: ignore[arg-type]

    def observe_model(self, observation: object) -> None:
        self.wrapped.observe_model(observation)  # type: ignore[arg-type]

    def close(self) -> None:
        self.wrapped.close()
        raise RuntimeError("private provider payload " + FAKE_KEY)


class RaisingWriter:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def write(self, value: str) -> int:
        raise self.error


def _config(workspace: Path) -> RunConfig:
    return load_run_config(
        task="repair demo",
        workspace=workspace,
        model="fake-model",
        verify_command="pytest -q",
        environ={"OPENAI_API_KEY": FAKE_KEY},
    )


def _chat_config(workspace: Path) -> RunConfig:
    return load_run_config(
        task="repair chat demo",
        workspace=workspace,
        model="chat-model",
        verify_command="pytest -q",
        api_mode="chat-completions",
        base_url="https://provider.example/api/v1",
        environ={"CHAT_COMPLETIONS_API_KEY": CHAT_FAKE_KEY},
    )


def _read_only_config(workspace: Path) -> RunConfig:
    return load_run_config(
        task="inspect demo",
        workspace=workspace,
        model="fake-model",
        verify_command=None,
        run_mode=RunMode.READ_ONLY,
        environ={"OPENAI_API_KEY": FAKE_KEY},
    )


def _optional_modify_config(workspace: Path) -> RunConfig:
    return load_run_config(
        task="create README",
        workspace=workspace,
        model="fake-model",
        verify_command=None,
        run_mode=RunMode.MODIFY,
        environ={"OPENAI_API_KEY": FAKE_KEY},
    )


def _successful_factories() -> ApplicationFactories:
    executor = RecordingExecutor()

    def logger_factory(config: RunConfig, clock: object) -> RunEventLogger:
        return RunEventLogger.create(
            config.workspace,
            run_id="5" * 32,
            sensitive_values=(config.api_key,),
            monotonic_clock=clock,  # type: ignore[arg-type]
        )

    return ApplicationFactories(
        model_client=lambda config: FakeModelClient((ModelResponse(text="done"),)),
        logger=logger_factory,
        command_executor=lambda: executor,  # type: ignore[arg-type]
        clock=lambda: 0.0,
    )


def _factories_with_model_client(
    workspace: Path,
    client: ModelClient,
    *,
    run_id: str,
) -> ApplicationFactories:
    executor = RecordingExecutor()

    def logger_factory(config: RunConfig, clock: object) -> RunEventLogger:
        assert config.workspace == workspace.resolve(strict=True)
        return RunEventLogger.create(
            config.workspace,
            run_id=run_id,
            sensitive_values=(config.api_key,),
            monotonic_clock=clock,  # type: ignore[arg-type]
        )

    return ApplicationFactories(
        model_client=lambda config: client,
        logger=logger_factory,
        command_executor=lambda: executor,  # type: ignore[arg-type]
        clock=lambda: 0.0,
    )


def test_modify_run_composes_exact_seven_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeModelClient((ModelResponse(text="done"),))
    gate_calls = 0
    from coding_agent.application import app as app_module

    original_gate = app_module.VerificationGate

    def recording_gate(*args: object, **kwargs: object) -> object:
        nonlocal gate_calls
        gate_calls += 1
        return original_gate(*args, **kwargs)

    monkeypatch.setattr(app_module, "VerificationGate", recording_gate)
    result = execute_agent_run(
        _config(tmp_path),
        factories=_factories_with_model_client(
            tmp_path,
            client,
            run_id="a" * 32,
        ),
    )

    assert result.report.status is AgentStatus.SUCCESS
    assert tuple(schema["name"] for schema in client.requests[0].tool_schemas) == (
        "list_directory",
        "read_file",
        "create_directory",
        "replace_text",
        "write_file",
        "run_command",
        "run_java_tests",
    )
    assert gate_calls == 1


def test_optional_modify_run_writes_readme_and_uses_local_integrity(
    tmp_path: Path,
) -> None:
    client = FakeModelClient(
        (
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        call_id="write-readme",
                        name="write_file",
                        arguments={
                            "path": "README.md",
                            "content": "# Demo\n\nLocal coding agent.\n",
                        },
                    ),
                )
            ),
            ModelResponse(text="README created."),
        )
    )

    result = execute_agent_run(
        _optional_modify_config(tmp_path),
        factories=_factories_with_model_client(
            tmp_path,
            client,
            run_id="d" * 32,
        ),
    )

    assert result.report.status is AgentStatus.SUCCESS
    assert result.report.verification.source is not None
    assert result.report.verification.source.value == "local_integrity"
    assert result.report.mutation_index == result.report.validation_index == 1
    assert (tmp_path / "README.md").read_text(encoding="utf-8").startswith(
        "# Demo"
    )


def test_optional_modify_run_creates_directory_project_in_one_batch(
    tmp_path: Path,
) -> None:
    source = "int main() { return 0; }\n"
    client = FakeModelClient(
        (
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        call_id="mkdir-snake",
                        name="create_directory",
                        arguments={"path": "snake"},
                    ),
                    ToolCall(
                        call_id="write-main",
                        name="write_file",
                        arguments={"path": "snake/main.cpp", "content": source},
                    ),
                )
            ),
            ModelResponse(text="Snake project created."),
        )
    )

    result = execute_agent_run(
        _optional_modify_config(tmp_path),
        factories=_factories_with_model_client(
            tmp_path,
            client,
            run_id="f" * 32,
        ),
    )

    assert result.report.status is AgentStatus.SUCCESS
    assert result.state.verification_attempt_count == 1
    assert result.state.mutation_index == result.state.validation_index == 2
    assert result.state.modified_paths == ("snake", "snake/main.cpp")
    assert (tmp_path / "snake").is_dir()
    assert (tmp_path / "snake" / "main.cpp").read_text(
        encoding="utf-8"
    ) == source


def test_optional_modify_capability_can_answer_without_mutation(
    tmp_path: Path,
) -> None:
    client = FakeModelClient((ModelResponse(text="Superpowers is a skill workflow."),))

    result = execute_agent_run(
        _optional_modify_config(tmp_path),
        factories=_factories_with_model_client(
            tmp_path,
            client,
            run_id="e" * 32,
        ),
    )

    assert result.report.status is AgentStatus.ANSWERED
    assert result.report.exit_code == 0
    assert result.report.mutation_index == 0
    assert result.report.verification.status.value == "not_run"
    assert len(client.requests) == 1


def test_read_only_run_composes_only_inspection_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeModelClient((ModelResponse(text="inspection complete"),))

    def forbidden_gate(*args: object, **kwargs: object) -> object:
        raise AssertionError("read-only run must not construct a verification gate")

    monkeypatch.setattr("coding_agent.application.app.VerificationGate", forbidden_gate)
    result = execute_agent_run(
        _read_only_config(tmp_path),
        factories=_factories_with_model_client(
            tmp_path,
            client,
            run_id="b" * 32,
        ),
    )

    assert result.report.status is AgentStatus.ANSWERED
    assert tuple(schema["name"] for schema in client.requests[0].tool_schemas) == (
        "list_directory",
        "read_file",
        "inspect_git",
    )


def test_read_only_stream_fallback_keeps_three_inspection_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CHAT_COMPLETIONS_API_KEY", raising=False)
    sdk = FakeChatSDK(_invalid_chat_stream(), _sync_chat_text("inspection done"))
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=CHAT_FAKE_KEY,
        base_url="https://offline-provider.example/api/v1",
        sdk_client=sdk,
    )
    events: list[ModelStreamEvent] = []

    result = execute_agent_run(
        _read_only_config(tmp_path),
        factories=_factories_with_model_client(
            tmp_path,
            client,
            run_id="1" * 32,
        ),
        stream_handler=events.append,
    )

    assert result.report.status is AgentStatus.ANSWERED
    assert result.state.completion_text == "inspection done"
    assert [event.kind for event in events] == [
        ModelStreamEventKind.RESPONSE_COMPLETED
    ]
    assert len(sdk.chat.completions.calls) == 2
    for call in sdk.chat.completions.calls:
        tools = call["tools"]
        assert isinstance(tools, list)
        assert [tool["function"]["name"] for tool in tools] == [
            "list_directory",
            "read_file",
            "inspect_git",
        ]


def test_read_only_unknown_write_is_paired_and_never_executed(
    tmp_path: Path,
) -> None:
    target = tmp_path / "must-not-exist.txt"
    client = FakeModelClient(
        (
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        call_id="write-1",
                        name="write_file",
                        arguments={
                            "path": target.name,
                            "content": "forbidden",
                        },
                    ),
                )
            ),
            ModelResponse(text="write was unavailable"),
        )
    )

    result = execute_agent_run(
        _read_only_config(tmp_path),
        factories=_factories_with_model_client(
            tmp_path,
            client,
            run_id="c" * 32,
        ),
    )

    assert result.report.status is AgentStatus.ANSWERED
    assert target.exists() is False
    tool_results = [
        message
        for message in client.requests[1].messages
        if getattr(message, "call_id", None) == "write-1"
    ]
    assert len(tool_results) == 1
    assert tool_results[0].status == "rejected"
    assert tool_results[0].error == (
        "unknown_tool: no tool registered as 'write_file'"
    )


def test_execute_agent_run_includes_selected_skill_in_main_request_only(
    tmp_path: Path,
) -> None:
    client = FakeModelClient((ModelResponse(text="done"),))
    factories = _factories_with_model_client(
        tmp_path,
        client,
        run_id="6" * 32,
    )
    private_body = "private selected instructions"
    result = execute_agent_run(
        _config(tmp_path),
        factories=factories,
        skill_instructions=f"### Skill: review — Review\n{private_body}",
    )
    assert result.report.status.value == "success"
    assert client.requests
    instructions = client.requests[0].instructions
    assert instructions is not None
    assert "## Selected skill instructions" in instructions
    assert private_body in instructions
    assert private_body not in json.dumps(result.report.to_dict(), ensure_ascii=False)
    assert private_body not in (tmp_path / result.report.log_path).read_text(
        encoding="utf-8"
    )


def test_chat_selected_skill_survives_invalid_stream_sync_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CHAT_COMPLETIONS_API_KEY", raising=False)
    sdk = FakeChatSDK(_invalid_chat_stream(), _sync_chat_text("review complete"))
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=CHAT_FAKE_KEY,
        base_url="https://offline-provider.example/api/v1",
        sdk_client=sdk,
    )
    private_body = "selected skill private sentinel"
    observed_events: list[RunEvent] = []
    stream_events: list[ModelStreamEvent] = []

    result = execute_agent_run(
        _chat_config(tmp_path),
        factories=_factories_with_model_client(
            tmp_path,
            client,
            run_id="2" * 32,
        ),
        skill_instructions=f"### Skill: review — Review\n{private_body}",
        event_observer=observed_events.append,
        stream_handler=stream_events.append,
    )

    assert result.report.status is AgentStatus.SUCCESS
    assert len(sdk.chat.completions.calls) == 2
    assert [event.kind for event in stream_events] == [
        ModelStreamEventKind.RESPONSE_COMPLETED
    ]
    for call in sdk.chat.completions.calls:
        messages = call["messages"]
        assert isinstance(messages, list)
        assert private_body in str(messages[0]["content"])
    public_surfaces = (
        repr(result)
        + repr(observed_events)
        + json.dumps(result.report.to_dict(), ensure_ascii=False)
        + (tmp_path / result.report.log_path).read_text(encoding="utf-8")
    )
    assert private_body not in public_surfaces


def test_execute_agent_run_without_skills_preserves_existing_instructions(
    tmp_path: Path,
) -> None:
    first_client = FakeModelClient((ModelResponse(text="done"),))
    second_client = FakeModelClient((ModelResponse(text="done"),))
    execute_agent_run(
        _config(tmp_path),
        factories=_factories_with_model_client(
            tmp_path,
            first_client,
            run_id="7" * 32,
        ),
    )
    execute_agent_run(
        _config(tmp_path),
        factories=_factories_with_model_client(
            tmp_path,
            second_client,
            run_id="8" * 32,
        ),
        skill_instructions=None,
    )
    first_instructions = first_client.requests[0].instructions
    assert first_instructions == second_client.requests[0].instructions
    assert first_instructions is not None
    assert "## Selected skill instructions" not in first_instructions


def test_production_factory_selects_responses_adapter_without_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    calls: list[tuple[str, str]] = []
    stand_in = FakeModelClient((ModelResponse(text="unused"),))

    def fake_constructor(*, model: str, api_key: str) -> ModelClient:
        calls.append((model, api_key))
        return stand_in

    def forbidden_chat_constructor(
        *, model: str, api_key: str, base_url: str
    ) -> ModelClient:
        raise AssertionError("Chat adapter must not be constructed")

    monkeypatch.setattr(
        "coding_agent.application.app.OpenAIResponsesClient",
        fake_constructor,
    )
    monkeypatch.setattr(
        "coding_agent.application.app.ChatCompletionsModelClient",
        forbidden_chat_constructor,
    )

    selected = production_factories().model_client(config)

    assert selected is stand_in
    assert calls == [(config.model, config.api_key)]
    assert stand_in.requests == ()


def test_production_factory_selects_chat_adapter_without_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _chat_config(tmp_path)
    calls: list[tuple[str, str, str]] = []
    stand_in = FakeModelClient((ModelResponse(text="unused"),))

    def fake_chat_constructor(
        *, model: str, api_key: str, base_url: str
    ) -> ModelClient:
        calls.append((model, api_key, base_url))
        return stand_in

    def forbidden_responses_constructor(
        *, model: str, api_key: str
    ) -> ModelClient:
        raise AssertionError("Responses adapter must not be constructed")

    monkeypatch.setattr(
        "coding_agent.application.app.ChatCompletionsModelClient",
        fake_chat_constructor,
    )
    monkeypatch.setattr(
        "coding_agent.application.app.OpenAIResponsesClient",
        forbidden_responses_constructor,
    )

    selected = production_factories().model_client(config)

    assert config.api_mode is ApiMode.CHAT_COMPLETIONS
    assert selected is stand_in
    assert calls == [(config.model, config.api_key, config.base_url)]
    assert stand_in.requests == ()


def test_chat_key_is_absent_from_config_output_report_and_jsonl(
    tmp_path: Path,
) -> None:
    config = _chat_config(tmp_path)
    stdout = StringIO()
    stderr = StringIO()

    code = run_application(
        config,
        stdout=stdout,
        stderr=stderr,
        factories=_successful_factories(),
    )

    payload = json.loads(stdout.getvalue())
    log_path = tmp_path / payload["log_path"]
    rendered = (
        repr(config)
        + stdout.getvalue()
        + stderr.getvalue()
        + log_path.read_text(encoding="utf-8")
    )
    assert code == 0
    assert CHAT_FAKE_KEY not in rendered


def test_composition_uses_fixed_tools_and_shared_executor(tmp_path: Path) -> None:
    config = _config(tmp_path)
    model = FakeModelClient((ModelResponse(text="done"),))
    executor = RecordingExecutor()
    executor_factory_calls = 0

    def model_factory(received: RunConfig) -> ModelClient:
        assert received is config
        return model

    def logger_factory(
        received: RunConfig,
        clock: object,
    ) -> RunEventLogger:
        assert received is config
        assert callable(clock)
        return RunEventLogger.create(
            received.workspace,
            run_id="1" * 32,
            sensitive_values=(received.api_key,),
            monotonic_clock=clock,  # type: ignore[arg-type]
        )

    def executor_factory() -> RecordingExecutor:
        nonlocal executor_factory_calls
        executor_factory_calls += 1
        return executor

    stdout = StringIO()
    stderr = StringIO()
    code = run_application(
        config,
        stdout=stdout,
        stderr=stderr,
        factories=ApplicationFactories(
            model_client=model_factory,
            logger=logger_factory,
            command_executor=executor_factory,  # type: ignore[arg-type]
            clock=lambda: 0.0,
        ),
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue())["status"] == "success"
    assert executor_factory_calls == 1
    assert len(executor.calls) == 1
    assert executor.calls[0][0] is config.verify_command
    assert executor.calls[0][1].workspace == config.workspace
    assert [schema["name"] for schema in model.requests[0].tool_schemas] == [
        "list_directory",
        "read_file",
        "create_directory",
        "replace_text",
        "write_file",
        "run_command",
        "run_java_tests",
    ]


def test_execute_agent_run_matches_run_application_report(tmp_path: Path) -> None:
    direct_workspace = tmp_path / "direct"
    application_workspace = tmp_path / "application"
    direct_workspace.mkdir()
    application_workspace.mkdir()
    direct = execute_agent_run(
        _config(direct_workspace),
        factories=_successful_factories(),
    )
    stdout = StringIO()
    stderr = StringIO()
    code = run_application(
        _config(application_workspace),
        stdout=stdout,
        stderr=stderr,
        factories=_successful_factories(),
    )
    assert stderr.getvalue() == ""
    assert code == direct.report.exit_code
    assert json.loads(stdout.getvalue()) == direct.report.to_dict()


def test_composition_builds_private_run_instructions_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "workspace instruction sentinel"
    (tmp_path / "AGENTS.md").write_text(sentinel, encoding="utf-8")
    config = _config(tmp_path)
    model = FakeModelClient((ModelResponse(text="done"),))
    factories = _successful_factories()
    original = RunInstructionBuilder.build
    calls = 0

    def counting_build(
        builder: RunInstructionBuilder,
        workspace: Path,
        *,
        skill_instructions: str | None = None,
        run_mode: RunMode = RunMode.MODIFY,
    ) -> object:
        nonlocal calls
        calls += 1
        return original(
            builder,
            workspace,
            skill_instructions=skill_instructions,
            run_mode=run_mode,
        )

    monkeypatch.setattr(RunInstructionBuilder, "build", counting_build)
    stdout = StringIO()
    stderr = StringIO()

    code = run_application(
        config,
        stdout=stdout,
        stderr=stderr,
        factories=ApplicationFactories(
            model_client=lambda received: model,
            logger=factories.logger,
            command_executor=factories.command_executor,
            clock=factories.clock,
        ),
    )

    payload = json.loads(stdout.getvalue())
    raw_log = (tmp_path / payload["log_path"]).read_text(encoding="utf-8")
    assert code == 0
    assert calls == 1
    assert "## MiniCodex base instructions" in model.requests[0].instructions
    assert sentinel in model.requests[0].instructions
    assert sentinel not in raw_log


def test_logger_create_failure_stops_before_agent(tmp_path: Path) -> None:
    config = _config(tmp_path)
    model = FakeModelClient((ModelResponse(text="must not run"),))
    executor = RecordingExecutor()

    def fail_logger(config: RunConfig, clock: object) -> RunEventLogger:
        raise RunLogError("log_path_reparse")

    stdout = StringIO()
    stderr = StringIO()
    code = run_application(
        config,
        stdout=stdout,
        stderr=stderr,
        factories=ApplicationFactories(
            model_client=lambda config: model,
            logger=fail_logger,  # type: ignore[arg-type]
            command_executor=lambda: executor,  # type: ignore[arg-type]
            clock=lambda: 0.0,
        ),
    )

    assert code == 1
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "error: audit log unavailable (log_path_reparse)\n"
    assert model.requests == ()
    assert executor.calls == []


def test_close_failure_downgrades_success_before_output(tmp_path: Path) -> None:
    config = _config(tmp_path)
    model = FakeModelClient((ModelResponse(text="done"),))
    executor = RecordingExecutor()
    failing: list[CloseFailingLogger] = []

    def logger_factory(config: RunConfig, clock: object) -> RunEventLogger:
        logger = CloseFailingLogger(
            RunEventLogger.create(
                config.workspace,
                run_id="2" * 32,
                sensitive_values=(config.api_key,),
                monotonic_clock=clock,  # type: ignore[arg-type]
            )
        )
        failing.append(logger)
        return logger  # type: ignore[return-value]

    stdout = StringIO()
    stderr = StringIO()
    code = run_application(
        config,
        stdout=stdout,
        stderr=stderr,
        factories=ApplicationFactories(
            model_client=lambda config: model,
            logger=logger_factory,
            command_executor=lambda: executor,  # type: ignore[arg-type]
            clock=lambda: 0.0,
        ),
    )

    payload = json.loads(stdout.getvalue())
    assert code == payload["exit_code"] == 1
    assert payload["status"] == "failed"
    assert payload["termination_reason"] == "audit_log_failure"
    assert payload["log_failure_code"] == "log_close_failed"
    assert stderr.getvalue() == ""
    assert failing[0].close_calls == 1
    assert stdout.getvalue().count('"schema_version"') == 1


def test_agent_interrupt_closes_and_reports_130(tmp_path: Path) -> None:
    config = _config(tmp_path)
    logger_holder: list[RunEventLogger] = []

    def logger_factory(config: RunConfig, clock: object) -> RunEventLogger:
        logger = RunEventLogger.create(
            config.workspace,
            run_id="3" * 32,
            sensitive_values=(config.api_key,),
            monotonic_clock=clock,  # type: ignore[arg-type]
        )
        logger_holder.append(logger)
        return logger

    stdout = StringIO()
    stderr = StringIO()
    code = run_application(
        config,
        stdout=stdout,
        stderr=stderr,
        factories=ApplicationFactories(
            model_client=lambda config: InterruptingModelClient(),
            logger=logger_factory,
            command_executor=RecordingExecutor,  # type: ignore[arg-type]
            clock=lambda: 0.0,
        ),
    )

    payload = json.loads(stdout.getvalue())
    assert code == payload["exit_code"] == 130
    assert payload["status"] == "interrupted"
    assert payload["termination_reason"] == "user_interrupted"
    assert stderr.getvalue() == ""
    assert logger_holder[0]._closed is True  # type: ignore[attr-defined]


def test_internal_failure_is_stable_and_redacted(tmp_path: Path) -> None:
    config = _config(tmp_path)
    logger_holder: list[UnexpectedCloseLogger] = []

    def logger_factory(config: RunConfig, clock: object) -> RunEventLogger:
        logger = UnexpectedCloseLogger(
            RunEventLogger.create(
                config.workspace,
                run_id="4" * 32,
                sensitive_values=(config.api_key,),
                monotonic_clock=clock,  # type: ignore[arg-type]
            )
        )
        logger_holder.append(logger)
        return logger  # type: ignore[return-value]

    stdout = StringIO()
    stderr = StringIO()
    code = run_application(
        config,
        stdout=stdout,
        stderr=stderr,
        factories=ApplicationFactories(
            model_client=lambda config: FakeModelClient((ModelResponse(text="done"),)),
            logger=logger_factory,
            command_executor=RecordingExecutor,  # type: ignore[arg-type]
            clock=lambda: 0.0,
        ),
    )

    assert code == 1
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "error: internal application failure\n"
    assert FAKE_KEY not in stderr.getvalue()
    assert "private provider payload" not in stderr.getvalue()
    assert logger_holder[0].wrapped._closed is True  # type: ignore[attr-defined]


def test_final_report_stdout_oserror_is_stable_and_redacted(tmp_path: Path) -> None:
    stderr = StringIO()

    code = run_application(
        _config(tmp_path),
        stdout=RaisingWriter(OSError("private output path " + FAKE_KEY)),  # type: ignore[arg-type]
        stderr=stderr,
        factories=_successful_factories(),
    )

    assert code == 1
    assert stderr.getvalue() == "error: final report output failed\n"
    assert FAKE_KEY not in stderr.getvalue()
    assert "private output path" not in stderr.getvalue()


def test_closed_stdout_is_a_stable_application_failure(tmp_path: Path) -> None:
    stdout = StringIO()
    stdout.close()
    stderr = StringIO()

    code = run_application(
        _config(tmp_path),
        stdout=stdout,
        stderr=stderr,
        factories=_successful_factories(),
    )

    assert code == 1
    assert stderr.getvalue() == "error: final report output failed\n"


def test_stdout_and_stderr_failure_returns_without_recursive_reporting(
    tmp_path: Path,
) -> None:
    code = run_application(
        _config(tmp_path),
        stdout=RaisingWriter(OSError("stdout failed")),  # type: ignore[arg-type]
        stderr=RaisingWriter(OSError("stderr failed")),  # type: ignore[arg-type]
        factories=_successful_factories(),
    )

    assert code == 1


@pytest.mark.parametrize(
    "error",
    [KeyboardInterrupt(), SystemExit(7)],
    ids=["keyboard_interrupt", "system_exit"],
)
def test_final_report_stdout_base_exception_propagates(
    tmp_path: Path,
    error: BaseException,
) -> None:
    with pytest.raises(type(error)) as caught:
        run_application(
            _config(tmp_path),
            stdout=RaisingWriter(error),  # type: ignore[arg-type]
            stderr=StringIO(),
            factories=_successful_factories(),
        )

    assert caught.value is error

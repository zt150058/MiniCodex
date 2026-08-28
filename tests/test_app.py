from __future__ import annotations

from io import StringIO
import json
from pathlib import Path

from coding_agent.app import ApplicationFactories, production_factories, run_application
from coding_agent.config import RunConfig, load_run_config
from coding_agent.logging import (
    EventType,
    RunEvent,
    RunEventLogger,
    RunLogError,
    RunMetadata,
)
from coding_agent.messages import ModelRequest, ModelResponse, ToolResultMetadata
from coding_agent.model import FakeModelClient, ModelClient
from coding_agent.safety import AuthorizedCommand
from coding_agent.tools.base import ExecutionContext, ToolExecution


FAKE_KEY = "task13-obviously-fake-key"


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[AuthorizedCommand, ExecutionContext]] = []

    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
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


def _config(workspace: Path) -> RunConfig:
    return load_run_config(
        task="repair demo",
        workspace=workspace,
        model="fake-model",
        verify_command="pytest -q",
        environ={"OPENAI_API_KEY": FAKE_KEY},
    )


def test_production_factory_selects_responses_adapter_without_request(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    config = _config(tmp_path)
    calls: list[tuple[str, str]] = []
    stand_in = FakeModelClient((ModelResponse(text="unused"),))

    def fake_constructor(*, model: str, api_key: str) -> ModelClient:
        calls.append((model, api_key))
        return stand_in

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "coding_agent.app.OpenAIResponsesClient",
        fake_constructor,
    )

    selected = production_factories().model_client(config)

    assert selected is stand_in
    assert calls == [(config.model, config.api_key)]
    assert stand_in.requests == ()


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
        "replace_text",
        "write_file",
        "run_command",
    ]


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

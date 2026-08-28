from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import shutil
import time

from coding_agent.agent import AgentRunner
from coding_agent.app import ApplicationFactories, run_application
from coding_agent.config import RunConfig, load_run_config
from coding_agent.context import ContextLimits, ContextManager
from coding_agent.logging import (
    EventType,
    RunEvent,
    RunEventLogger,
    RunLogError,
    RunMetadata,
)
from coding_agent.messages import AssistantMessage, ModelResponse, ToolCall, ToolResult
from coding_agent.model import FakeModelClient, ModelClient
from coding_agent.state import AgentStatus
from coding_agent.tools.base import ExecutionContext
from coding_agent.tools.filesystem import ReadFileTool
from coding_agent.tools.registry import ToolRegistry
from coding_agent.tools.shell import AuthorizedCommandExecutor


FAKE_KEY = "task13-failure-matrix-fake-key"
FIXTURE = Path(__file__).parents[2] / "examples" / "broken_pytest_project"


def _copy_demo(tmp_path: Path, name: str = "demo") -> Path:
    workspace = tmp_path / name
    shutil.copytree(
        FIXTURE,
        workspace,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
    )
    return workspace


def _run_with_fake(
    workspace: Path,
    fake: FakeModelClient,
    *,
    verify_command: str | None,
    run_id: str,
) -> tuple[int, dict[str, object], StringIO, StringIO]:
    config = load_run_config(
        task="Exercise a controlled Task 13 integration path.",
        workspace=workspace,
        model="fake-model",
        verify_command=verify_command,
        environ={"OPENAI_API_KEY": FAKE_KEY},
    )

    def model_factory(received: RunConfig) -> ModelClient:
        assert received is config
        return fake

    def logger_factory(received: RunConfig, clock: object) -> RunEventLogger:
        return RunEventLogger.create(
            received.workspace,
            run_id=run_id,
            sensitive_values=(received.api_key,),
            monotonic_clock=clock,  # type: ignore[arg-type]
        )

    stdout = StringIO()
    stderr = StringIO()
    code = run_application(
        config,
        stdout=stdout,
        stderr=stderr,
        factories=ApplicationFactories(
            model_client=model_factory,
            logger=logger_factory,
            command_executor=AuthorizedCommandExecutor,
            clock=time.monotonic,
        ),
    )
    return code, json.loads(stdout.getvalue()), stdout, stderr


def test_forced_verification_never_passes_before_budget_stop(
    tmp_path: Path,
) -> None:
    workspace = _copy_demo(tmp_path)
    fake = FakeModelClient(
        tuple(ModelResponse(text=f"still broken {index}") for index in range(12))
    )

    code, report, stdout, stderr = _run_with_fake(
        workspace,
        fake,
        verify_command="pytest -q",
        run_id="6" * 32,
    )

    assert code == report["exit_code"] == 1
    assert report["status"] == "failed"
    assert report["termination_reason"] == "logical_model_call_limit"
    assert report["logical_model_calls"] == 12
    assert report["provider_attempts"] == 12
    assert report["verification_attempts"] == 12
    assert report["verification"]["exit_code"] == 1  # type: ignore[index]
    assert "success" not in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_new_mutation_invalidates_previous_model_verification(
    tmp_path: Path,
) -> None:
    (tmp_path / "sample.py").write_text(
        "def value() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "test_sample.py").write_text(
        "from sample import value\n\n\ndef test_value() -> None:\n"
        "    assert value() == 1\n",
        encoding="utf-8",
    )
    fake = FakeModelClient(
        (
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "model-verification",
                        "run_command",
                        {"command": "pytest -q", "purpose": "verification"},
                    ),
                )
            ),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "mutate-after-pass",
                        "replace_text",
                        {
                            "path": "sample.py",
                            "old_text": "return 1",
                            "new_text": "return 2",
                            "expected_count": 1,
                        },
                    ),
                )
            ),
            ModelResponse(text="done with stale evidence"),
            *(ModelResponse(text=f"still stale {index}") for index in range(9)),
        )
    )

    code, report, _, stderr = _run_with_fake(
        tmp_path,
        fake,
        verify_command=None,
        run_id="7" * 32,
    )

    assert code == report["exit_code"] == 1
    assert report["status"] == "failed"
    assert report["termination_reason"] == "logical_model_call_limit"
    assert report["mutation_index"] == 1
    assert report["validation_index"] == 0
    assert report["verification_attempts"] == 1
    assert report["verification"]["status"] == "stale"  # type: ignore[index]
    assert stderr.getvalue() == ""


def test_repeated_tool_call_stops_before_fourth_dispatch(tmp_path: Path) -> None:
    (tmp_path / "sample.txt").write_text("unchanged\n", encoding="utf-8")
    responses = tuple(
        ModelResponse(
            tool_calls=(
                ToolCall(
                    f"repeat-{index}",
                    "read_file",
                    {"path": "sample.txt", "start_line": 1, "end_line": None},
                ),
            )
        )
        for index in range(3)
    )
    fake = FakeModelClient(responses)

    code, report, _, stderr = _run_with_fake(
        tmp_path,
        fake,
        verify_command=None,
        run_id="8" * 32,
    )

    assert code == report["exit_code"] == 1
    assert report["termination_reason"] == "repeated_tool_call"
    assert report["logical_model_calls"] == 3
    assert report["provider_attempts"] == 3
    assert report["tool_calls"] == 3
    assert len(fake.requests) == 3
    assert stderr.getvalue() == ""


def test_protected_write_rejections_have_no_side_effect(tmp_path: Path) -> None:
    calls = (
        ToolCall(
            "deny-git-one",
            "write_file",
            {"path": ".git/config", "content": "must not exist"},
        ),
        ToolCall(
            "deny-log",
            "write_file",
            {
                "path": ".coding-agent/logs/x.jsonl",
                "content": "must not exist",
            },
        ),
        ToolCall(
            "deny-git-two",
            "write_file",
            {"path": ".git/config", "content": "still forbidden"},
        ),
    )
    fake = FakeModelClient(
        tuple(ModelResponse(tool_calls=(call,)) for call in calls)
    )

    code, report, _, stderr = _run_with_fake(
        tmp_path,
        fake,
        verify_command=None,
        run_id="9" * 32,
    )

    assert code == report["exit_code"] == 1
    assert report["termination_reason"] == "consecutive_safety_rejections"
    assert report["tool_calls"] == 3
    assert report["mutation_index"] == 0
    assert report["changed_paths"] == []
    assert not (tmp_path / ".git" / "config").exists()
    assert not (tmp_path / ".coding-agent" / "logs" / "x.jsonl").exists()
    assert stderr.getvalue() == ""


def _summary_text() -> str:
    return json.dumps(
        {
            "goal": "continue the repair",
            "established_facts": ["nine files were inspected"],
            "files_examined": [f"item-{index}.txt" for index in range(9)],
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


def _read_turn(index: int, *, continuation: tuple[object, ...] = ()) -> ModelResponse:
    return ModelResponse(
        tool_calls=(
            ToolCall(
                f"context-read-{index}",
                "read_file",
                {
                    "path": f"item-{index}.txt",
                    "start_line": 1,
                    "end_line": None,
                },
            ),
        ),
        continuation_items=continuation,
    )


def _context_runner(
    tmp_path: Path,
    fake: FakeModelClient,
    *,
    logger: RunEventLogger | None = None,
) -> AgentRunner:
    for index in range(9):
        (tmp_path / f"item-{index}.txt").write_text(
            f"value {index}\n",
            encoding="utf-8",
        )
    return AgentRunner(
        model_client=fake,
        tool_registry=ToolRegistry((ReadFileTool(),)),
        execution_context=ExecutionContext(tmp_path),
        context_manager=ContextManager(
            model_client=fake,
            limits=ContextLimits(
                max_serialized_chars=60_000,
                max_history_items=18,
                recent_turns=8,
            ),
        ),
        clock=lambda: 0.0,
        event_sink=logger,
    )


def test_context_summary_clears_continuation_and_preserves_pairs(
    tmp_path: Path,
) -> None:
    active_continuation = object()
    summary_continuation = object()
    turns = [_read_turn(index) for index in range(9)]
    turns[-1] = _read_turn(8, continuation=(active_continuation,))
    fake = FakeModelClient(
        (
            *turns,
            ModelResponse(
                text=_summary_text(),
                continuation_items=(summary_continuation,),
            ),
            ModelResponse(text="continue after compression"),
        )
    )
    logger = RunEventLogger.create(tmp_path, run_id="a" * 32)
    runner = _context_runner(tmp_path, fake, logger=logger)

    state = runner.run("compress a legal tool history")
    logger.close()

    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert state.continuation_items == ()
    assert fake.requests[9].tool_schemas == ()
    assert fake.requests[9].continuation_items == ()
    assert fake.requests[10].continuation_items == ()
    seen_calls: set[str] = set()
    for message in fake.requests[10].messages:
        if isinstance(message, AssistantMessage):
            seen_calls.update(call.call_id for call in message.tool_calls)
        elif isinstance(message, ToolResult):
            assert message.call_id in seen_calls
    raw_log = (
        tmp_path / ".coding-agent" / "logs" / ("a" * 32 + ".jsonl")
    ).read_text(encoding="utf-8")
    assert '"summary_source":"model"' in raw_log
    assert "continuation_cleared\":true" in raw_log
    assert repr(active_continuation) not in raw_log
    assert repr(summary_continuation) not in raw_log


def test_invalid_context_summary_uses_fallback_and_continues(
    tmp_path: Path,
) -> None:
    fake = FakeModelClient(
        (
            *(_read_turn(index) for index in range(9)),
            ModelResponse(text="not valid summary json"),
            ModelResponse(text="continued after deterministic fallback"),
        )
    )
    logger = RunEventLogger.create(tmp_path, run_id="b" * 32)
    runner = _context_runner(tmp_path, fake, logger=logger)

    state = runner.run("fall back after an invalid summary")
    logger.close()

    assert state.status is AgentStatus.COMPLETION_CANDIDATE
    assert state.completion_text == "continued after deterministic fallback"
    assert state.logical_model_call_count == 11
    assert state.model_call_count == 11
    summary_message = fake.requests[10].messages[1]
    assert summary_message.content.startswith(  # type: ignore[union-attr]
        "coding-agent context summary\n"
    )
    assert "not valid summary json" not in summary_message.content  # type: ignore[operator]
    raw_log = (
        tmp_path / ".coding-agent" / "logs" / ("b" * 32 + ".jsonl")
    ).read_text(encoding="utf-8")
    assert '"summary_source":"fallback"' in raw_log
    assert '"summary_model_failed":true' in raw_log


class FailBeforeToolLogger:
    def __init__(self, wrapped: RunEventLogger) -> None:
        self.wrapped = wrapped

    @property
    def metadata(self) -> RunMetadata:
        return self.wrapped.metadata

    def emit(self, event_type: EventType, data: dict[str, object]) -> RunEvent:
        if event_type is EventType.TOOL_CALL_STARTED:
            self.metadata.log_failure_code = "log_write_failed"
            raise RunLogError("log_write_failed")
        return self.wrapped.emit(event_type, data)  # type: ignore[arg-type]

    def observe_model(self, observation: object) -> None:
        self.wrapped.observe_model(observation)  # type: ignore[arg-type]

    def close(self) -> None:
        self.wrapped.close()


def test_log_emit_failure_blocks_next_operation(tmp_path: Path) -> None:
    fake = FakeModelClient(
        (
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "must-not-execute",
                        "write_file",
                        {"path": "forbidden-by-log.txt", "content": "not written"},
                    ),
                )
            ),
            ModelResponse(text="must not be requested"),
        )
    )
    config = load_run_config(
        task="Stop before operating without an audit trail.",
        workspace=tmp_path,
        model="fake-model",
        verify_command=None,
        environ={"OPENAI_API_KEY": FAKE_KEY},
    )

    def logger_factory(received: RunConfig, clock: object) -> RunEventLogger:
        return FailBeforeToolLogger(
            RunEventLogger.create(
                received.workspace,
                run_id="c" * 32,
                sensitive_values=(received.api_key,),
                monotonic_clock=clock,  # type: ignore[arg-type]
            )
        )  # type: ignore[return-value]

    stdout = StringIO()
    stderr = StringIO()
    code = run_application(
        config,
        stdout=stdout,
        stderr=stderr,
        factories=ApplicationFactories(
            model_client=lambda received: fake,
            logger=logger_factory,
            command_executor=AuthorizedCommandExecutor,
            clock=time.monotonic,
        ),
    )

    report = json.loads(stdout.getvalue())
    assert code == report["exit_code"] == 1
    assert report["termination_reason"] == "audit_log_failure"
    assert report["log_failure_code"] == "log_write_failed"
    assert report["tool_calls"] == 0
    assert len(fake.requests) == 1
    assert not (tmp_path / "forbidden-by-log.txt").exists()
    assert stderr.getvalue() == ""


def _repair_model() -> FakeModelClient:
    return FakeModelClient(
        (
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "list",
                        "list_directory",
                        {
                            "path": ".",
                            "recursive": True,
                            "max_depth": 3,
                            "max_entries": 50,
                        },
                    ),
                )
            ),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "read-tests",
                        "read_file",
                        {
                            "path": "test_calculator.py",
                            "start_line": 1,
                            "end_line": None,
                        },
                    ),
                    ToolCall(
                        "read-source",
                        "read_file",
                        {
                            "path": "calculator.py",
                            "start_line": 1,
                            "end_line": None,
                        },
                    ),
                )
            ),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "fix-add",
                        "replace_text",
                        {
                            "path": "calculator.py",
                            "old_text": "return left - right",
                            "new_text": "return left + right",
                            "expected_count": 1,
                        },
                    ),
                )
            ),
            ModelResponse(text="first candidate"),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "fix-even",
                        "replace_text",
                        {
                            "path": "calculator.py",
                            "old_text": "return value % 2 == 1",
                            "new_text": "return value % 2 == 0",
                            "expected_count": 1,
                        },
                    ),
                )
            ),
            ModelResponse(text="verified candidate"),
        )
    )


def test_two_runs_use_independent_logs_and_fresh_fixture_copies(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.setenv(  # type: ignore[attr-defined]
        "PYTHONDONTWRITEBYTECODE",
        "1",
    )
    tracked_source = (FIXTURE / "calculator.py").read_bytes()
    tracked_test = (FIXTURE / "test_calculator.py").read_bytes()
    first_workspace = _copy_demo(tmp_path, "first-demo")
    second_workspace = _copy_demo(tmp_path, "second-demo")

    first_code, first_report, _, first_stderr = _run_with_fake(
        first_workspace,
        _repair_model(),
        verify_command="pytest -q",
        run_id="d" * 32,
    )
    second_code, second_report, _, second_stderr = _run_with_fake(
        second_workspace,
        _repair_model(),
        verify_command="pytest -q",
        run_id="e" * 32,
    )

    assert first_code == first_report["exit_code"] == 0
    assert second_code == second_report["exit_code"] == 0
    assert first_report["run_id"] != second_report["run_id"]
    assert first_report["log_path"] != second_report["log_path"]
    assert (first_workspace / first_report["log_path"]).is_file()  # type: ignore[operator]
    assert (second_workspace / second_report["log_path"]).is_file()  # type: ignore[operator]
    assert (FIXTURE / "calculator.py").read_bytes() == tracked_source
    assert (FIXTURE / "test_calculator.py").read_bytes() == tracked_test
    assert first_stderr.getvalue() == second_stderr.getvalue() == ""

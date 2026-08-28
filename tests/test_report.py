from __future__ import annotations

import json
import inspect
from pathlib import Path
import subprocess
import sys

import pytest

from coding_agent.logging import RunMetadata, TokenUsageTotals
from coding_agent.agent import AgentRunner
from coding_agent.logging import RunEventLogger
from coding_agent.messages import ModelResponse, ToolResultMetadata
from coding_agent.model import FakeModelClient, ModelClient, invoke_model
from coding_agent.openai_client import OpenAIResponsesClient
from coding_agent.context import ContextManager
from coding_agent.report import (
    MAX_REPORT_COMPLETION_CHARS,
    MAX_REPORT_STREAM_CHARS,
    FinalReport,
    ReportInvariantError,
)
from coding_agent.safety import CommandSource
from coding_agent.safety import AuthorizedCommand
from coding_agent.state import (
    AgentState,
    AgentStatus,
    TerminationReason,
    VerificationStatus,
)
from coding_agent.verification import VerificationResult
from coding_agent.tools.base import ExecutionContext, ToolExecution
from coding_agent.tools.registry import ToolRegistry
from coding_agent.verification import VerificationGate


def successful_state(tmp_path: Path) -> AgentState:
    state = AgentState.start("repair tests", tmp_path, 0.0)
    state.status = AgentStatus.SUCCESS
    state.completion_text = "all checks passed"
    state.mutation_index = 2
    state.modified_paths = ("b.py", "a.py")
    state.logical_model_call_count = 3
    state.model_call_count = 4
    state.tool_call_count = 5
    state.verification_attempt_count = 1
    state.verification_status = VerificationStatus.PASSED
    state.last_verification = VerificationResult(
        status=VerificationStatus.PASSED,
        validation_index=2,
        command="python -m pytest -q",
        source=CommandSource.USER_VERIFY,
        exit_code=0,
        stdout="656 passed",
        stderr="",
        timed_out=False,
        truncated=False,
        duration_ms=125,
        error=None,
    )
    return state


def run_metadata() -> RunMetadata:
    return RunMetadata(
        run_id="9" * 32,
        log_path=".coding-agent/logs/" + "9" * 32 + ".jsonl",
        started_at_utc="2026-08-28T00:00:00.000000Z",
        context_compression_count=1,
        token_usage=TokenUsageTotals(
            input_tokens=10,
            output_tokens=4,
            total_tokens=14,
            responses_with_usage=1,
            responses_without_usage=1,
        ),
        finished_elapsed_ms=1250,
    )


def test_success_report_uses_state_and_metadata_without_reading_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = successful_state(tmp_path)

    def forbidden_read(*args: object, **kwargs: object) -> str:
        raise AssertionError("report must not read JSONL")

    monkeypatch.setattr(Path, "read_text", forbidden_read)
    report = FinalReport.from_state(state, run_metadata())

    assert report.status is AgentStatus.SUCCESS
    assert report.exit_code == 0
    assert report.mutation_index == report.validation_index == 2
    assert report.changed_paths == ("b.py", "a.py")
    assert report.logical_model_calls == 3
    assert report.provider_attempts == 4
    assert report.tool_calls == 5
    assert report.verification_attempts == 1
    assert report.context_compressions == 1
    assert report.token_usage == run_metadata().token_usage
    assert report.elapsed_ms == 1250
    payload = json.loads(report.to_json())
    assert payload["status"] == "success"
    assert payload["verification"]["status"] == "passed"
    assert report.to_json().endswith("\n")


def test_report_scrubs_before_exact_character_truncation_and_hides_repr(
    tmp_path: Path,
) -> None:
    secret = "known-sensitive-value"
    state = successful_state(tmp_path)
    state.completion_text = secret + "界" * (MAX_REPORT_COMPLETION_CHARS + 20)
    assert state.last_verification is not None
    state.last_verification = VerificationResult(
        status=VerificationStatus.PASSED,
        validation_index=2,
        command="python -m pytest -q Authorization: Bearer hidden-token",
        source=CommandSource.USER_VERIFY,
        exit_code=0,
        stdout=secret + "雪" * (MAX_REPORT_STREAM_CHARS + 10),
        stderr="api_key=hidden-value sk-fakecredential1234",
        timed_out=False,
        truncated=True,
        duration_ms=125,
        error=None,
    )

    report = FinalReport.from_state(
        state,
        run_metadata(),
        sensitive_values=(secret,),
    )
    rendered = report.to_json()

    assert report.completion is not None
    assert len(report.completion.text) == MAX_REPORT_COMPLETION_CHARS
    assert report.completion.original_chars == (
        len("[REDACTED]") + MAX_REPORT_COMPLETION_CHARS + 20
    )
    assert report.completion.truncated is True
    assert report.verification.stdout is not None
    assert len(report.verification.stdout.text) == MAX_REPORT_STREAM_CHARS
    assert report.verification.stdout.truncated is True
    assert secret not in rendered
    assert "hidden-token" not in rendered
    assert "hidden-value" not in rendered
    assert "sk-fakecredential1234" not in rendered
    assert secret not in repr(report)
    assert "hidden-token" not in repr(report)
    assert rendered.count("\n") > 1
    assert rendered.endswith("\n") and not rendered.endswith("\n\n")
    assert list(json.loads(rendered))[:5] == [
        "schema_version",
        "run_id",
        "status",
        "exit_code",
        "completion",
    ]


@pytest.mark.parametrize(
    ("status", "reason", "expected_exit"),
    [
        (AgentStatus.FAILED, TerminationReason.AUDIT_LOG_FAILURE, 1),
        (AgentStatus.FAILED, TerminationReason.TIME_LIMIT, 1),
        (AgentStatus.INTERRUPTED, TerminationReason.USER_INTERRUPTED, 130),
    ],
)
def test_non_success_exit_mapping_is_explicit(
    tmp_path: Path,
    status: AgentStatus,
    reason: TerminationReason,
    expected_exit: int,
) -> None:
    state = AgentState.start("task", tmp_path, 0.0)
    state.status = status
    state.termination_reason = reason
    state.failure_reason = reason.value

    report = FinalReport.from_state(state, run_metadata())

    assert report.exit_code == expected_exit
    assert report.termination_reason is reason


@pytest.mark.parametrize(
    "status",
    [AgentStatus.RUNNING, AgentStatus.COMPLETION_CANDIDATE],
)
def test_nonterminal_state_cannot_be_rendered_as_final_report(
    tmp_path: Path,
    status: AgentStatus,
) -> None:
    state = AgentState.start("task", tmp_path, 0.0)
    state.status = status
    with pytest.raises(ReportInvariantError, match="not terminal"):
        FinalReport.from_state(state, run_metadata())


class PassingVerificationExecutor:
    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
    ) -> ToolExecution:
        return ToolExecution(
            output=json.dumps(
                {
                    "argv": list(command.argv),
                    "cleanup_error": None,
                    "purpose": "verification",
                    "stderr": "",
                    "stdout": "private integration evidence",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            metadata=ToolResultMetadata(exit_code=0, duration_ms=7),
        )


class FailOnSeventhWrite:
    def __init__(self, wrapped: object) -> None:
        self.wrapped = wrapped
        self.write_calls = 0

    def write(self, value: str) -> int:
        self.write_calls += 1
        if self.write_calls == 7:
            raise OSError("private terminal failure")
        return self.wrapped.write(value)  # type: ignore[attr-defined,no-any-return]

    def flush(self) -> None:
        self.wrapped.flush()  # type: ignore[attr-defined]

    def close(self) -> None:
        self.wrapped.close()  # type: ignore[attr-defined]


def test_integration_success_log_and_report_share_final_facts(
    tmp_path: Path,
) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="a" * 32)
    argv = (sys.executable, "-m", "pytest", "-q")
    command = AuthorizedCommand(
        argv=argv,
        normalized_command=subprocess.list2cmdline(argv),
        purpose="verification",
        source=CommandSource.USER_VERIFY,
    )
    runner = AgentRunner(
        model_client=FakeModelClient((ModelResponse(text="private completion"),)),
        tool_registry=ToolRegistry(),
        execution_context=ExecutionContext(tmp_path),
        verification_gate=VerificationGate(
            required_command=command,
            execution_context=ExecutionContext(tmp_path),
            executor=PassingVerificationExecutor(),
        ),
        event_sink=logger,
        clock=lambda: 0.0,
    )

    state = runner.run("private task")
    report = FinalReport.from_state(state, logger.metadata)
    logger.close()

    raw = (
        tmp_path / ".coding-agent" / "logs" / ("a" * 32 + ".jsonl")
    ).read_text(encoding="utf-8")
    events = [json.loads(line) for line in raw.splitlines()]
    assert state.status is AgentStatus.SUCCESS
    assert events[0]["event_type"] == "run_started"
    assert events[-1]["event_type"] == "run_completed"
    assert events[-1]["data"]["status"] == "success"
    assert [event["sequence"] for event in events] == list(
        range(1, len(events) + 1)
    )
    assert report.status is state.status
    assert report.logical_model_calls == state.logical_model_call_count == 1
    assert report.provider_attempts == state.model_call_count == 1
    assert report.tool_calls == state.tool_call_count == 1
    assert report.verification_attempts == state.verification_attempt_count == 1
    assert report.exit_code == 0
    assert "private task" not in raw
    assert "private completion" not in raw
    assert "private integration evidence" not in raw


def test_terminal_log_failure_produces_nonzero_report_without_second_terminal(
    tmp_path: Path,
) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="b" * 32)
    stream = FailOnSeventhWrite(logger._stream)  # type: ignore[attr-defined]
    logger._stream = stream  # type: ignore[attr-defined]
    runner = AgentRunner(
        model_client=FakeModelClient((ModelResponse(text="candidate"),)),
        tool_registry=ToolRegistry(),
        execution_context=ExecutionContext(tmp_path),
        event_sink=logger,
        clock=lambda: 0.0,
    )

    state = runner.run("terminal write failure")
    report = FinalReport.from_state(state, logger.metadata)
    logger.close()

    raw = (
        tmp_path / ".coding-agent" / "logs" / ("b" * 32 + ".jsonl")
    ).read_text(encoding="utf-8")
    events = [json.loads(line) for line in raw.splitlines()]
    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.AUDIT_LOG_FAILURE
    assert report.exit_code == 1
    assert report.log_failure_code == "log_write_failed"
    assert stream.write_calls == 7
    assert all(event["event_type"] != "run_completed" for event in events)


def test_task12_public_signatures_are_additive_only() -> None:
    assert tuple(inspect.signature(ModelClient.complete).parameters) == (
        "self",
        "request",
    )
    assert tuple(inspect.signature(OpenAIResponsesClient.__init__).parameters) == (
        "self",
        "model",
        "api_key",
        "sdk_client",
        "sleeper",
    )
    assert tuple(inspect.signature(OpenAIResponsesClient.complete).parameters) == (
        "self",
        "request",
    )
    assert tuple(
        inspect.signature(OpenAIResponsesClient.complete_with_budget).parameters
    ) == ("self", "request", "budget")
    assert tuple(inspect.signature(AgentRunner.run).parameters) == ("self", "task")
    assert tuple(inspect.signature(invoke_model).parameters) == (
        "client",
        "request",
        "budget",
        "purpose",
    )
    assert tuple(inspect.signature(ContextManager.requires_compression).parameters) == (
        "self",
        "messages",
    )

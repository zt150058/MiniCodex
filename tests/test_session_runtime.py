from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from coding_agent.context import ContextManager, ContextLimits
from coding_agent.app import ApplicationFactories
from coding_agent.config import load_run_config
from coding_agent.logging import RunEventLogger
from coding_agent.messages import (
    ModelResponse,
    ToolResultMetadata,
    UserMessage,
)
from coding_agent.model import FakeModelClient
from coding_agent.safety import AuthorizedCommand
from coding_agent.session import (
    SessionError,
    SessionNarrativeEntry,
    SessionNarrativeKind,
    SessionRunStatus,
)
from coding_agent.session_runtime import (
    AgentSessionRunExecutor,
    SessionNarrativeRenderer,
    SessionRunRequest,
)
from coding_agent.tools.base import ExecutionContext, ToolExecution


RUN_1 = "1" * 32
RUN_2 = "2" * 32


def _entry(
    run_id: str,
    kind: SessionNarrativeKind,
    content: str,
) -> SessionNarrativeEntry:
    return SessionNarrativeEntry(run_id=run_id, kind=kind, content=content)


def test_session_modules_import_without_provider_sdk_or_network(tmp_path: Path) -> None:
    script = """
import builtins
import importlib
import os
import socket

for name in ("OPENAI_API_KEY", "CHAT_COMPLETIONS_API_KEY"):
    os.environ.pop(name, None)
forbidden = {"openai", "httpx", "requests"}
real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name.split(".")[0] in forbidden:
        raise AssertionError(name)
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
socket.socket = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network"))
for name in (
    "coding_agent.session",
    "coding_agent.session_store",
    "coding_agent.session_events",
    "coding_agent.session_runtime",
    "coding_agent.session_controller",
):
    importlib.import_module(name)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_narrative_is_one_deterministic_initial_user_message() -> None:
    entries = (
        _entry(RUN_1, SessionNarrativeKind.USER, "fix parser"),
        _entry(RUN_1, SessionNarrativeKind.ASSISTANT, "parser fixed"),
        _entry(
            RUN_1,
            SessionNarrativeKind.RUN_SUMMARY,
            '{"status":"success"}',
        ),
    )
    renderer = SessionNarrativeRenderer()
    first = renderer.render(entries, "now add a test")
    second = renderer.render(entries, "now add a test")
    assert first == second
    assert first.startswith("coding-agent session context\n")
    assert first.endswith("current request\nnow add a test")
    assert "call_id" not in first
    assert (
        ContextManager.measure((UserMessage(first),)).serialized_chars
        <= ContextLimits().max_serialized_chars
    )


def test_narrative_keeps_newest_entries_and_reports_omission() -> None:
    entries = tuple(
        _entry(
            str(index).zfill(32),
            SessionNarrativeKind.ASSISTANT,
            f"entry-{index}-" + "x" * 8000,
        )
        for index in range(1, 9)
    )
    rendered = SessionNarrativeRenderer().render(entries, "current")
    assert "entry-8-" in rendered
    assert "entry-1-" not in rendered
    assert '"omitted_entries":' in rendered
    assert ContextManager.measure((UserMessage(rendered),)).serialized_chars <= 60_000


def test_current_request_that_cannot_fit_is_rejected_without_truncation() -> None:
    with pytest.raises(SessionError) as captured:
        SessionNarrativeRenderer().render((), "x" * 60_000)
    assert captured.value.code == "invalid_message"


class PassingExecutor:
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
                    "purpose": command.purpose,
                    "stderr": "",
                    "stdout": "1 passed",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            metadata=ToolResultMetadata(exit_code=0, duration_ms=1),
        )


def test_agent_session_executor_returns_sdk_free_terminal_outcome(
    tmp_path: Path,
) -> None:
    config = load_run_config(
        task="template task",
        workspace=tmp_path,
        model="fake-model",
        verify_command="pytest -q",
        environ={"OPENAI_API_KEY": "obviously-fake-session-key"},
    )
    factories = ApplicationFactories(
        model_client=lambda _: FakeModelClient((ModelResponse(text="done"),)),
        logger=lambda selected, clock: RunEventLogger.create(
            selected.workspace,
            run_id="5" * 32,
            sensitive_values=(selected.api_key,),
            monotonic_clock=clock,
        ),
        command_executor=PassingExecutor,
        clock=lambda: 0.0,
    )
    executor = AgentSessionRunExecutor(config, factories=factories)
    assert executor.workspace == tmp_path.resolve(strict=True)
    request = SessionRunRequest(
        session_id="1" * 32,
        run_id="2" * 32,
        current_message="actual follow-up",
        initial_user_message="current request\nactual follow-up",
    )
    confirmed: list[str] = []
    outcome = executor.execute(
        request,
        stream_handler=lambda event: None,
        confirmed_text_handler=confirmed.append,
        cancellation_requested=lambda: False,
        run_event_handler=lambda event: None,
    )
    assert outcome.status is SessionRunStatus.SUCCEEDED
    assert outcome.agent_status == "success"
    assert outcome.final_report is not None
    assert outcome.audit_run_id == outcome.final_report["run_id"]
    assert outcome.final_report["exit_code"] == 0
    persisted = json.dumps(outcome.final_report, ensure_ascii=False)
    for forbidden in (
        "completion",
        "failure_reason",
        "command",
        "stdout",
        "stderr",
        "private completion",
        "private stdout",
        "private stderr",
    ):
        assert forbidden not in persisted
    assert "OpenAI" not in type(outcome).__module__
    assert confirmed


def test_fresh_run_has_fresh_model_budget_and_no_prior_continuation(
    tmp_path: Path,
) -> None:
    (tmp_path / "shared.txt").write_text("same workspace", encoding="utf-8")
    clients: list[FakeModelClient] = []
    logger_ids = iter(("6" * 32, "7" * 32))

    def model_factory(_: object) -> FakeModelClient:
        client = FakeModelClient((ModelResponse(text="done"),))
        clients.append(client)
        return client

    config = load_run_config(
        task="template",
        workspace=tmp_path,
        model="fake-model",
        verify_command="pytest -q",
        environ={"OPENAI_API_KEY": "obviously-fake-session-key"},
    )
    executor = AgentSessionRunExecutor(
        config,
        factories=ApplicationFactories(
            model_client=model_factory,  # type: ignore[arg-type]
            logger=lambda selected, clock: RunEventLogger.create(
                selected.workspace,
                run_id=next(logger_ids),
                sensitive_values=(selected.api_key,),
                monotonic_clock=clock,
            ),
            command_executor=PassingExecutor,
            clock=lambda: 0.0,
        ),
    )
    renderer = SessionNarrativeRenderer()
    first_initial = renderer.render((), "first")
    first = SessionRunRequest(RUN_1, RUN_1, "first", first_initial)
    executor.execute(
        first,
        stream_handler=lambda event: None,
        confirmed_text_handler=lambda text: None,
        cancellation_requested=lambda: False,
        run_event_handler=lambda event: None,
    )
    second_initial = renderer.render(
        (_entry(RUN_1, SessionNarrativeKind.USER, "first"),),
        "second",
    )
    second = SessionRunRequest(RUN_1, RUN_2, "second", second_initial)
    executor.execute(
        second,
        stream_handler=lambda event: None,
        confirmed_text_handler=lambda text: None,
        cancellation_requested=lambda: False,
        run_event_handler=lambda event: None,
    )
    assert len(clients) == 2
    assert clients[0] is not clients[1]
    assert len(clients[0].requests) == len(clients[1].requests) == 1
    assert clients[1].requests[0].messages == (UserMessage(second_initial),)
    assert clients[1].requests[0].continuation_items == ()
    assert (executor.workspace / "shared.txt").read_text(encoding="utf-8") == "same workspace"

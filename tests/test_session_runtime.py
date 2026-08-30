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
from coding_agent.run_mode import RunMode
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
from coding_agent.skills import SkillCatalog
from coding_agent.tools.base import ExecutionContext, ToolExecution


RUN_1 = "1" * 32
RUN_2 = "2" * 32


def write_skill(root: Path, skill_id: str, body: str) -> Path:
    directory = root / skill_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    path.write_text(
        "---\n"
        f"id: {skill_id}\n"
        f"name: {skill_id.title()}\n"
        "description: deterministic test skill\n"
        "---\n"
        f"{body}",
        encoding="utf-8",
    )
    return path


def _entry(
    run_id: str,
    kind: SessionNarrativeKind,
    content: str,
) -> SessionNarrativeEntry:
    return SessionNarrativeEntry(run_id=run_id, kind=kind, content=content)


def test_session_run_request_accepts_frozen_skill_bundle_and_hides_body(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skills"
    write_skill(root, "review", "task21 private runtime body")
    bundle = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / "workspace",
    ).resolve(("review",))
    assert bundle is not None
    request = SessionRunRequest(
        session_id="1" * 32,
        run_id="2" * 32,
        current_message="inspect",
        initial_user_message="inspect",
        skill_bundle=bundle,
    )
    assert request.skill_bundle is bundle
    assert "task21 private runtime body" not in repr(request)
    with pytest.raises(TypeError):
        SessionRunRequest(
            session_id="1" * 32,
            run_id="2" * 32,
            current_message="inspect",
            initial_user_message="inspect",
            skill_bundle="invalid",  # type: ignore[arg-type]
        )


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


@pytest.mark.parametrize(
    ("mode", "agent_status", "session_status"),
    [
        (RunMode.MODIFY, "success", SessionRunStatus.SUCCEEDED),
        (RunMode.READ_ONLY, "answered", SessionRunStatus.SUCCEEDED),
    ],
)
def test_runtime_executes_with_request_mode_and_maps_terminal_status(
    tmp_path: Path,
    mode: RunMode,
    agent_status: str,
    session_status: SessionRunStatus,
) -> None:
    captured_configs: list[object] = []
    base_config = load_run_config(
        task="template task",
        workspace=tmp_path,
        model="fake-model",
        verify_command="pytest -q",
        environ={"OPENAI_API_KEY": "obviously-fake-session-key"},
    )
    factories = ApplicationFactories(
        model_client=lambda selected: (
            captured_configs.append(selected)
            or FakeModelClient((ModelResponse(text="done"),))
        ),
        logger=lambda selected, clock: RunEventLogger.create(
            selected.workspace,
            run_id="9" * 32,
            sensitive_values=(selected.api_key,),
            monotonic_clock=clock,
        ),
        command_executor=PassingExecutor,
        clock=lambda: 0.0,
    )
    request = SessionRunRequest(
        session_id="1" * 32,
        run_id="2" * 32,
        current_message="inspect",
        initial_user_message="inspect",
        run_mode=mode,
    )

    outcome = AgentSessionRunExecutor(
        base_config,
        factories=factories,
    ).execute(
        request,
        stream_handler=lambda event: None,
        confirmed_text_handler=lambda text: None,
        cancellation_requested=lambda: False,
        run_event_handler=lambda event: None,
    )

    assert captured_configs[0].run_mode is mode
    assert outcome.status is session_status
    assert outcome.agent_status == agent_status


def test_web_base_verify_runs_for_modify_but_not_read_only(tmp_path: Path) -> None:
    class RecordingPassingExecutor(PassingExecutor):
        def __init__(self) -> None:
            self.calls: list[AuthorizedCommand] = []

        def execute(
            self,
            command: AuthorizedCommand,
            context: ExecutionContext,
        ) -> ToolExecution:
            self.calls.append(command)
            return super().execute(command, context)

    command_executor = RecordingPassingExecutor()
    logger_ids = iter(("a" * 32, "b" * 32))
    base_config = load_run_config(
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
            run_id=next(logger_ids),
            sensitive_values=(selected.api_key,),
            monotonic_clock=clock,
        ),
        command_executor=lambda: command_executor,  # type: ignore[arg-type]
        clock=lambda: 0.0,
    )
    executor = AgentSessionRunExecutor(base_config, factories=factories)
    handlers = {
        "stream_handler": lambda event: None,
        "confirmed_text_handler": lambda text: None,
        "cancellation_requested": lambda: False,
        "run_event_handler": lambda event: None,
    }

    modify = executor.execute(
        SessionRunRequest(
            session_id="1" * 32,
            run_id="2" * 32,
            current_message="change it",
            initial_user_message="change it",
            run_mode=RunMode.MODIFY,
        ),
        **handlers,  # type: ignore[arg-type]
    )
    read_only = executor.execute(
        SessionRunRequest(
            session_id="1" * 32,
            run_id="3" * 32,
            current_message="explain it",
            initial_user_message="explain it",
            run_mode=RunMode.READ_ONLY,
        ),
        **handlers,  # type: ignore[arg-type]
    )

    assert modify.agent_status == "success"
    assert read_only.agent_status == "answered"
    assert [call.purpose for call in command_executor.calls] == ["verification"]


def test_session_run_request_mode_is_strict_and_sensitive_fields_stay_hidden() -> None:
    request = SessionRunRequest(
        session_id="1" * 32,
        run_id="2" * 32,
        current_message="private current message",
        initial_user_message="private initial history",
        run_mode=RunMode.READ_ONLY,
    )
    assert request.run_mode is RunMode.READ_ONLY
    assert "private current message" not in repr(request)
    assert "private initial history" not in repr(request)
    with pytest.raises(TypeError, match="run_mode"):
        SessionRunRequest(
            session_id="1" * 32,
            run_id="2" * 32,
            current_message="inspect",
            initial_user_message="inspect",
            run_mode="read_only",  # type: ignore[arg-type]
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


def test_agent_session_executor_passes_skill_bundle_without_persisting_body(
    tmp_path: Path,
) -> None:
    private_body = "task21 private runtime body"
    root = tmp_path / "skills"
    write_skill(root, "review", private_body)
    bundle = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / "workspace-skills",
    ).resolve(("review",))
    assert bundle is not None
    client = FakeModelClient((ModelResponse(text="done"),))
    config = load_run_config(
        task="template task",
        workspace=tmp_path,
        model="fake-model",
        verify_command="pytest -q",
        environ={"OPENAI_API_KEY": "obviously-fake-session-key"},
    )
    factories = ApplicationFactories(
        model_client=lambda _: client,
        logger=lambda selected, clock: RunEventLogger.create(
            selected.workspace,
            run_id="8" * 32,
            sensitive_values=(selected.api_key,),
            monotonic_clock=clock,
        ),
        command_executor=PassingExecutor,
        clock=lambda: 0.0,
    )
    executor = AgentSessionRunExecutor(config, factories=factories)
    request = SessionRunRequest(
        session_id="1" * 32,
        run_id="2" * 32,
        current_message="actual follow-up",
        initial_user_message="current request\nactual follow-up",
        skill_bundle=bundle,
    )
    outcome = executor.execute(
        request,
        stream_handler=lambda event: None,
        confirmed_text_handler=lambda text: None,
        cancellation_requested=lambda: False,
        run_event_handler=lambda event: None,
    )
    assert client.requests
    assert client.requests[0].instructions is not None
    assert private_body in client.requests[0].instructions
    assert private_body not in json.dumps(outcome.safe_summary, ensure_ascii=False)
    assert private_body not in json.dumps(outcome.final_report, ensure_ascii=False)


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

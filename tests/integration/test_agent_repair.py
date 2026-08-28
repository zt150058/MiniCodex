from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

from coding_agent.app import ApplicationFactories, run_application
from coding_agent.config import RunConfig, load_run_config
from coding_agent.logging import RunEventLogger
from coding_agent.messages import AssistantMessage, ModelResponse, ToolCall
from coding_agent.model import FakeModelClient, ModelClient
from coding_agent.tools.shell import AuthorizedCommandExecutor


FAKE_KEY = "task13-repair-fake-key"
FIXTURE = Path(__file__).parents[2] / "examples" / "broken_pytest_project"


def _run_pytest(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )


def _scripted_model() -> FakeModelClient:
    read_tests = ToolCall(
        "call-read-tests",
        "read_file",
        {"path": "test_calculator.py", "start_line": 1, "end_line": None},
    )
    read_source = ToolCall(
        "call-read-source",
        "read_file",
        {"path": "calculator.py", "start_line": 1, "end_line": None},
    )
    return FakeModelClient(
        (
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "call-list",
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
            ModelResponse(tool_calls=(read_tests, read_source)),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "call-fix-add",
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
            ModelResponse(text="The implementation is fixed."),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "call-fix-even",
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
            ModelResponse(text="The implementation is fixed and verified."),
        )
    )


def test_cli_repairs_demo_after_failed_forced_verification(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    network_calls: list[tuple[object, ...]] = []

    def reject_network(*args: object, **kwargs: object) -> object:
        network_calls.append((*args, kwargs))
        raise AssertionError("offline integration attempted network access")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        socket,
        "create_connection",
        reject_network,
    )
    monkeypatch.setenv(  # type: ignore[attr-defined]
        "PYTHONDONTWRITEBYTECODE",
        "1",
    )
    workspace = tmp_path / "demo"
    shutil.copytree(
        FIXTURE,
        workspace,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
    )
    copied_source = workspace / "calculator.py"
    copied_test = workspace / "test_calculator.py"
    original_test_bytes = copied_test.read_bytes()
    fake = _scripted_model()
    config = load_run_config(
        task="Repair the two calculator defects without changing tests.",
        workspace=workspace,
        model="fake-model",
        verify_command="pytest -q",
        environ={"OPENAI_API_KEY": FAKE_KEY},
    )

    def model_factory(received: RunConfig) -> ModelClient:
        assert received is config
        return fake

    def logger_factory(received: RunConfig, clock: object) -> RunEventLogger:
        return RunEventLogger.create(
            received.workspace,
            run_id="5" * 32,
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

    report = json.loads(stdout.getvalue())
    assert code == report["exit_code"] == 0
    assert report["status"] == "success"
    assert report["mutation_index"] == report["validation_index"] == 2
    assert report["verification_attempts"] == 2
    assert report["verification"]["exit_code"] == 0
    assert report["changed_paths"] == ["calculator.py"]
    assert report["logical_model_calls"] == 6
    assert report["provider_attempts"] == 6
    assert report["tool_calls"] == 7
    assert stderr.getvalue() == ""
    assert copied_test.read_bytes() == original_test_bytes
    source = copied_source.read_text(encoding="utf-8")
    assert "return left + right" in source
    assert "return value % 2 == 0" in source

    feedback_message = fake.requests[4].messages[-1]
    assert isinstance(feedback_message, AssistantMessage)
    assert feedback_message.content is not None
    feedback = feedback_message.content
    assert '"exit_code":1' in feedback
    assert "assert False is True" in feedback
    assert all(
        call.name != "run_command"
        for request in fake.requests
        for message in request.messages
        if isinstance(message, AssistantMessage)
        for call in message.tool_calls
    )

    events = [
        json.loads(line)
        for line in (workspace / report["log_path"]).read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert events[0]["event_type"] == "run_started"
    assert events[-1]["event_type"] == "run_completed"
    assert [event["sequence"] for event in events] == list(
        range(1, len(events) + 1)
    )
    log_text = json.dumps(events, ensure_ascii=False)
    assert FAKE_KEY not in log_text
    assert config.task not in log_text

    final_verification = _run_pytest(workspace)
    assert final_verification.returncode == 0, (
        final_verification.stdout + final_verification.stderr
    )
    assert "2 passed" in final_verification.stdout
    assert network_calls == []

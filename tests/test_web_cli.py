from __future__ import annotations

from io import StringIO
from pathlib import Path
import socket
from typing import Callable

import pytest

from coding_agent.config import ApiMode, RunConfig
import coding_agent.web_cli as web_cli
from coding_agent.web_cli import build_web_parser, main


API_KEY = "web-cli-secret-value"


def test_web_parser_has_no_task_and_uses_ephemeral_port_by_default() -> None:
    args = build_web_parser().parse_args(["--workspace", "workspace"])

    assert not hasattr(args, "task")
    assert args.workspace == "workspace"
    assert args.verify is None
    assert args.model is None
    assert args.api_mode == "responses"
    assert args.base_url is None
    assert args.port == 0
    assert args.open_browser is True


def test_web_main_passes_existing_config_and_web_options_to_injected_app(
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}

    def application(
        config: RunConfig,
        *,
        port: int,
        open_browser: bool,
        stdout: StringIO,
        stderr: StringIO,
    ) -> int:
        observed.update(
            task=config.task,
            workspace=config.workspace,
            model=config.model,
            api_mode=config.api_mode,
            base_url=config.base_url,
            port=port,
            open_browser=open_browser,
        )
        return 17

    stdout = StringIO()
    stderr = StringIO()
    result = main(
        ["--workspace", str(tmp_path), "--model", "test-model"],
        environ={"OPENAI_API_KEY": API_KEY},
        stdout=stdout,
        stderr=stderr,
        application=application,
    )

    assert result == 17
    assert observed == {
        "task": "local web session",
        "workspace": tmp_path.resolve(),
        "model": "test-model",
        "api_mode": ApiMode.RESPONSES,
        "base_url": None,
        "port": 0,
        "open_browser": True,
    }
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == ""


def test_web_main_no_open_browser_changes_only_application_flag(
    tmp_path: Path,
) -> None:
    observed: list[bool] = []

    def application(
        _config: RunConfig,
        *,
        port: int,
        open_browser: bool,
        stdout: StringIO,
        stderr: StringIO,
    ) -> int:
        del port, stdout, stderr
        observed.append(open_browser)
        return 0

    assert main(
        ["--workspace", str(tmp_path), "--no-open-browser"],
        environ={"OPENAI_API_KEY": API_KEY, "OPENAI_MODEL": "test-model"},
        stdout=StringIO(),
        stderr=StringIO(),
        application=application,
    ) == 0
    assert observed == [False]


@pytest.mark.parametrize("port", ["1", "65535"])
def test_web_parser_accepts_explicit_valid_ports(port: str) -> None:
    args = build_web_parser().parse_args(
        ["--workspace", "workspace", "--port", port]
    )

    assert args.port == int(port)


@pytest.mark.parametrize(
    "port",
    ["0", "-1", "65536", "not-a-port", "true", "false"],
)
def test_web_parser_rejects_invalid_explicit_ports(port: str) -> None:
    with pytest.raises(SystemExit) as caught:
        build_web_parser().parse_args(
            ["--workspace", "workspace", "--port", port]
        )

    assert caught.value.code == 2


class RecordingSocket:
    def __init__(self, events: list[str], *, assigned_port: int = 43123) -> None:
        self._events = events
        self._assigned_port = assigned_port
        self.closed = 0
        self.options: list[tuple[int, int, int]] = []

    def setsockopt(self, level: int, option: int, value: int) -> None:
        self.options.append((level, option, value))

    def bind(self, address: tuple[str, int]) -> None:
        self._events.append(f"socket:bind:{address[0]}:{address[1]}")

    def listen(self) -> None:
        self._events.append("socket:listen")

    def getsockname(self) -> tuple[str, int]:
        return ("127.0.0.1", self._assigned_port)

    def close(self) -> None:
        self.closed += 1
        self._events.append("socket:close")


class RecordingController:
    def __init__(
        self,
        events: list[str],
        shutdown_results: list[bool] | None = None,
    ) -> None:
        self._events = events
        self._shutdown_results = list(shutdown_results or [True])

    def shutdown(self, *, timeout_seconds: float) -> bool:
        self._events.append(f"controller:shutdown:{timeout_seconds}")
        if not self._shutdown_results:
            raise AssertionError("unexpected shutdown call")
        return self._shutdown_results.pop(0)


class RecordingServer:
    def __init__(
        self,
        events: list[str],
        outcome: BaseException | None = None,
    ) -> None:
        self._events = events
        self._outcome = outcome
        self.sockets: list[object] | None = None

    def run(self, *, sockets: list[object]) -> None:
        self._events.append("server:run")
        self.sockets = sockets
        if self._outcome is not None:
            raise self._outcome


def _run_config(tmp_path: Path) -> RunConfig:
    return RunConfig(
        task="local web session",
        workspace=tmp_path.resolve(),
        model="test-model",
        api_key=API_KEY,
    )


def _patch_composition(
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
    *,
    shutdown_results: list[bool] | None = None,
    server_outcome: BaseException | None = None,
) -> tuple[RecordingSocket, RecordingController, RecordingServer, dict[str, object]]:
    listener = RecordingSocket(events)
    controller = RecordingController(events, shutdown_results)
    server = RecordingServer(events, server_outcome)
    observed: dict[str, object] = {}

    def socket_factory() -> RecordingSocket:
        events.append("socket:create")
        return listener

    class Policy:
        token = "web-access-secret"

    def policy_factory(port: int) -> Policy:
        events.append(f"policy:generate:{port}")
        observed["policy_port"] = port
        return Policy()

    def executor_factory(config: RunConfig) -> object:
        observed["executor_config"] = config
        return object()

    def controller_factory(
        workspace: Path,
        executor: object,
        *,
        sensitive_values: tuple[str, ...],
    ) -> RecordingController:
        events.append("controller:open")
        observed["controller_args"] = (workspace, executor, sensitive_values)
        return controller

    def app_factory(*, controller: object, access_policy: object) -> object:
        events.append("app:create")
        observed["app_args"] = (controller, access_policy)
        return object()

    def config_factory(app: object, **options: object) -> object:
        observed["uvicorn_config"] = (app, options)
        return object()

    def server_factory(_config: object) -> RecordingServer:
        events.append("server:create")
        return server

    def forbidden_browser_open(_url: str) -> bool:
        raise AssertionError("Task 22 must not open a browser")

    monkeypatch.setattr(web_cli, "_socket_factory", socket_factory, raising=False)
    monkeypatch.setattr(web_cli, "_policy_factory", policy_factory, raising=False)
    monkeypatch.setattr(web_cli, "_executor_factory", executor_factory, raising=False)
    monkeypatch.setattr(
        web_cli,
        "_controller_factory",
        controller_factory,
        raising=False,
    )
    monkeypatch.setattr(web_cli, "_web_app_factory", app_factory, raising=False)
    monkeypatch.setattr(
        web_cli,
        "_uvicorn_config_factory",
        config_factory,
        raising=False,
    )
    monkeypatch.setattr(
        web_cli,
        "_uvicorn_server_factory",
        server_factory,
        raising=False,
    )
    monkeypatch.setattr(
        web_cli,
        "_browser_open",
        forbidden_browser_open,
        raising=False,
    )
    return listener, controller, server, observed


def test_web_application_uses_prebound_loopback_socket_and_reverse_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    listener, controller, server, observed = _patch_composition(
        monkeypatch,
        events,
    )
    stdout = StringIO()
    stderr = StringIO()

    result = web_cli.run_web_application(
        _run_config(tmp_path),
        port=0,
        open_browser=True,
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert events == [
        "socket:create",
        "socket:bind:127.0.0.1:0",
        "socket:listen",
        "policy:generate:43123",
        "controller:open",
        "app:create",
        "server:create",
        "server:run",
        "controller:shutdown:5.0",
        "socket:close",
    ]
    assert server.sockets == [listener]
    app, options = observed["uvicorn_config"]
    assert app is not None
    assert options == {
        "workers": 1,
        "access_log": False,
        "server_header": False,
        "proxy_headers": False,
        "reload": False,
    }
    workspace, _executor, sensitive_values = observed["controller_args"]
    assert workspace == tmp_path.resolve()
    assert sensitive_values == (API_KEY, "web-access-secret")
    assert stdout.getvalue() == (
        "Local coding agent: http://127.0.0.1:43123/\n"
    )
    assert stderr.getvalue() == ""
    assert listener.closed == 1
    assert controller is not None


def test_web_application_uses_exclusive_windows_address_option_when_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    listener, _controller, _server, _observed = _patch_composition(
        monkeypatch,
        events,
    )

    assert web_cli.run_web_application(
        _run_config(tmp_path),
        port=12345,
        open_browser=False,
        stdout=StringIO(),
        stderr=StringIO(),
    ) == 0

    assert all(option != socket.SO_REUSEADDR for _, option, _ in listener.options)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        assert (
            socket.SOL_SOCKET,
            socket.SO_EXCLUSIVEADDRUSE,
            1,
        ) in listener.options


def test_web_application_waits_cooperatively_and_warns_only_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    listener, _controller, _server, _observed = _patch_composition(
        monkeypatch,
        events,
        shutdown_results=[False, False, True],
    )
    stderr = StringIO()

    result = web_cli.run_web_application(
        _run_config(tmp_path),
        port=0,
        open_browser=False,
        stdout=StringIO(),
        stderr=stderr,
    )

    assert result == 0
    assert events[-4:] == [
        "controller:shutdown:5.0",
        "controller:shutdown:5.0",
        "controller:shutdown:5.0",
        "socket:close",
    ]
    assert stderr.getvalue() == "warning: shutdown_pending\n"
    assert listener.closed == 1


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt()])
def test_web_application_cleans_up_keyboard_interrupt_with_stable_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt: BaseException,
) -> None:
    events: list[str] = []
    listener, _controller, _server, _observed = _patch_composition(
        monkeypatch,
        events,
        server_outcome=interrupt,
    )
    stderr = StringIO()

    result = web_cli.run_web_application(
        _run_config(tmp_path),
        port=0,
        open_browser=False,
        stdout=StringIO(),
        stderr=stderr,
    )

    assert result == 130
    assert events[-2:] == ["controller:shutdown:5.0", "socket:close"]
    assert listener.closed == 1
    assert stderr.getvalue() == "error: interrupted\n"


def test_web_application_cleans_up_then_propagates_system_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    listener, _controller, _server, _observed = _patch_composition(
        monkeypatch,
        events,
        server_outcome=SystemExit(23),
    )

    with pytest.raises(SystemExit) as caught:
        web_cli.run_web_application(
            _run_config(tmp_path),
            port=0,
            open_browser=False,
            stdout=StringIO(),
            stderr=StringIO(),
        )

    assert caught.value.code == 23
    assert events[-2:] == ["controller:shutdown:5.0", "socket:close"]
    assert listener.closed == 1


@pytest.mark.parametrize(
    "failure_point",
    [
        "socket:create",
        "socket:bind",
        "policy:generate",
        "controller:open",
        "app:create",
        "server:create",
        "server:run",
    ],
)
def test_web_application_startup_failures_are_sanitized_and_cleaned_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    private_sentinel = "PRIVATE path C:/users/example secret-value"
    events: list[str] = []
    listener, controller, server, _observed = _patch_composition(
        monkeypatch,
        events,
    )

    def failure() -> None:
        raise RuntimeError(private_sentinel)

    if failure_point == "socket:create":
        monkeypatch.setattr(web_cli, "_socket_factory", failure)
    elif failure_point == "socket:bind":
        listener.bind = lambda _address: failure()  # type: ignore[method-assign]
    elif failure_point == "policy:generate":
        monkeypatch.setattr(web_cli, "_policy_factory", lambda _port: failure())
    elif failure_point == "controller:open":
        monkeypatch.setattr(
            web_cli,
            "_controller_factory",
            lambda *_args, **_kwargs: failure(),
        )
    elif failure_point == "app:create":
        monkeypatch.setattr(
            web_cli,
            "_web_app_factory",
            lambda **_kwargs: failure(),
        )
    elif failure_point == "server:create":
        monkeypatch.setattr(
            web_cli,
            "_uvicorn_server_factory",
            lambda _config: failure(),
        )
    else:
        server._outcome = RuntimeError(private_sentinel)

    stdout = StringIO()
    stderr = StringIO()
    result = web_cli.run_web_application(
        _run_config(tmp_path),
        port=0,
        open_browser=True,
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 1
    assert stderr.getvalue() == "error: web_server_failed\n"
    assert private_sentinel not in stdout.getvalue()
    assert private_sentinel not in stderr.getvalue()
    assert API_KEY not in stdout.getvalue()
    assert API_KEY not in stderr.getvalue()
    assert listener.closed == (0 if failure_point == "socket:create" else 1)
    controller_created = failure_point in {
        "app:create",
        "server:create",
        "server:run",
    }
    assert events.count("controller:shutdown:5.0") == int(controller_created)

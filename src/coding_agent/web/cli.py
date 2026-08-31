from __future__ import annotations

import argparse
import socket
import sys
from typing import Mapping, NoReturn, Protocol, Sequence, TextIO
import webbrowser

import uvicorn

from coding_agent.application.config import ConfigError, RunConfig, load_run_config
from coding_agent.providers.model_catalog import create_model_catalog
from coding_agent.sessions.session_controller import SessionController
from coding_agent.sessions.session_runtime import AgentSessionRunExecutor
from coding_agent.web.app import create_web_app
from coding_agent.web.auth import WebAccessPolicy


class WebApplication(Protocol):
    def __call__(
        self,
        config: RunConfig,
        *,
        port: int,
        open_browser: bool,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int: ...


_socket_factory = lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM)
_policy_factory = WebAccessPolicy.generate
_executor_factory = AgentSessionRunExecutor
_model_catalog_factory = create_model_catalog
_controller_factory = SessionController.open
_web_app_factory = create_web_app


def _uvicorn_config_factory(app: object, **options: object) -> uvicorn.Config:
    return uvicorn.Config(
        app,
        log_config=None,
        log_level="critical",
        **options,
    )


class _ReadyUvicornServer(uvicorn.Server):
    def __init__(
        self,
        config: uvicorn.Config,
        *,
        on_ready,
    ) -> None:
        super().__init__(config)
        self._on_ready = on_ready

    async def startup(self, sockets=None) -> None:
        await super().startup(sockets=sockets)
        if self.started:
            self._on_ready()


def _uvicorn_server_factory(
    config: uvicorn.Config,
    *,
    on_ready,
) -> uvicorn.Server:
    return _ReadyUvicornServer(config, on_ready=on_ready)


_browser_open = webbrowser.open


def _explicit_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "port must be an integer from 1 through 65535"
        ) from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(
            "port must be an integer from 1 through 65535"
        )
    return port


def build_web_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coding-agent-web",
        description="Run the local coding agent Web interface.",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="Existing workspace directory",
    )
    parser.add_argument(
        "--verify",
        default=None,
        help="User-specified required final verification command",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model identifier; overrides OPENAI_MODEL",
    )
    parser.add_argument(
        "--api-mode",
        choices=("responses", "chat-completions"),
        default="responses",
        help="Model API mode; defaults to responses",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="HTTPS API base URL; required only for chat-completions",
    )
    parser.add_argument(
        "--port",
        type=_explicit_port,
        default=0,
        help="Loopback TCP port; defaults to an ephemeral port",
    )
    parser.add_argument(
        "--no-open-browser",
        action="store_false",
        dest="open_browser",
        help="Do not open the local interface in a browser",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    application: WebApplication | None = None,
) -> int:
    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    args = build_web_parser().parse_args(argv)
    try:
        config = load_run_config(
            task="local web session",
            workspace=args.workspace,
            model=args.model,
            verify_command=args.verify,
            api_mode=args.api_mode,
            base_url=args.base_url,
            environ=environ,
        )
    except ConfigError as exc:
        print(f"error: {exc}", file=errors)
        return 2

    if application is None:
        application = run_web_application
    return application(
        config,
        port=args.port,
        open_browser=args.open_browser,
        stdout=output,
        stderr=errors,
    )


def run_web_application(
    config: RunConfig,
    *,
    port: int,
    open_browser: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    listener = None
    controller = None
    exit_code = 0
    try:
        listener = _socket_factory()
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_EXCLUSIVEADDRUSE,
                1,
            )
        listener.bind(("127.0.0.1", port))
        listener.listen()
        assigned_port = int(listener.getsockname()[1])
        policy = _policy_factory(assigned_port)
        executor = _executor_factory(config)
        model_catalog = _model_catalog_factory(config)
        controller = _controller_factory(
            config.workspace,
            executor,
            model_catalog=model_catalog,
            sensitive_values=(config.api_key, policy.token),
        )
        app = _web_app_factory(
            controller=controller,
            access_policy=policy,
        )
        server_config = _uvicorn_config_factory(
            app,
            workers=1,
            access_log=False,
            server_header=False,
            proxy_headers=False,
            reload=False,
        )
        local_url = f"http://127.0.0.1:{assigned_port}/"

        def on_ready() -> None:
            if not open_browser:
                return
            try:
                opened = _browser_open(local_url)
            except Exception:
                opened = False
            if not opened:
                _write_fixed(
                    stderr,
                    "warning: unable to open local browser\n",
                )

        server = _uvicorn_server_factory(
            server_config,
            on_ready=on_ready,
        )
        stdout.write(f"Local coding agent: {local_url}\n")
        server.run(sockets=[listener])
    except KeyboardInterrupt:
        exit_code = 130
        _write_fixed(stderr, "error: interrupted\n")
    except Exception:
        exit_code = 1
        _write_fixed(stderr, "error: web_server_failed\n")
    finally:
        if controller is not None:
            warning_written = False
            while True:
                try:
                    shutdown_complete = controller.shutdown(
                        timeout_seconds=5.0
                    )
                except Exception:
                    if exit_code == 0:
                        exit_code = 1
                        _write_fixed(stderr, "error: web_server_failed\n")
                    break
                if shutdown_complete:
                    break
                if not warning_written:
                    _write_fixed(stderr, "warning: shutdown_pending\n")
                    warning_written = True
        if listener is not None:
            try:
                listener.close()
            except Exception:
                if exit_code == 0:
                    exit_code = 1
                    _write_fixed(stderr, "error: web_server_failed\n")
    return exit_code


def _write_fixed(stream: TextIO, message: str) -> None:
    try:
        stream.write(message)
    except Exception:
        return


def entrypoint() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()

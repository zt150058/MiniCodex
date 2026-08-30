from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING, Mapping, NoReturn, Sequence, TextIO

from coding_agent.config import ConfigError, load_run_config
from coding_agent.run_mode import RunMode

if TYPE_CHECKING:
    from coding_agent.app import Application


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coding-agent",
        description=(
            "Run a one-shot local coding agent. It may read and modify workspace "
            "files and run authorized commands."
        ),
    )
    parser.add_argument("task", help="Coding task for the local agent")
    parser.add_argument(
        "--workspace",
        required=True,
        help="Existing workspace directory",
    )
    parser.add_argument(
        "--verify",
        default=None,
        help=(
            "User-specified required final verification command; authorized "
            "before the agent starts and run after the latest file modification."
        ),
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Inspect and answer without file mutation or verification tools",
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
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    application: Application | None = None,
) -> int:
    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    args = build_parser().parse_args(argv)
    if args.read_only and args.verify is not None:
        print(
            "error: --read-only cannot be combined with --verify",
            file=errors,
        )
        return 2
    try:
        config = load_run_config(
            task=args.task,
            workspace=args.workspace,
            model=args.model,
            verify_command=args.verify,
            api_mode=args.api_mode,
            base_url=args.base_url,
            environ=environ,
            run_mode=(
                RunMode.READ_ONLY if args.read_only else RunMode.MODIFY
            ),
        )
    except ConfigError as exc:
        print(f"error: {exc}", file=errors)
        return 2

    if application is None:
        from coding_agent.app import run_application

        application = run_application
    return application(config, stdout=output, stderr=errors)


def entrypoint() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()

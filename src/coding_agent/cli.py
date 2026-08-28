from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING, Mapping, NoReturn, Sequence, TextIO

from coding_agent.config import ConfigError, load_run_config

if TYPE_CHECKING:
    from coding_agent.app import Application


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coding-agent",
        description="Validate configuration for a one-shot local coding-agent task.",
    )
    parser.add_argument("task", help="One-shot coding task to validate")
    parser.add_argument(
        "--workspace",
        required=True,
        help="Existing workspace directory",
    )
    parser.add_argument(
        "--verify",
        default=None,
        help=(
            "Optional final verification command; authorized now and "
            "executed by Task 11."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model; overrides OPENAI_MODEL",
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
    try:
        config = load_run_config(
            task=args.task,
            workspace=args.workspace,
            model=args.model,
            verify_command=args.verify,
            environ=environ,
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

from __future__ import annotations

import argparse
import sys
from typing import Mapping, NoReturn, Sequence

from coding_agent.config import ConfigError, load_run_config


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
) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_run_config(
            task=args.task,
            workspace=args.workspace,
            model=args.model,
            verify_command=args.verify,
            environ=environ,
        )
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print("Configuration valid. Agent execution is not implemented in task 1.")
    return 0


def entrypoint() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()

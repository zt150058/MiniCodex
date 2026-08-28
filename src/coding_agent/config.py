from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Mapping

from coding_agent.safety import (
    AuthorizedCommand,
    CommandPolicy,
    CommandSource,
    PathGuard,
    SafetyCode,
    SafetyViolation,
)
from coding_agent.verification import is_credible_verification_command


class ConfigError(ValueError):
    """Raised when task-1 CLI configuration is invalid."""


@dataclass(frozen=True, slots=True)
class RunConfig:
    task: str
    workspace: Path
    model: str
    api_key: str = field(repr=False)
    verify_command: AuthorizedCommand | None = field(default=None, repr=False)


def load_run_config(
    *,
    task: str,
    workspace: str | Path,
    model: str | None,
    verify_command: str | None,
    environ: Mapping[str, str] | None = None,
) -> RunConfig:
    source = os.environ if environ is None else environ

    normalized_task = task.strip()
    if not normalized_task:
        raise ConfigError("task must not be empty")

    workspace_path = Path(workspace).expanduser()
    try:
        normalized_workspace = PathGuard(workspace_path).workspace
    except SafetyViolation as exc:
        if exc.code is SafetyCode.WORKSPACE_INVALID:
            if not workspace_path.exists():
                raise ConfigError("workspace does not exist") from None
            if not workspace_path.is_dir():
                raise ConfigError("workspace must be a directory") from None
        raise ConfigError(
            f"workspace rejected ({exc.code.value}): {exc.public_message}"
        ) from None

    selected_model = model if model is not None else source.get("OPENAI_MODEL", "")
    normalized_model = selected_model.strip()
    if not normalized_model:
        raise ConfigError("model is not configured; pass --model or set OPENAI_MODEL")

    normalized_api_key = source.get("OPENAI_API_KEY", "").strip()
    if not normalized_api_key:
        raise ConfigError("OPENAI_API_KEY is not configured")

    authorized_verify: AuthorizedCommand | None = None
    if verify_command is not None:
        normalized_verify = verify_command.strip()
        if not normalized_verify:
            raise ConfigError("--verify must not be empty")
        try:
            authorized_verify = CommandPolicy(normalized_workspace).authorize(
                normalized_verify,
                purpose="verification",
                source=CommandSource.USER_VERIFY,
            )
        except SafetyViolation as exc:
            raise ConfigError(
                f"--verify rejected ({exc.code.value}): {exc.public_message}"
            ) from None
        if not is_credible_verification_command(authorized_verify):
            raise ConfigError(
                "--verify rejected (verification_not_credible): "
                "command is not a credible verification command"
            )

    return RunConfig(
        task=normalized_task,
        workspace=normalized_workspace,
        model=normalized_model,
        api_key=normalized_api_key,
        verify_command=authorized_verify,
    )

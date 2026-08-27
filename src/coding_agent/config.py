from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Mapping


class ConfigError(ValueError):
    """Raised when task-1 CLI configuration is invalid."""


@dataclass(frozen=True, slots=True)
class RunConfig:
    task: str
    workspace: Path
    model: str
    api_key: str = field(repr=False)
    verify_command: str | None = None


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
        normalized_workspace = workspace_path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ConfigError(f"workspace does not exist: {workspace_path}") from exc
    if not normalized_workspace.is_dir():
        raise ConfigError(f"workspace must be a directory: {workspace_path}")

    selected_model = model if model is not None else source.get("OPENAI_MODEL", "")
    normalized_model = selected_model.strip()
    if not normalized_model:
        raise ConfigError("model is not configured; pass --model or set OPENAI_MODEL")

    normalized_api_key = source.get("OPENAI_API_KEY", "").strip()
    if not normalized_api_key:
        raise ConfigError("OPENAI_API_KEY is not configured")

    normalized_verify: str | None = None
    if verify_command is not None:
        normalized_verify = verify_command.strip()
        if not normalized_verify:
            raise ConfigError("--verify must not be empty")

    return RunConfig(
        task=normalized_task,
        workspace=normalized_workspace,
        model=normalized_model,
        api_key=normalized_api_key,
        verify_command=normalized_verify,
    )

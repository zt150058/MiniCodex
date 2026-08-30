from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from coding_agent.run_mode import RunMode
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


class ApiMode(StrEnum):
    RESPONSES = "responses"
    CHAT_COMPLETIONS = "chat-completions"


@dataclass(frozen=True, slots=True)
class RunConfig:
    task: str
    workspace: Path
    model: str
    api_key: str = field(repr=False)
    api_mode: ApiMode = ApiMode.RESPONSES
    base_url: str | None = field(default=None, repr=False)
    verify_command: AuthorizedCommand | None = field(default=None, repr=False)
    run_mode: RunMode = RunMode.MODIFY

    def __post_init__(self) -> None:
        if not isinstance(self.run_mode, RunMode):
            raise ConfigError("run mode must be 'modify' or 'read_only'")
        if not isinstance(self.api_mode, ApiMode):
            raise ConfigError(
                "api mode must be one of: responses, chat-completions"
            )
        if self.api_mode is ApiMode.RESPONSES:
            if self.base_url is not None:
                raise ConfigError("--base-url is not allowed with responses")
            return
        if self.base_url is None:
            raise ConfigError("--base-url is required with chat-completions")
        object.__setattr__(
            self,
            "base_url",
            _normalize_chat_base_url(self.base_url),
        )


_BASE_URL_ERROR = (
    "--base-url must be an absolute HTTPS URL without userinfo, query, or "
    "fragment"
)


def _normalize_chat_base_url(value: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(_BASE_URL_ERROR)
    if any(
        ord(character) <= 0x1F
        or ord(character) == 0x7F
        or character == "\\"
        for character in value
    ):
        raise ConfigError(_BASE_URL_ERROR)
    normalized = value.strip(" ")
    if not normalized:
        raise ConfigError("--base-url is required with chat-completions")
    if any(character.isspace() for character in normalized):
        raise ConfigError(_BASE_URL_ERROR)
    try:
        parsed = urlsplit(normalized)
        host = parsed.hostname
        parsed.port
    except ValueError:
        raise ConfigError(_BASE_URL_ERROR) from None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or host is None
        or not host.strip()
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in parsed.netloc)
        or "?" in normalized
        or "#" in normalized
    ):
        raise ConfigError(_BASE_URL_ERROR)
    return normalized.rstrip("/") + "/"


def load_run_config(
    *,
    task: str,
    workspace: str | Path,
    model: str | None,
    verify_command: str | None,
    api_mode: ApiMode | str = ApiMode.RESPONSES,
    base_url: str | None = None,
    environ: Mapping[str, str] | None = None,
    run_mode: RunMode | str = RunMode.MODIFY,
) -> RunConfig:
    source = os.environ if environ is None else environ

    if isinstance(run_mode, bool):
        raise ConfigError("run mode must be 'modify' or 'read_only'")
    try:
        selected_run_mode = RunMode(run_mode)
    except (TypeError, ValueError):
        raise ConfigError("run mode must be 'modify' or 'read_only'") from None

    try:
        selected_mode = ApiMode(api_mode)
    except (TypeError, ValueError):
        raise ConfigError(
            "api mode must be one of: responses, chat-completions"
        ) from None

    normalized_base_url: str | None = None
    if selected_mode is ApiMode.RESPONSES:
        if base_url is not None:
            raise ConfigError("--base-url is not allowed with responses")
        credential_name = "OPENAI_API_KEY"
    else:
        if base_url is None:
            raise ConfigError("--base-url is required with chat-completions")
        normalized_base_url = _normalize_chat_base_url(base_url)
        credential_name = "CHAT_COMPLETIONS_API_KEY"

    normalized_api_key = source.get(credential_name, "").strip()
    if not normalized_api_key:
        raise ConfigError(f"{credential_name} is not configured")

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
        api_mode=selected_mode,
        base_url=normalized_base_url,
        verify_command=authorized_verify,
        run_mode=selected_run_mode,
    )

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Protocol

from coding_agent.messages import JSONObject, ToolResultMetadata


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    workspace: Path
    command_timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        timeout = self.command_timeout_seconds
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
            or timeout > 300
        ):
            raise ValueError(
                "command_timeout_seconds must be greater than 0 and at most 300"
            )


@dataclass(frozen=True, slots=True)
class ToolExecution:
    output: str | None = None
    metadata: ToolResultMetadata = field(default_factory=ToolResultMetadata)


class ToolArgumentError(ValueError):
    """A tool rejected model-supplied arguments before execution."""


class Tool(Protocol):
    name: str
    schema: JSONObject

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution: ...

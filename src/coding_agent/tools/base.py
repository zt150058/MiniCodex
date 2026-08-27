from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from coding_agent.messages import JSONObject, ToolResultMetadata


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    workspace: Path


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

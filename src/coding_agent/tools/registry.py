from __future__ import annotations

from collections.abc import Iterable

from coding_agent.messages import JSONObject, ToolCall, ToolResult
from coding_agent.tools.base import ExecutionContext, Tool, ToolArgumentError


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    @property
    def schemas(self) -> tuple[JSONObject, ...]:
        return tuple(tool.schema for tool in self._tools.values())

    def execute(
        self,
        call: ToolCall,
        context: ExecutionContext,
    ) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                status="rejected",
                error=f"unknown_tool: no tool registered as {call.name!r}",
            )

        try:
            execution = tool.execute(call.arguments, context)
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                status="ok",
                output=execution.output,
                metadata=execution.metadata,
            )
        except ToolArgumentError as exc:
            detail = str(exc).strip() or "invalid arguments"
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                status="rejected",
                error=f"invalid_arguments: {detail}",
            )
        except Exception as exc:
            detail = str(exc).strip() or "no detail"
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                status="error",
                error=f"tool_execution_failed: {type(exc).__name__}: {detail}",
            )

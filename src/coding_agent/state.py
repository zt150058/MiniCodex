from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from coding_agent.messages import Message, UserMessage


class AgentStatus(StrEnum):
    RUNNING = "running"
    COMPLETION_CANDIDATE = "completion_candidate"
    FAILED = "failed"


@dataclass(slots=True)
class AgentState:
    task: str
    current_goal: str
    messages: tuple[Message, ...]
    open_issues: tuple[str, ...] = ()
    status: AgentStatus = AgentStatus.RUNNING
    model_call_count: int = 0
    tool_call_count: int = 0
    completion_text: str | None = None
    failure_reason: str | None = None
    continuation_items: tuple[object, ...] = field(default=(), repr=False)

    @classmethod
    def start(cls, task: str) -> AgentState:
        user_message = UserMessage(task)
        return cls(
            task=user_message.content,
            current_goal=user_message.content,
            messages=(user_message,),
        )

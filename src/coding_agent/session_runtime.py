from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from pathlib import Path

from coding_agent.budget import BudgetProfile
from typing import TYPE_CHECKING, Protocol

from coding_agent.agent import CancellationCheck, ConfirmedTextHandler
from coding_agent.config import RunConfig
from coding_agent.context import ContextLimits, ContextManager
from coding_agent.logging import RunEventObserver
from coding_agent.messages import JSONObject
from coding_agent.messages import UserMessage
from coding_agent.model_catalog import ModelCatalogError, require_model_id
from coding_agent.run_mode import RunMode
from coding_agent.session import (
    SessionError,
    SessionNarrativeEntry,
    SessionRunResult,
    SessionRunStatus,
    make_persisted_run_report,
    make_safe_run_summary,
)
from coding_agent.skills import SkillInstructionBundle
from coding_agent.streaming import ModelStreamHandler

if TYPE_CHECKING:
    from coding_agent.app import ApplicationFactories


_SESSION_CONTEXT_MARKER = "coding-agent session context\n"
_CURRENT_REQUEST_MARKER = "\ncurrent request\n"


class SessionNarrativeRenderer:
    def __init__(
        self,
        max_serialized_chars: int = ContextLimits().max_serialized_chars,
    ) -> None:
        if (
            isinstance(max_serialized_chars, bool)
            or not isinstance(max_serialized_chars, int)
            or max_serialized_chars <= 0
        ):
            raise ValueError("max_serialized_chars must be a positive integer")
        self._max_serialized_chars = max_serialized_chars

    @staticmethod
    def _render(
        entries: list[SessionNarrativeEntry],
        omitted_entries: int,
        current_request: str,
    ) -> str:
        payload = {
            "history": [
                {
                    "content": entry.content,
                    "kind": entry.kind.value,
                    "run_id": entry.run_id,
                }
                for entry in entries
            ],
            "omitted_entries": omitted_entries,
        }
        return (
            _SESSION_CONTEXT_MARKER
            + json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + _CURRENT_REQUEST_MARKER
            + current_request
        )

    def _fits(self, rendered: str) -> bool:
        try:
            message = UserMessage(rendered)
        except (TypeError, ValueError):
            return False
        return (
            ContextManager.measure((message,)).serialized_chars
            <= self._max_serialized_chars
        )

    def render(
        self,
        entries: tuple[SessionNarrativeEntry, ...],
        current_request: str,
    ) -> str:
        if not isinstance(entries, tuple) or any(
            not isinstance(entry, SessionNarrativeEntry) for entry in entries
        ):
            raise TypeError("entries must be a tuple of SessionNarrativeEntry")
        try:
            UserMessage(current_request)
        except (TypeError, ValueError):
            raise SessionError("invalid_message") from None

        selected: list[SessionNarrativeEntry] = []
        omitted = len(entries)
        rendered = self._render(selected, omitted, current_request)
        if not self._fits(rendered):
            raise SessionError("invalid_message")

        for entry in reversed(entries):
            candidate = [entry, *selected]
            candidate_rendered = self._render(
                candidate,
                omitted - 1,
                current_request,
            )
            if self._fits(candidate_rendered):
                selected = candidate
                omitted -= 1
                rendered = candidate_rendered
        return rendered


@dataclass(frozen=True, slots=True)
class SessionRunRequest:
    session_id: str
    run_id: str
    model_id: str = field(repr=False)
    current_message: str = field(repr=False)
    initial_user_message: str = field(repr=False)
    skill_bundle: SkillInstructionBundle | None = field(default=None, repr=False)
    run_mode: RunMode = RunMode.MODIFY
    budget_profile: BudgetProfile = BudgetProfile.STANDARD

    def __post_init__(self) -> None:
        try:
            require_model_id(self.model_id)
        except ModelCatalogError:
            raise ValueError("model_id must be a valid model identifier") from None
        if type(self.run_mode) is not RunMode:
            raise TypeError("run_mode must be RunMode")
        if type(self.budget_profile) is not BudgetProfile:
            raise TypeError("budget_profile must be BudgetProfile")
        if self.skill_bundle is not None and type(self.skill_bundle) is not SkillInstructionBundle:
            raise TypeError("skill_bundle must be SkillInstructionBundle or None")
        for value, name in (
            (self.session_id, "session_id"),
            (self.run_id, "run_id"),
        ):
            if (
                not isinstance(value, str)
                or len(value) != 32
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError(f"{name} must be a lowercase UUID hex string")
        for value in (self.current_message, self.initial_user_message):
            try:
                UserMessage(value)
            except (TypeError, ValueError):
                raise SessionError("invalid_message") from None


@dataclass(frozen=True, slots=True)
class SessionRunOutcome:
    status: SessionRunStatus
    agent_status: str | None
    termination_reason: str | None
    audit_run_id: str | None
    safe_summary: JSONObject = field(repr=False)
    final_report: JSONObject | None = field(repr=False)


class SessionRunExecutor(Protocol):
    @property
    def workspace(self) -> Path: ...

    @property
    def default_model_id(self) -> str: ...

    def execute(
        self,
        request: SessionRunRequest,
        *,
        stream_handler: ModelStreamHandler,
        confirmed_text_handler: ConfirmedTextHandler,
        cancellation_requested: CancellationCheck,
        run_event_handler: RunEventObserver,
    ) -> SessionRunOutcome: ...


class AgentSessionRunExecutor:
    def __init__(
        self,
        base_config: RunConfig,
        *,
        factories: ApplicationFactories | None = None,
    ) -> None:
        if not isinstance(base_config, RunConfig):
            raise TypeError("base_config must be RunConfig")
        if factories is not None:
            from coding_agent.app import ApplicationFactories

            if not isinstance(factories, ApplicationFactories):
                raise TypeError("factories must be ApplicationFactories or null")
        self._base_config = base_config
        self._factories = factories
        self._workspace = base_config.workspace.resolve(strict=True)

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def default_model_id(self) -> str:
        return self._base_config.model

    def execute(
        self,
        request: SessionRunRequest,
        *,
        stream_handler: ModelStreamHandler,
        confirmed_text_handler: ConfirmedTextHandler,
        cancellation_requested: CancellationCheck,
        run_event_handler: RunEventObserver,
    ) -> SessionRunOutcome:
        if not isinstance(request, SessionRunRequest):
            raise TypeError("request must be SessionRunRequest")
        from coding_agent.app import execute_agent_run

        config = replace(
            self._base_config,
            task=request.current_message,
            model=request.model_id,
            run_mode=request.run_mode,
            budget_profile=request.budget_profile,
        )
        skill_instructions = (
            None if request.skill_bundle is None else request.skill_bundle.text
        )
        execution = execute_agent_run(
            config,
            factories=self._factories,
            stream_handler=stream_handler,
            confirmed_text_handler=confirmed_text_handler,
            cancellation_requested=cancellation_requested,
            initial_user_message=request.initial_user_message,
            event_observer=run_event_handler,
            skill_instructions=skill_instructions,
        )
        report = execution.report.to_dict()
        agent_status = execution.report.status.value
        termination_reason = (
            None
            if execution.report.termination_reason is None
            else execution.report.termination_reason.value
        )
        status = {
            "success": SessionRunStatus.SUCCEEDED,
            "answered": SessionRunStatus.SUCCEEDED,
            "failed": SessionRunStatus.FAILED,
            "interrupted": SessionRunStatus.INTERRUPTED,
        }[agent_status]
        safe_summary = make_safe_run_summary(
            report,
            status=agent_status,
            termination_reason=termination_reason,
        )
        persisted_report = make_persisted_run_report(report)
        validated = SessionRunResult(
            run_id=request.run_id,
            status=status,
            agent_status=agent_status,
            termination_reason=termination_reason,
            audit_run_id=execution.report.run_id,
            safe_summary=safe_summary,
            final_report=persisted_report,
        )
        return SessionRunOutcome(
            status=validated.status,
            agent_status=validated.agent_status,
            termination_reason=validated.termination_reason,
            audit_run_id=validated.audit_run_id,
            safe_summary=validated.safe_summary,
            final_report=validated.final_report,
        )

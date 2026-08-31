from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import time
from typing import Protocol, TextIO

from coding_agent.engine.agent import (
    AgentInterrupted,
    AgentRunner,
    CancellationCheck,
    ConfirmedTextHandler,
)
from coding_agent.providers.chat_completions_client import ChatCompletionsModelClient
from coding_agent.application.config import ApiMode, RunConfig
from coding_agent.engine.context import ContextLimits, ContextManager
from coding_agent.engine.instructions import RunInstructionBuilder
from coding_agent.engine.logging import RunEventLogger, RunEventObserver, RunLogError
from coding_agent.engine.model import ModelClient
from coding_agent.providers.openai_client import OpenAIResponsesClient
from coding_agent.engine.progress import ProgressLimits
from coding_agent.engine.report import FinalReport
from coding_agent.engine.run_mode import RunMode
from coding_agent.engine.state import AgentState, AgentStatus, TerminationReason
from coding_agent.engine.streaming import ModelStreamHandler
from coding_agent.engine.termination import TerminationLimits, TerminationPolicy
from coding_agent.operations.tools.base import ExecutionContext
from coding_agent.operations.tools.filesystem import (
    CreateDirectoryTool,
    ListDirectoryTool,
    ReadFileTool,
    ReplaceTextTool,
    WriteFileTool,
)
from coding_agent.operations.tools.registry import ToolRegistry
from coding_agent.operations.tools.java import RunJavaTestsTool
from coding_agent.operations.tools.shell import (
    AuthorizedCommandExecutor,
    InspectGitTool,
    RunCommandTool,
)
from coding_agent.engine.verification import VerificationGate


Clock = Callable[[], float]


class Application(Protocol):
    def __call__(
        self,
        config: RunConfig,
        *,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class ApplicationFactories:
    model_client: Callable[[RunConfig], ModelClient] = field(repr=False)
    logger: Callable[[RunConfig, Clock], RunEventLogger] = field(repr=False)
    command_executor: Callable[[], AuthorizedCommandExecutor] = field(repr=False)
    clock: Clock = field(repr=False)


def _production_model_client(config: RunConfig) -> ModelClient:
    if config.api_mode is ApiMode.RESPONSES:
        return OpenAIResponsesClient(model=config.model, api_key=config.api_key)
    if config.base_url is None:
        raise ValueError("chat-completions base_url is missing")
    return ChatCompletionsModelClient(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
    )


def _production_logger(config: RunConfig, clock: Clock) -> RunEventLogger:
    return RunEventLogger.create(
        config.workspace,
        sensitive_values=(config.api_key,),
        monotonic_clock=clock,
    )


def production_factories() -> ApplicationFactories:
    return ApplicationFactories(
        model_client=_production_model_client,
        logger=_production_logger,
        command_executor=AuthorizedCommandExecutor,
        clock=time.monotonic,
    )


class ApplicationRunError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AgentExecutionResult:
    state: AgentState = field(repr=False)
    report: FinalReport


def _close_after_failed_setup(logger: RunEventLogger) -> None:
    try:
        logger.close()
    except Exception:
        pass


def execute_agent_run(
    config: RunConfig,
    *,
    factories: ApplicationFactories | None = None,
    stream_handler: ModelStreamHandler | None = None,
    confirmed_text_handler: ConfirmedTextHandler | None = None,
    cancellation_requested: CancellationCheck | None = None,
    initial_user_message: str | None = None,
    event_observer: RunEventObserver | None = None,
    skill_instructions: str | None = None,
) -> AgentExecutionResult:
    if not isinstance(config, RunConfig):
        raise TypeError("config must be RunConfig")
    selected = production_factories() if factories is None else factories
    if not isinstance(selected, ApplicationFactories):
        raise TypeError("factories must be ApplicationFactories")

    try:
        logger = selected.logger(config, selected.clock)
    except RunLogError as exc:
        raise ApplicationRunError(f"audit_log_unavailable:{exc.code}") from None
    except KeyboardInterrupt:
        raise
    except Exception:
        raise ApplicationRunError("internal_application_failure") from None

    try:
        if event_observer is not None:
            logger.set_event_observer(event_observer)
        execution_context = ExecutionContext(config.workspace)
        executor = selected.command_executor()
        if config.run_mode is RunMode.READ_ONLY:
            tools = (
                ListDirectoryTool(),
                ReadFileTool(),
                InspectGitTool(authorized_executor=executor),
            )
            verification_gate = None
        else:
            tools = (
                ListDirectoryTool(),
                ReadFileTool(),
                CreateDirectoryTool(),
                ReplaceTextTool(),
                WriteFileTool(),
                RunCommandTool(authorized_executor=executor),
                RunJavaTestsTool(executor=executor),
            )
            verification_gate = VerificationGate(
                required_command=config.verify_command,
                execution_context=execution_context,
                executor=executor,
            )
        registry = ToolRegistry(tools)
        model_client = selected.model_client(config)
        context_manager = ContextManager(
            model_client=model_client,
            limits=ContextLimits(),
        )
        termination_policy = TerminationPolicy(
            TerminationLimits.for_profile(config.budget_profile)
        )
        progress_limits = ProgressLimits.for_profile(config.budget_profile)
        instruction_snapshot = RunInstructionBuilder().build(
            config.workspace,
            skill_instructions=skill_instructions,
            run_mode=config.run_mode,
        )
        runner = AgentRunner(
            model_client=model_client,
            tool_registry=registry,
            execution_context=execution_context,
            context_manager=context_manager,
            termination_policy=termination_policy,
            clock=selected.clock,
            verification_gate=verification_gate,
            event_sink=logger,
            instructions=instruction_snapshot.text,
            stream_handler=stream_handler,
            confirmed_text_handler=confirmed_text_handler,
            cancellation_requested=cancellation_requested,
            initial_user_message=initial_user_message,
            run_mode=config.run_mode,
            budget_profile=config.budget_profile,
            progress_limits=progress_limits,
        )
    except KeyboardInterrupt:
        _close_after_failed_setup(logger)
        raise
    except Exception:
        _close_after_failed_setup(logger)
        raise ApplicationRunError("internal_application_failure") from None

    interrupted = False
    try:
        state = runner.run(config.task)
    except AgentInterrupted as exc:
        state = exc.state
        interrupted = True
    except KeyboardInterrupt:
        _close_after_failed_setup(logger)
        raise
    except Exception:
        _close_after_failed_setup(logger)
        raise ApplicationRunError("internal_application_failure") from None

    if logger.metadata.finished_elapsed_ms is None:
        logger.metadata.finished_elapsed_ms = max(
            0,
            int((selected.clock() - state.started_at_monotonic) * 1000),
        )

    try:
        logger.close()
    except RunLogError as exc:
        if logger.metadata.log_failure_code is None:
            logger.metadata.log_failure_code = exc.code
        if not interrupted:
            state.status = AgentStatus.FAILED
            state.termination_reason = TerminationReason.AUDIT_LOG_FAILURE
            state.failure_reason = TerminationReason.AUDIT_LOG_FAILURE.value
    except KeyboardInterrupt:
        raise
    except Exception:
        raise ApplicationRunError("internal_application_failure") from None

    try:
        report = FinalReport.from_state(
            state,
            logger.metadata,
            sensitive_values=(config.api_key,),
        )
    except Exception:
        raise ApplicationRunError("internal_application_failure") from None
    return AgentExecutionResult(state=state, report=report)


def run_application(
    config: RunConfig,
    *,
    stdout: TextIO,
    stderr: TextIO,
    factories: ApplicationFactories | None = None,
) -> int:
    if not isinstance(config, RunConfig):
        raise TypeError("config must be RunConfig")
    if not callable(getattr(stdout, "write", None)):
        raise TypeError("stdout must be writable")
    if not callable(getattr(stderr, "write", None)):
        raise TypeError("stderr must be writable")
    try:
        execution = execute_agent_run(config, factories=factories)
    except ApplicationRunError as exc:
        if exc.code.startswith("audit_log_unavailable:"):
            detail = exc.code.partition(":")[2]
            stderr.write(f"error: audit log unavailable ({detail})\n")
        else:
            stderr.write("error: internal application failure\n")
        return 1
    except KeyboardInterrupt:
        stderr.write("error: interrupted\n")
        return 130
    report = execution.report
    rendered = report.to_json()
    try:
        stdout.write(rendered)
    except Exception:
        try:
            stderr.write("error: final report output failed\n")
        except Exception:
            pass
        return 1
    return report.exit_code

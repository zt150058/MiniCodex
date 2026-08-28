from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import time
from typing import Protocol, TextIO

from coding_agent.agent import AgentInterrupted, AgentRunner
from coding_agent.config import RunConfig
from coding_agent.context import ContextManager
from coding_agent.logging import RunEventLogger, RunLogError
from coding_agent.model import ModelClient
from coding_agent.openai_client import OpenAIResponsesClient
from coding_agent.report import FinalReport, ReportInvariantError
from coding_agent.state import AgentStatus, TerminationReason
from coding_agent.termination import TerminationPolicy
from coding_agent.tools.base import ExecutionContext
from coding_agent.tools.filesystem import (
    ListDirectoryTool,
    ReadFileTool,
    ReplaceTextTool,
    WriteFileTool,
)
from coding_agent.tools.registry import ToolRegistry
from coding_agent.tools.shell import AuthorizedCommandExecutor, RunCommandTool
from coding_agent.verification import VerificationGate


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
    return OpenAIResponsesClient(model=config.model, api_key=config.api_key)


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
    selected = production_factories() if factories is None else factories
    if not isinstance(selected, ApplicationFactories):
        raise TypeError("factories must be ApplicationFactories")

    try:
        logger = selected.logger(config, selected.clock)
    except RunLogError as exc:
        stderr.write(f"error: audit log unavailable ({exc.code})\n")
        return 1
    except KeyboardInterrupt:
        stderr.write("error: interrupted\n")
        return 130
    except Exception:
        stderr.write("error: internal application failure\n")
        return 1

    try:
        execution_context = ExecutionContext(config.workspace)
        executor = selected.command_executor()
        registry = ToolRegistry(
            (
                ListDirectoryTool(),
                ReadFileTool(),
                ReplaceTextTool(),
                WriteFileTool(),
                RunCommandTool(authorized_executor=executor),
            )
        )
        model_client = selected.model_client(config)
        context_manager = ContextManager(model_client=model_client)
        termination_policy = TerminationPolicy()
        verification_gate = VerificationGate(
            required_command=config.verify_command,
            execution_context=execution_context,
            executor=executor,
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
        )
    except KeyboardInterrupt:
        try:
            logger.close()
        except Exception:
            pass
        stderr.write("error: interrupted\n")
        return 130
    except Exception:
        try:
            logger.close()
        except Exception:
            pass
        stderr.write("error: internal application failure\n")
        return 1

    interrupted = False
    try:
        state = runner.run(config.task)
    except AgentInterrupted as exc:
        state = exc.state
        interrupted = True
    except KeyboardInterrupt:
        try:
            logger.close()
        except Exception:
            pass
        stderr.write("error: interrupted\n")
        return 130
    except Exception:
        try:
            logger.close()
        except Exception:
            pass
        stderr.write("error: internal application failure\n")
        return 1

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
        stderr.write("error: interrupted\n")
        return 130
    except Exception:
        stderr.write("error: internal application failure\n")
        return 1

    try:
        report = FinalReport.from_state(
            state,
            logger.metadata,
            sensitive_values=(config.api_key,),
        )
        rendered = report.to_json()
    except (ReportInvariantError, Exception):
        stderr.write("error: internal application failure\n")
        return 1
    try:
        stdout.write(rendered)
    except Exception:
        try:
            stderr.write("error: final report output failed\n")
        except Exception:
            pass
        return 1
    return report.exit_code

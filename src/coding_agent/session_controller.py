from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import math
import os
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic
from typing import Protocol, TypeAlias

from coding_agent.session import (
    SessionControllerError,
    SessionError,
    SessionEvent,
    NewSessionEvent,
    PersistedSessionEventKind,
    SessionRecord,
    SessionRunRecord,
    SessionRunResult,
    SessionRunStatus,
    SessionStatus,
    SessionStoreError,
    make_safe_run_summary,
    utc_now,
)
from coding_agent.session_events import (
    SessionEventHub,
    SessionUpdateBatch,
    SessionUpdateKind,
)
from coding_agent.session_runtime import (
    SessionNarrativeRenderer,
    SessionRunExecutor,
    SessionRunOutcome,
    SessionRunRequest,
)
from coding_agent.session_store import (
    SQLiteSessionStore,
    SessionStore,
    WorkspaceSessionLease,
)
from coding_agent.skills import (
    SkillCatalog,
    SkillCatalogError,
    SkillCatalogView,
)
from coding_agent.logging import EventType, RunEvent
from coding_agent.run_mode import RunMode
from coding_agent.streaming import ModelStreamEvent, ModelStreamEventKind


class WorkerThread(Protocol):
    @property
    def daemon(self) -> bool: ...

    @property
    def name(self) -> str: ...

    def start(self) -> None: ...
    def join(self, timeout: float | None = None) -> None: ...
    def is_alive(self) -> bool: ...


ThreadFactory: TypeAlias = Callable[[Callable[[], None], str], WorkerThread]


class CancellationResult(StrEnum):
    REQUESTED = "requested"
    ALREADY_REQUESTED = "already_requested"
    ALREADY_FINISHED = "already_finished"


class _CancellationOwner(StrEnum):
    WORKER = "worker"


def default_thread_factory(
    target: Callable[[], None],
    name: str,
) -> WorkerThread:
    return Thread(target=target, name=name, daemon=False)


@dataclass(frozen=True, slots=True)
class RunHandle:
    session_id: str
    run_id: str
    run_mode: RunMode


@dataclass(frozen=True, slots=True)
class SessionView:
    session: SessionRecord
    runs: tuple[SessionRunRecord, ...]
    events: tuple[SessionEvent, ...] = field(repr=False)


@dataclass(slots=True)
class _ActiveRun:
    request: SessionRunRequest
    cancellation: Event
    done: Event
    thread: WorkerThread | None = None
    cancellation_done: Event = field(default_factory=Event)
    cancellation_owner: _CancellationOwner | None = None
    cancellation_error_code: str | None = None
    finalizing: bool = False


def _workspace_identity(workspace: Path) -> str:
    try:
        resolved = Path(workspace).resolve(strict=True)
    except OSError:
        raise SessionControllerError("invalid_session_state") from None
    return os.path.normcase(str(resolved))


def _timeout(value: float, *, allow_zero: bool = False) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        or (value == 0 and not allow_zero)
    ):
        raise SessionControllerError("invalid_session_state")
    return float(value)


class SessionController:
    def __init__(
        self,
        *,
        store: SessionStore,
        lease: WorkspaceSessionLease,
        executor: SessionRunExecutor,
        event_hub: SessionEventHub,
        narrative_renderer: SessionNarrativeRenderer = SessionNarrativeRenderer(),
        thread_factory: ThreadFactory = default_thread_factory,
        skill_catalog: SkillCatalog | None = None,
    ) -> None:
        if not isinstance(event_hub, SessionEventHub):
            raise TypeError("event_hub must be SessionEventHub")
        if not isinstance(narrative_renderer, SessionNarrativeRenderer):
            raise TypeError("narrative_renderer must be SessionNarrativeRenderer")
        if not callable(thread_factory):
            raise TypeError("thread_factory must be callable")
        try:
            identities = {
                _workspace_identity(store.workspace),
                _workspace_identity(lease.workspace),
                _workspace_identity(executor.workspace),
            }
        except (AttributeError, TypeError):
            raise SessionControllerError("invalid_session_state") from None
        if len(identities) != 1:
            raise SessionControllerError("invalid_session_state")
        if skill_catalog is None:
            skill_catalog = SkillCatalog.from_environment(store.workspace)
        elif type(skill_catalog) is not SkillCatalog:
            raise TypeError("skill_catalog must be SkillCatalog or None")
        expected_skill_root = (
            store.workspace / ".coding-agent" / "skills"
        ).resolve(strict=False)
        if skill_catalog.workspace_root != expected_skill_root:
            raise SessionControllerError("invalid_session_state")
        self._store = store
        self._lease = lease
        self._executor = executor
        self._event_hub = event_hub
        self._narrative_renderer = narrative_renderer
        self._thread_factory = thread_factory
        self._skill_catalog = skill_catalog
        self._lock = RLock()
        self._active: _ActiveRun | None = None
        self._admission_done: Event | None = None
        self._closed = False
        self._degraded = False
        self._event_run_id: str | None = None

    @classmethod
    def open(
        cls,
        workspace: Path,
        executor: SessionRunExecutor,
        *,
        sensitive_values: tuple[str, ...] = (),
        utc_clock: Callable[[], datetime] = utc_now,
        thread_factory: ThreadFactory = default_thread_factory,
        skill_catalog: SkillCatalog | None = None,
    ) -> SessionController:
        try:
            requested_identity = _workspace_identity(workspace)
            executor_identity = _workspace_identity(executor.workspace)
        except (AttributeError, TypeError):
            raise SessionControllerError("invalid_session_state") from None
        if requested_identity != executor_identity:
            raise SessionControllerError("invalid_session_state")
        lease = WorkspaceSessionLease.acquire(workspace)
        try:
            store = SQLiteSessionStore(
                workspace,
                utc_clock=utc_clock,
                sensitive_values=sensitive_values,
            )
            store.initialize()
            store.recover_incomplete_runs()
            return cls(
                store=store,
                lease=lease,
                executor=executor,
                event_hub=SessionEventHub(
                    utc_clock=utc_clock,
                    sensitive_values=sensitive_values,
                ),
                thread_factory=thread_factory,
                skill_catalog=skill_catalog,
            )
        except BaseException:
            lease.close()
            raise

    @property
    def workspace(self) -> Path:
        return self._store.workspace

    @staticmethod
    def _translate_store_error(exc: SessionStoreError) -> SessionControllerError:
        return SessionControllerError(exc.code)

    def _ensure_available(self) -> None:
        if self._closed:
            raise SessionControllerError("controller_closed")
        if self._degraded:
            raise SessionControllerError("controller_degraded")
        if self._active is not None or self._admission_done is not None:
            raise SessionControllerError("controller_busy")

    def _reserve_admission(self) -> Event:
        with self._lock:
            self._ensure_available()
            done = Event()
            self._admission_done = done
            return done

    def _release_admission(self, done: Event) -> None:
        with self._lock:
            if self._admission_done is done:
                self._admission_done = None
        done.set()

    def list_skills(self) -> SkillCatalogView:
        return self._skill_catalog.discover()

    def get_session_skills(self, session_id: str) -> tuple[str, ...]:
        try:
            return self._store.get_skill_selection(session_id)
        except SessionStoreError as exc:
            raise self._translate_store_error(exc) from None

    def set_session_skills(
        self,
        session_id: str,
        skill_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        admission = self._reserve_admission()
        try:
            try:
                session = self._store.get_session(session_id)
            except SessionStoreError as exc:
                raise self._translate_store_error(exc) from None
            if session.status is not SessionStatus.IDLE:
                raise SessionControllerError("invalid_session_state")
            try:
                self._skill_catalog.resolve(skill_ids)
            except SkillCatalogError as exc:
                raise SessionControllerError(exc.code) from None
            try:
                return self._store.replace_skill_selection(session_id, skill_ids)
            except SessionStoreError as exc:
                raise self._translate_store_error(exc) from None
        finally:
            self._release_admission(admission)

    def create_session(
        self,
        message: str,
        *,
        skill_ids: tuple[str, ...] = (),
        run_mode: RunMode = RunMode.MODIFY,
    ) -> RunHandle:
        if type(run_mode) is not RunMode:
            raise TypeError("run_mode must be RunMode")
        try:
            initial = self._narrative_renderer.render((), message)
        except (SessionError, TypeError, ValueError) as exc:
            code = getattr(exc, "code", "invalid_message")
            raise SessionControllerError(code) from None
        admission = self._reserve_admission()
        try:
            try:
                bundle = self._skill_catalog.resolve(skill_ids)
            except SkillCatalogError as exc:
                raise SessionControllerError(exc.code) from None
            selected_skills = (
                ()
                if bundle is None
                else tuple(item.descriptor for item in bundle.items)
            )
            try:
                submission = self._store.create_session(
                    message,
                    selected_skills=selected_skills,
                    run_mode=run_mode,
                )
            except SessionStoreError as exc:
                raise self._translate_store_error(exc) from None
            request = SessionRunRequest(
                session_id=submission.session.session_id,
                run_id=submission.run.run_id,
                current_message=message,
                initial_user_message=initial,
                skill_bundle=bundle,
                run_mode=run_mode,
            )
            handle = self._start_worker(request, admission)
            admission = None
            return handle
        finally:
            if admission is not None:
                self._release_admission(admission)

    def submit_message(
        self,
        session_id: str,
        message: str,
        *,
        run_mode: RunMode = RunMode.MODIFY,
    ) -> RunHandle:
        if type(run_mode) is not RunMode:
            raise TypeError("run_mode must be RunMode")
        admission = self._reserve_admission()
        try:
            try:
                narrative = self._store.load_narrative(session_id)
            except SessionStoreError as exc:
                raise self._translate_store_error(exc) from None
            try:
                initial = self._narrative_renderer.render(narrative, message)
            except (SessionError, TypeError, ValueError) as exc:
                code = getattr(exc, "code", "invalid_message")
                raise SessionControllerError(code) from None
            try:
                skill_ids = self._store.get_skill_selection(session_id)
            except SessionStoreError as exc:
                raise self._translate_store_error(exc) from None
            try:
                bundle = (
                    None if skill_ids == () else self._skill_catalog.resolve(skill_ids)
                )
            except SkillCatalogError as exc:
                raise SessionControllerError(exc.code) from None
            selected_skills = (
                ()
                if bundle is None
                else tuple(item.descriptor for item in bundle.items)
            )
            try:
                submission = self._store.submit_message(
                    session_id,
                    message,
                    selected_skills=selected_skills,
                    run_mode=run_mode,
                )
            except SessionStoreError as exc:
                raise self._translate_store_error(exc) from None
            request = SessionRunRequest(
                session_id=submission.session.session_id,
                run_id=submission.run.run_id,
                current_message=message,
                initial_user_message=initial,
                skill_bundle=bundle,
                run_mode=run_mode,
            )
            handle = self._start_worker(request, admission)
            admission = None
            return handle
        finally:
            if admission is not None:
                self._release_admission(admission)

    def _start_worker(
        self,
        request: SessionRunRequest,
        admission: Event,
    ) -> RunHandle:
        active = _ActiveRun(request=request, cancellation=Event(), done=Event())
        name = f"coding-agent-run-{request.run_id}"
        with self._lock:
            if self._admission_done is not admission:
                raise SessionControllerError("invalid_session_state")
            self._active = active
            self._admission_done = None
            start_cancelled = self._closed
            if start_cancelled:
                active.cancellation.set()
                active.cancellation_owner = _CancellationOwner.WORKER
        admission.set()
        try:
            self._event_hub.begin_run(request.session_id, request.run_id)
            self._event_run_id = request.run_id
            self._event_hub.publish(
                SessionUpdateKind.RUN_QUEUED,
                {"status": SessionRunStatus.QUEUED.value},
            )
            thread = self._thread_factory(lambda: self._worker(active), name)
            if thread.daemon:
                raise SessionControllerError("invalid_session_state")
            active.thread = thread
            thread.start()
        except BaseException as exc:
            with self._lock:
                active.finalizing = True
            failure = self._controller_failure(request.run_id)
            try:
                terminal = self._store.finish_run(failure)
                self._event_hub.publish(
                    SessionUpdateKind.RUN_FINISHED,
                    {
                        "status": terminal.status.value,
                        "agent_status": terminal.agent_status,
                    },
                )
            except Exception:
                self._degrade(active)
            finally:
                error_code = (
                    "thread_start_failed"
                    if isinstance(exc, Exception)
                    else "controller_error"
                )
                self._complete_cancellation_phase(active, error_code)
                with self._lock:
                    if self._active is active:
                        self._active = None
                active.done.set()
            if isinstance(exc, Exception):
                raise SessionControllerError("thread_start_failed") from None
            raise
        return RunHandle(request.session_id, request.run_id, request.run_mode)

    def _controller_failure(self, run_id: str) -> SessionRunResult:
        return SessionRunResult(
            run_id=run_id,
            status=SessionRunStatus.FAILED,
            agent_status="failed",
            termination_reason="controller_error",
            audit_run_id=None,
            safe_summary=make_safe_run_summary(
                None,
                status="failed",
                termination_reason="controller_error",
            ),
            final_report=None,
        )

    def _degrade(self, active: _ActiveRun) -> None:
        with self._lock:
            self._degraded = True
            if not active.cancellation.is_set():
                active.cancellation.set()
                active.cancellation_owner = _CancellationOwner.WORKER
        try:
            self._event_hub.publish(
                SessionUpdateKind.CONTROLLER_ERROR,
                {"code": "controller_error"},
            )
        except Exception:
            pass

    def _persist_worker_cancellation(self, active: _ActiveRun) -> None:
        with self._lock:
            owns_phase = (
                active.cancellation_owner is _CancellationOwner.WORKER
                and not active.cancellation_done.is_set()
            )
        if not owns_phase:
            return
        try:
            self._store.request_cancellation(active.request.run_id)
            self._publish(
                active,
                SessionUpdateKind.RUN_CANCELLING,
                {"status": SessionRunStatus.CANCELLING.value},
            )
        except SessionStoreError as exc:
            with self._lock:
                active.cancellation_error_code = exc.code
            self._degrade(active)
        except BaseException:
            with self._lock:
                active.cancellation_error_code = "controller_error"
            try:
                current = self._store.get_run(active.request.run_id)
            except Exception:
                current = None
            if current is not None and current.status is SessionRunStatus.CANCELLING:
                self._publish(
                    active,
                    SessionUpdateKind.RUN_CANCELLING,
                    {"status": SessionRunStatus.CANCELLING.value},
                )
            raise
        finally:
            active.cancellation_done.set()

    def _await_cancellation_phase(self, active: _ActiveRun) -> None:
        if not active.cancellation.is_set():
            return
        with self._lock:
            owner = active.cancellation_owner
        if owner is _CancellationOwner.WORKER:
            self._persist_worker_cancellation(active)
        active.cancellation_done.wait()

    def _complete_cancellation_phase(
        self,
        active: _ActiveRun,
        error_code: str,
    ) -> None:
        with self._lock:
            if active.cancellation_done.is_set():
                return
            if active.cancellation.is_set() and active.cancellation_error_code is None:
                active.cancellation_error_code = error_code
            active.cancellation_done.set()

    def _admit_finalization(self, active: _ActiveRun) -> None:
        while True:
            with self._lock:
                if (
                    not active.cancellation.is_set()
                    or active.cancellation_done.is_set()
                ):
                    active.finalizing = True
                    return
                owner = active.cancellation_owner
            if owner is _CancellationOwner.WORKER:
                self._persist_worker_cancellation(active)
            else:
                active.cancellation_done.wait()

    def _publish(
        self,
        active: _ActiveRun,
        kind: SessionUpdateKind,
        data: dict[str, object],
    ) -> None:
        try:
            self._event_hub.publish(kind, data)  # type: ignore[arg-type]
        except Exception:
            self._degrade(active)

    def _append_event(
        self,
        active: _ActiveRun,
        kind: PersistedSessionEventKind,
        data: dict[str, object],
    ) -> bool:
        try:
            self._store.append_event(
                NewSessionEvent(
                    session_id=active.request.session_id,
                    run_id=active.request.run_id,
                    kind=kind,
                    data=data,  # type: ignore[arg-type]
                )
            )
            return True
        except SessionStoreError:
            self._degrade(active)
            return False

    def _run_event_handler(self, active: _ActiveRun, event: RunEvent) -> None:
        if not isinstance(event, RunEvent):
            raise TypeError("run event must be RunEvent")
        data = event.data
        if event.event_type is EventType.TOOL_CALL_STARTED:
            self._publish(
                active,
                SessionUpdateKind.TOOL_STARTED,
                {"tool_name": data["tool_name"], "ordinal": data["ordinal"]},
            )
            return
        if event.event_type is EventType.TOOL_CALL_COMPLETED:
            safe = {
                "tool_name": data["tool_name"],
                "status": data["status"],
                "duration_ms": data["duration_ms"],
                "truncated": data["truncated"],
                "exit_code": data["exit_code"],
                "safe_error_code": data["safe_error_code"],
                "changed_paths": data["changed_paths"],
            }
            if self._append_event(
                active,
                PersistedSessionEventKind.TOOL_ACTIVITY,
                safe,
            ):
                self._publish(active, SessionUpdateKind.TOOL_FINISHED, safe)
            return
        if event.event_type is EventType.VERIFICATION_STARTED:
            self._publish(
                active,
                SessionUpdateKind.VERIFICATION_STARTED,
                {
                    "source": data["source"],
                    "attempt_index": data["attempt_index"],
                    "mutation_index": data["mutation_index"],
                },
            )
            return
        if event.event_type is EventType.VERIFICATION_COMPLETED:
            persisted = {
                "status": data["status"],
                "source": data["source"],
                "exit_code": data["exit_code"],
                "timed_out": data["timed_out"],
                "truncated": data["truncated"],
                "duration_ms": data["duration_ms"],
                "validation_index": data["validation_index"],
                "error_code": data["error_code"],
            }
            if self._append_event(
                active,
                PersistedSessionEventKind.VERIFICATION_ACTIVITY,
                persisted,
            ):
                self._publish(
                    active,
                    SessionUpdateKind.VERIFICATION_FINISHED,
                    {**persisted, "mutation_index": data["mutation_index"]},
                )

    def _worker(self, active: _ActiveRun) -> None:
        try:
            self._worker_body(active)
        finally:
            self._complete_cancellation_phase(active, "controller_error")
            with self._lock:
                if self._active is active:
                    self._active = None
            active.done.set()

    def _worker_body(self, active: _ActiveRun) -> None:
        result: SessionRunResult | None = None
        pending_text: list[str] = []

        def stream_handler(event: ModelStreamEvent) -> None:
            if not isinstance(event, ModelStreamEvent):
                raise TypeError("stream event must be ModelStreamEvent")
            if event.kind is ModelStreamEventKind.TEXT_DELTA:
                assert event.delta is not None
                pending_text.append(event.delta)
                self._publish(
                    active,
                    SessionUpdateKind.ASSISTANT_TEXT_DELTA,
                    {"content": event.delta},
                )
            elif event.kind is ModelStreamEventKind.RESPONSE_DISCARDED:
                pending_text.clear()
                self._publish(
                    active,
                    SessionUpdateKind.ASSISTANT_TEXT_DISCARDED,
                    {"reason": "provider_discarded"},
                )

        def confirmed_text_handler(text: str) -> None:
            if pending_text and "".join(pending_text) != text:
                pending_text.clear()
                self._publish(
                    active,
                    SessionUpdateKind.ASSISTANT_TEXT_DISCARDED,
                    {"reason": "text_mismatch"},
                )
            if self._append_event(
                active,
                PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED,
                {"content": text},
            ):
                self._publish(
                    active,
                    SessionUpdateKind.ASSISTANT_TEXT_COMMITTED,
                    {"content": text},
                )
            pending_text.clear()

        def cancellation_requested() -> bool:
            if not active.cancellation.is_set():
                return False
            self._await_cancellation_phase(active)
            return True

        try:
            self._store.start_run(active.request.run_id)
            self._event_hub.publish(
                SessionUpdateKind.RUN_STARTED,
                {"status": SessionRunStatus.RUNNING.value},
            )
            self._await_cancellation_phase(active)
            outcome: SessionRunOutcome = self._executor.execute(
                active.request,
                stream_handler=stream_handler,
                confirmed_text_handler=confirmed_text_handler,
                cancellation_requested=cancellation_requested,
                run_event_handler=lambda event: self._run_event_handler(active, event),
            )
            result = SessionRunResult(
                run_id=active.request.run_id,
                status=outcome.status,
                agent_status=outcome.agent_status,
                termination_reason=outcome.termination_reason,
                audit_run_id=outcome.audit_run_id,
                safe_summary=outcome.safe_summary,
                final_report=outcome.final_report,
            )
        except Exception:
            result = self._controller_failure(active.request.run_id)

        if pending_text:
            pending_text.clear()
            self._publish(
                active,
                SessionUpdateKind.ASSISTANT_TEXT_DISCARDED,
                {"reason": "run_finished"},
            )

        self._admit_finalization(active)

        try:
            assert result is not None
            terminal = self._store.finish_run(result)
            self._event_hub.publish(
                SessionUpdateKind.RUN_FINISHED,
                {
                    "status": terminal.status.value,
                    "agent_status": terminal.agent_status,
                },
            )
        except Exception:
            self._degraded = True
            try:
                self._event_hub.publish(
                    SessionUpdateKind.CONTROLLER_ERROR,
                    {"code": "controller_error"},
                )
            except Exception:
                pass
        finally:
            with self._lock:
                if self._active is active:
                    self._active = None
            active.done.set()

    def list_sessions(self, *, limit: int = 50) -> tuple[SessionRecord, ...]:
        try:
            return self._store.list_sessions(limit=limit)
        except SessionStoreError as exc:
            raise self._translate_store_error(exc) from None

    def read_updates(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
    ) -> SessionUpdateBatch:
        if run_id != self._event_run_id:
            raise SessionControllerError("run_not_found")
        try:
            return self._event_hub.read(
                after_sequence=after_sequence,
                expected_run_id=run_id,
            )
        except LookupError:
            raise SessionControllerError("run_not_found") from None
        except (TypeError, ValueError):
            raise SessionControllerError("invalid_session_state") from None

    def wait_for_updates(
        self,
        run_id: str,
        *,
        after_sequence: int,
        timeout_seconds: float,
    ) -> SessionUpdateBatch:
        if run_id != self._event_run_id:
            raise SessionControllerError("run_not_found")
        try:
            return self._event_hub.wait(
                after_sequence=after_sequence,
                timeout_seconds=timeout_seconds,
                expected_run_id=run_id,
            )
        except LookupError:
            raise SessionControllerError("run_not_found") from None
        except (TypeError, ValueError):
            raise SessionControllerError("invalid_session_state") from None

    def get_session(self, session_id: str) -> SessionView:
        try:
            return SessionView(
                session=self._store.get_session(session_id),
                runs=self._store.list_runs(session_id),
                events=self._store.load_events(session_id),
            )
        except SessionStoreError as exc:
            raise self._translate_store_error(exc) from None

    def wait_for_run(
        self,
        run_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> SessionRunRecord:
        timeout = None if timeout_seconds is None else _timeout(timeout_seconds)
        with self._lock:
            active = self._active
            done = active.done if active is not None and active.request.run_id == run_id else None
        if done is not None and not done.wait(timeout):
            raise SessionControllerError("controller_timeout")
        try:
            return self._store.get_run(run_id)
        except SessionStoreError as exc:
            raise self._translate_store_error(exc) from None

    def cancel(self, run_id: str) -> CancellationResult:
        with self._lock:
            current = self._active
            active = (
                current
                if current is not None and current.request.run_id == run_id
                else None
            )
            if active is not None:
                if active.finalizing:
                    return CancellationResult.ALREADY_FINISHED
                if active.cancellation.is_set():
                    return CancellationResult.ALREADY_REQUESTED
                active.cancellation.set()
                active.cancellation_owner = _CancellationOwner.WORKER
        if active is None:
            try:
                run = self._store.get_run(run_id)
            except SessionStoreError as exc:
                raise self._translate_store_error(exc) from None
            if run.status in {
                SessionRunStatus.SUCCEEDED,
                SessionRunStatus.FAILED,
                SessionRunStatus.INTERRUPTED,
            }:
                return CancellationResult.ALREADY_FINISHED
            raise SessionControllerError("invalid_session_state")
        active.cancellation_done.wait()
        with self._lock:
            error_code = active.cancellation_error_code
        if error_code is not None:
            raise SessionControllerError(error_code)
        return CancellationResult.REQUESTED

    def shutdown(self, *, timeout_seconds: float) -> bool:
        timeout = _timeout(timeout_seconds)
        deadline = monotonic() + timeout
        while True:
            with self._lock:
                self._closed = True
                admission = self._admission_done
                active = self._active
                if (
                    active is not None
                    and not active.finalizing
                    and not active.cancellation.is_set()
                ):
                    active.cancellation.set()
                    active.cancellation_owner = _CancellationOwner.WORKER
                thread = active.thread if active is not None else None
            remaining = max(0.0, deadline - monotonic())
            if admission is not None:
                if not admission.wait(remaining):
                    return False
                continue
            if active is not None:
                if thread is None:
                    if not active.done.wait(remaining):
                        return False
                else:
                    thread.join(remaining)
                    if thread.is_alive():
                        return False
                continue
            self._lease.close()
            return True

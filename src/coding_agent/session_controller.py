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
from coding_agent.session_deletion import (
    SessionDeletionError,
    SessionDeletionResult,
    SessionDeletionService,
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
    SkillDescriptor,
)
from coding_agent.skill_packages import SkillPackageError, SkillPackageInstaller
from coding_agent.logging import EventType, RunEvent
from coding_agent.budget import BudgetProfile, limits_for_profile
from coding_agent.model_catalog import (
    ModelCatalog,
    ModelCatalogError,
    ModelCatalogView,
)
from coding_agent.run_mode import RunMode
from coding_agent.safety import SafetyCode
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
SessionDeletionServiceFactory: TypeAlias = Callable[
    [Path, SessionStore], SessionDeletionService
]


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


def default_session_deletion_service_factory(
    workspace: Path,
    store: SessionStore,
) -> SessionDeletionService:
    return SessionDeletionService(workspace, store)


@dataclass(frozen=True, slots=True)
class RunHandle:
    session_id: str
    run_id: str
    run_mode: RunMode
    budget_profile: BudgetProfile
    model_id: str


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
    phase: str = "discover"
    main_model_calls: int = 0
    summary_model_calls: int = 0
    provider_attempts: int = 0
    tool_calls: int = 0


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


def _session_safe_tool_error_code(value: object) -> str | None:
    if value is None:
        return None
    if value in {"tool_error", "tool_rejected"}:
        return str(value)
    if not isinstance(value, str):
        raise ValueError("invalid_safe_error_code")
    if value.startswith("security_rejected:"):
        suffix = value.removeprefix("security_rejected:")
        try:
            return SafetyCode(suffix).value
        except ValueError:
            raise ValueError("invalid_safe_error_code") from None
    agent_codes = {
        "agent_rejected:decision_required": "decision_required",
        "agent_rejected:verification_required": "verification_required",
    }
    try:
        return agent_codes[value]
    except KeyError:
        raise ValueError("invalid_safe_error_code") from None


class SessionController:
    def __init__(
        self,
        *,
        store: SessionStore,
        lease: WorkspaceSessionLease,
        executor: SessionRunExecutor,
        model_catalog: ModelCatalog,
        event_hub: SessionEventHub,
        narrative_renderer: SessionNarrativeRenderer = SessionNarrativeRenderer(),
        thread_factory: ThreadFactory = default_thread_factory,
        skill_catalog: SkillCatalog | None = None,
        skill_installer: SkillPackageInstaller | None = None,
        session_deletion: SessionDeletionService | None = None,
    ) -> None:
        if not isinstance(event_hub, SessionEventHub):
            raise TypeError("event_hub must be SessionEventHub")
        if not isinstance(narrative_renderer, SessionNarrativeRenderer):
            raise TypeError("narrative_renderer must be SessionNarrativeRenderer")
        if not callable(thread_factory):
            raise TypeError("thread_factory must be callable")
        try:
            if not isinstance(model_catalog, ModelCatalog):
                raise TypeError("model_catalog must implement ModelCatalog")
            if model_catalog.default_model_id != executor.default_model_id:
                raise ValueError("model catalog and executor defaults differ")
            identities = {
                _workspace_identity(store.workspace),
                _workspace_identity(lease.workspace),
                _workspace_identity(executor.workspace),
            }
        except (AttributeError, TypeError, ValueError, ModelCatalogError):
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
        if skill_installer is None:
            skill_installer = SkillPackageInstaller(expected_skill_root)
        elif type(skill_installer) is not SkillPackageInstaller:
            raise TypeError("skill_installer must be SkillPackageInstaller or None")
        if skill_installer.workspace_skill_root != expected_skill_root:
            raise SessionControllerError("invalid_session_state")
        if session_deletion is None:
            session_deletion = default_session_deletion_service_factory(
                store.workspace,
                store,
            )
        try:
            deletion_matches = (
                session_deletion.store is store
                and _workspace_identity(session_deletion.workspace)
                == _workspace_identity(store.workspace)
            )
        except (AttributeError, TypeError):
            raise SessionControllerError("invalid_session_state") from None
        if not deletion_matches:
            raise SessionControllerError("invalid_session_state")
        self._store = store
        self._lease = lease
        self._executor = executor
        self._model_catalog = model_catalog
        self._event_hub = event_hub
        self._narrative_renderer = narrative_renderer
        self._thread_factory = thread_factory
        self._skill_catalog = skill_catalog
        self._skill_installer = skill_installer
        self._session_deletion = session_deletion
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
        model_catalog: ModelCatalog,
        sensitive_values: tuple[str, ...] = (),
        utc_clock: Callable[[], datetime] = utc_now,
        thread_factory: ThreadFactory = default_thread_factory,
        skill_catalog: SkillCatalog | None = None,
        skill_installer: SkillPackageInstaller | None = None,
        session_deletion_factory: SessionDeletionServiceFactory = (
            default_session_deletion_service_factory
        ),
    ) -> SessionController:
        try:
            if not isinstance(model_catalog, ModelCatalog):
                raise TypeError("model_catalog must implement ModelCatalog")
            if model_catalog.default_model_id != executor.default_model_id:
                raise ValueError("model catalog and executor defaults differ")
            requested_identity = _workspace_identity(workspace)
            executor_identity = _workspace_identity(executor.workspace)
        except (AttributeError, TypeError, ValueError, ModelCatalogError):
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
            try:
                session_deletion = session_deletion_factory(store.workspace, store)
            except Exception:
                raise SessionControllerError("invalid_session_state") from None
            try:
                deletion_matches = (
                    session_deletion.store is store
                    and _workspace_identity(session_deletion.workspace)
                    == _workspace_identity(store.workspace)
                )
            except (AttributeError, TypeError):
                raise SessionControllerError("invalid_session_state") from None
            if not deletion_matches:
                raise SessionControllerError("invalid_session_state")
            controller = cls(
                store=store,
                lease=lease,
                executor=executor,
                model_catalog=model_catalog,
                event_hub=SessionEventHub(
                    utc_clock=utc_clock,
                    sensitive_values=sensitive_values,
                ),
                thread_factory=thread_factory,
                skill_catalog=skill_catalog,
                skill_installer=skill_installer,
                session_deletion=session_deletion,
            )
            try:
                session_deletion.recover_pending()
            except SessionDeletionError as exc:
                raise SessionControllerError(exc.code) from None
            except Exception:
                raise SessionControllerError(
                    "session_deletion_recovery_failed"
                ) from None
            return controller
        except BaseException:
            lease.close()
            raise

    @property
    def workspace(self) -> Path:
        return self._store.workspace

    def list_models(self, *, refresh: bool = False) -> ModelCatalogView:
        return self._model_catalog.list_models(refresh=refresh)

    def _resolve_model(self, requested_model_id: str | None) -> str:
        try:
            return self._model_catalog.resolve(requested_model_id)
        except ModelCatalogError as exc:
            if exc.code == "model_not_available":
                raise SessionControllerError("model_not_available") from None
            raise

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

    def import_skill_archive(self, archive: bytes) -> SkillDescriptor:
        admission = self._reserve_admission()
        try:
            candidate = self._skill_installer.inspect(archive)
            before = self._skill_catalog.discover()
            if not before.usable:
                raise SessionControllerError("skill_catalog_unavailable")
            if any(item.skill_id == candidate.skill_id for item in before.skills):
                raise SessionControllerError("skill_already_exists")
            descriptor = self._skill_installer.install(archive)
            after = self._skill_catalog.discover()
            matches = tuple(
                item for item in after.skills if item.skill_id == descriptor.skill_id
            )
            if not after.usable or matches != (descriptor,):
                raise SessionControllerError("skill_install_failed")
            return descriptor
        except SkillPackageError as exc:
            raise SessionControllerError(exc.code) from None
        finally:
            self._release_admission(admission)

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
        model_id: str | None = None,
        run_mode: RunMode = RunMode.MODIFY,
        budget_profile: BudgetProfile = BudgetProfile.STANDARD,
    ) -> RunHandle:
        if type(run_mode) is not RunMode:
            raise TypeError("run_mode must be RunMode")
        if type(budget_profile) is not BudgetProfile:
            raise TypeError("budget_profile must be BudgetProfile")
        resolved_model_id = self._resolve_model(model_id)
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
                    model_id=resolved_model_id,
                    selected_skills=selected_skills,
                    run_mode=run_mode,
                    budget_profile=budget_profile,
                )
            except SessionStoreError as exc:
                raise self._translate_store_error(exc) from None
            request = SessionRunRequest(
                session_id=submission.session.session_id,
                run_id=submission.run.run_id,
                model_id=resolved_model_id,
                current_message=message,
                initial_user_message=initial,
                skill_bundle=bundle,
                run_mode=run_mode,
                budget_profile=budget_profile,
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
        model_id: str | None = None,
        run_mode: RunMode = RunMode.MODIFY,
        budget_profile: BudgetProfile = BudgetProfile.STANDARD,
    ) -> RunHandle:
        if type(run_mode) is not RunMode:
            raise TypeError("run_mode must be RunMode")
        if type(budget_profile) is not BudgetProfile:
            raise TypeError("budget_profile must be BudgetProfile")
        resolved_model_id = self._resolve_model(model_id)
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
                    model_id=resolved_model_id,
                    selected_skills=selected_skills,
                    run_mode=run_mode,
                    budget_profile=budget_profile,
                )
            except SessionStoreError as exc:
                raise self._translate_store_error(exc) from None
            request = SessionRunRequest(
                session_id=submission.session.session_id,
                run_id=submission.run.run_id,
                model_id=resolved_model_id,
                current_message=message,
                initial_user_message=initial,
                skill_bundle=bundle,
                run_mode=run_mode,
                budget_profile=budget_profile,
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
        return RunHandle(
            session_id=request.session_id,
            run_id=request.run_id,
            run_mode=request.run_mode,
            budget_profile=request.budget_profile,
            model_id=request.model_id,
        )

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

    def _publish_progress(self, active: _ActiveRun) -> None:
        profile = active.request.budget_profile
        limits = limits_for_profile(profile)
        self._publish(
            active,
            SessionUpdateKind.RUN_PROGRESS,
            {
                "budget_profile": profile.value,
                "phase": active.phase,
                "main_model_calls": active.main_model_calls,
                "main_model_limit": limits.max_main_logical_calls,
                "summary_model_calls": active.summary_model_calls,
                "summary_model_limit": limits.max_summary_logical_calls,
                "provider_attempts": active.provider_attempts,
                "provider_attempt_limit": limits.max_provider_attempts,
                "tool_calls": active.tool_calls,
                "tool_limit": limits.max_tool_calls,
            },
        )

    def _run_event_handler(self, active: _ActiveRun, event: RunEvent) -> None:
        if not isinstance(event, RunEvent):
            raise TypeError("run event must be RunEvent")
        data = event.data
        if event.event_type is EventType.RUN_STARTED:
            if data["budget_profile"] != active.request.budget_profile.value:
                self._degrade(active)
                return
            self._publish_progress(active)
            return
        if event.event_type is EventType.MODEL_CALL_STARTED:
            if data["purpose"] == "main":
                active.main_model_calls += 1
            else:
                active.summary_model_calls += 1
            self._publish_progress(active)
            return
        if event.event_type is EventType.PROVIDER_ATTEMPT_STARTED:
            active.provider_attempts = max(
                active.provider_attempts,
                int(data["provider_attempt_index"]),
            )
            self._publish_progress(active)
            return
        if event.event_type is EventType.PHASE_CHANGED:
            active.phase = str(data["to_phase"])
            self._publish(
                active,
                SessionUpdateKind.PHASE_CHANGED,
                {
                    "from_phase": data["from_phase"],
                    "to_phase": data["to_phase"],
                    "epoch": data["epoch"],
                },
            )
            self._publish_progress(active)
            return
        if event.event_type is EventType.DECISION_CHECKPOINT:
            self._publish(
                active,
                SessionUpdateKind.DECISION_CHECKPOINT,
                {
                    "reason": data["reason"],
                    "phase": data["phase"],
                    "main_calls_remaining": data["main_calls_remaining"],
                },
            )
            return
        if event.event_type is EventType.CONTEXT_COMPRESSION_COMPLETED:
            self._publish(
                active,
                SessionUpdateKind.CONTEXT_COMPRESSED,
                {
                    "summary_source": data["summary_source"],
                    "before_chars": data["before_chars"],
                    "after_chars": data["after_chars"],
                },
            )
            return
        if event.event_type is EventType.NO_PROGRESS_DETECTED:
            self._publish(
                active,
                SessionUpdateKind.NO_PROGRESS_DETECTED,
                {
                    "phase": data["phase"],
                    "post_checkpoint_main_turns": data[
                        "post_checkpoint_main_turns"
                    ],
                },
            )
            return
        if event.event_type is EventType.RUN_COMPLETED:
            if data["budget_profile"] != active.request.budget_profile.value:
                self._degrade(active)
                return
            active.phase = str(data["phase"])
            active.main_model_calls = int(data["main_model_calls"])
            active.summary_model_calls = int(data["summary_model_calls"])
            active.provider_attempts = int(data["provider_attempts"])
            active.tool_calls = int(data["tool_calls"])
            self._publish_progress(active)
            return
        if event.event_type is EventType.TOOL_CALL_STARTED:
            self._publish(
                active,
                SessionUpdateKind.TOOL_STARTED,
                {"tool_name": data["tool_name"], "ordinal": data["ordinal"]},
            )
            return
        if event.event_type is EventType.TOOL_CALL_COMPLETED:
            active.tool_calls = max(active.tool_calls, int(data["ordinal"]))
            safe = {
                "tool_name": data["tool_name"],
                "status": data["status"],
                "duration_ms": data["duration_ms"],
                "truncated": data["truncated"],
                "exit_code": data["exit_code"],
                "safe_error_code": _session_safe_tool_error_code(
                    data["safe_error_code"]
                ),
                "changed_paths": data["changed_paths"],
            }
            if self._append_event(
                active,
                PersistedSessionEventKind.TOOL_ACTIVITY,
                safe,
            ):
                self._publish(active, SessionUpdateKind.TOOL_FINISHED, safe)
                self._publish_progress(active)
            return
        if event.event_type is EventType.VERIFICATION_STARTED:
            active.tool_calls += 1
            self._publish(
                active,
                SessionUpdateKind.VERIFICATION_STARTED,
                {
                    "source": data["source"],
                    "attempt_index": data["attempt_index"],
                    "mutation_index": data["mutation_index"],
                },
            )
            self._publish_progress(active)
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

        def run_event_handler(event: RunEvent) -> None:
            if not isinstance(event, RunEvent):
                raise TypeError("run event must be RunEvent")
            if (
                event.event_type is EventType.TOOL_CALL_STARTED
                and pending_text
            ):
                pending_text.clear()
                self._publish(
                    active,
                    SessionUpdateKind.ASSISTANT_TEXT_DISCARDED,
                    {"reason": "tool_response_narration"},
                )
            self._run_event_handler(active, event)

        try:
            started = self._store.start_run(active.request.run_id)
            if (
                started.run_mode is not active.request.run_mode
                or started.budget_profile is not active.request.budget_profile
                or started.model_id != active.request.model_id
            ):
                raise SessionControllerError("invalid_session_state")
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
                run_event_handler=run_event_handler,
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

    def delete_session(self, session_id: str) -> SessionDeletionResult:
        admission = self._reserve_admission()
        try:
            try:
                session = self._store.get_session(session_id)
            except SessionStoreError as exc:
                raise self._translate_store_error(exc) from None
            if session.status is not SessionStatus.IDLE:
                raise SessionControllerError("invalid_session_state")
            try:
                result = self._session_deletion.delete(session_id)
            except SessionDeletionError as exc:
                raise SessionControllerError(exc.code) from None
            self._event_hub.forget_runs(result.run_ids)
            if self._event_run_id in result.run_ids:
                self._event_run_id = None
            return result
        finally:
            self._release_admission(admission)

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

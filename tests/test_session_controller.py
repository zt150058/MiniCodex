from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import io
import math
import threading
from threading import Condition, Event, Thread
import zipfile

import pytest

import coding_agent.session_controller as session_controller_module
from coding_agent.budget import BudgetProfile
from coding_agent.session import (
    NewSessionEvent,
    PersistedSessionEventKind,
    SessionControllerError,
    SessionRunRecord,
    SessionRunResult,
    SessionRunStatus,
    SessionStoreError,
    SessionStatus,
    make_safe_run_summary,
)
from coding_agent.session_controller import CancellationResult, SessionController
from coding_agent.logging import EventType, RunEvent
from coding_agent.model_catalog import (
    ModelCatalogError,
    ModelCatalogStatus,
    ModelCatalogView,
)
from coding_agent.run_mode import RunMode
from coding_agent.session_events import SessionEventHub, SessionUpdateKind
from coding_agent.session_deletion import (
    SessionDeletionError,
    SessionDeletionService,
)
from coding_agent.session_runtime import SessionRunOutcome, SessionRunRequest
from coding_agent.session_store import SQLiteSessionStore, WorkspaceSessionLease
from coding_agent.skill_packages import SkillPackageInstaller
from coding_agent.skills import (
    SkillCatalog,
    SkillCatalogView,
    SkillDescriptor,
    SkillSource,
)
from coding_agent.streaming import ModelStreamEvent, ModelStreamEventKind


MODEL_ID = "test-model"
SELECTED_MODEL_ID = "selected-model"


class RecordingModelCatalog:
    def __init__(
        self,
        default_model_id: str = MODEL_ID,
        model_ids: tuple[str, ...] = (MODEL_ID, SELECTED_MODEL_ID),
    ) -> None:
        self.default_model_id = default_model_id
        self.model_ids = model_ids
        self.calls: list[tuple[str, object]] = []

    def list_models(self, *, refresh: bool = False) -> ModelCatalogView:
        self.calls.append(("list_models", refresh))
        return ModelCatalogView(
            enabled=True,
            status=ModelCatalogStatus.READY,
            default_model_id=self.default_model_id,
            model_ids=self.model_ids,
            error_code=None,
        )

    def resolve(self, requested_model_id: str | None) -> str:
        self.calls.append(("resolve", requested_model_id))
        selected = self.default_model_id if requested_model_id is None else requested_model_id
        if selected not in self.model_ids:
            raise ModelCatalogError("model_not_available")
        return selected


class BlockingExecutor:
    default_model_id = MODEL_ID

    def __init__(
        self,
        workspace: Path,
        outcomes: tuple[SessionRunOutcome, ...],
    ) -> None:
        self.workspace = workspace.resolve(strict=True)
        self.outcomes = list(outcomes)
        self.requests: list[object] = []
        self.started = Event()
        self.release = Event()

    def execute(
        self,
        request: object,
        *,
        stream_handler: object,
        confirmed_text_handler: object,
        cancellation_requested: object,
        run_event_handler: object,
    ) -> SessionRunOutcome:
        del stream_handler, confirmed_text_handler, cancellation_requested
        del run_event_handler
        self.requests.append(request)
        self.started.set()
        assert self.release.wait(timeout=2.0)
        return self.outcomes.pop(0)


def failed_outcome(reason: str = "empty_model_response") -> SessionRunOutcome:
    return SessionRunOutcome(
        status=SessionRunStatus.FAILED,
        agent_status="failed",
        termination_reason=reason,
        audit_run_id="9" * 32,
        safe_summary=make_safe_run_summary(
            None,
            status="failed",
            termination_reason=reason,
        ),
        final_report=None,
    )


def changes_unverified_outcome() -> SessionRunOutcome:
    audit_run_id = "7" * 32
    report = {
        "schema_version": 3,
        "run_id": audit_run_id,
        "run_mode": "modify",
        "budget_profile": "standard",
        "phase": "finish",
        "status": "failed",
        "exit_code": 1,
        "termination_reason": "changes_unverified",
        "changed_paths": ["task_manager.py"],
        "mutation_index": 1,
        "validation_index": None,
        "verification": {
            "status": "stale",
            "source": None,
            "exit_code": None,
            "timed_out": False,
            "truncated": False,
            "duration_ms": None,
            "validation_index": None,
            "error_code": None,
        },
        "main_model_calls": 3,
        "summary_model_calls": 0,
        "logical_model_calls": 3,
        "summary_provider_attempts": 0,
        "provider_attempts": 3,
        "tool_calls": 2,
        "verification_attempts": 0,
        "context_compressions": 0,
        "token_usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "responses_with_usage": 3,
            "responses_without_usage": 0,
        },
        "elapsed_ms": 250,
        "log_failure_code": None,
        "log_path": f".coding-agent/logs/{audit_run_id}.jsonl",
    }
    return SessionRunOutcome(
        status=SessionRunStatus.FAILED,
        agent_status="failed",
        termination_reason="changes_unverified",
        audit_run_id=audit_run_id,
        safe_summary=make_safe_run_summary(
            report,
            status="failed",
            termination_reason="changes_unverified",
        ),
        final_report=report,
    )


def interrupted_outcome() -> SessionRunOutcome:
    return SessionRunOutcome(
        status=SessionRunStatus.INTERRUPTED,
        agent_status="interrupted",
        termination_reason="user_interrupted",
        audit_run_id="9" * 32,
        safe_summary=make_safe_run_summary(
            None,
            status="interrupted",
            termination_reason="user_interrupted",
        ),
        final_report=None,
    )


def make_controller(
    tmp_path: Path,
    executor: object,
    *,
    store: SQLiteSessionStore | None = None,
    thread_factory: object | None = None,
    skill_catalog: SkillCatalog | None = None,
    skill_installer: SkillPackageInstaller | None = None,
    session_deletion: SessionDeletionService | None = None,
    model_catalog: RecordingModelCatalog | None = None,
) -> SessionController:
    lease = WorkspaceSessionLease.acquire(tmp_path)
    selected_store = store or SQLiteSessionStore(tmp_path)
    selected_store.initialize()
    selected_store.recover_incomplete_runs()
    selected_catalog = skill_catalog or SkillCatalog(
        user_root=tmp_path / "user-skills",
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    selected_model_catalog = model_catalog or RecordingModelCatalog()
    if not hasattr(executor, "default_model_id"):
        executor.default_model_id = MODEL_ID
    kwargs: dict[str, object] = {}
    if thread_factory is not None:
        kwargs["thread_factory"] = thread_factory
    if skill_installer is not None:
        kwargs["skill_installer"] = skill_installer
    if session_deletion is not None:
        kwargs["session_deletion"] = session_deletion
    try:
        return SessionController(
            store=selected_store,
            lease=lease,
            executor=executor,  # type: ignore[arg-type]
            model_catalog=selected_model_catalog,
            event_hub=SessionEventHub(),
            skill_catalog=selected_catalog,
            **kwargs,  # type: ignore[arg-type]
        )
    except BaseException:
        lease.close()
        raise


def test_controller_rejects_catalog_executor_default_mismatch(
    tmp_path: Path,
) -> None:
    with pytest.raises(SessionControllerError) as captured:
        make_controller(
            tmp_path,
            BlockingExecutor(tmp_path, (failed_outcome(),)),
            model_catalog=RecordingModelCatalog(
                default_model_id="different-default",
                model_ids=("different-default",),
            ),
        )

    assert captured.value.code == "invalid_session_state"


def test_create_resolves_default_before_persisting_and_starting_worker(
    tmp_path: Path,
) -> None:
    catalog = RecordingModelCatalog()
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, model_catalog=catalog)
    handle = controller.create_session("inspect")

    assert executor.started.wait(timeout=1.0)
    request = executor.requests[0]
    assert isinstance(request, SessionRunRequest)
    assert catalog.calls[0] == ("resolve", None)
    assert handle.model_id == MODEL_ID
    assert request.model_id == MODEL_ID
    assert controller._store.get_run(handle.run_id).model_id == MODEL_ID
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_followup_can_snapshot_a_different_available_model(tmp_path: Path) -> None:
    catalog = RecordingModelCatalog()
    executor = BlockingExecutor(tmp_path, (failed_outcome(), failed_outcome()))
    controller = make_controller(tmp_path, executor, model_catalog=catalog)
    first = controller.create_session("first")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    controller.wait_for_run(first.run_id, timeout_seconds=2.0)

    second = controller.submit_message(
        first.session_id,
        "second",
        model_id=SELECTED_MODEL_ID,
    )
    controller.wait_for_run(second.run_id, timeout_seconds=2.0)

    assert second.model_id == SELECTED_MODEL_ID
    assert isinstance(executor.requests[1], SessionRunRequest)
    assert executor.requests[1].model_id == SELECTED_MODEL_ID
    assert controller._store.get_run(second.run_id).model_id == SELECTED_MODEL_ID
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_unknown_model_is_rejected_without_admission_side_effects(
    tmp_path: Path,
) -> None:
    catalog = RecordingModelCatalog()
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, model_catalog=catalog)

    with pytest.raises(SessionControllerError) as captured:
        controller.create_session("inspect", model_id="unknown-model")

    assert captured.value.code == "model_not_available"
    assert controller.list_sessions() == ()
    assert executor.requests == []
    assert executor.started.is_set() is False
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_catalog_refresh_does_not_mutate_active_request(tmp_path: Path) -> None:
    catalog = RecordingModelCatalog()
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, model_catalog=catalog)
    handle = controller.create_session("inspect", model_id=SELECTED_MODEL_ID)
    assert executor.started.wait(timeout=1.0)
    request = executor.requests[0]
    assert isinstance(request, SessionRunRequest)

    view = controller.list_models(refresh=True)

    assert view.model_ids == (MODEL_ID, SELECTED_MODEL_ID)
    assert request.model_id == SELECTED_MODEL_ID
    assert handle.model_id == SELECTED_MODEL_ID
    assert catalog.calls[-1] == ("list_models", True)
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_persisted_request_model_mismatch_fails_before_executor(
    tmp_path: Path,
) -> None:
    class MismatchingStore(SQLiteSessionStore):
        def start_run(self, run_id: str) -> SessionRunRecord:
            return replace(super().start_run(run_id), model_id="other-model")

    store = MismatchingStore(tmp_path)
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, store=store)
    handle = controller.create_session("inspect")

    terminal = controller.wait_for_run(handle.run_id, timeout_seconds=2.0)

    assert terminal.status is SessionRunStatus.FAILED
    assert terminal.termination_reason == "controller_error"
    assert executor.requests == []
    assert executor.started.is_set() is False
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_session_deletion_open_uses_exact_factory_service_and_recovers(
    tmp_path: Path,
) -> None:
    calls: list[tuple[Path, object]] = []
    services: list[SessionDeletionService] = []

    class RecordingService(SessionDeletionService):
        def __init__(self, workspace: Path, store: object) -> None:
            super().__init__(workspace, store)  # type: ignore[arg-type]
            self.recovery_calls = 0

        def recover_pending(self) -> None:
            self.recovery_calls += 1

    def factory(workspace: Path, store: object) -> SessionDeletionService:
        calls.append((workspace, store))
        service = RecordingService(workspace, store)
        services.append(service)
        return service

    controller = SessionController.open(
        tmp_path,
        BlockingExecutor(tmp_path, (failed_outcome(),)),
        model_catalog=RecordingModelCatalog(),
        session_deletion_factory=factory,  # type: ignore[arg-type]
    )

    assert len(calls) == 1
    assert calls[0][0] == tmp_path.resolve(strict=True)
    assert calls[0][1] is controller._store
    assert controller._session_deletion is services[0]
    assert services[0].recovery_calls == 1  # type: ignore[attr-defined]
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_session_deletion_open_default_composes_exact_dependency(
    tmp_path: Path,
) -> None:
    controller = SessionController.open(
        tmp_path,
        BlockingExecutor(tmp_path, (failed_outcome(),)),
        model_catalog=RecordingModelCatalog(),
    )

    assert type(controller._session_deletion) is SessionDeletionService
    assert controller._session_deletion.store is controller._store
    assert controller._session_deletion.workspace == controller.workspace
    assert controller.shutdown(timeout_seconds=1.0) is True


@pytest.mark.parametrize("mismatch", ("store", "workspace"))
def test_session_deletion_open_rejects_dependency_identity_and_closes_lease(
    tmp_path: Path,
    mismatch: str,
) -> None:
    def factory(workspace: Path, store: object) -> SessionDeletionService:
        if mismatch == "store":
            other_store = SQLiteSessionStore(workspace)
        else:
            other_workspace = tmp_path / "other"
            other_workspace.mkdir()
            other_store = SQLiteSessionStore(other_workspace)
        other_store.initialize()
        return SessionDeletionService(other_store.workspace, other_store)

    with pytest.raises(SessionControllerError) as captured:
        SessionController.open(
            tmp_path,
            BlockingExecutor(tmp_path, (failed_outcome(),)),
            model_catalog=RecordingModelCatalog(),
            session_deletion_factory=factory,  # type: ignore[arg-type]
        )

    assert captured.value.code == "invalid_session_state"
    replacement = WorkspaceSessionLease.acquire(tmp_path)
    replacement.close()


def test_session_deletion_recovery_failure_is_stable_and_closes_lease(
    tmp_path: Path,
) -> None:
    class FailingRecoveryService(SessionDeletionService):
        def recover_pending(self) -> None:
            raise SessionDeletionError("session_deletion_recovery_failed")

    with pytest.raises(SessionControllerError) as captured:
        SessionController.open(
            tmp_path,
            BlockingExecutor(tmp_path, (failed_outcome(),)),
            model_catalog=RecordingModelCatalog(),
            session_deletion_factory=lambda workspace, store: (
                FailingRecoveryService(workspace, store)
            ),
        )

    assert captured.value.code == "session_deletion_recovery_failed"
    replacement = WorkspaceSessionLease.acquire(tmp_path)
    replacement.close()


def test_session_deletion_factory_failure_is_stable_and_closes_lease(
    tmp_path: Path,
) -> None:
    def failing_factory(workspace: Path, store: object) -> SessionDeletionService:
        del workspace, store
        raise OSError("private factory detail")

    with pytest.raises(SessionControllerError) as captured:
        SessionController.open(
            tmp_path,
            BlockingExecutor(tmp_path, (failed_outcome(),)),
            model_catalog=RecordingModelCatalog(),
            session_deletion_factory=failing_factory,  # type: ignore[arg-type]
        )

    assert captured.value.code == "invalid_session_state"
    replacement = WorkspaceSessionLease.acquire(tmp_path)
    replacement.close()


def test_delete_session_removes_session_and_forgets_retained_run(
    tmp_path: Path,
) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor)
    handle = controller.create_session("delete retained session")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=1.0)
    assert controller.read_updates(handle.run_id).events

    result = controller.delete_session(handle.session_id)

    assert result.session_id == handle.session_id
    assert result.run_ids == (handle.run_id,)
    assert controller._event_run_id is None
    with pytest.raises(SessionControllerError) as missing_session:
        controller.get_session(handle.session_id)
    assert missing_session.value.code == "session_not_found"
    with pytest.raises(SessionControllerError) as missing_updates:
        controller.read_updates(handle.run_id)
    assert missing_updates.value.code == "run_not_found"
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_delete_session_rejects_active_controller_as_busy(tmp_path: Path) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor)
    handle = controller.create_session("active")
    assert executor.started.wait(timeout=1.0)

    with pytest.raises(SessionControllerError) as captured:
        controller.delete_session(handle.session_id)

    assert captured.value.code == "controller_busy"
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=1.0)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_delete_session_rejects_non_idle_session(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path)
    controller = make_controller(
        tmp_path,
        BlockingExecutor(tmp_path, (failed_outcome(),)),
        store=store,
    )
    submission = store.create_session(
        "queued outside controller", model_id=MODEL_ID
    )

    with pytest.raises(SessionControllerError) as captured:
        controller.delete_session(submission.session.session_id)

    assert captured.value.code == "invalid_session_state"
    assert store.session_exists(submission.session.session_id) is True
    assert controller.shutdown(timeout_seconds=1.0) is True


@pytest.mark.parametrize(
    ("state", "expected"),
    (("closed", "controller_closed"), ("degraded", "controller_degraded")),
)
def test_delete_session_honors_unavailable_controller_state(
    tmp_path: Path,
    state: str,
    expected: str,
) -> None:
    controller = make_controller(
        tmp_path,
        BlockingExecutor(tmp_path, (failed_outcome(),)),
    )
    if state == "closed":
        assert controller.shutdown(timeout_seconds=1.0) is True
    else:
        controller._degraded = True

    with pytest.raises(SessionControllerError) as captured:
        controller.delete_session("1" * 32)

    assert captured.value.code == expected
    if state == "degraded":
        controller._degraded = False
        assert controller.shutdown(timeout_seconds=1.0) is True


def test_delete_session_translates_failure_and_releases_admission(
    tmp_path: Path,
) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor)
    handle = controller.create_session("terminal")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=1.0)
    real_delete = controller._session_deletion.delete

    def fail_delete(session_id: str) -> object:
        del session_id
        raise SessionDeletionError("session_delete_failed")

    controller._session_deletion.delete = fail_delete  # type: ignore[method-assign]
    with pytest.raises(SessionControllerError) as captured:
        controller.delete_session(handle.session_id)
    assert captured.value.code == "session_delete_failed"

    controller._session_deletion.delete = real_delete  # type: ignore[method-assign]
    assert controller.delete_session(handle.session_id).session_id == handle.session_id
    assert controller.shutdown(timeout_seconds=1.0) is True


def skill_archive(skill_id: str = "review") -> bytes:
    raw = (
        f"---\nid: {skill_id}\nname: Review\n"
        "description: Review safely.\n---\nReview the workspace.\n"
    ).encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(f"{skill_id}/SKILL.md", raw)
    return output.getvalue()


def test_skill_installer_must_match_exact_workspace_root(tmp_path: Path) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    wrong = SkillPackageInstaller(tmp_path / "other-skills")
    with pytest.raises(SessionControllerError) as captured:
        make_controller(tmp_path, executor, skill_installer=wrong)
    assert captured.value.code == "invalid_session_state"


def test_skill_installer_injection_requires_exact_concrete_type(tmp_path: Path) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    with pytest.raises(TypeError, match="skill_installer must be"):
        make_controller(
            tmp_path,
            executor,
            skill_installer=object(),  # type: ignore[arg-type]
        )


def test_import_skill_archive_publishes_and_rediscovers_exact_descriptor(
    tmp_path: Path,
) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor)

    descriptor = controller.import_skill_archive(skill_archive())

    assert descriptor.skill_id == "review"
    assert descriptor.source is SkillSource.WORKSPACE
    assert controller.list_skills().skills == (descriptor,)
    assert (tmp_path / ".coding-agent" / "skills" / "review" / "SKILL.md").is_file()
    assert controller.list_sessions() == ()


def test_import_skill_archive_rejects_existing_user_skill_before_writing(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user-skills"
    write_skill(user_root, "review", "Review the workspace.")
    catalog = SkillCatalog(
        user_root=user_root,
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)

    with pytest.raises(SessionControllerError) as captured:
        controller.import_skill_archive(skill_archive())

    assert captured.value.code == "skill_already_exists"
    assert not (tmp_path / ".coding-agent" / "skills").exists()


def test_import_skill_archive_releases_admission_after_invalid_archive(
    tmp_path: Path,
) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor)

    with pytest.raises(SessionControllerError) as captured:
        controller.import_skill_archive(b"not-a-zip")
    assert captured.value.code == "invalid_skill_archive"

    descriptor = controller.import_skill_archive(skill_archive("second"))
    assert descriptor.skill_id == "second"


def test_import_skill_archive_rejects_unusable_preflight_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = SkillCatalog(
        user_root=tmp_path / "user-skills",
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    monkeypatch.setattr(
        catalog,
        "discover",
        lambda: SkillCatalogView(skills=(), diagnostics=(), usable=False),
    )
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)

    with pytest.raises(SessionControllerError) as captured:
        controller.import_skill_archive(skill_archive())

    assert captured.value.code == "skill_catalog_unavailable"
    assert not catalog.workspace_root.exists()


def test_import_skill_archive_holds_single_admission_while_installing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installer = SkillPackageInstaller(tmp_path / ".coding-agent" / "skills")
    original_install = installer.install
    entered = Event()
    release = Event()

    def blocking_install(archive: bytes) -> SkillDescriptor:
        entered.set()
        assert release.wait(timeout=2.0)
        return original_install(archive)

    monkeypatch.setattr(installer, "install", blocking_install)
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_installer=installer)
    results: list[SkillDescriptor] = []
    worker = Thread(
        target=lambda: results.append(controller.import_skill_archive(skill_archive())),
    )
    worker.start()
    assert entered.wait(timeout=1.0)

    with pytest.raises(SessionControllerError) as captured:
        controller.create_session("must be rejected")
    assert captured.value.code == "controller_busy"

    release.set()
    worker.join(timeout=2.0)
    assert not worker.is_alive()
    assert [item.skill_id for item in results] == ["review"]


def test_import_skill_archive_post_publish_mismatch_preserves_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = SkillCatalog(
        user_root=tmp_path / "user-skills",
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    real_discover = catalog.discover
    calls = 0

    def racing_discover() -> SkillCatalogView:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_discover()
        return SkillCatalogView(skills=(), diagnostics=(), usable=False)

    monkeypatch.setattr(catalog, "discover", racing_discover)
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)

    with pytest.raises(SessionControllerError) as captured:
        controller.import_skill_archive(skill_archive())

    assert captured.value.code == "skill_install_failed"
    assert (catalog.workspace_root / "review" / "SKILL.md").is_file()


def test_import_skill_archive_honors_closed_controller_state(tmp_path: Path) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor)
    assert controller.shutdown(timeout_seconds=1.0) is True

    with pytest.raises(SessionControllerError) as captured:
        controller.import_skill_archive(skill_archive())

    assert captured.value.code == "controller_closed"


def test_import_skill_archive_honors_degraded_controller_state(tmp_path: Path) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor)
    controller._degraded = True

    with pytest.raises(SessionControllerError) as captured:
        controller.import_skill_archive(skill_archive())

    assert captured.value.code == "controller_degraded"


def write_skill(root: Path, skill_id: str, body: str) -> Path:
    directory = root / skill_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    path.write_text(
        "---\n"
        f"id: {skill_id}\n"
        f"name: {skill_id.title()}\n"
        "description: deterministic controller test skill\n"
        "---\n"
        f"{body}",
        encoding="utf-8",
    )
    return path


def test_create_session_resolves_and_persists_ordered_first_run_skills(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user-skills"
    workspace_root = tmp_path / ".coding-agent" / "skills"
    write_skill(user_root, "first", "first private body")
    write_skill(workspace_root, "second", "second private body")
    catalog = SkillCatalog(user_root=user_root, workspace_root=workspace_root)
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)
    handle = controller.create_session("inspect", skill_ids=("second", "first"))
    assert executor.started.wait(timeout=1.0)
    request = executor.requests[0]
    assert isinstance(request, SessionRunRequest)
    assert request.skill_bundle is not None
    assert [item.descriptor.skill_id for item in request.skill_bundle.items] == [
        "second",
        "first",
    ]
    assert controller.get_session_skills(handle.session_id) == ("second", "first")
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_controller_rejects_catalog_for_different_workspace(
    tmp_path: Path,
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    lease = WorkspaceSessionLease.acquire(tmp_path)
    store = SQLiteSessionStore(tmp_path)
    store.initialize()
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    catalog = SkillCatalog(
        user_root=tmp_path / "user-skills",
        workspace_root=other / ".coding-agent" / "skills",
    )
    try:
        with pytest.raises(SessionControllerError) as captured:
            SessionController(
                store=store,
                lease=lease,
                executor=executor,
                model_catalog=RecordingModelCatalog(),
                event_hub=SessionEventHub(),
                skill_catalog=catalog,
            )
        assert captured.value.code == "invalid_session_state"
    finally:
        lease.close()


def test_idle_session_selection_can_be_reordered_and_cleared(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user-skills"
    write_skill(root, "first", "first")
    write_skill(root, "second", "second")
    catalog = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)
    first = controller.create_session("first")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    controller.wait_for_run(first.run_id, timeout_seconds=2.0)
    assert [item.skill_id for item in controller.list_skills().skills] == [
        "first",
        "second",
    ]
    assert controller.set_session_skills(
        first.session_id,
        ("second", "first"),
    ) == ("second", "first")
    assert controller.get_session_skills(first.session_id) == ("second", "first")
    assert controller.set_session_skills(first.session_id, ()) == ()
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_selection_change_is_rejected_while_any_run_is_active(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user-skills"
    write_skill(root, "review", "review")
    catalog = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)
    handle = controller.create_session("running")
    assert executor.started.wait(timeout=1.0)
    with pytest.raises(SessionControllerError) as captured:
        controller.set_session_skills(handle.session_id, ("review",))
    assert captured.value.code == "controller_busy"
    assert controller.get_session_skills(handle.session_id) == ()
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_submit_message_resolves_persisted_selection_for_new_run(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user-skills"
    write_skill(root, "review", "follow-up private body")
    catalog = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    executor = BlockingExecutor(tmp_path, (failed_outcome(), failed_outcome()))
    store = SQLiteSessionStore(tmp_path)
    controller = make_controller(
        tmp_path,
        executor,
        store=store,
        skill_catalog=catalog,
    )
    first = controller.create_session("first")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    controller.wait_for_run(first.run_id, timeout_seconds=2.0)
    assert controller.set_session_skills(first.session_id, ("review",)) == (
        "review",
    )
    executor.started.clear()
    executor.release.clear()
    second = controller.submit_message(first.session_id, "second")
    assert executor.started.wait(timeout=1.0)
    request = executor.requests[-1]
    assert isinstance(request, SessionRunRequest)
    assert request.skill_bundle is not None
    assert request.skill_bundle.text.endswith("follow-up private body")
    snapshots = store.get_run_skill_snapshots(second.run_id)
    assert [item.skill_id for item in snapshots] == ["review"]
    executor.release.set()
    controller.wait_for_run(second.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_same_session_can_submit_independent_run_modes(tmp_path: Path) -> None:
    executor = BlockingExecutor(
        tmp_path,
        (failed_outcome("inspection_finished"), failed_outcome("change_finished")),
    )
    controller = make_controller(tmp_path, executor)

    first = controller.create_session(
        "inspect",
        run_mode=RunMode.READ_ONLY,
    )
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    controller.wait_for_run(first.run_id, timeout_seconds=2.0)

    executor.started.clear()
    executor.release.clear()
    second = controller.submit_message(
        first.session_id,
        "now change it",
        run_mode=RunMode.MODIFY,
    )
    assert executor.started.wait(timeout=1.0)

    assert first.run_mode is RunMode.READ_ONLY
    assert second.run_mode is RunMode.MODIFY
    assert executor.requests[0].run_mode is RunMode.READ_ONLY
    assert executor.requests[1].run_mode is RunMode.MODIFY
    assert controller.get_session(first.session_id).runs[0].run_mode is RunMode.READ_ONLY
    assert controller.get_session(first.session_id).runs[1].run_mode is RunMode.MODIFY

    executor.release.set()
    controller.wait_for_run(second.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_follow_up_can_choose_new_profile_without_mutating_prior_run(
    tmp_path: Path,
) -> None:
    executor = BlockingExecutor(
        tmp_path,
        (failed_outcome("first_finished"), failed_outcome("second_finished")),
    )
    controller = make_controller(tmp_path, executor)

    first = controller.create_session(
        "inspect",
        budget_profile=BudgetProfile.STANDARD,
    )
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    controller.wait_for_run(first.run_id, timeout_seconds=2.0)

    executor.started.clear()
    executor.release.clear()
    second = controller.submit_message(
        first.session_id,
        "go deeper",
        budget_profile=BudgetProfile.DEEP,
    )
    assert executor.started.wait(timeout=1.0)

    runs = controller.get_session(first.session_id).runs
    assert [run.budget_profile for run in runs] == [
        BudgetProfile.STANDARD,
        BudgetProfile.DEEP,
    ]
    assert first.budget_profile is BudgetProfile.STANDARD
    assert second.budget_profile is BudgetProfile.DEEP
    assert executor.requests[0].budget_profile is BudgetProfile.STANDARD
    assert executor.requests[1].budget_profile is BudgetProfile.DEEP

    executor.release.set()
    controller.wait_for_run(second.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_controller_defaults_run_mode_to_modify(tmp_path: Path) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor)
    handle = controller.create_session("inspect")
    assert executor.started.wait(timeout=1.0)

    assert handle.run_mode is RunMode.MODIFY
    assert executor.requests[0].run_mode is RunMode.MODIFY

    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_controller_rejects_non_enum_mode_before_store(tmp_path: Path) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    store = SQLiteSessionStore(tmp_path)
    controller = make_controller(tmp_path, executor, store=store)

    with pytest.raises(TypeError, match="run_mode must be RunMode"):
        controller.create_session(
            "inspect",
            run_mode="read_only",  # type: ignore[arg-type]
        )

    assert store.list_sessions() == ()
    assert executor.requests == []
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_missing_selected_skill_creates_no_follow_up_run_or_event(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user-skills"
    skill_file = write_skill(root, "review", "private removed body")
    catalog = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)
    first = controller.create_session("first")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    controller.wait_for_run(first.run_id, timeout_seconds=2.0)
    controller.set_session_skills(first.session_id, ("review",))
    before = controller.get_session(first.session_id)
    skill_file.unlink()
    with pytest.raises(SessionControllerError) as captured:
        controller.submit_message(first.session_id, "second")
    assert captured.value.code == "selected_skill_unavailable"
    after = controller.get_session(first.session_id)
    assert after.runs == before.runs
    assert after.events == before.events
    assert len(executor.requests) == 1
    assert "private removed body" not in repr(captured.value)
    assert str(tmp_path) not in repr(captured.value)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_catalog_change_after_admission_does_not_change_active_bundle(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user-skills"
    skill_file = write_skill(root, "review", "old private body")
    catalog = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)
    handle = controller.create_session("first", skill_ids=("review",))
    assert executor.started.wait(timeout=1.0)
    request = executor.requests[0]
    assert isinstance(request, SessionRunRequest)
    assert request.skill_bundle is not None
    write_skill(root, "review", "new private body")
    assert "old private body" in request.skill_bundle.text
    assert "new private body" not in request.skill_bundle.text
    assert skill_file.read_text(encoding="utf-8").endswith("new private body")
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_skill_resolution_failure_creates_no_first_session_or_worker(
    tmp_path: Path,
) -> None:
    catalog = SkillCatalog(
        user_root=tmp_path / "user-skills",
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)
    with pytest.raises(SessionControllerError) as captured:
        controller.create_session("first", skill_ids=("missing",))
    assert captured.value.code == "selected_skill_unavailable"
    assert controller.list_sessions() == ()
    assert executor.requests == []
    assert executor.started.is_set() is False
    assert str(tmp_path) not in repr(captured.value)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_create_session_rejects_empty_tuple_subclass_without_side_effects(
    tmp_path: Path,
) -> None:
    class EmptyTuple(tuple[()]):
        pass

    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor)
    try:
        with pytest.raises(SessionControllerError) as captured:
            controller.create_session(
                "first",
                skill_ids=EmptyTuple(),  # type: ignore[arg-type]
            )
        assert captured.value.code == "invalid_skill_selection"
        assert controller.list_sessions() == ()
        assert executor.requests == []
        assert executor.started.is_set() is False
    finally:
        executor.release.set()
        assert controller.shutdown(timeout_seconds=1.0) is True


def test_controller_rejects_mismatched_workspace_components(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    lease = WorkspaceSessionLease.acquire(first)
    store = SQLiteSessionStore(first)
    store.initialize()
    executor = BlockingExecutor(second, (failed_outcome(),))
    try:
        with pytest.raises(SessionControllerError) as captured:
            SessionController(
                store=store,
                lease=lease,
                executor=executor,
                model_catalog=RecordingModelCatalog(),
                event_hub=SessionEventHub(),
            )
        assert captured.value.code == "invalid_session_state"
    finally:
        lease.close()


def test_open_rejects_executor_workspace_before_recovery(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    store = SQLiteSessionStore(first)
    store.initialize()
    submission = store.create_session("must remain queued", model_id=MODEL_ID)
    executor = BlockingExecutor(second, (failed_outcome(),))

    with pytest.raises(SessionControllerError) as captured:
        SessionController.open(
            first,
            executor,
            model_catalog=RecordingModelCatalog(),
        )

    assert captured.value.code == "invalid_session_state"
    unchanged = SQLiteSessionStore(first)
    unchanged.initialize()
    assert unchanged.get_run(submission.run.run_id).status is SessionRunStatus.QUEUED
    assert (
        unchanged.get_session(submission.session.session_id).status
        is SessionStatus.RUNNING
    )
    assert all(
        event.kind is not PersistedSessionEventKind.RUN_RECOVERED
        for event in unchanged.load_events(submission.session.session_id)
    )


def test_controller_rejects_second_run_while_worker_is_active(
    tmp_path: Path,
) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor)
    first = controller.create_session("first task")
    assert executor.started.wait(timeout=1.0)
    with pytest.raises(SessionControllerError) as captured:
        controller.create_session("second task")
    assert captured.value.code == "controller_busy"
    assert len(controller.list_sessions()) == 1
    executor.release.set()
    terminal = controller.wait_for_run(first.run_id, timeout_seconds=2.0)
    assert terminal.status is SessionRunStatus.FAILED
    assert controller.get_session(first.session_id).session.status is SessionStatus.IDLE
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_invalid_message_creates_no_database_row(tmp_path: Path) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor)
    with pytest.raises(SessionControllerError) as captured:
        controller.create_session("   ")
    assert captured.value.code == "invalid_message"
    assert controller.list_sessions() == ()
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_get_session_returns_runs_events_and_stable_not_found(
    tmp_path: Path,
) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor)
    handle = controller.create_session("inspect")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    view = controller.get_session(handle.session_id)
    assert [run.run_id for run in view.runs] == [handle.run_id]
    assert [event.sequence for event in view.events] == sorted(
        event.sequence for event in view.events
    )
    with pytest.raises(SessionControllerError) as captured:
        controller.get_session("f" * 32)
    assert captured.value.code == "session_not_found"
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_worker_is_named_and_non_daemon(tmp_path: Path) -> None:
    created: list[Thread] = []

    def thread_factory(target: object, name: str) -> Thread:
        thread = Thread(target=target, name=name, daemon=False)  # type: ignore[arg-type]
        created.append(thread)
        return thread

    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(
        tmp_path,
        executor,
        thread_factory=thread_factory,
    )
    handle = controller.create_session("inspect")
    assert executor.started.wait(timeout=1.0)
    assert created[0].daemon is False
    assert handle.run_id in created[0].name
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_executor_exception_finishes_with_fixed_controller_error(
    tmp_path: Path,
) -> None:
    class ExplodingExecutor:
        workspace = tmp_path.resolve(strict=True)

        def execute(self, request: object, **kwargs: object) -> SessionRunOutcome:
            del request, kwargs
            raise RuntimeError("private executor detail")

    controller = make_controller(tmp_path, ExplodingExecutor())
    handle = controller.create_session("explode")
    terminal = controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert terminal.status is SessionRunStatus.FAILED
    assert terminal.termination_reason == "controller_error"
    rendered = repr(controller.get_session(handle.session_id))
    assert "private executor detail" not in rendered
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_idle_session_accepts_follow_up_with_safe_narrative(
    tmp_path: Path,
) -> None:
    executor = BlockingExecutor(
        tmp_path,
        (failed_outcome("first"), failed_outcome("second")),
    )
    controller = make_controller(tmp_path, executor)
    first = controller.create_session("inspect parser")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    controller.wait_for_run(first.run_id, timeout_seconds=2.0)

    executor.started.clear()
    executor.release.clear()
    second = controller.submit_message(first.session_id, "now fix parser")
    assert executor.started.wait(timeout=1.0)
    second_request = executor.requests[1]
    assert second_request.current_message == "now fix parser"
    assert "inspect parser" in second_request.initial_user_message
    assert "now fix parser" in second_request.initial_user_message
    assert "call_id" not in second_request.initial_user_message
    executor.release.set()
    controller.wait_for_run(second.run_id, timeout_seconds=2.0)

    view = controller.get_session(first.session_id)
    assert [run.ordinal for run in view.runs] == [1, 2]
    assert view.runs[0].status is SessionRunStatus.FAILED
    assert controller.shutdown(timeout_seconds=1.0) is True


def _safe_tool_completed_event(safe_error_code: str | None = None) -> RunEvent:
    return RunEvent(
        schema_version=1,
        run_id="8" * 32,
        sequence=1,
        timestamp_utc="2026-08-29T00:00:00.000000Z",
        elapsed_ms=1,
        event_type=EventType.TOOL_CALL_COMPLETED,
        data={
            "ordinal": 1,
            "tool_name": "read_file",
            "call_id_hash": "a" * 64,
            "status": "rejected" if safe_error_code is not None else "ok",
            "safe_error_code": safe_error_code,
            "output_chars": 99,
            "exit_code": None,
            "timed_out": False,
            "truncated": False,
            "duration_ms": 2,
            "changed_paths": [],
            "mutation_index_before": 0,
            "mutation_index_after": 0,
            "executed": safe_error_code is None,
        },
    )


def _safe_tool_started_event() -> RunEvent:
    return RunEvent(
        schema_version=1,
        run_id="8" * 32,
        sequence=1,
        timestamp_utc="2026-08-29T00:00:00.000000Z",
        elapsed_ms=1,
        event_type=EventType.TOOL_CALL_STARTED,
        data={
            "ordinal": 1,
            "tool_name": "read_file",
            "call_id_hash": "a" * 64,
            "mutation_index": 0,
        },
    )


@pytest.mark.parametrize(
    ("audit_code", "wire_code"),
    [
        ("security_rejected:executable_denied", "executable_denied"),
        ("agent_rejected:decision_required", "decision_required"),
        ("agent_rejected:verification_required", "verification_required"),
        ("tool_error", "tool_error"),
        ("tool_rejected", "tool_rejected"),
        (None, None),
    ],
)
def test_tool_error_code_is_projected_to_safe_session_wire_code(
    tmp_path: Path,
    audit_code: str | None,
    wire_code: str | None,
) -> None:
    class ScriptedExecutor:
        workspace = tmp_path.resolve(strict=True)

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            audit = handlers["run_event_handler"]
            audit(_safe_tool_completed_event(safe_error_code=audit_code))  # type: ignore[operator]
            return failed_outcome()

    controller = make_controller(tmp_path, ScriptedExecutor())
    handle = controller.create_session("project safe code")
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)

    view = controller.get_session(handle.session_id)
    persisted = next(
        event
        for event in view.events
        if event.kind is PersistedSessionEventKind.TOOL_ACTIVITY
    )
    updates = controller.read_updates(handle.run_id).events
    published = next(
        item for item in updates if item.kind is SessionUpdateKind.TOOL_FINISHED
    )

    assert persisted.data["safe_error_code"] == wire_code
    assert published.data["safe_error_code"] == wire_code
    assert all(
        item.kind is not SessionUpdateKind.CONTROLLER_ERROR for item in updates
    )
    assert controller.shutdown(timeout_seconds=1.0) is True


@pytest.mark.parametrize(
    "unsafe_code",
    [
        "security_rejected:not_a_safety_code",
        "agent_rejected:not_an_agent_code",
        "unknown_namespace:value",
    ],
)
def test_safe_session_wire_code_rejects_unknown_namespaces(
    unsafe_code: str,
) -> None:
    helper = getattr(
        session_controller_module,
        "_session_safe_tool_error_code",
    )

    with pytest.raises(ValueError, match="^invalid_safe_error_code$"):
        helper(unsafe_code)


def test_changes_unverified_session_detail_survives_controller_reload(
    tmp_path: Path,
) -> None:
    class ImmediateExecutor:
        workspace = tmp_path.resolve(strict=True)

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request, handlers
            return changes_unverified_outcome()

    controller = make_controller(tmp_path, ImmediateExecutor())
    handle = controller.create_session("write a Python file")
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True

    reloaded = make_controller(tmp_path, ImmediateExecutor())
    view = reloaded.get_session(handle.session_id)
    run = view.runs[0]

    assert run.status is SessionRunStatus.FAILED
    assert run.agent_status == "failed"
    assert run.termination_reason == "changes_unverified"
    assert run.final_report is not None
    assert run.final_report["changed_paths"] == ["task_manager.py"]
    assert run.final_report["verification"]["status"] == "stale"
    assert reloaded.shutdown(timeout_seconds=1.0) is True


def test_stream_commit_discard_and_audit_event_mapping(tmp_path: Path) -> None:
    class ScriptedExecutor:
        workspace = tmp_path.resolve(strict=True)

        def execute(
            self,
            request: object,
            *,
            stream_handler: object,
            confirmed_text_handler: object,
            cancellation_requested: object,
            run_event_handler: object,
        ) -> SessionRunOutcome:
            del request, cancellation_requested
            stream = stream_handler  # type: ignore[assignment]
            confirmed = confirmed_text_handler  # type: ignore[assignment]
            audit = run_event_handler  # type: ignore[assignment]
            stream(ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, "discard me"))
            stream(ModelStreamEvent(ModelStreamEventKind.RESPONSE_DISCARDED))
            stream(ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, "keep "))
            stream(ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, "me"))
            stream(ModelStreamEvent(ModelStreamEventKind.RESPONSE_COMPLETED))
            confirmed("keep me")
            audit(_safe_tool_completed_event())
            return failed_outcome()

    controller = make_controller(tmp_path, ScriptedExecutor())
    handle = controller.create_session("stream")
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    live = controller.read_updates(handle.run_id).events
    selected = [
        update.kind
        for update in live
        if update.kind
        in {
            SessionUpdateKind.ASSISTANT_TEXT_DELTA,
            SessionUpdateKind.ASSISTANT_TEXT_DISCARDED,
            SessionUpdateKind.ASSISTANT_TEXT_COMMITTED,
            SessionUpdateKind.TOOL_FINISHED,
        }
    ]
    assert selected == [
        SessionUpdateKind.ASSISTANT_TEXT_DELTA,
        SessionUpdateKind.ASSISTANT_TEXT_DISCARDED,
        SessionUpdateKind.ASSISTANT_TEXT_DELTA,
        SessionUpdateKind.ASSISTANT_TEXT_DELTA,
        SessionUpdateKind.ASSISTANT_TEXT_COMMITTED,
        SessionUpdateKind.TOOL_FINISHED,
    ]
    events = controller.get_session(handle.session_id).events
    durable = [
        event
        for event in events
        if event.kind
        in {
            PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED,
            PersistedSessionEventKind.TOOL_ACTIVITY,
        }
    ]
    assert [event.kind for event in durable] == [
        PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED,
        PersistedSessionEventKind.TOOL_ACTIVITY,
    ]
    assert durable[0].data == {"content": "keep me"}
    rendered = repr(events)
    for forbidden in ("discard me", "call_id", "arguments", "stdout", "raw result"):
        assert forbidden not in rendered
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_tool_response_narration_is_discarded_before_tool_started(
    tmp_path: Path,
) -> None:
    class ToolNarrationExecutor:
        workspace = tmp_path.resolve(strict=True)

        def execute(
            self,
            request: object,
            *,
            stream_handler: object,
            confirmed_text_handler: object,
            cancellation_requested: object,
            run_event_handler: object,
        ) -> SessionRunOutcome:
            del request, confirmed_text_handler, cancellation_requested
            stream = stream_handler  # type: ignore[assignment]
            audit = run_event_handler  # type: ignore[assignment]
            stream(
                ModelStreamEvent(
                    ModelStreamEventKind.TEXT_DELTA,
                    "I will inspect",
                )
            )
            audit(_safe_tool_started_event())
            return failed_outcome()

    controller = make_controller(tmp_path, ToolNarrationExecutor())
    handle = controller.create_session("inspect")
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)

    selected_updates = [
        update
        for update in controller.read_updates(handle.run_id).events
        if update.kind
        in {
            SessionUpdateKind.ASSISTANT_TEXT_DELTA,
            SessionUpdateKind.ASSISTANT_TEXT_DISCARDED,
            SessionUpdateKind.TOOL_STARTED,
        }
    ]
    assert [update.kind for update in selected_updates] == [
        SessionUpdateKind.ASSISTANT_TEXT_DELTA,
        SessionUpdateKind.ASSISTANT_TEXT_DISCARDED,
        SessionUpdateKind.TOOL_STARTED,
    ]
    assert selected_updates[1].data == {
        "reason": "tool_response_narration"
    }
    durable_kinds = [
        event.kind for event in controller.get_session(handle.session_id).events
    ]
    assert (
        PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED
        not in durable_kinds
    )
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_convergence_audit_events_project_safe_progress_updates(
    tmp_path: Path,
) -> None:
    class ConvergenceExecutor:
        workspace = tmp_path.resolve(strict=True)

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            publish = handlers["run_event_handler"]  # type: ignore[assignment]
            events = (
                (
                    EventType.RUN_STARTED,
                    {
                        "task_chars": 7,
                        "mutation_index": 0,
                        "run_mode": "modify",
                        "budget_profile": "deep",
                        "max_main_model_calls": 40,
                        "max_summary_model_calls": 6,
                        "max_provider_attempts": 80,
                        "max_summary_provider_attempts": 12,
                        "max_tool_calls": 140,
                        "max_runtime_seconds": 1800,
                        "verification_tool_reserve": 1,
                    },
                ),
                (
                    EventType.PHASE_CHANGED,
                    {"from_phase": "discover", "to_phase": "act", "epoch": 1},
                ),
                (
                    EventType.DECISION_CHECKPOINT,
                    {
                        "reason": "exploration_limit",
                        "phase": "act",
                        "main_calls_remaining": 33,
                    },
                ),
                (
                    EventType.CONTEXT_COMPRESSION_COMPLETED,
                    {
                        "before_chars": 49_000,
                        "before_items": 21,
                        "after_chars": 31_000,
                        "after_items": 11,
                        "summary_source": "fallback",
                        "summary_model_failed": True,
                        "continuation_cleared": True,
                    },
                ),
                (
                    EventType.NO_PROGRESS_DETECTED,
                    {"phase": "act", "post_checkpoint_main_turns": 2},
                ),
                (
                    EventType.RUN_COMPLETED,
                    {
                        "status": "failed",
                        "termination_reason": "no_progress",
                        "budget_profile": "deep",
                        "phase": "act",
                        "main_model_calls": 7,
                        "summary_model_calls": 1,
                        "logical_model_calls": 8,
                        "summary_provider_attempts": 1,
                        "provider_attempts": 9,
                        "tool_calls": 12,
                        "verification_attempts": 0,
                        "mutation_index": 0,
                        "validation_index": None,
                        "elapsed_ms": 50,
                    },
                ),
            )
            for sequence, (event_type, data) in enumerate(events, start=1):
                publish(  # type: ignore[operator]
                    RunEvent(
                        schema_version=3,
                        run_id="8" * 32,
                        sequence=sequence,
                        timestamp_utc="2026-08-29T00:00:00.000000Z",
                        elapsed_ms=sequence,
                        event_type=event_type,
                        data=data,  # type: ignore[arg-type]
                    )
                )
            return failed_outcome("no_progress")

    controller = make_controller(tmp_path, ConvergenceExecutor())
    handle = controller.create_session(
        "inspect",
        budget_profile=BudgetProfile.DEEP,
    )
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    updates = controller.read_updates(handle.run_id).events
    selected = [
        update
        for update in updates
        if update.kind
        in {
            SessionUpdateKind.RUN_PROGRESS,
            SessionUpdateKind.PHASE_CHANGED,
            SessionUpdateKind.DECISION_CHECKPOINT,
            SessionUpdateKind.CONTEXT_COMPRESSED,
            SessionUpdateKind.NO_PROGRESS_DETECTED,
        }
    ]

    assert [update.kind for update in selected] == [
        SessionUpdateKind.RUN_PROGRESS,
        SessionUpdateKind.PHASE_CHANGED,
        SessionUpdateKind.RUN_PROGRESS,
        SessionUpdateKind.DECISION_CHECKPOINT,
        SessionUpdateKind.CONTEXT_COMPRESSED,
        SessionUpdateKind.NO_PROGRESS_DETECTED,
        SessionUpdateKind.RUN_PROGRESS,
    ]
    assert selected[-1].data == {
        "budget_profile": "deep",
        "phase": "act",
        "main_model_calls": 7,
        "main_model_limit": 40,
        "summary_model_calls": 1,
        "summary_model_limit": 6,
        "provider_attempts": 9,
        "provider_attempt_limit": 80,
        "tool_calls": 12,
        "tool_limit": 140,
    }
    encoded = "".join(update.to_json() for update in selected)
    for forbidden in ("summary_text", "continuation", "instructions", "Bearer "):
        assert forbidden not in encoded
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_post_mutation_checkpoint_does_not_cancel_or_degrade_controller(
    tmp_path: Path,
) -> None:
    class PostMutationCheckpointExecutor:
        workspace = tmp_path.resolve(strict=True)

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            publish = handlers["run_event_handler"]  # type: ignore[assignment]
            cancellation_requested = handlers[  # type: ignore[assignment]
                "cancellation_requested"
            ]
            publish(  # type: ignore[operator]
                RunEvent(
                    schema_version=3,
                    run_id="8" * 32,
                    sequence=1,
                    timestamp_utc="2026-08-31T12:10:10.988545Z",
                    elapsed_ms=17_561,
                    event_type=EventType.DECISION_CHECKPOINT,
                    data={
                        "reason": "post_mutation_integrity",
                        "phase": "verify",
                        "main_calls_remaining": 20,
                    },
                )
            )
            if cancellation_requested():  # type: ignore[operator]
                return interrupted_outcome()
            return failed_outcome("empty_model_response")

    controller = make_controller(tmp_path, PostMutationCheckpointExecutor())
    first = controller.create_session("create a game")
    first_terminal = controller.wait_for_run(first.run_id, timeout_seconds=2.0)

    assert first_terminal.status is SessionRunStatus.FAILED
    assert first_terminal.termination_reason == "empty_model_response"

    second = controller.submit_message(first.session_id, "continue")
    second_terminal = controller.wait_for_run(second.run_id, timeout_seconds=2.0)
    assert second_terminal.status is SessionRunStatus.FAILED
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_old_run_read_cannot_cross_new_run_hub_reset(tmp_path: Path) -> None:
    class BlockingReadHub(SessionEventHub):
        def __init__(self) -> None:
            super().__init__()
            self.armed = False
            self.read_entered = Event()
            self.release_read = Event()

        def read(
            self,
            *,
            after_sequence: int = 0,
            expected_run_id: str | None = None,
        ):  # type: ignore[no-untyped-def]
            if self.armed:
                self.read_entered.set()
                assert self.release_read.wait(timeout=2.0)
            if expected_run_id is None:
                return super().read(after_sequence=after_sequence)
            return super().read(
                after_sequence=after_sequence,
                expected_run_id=expected_run_id,  # type: ignore[call-arg]
            )

    store = SQLiteSessionStore(tmp_path)
    store.initialize()
    lease = WorkspaceSessionLease.acquire(tmp_path)
    event_hub = BlockingReadHub()
    executor = BlockingExecutor(
        tmp_path,
        (failed_outcome("first"), failed_outcome("second")),
    )
    controller = SessionController(
        store=store,
        lease=lease,
        executor=executor,
        model_catalog=RecordingModelCatalog(),
        event_hub=event_hub,
    )
    first = controller.create_session("first")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    controller.wait_for_run(first.run_id, timeout_seconds=2.0)
    event_hub.armed = True
    batches: list[object] = []
    error_codes: list[str] = []

    def read_old_run() -> None:
        try:
            batches.append(controller.read_updates(first.run_id))
        except SessionControllerError as exc:
            error_codes.append(exc.code)

    reader = Thread(target=read_old_run)
    reader.start()
    assert event_hub.read_entered.wait(timeout=1.0)
    second = controller.submit_message(first.session_id, "second")
    controller.wait_for_run(second.run_id, timeout_seconds=2.0)
    event_hub.release_read.set()
    reader.join(timeout=1.0)

    assert not reader.is_alive()
    assert batches == []
    assert error_codes == ["run_not_found"]
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_old_run_waiter_is_invalidated_when_new_run_begins(tmp_path: Path) -> None:
    wait_entered = Event()

    class SignallingCondition(Condition):
        def wait_for(self, predicate, timeout=None):  # type: ignore[no-untyped-def]
            wait_entered.set()
            return super().wait_for(predicate, timeout)

    class FollowUpEventExecutor:
        workspace = tmp_path.resolve(strict=True)
        default_model_id = MODEL_ID

        def __init__(self) -> None:
            self.calls = 0

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            self.calls += 1
            if self.calls == 2:
                handlers["confirmed_text_handler"]("new run content")  # type: ignore[operator]
            return failed_outcome()

    store = SQLiteSessionStore(tmp_path)
    store.initialize()
    lease = WorkspaceSessionLease.acquire(tmp_path)
    event_hub = SessionEventHub()
    event_hub._condition = SignallingCondition()  # type: ignore[attr-defined]
    controller = SessionController(
        store=store,
        lease=lease,
        executor=FollowUpEventExecutor(),
        model_catalog=RecordingModelCatalog(),
        event_hub=event_hub,
    )
    first = controller.create_session("first")
    controller.wait_for_run(first.run_id, timeout_seconds=2.0)
    last_sequence = controller.read_updates(first.run_id).last_sequence
    batches: list[object] = []
    error_codes: list[str] = []

    def wait_on_old_run() -> None:
        try:
            batches.append(
                controller.wait_for_updates(
                    first.run_id,
                    after_sequence=last_sequence,
                    timeout_seconds=2.0,
                )
            )
        except SessionControllerError as exc:
            error_codes.append(exc.code)

    waiter = Thread(target=wait_on_old_run)
    waiter.start()
    assert wait_entered.wait(timeout=1.0)
    second = controller.submit_message(first.session_id, "second")
    controller.wait_for_run(second.run_id, timeout_seconds=2.0)
    waiter.join(timeout=1.0)

    assert not waiter.is_alive()
    assert batches == []
    assert error_codes == ["run_not_found"]
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_sync_fallback_confirmed_text_is_committed(tmp_path: Path) -> None:
    class SyncExecutor:
        workspace = tmp_path.resolve(strict=True)

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            handlers["confirmed_text_handler"]("sync fallback text")  # type: ignore[operator]
            return failed_outcome()

    controller = make_controller(tmp_path, SyncExecutor())
    handle = controller.create_session("sync")
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    events = controller.get_session(handle.session_id).events
    committed = [
        event
        for event in events
        if event.kind is PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED
    ]
    assert [event.data["content"] for event in committed] == ["sync fallback text"]
    assert controller.shutdown(timeout_seconds=1.0) is True


class FailingToolActivityStore(SQLiteSessionStore):
    def append_event(self, event: NewSessionEvent):  # type: ignore[no-untyped-def]
        if event.kind is PersistedSessionEventKind.TOOL_ACTIVITY:
            raise SessionStoreError("storage_unavailable")
        return super().append_event(event)


def test_run_event_store_failure_degrades_and_returns_to_executor(
    tmp_path: Path,
) -> None:
    store = FailingToolActivityStore(tmp_path)
    store.initialize()

    class RunEventCallingExecutor:
        workspace = tmp_path.resolve(strict=True)

        def __init__(self) -> None:
            self.handler_returned = False
            self.cancellation_seen_after_handler = False
            self.received_callback_exception: Exception | None = None

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            try:
                handlers["run_event_handler"](_safe_tool_completed_event())  # type: ignore[operator]
                self.handler_returned = True
            except Exception as exc:
                self.received_callback_exception = exc
            self.cancellation_seen_after_handler = handlers["cancellation_requested"]()  # type: ignore[operator]
            return failed_outcome()

    executor = RunEventCallingExecutor()
    controller = make_controller(tmp_path, executor, store=store)
    handle = controller.create_session("observe tool event")
    terminal = controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert executor.handler_returned is True
    assert executor.cancellation_seen_after_handler is True
    assert executor.received_callback_exception is None
    assert terminal.status in {SessionRunStatus.FAILED, SessionRunStatus.INTERRUPTED}
    with pytest.raises(SessionControllerError) as captured:
        controller.create_session("must be rejected")
    assert captured.value.code == "controller_degraded"
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_cancel_is_idempotent_and_finishes_interrupted(tmp_path: Path) -> None:
    class CooperativeBlockingExecutor:
        workspace = tmp_path.resolve(strict=True)

        def __init__(self) -> None:
            self.started = Event()
            self.cancel_observed = Event()
            self.release = Event()

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            self.started.set()
            while not handlers["cancellation_requested"]():  # type: ignore[operator]
                self.cancel_observed.wait(0.01)
            self.cancel_observed.set()
            assert self.release.wait(timeout=2.0)
            return interrupted_outcome()

    executor = CooperativeBlockingExecutor()
    controller = make_controller(tmp_path, executor)
    handle = controller.create_session("cancel me")
    assert executor.started.wait(timeout=1.0)
    assert controller.cancel(handle.run_id) is CancellationResult.REQUESTED
    assert controller.cancel(handle.run_id) is CancellationResult.ALREADY_REQUESTED
    assert executor.cancel_observed.wait(timeout=1.0)
    executor.release.set()
    terminal = controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert terminal.status is SessionRunStatus.INTERRUPTED
    assert controller.cancel(handle.run_id) is CancellationResult.ALREADY_FINISHED
    events = controller.get_session(handle.session_id).events
    assert sum(
        event.kind is PersistedSessionEventKind.CANCELLATION_REQUESTED
        for event in events
    ) == 1
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_shutdown_timeout_never_force_stops_worker(tmp_path: Path) -> None:
    class UncooperativeBlockingExecutor:
        workspace = tmp_path.resolve(strict=True)

        def __init__(self) -> None:
            self.started = Event()
            self.release = Event()
            self.forced_stop_calls = 0

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request, handlers
            self.started.set()
            assert self.release.wait(timeout=2.0)
            return failed_outcome()

    executor = UncooperativeBlockingExecutor()
    controller = make_controller(tmp_path, executor)
    controller.create_session("wait for admitted operation")
    assert executor.started.wait(timeout=1.0)
    assert controller.shutdown(timeout_seconds=0.01) is False
    assert executor.forced_stop_calls == 0
    executor.release.set()
    assert controller.shutdown(timeout_seconds=2.0) is True


def test_shutdown_timeout_includes_blocked_cancellation_persistence(
    tmp_path: Path,
) -> None:
    class BlockingCancellationStore(SQLiteSessionStore):
        def __init__(self, workspace: Path) -> None:
            super().__init__(workspace)
            self.write_entered = Event()
            self.release_write = Event()

        def request_cancellation(self, run_id: str) -> SessionRunRecord:
            self.write_entered.set()
            assert self.release_write.wait(timeout=2.0)
            return super().request_cancellation(run_id)

    class CooperativeExecutor:
        workspace = tmp_path.resolve(strict=True)

        def __init__(self) -> None:
            self.started = Event()

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            self.started.set()
            cancellation_requested = handlers["cancellation_requested"]
            assert callable(cancellation_requested)
            while not cancellation_requested():
                self.started.wait(0.001)
            return interrupted_outcome()

    store = BlockingCancellationStore(tmp_path)
    store.initialize()
    executor = CooperativeExecutor()
    controller = make_controller(tmp_path, executor, store=store)
    controller.create_session("bounded shutdown")
    assert executor.started.wait(timeout=1.0)
    returned = Event()
    results: list[bool] = []

    def call_shutdown() -> None:
        results.append(controller.shutdown(timeout_seconds=0.01))
        returned.set()

    caller = Thread(target=call_shutdown)
    caller.start()
    assert store.write_entered.wait(timeout=1.0)
    completed_while_write_blocked = returned.wait(timeout=0.2)
    store.release_write.set()
    caller.join(timeout=1.0)

    assert completed_while_write_blocked is True
    assert results == [False]
    assert controller.shutdown(timeout_seconds=2.0) is True
    session = controller.list_sessions()[0]
    events = controller.get_session(session.session_id).events
    assert sum(
        event.kind is PersistedSessionEventKind.CANCELLATION_REQUESTED
        for event in events
    ) == 1


def test_shutdown_timeout_includes_blocked_session_admission(tmp_path: Path) -> None:
    class BlockingCreateStore(SQLiteSessionStore):
        def __init__(self, workspace: Path) -> None:
            super().__init__(workspace)
            self.create_entered = Event()
            self.release_create = Event()

        def create_session(
            self,
            message: str,
            *,
            model_id: str,
            selected_skills: tuple[SkillDescriptor, ...] = (),
            run_mode: RunMode = RunMode.MODIFY,
            budget_profile: BudgetProfile = BudgetProfile.STANDARD,
        ):  # type: ignore[no-untyped-def]
            self.create_entered.set()
            assert self.release_create.wait(timeout=2.0)
            return super().create_session(
                message,
                model_id=model_id,
                selected_skills=selected_skills,
                run_mode=run_mode,
                budget_profile=budget_profile,
            )

    store = BlockingCreateStore(tmp_path)
    store.initialize()
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, store=store)
    handles: list[object] = []

    creator = Thread(target=lambda: handles.append(controller.create_session("blocked")))
    creator.start()
    assert store.create_entered.wait(timeout=1.0)
    returned = Event()
    results: list[bool] = []

    def call_shutdown() -> None:
        results.append(controller.shutdown(timeout_seconds=0.02))
        returned.set()

    closer = Thread(target=call_shutdown)
    closer.start()
    completed_while_store_blocked = returned.wait(timeout=0.2)
    store.release_create.set()
    creator.join(timeout=1.0)
    closer.join(timeout=1.0)
    executor.release.set()

    assert completed_while_store_blocked is True
    assert results == [False]
    assert len(handles) == 1
    assert controller.shutdown(timeout_seconds=2.0) is True


def test_shutdown_timeout_includes_blocked_follow_up_admission(
    tmp_path: Path,
) -> None:
    class BlockingSubmitStore(SQLiteSessionStore):
        def __init__(self, workspace: Path) -> None:
            super().__init__(workspace)
            self.submit_entered = Event()
            self.release_submit = Event()

        def submit_message(
            self,
            session_id: str,
            message: str,
            *,
            model_id: str,
            selected_skills: tuple[SkillDescriptor, ...] = (),
            run_mode: RunMode = RunMode.MODIFY,
            budget_profile: BudgetProfile = BudgetProfile.STANDARD,
        ):  # type: ignore[no-untyped-def]
            self.submit_entered.set()
            assert self.release_submit.wait(timeout=2.0)
            return super().submit_message(
                session_id,
                message,
                model_id=model_id,
                selected_skills=selected_skills,
                run_mode=run_mode,
                budget_profile=budget_profile,
            )

    store = BlockingSubmitStore(tmp_path)
    store.initialize()
    first = store.create_session("first", model_id=MODEL_ID)
    store.finish_run(
        SessionRunResult(
            run_id=first.run.run_id,
            status=SessionRunStatus.FAILED,
            agent_status="failed",
            termination_reason="empty_model_response",
            audit_run_id=None,
            safe_summary=make_safe_run_summary(
                None,
                status="failed",
                termination_reason="empty_model_response",
            ),
            final_report=None,
        )
    )
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, store=store)
    handles: list[object] = []
    submitter = Thread(
        target=lambda: handles.append(
            controller.submit_message(first.session.session_id, "follow up")
        )
    )
    submitter.start()
    assert store.submit_entered.wait(timeout=1.0)
    returned = Event()
    results: list[bool] = []

    def call_shutdown() -> None:
        results.append(controller.shutdown(timeout_seconds=0.02))
        returned.set()

    closer = Thread(target=call_shutdown)
    closer.start()
    completed_while_store_blocked = returned.wait(timeout=0.2)
    store.release_submit.set()
    submitter.join(timeout=1.0)
    closer.join(timeout=1.0)
    executor.release.set()

    assert completed_while_store_blocked is True
    assert results == [False]
    assert len(handles) == 1
    assert controller.shutdown(timeout_seconds=2.0) is True


def test_shutdown_does_not_wait_for_inactive_cancel_lookup(tmp_path: Path) -> None:
    class BlockingLookupStore(SQLiteSessionStore):
        def __init__(self, workspace: Path) -> None:
            super().__init__(workspace)
            self.lookup_entered = Event()
            self.release_lookup = Event()

        def get_run(self, run_id: str) -> SessionRunRecord:
            self.lookup_entered.set()
            assert self.release_lookup.wait(timeout=2.0)
            return super().get_run(run_id)

    store = BlockingLookupStore(tmp_path)
    store.initialize()
    controller = make_controller(
        tmp_path,
        BlockingExecutor(tmp_path, (failed_outcome(),)),
        store=store,
    )
    error_codes: list[str] = []

    def cancel_missing() -> None:
        try:
            controller.cancel("f" * 32)
        except SessionControllerError as exc:
            error_codes.append(exc.code)

    caller = Thread(target=cancel_missing)
    caller.start()
    assert store.lookup_entered.wait(timeout=1.0)
    returned = Event()
    results: list[bool] = []

    def call_shutdown() -> None:
        results.append(controller.shutdown(timeout_seconds=0.02))
        returned.set()

    closer = Thread(target=call_shutdown)
    closer.start()
    completed_while_lookup_blocked = returned.wait(timeout=0.2)
    store.release_lookup.set()
    caller.join(timeout=1.0)
    closer.join(timeout=1.0)

    assert completed_while_lookup_blocked is True
    assert results == [True]
    assert error_codes == ["run_not_found"]


class FailingCancellationStore(SQLiteSessionStore):
    def __init__(self, workspace: Path) -> None:
        super().__init__(workspace)
        self.cancellation_write_entered = Event()
        self.release_cancellation_write = Event()

    def request_cancellation(self, run_id: str):  # type: ignore[no-untyped-def]
        del run_id
        self.cancellation_write_entered.set()
        assert self.release_cancellation_write.wait(timeout=2.0)
        raise SessionStoreError("storage_unavailable")


def test_cancel_token_linearizes_before_durable_transition_failure(
    tmp_path: Path,
) -> None:
    store = FailingCancellationStore(tmp_path)
    store.initialize()

    class CancellationProbeExecutor:
        workspace = tmp_path.resolve(strict=True)

        def __init__(self) -> None:
            self.started = Event()
            self.allow_boundary_check = Event()
            self.cancel_observed = Event()
            self.release = Event()
            self.next_operation_started = False

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            self.started.set()
            assert self.allow_boundary_check.wait(timeout=2.0)
            if handlers["cancellation_requested"]():  # type: ignore[operator]
                self.cancel_observed.set()
            else:
                self.next_operation_started = True
            assert self.release.wait(timeout=2.0)
            return interrupted_outcome()

    executor = CancellationProbeExecutor()
    controller = make_controller(tmp_path, executor, store=store)
    handle = controller.create_session("cancel at boundary")
    assert executor.started.wait(timeout=1.0)
    error_codes: list[str] = []

    def request_cancel() -> None:
        try:
            controller.cancel(handle.run_id)
        except SessionControllerError as exc:
            error_codes.append(exc.code)

    thread = Thread(target=request_cancel)
    thread.start()
    executor.allow_boundary_check.set()
    assert store.cancellation_write_entered.wait(timeout=1.0)
    assert executor.next_operation_started is False
    store.release_cancellation_write.set()
    assert executor.cancel_observed.wait(timeout=1.0)
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert error_codes == ["storage_unavailable"]
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    with pytest.raises(SessionControllerError) as captured:
        controller.create_session("degraded")
    assert captured.value.code == "controller_degraded"
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_cancel_queued_run_waits_for_durable_start_without_degrading(
    tmp_path: Path,
) -> None:
    worker_gate = Event()

    class GatedWorker:
        daemon = False

        def __init__(self, target: object, name: str) -> None:
            self.name = name
            self._target = target
            self._thread = Thread(target=self._run, name=name, daemon=False)

        def _run(self) -> None:
            assert worker_gate.wait(timeout=2.0)
            self._target()  # type: ignore[operator]

        def start(self) -> None:
            self._thread.start()

        def join(self, timeout: float | None = None) -> None:
            self._thread.join(timeout)

        def is_alive(self) -> bool:
            return self._thread.is_alive()

    class CancellationAwareExecutor:
        workspace = tmp_path.resolve(strict=True)
        default_model_id = MODEL_ID

        def __init__(self) -> None:
            self.calls = 0

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            self.calls += 1
            if self.calls == 1:
                cancellation_requested = handlers["cancellation_requested"]
                assert callable(cancellation_requested)
                assert cancellation_requested() is True
                return interrupted_outcome()
            return failed_outcome()

    executor = CancellationAwareExecutor()
    controller = make_controller(
        tmp_path,
        executor,
        thread_factory=lambda target, name: GatedWorker(target, name),
    )
    handle = controller.create_session("cancel before start")
    assert controller.get_session(handle.session_id).runs[0].status \
        is SessionRunStatus.QUEUED
    cancel_returned = Event()
    results: list[CancellationResult] = []
    error_codes: list[str] = []

    def request_cancel() -> None:
        try:
            results.append(controller.cancel(handle.run_id))
        except SessionControllerError as exc:
            error_codes.append(exc.code)
        finally:
            cancel_returned.set()

    caller = Thread(target=request_cancel)
    caller.start()
    returned_before_start = cancel_returned.wait(timeout=0.1)
    worker_gate.set()
    caller.join(timeout=1.0)
    terminal = controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    try:
        assert returned_before_start is False
        assert results == [CancellationResult.REQUESTED]
        assert error_codes == []
        assert terminal.status is SessionRunStatus.INTERRUPTED
        events = controller.get_session(handle.session_id).events
        assert sum(
            event.kind is PersistedSessionEventKind.CANCELLATION_REQUESTED
            for event in events
        ) == 1
        second = controller.submit_message(handle.session_id, "still usable")
        assert controller.wait_for_run(second.run_id, timeout_seconds=2.0).status \
            is SessionRunStatus.FAILED
    finally:
        worker_gate.set()
        assert controller.shutdown(timeout_seconds=2.0) is True


def test_cancel_waits_for_started_publication_and_preserves_live_order(
    tmp_path: Path,
) -> None:
    class StartedBarrierHub(SessionEventHub):
        def __init__(self) -> None:
            super().__init__()
            self.started_publish_entered = Event()
            self.release_started_publish = Event()

        def publish(self, kind: SessionUpdateKind, data: object):  # type: ignore[no-untyped-def]
            if kind is SessionUpdateKind.RUN_STARTED:
                self.started_publish_entered.set()
                assert self.release_started_publish.wait(timeout=2.0)
            return super().publish(kind, data)  # type: ignore[arg-type]

    class CancellationAwareExecutor:
        workspace = tmp_path.resolve(strict=True)
        default_model_id = MODEL_ID

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            cancellation_requested = handlers["cancellation_requested"]
            assert callable(cancellation_requested)
            assert cancellation_requested() is True
            return interrupted_outcome()

    store = SQLiteSessionStore(tmp_path)
    store.initialize()
    lease = WorkspaceSessionLease.acquire(tmp_path)
    event_hub = StartedBarrierHub()
    controller = SessionController(
        store=store,
        lease=lease,
        executor=CancellationAwareExecutor(),
        model_catalog=RecordingModelCatalog(),
        event_hub=event_hub,
    )
    handle = controller.create_session("cancel during started publication")
    assert event_hub.started_publish_entered.wait(timeout=1.0)
    cancel_returned = Event()
    results: list[CancellationResult] = []

    def request_cancel() -> None:
        results.append(controller.cancel(handle.run_id))
        cancel_returned.set()

    caller = Thread(target=request_cancel)
    caller.start()
    assert cancel_returned.wait(timeout=0.1) is False
    event_hub.release_started_publish.set()
    caller.join(timeout=1.0)
    assert not caller.is_alive()
    assert results == [CancellationResult.REQUESTED]
    assert controller.wait_for_run(handle.run_id, timeout_seconds=2.0).status \
        is SessionRunStatus.INTERRUPTED

    live_kinds = [
        update.kind for update in controller.read_updates(handle.run_id).events
    ]
    assert live_kinds == [
        SessionUpdateKind.RUN_QUEUED,
        SessionUpdateKind.RUN_STARTED,
        SessionUpdateKind.RUN_CANCELLING,
        SessionUpdateKind.RUN_FINISHED,
    ]
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_cancel_live_event_precedes_finish_after_durable_commit(
    tmp_path: Path,
) -> None:
    class CommitBarrierStore(SQLiteSessionStore):
        def __init__(self, workspace: Path) -> None:
            super().__init__(workspace)
            self.cancel_committed = Event()
            self.release_cancel_return = Event()
            self.finish_entered = Event()

        def request_cancellation(self, run_id: str) -> SessionRunRecord:
            cancelling = super().request_cancellation(run_id)
            self.cancel_committed.set()
            assert self.release_cancel_return.wait(timeout=2.0)
            return cancelling

        def finish_run(self, result: SessionRunResult) -> SessionRunRecord:
            self.finish_entered.set()
            return super().finish_run(result)

    class CommitAwareExecutor:
        workspace = tmp_path.resolve(strict=True)

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            self.started.set()
            cancellation_requested = handlers["cancellation_requested"]
            assert callable(cancellation_requested)
            while not cancellation_requested():
                self.cancel_wait.wait(0.001)
            return interrupted_outcome()

        def __init__(self) -> None:
            self.cancel_wait = Event()
            self.started = Event()

    store = CommitBarrierStore(tmp_path)
    store.initialize()
    executor = CommitAwareExecutor()
    controller = make_controller(tmp_path, executor, store=store)
    handle = controller.create_session("ordered cancel")
    assert executor.started.wait(timeout=1.0)
    results: list[CancellationResult] = []
    caller = Thread(target=lambda: results.append(controller.cancel(handle.run_id)))
    caller.start()
    assert store.cancel_committed.wait(timeout=1.0)
    finish_before_cancel_return = store.finish_entered.wait(timeout=0.2)
    store.release_cancel_return.set()
    caller.join(timeout=1.0)
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)

    live_kinds = [
        event.kind for event in controller.read_updates(handle.run_id).events
    ]
    assert finish_before_cancel_return is False
    assert results == [CancellationResult.REQUESTED]
    assert live_kinds.index(SessionUpdateKind.RUN_CANCELLING) \
        < live_kinds.index(SessionUpdateKind.RUN_FINISHED)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_system_exit_after_cancellation_commit_does_not_deadlock_or_lose_live_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = Event()
    exceptions: list[type[BaseException]] = []

    def hook(args: threading.ExceptHookArgs) -> None:
        exceptions.append(args.exc_type)
        observed.set()

    monkeypatch.setattr(threading, "excepthook", hook)

    class ExitAfterCommitStore(SQLiteSessionStore):
        def request_cancellation(self, run_id: str) -> SessionRunRecord:
            super().request_cancellation(run_id)
            raise SystemExit(17)

    class CancellationAwareExecutor:
        workspace = tmp_path.resolve(strict=True)
        default_model_id = MODEL_ID

        def __init__(self) -> None:
            self.started = Event()

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            self.started.set()
            cancellation_requested = handlers["cancellation_requested"]
            assert callable(cancellation_requested)
            while not cancellation_requested():
                Event().wait(0.001)
            return interrupted_outcome()

    store = ExitAfterCommitStore(tmp_path)
    store.initialize()
    executor = CancellationAwareExecutor()
    controller = make_controller(tmp_path, executor, store=store)
    handle = controller.create_session("cancel then exit")
    assert executor.started.wait(timeout=1.0)
    error_codes: list[str] = []

    def request_cancel() -> None:
        try:
            controller.cancel(handle.run_id)
        except SessionControllerError as exc:
            error_codes.append(exc.code)

    caller = Thread(target=request_cancel)
    caller.start()
    caller.join(timeout=1.0)
    assert not caller.is_alive()
    assert observed.wait(timeout=1.0)
    assert error_codes == ["controller_error"]
    assert exceptions == [SystemExit]

    current = controller.wait_for_run(handle.run_id, timeout_seconds=1.0)
    assert current.status is SessionRunStatus.CANCELLING
    live_kinds = [
        update.kind for update in controller.read_updates(handle.run_id).events
    ]
    assert SessionUpdateKind.RUN_CANCELLING in live_kinds
    assert SessionUpdateKind.RUN_FINISHED not in live_kinds
    durable_kinds = [
        event.kind for event in controller.get_session(handle.session_id).events
    ]
    assert durable_kinds.count(PersistedSessionEventKind.CANCELLATION_REQUESTED) == 1
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_cancellation_live_event_is_not_duplicated_after_publish_system_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = Event()

    def hook(args: threading.ExceptHookArgs) -> None:
        assert args.exc_type is SystemExit
        observed.set()

    monkeypatch.setattr(threading, "excepthook", hook)

    class ExitAfterCancellingPublishHub(SessionEventHub):
        def __init__(self) -> None:
            super().__init__()
            self.raised = False

        def publish(self, kind: SessionUpdateKind, data: object):  # type: ignore[no-untyped-def]
            update = super().publish(kind, data)  # type: ignore[arg-type]
            if kind is SessionUpdateKind.RUN_CANCELLING and not self.raised:
                self.raised = True
                raise SystemExit(17)
            return update

    class CancellationAwareExecutor:
        workspace = tmp_path.resolve(strict=True)
        default_model_id = MODEL_ID

        def __init__(self) -> None:
            self.started = Event()

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            self.started.set()
            cancellation_requested = handlers["cancellation_requested"]
            assert callable(cancellation_requested)
            while not cancellation_requested():
                Event().wait(0.001)
            return interrupted_outcome()

    store = SQLiteSessionStore(tmp_path)
    store.initialize()
    lease = WorkspaceSessionLease.acquire(tmp_path)
    event_hub = ExitAfterCancellingPublishHub()
    executor = CancellationAwareExecutor()
    controller = SessionController(
        store=store,
        lease=lease,
        executor=executor,
        model_catalog=RecordingModelCatalog(),
        event_hub=event_hub,
    )
    handle = controller.create_session("cancel publish exits")
    assert executor.started.wait(timeout=1.0)

    with pytest.raises(SessionControllerError) as captured:
        controller.cancel(handle.run_id)
    assert captured.value.code == "controller_error"
    assert observed.wait(timeout=1.0)

    live_kinds = [
        update.kind for update in controller.read_updates(handle.run_id).events
    ]
    assert live_kinds.count(SessionUpdateKind.RUN_CANCELLING) == 1
    durable_kinds = [
        event.kind for event in controller.get_session(handle.session_id).events
    ]
    assert durable_kinds.count(PersistedSessionEventKind.CANCELLATION_REQUESTED) == 1
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_thread_start_failure_converges_queued_row(tmp_path: Path) -> None:
    class StartFailingThread:
        daemon = False
        name = "start-failing"

        def start(self) -> None:
            raise OSError("private start detail")

        def join(self, timeout: float | None = None) -> None:
            del timeout

        def is_alive(self) -> bool:
            return False

    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(
        tmp_path,
        executor,
        thread_factory=lambda target, name: StartFailingThread(),
    )
    with pytest.raises(SessionControllerError) as captured:
        controller.create_session("cannot start")
    assert captured.value.code == "thread_start_failed"
    run = controller.list_sessions()[0]
    terminal = controller.get_session(run.session_id).runs[0]
    assert terminal.status is SessionRunStatus.FAILED
    assert terminal.termination_reason == "controller_error"
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_thread_factory_failure_converges_queued_row(tmp_path: Path) -> None:
    def failing_factory(target: object, name: str) -> Thread:
        del target, name
        raise OSError("private factory detail")

    controller = make_controller(
        tmp_path,
        BlockingExecutor(tmp_path, (failed_outcome(),)),
        thread_factory=failing_factory,
    )

    with pytest.raises(SessionControllerError) as captured:
        controller.create_session("factory fails")

    assert captured.value.code == "thread_start_failed"
    session = controller.list_sessions()[0]
    run = controller.get_session(session.session_id).runs[0]
    assert run.status is SessionRunStatus.FAILED
    assert run.termination_reason == "controller_error"
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_initial_live_publish_failure_converges_queued_row(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path)
    store.initialize()
    lease = WorkspaceSessionLease.acquire(tmp_path)
    controller = SessionController(
        store=store,
        lease=lease,
        executor=BlockingExecutor(tmp_path, (failed_outcome(),)),
        model_catalog=RecordingModelCatalog(),
        event_hub=SessionEventHub(max_bytes=1),
    )

    with pytest.raises(SessionControllerError) as captured:
        controller.create_session("publish fails")

    assert captured.value.code == "thread_start_failed"
    session = controller.list_sessions()[0]
    run = controller.get_session(session.session_id).runs[0]
    assert run.status is SessionRunStatus.FAILED
    assert run.termination_reason == "controller_error"
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_thread_factory_failure_completes_pending_cancellation_phase(
    tmp_path: Path,
) -> None:
    factory_entered = Event()
    release_factory = Event()

    def failing_factory(target: object, name: str) -> object:
        del target, name
        factory_entered.set()
        assert release_factory.wait(timeout=2.0)
        raise OSError("private factory detail")

    controller = make_controller(
        tmp_path,
        BlockingExecutor(tmp_path, (failed_outcome(),)),
        thread_factory=failing_factory,
    )
    create_errors: list[str] = []

    def create() -> None:
        try:
            controller.create_session("factory race")
        except SessionControllerError as exc:
            create_errors.append(exc.code)

    creator = Thread(target=create)
    creator.start()
    assert factory_entered.wait(timeout=1.0)
    pending = controller._active  # type: ignore[attr-defined]
    assert pending is not None
    session_id = pending.request.session_id
    run_id = pending.request.run_id
    cancel_errors: list[str] = []
    cancel_returned = Event()

    def request_cancel() -> None:
        try:
            controller.cancel(run_id)
        except SessionControllerError as exc:
            cancel_errors.append(exc.code)
        finally:
            cancel_returned.set()

    caller = Thread(target=request_cancel)
    caller.start()
    assert cancel_returned.wait(timeout=0.1) is False
    release_factory.set()
    creator.join(timeout=1.0)
    caller.join(timeout=1.0)
    cancel_stuck = caller.is_alive()
    if cancel_stuck:
        pending.cancellation_done.set()
        caller.join(timeout=1.0)

    assert not creator.is_alive()
    assert cancel_stuck is False
    assert create_errors == ["thread_start_failed"]
    assert cancel_errors == ["thread_start_failed"]
    assert controller.get_session(session_id).runs[0].status \
        is SessionRunStatus.FAILED
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_daemon_worker_rejection_converges_queued_row(tmp_path: Path) -> None:
    started = Event()

    def daemon_factory(target: object, name: str) -> Thread:
        return Thread(
            target=lambda: started.set(),
            name=name,
            daemon=True,
        )

    controller = make_controller(
        tmp_path,
        BlockingExecutor(tmp_path, (failed_outcome(),)),
        thread_factory=daemon_factory,
    )

    with pytest.raises(SessionControllerError) as captured:
        controller.create_session("daemon rejected")

    assert captured.value.code == "thread_start_failed"
    assert started.is_set() is False
    session = controller.list_sessions()[0]
    run = controller.get_session(session.session_id).runs[0]
    assert run.status is SessionRunStatus.FAILED
    assert run.termination_reason == "controller_error"
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_finalization_failure_leaves_recoverable_incomplete_row(
    tmp_path: Path,
) -> None:
    class FinalizationFailingStore(SQLiteSessionStore):
        def finish_run(self, result: object):  # type: ignore[no-untyped-def]
            del result
            raise SessionStoreError("storage_unavailable")

    store = FinalizationFailingStore(tmp_path)
    store.initialize()
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, store=store)
    handle = controller.create_session("finish failure")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    incomplete = controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert incomplete.status is SessionRunStatus.RUNNING
    assert controller.shutdown(timeout_seconds=1.0) is True
    recovered = SQLiteSessionStore(tmp_path)
    recovered.initialize()
    rows = recovered.recover_incomplete_runs()
    assert [row.status for row in rows] == [SessionRunStatus.INTERRUPTED]


def test_cancel_after_terminal_commit_does_not_degrade_controller(
    tmp_path: Path,
) -> None:
    class FinishCommitBarrierStore(SQLiteSessionStore):
        def __init__(self, workspace: Path) -> None:
            super().__init__(workspace)
            self.finish_committed = Event()
            self.release_finish_return = Event()

        def finish_run(self, result: SessionRunResult) -> SessionRunRecord:
            terminal = super().finish_run(result)
            self.finish_committed.set()
            assert self.release_finish_return.wait(timeout=2.0)
            return terminal

    store = FinishCommitBarrierStore(tmp_path)
    store.initialize()
    executor = BlockingExecutor(
        tmp_path,
        (failed_outcome("first_error"), failed_outcome("second_error")),
    )
    controller = make_controller(tmp_path, executor, store=store)
    first = controller.create_session("first")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    assert store.finish_committed.wait(timeout=1.0)

    assert controller.cancel(first.run_id) is CancellationResult.ALREADY_FINISHED

    store.release_finish_return.set()
    assert (
        controller.wait_for_run(first.run_id, timeout_seconds=2.0).status
        is SessionRunStatus.FAILED
    )
    second = controller.submit_message(first.session_id, "second")
    assert (
        controller.wait_for_run(second.run_id, timeout_seconds=2.0).status
        is SessionRunStatus.FAILED
    )
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_shutdown_after_finalization_admission_does_not_publish_cancelling(
    tmp_path: Path,
) -> None:
    class PreFinishBarrierStore(SQLiteSessionStore):
        def __init__(self, workspace: Path) -> None:
            super().__init__(workspace)
            self.finish_entered = Event()
            self.release_finish = Event()

        def finish_run(self, result: SessionRunResult) -> SessionRunRecord:
            self.finish_entered.set()
            assert self.release_finish.wait(timeout=2.0)
            return super().finish_run(result)

    store = PreFinishBarrierStore(tmp_path)
    store.initialize()
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, store=store)
    handle = controller.create_session("finish atomically")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    assert store.finish_entered.wait(timeout=1.0)

    assert controller.shutdown(timeout_seconds=0.01) is False
    store.release_finish.set()
    assert controller.shutdown(timeout_seconds=2.0) is True

    live_kinds = [
        event.kind for event in controller.read_updates(handle.run_id).events
    ]
    durable_kinds = [
        event.kind
        for event in controller.get_session(handle.session_id).events
    ]
    assert SessionUpdateKind.RUN_CANCELLING not in live_kinds
    assert PersistedSessionEventKind.CANCELLATION_REQUESTED not in durable_kinds


def test_open_recovers_before_accepting_new_work(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path)
    store.initialize()
    submission = store.create_session("left queued", model_id=MODEL_ID)
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = SessionController.open(
        tmp_path,
        executor,
        model_catalog=RecordingModelCatalog(),
    )
    recovered = controller.wait_for_run(submission.run.run_id, timeout_seconds=None)
    assert recovered.status is SessionRunStatus.INTERRUPTED
    assert controller.get_session(submission.session.session_id).session.status is SessionStatus.IDLE
    assert controller.shutdown(timeout_seconds=1.0) is True


@pytest.mark.parametrize("timeout", [True, 0, -1, math.nan, math.inf])
def test_invalid_shutdown_timeout_is_rejected(
    tmp_path: Path,
    timeout: object,
) -> None:
    controller = make_controller(
        tmp_path,
        BlockingExecutor(tmp_path, (failed_outcome(),)),
    )
    with pytest.raises(SessionControllerError):
        controller.shutdown(timeout_seconds=timeout)  # type: ignore[arg-type]
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_system_exit_reaches_threading_excepthook_after_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = Event()
    exceptions: list[type[BaseException]] = []

    def hook(args: threading.ExceptHookArgs) -> None:
        exceptions.append(args.exc_type)
        observed.set()

    monkeypatch.setattr(threading, "excepthook", hook)

    class ExitingExecutor:
        workspace = tmp_path.resolve(strict=True)

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request, handlers
            raise SystemExit(17)

    controller = make_controller(tmp_path, ExitingExecutor())
    handle = controller.create_session("exit")
    assert observed.wait(timeout=1.0)
    incomplete = controller.wait_for_run(handle.run_id, timeout_seconds=1.0)
    assert incomplete.status is SessionRunStatus.RUNNING
    assert exceptions == [SystemExit]
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_system_exit_before_observing_cancel_completes_caller_with_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = Event()
    exceptions: list[type[BaseException]] = []

    def hook(args: threading.ExceptHookArgs) -> None:
        exceptions.append(args.exc_type)
        observed.set()

    monkeypatch.setattr(threading, "excepthook", hook)

    class ExitBeforeCancellationProbeExecutor:
        workspace = tmp_path.resolve(strict=True)

        def __init__(self) -> None:
            self.started = Event()
            self.release = Event()

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request, handlers
            self.started.set()
            assert self.release.wait(timeout=2.0)
            raise SystemExit(17)

    executor = ExitBeforeCancellationProbeExecutor()
    controller = make_controller(tmp_path, executor)
    handle = controller.create_session("cancel before exit")
    assert executor.started.wait(timeout=1.0)
    cancel_errors: list[str] = []
    cancel_results: list[CancellationResult] = []
    cancel_entered = Event()
    cancel_returned = Event()

    def request_cancel() -> None:
        cancel_entered.set()
        try:
            cancel_results.append(controller.cancel(handle.run_id))
        except SessionControllerError as exc:
            cancel_errors.append(exc.code)
        finally:
            cancel_returned.set()

    caller = Thread(target=request_cancel)
    caller.start()
    assert cancel_entered.wait(timeout=1.0)
    assert cancel_returned.wait(timeout=0.1) is False
    executor.release.set()
    caller.join(timeout=1.0)

    assert not caller.is_alive()
    assert observed.wait(timeout=1.0)
    assert exceptions == [SystemExit]
    assert cancel_results == []
    assert cancel_errors == ["controller_error"]
    assert controller.wait_for_run(handle.run_id, timeout_seconds=1.0).status \
        is SessionRunStatus.RUNNING
    assert controller.shutdown(timeout_seconds=1.0) is True

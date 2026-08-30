from __future__ import annotations

from pathlib import Path
import math
import threading
from threading import Condition, Event, Thread

import pytest

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
from coding_agent.session_events import SessionEventHub, SessionUpdateKind
from coding_agent.session_runtime import SessionRunOutcome, SessionRunRequest
from coding_agent.session_store import SQLiteSessionStore, WorkspaceSessionLease
from coding_agent.skills import SkillCatalog, SkillDescriptor
from coding_agent.streaming import ModelStreamEvent, ModelStreamEventKind


class BlockingExecutor:
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
) -> SessionController:
    lease = WorkspaceSessionLease.acquire(tmp_path)
    selected_store = store or SQLiteSessionStore(tmp_path)
    selected_store.initialize()
    selected_store.recover_incomplete_runs()
    selected_catalog = skill_catalog or SkillCatalog(
        user_root=tmp_path / "user-skills",
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    kwargs: dict[str, object] = {}
    if thread_factory is not None:
        kwargs["thread_factory"] = thread_factory
    return SessionController(
        store=selected_store,
        lease=lease,
        executor=executor,  # type: ignore[arg-type]
        event_hub=SessionEventHub(),
        skill_catalog=selected_catalog,
        **kwargs,  # type: ignore[arg-type]
    )


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
    submission = store.create_session("must remain queued")
    executor = BlockingExecutor(second, (failed_outcome(),))

    with pytest.raises(SessionControllerError) as captured:
        SessionController.open(first, executor)

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


def _safe_tool_completed_event() -> RunEvent:
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
            "status": "ok",
            "safe_error_code": None,
            "output_chars": 99,
            "exit_code": None,
            "timed_out": False,
            "truncated": False,
            "duration_ms": 2,
            "changed_paths": [],
            "mutation_index_before": 0,
            "mutation_index_after": 0,
            "executed": True,
        },
    )


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
            selected_skills: tuple[SkillDescriptor, ...] = (),
        ):  # type: ignore[no-untyped-def]
            self.create_entered.set()
            assert self.release_create.wait(timeout=2.0)
            return super().create_session(
                message,
                selected_skills=selected_skills,
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
            selected_skills: tuple[SkillDescriptor, ...] = (),
        ):  # type: ignore[no-untyped-def]
            self.submit_entered.set()
            assert self.release_submit.wait(timeout=2.0)
            return super().submit_message(
                session_id,
                message,
                selected_skills=selected_skills,
            )

    store = BlockingSubmitStore(tmp_path)
    store.initialize()
    first = store.create_session("first")
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
    submission = store.create_session("left queued")
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = SessionController.open(tmp_path, executor)
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

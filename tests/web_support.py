from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import socket
from threading import Event, Thread

import httpx
import uvicorn

from coding_agent.session import (
    PersistedSessionEventKind,
    SessionControllerError,
    SessionEvent,
    SessionRecord,
    SessionRunRecord,
    SessionRunStatus,
    SessionStatus,
)
from coding_agent.session_controller import (
    CancellationResult,
    RunHandle,
    SessionView,
)
from coding_agent.session_events import (
    SESSION_UPDATE_SCHEMA_VERSION,
    SessionUpdate,
    SessionUpdateBatch,
    SessionUpdateKind,
)
from coding_agent.skills import (
    SkillCatalogDiagnostic,
    SkillCatalogView,
    SkillDescriptor,
    SkillSource,
)


SESSION_ID = "1" * 32
RUN_ID = "2" * 32
SECOND_RUN_ID = "3" * 32
SECOND_SESSION_ID = "4" * 32
TIMESTAMP = "2026-08-30T00:00:00.000000Z"


def make_session_record(
    *,
    session_id: str = SESSION_ID,
    title: str = "Repair tests",
    status: SessionStatus = SessionStatus.IDLE,
    last_run_id: str | None = RUN_ID,
) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        title=title,
        status=status,
        created_at_utc=TIMESTAMP,
        updated_at_utc=TIMESTAMP,
        last_run_id=last_run_id,
        next_sequence=2,
    )


def make_run_record(
    *,
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    status: SessionRunStatus = SessionRunStatus.QUEUED,
) -> SessionRunRecord:
    terminal = status in {
        SessionRunStatus.SUCCEEDED,
        SessionRunStatus.FAILED,
        SessionRunStatus.INTERRUPTED,
    }
    active = status in {SessionRunStatus.RUNNING, SessionRunStatus.CANCELLING}
    return SessionRunRecord(
        run_id=run_id,
        session_id=session_id,
        ordinal=1 if run_id == RUN_ID else 2,
        status=status,
        user_event_sequence=1,
        started_at_utc=TIMESTAMP if active or terminal else None,
        finished_at_utc=TIMESTAMP if terminal else None,
        agent_status="success" if status is SessionRunStatus.SUCCEEDED else None,
        termination_reason="model_completed" if terminal else None,
        audit_run_id=None,
        final_report=None,
    )


def make_session_event(
    *,
    session_id: str = SESSION_ID,
    run_id: str = RUN_ID,
    sequence: int = 1,
) -> SessionEvent:
    return SessionEvent(
        session_id=session_id,
        run_id=run_id,
        sequence=sequence,
        kind=PersistedSessionEventKind.USER_MESSAGE,
        created_at_utc=TIMESTAMP,
        data={"content": "repair tests"},
    )


def make_session_view() -> SessionView:
    return SessionView(
        session=make_session_record(),
        runs=(make_run_record(),),
        events=(make_session_event(),),
    )


def make_skill_view() -> SkillCatalogView:
    return SkillCatalogView(
        skills=(
            SkillDescriptor(
                skill_id="python-testing",
                name="Python testing",
                description="Use focused pytest workflows.",
                source=SkillSource.WORKSPACE,
                sha256="a" * 64,
                char_count=128,
            ),
            SkillDescriptor(
                skill_id="code-review",
                name="Code review",
                description="Review changes before completion.",
                source=SkillSource.USER,
                sha256="b" * 64,
                char_count=96,
            ),
        ),
        diagnostics=(
            SkillCatalogDiagnostic(
                code="invalid_skill_metadata",
                source=SkillSource.WORKSPACE,
                entry_name="broken-skill",
            ),
        ),
        usable=True,
    )


def make_update(
    sequence: int,
    kind: SessionUpdateKind,
    data: dict[str, object],
) -> SessionUpdate:
    return SessionUpdate(
        schema_version=SESSION_UPDATE_SCHEMA_VERSION,
        session_id=SESSION_ID,
        run_id=RUN_ID,
        sequence=sequence,
        timestamp_utc=TIMESTAMP,
        kind=kind,
        data=data,  # type: ignore[arg-type]
    )


@dataclass
class RecordingController:
    sessions: tuple[SessionRecord, ...] = ()
    session_view: SessionView | None = None
    skill_view: SkillCatalogView = field(
        default_factory=lambda: SkillCatalogView((), (), True)
    )
    selected_skill_ids: tuple[str, ...] = ()
    create_handle: RunHandle = field(
        default_factory=lambda: RunHandle(SESSION_ID, RUN_ID)
    )
    follow_up_handle: RunHandle = field(
        default_factory=lambda: RunHandle(SESSION_ID, SECOND_RUN_ID)
    )
    cancellation_result: CancellationResult = CancellationResult.REQUESTED
    update_batches: deque[SessionUpdateBatch] = field(default_factory=deque)
    errors: dict[str, RuntimeError] = field(default_factory=dict)
    calls: list[tuple[object, ...]] = field(default_factory=list)
    private_skill_instruction: str = field(
        default="PRIVATE_SKILL_BODY_SENTINEL",
        repr=False,
    )

    def _record(self, name: str, *args: object) -> None:
        self.calls.append((name, *args))
        error = self.errors.get(name)
        if error is not None:
            raise error

    def list_sessions(self, *, limit: int = 50) -> tuple[SessionRecord, ...]:
        self._record("list_sessions", limit)
        return self.sessions

    def create_session(
        self, message: str, *, skill_ids: tuple[str, ...] = ()
    ) -> RunHandle:
        self._record("create_session", message, skill_ids)
        return self.create_handle

    def get_session(self, session_id: str) -> SessionView:
        self._record("get_session", session_id)
        if self.session_view is None:
            raise SessionControllerError("session_not_found")
        return self.session_view

    def submit_message(self, session_id: str, message: str) -> RunHandle:
        self._record("submit_message", session_id, message)
        return self.follow_up_handle

    def list_skills(self) -> SkillCatalogView:
        self._record("list_skills")
        return self.skill_view

    def get_session_skills(self, session_id: str) -> tuple[str, ...]:
        self._record("get_session_skills", session_id)
        return self.selected_skill_ids

    def set_session_skills(
        self, session_id: str, skill_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        self._record("set_session_skills", session_id, skill_ids)
        self.selected_skill_ids = skill_ids
        return skill_ids

    def cancel(self, run_id: str) -> CancellationResult:
        self._record("cancel", run_id)
        return self.cancellation_result

    def read_updates(
        self, run_id: str, *, after_sequence: int = 0
    ) -> SessionUpdateBatch:
        self._record("read_updates", run_id, after_sequence)
        if self.update_batches:
            return self.update_batches.popleft()
        return SessionUpdateBatch((), after_sequence, False)

    def wait_for_updates(
        self,
        run_id: str,
        *,
        after_sequence: int,
        timeout_seconds: float,
    ) -> SessionUpdateBatch:
        self._record("wait_for_updates", run_id, after_sequence, timeout_seconds)
        if self.update_batches:
            return self.update_batches.popleft()
        return SessionUpdateBatch((), after_sequence, False)


async def request(
    app: object,
    method: str,
    path: str,
    *,
    json: object = None,
    content: bytes | str | None = None,
    headers: httpx.Headers | dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:43123",
    ) as client:
        return await client.request(
            method,
            path,
            json=json,
            content=content,
            headers=headers,
        )


def auth_headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer fixed-test-token",
        "Origin": "http://127.0.0.1:43123",
    }


@contextmanager
def running_uvicorn_app(
    app_factory: Callable[[int], object],
) -> Iterator[str]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = int(listener.getsockname()[1])
    ready = Event()
    failures: list[BaseException] = []

    class ReadyServer(uvicorn.Server):
        async def startup(self, sockets=None) -> None:
            await super().startup(sockets=sockets)
            ready.set()

    config = uvicorn.Config(
        app_factory(port),
        host="127.0.0.1",
        port=port,
        loop="asyncio",
        http="h11",
        lifespan="off",
        access_log=False,
        log_level="critical",
        server_header=False,
        date_header=False,
        proxy_headers=False,
        workers=1,
        timeout_graceful_shutdown=2,
    )
    server = ReadyServer(config)

    def serve() -> None:
        try:
            server.run(sockets=[listener])
        except BaseException as error:
            failures.append(error)
            ready.set()

    thread = Thread(target=serve, name="test-uvicorn", daemon=False)
    thread.start()
    if not ready.wait(timeout=5.0) or failures or not server.started:
        server.should_exit = True
        listener.close()
        thread.join(timeout=5.0)
        raise AssertionError("test Uvicorn server failed to start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)
        if thread.is_alive():
            server.force_exit = True
            listener.close()
            thread.join(timeout=5.0)
        else:
            listener.close()
        assert not thread.is_alive(), "test Uvicorn server failed to stop"
        assert failures == [], f"test Uvicorn thread failed: {type(failures[0]).__name__ if failures else ''}"

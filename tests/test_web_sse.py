from __future__ import annotations

import asyncio
from collections import deque
from threading import Barrier, Condition, Event, Thread
from time import monotonic

import httpx
import pytest

from coding_agent.session_events import (
    SESSION_UPDATE_SCHEMA_VERSION,
    SessionUpdate,
    SessionUpdateBatch,
    SessionUpdateKind,
)
from coding_agent.web import create_web_app
from coding_agent.web_auth import WebAccessPolicy
from tests.web_support import (
    RUN_ID,
    RecordingController,
    SESSION_ID,
    TIMESTAMP,
    auth_headers,
    make_update,
    request,
    running_uvicorn_app,
)


def make_app(controller: RecordingController):
    return create_web_app(
        controller=controller,
        access_policy=WebAccessPolicy(token="fixed-test-token", port=43123),
    )


def test_sse_terminal_replay_uses_exact_ordered_frames() -> None:
    started = make_update(
        1,
        SessionUpdateKind.RUN_STARTED,
        {"status": "running"},
    )
    finished = make_update(
        2,
        SessionUpdateKind.RUN_FINISHED,
        {"status": "succeeded", "agent_status": "success"},
    )
    controller = RecordingController(
        update_batches=deque(
            [SessionUpdateBatch((started, finished), 2, False)]
        )
    )
    response = asyncio.run(
        request(
            make_app(controller),
            "GET",
            f"/api/v1/runs/{RUN_ID}/events",
            headers={**auth_headers(), "Accept": "text/event-stream"},
        )
    )

    expected = (
        f"id: 1\nevent: run_started\ndata: {started.to_json()}\n\n"
        f"id: 2\nevent: run_finished\ndata: {finished.to_json()}\n\n"
    )
    assert response.status_code == 200
    assert response.text == expected
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert controller.calls == [("read_updates", RUN_ID, 0)]


def test_sse_answered_terminal_preserves_exact_v2_status_pair() -> None:
    finished = make_update(
        1,
        SessionUpdateKind.RUN_FINISHED,
        {"status": "succeeded", "agent_status": "answered"},
    )
    controller = RecordingController(
        update_batches=deque(
            [SessionUpdateBatch((finished,), 1, False)]
        )
    )
    response = asyncio.run(
        request(
            make_app(controller),
            "GET",
            f"/api/v1/runs/{RUN_ID}/events",
            headers={**auth_headers(), "Accept": "text/event-stream"},
        )
    )

    assert response.status_code == 200
    assert response.text == (
        f"id: 1\nevent: run_finished\ndata: {finished.to_json()}\n\n"
    )
    assert finished.to_dict()["data"] == {
        "status": "succeeded",
        "agent_status": "answered",
    }


def test_sse_last_event_id_replays_only_newer_terminal_event() -> None:
    finished = make_update(
        2,
        SessionUpdateKind.RUN_FINISHED,
        {"status": "succeeded", "agent_status": "success"},
    )
    controller = RecordingController(
        update_batches=deque([SessionUpdateBatch((finished,), 2, False)])
    )
    response = asyncio.run(
        request(
            make_app(controller),
            "GET",
            f"/api/v1/runs/{RUN_ID}/events",
            headers={
                **auth_headers(),
                "Accept": "text/event-stream",
                "Last-Event-ID": "1",
            },
        )
    )

    assert response.status_code == 200
    assert response.text == (
        f"id: 2\nevent: run_finished\ndata: {finished.to_json()}\n\n"
    )
    assert controller.calls == [("read_updates", RUN_ID, 1)]


def cursor_headers(*values: str | bytes) -> httpx.Headers:
    pairs: list[tuple[str | bytes, str | bytes]] = [
        ("Authorization", "Bearer fixed-test-token"),
        ("Origin", "http://127.0.0.1:43123"),
        ("Accept", "text/event-stream"),
    ]
    pairs.extend(("Last-Event-ID", value) for value in values)
    return httpx.Headers(pairs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "headers",
    [
        cursor_headers("1", "1"),
        cursor_headers("-1"),
        cursor_headers("+1"),
        cursor_headers(" 1"),
        cursor_headers(b"\xff"),
        cursor_headers("one"),
    ],
)
def test_sse_rejects_invalid_event_cursor(headers: httpx.Headers) -> None:
    controller = RecordingController()
    response = asyncio.run(
        request(
            make_app(controller),
            "GET",
            f"/api/v1/runs/{RUN_ID}/events",
            headers=headers,
        )
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "invalid_event_cursor"}}
    assert controller.calls == []


def test_sse_rejects_cursor_ahead_of_latest_sequence() -> None:
    controller = RecordingController(
        update_batches=deque([SessionUpdateBatch((), 1, False)])
    )
    response = asyncio.run(
        request(
            make_app(controller),
            "GET",
            f"/api/v1/runs/{RUN_ID}/events",
            headers=cursor_headers("2"),
        )
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "invalid_event_cursor"}}
    assert controller.calls == [("read_updates", RUN_ID, 2)]


def test_sse_reset_control_event_omits_retained_suffix() -> None:
    retained = make_update(
        42,
        SessionUpdateKind.RUN_STARTED,
        {"status": "running"},
    )
    controller = RecordingController(
        update_batches=deque([SessionUpdateBatch((retained,), 42, True)])
    )
    response = asyncio.run(
        request(
            make_app(controller),
            "GET",
            f"/api/v1/runs/{RUN_ID}/events",
            headers={**auth_headers(), "Accept": "text/event-stream"},
        )
    )

    assert response.status_code == 200
    assert response.text == (
        "event: reset_required\n"
        f'data: {{"last_sequence":42,"run_id":"{RUN_ID}"}}\n\n'
    )
    assert "run_started" not in response.text


def test_sse_empty_wait_emits_heartbeat_before_terminal_event() -> None:
    finished = make_update(
        1,
        SessionUpdateKind.RUN_FINISHED,
        {"status": "failed", "agent_status": "failed"},
    )
    controller = RecordingController(
        update_batches=deque(
            [
                SessionUpdateBatch((), 0, False),
                SessionUpdateBatch((), 0, False),
                SessionUpdateBatch((finished,), 1, False),
            ]
        )
    )
    response = asyncio.run(
        request(
            make_app(controller),
            "GET",
            f"/api/v1/runs/{RUN_ID}/events",
            headers={**auth_headers(), "Accept": "text/event-stream"},
        )
    )

    assert response.status_code == 200
    assert response.text == (
        ": keep-alive\n\n"
        f"id: 1\nevent: run_finished\ndata: {finished.to_json()}\n\n"
    )
    assert controller.calls == [
        ("read_updates", RUN_ID, 0),
        ("wait_for_updates", RUN_ID, 0, 15.0),
        ("wait_for_updates", RUN_ID, 0, 15.0),
    ]


def test_sse_connection_limit_rejects_first_disallowed_per_run() -> None:
    from coding_agent.web import _SseConnectionLimiter, WebStreamLimitError

    limiter = _SseConnectionLimiter(max_connections=4, max_per_run=2)
    first = limiter.acquire(RUN_ID)
    second = limiter.acquire(RUN_ID)
    with pytest.raises(WebStreamLimitError) as caught:
        limiter.acquire(RUN_ID)
    assert caught.value.code == "stream_limit_reached"

    second.close()
    third = limiter.acquire(RUN_ID)
    third.close()
    first.close()


def test_sse_connection_limit_rejects_fifth_process_connection() -> None:
    from coding_agent.web import _SseConnectionLimiter, WebStreamLimitError

    limiter = _SseConnectionLimiter(max_connections=4, max_per_run=2)
    permits = [
        limiter.acquire("3" * 32),
        limiter.acquire("4" * 32),
        limiter.acquire("5" * 32),
        limiter.acquire("6" * 32),
    ]
    with pytest.raises(WebStreamLimitError) as caught:
        limiter.acquire("7" * 32)
    assert caught.value.code == "stream_limit_reached"
    for permit in permits:
        permit.close()


def test_sse_permit_close_is_thread_safe_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import coding_agent.web as web_module
    from coding_agent.web import _SseConnectionLimiter, _SsePermit

    barrier = Barrier(2)

    class RacingPermit(_SsePermit):
        def __getattribute__(self, name: str):
            value = super().__getattribute__(name)
            if name == "_closed":
                barrier.wait(timeout=5.0)
            return value

    monkeypatch.setattr(web_module, "_SsePermit", RacingPermit)
    limiter = _SseConnectionLimiter(max_connections=1, max_per_run=1)
    permit = limiter.acquire(RUN_ID)
    errors: list[BaseException] = []

    def close_permit() -> None:
        try:
            permit.close()
        except BaseException as error:
            errors.append(error)

    threads = [Thread(target=close_permit), Thread(target=close_permit)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    replacement = limiter.acquire(RUN_ID)
    replacement.close()


def test_sse_disconnect_generator_close_releases_without_cancelling() -> None:
    from coding_agent.web import _SseConnectionLimiter, _sse_stream

    started = make_update(
        1,
        SessionUpdateKind.RUN_STARTED,
        {"status": "running"},
    )
    controller = RecordingController()
    limiter = _SseConnectionLimiter(max_connections=1, max_per_run=1)
    permit = limiter.acquire(RUN_ID)
    generator = _sse_stream(
        controller,
        RUN_ID,
        0,
        SessionUpdateBatch((started,), 1, False),
        permit,
    )

    assert next(generator).startswith("id: 1\n")
    generator.close()
    replacement = limiter.acquire(RUN_ID)
    replacement.close()
    assert not any(call[0] == "cancel" for call in controller.calls)


def test_sse_disconnect_before_first_iteration_releases_permit() -> None:
    from coding_agent.web import _SseConnectionLimiter, _sse_stream

    controller = RecordingController()
    limiter = _SseConnectionLimiter(max_connections=1, max_per_run=1)
    stream = _sse_stream(
        controller,
        RUN_ID,
        0,
        SessionUpdateBatch((), 0, False),
        limiter.acquire(RUN_ID),
    )

    stream.close()
    replacement = limiter.acquire(RUN_ID)
    replacement.close()


def test_sse_stream_error_after_start_is_fixed_and_private() -> None:
    from coding_agent.web import _SseConnectionLimiter, _sse_stream

    sentinel = "PRIVATE_CONTROLLER_EXCEPTION"
    started = make_update(
        1,
        SessionUpdateKind.RUN_STARTED,
        {"status": "running"},
    )
    controller = RecordingController(
        errors={"wait_for_updates": RuntimeError(sentinel)}
    )
    limiter = _SseConnectionLimiter(max_connections=1, max_per_run=1)
    generator = _sse_stream(
        controller,
        RUN_ID,
        0,
        SessionUpdateBatch((started,), 1, False),
        limiter.acquire(RUN_ID),
    )

    assert next(generator).startswith("id: 1\nevent: run_started\n")
    assert next(generator) == (
        'event: transport_error\ndata: {"code":"stream_unavailable"}\n\n'
    )
    with pytest.raises(StopIteration):
        next(generator)
    assert sentinel not in repr(generator)
    replacement = limiter.acquire(RUN_ID)
    replacement.close()


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(7)])
def test_sse_base_exception_is_not_converted(error: BaseException) -> None:
    from coding_agent.web import _SseConnectionLimiter, _sse_stream

    started = make_update(
        1,
        SessionUpdateKind.RUN_STARTED,
        {"status": "running"},
    )
    controller = RecordingController()
    limiter = _SseConnectionLimiter(max_connections=1, max_per_run=1)
    generator = _sse_stream(
        controller,
        RUN_ID,
        0,
        SessionUpdateBatch((started,), 1, False),
        limiter.acquire(RUN_ID),
    )
    assert next(generator).startswith("id: 1\n")

    def raise_base_exception(*_args, **_kwargs):
        raise error

    controller.wait_for_updates = raise_base_exception  # type: ignore[method-assign]
    with pytest.raises(type(error)):
        next(generator)
    replacement = limiter.acquire(RUN_ID)
    replacement.close()


class BlockingSseController(RecordingController):
    def __init__(self) -> None:
        super().__init__()
        self.release_waits = Event()
        self._condition = Condition()
        self._waiting = 0
        self._completed_waits = 0

    @staticmethod
    def _update(
        run_id: str,
        sequence: int,
        kind: SessionUpdateKind,
        data: dict[str, object],
    ) -> SessionUpdate:
        return SessionUpdate(
            schema_version=SESSION_UPDATE_SCHEMA_VERSION,
            session_id=SESSION_ID,
            run_id=run_id,
            sequence=sequence,
            timestamp_utc=TIMESTAMP,
            kind=kind,
            data=data,  # type: ignore[arg-type]
        )

    def read_updates(
        self, run_id: str, *, after_sequence: int = 0
    ) -> SessionUpdateBatch:
        self._record("read_updates", run_id, after_sequence)
        if self.release_waits.is_set():
            finished = self._update(
                run_id,
                2,
                SessionUpdateKind.RUN_FINISHED,
                {"status": "failed", "agent_status": "failed"},
            )
            return SessionUpdateBatch((finished,), 2, False)
        started = self._update(
            run_id,
            1,
            SessionUpdateKind.RUN_STARTED,
            {"status": "running"},
        )
        return SessionUpdateBatch((started,), 1, False)

    def wait_for_updates(
        self,
        run_id: str,
        *,
        after_sequence: int,
        timeout_seconds: float,
    ) -> SessionUpdateBatch:
        self._record("wait_for_updates", run_id, after_sequence, timeout_seconds)
        with self._condition:
            self._waiting += 1
            self._condition.notify_all()
        if not self.release_waits.wait(timeout=5.0):
            raise RuntimeError("test wait barrier timed out")
        with self._condition:
            self._completed_waits += 1
            self._condition.notify_all()
        finished = self._update(
            run_id,
            2,
            SessionUpdateKind.RUN_FINISHED,
            {"status": "failed", "agent_status": "failed"},
        )
        return SessionUpdateBatch((finished,), 2, False)

    def wait_until_waiting(self, count: int) -> None:
        with self._condition:
            assert self._condition.wait_for(
                lambda: self._waiting >= count,
                timeout=5.0,
            )

    def wait_until_completed(self, count: int) -> None:
        with self._condition:
            assert self._condition.wait_for(
                lambda: self._completed_waits >= count,
                timeout=5.0,
            )


def live_app_factory(controller: BlockingSseController):
    def factory(port: int):
        return create_web_app(
            controller=controller,
            access_policy=WebAccessPolicy(
                token="fixed-test-token",
                port=port,
            ),
        )

    return factory


def live_headers(base_url: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer fixed-test-token",
        "Origin": base_url,
        "Accept": "text/event-stream",
    }


def open_live_stream(
    client: httpx.Client,
    run_id: str,
    headers: dict[str, str],
) -> httpx.Response:
    request_value = client.build_request(
        "GET",
        f"/api/v1/runs/{run_id}/events",
        headers=headers,
    )
    return client.send(request_value, stream=True)


def test_sse_disconnect_releases_real_loopback_permits_without_cancel() -> None:
    controller = BlockingSseController()
    with running_uvicorn_app(live_app_factory(controller)) as base_url:
        client = httpx.Client(base_url=base_url, trust_env=False, timeout=5.0)
        responses: list[httpx.Response] = []
        try:
            responses.append(open_live_stream(client, RUN_ID, live_headers(base_url)))
            responses.append(open_live_stream(client, RUN_ID, live_headers(base_url)))
            controller.wait_until_waiting(2)
            for response in responses:
                assert response.status_code == 200
                response.close()
            controller.release_waits.set()
            controller.wait_until_completed(2)
            deadline = monotonic() + 5.0
            while True:
                replacement = open_live_stream(
                    client,
                    RUN_ID,
                    live_headers(base_url),
                )
                if replacement.status_code == 200:
                    replacement.close()
                    break
                assert replacement.status_code == 429
                replacement.close()
                if monotonic() >= deadline:
                    pytest.fail("SSE permit was not released after disconnect")
        finally:
            for response in responses:
                response.close()
            controller.release_waits.set()
            client.close()
    assert not any(call[0] == "cancel" for call in controller.calls)


def test_sse_limit_rejects_third_real_connection_for_one_run() -> None:
    controller = BlockingSseController()
    with running_uvicorn_app(live_app_factory(controller)) as base_url:
        client = httpx.Client(base_url=base_url, trust_env=False, timeout=5.0)
        responses: list[httpx.Response] = []
        try:
            responses.append(open_live_stream(client, RUN_ID, live_headers(base_url)))
            responses.append(open_live_stream(client, RUN_ID, live_headers(base_url)))
            controller.wait_until_waiting(2)
            denied = client.get(
                f"/api/v1/runs/{RUN_ID}/events",
                headers=live_headers(base_url),
            )
            assert denied.status_code == 429
            assert denied.json() == {"error": {"code": "stream_limit_reached"}}
        finally:
            for response in responses:
                response.close()
            controller.release_waits.set()
            client.close()


def test_sse_limit_rejects_fifth_real_process_connection() -> None:
    controller = BlockingSseController()
    run_ids = tuple(f"{value:x}" * 32 for value in range(2, 7))
    with running_uvicorn_app(live_app_factory(controller)) as base_url:
        client = httpx.Client(base_url=base_url, trust_env=False, timeout=5.0)
        responses: list[httpx.Response] = []
        try:
            for run_id in run_ids[:4]:
                responses.append(
                    open_live_stream(client, run_id, live_headers(base_url))
                )
            controller.wait_until_waiting(4)
            denied = client.get(
                f"/api/v1/runs/{run_ids[4]}/events",
                headers=live_headers(base_url),
            )
            assert denied.status_code == 429
            assert denied.json() == {"error": {"code": "stream_limit_reached"}}
        finally:
            for response in responses:
                response.close()
            controller.release_waits.set()
            client.close()

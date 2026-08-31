from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from threading import Event, Thread

import pytest

from coding_agent.session_events import (
    SESSION_UPDATE_SCHEMA_VERSION,
    SessionEventHub,
    SessionUpdate,
    SessionUpdateKind,
)

SESSION_ID = "1" * 32
RUN_ID = "2" * 32
NOW = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)


def test_run_finished_schema_v3_carries_session_and_agent_status() -> None:
    assert SESSION_UPDATE_SCHEMA_VERSION == 3
    update = SessionUpdate(
        schema_version=3,
        session_id=SESSION_ID,
        run_id=RUN_ID,
        sequence=1,
        timestamp_utc="2026-08-29T08:00:00.000000Z",
        kind=SessionUpdateKind.RUN_FINISHED,
        data={"status": "succeeded", "agent_status": "answered"},
    )
    assert update.to_dict()["data"] == {
        "status": "succeeded",
        "agent_status": "answered",
    }


@pytest.mark.parametrize(
    "data",
    [
        {"status": "succeeded"},
        {"status": "succeeded", "agent_status": "unknown"},
        {"status": "failed", "agent_status": "success"},
        {"status": "interrupted", "agent_status": "failed"},
        {"status": "succeeded", "agent_status": "answered", "extra": 1},
    ],
)
def test_run_finished_rejects_incomplete_or_invalid_v3_data(
    data: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        SessionUpdate(
            schema_version=3,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            sequence=1,
            timestamp_utc="2026-08-29T08:00:00.000000Z",
            kind=SessionUpdateKind.RUN_FINISHED,
            data=data,  # type: ignore[arg-type]
        )


def test_convergence_events_project_only_safe_runtime_fields() -> None:
    updates = (
        SessionUpdate(
            schema_version=SESSION_UPDATE_SCHEMA_VERSION,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            sequence=1,
            timestamp_utc="2026-08-29T08:00:00.000000Z",
            kind=SessionUpdateKind.PHASE_CHANGED,
            data={"from_phase": "discover", "to_phase": "act", "epoch": 1},
        ),
        SessionUpdate(
            schema_version=SESSION_UPDATE_SCHEMA_VERSION,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            sequence=2,
            timestamp_utc="2026-08-29T08:00:00.000000Z",
            kind=SessionUpdateKind.DECISION_CHECKPOINT,
            data={
                "reason": "exploration_limit",
                "phase": "discover",
                "main_calls_remaining": 18,
            },
        ),
        SessionUpdate(
            schema_version=SESSION_UPDATE_SCHEMA_VERSION,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            sequence=3,
            timestamp_utc="2026-08-29T08:00:00.000000Z",
            kind=SessionUpdateKind.CONTEXT_COMPRESSED,
            data={
                "summary_source": "fallback",
                "before_chars": 49_000,
                "after_chars": 31_000,
            },
        ),
    )

    assert [update.kind.value for update in updates] == [
        "phase_changed",
        "decision_checkpoint",
        "context_compressed",
    ]
    encoded = json.dumps([update.to_dict() for update in updates])
    for forbidden in (
        "instructions",
        "summary_text",
        "continuation",
        "C:\\Users",
        "Bearer ",
    ):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    "reason",
    ["verification_failure", "final_read_allowance_exhausted"],
)
def test_decision_checkpoint_accepts_recovery_reasons(reason: str) -> None:
    update = SessionUpdate(
        schema_version=SESSION_UPDATE_SCHEMA_VERSION,
        session_id=SESSION_ID,
        run_id=RUN_ID,
        sequence=1,
        timestamp_utc="2026-08-29T08:00:00.000000Z",
        kind=SessionUpdateKind.DECISION_CHECKPOINT,
        data={
            "reason": reason,
            "phase": "verify",
            "main_calls_remaining": 3,
        },
    )

    assert update.data["reason"] == reason


def test_decision_checkpoint_accepts_post_mutation_integrity() -> None:
    update = SessionUpdate(
        schema_version=SESSION_UPDATE_SCHEMA_VERSION,
        session_id=SESSION_ID,
        run_id=RUN_ID,
        sequence=1,
        timestamp_utc="2026-08-29T08:00:00.000000Z",
        kind=SessionUpdateKind.DECISION_CHECKPOINT,
        data={
            "reason": "post_mutation_integrity",
            "phase": "verify",
            "main_calls_remaining": 20,
        },
    )

    assert update.data["reason"] == "post_mutation_integrity"


@pytest.mark.parametrize(
    ("kind", "data"),
    [
        (
            SessionUpdateKind.VERIFICATION_STARTED,
            {
                "source": "local_integrity",
                "attempt_index": 1,
                "mutation_index": 1,
            },
        ),
        (
            SessionUpdateKind.VERIFICATION_FINISHED,
            {
                "source": "local_integrity",
                "status": "passed",
                "exit_code": 0,
                "timed_out": False,
                "truncated": False,
                "duration_ms": 0,
                "validation_index": 1,
                "mutation_index": 1,
                "error_code": None,
            },
        ),
    ],
)
def test_session_updates_accept_local_integrity_verification_source(
    kind: SessionUpdateKind,
    data: dict[str, object],
) -> None:
    update = SessionUpdate(
        schema_version=SESSION_UPDATE_SCHEMA_VERSION,
        session_id=SESSION_ID,
        run_id=RUN_ID,
        sequence=1,
        timestamp_utc="2026-08-29T08:00:00.000000Z",
        kind=kind,
        data=data,  # type: ignore[arg-type]
    )

    assert update.data["source"] == "local_integrity"


def test_session_update_accepts_duplicate_only_checkpoint_reason() -> None:
    update = SessionUpdate(
        schema_version=SESSION_UPDATE_SCHEMA_VERSION,
        session_id=SESSION_ID,
        run_id=RUN_ID,
        sequence=1,
        timestamp_utc="2026-08-29T08:00:00.000000Z",
        kind=SessionUpdateKind.DECISION_CHECKPOINT,
        data={
            "reason": "duplicate_only_turn",
            "phase": "discover",
            "main_calls_remaining": 30,
        },
    )
    assert update.data["reason"] == "duplicate_only_turn"


def test_run_progress_requires_exact_profile_phase_counts_and_limits() -> None:
    data = {
        "budget_profile": "deep",
        "phase": "verify",
        "main_model_calls": 7,
        "main_model_limit": 40,
        "summary_model_calls": 1,
        "summary_model_limit": 6,
        "provider_attempts": 9,
        "provider_attempt_limit": 80,
        "tool_calls": 12,
        "tool_limit": 140,
    }
    update = SessionUpdate(
        schema_version=SESSION_UPDATE_SCHEMA_VERSION,
        session_id=SESSION_ID,
        run_id=RUN_ID,
        sequence=1,
        timestamp_utc="2026-08-29T08:00:00.000000Z",
        kind=SessionUpdateKind.RUN_PROGRESS,
        data=data,
    )
    assert update.to_dict()["data"] == data

    for invalid in (
        {**data, "instructions": "private"},
        {**data, "budget_profile": "unlimited"},
        {**data, "main_model_calls": -1},
    ):
        with pytest.raises(ValueError):
            SessionUpdate(
                schema_version=SESSION_UPDATE_SCHEMA_VERSION,
                session_id=SESSION_ID,
                run_id=RUN_ID,
                sequence=1,
                timestamp_utc="2026-08-29T08:00:00.000000Z",
                kind=SessionUpdateKind.RUN_PROGRESS,
                data=invalid,  # type: ignore[arg-type]
            )


def test_update_schema_is_ordered_and_repr_hides_data() -> None:
    hub = SessionEventHub(utc_clock=lambda: NOW, sensitive_values=("sk-private",))
    hub.begin_run(SESSION_ID, RUN_ID)
    first = hub.publish(SessionUpdateKind.RUN_STARTED, {"status": "running"})
    second = hub.publish(
        SessionUpdateKind.ASSISTANT_TEXT_DELTA,
        {"content": "hello sk-private"},
    )
    assert (first.sequence, second.sequence) == (1, 2)
    assert first.to_json() == json.dumps(
        first.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    assert second.data == {"content": "hello [REDACTED]"}
    assert "hello" not in repr(second)
    assert hub.read(after_sequence=1).events == (second,)


def test_lifecycle_publication_is_idempotent_per_run() -> None:
    hub = SessionEventHub(utc_clock=lambda: NOW)
    hub.begin_run(SESSION_ID, RUN_ID)
    first = hub.publish(
        SessionUpdateKind.RUN_CANCELLING,
        {"status": "cancelling"},
    )
    repeated = hub.publish(
        SessionUpdateKind.RUN_CANCELLING,
        {"status": "cancelling"},
    )

    assert repeated is first
    assert hub.read().events == (first,)
    assert hub.read().last_sequence == 1


@pytest.mark.parametrize(
    ("kind", "data"),
    [
        (
            SessionUpdateKind.TOOL_STARTED,
            {"tool_name": "read_file", "arguments": {"path": "x"}},
        ),
        (
            SessionUpdateKind.TOOL_FINISHED,
            {"tool_name": "run_command", "stdout": "secret"},
        ),
        (SessionUpdateKind.CONTROLLER_ERROR, {"error": "raw provider body"}),
        (SessionUpdateKind.ASSISTANT_TEXT_DELTA, {"content": ""}),
    ],
)
def test_update_payload_rejects_non_allowlisted_or_invalid_fields(
    kind: SessionUpdateKind,
    data: dict[str, object],
) -> None:
    hub = SessionEventHub(utc_clock=lambda: NOW)
    hub.begin_run(SESSION_ID, RUN_ID)
    with pytest.raises((TypeError, ValueError)):
        hub.publish(kind, data)  # type: ignore[arg-type]


def test_hub_enforces_count_and_encoded_byte_limits() -> None:
    hub = SessionEventHub(
        utc_clock=lambda: NOW,
        max_events=3,
        max_bytes=600,
    )
    hub.begin_run(SESSION_ID, RUN_ID)
    for index in range(6):
        hub.publish(
            SessionUpdateKind.ASSISTANT_TEXT_DELTA,
            {"content": f"{index}-" + "x" * 120},
        )
    batch = hub.read(after_sequence=0)
    assert batch.reset_required is True
    assert len(batch.events) <= 3
    assert batch.events[-1].sequence == 6
    assert sum(len(event.to_json().encode("utf-8")) for event in batch.events) <= 600


def test_wait_wakes_for_new_event_without_polling_sleep() -> None:
    hub = SessionEventHub(utc_clock=lambda: NOW)
    hub.begin_run(SESSION_ID, RUN_ID)
    entered = Event()
    result: list[object] = []

    def waiter() -> None:
        entered.set()
        result.append(hub.wait(after_sequence=0, timeout_seconds=2.0))

    thread = Thread(target=waiter)
    thread.start()
    assert entered.wait(timeout=1.0)
    published = hub.publish(SessionUpdateKind.RUN_STARTED, {"status": "running"})
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert result[0].events == (published,)


def test_begin_run_replaces_previous_replay_window() -> None:
    hub = SessionEventHub(utc_clock=lambda: NOW)
    hub.begin_run(SESSION_ID, RUN_ID)
    hub.publish(
        SessionUpdateKind.RUN_FINISHED,
        {"status": "failed", "agent_status": "failed"},
    )
    hub.begin_run("3" * 32, "4" * 32)
    assert hub.read().events == ()
    assert hub.read().last_sequence == 0


def test_forget_runs_clears_only_matching_retained_projection() -> None:
    hub = SessionEventHub(utc_clock=lambda: NOW)
    hub.begin_run(SESSION_ID, RUN_ID)
    hub.publish(SessionUpdateKind.RUN_STARTED, {"status": "running"})
    hub.publish(
        SessionUpdateKind.RUN_FINISHED,
        {"status": "failed", "agent_status": "failed"},
    )
    before = hub.read(expected_run_id=RUN_ID)

    assert hub.forget_runs(()) is False
    assert hub.forget_runs(("3" * 32,)) is False
    assert hub.read(expected_run_id=RUN_ID) == before
    assert hub.forget_runs((RUN_ID,)) is True
    assert hub._session_id is None
    assert hub._run_id is None
    assert tuple(hub._events) == ()
    assert hub._lifecycle_updates == {}
    assert hub._retained_bytes == 0
    assert hub._next_sequence == 1
    with pytest.raises(LookupError, match="run not found"):
        hub.read(expected_run_id=RUN_ID)

    hub.begin_run("4" * 32, "5" * 32)
    first = hub.publish(SessionUpdateKind.RUN_STARTED, {"status": "running"})
    assert first.sequence == 1


def test_forget_runs_wakes_waiter_for_deleted_retained_run() -> None:
    hub = SessionEventHub(utc_clock=lambda: NOW)
    hub.begin_run(SESSION_ID, RUN_ID)
    started = hub.publish(SessionUpdateKind.RUN_STARTED, {"status": "running"})
    entered = Event()
    failures: list[BaseException] = []

    def wait_for_old_run() -> None:
        entered.set()
        try:
            hub.wait(
                after_sequence=started.sequence,
                timeout_seconds=2.0,
                expected_run_id=RUN_ID,
            )
        except BaseException as exc:
            failures.append(exc)

    waiter = Thread(target=wait_for_old_run)
    waiter.start()
    assert entered.wait(timeout=1.0)
    assert hub.forget_runs((RUN_ID,)) is True
    waiter.join(timeout=1.0)

    assert not waiter.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], LookupError)
    assert str(failures[0]) == "session update run not found"


@pytest.mark.parametrize(
    "run_ids",
    ([RUN_ID], ("bad",), (RUN_ID, RUN_ID)),
)
def test_forget_runs_rejects_invalid_or_duplicate_ids(run_ids: object) -> None:
    hub = SessionEventHub(utc_clock=lambda: NOW)
    with pytest.raises((TypeError, ValueError)):
        hub.forget_runs(run_ids)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "timeout_seconds",
    [True, 0, -1, math.nan, math.inf],
)
def test_wait_rejects_invalid_timeout(timeout_seconds: object) -> None:
    hub = SessionEventHub(utc_clock=lambda: NOW)
    hub.begin_run(SESSION_ID, RUN_ID)
    with pytest.raises((TypeError, ValueError)):
        hub.wait(after_sequence=0, timeout_seconds=timeout_seconds)  # type: ignore[arg-type]


def test_wait_timeout_and_cursor_boundaries_are_deterministic() -> None:
    hub = SessionEventHub(utc_clock=lambda: NOW)
    hub.begin_run(SESSION_ID, RUN_ID)
    empty = hub.wait(after_sequence=0, timeout_seconds=0.001)
    assert empty.events == ()
    assert empty.last_sequence == 0
    first = hub.publish(SessionUpdateKind.RUN_STARTED, {"status": "running"})
    at_latest = hub.read(after_sequence=first.sequence)
    assert at_latest.events == ()
    assert at_latest.last_sequence == first.sequence
    with pytest.raises(ValueError):
        hub.read(after_sequence=first.sequence + 1)


def test_individually_oversized_event_does_not_consume_sequence() -> None:
    hub = SessionEventHub(utc_clock=lambda: NOW, max_bytes=320)
    hub.begin_run(SESSION_ID, RUN_ID)
    with pytest.raises(ValueError):
        hub.publish(
            SessionUpdateKind.ASSISTANT_TEXT_DELTA,
            {"content": "x" * 400},
        )
    first = hub.publish(SessionUpdateKind.RUN_STARTED, {"status": "running"})
    assert first.sequence == 1


def test_concurrent_publish_and_read_preserve_total_sequence_order() -> None:
    hub = SessionEventHub(utc_clock=lambda: NOW, max_events=20)
    hub.begin_run(SESSION_ID, RUN_ID)
    failures: list[BaseException] = []

    def publish(index: int) -> None:
        try:
            hub.publish(
                SessionUpdateKind.ASSISTANT_TEXT_DELTA,
                {"content": f"delta-{index}"},
            )
        except BaseException as exc:
            failures.append(exc)

    threads = [Thread(target=publish, args=(index,)) for index in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1.0)
    assert failures == []
    batch = hub.read()
    assert [event.sequence for event in batch.events] == list(range(1, 11))
    assert {event.data["content"] for event in batch.events} == {
        f"delta-{index}" for index in range(10)
    }

from __future__ import annotations

import asyncio
import json
from collections import deque

import pytest

from coding_agent.session import SessionControllerError
from coding_agent.session_controller import CancellationResult
from coding_agent.web_auth import WebAccessPolicy
from tests.web_support import (
    RUN_ID,
    SECOND_RUN_ID,
    SECOND_SESSION_ID,
    SESSION_ID,
    RecordingController,
    auth_headers,
    make_session_record,
    make_session_view,
    make_skill_view,
    request,
)


def make_app(controller: RecordingController | None = None):
    from coding_agent.web import create_web_app

    return create_web_app(
        controller=controller or RecordingController(),
        access_policy=WebAccessPolicy(token="fixed-test-token", port=43123),
    )


def test_health_requires_auth_and_returns_exact_schema() -> None:
    controller = RecordingController()
    app = make_app(controller)

    denied = asyncio.run(request(app, "GET", "/api/v1/health"))
    allowed = asyncio.run(
        request(app, "GET", "/api/v1/health", headers=auth_headers())
    )

    assert denied.status_code == 401
    assert denied.json() == {"error": {"code": "unauthorized"}}
    assert allowed.status_code == 200
    assert allowed.json() == {"schema_version": 1, "status": "ok"}
    assert allowed.headers["cache-control"] == "no-store"
    assert controller.calls == []


def test_unhandled_route_error_is_stable_and_private(capsys) -> None:
    private_detail = "private path D:\\sensitive\\workspace"
    app = make_app()

    def explode() -> None:
        raise RuntimeError(private_detail)

    app.add_api_route("/api/v1/explode", explode, methods=["GET"])
    response = asyncio.run(
        request(app, "GET", "/api/v1/explode", headers=auth_headers())
    )
    captured = capsys.readouterr()

    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_server_error"}}
    assert private_detail not in response.text
    assert private_detail not in repr(response)
    assert private_detail not in captured.out
    assert private_detail not in captured.err


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": "repair", "extra": True},
        {"message": True},
        {"message": "repair", "skill_ids": [True]},
        {"message": "repair", "skill_ids": "python-testing"},
    ],
)
def test_create_session_rejects_invalid_request_shapes(payload: object) -> None:
    controller = RecordingController()
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            "/api/v1/sessions",
            json=payload,
            headers=auth_headers(),
        )
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "invalid_request"}}
    assert controller.calls == []


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/xml"])
def test_create_session_requires_json_media_type(content_type: str | None) -> None:
    controller = RecordingController()
    headers = auth_headers()
    if content_type is not None:
        headers["Content-Type"] = content_type
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            "/api/v1/sessions",
            content=b'{"message":"repair"}',
            headers=headers,
        )
    )

    assert response.status_code == 415
    assert response.json() == {"error": {"code": "unsupported_media_type"}}
    assert controller.calls == []


def test_create_session_rejects_malformed_json() -> None:
    controller = RecordingController()
    headers = {**auth_headers(), "Content-Type": "application/json"}
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            "/api/v1/sessions",
            content=b'{"message":',
            headers=headers,
        )
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "invalid_request"}}
    assert controller.calls == []


def json_message_body(size: int) -> bytes:
    empty = json.dumps(
        {"message": ""}, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert size >= len(empty)
    body = json.dumps(
        {"message": "x" * (size - len(empty))},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert len(body) == size
    return body


def test_create_session_accepts_exact_body_limit() -> None:
    controller = RecordingController()
    headers = {**auth_headers(), "Content-Type": "application/json"}
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            "/api/v1/sessions",
            content=json_message_body(131_072),
            headers=headers,
        )
    )

    assert response.status_code == 201
    assert response.json() == {
        "session_id": controller.create_handle.session_id,
        "run_id": controller.create_handle.run_id,
    }
    assert controller.calls[0][0] == "create_session"
    assert len(controller.calls[0][1]) == 131_058
    assert controller.calls[0][2] == ()


def test_create_session_rejects_first_byte_over_body_limit() -> None:
    controller = RecordingController()
    headers = {**auth_headers(), "Content-Type": "application/json"}
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            "/api/v1/sessions",
            content=json_message_body(131_073),
            headers=headers,
        )
    )

    assert response.status_code == 413
    assert response.json() == {"error": {"code": "request_too_large"}}
    assert controller.calls == []


async def chunked_asgi_request(app, chunks: tuple[bytes, ...]) -> tuple[int, object]:
    messages = deque(
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    )
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        if messages:
            return messages.popleft()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/sessions",
            "raw_path": b"/api/v1/sessions",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"127.0.0.1:43123"),
                (b"origin", b"http://127.0.0.1:43123"),
                (b"authorization", b"Bearer fixed-test-token"),
                (b"content-type", b"application/json"),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 43123),
        },
        receive,
        send,
    )
    start = next(item for item in sent if item["type"] == "http.response.start")
    body = b"".join(
        item.get("body", b"")
        for item in sent
        if item["type"] == "http.response.body"
    )
    return int(start["status"]), json.loads(body)


def test_streamed_body_without_content_length_is_still_bounded() -> None:
    controller = RecordingController()
    body = json_message_body(131_073)
    status, response_body = asyncio.run(
        chunked_asgi_request(make_app(controller), (body[:80_000], body[80_000:]))
    )

    assert status == 413
    assert response_body == {"error": {"code": "request_too_large"}}
    assert controller.calls == []


def test_create_session_delegates_message_and_ordered_skill_ids() -> None:
    controller = RecordingController()
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            "/api/v1/sessions",
            json={"message": "repair tests", "skill_ids": ["python-testing"]},
            headers=auth_headers(),
        )
    )

    assert response.status_code == 201
    assert response.json() == {"session_id": SESSION_ID, "run_id": RUN_ID}
    assert controller.calls == [
        ("create_session", "repair tests", ("python-testing",)),
    ]


def test_list_sessions_preserves_controller_order_and_exact_projection() -> None:
    first = make_session_record()
    second = make_session_record(
        session_id=SECOND_SESSION_ID,
        title="Second session",
        last_run_id=None,
    )
    controller = RecordingController(sessions=(first, second))
    response = asyncio.run(
        request(
            make_app(controller),
            "GET",
            "/api/v1/sessions?limit=2",
            headers=auth_headers(),
        )
    )

    assert response.status_code == 200
    assert response.json() == {
        "sessions": [
            {
                "session_id": SESSION_ID,
                "title": "Repair tests",
                "status": "idle",
                "created_at_utc": "2026-08-30T00:00:00.000000Z",
                "updated_at_utc": "2026-08-30T00:00:00.000000Z",
                "last_run_id": RUN_ID,
                "next_sequence": 2,
            },
            {
                "session_id": SECOND_SESSION_ID,
                "title": "Second session",
                "status": "idle",
                "created_at_utc": "2026-08-30T00:00:00.000000Z",
                "updated_at_utc": "2026-08-30T00:00:00.000000Z",
                "last_run_id": None,
                "next_sequence": 2,
            },
        ]
    }
    assert controller.calls == [("list_sessions", 2)]


@pytest.mark.parametrize("limit", [1, 500])
def test_list_sessions_accepts_controller_limit_boundaries(limit: int) -> None:
    controller = RecordingController()
    response = asyncio.run(
        request(
            make_app(controller),
            "GET",
            f"/api/v1/sessions?limit={limit}",
            headers=auth_headers(),
        )
    )

    assert response.status_code == 200
    assert controller.calls == [("list_sessions", limit)]


@pytest.mark.parametrize("limit", [0, 501, "true", "1.5"])
def test_list_sessions_rejects_invalid_limit(limit: object) -> None:
    controller = RecordingController()
    response = asyncio.run(
        request(
            make_app(controller),
            "GET",
            f"/api/v1/sessions?limit={limit}",
            headers=auth_headers(),
        )
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "invalid_request"}}
    assert controller.calls == []


def test_session_detail_uses_allowlisted_projection_and_selected_skills() -> None:
    controller = RecordingController(
        session_view=make_session_view(),
        selected_skill_ids=("python-testing", "code-review"),
    )
    response = asyncio.run(
        request(
            make_app(controller),
            "GET",
            f"/api/v1/sessions/{SESSION_ID}",
            headers=auth_headers(),
        )
    )

    assert response.status_code == 200
    assert response.json() == {
        "session": {
            "session_id": SESSION_ID,
            "title": "Repair tests",
            "status": "idle",
            "created_at_utc": "2026-08-30T00:00:00.000000Z",
            "updated_at_utc": "2026-08-30T00:00:00.000000Z",
            "last_run_id": RUN_ID,
            "next_sequence": 2,
        },
        "runs": [
            {
                "run_id": RUN_ID,
                "ordinal": 1,
                "status": "queued",
                "started_at_utc": None,
                "finished_at_utc": None,
                "agent_status": None,
                "termination_reason": None,
                "audit_run_id": None,
                "final_report": None,
            }
        ],
        "events": [
            {
                "session_id": SESSION_ID,
                "run_id": RUN_ID,
                "sequence": 1,
                "kind": "user_message",
                "created_at_utc": "2026-08-30T00:00:00.000000Z",
                "data": {"content": "repair tests"},
            }
        ],
        "skill_ids": ["python-testing", "code-review"],
    }
    assert controller.calls == [
        ("get_session", SESSION_ID),
        ("get_session_skills", SESSION_ID),
    ]
    forbidden = {
        "instructions",
        "api_key",
        "authorization",
        "continuation_items",
        "completion",
        "stdout",
        "stderr",
        "environment",
    }
    assert not forbidden.intersection(all_json_keys(response.json()))


def all_json_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(
            *(all_json_keys(item) for item in value.values()),
        )
    if isinstance(value, list):
        return set().union(*(all_json_keys(item) for item in value))
    return set()


def test_session_follow_up_delegates_and_returns_accepted_handle() -> None:
    controller = RecordingController()
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            f"/api/v1/sessions/{SESSION_ID}/messages",
            json={"message": "continue"},
            headers=auth_headers(),
        )
    )

    assert response.status_code == 202
    assert response.json() == {"session_id": SESSION_ID, "run_id": SECOND_RUN_ID}
    assert controller.calls == [("submit_message", SESSION_ID, "continue")]


def test_skill_catalog_projects_only_public_metadata_in_order() -> None:
    controller = RecordingController(skill_view=make_skill_view())
    response = asyncio.run(
        request(
            make_app(controller),
            "GET",
            "/api/v1/skills",
            headers=auth_headers(),
        )
    )

    assert response.status_code == 200
    assert response.json() == {
        "skills": [
            {
                "skill_id": "python-testing",
                "name": "Python testing",
                "description": "Use focused pytest workflows.",
                "source": "workspace",
                "sha256": "a" * 64,
                "char_count": 128,
            },
            {
                "skill_id": "code-review",
                "name": "Code review",
                "description": "Review changes before completion.",
                "source": "user",
                "sha256": "b" * 64,
                "char_count": 96,
            },
        ],
        "diagnostics": [
            {
                "code": "invalid_skill_metadata",
                "source": "workspace",
                "entry_name": "broken-skill",
            }
        ],
        "usable": True,
    }
    assert controller.private_skill_instruction not in response.text
    assert controller.calls == [("list_skills",)]


def test_get_and_set_session_skill_selection_preserves_order() -> None:
    controller = RecordingController(selected_skill_ids=("python-testing",))
    app = make_app(controller)
    current = asyncio.run(
        request(
            app,
            "GET",
            f"/api/v1/sessions/{SESSION_ID}/skills",
            headers=auth_headers(),
        )
    )
    updated = asyncio.run(
        request(
            app,
            "PUT",
            f"/api/v1/sessions/{SESSION_ID}/skills",
            json={"skill_ids": ["code-review", "python-testing"]},
            headers=auth_headers(),
        )
    )

    assert current.status_code == 200
    assert current.json() == {"skill_ids": ["python-testing"]}
    assert updated.status_code == 200
    assert updated.json() == {"skill_ids": ["code-review", "python-testing"]}
    assert controller.calls == [
        ("get_session_skills", SESSION_ID),
        (
            "set_session_skills",
            SESSION_ID,
            ("code-review", "python-testing"),
        ),
    ]


@pytest.mark.parametrize(
    "result",
    [
        CancellationResult.REQUESTED,
        CancellationResult.ALREADY_REQUESTED,
        CancellationResult.ALREADY_FINISHED,
    ],
)
def test_cancel_returns_existing_controller_result(result: CancellationResult) -> None:
    controller = RecordingController(cancellation_result=result)
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            f"/api/v1/runs/{RUN_ID}/cancel",
            json={},
            headers=auth_headers(),
        )
    )

    assert response.status_code == 200
    assert response.json() == {"result": result.value}
    assert controller.calls == [("cancel", RUN_ID)]


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("invalid_message", 400),
        ("invalid_skill_selection", 400),
        ("duplicate_skill_selection", 400),
        ("skill_selection_too_large", 400),
        ("invalid_session_state", 409),
        ("controller_busy", 409),
        ("session_not_found", 404),
        ("run_not_found", 404),
        ("selected_skill_unavailable", 409),
        ("controller_in_use", 409),
        ("skill_catalog_unavailable", 503),
        ("duplicate_skill_id", 503),
        ("controller_closed", 503),
        ("controller_degraded", 503),
        ("controller_timeout", 503),
        ("thread_start_failed", 503),
        ("storage_unavailable", 503),
        ("database_corrupt", 503),
        ("schema_unsupported", 503),
    ],
)
def test_controller_error_mapping_is_stable(code: str, status: int) -> None:
    controller = RecordingController(
        errors={"list_sessions": SessionControllerError(code)}
    )
    response = asyncio.run(
        request(
            make_app(controller),
            "GET",
            "/api/v1/sessions",
            headers=auth_headers(),
        )
    )

    assert response.status_code == status
    assert response.json() == {"error": {"code": code}}


def test_unknown_controller_error_mapping_uses_safe_default() -> None:
    controller = RecordingController(
        errors={"list_sessions": SessionControllerError("private_new_code")}
    )
    response = asyncio.run(
        request(
            make_app(controller),
            "GET",
            "/api/v1/sessions",
            headers=auth_headers(),
        )
    )

    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_server_error"}}
    assert "private_new_code" not in response.text

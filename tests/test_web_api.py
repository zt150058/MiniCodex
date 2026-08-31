from __future__ import annotations

import asyncio
import json
from collections import deque

import pytest

from coding_agent.budget import BudgetProfile
from coding_agent.session import SessionControllerError
from coding_agent.session_controller import CancellationResult, RunHandle
from coding_agent.session_deletion import SessionDeletionResult
from coding_agent.run_mode import RunMode
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


def test_delete_session_is_authenticated_bodyless_and_delegates_exact_id() -> None:
    controller = RecordingController()
    app = make_app(controller)

    denied = asyncio.run(
        request(app, "DELETE", f"/api/v1/sessions/{SESSION_ID}")
    )
    allowed = asyncio.run(
        request(
            app,
            "DELETE",
            f"/api/v1/sessions/{SESSION_ID}",
            content=b"",
            headers={**auth_headers(), "Content-Type": "text/plain"},
        )
    )

    assert denied.status_code == 401
    assert denied.json() == {"error": {"code": "unauthorized"}}
    assert allowed.status_code == 200
    assert allowed.json() == {
        "session_id": SESSION_ID,
        "deleted": True,
        "cleanup_pending": False,
    }
    assert allowed.headers["cache-control"] == "no-store"
    assert controller.calls == [("delete_session", SESSION_ID)]


@pytest.mark.parametrize(
    ("content", "expected_status", "expected_code"),
    (
        (b"{}", 400, "invalid_request"),
        (b"x", 400, "invalid_request"),
        (b"x" * 131_073, 413, "request_too_large"),
    ),
    ids=("json", "one-byte", "oversized"),
)
def test_delete_session_rejects_every_nonempty_body_before_delegation(
    content: bytes,
    expected_status: int,
    expected_code: str,
) -> None:
    controller = RecordingController()
    response = asyncio.run(
        request(
            make_app(controller),
            "DELETE",
            f"/api/v1/sessions/{SESSION_ID}",
            content=content,
            headers=auth_headers(),
        )
    )

    assert response.status_code == expected_status
    assert response.json() == {"error": {"code": expected_code}}
    assert controller.calls == []


def test_delete_session_cleanup_warning_omits_runs_and_private_details() -> None:
    private_run_id = "f" * 32
    controller = RecordingController(
        delete_result=SessionDeletionResult(
            SESSION_ID,
            (private_run_id,),
            True,
        )
    )
    response = asyncio.run(
        request(
            make_app(controller),
            "DELETE",
            f"/api/v1/sessions/{SESSION_ID}",
            headers=auth_headers(),
        )
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": SESSION_ID,
        "deleted": True,
        "cleanup_pending": True,
        "warning_code": "session_log_cleanup_pending",
    }
    assert private_run_id not in response.text
    assert "run_ids" not in response.text
    assert "staging" not in response.text.lower()
    assert "\\" not in response.text


@pytest.mark.parametrize(
    ("code", "status"),
    (
        ("session_not_found", 404),
        ("invalid_session_state", 409),
        ("controller_busy", 409),
        ("storage_unavailable", 503),
        ("session_delete_failed", 503),
        ("session_deletion_recovery_failed", 503),
    ),
)
def test_delete_session_uses_route_stable_error_mapping(
    code: str,
    status: int,
) -> None:
    controller = RecordingController(
        errors={"delete_session": SessionControllerError(code)}
    )
    response = asyncio.run(
        request(
            make_app(controller),
            "DELETE",
            f"/api/v1/sessions/{SESSION_ID}",
            headers=auth_headers(),
        )
    )

    assert response.status_code == status
    assert response.json() == {"error": {"code": code}}
    assert controller.calls == [("delete_session", SESSION_ID)]


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
        "run_mode": "modify",
        "budget_profile": "standard",
    }
    assert controller.calls[0][0] == "create_session"
    assert len(controller.calls[0][1]) == 131_058
    assert controller.calls[0][2:] == (
        (),
        RunMode.MODIFY,
        BudgetProfile.STANDARD,
    )


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
    assert response.json() == {
        "session_id": SESSION_ID,
        "run_id": RUN_ID,
        "run_mode": "modify",
        "budget_profile": "standard",
    }
    assert controller.calls == [
        (
            "create_session",
            "repair tests",
            ("python-testing",),
            RunMode.MODIFY,
            BudgetProfile.STANDARD,
        ),
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
                "run_mode": "modify",
                "budget_profile": "standard",
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
    assert response.json() == {
        "session_id": SESSION_ID,
        "run_id": SECOND_RUN_ID,
        "run_mode": "modify",
        "budget_profile": "standard",
    }
    assert controller.calls == [
        (
            "submit_message",
            SESSION_ID,
            "continue",
            RunMode.MODIFY,
            BudgetProfile.STANDARD,
        )
    ]


@pytest.mark.parametrize(
    ("path", "expected_status", "call_name"),
    [
        ("/api/v1/sessions", 201, "create_session"),
        (f"/api/v1/sessions/{SESSION_ID}/messages", 202, "submit_message"),
    ],
)
def test_run_mode_defaults_to_modify(
    path: str,
    expected_status: int,
    call_name: str,
) -> None:
    controller = RecordingController()
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            path,
            json={"message": "hello"},
            headers=auth_headers(),
        )
    )

    assert response.status_code == expected_status
    assert response.json()["run_mode"] == "modify"
    assert controller.calls[0][0] == call_name
    assert controller.calls[0][-2] is RunMode.MODIFY


@pytest.mark.parametrize("mode", tuple(RunMode))
@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/api/v1/sessions", 201),
        (f"/api/v1/sessions/{SESSION_ID}/messages", 202),
    ],
)
def test_create_and_follow_up_accept_exact_run_modes(
    mode: RunMode,
    path: str,
    expected_status: int,
) -> None:
    controller = RecordingController(
        create_handle=RunHandle(
            SESSION_ID,
            RUN_ID,
            mode,
            BudgetProfile.STANDARD,
        ),
        follow_up_handle=RunHandle(
            SESSION_ID,
            SECOND_RUN_ID,
            mode,
            BudgetProfile.STANDARD,
        ),
    )
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            path,
            json={"message": "hello", "run_mode": mode.value},
            headers=auth_headers(),
        )
    )

    assert response.status_code == expected_status
    assert response.json()["run_mode"] == mode.value
    assert controller.calls[0][-2] is mode


@pytest.mark.parametrize("value", ["auto", "READ_ONLY", "", 1, True, None, []])
@pytest.mark.parametrize(
    "path",
    ["/api/v1/sessions", f"/api/v1/sessions/{SESSION_ID}/messages"],
)
def test_rest_rejects_invalid_run_mode_without_controller_call(
    value: object,
    path: str,
) -> None:
    controller = RecordingController()
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            path,
            json={"message": "hello", "run_mode": value},
            headers=auth_headers(),
        )
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "invalid_request"}}
    assert controller.calls == []


def test_budget_profile_defaults_to_standard() -> None:
    controller = RecordingController()
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            "/api/v1/sessions",
            json={"message": "hello", "skill_ids": [], "run_mode": "modify"},
            headers=auth_headers(),
        )
    )

    assert response.status_code == 201
    assert response.json()["budget_profile"] == "standard"
    assert controller.calls[0][-1] is BudgetProfile.STANDARD


@pytest.mark.parametrize("profile", tuple(BudgetProfile))
@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/api/v1/sessions", 201),
        (f"/api/v1/sessions/{SESSION_ID}/messages", 202),
    ],
)
def test_create_and_follow_up_accept_exact_budget_profiles(
    profile: BudgetProfile,
    path: str,
    expected_status: int,
) -> None:
    controller = RecordingController(
        create_handle=RunHandle(SESSION_ID, RUN_ID, RunMode.MODIFY, profile),
        follow_up_handle=RunHandle(
            SESSION_ID,
            SECOND_RUN_ID,
            RunMode.MODIFY,
            profile,
        ),
    )
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            path,
            json={"message": "hello", "budget_profile": profile.value},
            headers=auth_headers(),
        )
    )

    assert response.status_code == expected_status
    assert response.json()["budget_profile"] == profile.value
    assert controller.calls[0][-1] is profile


@pytest.mark.parametrize("value", ["", "DEEP", "auto", None, True, 1, {}])
@pytest.mark.parametrize(
    "path",
    ["/api/v1/sessions", f"/api/v1/sessions/{SESSION_ID}/messages"],
)
def test_rest_rejects_invalid_budget_profile_before_controller(
    value: object,
    path: str,
) -> None:
    controller = RecordingController()
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            path,
            json={"message": "hello", "budget_profile": value},
            headers=auth_headers(),
        )
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "invalid_request"}}
    assert controller.calls == []


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


def test_skill_import_accepts_exact_raw_limit_and_projects_public_descriptor() -> None:
    archive = b"z" * 131_072
    controller = RecordingController()

    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            "/api/v1/skills/import",
            content=archive,
            headers={**auth_headers(), "Content-Type": "application/zip"},
        )
    )

    assert response.status_code == 201
    assert response.json() == {
        "skill_id": "review",
        "name": "Review",
        "description": "Review safely.",
        "source": "workspace",
        "sha256": "c" * 64,
        "char_count": 12,
    }
    assert controller.calls == [("import_skill_archive", archive)]
    assert "z" * 128 not in response.text


def test_skill_import_rejects_first_raw_byte_over_limit() -> None:
    controller = RecordingController()
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            "/api/v1/skills/import",
            content=b"z" * 131_073,
            headers={**auth_headers(), "Content-Type": "application/zip"},
        )
    )

    assert response.status_code == 413
    assert response.json() == {"error": {"code": "skill_archive_too_large"}}
    assert controller.calls == []


@pytest.mark.parametrize(
    ("content", "extra_headers", "status", "code"),
    [
        (b"", {"Content-Type": "application/zip"}, 400, "invalid_skill_archive"),
        (b"zip", {}, 415, "unsupported_media_type"),
        (b"zip", {"Content-Type": "application/json"}, 415, "unsupported_media_type"),
        (
            b"zip",
            {"Content-Type": "application/zip", "Content-Encoding": "gzip"},
            415,
            "unsupported_content_encoding",
        ),
    ],
)
def test_skill_import_rejects_invalid_body_media_and_encoding(
    content: bytes,
    extra_headers: dict[str, str],
    status: int,
    code: str,
) -> None:
    controller = RecordingController()
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            "/api/v1/skills/import",
            content=content,
            headers={**auth_headers(), **extra_headers},
        )
    )

    assert response.status_code == status
    assert response.json() == {"error": {"code": code}}
    assert controller.calls == []


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("invalid_skill_archive", 400),
        ("unsafe_skill_archive", 400),
        ("skill_catalog_unavailable", 409),
        ("skill_already_exists", 409),
        ("controller_busy", 409),
        ("skill_install_failed", 500),
    ],
)
def test_skill_import_uses_route_specific_stable_error_mapping(
    code: str,
    status: int,
) -> None:
    controller = RecordingController(
        errors={"import_skill_archive": SessionControllerError(code)}
    )
    response = asyncio.run(
        request(
            make_app(controller),
            "POST",
            "/api/v1/skills/import",
            content=b"zip",
            headers={**auth_headers(), "Content-Type": "application/zip"},
        )
    )

    assert response.status_code == status
    assert response.json() == {"error": {"code": code}}


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

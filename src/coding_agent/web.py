from __future__ import annotations

from collections.abc import Iterator
import html
from importlib.resources import files
from importlib.resources.abc import Traversable
import json
import re
from threading import Lock
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictStr, field_validator
from starlette.background import BackgroundTask
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import Response, StreamingResponse

from .session import (
    SessionControllerError,
    SessionEvent,
    SessionRecord,
    SessionRunRecord,
)
from .session_controller import SessionController, SessionView
from .session_events import SessionUpdateBatch, SessionUpdateKind
from .budget import BudgetProfile
from .model_catalog import ModelCatalogView
from .run_mode import RunMode
from .skills import SkillCatalogDiagnostic, SkillCatalogView, SkillDescriptor
from .web_auth import WebAccessPolicy, WebAuthorizationError


MAX_MUTATION_BODY_BYTES = 131_072
_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_SKILL_IMPORT_PATH = "/api/v1/skills/import"
_CONTROLLER_ERROR_STATUS = {
    "invalid_message": 400,
    "model_not_available": 400,
    "invalid_skill_selection": 400,
    "duplicate_skill_selection": 400,
    "skill_selection_too_large": 400,
    "invalid_session_state": 409,
    "controller_busy": 409,
    "session_not_found": 404,
    "run_not_found": 404,
    "selected_skill_unavailable": 409,
    "controller_in_use": 409,
    "skill_catalog_unavailable": 503,
    "duplicate_skill_id": 503,
    "controller_closed": 503,
    "controller_degraded": 503,
    "controller_timeout": 503,
    "thread_start_failed": 503,
    "storage_unavailable": 503,
    "database_corrupt": 503,
    "schema_unsupported": 503,
    "session_delete_failed": 503,
    "session_deletion_recovery_failed": 503,
}
_EVENT_CURSOR_PATTERN = re.compile(r"[0-9]+\Z")
_ACCESS_TOKEN_MARKER = "__CODING_AGENT_ACCESS_TOKEN__"
_WORKSPACE_PATH_MARKER = "__CODING_AGENT_WORKSPACE_PATH__"
_DOCUMENT_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
        "object-src 'none'; base-uri 'none'; form-action 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_STATIC_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


class WebStreamLimitError(RuntimeError):
    def __init__(self, code: str = "stream_limit_reached") -> None:
        self.code = code
        super().__init__(code)


class _SsePermit:
    __slots__ = ("_limiter", "_run_id")

    def __init__(self, limiter: _SseConnectionLimiter, run_id: str) -> None:
        self._limiter = limiter
        self._run_id = run_id

    def close(self) -> None:
        self._limiter._release(self, self._run_id)


class _SseConnectionLimiter:
    def __init__(self, *, max_connections: int, max_per_run: int) -> None:
        if (
            type(max_connections) is not int
            or type(max_per_run) is not int
            or max_connections <= 0
            or max_per_run <= 0
            or max_per_run > max_connections
        ):
            raise ValueError("invalid SSE connection limits")
        self._max_connections = max_connections
        self._max_per_run = max_per_run
        self._lock = Lock()
        self._total = 0
        self._per_run: dict[str, int] = {}
        self._active_permits: set[_SsePermit] = set()

    def acquire(self, run_id: str) -> _SsePermit:
        with self._lock:
            per_run = self._per_run.get(run_id, 0)
            if self._total >= self._max_connections or per_run >= self._max_per_run:
                raise WebStreamLimitError()
            self._total += 1
            self._per_run[run_id] = per_run + 1
            permit = _SsePermit(self, run_id)
            self._active_permits.add(permit)
        return permit

    def _release(self, permit: _SsePermit, run_id: str) -> None:
        with self._lock:
            if permit not in self._active_permits:
                return
            self._active_permits.remove(permit)
            per_run = self._per_run[run_id] - 1
            self._total -= 1
            if per_run:
                self._per_run[run_id] = per_run
            else:
                del self._per_run[run_id]


class _CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: StrictStr
    model_id: StrictStr | None = None
    skill_ids: tuple[StrictStr, ...] = ()
    run_mode: RunMode = RunMode.MODIFY
    budget_profile: BudgetProfile = BudgetProfile.STANDARD

    @field_validator("run_mode", mode="before")
    @classmethod
    def accept_exact_run_mode(cls, value: object) -> object:
        if type(value) is str and value in {mode.value for mode in RunMode}:
            return RunMode(value)
        return value

    @field_validator("budget_profile", mode="before")
    @classmethod
    def accept_exact_budget_profile(cls, value: object) -> object:
        if type(value) is str and value in {
            profile.value for profile in BudgetProfile
        }:
            return BudgetProfile(value)
        return value

    @field_validator("skill_ids", mode="before")
    @classmethod
    def accept_json_array(cls, value: object) -> object:
        if type(value) is list and all(type(item) is str for item in value):
            return tuple(value)
        return value


class _FollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: StrictStr
    model_id: StrictStr | None = None
    run_mode: RunMode = RunMode.MODIFY
    budget_profile: BudgetProfile = BudgetProfile.STANDARD

    @field_validator("run_mode", mode="before")
    @classmethod
    def accept_exact_run_mode(cls, value: object) -> object:
        if type(value) is str and value in {mode.value for mode in RunMode}:
            return RunMode(value)
        return value

    @field_validator("budget_profile", mode="before")
    @classmethod
    def accept_exact_budget_profile(cls, value: object) -> object:
        if type(value) is str and value in {
            profile.value for profile in BudgetProfile
        }:
            return BudgetProfile(value)
        return value


class _SkillSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    skill_ids: tuple[StrictStr, ...]

    @field_validator("skill_ids", mode="before")
    @classmethod
    def accept_json_array(cls, value: object) -> object:
        if type(value) is list and all(type(item) is str for item in value):
            return tuple(value)
        return value


class _BoundedMutationBody:
    def __init__(self, app: ASGIApp, *, maximum_bytes: int) -> None:
        self._app = app
        self._maximum_bytes = maximum_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _MUTATION_METHODS:
            await self._app(scope, receive, send)
            return

        buffered: list[dict[str, Any]] = []
        total = 0
        while True:
            message = await receive()
            buffered.append(message)
            if message["type"] != "http.request":
                break
            total += len(message.get("body", b""))
            if total > self._maximum_bytes:
                while message.get("more_body", False):
                    message = await receive()
                code = (
                    "skill_archive_too_large"
                    if scope.get("path") == _SKILL_IMPORT_PATH
                    else "request_too_large"
                )
                response = _error_response(code, status_code=413)
                await response(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        index = 0

        async def replay_receive():
            nonlocal index
            if index < len(buffered):
                message = buffered[index]
                index += 1
                return message
            return await receive()

        await self._app(scope, replay_receive, send)


def _error_response(code: str, *, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code}},
    )


def _required_media_type(method: str, path: str) -> str | None:
    if method == "POST" and path == _SKILL_IMPORT_PATH:
        return "application/zip"
    if method == "DELETE":
        return None
    if method in _MUTATION_METHODS:
        return "application/json"
    return None


def _skill_import_error_status(code: str) -> int | None:
    return {
        "invalid_skill_archive": 400,
        "unsafe_skill_archive": 400,
        "skill_catalog_unavailable": 409,
        "skill_already_exists": 409,
        "controller_busy": 409,
        "skill_install_failed": 500,
    }.get(code)


def _serialize_session(record: SessionRecord) -> dict[str, object]:
    return {
        "session_id": record.session_id,
        "title": record.title,
        "status": record.status.value,
        "created_at_utc": record.created_at_utc,
        "updated_at_utc": record.updated_at_utc,
        "last_run_id": record.last_run_id,
        "next_sequence": record.next_sequence,
    }


def _serialize_run(record: SessionRunRecord) -> dict[str, object]:
    return {
        "run_id": record.run_id,
        "ordinal": record.ordinal,
        "status": record.status.value,
        "run_mode": record.run_mode.value,
        "budget_profile": record.budget_profile.value,
        "model_id": record.model_id,
        "started_at_utc": record.started_at_utc,
        "finished_at_utc": record.finished_at_utc,
        "agent_status": record.agent_status,
        "termination_reason": record.termination_reason,
        "audit_run_id": record.audit_run_id,
        "final_report": record.final_report,
    }


def _serialize_model_catalog(view: ModelCatalogView) -> dict[str, object]:
    return {
        "enabled": view.enabled,
        "status": view.status.value,
        "default_model_id": view.default_model_id,
        "model_ids": list(view.model_ids),
        "error_code": view.error_code,
    }


def _serialize_event(record: SessionEvent) -> dict[str, object]:
    return {
        "session_id": record.session_id,
        "run_id": record.run_id,
        "sequence": record.sequence,
        "kind": record.kind.value,
        "created_at_utc": record.created_at_utc,
        "data": record.data,
    }


def _serialize_session_view(
    view: SessionView, *, skill_ids: tuple[str, ...]
) -> dict[str, object]:
    return {
        "session": _serialize_session(view.session),
        "runs": [_serialize_run(run) for run in view.runs],
        "events": [_serialize_event(event) for event in view.events],
        "skill_ids": list(skill_ids),
    }


def _serialize_skill(descriptor: SkillDescriptor) -> dict[str, object]:
    return {
        "skill_id": descriptor.skill_id,
        "name": descriptor.name,
        "description": descriptor.description,
        "source": descriptor.source.value,
        "sha256": descriptor.sha256,
        "char_count": descriptor.char_count,
    }


def _serialize_skill_diagnostic(
    diagnostic: SkillCatalogDiagnostic,
) -> dict[str, str]:
    return {
        "code": diagnostic.code,
        "source": diagnostic.source.value,
        "entry_name": diagnostic.entry_name,
    }


def _serialize_skill_catalog(view: SkillCatalogView) -> dict[str, object]:
    return {
        "skills": [_serialize_skill(skill) for skill in view.skills],
        "diagnostics": [
            _serialize_skill_diagnostic(diagnostic)
            for diagnostic in view.diagnostics
        ],
        "usable": view.usable,
    }


def _parse_last_event_id(
    raw_headers: tuple[tuple[bytes, bytes], ...],
) -> int:
    values = tuple(
        value
        for name, value in raw_headers
        if name.lower() == b"last-event-id"
    )
    if not values:
        return 0
    if len(values) != 1:
        raise ValueError("invalid_event_cursor")
    try:
        decoded = values[0].decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("invalid_event_cursor") from None
    if _EVENT_CURSOR_PATTERN.fullmatch(decoded) is None:
        raise ValueError("invalid_event_cursor")
    return int(decoded)


def _event_frame(event) -> str:
    return (
        f"id: {event.sequence}\n"
        f"event: {event.kind.value}\n"
        f"data: {event.to_json()}\n\n"
    )


def _reset_frame(run_id: str, last_sequence: int) -> str:
    data = json.dumps(
        {"last_sequence": last_sequence, "run_id": run_id},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"event: reset_required\ndata: {data}\n\n"


def _iterate_sse(
    controller: SessionController,
    run_id: str,
    after_sequence: int,
    initial_batch: SessionUpdateBatch,
    permit: _SsePermit,
) -> Iterator[str]:
    try:
        cursor = after_sequence
        batch = initial_batch
        while True:
            if batch.reset_required:
                yield _reset_frame(run_id, batch.last_sequence)
                return
            for event in batch.events:
                yield _event_frame(event)
                cursor = event.sequence
                if event.kind is SessionUpdateKind.RUN_FINISHED:
                    return
            batch = controller.wait_for_updates(
                run_id,
                after_sequence=cursor,
                timeout_seconds=15.0,
            )
            if not batch.events and not batch.reset_required:
                yield ": keep-alive\n\n"
    except Exception:
        yield 'event: transport_error\ndata: {"code":"stream_unavailable"}\n\n'
    finally:
        permit.close()


class _PermitOwnedSseStream(Iterator[str]):
    def __init__(
        self,
        controller: SessionController,
        run_id: str,
        after_sequence: int,
        initial_batch: SessionUpdateBatch,
        permit: _SsePermit,
    ) -> None:
        self._permit = permit
        self._iterator = _iterate_sse(
            controller,
            run_id,
            after_sequence,
            initial_batch,
            permit,
        )

    def __iter__(self) -> _PermitOwnedSseStream:
        return self

    def __next__(self) -> str:
        return next(self._iterator)

    def close(self) -> None:
        try:
            self._iterator.close()
        finally:
            self._permit.close()


def _sse_stream(
    controller: SessionController,
    run_id: str,
    after_sequence: int,
    initial_batch: SessionUpdateBatch,
    permit: _SsePermit,
) -> _PermitOwnedSseStream:
    return _PermitOwnedSseStream(
        controller,
        run_id,
        after_sequence,
        initial_batch,
        permit,
    )


def create_web_app(
    *,
    controller: SessionController,
    access_policy: WebAccessPolicy,
    gui_root: Traversable | None = None,
) -> FastAPI:
    resource_root = (
        files("coding_agent").joinpath("web_static")
        if gui_root is None
        else gui_root
    )
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    sse_limiter = _SseConnectionLimiter(max_connections=4, max_per_run=2)
    app.add_middleware(
        _BoundedMutationBody,
        maximum_bytes=MAX_MUTATION_BODY_BYTES,
    )

    @app.exception_handler(RequestValidationError)
    def invalid_request(_request: Request, _error: RequestValidationError):
        return _error_response("invalid_request", status_code=400)

    @app.middleware("http")
    async def authorize_request(request: Request, call_next):
        is_api = request.url.path.startswith("/api/v1")
        try:
            access_policy.authorize(
                tuple(request.scope["headers"]),
                require_bearer=is_api,
            )
            required_media_type = _required_media_type(
                request.method,
                request.url.path,
            )
            if is_api and required_media_type is not None:
                media_type = request.headers.get("content-type", "").split(";", 1)[0]
                if media_type.strip().lower() != required_media_type:
                    response = _error_response(
                        "unsupported_media_type",
                        status_code=415,
                    )
                elif (
                    request.url.path == _SKILL_IMPORT_PATH
                    and request.headers.get("content-encoding", "").strip()
                ):
                    response = _error_response(
                        "unsupported_content_encoding",
                        status_code=415,
                    )
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        except WebAuthorizationError as error:
            status_code = 401 if error.code == "unauthorized" else 403
            response = _error_response(error.code, status_code=status_code)
        except SessionControllerError as error:
            status_code = _CONTROLLER_ERROR_STATUS.get(error.code)
            if status_code is None:
                response = _error_response(
                    "internal_server_error",
                    status_code=500,
                )
            else:
                response = _error_response(error.code, status_code=status_code)
        except Exception:
            response = _error_response("internal_server_error", status_code=500)
        if is_api:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def gui_document() -> Response:
        source = resource_root.joinpath("index.html").read_text(
            encoding="utf-8"
        )
        if (
            source.count(_ACCESS_TOKEN_MARKER) != 1
            or source.count(_WORKSPACE_PATH_MARKER) != 2
        ):
            raise RuntimeError("invalid GUI bootstrap resource")
        rendered = source.replace(
            _ACCESS_TOKEN_MARKER,
            html.escape(access_policy.token, quote=True),
        )
        workspace_path = html.escape(
            str(controller.workspace.resolve(strict=False)),
            quote=True,
        )
        rendered = rendered.replace(_WORKSPACE_PATH_MARKER, workspace_path)
        return Response(
            rendered,
            media_type="text/html",
            headers=_DOCUMENT_SECURITY_HEADERS,
        )

    @app.get("/app.js")
    def gui_script() -> Response:
        source = resource_root.joinpath("app.js").read_text(encoding="utf-8")
        return Response(
            source,
            media_type="text/javascript",
            headers=_STATIC_SECURITY_HEADERS,
        )

    @app.get("/styles.css")
    def gui_styles() -> Response:
        source = resource_root.joinpath("styles.css").read_text(
            encoding="utf-8"
        )
        return Response(
            source,
            media_type="text/css",
            headers=_STATIC_SECURITY_HEADERS,
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, object]:
        return {"schema_version": 1, "status": "ok"}

    @app.get("/api/v1/models")
    def list_models(
        refresh: Literal["false", "true"] = "false",
    ) -> dict[str, object]:
        return _serialize_model_catalog(
            controller.list_models(refresh=refresh == "true")
        )

    @app.post("/api/v1/sessions", status_code=201)
    def create_session(payload: _CreateSessionRequest) -> dict[str, str]:
        handle = controller.create_session(
            payload.message,
            skill_ids=payload.skill_ids,
            model_id=payload.model_id,
            run_mode=payload.run_mode,
            budget_profile=payload.budget_profile,
        )
        return {
            "session_id": handle.session_id,
            "run_id": handle.run_id,
            "run_mode": handle.run_mode.value,
            "budget_profile": handle.budget_profile.value,
            "model_id": handle.model_id,
        }

    @app.get("/api/v1/sessions")
    def list_sessions(
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> dict[str, object]:
        return {
            "sessions": [
                _serialize_session(session)
                for session in controller.list_sessions(limit=limit)
            ]
        }

    @app.get("/api/v1/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, object]:
        view = controller.get_session(session_id)
        skill_ids = controller.get_session_skills(session_id)
        return _serialize_session_view(view, skill_ids=skill_ids)

    @app.delete("/api/v1/sessions/{session_id}", response_model=None)
    async def delete_session(
        session_id: str,
        request: Request,
    ) -> dict[str, object] | JSONResponse:
        if await request.body():
            return _error_response("invalid_request", status_code=400)
        result = controller.delete_session(session_id)
        payload: dict[str, object] = {
            "session_id": result.session_id,
            "deleted": True,
            "cleanup_pending": result.cleanup_pending,
        }
        if result.cleanup_pending:
            payload["warning_code"] = "session_log_cleanup_pending"
        return payload

    @app.post("/api/v1/sessions/{session_id}/messages", status_code=202)
    def submit_message(
        session_id: str,
        payload: _FollowUpRequest,
    ) -> dict[str, str]:
        handle = controller.submit_message(
            session_id,
            payload.message,
            model_id=payload.model_id,
            run_mode=payload.run_mode,
            budget_profile=payload.budget_profile,
        )
        return {
            "session_id": handle.session_id,
            "run_id": handle.run_id,
            "run_mode": handle.run_mode.value,
            "budget_profile": handle.budget_profile.value,
            "model_id": handle.model_id,
        }

    @app.get("/api/v1/skills")
    def list_skills() -> dict[str, object]:
        return _serialize_skill_catalog(controller.list_skills())

    @app.post(_SKILL_IMPORT_PATH, status_code=201, response_model=None)
    async def import_skill(
        request: Request,
    ) -> dict[str, object] | JSONResponse:
        archive = await request.body()
        if not archive:
            return _error_response("invalid_skill_archive", status_code=400)
        try:
            descriptor = controller.import_skill_archive(archive)
        except SessionControllerError as exc:
            status_code = _skill_import_error_status(exc.code)
            if status_code is None:
                raise
            return _error_response(exc.code, status_code=status_code)
        return _serialize_skill(descriptor)

    @app.get("/api/v1/sessions/{session_id}/skills")
    def get_session_skills(session_id: str) -> dict[str, object]:
        return {"skill_ids": list(controller.get_session_skills(session_id))}

    @app.put("/api/v1/sessions/{session_id}/skills")
    def set_session_skills(
        session_id: str,
        payload: _SkillSelectionRequest,
    ) -> dict[str, object]:
        selected = controller.set_session_skills(session_id, payload.skill_ids)
        return {"skill_ids": list(selected)}

    @app.post("/api/v1/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict[str, str]:
        return {"result": controller.cancel(run_id).value}

    @app.get("/api/v1/runs/{run_id}/events")
    def stream_run_events(request: Request, run_id: str) -> StreamingResponse:
        try:
            after_sequence = _parse_last_event_id(tuple(request.scope["headers"]))
        except ValueError:
            return _error_response(  # type: ignore[return-value]
                "invalid_event_cursor",
                status_code=400,
            )
        try:
            permit = sse_limiter.acquire(run_id)
        except WebStreamLimitError as error:
            return _error_response(error.code, status_code=429)  # type: ignore[return-value]
        try:
            initial_batch = controller.read_updates(
                run_id,
                after_sequence=after_sequence,
            )
        except SessionControllerError as error:
            permit.close()
            if error.code == "invalid_session_state":
                return _error_response(  # type: ignore[return-value]
                    "invalid_event_cursor",
                    status_code=400,
                )
            raise
        except BaseException:
            permit.close()
            raise
        if after_sequence > initial_batch.last_sequence:
            permit.close()
            return _error_response(  # type: ignore[return-value]
                "invalid_event_cursor",
                status_code=400,
            )
        stream = _sse_stream(
            controller,
            run_id,
            after_sequence,
            initial_batch,
            permit,
        )
        try:
            return StreamingResponse(
                stream,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-store",
                    "X-Accel-Buffering": "no",
                    "X-Content-Type-Options": "nosniff",
                },
                background=BackgroundTask(stream.close),
            )
        except BaseException:
            stream.close()
            raise

    return app

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import socket
import sys

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coding_agent.session import (
    PersistedSessionEventKind,
    SessionEvent,
    SessionRecord,
    SessionRunStatus,
    SessionStatus,
)
from coding_agent.session_controller import SessionView
from coding_agent.web import create_web_app
from coding_agent.web_auth import WebAccessPolicy
from tests.web_support import (
    TIMESTAMP,
    RecordingController,
    make_run_record,
    make_skill_view,
)


FIXTURE_TOKEN = "local-visual-fixture-token"


def _event(
    *,
    session_id: str,
    run_id: str,
    sequence: int,
    kind: PersistedSessionEventKind,
    data: dict[str, object],
) -> SessionEvent:
    return SessionEvent(
        session_id=session_id,
        run_id=run_id,
        sequence=sequence,
        kind=kind,
        created_at_utc=TIMESTAMP,
        data=data,  # type: ignore[arg-type]
    )


def _view(
    index: int,
    title: str,
    run_status: SessionRunStatus,
) -> SessionView:
    session_id = f"{index}" * 32
    run_id = f"{chr(96 + index)}" * 32
    active_status = {
        SessionRunStatus.RUNNING: SessionStatus.RUNNING,
        SessionRunStatus.CANCELLING: SessionStatus.CANCELLING,
    }.get(run_status, SessionStatus.IDLE)
    events = (
        _event(
            session_id=session_id,
            run_id=run_id,
            sequence=1,
            kind=PersistedSessionEventKind.USER_MESSAGE,
            data={"content": "检查这个演示工作区，并给出可验证的修改。"},
        ),
        _event(
            session_id=session_id,
            run_id=run_id,
            sequence=2,
            kind=PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED,
            data={
                "content": (
                    "我已经读取了相关文件，正在保持修改范围最小。\n\n"
                    "```python\n"
                    "def verified_change() -> str:\n"
                    "    return \"ready\"\n"
                    "```\n\n"
                    "这里是一段较长的说明，用于检查中央对话区的宽度、换行、滚动和代码块展示。"
                    * 3
                )
            },
        ),
        _event(
            session_id=session_id,
            run_id=run_id,
            sequence=3,
            kind=PersistedSessionEventKind.TOOL_ACTIVITY,
            data={
                "tool_name": "read_file",
                "status": "ok",
                "duration_ms": 18,
                "truncated": False,
                "exit_code": None,
                "safe_error_code": None,
                "changed_paths": [],
            },
        ),
        _event(
            session_id=session_id,
            run_id=run_id,
            sequence=4,
            kind=PersistedSessionEventKind.VERIFICATION_ACTIVITY,
            data={
                "status": "passed",
                "source": "user_verify",
                "exit_code": 0,
                "timed_out": False,
                "truncated": False,
                "duration_ms": 124,
                "validation_index": 1,
                "error_code": None,
            },
        ),
    )
    session = SessionRecord(
        session_id=session_id,
        title=title,
        status=active_status,
        created_at_utc=TIMESTAMP,
        updated_at_utc=TIMESTAMP,
        last_run_id=run_id,
        next_sequence=len(events) + 1,
    )
    run = replace(
        make_run_record(
            run_id=run_id,
            session_id=session_id,
            status=run_status,
        ),
        ordinal=1,
    )
    return SessionView(session=session, runs=(run,), events=events)


class VisualFixtureController(RecordingController):
    def __init__(self) -> None:
        views = (
            _view(1, "等待中的代码任务", SessionRunStatus.QUEUED),
            _view(2, "正在分析测试失败", SessionRunStatus.RUNNING),
            _view(3, "正在安全取消", SessionRunStatus.CANCELLING),
            _view(4, "已验证的修改", SessionRunStatus.SUCCEEDED),
            _view(5, "验证失败的修改", SessionRunStatus.FAILED),
        )
        super().__init__(
            sessions=tuple(view.session for view in views),
            session_view=views[0],
            skill_view=make_skill_view(),
            selected_skill_ids=("python-testing",),
        )
        self._views = {view.session.session_id: view for view in views}

    def get_session(self, session_id: str) -> SessionView:
        self._record("get_session", session_id)
        return self._views[session_id]


def main() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = int(listener.getsockname()[1])
    app = create_web_app(
        controller=VisualFixtureController(),  # type: ignore[arg-type]
        access_policy=WebAccessPolicy(token=FIXTURE_TOKEN, port=port),
    )
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="critical",
        access_log=False,
        server_header=False,
        proxy_headers=False,
    )
    print(f"http://127.0.0.1:{port}/")
    try:
        uvicorn.Server(config).run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()

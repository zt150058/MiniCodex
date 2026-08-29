# Session Lifecycle and Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add workspace-local durable multi-run sessions, one cooperative background Agent run, and a bounded UI-safe event boundary without changing the accepted CLI, provider, safety, or verification behavior.

**Architecture:** Task 19 creates immutable session records, a protected SQLite repository, and a workspace process lease. Task 20 renders safe prior history into one initial user message, adds narrow Agent cancellation and confirmed-text hooks, exposes a bounded event hub, and coordinates the existing production runtime through one non-daemon worker. SQLite is UI history, JSONL remains audit, and no provider or SDK object crosses into session modules.

**Tech Stack:** Python 3.11+, standard-library `sqlite3`, `threading`, `msvcrt`/`fcntl`, dataclasses, pytest, existing OpenAI SDK only at existing adapter boundaries.

**Spec:** `docs/superpowers/specs/2026-08-29-session-lifecycle-design.md`

## Global Constraints

- Execute in `D:\code\coding_agent` on the current `main` workspace unless the user gives a newer direct instruction.
- Do not create a branch or worktree. Do not access a remote repository.
- Do not stage, commit, or push until the user reviews the completed milestone and explicitly authorizes it.
- Do not call a real model endpoint or read a real API key. All new tests are offline.
- Do not add a production dependency, Agent framework, ORM, web framework, HTTP server, Skill system, MCP integration, GUI, or transport endpoint.
- Keep `ModelClient.complete(ModelRequest) -> ModelResponse`, provider request mapping, message JSON, tool schemas, Task 8 safety, Task 11 success, JSONL privacy, `FinalReport`, CLI arguments, and CLI exit behavior compatible.
- Persist no provider continuation, reasoning, encrypted content, instruction body, tool arguments, tool output, stdout, stderr, raw exception body, or provisional stream text.
- A session database is workspace-local at `.coding-agent/sessions.sqlite3`; a live controller holds `.coding-agent/sessions.lock`.
- Exactly one run may be queued, running, or cancelling in a workspace database and in a controller.
- Cooperative cancellation never force-kills a thread or an admitted context-preparation, model, tool, or verification operation.
- Task 20 remains `进行中` at the final review checkpoint.
- Every production behavior uses one RED command, a verified expected failure, minimal GREEN, focused regression, and only then refactoring.
- For a reproducible unexpected failure, invoke `superpowers:systematic-debugging` before editing production code.
- Before reporting success, invoke `superpowers:verification-before-completion` and use fresh command output.

---

## Locked file map

### Create

- `src/coding_agent/session.py` — domain enums, immutable records, stable errors, title, safe terminal summary, and privacy-preserving persisted-report projection.
- `src/coding_agent/session_store.py` — workspace lease, SQLite schema, transactions, strict row decoding, and incomplete-run recovery.
- `src/coding_agent/session_events.py` — UI-safe update types, exact payload validation, bounded event hub, replay, and wait.
- `src/coding_agent/session_controller.py` — single-worker lifecycle, submit/cancel/wait/shutdown, stream buffering, and degradation.
- `src/coding_agent/session_runtime.py` — narrative renderer, executor protocol, outcome types, and production adapter over shared composition.
- `tests/test_session.py` — domain, title, summary, bounds, and representation tests.
- `tests/test_session_store.py` — SQLite, lease, state transition, recovery, corruption, and path tests.
- `tests/test_session_events.py` — safe schema, sequence, count/byte limit, replay, wait, and privacy tests.
- `tests/test_session_runtime.py` — narrative, shared composition, safe persisted-report outcome, and offline boundary tests.
- `tests/test_session_controller.py` — thread ownership, sequential follow-up, streaming lifecycle, cancellation, failure, and shutdown tests.

### Modify additively

- `src/coding_agent/state.py` — `AgentState.start(..., *, initial_user_message: str | None = None)`.
- `src/coding_agent/agent.py` — additive initial message, cancellation check, and confirmed-text callback constructor inputs.
- `src/coding_agent/logging.py` — optional post-flush `RunEvent` observer with ordinary-exception isolation.
- `src/coding_agent/app.py` — extract and reuse accepted construction/execution while preserving `run_application`.
- `tests/test_agent_loop.py` — initial message, confirmed text, and cancellation boundary tests.
- `tests/test_logging.py` — post-flush observer order and failure isolation.
- `tests/test_app.py` — unchanged public application behavior through shared composition.
- `TASKS.md` — add Tasks 19–21 and update only the active/completed status required by the execution checkpoint.
- `DESIGN.md` — after all behavior is green, record delivered session/controller boundaries and still-deferred transport/GUI/Skill/MCP scope.

### Must remain unchanged

- `src/coding_agent/messages.py`
- `src/coding_agent/model.py`
- `src/coding_agent/context.py`
- `src/coding_agent/termination.py`
- `src/coding_agent/verification.py`
- `src/coding_agent/safety.py`
- `src/coding_agent/tools/**`
- `src/coding_agent/openai_client.py`
- `src/coding_agent/chat_completions_client.py`
- `src/coding_agent/config.py`
- `src/coding_agent/cli.py`
- `src/coding_agent/report.py`
- `src/coding_agent/instructions.py`
- `src/coding_agent/streaming.py`
- `pyproject.toml`
- accepted Task 1–18 tests except the three explicitly listed test files.

## Locked public types and signatures

The implementation must use these names consistently:

```python
# session.py
def utc_now() -> datetime: ...
def uuid4_hex() -> str: ...

class SessionStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"

class SessionRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"

class PersistedSessionEventKind(StrEnum):
    USER_MESSAGE = "user_message"
    RUN_QUEUED = "run_queued"
    RUN_STARTED = "run_started"
    ASSISTANT_TEXT_COMMITTED = "assistant_text_committed"
    TOOL_ACTIVITY = "tool_activity"
    VERIFICATION_ACTIVITY = "verification_activity"
    CANCELLATION_REQUESTED = "cancellation_requested"
    RUN_FINISHED = "run_finished"
    RUN_RECOVERED = "run_recovered"

class SessionNarrativeKind(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    RUN_SUMMARY = "run_summary"

class SessionError(RuntimeError):
    code: str

class SessionStoreError(SessionError): ...
class SessionControllerError(SessionError): ...

@dataclass(frozen=True, slots=True)
class SessionRecord: ...

@dataclass(frozen=True, slots=True)
class SessionRunRecord: ...

@dataclass(frozen=True, slots=True)
class SessionEvent: ...

@dataclass(frozen=True, slots=True)
class SessionSubmission:
    session: SessionRecord
    user_event: SessionEvent
    run: SessionRunRecord

@dataclass(frozen=True, slots=True)
class SessionNarrativeEntry: ...

@dataclass(frozen=True, slots=True)
class NewSessionEvent: ...

@dataclass(frozen=True, slots=True)
class SessionRunResult:
    run_id: str
    status: SessionRunStatus
    agent_status: str | None
    termination_reason: str | None
    audit_run_id: str | None
    safe_summary: JSONObject = field(repr=False)
    final_report: JSONObject | None = field(default=None, repr=False)

def make_safe_run_summary(
    report: JSONObject | None,
    *,
    status: str,
    termination_reason: str | None,
) -> JSONObject: ...

def make_persisted_run_report(report: JSONObject) -> JSONObject: ...
```

```python
# session_store.py
class WorkspaceSessionLease:
    @classmethod
    def acquire(cls, workspace: Path) -> WorkspaceSessionLease: ...

    @property
    def workspace(self) -> Path: ...

    def close(self) -> None: ...

class SessionStore(Protocol):
    @property
    def workspace(self) -> Path: ...

    def initialize(self) -> None: ...
    def create_session(self, message: str) -> SessionSubmission: ...
    def get_session(self, session_id: str) -> SessionRecord: ...
    def get_run(self, run_id: str) -> SessionRunRecord: ...
    def list_sessions(self, *, limit: int = 50) -> tuple[SessionRecord, ...]: ...
    def list_runs(self, session_id: str) -> tuple[SessionRunRecord, ...]: ...
    def submit_message(self, session_id: str, message: str) -> SessionSubmission: ...
    def start_run(self, run_id: str) -> SessionRunRecord: ...
    def append_event(self, event: NewSessionEvent) -> SessionEvent: ...
    def request_cancellation(self, run_id: str) -> SessionRunRecord: ...
    def finish_run(self, result: SessionRunResult) -> SessionRunRecord: ...
    def load_events(self, session_id: str, *, after_sequence: int = 0) -> tuple[SessionEvent, ...]: ...
    def load_narrative(self, session_id: str) -> tuple[SessionNarrativeEntry, ...]: ...
    def recover_incomplete_runs(self) -> tuple[SessionRunRecord, ...]: ...

class SQLiteSessionStore: ...
```

```python
# agent.py additions; run(task) remains unchanged
ConfirmedTextHandler: TypeAlias = Callable[[str], None]
CancellationCheck: TypeAlias = Callable[[], bool]

AgentRunner(
    ...,
    initial_user_message: str | None = None,
    cancellation_requested: CancellationCheck | None = None,
    confirmed_text_handler: ConfirmedTextHandler | None = None,
)
```

```python
# session_events.py
class SessionUpdateKind(StrEnum): ...
@dataclass(frozen=True, slots=True)
class SessionUpdate:
    schema_version: int
    session_id: str
    run_id: str
    sequence: int
    timestamp_utc: str
    kind: SessionUpdateKind
    data: JSONObject = field(repr=False)

    def to_dict(self) -> JSONObject: ...
    def to_json(self) -> str: ...
@dataclass(frozen=True, slots=True)
class SessionUpdateBatch: ...
class SessionEventHub: ...
```

```python
# session_runtime.py
@dataclass(frozen=True, slots=True)
class SessionRunRequest: ...
@dataclass(frozen=True, slots=True)
class SessionRunOutcome: ...
class SessionNarrativeRenderer: ...
class SessionRunExecutor(Protocol):
    @property
    def workspace(self) -> Path: ...

    def execute(
        self,
        request: SessionRunRequest,
        *,
        stream_handler: ModelStreamHandler,
        confirmed_text_handler: ConfirmedTextHandler,
        cancellation_requested: CancellationCheck,
        run_event_handler: RunEventObserver,
    ) -> SessionRunOutcome: ...
class AgentSessionRunExecutor: ...
```

```python
# session_controller.py
class CancellationResult(StrEnum):
    REQUESTED = "requested"
    ALREADY_REQUESTED = "already_requested"
    ALREADY_FINISHED = "already_finished"

@dataclass(frozen=True, slots=True)
class RunHandle: ...
@dataclass(frozen=True, slots=True)
class SessionView: ...

class WorkerThread(Protocol):
    @property
    def daemon(self) -> bool: ...
    @property
    def name(self) -> str: ...
    def start(self) -> None: ...
    def join(self, timeout: float | None = None) -> None: ...
    def is_alive(self) -> bool: ...

ThreadFactory: TypeAlias = Callable[[Callable[[], None], str], WorkerThread]

def default_thread_factory(target: Callable[[], None], name: str) -> WorkerThread: ...

class SessionController:
    @classmethod
    def open(
        cls,
        workspace: Path,
        executor: SessionRunExecutor,
        *,
        sensitive_values: tuple[str, ...] = (),
        utc_clock: Callable[[], datetime] = utc_now,
        thread_factory: ThreadFactory = default_thread_factory,
    ) -> SessionController: ...

    def create_session(self, first_message: str) -> RunHandle: ...
    def submit_message(self, session_id: str, message: str) -> RunHandle: ...
    def get_session(self, session_id: str) -> SessionView: ...
    def list_sessions(self, *, limit: int = 50) -> tuple[SessionRecord, ...]: ...
    def cancel(self, run_id: str) -> CancellationResult: ...
    def read_updates(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
    ) -> SessionUpdateBatch: ...
    def wait_for_updates(
        self,
        run_id: str,
        *,
        after_sequence: int,
        timeout_seconds: float,
    ) -> SessionUpdateBatch: ...
    def wait_for_run(
        self,
        run_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> SessionRunRecord: ...
    def shutdown(self, *, timeout_seconds: float) -> bool: ...
```

### Task 0: Baseline, approved task definitions, and active status

**Files:**
- Read: `AGENTS.md`, `DESIGN.md`, `TASKS.md`, the specification, this plan, and all files in the locked map.
- Modify after baseline only: `TASKS.md`

**Interfaces:**
- Consumes: accepted Task 1–18 repository at committed HEAD.
- Produces: an explicit Task 19–21 roadmap with only Task 19 active.

- [ ] **Step 1: Verify repository identity and cleanliness**

Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git log -3 --oneline
git status --short --untracked-files=all
git diff --check
```

Expected: root is `D:/code/coding_agent`, branch is the user-approved current branch, HEAD contains the accepted Task 18 commit, status contains only the approved spec/plan when those documents are intentionally uncommitted, and whitespace check exits 0. Any other source/test modification is a stop condition.

- [ ] **Step 2: Run the fresh Task 1–18 baseline**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .\.pytest-tmp\milestone-b-baseline
```

Expected: exit 0 with the real pass/fail/skip/warning counts recorded. Any failure stops execution before `TASKS.md` changes.

- [ ] **Step 3: Append exact task definitions and update status**

Add `Task 19: 会话领域与 SQLite 持久化`, `Task 20: 单活动运行控制器与 GUI 安全事件桥`, and `Task 21: 声明式 Skill 目录与选择` using the approved spec boundaries and acceptance criteria. Change Task 18 from `进行中` to `已完成`; set Task 19 to `进行中`; leave Tasks 20–21 `未开始`. Assert exactly one `进行中` value.

Run:

```powershell
rg -n "状态：`进行中`|## 19\.|## 20\.|## 21\." TASKS.md
git diff --check
```

Expected: exactly Task 19 is active, Tasks 19–21 exist once, and whitespace check exits 0.

**Acceptance:** baseline is fresh and green, the committed Task 18 is closed, and no production behavior changed.

### Task 1: Session domain, title, strict records, and safe summaries

**Files:**
- Create: `src/coding_agent/session.py`
- Create: `tests/test_session.py`

**Interfaces:**
- Consumes: `JSONObject` and `AgentStatus`/`TerminationReason` string values; no SQLite or controller type.
- Produces: every immutable domain value consumed by `session_store.py`, `session_runtime.py`, and `session_controller.py`.

- [ ] **Step 1: Write the title and error RED tests**

Create `tests/test_session.py` with this first slice:

```python
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from coding_agent.session import SessionError, make_session_title, utc_now, uuid4_hex


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("  Fix   the parser  \nignore this line", "Fix the parser"),
        ("\n\n修复 Windows 路径\n第二行", "修复 Windows 路径"),
        ("x" * 80, "x" * 80),
        ("x" * 81, "x" * 79 + "…"),
    ],
)
def test_make_session_title_is_deterministic(message: str, expected: str) -> None:
    assert make_session_title(message) == expected


def test_default_clock_and_id_factories_produce_strict_domain_values() -> None:
    now = utc_now()
    identifier = uuid4_hex()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    assert len(identifier) == 32
    assert identifier == identifier.lower()
    assert all(character in "0123456789abcdef" for character in identifier)


@pytest.mark.parametrize("message", ["", "   ", "\n\t"])
def test_make_session_title_rejects_empty_message(message: str) -> None:
    with pytest.raises(SessionError) as captured:
        make_session_title(message)
    assert captured.value.code == "invalid_message"
    assert message not in repr(captured.value)
```

- [ ] **Step 2: Run RED for the missing domain module**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-domain-red1
```

Expected: exit 1 during collection because `coding_agent.session` does not exist. The test file itself must compile.

- [ ] **Step 3: Implement only stable errors and title generation**

Create `src/coding_agent/session.py` with `SessionError`, the `invalid_message` code validation, `_require_text`, `utc_now`, `uuid4_hex`, and `make_session_title`. Add the shown `timedelta` test import. `utc_now` returns `datetime.now(timezone.utc)` and `uuid4_hex` returns `uuid.uuid4().hex`. `SessionError.__str__` and `repr` expose only the stable code. `make_session_title` chooses the first non-empty line, collapses whitespace with `" ".join(line.split())`, and applies the exact 80-code-point rule from the test.

- [ ] **Step 4: Run GREEN and domain regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-domain-green1
.\.venv\Scripts\python.exe -m pytest tests/test_messages.py tests/test_agent_loop.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-domain-regression1
```

Expected: both commands exit 0; record actual counts.

- [ ] **Step 5: Add RED tests for exact enums and immutable records**

Append tests that construct records and reject malformed identities, sequences, timestamps, statuses, payloads, and content sizes:

```python
from dataclasses import FrozenInstanceError

from coding_agent.session import (
    NewSessionEvent,
    PersistedSessionEventKind,
    SessionNarrativeKind,
    SessionEvent,
    SessionNarrativeEntry,
    SessionRecord,
    SessionRunRecord,
    SessionRunResult,
    SessionRunStatus,
    SessionStatus,
    SessionSubmission,
)

SESSION_ID = "1" * 32
RUN_ID = "2" * 32
NOW = "2026-08-29T08:00:00.000000Z"


def test_domain_records_are_immutable_and_payload_repr_is_hidden() -> None:
    event = SessionEvent(
        session_id=SESSION_ID,
        run_id=RUN_ID,
        sequence=1,
        kind=PersistedSessionEventKind.USER_MESSAGE,
        created_at_utc=NOW,
        data={"content": "private conversation"},
    )
    session = SessionRecord(
        session_id=SESSION_ID,
        title="Fix parser",
        status=SessionStatus.RUNNING,
        created_at_utc=NOW,
        updated_at_utc=NOW,
        last_run_id=RUN_ID,
        next_sequence=3,
    )
    run = SessionRunRecord(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        ordinal=1,
        status=SessionRunStatus.QUEUED,
        user_event_sequence=1,
        started_at_utc=None,
        finished_at_utc=None,
        agent_status=None,
        termination_reason=None,
        audit_run_id=None,
        final_report=None,
    )
    submission = SessionSubmission(session=session, user_event=event, run=run)
    assert submission.run.status is SessionRunStatus.QUEUED
    assert "private conversation" not in repr(event)
    with pytest.raises(FrozenInstanceError):
        session.title = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_id", "not-a-uuid"),
        ("session_id", "A" * 32),
        ("sequence", 0),
        ("sequence", True),
        ("created_at_utc", "2026-08-29"),
    ],
)
def test_session_event_rejects_invalid_invariants(field: str, value: object) -> None:
    values: dict[str, object] = {
        "session_id": SESSION_ID,
        "run_id": RUN_ID,
        "sequence": 1,
        "kind": PersistedSessionEventKind.RUN_STARTED,
        "created_at_utc": NOW,
        "data": {"status": "running"},
    }
    values[field] = value
    with pytest.raises((TypeError, ValueError)):
        SessionEvent(**values)  # type: ignore[arg-type]


def test_new_event_and_run_result_hide_sensitive_payloads() -> None:
    event = NewSessionEvent(
        session_id=SESSION_ID,
        run_id=RUN_ID,
        kind=PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED,
        data={"content": "secret assistant text"},
    )
    result = SessionRunResult(
        run_id=RUN_ID,
        status=SessionRunStatus.SUCCEEDED,
        agent_status="success",
        termination_reason=None,
        audit_run_id="3" * 32,
        safe_summary={
            "status": "success",
            "exit_code": 0,
            "termination_reason": None,
            "changed_paths": [],
            "verification_status": "passed",
            "mutation_index": 0,
            "validation_index": 0,
            "logical_model_calls": 1,
            "provider_attempts": 1,
            "tool_calls": 0,
            "verification_attempts": 1,
        },
        final_report=None,
    )
    assert "secret assistant text" not in repr(event)
    assert "logical_model_calls" not in repr(result)


def test_narrative_entry_allows_only_safe_kinds_and_text() -> None:
    entry = SessionNarrativeEntry(
        run_id=RUN_ID,
        kind=SessionNarrativeKind.ASSISTANT,
        content="Finished the requested change.",
    )
    assert entry.kind.value == "assistant"
    assert "Finished" not in repr(entry)
```

- [ ] **Step 6: Run record RED**

Run the new tests by name. Expected: exit 1 because the enums and records are not defined; the earlier title tests remain green.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session.py -k "domain_records or invalid_invariants or new_event or narrative_entry" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-domain-red2
```

- [ ] **Step 7: Implement exact domain values**

Add the enums and frozen slot dataclasses with the fields locked above. Add `SessionNarrativeKind` values `USER`, `ASSISTANT`, and `RUN_SUMMARY`. Validate lowercase 32-character hexadecimal IDs, positive non-boolean integers, UTC timestamps ending in `Z`, exact enum instances, JSON-compatible payloads via a local normalizer, terminal/nonterminal run field combinations, and the four size limits. Mark `data`, `content`, and `final_report` fields `repr=False`.

- [ ] **Step 8: Run record GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-domain-green2
.\.venv\Scripts\python.exe -m pytest tests/test_messages.py tests/test_agent_loop.py tests/test_report.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-domain-regression2
```

Expected: exit 0 for both commands with actual counts recorded.

- [ ] **Step 9: Add safe terminal-summary RED tests**

Add one parameterized test proving stable fields and forbidden content:

```python
from coding_agent.session import make_safe_run_summary


def test_safe_run_summary_contains_only_accepted_terminal_facts() -> None:
    report = {
        "status": "success",
        "exit_code": 0,
        "termination_reason": None,
        "changed_paths": ["src/a.py"],
        "mutation_index": 1,
        "validation_index": 1,
        "verification": {
            "status": "passed",
            "validation_index": 1,
            "stdout": "must not persist",
        },
        "logical_model_calls": 2,
        "provider_attempts": 3,
        "tool_calls": 4,
        "verification_attempts": 1,
        "sensitive": "must not persist",
    }
    summary = make_safe_run_summary(
        report,
        status="success",
        termination_reason=None,
    )
    assert summary == {
        "status": "success",
        "exit_code": 0,
        "termination_reason": None,
        "changed_paths": ["src/a.py"],
        "verification_status": "passed",
        "mutation_index": 1,
        "validation_index": 1,
        "logical_model_calls": 2,
        "provider_attempts": 3,
        "tool_calls": 4,
        "verification_attempts": 1,
    }
    rendered = str(summary)
    assert "stdout" not in rendered
    assert "sensitive" not in rendered
```

Run RED, implement `make_safe_run_summary(report, *, status, termination_reason)` as the exact eleven-key allowlist projection with strict required-type validation and null unavailable counters, then run GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session.py::test_safe_run_summary_contains_only_accepted_terminal_facts -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-domain-red3
.\.venv\Scripts\python.exe -m pytest tests/test_session.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-domain-green3
```

Expected RED: missing `make_safe_run_summary`. Expected GREEN: all domain tests pass. Run `tests/test_report.py` again after GREEN.

- [ ] **Step 10: Add safe persisted-report RED tests**

Append an exact allowlist test using a real-shaped report dictionary:

```python
from coding_agent.session import make_persisted_run_report


def test_persisted_run_report_excludes_conversation_and_command_evidence() -> None:
    report = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "status": "success",
        "exit_code": 0,
        "completion": {"text": "private completion", "original_chars": 18, "truncated": False},
        "termination_reason": None,
        "failure_reason": "private failure",
        "changed_paths": ["src/a.py"],
        "mutation_index": 1,
        "validation_index": 1,
        "verification": {
            "status": "passed",
            "source": "user",
            "command": "private verify command",
            "exit_code": 0,
            "timed_out": False,
            "truncated": False,
            "duration_ms": 25,
            "validation_index": 1,
            "stdout": {"text": "private stdout", "original_chars": 14, "truncated": False},
            "stderr": {"text": "private stderr", "original_chars": 14, "truncated": False},
            "error_code": None,
        },
        "logical_model_calls": 2,
        "provider_attempts": 3,
        "tool_calls": 4,
        "verification_attempts": 1,
        "context_compressions": 1,
        "token_usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "responses_with_usage": 2,
            "responses_without_usage": 0,
        },
        "elapsed_ms": 250,
        "log_failure_code": None,
        "log_path": ".coding-agent/logs/" + RUN_ID + ".jsonl",
    }
    persisted = make_persisted_run_report(report)
    assert set(persisted) == {
        "schema_version", "run_id", "status", "exit_code", "termination_reason",
        "changed_paths", "mutation_index", "validation_index", "verification",
        "logical_model_calls", "provider_attempts", "tool_calls",
        "verification_attempts", "context_compressions", "token_usage",
        "elapsed_ms", "log_failure_code", "log_path",
    }
    assert set(persisted["verification"]) == {
        "status", "source", "exit_code", "timed_out", "truncated",
        "duration_ms", "validation_index", "error_code",
    }
    raw = json.dumps(persisted, ensure_ascii=False)
    for forbidden in (
        "private completion", "private failure", "private verify command",
        "private stdout", "private stderr", "completion", "failure_reason",
        "command", "stdout", "stderr",
    ):
        assert forbidden not in raw
```

Add parameterized cases for a non-object report, missing allowlisted fields, boolean counters, negative counters, invalid status/exit-code combinations, changed paths that are absolute or contain `..`, malformed `verification`/`token_usage`, non-relative or mismatched `log_path`, and non-JSON values. Each case must raise `TypeError` or `ValueError` without rendering the rejected value.

- [ ] **Step 11: Run persisted-report RED, implement the exact projection, and run GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session.py -k "persisted_run_report" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-domain-red4
.\.venv\Scripts\python.exe -m pytest tests/test_session.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-domain-green4
.\.venv\Scripts\python.exe -m pytest tests/test_report.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-report-regression
```

Expected RED: import failure for `make_persisted_run_report`. Implement the exact top-level, verification, and token-usage projections locked in the specification; validate a normalized relative `.coding-agent/logs/<run_id>.jsonl` path and copy only allowlisted scalar/list values. Expected GREEN: all domain and report regression tests pass, and the persisted projection contains no conversation or command evidence.

**Acceptance:** Task 19 has stable provider-neutral domain values, deterministic titles, bounded content, safe summaries, a strict privacy-preserving persisted report projection, and no database or thread behavior yet.

### Task 2: Protected SQLite store, workspace lease, transitions, and recovery

**Files:**
- Create: `src/coding_agent/session_store.py`
- Create: `tests/test_session_store.py`
- Modify after Task 19 acceptance: `TASKS.md`

**Interfaces:**
- Consumes: all Task 1 records and `scrub_text(value, sensitive_values)` from `logging.py`.
- Produces: `WorkspaceSessionLease`, `SessionStore`, and `SQLiteSessionStore` for Task 20.

The constructor is locked as:

```python
SQLiteSessionStore(
    workspace: Path,
    *,
    utc_clock: Callable[[], datetime] = utc_now,
    id_factory: Callable[[], str] = uuid4_hex,
    sensitive_values: tuple[str, ...] = (),
    busy_timeout_ms: int = 5_000,
)
```

#### Cycle 2A: internal path, schema, and lease

- [ ] **Step 1: Write path/schema RED tests**

Create these tests using only `tmp_path`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from coding_agent.session import (
    NewSessionEvent,
    PersistedSessionEventKind,
    SessionRunResult,
    SessionRunStatus,
    SessionStatus,
    SessionStoreError,
    make_safe_run_summary,
)
from coding_agent.session_store import SQLiteSessionStore, WorkspaceSessionLease


NOW = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)


def persisted_failed_report(
    audit_run_id: str,
    reason: str = "empty_model_response",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": audit_run_id,
        "status": "failed",
        "exit_code": 1,
        "termination_reason": reason,
        "changed_paths": [],
        "mutation_index": 0,
        "validation_index": None,
        "verification": {
            "status": "not_run",
            "source": None,
            "exit_code": None,
            "timed_out": False,
            "truncated": False,
            "duration_ms": None,
            "validation_index": None,
            "error_code": None,
        },
        "logical_model_calls": 0,
        "provider_attempts": 0,
        "tool_calls": 0,
        "verification_attempts": 0,
        "context_compressions": 0,
        "token_usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "responses_with_usage": 0,
            "responses_without_usage": 0,
        },
        "elapsed_ms": 1,
        "log_failure_code": None,
        "log_path": f".coding-agent/logs/{audit_run_id}.jsonl",
    }


def test_initialize_creates_versioned_wal_database(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    assert store.workspace == tmp_path.resolve(strict=True)
    store.initialize()
    database = tmp_path / ".coding-agent" / "sessions.sqlite3"
    assert database.is_file()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"sessions", "session_runs", "session_events"} <= names
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_workspace_lease_is_exclusive_and_reacquirable(tmp_path: Path) -> None:
    first = WorkspaceSessionLease.acquire(tmp_path)
    assert first.workspace == tmp_path.resolve(strict=True)
    try:
        with pytest.raises(SessionStoreError) as captured:
            WorkspaceSessionLease.acquire(tmp_path)
        assert captured.value.code == "controller_in_use"
    finally:
        first.close()
    second = WorkspaceSessionLease.acquire(tmp_path)
    second.close()


def test_store_rejects_reparse_internal_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    internal = tmp_path / ".coding-agent"
    try:
        internal.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.fail(f"target Windows environment must allow this test: {exc}")
    with pytest.raises(SessionStoreError) as captured:
        SQLiteSessionStore(tmp_path).initialize()
    assert captured.value.code == "storage_unavailable"
    assert not (outside / "sessions.sqlite3").exists()
```

- [ ] **Step 2: Verify schema RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_store.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-store-red1
```

Expected: exit 1 because `session_store.py` is absent. The symlink test must execute on the target Windows environment; do not add a permanent skip.

- [ ] **Step 3: Implement minimal internal-path validation, lease, and schema**

Use exact version-1 DDL with strict status checks and foreign keys. The active-run index is:

```sql
CREATE UNIQUE INDEX one_active_workspace_run
ON session_runs ((1))
WHERE status IN ('queued', 'running', 'cancelling');
```

The three tables include every field from the domain records, `data_json TEXT NOT NULL` for events, and `final_report_json TEXT` for runs. Enable `foreign_keys=ON`, `busy_timeout=<validated positive integer>`, WAL, and `user_version=1`. Validate and store `workspace.resolve(strict=True)` before every existing `.coding-agent`, database, and lock component is inspected and before SQLite or OS-lock access. Expose that same `workspace: Path` on the store and lease. Keep the lock stream open until idempotent `close()`.

- [ ] **Step 4: Run schema GREEN and existing path/logging regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_store.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-store-green1
.\.venv\Scripts\python.exe -m pytest tests/test_path_safety.py tests/test_logging.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-store-regression1
```

Expected: exit 0 for both commands.

#### Cycle 2B: create, list, submit, and stable sequence

- [ ] **Step 5: Add atomic CRUD RED tests**

Use an injected deterministic ID iterator and advancing UTC clock:

```python
def test_create_and_follow_up_are_atomic_and_stably_ordered(tmp_path: Path) -> None:
    ids = iter(("1" * 32, "2" * 32, "3" * 32))
    times = iter(
        datetime(2026, 8, 29, 8, minute, tzinfo=timezone.utc)
        for minute in range(6)
    )
    store = SQLiteSessionStore(
        tmp_path,
        id_factory=lambda: next(ids),
        utc_clock=lambda: next(times),
        sensitive_values=("sk-private",),
    )
    store.initialize()

    first = store.create_session(" Fix sk-private parser \nignored")
    assert first.session.session_id == "1" * 32
    assert first.run.run_id == "2" * 32
    assert first.run.ordinal == 1
    assert first.user_event.sequence == 1
    assert first.session.next_sequence == 3
    assert "sk-private" not in str(store.load_events(first.session.session_id))

    store.finish_run(
        SessionRunResult(
            run_id=first.run.run_id,
            status=SessionRunStatus.FAILED,
            agent_status="failed",
            termination_reason="empty_model_response",
            audit_run_id="4" * 32,
            safe_summary=make_safe_run_summary(
                None,
                status="failed",
                termination_reason="empty_model_response",
            ),
            final_report=persisted_failed_report("4" * 32),
        )
    )
    assert store.get_run(first.run.run_id).final_report == persisted_failed_report("4" * 32)
    second = store.submit_message(first.session.session_id, "Try again")
    assert second.run.ordinal == 2
    assert second.user_event.sequence < second.session.next_sequence
    events = store.load_events(first.session.session_id)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert store.get_session(first.session.session_id).status is SessionStatus.RUNNING
    assert store.get_run(second.run.run_id) == second.run
    assert [run.ordinal for run in store.list_runs(first.session.session_id)] == [1, 2]


def test_list_sessions_uses_updated_desc_then_id_asc(tmp_path: Path) -> None:
    # Use repeated timestamps and deterministic IDs to prove both sort keys.
    store = make_store_with_repeated_clock(tmp_path)
    ids = [store.create_session(text).session.session_id for text in ("a", "b", "c")]
    assert [item.session_id for item in store.list_sessions(limit=2)] == sorted(ids)[:2]
```

The local helper `make_store_with_repeated_clock` is defined in the test file and returns IDs/timestamps that make the expected order explicit; it performs no production monkeypatch.

- [ ] **Step 6: Run CRUD RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_store.py -k "atomic_and_stably_ordered or updated_desc" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-store-red2
```

Expected: exit 1 because repository CRUD methods are missing.

- [ ] **Step 7: Implement CRUD with independent transactions**

Implement strict connection and row-decoding helpers. `create_session` and `submit_message` each write `user_message` and `run_queued`, allocate one queued run, update `last_run_id/updated_at/next_sequence`, and return `SessionSubmission`. `create_session` sets title from scrubbed content. `submit_message` requires an idle session. Both check the partial unique index inside the transaction. `get_run` returns one strict record, `list_runs` validates the session and returns ordinal order, `load_events` uses ascending sequence, and unknown IDs use the exact not-found codes. `list_sessions` validates `1 <= limit <= 500` and uses `updated_at_utc DESC, session_id ASC`.

- [ ] **Step 8: Run CRUD GREEN and concurrency regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_store.py -k "create or follow_up or list_sessions" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-store-green2
.\.venv\Scripts\python.exe -m pytest tests/test_session.py tests/test_logging.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-store-regression2
```

Expected: exit 0 and no leaked sensitive value in pytest output.

#### Cycle 2C: run transitions, safe events, cancellation, and terminal facts

- [ ] **Step 9: Add transition RED tests**

Add a table-driven test that executes these exact transitions:

```python
def interrupted_result(run_id: str) -> SessionRunResult:
    return SessionRunResult(
        run_id=run_id,
        status=SessionRunStatus.INTERRUPTED,
        agent_status="interrupted",
        termination_reason="user_interrupted",
        audit_run_id="4" * 32,
        safe_summary=make_safe_run_summary(
            None,
            status="interrupted",
            termination_reason="user_interrupted",
        ),
        final_report=None,
    )


def test_run_transitions_and_cancel_are_atomic(tmp_path: Path) -> None:
    store = deterministic_store(tmp_path)
    submission = store.create_session("Fix it")
    running = store.start_run(submission.run.run_id)
    assert running.status is SessionRunStatus.RUNNING
    committed = store.append_event(
        NewSessionEvent(
            session_id=submission.session.session_id,
            run_id=running.run_id,
            kind=PersistedSessionEventKind.ASSISTANT_TEXT_COMMITTED,
            data={"content": "I inspected the file."},
        )
    )
    first_cancel = store.request_cancellation(running.run_id)
    second_cancel = store.request_cancellation(running.run_id)
    assert first_cancel.status is SessionRunStatus.CANCELLING
    assert second_cancel == first_cancel
    cancellation_events = [
        event
        for event in store.load_events(submission.session.session_id)
        if event.kind is PersistedSessionEventKind.CANCELLATION_REQUESTED
    ]
    assert len(cancellation_events) == 1
    terminal = store.finish_run(interrupted_result(running.run_id))
    assert terminal.status is SessionRunStatus.INTERRUPTED
    assert store.get_session(submission.session.session_id).status is SessionStatus.IDLE
    assert committed.sequence < store.load_events(submission.session.session_id)[-1].sequence
    narrative = store.load_narrative(submission.session.session_id)
    assert [entry.kind for entry in narrative] == [
        SessionNarrativeKind.USER,
        SessionNarrativeKind.ASSISTANT,
        SessionNarrativeKind.RUN_SUMMARY,
    ]
    assert all("stdout" not in entry.content for entry in narrative)


def test_finish_rejects_full_or_unprojected_report_without_writing(tmp_path: Path) -> None:
    store = deterministic_store(tmp_path)
    submission = store.create_session("Fix it")
    running = store.start_run(submission.run.run_id)
    unsafe = SessionRunResult(
        run_id=running.run_id,
        status=SessionRunStatus.FAILED,
        agent_status="failed",
        termination_reason="empty_model_response",
        audit_run_id="4" * 32,
        safe_summary=make_safe_run_summary(
            None,
            status="failed",
            termination_reason="empty_model_response",
        ),
        final_report={
            "completion": {"text": "must not persist"},
            "verification": {"command": "pytest -q", "stdout": "private"},
        },
    )
    with pytest.raises(SessionStoreError) as captured:
        store.finish_run(unsafe)
    assert captured.value.code == "invalid_session_state"
    assert store.get_run(running.run_id).status is SessionRunStatus.RUNNING
    assert all(
        event.kind is not PersistedSessionEventKind.RUN_FINISHED
        for event in store.load_events(submission.session.session_id)
    )


def test_active_run_unique_constraint_rolls_back_second_submission(tmp_path: Path) -> None:
    store = deterministic_store(tmp_path)
    first = store.create_session("first")
    with pytest.raises(SessionStoreError) as captured:
        store.create_session("second")
    assert captured.value.code == "controller_busy"
    assert len(store.list_sessions()) == 1
    assert store.get_session(first.session.session_id).status is SessionStatus.RUNNING
```

Add invalid-transition cases for starting twice, finishing twice, appending an event to a terminal run, cancelling queued/terminal/unknown runs, wrong session/run pairs, oversized payloads, non-JSON values, and safe persisted-report size/type failures. Every failure asserts the stable code and unchanged rows.

- [ ] **Step 10: Run transition RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_store.py -k "transitions or unique_constraint or invalid_transition or oversized" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-store-red3
```

Expected: exit 1 because transition methods are missing.

- [ ] **Step 11: Implement minimal transition transactions**

`start_run` accepts only queued and writes `run_started`. `request_cancellation` accepts running, is idempotent for cancelling, and rejects queued/terminal/unknown runs with exact codes. `append_event` accepts only allowlisted event kind/payload combinations for the matching active run. `finish_run` accepts queued, running, or cancelling, validates terminal `SessionRunResult`, writes its exact eleven-key `safe_summary` as `run_finished.data`, validates the optional `final_report` against the exact `make_persisted_run_report` schema, requires its audit `run_id`, status, exit code, and termination reason to agree with `SessionRunResult`, stores it as canonical sorted compact JSON separately, and returns the session to idle. A raw or partial `FinalReport.to_dict()` raises `SessionStoreError("invalid_session_state")` with an unchanged transaction, proving the store never accepts completion, failure, command, stdout, or stderr fields. `load_narrative` projects only user content, confirmed assistant content, and canonical run summary in sequence order. No method uses `INSERT OR REPLACE`.

- [ ] **Step 12: Run transition GREEN and full Task 19 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_store.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-store-green3
.\.venv\Scripts\python.exe -m pytest tests/test_session.py tests/test_session_store.py tests/test_messages.py tests/test_logging.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-store-regression3
```

Expected: exit 0 with actual counts.

#### Cycle 2D: recovery, malformed storage, cross-thread access, and real process lock

- [ ] **Step 13: Add recovery and failure RED tests**

Add tests that:

```python
def test_recovery_interrupts_incomplete_runs_without_executor(tmp_path: Path) -> None:
    store = deterministic_store(tmp_path)
    first = store.create_session("first")
    store.start_run(first.run.run_id)
    recovered = store.recover_incomplete_runs()
    assert [(run.run_id, run.status, run.termination_reason) for run in recovered] == [
        (first.run.run_id, SessionRunStatus.INTERRUPTED, "process_restarted")
    ]
    assert store.get_session(first.session.session_id).status is SessionStatus.IDLE
    assert store.load_events(first.session.session_id)[-1].kind is PersistedSessionEventKind.RUN_RECOVERED
    assert store.recover_incomplete_runs() == ()


def test_connections_are_safe_across_caller_and_worker_threads(tmp_path: Path) -> None:
    store = deterministic_store(tmp_path)
    submission = store.create_session("threaded")
    failures: list[BaseException] = []
    thread = Thread(
        target=lambda: capture_failure(failures, lambda: store.start_run(submission.run.run_id))
    )
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert failures == []
```

Also add exact tests for `PRAGMA user_version=2` → `schema_unsupported`, non-database bytes → `database_corrupt`, malformed stored JSON → `database_corrupt`, transaction injection rollback, and a subprocess that holds `WorkspaceSessionLease` while the parent receives `controller_in_use`, then releases it and allows acquisition. The subprocess communicates readiness through stdout and never sleeps or accesses a network.

- [ ] **Step 14: Run recovery RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_store.py -k "recovery or worker_threads or schema_unsupported or database_corrupt or process_lease or rollback" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-store-red4
```

Expected: exit 1 due to missing recovery/decoding/cross-process behavior, not a fixture or subprocess syntax error.

- [ ] **Step 15: Implement recovery and stable SQLite error mapping**

Recover all incomplete runs in one immediate transaction and return records ordered by session ID then ordinal. Decode every row through exact-field constructors. Map only known SQLite categories to stable codes without including `str(exc)`. Use one connection per public call. Make lease close idempotent and preserve `KeyboardInterrupt`/`SystemExit`.

- [ ] **Step 16: Run Task 19 GREEN, baseline regression, and status checkpoint**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session.py tests/test_session_store.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-complete
.\.venv\Scripts\python.exe -m pytest tests/test_messages.py tests/test_agent_loop.py tests/test_context.py tests/test_logging.py tests/test_report.py tests/test_path_safety.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task19-regression
git diff --check
```

Expected: all commands exit 0. Inspect the diff for Task 20 code; none may exist. Then change only Task 19 to `已完成` and Task 20 to `进行中`, proving there is still exactly one active task.

**Acceptance:** Task 19 independently delivers protected, atomic, recoverable durable sessions with no Agent thread, transport, Skill, or provider behavior.

### Task 3: UI-safe event schema and bounded in-memory replay

**Files:**
- Create: `src/coding_agent/session_events.py`
- Create: `tests/test_session_events.py`

**Interfaces:**
- Consumes: `JSONObject`, UTC clock, and known sensitive values.
- Produces: `SessionUpdate`, `SessionUpdateBatch`, and `SessionEventHub` for the controller; no SQLite type.

Lock the batch interface:

```python
@dataclass(frozen=True, slots=True)
class SessionUpdateBatch:
    events: tuple[SessionUpdate, ...]
    last_sequence: int
    reset_required: bool
```

Lock the hub constructor/methods:

```python
SessionEventHub(
    *,
    utc_clock: Callable[[], datetime] = utc_now,
    sensitive_values: tuple[str, ...] = (),
    max_events: int = 1_000,
    max_bytes: int = 1_048_576,
)

def begin_run(session_id: str, run_id: str) -> None
def publish(kind: SessionUpdateKind, data: JSONObject) -> SessionUpdate
def read(*, after_sequence: int = 0) -> SessionUpdateBatch
def wait(*, after_sequence: int, timeout_seconds: float) -> SessionUpdateBatch
```

- [ ] **Step 1: Write schema and privacy RED tests**

```python
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from coding_agent.session_events import (
    SessionEventHub,
    SessionUpdateKind,
)

SESSION_ID = "1" * 32
RUN_ID = "2" * 32
NOW = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)


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


@pytest.mark.parametrize(
    ("kind", "data"),
    [
        (SessionUpdateKind.TOOL_STARTED, {"tool_name": "read_file", "arguments": {"path": "x"}}),
        (SessionUpdateKind.TOOL_FINISHED, {"tool_name": "run_command", "stdout": "secret"}),
        (SessionUpdateKind.CONTROLLER_ERROR, {"error": "raw provider body"}),
        (SessionUpdateKind.ASSISTANT_TEXT_DELTA, {"content": ""}),
    ],
)
def test_update_payload_rejects_non_allowlisted_or_invalid_fields(kind, data) -> None:
    hub = SessionEventHub(utc_clock=lambda: NOW)
    hub.begin_run(SESSION_ID, RUN_ID)
    with pytest.raises((TypeError, ValueError)):
        hub.publish(kind, data)
```

- [ ] **Step 2: Run event schema RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_events.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-events-red1
```

Expected: exit 1 because the event module is absent.

- [ ] **Step 3: Implement exact update kinds and payload allowlists**

Define all twelve approved `SessionUpdateKind` values. Use a per-kind exact-key map and validators for non-empty text, positive ordinals, non-negative duration, boolean flags, nullable exit code, safe error code, normalized changed-path list, status, and fixed controller error code. `to_dict()` returns schema version 1 and canonical JSON-compatible data. `to_json()` calls `json.dumps(to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)` with no trailing newline. The title/message scrubber runs before object construction. Data remains hidden from `repr`.

- [ ] **Step 4: Run schema GREEN and message/log privacy regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_events.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-events-green1
.\.venv\Scripts\python.exe -m pytest tests/test_messages.py tests/test_logging.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-events-regression1
```

- [ ] **Step 5: Add count, byte, replay, reset, and wait RED tests**

```python
from threading import Event, Thread


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
    hub.publish(SessionUpdateKind.RUN_FINISHED, {"status": "failed"})
    hub.begin_run("3" * 32, "4" * 32)
    assert hub.read().events == ()
    assert hub.read().last_sequence == 0
```

Add timeout validation for bool, zero, negative, NaN, and infinity; an immediate empty batch at a fake condition timeout; a cursor equal to latest; a cursor ahead of latest; one event individually larger than `max_bytes` that is rejected without changing sequence; and concurrent publish/read ordering.

- [ ] **Step 6: Run bounded-hub RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_events.py -k "limits or wakes or replaces or timeout or cursor or concurrent" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-events-red2
```

Expected: exit 1 because the first implementation does not provide bounded condition-backed replay.

- [ ] **Step 7: Implement the bounded hub**

Use one `threading.Condition`, one deque of `(event, encoded_size)`, and total retained bytes. `publish` validates before acquiring the condition, calculates `encoded_size = len(event.to_json().encode("utf-8"))`, rejects an individually oversized encoded event before consuming a sequence, appends with the next sequence, evicts oldest values while either bound is exceeded, and calls `notify_all`. Do not split text. `wait` uses `Condition.wait_for` with the exact finite timeout and returns the same result shape as `read`.

- [ ] **Step 8: Run event GREEN and streaming regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_events.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-events-green2
.\.venv\Scripts\python.exe -m pytest tests/test_streaming.py tests/test_openai_streaming_client.py tests/test_chat_completions_streaming_client.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-events-regression2
```

Expected: both commands exit 0 with no skip added.

**Acceptance:** a future transport can read safe ordered updates or wait for them, memory remains bounded, and no transport, database, provider payload, or consumer callback exists in this component.

### Task 4: Additive initial-message and confirmed-text Agent hooks

**Files:**
- Modify: `src/coding_agent/state.py`
- Modify: `src/coding_agent/agent.py`
- Modify: `tests/test_agent_loop.py`

**Interfaces:**
- Consumes: current `AgentState.start`, `AgentRunner`, `ModelResponse`, and `AssistantMessage` behavior.
- Produces: one model-facing rendered initial message while retaining the current task, plus one callback for valid complete main-response text.

- [ ] **Step 1: Add initial-message RED tests**

Extend the existing `_runner` helper only with optional `initial_user_message` and `confirmed_text_handler` arguments, passed unchanged to `AgentRunner`. Add:

```python
def test_rendered_initial_message_does_not_replace_current_task(tmp_path: Path) -> None:
    rendered = (
        "coding-agent session context\n"
        '{"prior":[{"role":"assistant","content":"old result"}]}\n'
        "current request\nfix the new failure"
    )
    runner, client = _runner(
        tmp_path,
        (ModelResponse(text="done"),),
        initial_user_message=rendered,
    )
    state = runner.run("fix the new failure")
    assert state.task == "fix the new failure"
    assert state.current_goal == "fix the new failure"
    assert client.requests[0].messages[0] == UserMessage(rendered)
    assert all(not isinstance(item, ToolResult) for item in client.requests[0].messages)


@pytest.mark.parametrize("initial", ["", "   ", 3])
def test_rendered_initial_message_is_strict(tmp_path: Path, initial: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        AgentRunner(
            model_client=FakeModelClient((ModelResponse(text="done"),)),
            tool_registry=ToolRegistry(()),
            execution_context=ExecutionContext(tmp_path),
            initial_user_message=initial,  # type: ignore[arg-type]
        )
```

- [ ] **Step 2: Run initial-message RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -k "rendered_initial_message" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-agent-red1
```

Expected: exit 1 because `AgentRunner` rejects the new keyword and `AgentState.start` cannot separate task from initial content.

- [ ] **Step 3: Implement minimal initial-message support**

Add keyword-only `initial_user_message` to `AgentState.start`; validate it with `UserMessage` when non-null, keep `task/current_goal` from the original task, and use the selected value only for `messages[0]`. Add the optional constructor field to `AgentRunner` and pass it to `AgentState.start`. Existing null behavior remains byte-for-byte equivalent.

- [ ] **Step 4: Run initial-message GREEN and context regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -k "rendered_initial_message or direct_text or compression" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-agent-green1
.\.venv\Scripts\python.exe -m pytest tests/test_context.py tests/test_messages.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-agent-regression1
```

Expected: exit 0. The existing `_partition_complete_turns` tests remain unchanged.

- [ ] **Step 5: Add confirmed-text RED tests**

```python
def test_confirmed_text_handler_receives_each_complete_main_text(tmp_path: Path) -> None:
    seen: list[str] = []
    runner, _ = _runner(
        tmp_path,
        (
            ModelResponse(text="I will inspect", tool_calls=(_record_call(1),)),
            ModelResponse(text="Finished"),
        ),
        tools=(RecordingTool("one"),),
        confirmed_text_handler=seen.append,
    )
    state = runner.run("repair")
    assert state.completion_text == "Finished"
    assert seen == ["I will inspect", "Finished"]


def test_confirmed_text_handler_ignores_empty_and_failed_responses(tmp_path: Path) -> None:
    seen: list[str] = []
    runner, _ = _runner(
        tmp_path,
        (TransientModelError("hidden"), ModelResponse()),
        confirmed_text_handler=seen.append,
    )
    state = runner.run("repair")
    assert state.status is AgentStatus.FAILED
    assert seen == []


def test_confirmed_text_handler_system_exit_is_not_swallowed(tmp_path: Path) -> None:
    def exit_handler(_: str) -> None:
        raise SystemExit(19)

    runner, _ = _runner(
        tmp_path,
        (ModelResponse(text="done"),),
        confirmed_text_handler=exit_handler,
    )
    with pytest.raises(SystemExit) as captured:
        runner.run("repair")
    assert captured.value.code == 19
```

- [ ] **Step 6: Run confirmed-text RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -k "confirmed_text_handler" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-agent-red2
```

Expected: exit 1 because the callback keyword/behavior does not exist.

- [ ] **Step 7: Implement confirmed text at the complete-response boundary**

Define `ConfirmedTextHandler` in `agent.py`, validate callable-or-null, and invoke it once after `invoke_model`/`invoke_model_stream` returns a valid response and nonblank `assistant_text` is normalized, before processing its tools or candidate. Do not invoke it for summary calls, provider deltas, model errors, invalid/empty text, or tool results. Do not catch `BaseException` from the handler.

- [ ] **Step 8: Run confirmed-text GREEN and streaming regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -k "confirmed_text_handler or text_with_tool_calls or main_calls_stream" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-agent-green2
.\.venv\Scripts\python.exe -m pytest tests/test_streaming.py tests/test_context.py tests/test_agent_loop.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-agent-regression2
```

Expected: exit 0; existing streaming event order and synchronous summary behavior are unchanged.

**Acceptance:** session history can enter as one valid initial user message, confirmed main text is observable independently of deltas, and all existing callers remain compatible.

### Task 5: Cooperative Agent cancellation at exact operation boundaries

**Files:**
- Modify: `src/coding_agent/agent.py`
- Modify: `tests/test_agent_loop.py`

**Interfaces:**
- Consumes: existing `_append_unexecuted_results`, `AgentStatus.INTERRUPTED`, `TerminationReason.USER_INTERRUPTED`, and Task 4 hooks.
- Produces: additive `cancellation_requested: CancellationCheck | None` with no new termination enum.

- [ ] **Step 1: Add pre-model and post-model RED tests**

```python
from threading import Event


def test_cooperative_cancel_before_model_starts_no_operation(tmp_path: Path) -> None:
    cancel = Event()
    cancel.set()
    runner, client = _runner(
        tmp_path,
        (ModelResponse(text="must not run"),),
        cancellation_requested=cancel.is_set,
    )
    state = runner.run("stop")
    assert state.status is AgentStatus.INTERRUPTED
    assert state.termination_reason is TerminationReason.USER_INTERRUPTED
    assert client.requests == []
    assert state.logical_model_call_count == 0
    assert state.tool_call_count == 0


def test_cancel_after_model_confirms_text_and_pairs_unexecuted_tools(tmp_path: Path) -> None:
    cancel = Event()
    seen: list[str] = []

    class CancellingModel:
        requests: list[ModelRequest] = []
        def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            cancel.set()
            return ModelResponse(text="complete text", tool_calls=(_record_call(1), _record_call(2)))

    tool = RecordingTool("never")
    runner = AgentRunner(
        model_client=CancellingModel(),
        tool_registry=ToolRegistry((tool,)),
        execution_context=ExecutionContext(tmp_path),
        cancellation_requested=cancel.is_set,
        confirmed_text_handler=seen.append,
    )
    state = runner.run("stop after model")
    assert seen == ["complete text"]
    assert tool.calls == []
    assert state.status is AgentStatus.INTERRUPTED
    results = [item for item in state.messages if isinstance(item, ToolResult)]
    assert [result.call_id for result in results] == ["call-1", "call-2"]
    assert all(result.status == "rejected" for result in results)
    ModelRequest(messages=state.messages)


def test_cancel_during_admitted_context_summary_blocks_next_main_model(tmp_path: Path) -> None:
    cancel = Event()
    summary = json.dumps(
        {
            "goal": "repair",
            "established_facts": [],
            "files_examined": [],
            "changes_made": [],
            "commands_and_results": [],
            "unresolved_errors": [],
            "open_issues": [],
            "verification_state": {},
            "avoid_repeating": [],
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    class CancellingSummaryModel:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            if len(self.requests) == 1:
                return ModelResponse(tool_calls=(_record_call(1),))
            if len(self.requests) == 2:
                return ModelResponse(tool_calls=(_record_call(2),))
            assert request.tool_schemas == ()
            cancel.set()
            return ModelResponse(text=summary)

    client = CancellingSummaryModel()
    runner = AgentRunner(
        model_client=client,
        tool_registry=ToolRegistry((RecordingTool("record"),)),
        execution_context=ExecutionContext(tmp_path),
        context_manager=ContextManager(
            model_client=client,
            limits=ContextLimits(max_history_items=4, recent_turns=1),
        ),
        cancellation_requested=cancel.is_set,
    )
    state = runner.run("repair")
    assert len(client.requests) == 3
    assert client.requests[-1].tool_schemas == ()
    assert state.logical_model_call_count == 2
    assert state.status is AgentStatus.INTERRUPTED
    assert state.termination_reason is TerminationReason.USER_INTERRUPTED
```

Update `_runner` to pass an optional `cancellation_requested` callable. The existing `_record_call(1)` and `_record_call(2)` values are exactly `call-1` and `call-2`, both using tool name `record`; keep the shown assertions unchanged.

- [ ] **Step 2: Run cancellation RED 1**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -k "cooperative_cancel_before or cancel_after_model or cancel_during_admitted_context" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-cancel-red1
```

Expected: exit 1 because the constructor does not accept cancellation and no cancellation checkpoints exist.

- [ ] **Step 3: Implement pre/post model cancellation and interruption helper**

Add `CancellationCheck`, callable validation, `_is_cancellation_requested()` with strict boolean return validation, and `_interrupt(state, pending_calls=())`. `_interrupt` uses `_append_unexecuted_results` before setting `INTERRUPTED/USER_INTERRUPTED`. Check before context preparation, after preparation, and after a valid main response has delivered confirmed text and appended any assistant tool-call message. The pre-prepare check admits the entire `ContextManager.prepare()` call, including an optional summary model request; a cancellation set inside that admitted call is observed by the post-prepare check, which prevents the next main model request. Do not modify `context.py`. Cancellation has priority over admitting the next operation.

- [ ] **Step 4: Run cancellation GREEN 1 and budget regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -k "cooperative_cancel_before or cancel_after_model" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-cancel-green1
.\.venv\Scripts\python.exe -m pytest tests/test_termination.py tests/test_agent_loop.py -k "limit or boundary or cancel" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-cancel-regression1
```

- [ ] **Step 5: Add tool-batch and verification RED tests**

Add a recording tool whose first execution sets the cancel event, then assert the first result is real, later calls are paired rejected results, and `tool_call_count` counts only the executed call. Add required-verification fixtures for:

```python
def test_cancel_before_required_verification_does_not_execute_it(tmp_path: Path) -> None:
    cancel = Event()
    executor = FakeVerificationExecutor(_verification_execution(0))
    gate = _verification_gate(tmp_path, executor=executor)

    def confirm(_: str) -> None:
        cancel.set()

    runner, _ = _runner(
        tmp_path,
        (ModelResponse(text="candidate"),),
        verification_gate=gate,
        confirmed_text_handler=confirm,
        cancellation_requested=cancel.is_set,
    )
    state = runner.run("cancel before verify")
    assert state.status is AgentStatus.INTERRUPTED
    assert executor.calls == []
    assert state.verification_attempt_count == 0


def test_cancel_requested_during_verification_stops_after_admitted_result(tmp_path: Path) -> None:
    cancel = Event()
    executor = CancellingVerificationExecutor(cancel, _verification_execution(0))
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(text="candidate"),),
        verification_gate=_verification_gate(tmp_path, executor=executor),
        cancellation_requested=cancel.is_set,
    )
    state = runner.run("cancel during verify")
    assert len(executor.calls) == 1
    assert state.verification_attempt_count == 1
    assert state.status is AgentStatus.INTERRUPTED
    assert state.termination_reason is TerminationReason.USER_INTERRUPTED
```

Also add cancellation-check callbacks returning `1` and raising `SystemExit`; the first raises a stable `TypeError`, and the second propagates `SystemExit`. Existing real `KeyboardInterrupt` tests must remain unchanged.

- [ ] **Step 6: Run cancellation RED 2**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -k "cancel_after_first_tool or cancel_before_required or cancel_requested_during or cancellation_check" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-cancel-red2
```

Expected: exit 1 because tool/verification checkpoints are missing.

- [ ] **Step 7: Implement remaining checkpoints without changing admission rules**

Check before each tool, immediately after each returned `ToolResult`, before required verification admission, and after verification returns but before applying success/feedback. An admitted operation keeps its real result and counters. Rejected later calls do not increment tool count. A cancellation after a fresh verification result still returns interrupted because the user requested stop before terminal state was applied. Keep the existing policy/budget order for runs without cancellation.

- [ ] **Step 8: Run cancellation GREEN 2 and complete Agent regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -k "cancel or interrupt or system_exit or verification or unexecuted" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-cancel-green2
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py tests/test_context.py tests/test_termination.py tests/test_verification.py tests/test_streaming.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-cancel-regression2
```

Expected: exit 0; no operation is admitted after cancellation linearizes, an already-admitted context/model/tool/verification unit may finish, message pairing remains valid, and Task 10/11 boundary tests retain accepted outcomes when cancellation is absent.

**Acceptance:** cancellation is cooperative, deterministic, message-safe, does not swallow `BaseException`, and never introduces a second success or budget path.

### Task 6: Narrative renderer, post-flush audit observer, and shared production runtime

**Files:**
- Create: `src/coding_agent/session_runtime.py`
- Create: `tests/test_session_runtime.py`
- Modify: `src/coding_agent/logging.py`
- Modify: `tests/test_logging.py`
- Modify: `src/coding_agent/app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: Task 1 records, `ContextManager.measure`, Task 4/5 Agent hooks, `ApplicationFactories`, `RunConfig`, `RunEventLogger`, and `FinalReport`.
- Produces: safe initial-message rendering and one SDK-free `SessionRunExecutor` used by the controller.

#### Cycle 6A: post-flush audit observation

- [ ] **Step 1: Add logger observer RED tests**

Append to `tests/test_logging.py`:

```python
def test_event_observer_runs_only_after_line_is_flushed(tmp_path: Path) -> None:
    observed: list[tuple[RunEvent, str]] = []
    logger = RunEventLogger.create(tmp_path, run_id="1" * 32)

    def observer(event: RunEvent) -> None:
        log_path = tmp_path / logger.metadata.log_path
        observed.append((event, log_path.read_text(encoding="utf-8")))

    logger.set_event_observer(observer)
    event = logger.emit(EventType.RUN_STARTED, {"task_chars": 4, "mutation_index": 0})
    assert observed[0][0] == event
    assert json.loads(observed[0][1].splitlines()[-1])["sequence"] == event.sequence
    logger.close()


def test_ordinary_event_observer_failure_does_not_poison_audit_log(tmp_path: Path) -> None:
    calls = 0
    def observer(_: RunEvent) -> None:
        nonlocal calls
        calls += 1
        raise OSError("private bridge detail")

    logger = RunEventLogger.create(tmp_path, run_id="2" * 32)
    logger.set_event_observer(observer)
    first = logger.emit(EventType.RUN_STARTED, {"task_chars": 4, "mutation_index": 0})
    second = logger.emit(
        EventType.RUN_COMPLETED,
        {
            "status": "failed",
            "termination_reason": "empty_model_response",
            "logical_model_calls": 1,
            "provider_attempts": 1,
            "tool_calls": 0,
            "verification_attempts": 0,
            "mutation_index": 0,
            "validation_index": None,
            "elapsed_ms": 1,
        },
    )
    logger.close()
    assert (first.sequence, second.sequence, calls) == (1, 2, 2)
    text = (tmp_path / logger.metadata.log_path).read_text(encoding="utf-8")
    assert "private bridge detail" not in text
    assert len(text.splitlines()) == 2


def test_event_observer_system_exit_is_not_swallowed(tmp_path: Path) -> None:
    logger = RunEventLogger.create(tmp_path, run_id="3" * 32)
    logger.set_event_observer(lambda _: (_ for _ in ()).throw(SystemExit(7)))
    with pytest.raises(SystemExit) as captured:
        logger.emit(EventType.RUN_STARTED, {"task_chars": 4, "mutation_index": 0})
    assert captured.value.code == 7
    logger.close()
```

The shown dictionary is the complete accepted `RUN_COMPLETED` payload; do not introduce a production helper for the test.

- [ ] **Step 2: Run observer RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_logging.py -k "event_observer" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-logger-red
```

Expected: exit 1 because `set_event_observer` is missing.

- [ ] **Step 3: Implement post-flush observation**

Add a `RunEventObserver = Callable[[RunEvent], None]` alias and hidden optional field. `set_event_observer` is allowed only before the first event and before close, accepts callable-or-null, and does not render it. In `emit`, assign `_sequence` only after successful flush, then call the observer. Catch `Exception` from the observer and continue without changing metadata or audit status. Do not catch `BaseException`.

- [ ] **Step 4: Run observer GREEN and full logging/report regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_logging.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-logger-green
.\.venv\Scripts\python.exe -m pytest tests/test_report.py tests/test_agent_loop.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-logger-regression
```

#### Cycle 6B: deterministic narrative renderer

- [ ] **Step 5: Write narrative RED tests**

Create `tests/test_session_runtime.py` with:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.context import ContextManager, ContextLimits
from coding_agent.messages import UserMessage
from coding_agent.session import (
    SessionError,
    SessionNarrativeEntry,
    SessionNarrativeKind,
)
from coding_agent.session_runtime import SessionNarrativeRenderer

RUN_1 = "1" * 32
RUN_2 = "2" * 32


def _entry(run_id: str, kind: SessionNarrativeKind, content: str) -> SessionNarrativeEntry:
    return SessionNarrativeEntry(run_id=run_id, kind=kind, content=content)


def test_narrative_is_one_deterministic_initial_user_message() -> None:
    entries = (
        _entry(RUN_1, SessionNarrativeKind.USER, "fix parser"),
        _entry(RUN_1, SessionNarrativeKind.ASSISTANT, "parser fixed"),
        _entry(RUN_1, SessionNarrativeKind.RUN_SUMMARY, '{"status":"success"}'),
    )
    renderer = SessionNarrativeRenderer()
    first = renderer.render(entries, "now add a test")
    second = renderer.render(entries, "now add a test")
    assert first == second
    assert first.startswith("coding-agent session context\n")
    assert first.endswith("current request\nnow add a test")
    assert "call_id" not in first
    assert ContextManager.measure((UserMessage(first),)).serialized_chars <= ContextLimits().max_serialized_chars


def test_narrative_keeps_newest_entries_and_reports_omission() -> None:
    entries = tuple(
        _entry(str(index).zfill(32), SessionNarrativeKind.ASSISTANT, f"entry-{index}-" + "x" * 8000)
        for index in range(1, 9)
    )
    rendered = SessionNarrativeRenderer().render(entries, "current")
    assert "entry-8-" in rendered
    assert "entry-1-" not in rendered
    assert '"omitted_entries":' in rendered
    assert ContextManager.measure((UserMessage(rendered),)).serialized_chars <= 60_000


def test_current_request_that_cannot_fit_is_rejected_without_truncation() -> None:
    with pytest.raises(SessionError) as captured:
        SessionNarrativeRenderer().render((), "x" * 60_000)
    assert captured.value.code == "invalid_message"
```

- [ ] **Step 6: Run narrative RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_runtime.py -k "narrative or current_request" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-runtime-red1
```

Expected: exit 1 because `session_runtime.py` is absent.

- [ ] **Step 7: Implement exact newest-first selection**

Define `SessionNarrativeRenderer(max_serialized_chars: int = ContextLimits().max_serialized_chars)`. Render canonical compact JSON with keys `history` and `omitted_entries`, then the literal current-request marker. First measure current request with empty history. Iterate entries from newest to oldest, insert each candidate at the front to retain chronological display, and keep it only when the complete `UserMessage` remains within the configured serialized-char bound. Do not truncate the current request or an included entry. Reject non-tuples, invalid entries, nonpositive/bool limits, and an unfit current request.

- [ ] **Step 8: Run narrative GREEN and context compression regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_runtime.py -k "narrative or current_request" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-runtime-green1
.\.venv\Scripts\python.exe -m pytest tests/test_context.py tests/test_agent_loop.py -k "compression or initial or summary" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-runtime-regression1
```

#### Cycle 6C: shared application execution and SDK-free outcome

- [ ] **Step 9: Add shared-runtime RED tests**

In `tests/test_app.py`, add a test calling the new stream-free `execute_agent_run` with existing successful fake factories and asserting one `FinalReport` equal to the one rendered by `run_application`. In `tests/test_session_runtime.py`, add:

```python
class PassingExecutor:
    def execute(self, command: AuthorizedCommand, context: ExecutionContext) -> ToolExecution:
        return ToolExecution(
            output=json.dumps(
                {
                    "argv": list(command.argv),
                    "cleanup_error": None,
                    "purpose": command.purpose,
                    "stderr": "",
                    "stdout": "1 passed",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            metadata=ToolResultMetadata(exit_code=0, duration_ms=1),
        )


def test_agent_session_executor_returns_sdk_free_terminal_outcome(tmp_path: Path) -> None:
    config = load_run_config(
        task="template task",
        workspace=tmp_path,
        model="fake-model",
        verify_command="pytest -q",
        environ={"OPENAI_API_KEY": "obviously-fake-session-key"},
    )
    factories = ApplicationFactories(
        model_client=lambda _: FakeModelClient((ModelResponse(text="done"),)),
        logger=lambda selected, clock: RunEventLogger.create(
            selected.workspace,
            run_id="5" * 32,
            sensitive_values=(selected.api_key,),
            monotonic_clock=clock,
        ),
        command_executor=PassingExecutor,
        clock=lambda: 0.0,
    )
    executor = AgentSessionRunExecutor(config, factories=factories)
    assert executor.workspace == tmp_path.resolve(strict=True)
    request = SessionRunRequest(
        session_id="1" * 32,
        run_id="2" * 32,
        current_message="actual follow-up",
        initial_user_message="current request\nactual follow-up",
    )
    confirmed: list[str] = []
    outcome = executor.execute(
        request,
        stream_handler=lambda event: None,
        confirmed_text_handler=confirmed.append,
        cancellation_requested=lambda: False,
        run_event_handler=lambda event: None,
    )
    assert outcome.status is SessionRunStatus.SUCCEEDED
    assert outcome.agent_status == "success"
    assert outcome.final_report is not None
    assert outcome.audit_run_id == outcome.final_report["run_id"]
    assert outcome.final_report["exit_code"] == 0
    persisted = json.dumps(outcome.final_report, ensure_ascii=False)
    for forbidden in (
        "completion", "failure_reason", "command", "stdout", "stderr",
        "private completion", "private stdout", "private stderr",
    ):
        assert forbidden not in persisted
    assert "OpenAI" not in type(outcome).__module__
    assert confirmed
```

Import the production/test types used in the shown factory directly. Do not import one test module from another and do not copy production composition into the fake factory.

- [ ] **Step 10: Run shared-runtime RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_app.py tests/test_session_runtime.py -k "execute_agent_run or agent_session_executor" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-runtime-red2
```

Expected: exit 1 because the shared execution helper and production session executor do not exist.

- [ ] **Step 11: Extract one shared execution path**

In `app.py`, add provider-neutral `ApplicationRunError(code)`, immutable `AgentExecutionResult(state, report)`, and:

```python
def execute_agent_run(
    config: RunConfig,
    *,
    factories: ApplicationFactories | None = None,
    stream_handler: ModelStreamHandler | None = None,
    confirmed_text_handler: ConfirmedTextHandler | None = None,
    cancellation_requested: CancellationCheck | None = None,
    initial_user_message: str | None = None,
    event_observer: RunEventObserver | None = None,
) -> AgentExecutionResult: ...
```

Move the existing accepted logger construction, five-tool registry, model/context/policy/gate/instruction/runner construction, Agent execution, logger-close handling, metadata completion, and `FinalReport.from_state` into this helper. Preserve all existing error and `BaseException` behavior. `run_application` calls the helper, maps only stable errors to its accepted stderr text, renders exactly one report, and returns its exit code.

Implement `SessionRunRequest`, `SessionRunOutcome`, `SessionRunExecutor`, and `AgentSessionRunExecutor`. The protocol and production executor expose `workspace: Path`, equal to `base_config.workspace.resolve(strict=True)`. The executor uses `dataclasses.replace(base_config, task=request.current_message)`, passes the initial message, the stream/confirmed/cancellation handlers, and `run_event_handler` as the logger's post-flush observer. It builds `safe_summary` with `make_safe_run_summary`, builds the optional stored `final_report` only with `make_persisted_run_report(execution.report.to_dict())`, and never returns the full report, `AgentState`, logger, model client, API key, or SDK object. The existing synchronous CLI still renders the unchanged full `FinalReport` from `execute_agent_run`.

- [ ] **Step 12: Run shared-runtime GREEN and full app/CLI regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_runtime.py tests/test_app.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-runtime-green2
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/test_app.py tests/test_report.py tests/test_instructions.py tests/test_agent_loop.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-runtime-regression2
```

Expected: exit 0. Existing stdout/stderr cardinality, exit 0/1/130, logger close, instruction construction, tool order, and lazy CLI behavior are unchanged.

**Acceptance:** Task 20 has one deterministic history renderer, one accepted production composition path, a provider-neutral terminal outcome, and a best-effort post-flush audit observation boundary.

### Task 7: Single-active-run SessionController and lifecycle convergence

**Files:**
- Create: `src/coding_agent/session_controller.py`
- Create: `tests/test_session_controller.py`

**Interfaces:**
- Consumes: `SessionStore`, `WorkspaceSessionLease`, `SessionEventHub`, `SessionNarrativeRenderer`, `SessionRunExecutor`, and all approved callbacks.
- Produces: the framework-neutral API later Task 22 will adapt to SSE.

Lock the remaining record fields:

```python
@dataclass(frozen=True, slots=True)
class SessionRunRequest:
    session_id: str
    run_id: str
    current_message: str = field(repr=False)
    initial_user_message: str = field(repr=False)

@dataclass(frozen=True, slots=True)
class SessionRunOutcome:
    status: SessionRunStatus
    agent_status: str | None
    termination_reason: str | None
    audit_run_id: str | None
    safe_summary: JSONObject = field(repr=False)
    final_report: JSONObject | None = field(repr=False)

@dataclass(frozen=True, slots=True)
class RunHandle:
    session_id: str
    run_id: str

@dataclass(frozen=True, slots=True)
class SessionView:
    session: SessionRecord
    runs: tuple[SessionRunRecord, ...]
    events: tuple[SessionEvent, ...] = field(repr=False)
```

`SessionRunOutcome.final_report` and `SessionRunResult.final_report` mean only the output of `make_persisted_run_report`; they never carry the full `FinalReport.to_dict()` value. Controller-generated failures use `None`. The unchanged synchronous CLI retains the full report in `AgentExecutionResult`.

The controller constructor is:

```python
class WorkerThread(Protocol):
    @property
    def daemon(self) -> bool: ...

    @property
    def name(self) -> str: ...

    def start(self) -> None: ...
    def join(self, timeout: float | None = None) -> None: ...
    def is_alive(self) -> bool: ...


ThreadFactory: TypeAlias = Callable[[Callable[[], None], str], WorkerThread]


def default_thread_factory(
    target: Callable[[], None],
    name: str,
) -> WorkerThread:
    return Thread(target=target, name=name, daemon=False)


SessionController(
    *,
    store: SessionStore,
    lease: WorkspaceSessionLease,
    executor: SessionRunExecutor,
    event_hub: SessionEventHub,
    narrative_renderer: SessionNarrativeRenderer = SessionNarrativeRenderer(),
    thread_factory: ThreadFactory = default_thread_factory,
)
```

`SessionController.open(...)` is exactly:

```python
@classmethod
def open(
    cls,
    workspace: Path,
    executor: SessionRunExecutor,
    *,
    sensitive_values: tuple[str, ...] = (),
    utc_clock: Callable[[], datetime] = utc_now,
    thread_factory: ThreadFactory = default_thread_factory,
) -> SessionController: ...
```

It resolves the workspace, verifies `executor.workspace` is the same platform-normalized identity, acquires the lease, initializes `SQLiteSessionStore`, performs recovery, creates the event hub with the same sensitive values, and releases the lease on any initialization failure.

#### Cycle 7A: one worker, busy rejection, terminal convergence, and views

- [ ] **Step 1: Write controller fixture and RED tests**

Create `tests/test_session_controller.py` with deterministic real store/hub plus a fake executor:

```python
from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

import pytest

from coding_agent.session import (
    SessionControllerError,
    SessionRunStatus,
    SessionStatus,
    make_safe_run_summary,
)
from coding_agent.session_controller import SessionController
from coding_agent.session_events import SessionEventHub
from coding_agent.session_runtime import SessionRunOutcome
from coding_agent.session_store import SQLiteSessionStore, WorkspaceSessionLease


class BlockingExecutor:
    def __init__(self, workspace: Path, outcomes: tuple[SessionRunOutcome, ...]) -> None:
        self.workspace = workspace.resolve(strict=True)
        self.outcomes = list(outcomes)
        self.requests = []
        self.started = Event()
        self.release = Event()

    def execute(
        self,
        request,
        *,
        stream_handler,
        confirmed_text_handler,
        cancellation_requested,
        run_event_handler,
    ) -> SessionRunOutcome:
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


def make_controller(
    tmp_path: Path,
    executor,
    *,
    store: SQLiteSessionStore | None = None,
) -> SessionController:
    lease = WorkspaceSessionLease.acquire(tmp_path)
    store = store or SQLiteSessionStore(tmp_path)
    store.initialize()
    store.recover_incomplete_runs()
    return SessionController(
        store=store,
        lease=lease,
        executor=executor,
        event_hub=SessionEventHub(),
    )


def test_controller_rejects_mismatched_workspace_components(tmp_path: Path) -> None:
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


def test_controller_rejects_second_run_while_worker_is_active(tmp_path: Path) -> None:
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
```

Add tests for invalid message before any database row, `get_session` returning runs/events, `list_sessions` delegation, stable not-found errors, the shown workspace mismatch, a non-daemon worker assertion through an injected recording thread factory, and ordinary executor exception mapping to a terminal failed row without exception text.

- [ ] **Step 2: Run controller RED 1**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_controller.py -k "second_run or invalid_message or get_session or workspace_components or non_daemon or executor_exception" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-controller-red1
```

Expected: exit 1 because `session_controller.py` does not exist.

- [ ] **Step 3: Implement minimal worker lifecycle**

Validate all injected protocols and compare `os.path.normcase(str(component.workspace.resolve(strict=True)))` for store, lease, and executor before recovery or thread creation; mismatch raises `SessionControllerError("invalid_session_state")`. Own one lock and active-run structure, validate/render before store submission, create the durable queued run, reset the hub, publish queued, and start one named non-daemon thread. The worker calls `start_run`, publishes started, executes, maps outcome to `SessionRunResult`, finishes durably, publishes finished, clears active ownership under the lock, and signals its done event. `wait_for_run` waits on the done event outside the controller lock and then calls `store.get_run`. Ordinary executor errors use only fixed `controller_error`; they do not render the exception.

- [ ] **Step 4: Run controller GREEN 1 and store/event regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_controller.py -k "second_run or invalid_message or get_session or workspace_components or non_daemon or executor_exception" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-controller-green1
.\.venv\Scripts\python.exe -m pytest tests/test_session_store.py tests/test_session_events.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-controller-regression1
```

#### Cycle 7B: sequential follow-up and safe narrative

- [ ] **Step 5: Add follow-up RED tests**

```python
def test_idle_session_accepts_follow_up_with_safe_narrative(tmp_path: Path) -> None:
    executor = BlockingExecutor(tmp_path, (failed_outcome("first"), failed_outcome("second")))
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
    controller.shutdown(timeout_seconds=1.0)
```

Add a test that two runs through `AgentSessionRunExecutor` receive distinct fresh fake model clients/budgets, no continuation from run one, and only the single rendered initial `UserMessage` in run two before its own turns. Assert the accepted workspace file remains shared.

- [ ] **Step 6: Run follow-up RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_controller.py tests/test_session_runtime.py -k "follow_up or fresh.*budget or no.*continuation" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-controller-red2
```

Expected: exit 1 because submit/narrative orchestration is incomplete.

- [ ] **Step 7: Implement idle-only follow-up**

Load narrative before the write transaction, render it with the current message, then call `store.submit_message`. Preserve original database entries; do not inject old tool/verification/provider state. Reject follow-up for running/cancelling/missing/degraded/closed sessions before thread creation.

- [ ] **Step 8: Run follow-up GREEN and context/runtime regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_controller.py tests/test_session_runtime.py -k "follow_up or fresh or continuation" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-controller-green2
.\.venv\Scripts\python.exe -m pytest tests/test_context.py tests/test_agent_loop.py tests/test_app.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-controller-regression2
```

#### Cycle 7C: stream commit/discard and audit-event mapping

- [ ] **Step 9: Add callback lifecycle RED tests**

Create a scripted executor that invokes handlers in this exact order:

```python
def execute(...):
    stream_handler(ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, "discard me"))
    stream_handler(ModelStreamEvent(ModelStreamEventKind.RESPONSE_DISCARDED))
    stream_handler(ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, "keep "))
    stream_handler(ModelStreamEvent(ModelStreamEventKind.TEXT_DELTA, "me"))
    stream_handler(ModelStreamEvent(ModelStreamEventKind.RESPONSE_COMPLETED))
    confirmed_text_handler("keep me")
    run_event_handler(safe_tool_completed_run_event())
    return failed_outcome()
```

Then assert live kinds contain delta/discard/delta/delta/committed/tool-finished in order; durable events contain only `assistant_text_committed` with `keep me` and safe `tool_activity`; no row contains `discard me`, tool arguments, stdout, call ID, API key, or raw result. Add a second executor that emits no deltas and calls `confirmed_text_handler("sync fallback text")`, proving committed persistence and live output.

Add this failure-isolation shape with a `SQLiteSessionStore` subclass whose `append_event` raises `SessionStoreError("storage_unavailable")` only for `TOOL_ACTIVITY`:

```python
def test_run_event_store_failure_degrades_and_returns_to_executor(tmp_path: Path) -> None:
    store = FailingToolActivityStore(tmp_path)
    store.initialize()
    executor = RunEventCallingExecutor(tmp_path)
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
```

`RunEventCallingExecutor.execute` calls `run_event_handler(safe_tool_completed_run_event())` inside a narrow `try/except Exception` used only to record whether the callback escaped, then records `cancellation_requested()`, and returns `failed_outcome()`. Its `workspace` is `tmp_path.resolve(strict=True)`. The assertion proves a durable observer failure reaches controller degradation without reaching model retry/error handling.

- [ ] **Step 10: Run callback RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_controller.py -k "stream_commit_discard or audit_event_mapping or sync_fallback or run_event_store_failure" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-controller-red3
```

Expected: exit 1 because controller callback adapters and audit mapping do not exist.

- [ ] **Step 11: Implement non-throwing callback adapters**

Buffer deltas per current response in memory and publish them immediately. Discard clears the buffer and publishes only fixed discard facts. Confirmed text must equal the provider-complete text supplied by the Agent hook; scrub it, append the durable event, publish committed, and clear the buffer. A pending buffer at worker termination is discarded. Map only accepted `EventType` tool/verification events and exact safe fields. The controller's `run_event_handler` adapter catches `SessionStoreError` itself, calls one idempotent degradation helper that sets the current cancellation token and fixed `controller_error`, then returns normally. It must not rely on `RunEventLogger` swallowing the error, because that would hide the controller's required state transition. Unexpected ordinary observer exceptions remain isolated by the logger; `BaseException` is not caught.

- [ ] **Step 12: Run callback GREEN and provider streaming regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_controller.py -k "stream_commit_discard or audit_event_mapping or sync_fallback or run_event_store_failure" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-controller-green3
.\.venv\Scripts\python.exe -m pytest tests/test_streaming.py tests/test_openai_streaming_client.py tests/test_chat_completions_streaming_client.py tests/test_logging.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-controller-regression3
```

#### Cycle 7D: cancellation, shutdown, thread failure, degradation, and process recovery

- [ ] **Step 13: Add controller cancellation RED tests**

```python
def test_cancel_is_idempotent_and_finishes_interrupted(tmp_path: Path) -> None:
    executor = CooperativeBlockingExecutor(tmp_path)
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
    assert sum(event.kind.value == "cancellation_requested" for event in events) == 1


def test_shutdown_timeout_never_force_stops_worker(tmp_path: Path) -> None:
    executor = UncooperativeBlockingExecutor(tmp_path)
    controller = make_controller(tmp_path, executor)
    controller.create_session("wait for admitted operation")
    assert executor.started.wait(timeout=1.0)
    assert controller.shutdown(timeout_seconds=0.01) is False
    assert executor.forced_stop_calls == 0
    executor.release.set()
    assert controller.shutdown(timeout_seconds=2.0) is True


def test_cancel_token_linearizes_before_durable_transition_failure(tmp_path: Path) -> None:
    store = FailingCancellationStore(tmp_path)
    store.initialize()
    executor = CancellationProbeExecutor(tmp_path)
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
    assert store.cancellation_write_entered.wait(timeout=1.0)
    executor.allow_boundary_check.set()
    assert executor.cancel_observed.wait(timeout=1.0)
    assert executor.next_operation_started is False
    store.release_cancellation_write.set()
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert error_codes == ["storage_unavailable"]
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    with pytest.raises(SessionControllerError) as captured:
        controller.create_session("degraded")
    assert captured.value.code == "controller_degraded"
```

`FailingCancellationStore.request_cancellation` signals `cancellation_write_entered`, waits for `release_cancellation_write`, then raises `SessionStoreError("storage_unavailable")`. `CancellationProbeExecutor.execute` signals `started`, waits for `allow_boundary_check`, records the strict boolean returned by `cancellation_requested`, sets `cancel_observed` instead of marking `next_operation_started`, then waits for `release` and returns an interrupted SDK-free outcome. Every fake executor in this file stores `workspace.resolve(strict=True)`.

Also add tests for thread `.start()` raising `OSError`, finalization failure leaving a recoverable incomplete row, `open()` releasing its lease on initialization failure, restart recovery before new submissions, close rejecting new work, bool/zero/negative/NaN/infinite timeouts, and `SystemExit` recorded through `threading.excepthook` after cleanup rather than converted to an ordinary success/failure.

- [ ] **Step 14: Run controller failure RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_controller.py -k "cancel_is_idempotent or cancel_token_linearizes or shutdown_timeout or thread_start or degraded or finalization or restart_recovery or system_exit" -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-controller-red4
```

Expected: exit 1 because cancellation ownership, shutdown, degradation, and cleanup are incomplete.

- [ ] **Step 15: Implement terminal lifecycle and cleanup**

Use one `threading.Event` cancellation token and one completion event per run. `cancel` acquires the controller lifecycle lock, validates active ownership, and sets the token as the cancellation linearization point before releasing the lock and calling `store.request_cancellation`; it never holds the lifecycle lock across the database call. A successful durable change publishes cancelling once. A durable failure leaves the token set, marks the controller degraded, publishes only fixed `controller_error`, and raises `SessionControllerError("storage_unavailable")` to the caller. `shutdown` marks closed-to-new-work before cancellation and joins outside locks. A thread-start exception finishes the queued run with stable failure and clears active ownership. Worker `finally` always clears active state and signals completion; cleanup for `BaseException` occurs before re-raise. `open` acquires lease, initializes, recovers, and closes the lease on every construction failure.

- [ ] **Step 16: Run controller GREEN and all Task 20 focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_controller.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-controller-green4
.\.venv\Scripts\python.exe -m pytest tests/test_session.py tests/test_session_store.py tests/test_session_events.py tests/test_session_runtime.py tests/test_agent_loop.py tests/test_logging.py tests/test_app.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\task20-focused
```

Expected: exit 0 with actual counts, no skip, no live thread after test cleanup, and no `.coding-agent` write outside each `tmp_path`.

**Acceptance:** one controller safely owns one worker, supports durable sequential follow-ups, emits only safe live data, cooperatively cancels, converges all ordinary failures, and leaves incomplete storage recoverable after catastrophic termination.

### Task 8: Documentation alignment, full verification, review, and user checkpoint

**Files:**
- Modify: `DESIGN.md`
- Inspect: every created/modified file and the complete repository test suite.
- Keep: Task 20 `进行中` in `TASKS.md`.

**Interfaces:**
- Consumes: completed green Task 19–20 behavior.
- Produces: fresh evidence and an accurate design baseline; no commit.

- [ ] **Step 1: Add delivered design facts without claiming deferred UI work**

Update `DESIGN.md` with:

- per-workspace SQLite durable history and workspace lease;
- one session containing sequential independent runs;
- safe narrative rendered as one initial user message;
- one non-daemon active worker and cooperative cancellation;
- provisional in-memory deltas versus confirmed durable text;
- UI-safe bounded update boundary;
- JSONL audit versus SQLite UI-history responsibilities;
- restart recovery as interruption, not resume;
- explicit remaining deferrals: executable/resumable sessions, Skill catalog, MCP, HTTP/SSE, TUI, GUI, accounts, and concurrent runs.

Do not describe future transports, Skill selection, or GUI controls as implemented.

- [ ] **Step 2: Run format and focused Task 19–20 verification**

```powershell
git diff --check
.\.venv\Scripts\python.exe -m pytest tests/test_session.py tests/test_session_store.py tests/test_session_events.py tests/test_session_runtime.py tests/test_session_controller.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\milestone-b-focused
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py tests/test_context.py tests/test_termination.py tests/test_verification.py tests/test_streaming.py tests/test_logging.py tests/test_report.py tests/test_app.py tests/test_cli.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\milestone-b-core-regression
```

Expected: all commands exit 0. Record actual pass/fail/skip/warning counts rather than estimates.

- [ ] **Step 3: Run provider, safety, filesystem, and command regression explicitly**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_model.py tests/test_openai_client.py tests/test_openai_streaming_client.py tests/test_chat_completions_client.py tests/test_chat_completions_streaming_client.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\milestone-b-provider-regression
.\.venv\Scripts\python.exe -m pytest tests/test_path_safety.py tests/test_command_safety.py tests/tools/test_read_tools.py tests/tools/test_write_tools.py tests/tools/test_shell_tool.py -q -p no:cacheprovider --basetemp .\.pytest-tmp\milestone-b-safety-regression
```

Expected: both exit 0, fully offline. The Windows reparse and process-tree tests must execute rather than be permanently skipped.

- [ ] **Step 4: Run Windows-specific session and existing OS acceptance slices**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_store.py -k "process_lease or reparse or symlink or worker_threads or recovery" -q -p no:cacheprovider --basetemp .\.pytest-tmp\milestone-b-windows-session
.\.venv\Scripts\python.exe -m pytest tests/test_path_safety.py -k "reparse or junction or symlink" -q -p no:cacheprovider --basetemp .\.pytest-tmp\milestone-b-windows-path
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "process_tree or timeout or cleanup" -q -p no:cacheprovider --basetemp .\.pytest-tmp\milestone-b-windows-process
```

Expected: all selected tests execute and pass. If target Windows cannot execute a required test, Task 20 stays active and the missing evidence is reported.

- [ ] **Step 5: Run the complete fresh suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .\.pytest-tmp\milestone-b-full
```

Expected: exit 0. Report exact totals, warnings, skips, and failures.

- [ ] **Step 6: Audit signatures, SDK isolation, persistence privacy, and dependency scope**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import inspect; from coding_agent.agent import AgentRunner; from coding_agent.model import ModelClient; from coding_agent.session import make_persisted_run_report; from coding_agent.session_controller import SessionController; from coding_agent.session_store import SessionStore; print(inspect.signature(AgentRunner.run)); print(inspect.signature(ModelClient.complete)); print(inspect.signature(make_persisted_run_report)); print(inspect.signature(SessionController.open)); print(inspect.signature(SessionController.submit_message)); print(inspect.signature(SessionStore.get_run)); print(inspect.signature(SessionStore.list_runs))"
.\.venv\Scripts\python.exe -c "import builtins,importlib,os,socket; [os.environ.pop(name,None) for name in ('OPENAI_API_KEY','CHAT_COMPLETIONS_API_KEY')]; forbidden={'openai','httpx','requests'}; real=builtins.__import__; builtins.__import__=lambda name,*a,**k: (_ for _ in ()).throw(AssertionError(name)) if name.split('.')[0] in forbidden else real(name,*a,**k); socket.socket=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network')); [importlib.import_module(name) for name in ('coding_agent.session','coding_agent.session_store','coding_agent.session_events','coding_agent.session_runtime','coding_agent.session_controller')]"
.\.venv\Scripts\python.exe -m pip check
git diff -- pyproject.toml
rg -n "LangChain|LlamaIndex|Agents SDK|Claude Agent SDK|AutoGen|CrewAI|FastAPI|Starlette|Flask|Django|aiohttp|websocket|MCP" src tests pyproject.toml
rg -n "continuation_items|encrypted|reasoning|instructions|tool_calls|arguments|stdout|stderr|Authorization" src/coding_agent/session*.py tests/test_session*.py
```

Expected: `AgentRunner.run` and `ModelClient.complete` retain accepted signatures; the child process removes provider-key variables before imports, blocks provider/network imports and raw socket construction, and imports every new module without attempting either; `pip check` exits 0; dependency diff is empty; framework scan finds no introduced implementation; sensitive-term matches occur only in explicit rejection/negative tests or non-persistence assertions, never SQLite serialization fields.

- [ ] **Step 7: Scan credentials, personal paths, unfinished markers, and test suppression**

```powershell
$scan = Get-ChildItem -Recurse -File src,tests,docs,AGENTS.md,DESIGN.md,TASKS.md,README.md,README.txt | Where-Object { $_.FullName -notmatch '\\.venv\\|\\.git\\|\\.coding-agent\\|\\.pytest-tmp\\' }
$secretPatterns = @('sk-[A-Za-z0-9]{16,}','Bearer\s+[A-Za-z0-9._-]{12,}','Authorization\s*:')
$pathPatterns = @('C:\\Users\\','D:\\code\\coding_agent')
$unfinishedPatterns = @('TO' + 'DO','TB' + 'D','FIX' + 'ME')
$suppressionPatterns = @('pytest\.mark\.skip','pytest\.mark\.xfail','@unittest\.skip')
$scan | Select-String -Pattern $secretPatterns
$scan | Select-String -Pattern $pathPatterns
$scan | Select-String -Pattern $unfinishedPatterns
$scan | Select-String -Pattern $suppressionPatterns
```

Expected: no real credential, Authorization value, or newly introduced personal absolute path; no unfinished production marker; no new skip/xfail/suppression. Clearly distinguish existing fake-key fixtures and documentation examples from real secrets without printing a suspected secret value.

- [ ] **Step 8: Inspect SQLite and thread ownership invariants through focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_store.py -k "atomic or rollback or unique or recovery or process_lease" -q -p no:cacheprovider --basetemp .\.pytest-tmp\milestone-b-store-invariants
.\.venv\Scripts\python.exe -m pytest tests/test_session_controller.py -k "second_run or workspace_components or cancel or linearizes or shutdown or degraded or run_event_store_failure or thread_start or finalization" -q -p no:cacheprovider --basetemp .\.pytest-tmp\milestone-b-controller-invariants
.\.venv\Scripts\python.exe -m pytest tests/test_session_controller.py tests/test_session_events.py -k "discard or committed or payload or limits or reset" -q -p no:cacheprovider --basetemp .\.pytest-tmp\milestone-b-event-privacy
.\.venv\Scripts\python.exe -m pytest tests/test_session.py tests/test_session_store.py tests/test_session_runtime.py -k "persisted_run_report or unprojected_report or agent_session_executor" -q -p no:cacheprovider --basetemp .\.pytest-tmp\milestone-b-persistence-privacy
```

Expected: exit 0 and direct evidence for atomic state, one active run, bounded updates, no durable provisional text, and deterministic failure convergence.

- [ ] **Step 9: Perform complete diff review and independent code review**

Run:

```powershell
git diff --stat
git status --short --untracked-files=all
git diff -- src/coding_agent tests TASKS.md DESIGN.md docs/superpowers/specs/2026-08-29-session-lifecycle-design.md docs/superpowers/plans/2026-08-29-session-lifecycle-controller.md
```

Read every changed line. Invoke `superpowers:requesting-code-review` for a read-only review of the locked spec, plan, changed production modules, tests, and deferral boundary. Any actionable finding receives a separate RED/GREEN cycle and all affected verification is rerun. Do not commit during review.

- [ ] **Step 10: Check the final acceptance matrix**

| Requirement | Required fresh evidence |
|---|---|
| Workspace SQLite and schema version | initialization/schema tests |
| Strict immutable records and hidden content | domain tests |
| Full FinalReport evidence never enters SQLite | persisted-report projection and unprojected-report rollback tests |
| Stable title and list/event order | domain/store ordering tests |
| Sequential runs per session | follow-up controller/store tests |
| Fresh state/budgets/verification/continuation | production executor follow-up test |
| One initial user message | narrative plus ContextManager test |
| Newest deterministic history selection | narrative omission test |
| Single active run in memory/database/process | busy/index/process-lease tests |
| No restart resume | recovery-without-executor test |
| Delta provisional, valid text durable | commit/discard/sync fallback tests |
| Bounded ordered UI updates | event count/bytes/replay/wait tests |
| Safe tool and verification events | allowlist and audit mapping tests |
| Cancel before first operation | Agent cancellation test |
| Cancel during admitted context preparation | summary-admission/post-prepare cancellation test |
| Cancel after admitted operations | model/tool/verification boundary tests |
| Token linearizes before durable cancellation write | barrier plus injected write-failure test |
| Multi-tool pairing | ModelRequest reconstruction assertion |
| Idempotent cancel and finite shutdown | controller tests |
| Observer failure degrades without reaching provider | run-event store-failure callback test |
| Storage degradation and recovery path | injected store-failure tests |
| Store/lease/executor workspace identity | component mismatch test |
| Thread/start/ordinary/BaseException behavior | controller exception tests |
| JSONL remains audit truth | post-flush observer tests |
| CLI/app output and exits unchanged | app/CLI regressions |
| Provider mapping and stream behavior unchanged | provider regressions |
| Safety and verification unchanged | safety/verification regressions |
| No SDK leakage/network/key/dependency | isolation and scans |
| No Skill/MCP/HTTP/GUI scope leak | source/dependency diff review |
| Complete repository remains green | full pytest output |

Any row without passing fresh evidence blocks a completion claim and leaves Task 20 active.

- [ ] **Step 11: Stop for user review**

Report:

- every RED command, exit code, and expected missing behavior;
- every GREEN and regression command with actual counts;
- created/modified files and reasons;
- SQLite schema/transaction/lease evidence;
- sequential history and fresh-run evidence;
- event buffer, streaming commit/discard, and privacy evidence;
- cancellation boundary and no-extra-operation evidence;
- controller failure/recovery and thread cleanup evidence;
- provider, CLI, safety, verification, dependency, credential, and scope audits;
- warnings, skips, failures, deviations, and unverified items;
- final `git status` and `git diff --stat`.

Keep Task 20 `进行中`. Do not stage, commit, push, start Task 21, create transport/GUI code, or invoke a branch-finishing workflow.

**Acceptance:** the milestone is evidence-complete and reviewable, but remains uncommitted and active until explicit user acceptance.

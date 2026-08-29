# Session Lifecycle and Durable History Design

**Date:** 2026-08-29  
**Status:** Approved  
**Scope:** Task 19 (session domain and SQLite persistence) and Task 20 (single-run controller, cooperative cancellation, and UI-safe events)

## 1. Goal

This milestone adds the framework-neutral backend boundary needed by a later local GUI. A workspace can retain multiple sessions, a session can contain multiple sequential Agent runs, and one process can own at most one active run at a time. A caller can read durable history, observe provisional model text and safe lifecycle events, request cooperative cancellation, and submit a later follow-up message to an idle session.

The existing `AgentRunner` remains the only Agent loop. The existing one-shot CLI remains synchronous and compatible. SQLite stores UI-facing history; the accepted JSONL logger remains the audit record. The two formats have deliberately different responsibilities.

## 2. Locked scope

### 2.1 Included

- one SQLite database per workspace at `.coding-agent/sessions.sqlite3`;
- versioned schema initialization and strict parsing;
- durable sessions, sequential runs, user messages, confirmed assistant text, safe activity events, run summaries, and safe persisted-report projections;
- deterministic session titles derived from the first user message;
- a single-active-run `SessionController` using one background worker thread;
- safe cooperative cancellation at Agent operation boundaries;
- a provider-neutral, UI-safe event envelope with bounded in-memory replay;
- a safe narrative renderer for follow-up runs;
- process ownership for a workspace session database and deterministic recovery of incomplete rows;
- additive composition reuse so the CLI and controller construct the same accepted tools, security policy, verification gate, model clients, logger, and instruction snapshot;
- fully offline tests with injected clocks, ID factories, executors, thread factories, model clients, and filesystem fixtures.

### 2.2 Excluded

- resuming an in-progress `AgentState` after restart;
- persisting provider continuation, reasoning, encrypted content, instructions, tool arguments, tool output, command streams, or provisional model deltas;
- more than one simultaneously active Agent run;
- a pending-run queue;
- forcefully terminating a worker thread, model request, command, or verification process;
- HTTP, SSE, WebSocket, TUI, or GUI code;
- Skill discovery, selection, persistence, or execution;
- MCP, plugin execution, accounts, remote storage, or synchronization;
- deleting, archiving, or renaming sessions;
- new third-party dependencies;
- changes to Task 8 safety policy, Task 11 verification success, provider mappings, or the model/tool message schemas.

Task 21 will own declarative Skill discovery and selection. Later tasks will adapt the controller event boundary to local SSE and then build the light GUI.

## 3. Architecture

The accepted architecture is a layered hybrid:

```text
future GUI/SSE adapter
        |
SessionController -------- SessionEventHub (memory only)
        |
SessionStore (SQLite)      AgentSessionRunExecutor
                                  |
                            existing AgentRunner
                         / model / tools / verification
                                  |
                         existing JSONL audit logger
```

Responsibilities are strict:

- `SessionController` owns lifecycle transitions, one worker, cancellation, and failure convergence. It does not implement reasoning or tool execution.
- `SQLiteSessionStore` owns durable schema and transactions. It does not start threads or publish live events.
- `SessionEventHub` owns an in-memory ordered replay window. It is neither persistence nor audit.
- `AgentSessionRunExecutor` adapts the accepted production composition to the controller without exposing OpenAI SDK objects.
- `AgentRunner` remains the sole Agent state machine.
- `RunEventLogger` remains the audit source. Its optional post-flush observer is additive and receives only already-validated `RunEvent` values.
- `FinalReport` remains the evidence-derived terminal report for the synchronous CLI and in-memory execution result. SQLite stores only a deterministic safe report projection; it never stores the full report's completion text, failure text, verification command, stdout, stderr, or evidence excerpts.

## 4. Workspace storage and ownership

Each configured workspace has independent state:

```text
<workspace>/.coding-agent/sessions.sqlite3
<workspace>/.coding-agent/sessions.lock
```

The internal directory, database, and lock path must be normalized, contained by the configured workspace, and rejected when any existing internal component is a symlink, junction, or other reparse point. These are trusted application paths, not model-facing paths. Existing Task 8 protection continues to prevent tools from reading or modifying `.coding-agent`.

Every workspace-bound component stores `workspace.resolve(strict=True)`. Identity comparison uses `os.path.normcase(str(workspace))` so Windows case aliases compare equal while distinct resolved workspaces are rejected.

`WorkspaceSessionLease` holds a non-blocking operating-system file lock for the controller lifetime and exposes its normalized `workspace: Path`. Windows uses `msvcrt`; non-Windows test and development environments use `fcntl`. Merely finding a lock file is not an ownership signal. A second live controller for the same workspace fails with the stable code `controller_in_use` and must not recover or modify the first controller's rows.

The design retains the accepted local-process and TOCTOU limitations. It does not claim to be an operating-system sandbox.

## 5. Domain model

### 5.1 Stable enums

```python
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
```

Session status describes whether another message may be submitted. Run status is immutable after it reaches `SUCCEEDED`, `FAILED`, or `INTERRUPTED`.

### 5.2 Records

`SessionRecord` is immutable and contains:

- `session_id: str`;
- `title: str`;
- `status: SessionStatus`;
- `created_at_utc: str`;
- `updated_at_utc: str`;
- `last_run_id: str | None`;
- `next_sequence: int`.

`SessionRunRecord` is immutable and contains:

- `run_id: str`;
- `session_id: str`;
- `ordinal: int`;
- `status: SessionRunStatus`;
- `user_event_sequence: int`;
- `started_at_utc: str | None`;
- `finished_at_utc: str | None`;
- `agent_status: str | None`;
- `termination_reason: str | None`;
- `audit_run_id: str | None`;
- `final_report: JSONObject | None`, containing only the persisted safe report projection defined below.

`SessionEvent` is immutable and contains:

- `session_id: str`;
- `run_id: str | None`;
- `sequence: int`;
- `kind: PersistedSessionEventKind`;
- `created_at_utc: str`;
- `data: JSONObject`, hidden from `repr`.

IDs are lowercase UUID hex strings. Production uses `uuid.uuid4().hex`; tests inject an ID factory. Timestamps are UTC ISO 8601 strings with `Z`; tests inject a timezone-aware clock.

### 5.3 Persisted event kinds

- `user_message`;
- `run_queued`;
- `run_started`;
- `assistant_text_committed`;
- `tool_activity`;
- `verification_activity`;
- `cancellation_requested`;
- `run_finished`;
- `run_recovered`.

User and assistant content is stored only in the specific message events. Generic lifecycle event payloads cannot contain arbitrary text.

`run_finished.data` is the exact deterministic safe run summary. `SessionRunResult` carries that already-validated `safe_summary` separately from its optional safe persisted report projection, so storage never infers UI history from provider or exception content. `load_narrative()` projects only `user_message`, `assistant_text_committed`, and `run_finished` summary events, in sequence order; it ignores tool and verification activity.

The safe summary has exactly these keys: `status`, `exit_code`, `termination_reason`, `changed_paths`, `verification_status`, `mutation_index`, `validation_index`, `logical_model_calls`, `provider_attempts`, `tool_calls`, and `verification_attempts`. Unavailable controller-level facts are null and changed paths are empty; extra final-report fields are never copied.

The separately stored safe report projection is built by `make_persisted_run_report(report: JSONObject) -> JSONObject`. Its top-level allowlist is exactly `schema_version`, `run_id`, `status`, `exit_code`, `termination_reason`, `changed_paths`, `mutation_index`, `validation_index`, `verification`, `logical_model_calls`, `provider_attempts`, `tool_calls`, `verification_attempts`, `context_compressions`, `token_usage`, `elapsed_ms`, `log_failure_code`, and `log_path`. `verification` contains exactly `status`, `source`, `exit_code`, `timed_out`, `truncated`, `duration_ms`, `validation_index`, and `error_code`; `token_usage` contains exactly `input_tokens`, `output_tokens`, `total_tokens`, `responses_with_usage`, and `responses_without_usage`. `log_path` must be a normalized relative `.coding-agent/logs/<run_id>.jsonl` path. The projected `run_id` is the audit run ID, must equal `SessionRunResult.audit_run_id`, and its status/termination facts must agree with the terminal result. The projection rejects malformed or extra nested values and never includes `completion`, `failure_reason`, `command`, `stdout`, `stderr`, provider payloads, or evidence excerpts.

### 5.4 Title and size rules

The title is derived from the first non-empty line of the first message, collapses whitespace, and keeps at most 80 Unicode code points. A longer title uses a deterministic final ellipsis. Title generation happens after known-sensitive-value scrubbing and never calls a model.

Controller input and persistence enforce these UTF-8 byte limits:

- user message: 65,536 bytes;
- confirmed assistant text: 262,144 bytes;
- encoded safe event JSON: 65,536 bytes;
- encoded safe persisted report JSON: 524,288 bytes.

The safe narrative renderer also verifies the current request against the existing `ContextManager.measure()` limit before creating a run. Therefore a value may satisfy the storage byte limit but still be rejected as `invalid_message` when its model-facing JSON representation cannot fit as the single initial message. No database row is created for that rejected submission.

## 6. SQLite schema and transactions

`PRAGMA user_version` is the schema version authority. Version 1 contains:

- `sessions` for the current session snapshot;
- `session_runs` for ordered run records and terminal reports;
- `session_events` for the durable UI-safe timeline.

Required constraints include:

- primary IDs are non-empty text;
- `(session_id, ordinal)` is unique;
- `(session_id, sequence)` is unique;
- status columns have exact `CHECK` allowlists;
- foreign keys reference their session and run;
- a partial unique index permits at most one `queued`, `running`, or `cancelling` run in the workspace database;
- event sequence and run ordinal are positive;
- final report is null until terminal.

Every connection enables foreign keys and a finite busy timeout. The initialized file uses WAL. Public operations obtain their own connections instead of sharing a raw connection across the controller and worker threads.

Multi-row state changes are atomic:

- creating a session writes the session, first user event, and queued run in one transaction;
- submitting a follow-up writes the user event, advances sequence, and creates the queued run in one transaction;
- starting changes the run and session together and writes `run_started`;
- cancellation changes the run and session together and writes `cancellation_requested` once;
- finishing stores confirmed text not already committed, safe events, terminal report, terminal run status, and idle session snapshot together;
- recovery marks all incomplete runs interrupted, writes `run_recovered`, and returns sessions to idle in one transaction.

Unknown newer schema versions, malformed stored JSON, constraint violations, corruption, and unavailable storage produce stable `SessionStoreError` codes. The application never silently deletes, recreates, or overwrites an existing database.

## 7. Store interface

```python
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
```

Repository methods validate exact types and stable ranges before opening a write transaction. List order is `updated_at_utc DESC, session_id ASC`. Events are returned in sequence order.

`SessionSubmission` is an immutable triple containing the updated `SessionRecord`, accepted user `SessionEvent`, and newly queued `SessionRunRecord`. This makes user acceptance and queued-run creation one indivisible operation. `start_run()` changes that existing queued row to running; it never allocates a second run.

## 8. Sequential follow-up semantics

A session can accept another message only while idle. Each accepted message creates a fresh run with fresh:

- `AgentState`;
- logical model and provider-attempt budget;
- tool budget and error counters;
- verification state and evidence;
- continuation tuple;
- JSONL run and `FinalReport`.

Filesystem changes persist because all runs target the same workspace. Prior execution state does not persist.

`SessionNarrativeRenderer` converts durable history to one structured initial `UserMessage`. It contains canonical JSON records for prior user messages, confirmed assistant text, and deterministic safe run summaries, followed by the complete current request. It adds newest history first until `ContextManager.measure((UserMessage(rendered),))` would exceed the accepted maximum, then emits a deterministic omitted-entry count. The same input produces byte-identical text.

No old tool call, tool result, `call_id`, continuation, reasoning, provider payload, verification evidence, or previous budget is included. This keeps the existing context invariant: one initial user message followed only by the current run's assistant/tool turns.

`AgentState.task` and `current_goal` remain the current user message, not the rendered session context. `AgentState.start` receives an additive optional initial message value, and `AgentRunner.run(task)` keeps its accepted signature.

## 9. Agent integration

`AgentRunner` gains additive constructor inputs:

```python
initial_user_message: str | None = None
cancellation_requested: Callable[[], bool] | None = None
confirmed_text_handler: Callable[[str], None] | None = None
```

Existing callers omit all three and preserve accepted behavior.

The confirmed-text handler is called only for non-empty text from a valid complete main `ModelResponse`, including a synchronous fallback. Provisional stream deltas never call it. The controller-provided handler is non-throwing; it validates, scrubs, publishes, and persists through its own failure boundary.

Cancellation is checked:

- before context preparation and a model call;
- after a model call returns;
- before and after every tool execution;
- before and after required verification;
- before the next loop iteration.

The check immediately before `ContextManager.prepare()` admits one complete context-preparation operation, including an optional summary model request. A cancellation arriving after that admission allows preparation and its summary request to finish, but the post-prepare check blocks the main model request. The same rule applies to one already-admitted model, tool, or verification operation: it may return or time out, but no later operation is admitted after the cancellation token's linearization point. If a tool-call batch has unresolved calls, every unexecuted call receives a stable paired rejected `ToolResult` before the state becomes interrupted. Cooperative cancellation returns `AgentStatus.INTERRUPTED` and `TerminationReason.USER_INTERRUPTED`; it does not raise `AgentInterrupted`. Real `KeyboardInterrupt` retains the accepted `AgentInterrupted` behavior, and `SystemExit` is not swallowed.

## 10. Controller and execution boundary

```python
class SessionRunExecutor(Protocol):
    @property
    def workspace(self) -> Path: ...

    def execute(
        self,
        request: SessionRunRequest,
        *,
        stream_handler: ModelStreamHandler,
        confirmed_text_handler: ConfirmedTextHandler,
        cancellation_requested: Callable[[], bool],
        run_event_handler: Callable[[RunEvent], None],
    ) -> SessionRunOutcome: ...
```

`AgentSessionRunExecutor` is the production implementation. It reuses the accepted `RunConfig`, provider selection, instruction builder, five-tool registry, execution context, command executor, verification gate, termination policy, JSONL logger, and report creation. No OpenAI SDK type appears in the controller, store, event, or domain modules.

`SessionRunOutcome` carries `safe_summary: JSONObject` independently from `final_report`. `AgentSessionRunExecutor` derives `final_report` with `make_persisted_run_report(execution.report.to_dict())`; the full `FinalReport` remains available only to the existing CLI execution path. The controller passes `safe_summary` unchanged into `SessionRunResult.safe_summary`; the store validates its exact allowlist and writes it as `run_finished.data`. Controller/thread failures construct the same schema with null unavailable counters and no raw exception.

`run_application()` retains its signature, stdout/stderr cardinality, synchronous behavior, and exit codes. Shared composition is extracted without moving policy decisions into the controller.

`SessionController` exposes:

```python
def create_session(first_message: str) -> RunHandle
def submit_message(session_id: str, message: str) -> RunHandle
def get_session(session_id: str) -> SessionView
def list_sessions(*, limit: int = 50) -> tuple[SessionRecord, ...]
def cancel(run_id: str) -> CancellationResult
def read_updates(run_id: str, *, after_sequence: int = 0) -> SessionUpdateBatch
def wait_for_updates(run_id: str, *, after_sequence: int, timeout_seconds: float) -> SessionUpdateBatch
def wait_for_run(run_id: str, *, timeout_seconds: float | None = None) -> SessionRunRecord
def shutdown(*, timeout_seconds: float) -> bool
```

The controller constructor accepts a `SessionStore`, `WorkspaceSessionLease`, and `SessionRunExecutor` that all expose a normalized `workspace: Path`; it rejects any platform-normalized identity mismatch before recovery or thread creation. `SessionEventHub` is process memory and has no filesystem identity. The convenience constructor is exactly:

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

`ThreadFactory` is `Callable[[Callable[[], None], str], WorkerThread]`. `WorkerThread` exposes read-only `daemon` and `name` plus `start()`, `join(timeout)`, and `is_alive()`. `default_thread_factory(target, name)` returns `threading.Thread(target=target, name=name, daemon=False)`.

Creation and submission return only after a non-daemon worker has been started. A thread-start failure atomically records a failed run and returns `thread_start_failed`. There is no queue. A controller lock protects in-memory ownership but is never held while a model, tool, verification command, callback, database busy wait, or thread join runs.

Cancellation is idempotent. Under the controller lifecycle lock, a first request sets the cancellation token; that write is the linearization point that blocks later operation admission. The controller then persists the cancelling state and durable event without holding the lifecycle lock. If persistence fails, the token remains set and the controller becomes degraded. A repeated request returns the same outcome without a duplicate durable event. Cancelling a terminal run returns `already_finished`. `shutdown` prevents new submissions, requests cancellation, waits up to the supplied finite positive timeout, and returns false without force when the current operation remains active.

## 11. UI-safe live events

`SessionUpdate` is a provider-neutral immutable envelope:

```python
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
```

`to_json()` is canonical compact UTF-8 JSON using `ensure_ascii=False`, `sort_keys=True`, `separators=(",", ":")`, and `allow_nan=False`. Event-hub byte accounting uses `len(update.to_json().encode("utf-8"))`.

Kinds are:

- `run_queued`;
- `run_started`;
- `run_cancelling`;
- `assistant_text_delta`;
- `assistant_text_committed`;
- `assistant_text_discarded`;
- `tool_started`;
- `tool_finished`;
- `verification_started`;
- `verification_finished`;
- `run_finished`;
- `controller_error`.

The envelope never contains provider objects, continuation, reasoning, encrypted content, instructions, API keys, authorization headers, tool arguments, tool output, stdout, stderr, or raw exceptions. Tool updates may contain only tool name, status, duration, truncation, exit code, safe error code, and normalized changed paths.

`SessionEventHub` retains the current or most recently finished run only. It assigns sequences from 1, retains at most 1,000 events and at most 1,048,576 encoded bytes, and evicts oldest events until both constraints hold. `read` is non-blocking. `wait` uses `threading.Condition` and a finite injected timeout; it does not create a polling thread. A cursor older than the retained prefix receives `reset_required=True` and must reload durable history.

Text delta is provisional. The controller buffers it only in memory. `RESPONSE_COMPLETED` is followed by the `confirmed_text_handler`, which persists the exact complete response text and emits `assistant_text_committed`. `RESPONSE_DISCARDED` or an interrupted response clears the provisional buffer, emits `assistant_text_discarded`, and writes no text row. A non-streaming fallback still invokes the confirmed handler.

## 12. Audit bridge

`RunEventLogger` accepts an optional post-flush observer. A successfully validated, serialized, written, and flushed `RunEvent` is passed to the observer. The controller maps only accepted tool, verification, and run lifecycle facts to session updates and persisted safe events.

An ordinary observer exception is isolated from the audit result and Agent state. The controller-supplied observer adapter catches `SessionStoreError` itself, marks the controller degraded, sets the cancellation token, publishes one fixed `controller_error`, and returns normally so the model/provider layer cannot reinterpret a persistence failure as a retryable model error. The logger still isolates any unexpected ordinary `Exception` raised by another observer. `KeyboardInterrupt`, `SystemExit`, and other `BaseException` values are not swallowed. Existing logger construction without an observer is unchanged.

## 13. Failure handling

Stable public error codes are:

- `invalid_message`;
- `session_not_found`;
- `run_not_found`;
- `controller_busy`;
- `invalid_session_state`;
- `controller_in_use`;
- `storage_unavailable`;
- `schema_unsupported`;
- `database_corrupt`;
- `controller_degraded`;
- `controller_closed`;
- `thread_start_failed`.

Errors and representations do not include message bodies, API keys, provider error bodies, database content, or absolute personal paths.

- A write failure before thread start prevents execution.
- A durable write failure during execution puts the controller in degraded state, requests cancellation, and rejects future runs.
- A finalization failure emits a memory-only `controller_error`; incomplete rows are recovered after the next successful lease acquisition.
- No unknown SQLite failure is retried indefinitely.
- No corrupt or unsupported database is automatically replaced.
- Consumer disconnects do not affect the worker because consumers read from the event hub rather than run inside the producer callback.

## 14. Recovery and terminal mapping

After obtaining the workspace lease and initializing the schema, the controller atomically maps legacy incomplete `QUEUED`, `RUNNING`, and `CANCELLING` rows to `INTERRUPTED`, records reason `process_restarted`, appends `run_recovered`, and returns sessions to `IDLE`. It never constructs an `AgentState` or repeats a model, tool, mutation, or verification operation.

Terminal mapping is exact:

- `AgentStatus.SUCCESS` to `SessionRunStatus.SUCCEEDED`;
- `AgentStatus.INTERRUPTED` or `AgentInterrupted` to `SessionRunStatus.INTERRUPTED`;
- `AgentStatus.FAILED`, `COMPLETION_CANDIDATE`, unexpected nonterminal return, or ordinary production exception to `SessionRunStatus.FAILED`.

Only the existing fresh-verification route can create `AgentStatus.SUCCESS`. This milestone does not add a second success path.

## 15. Privacy and security

- Known sensitive values, including the configured API key, are scrubbed before title, message, summary, update, event, or report persistence.
- The full `FinalReport` is never written to SQLite; only the exact persisted-report allowlist is eligible for storage.
- Content and JSON payload fields are hidden from dataclass representations.
- Stored conversations are still local sensitive data and may contain source excerpts not recognizable as credentials; documentation must state that explicitly.
- SQLite and lock files remain under the ignored protected internal directory.
- The store never logs SQL parameters or raw SQLite errors to UI-visible text.
- No provider continuation, reasoning, instruction body, tool output, or provisional text is serialized.
- No network is used by default tests.
- No Agent framework, ORM, web framework, or database dependency is introduced.

## 16. Task decomposition

### Task 19: Session domain and protected SQLite persistence

Task 19 delivers the domain records, deterministic title and run summary, workspace lease, schema, repository transactions, stable list/load behavior, corruption/version failures, and incomplete-run recovery. It does not create a worker or call `AgentRunner`.

### Task 20: Single-run controller, cancellation, and UI-safe event bridge

Task 20 delivers the safe narrative renderer, bounded event hub, additive Agent cancellation and confirmed-text hooks, controller thread lifecycle, production execution adapter, post-flush audit observer, and CLI compatibility. It does not create a transport or interface.

Task 18 is marked completed only after baseline verification. During execution, Task 19 becomes active first. After Task 19 acceptance passes, Task 19 becomes completed and Task 20 becomes active. Task 20 remains active at the final user review checkpoint.

## 17. Test and acceptance requirements

All new behavior follows strict RED, minimal GREEN, and focused regression cycles. Tests use temporary workspaces and databases, fake executors, fake model clients, injected clocks and IDs, thread synchronization primitives, and subprocesses only for real workspace-lock verification. They use no external API, real credential, arbitrary sleep, permanent skip, or xfail.

Acceptance requires evidence for:

1. deterministic titles, IDs under injection, strict records, and hidden representations;
2. schema initialization, newer-version rejection, malformed-data rejection, and atomic rollback;
3. stable session list order, event order, and sequential run ordinals;
4. one active run within one controller and across two controllers;
5. a real Windows process lock test without permanent skip;
6. crash recovery without Agent execution;
7. multiple follow-ups with fresh budgets, verification state, and continuation;
8. one valid initial user message under existing context compression rules;
9. deterministic newest-first narrative selection and stable oversized-message rejection;
10. provisional delta, confirmed text, discarded text, and synchronous fallback;
11. no durable provisional text;
12. cancellation before context preparation and after an admitted summary/model/tool/verification operation without admitting one extra operation;
13. paired rejected tool results when a batch is cancelled;
14. idempotent cancellation and finite shutdown;
15. bounded event count and bytes, ordered replay, wait, and reset-required behavior;
16. safe tool and verification event payloads;
17. cancellation-token linearization before the durable cancellation transition, including injected persistence failure;
18. storage degradation, thread-start failure, observer failure isolation, and terminal finalization behavior;
19. store, lease, and executor workspace-identity agreement;
20. full-report rejection plus safe persisted-report projection without completion, failure, command, stdout, or stderr evidence;
21. unchanged `KeyboardInterrupt`, `SystemExit`, CLI, provider, safety, verification, logging, and report behavior;
22. no SDK leakage, network, credentials, new dependency, Agent framework, deferred Skill/MCP/HTTP/GUI code, or provider payload persistence;
23. complete Task 1–19 regression and Windows reparse/process-tree tests.

## 18. Deferred sequence

- Task 21: declarative Skill discovery, selection, persistence, and immutable snapshots;
- Task 22: local HTTP/SSE adapter over `SessionController` and `SessionEventHub`;
- Task 23: light local GUI with session sidebar, large central conversation area, elapsed-time/status header, and bottom input;
- later separately approved work: MCP and executable extensions.

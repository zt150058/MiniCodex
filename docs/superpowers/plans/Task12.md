# Task 12 Redacted JSONL Run Log and Final Report Implementation Plan

> **Execution workflow:** Execute this plan in order with `superpowers:executing-plans`, `superpowers:test-driven-development`, `superpowers:systematic-debugging` for reproducible unexpected failures, and `superpowers:verification-before-completion` before reporting results. Work directly in the current `main` workspace. Do not create a branch, worktree, subagent, commit, or remote operation.

**Goal:** Add one protected, per-run, redacted JSONL audit log and one deterministic final report without changing the Task 1–11 Agent decisions, safety rules, model protocol, verification freshness rule, or CLI behavior.

**Architecture:** A centralized `RunEventLogger` owns the event schema, sequence, clocks, allowlist, redaction, secure internal path creation, UTF-8 JSONL writes, and run metadata. `AgentRunner` remains the only owner of top-level semantic ordering. A provider-neutral observation seam in `model.py` exposes logical model calls and physical attempts, including Task 9 retries, without SDK types. `ContextManager` adds one pure threshold query so `AgentRunner` can emit compression-started before any summary call. `FinalReport` is built directly from final `AgentState` plus `RunMetadata`; it never reparses the JSONL file or reconstructs state from prose.

**Approved basis:** `AGENTS.md`; `DESIGN.md` sections 2, 4–8, 10–17; `TASKS.md` Task 12; the accepted Task 8 protected-path policy; Task 10 context, counters, continuation, termination, and interruption contracts; Task 11 verification evidence and `SUCCESS` contract.

## Planning baseline

- Repository root: `D:\code\coding_agent`.
- Branch: `main`.
- HEAD: `34980a60e43f96fcd85b04f1f5b2bc1ac3c7d175` (`完善验证逻辑`).
- Task 11's accepted implementation is at HEAD. The user explicitly authorized correcting its stale `TASKS.md` status from `进行中` to `已完成`; that is the only pre-plan diff.
- Task 12 remains `未开始` throughout planning. Approved execution changes it to `进行中` and leaves it there at the review stop.
- `git diff --check` exits 0. The status correction produces only the expected `TASKS.md` diff.
- A sandboxed run with a writable base temp reached `654 passed, 2 failed`; both failures were Task 7 process-tree cleanup because the restricted account could not complete `taskkill.exe` cleanup.
- The same full offline suite run outside that restriction with a fresh host-owned base temp exited 0: `656 passed, 0 failed, 0 skipped, 1 warning` in 17.08 seconds. The warning is the existing inability to create `D:\code\coding_agent\.pytest_cache`; it is not a product failure.

## Architectural alternatives and decision

### Alternative A — every component writes its own log

This gives each component direct knowledge of its events, but it spreads logging, secret handling, clock, and failure semantics through the OpenAI adapter, tool implementations, context manager, and verification gate. It also creates several possible sequence owners.

### Alternative B — reconstruct all events after the run

This minimizes integration edits, but final state cannot prove the ordering of provider retries, blocked operations, context compression failure, or verification attempts. Reconstruction would fabricate an audit trail rather than record one.

### Alternative C — centralized semantic logger plus narrow provider-neutral observations

This is selected. `AgentRunner` emits state-machine events before and after operations. `model.py` emits SDK-free model observations around logical calls and actual provider attempts. Existing components continue returning their accepted values; tools and `VerificationGate` do not acquire logger dependencies. One logger owns sequence and persistence, and one state machine remains authoritative.

## Locked file map

### Create

- `src/coding_agent/logging.py` — event types, allowlist schemas, redaction, run metadata, model-observation adapter, secure JSONL creation, sequence/time, and stable logging errors.
- `src/coding_agent/report.py` — immutable final report, bounded evidence excerpts, invariant validation, exit mapping, and deterministic rendering.
- `tests/test_logging.py` — path, schema, ordering, clocks, privacy, failure, model-attempt, Agent integration, and Task 8 protection tests.
- `tests/test_report.py` — report construction, success/failure/interruption, bounded evidence, counters, ordering, redaction, and invariant tests.

### Modify

- `src/coding_agent/model.py` — additive provider-neutral `ModelObservation`, `ModelObservationKind`, `ModelCallPurpose`, observer field on `ModelCallBudget`, and observed begin/end helpers. Keep `ModelClient.complete` unchanged.
- `src/coding_agent/openai_client.py` — emit safe physical-attempt outcomes through `ModelCallBudget`; preserve constructor and `complete`/`complete_with_budget` signatures, retry count, delay, mapping, and errors.
- `src/coding_agent/context.py` — add the pure `requires_compression(messages)` query and pass `ModelCallPurpose.SUMMARY` to `invoke_model`; do not change compression thresholds or output.
- `src/coding_agent/state.py` — add only `TerminationReason.AUDIT_LOG_FAILURE`.
- `src/coding_agent/agent.py` — optional logger injection and event ordering; keep run return type and all Task 10/11 decisions.
- `tests/test_model.py` — observation and no-observer compatibility tests.
- `tests/test_openai_client.py` — provider retry observation tests using fake SDK clients.
- `tests/test_context.py` — pure compression-query and summary-purpose tests.
- `tests/test_agent_loop.py` — no-logger compatibility, complete event order, blocked operations, interruption, and logger-failure integration.
- `TASKS.md` — during approved execution Task 0 only: Task 11 remains `已完成`; change Task 12 from `未开始` to `进行中`. Task 12 remains `进行中` at the final review stop.

### Read and keep unchanged

- `src/coding_agent/messages.py`
- `src/coding_agent/verification.py`
- `src/coding_agent/safety.py`
- `src/coding_agent/termination.py`
- `src/coding_agent/config.py`
- `src/coding_agent/cli.py`
- every file under `src/coding_agent/tools/`
- all existing tests except those explicitly listed under Modify
- `pyproject.toml`, `AGENTS.md`, and `DESIGN.md`

`safety.py` stays unchanged. The logger is a trusted internal writer with a dedicated, non-model-controlled path routine. `PathGuard` continues rejecting `.coding-agent` for every model-visible file tool.

## Locked public interfaces

### Provider-neutral model observations (`model.py`)

```python
class ModelCallPurpose(StrEnum):
    MAIN = "main"
    SUMMARY = "summary"


class ModelObservationKind(StrEnum):
    LOGICAL_STARTED = "logical_started"
    LOGICAL_COMPLETED = "logical_completed"
    LOGICAL_FAILED = "logical_failed"
    LOGICAL_BLOCKED = "logical_blocked"
    PROVIDER_STARTED = "provider_started"
    PROVIDER_COMPLETED = "provider_completed"
    PROVIDER_FAILED = "provider_failed"
    PROVIDER_BLOCKED = "provider_blocked"


@dataclass(frozen=True, slots=True)
class ModelObservation:
    kind: ModelObservationKind
    purpose: ModelCallPurpose
    logical_call_index: int
    provider_attempt_index: int | None = None
    message_count: int | None = None
    tool_schema_count: int | None = None
    continuation_count: int | None = None
    has_text: bool | None = None
    text_chars: int | None = None
    tool_call_count: int | None = None
    usage: TokenUsage | None = None
    provider_response_id_hash: str | None = None
    error_code: str | None = None
    retry_scheduled: bool | None = None
    retry_delay_ms: int | None = None


class ModelObservationSink(Protocol):
    def observe_model(self, observation: ModelObservation) -> None: ...
```

`ModelObservation.__post_init__` validates the exact allowed field combinations per kind. It contains no request body, message text, tool arguments, continuation object, SDK object, environment mapping, exception object, or provider exception body.

`ModelCallBudget` gains one optional field and four methods:

```python
observer: ModelObservationSink | None = field(default=None, repr=False, compare=False)

def begin_logical_call(
    self,
    purpose: ModelCallPurpose,
    request: ModelRequest,
) -> int: ...

def finish_logical_call(
    self,
    purpose: ModelCallPurpose,
    logical_call_index: int,
    *,
    response: ModelResponse | None,
    error_code: str | None,
) -> None: ...

def begin_provider_attempt(self, purpose: ModelCallPurpose) -> int: ...

def finish_provider_attempt(
    self,
    purpose: ModelCallPurpose,
    provider_attempt_index: int,
    *,
    error_code: str | None,
    retry_scheduled: bool,
    retry_delay_ms: int | None,
) -> None: ...
```

The accepted `start_logical_call`, `claim_provider_attempt`, and counter fields remain available and unchanged for existing direct budget tests. The observed helpers call the observer before incrementing a permitted operation, then increment exactly once. If the limit is already reached they emit only the corresponding `BLOCKED` observation and raise the existing `ModelBudgetExceeded` without incrementing. If the observer fails before an operation, the operation and its counter do not start.

`invoke_model` gains one compatible keyword-only argument:

```python
def invoke_model(
    client: ModelClient,
    request: ModelRequest,
    budget: ModelCallBudget,
    *,
    purpose: ModelCallPurpose = ModelCallPurpose.MAIN,
) -> ModelResponse: ...
```

It emits one logical start and exactly one logical completed or failed observation. For a non-budget-aware client it also emits the single provider attempt. A `BudgetAwareModelClient` continues owning its own physical attempt boundary so observations are not duplicated. `ContextManager` explicitly uses `SUMMARY`; `AgentRunner` uses the default `MAIN`.

### Run logging (`logging.py`)

```python
EVENT_SCHEMA_VERSION = 1


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    MODEL_CALL_STARTED = "model_call_started"
    MODEL_CALL_COMPLETED = "model_call_completed"
    MODEL_CALL_FAILED = "model_call_failed"
    MODEL_CALL_BLOCKED = "model_call_blocked"
    PROVIDER_ATTEMPT_STARTED = "provider_attempt_started"
    PROVIDER_ATTEMPT_COMPLETED = "provider_attempt_completed"
    PROVIDER_ATTEMPT_FAILED = "provider_attempt_failed"
    PROVIDER_ATTEMPT_BLOCKED = "provider_attempt_blocked"
    CONTEXT_COMPRESSION_STARTED = "context_compression_started"
    CONTEXT_COMPRESSION_COMPLETED = "context_compression_completed"
    CONTEXT_COMPRESSION_FAILED = "context_compression_failed"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_CALL_BLOCKED = "tool_call_blocked"
    MUTATION_RECORDED = "mutation_recorded"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_COMPLETED = "verification_completed"
    VERIFICATION_EVIDENCE_RECORDED = "verification_evidence_recorded"
    VERIFICATION_BLOCKED = "verification_blocked"
    COMPLETION_CANDIDATE = "completion_candidate"
    RUN_COMPLETED = "run_completed"


@dataclass(frozen=True, slots=True)
class RunEvent:
    schema_version: int
    run_id: str
    sequence: int
    timestamp_utc: str
    elapsed_ms: int
    event_type: EventType
    data: JSONObject

    def to_dict(self) -> JSONObject: ...
    def to_json(self) -> str: ...


@dataclass(slots=True)
class TokenUsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    responses_with_usage: int = 0
    responses_without_usage: int = 0


@dataclass(slots=True)
class RunMetadata:
    run_id: str
    log_path: str
    started_at_utc: str
    context_compression_count: int = 0
    token_usage: TokenUsageTotals = field(default_factory=TokenUsageTotals)
    finished_elapsed_ms: int | None = None
    log_failure_code: str | None = None


class RunLogError(RuntimeError):
    code: str

    def __init__(self, code: str) -> None: ...


class EventSink(ModelObservationSink, Protocol):
    @property
    def metadata(self) -> RunMetadata: ...

    def emit(self, event_type: EventType, data: JSONObject) -> RunEvent: ...


class RunEventLogger(ModelObservationSink):
    @classmethod
    def create(
        cls,
        workspace: Path,
        *,
        run_id: str | None = None,
        sensitive_values: tuple[str, ...] = (),
        utc_clock: Callable[[], datetime] = _utc_now,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> RunEventLogger: ...

    @property
    def metadata(self) -> RunMetadata: ...

    def emit(self, event_type: EventType, data: JSONObject) -> RunEvent: ...
    def observe_model(self, observation: ModelObservation) -> None: ...
    def close(self) -> None: ...
```

`_utc_now()` returns `datetime.now(timezone.utc)` in production. Tests inject a zero-argument callable returning an aware UTC datetime. `MemoryEventSink` exists only in `tests/test_logging.py`; production code contains no second logger.

`AgentRunner.__init__` gains one additive keyword:

```python
event_sink: EventSink | None = None
```

`None` performs no event work, creates no `.coding-agent` directory, and preserves all accepted Task 1–11 behavior. Every injected `EventSink` also implements `ModelObservationSink`, so it is supplied directly to the run-scoped `ModelCallBudget`. The production `RunEventLogger` implements the combined protocol.

### Context threshold query (`context.py`)

```python
def requires_compression(self, messages: tuple[Message, ...]) -> bool: ...
```

It uses the existing `measure` result and exact Task 10 rule: `serialized_chars > max_serialized_chars or history_items > max_history_items`. `prepare` calls the same method, so logging cannot drift from compression behavior.

### Final report (`report.py`)

```python
REPORT_SCHEMA_VERSION = 1
MAX_REPORT_COMPLETION_CHARS = 4096
MAX_REPORT_COMMAND_CHARS = 4096
MAX_REPORT_STREAM_CHARS = 8192


@dataclass(frozen=True, slots=True)
class EvidenceExcerpt:
    text: str
    original_chars: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class VerificationReport:
    status: VerificationStatus
    source: CommandSource | None
    command: str | None
    exit_code: int | None
    timed_out: bool
    truncated: bool
    duration_ms: int | None
    validation_index: int | None
    stdout: EvidenceExcerpt | None
    stderr: EvidenceExcerpt | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class FinalReport:
    schema_version: int
    run_id: str
    status: AgentStatus
    exit_code: int
    completion: EvidenceExcerpt | None
    termination_reason: TerminationReason | None
    failure_reason: str | None
    changed_paths: tuple[str, ...]
    mutation_index: int
    validation_index: int | None
    verification: VerificationReport
    logical_model_calls: int
    provider_attempts: int
    tool_calls: int
    verification_attempts: int
    context_compressions: int
    token_usage: TokenUsageTotals
    elapsed_ms: int
    log_failure_code: str | None
    log_path: str

    @classmethod
    def from_state(
        cls,
        state: AgentState,
        metadata: RunMetadata,
        *,
        sensitive_values: tuple[str, ...] = (),
    ) -> FinalReport: ...

    def to_dict(self) -> JSONObject: ...
    def to_json(self) -> str: ...


class ReportInvariantError(RuntimeError):
    """Final state and controlled run metadata contradict each other."""
```

`to_dict()` preserves the field order shown above. Nested verification and excerpt fields preserve declaration order. `to_json()` uses UTF-8-compatible Unicode (`ensure_ascii=False`), two-space indentation, no sorted-key rewrite, and one trailing newline. Task 12 returns/render this value through the explicit builder API; printing it from the real CLI remains Task 13.

## JSONL location and creation policy

- Canonical path: `<workspace>/.coding-agent/logs/<run_id>.jsonl`.
- `RunMetadata.log_path` and the final report contain only the normalized workspace-relative POSIX path, for example `.coding-agent/logs/0123...cdef.jsonl`, not an absolute user path.
- Every run owns one file. Files are never appended across runs.
- Auto IDs use `uuid.uuid4().hex`, exactly 32 lowercase hexadecimal characters. An injected test ID must match the same exact pattern.
- The logger canonicalizes the existing workspace first. It rejects a reparse workspace root.
- It creates `.coding-agent`, then `logs`, one component at a time. Before and after each creation it uses `os.lstat` and Windows `st_file_attributes` to reject symlinks, junctions, and every reparse point. Existing non-directory components are rejected.
- After each step it resolves the component and verifies containment with `os.path.commonpath` and `os.path.normcase`.
- The filename is derived only from the validated run ID; no model text, task, provider ID, call ID, or command participates in the path.
- The final file is opened in exclusive text creation mode `x`, UTF-8, `newline="\n"`. An injected-ID collision raises `RunLogError(code="log_file_exists")`. Auto generation retries ID creation at most 16 times, then raises `run_id_collision`.
- Every event is serialized completely before writing. A successful emit performs one `write(line + "\n")` followed immediately by `flush()`; `fsync` is not used because the approved requirement is immediate process-buffer flush, not crash-consistent disk journaling.
- The file always ends with a newline after every successful event. Partial operating-system writes cannot be rolled back; a write/flush failure poisons the logger, stores a stable failure code, and stops the Agent before another model/tool/verification operation.
- `close()` is idempotent. Close failure uses `log_close_failed`; it never erases a previous failure code.
- Model tools continue to receive `PathGuard`, which rejects `.coding-agent` case-insensitively. The logger never passes its internal path to a tool.

## Sequence and time semantics

- Sequence starts at `1` for `run_started`.
- The logger computes a candidate sequence, constructs and serializes the event, writes and flushes it, then commits the sequence. Serialization or write failure does not consume the sequence.
- After any failure the logger is poisoned; every later emit raises `RunLogError(code="log_unavailable")` without another write.
- `timestamp_utc` is an RFC 3339 UTC value with six fractional digits and terminal `Z`, for example `2026-08-28T01:02:03.456789Z`.
- `elapsed_ms` is `max(0, floor((monotonic_now - logger_start) * 1000))`. A non-finite value or a value before the start raises `invalid_clock` before writing.
- Tests inject independent fake wall and monotonic clocks. No test sleeps.
- `run_started` is the first successful event. Every ordinary return path attempts exactly one `run_completed` event.
- `SUCCESS`, failed/budget termination, and interruption all use `run_completed`; its data distinguishes status and reason. There is no second terminal event type.
- `SystemExit` remains uncaught, so Task 12 does not promise a terminal event for it. `KeyboardInterrupt` is converted by the existing handler, and the logger makes one best-effort interrupted terminal write before `AgentInterrupted` is raised.
- If terminal logging itself fails, there is no fabricated second terminal line. The final state/report uses `AUDIT_LOG_FAILURE` for ordinary paths; on an already occurring keyboard interrupt, user interruption remains primary and `RunMetadata.log_failure_code` reports the audit failure.

## Event data allowlists

The logger rejects missing or extra keys, wrong types, non-finite numbers, oversized arrays, and unrecognized enum strings before serialization. No generic recursive arbitrary-object redactor exists.

| Event | Exact `data` fields |
| --- | --- |
| `run_started` | `task_chars`, `mutation_index` |
| `model_call_started` | `purpose`, `logical_call_index`, `provider_attempts_before`, `message_count`, `tool_schema_count`, `continuation_count` |
| `model_call_completed` | `purpose`, `logical_call_index`, `provider_attempts_after`, `has_text`, `text_chars`, `tool_call_count`, `usage`, `provider_response_id_hash`, `continuation_count` |
| `model_call_failed` | `purpose`, `logical_call_index`, `provider_attempts_after`, `error_code` |
| `model_call_blocked` | `purpose`, `reason`, `logical_calls`, `provider_attempts` |
| `provider_attempt_started` | `purpose`, `logical_call_index`, `provider_attempt_index` |
| `provider_attempt_completed` | `purpose`, `logical_call_index`, `provider_attempt_index` |
| `provider_attempt_failed` | `purpose`, `logical_call_index`, `provider_attempt_index`, `error_code`, `retry_scheduled`, `retry_delay_ms` |
| `provider_attempt_blocked` | `purpose`, `logical_call_index`, `reason`, `provider_attempts` |
| `context_compression_started` | `before_chars`, `before_items`, `continuation_count` |
| `context_compression_completed` | `before_chars`, `before_items`, `after_chars`, `after_items`, `summary_source`, `summary_model_failed`, `continuation_cleared` |
| `context_compression_failed` | `before_chars`, `before_items`, `reason` |
| `tool_call_started` | `ordinal`, `tool_name`, `call_id_hash`, `mutation_index` |
| `tool_call_completed` | `ordinal`, `tool_name`, `call_id_hash`, `status`, `safe_error_code`, `output_chars`, `exit_code`, `timed_out`, `truncated`, `duration_ms`, `changed_paths`, `mutation_index_before`, `mutation_index_after`, `executed` |
| `tool_call_blocked` | `ordinal`, `tool_name`, `call_id_hash`, `reason`, `executed` |
| `mutation_recorded` | `mutation_index`, `changed_paths`, `verification_status` |
| `verification_started` | `source`, `command_hash`, `mutation_index`, `attempt_index` |
| `verification_completed` | `source`, `status`, `exit_code`, `timed_out`, `truncated`, `duration_ms`, `validation_index`, `mutation_index`, `stdout_chars`, `stderr_chars`, `error_code` |
| `verification_evidence_recorded` | same fields as `verification_completed`, plus `command_hash`; it represents an already executed credible model tool result and never claims a second execution |
| `verification_blocked` | `source`, `reason`, `mutation_index`, `executed` |
| `completion_candidate` | `text_chars`, `mutation_index`, `validation_index`, `verification_status` |
| `run_completed` | `status`, `termination_reason`, `logical_model_calls`, `provider_attempts`, `tool_calls`, `verification_attempts`, `mutation_index`, `validation_index`, `elapsed_ms` |

`usage` is explicit null or exactly `input_tokens`, `output_tokens`, and `total_tokens`. `changed_paths` preserves `AgentState.modified_paths`/tool metadata first-seen order; it is not resorted. `call_id_hash`, `command_hash`, and `provider_response_id_hash` are lowercase SHA-256 hex strings, so raw provider/model-controlled identifiers and commands do not enter JSONL.

## Privacy and redaction policy

- Event payloads never accept message text, task text, model output, tool arguments, tool output, verification stdout/stderr, file content, request body, response object, continuation value, environment mapping, exception object, exception string, Authorization header, or encrypted reasoning.
- Text-bearing allowlist fields are limited to enum values, tool names, normalized workspace-relative changed paths, and stable local error codes.
- Tool names are limited to 128 Unicode characters after control-character rejection. Changed paths are limited to 260 characters each and at most 40 entries per event. Values over the bound cause `invalid_event_data`; they are not silently serialized.
- Logical model failures use only `transient_model_error`, `fatal_model_error`, `invalid_model_response`, `model_budget_exceeded`, or `model_client_error`. Physical OpenAI attempts use only `rate_limit`, `server_error`, `timeout`, `connection_error`, `authentication_rejected`, `permission_rejected`, `not_found`, `request_rejected`, or `provider_error`. These codes are selected by local exception class/status branches; exception strings are never parsed.
- Known sensitive values supplied to `RunEventLogger.create` and `FinalReport.from_state` are replaced by `[REDACTED]` before any permitted text is stored or rendered. Empty values are ignored.
- Permitted report text is additionally scrubbed for `Bearer <token>`, OpenAI-style `sk-...`, and case-insensitive assignment forms for `api_key`, `apikey`, `authorization`, `token`, `secret`, and `password`. Replacement is deterministic and occurs before truncation.
- JSONL does not include completion text, commands, stdout, or stderr at all; it stores only lengths and hashes.
- `repr(RunEventLogger)`, `repr(RunMetadata)`, `repr(FinalReport)`, and `repr(EvidenceExcerpt)` do not expose sensitive report text. `EvidenceExcerpt.text` is marked `repr=False`; `VerificationReport.command` is marked `repr=False`.
- A logger error uses only stable codes: `invalid_workspace`, `invalid_run_id`, `log_path_reparse`, `log_path_outside_workspace`, `log_directory_invalid`, `log_file_exists`, `run_id_collision`, `invalid_clock`, `invalid_event_data`, `event_serialization_failed`, `log_write_failed`, `log_flush_failed`, `log_close_failed`, and `log_unavailable`. Operating-system and serialization exception text is never copied into state, events, repr, or reports.

## Locked event ordering

1. `run_started` is emitted after `AgentState.start` and before context inspection or any model/tool/verification operation.
2. Model logical and physical observations are emitted by `invoke_model`/the budget. A retry sequence is `model_call_started`, then repeated `provider_attempt_started`, `provider_attempt_failed`, then a final started/completed or failed, then one `model_call_completed` or `model_call_failed`.
3. A blocked logical/provider budget emits only the corresponding blocked event; it never emits a started/completed pair and never increments the blocked counter.
4. If compression is required, `context_compression_started` precedes the summary logical call. On success the Agent atomically assigns prepared messages and cleared continuation, then emits `context_compression_completed`. On failure it emits `context_compression_failed` before the terminal event.
5. `tool_call_started` is emitted immediately before `ToolRegistry.execute`. A returned `ok`, `error`, or `rejected` result produces one `tool_call_completed` with `executed=true`; safety rejection is identified only by its stable safety code.
6. If a tool call is forbidden by a Task 10 precheck, `tool_call_blocked` is emitted with `executed=false`. The existing paired rejected `ToolResult` is still appended, but no started/completed event or tool count is fabricated for it.
7. The Agent applies `_record_successful_mutation` before `mutation_recorded`; therefore the event's index is the new index. It follows the corresponding tool completion event and precedes any verification evidence observation.
8. A required Task 11 command gets `verification_started` after its tool/time precheck and before `VerificationGate.evaluate`. It gets one `verification_completed` after the result is recorded. If precheck blocks it, only `verification_blocked` is emitted.
9. A credible model-selected verification is already represented by tool events. If `observe_tool_result` records it, the Agent emits `verification_evidence_recorded`; it does not emit another start or increment a second attempt.
10. `completion_candidate` is emitted before gate evaluation. It never implies success. A passing verification completes before `run_completed(status="success")`.
11. All ordinary failed states, including budget reasons and `AUDIT_LOG_FAILURE`, use the same terminal state source. Logging never changes budget priority or turns a candidate into success.

## Logging failure strategy

- `RunLogError` before an operation propagates to the outer `AgentRunner.run` guard. The guard synchronizes the real model budget, sets `FAILED`, `termination_reason=AUDIT_LOG_FAILURE`, `failure_reason="audit_log_failure"`, stores `metadata.log_failure_code`, and returns without another model/tool/verification operation.
- If an operation completed but its after-event fails, its real state/counter/result remains; the run then stops with `AUDIT_LOG_FAILURE`.
- A failed `run_completed` write downgrades an ordinary success/failure return to `FAILED/AUDIT_LOG_FAILURE`; no replacement terminal JSON line is fabricated.
- Logger failure does not get converted into model/tool error counters and is never retried.
- During `KeyboardInterrupt`, `AgentRunner` first produces the existing `INTERRUPTED/USER_INTERRUPTED` state, then makes one best-effort terminal emit. A logging failure is recorded in metadata but does not replace the interrupt or swallow `AgentInterrupted`.
- `SystemExit` continues to propagate untouched. No report or complete JSONL tail is promised for it.
- Task 13 will decide whether to print the already built nonzero report to stderr. Task 12 does not wire stdout/stderr or change CLI exits.

## Final report semantics

- `FinalReport.from_state` rejects a nonterminal `RUNNING` or `COMPLETION_CANDIDATE` state with `ReportInvariantError("state is not terminal")`.
- Exit `0` is allowed only for `AgentStatus.SUCCESS` with a `PASSED` `VerificationResult`, `exit_code == 0`, `timed_out is False`, and `validation_index == mutation_index`.
- `INTERRUPTED` maps to exit `130` and reason `USER_INTERRUPTED`.
- Every other terminal Agent state maps to exit `1`. Startup/configuration exit `2` remains owned by the existing CLI and is deferred to Task 13 integration because no `AgentState` exists for a rejected configuration.
- `COMPLETION_CANDIDATE` is never renderable as success.
- `changed_paths` preserves `AgentState.modified_paths` first-seen order.
- Logical calls, provider attempts, tool calls, verification attempts, mutation index, validation index, status, reason, and evidence come only from final `AgentState`.
- Context-compression count, token totals, elapsed time, run ID, and relative log path come only from `RunMetadata`. The report never parses JSONL.
- Token totals add every non-null main and summary `TokenUsage`. `responses_without_usage` makes incomplete provider usage explicit; a missing usage object is never treated as zero evidence.
- Completion text is scrubbed then capped at 4096 characters. Command is scrubbed then capped at 4096 characters. Verification stdout/stderr are independently scrubbed then capped at 8192 characters, with original post-redaction character counts and explicit report truncation flags.
- The existing shell already bounds each stream by 65,536 raw bytes. The report applies its own smaller rendering cap and combines `VerificationResult.truncated` with excerpt truncation; it never claims the excerpt is the complete stream when either limit applied.
- `failure_reason` is accepted only when it equals the stable `termination_reason.value`; arbitrary exception text is rejected.
- The report includes the JSONL relative path even after logger failure so the user can inspect any successfully flushed prefix. `log_failure_code` is copied from the stable `RunMetadata.log_failure_code`, while `termination_reason=AUDIT_LOG_FAILURE` states the run outcome; neither contains an exception body.

---

## Task 0: Reconfirm and activate Task 12

**Files:** Read all locked baseline files. Modify only Task 12's status after checks pass.

1. Re-read `AGENTS.md`, `DESIGN.md`, `TASKS.md`, Task 8/10/11 plans, and every source/test in the locked file map.
2. Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git log -5 --oneline
git status --short --untracked-files=all
git diff --check
.\.venv\Scripts\python.exe -m pytest -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-baseline
```

3. Expected: D: repository, `main`, Task 11 commit at HEAD, only the user-authorized Task 11 status correction plus approved `Task12.md`, whitespace exit 0, and full suite exit 0 with real totals. On the restricted runner, use a newly named writable base temp; if Windows process-tree cleanup is permission-blocked, rerun the identical suite outside that restriction with another fresh base temp and report both outputs.
4. Change only Task 12 from `未开始` to `进行中`. Assert exactly Task 12 is `进行中`.

**Acceptance:** baseline evidence is fresh, no unapproved diff exists, and no production/test file changes before the first RED.

---

## Task 1: Implement the event envelope, allowlists, secure path, and JSONL writer

**Files:** Create `src/coding_agent/logging.py`; create `tests/test_logging.py`.

### RED 1A — envelope, clocks, sequence, JSONL format

Add deterministic `FakeUtcClock` and `FakeMonotonicClock`, then tests equivalent to:

```python
def test_jsonl_has_deterministic_envelope_sequence_utf8_and_newline(tmp_path: Path) -> None:
    logger = RunEventLogger.create(
        tmp_path,
        run_id="0" * 32,
        utc_clock=FakeUtcClock("2026-08-28T01:02:03.456789+00:00"),
        monotonic_clock=FakeMonotonicClock(10.0, 10.125, 10.250),
    )
    first = logger.emit(EventType.RUN_STARTED, {
        "task_chars": 2,
        "mutation_index": 0,
    })
    second = logger.emit(EventType.TOOL_CALL_STARTED, {
        "ordinal": 1,
        "tool_name": "读取",
        "call_id_hash": "a" * 64,
        "mutation_index": 0,
    })
    logger.close()

    assert first.sequence == 1
    assert second.sequence == 2
    assert first.timestamp_utc == "2026-08-28T01:02:03.456789Z"
    assert second.elapsed_ms == 250
    raw = (tmp_path / ".coding-agent" / "logs" / ("0" * 32 + ".jsonl")).read_bytes()
    assert raw.endswith(b"\n")
    lines = raw.decode("utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["sequence"] for line in lines] == [1, 2]
    assert "读取" in raw.decode("utf-8")
```

Also test sequence starts at one, explicit nulls, exact envelope keys, invalid/nonmonotonic/non-finite clocks, serialization failure, and immediate flush using an injected recording stream.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_logging.py -k "envelope or sequence or utf8 or newline or clock or flush" -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-1a
```

Expected RED: import failure because `coding_agent.logging` does not exist. A fixture/syntax failure is not an acceptable RED.

Implement only the envelope, clocks, schemas required by these nodes, writer, and stable errors. Run the same command for GREEN.

### RED 1B — path creation, collision, reparse denial, and Task 8 separation

Add tests for:

- exact relative path and exclusive creation;
- invalid run IDs including separators, uppercase, short, long, and nonhex;
- injected collision and 16 auto-ID collisions;
- `.coding-agent` or `logs` already being a file;
- real Windows symlink/junction/reparse at either internal component;
- workspace root being a reparse point;
- containment and case normalization;
- `ReadFileTool`, `ListDirectoryTool`, `ReplaceTextTool`, and `WriteFileTool` still rejecting `.coding-agent` after a logger creates it.

Use real OS link helpers that fail the test with the Windows error code if the environment cannot create required reparse evidence; do not skip or xfail.

Run explicit path/security nodes. Expected RED: secure internal creation is absent. Implement the dedicated internal path routine without changing `PathGuard` or any tool. Run GREEN and:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-1b
```

### RED 1C — exact event schemas and privacy boundary

Parameterize every `EventType` with one valid exact object, then missing, extra, wrong-type, non-finite, and oversized cases. Add sentinel values to attempted message text, command, output, environment, continuation, and exception-like fields and assert they are rejected before write. Add permitted field tests proving known keys, bearer values, OpenAI-style keys, and assignment patterns are scrubbed.

Run the privacy/schema nodes. Expected RED: schemas/redaction are incomplete. Implement per-event validators and bounded permitted-string scrubbers; do not add an arbitrary object walker. Run GREEN.

**Task 1 regression:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_logging.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-1-regression-a
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_path_safety.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-1-regression-b
```

**Acceptance:** independent valid UTF-8 JSON objects, continuous committed sequence, protected per-run path, real reparse denial, exact allowlists, no sensitive arbitrary payload, and unchanged model-tool protection.

---

## Task 2: Expose logical calls and physical attempts without SDK leakage

**Files:** Modify `src/coding_agent/model.py`, `src/coding_agent/openai_client.py`, `tests/test_model.py`, `tests/test_openai_client.py`; extend `tests/test_logging.py` for observation mapping.

### RED 2A — provider-neutral observation types and generic client

Add a `RecordingModelObserver` and tests proving:

```python
def test_generic_client_emits_one_logical_and_one_physical_attempt() -> None:
    observer = RecordingModelObserver()
    budget = ModelCallBudget(observer=observer)
    response = invoke_model(
        FakeModelClient((ModelResponse(text="ok", usage=TokenUsage(3, 2, 5)),)),
        request(),
        budget,
        purpose=ModelCallPurpose.MAIN,
    )
    assert response.text == "ok"
    assert [item.kind for item in observer.items] == [
        ModelObservationKind.LOGICAL_STARTED,
        ModelObservationKind.PROVIDER_STARTED,
        ModelObservationKind.PROVIDER_COMPLETED,
        ModelObservationKind.LOGICAL_COMPLETED,
    ]
    assert budget.logical_calls == 1
    assert budget.provider_attempts == 1
```

Cover transient/fatal errors, blocked logical/provider limits, observer failure before claim, observer failure after actual client return, no observer, summary purpose, usage null, provider ID hashing, and repr omission. Assert Task 3 `FakeModelClient` requests remain unchanged.

Run named nodes. Expected RED: observation types and keyword do not exist. Implement minimal observed helpers and `invoke_model` integration. Run GREEN plus `tests/test_model.py` complete.

### RED 2B — Task 9 retries and delays

Using the existing fake SDK exception factories, add exact sequences for 429, 5xx, timeout, connection error, authentication, bad request, and provider-attempt exhaustion. For two transient failures then success assert:

```python
assert sdk.responses.calls == 3
assert sleeper.delays == [0.25, 0.50]
assert provider_kinds == [
    PROVIDER_STARTED, PROVIDER_FAILED,
    PROVIDER_STARTED, PROVIDER_FAILED,
    PROVIDER_STARTED, PROVIDER_COMPLETED,
]
assert [event.retry_delay_ms for event in failures] == [250, 500]
assert budget.provider_attempts == 3
```

Assert stable error codes only, no SDK exception text, request body, key, Authorization header, or response object. Permanent errors have one physical attempt and no retry. Budget-blocked third attempt has no started event and no SDK call.

Expected RED: OpenAI retries claim counts but expose no observations. Modify only the existing attempt loop to call budget observed helpers around the exact current `responses.create`. Preserve `max_retries=0`, `store=False`, retry count, delays, mapping, and public signatures. Run GREEN and all Task 9 tests.

### RED 2C — mapping into JSONL and metadata

Feed all valid `ModelObservation` variants into `RunEventLogger.observe_model`. Assert exact event types/fields, sequence, token aggregation for main and summary responses, `responses_without_usage`, hashes instead of raw IDs, and no continuation contents.

Expected RED: logger observation mapping is absent. Implement the adapter and metadata updates only after the corresponding event write succeeds.

**Task 2 regression:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_model.py tests\test_openai_client.py tests\test_logging.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-2-regression-a
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_agent_loop.py tests\test_context.py tests\test_termination.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-2-regression-b
```

**Acceptance:** one physical event per real request, Task 9 retry order and counters match, no private-field inference, no SDK type above the adapter, and no behavior change when the observer is absent.

---

## Task 3: Integrate context, tool, mutation, blocked-operation, and terminal events

**Files:** Modify `src/coding_agent/context.py`, `src/coding_agent/agent.py`, `tests/test_context.py`, `tests/test_agent_loop.py`, `tests/test_logging.py`.

### RED 3A — one compression predicate and event lifecycle

Add boundary tests at exact character/item limits and one above. Assert `requires_compression` and `prepare` make the same decision. Add Agent tests for:

- no compression produces no compression event and preserves continuation;
- compression started occurs before summary model started;
- completion occurs after messages/continuation are atomically applied;
- completion records source and continuation cleared;
- transient summary failure records fallback completion;
- fatal/budget/uncompressible failure records compression failed then run completed;
- neither summary prompt nor old/new continuation appears in logger repr/JSON.

Expected RED: threshold query/event integration is absent. Implement the pure method, explicit summary purpose, and minimal Agent ordering. Run GREEN and all context tests.

### RED 3B — tool, safety, mutation, and mid-batch blocking

Use offline recording tools and existing `ToolRegistry` to cover `ok`, ordinary `error`, `security_rejected`, changed paths, repeated calls, tool limit, time limit, and a multi-tool response stopped after the first execution. Assert:

```text
tool_call_started
tool_call_completed
mutation_recorded            # only for real changed_paths
```

For unexecuted calls assert only `tool_call_blocked(executed=false)`, the paired rejected `ToolResult`, no Registry invocation, no tool counter increment, and no started/completed event. Assert raw arguments, output, error message, file contents, and call ID are absent; only hashes, lengths, safe code, metadata, and paths remain.

Expected RED: Agent has no event sink. Add the optional constructor argument and event calls without moving any Task 10 budget check or Task 6 mutation update. Run GREEN and full Agent/tool regressions.

### RED 3C — terminal outcomes and exact last event

Parameterize normal candidate without gate, Task 11 success, fatal/empty/model-error budget, tool/time/safety/repetition/context termination, internal invariant, and user interrupt. Assert:

- first successful event is `run_started`;
- ordinary return has exactly one last `run_completed`;
- candidate without a gate ends with status `completion_candidate`, not success;
- successful gate ends with status `success` only after verification completion;
- failure/budget reason equals state reason;
- `KeyboardInterrupt` best-effort terminal is interrupted, then `AgentInterrupted` carries the same state;
- `SystemExit` propagates and no fabricated terminal event is asserted.

Expected RED: terminal wrapper is absent. Refactor `run` to centralize normal completion logging while preserving `_run_loop` decisions and return type. Run GREEN.

### RED 3D — no-logger compatibility

Run every existing Agent scenario with `event_sink=None` and compare final state fields, request list, tool executions, verification executions, continuation, and exception semantics to the accepted behavior. Assert no `.coding-agent` directory is created.

If these tests pass immediately after prior GREEN, record them as compatibility confirmation; do not invent a failure. Any difference is a regression and must be debugged before proceeding.

**Task 3 regression:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py tests\test_context.py tests\test_termination.py tests\test_logging.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-3-regression-a
.\.venv\Scripts\python.exe -m pytest tests\tools tests\test_path_safety.py tests\test_command_safety.py tests\test_verification.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-3-regression-b
```

**Acceptance:** event observation follows rather than controls state decisions, blocked operations are truthful, mutation ordering is exact, one terminal event exists when persistence works, and the default path remains byte-for-behavior compatible.

---

## Task 4: Integrate Task 11 verification and logging-failure stop behavior

**Files:** Modify `src/coding_agent/state.py`, `src/coding_agent/agent.py`, `tests/test_agent_loop.py`, `tests/test_logging.py`. Keep `verification.py` unchanged.

### RED 4A — verification events and success ordering

Add exact event-list tests for:

- required pass;
- required nonzero failure followed by another model turn;
- timeout with partial bounded output lengths;
- startup error and ordinary executor error reduced to stable codes;
- credible model verification evidence;
- noncredible/inspect/test tool result not represented as evidence;
- stale evidence after mutation;
- required verification blocked by tool/time budget;
- completion candidate with missing evidence returning to RUNNING.

Assert `verification_started` is before required executor invocation, `verification_completed` is after state evidence assignment, and success `run_completed` follows it. Model evidence uses only `verification_evidence_recorded`; it does not fabricate a second execution.

Expected RED: verification semantic events are absent. Add event projection around existing `VerificationGate` calls and observations. Do not modify the gate, credibility classifier, freshness predicate, or tool counts. Run GREEN plus every Task 11 test.

### RED 4B — write, flush, serialization, open, and terminal failures

Use fake streams/sinks that fail at controlled event numbers. Test:

- failure writing `run_started` starts no model/tool operation;
- failure writing model/tool/verification started prevents that operation and its counter claim;
- failure writing an after-event preserves the completed operation's real counter/result, then stops;
- failure writing terminal event downgrades ordinary success to `FAILED/AUDIT_LOG_FAILURE` without a second terminal line;
- serialization failure does not consume sequence;
- logger remains poisoned and is not retried;
- exception bodies containing key/Bearer/provider payload never reach state, event, repr, or report metadata;
- interruption remains `USER_INTERRUPTED` even if its best-effort terminal write fails.

Expected RED: stable audit failure reason/outer guard is absent. Add `AUDIT_LOG_FAILURE` and one outer catch. No logger error increments model/tool/safety counters or changes verification evidence. Run GREEN.

**Task 4 regression:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_logging.py tests\test_agent_loop.py tests\test_verification.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-4-regression-a
.\.venv\Scripts\python.exe -m pytest tests\test_model.py tests\test_openai_client.py tests\test_context.py tests\test_termination.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-4-regression-b
```

**Acceptance:** all Task 11 outcomes are auditable without output bodies, failure to audit stops future work, success remains freshness-gated, and interruption/SystemExit semantics remain accepted.

---

## Task 5: Build the deterministic bounded final report

**Files:** Create `src/coding_agent/report.py`; create `tests/test_report.py`.

### RED 5A — exact fields, order, exits, and success invariant

Construct real `AgentState`, `VerificationResult`, and `RunMetadata` values. Add:

```python
def test_success_report_uses_state_and_metadata_without_reading_log(tmp_path: Path) -> None:
    state = successful_state(tmp_path, mutation_index=2, validation_index=2)
    metadata = run_metadata(
        run_id="1" * 32,
        log_path=".coding-agent/logs/" + "1" * 32 + ".jsonl",
        elapsed_ms=1250,
        compressions=1,
        usage=(10, 4, 14),
    )
    report = FinalReport.from_state(state, metadata)
    assert report.status is AgentStatus.SUCCESS
    assert report.exit_code == 0
    assert report.mutation_index == report.validation_index == 2
    assert report.logical_model_calls == state.logical_model_call_count
    assert report.provider_attempts == state.model_call_count
    assert report.context_compressions == 1
```

Monkeypatch file reads to fail, proving the report does not parse JSONL. Test failure reasons, all budget reasons, audit failure, interrupt 130, candidate/running rejection, missing/stale/contradictory success evidence, changed-path order, zero-mutation success, and Task 11 exact fresh predicate.

Expected RED: report module is absent. Implement immutable types, validation, and exit mapping. Run GREEN.

### RED 5B — bounded output, redaction, repr, and deterministic rendering

Use completion, command, stdout, and stderr containing:

- more than each exact character cap;
- multibyte Unicode at the boundary;
- known injected key;
- `Authorization: Bearer ...`;
- `sk-...` and assignment patterns;
- continuation/encrypted-reasoning sentinels.

Assert scrub-before-truncate, exact character counts after scrub, explicit truncation, no broken Unicode, no sentinel in repr/JSON, two-space deterministic JSON, exact key order, explicit null values, and exactly one trailing newline. Assert JSONL remains length/hash only while report excerpts contain only bounded redacted evidence.

Expected RED: excerpts/redaction/rendering are absent. Implement minimum scrubber reuse and renderer. Run GREEN.

### RED 5C — token completeness and shared facts

Add main/summary responses with and without usage through `RunEventLogger`, then build a report from its metadata and final state. Assert totals and missing-usage count. Assert model/tool/verification counters come from state even if a deliberately inconsistent fake metadata object tries to supply alternatives; `RunMetadata` has no duplicate fields for those counters.

Expected RED: aggregation/report integration is incomplete. Correct only metadata aggregation or report projection. Run GREEN.

**Task 5 regression:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_report.py tests\test_logging.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-5-regression-a
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py tests\test_verification.py tests\test_context.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-5-regression-b
```

**Acceptance:** no report state reconstruction, no candidate-as-success, exact exit semantics, stable facts, bounded redacted evidence, and deterministic output ready for Task 13 to print.

---

## Task 6: Cross-component audit scenarios

**Files:** Extend `tests/test_logging.py` and `tests/test_report.py` only. Production changes are allowed only for a demonstrated locked-contract defect.

### RED/integration scenarios

Build fully offline scenarios with `FakeModelClient`, fake SDK client, fake tools, fake verification executor, fake clocks, and temporary workspaces:

1. main response calls a read tool, a mutating tool, required verification passes, and final state succeeds;
2. required verification fails, model repairs, mutation invalidates evidence, second verification passes;
3. OpenAI fake retries twice, context then compresses, continuation clears, and the main call continues;
4. safety rejection repeats to termination;
5. tool batch stops at budget and pairs every result;
6. keyboard interruption during model, tool, and verification boundaries;
7. logger fails at every before-operation boundary in a parameterized matrix.

For each scenario assert exact event type list, continuous sequence, counter equality with state, terminal status/reason, report equality, and absence of sensitive sentinels in raw JSONL and rendered report. An integration case may be green immediately because earlier TDD stages already implemented the behavior; record it as confirmation rather than manufacturing a failure.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_logging.py tests\test_report.py -k "integration or complete_order or failure_boundary" -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-6-integration
```

Then run Task 8–11 regressions:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\test_command_safety.py tests\test_openai_client.py tests\test_context.py tests\test_termination.py tests\test_verification.py tests\test_agent_loop.py tests\tools -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-6-regression
```

**Acceptance:** one event stream explains the run without containing provider payloads, one report matches final facts, and no accepted security/context/verification behavior changes.

---

## Task 7: Final offline verification and review stop

No production behavior is added here. Use fresh base-temp names and report actual counts.

### Focused suites

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_logging.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-final-logging
.\.venv\Scripts\python.exe -m pytest tests\test_report.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-final-report
.\.venv\Scripts\python.exe -m pytest tests\test_model.py tests\test_openai_client.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-final-model
.\.venv\Scripts\python.exe -m pytest tests\test_context.py tests\test_termination.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-final-context
.\.venv\Scripts\python.exe -m pytest tests\test_verification.py tests\test_agent_loop.py -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-final-agent
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\test_command_safety.py tests\tools -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-final-safety
```

Each command must exit 0. Report passed, failed, skipped, warning, and Windows reparse/process-tree evidence separately.

### Complete Task 1–11 regression

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=D:\code\coding_agent\.coding-agent\pytest-temp\task12-final-full
```

Expected: exit 0 with fresh real totals. If the restricted account blocks `taskkill.exe` or a required Windows reparse operation, rerun outside that restriction; retain both outputs and do not describe the restricted result as green.

### Public signature and ownership audit

Use `inspect.signature` to assert:

- `ModelClient.complete(ModelRequest) -> ModelResponse` unchanged;
- `OpenAIResponsesClient.__init__`, `complete`, and `complete_with_budget` unchanged;
- `VerificationGate` signatures unchanged;
- `PathGuard` and `CommandPolicy` signatures unchanged;
- `AgentRunner.run(self, task: str) -> AgentState` unchanged;
- only additive `event_sink`, observation, context query, and report APIs exist.

Scan production imports and fail if OpenAI SDK appears outside `openai_client.py`, logging imports appear in tools/verification/safety, or Task 2 message types changed.

### Event, sequence, and physical-attempt audit

- Parse every line from representative log files independently with `json.loads`.
- Verify schema version 1, exact envelope keys, sequence `1..N`, monotonic elapsed, first `run_started`, and at most one successful last `run_completed`.
- Search every `responses.create` path and prove `provider_attempt_started`/count acquisition occurs immediately before it.
- Prove Task 9 retry delays/calls/events are `[250, 500]` milliseconds and three attempts in the two-failure case.
- Prove summary and main calls share the same budget observer and report usage totals.
- Prove blocked operations have no started/completed event and no execution.

### Privacy, credentials, and continuation audit

Scan raw logs, rendered reports, repr values, source, tests, and docs for real-key patterns, Bearer headers, environment dumps, provider request bodies, exception bodies, continuation snapshots, encrypted reasoning, and full message-history serialization. Test sentinel credentials only. Confirm event schemas do not contain generic payload/body/message/output/arguments/environment fields.

### Safety and protected-directory audit

- Run all real Windows symlink/junction/reparse tests with zero skip/xfail.
- Prove logger creation rejects reparse internal components.
- Prove every model file tool still rejects `.coding-agent` after a log exists.
- Confirm `safety.py`, filesystem tools, command policy, and protected component rules have no diff.

### Deferred scope, dependency, and suppression audit

Confirm:

- `pyproject.toml` has no diff and no new dependency;
- no network test or real API call exists;
- no Agent framework exists;
- no CLI Agent assembly, console printing, demo project, integration fixture directory, README/video/ZIP behavior, or Task 13 feature was added;
- no skipped/xfail test, weakened assertion, unfinished production marker, or placeholder instruction was introduced.

### Diff and status audit

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff -- src\coding_agent\logging.py src\coding_agent\report.py src\coding_agent\model.py src\coding_agent\openai_client.py src\coding_agent\context.py src\coding_agent\state.py src\coding_agent\agent.py tests\test_logging.py tests\test_report.py tests\test_model.py tests\test_openai_client.py tests\test_context.py tests\test_agent_loop.py TASKS.md
```

Review every changed line. Task 12 remains `进行中`; do not stage, commit, push, start Task 13, or invoke a branch-finishing workflow.

---

## Final acceptance matrix

| Requirement | Evidence |
| --- | --- |
| Exact `.coding-agent/logs/<run_id>.jsonl` | path/relative-report test |
| One exclusive file per run | collision and two-run tests |
| Deterministic injectable run ID | exact 32-hex validation tests |
| Internal writer does not relax tools | four file-tool protected-path tests |
| No path escape or reparse log path | containment plus real Windows link/junction tests |
| UTF-8 JSONL, one object per line, trailing newline | raw-byte/independent-parse test |
| Immediate flush | recording-stream test |
| Sequence begins at one and is continuous | envelope and complete-run tests |
| Failed write does not consume sequence | controlled serialization/write failure tests |
| Deterministic UTC and elapsed clocks | fake-clock test |
| First event is run started | all complete-order scenarios |
| Model metadata without bodies | model observation/privacy tests |
| Physical retries ordered and counted | Task 9 two-retry event test |
| Logical and physical counts remain distinct | model budget plus final-report tests |
| Tool success/error/safety rejection | tool event matrix |
| Blocked/unexecuted tool distinguished | mid-batch budget test |
| Mutation follows completed modification | mutation event/index test |
| Compression and continuation lifecycle | compression event/order test |
| Verification pass/fail/timeout/error | Task 11 event matrix |
| Candidate is not success | candidate report/event test |
| Success follows fresh verification | success ordering and report invariant |
| Failure/budget terminal reason | parameterized terminal matrix |
| Interrupt best-effort terminal | interruption and logger-failure tests |
| SystemExit not swallowed | existing plus event integration test |
| Logger failure stops future operations | before/after boundary matrix |
| Stable logger error without exception text | injected OS/stream failures |
| API key/Bearer/common pattern redaction | sentinel privacy matrix |
| No environment/provider/continuation/reasoning payload | rejected-field and raw-file scan |
| Bounded output facts in logs | length/hash-only schema tests |
| Final report comes from state/metadata, not logs | file-read-forbidden report test |
| Report exit 0 only for Task 11 success | freshness/invariant matrix |
| Report changed paths preserve first-seen order | changed-path test |
| Report counters and token usage accurate | state/metadata aggregation test |
| Report evidence bounded and redacted | exact-cap excerpt tests |
| No logger preserves accepted behavior | compatibility matrix |
| Task 1–11 regression | full suite command |
| Task 13 deferred | file/import/diff audit |

## Plan self-check

- Every Task 12 acceptance criterion maps to a named test or explicit audit.
- The event set is minimal for approved facts: provider retry is represented by attempt events; safety rejection remains a tool result; model verification evidence is not double-counted.
- There is one sequence owner, one top-level state machine, and no duplicate logical/provider/tool/verification counter source.
- Every permitted text field has an exact type and bound; arbitrary payloads are rejected rather than recursively sanitized.
- Continuation, encrypted reasoning, provider bodies, message history, tool arguments/output, environment mappings, and exception bodies have no schema path into JSONL.
- Sequence is committed only after serialize/write/flush, eliminating the ordinary off-by-one case.
- Successful persistence yields exactly one terminal event; persistence failure never fabricates a replacement line.
- `COMPLETION_CANDIDATE` cannot produce report exit 0.
- The internal writer uses a constant protected path and real reparse checks; Task 8 remains unchanged and model tools remain denied.
- Model observation is provider-neutral; OpenAI SDK types stay in `openai_client.py`.
- Task 9 request mapping/retries, Task 10 budgets/context/continuation, and Task 11 freshness/success remain authoritative.
- No dependency, real network/key, branch, worktree, subagent, Git write, CLI wiring, demo, or Task 13 implementation is planned.
- Public types, enum values, event fields, report fields, commands, and expected RED causes are defined consistently with no unresolved placeholder.

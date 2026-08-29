# Milestone A: Run Instructions and Provider-Neutral Streaming Design

**Status:** Approved brainstorming decisions formalized for implementation planning

**Scope:** Task 16 (run instructions), Task 17 (provider-neutral streaming core), and Task 18 (Responses/Chat streaming adapters)

## 1. Goal

Milestone A prepares the existing local coding agent for a later session controller and Web GUI without replacing the verified synchronous architecture. It adds a stable run-level instruction snapshot, a provider-neutral streaming boundary, and streaming implementations for both existing model adapters.

The milestone must preserve every Task 1–15 safety, verification, context, logging, and provider behavior. The current one-shot CLI remains usable and synchronous by default. Streaming is opt-in through an in-memory callback and will be exposed through lifecycle/SSE components in later tasks.

## 2. Non-goals

This milestone does not implement:

- persistent sessions, checkpoints, resume, branching, or long-term memory;
- Skill discovery, installation, catalog management, or executable Skills;
- MCP, plugins, extensions, subagents, steering, or follow-up queues;
- FastAPI, SSE endpoints, static Web UI, TUI, or GUI state;
- asynchronous model clients, threads, multiprocessing, or concurrent tool calls;
- provider auto-detection or exception-text parsing;
- server-side conversation state, `previous_response_id`, or Responses storage;
- changes to Task 8 safety policy, Task 11 verification, or Task 12 JSONL payload privacy;
- persistence or logging of provider continuation, encrypted reasoning, instruction bodies, or streamed text.

## 3. Compatibility baseline

The following interfaces and behaviors remain valid:

```python
class ModelClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...

def invoke_model(
    client: ModelClient,
    request: ModelRequest,
    budget: ModelCallBudget,
    *,
    purpose: ModelCallPurpose = ModelCallPurpose.MAIN,
) -> ModelResponse: ...
```

- `ModelClient` is not extended with a required method.
- `OpenAIResponsesClient.complete(ModelRequest) -> ModelResponse` and `ChatCompletionsModelClient.complete(ModelRequest) -> ModelResponse` retain their exact public signatures.
- `complete()` never sends `stream=True`.
- Existing synchronous request dictionaries remain byte-for-byte equivalent at the Python-value level when `ModelRequest.instructions is None`.
- Existing message types continue to represent only complete messages and complete tool calls.
- `AgentState` receives no partial assistant message, partial tool call, or partial continuation.
- Responses continuation stays memory-only; Chat continuation remains empty.
- Task 9/10 shared logical-call and physical-attempt budgets remain authoritative.

## 4. Task 16: Run instruction snapshot

### 4.1 Provider-neutral request field

`ModelRequest` receives one additive final field:

```python
instructions: str | None = field(default=None, repr=False)
```

Rules:

- `None` means that no provider-level instructions are supplied.
- A non-null value must be a string containing at least one non-whitespace character.
- Whitespace inside a valid value is preserved.
- `instructions` appears in `ModelRequest.to_dict()` and JSON as an explicit string or `null`; `from_dict()` requires the field after the schema change.
- `repr(ModelRequest)` must not contain the instruction body.
- Instructions are not inserted into `messages`, so they cannot change message indexes, tool-result pairing, context turn partitioning, or continuation indexes.

### 4.2 Builder interfaces

Create `src/coding_agent/instructions.py` with these interfaces:

```python
MAX_AGENTS_FILE_BYTES = 65_536
MAX_SKILL_INSTRUCTIONS_BYTES = 65_536

class InstructionErrorCode(StrEnum):
    AGENTS_FILE_TOO_LARGE = "agents_file_too_large"
    AGENTS_FILE_NOT_UTF8 = "agents_file_not_utf8"
    AGENTS_FILE_UNREADABLE = "agents_file_unreadable"
    AGENTS_FILE_UNSAFE = "agents_file_unsafe"
    SKILL_INSTRUCTIONS_INVALID = "skill_instructions_invalid"
    SKILL_INSTRUCTIONS_TOO_LARGE = "skill_instructions_too_large"

class InstructionBuildError(RuntimeError):
    code: InstructionErrorCode

@dataclass(frozen=True, slots=True)
class RunInstructionSnapshot:
    text: str = field(repr=False)
    sha256: str
    char_count: int

class RunInstructionBuilder:
    def build(
        self,
        workspace: Path,
        *,
        skill_instructions: str | None = None,
    ) -> RunInstructionSnapshot: ...
```

`RunInstructionSnapshot` verifies that `text` is non-empty, `char_count == len(text)`, and `sha256` is the lowercase SHA-256 of the UTF-8 text. Its repr exposes only the hash and character count.

### 4.3 Sources and deterministic order

The builder composes exactly these sections in order:

1. `## MiniCodex base instructions`
2. `## Workspace instructions (AGENTS.md)` when a root file exists and is not blank
3. `## Selected skill instructions` when a non-null skill snapshot is supplied

Sections are separated by two LF characters. Source CRLF and lone CR are normalized to LF, and leading/trailing blank space around each optional source is removed. Content inside the source is otherwise preserved. The result is built once per Agent run and reused unchanged for every main model request in that run.

The fixed base section instructs the model to:

- operate only through the supplied local tools and inside the configured workspace;
- inspect before modifying and make focused changes;
- treat local deterministic safety and verification decisions as authoritative;
- never claim a test or command ran without returned local evidence;
- use tool calls rather than inventing file contents or execution results;
- regard a completion statement as a candidate, not proof of success.

### 4.4 Root `AGENTS.md` loading

- Only `<workspace>/AGENTS.md` is read. Nested instruction files are not discovered.
- `PathGuard` validates the workspace and the existing file. Symlinks, junctions, and reparse points are rejected using Task 8 behavior.
- A genuinely missing root file is normal and produces the base section only.
- A broken link, unsafe link, non-file entry, or other safety rejection becomes `InstructionBuildError(AGENTS_FILE_UNSAFE)`.
- The file is opened in binary mode and at most `65_537` bytes are read. A 65,536-byte file is allowed; the first byte beyond that limit produces `AGENTS_FILE_TOO_LARGE`.
- Bytes are decoded using strict `utf-8-sig`; a UTF-8 BOM is accepted and removed. Invalid bytes produce `AGENTS_FILE_NOT_UTF8`.
- Other `OSError` failures produce `AGENTS_FILE_UNREADABLE` without including the path or original exception text.
- A blank decoded file contributes no workspace section.

### 4.5 Selected Skill input boundary

Task 16 does not implement Skill management. It only accepts an already selected, in-memory declarative instruction string:

- `None` omits the section.
- Empty or whitespace-only strings and non-string values produce `SKILL_INSTRUCTIONS_INVALID`.
- UTF-8 encoded size may be at most 65,536 bytes; the first byte beyond the limit produces `SKILL_INSTRUCTIONS_TOO_LARGE`.
- The builder never imports, executes, or resolves code named by Skill text.

Task 21 will own catalog discovery, user selection, persistence, and snapshot storage.

### 4.6 Agent and provider integration

`AgentRunner.__init__` receives one additive keyword-only parameter:

```python
instructions: str | None = None
```

Every main `ModelRequest` carries that exact value. `ContextManager` summary calls continue to use their existing dedicated summary prompt with `instructions=None`; Skill or workspace behavioral text must not distort the summary JSON contract. Context compression changes messages and clears continuation, but never changes the run instruction value.

`run_application()` builds one snapshot after the audit logger is available and before `AgentRunner` construction. Production passes `snapshot.text` to `AgentRunner`. An instruction load failure stays inside the existing stable application error boundary and never prints the source text, local path, or raw exception.

Provider mappings are conditional:

- Responses adds top-level `instructions=<text>` only for a non-null value.
- Chat Completions prepends exactly one `{"role": "system", "content": <text>}` provider message only for a non-null value.
- The provider-only system message is never appended to local `messages`.
- When instructions are null, current provider request shapes remain unchanged.

No JSONL event contains the instruction body. This milestone adds no instruction content field to logging. Tests may assert the body is absent from repr, stable errors, and JSONL output. Future observability may record only the snapshot hash and character count.

## 5. Task 17: Provider-neutral streaming core

### 5.1 Module and public interfaces

Create `src/coding_agent/streaming.py`:

```python
class ModelStreamEventKind(StrEnum):
    TEXT_DELTA = "text_delta"
    RESPONSE_COMPLETED = "response_completed"
    RESPONSE_DISCARDED = "response_discarded"

@dataclass(frozen=True, slots=True)
class ModelStreamEvent:
    kind: ModelStreamEventKind
    delta: str | None = None

ModelStreamHandler: TypeAlias = Callable[[ModelStreamEvent], None]

@runtime_checkable
class StreamingModelClient(Protocol):
    def stream(
        self,
        request: ModelRequest,
        emit: ModelStreamHandler,
    ) -> ModelResponse: ...

@runtime_checkable
class BudgetAwareStreamingModelClient(Protocol):
    def stream_with_budget(
        self,
        request: ModelRequest,
        budget: ModelCallBudget,
        emit: ModelStreamHandler,
    ) -> ModelResponse: ...

class StreamingUnsupportedError(ModelError): ...
class StreamInterruptedError(ModelError): ...

def invoke_model_stream(
    client: ModelClient,
    request: ModelRequest,
    budget: ModelCallBudget,
    emit: ModelStreamHandler,
    *,
    purpose: ModelCallPurpose = ModelCallPurpose.MAIN,
) -> ModelResponse: ...
```

Event invariants:

- `TEXT_DELTA` requires a non-empty string `delta`.
- `RESPONSE_COMPLETED` and `RESPONSE_DISCARDED` require `delta is None`.
- Events contain no SDK object, tool argument fragment, continuation, hidden reasoning, response body, credential, or complete request.

### 5.2 Logical and physical budget semantics

`invoke_model_stream` represents exactly one logical model call.

- It begins and finishes the logical call using the same observation behavior as `invoke_model`.
- Every actual SDK stream request claims one provider attempt immediately before `responses.create` or `chat.completions.create`.
- A non-stream fallback is a second physical provider request under the same logical call and the same `ModelCallBudget`.
- Fallback must enter a private budget-aware complete helper; it must not call a public `complete()` method that creates a new budget or logical call.
- The first disallowed logical call or provider request is blocked before the operation, and counters never exceed limits.
- A provider attempt is marked completed only after the stream is fully consumed, the terminal response is parsed, and the final `ModelResponse` is valid.

`model.py` may extract a private `_complete_with_active_budget(client, request, budget)` helper from the current `invoke_model` implementation. `invoke_model` continues to expose the same signature and behavior.

### 5.3 Capability and fallback rules

Fallback to synchronous `complete_with_budget`/private active complete occurs only when:

1. the client does not implement `StreamingModelClient`; or
2. streaming raises local structured `StreamingUnsupportedError` before any provider delta or delivered text delta.

No fallback occurs for authentication, permission, invalid request, ordinary HTTP 400, malformed stream, parsing error, unknown event, timeout/connection/server error after a delta, or an exception inferred only from text. Provider adapters do not inspect exception messages to decide capability.

If `StreamingUnsupportedError` occurs after a text delta was delivered, it is converted to stable `StreamInterruptedError`, `RESPONSE_DISCARDED` is emitted, and no synchronous call is made.

When a client lacks streaming locally, fallback consumes only the normal non-stream provider attempt; there is no failed network stream attempt to count. When a streaming-capable client makes a real request and reports structured unsupported, that failed physical request is counted, and the fallback consumes the next provider attempt.

### 5.4 Completion and failure delivery

- Provider adapters emit `TEXT_DELTA` as soon as validated text fragments arrive.
- On a valid final response, `invoke_model_stream` emits one `RESPONSE_COMPLETED` and returns the complete existing `ModelResponse`.
- If an exception occurs after at least one text delta was successfully delivered, `invoke_model_stream` emits one `RESPONSE_DISCARDED` before propagating a stable error.
- No partial text, partial tool call, or partial continuation is returned in `ModelResponse`.
- `KeyboardInterrupt` and `SystemExit` are never caught by `except Exception` paths.
- If the consumer callback itself raises, no recursive callback is attempted and the consumer exception propagates.

`AgentRunner` receives an additive optional keyword-only `stream_handler: ModelStreamHandler | None = None`. A null handler preserves `invoke_model`. A non-null handler uses `invoke_model_stream` for main calls only. Summary calls remain synchronous and do not emit user-visible deltas. Existing CLI construction does not supply a handler, so CLI output remains the final JSON report.

## 6. Task 18: Responses streaming adapter

### 6.1 Request

`OpenAIResponsesClient` implements both streaming protocols without changing its constructor or complete methods.

- Public `stream(request, emit)` creates a standalone one-logical/three-attempt budget and delegates through `invoke_model_stream`.
- `stream_with_budget(request, budget, emit)` uses the shared run budget.
- It calls `client.responses.create` with the existing model/input/tools/output/include mapping plus `store=False` and `stream=True`.
- It never sends `conversation` or `previous_response_id`.
- Conditional instructions mapping is identical to the synchronous path.
- SDK automatic retries remain disabled by the existing `max_retries=0` client construction.

### 6.2 Event parsing

The parser uses Mapping/attribute duck typing; OpenAI SDK event classes do not cross the adapter.

- `response.output_text.delta` validates a non-empty string and emits it immediately.
- The accepted nonterminal Responses 3.5.0 event types are exactly: `response.created`, `response.in_progress`, `response.queued`, `response.output_item.added`, `response.output_item.done`, `response.content_part.added`, `response.content_part.done`, `response.output_text.delta`, `response.output_text.done`, `response.function_call_arguments.delta`, `response.function_call_arguments.done`, `response.reasoning_summary_part.added`, `response.reasoning_summary_part.done`, `response.reasoning_summary_text.delta`, `response.reasoning_summary_text.done`, `response.reasoning_text.delta`, and `response.reasoning_text.done`. Each accepted event still undergoes field validation appropriate to its type.
- Function argument delta events are grouped by `output_index` and stable `item_id`, concatenated in arrival order, and never exposed outside the adapter.
- When argument deltas were observed, the corresponding `response.function_call_arguments.done` event must carry the same `output_index`/`item_id`, a non-empty name, and the exact concatenated argument string. A matching completed function item must then appear in the terminal response. Conflicts, missing done events, duplicate done events, or mismatches are invalid.
- A provider that emits no function argument deltas may still supply a complete valid function item in the terminal response.
- Function calls are instantiated only from completed output items/terminal response, after the fragment checks above and full JSON object validation by the existing response parser.
- Reasoning and encrypted-reasoning events are never emitted, logged, or included in error text.
- `response.completed` must occur exactly once and contain a complete response accepted by the existing `_parse_response` contract.
- `response.failed`, `response.incomplete`, `error`, refusal/audio/image/file-search/web-search/code-interpreter/shell/MCP/custom-tool events, any other unknown event, a duplicate terminal event, an absent terminal event, missing fields, or malformed fields produce a stable `InvalidOpenAIResponseError`.
- If text deltas were emitted and final text exists, their concatenation must equal final parsed text. A mismatch is invalid and causes the provisional content to be discarded.
- A final response with text but no text deltas is allowed; it completes without incremental text events.
- Usage, provider response ID, ordered tool calls, and SDK-free cumulative continuation are built only from the validated terminal response.

### 6.3 Retry behavior

- A transient 429, 5xx, timeout, or connection error before any provider delta may retry twice with existing delays 0.25 and 0.50 seconds.
- The first provider delta permanently disables retry for that logical call, including function-argument deltas that are not sent to the UI.
- A transient failure after a delta becomes `StreamInterruptedError` without sleep or another request.
- Fatal errors and invalid stream structures never retry.
- Stream resources are closed in `finally` when they expose a callable `close`; cleanup failure must not replace an already active provider/parse exception or a `BaseException`. A close failure after an otherwise successful stream raises `StreamInterruptedError("model stream cleanup failed")` and is never retried.

## 7. Task 18: Chat Completions streaming adapter

### 7.1 Request

`ChatCompletionsModelClient` implements the same streaming protocols and preserves its existing synchronous behavior.

- The streaming request uses existing model/full-history/tool/max-token mapping and adds `stream=True`.
- This milestone does not require `stream_options`; usage remains optional unless the endpoint sends it.
- It does not send `store`, `conversation`, `previous_response_id`, or server state.
- Instructions, when present, are one leading provider-only system message.
- continuation remains empty and non-empty continuation is rejected before any SDK call.

### 7.2 Chunk aggregation

- Every chunk must expose zero or one choice. A choice must use index 0.
- Empty-choice chunks are allowed only to carry optional final usage.
- Delta role is `assistant` or null. Legacy `function_call`, refusals, non-function tool calls, multiple choices, and nonzero choice indexes are rejected.
- Non-empty content fragments emit `TEXT_DELTA` immediately and are concatenated in arrival order.
- Tool-call fragments are grouped by their integer `index`; indexes must become the contiguous ordered sequence `0..n-1`.
- Each tool call must finish with one stable non-empty ID, type `function`, one stable non-empty function name, and concatenated arguments that parse to a JSON object.
- Repeated identical ID/name fragments are accepted; conflicting values, missing values, duplicate completed IDs, sparse indexes, malformed JSON, and non-object arguments are rejected.
- Exactly one final finish reason must be observed and it must be `stop` or `tool_calls`. Tool calls remain valid with `finish_reason="stop"`.
- The terminal aggregate is converted to the current complete Chat response shape and passed through the existing `_parse_response` validation.
- Optional usage must contain complete non-negative prompt/completion/total counts. Response ID must be stable across non-empty chunks when supplied.

Retry, fallback, post-delta interruption, close, BaseException, privacy, and provider-attempt rules are the same as Responses.

## 8. Test strategy

All tests remain offline and inject fake SDK clients, stream iterators, events, exceptions, clocks, and sleepers. They do not read model credentials or call a network endpoint.

Task 16 tests cover:

- explicit null/string instruction JSON roundtrip and hidden repr;
- deterministic base/workspace/Skill order and snapshot hash;
- missing, blank, exact-limit, over-limit, BOM, invalid UTF-8, unreadable, file-type, symlink, junction, and reparse cases;
- root-only loading and no nested discovery;
- main requests preserve instructions before and after context compression;
- summary requests keep `instructions=None`;
- Responses and Chat conditional mapping;
- application composition reads the snapshot once;
- logs and stable errors do not contain instruction text.

Task 17 tests cover:

- protocol compatibility without changing `ModelClient`;
- event invariants;
- stream success/completion, local non-stream fallback, structured unsupported fallback, and no fallback after a delta;
- one logical call across fallback and exact provider attempt counts;
- provider limit off-by-one behavior;
- completed/discarded event order;
- callback failure and BaseException propagation;
- partial output never entering Agent state/history;
- CLI/no-handler synchronous regression.

Task 18 tests cover both adapters for:

- request mapping, instructions, strict tools, `store=False`, full local history, and no server state;
- text, single tool, multiple ordered tools, mixed text/tools, usage, response ID, and continuation;
- split function arguments and interleaved tool indexes;
- all terminal/malformed/unknown cases;
- pre-delta retry attempts/delays and post-delta no-retry;
- structured unsupported fallback and ordinary 400 no-fallback;
- resource close and cleanup failure precedence;
- no SDK types, provider payload, encrypted reasoning, keys, or authorization data crossing the boundary;
- all Task 1–15 regression tests.

## 9. Documentation and task status

Execution adds Tasks 16–18 to `TASKS.md`. The approved milestone may execute them sequentially without a user checkpoint between every RED/GREEN cycle, but only one task may be `进行中` at a time:

1. Task 16 becomes `进行中` after baseline verification.
2. After Task 16 acceptance tests pass, it becomes `已完成` and Task 17 becomes `进行中`.
3. After Task 17 acceptance tests pass, it becomes `已完成` and Task 18 becomes `进行中`.
4. Task 18 remains `进行中` at the final milestone review checkpoint. It becomes `已完成` only after user review and explicit authorization.

`DESIGN.md` and public API documentation are updated only after behavior is green. They must distinguish adapter streaming support from the still-unimplemented session controller/SSE/GUI. Task 15 historical spec and plan are not rewritten.

## 10. Stop conditions

Execution stops for user direction if:

- a locked Task 1–15 public interface must be removed or changed incompatibly;
- a new dependency is required;
- instructions cannot be loaded through Task 8 path safety without weakening it;
- a provider needs exception-text inspection or endpoint-specific hardcoding;
- fallback cannot preserve one logical-call/shared-attempt accounting;
- a partial tool call or continuation would need to enter Agent state;
- streaming requires real network access to test;
- implementation would need session, Skill catalog, lifecycle controller, SSE, GUI, Task 19+, or another deferred subsystem.

## 11. Final acceptance

Milestone A is ready for user review only when:

- every Task 16–18 focused test passes;
- the complete offline repository suite passes;
- synchronous exact-request regressions pass for both providers;
- instruction and stream privacy scans pass;
- provider attempts and fallback off-by-one tests pass;
- no dependency or framework is added;
- no real credential or network is used;
- `git diff --check` passes;
- the diff is limited to the approved file map;
- Task 18 remains `进行中` and no Git commit/push occurs without explicit authorization.

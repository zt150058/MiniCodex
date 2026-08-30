# Local Web GUI Milestone Design

**Date:** 2026-08-30

**Status:** Approved in conversation

**Scope:** Task 22 (local FastAPI/REST/SSE transport) and Task 23 (static local GUI)

## 1. Goal and roadmap alignment

This milestone exposes the existing provider-neutral session controller through
an authenticated loopback HTTP boundary and then adds a light, local,
Codex-inspired browser interface. It does not move Agent behavior into the Web
layer. The browser remains a projection and command surface over the accepted
Task 19-21 session, controller, event, and Skill contracts.

The earlier roadmap named follow-up as Task 22, FastAPI/SSE as Task 23, and the
static GUI as Task 24. During the accepted Task 19-20 design, sequential
follow-up was implemented in `SessionStore` and `SessionController`. The current
numbering is therefore:

- Task 22: local FastAPI, REST, Bearer authentication, and SSE adapter;
- Task 23: same-origin static GUI;
- later separately approved work: MCP and executable extensions.

Task 22 and Task 23 share one design and one implementation plan. They retain
separate code boundaries and review checkpoints.

## 2. Locked scope

### 2.1 Task 22 delivers

- a separate `coding-agent-web` console entry point;
- an application factory that receives one existing `SessionController`;
- an IPv4 listener fixed to `127.0.0.1`;
- a default system-assigned port (`0`) and an optional explicit port;
- per-process random Bearer authentication;
- strict Host and Origin checks;
- strict JSON request DTOs and stable safe error responses;
- REST access to sessions, follow-up, cancellation, and declarative Skills;
- SSE adaptation of `SessionController.read_updates()` and
  `wait_for_updates()`;
- finite startup and disconnect cleanup plus cooperative controller shutdown;
- fully offline tests using injected controllers and ASGI clients.

### 2.2 Task 23 delivers

- packaged same-origin HTML, CSS, and JavaScript with no build step;
- a left session sidebar, large central conversation area, fixed run header,
  elapsed time, and bottom composer;
- new-session and sequential follow-up flows;
- declarative Skill discovery and selection;
- provisional text, confirmed text, safe tool activity, verification activity,
  cancellation, and final run state rendering;
- authenticated fetch-based SSE with deterministic reconnect and snapshot
  reset;
- a warm ivory visual system suitable for a 16:9 demonstration;
- responsive behavior for narrow windows;
- a manual visual checkpoint in addition to automated contracts.

### 2.3 Explicit exclusions

This milestone does not add:

- WebSocket, remote binding, TLS termination, accounts, login, multi-user
  authorization, or remote deployment;
- more than one active run, a run queue, or parallel Agent execution;
- a second session database, event store, state machine, or cancellation path;
- changes to model messages, provider continuation, tool policy, path policy,
  verification success, or termination rules;
- executable Skills, MCP, plugin installation, remote Skill discovery, or a
  marketplace;
- React, Vue, npm, a frontend bundler, a production Node.js runtime, a terminal
  emulator, or a rich text editor;
- provider payload, hidden reasoning, API key, full command output, or
  continuation exposure;
- automatic Git operations or real external API calls in tests.

## 3. Architecture

```text
coding-agent-web
      |
      +-- web CLI and production composition
      |      +-- existing RunConfig
      |      +-- AgentSessionRunExecutor
      |      +-- SessionController.open()
      |      +-- exclusive loopback socket
      |      `-- single-worker Uvicorn server
      |
      `-- FastAPI application
             +-- WebAccessPolicy
             +-- strict request DTOs
             +-- stable domain-error mapping
             +-- REST serialization
             +-- bounded SSE adapter
             `-- packaged GUI resources (Task 23)
                         |
                         v
                 SessionController
                    SessionEventHub
                    SQLiteSessionStore
```

FastAPI, Pydantic, Starlette, and Uvicorn types terminate inside the Web
modules. No Web or SDK type enters `AgentRunner`, the message model, session
domain records, `SessionController`, tools, safety, verification, or provider
adapters.

The adapter is deliberately thin and synchronous. FastAPI executes ordinary
sync route functions and the sync SSE iterator in its worker-thread boundary.
The adapter calls the already thread-safe controller methods directly. It does
not introduce an `asyncio` cancellation model alongside the existing
controller worker and cancellation token.

## 4. Dependencies

The accepted new direct runtime dependencies are:

- `fastapi`;
- `uvicorn`.

The accepted new direct test dependency is:

- `httpx`.

The target Windows development environment also uses its existing Node.js 20
built-in `node:test` runner to execute browser-independent GUI logic. Node is a
test tool only: the project adds no npm package, `package.json`, build step,
downloaded browser, or installed/runtime dependency on Node.

SSE uses Starlette's existing `StreamingResponse`; no SSE package is added.
The GUI uses only packaged HTML, CSS, JavaScript, and inline SVG.

## 5. File and interface map

### 5.1 New Python modules

`src/coding_agent/web_auth.py` owns deterministic request authorization:

```python
class WebAuthorizationError(RuntimeError):
    code: str

@dataclass(frozen=True, slots=True)
class WebAccessPolicy:
    token: str = field(repr=False)
    port: int

    @classmethod
    def generate(
        cls,
        port: int,
        *,
        token_factory: Callable[[], str] = default_token_factory,
    ) -> WebAccessPolicy: ...

    def authorize(
        self,
        raw_headers: tuple[tuple[bytes, bytes], ...],
        *,
        require_bearer: bool,
    ) -> None: ...
```

`src/coding_agent/web.py` owns the HTTP adapter and static-resource boundary:

```python
def create_web_app(
    *,
    controller: SessionController,
    access_policy: WebAccessPolicy,
    gui_root: Traversable | None = None,
) -> FastAPI: ...
```

`src/coding_agent/web_cli.py` owns the separate parser and production server
lifecycle:

```python
class WebApplication(Protocol):
    def __call__(
        self,
        config: RunConfig,
        *,
        port: int,
        open_browser: bool,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int: ...

def build_web_parser() -> argparse.ArgumentParser: ...

def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    application: WebApplication | None = None,
) -> int: ...

def run_web_application(
    config: RunConfig,
    *,
    port: int,
    open_browser: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> int: ...

def entrypoint() -> NoReturn: ...
```

### 5.2 New GUI resources

- `src/coding_agent/web_static/index.html` contains semantic structure and one
  server-replaced in-memory access-token bootstrap node;
- `src/coding_agent/web_static/app.js` contains the state projection, API
  client, fetch-based SSE parser, reconnect loop, and DOM rendering;
- `src/coding_agent/web_static/styles.css` contains the responsive warm ivory
  visual system.

`tests/js/web_gui.test.mjs` and `tests/js/dom_harness.mjs` execute the real
`app.js` module through Node's built-in runner. They cover pure state, API,
SSE, reconnect, and safe DOM projection behavior without a third-party DOM
package.

### 5.3 Existing files changed

- `pyproject.toml` adds the accepted direct dependencies, package data, and the
  `coding-agent-web` entry point;
- `tests/test_cli.py` updates its pyproject metadata contract through a RED then
  GREEN cycle for the approved dependencies and second entry point;
- `TASKS.md` adds Tasks 22 and 23 and changes status only at the execution
  checkpoints;
- `DESIGN.md` first records the approved in-progress milestone before production
  edits, then records delivered behavior after GREEN;
- `README.txt`, `README.md`, `docs/USAGE.md`, and `docs/OPENAI_API.md` are
  updated only after behavior is green.

The implementation must stop if it needs to change an accepted public
`SessionController`, `SessionEventHub`, session record, Skill, model, tool,
safety, verification, provider, or CLI interface.

## 6. Web CLI and production lifecycle

`coding-agent-web` accepts:

```text
--workspace PATH
--verify COMMAND
--model MODEL
--api-mode {responses,chat-completions}
--base-url URL
--port PORT
--no-open-browser
```

`--workspace` is required. `--port` defaults to `0` and accepts only an integer
from 1 through 65535 when explicitly provided. The existing provider,
credential, model, base-URL, and verification rules are reused through
`load_run_config()` with a private non-empty base-task value. Each actual
session run continues to replace that value with the submitted message through
`AgentSessionRunExecutor`.

Production startup is ordered:

1. validate CLI and run configuration before opening a socket or controller;
2. create an IPv4 TCP socket and bind only `127.0.0.1`;
3. request port `0` unless the user explicitly selected a port;
4. enable exclusive-address behavior on Windows where supported and never set
   address reuse;
5. read the actual assigned port;
6. generate one access token and construct `WebAccessPolicy`;
7. create one `AgentSessionRunExecutor` and one `SessionController`;
8. create the FastAPI app and one-worker Uvicorn server;
9. report only the local address;
10. after Task 23 resources exist, open the browser unless
    `--no-open-browser` was supplied;
11. on exit, call `controller.shutdown(timeout_seconds=5.0)`;
12. if it returns false, emit one fixed `shutdown_pending` warning and continue
    five-second cooperative waits until the existing non-daemon worker reaches
    a terminal boundary and `shutdown()` returns true;
13. close the socket in reverse acquisition order after the controller releases
    its workspace lease.

Task 22's API checkpoint does not open a missing GUI. Task 23 activates default
browser opening after packaged GUI resources are present.

Uvicorn is configured with access logging, server headers, proxy-header trust,
reload, and multiple workers disabled. A browser-open failure is nonfatal and
produces only a fixed warning. Configuration, bind, controller, and server
failures return stable nonzero exit codes without raw exceptions or paths.
Shutdown does not claim a finite hard-stop guarantee: Task 20 intentionally
uses cooperative cancellation and a non-daemon worker, so an already-admitted
blocking operation may delay process exit. The Web layer does not weaken that
invariant, release the workspace lease early, or force-kill the worker.
`KeyboardInterrupt` starts the graceful local shutdown path; `SystemExit` is
not swallowed by a broad exception handler.

## 7. Authentication and browser security

`WebAccessPolicy.generate()` uses `secrets.token_urlsafe(32)`. The token is
kept only in process memory, hidden from repr, and compared with
`secrets.compare_digest()`.

Every `/api/v1` REST and SSE request must pass all of:

1. exactly one syntactically valid Host header whose host is `127.0.0.1` or
   `localhost` and whose port is the actual bound port;
2. if Origin exists, exactly one Origin equal to the request's approved local
   origin;
3. exactly one `Authorization: Bearer <token>` header.

Raw ASGI headers are inspected so duplicate Host, Origin, or Authorization
values cannot be hidden by a convenience mapping. Missing or invalid Bearer
credentials always produce `401` with `unauthorized`. Invalid Host or Origin
always produces `403` with `request_forbidden`. Authentication comparison does
not report which part mismatched.

CORS is not enabled. Wildcard origins and credentialed cross-origin requests
are not supported. API preflight does not grant access.

Task 23's top-level HTML request requires the same Host and Origin checks but
does not require Bearer because the document bootstraps it. The server replaces
one exact placeholder with an HTML-escaped token in an uncached document. The
application reads the value into a module-local variable and immediately
removes the bootstrap node. It never writes the token to a URL, Cookie,
`localStorage`, `sessionStorage`, IndexedDB, SQLite, JSONL, console, error, or
SSE event.

The document uses a strict Content Security Policy with same-origin scripts,
styles, images, and connections, plus `frame-ancestors 'none'`,
`object-src 'none'`, `base-uri 'none'`, and `form-action 'none'`. It also sends
`Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and
`X-Content-Type-Options: nosniff`.

The token protects the local HTTP surface from cross-site browser commands. It
does not claim to isolate one hostile local operating-system user from another
user with equal access to the process and loopback interface.

## 8. REST contract

All API routes use the `/api/v1` prefix:

| Method | Path | Controller behavior |
| --- | --- | --- |
| GET | `/api/v1/health` | authenticated fixed health/schema response |
| GET | `/api/v1/sessions?limit=50` | `list_sessions(limit=...)` |
| POST | `/api/v1/sessions` | `create_session(message, skill_ids=...)` |
| GET | `/api/v1/sessions/{session_id}` | `get_session()` plus selected Skill IDs |
| POST | `/api/v1/sessions/{session_id}/messages` | `submit_message()` |
| GET | `/api/v1/skills` | `list_skills()` |
| GET | `/api/v1/sessions/{session_id}/skills` | `get_session_skills()` |
| PUT | `/api/v1/sessions/{session_id}/skills` | `set_session_skills()` |
| POST | `/api/v1/runs/{run_id}/cancel` | `cancel()` |
| GET | `/api/v1/runs/{run_id}/events` | authenticated SSE adapter |

Mutation DTOs are strict Pydantic models with coercion disabled and extra
fields forbidden:

```json
{"message":"repair the failing test","skill_ids":["python-testing"]}
```

```json
{"message":"continue with the next failure"}
```

```json
{"skill_ids":["python-testing","code-review"]}
```

The Web layer validates JSON shape and delegates message, ID, Skill selection,
session state, and controller availability invariants to their existing owners.
It does not duplicate or weaken them.

Session projections expose only:

- the existing session ID, title, status, timestamps, last run ID, and sequence;
- run ID, ordinal, status, timestamps, agent status, termination reason, audit
  run ID, and the already-safe persisted final report;
- existing persisted safe session event fields and data;
- selected Skill IDs;
- Skill descriptor metadata and stable catalog diagnostics.

They never expose Skill instruction text, full `FinalReport`, raw command
output, model messages, provider objects, continuation, hidden reasoning,
credentials, environment, or local absolute paths.

Every mutation body is limited to 131,072 raw bytes. An ASGI receive wrapper
counts chunks, so missing or deceptive Content-Length does not bypass the
limit. Oversized requests produce `413 request_too_large` before a controller
call. Mutation routes require JSON media type and return `415` otherwise.

Errors have exactly this public shape:

```json
{"error":{"code":"controller_busy"}}
```

Stable status groups are:

- `400`: invalid JSON, DTO, message, ID, cursor, or local request invariant;
- `401`: unauthorized;
- `403`: forbidden Host or Origin;
- `404`: missing session or run;
- `409`: busy controller, session-state conflict, or Skill-selection conflict;
- `413`: request body too large;
- `415`: unsupported request media type;
- `429`: SSE connection limit;
- `503`: closed/degraded controller or unavailable storage;
- `500`: fixed `internal_server_error` for other ordinary exceptions.

No mapping catches `BaseException`.

## 9. SSE contract

The browser uses authenticated `fetch()` rather than native `EventSource`, so
the Bearer header never enters a URL. It requests:

```http
GET /api/v1/runs/{run_id}/events
Authorization: Bearer <memory-only-token>
Accept: text/event-stream
Last-Event-ID: 12
```

`Last-Event-ID` is the only cursor source. Missing means zero. Duplicate,
negative, non-decimal, or ahead-of-latest values produce `400` before the
stream starts.

Each existing `SessionUpdate` is encoded as:

```text
id: 13
event: assistant_text_delta
data: {"schema_version":1,...}

```

The `data` line is exactly `SessionUpdate.to_json()`. The adapter does not
interpret, augment, resequence, or persist it. It emits a comment heartbeat
after 15 seconds without an event; comments do not consume sequence numbers.

When the current batch reports `reset_required`, the adapter emits:

```text
event: reset_required
data: {"last_sequence":42,"run_id":"..."}

```

and closes without pretending the retained suffix is complete. The GUI reloads
the durable session snapshot and reconnects only if that run is still active.
After sending `run_finished`, the adapter closes normally.

An SSE disconnect closes the iterator and releases its connection permit. It
does not call `cancel()`. At most four SSE streams may be active process-wide
and at most two for one run. Excess connections receive
`429 stream_limit_reached`.

SSE responses send `text/event-stream; charset=utf-8`, `Cache-Control:
no-store`, `X-Accel-Buffering: no`, and `X-Content-Type-Options: nosniff`.
An ordinary failure before headers produces the normal JSON error. Once a
stream has begun, an ordinary controller failure is represented by one fixed
safe terminal transport event and the stream closes. No traceback or raw
exception enters a stream.

## 10. GUI behavior

The desktop layout has a roughly 260-pixel session sidebar and a flexible
central column. It has no permanent right rail. The central header contains the
session title, run status, current phase, elapsed time, and Cancel action. The
conversation fills the remaining area, and the composer remains at the bottom.

The visual palette uses warm ivory surfaces, deep brown-gray text, a muted
terracotta accent, soft green success, warm gold running state, and dark
red-brown failure. It never uses a black application background. System fonts,
small-radius cards, restrained shadows, and inline SVG avoid remote assets.

The client maintains one selected session and at most one SSE connection. It
projects existing server facts:

- user messages and confirmed assistant text come from durable events;
- provisional model deltas remain in memory and show a subtle live cursor;
- confirmed text replaces the provisional buffer;
- discarded provisional text is removed;
- safe tool and verification events render as collapsible activity cards;
- success appears only when the server reports the accepted successful result;
- elapsed time is a display calculation based on server run timestamps;
- closing or hiding the page never cancels a run.

When another session owns the active run, history remains browsable but send
and Skill-mutation controls are disabled. New sessions may select Skills before
creation. Idle existing sessions may update selection for their next run.
Running and cancelling sessions show the immutable current selection and make
the selector read-only. The UI displays descriptor name, description, and
source but never Skill instructions.

SSE reconnect delays are 0.5, 1, 2, then 5 seconds, capped at 5 seconds. A
reconnect includes the last accepted sequence. A reset reloads the session
snapshot. Authentication and origin failures do not retry. A terminal run does
not reconnect. Page visibility changes never create a second connection.

All model-originated text is inserted with `textContent`. A small deterministic
renderer may split fenced code blocks into text and `pre/code` DOM nodes, but
it does not use `innerHTML` for model content or implement general Markdown.

At Task 23, `coding-agent-web` opens the local page after the socket is
listening unless `--no-open-browser` was provided. Failure to open a browser is
nonfatal and produces a fixed safe warning.

## 11. Determinism, safety, and failure handling

- Only one controller, session lease, worker owner, and Web server exist per
  process.
- The controller remains the sole owner of one-active-run admission.
- The Web layer has no implicit retry for mutations.
- Repeated POST requests are not treated as idempotent unless the controller
  already defines an idempotent result, such as cancellation.
- HTTP disconnect is not Agent cancellation.
- All serialization uses explicit allowlists and finite JSON values.
- Access token and API keys are included in sensitive-value scrubbing where a
  production component accepts that list, even though neither value should
  reach session events.
- Static assets and HTML have bounded packaged sizes and no remote references.
- The browser never reads JSONL logs or workspace files directly.
- Task 8 path and command policy, Task 10 budgets, Task 11 verification, Task
  12 audit rules, and Task 20 cancellation remain authoritative.
- No test calls a real provider or reads a real credential.

## 12. Test strategy and checkpoints

### 12.1 Task 22 automated acceptance

Tests cover:

1. token generation, hidden repr, constant-time comparison behavior, duplicate
   headers, exact Host, exact port, Origin, and stable auth errors;
2. strict DTOs, unsupported media type, declared and streamed body limits, and
   zero controller calls after rejection;
3. health, session list/create/detail/follow-up, Skill list/get/set, cancellation,
   and stable controller error mapping;
4. exact provider-neutral response projections and absence of private fields;
5. SSE replay, ordering, encoding, heartbeat, terminal close, disconnect,
   current-run mismatch, cursor rejection, reset-required, and connection caps;
6. Web CLI parsing, existing provider configuration reuse, fixed loopback,
   port zero, explicit port, socket/server injection, stable startup failure,
   reverse cleanup, repeated cooperative shutdown waits, `KeyboardInterrupt`,
   and `SystemExit`;
7. installed entry point and imports without external network access.

After focused tests, the execution runs Task 19-21 regressions, the complete
offline suite, Windows workspace-lease/reparse/process-tree tests, dependency
checks, secret/path/provider-payload scans, suppression scans, diff checks, and
interface audits. Task 22 remains `进行中` at the API/authentication checkpoint.

### 12.2 Task 23 automated and visual acceptance

Automated tests cover:

1. installed static-resource discovery and exact content types;
2. token replacement count, HTML escaping, no-store response, CSP, referrer,
   framing, and nosniff headers;
3. semantic layout landmarks, labels, input controls, and accessibility
   attributes;
4. no remote URLs, inline event handlers, unsafe model-content HTML sink,
   persistent browser token storage, WebSocket, native EventSource, or frontend
   framework artifacts;
5. client Bearer attachment, one active stream, ordered cursor, reconnect
   schedule, reset reload, terminal close, state transitions, and no
   disconnect-cancel coupling through executable Node tests against the real
   module;
6. package/wheel inclusion and `coding-agent-web` installed entry behavior.

The finite REST server workflows remain covered through Task 22 ASGI
integration tests. Infinite SSE disconnect and concurrency behavior uses a
real loopback Uvicorn server because HTTPX's in-memory ASGI transport buffers a
stream until completion. Browser-independent GUI behavior runs through Node's
built-in test runner. Because the project adds no browser automation runtime,
visual quality remains an explicit human checkpoint rather than a claimed
pytest result. The offline fixture is inspected at 1280x720, 1440x900, and a
narrow viewport across idle, running, cancelling, succeeded, failed, long-text,
code-block, tool, verification, and Skill-diagnostic states.

Final acceptance reruns the full repository suite, all Windows safety tests,
`pip check`, an offline clean install and entry-point check, package-data
inspection, credential and personal-path scans, dependency and Agent-framework
audits, whitespace checks, status inspection, and a complete diff review. Task
23 remains `进行中` for user review; no automatic commit or push occurs.

## 13. Task status transitions

At execution baseline, after confirming the accepted Task 21 commit and a clean
workspace:

- Task 21 changes from `进行中` to `已完成`;
- Task 22 is added as `进行中`;
- Task 23 is added as `未开始`.

After Task 22 focused and regression acceptance and explicit user approval:

- Task 22 changes to `已完成`;
- Task 23 changes to `进行中`.

At the final GUI and repository checkpoint, Task 23 remains `进行中` until the
user performs final review and authorizes completion. Exactly one task is
`进行中` at every implementation checkpoint.

## 14. Decisions and limitations

The accepted thin synchronous adapter minimizes concurrency models and keeps
all Agent semantics in the controller. FastAPI/Uvicorn are accepted because the
previous milestone roadmap already selected them for the local Web boundary.
Bearer-over-fetch avoids putting credentials in an SSE URL. A pre-bound random
port avoids demo failures caused by a fixed occupied port. A no-build vanilla
GUI keeps installation small and explainable.

The first GUI is intentionally not a general IDE. It does not edit files
directly, expose a terminal, render arbitrary HTML, resume interrupted Agent
execution, run sessions concurrently, or install executable extensions. Its
automated tests prove structural, transport, packaging, and security contracts;
the final appearance remains a recorded human visual acceptance item.

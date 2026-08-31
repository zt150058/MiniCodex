# Chat Completions Dynamic Model Selection Design

**Date:** 2026-08-31

**Status:** Approved

**Scope:** Web GUI model discovery and per-run model selection for the
OpenAI-compatible Chat Completions mode

## 1. Objective

The local Web GUI will discover every valid model ID exposed by the configured
Chat Completions provider and let the user choose the model used by the next
run. Model discovery remains a local control-plane capability: the browser
never receives the provider credential or base URL, the model never controls
selection, and a selection cannot change a run that has already been admitted.

Responses mode keeps its existing startup-configured model behavior. The
one-shot CLI also remains unchanged.

## 2. Locked product decisions

- Dynamic discovery and selection apply only when `api_mode` is
  `chat-completions`.
- Discovery uses the configured compatible provider's Models endpoint through
  the existing official OpenAI Python client.
- The GUI presents every valid model ID returned by the provider. It does not
  guess model capabilities or filter IDs by naming convention.
- The startup-configured model is always present as a fallback choice, even if
  the provider omits it from the latest Models response.
- The compact model selector sits in the composer action row beside the
  existing run-mode and budget controls. It does not add a new page header or
  consume conversation-log height on desktop layouts.
- The selector is disabled while a run or another controller mutation is
  active. A changed selection applies only to the next newly admitted run.
- Each run snapshots and persists its exact selected model ID.
- GUI startup performs a lazy initial discovery. A compact refresh action lets
  the user explicitly request a new catalog snapshot.
- Discovery failure never prevents the Web server from starting and never
  removes the configured fallback model.
- No production dependency is added.

## 3. Approaches considered

### 3.1 Recommended: authenticated local catalog with a last-good cache

The Python server owns discovery, validation, caching, and selection
authorization. The GUI reads a safe local projection and submits one exact
model ID with each new run. This keeps credentials out of the browser, gives
offline/failure fallback behavior, and makes the run record auditable.

### 3.2 Browser calls the provider directly

This would require exposing the provider base URL and credential to browser
JavaScript and would make cross-origin behavior provider-dependent. It violates
the existing credential boundary and is rejected.

### 3.3 Fetch from the provider on every message

This keeps the credential server-side but adds network latency and a new
failure point to every run admission. It also allows a remote catalog outage to
block a model that was already selected successfully. It is rejected in favor
of explicit refresh plus a last-good snapshot.

## 4. Architecture

```text
Chat Completions provider
        GET /models
             |
             v
ChatCompletionsModelCatalog
  - bounded SDK request
  - validate / deduplicate IDs
  - keep last-good snapshot
             |
             +---- GET /api/v1/models ----> static GUI selector
             |
             `---- SessionController admission validation
                         |
                         v
                 SessionRunRequest(model_id)
                         |
                         v
              AgentSessionRunExecutor
                  replace(base_config,
                          model=request.model_id)
                         |
                         v
              per-run model client instance
```

A new focused `model_catalog.py` module owns provider discovery and the
last-good snapshot. `SessionController` remains the admission boundary: it
accepts only the configured default or an ID in the catalog's last successful
snapshot, then copies the resolved ID into the immutable run request.

`AgentSessionRunExecutor` continues constructing a new model client per run.
It changes only by copying the immutable request model into `RunConfig` along
with the current task, run mode, and budget profile. There is no shared mutable
model client and no mid-stream reconfiguration.

## 5. Model catalog boundary

### 5.1 Public types

`src/coding_agent/model_catalog.py` defines provider-neutral local types with a
Chat Completions production implementation:

```python
class ModelCatalogStatus(StrEnum):
    READY = "ready"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class ModelCatalogView:
    enabled: bool
    status: ModelCatalogStatus
    default_model_id: str
    model_ids: tuple[str, ...]
    error_code: str | None


class ModelCatalog(Protocol):
    @property
    def default_model_id(self) -> str: ...
    def list_models(self, *, refresh: bool = False) -> ModelCatalogView: ...
    def resolve(self, requested_model_id: str | None) -> str: ...
```

The production factory creates a remote-backed catalog only for Chat
Completions. Responses mode receives a disabled catalog whose sole resolved
choice is the configured startup model and which performs no Models request.
Tests inject deterministic fake catalogs or fake SDK clients; default tests do
not use the network.

### 5.2 Discovery and normalization

The production catalog constructs a separate synchronous OpenAI client using
the already validated Chat Completions API key and base URL, `max_retries=0`,
and a finite request timeout. Calling the SDK Models list operation therefore
targets the compatible base URL's `/models` resource without assembling an
unvalidated URL manually.

The catalog iterates the complete provider response and accepts an ID only
when it is an exact non-empty string with no surrounding whitespace, control
characters, or invalid UTF-8 representation and no more than 256 UTF-8 bytes.
It deduplicates exact IDs and returns them in deterministic case-insensitive
order with an exact-string tie break. The configured default is inserted if it
was absent.

Discovery is bounded to 2,048 unique valid IDs. If the provider exceeds that
limit, returns an unusable payload, times out, rejects authentication, or does
not implement Models listing, the whole refresh fails rather than silently
presenting a partial catalog. Provider response bodies, exception text,
credentials, and the base URL are not returned to the GUI or written to run
JSONL.

### 5.3 Cache and refresh semantics

- The first ordinary `list_models()` call performs discovery when no successful
  snapshot exists.
- Later ordinary calls return the cached snapshot without another remote call.
- `refresh=True` explicitly attempts a new complete snapshot.
- A successful discovery atomically replaces the last-good snapshot and
  returns `ready`.
- A failed refresh with a last-good snapshot preserves those IDs and returns
  `stale` with `model_catalog_unavailable`.
- A failed initial discovery returns `unavailable` with only the configured
  default model.
- Responses mode always returns `disabled` with only the configured default.

The catalog serializes concurrent refreshes with its own lock. The synchronous
FastAPI route runs outside the event loop, and the provider timeout bounds the
lock hold. Catalog refresh does not consume an Agent run's model-call budget.

## 6. HTTP contract

The authenticated local endpoint is:

```http
GET /api/v1/models?refresh=false
Authorization: Bearer <memory-only-token>
```

Its response contains only safe control-plane data:

```json
{
  "enabled": true,
  "status": "ready",
  "default_model_id": "configured-model",
  "model_ids": ["configured-model", "provider-model"],
  "error_code": null
}
```

`refresh` accepts only FastAPI's strict boolean query representation. The
endpoint uses the existing Host, Origin, Bearer, and no-store protections.

Create-session and follow-up JSON bodies add optional `model_id`. Omission or
JSON `null` resolves to the configured startup model for backward
compatibility. A supplied value must be an exact valid model ID and must be the
configured default or belong to the last-good provider snapshot. Invalid,
unknown, or no-longer-authorized selections are rejected before a session
event, run row, worker, or provider model call is created. The stable error is
`model_not_available` with HTTP 400.

Successful create and follow-up responses include the resolved `model_id` in
the returned run handle.

## 7. Run immutability and persistence

`model_id` is added to these run-level values:

- `RunHandle`;
- `SessionRunRequest`;
- `SessionRunRecord`;
- `SessionStore.create_session()` and `submit_message()`;
- REST run projections and create/follow-up responses.

The controller resolves the requested value before calling the store. The
store and worker receive the same resolved string, preventing the persisted
record and executing configuration from diverging. Run-start invariants check
that the active request still matches the persisted run mode, budget profile,
and model ID.

SQLite adds a nullable `model_id` column to `session_runs`. New rows always
write a validated non-null ID. Existing rows migrate to `NULL` because a later
process startup may use a different configured model and must not invent a
historical value. REST serializes those legacy records as `model_id: null`.
No existing final report or audit JSONL is rewritten during migration.

The selected model does not become part of the conversation narrative sent to
the model. It is execution metadata, not user content or model authority.

## 8. GUI behavior and layout

The composer action row gains a compact labeled native select and refresh
button inside the left control group:

```text
[允许修改 | 只读问答] [标准 | 深入] [模型: selected-model ▾] [↻]   Enter…   [发送]
```

On narrow layouts the left controls may wrap within the existing composer
card. The composer remains the final grid row, so the conversation log keeps
its `minmax(0, 1fr)` space and the empty state stays centered. No new global
status strip is introduced.

GUI startup requests `/api/v1/models`. In Chat Completions mode it fills the
select with every returned ID and selects the configured default. The full ID
is available as the option text and accessible label; the closed control may
use CSS ellipsis when the ID is long. The current selection remains while the
page is open. Reloading the page intentionally returns to the configured
default; browser local storage is not added.

The refresh button requests `refresh=true`. If the new result no longer
contains the current selection, the GUI returns to the configured default. A
`stale` result keeps the last-good options and shows a compact non-blocking
warning. An `unavailable` result leaves only the default and shows “无法获取模型
列表”. In Responses mode `enabled=false` hides both controls.

The select and refresh button use the same mutation lock as send, run mode,
budget profile, Skill import, and session deletion. The submit path snapshots
the selected model before its asynchronous request and sends that exact value.
Loading a historical session may display the model used by each run, but it
does not silently change the next-run selection.

## 9. Error handling and security

- Web startup is independent of remote model discovery.
- Discovery uses only the Chat Completions credential and never falls back to
  `OPENAI_API_KEY`.
- The browser never receives the credential or compatible provider base URL.
- Remote exception messages and bodies are collapsed to
  `model_catalog_unavailable`.
- Provider model IDs are untrusted input and are bounded before caching,
  serialization, persistence, display, or logging.
- The controller validates submitted IDs independently of GUI state.
- Refresh cannot mutate a running request, `RunConfig`, or model client.
- Selecting an API-listed model does not assert that it supports text,
  streaming, tools, or the Agent's required Chat Completions semantics. A
  capability-incompatible selection follows the existing stable provider/model
  failure path for that run.
- Discovery itself creates no workspace file and writes no run audit event.

## 10. Testing strategy

All automated tests remain offline.

### 10.1 Catalog unit tests

- fake SDK success, pagination, deterministic ordering, exact deduplication,
  and default insertion;
- invalid entries, ID-size limits, catalog-size limit, malformed payload,
  timeout, authentication/provider errors, and missing Models support;
- initial failure fallback, last-good stale fallback, successful refresh
  replacement, and concurrent serialization;
- disabled Responses catalog performs no provider call;
- repr and error projections do not expose credentials or base URL.

### 10.2 Session and storage tests

- model selection is immutable in `RunHandle`, `SessionRunRequest`, and the
  executor's replaced `RunConfig`;
- create and follow-up persist the exact resolved model independently;
- model mode/budget/model mismatches fail controller invariants;
- SQLite migration preserves legacy runs as `NULL` and writes non-null values
  for new runs;
- process-restart recovery and session deletion continue to work with the new
  column.

### 10.3 REST tests

- authenticated catalog success, refresh, stale, unavailable, and disabled
  projections;
- create/follow-up defaulting and exact selected-model propagation;
- invalid types, extra fields, unknown model IDs, and provider errors map to
  stable safe responses without admitting a run.

### 10.4 GUI tests

- control placement, accessible label, option rendering, long-ID truncation,
  and Responses-mode hiding;
- initial load, manual refresh, stale/unavailable warning, fallback selection,
  and current selection submission;
- mutation locking, Enter submission, session selection, empty-state vertical
  layout, and existing run-mode/budget controls remain unchanged;
- dynamic strings continue to use safe DOM text APIs rather than HTML sinks.

Relevant Python tests, Node GUI tests, `git diff --check`, and the existing
unsafe-HTML-sink scan run before completion. A real compatible-provider smoke
test remains opt-in and requires explicit user authorization.

## 11. Non-goals

- Responses API model discovery or switching;
- changing the one-shot CLI model during a run;
- model capability probing, benchmark metadata, pricing, aliases, favorites,
  search, or heuristic filtering;
- automatic periodic refresh;
- exposing API keys or provider URLs in GUI state;
- switching an active run's model or reusing a mutable client across runs;
- guaranteeing that every listed model supports the Agent's tool-calling and
  streaming requirements.

## 12. Acceptance criteria

The feature is accepted when:

1. Chat Completions GUI startup shows every valid ID from a successful bounded
   Models listing plus the configured fallback.
2. The compact selector and refresh action live in the composer action row and
   do not displace the desktop conversation region.
3. A selected model is validated, persisted, returned by REST, and used to
   construct exactly that new run's client.
4. Follow-up runs may choose a different model while earlier and active runs
   remain unchanged.
5. Discovery failure preserves the last-good catalog or startup fallback and
   does not prevent server startup or default-model runs.
6. Responses mode and the one-shot CLI retain current behavior.
7. Legacy SQLite rows remain readable without fabricated model IDs.
8. Credentials, base URL, provider bodies, and raw exception text never reach
   the GUI, run JSONL, tests, documentation examples, or logs.
9. Offline unit, storage, controller, REST, and GUI tests cover success and
   failure paths without weakening existing safety or execution invariants.

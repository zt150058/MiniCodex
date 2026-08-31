# Chat Completions Dynamic Model Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. `superpowers:subagent-driven-development` may be used only if the user explicitly authorizes subagents. Use `superpowers:test-driven-development` before every production change, `superpowers:systematic-debugging` after any unexpected failure, `superpowers:requesting-code-review` after the core module is complete, and `superpowers:verification-before-completion` before reporting completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover every valid model ID exposed by the configured Chat Completions provider and let the local Web GUI select an immutable, persisted model for each new run.

**Architecture:** A server-side `ModelCatalog` calls the compatible provider's Models API with bounded parsing and a last-good cache. The authenticated REST layer projects only safe IDs, `SessionController` validates and snapshots one ID during admission, SQLite persists it, and `AgentSessionRunExecutor` creates the run-specific model client from that immutable value. The static GUI adds a compact composer selector and refresh control without exposing credentials or changing Responses/one-shot CLI behavior.

**Tech Stack:** Python 3.11+, standard library, existing official `openai` Python SDK, FastAPI, SQLite, plain HTML/CSS/JavaScript, pytest, Node's built-in test runner, Windows PowerShell.

**Spec:** `docs/superpowers/specs/2026-08-31-chat-completions-dynamic-model-selection-design.md`

## Global Constraints

- Work only in `D:\code\coding_agent`; do not create a branch or worktree unless the user explicitly requests it.
- Task29 is currently `进行中`. Do not start Task30 production changes until Task29 is verified, reviewed, and marked `已完成` or the user explicitly resolves that project-state conflict.
- Preserve every pre-existing Task29 and GUI change. Never reset, restore, overwrite, or reformat an unrelated dirty path.
- Do not stage, commit, push, pull, fetch, or access a remote repository unless the user explicitly authorizes that exact Git action. Commit commands below are authorization checkpoints, not standing permission.
- Do not dispatch subagents unless the user explicitly requests them. The Session/Controller/REST/GUI changes are tightly coupled and should normally execute inline.
- Read `AGENTS.md`, `DESIGN.md`, `TASKS.md`, the approved spec, and the relevant current source/tests before production edits.
- Add no dependency and introduce no Agent framework or Agent SDK.
- Make no real provider request in default tests. Catalog tests inject fake SDK resources; a live smoke test requires separate explicit authorization.
- Dynamic discovery and selection apply only to Web Chat Completions mode. Responses mode and the one-shot CLI retain their startup-configured model behavior.
- Never expose or persist the API key, base URL, provider body, SDK exception text, headers, or environment dump.
- Accept all valid provider-returned IDs without capability/name heuristics, bounded to 256 UTF-8 bytes per ID and 2,048 unique IDs per complete snapshot.
- Always retain the configured startup model as the fallback option.
- A run's selected model is immutable after admission. Refresh and later selections cannot mutate active or historical runs.
- Legacy SQLite run rows use `model_id = NULL`; never fabricate a historical model from the current process configuration.
- Keep provider discovery outside Agent logical/provider budgets and JSONL run events.
- Keep filesystem path, command, verification, termination, Skill, session deletion, and tool-authority behavior unchanged.

## Locked File Map

**New production file**

- `src/coding_agent/model_catalog.py` — model-ID grammar, catalog view/error types, disabled catalog, Chat Completions discovery, last-good cache, and production catalog factory.

**Production files to modify**

- `src/coding_agent/session.py` — add nullable historical `model_id` to `SessionRunRecord`.
- `src/coding_agent/session_runtime.py` — add model ID to immutable run request and copy it into per-run `RunConfig`.
- `src/coding_agent/session_store.py` — schema v5 migration and exact run-model persistence.
- `src/coding_agent/session_controller.py` — inject catalog, resolve at admission, enforce persisted/request equality, expose safe catalog view.
- `src/coding_agent/web.py` — catalog endpoint, strict request field, response projection, and stable error mapping.
- `src/coding_agent/web_cli.py` — build one catalog from the validated Web `RunConfig` and inject it into the controller.
- `src/coding_agent/web_static/index.html` — compact accessible selector, refresh button, and status text inside the composer.
- `src/coding_agent/web_static/styles.css` — unified compact controls, ellipsis, warning, disabled, and narrow-layout behavior.
- `src/coding_agent/web_static/app.js` — catalog API/state/rendering/refresh, locking, and exact per-submit snapshot.

**Tests to create or modify**

- Create `tests/test_model_catalog.py`.
- Modify `tests/test_session.py`.
- Modify `tests/test_session_runtime.py`.
- Modify `tests/test_session_store.py`.
- Modify `tests/test_session_controller.py`.
- Modify `tests/web_support.py`.
- Modify `tests/test_web_api.py`.
- Modify `tests/test_web_cli.py`.
- Modify `tests/test_web_gui.py`.
- Modify `tests/js/web_gui.test.mjs`.
- Modify `tests/test_docs.py`.

**Architecture and user documentation**

- Modify `DESIGN.md`.
- Modify `TASKS.md`.
- Modify `docs/USAGE.md` only if its current Web launch/GUI section needs the new behavior documented.
- Retain the approved spec and this plan.

---

### Task 0: Project-state and architecture approval gate

**Files:**

- Read: `AGENTS.md`
- Read: `DESIGN.md`
- Read: `TASKS.md`
- Read: `docs/superpowers/specs/2026-08-31-chat-completions-dynamic-model-selection-design.md`
- Read: every production and test file in the locked file map
- Modify: `DESIGN.md`
- Modify: `TASKS.md`

**Interfaces:**

- Consumes: the user-approved written spec and the final reviewed Task29 baseline.
- Produces: an authoritative `DESIGN.md` subsection and a single Task30 entry with state `未开始`, followed by an explicit user approval gate before production code.

- [ ] **Step 1: Confirm exact repository ownership and Task29 state**

Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git log -5 --oneline
git status --short --untracked-files=all
git diff --check
rg -n "^## 29\.|^## 30\.|`进行中`|`未开始`" TASKS.md
```

Expected: repository root is `D:/code/coding_agent`; whitespace check exits 0. If Task29 is still `进行中`, stop without touching production files and ask the user to complete/review Task29 first. Record all dirty paths so later diffs can distinguish pre-existing changes.

- [ ] **Step 2: Run the post-Task29 baseline**

Run only after Task29 is resolved:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
node --test tests/js/web_gui.test.mjs
```

Expected: both exit 0. Record actual pass/fail/skip/warning counts rather than copying counts from an earlier run. Any failure stops Task30 before documentation or production edits.

- [ ] **Step 3: Update the architectural source of truth**

Append a focused `DESIGN.md` subsection that states exactly:

```markdown
## Chat Completions Web 模型发现与逐 Run 选择

Task30 按 `docs/superpowers/specs/2026-08-31-chat-completions-dynamic-model-selection-design.md` 实施。仅 Chat Completions Web 模式通过服务端 Models API 获取有界、完整的模型 ID 快照；浏览器不接触凭据或 base URL。Controller 从配置默认值或最后一次成功快照中解析模型，并在 admission 时把精确 ID 固化进 Run、SQLite 和每次新建的 RunConfig。刷新失败保留 last-good 快照或启动默认值，Responses 与一次性 CLI 保持原行为。
```

Update the non-goals/limitations section to say that API listing does not prove text, streaming, or tool-calling compatibility and that active-run model switching remains unsupported.

- [ ] **Step 4: Register Task30 without changing Task29 history**

Add `## 30. Chat Completions 动态模型选择` to `TASKS.md` with the nine acceptance criteria from the spec, required offline catalog/Session/SQLite/REST/GUI tests, suggested commit `feat: add dynamic chat model selection`, and current state `未开始`.

Run:

```powershell
rg -n "^## 29\.|^## 30\.|Chat Completions 动态模型选择|`进行中`|`未开始`" TASKS.md
git diff --check -- DESIGN.md TASKS.md
```

Expected: Task29 history is unchanged; Task30 appears exactly once and is not marked `进行中` yet.

- [ ] **Step 5: Stop for the mandatory project-doc approval**

Present the exact `DESIGN.md` and `TASKS.md` diffs to the user. Do not begin Task 1 until the user explicitly approves both updated files and this implementation plan.

**Acceptance:** Task29 is resolved, baseline tests are green, architecture/task docs match the approved spec, and the user explicitly authorizes Task30 implementation.

---

### Task 1: Bounded model catalog and last-good cache

**Files:**

- Create: `src/coding_agent/model_catalog.py`
- Create: `tests/test_model_catalog.py`

**Interfaces:**

- Produces: `require_model_id(value: object) -> str`.
- Produces: `ModelCatalogStatus`, `ModelCatalogView`, `ModelCatalogError(code)`.
- Produces: runtime-checkable `ModelCatalog` protocol with `default_model_id`, `list_models(refresh=False)`, and `resolve(requested_model_id)`.
- Produces: `DisabledModelCatalog(default_model_id)` and `ChatCompletionsModelCatalog(default_model_id, api_key, base_url, sdk_client=None, timeout_seconds=10.0)`.
- Produces: `create_model_catalog(config: RunConfig) -> ModelCatalog`.

- [ ] **Step 1: Mark Task30 active after approval**

Change only Task30's state from `未开始` to `进行中`, then run:

```powershell
rg -n "^## 30\.|`进行中`" TASKS.md
```

Expected: Task30 is the only active task.

- [ ] **Step 2: Write failing ID and view tests**

Add tests equivalent to:

```python
@pytest.mark.parametrize("value", ["", " model", "model ", "a\nmodel", "\ud800"])
def test_require_model_id_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ModelCatalogError, match="^invalid_model_id$"):
        require_model_id(value)


def test_view_is_immutable_and_contains_default() -> None:
    view = ModelCatalogView(
        enabled=True,
        status=ModelCatalogStatus.READY,
        default_model_id="chat-default",
        model_ids=("chat-default", "z-model"),
        error_code=None,
    )
    assert view.model_ids[0] == "chat-default"
```

Include exact 256-byte acceptance and 257-byte rejection, exact-string preservation, type rejection, invalid status/error combinations, and secret-free `repr` assertions.

- [ ] **Step 3: Run the focused tests and observe RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_model_catalog.py -q -p no:cacheprovider
```

Expected: collection fails because `coding_agent.model_catalog` does not exist.

- [ ] **Step 4: Implement pure catalog types and disabled behavior**

Implement these exact contracts before remote discovery:

```python
MAX_MODEL_ID_BYTES = 256
MAX_MODEL_IDS = 2_048
MODEL_CATALOG_ERROR = "model_catalog_unavailable"

class ModelCatalogStatus(StrEnum):
    READY = "ready"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"

class ModelCatalogError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

@runtime_checkable
class ModelCatalog(Protocol):
    @property
    def default_model_id(self) -> str:
        raise NotImplementedError

    def list_models(self, *, refresh: bool = False) -> ModelCatalogView:
        raise NotImplementedError

    def resolve(self, requested_model_id: str | None) -> str:
        raise NotImplementedError
```

`DisabledModelCatalog.list_models()` must return `enabled=False`, `status=disabled`, the one configured model, and no error. `resolve(None)` and `resolve(default)` return the default; every other value raises `ModelCatalogError("model_not_available")`.

- [ ] **Step 5: Write failing discovery/cache tests**

Use a fake SDK whose `models.list()` returns objects with `.id`. Add separately
named tests for complete multi-page listing with exact deduplication/default
insertion; ordinary cache reuse and refresh replacement; failed initial
discovery; failed refresh with a stale last-good result; rejection above 2,048
unique IDs; default/last-good-only resolution; and secret-free error/repr
projection.

Assert deterministic sorting uses `(value.casefold(), value)`, invalid returned entries are skipped, and a snapshot with zero valid provider IDs still contains the default.

- [ ] **Step 6: Implement Chat discovery minimally**

Construct `OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=timeout_seconds)` only when no fake SDK is injected. Hold a private `RLock`, call `self._client.models.list()`, validate every `.id`, fail the whole refresh when more than 2,048 unique valid IDs appear, atomically replace `_last_good`, and collapse `Exception` to the safe unavailable view. Re-raise `KeyboardInterrupt`, `SystemExit`, and other `BaseException` values.

`create_model_catalog(config)` returns `DisabledModelCatalog(config.model)` for Responses and `ChatCompletionsModelCatalog(default_model_id=config.model, api_key=config.api_key, base_url=config.base_url)` for Chat Completions after asserting the validated base URL is non-null. It performs no network request during construction.

- [ ] **Step 7: Run focused and adapter-regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_model_catalog.py tests/test_config.py tests/test_chat_completions_client.py tests/test_chat_completions_streaming_client.py -q -p no:cacheprovider
```

Expected: all pass offline with zero real network calls.

- [ ] **Step 8: Review checkpoint and optional commit**

Inspect:

```powershell
git diff -- src/coding_agent/model_catalog.py tests/test_model_catalog.py
git diff --check -- src/coding_agent/model_catalog.py tests/test_model_catalog.py
```

If and only if the user separately authorizes a commit:

```powershell
git add src/coding_agent/model_catalog.py tests/test_model_catalog.py TASKS.md DESIGN.md
git commit -m "feat: add bounded chat model catalog"
```

**Acceptance:** catalog construction is offline, discovery is bounded and complete-or-fail, last-good fallback is deterministic, and secrets/provider diagnostics do not cross the boundary.

---

### Task 2: Immutable run model metadata

**Files:**

- Modify: `src/coding_agent/session.py`
- Modify: `src/coding_agent/session_runtime.py`
- Modify: `tests/test_session.py`
- Modify: `tests/test_session_runtime.py`

**Interfaces:**

- Consumes: `require_model_id` from Task 1.
- Produces: `SessionRunRecord.model_id: str | None` (`None` only for migrated history).
- Produces: required `SessionRunRequest.model_id: str`.
- Produces: `SessionRunExecutor.default_model_id: str` and `AgentSessionRunExecutor.default_model_id`.
- Produces: executor replacement `replace(base_config, task=request.current_message, run_mode=request.run_mode, budget_profile=request.budget_profile, model=request.model_id)`.

- [ ] **Step 1: Write failing domain tests**

Add separately named tests proving that a run record accepts `None` for legacy
projection, rejects an invalid non-null ID, a run request requires a valid ID,
and the executor exposes its startup default while replacing the model for one
run only.

In the executor test, use base model `startup-model`, request model `selected-model`, capture the `RunConfig` passed to the fake application factory, and assert the base config remains unchanged.

- [ ] **Step 2: Run focused tests and observe RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session.py tests/test_session_runtime.py -q -p no:cacheprovider
```

Expected: failures report missing `model_id` and `default_model_id` behavior.

- [ ] **Step 3: Add immutable model metadata**

Add the fields without changing final-report schema or narrative rendering:

Add `model_id: str | None = field(default=None, repr=False)` as the final
`SessionRunRecord` field so historical/test constructors remain compatible.
Add required `model_id: str = field(repr=False)` before the defaulted request
fields in `SessionRunRequest`. Add this protocol property:

```python
@property
def default_model_id(self) -> str:
    raise NotImplementedError
```

Validate non-null IDs through `require_model_id`; never include the model in `SessionNarrativeRenderer`. `AgentSessionRunExecutor.execute()` must copy the selected model into the fresh config before `execute_agent_run()` constructs its client.

- [ ] **Step 4: Update local constructors and pass tests**

Update test builders in these two files with explicit `model_id="test-model"`, using `None` only in the dedicated legacy record test.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session.py tests/test_session_runtime.py -q -p no:cacheprovider
```

Expected: all pass.

- [ ] **Step 5: Review checkpoint and optional commit**

Run `git diff --check` on the four Task 2 paths. Commit only with separate user authorization:

```powershell
git add src/coding_agent/session.py src/coding_agent/session_runtime.py tests/test_session.py tests/test_session_runtime.py
git commit -m "feat: snapshot model in session runs"
```

**Acceptance:** one run request has one immutable valid model, the executor constructs that exact run configuration, and history/narrative semantics are unchanged.

---

### Task 3: SQLite schema v5 and exact model persistence

**Files:**

- Modify: `src/coding_agent/session_store.py`
- Modify: `tests/test_session_store.py`

**Interfaces:**

- Consumes: nullable `SessionRunRecord.model_id` and `require_model_id`.
- Produces: `SCHEMA_VERSION = 5`, nullable database column `session_runs.model_id`, and required internal `model_id` arguments for new submissions.
- Produces: v1/v2/v3/v4-to-v5 migration with no final-report rewrite for model selection.

- [ ] **Step 1: Write failing fresh-schema and migration tests**

Add separately named tests for fresh-schema create/follow-up persistence, v4
nullable migration without fabricated history, sequential v1-to-v5 migration,
pre-write rejection of missing/invalid IDs, and reopen/recovery preservation.

For the v4 fixture, insert a historical run, initialize the new store, assert `PRAGMA user_version == 5`, `model_id is None`, and all earlier run/event/report fields are byte-for-byte equivalent.

- [ ] **Step 2: Run focused tests and observe RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_store.py -q -p no:cacheprovider
```

Expected: schema/version/signature assertions fail before implementation.

- [ ] **Step 3: Implement the v5 migration carefully**

Change the fresh schema to include:

```sql
model_id TEXT CHECK(model_id IS NULL OR length(model_id) > 0),
```

Set `SCHEMA_VERSION = 5`. Change `_migrate_to_version_4()` to set literal user version `4`, not the mutable `SCHEMA_VERSION`, then add:

```python
@classmethod
def _migrate_to_version_5(cls, connection: sqlite3.Connection) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(session_runs)")
        }
        if "model_id" not in columns:
            connection.execute(
                "ALTER TABLE session_runs ADD COLUMN model_id TEXT"
            )
        connection.execute("PRAGMA user_version = 5")
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        raise SessionStoreError("storage_unavailable") from None
```

The method must be idempotent by inspecting `PRAGMA table_info`, rollback on every failure, and never update legacy rows or report JSON.

- [ ] **Step 4: Thread exact model IDs through store writes and reads**

Require kw-only `model_id: str` in `SessionStore.create_session`, `SQLiteSessionStore.create_session`, `SessionStore.submit_message`, and `SQLiteSessionStore.submit_message`. Validate before opening a transaction. Add the named column to both INSERT statements; do not return to a positional `INSERT INTO session_runs VALUES` statement without an explicit column list. Decode SQL `NULL` as Python `None` and non-null via `require_model_id`.

- [ ] **Step 5: Run store and deletion/recovery regression tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_store.py tests/test_session_deletion.py tests/test_session.py -q -p no:cacheprovider
```

Expected: all pass; session deletion manifests and recovery remain independent of model choice.

- [ ] **Step 6: Review checkpoint and optional commit**

Inspect the exact SQL diff and run `git diff --check`. Commit only with explicit authorization:

```powershell
git add src/coding_agent/session_store.py tests/test_session_store.py
git commit -m "feat: persist per-run model selection"
```

**Acceptance:** every new run stores an exact non-null model, all old schemas migrate atomically to v5, and historical runs remain honestly unknown.

---

### Task 4: Controller admission and run invariants

**Files:**

- Modify: `src/coding_agent/session_controller.py`
- Modify: `tests/test_session_controller.py`
- Modify: `tests/web_support.py`

**Interfaces:**

- Consumes: `ModelCatalog`, catalog `resolve/list_models`, executor `default_model_id`, and required store model arguments.
- Produces: `RunHandle.model_id: str`.
- Produces: `SessionController.list_models(refresh=False) -> ModelCatalogView`.
- Produces: optional external `model_id` on `create_session` and `submit_message`; `None` means configured default.

- [ ] **Step 1: Write failing controller tests**

Add separately named tests for catalog/executor default mismatch, default
resolution before store/worker calls, a follow-up selecting another model,
unknown-model rejection with zero side effects, refresh delegation without
active-run mutation, and persisted/request model mismatch at run start.

Update shared fake executors with `default_model_id="test-model"`, fake catalogs with a deterministic snapshot, and `make_run_record(model_id="test-model")`.

- [ ] **Step 2: Run focused tests and observe RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_controller.py -q -p no:cacheprovider
```

Expected: failures identify missing catalog injection and model propagation.

- [ ] **Step 3: Inject and validate the catalog**

Add `model_catalog: ModelCatalog` to `SessionController.__init__` and `.open()`. At construction, require the catalog default to equal `executor.default_model_id`; convert invalid collaborators to `SessionControllerError("invalid_session_state")`. Store it privately without exposing credentials.

Implement:

```python
def list_models(self, *, refresh: bool = False) -> ModelCatalogView:
    return self._model_catalog.list_models(refresh=refresh)
```

Translate only `ModelCatalogError("model_not_available")` to the same controller code; unexpected catalog invariants remain internal errors.

- [ ] **Step 4: Resolve before admission side effects**

In create/follow-up, call `resolved_model = self._model_catalog.resolve(model_id)` before store writes. Pass it to the store and `SessionRunRequest`. Add it to `RunHandle`. During `_start_worker`/run-start reconciliation, compare persisted `model_id` with `request.model_id` alongside run mode and budget profile.

- [ ] **Step 5: Run controller, event, and session regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_controller.py tests/test_session_events.py tests/test_session_runtime.py -q -p no:cacheprovider
```

Expected: all pass and refresh cannot alter the active request.

- [ ] **Step 6: Review checkpoint and optional commit**

Run `git diff --check` on Task 4 paths. Commit only with explicit authorization:

```powershell
git add src/coding_agent/session_controller.py tests/test_session_controller.py tests/web_support.py
git commit -m "feat: validate model at run admission"
```

**Acceptance:** the same resolved ID reaches persisted record, run request, handle, and executor; rejected IDs admit no work.

---

### Task 5: REST contract and Web composition root

**Files:**

- Modify: `src/coding_agent/web.py`
- Modify: `src/coding_agent/web_cli.py`
- Modify: `tests/test_web_api.py`
- Modify: `tests/test_web_cli.py`
- Modify: `tests/web_support.py`

**Interfaces:**

- Consumes: controller catalog/admission methods and `create_model_catalog(config)`.
- Produces: authenticated `GET /api/v1/models?refresh=false|true`.
- Produces: optional strict `model_id` in create/follow-up JSON and `model_id` in run responses/projections.

- [ ] **Step 1: Write failing REST contract tests**

Add tests for ready/stale/unavailable/disabled catalog JSON, `refresh=true`, rejection of `refresh=1`, auth/Host/Origin/no-store behavior, exact defaulting, selected propagation, `null`, invalid type, extra field, unknown ID HTTP 400, and serialized legacy run `model_id: null`.

The core success assertion is:

```python
assert response.json() == {
    "enabled": True,
    "status": "ready",
    "default_model_id": "chat-default",
    "model_ids": ["chat-default", "other-model"],
    "error_code": None,
}
```

- [ ] **Step 2: Run API tests and observe RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_api.py -q -p no:cacheprovider
```

Expected: model route/fields are absent.

- [ ] **Step 3: Implement the thin REST projection**

Use `Literal["false", "true"]` for the query rather than permissive boolean coercion:

```python
@app.get("/api/v1/models")
def list_models(refresh: Literal["false", "true"] = "false") -> dict[str, object]:
    return _serialize_model_catalog(
        controller.list_models(refresh=refresh == "true")
    )
```

Add `model_id: StrictStr | None = None` to both strict Pydantic bodies. Pass it to controller, return the resolved handle field, and add nullable `model_id` to `_serialize_run`. Map `model_not_available` to HTTP 400. Never serialize catalog internals, key, base URL, exception, or SDK object.

- [ ] **Step 4: Write failing Web composition tests**

In `tests/test_web_cli.py`, inject a fake `_model_catalog_factory`, capture its exact `RunConfig`, and assert the resulting catalog is passed to `_controller_factory(config.workspace, executor, sensitive_values=(config.api_key, policy.token), model_catalog=catalog)`. Cover Responses disabled creation and Chat creation without a remote call.

- [ ] **Step 5: Wire the production catalog at startup**

In `web_cli.py` define `_model_catalog_factory = create_model_catalog`, construct it after validated config and before controller open, then pass it as an explicit keyword. Construction must not call `/models`; Web server startup succeeds when the remote service is offline.

- [ ] **Step 6: Run Web/API composition regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_api.py tests/test_web_cli.py tests/test_web_auth.py -q -p no:cacheprovider
```

Expected: all pass offline.

- [ ] **Step 7: Review checkpoint and optional commit**

Run `git diff --check` on Task 5 paths. Commit only with explicit authorization:

```powershell
git add src/coding_agent/web.py src/coding_agent/web_cli.py tests/test_web_api.py tests/test_web_cli.py tests/web_support.py
git commit -m "feat: expose safe model selection API"
```

**Acceptance:** local REST exposes only safe catalog metadata, request validation is exact, and Web startup never depends on provider availability.

---

### Task 6: Composer model selector and refresh behavior

**Files:**

- Modify: `src/coding_agent/web_static/index.html`
- Modify: `src/coding_agent/web_static/styles.css`
- Modify: `src/coding_agent/web_static/app.js`
- Modify: `tests/test_web_gui.py`
- Modify: `tests/js/web_gui.test.mjs`

**Interfaces:**

- Consumes: Task 5 catalog and run JSON contracts.
- Produces: `api.listModels(refresh = false)`, state `modelCatalog`/`selectedModelId`, composer select, refresh button, and non-blocking safe status.

- [ ] **Step 1: Write failing static structure tests**

Require exact IDs:

```text
model-control
model-select
refresh-models-button
model-catalog-status
```

Assert the controls are descendants of `.composer-actions`, have a visible/accessibility label, use native `<select>`, contain no inline handler/style, and preserve the existing Enter/Shift+Enter hint and send button.

- [ ] **Step 2: Write failing Node behavior tests**

Add cases for:

```javascript
test("initialization loads the model catalog and selects its default", async () => {});
test("Responses mode hides model controls", async () => {});
test("refresh replaces options and falls back when selection disappeared", async () => {});
test("stale and unavailable catalogs keep safe usable choices", async () => {});
test("selected model is snapshotted into create and follow-up requests", async () => {});
test("active sessions disable select and refresh", async () => {});
test("provider IDs render as text and never as HTML", async () => {});
```

Use a malicious-looking ID such as `<img src=x onerror=alert(1)>` only if it passes the server grammar; assert it remains option text and creates no element.

- [ ] **Step 3: Run GUI tests and observe RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_gui.py -q -p no:cacheprovider
node --test tests/js/web_gui.test.mjs
```

Expected: missing model elements/API behavior fail.

- [ ] **Step 4: Add compact composer markup and CSS**

Place a labeled wrapper after budget controls and before the Enter hint:

```html
<div id="model-control" class="model-control" hidden>
  <label for="model-select">模型</label>
  <select id="model-select" aria-label="选择下一次运行使用的模型"></select>
  <button id="refresh-models-button" type="button" aria-label="刷新模型列表">↻</button>
  <span id="model-catalog-status" role="status" aria-live="polite"></span>
</div>
```

Match existing warm border/background/radius/font tokens. Cap the closed select width, use `min-width: 0` and text overflow behavior, keep desktop `.composer-actions` compact, and wrap only at the existing narrow breakpoint. Do not change `.workspace` row sizing or add a connection/status strip.

- [ ] **Step 5: Add catalog state, safe rendering, and refresh**

Extend initial state with:

```javascript
modelCatalog: {
  enabled: false,
  status: "disabled",
  defaultModelId: null,
  modelIds: [],
  errorCode: null,
},
selectedModelId: null,
```

`api.listModels(refresh)` calls `/api/v1/models?refresh=true|false`. Initialization must not let a catalog request failure prevent sessions/Skills from rendering: catch it and synthesize a disabled/unavailable safe view without displaying raw exception text. Populate options with `document.createElement("option")` and `appendPlainText`/`textContent`; never use `innerHTML`, `insertAdjacentHTML`, or untrusted attribute construction.

On explicit refresh, preserve the current selected ID only if still present; otherwise select `default_model_id`. Map `stale` to a short warning and `unavailable` to `无法获取模型列表`. Hide the entire control when `enabled` is false.

- [ ] **Step 6: Snapshot model on submit and enforce locks**

At the start of `submitComposer()`, copy `const modelId = state.selectedModelId`; pass it as the final argument to both API methods. Update JSON bodies with `model_id: modelId`. Disable select and refresh when any session is active or refresh is pending. Do not change selection when browsing historical sessions. Task30 does not add a separate visible per-run model card; persistence and REST projection provide the audit record.

- [ ] **Step 7: Run focused GUI tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_gui.py -q -p no:cacheprovider
node --test tests/js/web_gui.test.mjs
```

Expected: all pass, including existing Markdown/table rendering, Skill expansion/import, session deletion, empty state, Enter submission, and layout contracts.

- [ ] **Step 8: Run the unsafe HTML sink scan**

Use the repository's existing sink assertion from `tests/test_web_gui.py`; additionally run:

```powershell
rg -n "innerHTML|outerHTML|insertAdjacentHTML|document\.write" src/coding_agent/web_static tests/js/web_gui.test.mjs
```

Expected: zero production unsafe sinks; any test fixture occurrence is reviewed as inert text.

- [ ] **Step 9: Review checkpoint and optional commit**

Inspect the five GUI diffs separately from their pre-existing Task29 state and run `git diff --check`. Commit only with explicit authorization:

```powershell
git add src/coding_agent/web_static/index.html src/coding_agent/web_static/styles.css src/coding_agent/web_static/app.js tests/test_web_gui.py tests/js/web_gui.test.mjs
git commit -m "feat: add composer model selector"
```

**Acceptance:** Chat mode shows every safe returned ID in the composer, refresh/fallback is usable, Responses hides controls, and layout/security regressions remain green.

---

### Task 7: Documentation, integration audit, and complete verification

**Files:**

- Modify: `docs/USAGE.md` if required by its current Web section
- Modify: `tests/test_docs.py`
- Modify: `TASKS.md` only after user review
- Verify: every path in the locked file map

**Interfaces:**

- Consumes: completed Tasks 1–6.
- Produces: accurate user-facing behavior, dependency/security audit, code review evidence, and final test evidence.

- [ ] **Step 1: Add failing documentation contract tests**

Require docs to state: Chat-only discovery, all valid IDs, startup default fallback, next-run-only semantics, `/models` compatibility caveat, and no browser credential exposure. Do not document a real provider URL, token, or API key.

- [ ] **Step 2: Update usage documentation minimally**

In the existing Web Chat Completions section, explain that the composer lists provider-returned model IDs, refresh may show stale/fallback choices, and listing does not guarantee function-tool/stream support. Leave Responses and one-shot CLI instructions unchanged.

- [ ] **Step 3: Run focused cross-layer integration tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_model_catalog.py tests/test_session.py tests/test_session_runtime.py tests/test_session_store.py tests/test_session_controller.py tests/test_web_api.py tests/test_web_cli.py tests/test_web_gui.py tests/test_docs.py -q -p no:cacheprovider
node --test tests/js/web_gui.test.mjs
```

Expected: all pass offline. Record actual counts.

- [ ] **Step 4: Run provider and session regression suites**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_chat_completions_client.py tests/test_chat_completions_streaming_client.py tests/integration/test_chat_completions_agent.py tests/test_web_sse.py tests/test_session_events.py tests/test_session_deletion.py -q -p no:cacheprovider
```

Expected: all pass; no real API request occurs.

- [ ] **Step 5: Request core-module code review**

Invoke `superpowers:requesting-code-review` and review at minimum:

- catalog complete-or-fail bounds and secret handling;
- controller admission side-effect ordering;
- v4-to-v5 and v1-to-v5 migrations;
- executor/store/request model equality;
- REST strictness and GUI safe DOM behavior;
- pre-existing Task29 changes remain preserved.

Resolve findings with TDD; invoke systematic debugging for any reproducible failure.

- [ ] **Step 6: Run the complete offline suite from a fresh command**

Invoke `superpowers:verification-before-completion`, then run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
node --test tests/js/web_gui.test.mjs
git diff --check
git status --short --untracked-files=all
```

Expected: Python and Node exit 0; whitespace check exits 0. Report actual counts and distinguish pre-existing Task29/user changes from Task30 changes.

- [ ] **Step 7: Perform static policy audits**

```powershell
rg -n "langchain|llamaindex|openai-agents|autogen|crewai" pyproject.toml src tests
rg -n "API_KEY\s*=|Bearer [A-Za-z0-9]|sk-[A-Za-z0-9]" src tests docs README.md README.txt DESIGN.md TASKS.md
rg -n "innerHTML|outerHTML|insertAdjacentHTML|document\.write" src/coding_agent/web_static
```

Expected: no prohibited framework/dependency, embedded credential, or unsafe production HTML sink. Review benign environment-variable-name references rather than suppressing them.

- [ ] **Step 8: Optional live smoke test remains a separate authorization**

Do not run it by default. If the user explicitly authorizes a real Chat Completions request and confirms a non-production credential, test only catalog listing plus one harmless read-only run and report it separately from automated evidence. Never capture the key, headers, provider body, or environment.

- [ ] **Step 9: User review before completion state**

Present changed files, exact behavior, migration semantics, review findings, and real verification output. Keep Task30 `进行中` until the user accepts the implementation. After acceptance, change only Task30 to `已完成` and rerun:

```powershell
git diff --check -- TASKS.md
rg -n "^## 30\.|`已完成`|`进行中`" TASKS.md
```

- [ ] **Step 10: Final optional commit checkpoint**

Only if the user explicitly authorizes a commit after reviewing the complete diff:

```powershell
git add DESIGN.md TASKS.md docs/USAGE.md docs/superpowers/specs/2026-08-31-chat-completions-dynamic-model-selection-design.md docs/superpowers/plans/2026-08-31-chat-completions-dynamic-model-selection.md src/coding_agent/model_catalog.py src/coding_agent/session.py src/coding_agent/session_runtime.py src/coding_agent/session_store.py src/coding_agent/session_controller.py src/coding_agent/web.py src/coding_agent/web_cli.py src/coding_agent/web_static/index.html src/coding_agent/web_static/styles.css src/coding_agent/web_static/app.js tests/test_model_catalog.py tests/test_session.py tests/test_session_runtime.py tests/test_session_store.py tests/test_session_controller.py tests/web_support.py tests/test_web_api.py tests/test_web_cli.py tests/test_web_gui.py tests/js/web_gui.test.mjs tests/test_docs.py
git commit -m "feat: add dynamic chat model selection"
```

Do not push without a second explicit authorization.

**Acceptance:** all approved requirements are implemented and verified offline, Task29 work is preserved, no secret or authority boundary regresses, and Task30 is marked complete only after user acceptance.

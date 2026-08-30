# Local Web GUI Milestone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an authenticated loopback FastAPI/REST/SSE adapter over the accepted session controller, then add a packaged warm-light local GUI without changing Agent semantics.

**Architecture:** A thin synchronous FastAPI boundary delegates every domain operation to the existing `SessionController`; a fetch-based SSE client consumes the existing bounded `SessionEventHub` contract. A separate `coding-agent-web` composition root owns the loopback socket, access token, controller, Uvicorn server, and packaged no-build GUI.

**Tech Stack:** Python 3.11+, FastAPI, Starlette `StreamingResponse`, Uvicorn, Pydantic through FastAPI, HTTPX for offline HTTP tests, SQLite through the existing store, vanilla HTML/CSS/JavaScript, Node.js 20 built-in `node:test` for browser-independent GUI behavior, and pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-local-web-gui-design.md`

## Global Constraints

- Work in the user-approved current `main` workspace; do not create a branch or worktree unless a later direct user instruction changes this.
- Do not stage, commit, push, pull, fetch, or modify a remote during implementation or checkpoints.
- Do not call a real model API, read a real credential, or permit external-network access in tests.
- Preserve `ModelClient`, `AgentRunner`, `SessionController`, `SessionEventHub`, session records, Skill records, tool, safety, verification, provider, existing CLI, and report public interfaces.
- FastAPI, Pydantic, Starlette, and Uvicorn types may exist only in Web modules.
- Bind only IPv4 `127.0.0.1`; no option may widen the listener.
- Use one controller and one active Agent run; the Web layer must not add a queue or parallel execution.
- Do not expose API keys, Bearer token, Skill instructions, model messages, provider payloads, continuation, hidden reasoning, environment values, raw exception text, traceback, or local absolute paths.
- Node.js is a test-only executable already present in the target environment; do not add npm, `package.json`, JavaScript packages, a build step, or a production Node dependency.
- Use strict TDD for every production behavior: one focused failing test, observed expected RED, minimum GREEN, focused regression, then the next behavior.
- RED/GREEN evidence is recorded and summarized at the two milestone checkpoints; execution pauses early only for an interface conflict, new unapproved dependency, security-boundary change, edit outside the locked map, or repeated unexplained failure.
- Task 22 remains `进行中` at the API/authentication checkpoint. After explicit acceptance, Task 22 becomes `已完成` and Task 23 becomes `进行中`. Task 23 remains `进行中` at final review.
- No automatic Git commit step exists in this plan. Suggested commit messages remain documentation only until user authorization.

---

## File map

### Create for Task 22

- `src/coding_agent/web_auth.py` — token generation, raw-header Host/Origin/Bearer validation, hidden representations, stable authorization errors.
- `src/coding_agent/web.py` — strict DTOs, body limit, stable errors, REST projection, SSE encoding and connection bounds, FastAPI factory.
- `src/coding_agent/web_cli.py` — separate parser, loopback socket, controller/Uvicorn composition, cleanup and entry point.
- `tests/web_support.py` — deterministic controller doubles and accepted session/Skill/event record factories; test-only content.
- `tests/test_web_auth.py` — security policy tests.
- `tests/test_web_api.py` — request, response, error, and REST integration tests.
- `tests/test_web_sse.py` — SSE replay, wait, reset, disconnect, and limit tests.
- `tests/test_web_cli.py` — parser, config reuse, socket, lifecycle, and entry tests.

### Create for Task 23

- `src/coding_agent/web_static/index.html` — semantic GUI shell and one exact token-bootstrap marker.
- `src/coding_agent/web_static/app.js` — in-memory UI state, API client, SSE parser/reconnect, safe DOM projection.
- `src/coding_agent/web_static/styles.css` — warm ivory responsive visual system.
- `tests/test_web_gui.py` — static-resource, CSP, packaging, DOM, client-contract, and unsafe-sink tests.
- `tests/js/dom_harness.mjs` — minimal test-only DOM implementation for observable safe-rendering behavior.
- `tests/js/web_gui.test.mjs` — executable Node tests for state, API, SSE parsing/reconnect, actions, and DOM projection.
- `tests/manual_web_fixture.py` — deterministic local visual fixture using `tests/web_support.py`; never installed in the package.

### Modify

- `pyproject.toml` — add only `fastapi`, `uvicorn`, test `httpx`, `coding-agent-web`, and packaged `web_static` files.
- `tests/test_cli.py` — TDD-update the exact pyproject dependency and console-entry metadata contract.
- `TASKS.md` — add exact Task 22/23 descriptions and update statuses only at locked checkpoints.
- `DESIGN.md` — record the approved in-progress milestone before code, then describe delivered local transport and GUI after GREEN.
- `README.txt`, `README.md`, `docs/USAGE.md`, `docs/OPENAI_API.md` — document only verified launch, security, GUI, and provider behavior.

### Must remain unchanged

- `src/coding_agent/agent.py`
- `src/coding_agent/app.py`
- `src/coding_agent/chat_completions_client.py`
- `src/coding_agent/cli.py`
- `src/coding_agent/config.py`
- `src/coding_agent/context.py`
- `src/coding_agent/instructions.py`
- `src/coding_agent/logging.py`
- `src/coding_agent/messages.py`
- `src/coding_agent/model.py`
- `src/coding_agent/openai_client.py`
- `src/coding_agent/report.py`
- `src/coding_agent/safety.py`
- `src/coding_agent/session.py`
- `src/coding_agent/session_controller.py`
- `src/coding_agent/session_events.py`
- `src/coding_agent/session_runtime.py`
- `src/coding_agent/session_store.py`
- `src/coding_agent/skills.py`
- `src/coding_agent/state.py`
- `src/coding_agent/streaming.py`
- `src/coding_agent/termination.py`
- `src/coding_agent/tools/**`
- all existing Task 1-21 tests except the explicitly listed metadata assertions in `tests/test_cli.py`

If a RED proves that an accepted core file must change, stop and request design approval rather than adapting the interface.

---

### Task 0: Baseline, dependency availability, roadmap, and status activation

**Files:**
- Read: `AGENTS.md`
- Read: `DESIGN.md`
- Read: `TASKS.md`
- Read: `docs/superpowers/specs/2026-08-30-local-web-gui-design.md`
- Read: this plan
- Read: every file in the locked existing session/controller/Skill map
- Modify after baseline only: `TASKS.md`
- Modify after baseline only: `DESIGN.md`
- Modify after an observed metadata RED only: `tests/test_cli.py`
- Modify after baseline only: `pyproject.toml`

**Interfaces:**
- Consumes: accepted Task 21 HEAD and a clean workspace containing at most this approved spec and plan.
- Produces: an in-progress design baseline, exact Task 22/23 roadmap, tested direct dependency/entry metadata, and exactly Task 22 active.

- [ ] **Step 1: Re-read project instructions and accepted boundaries**

Read the complete files, not excerpts:

```powershell
Get-Content AGENTS.md
Get-Content DESIGN.md
Get-Content TASKS.md
Get-Content docs\superpowers\specs\2026-08-30-local-web-gui-design.md
Get-Content docs\superpowers\plans\2026-08-30-local-web-gui.md
Get-Content src\coding_agent\session.py
Get-Content src\coding_agent\session_store.py
Get-Content src\coding_agent\session_events.py
Get-Content src\coding_agent\session_runtime.py
Get-Content src\coding_agent\session_controller.py
Get-Content src\coding_agent\skills.py
Get-Content src\coding_agent\config.py
Get-Content src\coding_agent\cli.py
Get-Content src\coding_agent\app.py
```

Expected: no accepted interface conflicts with the spec. If a conflict exists,
record exact paths and signatures and stop before editing.

- [ ] **Step 2: Verify repository and Task 21 baseline**

```powershell
git rev-parse --show-toplevel
git branch --show-current
git log -3 --oneline
git status --short --untracked-files=all
git diff --check
git diff --name-only HEAD
```

Expected: root is `D:/code/coding_agent`, branch is `main`, HEAD contains the
accepted Task 21 commit, and status contains only the approved spec/plan when
they have not yet been committed. Any production/test change is a stop.

- [ ] **Step 3: Run the fresh Task 1-21 baseline**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit `0`; record actual passed, failed, skipped, warning counts. A
failure stops execution before roadmap or dependency edits.

- [ ] **Step 4: Add the exact Task 22 and Task 23 roadmap**

Append these sections before `任务完成规则` and change only Task 21's status to
`已完成`:

```markdown
## 22. 本地 FastAPI、REST 与 SSE 传输层

**任务目标**

以经过认证的 loopback FastAPI 边界暴露现有 SessionController、SessionEventHub 和声明式 Skill 能力，不改变 Agent、会话或安全语义。

**涉及模块**

- `src/coding_agent/web_auth.py`
- `src/coding_agent/web.py`
- `src/coding_agent/web_cli.py`
- Web 传输层离线测试

**验收标准**

- 只绑定 IPv4 `127.0.0.1`，默认使用系统分配端口。
- REST 和 SSE 均要求进程级 Bearer token、严格 Host 与 Origin 检查。
- 所有业务操作委托给现有 SessionController；不增加运行队列或第二套状态机。
- SSE 保持既有安全事件顺序、游标、重放、等待和 reset-required 语义。
- HTTP 错误、日志和对象表示不泄漏凭据、路径、异常正文、Skill 指令或 provider 数据。
- Task 1-21 行为保持，测试不调用真实外部 API。

**需要编写的测试**

- token、Host、Origin、重复 header 和脱敏测试。
- 严格 DTO、请求体上限、REST 映射和稳定错误测试。
- SSE 顺序、heartbeat、重放、reset、断连、终止和连接上限测试。
- Web CLI、loopback socket、随机端口、资源关闭和安装入口测试。

**建议的 Git 提交说明**

`feat: add authenticated local web transport`

**当前状态**

`进行中`

## 23. 本地静态 GUI

**任务目标**

在 Task 22 同源服务中增加无构建步骤的暖色浅色 GUI，展示持久会话、流式 Agent 状态、Skill 选择、取消与验证结果。

**涉及模块**

- `src/coding_agent/web_static/index.html`
- `src/coding_agent/web_static/app.js`
- `src/coding_agent/web_static/styles.css`
- GUI 资源、安全、交互合同和打包测试

**验收标准**

- 左侧会话列表、中间大对话区、顶部运行状态与耗时、底部输入框符合批准设计。
- 使用 fetch Bearer SSE；token 只在页面内存中存在。
- 可新建会话、提交 follow-up、选择 Skill、取消 run，并恢复 SSE 游标。
- 模型文本不经过不安全 HTML sink；不加载远程脚本、样式、字体或图像。
- GUI 不伪造 SUCCESS，不把浏览器断开映射为 Agent 取消。
- 静态资源随 wheel 安装，现有 CLI 和 Task 1-22 全部回归通过。

**需要编写的测试**

- HTML/CSS/JS 结构、CSP、token bootstrap 和禁止模式测试。
- API 路径、Bearer、SSE 游标、重连、reset 和终止合同测试。
- wheel 资源、安装入口、响应 header 和无外部资源测试。
- 离线视觉 fixture 和人工多尺寸状态验收。

**建议的 Git 提交说明**

`feat: add local coding agent web interface`

**当前状态**

`未开始`
```

- [ ] **Step 5: Align DESIGN.md with the approved in-progress milestone**

Add this exact status section before `首版不实现的功能` and remove only the
three obsolete blanket bullets that say every Web UI, SSE, and local HTTP/GUI
surface is unapproved or wholly deferred:

```markdown
## 18. 已批准、正在实施的本地 Web 里程碑

Task22–Task23 已通过 `docs/superpowers/specs/2026-08-30-local-web-gui-design.md` 的架构审批。实施顺序为：先增加仅绑定 IPv4 loopback、使用进程级 Bearer/Host/Origin 防护的 FastAPI REST/SSE 薄适配层，再增加同源、无构建步骤的本地静态 GUI。AgentRunner、SessionController、SessionEventHub、声明式 Skill、安全策略、验证门和 provider 边界保持不变。

在对应行为通过测试和用户验收前，本节只表示设计已批准，不表示 HTTP/SSE 或 GUI 已经交付。远程访问、WebSocket、账户、多用户、多活动运行、MCP、可执行 Skill 和前端框架仍不在范围内。
```

Renumber the following headings deterministically. Do not update public README
claims before behavior is GREEN.

- [ ] **Step 6: Write the pyproject metadata RED**

Change only the two existing metadata tests in `tests/test_cli.py` to the
approved expectations:

```python
def test_dependency_declarations_are_limited_to_approved_packages() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["requires-python"] == ">=3.11"
    assert metadata["project"]["dependencies"] == ["openai", "fastapi", "uvicorn"]
    assert metadata["project"]["optional-dependencies"]["test"] == ["pytest", "httpx"]
    assert metadata["build-system"]["requires"] == ["setuptools>=68"]
    assert metadata["build-system"]["build-backend"] == "setuptools.build_meta"


def test_console_scripts_and_web_assets_use_approved_entrypoints() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["scripts"] == {
        "coding-agent": "coding_agent.cli:entrypoint",
        "coding-agent-web": "coding_agent.web_cli:entrypoint",
    }
    assert metadata["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]
    assert metadata["tool"]["setuptools"]["package-data"] == {
        "coding_agent": ["web_static/*.html", "web_static/*.css", "web_static/*.js"]
    }
```

- [ ] **Step 7: Run metadata RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -k "dependency_declarations or console_scripts_and_web_assets" -q
```

Expected: exit `1`; both tests fail because `pyproject.toml` still contains only
the accepted Task 1-21 metadata. A collection or syntax error is not an accepted
RED.

- [ ] **Step 8: Add only the accepted direct dependencies and package contract**

Edit `pyproject.toml` to produce these exact logical values:

```toml
dependencies = ["openai", "fastapi", "uvicorn"]

[project.optional-dependencies]
test = ["pytest", "httpx"]

[project.scripts]
coding-agent = "coding_agent.cli:entrypoint"
coding-agent-web = "coding_agent.web_cli:entrypoint"

[tool.setuptools.package-data]
coding_agent = ["web_static/*.html", "web_static/*.css", "web_static/*.js"]
```

The entry module and resources are intentionally absent at this metadata GREEN
boundary. Do not install an SSE package, frontend framework, or browser driver.

- [ ] **Step 9: Run metadata GREEN, then install the explicitly approved dependencies**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -k "dependency_declarations or console_scripts_and_web_assets" -q
```

Expected: exit `0`; exactly the two metadata tests pass before installation.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pip check
```

Expected: both exit `0`. Record the installed FastAPI, Uvicorn, and HTTPX
versions. This is the only dependency-install step; do not add an SSE package,
frontend framework, browser driver, or transitive package as a direct project
dependency. If the package index is unavailable and the approved packages are
not cached, stop and report the dependency bootstrap blocker.

- [ ] **Step 10: Verify roadmap and dependency diff**

```powershell
.\.venv\Scripts\python.exe -c "import pathlib,tomllib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); assert d['project']['dependencies']==['openai','fastapi','uvicorn']; assert d['project']['optional-dependencies']['test']==['pytest','httpx']; assert d['project']['scripts']['coding-agent-web']=='coding_agent.web_cli:entrypoint'"
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
$active = (Select-String -Path TASKS.md -Pattern '^`进行中`$').Count
if ($active -ne 1) { throw "expected one active task, got $active" }
git diff --check
```

Expected: exit `0`; Task 21 is complete, only Task 22 is active, Task 23 is not
started, and no production behavior exists yet.

---

### Task 1: Access-token, Host, and Origin policy

**Files:**
- Create: `tests/test_web_auth.py`
- Create: `src/coding_agent/web_auth.py`

**Interfaces:**
- Consumes: raw ASGI header bytes and actual bound TCP port.
- Produces: `WebAuthorizationError`, `default_token_factory() -> str`,
  `WebAccessPolicy.generate(...)`, and `WebAccessPolicy.authorize(...)` exactly
  as specified.

- [ ] **Step 1: Write token and representation RED tests**

```python
from __future__ import annotations

import pytest


def test_policy_generates_one_hidden_process_token() -> None:
    from coding_agent.web_auth import WebAccessPolicy

    calls: list[None] = []
    policy = WebAccessPolicy.generate(
        43123,
        token_factory=lambda: calls.append(None) or "fixed-test-token",
    )

    assert calls == [None]
    assert policy.port == 43123
    assert "fixed-test-token" not in repr(policy)


@pytest.mark.parametrize("port", [True, 0, -1, 65536, 1.5, "80"])
def test_policy_rejects_invalid_port(port: object) -> None:
    from coding_agent.web_auth import WebAccessPolicy

    with pytest.raises((TypeError, ValueError)):
        WebAccessPolicy(token="fixed-test-token", port=port)  # type: ignore[arg-type]
```

- [ ] **Step 2: Run token RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_auth.py -q
```

Expected: exit nonzero because `coding_agent.web_auth` does not exist; the test
file itself imports and collects without a syntax or fixture failure.

- [ ] **Step 3: Implement the minimum immutable token policy**

Create `web_auth.py` with the approved dataclass, stable error code, exact port
checks, non-empty token validation, and:

```python
def default_token_factory() -> str:
    return secrets.token_urlsafe(32)

@classmethod
def generate(cls, port: int, *, token_factory=default_token_factory):
    if not callable(token_factory):
        raise TypeError("token_factory must be callable")
    return cls(token=token_factory(), port=port)
```

The token field uses `field(repr=False)`.

- [ ] **Step 4: Run token GREEN and Task 21 regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_auth.py tests\test_skills.py -q
```

Expected: exit `0`; record actual counts.

- [ ] **Step 5: Add exact authorization RED tests**

Add helpers and parameterized cases:

```python
TOKEN = "fixed-test-token"


def raw_headers(*pairs: tuple[str, str]) -> tuple[tuple[bytes, bytes], ...]:
    return tuple((name.lower().encode("ascii"), value.encode("ascii")) for name, value in pairs)


def valid_headers(*, origin: str | None = "http://127.0.0.1:43123"):
    pairs = [
        ("host", "127.0.0.1:43123"),
        ("authorization", f"Bearer {TOKEN}"),
    ]
    if origin is not None:
        pairs.append(("origin", origin))
    return raw_headers(*pairs)


def test_authorize_accepts_exact_ipv4_and_localhost_origins() -> None:
    from coding_agent.web_auth import WebAccessPolicy

    policy = WebAccessPolicy(token=TOKEN, port=43123)
    policy.authorize(valid_headers(), require_bearer=True)
    policy.authorize(
        raw_headers(
            ("host", "localhost:43123"),
            ("origin", "http://localhost:43123"),
            ("authorization", f"Bearer {TOKEN}"),
        ),
        require_bearer=True,
    )
    policy.authorize(valid_headers(origin=None), require_bearer=True)


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        (raw_headers(("authorization", f"Bearer {TOKEN}")), "request_forbidden"),
        (raw_headers(("host", "evil.example:43123"), ("authorization", f"Bearer {TOKEN}")), "request_forbidden"),
        (raw_headers(("host", "127.0.0.1.evil:43123"), ("authorization", f"Bearer {TOKEN}")), "request_forbidden"),
        (raw_headers(("host", "127.0.0.1:43124"), ("authorization", f"Bearer {TOKEN}")), "request_forbidden"),
        (raw_headers(("host", "127.0.0.1:43123")), "unauthorized"),
        (raw_headers(("host", "127.0.0.1:43123"), ("authorization", "Basic abc")), "unauthorized"),
        (raw_headers(("host", "127.0.0.1:43123"), ("authorization", "Bearer wrong")), "unauthorized"),
        (raw_headers(("host", "127.0.0.1:43123"), ("origin", "https://127.0.0.1:43123"), ("authorization", f"Bearer {TOKEN}")), "request_forbidden"),
    ],
)
def test_authorize_rejects_invalid_requests(headers, code: str) -> None:
    from coding_agent.web_auth import WebAccessPolicy, WebAuthorizationError

    with pytest.raises(WebAuthorizationError) as caught:
        WebAccessPolicy(token=TOKEN, port=43123).authorize(headers, require_bearer=True)
    assert caught.value.code == code
    assert TOKEN not in str(caught.value)
    assert TOKEN not in repr(caught.value)
```

Add separate duplicate Host, Origin, and Authorization cases. Add
`require_bearer=False` cases proving Host/Origin remain mandatory while an
Authorization header is neither required nor parsed for the GUI document.

- [ ] **Step 6: Run authorization RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_auth.py -q
```

Expected: exit nonzero because `authorize()` is absent or accepts an invalid
case; failure must identify the new behavior, not a bad test.

- [ ] **Step 7: Implement exact raw-header authorization**

Implement helpers that collect all values by lowercase byte name, reject
counts other than one for Host and present Origin, parse Host without suffix
matching, compare exact local origins, and accept exactly one Bearer value.
Use:

```python
if not secrets.compare_digest(provided_token, self.token):
    raise WebAuthorizationError("unauthorized")
```

Do not include a supplied header value in any exception.

- [ ] **Step 8: Run authorization GREEN and security regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_auth.py tests\test_path_safety.py tests\test_command_safety.py tests\test_skills.py -q
```

Expected: exit `0`; all exact security cases and existing safety tests pass.

---

### Task 2: FastAPI shell, strict request boundary, and stable errors

**Files:**
- Create: `tests/web_support.py`
- Create: `tests/test_web_api.py`
- Create: `src/coding_agent/web.py`

**Interfaces:**
- Consumes: injected `SessionController`, `WebAccessPolicy`, raw ASGI requests.
- Produces: `create_web_app(*, controller, access_policy, gui_root=None) -> FastAPI`.

- [ ] **Step 1: Add deterministic ASGI and controller test support**

`tests/web_support.py` must define fixed lowercase 32-hex IDs, UTC timestamps,
record factories using the real Task 19 dataclasses, and a strict controller
double whose methods record calls. It must not import provider modules or read
credentials. The ASGI helper is:

```python
@dataclass
class RecordingController:
    sessions: tuple[SessionRecord, ...] = ()
    session_view: SessionView | None = None
    skill_view: SkillCatalogView = field(
        default_factory=lambda: SkillCatalogView((), (), True)
    )
    selected_skill_ids: tuple[str, ...] = ()
    create_handle: RunHandle = field(
        default_factory=lambda: RunHandle(SESSION_ID, RUN_ID)
    )
    follow_up_handle: RunHandle = field(
        default_factory=lambda: RunHandle(SESSION_ID, SECOND_RUN_ID)
    )
    cancellation_result: CancellationResult = CancellationResult.REQUESTED
    update_batches: deque[SessionUpdateBatch] = field(default_factory=deque)
    errors: dict[str, RuntimeError] = field(default_factory=dict)
    calls: list[tuple[object, ...]] = field(default_factory=list)

    def list_sessions(self, *, limit: int = 50) -> tuple[SessionRecord, ...]: ...
    def create_session(self, message: str, *, skill_ids: tuple[str, ...] = ()) -> RunHandle: ...
    def get_session(self, session_id: str) -> SessionView: ...
    def submit_message(self, session_id: str, message: str) -> RunHandle: ...
    def list_skills(self) -> SkillCatalogView: ...
    def get_session_skills(self, session_id: str) -> tuple[str, ...]: ...
    def set_session_skills(self, session_id: str, skill_ids: tuple[str, ...]) -> tuple[str, ...]: ...
    def cancel(self, run_id: str) -> CancellationResult: ...
    def read_updates(self, run_id: str, *, after_sequence: int = 0) -> SessionUpdateBatch: ...
    def wait_for_updates(self, run_id: str, *, after_sequence: int, timeout_seconds: float) -> SessionUpdateBatch: ...


async def request(app, method: str, path: str, *, json=None, content=None, headers=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:43123",
    ) as client:
        return await client.request(method, path, json=json, content=content, headers=headers)


def auth_headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer fixed-test-token",
        "Origin": "http://127.0.0.1:43123",
    }
```

HTTPX supplies the exact Host from `base_url`.

- [ ] **Step 2: Write health/auth/error RED tests**

```python
def test_health_requires_auth_and_returns_exact_schema() -> None:
    controller = RecordingController()
    app = create_web_app(
        controller=controller,
        access_policy=WebAccessPolicy(token="fixed-test-token", port=43123),
    )

    denied = asyncio.run(request(app, "GET", "/api/v1/health"))
    allowed = asyncio.run(request(app, "GET", "/api/v1/health", headers=auth_headers()))

    assert denied.status_code == 401
    assert denied.json() == {"error": {"code": "unauthorized"}}
    assert allowed.status_code == 200
    assert allowed.json() == {"schema_version": 1, "status": "ok"}
    assert allowed.headers["cache-control"] == "no-store"
```

Add a controller method configured to raise `RuntimeError("private path D:\\x")`
and assert the response is exactly `500/internal_server_error`, with no raw
text in body, headers, captured stderr, or repr.

- [ ] **Step 3: Run Web shell RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_api.py -q
```

Expected: exit nonzero because `coding_agent.web` does not exist.

- [ ] **Step 4: Implement app factory, auth middleware, and stable errors**

Create the FastAPI app with OpenAPI docs disabled (`docs_url=None`,
`redoc_url=None`, `openapi_url=None`). Add one middleware path that:

- enforces Host/Origin on every request;
- requires Bearer for `/api/v1`;
- uses `require_bearer=False` only for future GUI resources;
- adds `Cache-Control: no-store` to API responses;
- re-raises `KeyboardInterrupt` and `SystemExit`;
- maps ordinary exceptions to the fixed JSON envelope.

Add only the authenticated health route for the first GREEN.

- [ ] **Step 5: Run Web shell GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_auth.py tests\test_web_api.py -q
```

Expected: exit `0`; record actual counts.

- [ ] **Step 6: Add strict DTO, media type, and byte-limit RED tests**

Parameterize `POST /api/v1/sessions` requests over missing fields, extra fields, wrong
types, bool values, duplicate JSON fields if the selected parser exposes them,
non-JSON media types, malformed JSON, exact 131,072-byte accepted body, and
131,073-byte rejected body. Include a custom ASGI call that sends body chunks
without Content-Length. The rejection assertion is:

```python
assert response.status_code == 413
assert response.json() == {"error": {"code": "request_too_large"}}
assert controller.calls == []
```

The accepted exact-boundary payload must be structurally valid; calculate its
message padding from `json.dumps(..., separators=(",", ":"), ensure_ascii=False).encode()`.

- [ ] **Step 7: Run request-boundary RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_api.py -k "request or media or body" -q
```

Expected: exit nonzero because strict DTOs and bounded receive are missing.

- [ ] **Step 8: Implement strict DTOs and bounded ASGI receive**

Define private models using `ConfigDict(extra="forbid", strict=True)`:

```python
class _CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: StrictStr
    skill_ids: tuple[StrictStr, ...] = ()

class _FollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: StrictStr

class _SkillSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    skill_ids: tuple[StrictStr, ...]
```

Implement a pure ASGI body-limit wrapper that totals each `http.request` body
chunk before forwarding it. Return `413` once and drain/discard remaining
request chunks without invoking FastAPI routing. Require JSON on mutation
routes. Convert FastAPI/Pydantic validation output to only `invalid_request`.
Add only `POST /api/v1/sessions` as the public boundary test surface; delegate
to `controller.create_session(message, skill_ids=...)` and return its two IDs
with status `201`. The remaining session routes stay absent until Task 3.

- [ ] **Step 9: Run request-boundary GREEN and regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_api.py tests\test_session.py tests\test_session_controller.py -q
```

Expected: exit `0`; exact and streamed byte limits pass without controller
side effects.

---

### Task 3: REST session, Skill, cancellation, and safe projection routes

**Files:**
- Modify: `tests/web_support.py`
- Modify: `tests/test_web_api.py`
- Modify: `src/coding_agent/web.py`

**Interfaces:**
- Consumes: the accepted `SessionController` methods without signature changes.
- Produces: all Task 22 non-SSE `/api/v1` routes and explicit allowlist serializers.

- [ ] **Step 1: Write session route RED tests**

Keep the Task 2 create-session test as a regression. Use real `SessionRecord`,
`SessionRunRecord`, and `SessionEvent` values from `web_support`. Add exact
response dictionaries and controller-call assertions for the still-missing
list, detail, and follow-up routes:

```python
assert follow_up.status_code == 202
assert follow_up.json() == {"session_id": SESSION_ID, "run_id": SECOND_RUN_ID}
```

Add exact tests for `GET /api/v1/sessions`,
`GET /api/v1/sessions/{session_id}`, stable list order,
the `limit` boundaries accepted by the existing controller, and session detail
projection. Assert forbidden keys are absent recursively:

```python
forbidden = {
    "instructions", "api_key", "authorization", "continuation_items",
    "completion", "stdout", "stderr", "environment",
}
assert not forbidden.intersection(all_json_keys(response.json()))
```

- [ ] **Step 2: Run session route RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_api.py -k "session" -q
```

Expected: exit nonzero because list, detail, and follow-up routes do not exist;
the Task 2 create-session regression remains GREEN.

- [ ] **Step 3: Implement explicit session serializers and routes**

Write separate private serializers for `SessionRecord`, `SessionRunRecord`, and
`SessionEvent`; do not use `dataclasses.asdict()`. Enum values become strings,
safe JSON fields are copied, and no unknown dataclass field is automatically
included. Add the four session routes and pass tuple Skill IDs unchanged.

- [ ] **Step 4: Run session route GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_api.py -k "session" -q
```

Expected: exit `0`; exact projections and call records pass.

- [ ] **Step 5: Write Skill and cancellation RED tests**

Use the real `SkillDescriptor`, `SkillCatalogDiagnostic`, `SkillCatalogView`,
and `CancellationResult`. Assert exact descriptor metadata, diagnostic order,
selected ID order for `GET /api/v1/skills`,
`GET /api/v1/sessions/{session_id}/skills`, and
`PUT /api/v1/sessions/{session_id}/skills`. Exercise cancellation through
`POST /api/v1/runs/{run_id}/cancel` and assert:

```python
assert cancelled.status_code == 200
assert cancelled.json() == {"result": "requested"}
assert controller.calls[-1] == ("cancel", RUN_ID)
```

Parameterize `requested`, `already_requested`, and `already_finished`. Assert
no Skill response key contains the private body sentinel stored only in the
test controller.

- [ ] **Step 6: Run Skill/cancel RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_api.py -k "skill or cancel" -q
```

Expected: exit nonzero because the routes do not exist.

- [ ] **Step 7: Implement Skill and cancellation routes**

Serialize only `skill_id`, `name`, `description`, `source`, `sha256`, and
`char_count`; diagnostics expose only `code`, `source`, and `entry_name`.
Return the controller cancellation enum value without inventing a second
status model.

- [ ] **Step 8: Write and run stable domain-error mapping RED/GREEN**

Parameterize every controller code actually reachable from these routes. The
test table contains exact `(code, status)` rows and asserts the fixed envelope.
At minimum include:

```python
EXPECTED = {
    "invalid_message": 400,
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
}
```

RED command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_api.py -k "error_mapping" -q
```

Implement one exact lookup with a safe default, then run the same command for
GREEN followed by:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_api.py tests\test_session.py tests\test_session_store.py tests\test_session_controller.py tests\test_skills.py -q
```

Expected: all commands exit `0`; record actual counts.

---

### Task 4: Ordered bounded SSE transport

**Files:**
- Create: `tests/test_web_sse.py`
- Modify: `tests/web_support.py`
- Modify: `src/coding_agent/web.py`

**Interfaces:**
- Consumes: `SessionController.read_updates(run_id, after_sequence=...)` and
  `wait_for_updates(run_id, after_sequence=..., timeout_seconds=...)`.
- Produces: `GET /api/v1/runs/{run_id}/events`, exact SSE frames, one private
  process/run connection limiter, and finite iterator cleanup.

- [ ] **Step 1: Write finite replay and terminal RED tests**

Construct real `SessionUpdate` objects with ordered sequence values and a final
`RUN_FINISHED`. The controller returns one `SessionUpdateBatch`. Through HTTPX,
assert exact body bytes:

```python
expected = (
    f"id: 1\nevent: run_started\ndata: {started.to_json()}\n\n"
    f"id: 2\nevent: run_finished\ndata: {finished.to_json()}\n\n"
)
assert response.status_code == 200
assert response.text == expected
assert response.headers["content-type"].startswith("text/event-stream")
assert response.headers["cache-control"] == "no-store"
assert response.headers["x-accel-buffering"] == "no"
```

Assert `Last-Event-ID: 1` passes `after_sequence=1` and only event 2 is emitted.

- [ ] **Step 2: Run replay RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_sse.py -k "replay or terminal" -q
```

Expected: exit nonzero because the route is absent.

- [ ] **Step 3: Implement cursor parser and finite SSE iterator**

Parse the raw header with one-value enforcement and ASCII decimal validation.
Call `read_updates()` first, yield each event in order, and close immediately
after `SessionUpdateKind.RUN_FINISHED`. Use only `SessionUpdate.to_json()` for
data.

- [ ] **Step 4: Run replay GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_sse.py -k "replay or terminal" -q
```

Expected: exit `0`.

- [ ] **Step 5: Add cursor/reset/heartbeat RED tests**

Parameterize duplicate, negative, signed, whitespace, non-ASCII, and
ahead-of-latest cursors for exact `400 invalid_event_cursor`. Make a controller
return `reset_required=True` and assert the stream is exactly:

```text
event: reset_required
data: {"last_sequence":42,"run_id":"<fixed-run-id>"}

```

with sorted compact JSON and no retained suffix. For heartbeat, inject a
controller that returns an empty initial batch, then an empty wait batch, then
a terminal batch. Assert one `: keep-alive\n\n` between them and every wait uses
`timeout_seconds=15.0`.

- [ ] **Step 6: Run cursor/reset/heartbeat RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_sse.py -k "cursor or reset or heartbeat" -q
```

Expected: exit nonzero for the first missing behavior.

- [ ] **Step 7: Implement reset and wait loop**

On reset, emit the fixed control event and return. Otherwise emit events,
update the local cursor, and call `wait_for_updates()` after an empty batch. An
empty wait result produces exactly one heartbeat. Do not add a sequence to a
heartbeat.

- [ ] **Step 8: Add direct generator/limiter RED tests and a real-loopback harness**

Do not use HTTPX `ASGITransport` for an unbounded response: it waits for
`response_complete` and cannot observe an open SSE stream. Test the real sync
SSE generator directly for started-stream failures and `close()` cleanup. Test
the real limiter through acquire/release behavior rather than source text:

```python
limiter = _SseConnectionLimiter(max_connections=4, max_per_run=2)
first = limiter.acquire(RUN_ID)
second = limiter.acquire(RUN_ID)
with pytest.raises(WebStreamLimitError) as caught:
    limiter.acquire(RUN_ID)
assert caught.value.code == "stream_limit_reached"
second.close()
third = limiter.acquire(RUN_ID)
third.close()
first.close()
```

Add `running_uvicorn_app(app)` to `tests/web_support.py`. It pre-binds an
actual `127.0.0.1:0` socket, runs a test-only `uvicorn.Server` subclass in a
non-daemon thread, signals a `threading.Event` after `startup()` completes,
yields the real HTTP base URL, then sets `should_exit`, joins with a finite
deadline, and closes the socket. A failed readiness or join assertion fails the
test; it never uses an arbitrary sleep.

Use that harness plus a blocking controller and real HTTPX network streams to
verify:

- closing the client response, then releasing the controller wait boundary,
  closes the generator and permits another stream;
- no controller `cancel()` call occurs;
- the fifth process-wide connection returns `429 stream_limit_reached`;
- the third connection for one run returns the same `429`;
- no request leaves loopback.

Directly drive the generator to verify an ordinary controller error after one
emitted frame yields one fixed `transport_error` event with no exception
sentinel and closes, while `KeyboardInterrupt` and `SystemExit` are not
converted.

- [ ] **Step 9: Run disconnect/cap RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_sse.py -k "disconnect or limit or stream_error or base_exception" -q
```

Expected: exit nonzero because permits, generator cleanup, and the route cap are
missing. The command must finish; an ASGITransport hang is a test defect.

- [ ] **Step 10: Implement finite connection ownership**

Add a private lock-protected limiter with four global and two per-run permits.
Acquire before returning `StreamingResponse`; release in the generator's
`finally`. Never hold its lock while reading or waiting on the controller. The
post-start ordinary-error frame has no ID and exact data
`{"code":"stream_unavailable"}`.

- [ ] **Step 11: Run all SSE GREEN and Task 20 event regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_sse.py tests\test_session_events.py tests\test_session_controller.py -q
```

Expected: exit `0`; zero skipped SSE tests; record actual counts.

---

### Task 5: Separate Web CLI, loopback server, and cleanup

**Files:**
- Create: `tests/test_web_cli.py`
- Create: `src/coding_agent/web_cli.py`
- Modify only for finalized imports: `src/coding_agent/web.py`

**Interfaces:**
- Consumes: existing `load_run_config`, `AgentSessionRunExecutor`,
  `SessionController.open`, `create_web_app`, and Uvicorn.
- Produces: `WebApplication`, `build_web_parser`, `main`,
  `run_web_application`, and `entrypoint` with the approved signatures.

- [ ] **Step 1: Write parser and injected-application RED tests**

Mirror the existing CLI testing style. Assert no positional task and exact
accepted options. The injected application test records:

```python
assert observed == {
    "task": "local web session",
    "workspace": tmp_path.resolve(),
    "model": "test-model",
    "api_mode": ApiMode.RESPONSES,
    "base_url": None,
    "port": 0,
    "open_browser": True,
}
```

Assert `--no-open-browser` changes only that boolean. Parameterize explicit
ports 1 and 65535 as accepted and bool-like, zero, negative, 65536, and text as
parser exit `2`. Reuse fake environment credentials without printing them.

- [ ] **Step 2: Run parser RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_cli.py -k "parser or injected" -q
```

Expected: exit nonzero because `web_cli.py` does not exist.

- [ ] **Step 3: Implement parser and config reuse**

Create a separate parser named `coding-agent-web`. Call existing
`load_run_config(task="local web session", ...)`. Preserve its Responses and
Chat Completions credential/base URL/verify rules. Do not add host, token,
remote, reload, or worker options.

- [ ] **Step 4: Run parser GREEN and existing CLI regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_cli.py tests\test_cli.py -q
```

Expected: exit `0`; existing `coding-agent` behavior is unchanged.

- [ ] **Step 5: Write socket and lifecycle RED tests**

Patch only private production factories in `web_cli` with recording doubles.
Assert acquisition order:

```python
assert events == [
    "socket:create", "socket:bind:127.0.0.1:0", "socket:listen",
    "policy:generate:<assigned-port>", "controller:open",
    "app:create", "server:create", "server:run",
    "controller:shutdown:5.0", "socket:close",
]
```

Assert the Uvicorn configuration has one process, no access log, no server
header, no proxy trust, no reload, and uses the pre-bound socket. Add each
startup failure point and assert reverse cleanup exactly once, stable stderr,
nonzero exit, no token/key/path/exception sentinel, and no browser call at the
Task 22 checkpoint.

Add a real cooperative-shutdown sequence where `shutdown()` returns
`False, False, True`. Assert three calls each use `timeout_seconds=5.0`, stderr
contains exactly one fixed `warning: shutdown_pending`, the socket closes only
after the `True` result, and the code never force-stops or daemonizes the worker.

Add `KeyboardInterrupt` during server run: cooperative controller shutdown and
socket close finish before the stable interrupted exit. Add `SystemExit`:
cooperative cleanup finishes in `finally`, then the same `SystemExit`
propagates. These tests do not claim a hard upper bound when an admitted Agent
operation has not returned.

- [ ] **Step 6: Run lifecycle RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_cli.py -k "socket or lifecycle or cleanup or interrupt" -q
```

Expected: exit nonzero because production composition is missing.

- [ ] **Step 7: Implement pre-bound loopback composition**

Use `socket.socket(AF_INET, SOCK_STREAM)`, Windows `SO_EXCLUSIVEADDRUSE` when
available, `bind(("127.0.0.1", port))`, and `listen()`. Never set
`SO_REUSEADDR`. Construct sensitive values with API key and Web token. Create:

```python
executor = AgentSessionRunExecutor(config)
controller = SessionController.open(
    config.workspace,
    executor,
    sensitive_values=(config.api_key, policy.token),
)
app = create_web_app(controller=controller, access_policy=policy)
```

Pass the socket to one Uvicorn `Server`. Print only
`Local coding agent: http://127.0.0.1:<port>/`. Implement exact reverse cleanup
and fixed public error strings. Repeatedly call
`controller.shutdown(timeout_seconds=5.0)` until it returns true; emit the fixed
`warning: shutdown_pending` at most once. Do not release the lease early, kill
the thread, or claim finite process exit. At this checkpoint do not open a
browser because GUI resources do not exist.

- [ ] **Step 8: Run CLI GREEN and installation import checks**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_cli.py tests\test_web_auth.py tests\test_web_api.py tests\test_web_sse.py -q
.\.venv\Scripts\python.exe -c "import coding_agent.web_auth,coding_agent.web,coding_agent.web_cli; print('web transport imports')"
```

Expected: both exit `0`; no external request is made.

---

### Task 6: Task 22 audit, full regression, and API/authentication checkpoint

**Files:**
- Review: all Task 22 files and protected core files
- Status: keep Task 22 `进行中`; keep Task 23 `未开始`

**Interfaces:**
- Consumes: green Task 22 transport.
- Produces: fresh API/authentication evidence and a mandatory user checkpoint.

- [ ] **Step 1: Run Task 22 focused suites**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_auth.py tests\test_web_api.py tests\test_web_sse.py tests\test_web_cli.py -q
```

Expected: exit `0`, zero failed, zero skipped; record actual pass/warning count.

- [ ] **Step 2: Run Task 19-21 focused regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session.py tests\test_session_store.py tests\test_session_events.py tests\test_session_runtime.py tests\test_session_controller.py tests\test_skills.py -q
```

Expected: exit `0`; record actual counts.

- [ ] **Step 3: Run full offline and Windows acceptance**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\test_command_safety.py tests\test_session_store.py tests\test_skills.py -k "symlink or junction or reparse or workspace_lease" -q
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py -k "process_tree or timeout" -q
```

Expected: all exit `0`; the Windows reparse, lease, timeout, and process-tree
tests are collected and execute with zero permanent skip.

- [ ] **Step 4: Audit interfaces, dependencies, isolation, and secrets**

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "import inspect; from coding_agent.web import create_web_app; from coding_agent.web_auth import WebAccessPolicy; from coding_agent.web_cli import main,run_web_application; print(inspect.signature(create_web_app)); print(inspect.signature(WebAccessPolicy.authorize)); print(inspect.signature(main)); print(inspect.signature(run_web_application))"
rg -n "FastAPI|pydantic|starlette|uvicorn" src\coding_agent -g "*.py" -g "!web.py" -g "!web_cli.py" -g "!web_auth.py"
rg -n -i "api[_ -]?key|authorization|bearer|continuation|encrypted|reasoning|skill.*instructions|localhost|127\.0\.0\.1" src\coding_agent\web*.py tests\test_web*.py
rg -n "0\.0\.0\.0|::|SO_REUSEADDR|allow_origins.*\*|EventSource|WebSocket|previous_response_id|conversation" src\coding_agent\web*.py
rg -n "langchain|llamaindex|autogen|crewai|agents sdk|agent sdk" pyproject.toml src tests
```

Expected: `pip check` passes; Web-framework matches outside Web files are absent
or existing documentation-only references; every sensitive-term match is
manually classified as a negative test, header name, or scrub rule; no secret
literal, wildcard listener/CORS, provider state, or Agent framework appears.

- [ ] **Step 5: Scan suppressions, artifacts, whitespace, and full diff**

```powershell
rg -n "pytest\.skip|pytest\.xfail|@pytest\.mark\.skip|@pytest\.mark\.xfail" tests
rg -n "pass\s*(#.*)?$|NotImplementedError" src\coding_agent\web*.py
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff -- TASKS.md pyproject.toml src/coding_agent/web_auth.py src/coding_agent/web.py src/coding_agent/web_cli.py tests/web_support.py tests/test_web_auth.py tests/test_web_api.py tests/test_web_sse.py tests/test_web_cli.py
```

Expected: no new suppression, unfinished production path, cache artifact,
whitespace error, protected-core diff, or unrelated change.

- [ ] **Step 6: Stop at the Task 22 checkpoint**

Report every RED/GREEN command and actual result, focused/full/Windows counts,
API matrix, auth matrix, SSE matrix, dependency/secret/scope audit, file list,
diff stat, and status. Keep Task 22 active. Do not start Task 23 until the user
explicitly accepts this checkpoint.

---

### Task 7: Activate Task 23 and add secure packaged GUI bootstrap

**Files:**
- Modify: `TASKS.md`
- Create: `src/coding_agent/web_static/index.html`
- Create: `src/coding_agent/web_static/app.js`
- Create: `src/coding_agent/web_static/styles.css`
- Create: `tests/test_web_gui.py`
- Modify: `src/coding_agent/web.py`
- Modify: `src/coding_agent/web_cli.py`

**Interfaces:**
- Consumes: accepted Task 22 app, policy, CLI, and package-data declaration.
- Produces: uncached same-origin document bootstrap and installed static assets;
  Task 22 complete and exactly Task 23 active.

- [ ] **Step 1: Reconfirm accepted checkpoint and activate Task 23**

```powershell
git status --short --untracked-files=all
git diff --check
.\.venv\Scripts\python.exe -m pytest tests\test_web_auth.py tests\test_web_api.py tests\test_web_sse.py tests\test_web_cli.py -q
```

After GREEN, change only Task 22 to `已完成` and Task 23 to `进行中`. Assert
exactly one active task.

- [ ] **Step 2: Write static resource and bootstrap RED tests**

Use `importlib.resources.files("coding_agent").joinpath("web_static")`. Assert
all three files exist after implementation. Call `/` without Bearer but with
valid Host and Origin and assert:

```python
assert response.status_code == 200
assert response.headers["cache-control"] == "no-store"
assert response.headers["referrer-policy"] == "no-referrer"
assert response.headers["x-content-type-options"] == "nosniff"
assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
assert response.text.count("fixed-test-token") == 1
assert "__CODING_AGENT_ACCESS_TOKEN__" not in response.text
```

Assert invalid Host/Origin is rejected. Assert `/app.js` and `/styles.css` have
exact JS/CSS media types, no-store, nosniff, and never contain the token.

- [ ] **Step 3: Run bootstrap RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_gui.py -k "resource or bootstrap or header" -q
```

Expected: exit nonzero because GUI resources/routes are absent.

- [ ] **Step 4: Implement exact resource routes and token replacement**

Create minimal valid files. `index.html` contains exactly one marker in:

```html
<meta id="coding-agent-bootstrap" name="coding-agent-token"
      content="__CODING_AGENT_ACCESS_TOKEN__">
```

Read package files with `Traversable.read_text(encoding="utf-8")`. Verify the
marker count is exactly one before `html.escape(token, quote=True)` replacement;
otherwise return a fixed internal error. Serve explicit media types and the
approved security headers. Do not use `StaticFiles` directory traversal.

- [ ] **Step 5: Run bootstrap GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_gui.py -k "resource or bootstrap or header" -q
```

Expected: exit `0`.

- [ ] **Step 6: Add browser-opening RED/GREEN**

Extend `test_web_cli.py` with injected browser and server-ready hooks. Assert
the browser receives only `http://127.0.0.1:<port>/`, after socket/server
readiness and before blocking run; token is not in the URL. Assert
`--no-open-browser` makes zero calls. An injected `OSError` from the browser
produces exactly `warning: unable to open local browser` while the server still
runs and exits normally.

RED then GREEN commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_cli.py -k "browser" -q
.\.venv\Scripts\python.exe -m pytest tests\test_web_cli.py -k "browser" -q
```

The first must fail for missing browser behavior; the second must pass after
the minimum implementation.

---

### Task 8: Semantic warm-light GUI shell and safe rendering

**Files:**
- Modify: `src/coding_agent/web_static/index.html`
- Modify: `src/coding_agent/web_static/styles.css`
- Modify: `src/coding_agent/web_static/app.js`
- Modify: `tests/test_web_gui.py`
- Create: `tests/js/dom_harness.mjs`
- Create: `tests/js/web_gui.test.mjs`

**Interfaces:**
- Consumes: in-memory bootstrap token and `/api/v1` routes.
- Produces: the exact DOM landmarks and a safe text/activity renderer.

- [ ] **Step 1: Write semantic layout and accessibility RED tests**

Parse HTML with `html.parser.HTMLParser` and assert unique IDs:

```python
REQUIRED_IDS = {
    "session-sidebar", "new-session-button", "session-list",
    "skill-list", "conversation-title", "run-status", "run-phase",
    "run-elapsed", "cancel-run-button", "conversation-log",
    "message-composer", "message-input", "send-message-button",
    "connection-status", "coding-agent-bootstrap",
}
```

Assert semantic `nav`, `main`, `header`, `ol`, `form`, buttons with explicit
types, labels, an `aria-live="polite"` connection/status region, and keyboard
reachable controls. Assert no inline event attributes.

CSS source assertions require exact custom properties for background, surface,
ink, accent, success, running, failure, border, and shadow; a 260px sidebar;
central `minmax(0, 1fr)`; sticky header/composer; responsive drawer breakpoint;
focus-visible styles; and reduced-motion handling. Assert no `#000`, pure black
background, external URL, or remote font.

- [ ] **Step 2: Run layout RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_gui.py -k "layout or accessibility or palette or responsive" -q
```

Expected: exit nonzero because the minimal resource shell lacks approved layout.

- [ ] **Step 3: Implement semantic HTML and full approved CSS**

Build the two-column desktop structure and narrow drawer. Use warm ivory tokens,
system fonts, inline SVG icons, no right rail, and central activity cards. Add
empty-state copy that accurately says the Agent may read, modify, and run
authorized commands in the selected workspace.

- [ ] **Step 4: Run layout GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_gui.py -k "layout or accessibility or palette or responsive" -q
```

Expected: exit `0`.

- [ ] **Step 5: Write executable safe-renderer RED tests**

`tests/js/dom_harness.mjs` implements only the observable DOM used by the GUI:
`createElement`, `createTextNode`, `append`, `replaceChildren`, `remove`,
`setAttribute`, `textContent`, child order, event listeners, dispatch, disabled,
value, dataset, and class-list behavior. It records element and text nodes as a
tree and deliberately provides no HTML parser or `innerHTML`.

`tests/js/web_gui.test.mjs` reads the real packaged `app.js` and imports it from
a `data:text/javascript;base64,...` module URL, so Node executes the exact file
without `package.json` or a copy. Write behavior tests:

```javascript
test("model markup remains text and cannot create an element", () => {
  const document = new TestDocument();
  const container = document.createElement("section");
  gui.appendMessage(container, "assistant", '<img src=x onerror="secret()">');
  assert.equal(container.textContent, '<img src=x onerror="secret()">');
  assert.deepEqual(findElements(container, "img"), []);
});

test("closed fenced code creates explicit pre and code nodes", () => {
  const document = new TestDocument();
  const container = document.createElement("section");
  gui.appendMessage(container, "assistant", "before\n```py\nprint(1)\n```\nafter");
  assert.equal(findElements(container, "pre").length, 1);
  assert.equal(findElements(container, "code")[0].textContent, "print(1)\n");
});

test("unknown activity never serializes unrecognized data", () => {
  const document = new TestDocument();
  const container = document.createElement("section");
  gui.appendActivity(container, "future_kind", { private: "must-not-render" });
  assert.equal(container.textContent.includes("must-not-render"), false);
});
```

Add bootstrap behavior proving the meta token is read once, the node is
removed, and the returned client keeps it only in closure state. Keep a
separate Python security audit that rejects persistent storage APIs, unsafe HTML
sinks, external URLs/assets, WebSocket, native EventSource, and frontend
framework imports; that audit supplements rather than replaces executable
behavior tests.

- [ ] **Step 6: Run renderer RED**

```powershell
node --test tests\js\web_gui.test.mjs
```

Expected: exit `1` because the real module lacks the exported renderer and
bootstrap behavior; module loading itself succeeds without a browser global.

- [ ] **Step 7: Implement deterministic safe rendering**

Export explicit browser-independent functions:

```javascript
export function appendPlainText(document, parent, text) { /* createTextNode only */ }
export function appendMessage(document, container, role, text) { /* explicit elements */ }
export function appendActivity(document, container, kind, data) { /* allowlisted fields */ }
export function renderRunHeader(document, elements, run, phase) { /* server state only */ }
```

Implement fenced-code splitting using string indexes and element creation; an
unclosed fence remains plain text. Unknown activity kinds display only their
safe kind label, not serialized data. Browser startup is guarded by
`typeof window !== "undefined" && typeof document !== "undefined"`, allowing
the same module to execute in Node without browser shims.

- [ ] **Step 8: Run renderer GREEN and resource suite**

```powershell
node --test tests\js\web_gui.test.mjs
.\.venv\Scripts\python.exe -m pytest tests\test_web_gui.py -q
```

Expected: both exit `0`; report Node and pytest counts separately.

---

### Task 9: GUI API state, sessions, Skills, cancellation, and SSE recovery

**Files:**
- Modify: `src/coding_agent/web_static/app.js`
- Modify: `src/coding_agent/web_static/index.html`
- Modify: `tests/test_web_gui.py`
- Modify: `tests/js/dom_harness.mjs`
- Modify: `tests/js/web_gui.test.mjs`
- Create: `tests/manual_web_fixture.py`

**Interfaces:**
- Consumes: exact Task 22 routes and SSE frames.
- Produces: one in-memory client state, one selected session, at most one active
  fetch stream, deterministic reconnect, and complete GUI actions.

- [ ] **Step 1: Write executable API-client and state RED tests**

Use an injected `fetchImpl` that records actual `Request` inputs and returns
real Node `Response` objects. Test `createApiClient({fetchImpl, accessToken})`
through its public operations:

```javascript
test("list sessions authenticates without placing token in the URL", async () => {
  const calls = [];
  const api = gui.createApiClient({
    accessToken: "fixed-test-token",
    fetchImpl: async (request) => {
      calls.push(request);
      return Response.json({ sessions: [] });
    },
  });
  assert.deepEqual(await api.listSessions(), { sessions: [] });
  assert.equal(calls[0].url, "http://local.invalid/api/v1/sessions?limit=50");
  assert.equal(calls[0].headers.get("authorization"), "Bearer fixed-test-token");
  assert.equal(calls[0].url.includes("fixed-test-token"), false);
});
```

Add observable tests for create, follow-up, Skill selection, and cancellation:
exact method/body/header; one fetch attempt on a `500`; and only stable error
code exposure. Test `createInitialUiState()` exact safe fields and mutate a
returned state to prove a new call returns an independent value. No state field
may carry credentials, provider content, continuation, reasoning, or Skill
instructions.

- [ ] **Step 2: Run API/state RED**

```powershell
node --test tests\js\web_gui.test.mjs
```

Expected: exit `1` because the client/state exports are absent.

- [ ] **Step 3: Implement exact API client and state container**

Export `createApiClient` and `createInitialUiState`. The client exposes named
methods `listSessions`, `loadSession`, `listSkills`, `createSession`,
`submitFollowUp`, `saveSkillSelection`, `cancelRun`, and `openRunStream`.
Mutations perform one request and return parsed safe JSON or a stable
`WebClientError(code)`. The browser controller, not the API client, owns control
disable/enable behavior.

- [ ] **Step 4: Write and implement executable session/Skill action RED/GREEN**

Use `TestDocument`, a recording API client, injected clock, and injected timer
functions to exercise `createUiController(...)`. Dispatch real test-harness
`click`, `submit`, and `change` events and assert the rendered tree, API calls,
state, and disabled controls. The implementation must:

- create a session with the preselected ordered Skill IDs;
- select the returned session and run;
- use follow-up for an existing idle session;
- disable send and Skill mutation whenever any loaded session is running or
  cancelling;
- keep history navigation enabled;
- display Skill metadata and diagnostics but no instruction field;
- display exact cancellation results without inventing completion.

Run before and after implementation:

```powershell
node --test tests\js\web_gui.test.mjs
```

The first run must exit `1` on missing controller behavior; after exporting and
implementing `createUiController`, the second exits `0`.

- [ ] **Step 5: Write executable fetch-SSE parser/reconnect RED tests**

Test exported `parseSseFrames`, `reduceSessionUpdate`,
`reconnectDelayForAttempt`, and `consumeRunStream`. Use hand-written literal
frames split across UTF-8 chunks and Node's real `ReadableStream`/`Response`.
Lock constants through their observable boundary:

```javascript
const RECONNECT_DELAYS_MS = Object.freeze([500, 1000, 2000, 5000]);
const TERMINAL_RUN_STATUSES = new Set(["succeeded", "failed", "interrupted"]);
```

Assert the parser preserves a partial frame, accepts complete ordered frames,
and rejects duplicate/decreasing/invalid IDs. Assert state reduction appends a
provisional delta, replaces it on confirmed text, clears it on discard, records
safe activity, and uses only the server's terminal status. Assert reconnect
attempts 0 through 6 return `500, 1000, 2000, 5000, 5000, 5000, 5000`.

Use a fake fetch returning real Responses to prove `openRunStream` sends Bearer
and Last-Event-ID, `consumeRunStream` handles reset and terminal close, abort
does not call the API cancellation method, and 401/403 return authentication
failure without scheduling a timer.

- [ ] **Step 6: Run SSE client RED**

```powershell
node --test tests\js\web_gui.test.mjs
```

Expected: exit nonzero because SSE client functions are absent.

- [ ] **Step 7: Implement one-stream SSE state projection**

Export and implement the tested pure functions. Parse only `id`, `event`, and
`data`; reject invalid/non-increasing IDs by
closing and reloading the durable snapshot. Apply provisional delta to memory,
confirmed text to the durable display, discard by clearing provisional text,
and safe lifecycle/activity kinds through explicit cases. A terminal event
updates the snapshot and stops timers. Visibility restoration reconnects only
when no active stream exists.

- [ ] **Step 8: Run GUI action/SSE GREEN and Task 22 regression**

```powershell
node --test tests\js\web_gui.test.mjs
.\.venv\Scripts\python.exe -m pytest tests\test_web_gui.py tests\test_web_api.py tests\test_web_sse.py -q
```

Expected: both exit `0`; report Node and pytest counts separately.

- [ ] **Step 9: Create deterministic manual visual fixture**

`tests/manual_web_fixture.py` imports `RecordingController`, populates sessions,
runs, messages, long text, fenced code, tool/verification cards, Skill
diagnostics, and switchable idle/running/cancelling/succeeded/failed states,
then starts the real Task 23 app on loopback with a fixed test-only token. It
prints only the local fixture URL and exits cleanly on Ctrl+C. It never imports
a provider client, reads a key, opens a workspace outside a temporary fixture,
or enters package data.

Run its import boundary:

```powershell
.\.venv\Scripts\python.exe -c "import runpy; ns=runpy.run_path('tests/manual_web_fixture.py', run_name='fixture_import'); assert 'main' in ns; print('manual fixture imports offline')"
```

Expected: exit `0` without starting a server during import.

---

### Task 10: Documentation, packaging, installed entry, and visual checkpoint

**Files:**
- Modify: `DESIGN.md`
- Modify: `README.txt`
- Modify: `README.md`
- Modify: `docs/USAGE.md`
- Modify: `docs/OPENAI_API.md`
- Modify: `tests/test_docs.py`
- Modify: `tests/test_web_gui.py`

**Interfaces:**
- Consumes: green Task 22-23 behavior.
- Produces: accurate public setup/usage/security documentation, installed
  resources, and human visual evidence.

- [ ] **Step 1: Write documentation and package RED tests**

Extend docs tests to require:

- `coding-agent-web --workspace <path>` and `--no-open-browser`;
- loopback-only, random port, Bearer, Host/Origin, and no-remote-use warning;
- session persistence, one active run, follow-up, cancellation, and Skill
  selection;
- Responses and Chat Completions configuration remains exact;
- browser closing does not cancel;
- no account, remote server, MCP, executable Skill, or parallel run claim;
- no real credential, personal absolute path, or invented repository URL.

Build a wheel and inspect its archive names for all three `web_static` files and
the `coding-agent-web` entry metadata.

- [ ] **Step 2: Run docs/package RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py tests\test_web_gui.py -k "docs or package or wheel" -q
```

Expected: exit nonzero because docs still describe transport/GUI as deferred.

- [ ] **Step 3: Update documentation with verified behavior only**

Document installation, both CLI entry points, environment variables, provider
modes, verification command, local GUI launch, random port, browser behavior,
session/Skill use, cancellation, SSE reconnect, security threat boundary,
troubleshooting, and remaining limitations. Keep README.txt within its accepted
Task 14 concise-submission contract. Do not paste token, API key, local absolute
path, or full event/output examples that exceed existing privacy rules.

- [ ] **Step 4: Run docs/package GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py tests\test_web_gui.py -q
```

Expected: exit `0`.

- [ ] **Step 5: Perform a clean local package installation check**

Build with the already configured build backend, create a fresh temporary
virtual environment, and install the wheel without resolving dependencies only
after confirming FastAPI/Uvicorn are available from the approved environment or
local cache. Then verify resource discovery and both help entries. The logical
commands are:

```powershell
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir .\.package-check
python -m venv .\.install-check
.\.install-check\Scripts\python.exe -m pip install --no-deps .\.package-check\coding_agent-0.1.0-py3-none-any.whl
.\.install-check\Scripts\python.exe -c "from importlib.resources import files; root=files('coding_agent').joinpath('web_static'); assert all(root.joinpath(n).is_file() for n in ('index.html','app.js','styles.css'))"
.\.install-check\Scripts\coding-agent.exe --help
.\.install-check\Scripts\coding-agent-web.exe --help
```

Use validated explicit repository-local artifact paths, review them, and remove
only `.package-check` and `.install-check` after checks. If the fresh venv lacks
runtime dependencies, the resource/import check remains valid and the existing
main venv performs the live help/import check; report that limitation rather
than accessing the network silently.

- [ ] **Step 6: Run the offline manual visual fixture and inspect approved states**

Start:

```powershell
.\.venv\Scripts\python.exe tests\manual_web_fixture.py
```

Inspect in the local browser at 1280x720, 1440x900, and a narrow viewport.
Record observed results for sidebar, central width, fixed run header, elapsed
time, composer, session switching, Skill selector, provisional cursor, long
text, fenced code, tool/verification cards, reconnect state, cancel state,
success, failure, keyboard focus, contrast, and reduced motion. This is a human
checkpoint; do not report it as an automated test.

After inspection, stop the fixture and confirm no process or temporary database
remains.

---

### Task 11: Final Milestone C verification and user stop

**Files:**
- Review: every modified/new file in this plan
- Status: keep Task 23 `进行中`

**Interfaces:**
- Consumes: green Task 22/23 behavior and completed visual checkpoint.
- Produces: fresh final acceptance matrix and no automatic Git operation.

- [ ] **Step 1: Run all Web focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_auth.py tests\test_web_api.py tests\test_web_sse.py tests\test_web_cli.py tests\test_web_gui.py tests\test_docs.py -q
node --test tests\js\web_gui.test.mjs
```

Expected: both commands exit `0`; record Python and Node passed, failed,
skipped, and warning counts separately.

- [ ] **Step 2: Run Task 16-21 interaction regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_instructions.py tests\test_streaming.py tests\test_openai_streaming_client.py tests\test_chat_completions_streaming_client.py tests\test_session.py tests\test_session_store.py tests\test_session_events.py tests\test_session_runtime.py tests\test_session_controller.py tests\test_skills.py -q
```

Expected: exit `0`; streaming, sessions, follow-up, cancellation, and Skills
remain green.

- [ ] **Step 3: Run complete repository and Windows specialist suites**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\test_command_safety.py tests\test_session_store.py tests\test_skills.py -k "symlink or junction or reparse or workspace_lease" -q
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py -k "process_tree or timeout" -q
```

Expected: every command exits `0`; no required Windows case is skipped.

- [ ] **Step 4: Verify public signatures and provider-neutral boundaries**

```powershell
.\.venv\Scripts\python.exe -c "import inspect; from coding_agent.model import ModelClient; from coding_agent.session_controller import SessionController; from coding_agent.web import create_web_app; from coding_agent.web_auth import WebAccessPolicy; from coding_agent.web_cli import main,run_web_application; print(inspect.signature(ModelClient.complete)); print(inspect.signature(SessionController.create_session)); print(inspect.signature(SessionController.submit_message)); print(inspect.signature(create_web_app)); print(inspect.signature(WebAccessPolicy.authorize)); print(inspect.signature(main)); print(inspect.signature(run_web_application))"
rg -n "FastAPI|pydantic|starlette|uvicorn|Request|Response" src\coding_agent -g "*.py" -g "!web.py" -g "!web_cli.py" -g "!web_auth.py"
rg -n "openai|ChatCompletion|ResponseOutput" src\coding_agent\web*.py
```

Expected: accepted core signatures are unchanged; Web-framework and SDK types
do not cross their boundaries.

- [ ] **Step 5: Run dependency, secret, privacy, and prohibited-scope audits**

```powershell
.\.venv\Scripts\python.exe -m pip check
rg -n -i "sk-[A-Za-z0-9]|api[_ -]?key\s*[:=]\s*['\"][^'\"]+|authorization:\s*bearer\s+[A-Za-z0-9]" . -g "!*.sqlite3" -g "!*.db"
rg -n -i "C:\\Users\\|D:\\code\\|/home/|/Users/" README.txt README.md DESIGN.md docs src tests
rg -n "localStorage|sessionStorage|indexedDB|document\.cookie|innerHTML|outerHTML|insertAdjacentHTML|eval\(|new Function|WebSocket|EventSource" src\coding_agent\web_static
rg -n "0\.0\.0\.0|SO_REUSEADDR|allow_origins.*\*|previous_response_id|conversation|continuation|encrypted.*reasoning" src\coding_agent\web*.py src\coding_agent\web_static
rg -n "langchain|llamaindex|autogen|crewai|agents sdk|agent sdk" pyproject.toml src tests
```

Expected: `pip check` exits `0`; every match is classified. No real credential,
personal path, unsafe browser sink, wildcard network/CORS, provider payload,
server state, Agent framework, MCP, executable Skill, account, remote access,
or parallel-run implementation exists.

- [ ] **Step 6: Scan unfinished paths, suppressions, artifacts, and package data**

```powershell
rg -n "pytest\.skip|pytest\.xfail|@pytest\.mark\.skip|@pytest\.mark\.xfail" tests
rg -n "NotImplementedError|pass\s*(#.*)?$" src\coding_agent\web*.py
.\.venv\Scripts\python.exe -c "from importlib.resources import files; root=files('coding_agent').joinpath('web_static'); print([(n,root.joinpath(n).is_file()) for n in ('index.html','app.js','styles.css')])"
Get-ChildItem -Force -Recurse -Directory | Where-Object { $_.Name -in @('__pycache__','.pytest_cache','.package-check','.install-check') } | Select-Object -ExpandProperty FullName
```

Expected: no new suppressed test or unfinished production branch; resources
exist; repository-local temporary artifacts are removed through validated
explicit paths before final status.

- [ ] **Step 7: Check whitespace, status, and complete diff**

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff
```

Print every untracked source/resource/test file in full because plain `git diff`
does not include it. Confirm the diff contains only the locked map and approved
spec/plan/docs/status changes. Confirm Task 23 is the only active task.

- [ ] **Step 8: Complete the acceptance matrix and stop**

Report fresh evidence for:

| Requirement | Evidence |
| --- | --- |
| loopback-only socket and random port | CLI socket tests and source audit |
| Bearer, Host, Origin, duplicate-header rejection | auth focused suite |
| no token/key/provider/Skill-body leak | response tests and scans |
| strict DTO and 131,072-byte body limit | API boundary tests |
| session/follow-up/Skill/cancel delegation | REST integration tests |
| single active run unchanged | controller and Web conflict tests |
| exact ordered SSE and Last-Event-ID | SSE suite |
| heartbeat, reset, disconnect, and caps | SSE suite |
| loopback startup and cooperative shutdown/lease cleanup | Web CLI lifecycle tests |
| same-origin secure token bootstrap | GUI header/resource tests |
| safe DOM rendering and no persistent token | executable Node DOM behavior tests plus supplementary source audit |
| one fetch stream and deterministic reconnect | executable Node API/SSE/controller behavior tests |
| no false SUCCESS or disconnect cancellation | GUI/API/controller tests |
| packaged assets and installed entry | wheel/install checks |
| warm responsive approved layout | documented human visual checkpoint |
| Task 1-21 regression | component and full repository suites |
| Windows reparse, lease, timeout, process tree | specialist suites |
| no deferred MCP/account/remote/parallel scope | diff and source audit |

Keep Task 23 `进行中`. Do not stage, commit, push, start MCP work, or claim the
visual result without the recorded human checkpoint. Stop for user review and
authorization.

---

## Plan self-review

- **Spec coverage:** Every approved scope, API route, authentication rule, SSE
  invariant, GUI behavior, lifecycle rule, dependency, checkpoint, and final
  audit maps to a numbered task and named test command. Browser-independent GUI
  behavior is executed with Node 20's built-in test runner; Python source scans
  remain supplementary security audits rather than functional proof.
- **Placeholder scan:** Production and test steps contain exact files, names,
  commands, failure causes, GREEN expectations, and acceptance results; no
  deferred implementation marker is used.
- **Type consistency:** `WebAccessPolicy`, `create_web_app`, `WebApplication`,
  `main`, and `run_web_application` signatures match the approved spec; later
  tasks consume the same names.
- **Boundary consistency:** No accepted core public interface changes. Web types
  remain in Web modules; provider and Skill instruction data remain private.
- **Off-by-one review:** explicit ports are 1-65535; body acceptance is exactly
  131,072 bytes and rejection starts at 131,073; SSE cursor starts at zero,
  event sequence remains positive, and global/per-run stream caps reject the
  first disallowed connection.
- **Lifecycle review:** cooperative controller shutdown reaches true before
  socket close, no hard-stop claim contradicts Task 20, disconnect never
  cancels, terminal events close streams, and only one task status is active at
  each checkpoint.
- **Scope review:** Task 22 stops before GUI, Task 23 adds only the approved GUI,
  and neither task adds MCP, executable Skills, accounts, remote access, or
  parallel Agent execution.

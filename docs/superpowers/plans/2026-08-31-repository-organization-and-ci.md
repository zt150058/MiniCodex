# Repository Organization and CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize MiniCodex production and test code by responsibility, consolidate project documentation, and add an offline Windows GitHub Actions test pipeline without changing runtime behavior.

**Architecture:** Move the current flat `coding_agent` package into seven responsibility-based subpackages and mirror those boundaries in unit tests. Preserve only the two installed command names and all runtime behavior; update imports, package resources, documentation links, and CI as one controlled migration with a green test checkpoint after each dependency-safe move batch.

**Tech Stack:** Python 3.11, setuptools, pytest, FastAPI/httpx tests, Node.js 24 built-in test runner, GitHub Actions on `windows-latest`, PowerShell.

**Spec:** `docs/superpowers/specs/2026-08-31-repository-organization-and-ci-design.md`

## Global Constraints

- Target Windows and Python 3.11 for the first version.
- Do not add production or test dependencies; approved dependencies remain `openai`, `fastapi`, `uvicorn`, `pytest`, and `httpx`.
- Do not add an Agent framework, Agent SDK, hosted file tool, or hosted execution tool.
- Preserve the `coding-agent` and `coding-agent-web` command names and all CLI, GUI, REST/SSE, SQLite, security, budget, and verification behavior.
- Do not preserve old internal Python import paths with forwarding modules.
- Keep filesystem paths workspace-confined and shell command timeout/output enforcement unchanged.
- Do not split or rewrite large modules while moving them.
- Do not modify historical files under `docs/superpowers/plans/` or earlier `docs/superpowers/specs/` merely to rewrite old import paths.
- Do not commit, push, rewrite Git history, or operate on a remote without separate explicit user authorization.
- Do not dispatch subagents unless the user explicitly chooses the subagent-driven execution option.
- Use `apply_patch` for content edits. For pure file moves, use explicit `Move-Item -LiteralPath` commands after resolving and verifying both paths are inside `D:\code\coding_agent`; never move a computed or recursive broad target.
- Every production move batch ends with focused tests, the full offline Python suite, and an old-import scan before the next batch.

## Locked File Map

The implementation must use this mapping; do not invent additional layers during execution.

| Current path | Final path |
| --- | --- |
| `src/coding_agent/app.py` | `src/coding_agent/application/app.py` |
| `src/coding_agent/config.py` | `src/coding_agent/application/config.py` |
| `src/coding_agent/cli.py` | `src/coding_agent/application/cli.py` |
| `src/coding_agent/{agent,budget,context,instructions,logging,messages,model,progress,report,run_mode,state,streaming,termination,verification}.py` | same filename under `src/coding_agent/engine/` |
| `src/coding_agent/openai_client.py` | `src/coding_agent/providers/openai_client.py` |
| `src/coding_agent/chat_completions_client.py` | `src/coding_agent/providers/chat_completions_client.py` |
| `src/coding_agent/model_catalog.py` | `src/coding_agent/providers/model_catalog.py` |
| `src/coding_agent/safety.py` | `src/coding_agent/operations/safety.py` |
| `src/coding_agent/tools/*.py` | same filename under `src/coding_agent/operations/tools/` |
| `src/coding_agent/session.py` | `src/coding_agent/sessions/session.py` |
| `src/coding_agent/session_controller.py` | `src/coding_agent/sessions/session_controller.py` |
| `src/coding_agent/session_deletion.py` | `src/coding_agent/sessions/session_deletion.py` |
| `src/coding_agent/session_events.py` | `src/coding_agent/sessions/session_events.py` |
| `src/coding_agent/session_runtime.py` | `src/coding_agent/sessions/session_runtime.py` |
| `src/coding_agent/session_store.py` | `src/coding_agent/sessions/session_store.py` |
| `src/coding_agent/skills.py` | `src/coding_agent/skills/catalog.py` |
| `src/coding_agent/skill_packages.py` | `src/coding_agent/skills/packages.py` |
| `src/coding_agent/web.py` | `src/coding_agent/web/app.py` |
| `src/coding_agent/web_auth.py` | `src/coding_agent/web/auth.py` |
| `src/coding_agent/web_cli.py` | `src/coding_agent/web/cli.py` |
| `src/coding_agent/web_static/*` | same filename under `src/coding_agent/web/static/` |
| `DESIGN.md` | `docs/project/DESIGN.md` |
| `TASKS.md` | `docs/project/TASKS.md` |
| `requirement.pdf` | `docs/project/requirement.pdf` |

The unit-test mapping is:

- `tests/application/`: `test_app.py`, `test_cli.py`, `test_docs.py`, plus new repository-layout and CI contract tests.
- `tests/engine/`: `test_agent_loop.py`, `test_budget.py`, `test_context.py`, `test_instructions.py`, `test_logging.py`, `test_messages.py`, `test_model.py`, `test_progress.py`, `test_report.py`, `test_run_mode.py`, `test_streaming.py`, `test_termination.py`, `test_verification.py`.
- `tests/providers/`: all `test_openai_*`, `test_chat_completions_*`, and `test_model_catalog.py` files.
- `tests/operations/`: `test_command_safety.py`, `test_path_safety.py`, and the four current `tests/tools/test_*_tool.py` or `test_*_tools.py` files.
- `tests/sessions/`: all `test_session*.py` files.
- `tests/skills/`: `test_skills.py` and `test_skill_packages.py`.
- `tests/web/`: all `test_web*.py` files and `web_support.py`, renamed to `support.py`.
- `tests/manual/`: `manual_web_fixture.py`.
- `tests/integration/` and `tests/js/` retain their current responsibilities.

---

### Task 1: Close the Existing Task and Establish a Verified Baseline

**Files:**
- Modify: `TASKS.md`
- Inspect: `AGENTS.md`
- Inspect: `docs/superpowers/specs/2026-08-31-post-mutation-convergence-and-transient-narration-design.md`
- Inspect: `docs/superpowers/plans/Task32.md`

**Interfaces:**
- Consumes: clean baseline commit `79ab64d` and Task 32 acceptance criteria.
- Produces: a recorded green baseline and one active Task 33 entry before any production move.

- [ ] **Step 1: Confirm the workspace and current task state**

Run:

```powershell
git status --short
git log -1 --oneline
rg -n "^## 32\.|当前状态|进行中|已完成" TASKS.md
```

Expected: no pre-existing changes except the approved design and plan documents; HEAD begins with `79ab64d`; Task 32 is the only entry still marked `进行中`.

- [ ] **Step 2: Run the complete pre-move Python baseline**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit code `0`. Record the real passed/skipped counts. If it fails, stop the reorganization and invoke `superpowers:systematic-debugging`; do not mark Task 32 complete.

- [ ] **Step 3: Run the complete pre-move Node baseline**

Run:

```powershell
node --test tests/js/web_gui.test.mjs
```

Expected: exit code `0` with no failed Node tests. If it fails, stop before moving files.

- [ ] **Step 4: Reconcile Task 32 and append Task 33**

After the baseline and Task 32 acceptance review succeed, change only Task 32's final status to `已完成`, then append this exact task shell before `## 任务完成规则`:

```markdown
## 33. 仓库结构整理、文档收尾与持续集成

**任务目标**

按职责重组生产与测试代码，整理根目录文档，并增加 Windows GitHub Actions 自动测试；保持 CLI、GUI、API、安全、验证和持久化行为不变。

**涉及模块**

- `src/coding_agent/` 与 `tests/` 的职责子目录
- `docs/project/`、`README.md`、`README.txt`、`AGENTS.md`
- `pyproject.toml`
- `.github/workflows/tests.yml`

**验收标准**

- 生产代码按 application、engine、providers、operations、sessions、skills、web 分包，根包只保留 `__init__.py`。
- 测试目录镜像生产职责，旧内部导入路径无有效残留。
- 根目录只保留 AGENTS.md、README.md、README.txt 三份项目说明文档。
- README.md 说明项目、目录结构和文件夹职责；README.txt 不超过 1000 个汉字并包含仓库地址、运行方法、特色和安全边界。
- push 与 pull request 在 windows-latest、Python 3.11、Node.js 24 下自动运行离线测试与打包检查。
- 两个 CLI 命令、Web 静态资源、完整 Python/Node 测试和安全边界保持正常。

**当前状态**

`进行中`
```

- [ ] **Step 5: Check the documentation-only transition**

Run:

```powershell
git diff --check -- TASKS.md
git diff -- TASKS.md
```

Expected: no whitespace error; the diff changes only Task 32's status and adds Task 33. Do not commit.

---

### Task 2: Scaffold Responsibility Packages with a Red/Green Layout Contract

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/application/__init__.py`
- Create: `tests/application/test_repository_layout.py`
- Create: `tests/engine/__init__.py`
- Create: `tests/providers/__init__.py`
- Create: `tests/operations/__init__.py`
- Create: `tests/sessions/__init__.py`
- Create: `tests/skills/__init__.py`
- Create: `tests/web/__init__.py`
- Create: `tests/manual/__init__.py`
- Create: `src/coding_agent/application/__init__.py`
- Create: `src/coding_agent/engine/__init__.py`
- Create: `src/coding_agent/providers/__init__.py`
- Create: `src/coding_agent/operations/__init__.py`
- Create: `src/coding_agent/operations/tools/__init__.py`
- Create: `src/coding_agent/sessions/__init__.py`
- Create: `src/coding_agent/skills/__init__.py`
- Create: `src/coding_agent/web/__init__.py`

**Interfaces:**
- Consumes: the unchanged `coding_agent` root package.
- Produces: importable empty responsibility packages used by all later move tasks.

- [ ] **Step 1: Write the failing package-layout test**

Create `tests/application/test_repository_layout.py` with this initial contract:

```python
from __future__ import annotations

import importlib

import pytest


RESPONSIBILITY_PACKAGES = (
    "application",
    "engine",
    "providers",
    "operations",
    "operations.tools",
    "sessions",
    "skills",
    "web",
)


@pytest.mark.parametrize("suffix", RESPONSIBILITY_PACKAGES)
def test_responsibility_package_is_importable(suffix: str) -> None:
    module = importlib.import_module(f"coding_agent.{suffix}")
    assert module.__name__ == f"coding_agent.{suffix}"
```

- [ ] **Step 2: Run the test to verify the expected red state**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_repository_layout.py -q
```

Expected: nonzero exit caused by `ModuleNotFoundError` for the new responsibility packages, not by a syntax or environment error.

- [ ] **Step 3: Create package markers**

Use `apply_patch` to create each listed `__init__.py`. Production markers contain only an accurate one-line package docstring, for example:

```python
"""Provider adapters for supported model APIs."""
```

Test markers may be empty. Do not re-export old module names.

- [ ] **Step 4: Run the package-layout test green**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_repository_layout.py -q
```

Expected: all parameter cases pass.

- [ ] **Step 5: Review the scaffold checkpoint**

Run:

```powershell
git diff --check
git status --short
```

Expected: only package markers, the layout test, Task 33, design, and plan are new/modified. Do not commit.

---

### Task 3: Move the Provider-Neutral Engine

**Files:**
- Move: the fourteen engine modules in the locked map to `src/coding_agent/engine/`
- Move: the fourteen engine unit tests in the locked map to `tests/engine/`
- Modify: every Python file under `src/` and `tests/` that imports or monkeypatches a moved engine module
- Modify: `tests/application/test_repository_layout.py`

**Interfaces:**
- Consumes: importable `coding_agent.engine` package; the old operations, providers, application, session, Skill, and Web modules still exist during this task.
- Produces: `coding_agent.engine.agent.AgentRunner`, `coding_agent.engine.model.ModelClient`, and all other engine symbols at their new paths.

- [ ] **Step 1: Add a failing engine-module import contract**

Extend `tests/application/test_repository_layout.py`:

```python
ENGINE_MODULES = (
    "agent", "budget", "context", "instructions", "logging", "messages",
    "model", "progress", "report", "run_mode", "state", "streaming",
    "termination", "verification",
)


@pytest.mark.parametrize("name", ENGINE_MODULES)
def test_engine_module_is_importable(name: str) -> None:
    module = importlib.import_module(f"coding_agent.engine.{name}")
    assert module.__name__ == f"coding_agent.engine.{name}"
```

- [ ] **Step 2: Verify the engine contract fails before the move**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_repository_layout.py -q
```

Expected: the responsibility-package cases pass and engine-module cases fail because the modules do not yet exist below `engine/`.

- [ ] **Step 3: Move the engine files and their tests**

Resolve each exact source and destination, verify both start with `D:\code\coding_agent\`, and move the filenames from the locked map with `Move-Item -LiteralPath`. Move individual files only; do not move the whole repository or a computed directory tree.

- [ ] **Step 4: Update engine imports everywhere**

Apply these exact prefix changes in executable source and tests, including `monkeypatch.setattr(...)` strings and dynamic-import assertions:

```text
coding_agent.agent        -> coding_agent.engine.agent
coding_agent.budget       -> coding_agent.engine.budget
coding_agent.context      -> coding_agent.engine.context
coding_agent.instructions -> coding_agent.engine.instructions
coding_agent.logging      -> coding_agent.engine.logging
coding_agent.messages     -> coding_agent.engine.messages
coding_agent.model        -> coding_agent.engine.model
coding_agent.progress     -> coding_agent.engine.progress
coding_agent.report       -> coding_agent.engine.report
coding_agent.run_mode     -> coding_agent.engine.run_mode
coding_agent.state        -> coding_agent.engine.state
coding_agent.streaming    -> coding_agent.engine.streaming
coding_agent.termination  -> coding_agent.engine.termination
coding_agent.verification -> coding_agent.engine.verification
```

Do not change operation/provider/session imports yet. Update type-checking imports and lazy imports inside function bodies as well as top-level imports.

- [ ] **Step 5: Prove the engine batch is green**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/engine tests/integration tests/application/test_repository_layout.py -q
.\.venv\Scripts\python.exe -m pytest -q
rg -n "coding_agent\.(agent|budget|context|instructions|logging|messages|model|progress|report|run_mode|state|streaming|termination|verification)(\b|\.)" src tests pyproject.toml
```

Expected: both pytest commands exit `0`; the `rg` command returns no old engine imports. Matches inside `docs/superpowers/` are intentionally out of scope.

---

### Task 4: Move Safety and Local Tools

**Files:**
- Move: `src/coding_agent/safety.py` to `src/coding_agent/operations/safety.py`
- Move: all five current `src/coding_agent/tools/*.py` implementation files to `src/coding_agent/operations/tools/`
- Move: `tests/test_command_safety.py`, `tests/test_path_safety.py`, and all `tests/tools/test_*.py` to `tests/operations/`
- Modify: all imports and monkeypatch targets referencing `coding_agent.safety` or `coding_agent.tools`
- Modify: `tests/application/test_repository_layout.py`

**Interfaces:**
- Consumes: engine messages, state, and verification types at `coding_agent.engine.*`.
- Produces: `coding_agent.operations.safety` and `coding_agent.operations.tools.*` with unchanged classes, schemas, command policy, and execution semantics.

- [ ] **Step 1: Add failing operation-module contracts**

Add:

```python
OPERATION_MODULES = (
    "safety",
    "tools.base",
    "tools.filesystem",
    "tools.java",
    "tools.registry",
    "tools.shell",
)


@pytest.mark.parametrize("name", OPERATION_MODULES)
def test_operation_module_is_importable(name: str) -> None:
    module = importlib.import_module(f"coding_agent.operations.{name}")
    assert module.__name__ == f"coding_agent.operations.{name}"
```

- [ ] **Step 2: Run the red operation contract**

Run the layout test and expect import failures only for the new operation module paths.

- [ ] **Step 3: Move operation modules and tests**

Use explicit verified `Move-Item -LiteralPath` calls. Preserve `src/coding_agent/operations/tools/__init__.py` created in Task 2.

- [ ] **Step 4: Update all safety/tool imports**

Apply:

```text
coding_agent.safety       -> coding_agent.operations.safety
coding_agent.tools.base   -> coding_agent.operations.tools.base
coding_agent.tools.filesystem -> coding_agent.operations.tools.filesystem
coding_agent.tools.java   -> coding_agent.operations.tools.java
coding_agent.tools.registry -> coding_agent.operations.tools.registry
coding_agent.tools.shell  -> coding_agent.operations.tools.shell
```

Update string targets used by monkeypatch and subprocess import probes. Do not alter strict schemas, tool names, command allowlists, timeouts, output limits, or error text.

- [ ] **Step 5: Prove the operation batch is green**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/operations tests/engine/test_instructions.py tests/engine/test_verification.py tests/application/test_repository_layout.py -q
.\.venv\Scripts\python.exe -m pytest -q
rg -n "coding_agent\.(safety|tools)(\b|\.)" src tests pyproject.toml
```

Expected: tests pass; no old safety/tool import remains.

---

### Task 5: Move Model Provider Adapters

**Files:**
- Move: the three provider modules in the locked map to `src/coding_agent/providers/`
- Move: the five provider test files in the locked map to `tests/providers/`
- Modify: imports and monkeypatch strings across `src/` and `tests/`
- Modify: `tests/application/test_repository_layout.py`

**Interfaces:**
- Consumes: `coding_agent.engine.model`, `coding_agent.engine.messages`, `coding_agent.engine.streaming`, and the still-top-level `coding_agent.config`.
- Produces: provider clients and model catalog under `coding_agent.providers.*` with unchanged SDK timeout, retry, strict parsing, and privacy behavior.

- [ ] **Step 1: Add the failing provider import contract**

Add:

```python
PROVIDER_MODULES = (
    "openai_client",
    "chat_completions_client",
    "model_catalog",
)


@pytest.mark.parametrize("name", PROVIDER_MODULES)
def test_provider_module_is_importable(name: str) -> None:
    module = importlib.import_module(f"coding_agent.providers.{name}")
    assert module.__name__ == f"coding_agent.providers.{name}"
```

- [ ] **Step 2: Run the layout test red**

Expected: only provider-module cases fail due to absent new modules.

- [ ] **Step 3: Move provider modules and tests**

Use explicit verified file moves; do not rename the client classes or protocol types.

- [ ] **Step 4: Update provider references**

Apply:

```text
coding_agent.openai_client            -> coding_agent.providers.openai_client
coding_agent.chat_completions_client  -> coding_agent.providers.chat_completions_client
coding_agent.model_catalog            -> coding_agent.providers.model_catalog
```

Update monkeypatch paths such as SDK factories. Preserve constructor signatures and `ModelClient` conformance.

- [ ] **Step 5: Prove the provider batch is green and offline**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/providers tests/integration/test_chat_completions_agent.py tests/application/test_repository_layout.py -q
.\.venv\Scripts\python.exe -m pytest -q
rg -n "coding_agent\.(openai_client|chat_completions_client|model_catalog)(\b|\.)" src tests pyproject.toml
```

Expected: all commands pass without a real key or network call; old provider imports are absent.

---

### Task 6: Move Declarative Skill Modules

**Files:**
- Move: `src/coding_agent/skills.py` to `src/coding_agent/skills/catalog.py`
- Move: `src/coding_agent/skill_packages.py` to `src/coding_agent/skills/packages.py`
- Move: `tests/test_skills.py` to `tests/skills/test_catalog.py`
- Move: `tests/test_skill_packages.py` to `tests/skills/test_packages.py`
- Modify: all Skill imports and monkeypatch targets
- Modify: `tests/application/test_repository_layout.py`

**Interfaces:**
- Consumes: unchanged engine and operation types.
- Produces: `coding_agent.skills.catalog` and `coding_agent.skills.packages`; public class/function names remain unchanged.

- [ ] **Step 1: Add failing Skill module contracts**

Add:

```python
SKILL_MODULES = ("catalog", "packages")


@pytest.mark.parametrize("name", SKILL_MODULES)
def test_skill_module_is_importable(name: str) -> None:
    module = importlib.import_module(f"coding_agent.skills.{name}")
    assert module.__name__ == f"coding_agent.skills.{name}"
```

- [ ] **Step 2: Verify the Skill contract is red**

Expected: `catalog` and `packages` imports fail before the move.

- [ ] **Step 3: Move and rename Skill modules and tests**

Use explicit verified moves. Do not create executable Skill behavior or broaden ZIP grammar.

- [ ] **Step 4: Update Skill references**

Apply:

```text
coding_agent.skills         -> coding_agent.skills.catalog
coding_agent.skill_packages -> coding_agent.skills.packages
```

Order replacements carefully: replace `coding_agent.skill_packages` first, and replace only exact old `coding_agent.skills` module references so new `coding_agent.skills.catalog` paths are not doubled. Update relative imports inside `packages.py` to `.catalog`.

- [ ] **Step 5: Prove the Skill batch is green**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/skills tests/sessions tests/web tests/application/test_repository_layout.py -q
.\.venv\Scripts\python.exe -m pytest -q
rg -n "coding_agent\.skill_packages(\b|\.)|from coding_agent import skills|coding_agent\.skills(?!\.(catalog|packages))" src tests --pcre2
```

Expected: tests pass and no executable code imports the former module paths.

---

### Task 7: Move Session Domain and Persistence

**Files:**
- Move: the six session modules in the locked map to `src/coding_agent/sessions/`
- Move: the six `tests/test_session*.py` files to `tests/sessions/`
- Modify: all session imports and monkeypatch paths
- Modify: `tests/application/test_repository_layout.py`

**Interfaces:**
- Consumes: engine, provider catalog, operations safety, and Skill catalog/package interfaces at their new locations; application remains top-level until Task 8.
- Produces: unchanged session entities, store protocol, SQLite store, event hub, controller, runtime executor, and deletion coordinator under `coding_agent.sessions.*`.

- [ ] **Step 1: Add failing session import contracts**

Add:

```python
SESSION_MODULES = (
    "session",
    "session_controller",
    "session_deletion",
    "session_events",
    "session_runtime",
    "session_store",
)


@pytest.mark.parametrize("name", SESSION_MODULES)
def test_session_module_is_importable(name: str) -> None:
    module = importlib.import_module(f"coding_agent.sessions.{name}")
    assert module.__name__ == f"coding_agent.sessions.{name}"
```

- [ ] **Step 2: Verify the session contract is red**

Expected: new session module imports fail before the move.

- [ ] **Step 3: Move session modules and unit tests**

Use verified individual moves. Preserve filenames to minimize changes to historical terminology.

- [ ] **Step 4: Update all session references**

Apply exact prefix changes:

```text
coding_agent.session            -> coding_agent.sessions.session
coding_agent.session_controller -> coding_agent.sessions.session_controller
coding_agent.session_deletion   -> coding_agent.sessions.session_deletion
coding_agent.session_events     -> coding_agent.sessions.session_events
coding_agent.session_runtime    -> coding_agent.sessions.session_runtime
coding_agent.session_store      -> coding_agent.sessions.session_store
```

Replace longer names before `coding_agent.session` to avoid partial duplication. Update internal relative imports, test monkeypatch strings, `TYPE_CHECKING` imports, and the manual fixture imports.

- [ ] **Step 5: Prove schema and session behavior are unchanged**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/sessions tests/integration tests/application/test_repository_layout.py -q
.\.venv\Scripts\python.exe -m pytest -q
rg -n "coding_agent\.(session|session_controller|session_deletion|session_events|session_runtime|session_store)(\b|\.)" src tests pyproject.toml
```

Expected: migrations, deletion recovery, events, controller, and full suite pass; old paths are absent.

---

### Task 8: Move Application and Web Boundaries, Then Request Core Review

**Files:**
- Move: `app.py`, `config.py`, `cli.py` to `src/coding_agent/application/`
- Move/rename: Web Python modules and static assets according to the locked map
- Move: `tests/test_app.py`, `tests/test_cli.py`, `tests/test_docs.py` to `tests/application/`
- Move: all `tests/test_web*.py` to `tests/web/`
- Move/rename: `tests/web_support.py` to `tests/web/support.py`
- Move: `tests/manual_web_fixture.py` to `tests/manual/manual_web_fixture.py`
- Modify: `tests/js/web_gui.test.mjs`
- Modify: `docs/USAGE.md`
- Modify: `pyproject.toml`
- Modify: every remaining application/Web import and monkeypatch path
- Modify: `tests/application/test_repository_layout.py`

**Interfaces:**
- Consumes: all responsibility packages completed by Tasks 3-7.
- Produces: `coding_agent.application.app`, `coding_agent.application.config`, `coding_agent.application.cli`, `coding_agent.web.app`, `coding_agent.web.auth`, and `coding_agent.web.cli`; installed command names remain unchanged.

- [ ] **Step 1: Add failing application and Web contracts**

Add:

```python
APPLICATION_MODULES = ("app", "config", "cli")
WEB_MODULES = ("app", "auth", "cli")


@pytest.mark.parametrize("name", APPLICATION_MODULES)
def test_application_module_is_importable(name: str) -> None:
    module = importlib.import_module(f"coding_agent.application.{name}")
    assert module.__name__ == f"coding_agent.application.{name}"


@pytest.mark.parametrize("name", WEB_MODULES)
def test_web_module_is_importable(name: str) -> None:
    module = importlib.import_module(f"coding_agent.web.{name}")
    assert module.__name__ == f"coding_agent.web.{name}"
```

- [ ] **Step 2: Verify these contracts are red**

Expected: application/Web module cases fail before their files move.

- [ ] **Step 3: Move application, Web, static, and associated test files**

Use explicit verified moves. Before moving `web_static`, resolve both `D:\code\coding_agent\src\coding_agent\web_static` and `D:\code\coding_agent\src\coding_agent\web\static`, verify they are workspace descendants, then move its three files individually. Move the manual fixture and Web support file individually.

- [ ] **Step 4: Update application and Web imports**

Apply:

```text
coding_agent.app      -> coding_agent.application.app
coding_agent.config   -> coding_agent.application.config
coding_agent.cli      -> coding_agent.application.cli
coding_agent.web_auth -> coding_agent.web.auth
coding_agent.web_cli  -> coding_agent.web.cli
coding_agent.web      -> coding_agent.web.app
tests.web_support     -> tests.web.support
```

Replace `coding_agent.web_auth` and `coding_agent.web_cli` before exact `coding_agent.web`. Do not rewrite already-correct `coding_agent.web.app` paths. Update lazy imports, monkeypatch strings, subprocess import probes, and manual-fixture command documentation.

Because three tests/fixtures move one directory deeper, set their repository anchors exactly as follows:

```python
ROOT = Path(__file__).resolve().parents[2]
```

Apply that line in `tests/application/test_docs.py`, `tests/web/test_web_gui.py`, and `tests/manual/manual_web_fixture.py`. The integration fixtures already use `parents[2]` and must remain unchanged.

- [ ] **Step 5: Update package entry points and resources**

Set the exact `pyproject.toml` entries:

```toml
[project.scripts]
coding-agent = "coding_agent.application.cli:entrypoint"
coding-agent-web = "coding_agent.web.cli:entrypoint"

[tool.setuptools.package-data]
"coding_agent.web" = ["static/*.html", "static/*.css", "static/*.js"]
```

In `coding_agent.web.app`, load resources with:

```python
files("coding_agent.web").joinpath("static")
```

Update `tests/js/web_gui.test.mjs` to resolve `../../src/coding_agent/web/static/app.js`. Update the manual command in `docs/USAGE.md` to `tests\manual\manual_web_fixture.py`.

- [ ] **Step 6: Extend the final source-layout assertion**

Add to `test_repository_layout.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "src" / "coding_agent"


def test_root_package_contains_only_marker_and_subpackages() -> None:
    assert sorted(path.name for path in PACKAGE_ROOT.glob("*.py")) == ["__init__.py"]
```

- [ ] **Step 7: Prove commands, GUI resources, and full behavior are green**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application tests/web tests/js tests/integration -q
node --test tests/js/web_gui.test.mjs
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\coding-agent.exe --help
.\.venv\Scripts\coding-agent-web.exe --help
```

Expected: every command exits `0`; installed editable entry points resolve their new targets; GUI tests find the moved static resource.

- [ ] **Step 8: Scan all executable code for old paths**

Run an `rg` expression covering every old module prefix from the locked map against `src`, `tests`, and `pyproject.toml`. Expected: no matches. Do not scan historical Superpowers plans/specs as though they were executable imports.

- [ ] **Step 9: Request a core-module code review checkpoint**

Invoke `superpowers:requesting-code-review` for Tasks 3-8. Review specifically for missed imports, package-resource errors, circular imports, monkeypatch targets, unintended public behavior changes, dependency changes, and weakened safety/verification rules. If subagents were not explicitly authorized, keep the review inline and do not dispatch one. Resolve every confirmed finding before starting documentation work.

---

### Task 9: Move Project Documents and Rewrite the Public Readmes

**Files:**
- Move: `DESIGN.md` to `docs/project/DESIGN.md`
- Move: `TASKS.md` to `docs/project/TASKS.md`
- Move: `requirement.pdf` to `docs/project/requirement.pdf`
- Modify: `AGENTS.md`
- Rewrite: `README.md`
- Rewrite: `README.txt`
- Modify: `docs/project/DESIGN.md`
- Modify: `docs/USAGE.md`
- Modify: `docs/OPENAI_API.md` only if it contains a current broken path
- Modify: `tests/application/test_docs.py`
- Modify: `tests/application/test_repository_layout.py`

**Interfaces:**
- Consumes: final production/test directory names and stable command examples.
- Produces: three root project documents, current design/task paths, folder-level README, and a submission README under 1000 characters.

- [ ] **Step 1: Write failing document-location and README contracts**

Add or update tests with this contract shape:

```python
ROOT_DOCUMENTS = {"AGENTS.md", "README.md", "README.txt"}


def test_root_contains_only_three_project_documents() -> None:
    found = {
        path.name
        for path in ROOT.iterdir()
        if path.is_file() and path.suffix.lower() in {".md", ".txt", ".pdf"}
    }
    assert found == ROOT_DOCUMENTS


def test_project_documents_have_final_locations() -> None:
    assert (ROOT / "docs/project/DESIGN.md").is_file()
    assert (ROOT / "docs/project/TASKS.md").is_file()
    assert (ROOT / "docs/project/requirement.pdf").is_file()


def test_readme_txt_submission_contract() -> None:
    text = (ROOT / "README.txt").read_text(encoding="utf-8")
    assert len(text) <= 1000
    assert "https://github.com/zt150058/MiniCodex" in text
    assert "Python 3.11" in text
    assert "coding-agent" in text
    assert "coding-agent-web" in text


def test_agents_points_to_current_design_and_tasks() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "docs/project/DESIGN.md" in text
    assert "docs/project/TASKS.md" in text
```

Also change existing document tests that read `ROOT / "DESIGN.md"` or `ROOT / "TASKS.md"` to read the `docs/project/` paths.

- [ ] **Step 2: Run document tests red**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_docs.py tests/application/test_repository_layout.py -q
```

Expected: failures identify the still-root design/task/PDF paths and old README/AGENTS contracts.

- [ ] **Step 3: Move the three project-history documents**

Create `docs/project/`, resolve exact paths, verify all sources and destinations are under the workspace, and use individual `Move-Item -LiteralPath` calls for `DESIGN.md`, `TASKS.md`, and `requirement.pdf`.

- [ ] **Step 4: Update active project rules and design**

In `AGENTS.md`, replace every rule reference to root `DESIGN.md` and `TASKS.md` with `docs/project/DESIGN.md` and `docs/project/TASKS.md`.

In `docs/project/DESIGN.md`, update the package-layout and module-responsibility sections to describe `application/`, `engine/`, `providers/`, `operations/`, `sessions/`, `skills/`, and `web/`. Add a concise migration note stating that Task 33 moved internal modules and that older task/history paths are historical rather than compatibility promises.

- [ ] **Step 5: Rewrite README.md at folder granularity**

Use exactly these top-level sections:

```markdown
# MiniCodex

## 项目简介

## 仓库结构

## 目录职责

## 详细文档
```

The repository tree names `.github/`, `docs/`, `examples/`, `src/`, `tests/`, and `pyproject.toml`; the package tree names the seven production subpackages. Explain folders only—do not add a file-by-file module catalog. Link detailed usage to `docs/USAGE.md`, provider behavior to `docs/OPENAI_API.md`, architecture to `docs/project/DESIGN.md`, and implementation history to `docs/project/TASKS.md`.

- [ ] **Step 6: Rewrite README.txt under the hard length limit**

Keep the complete file at 1000 Unicode characters or fewer. Include the exact repository URL, these run forms, the two credential modes, core features, and the non-OS-sandbox boundary:

```text
pip install -e ".[test]"
coding-agent "修复测试" --workspace . --verify "pytest -q"
coding-agent "介绍项目" --workspace . --read-only
coding-agent-web --workspace .
```

Do not link to obsolete root design/task paths.

- [ ] **Step 7: Update current documentation references**

Update `docs/USAGE.md`, `docs/OPENAI_API.md`, and active document tests for the new executable, manual-fixture, and project-document paths. Preserve historical plan/spec text. Use this scoped scan:

```powershell
rg -n "(^|[(/`])DESIGN\.md|(^|[(/`])TASKS\.md|tests[\\/]manual_web_fixture\.py|src/coding_agent/web_static" AGENTS.md README.md README.txt docs/USAGE.md docs/OPENAI_API.md docs/project tests src pyproject.toml
```

Expected: no current broken path; historical task descriptions in `docs/project/TASKS.md` may retain their original file paths, while Task 33 and the current design use final paths.

- [ ] **Step 8: Run document tests green**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_docs.py tests/application/test_repository_layout.py -q
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

Expected: all pass; README.txt satisfies the measured hard limit; root-document contract passes.

---

### Task 10: Add the Windows GitHub Actions Pipeline

**Files:**
- Create: `.github/workflows/tests.yml`
- Create: `tests/application/test_ci_workflow.py`

**Interfaces:**
- Consumes: final package paths, final test paths, `pyproject.toml` entry points/package data, and no secrets.
- Produces: one read-only Windows workflow triggered by push and pull request.

- [ ] **Step 1: Write the failing workflow contract test**

Create `tests/application/test_ci_workflow.py`:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"


def test_windows_test_workflow_contract() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required = (
        "push:",
        "pull_request:",
        "contents: read",
        "runs-on: windows-latest",
        "timeout-minutes: 30",
        "actions/checkout@v7",
        "actions/setup-python@v7",
        "python-version: '3.11'",
        "actions/setup-node@v7",
        "node-version: '24'",
        'python -m pip install -e ".[test]"',
        "python -m pytest -q",
        "node --test tests/js/web_gui.test.mjs",
        "coding-agent --help",
        "coding-agent-web --help",
        "python -m pip wheel . --no-deps",
        "git diff --check",
    )
    for marker in required:
        assert marker in text
    assert "OPENAI_API_KEY" not in text
    assert "CHAT_COMPLETIONS_API_KEY" not in text
```

- [ ] **Step 2: Verify the workflow test is red**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_ci_workflow.py -q
```

Expected: `FileNotFoundError` for `.github/workflows/tests.yml`.

- [ ] **Step 3: Create the exact workflow**

Create `.github/workflows/tests.yml` with this structure:

```yaml
name: tests

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  test:
    runs-on: windows-latest
    timeout-minutes: 30
    env:
      PYTHONUTF8: "1"
    steps:
      - name: Check out repository
        uses: actions/checkout@v7
      - name: Set up Python
        uses: actions/setup-python@v7
        with:
          python-version: '3.11'
          cache: pip
      - name: Set up Node.js
        uses: actions/setup-node@v7
        with:
          node-version: '24'
          package-manager-cache: false
      - name: Install project and test dependencies
        run: python -m pip install -e ".[test]"
      - name: Run Python tests
        run: python -m pytest -q
      - name: Run GUI DOM tests
        run: node --test tests/js/web_gui.test.mjs
      - name: Check command entry points
        run: |
          coding-agent --help
          coding-agent-web --help
      - name: Build wheel
        run: python -m pip wheel . --no-deps --wheel-dir "${{ runner.temp }}\wheelhouse"
      - name: Check package imports
        run: python -c "import coding_agent; import coding_agent.application.cli; import coding_agent.web.app"
      - name: Check tracked diff whitespace
        run: git diff --check
```

Do not add release, upload, deployment, write permission, secret, live API, or package-install steps beyond `.[test]` and the build-system requirements already declared by the project.

- [ ] **Step 4: Run workflow and packaging contracts locally**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_ci_workflow.py tests/application/test_cli.py tests/application/test_repository_layout.py -q
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir .pytest_cache/repository-build
.\.venv\Scripts\python.exe -c "import coding_agent; import coding_agent.application.cli; import coding_agent.web.app"
```

Expected: all commands exit `0` and a wheel appears only below ignored `.pytest_cache/repository-build`.

- [ ] **Step 5: Inspect the built wheel for required resources**

Run a standard-library `zipfile` assertion against the newest wheel below `.pytest_cache/repository-build`. Assert it contains:

```text
coding_agent/application/cli.py
coding_agent/engine/agent.py
coding_agent/operations/tools/filesystem.py
coding_agent/web/app.py
coding_agent/web/static/index.html
coding_agent/web/static/app.js
coding_agent/web/static/styles.css
```

Expected: exit code `0`; do not install a wheel-inspection dependency.

- [ ] **Step 6: Run the workflow contract green**

Run the CI contract test again and expect it to pass. Then run `git diff --check`.

---

### Task 11: Final Verification, Task Status, and Handoff

**Files:**
- Modify: `docs/project/TASKS.md`
- Inspect: all files changed by Tasks 1-10

**Interfaces:**
- Consumes: completed package, documentation, and CI changes.
- Produces: verified Task 33 completion evidence and a review-ready handoff without an unauthorized commit.

- [ ] **Step 1: Verify final tracked structure**

Run:

```powershell
rg --files src/coding_agent tests docs .github | Sort-Object
Get-ChildItem -File | Select-Object -ExpandProperty Name
git status --short
```

Expected: the locked source/test/document map is present; root production package has only `__init__.py`; root project documents are exactly AGENTS.md, README.md, README.txt; no old duplicate tracked source remains.

- [ ] **Step 2: Run focused contracts**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_repository_layout.py tests/application/test_docs.py tests/application/test_ci_workflow.py tests/application/test_cli.py tests/web/test_web_gui.py -q
node --test tests/js/web_gui.test.mjs
```

Expected: exit code `0` for both commands.

- [ ] **Step 3: Run the complete offline Python suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit code `0`. Record real passed/skipped counts and duration.

- [ ] **Step 4: Run packaging and command smoke checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir .pytest_cache/repository-build-final
.\.venv\Scripts\coding-agent.exe --help
.\.venv\Scripts\coding-agent-web.exe --help
```

Expected: all exit `0`; the wheel inspection from Task 10 still passes for the final wheel.

- [ ] **Step 5: Run policy and residue scans**

Run:

```powershell
rg -n "langchain|llamaindex|openai-agents|autogen|crewai" pyproject.toml src tests
rg -n "OPENAI_API_KEY|CHAT_COMPLETIONS_API_KEY" .github
git diff --check
git diff --stat
```

Expected: framework scan has no introduced dependency/use; CI secret-name scan is empty; diff check exits `0`; diff stat contains only the approved structural, documentation, test, packaging, and workflow scope.

- [ ] **Step 6: Inspect the diff for behavioral changes**

Review moved-file diffs with rename detection:

```powershell
git diff --find-renames -- src tests pyproject.toml docs AGENTS.md README.md README.txt .github
```

Expected: production changes are path/import/resource-location changes only. Any logic difference outside import/resource lookup returns to the approved design before completion.

- [ ] **Step 7: Mark Task 33 complete only after evidence exists**

Change Task 33's status in `docs/project/TASKS.md` from `进行中` to `已完成`. Then run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_docs.py -q
git diff --check
```

Expected: both pass. If any required verification above failed, leave Task 33 `进行中`.

- [ ] **Step 8: Apply verification-before-completion and final review**

Invoke `superpowers:verification-before-completion`, using only the fresh command outputs from Steps 2-7. Then invoke `superpowers:requesting-code-review` for the complete diff. Resolve confirmed findings and rerun every affected focused test plus the full suite when production code changes.

- [ ] **Step 9: Report without committing**

Report:

```text
- final source/test/document structure
- CI workflow triggers and runner versions
- exact Python and Node commands with real exit codes/counts
- wheel and CLI smoke results
- verified absence of new dependencies/frameworks/secrets
- any remaining assumptions or manual-only checks
```

Do not commit, stage, push, or create a pull request unless the user separately authorizes it.

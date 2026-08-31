# Web GUI Copy, Workspace Path, and Activity Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Use `superpowers:test-driven-development` before production changes, `superpowers:systematic-debugging` for reproducible unexpected failures, `superpowers:requesting-code-review` after the core GUI slice, and `superpowers:verification-before-completion` before reporting completion. Steps use checkbox (`- [ ]`) syntax for tracking. The user authorized inline execution after this plan; do not dispatch subagents.

**Goal:** Add safe fenced-code copying, replace run call counters with the absolute workspace path, simplify the MiniCodex brand, and animate only the current active reply card.

**Architecture:** The existing server-rendered local document receives one deliberately escaped absolute-workspace marker while retaining its loopback/no-store security boundary. The deterministic DOM renderer creates copy controls and active indicators with node APIs only; injected clipboard/timer functions keep behavior testable and provider/session layers unchanged.

**Tech Stack:** Python 3.11+, FastAPI, standard-library `html`/`pathlib`, plain HTML/CSS/JavaScript, pytest, Node's built-in test runner.

**Spec:** `docs/superpowers/specs/2026-08-31-web-gui-copy-workspace-path-activity-animation-design.md`

## Global Constraints

- Work only in `D:\code\coding_agent`; preserve all pre-existing Task29/Task30 and user changes.
- Execute inline in this session. Do not use a subagent, branch, worktree, commit, push, pull, fetch, or remote repository operation.
- Add no dependency and make no real network/provider request.
- Modify only the Web document/static GUI, their tests, architecture/task/user docs, and this plan/spec.
- The absolute configured workspace root is the only new host-path disclosure; it must not enter REST, SSE, SQLite, JSONL, model context, reports, exceptions, or attributes other than the fixed path title.
- Continue using `createElement`, `createTextNode`, fixed `className`, and fixed attributes. Never use `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, inline event handlers, or inline styles.
- Copy states and animation never change Agent success, progress, budget, cancellation, Session, or verification semantics.
- Every production change follows a focused RED/GREEN test cycle and all existing GUI behavior remains covered.

## Locked File Map

**Production files**

- `src/coding_agent/web.py` — replace the basename bootstrap with an escaped absolute path marker.
- `src/coding_agent/web_static/index.html` — simplify the brand and replace the phase/counter fact with a folder/path fact.
- `src/coding_agent/web_static/styles.css` — brand/path, code-copy, active-indicator, responsive, and reduced-motion styles.
- `src/coding_agent/web_static/app.js` — remove counter rendering, add deterministic code-copy behavior, and mark current activity cards active.

**Tests and docs**

- `tests/test_web_gui.py` — HTTP bootstrap, static structure/style, accessibility, and unsafe-sink contracts.
- `tests/js/web_gui.test.mjs` — renderer clipboard, header, animation, and existing GUI regressions.
- `docs/USAGE.md` and `tests/test_docs.py` — user-facing local-path disclosure and interaction contract.
- `DESIGN.md`, `TASKS.md`, approved spec, and this plan — architecture/order/approval record.

---

### Task 1: Absolute workspace path and simplified header

**Files:**

- Modify: `src/coding_agent/web.py`
- Modify: `src/coding_agent/web_static/index.html`
- Modify: `src/coding_agent/web_static/styles.css`
- Modify: `src/coding_agent/web_static/app.js`
- Test: `tests/test_web_gui.py`
- Test: `tests/js/web_gui.test.mjs`

**Interfaces:**

- Replaces: `_WORKSPACE_NAME_MARKER` with `_WORKSPACE_PATH_MARKER = "__CODING_AGENT_WORKSPACE_PATH__"`.
- Produces: `id="workspace-path"` whose text and `title` are the exact escaped `str(controller.workspace.resolve(strict=False))`.
- Replaces: `renderRunHeader(document, elements, run, phase, progress, transientStatus)` with `renderRunHeader(document, elements, run, transientStatus = null)`.
- Removes: DOM IDs `workspace-name` and `run-phase`; keeps server-side progress ingestion unchanged.

- [ ] **Step 1: Write failing Python document and layout tests**

Update `REQUIRED_IDS` to remove `workspace-name`/`run-phase` and add `workspace-path`. Replace the basename test with:

```python
def test_document_projects_the_escaped_absolute_workspace_path(tmp_path: Path) -> None:
    workspace = tmp_path / 'folder<&"'
    workspace.mkdir()
    response = asyncio.run(
        request(make_app(workspace=workspace), "GET", "/", headers=document_headers())
    )
    escaped = html.escape(str(workspace.resolve()), quote=True)
    assert response.status_code == 200
    assert response.text.count(escaped) == 2
    assert "__CODING_AGENT_WORKSPACE_PATH__" not in response.text
```

Add structural assertions that the folder SVG is inside the workspace fact, `.brand-name` is at least `20px`, the old `.workspace-name` rule is absent, the path rule has `min-width: 0`, `overflow: hidden`, `text-overflow: ellipsis`, and `white-space: nowrap`, and the static HTML contains none of the four call-counter labels.

- [ ] **Step 2: Run focused Python tests and observe RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_gui.py -q -p no:cacheprovider
```

Expected: failures identify the old basename marker, `workspace-name`, `run-phase`, and missing path layout.

- [ ] **Step 3: Write failing Node header test**

Change the existing run-header test to call:

```javascript
gui.renderRunHeader(document, elements, run, state.transientStatus);
assert.equal(elements.runStatus.textContent, "根据已有信息作出决策");
assert.equal(elements.workspacePath.textContent, "D:\\code\\coding_agent");
assert.equal(elements.runFacts.textContent.includes("8/24"), false);
assert.equal(elements.runFacts.textContent.includes("17/80"), false);
```

Update the fixture to expose `workspacePath` and `runFacts`, and remove `runPhase`. Run the named test and confirm it fails against the old signature/counter renderer.

- [ ] **Step 4: Implement the absolute path bootstrap and markup**

In `web.py`, validate exactly two path markers and render with:

```python
workspace_path = html.escape(
    str(controller.workspace.resolve(strict=False)),
    quote=True,
)
rendered = rendered.replace(_WORKSPACE_PATH_MARKER, workspace_path)
```

In `index.html`, remove the workspace eyebrow from `.brand-copy`, keep only `MiniCodex`, and replace the phase fact with:

```html
<div class="run-fact workspace-path-fact">
  <span class="fact-label">工作区</span>
  <span class="workspace-path-value">
    <svg class="workspace-path-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M3.5 6.5h6l2 2h9v9A2.5 2.5 0 0 1 18 20H6a2.5 2.5 0 0 1-2.5-2.5Z" />
    </svg>
    <span id="workspace-path" title="__CODING_AGENT_WORKSPACE_PATH__">__CODING_AGENT_WORKSPACE_PATH__</span>
  </span>
</div>
```

- [ ] **Step 5: Implement CSS and remove counter rendering**

Set `.brand-name { font-size: 20px; }`, remove `.workspace-name`, and add bounded path styles. Keep `.run-header` row count unchanged. On narrow screens cap `.workspace-path-fact` with viewport-relative width and hide elapsed only below the smallest existing breakpoint if both cannot fit.

Remove `runPhase` from element collection and make `renderRunHeader` write only status/cancel state. Do not remove `run_progress` parsing or budget-profile synchronization.

- [ ] **Step 6: Run focused header tests GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_gui.py -q -p no:cacheprovider
node --test --test-name-pattern="header|workspace path|MiniCodex" tests/js/web_gui.test.mjs
```

Expected: all selected tests pass; document security headers and marker-corruption tests remain green.

---

### Task 2: Safe fenced-code copy button

**Files:**

- Modify: `src/coding_agent/web_static/app.js`
- Modify: `src/coding_agent/web_static/styles.css`
- Test: `tests/js/web_gui.test.mjs`
- Test: `tests/test_web_gui.py`

**Interfaces:**

- Produces: `defaultClipboardWrite(text: string) -> Promise<void>` using only `navigator.clipboard.writeText`.
- Extends: `appendMessage(document, container, role, text, runMode = null, onCopyCode = null)`.
- Extends: `createUiController({... clipboardWrite, setTimeoutImpl, clearTimeoutImpl })` with callable injected dependencies.
- Produces fixed button states: `复制`, `复制中…`, `已复制`, `复制失败`; reset delay is exactly `1_500` ms.

- [ ] **Step 1: Write failing renderer and clipboard tests**

Add separately named Node tests proving:

```javascript
const writes = [];
const controller = gui.createUiController({
  document,
  elements,
  api,
  clipboardWrite: async (text) => { writes.push(text); },
  setTimeoutImpl: (callback, delay) => { timers.push({ callback, delay }); return timers.length; },
  clearTimeoutImpl: () => {},
});
```

- one closed fence creates one `.code-copy-button`;
- clicking copies `const value = "<tag>";` exactly without fence/language/trailing display newline;
- a second click while pending does not call clipboard twice;
- success becomes `已复制`, timer delay equals `1500`, and callback restores `复制`/enabled;
- rejection becomes `复制失败` without exception content or connection notice;
- an unclosed fence and user Markdown create no copy button;
- malicious code stays a text node and creates no `img`, `script`, or handler attribute.

- [ ] **Step 2: Run copy tests RED**

Run:

```powershell
node --test --test-name-pattern="copy|clipboard|fenced code" tests/js/web_gui.test.mjs
```

Expected: copy controls/dependencies are absent.

- [ ] **Step 3: Implement deterministic code-block DOM**

For each closed fence, compute `const codeText = codeLines.join("\n")`, then create:

```javascript
const wrapper = document.createElement("div");
wrapper.className = "code-block";
const button = document.createElement("button");
button.type = "button";
button.className = "code-copy-button";
button.setAttribute("aria-label", "复制代码");
appendPlainText(document, button, "复制");
button.disabled = typeof onCopyCode !== "function";
button.addEventListener("click", () => onCopyCode?.(button, codeText));
wrapper.append(button, pre);
```

Pass `onCopyCode` through recursive blockquote rendering. Keep code display text in `code` via `appendPlainText`; never store `codeText` in an attribute.

- [ ] **Step 4: Implement injected clipboard state machine**

Validate `clipboardWrite`, `setTimeoutImpl`, and `clearTimeoutImpl` as callables. Track reset IDs in `copyResetTimers`; clear them in `destroy()`.

On click, ignore disabled buttons, set `复制中…`, then use `Promise.resolve().then(() => clipboardWrite(codeText))`. Map fulfillment/rejection only to fixed Chinese labels, schedule exact 1500 ms reset, and never route clipboard errors through `track()` or `setConnectionNotice()`.

- [ ] **Step 5: Style the copy control**

Use `.code-block { position: relative; }`, preserve horizontal scrolling on `pre`, and position the warm secondary button at the top-right with sufficient code padding. Add hover, focus-visible, disabled, success, and failure states through fixed classes/data state only.

- [ ] **Step 6: Run copy and Markdown regressions GREEN**

Run:

```powershell
node --test --test-name-pattern="Markdown|fence|copy|clipboard|markup" tests/js/web_gui.test.mjs
.\.venv\Scripts\python.exe -m pytest tests/test_web_gui.py -q -p no:cacheprovider
```

Expected: copy tests and existing Markdown/table/link/safe-text tests pass.

---

### Task 3: Active-only reply animation

**Files:**

- Modify: `src/coding_agent/web_static/app.js`
- Modify: `src/coding_agent/web_static/styles.css`
- Test: `tests/js/web_gui.test.mjs`
- Test: `tests/test_web_gui.py`

**Interfaces:**

- Extends: `appendActivity(document, container, kind, data, { active = false } = {})`.
- Produces: `.activity-card--active`, one `.activity-indicator`, and three `.activity-indicator__dot` children only when `active=true`.

- [ ] **Step 1: Write failing activity lifecycle tests**

Add Node assertions that `appendActivity(..., {active: true})` creates one hidden-from-accessibility indicator and three dots, while the default call creates none. Exercise `renderConversation` through controller state so current `tool_started` and provisional model text are active, then finish the run and assert the terminal/history DOM has no indicator.

Add a Python CSS contract requiring `@keyframes activity-pulse`, staggered delays, `.activity-card--active`, and a `prefers-reduced-motion: reduce` override with `animation: none` for indicator dots.

- [ ] **Step 2: Run animation tests RED**

Run:

```powershell
node --test --test-name-pattern="indicator|animation|activity" tests/js/web_gui.test.mjs
.\.venv\Scripts\python.exe -m pytest tests/test_web_gui.py -k "animation or activity" -q -p no:cacheprovider
```

Expected: indicator DOM/classes/keyframes are absent.

- [ ] **Step 3: Implement active indicator DOM**

Build the activity label/details inside a fixed `.activity-card__content` span. For `active=true`, add the active class and prepend:

```javascript
const indicator = document.createElement("span");
indicator.className = "activity-indicator";
indicator.setAttribute("aria-hidden", "true");
for (let index = 0; index < 3; index += 1) {
  const dot = document.createElement("span");
  dot.className = "activity-indicator__dot";
  indicator.append(dot);
}
```

Pass `{active: true}` only in the two live branches at the end of `renderConversation`: current activity and provisional model text. Leave terminal/history/cancel calls unchanged.

- [ ] **Step 4: Implement subtle/reduced animation CSS**

Use flex alignment and three 5px dots. Apply a 1.1-second ease-in-out infinite opacity/translate pulse with `0ms`, `140ms`, and `280ms` delays. Under reduced motion set `animation: none`, `opacity: .55`, and `transform: none`.

- [ ] **Step 5: Run activity and SSE regressions GREEN**

Run:

```powershell
node --test --test-name-pattern="activity|indicator|terminal|SSE reducer|conversation" tests/js/web_gui.test.mjs
.\.venv\Scripts\python.exe -m pytest tests/test_web_gui.py tests/test_web_sse.py -q -p no:cacheprovider
```

Expected: active-only animation and all terminal/SSE safety behavior pass.

---

### Task 4: Documentation, review, and complete verification

**Files:**

- Modify: `docs/USAGE.md`
- Modify: `tests/test_docs.py`
- Verify: every locked production/test path
- Modify: `TASKS.md` only after implementation acceptance; keep Task31 `进行中` during this execution handoff.

**Interfaces:**

- Documents: exact absolute-path disclosure boundary, copy feedback, active-only animation, and removal of call counters.
- Produces: fresh offline verification evidence and local review findings.

- [ ] **Step 1: Add failing docs contract test**

Require `docs/USAGE.md` to contain all of:

```python
for required in (
    "工作区绝对路径",
    "代码块右上角",
    "已复制",
    "当前活动回复",
    "减少动态效果",
    "不写入 REST、SSE、SQLite、JSONL 或模型上下文",
):
    assert required in usage
```

- [ ] **Step 2: Update the Web GUI usage section**

Add one compact paragraph after the session/model controls. State that the visible absolute path is intentionally local/no-store, copying uses browser clipboard with fixed success/failure text, animation means only “still running,” and counters are no longer shown.

- [ ] **Step 3: Run focused cross-layer tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_gui.py tests/test_web_api.py tests/test_web_cli.py tests/test_docs.py -q -p no:cacheprovider
node --test tests/js/web_gui.test.mjs
```

Record actual counts and exit codes.

- [ ] **Step 4: Perform the core local code review**

Because the user did not authorize subagents, apply the `requesting-code-review` checklist locally. Inspect path marker cardinality/escaping, absence of path in API/events, exact clipboard text and stable error behavior, timer cleanup, active-only indicator lifecycle, reduced motion, responsive header overflow, unsafe sinks, and preservation of Task29/Task30 changes. Resolve every reproducible finding with a new RED/GREEN test.

- [ ] **Step 5: Invoke verification-before-completion and run the complete suites**

Run from fresh commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
node --test tests/js/web_gui.test.mjs
git diff --check
git status --short --untracked-files=all
```

Expected: both suites and whitespace check exit 0; report real counts.

- [ ] **Step 6: Run static policy audits**

Run:

```powershell
rg -n -i "langchain|llamaindex|openai-agents|autogen|crewai" pyproject.toml src tests
rg -n "innerHTML|outerHTML|insertAdjacentHTML|document\.write" src/coding_agent/web_static
rg -n "API_KEY\s*=|Bearer [A-Za-z0-9]|sk-[A-Za-z0-9]" src tests docs README.md README.txt DESIGN.md TASKS.md
```

Expected: no prohibited framework or production unsafe sink; credential matches are only documented variable names and explicit fake redaction/auth fixtures.

- [ ] **Step 7: Report without committing**

Present changed files, behavior, the deliberate local absolute-path disclosure, review findings, and exact verification output. Keep Task31 `进行中` until the user later accepts the implementation. Do not stage, commit, or push.

## Self-Review

- Spec coverage: Tasks 1–3 cover every layout, path, clipboard, animation, responsive, reduced-motion, and security requirement; Task 4 covers docs, review, and full verification.
- Placeholder scan: the plan contains no unfinished markers or unspecified implementation, error, or testing steps.
- Type consistency: the new `renderRunHeader`, `appendMessage`, `appendActivity`, clipboard, and timer names/signatures are defined once and used consistently by later steps.
- Scope: all changes stay inside the existing local Web document/static renderer and do not alter Agent, provider, Session, SQLite, tool, verification, or permission behavior.

# Web GUI Runtime Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the accepted Chat Completions streaming adapter tolerate BayesDL continuation placeholders, preserve the real model failure in the audit trail, and keep the local GUI responsive across failed runs and follow-ups.

**Architecture:** Keep the existing provider-neutral messages, Agent loop, session controller, REST/SSE API, and single-active-run invariant unchanged. Apply narrow compatibility handling at the Chat Completions stream boundary, align the audit logger with error codes already emitted by model adapters, and repair only the GUI's local cursor/rendering/event-delegation state.

**Tech Stack:** Python 3.11+, pytest, official OpenAI Python SDK types at the adapter boundary, vanilla JavaScript, Node.js built-in `node:test`.

**Spec:** `docs/superpowers/specs/2026-08-30-local-web-gui-design.md`, with the bounded defect design approved in the 2026-08-30 debugging conversation.

## Global Constraints

- Remain on the current `main` worktree; do not create a branch or worktree.
- Do not call a real provider or read a real API key from tests.
- Do not change `ModelClient.complete(ModelRequest) -> ModelResponse`, message types, tool schemas, Agent loop semantics, session persistence, REST/SSE routes, or security policy.
- Preserve strict final tool-call validation: every completed call still requires one non-empty unique `call_id`, type `function`, a non-empty name, and JSON-object arguments.
- Do not add dependencies, stage, commit, push, pull, fetch, or modify remotes.
- Keep Task 23 `进行中` for user review.

## File Map

- Modify `src/coding_agent/chat_completions_client.py`: ignore an exact empty-string continuation placeholder only after the corresponding stable tool field has already been established.
- Modify `tests/test_chat_completions_streaming_client.py`: reproduce the BayesDL multi-fragment tool call and retain first-fragment/final completeness rejection.
- Modify `src/coding_agent/logging.py`: accept every stable provider-attempt failure code already emitted by the model/streaming layers.
- Modify `tests/test_logging.py`: prove adapter failures are recorded as provider failures rather than becoming `RunLogError`.
- Modify `src/coding_agent/web_static/app.js`: reset the SSE cursor when the active run changes, reload durable follow-up state before rendering, delegate nested session clicks, and render the safe terminal reason.
- Modify `tests/js/web_gui.test.mjs`: exercise all four browser-visible regressions with the real controller/reducer.
- Create this plan only; do not modify `TASKS.md` or public documentation.

---

### Task 1: Chat Completions continuation placeholders

**Interfaces:**

- Consumes `_stable_fragment(current: str | None, incoming: object, *, field_name: str) -> str | None` and the existing stream aggregation path.
- Produces the unchanged `ModelResponse`/`ToolCall` result.

- [ ] **Step 1: Add the failing compatibility test**

Add a test whose fake stream contains a first tool fragment with `id="call-1"`, `type="function"`, name `inspect_workspace`, and the first arguments fragment; later fragments for the same index contain `id=""` and only more arguments. Assert that `client.stream(...)` returns exactly one `ToolCall("call-1", "inspect_workspace", {"path": "."})`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
\.\.venv\Scripts\python.exe -m pytest tests/test_chat_completions_streaming_client.py -k "blank_continuation_identifier" -q -p no:cacheprovider --basetemp .pytest-tmp/runtime-fix-stream-red
```

Expected: exit `1`; `InvalidChatCompletionsResponseError` reports `tool identifier is invalid`.

- [ ] **Step 3: Implement the minimum compatibility rule**

In `_stable_fragment`, return the already-established `current` value only when `incoming == ""` and `current is not None`. Keep the existing rejection for an empty first fragment, whitespace-only fragments, non-strings, changed non-empty values, duplicate call IDs, incomplete calls, and malformed arguments.

- [ ] **Step 4: Verify GREEN and strictness regression**

Run:

```powershell
\.\.venv\Scripts\python.exe -m pytest tests/test_chat_completions_streaming_client.py -k "blank_continuation_identifier or invalid_tool or additional_invalid_shapes or incomplete" -q -p no:cacheprovider --basetemp .pytest-tmp/runtime-fix-stream-green
```

Expected: exit `0`; the compatibility case and existing invalid-first/final-incomplete cases pass.

**Acceptance:** BayesDL-style empty continuation placeholders do not erase an established ID, while a stream that never supplies a valid ID remains invalid.

---

### Task 2: Audit provider error-code alignment

**Interfaces:**

- Consumes `RunEventLogger.observe(ModelObservation)` and existing stable model/stream error codes.
- Produces the unchanged `provider_attempt_failed` JSONL envelope.

- [ ] **Step 1: Add the failing logger tests**

Add a parameterized test that sends `ModelObservationKind.PROVIDER_FAILED` observations carrying `invalid_model_response`, `streaming_unsupported`, `stream_interrupted`, `model_client_error`, `transient_model_error`, and `fatal_model_error`. Assert each is flushed as the exact safe `error_code` without raising `RunLogError`, provider content, or credentials.

- [ ] **Step 2: Verify RED**

Run:

```powershell
\.\.venv\Scripts\python.exe -m pytest tests/test_logging.py -k "adapter_provider_error_codes" -q -p no:cacheprovider --basetemp .pytest-tmp/runtime-fix-logging-red
```

Expected: exit `1`; the first adapter-layer code outside `_PROVIDER_ERROR_CODES` raises `RunLogError("invalid_event_data")`.

- [ ] **Step 3: Implement the minimum whitelist alignment**

Build `_PROVIDER_ERROR_CODES` from the existing provider transport codes, `_MODEL_ERROR_CODES`, and the two streaming lifecycle codes `streaming_unsupported` and `stream_interrupted`. Do not allow arbitrary strings and do not change event keys or redaction.

- [ ] **Step 4: Verify GREEN and logging regression**

Run:

```powershell
\.\.venv\Scripts\python.exe -m pytest tests/test_logging.py -q -p no:cacheprovider --basetemp .pytest-tmp/runtime-fix-logging-green
```

Expected: exit `0`; valid adapter failures are logged and unknown error codes remain rejected.

**Acceptance:** an adapter parsing failure remains `invalid_model_response`; the audit logger no longer replaces it with `audit_log_failure`.

---

### Task 3: GUI run lifecycle and interaction repair

**Interfaces:**

- Consumes the unchanged `createUiController`, `consumeRunStream`, `reduceSessionUpdate`, session-detail DTO, and SSE envelopes.
- Produces the same controller API and DOM structure with corrected observable behavior.

- [ ] **Step 1: Add failing run-cursor and follow-up tests**

Extend the selected-idle-session controller fixture so its second `loadSession` result contains the newly persisted `user_message` and new run. Assert after submit, before any session switch, that the conversation contains `Continue`; assert the new stream receives `lastSequence == 0` even if the preceding failed run left a larger sequence.

- [ ] **Step 2: Verify RED**

Run:

```powershell
node --test --test-name-pattern "follow-up immediately|new run cursor" tests/js/web_gui.test.mjs
```

Expected: exit `1`; current code neither reloads the durable user event nor resets `lastSequence` before opening the new run.

- [ ] **Step 3: Implement durable follow-up reload and run-bound cursor reset**

After `submitFollowUp`, call the existing `selectSession(handle.session_id)` rather than hand-building a partial run. In `selectSession`, compare the previous and next active run IDs and set `state.lastSequence = 0` before starting a different run. Preserve the cursor when reconnecting the same active run.

- [ ] **Step 4: Verify first GUI GREEN**

Run the same Node command. Expected: exit `0`; the accepted message renders from server state and the new run starts from SSE sequence zero.

- [ ] **Step 5: Add the failing nested-click test**

Dispatch the session-list click with the rendered status `<span>` as `event.target`. Assert that its ancestor button's session ID is selected.

- [ ] **Step 6: Verify nested-click RED**

Run:

```powershell
node --test --test-name-pattern "nested session content" tests/js/web_gui.test.mjs
```

Expected: exit `1`; `event.target.dataset.sessionId` is absent.

- [ ] **Step 7: Implement bounded ancestor lookup**

Walk `parentNode` from the click target up to, but not beyond, `sessionList`; select the first element with a non-empty `data-session-id`. Ignore clicks outside a session button.

- [ ] **Step 8: Verify nested-click GREEN**

Run the same Node command. Expected: exit `0`.

- [ ] **Step 9: Add the failing terminal-reason test**

Apply a `run_finished` frame with `status="failed"` and `termination_reason="invalid_model_response"`. Assert the matching run stores the reason and the rendered conversation contains a plain-text failure activity with that stable reason, without rendering unrecognized/private payload fields.

- [ ] **Step 10: Verify terminal-reason RED**

Run:

```powershell
node --test --test-name-pattern "safe terminal reason" tests/js/web_gui.test.mjs
```

Expected: exit `1`; current reducer drops `termination_reason` and the conversation renders no explanation.

- [ ] **Step 11: Implement safe terminal-reason projection**

For `run_finished`, copy only a string-or-null `termination_reason` onto the matching run. Render one plain-text `run_failed` activity from the selected failed run using only that field. Do not render exception bodies, tracebacks, paths, provider data, or arbitrary event fields.

- [ ] **Step 12: Verify GUI GREEN and full GUI regression**

Run:

```powershell
node --test tests/js/web_gui.test.mjs
\.\.venv\Scripts\python.exe -m pytest tests/test_web_gui.py tests/test_web_api.py tests/test_web_sse.py -q -p no:cacheprovider --basetemp .pytest-tmp/runtime-fix-gui-green
```

Expected: both commands exit `0` with no skipped tests.

**Acceptance:** follow-ups render immediately, each new run starts with its own cursor, nested session content is clickable, and failures display only the stable server-provided reason.

---

### Task 4: Offline regression and review evidence

- [ ] **Step 1: Run focused combined tests**

```powershell
\.\.venv\Scripts\python.exe -m pytest tests/test_chat_completions_streaming_client.py tests/test_logging.py tests/test_session_controller.py tests/test_web_api.py tests/test_web_sse.py tests/test_web_gui.py -q -p no:cacheprovider --basetemp .pytest-tmp/runtime-fix-focused
node --test tests/js/web_gui.test.mjs
```

- [ ] **Step 2: Run the complete offline suite**

```powershell
\.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .pytest-tmp/runtime-fix-full
```

- [ ] **Step 3: Audit scope and hygiene**

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
rg -n "OPENAI_API_KEY|CHAT_COMPLETIONS_API_KEY|Authorization: Bearer|sk-[A-Za-z0-9_-]{8,}" src tests docs/superpowers/plans/2026-08-30-web-gui-runtime-fixes.md
rg -n "TODO|TBD|FIXME|skip|xfail" src/coding_agent/chat_completions_client.py src/coding_agent/logging.py src/coding_agent/web_static/app.js tests/test_chat_completions_streaming_client.py tests/test_logging.py tests/js/web_gui.test.mjs
```

Expected: whitespace clean; only the planned files differ; no real credential, new dependency, skip/xfail, network test, server-side conversation, or unrelated refactor appears.

- [ ] **Step 4: Stop for user review**

Keep Task 23 `进行中`. Report every RED/GREEN command and actual result. Do not stage, commit, push, or begin another task.

## Self-Review

- Requirement coverage: all five confirmed root causes map to named tests and one minimal production change.
- Placeholder scan: the plan contains no unfinished implementation placeholder.
- Type consistency: all changes reuse existing Python and JavaScript public interfaces.
- Scope: no Agent, session, REST/SSE, security, CLI, dependency, or task-status change is included.
- Off-network guarantee: provider behavior is represented only by fake SDK chunks; no test reads environment credentials.

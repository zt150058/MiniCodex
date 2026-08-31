# Modify-Mode Reliability Implementation Plan

> Required workflow: `superpowers:executing-plans`,
> `superpowers:test-driven-development`, `superpowers:systematic-debugging` for
> unexpected failures, and `superpowers:verification-before-completion`.

**Goal:** Close Task26 by fixing modify-mode answer convergence, introducing a
fresh local integrity verification fallback when `--verify` is absent, and
recovering once from provider output limits without broadening command safety.

**Spec:** `docs/superpowers/specs/2026-08-31-modify-mode-reliability-design.md`.

## Locked file map

Production files may be modified only where required by the behavior below:

- `src/coding_agent/model.py`
- `src/coding_agent/chat_completions_client.py`
- `src/coding_agent/openai_client.py`
- `src/coding_agent/state.py`
- `src/coding_agent/agent.py`
- `src/coding_agent/termination.py`
- `src/coding_agent/verification.py`
- `src/coding_agent/safety.py`
- `src/coding_agent/report.py`
- `src/coding_agent/logging.py`
- `src/coding_agent/session.py`
- `src/coding_agent/session_store.py`
- `src/coding_agent/session_runtime.py`
- `src/coding_agent/session_events.py`
- `src/coding_agent/instructions.py`
- `src/coding_agent/web_static/app.js`
- public documentation and `TASKS.md`.

Tests may be added or changed only in the corresponding existing unit,
integration, Session, Web/GUI, and documentation test modules. No dependency,
network call, real credential, branch, worktree, stage, commit, or push is
allowed.

## Task 0: Baseline and characterization

1. Run `git status --short --untracked-files=all`, `git diff --check`, and the
   complete offline suite. Expected GREEN: the approved Task26 dirty baseline
   has no unrelated modification and all tests pass.
2. Add offline characterization tests for:
   - modify + optional gate + one text response currently repeating;
   - write + optional gate + completion currently becoming
     `changes_unverified`;
   - Chat sync/stream `finish_reason="length"` currently raising generic
     invalid response and Agent repeating it three times.
3. Run each exact test with `python -m pytest -q -p no:cacheprovider <path>::<test>`.
   Expected RED: assertions fail only because the new terminal/error contracts
   do not exist.

## Task 1: Provider-neutral model failure taxonomy

1. RED tests define `InvalidModelResponseError` and `ModelOutputLimitError`,
   fixed codes `invalid_model_response`/`model_output_limit`, Chat sync and
   stream `length`, Responses `incomplete/max_output_tokens`, and malformed
   response behavior. Tests assert one provider attempt and absence of sentinel
   body/partial text in exceptions, observations, and repr.
2. Implement the two classes in `model.py`; make both provider-specific invalid
   classes subclass `InvalidModelResponseError`; map only the documented output
   limit shapes to `ModelOutputLimitError`.
3. GREEN commands:
   - `python -m pytest -q -p no:cacheprovider tests/test_model.py`
   - `python -m pytest -q -p no:cacheprovider tests/test_chat_completions_client.py tests/test_chat_completions_streaming_client.py -k "length or invalid"`
   - `python -m pytest -q -p no:cacheprovider tests/test_openai_client.py -k "incomplete or invalid"`
4. Regression: run all model/provider/streaming tests. Acceptance: Task9 and
   Chat accepted mappings and adapter retry counts are unchanged.

## Task 2: Bounded output-limit recovery

1. RED Agent tests script output-limit then a one-file tool call and valid
   completion; assert the second request alone contains the fixed temporary
   recovery instruction, no partial text/history entry exists, and success
   resets the consecutive counter. A second test scripts two consecutive
   output limits and asserts exactly two main/provider calls, no tool execution,
   and `TerminationReason.MODEL_OUTPUT_LIMIT`. A malformed response test asserts
   immediate `INVALID_MODEL_RESPONSE` after one call.
2. Add the exact state counters and termination enum values. Catch the two new
   types before generic `ModelError`. Do not catch `FatalModelError`, budget
   errors, `KeyboardInterrupt`, or `SystemExit`.
3. GREEN: `python -m pytest -q -p no:cacheprovider tests/test_agent_loop.py -k "output_limit or invalid_model_response"`.
4. Regression: Agent, termination, streaming, report, logging, Session event,
   and integration failure tests. Acceptance: the first correction remains
   subject to all existing budgets and cannot execute partial calls.

## Task 3: Capability-mode `ANSWERED`

1. RED tests cover a production-shaped modify run with optional gate and one
   text response, report projection, Session persistence/runtime, SSE, and GUI
   header. Assert one main/provider call, zero tools/mutations/verifications,
   `FINISH/ANSWERED`, exit 0, and preserved `run_mode="modify"`.
2. Generalize only the run-mode restriction in Agent/report/Session invariants;
   retain every zero-mutation, zero-verification, nonempty-text condition.
3. GREEN: run the exact Agent/report/Session/GUI tests, then their complete
   modules. Acceptance: a modify request that did mutate can never use
   `ANSWERED`; `SUCCESS` still requires fresh passing evidence.

## Task 4: Local integrity verification fallback

1. RED verification tests create changed UTF-8 files under `tmp_path` and cover
   Markdown, C++, valid/invalid Python, JSON and TOML, multiple paths,
   missing/directory/reparse/protected paths, over-limit bytes, stale mutation,
   existing failed evidence, and required `--verify`. Assert exact source
   `local_integrity`, command label, validation index, safe relative output,
   one attempt, and no absolute paths/content.
2. Implement a private deterministic validator in `verification.py` using
   `PathGuard`. Add `CommandSource.LOCAL_INTEGRITY`. Expose a gate predicate so
   `AgentRunner` performs the normal verification budget precheck and emits the
   existing started/completed events before evaluating it.
3. RED/GREEN integration tests:
   - `write README -> completion` ends fresh `SUCCESS`;
   - `write Python -> completion` validates syntax;
   - failed model verification remains failed and never invokes integrity;
   - failed user `--verify` remains `changes_unverified`.
4. Run `python -m pytest -q -p no:cacheprovider tests/test_verification.py tests/test_agent_loop.py tests/integration/test_agent_repair.py tests/integration/test_agent_failures.py`.
   Acceptance: no arbitrary command or compiler was authorized.

## Task 5: Projection, GUI, instructions, and documentation

1. RED strict-schema tests require `local_integrity` in evidence, modify-mode
   `answered`, and safe output-limit/invalid-response reasons through report,
   Session, SSE and GUI. Documentation tests require the verification ladder,
   output splitting, and explicit C++ compile limitation.
2. Update allowlists and renderers without logging content. The GUI labels
   modify-mode `answered` as `已回答` and integrity success as completed; details
   come only from the bounded report fields.
3. GREEN exact projection/GUI/docs suites, then Node GUI tests.
4. Acceptance: database schema is unchanged; old records decode; secrets,
   provider payloads, partial text, absolute paths and hidden control never
   cross the boundary.

## Task 6: Final Task26 verification and transition gate

Run fresh:

```powershell
python -m pytest -q -p no:cacheprovider
node --test tests/js/web_gui.test.mjs
python -m pip check
git diff --check
git status --short --untracked-files=all
git diff --stat
```

Also run the existing Windows reparse/junction and timeout/process-tree exact
tests plus scans for credentials, personal absolute paths, SDK leakage, Agent
frameworks, `TODO|TBD|FIXME`, and `skip|xfail`. Review the complete diff.

Only after every Task26 acceptance row has fresh evidence, change Task26 to
`已完成` and Task27 to `进行中`. Do not commit. If any evidence is absent, leave
Task26 `进行中` and do not start Task27.

## Acceptance matrix

| Requirement | Evidence |
|---|---|
| Modify knowledge answer does not repeat | Agent + app/Session integration |
| `ANSWERED` keeps zero-fact invariant | Agent, report, Session strict tests |
| README/plain source can finish without forced command | integrity integration |
| Mandatory verifier cannot fall back | verification + Agent tests |
| Failed evidence cannot be overwritten | verification freshness test |
| Chat `length` is distinct | sync + streaming adapter tests |
| Responses max-output incomplete is distinct | Responses adapter test |
| One recovery then bounded stop | Agent off-by-one tests |
| Invalid completed payload is not blindly retried | Agent one-call test |
| Partial stream/tool JSON never executes or persists | streaming/controller tests |
| No shell/compiler authority expansion | safety and registry regressions |
| Privacy and offline boundaries | scans + injected fake tests |
| Task1-Task25 remain green | complete offline suite |


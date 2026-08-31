# Adaptive Agent Convergence and Layered Budgets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` and `superpowers:test-driven-development` to implement this plan task-by-task. Use `superpowers:systematic-debugging` before changing code for any reproducible unexpected failure, and use `superpowers:verification-before-completion` before reporting completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic phase/progress control, separate main and summary model budgets, high/low-water context compaction, run-scoped summary fallback and exploration memory, `standard`/`deep` per-run profiles, and bounded decision/verification recovery without weakening existing run modes, safety, verification, streaming, sessions, or provider boundaries.

**Architecture:** `budget.py` owns immutable profile values, while `progress.py` owns provider-neutral phase, convergence state, run-scoped exploration observations, response-level final-read allowance, and the deterministic two-step decision-required handshake. `AgentRunner` remains the only orchestration loop and composes these controls with the existing `ModelCallBudget`, `ContextManager`, `TerminationPolicy`, `VerificationGate`, event log, Session stack, and GUI; after compression it exposes only bounded safe exploration coverage, and after a real mutation it derives whether changes are unverified without rewriting commands. Model/provider adapters retain their accepted request and response mappings; no SDK type enters the new modules.

**Tech Stack:** Python 3.11+, standard-library dataclasses/enums/hashlib/json, pytest, SQLite, existing FastAPI/Pydantic transport, existing dependency-free HTML/CSS/JavaScript GUI, Node's built-in test runner.

**Spec:** `DESIGN.md` sections 6, 11, 15, and 20, `TASKS.md` Task 26, and the approved amendment specification in this plan.

## Global Constraints

- Implement directly in the existing synchronous single-Agent architecture; do not add a Planner, Agent framework, multi-Agent execution, MCP, tokenizer, or dependency.
- `RunMode` remains the explicit immutable capability boundary. `BudgetProfile` never grants tools or authority.
- `ModelClient.complete(ModelRequest) -> ModelResponse`, tool schemas, Task8 safety policies, Task11 verification success rules, and provider request/response mappings remain compatible.
- Default tests are completely offline and must not read a real API key or access a network endpoint.
- `standard` values are exactly main `24`, summary `4`, provider `48`, summary-provider `8`, tools `80`, runtime `1200.0` seconds.
- `deep` values are exactly main `40`, summary `6`, provider `80`, summary-provider `12`, tools `140`, runtime `1800.0` seconds.
- Context values are exactly hard chars `60_000`, trigger chars `48_000`, target chars `33_000`, hard items `24`, trigger items `20`, target items `12`.
- Standard convergence thresholds are main turns `4`, read tools `12`, idle turns `2`, post-checkpoint turns `2`; deep values are `6`, `24`, `3`, `3`. Both profiles use a final-decision threshold of four remaining main calls.
- After an ordinary exploration checkpoint, `standard` permits exactly one additional model response that attempts read tools and `deep` permits exactly two; the next request is decision-required and further read tools are paired but not executed. A duplicate-only read turn closes reads immediately instead of receiving this allowance.
- A rejected command is never rewritten or executed. The first safety rejection may be followed by at most two corrective model responses under the existing consecutive-three safety limit.
- `required_verification_pending` remains exclusive to a user-supplied forced `--verify`; model-selected verification uses the derived `AgentState.has_unverified_changes` property and must not consume or create a forced-verification reservation.
- Every provider request claims its global attempt immediately before the SDK request. Summary attempts also claim the summary-provider sub-budget.
- All caps allow the last legal operation and reject the first illegal operation without incrementing past the cap.
- Do not store or render control instructions, summary bodies, provider payloads, continuation data, hidden reasoning, credentials, Authorization headers, exception bodies, or host absolute workspace paths.
- Do not stage, commit, push, pull, fetch, create a branch/worktree, or modify a remote unless the user separately authorizes it.
- At the final review stop, Task26 remains `进行中`.

## Approved Corrective Design Amendment: Run-Scoped Exploration Memory

The 2026-08-31 real README-generation run reproduced a cross-component failure rather than a hard-budget exhaustion: Deep mode made 9 main calls and 35 tool calls, compressed context three times, accepted an invalid semantic summary into deterministic fallback, then executed 19 exact duplicate reads before terminating in `discover/no_progress` with zero mutations. The following design is approved as part of Task26 and supersedes narrower successful-read assumptions elsewhere in this plan:

- Add a run-scoped `ExplorationLedger` separate from message history. It records read-tool name, safe normalized workspace-relative target, request/result SHA-256 fingerprints, result status, and mutation epoch; it never records file content, provider payload, continuation, credential, or host absolute path.
- Aggregate exploration by main-model response. A batch is novel when at least one successful read has a new request/result fingerprint. It is duplicate-only when it attempts reads but produces no novel result, mutation, verification, or completion progress.
- Count checkpoint read allowance by responses that attempt reads, including duplicates, not only by novel successful reads. Multiple reads in one response remain one batch.
- An ordinary threshold checkpoint retains exact Standard 1 / Deep 2 final read batches. A duplicate-only response activates `decision_required` immediately and receives no additional read allowance.
- Track decision attempts without strong progress. The first failed decision response must leave paired feedback in history and, if higher-priority hard budgets permit, receive exactly one corrective response. A second failed decision response terminates as `no_progress` without another model call.
- Keep the exploration ledger, checkpoint, and decision-handshake state across context compression. Clear provider continuation exactly as before. A real mutation starts a new mutation epoch so later repair inspection can be classified against the modified workspace without erasing prior coverage.
- Inject a bounded `Exploration coverage` control only after compression or while a checkpoint is active. Render only safe relative target labels, deterministic counts, and an omitted-item count. Observation collections stay repr-private and are excluded from JSONL, FinalReport, Session, REST, SSE, and GUI payloads.
- Accept summary output as either bare JSON or exactly one JSON code fence with only surrounding whitespace. The decoded value must still pass the existing exact-field, exact-type, size, and local-invariant validation. Extra prose, multiple objects, malformed fences, missing fields, or wrong types latch deterministic fallback.
- Expand fallback `files_examined` deterministically within `max_summary_chars`, preserving deduplicated safe relative targets in first-seen order instead of only the newest eight. Do not copy successful tool output into the ledger or fallback.
- Keep context hard/high/low watermarks, Standard/Deep hard budgets, provider interfaces, safety policy, verification freshness, `SUCCESS` invariants, run modes, and dependencies unchanged.

The implementation amendment must add strict TDD coverage for batched 4–5-file reads, real high-water compression, fenced-summary parsing, fallback target retention, duplicate-only turn detection, response-level batch equality, exact one-response decision recovery, same-batch rejected-read plus legal write, mutation-epoch rereads, and a README end-to-end flow that modifies and verifies instead of reaching `no_progress`. All tests remain offline and the final review stop remains uncommitted with Task26 `进行中`.

**Execution scope after this approval:** execute only `Corrective Task 0` through
`Corrective Task 6` below. The later unchecked sections are retained as the
already-executed pre-correction Task26 plan and audit trail; they must not be
re-run. Whenever historical wording differs from the corrective amendment,
the corrective amendment is authoritative.

**Second approved closure amendment (2026-08-31):** the real modify-mode
knowledge-answer, README-generation, and long C++-generation failures are
governed by
`docs/superpowers/specs/2026-08-31-modify-mode-reliability-design.md` and
`docs/superpowers/plans/2026-08-31-modify-mode-reliability.md`. That amendment
supersedes the earlier restrictions that `ANSWERED` requires `read_only`, that
an optional gate must immediately fail the first unverified completion, and
that output-limit responses are generic consecutive model errors. It does not
supersede forced `--verify`, Task8 safety, verification freshness, privacy,
offline, or no-arbitrary-command constraints. Execute the new closure plan
before marking Task26 complete or starting Task27.

## Corrective Amendment Locked File Map

### Modify production

- `src/coding_agent/progress.py` — exploration observations, response-level read accounting, duplicate-only detection, bounded coverage rendering, and exact decision handshake.
- `src/coding_agent/context.py` — strict single-fence JSON normalization and deterministic first-seen fallback target retention.
- `src/coding_agent/agent.py` — mutation-epoch observation, compression notification, safe coverage injection, and decision-handshake integration.
- `src/coding_agent/logging.py` — exact allowlist addition for the safe `duplicate_only_turn` checkpoint reason only.
- `src/coding_agent/session_events.py` — accept the same exact safe checkpoint reason without changing the event shape or database schema.

### Modify tests

- `tests/test_progress.py`
- `tests/test_context.py`
- `tests/test_agent_loop.py`
- `tests/test_logging.py`
- `tests/test_session_events.py`
- `tests/integration/test_adaptive_convergence.py`
- `tests/integration/test_chat_completions_agent.py` — explicitly approved
  follow-up contract update for temporary post-compression coverage injection.
- `tests/integration/test_agent_failures.py` — explicitly approved follow-up
  contract update for the two-response duplicate-read decision handshake.
- `tests/test_docs.py`

### Modify documentation after behavior is green

- `AGENTS.md`
- `DESIGN.md`
- `TASKS.md`
- `README.md`
- `README.txt`
- `docs/USAGE.md`
- `docs/superpowers/plans/Task26.md`

### Must remain unchanged for this amendment

- `src/coding_agent/messages.py`, `model.py`, both provider adapters, `state.py`, `termination.py`, `verification.py`, all Task8 safety and tool implementations, config/CLI/app composition, Session store/controller/runtime, REST/SSE code, GUI assets, and `pyproject.toml`.
- Public `ModelClient`, `ModelRequest`, `ModelResponse`, `ToolCall`, `ToolResult`, `AgentRunner.run`, provider mapping, tool schema, verification, run-mode, budget-profile, and persistence interfaces.

If implementation requires a file outside the modify lists or changes a protected public interface, stop for user approval instead of adapting the design.

---

### Corrective Task 0: Reconfirm the approved dirty-worktree baseline

**Files:** Read only.

**Interfaces:** No interface changes.

- [ ] **Step 1: Re-read the approved baseline and corrective amendment**

Read `AGENTS.md`, `DESIGN.md`, `TASKS.md`, this complete plan, `progress.py`, `context.py`, `agent.py`, `logging.py`, `session_events.py`, and every test in the corrective locked file map.

- [ ] **Step 2: Verify repository identity and approved worktree shape**

Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git log -5 --oneline
git status --short --untracked-files=all
git diff --check
```

Expected: root is `D:/code/coding_agent`, branch is the user-approved current branch, Task26 remains `进行中`, the worktree contains only the already approved Task26 body plus this corrective plan, `git diff --check` exits `0`, and nothing is staged. LF-to-CRLF notices are warnings, not whitespace errors.

- [ ] **Step 3: Run a fresh offline baseline**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-corrective-baseline
node --test tests/js/web_gui.test.mjs
```

Expected: both commands exit `0`; record actual Python passed/failed/skipped/warning counts and actual Node passed/failed/skipped counts. Any failure blocks the amendment.

**Acceptance:** the executor starts from the exact approved Task26 worktree and has fresh green baseline evidence.

---

### Corrective Task 1: Add run-scoped exploration observations and bounded coverage

**Files:**

- Modify: `src/coding_agent/progress.py`
- Test: `tests/test_progress.py`

**Interfaces:**

- Retains `ProgressLedger.begin_main_turn() -> None`, `observe_tool(...) -> ProgressStrength`, `finish_main_turn() -> ProgressStrength`, and `render_execution_control(...) -> str` for existing callers.
- Adds exact provider-neutral types in `progress.py`:

```python
class ExplorationNovelty(StrEnum):
    NOT_READ = "not_read"
    NOVEL = "novel"
    DUPLICATE = "duplicate"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ExplorationObservation:
    tool_name: str
    target_label: str | None = field(repr=False)
    request_fingerprint: str
    result_fingerprint: str
    mutation_epoch: int
    status: str


@dataclass(frozen=True, slots=True)
class ExplorationTurnSummary:
    attempted_reads: int
    novel_reads: int
    duplicate_reads: int
    failed_reads: int

    @property
    def duplicate_only(self) -> bool: ...


@dataclass(slots=True)
class ExplorationLedger:
    observations: list[ExplorationObservation] = field(
        default_factory=list,
        repr=False,
    )
    attempted_read_batches: int = 0
    novel_read_batches: int = 0
    duplicate_only_turns: int = 0
    context_compacted: bool = False

    def begin_turn(self) -> None: ...
    def observe(
        self,
        call: ToolCall,
        result: ToolResult,
        *,
        mutation_epoch: int,
    ) -> ExplorationNovelty: ...
    def finish_turn(self) -> ExplorationTurnSummary: ...
    def mark_context_compacted(self) -> None: ...
    def render_coverage(
        self,
        *,
        max_chars: int = 4096,
        force: bool = False,
    ) -> str | None: ...
```

- Adds `exploration: ExplorationLedger = field(default_factory=ExplorationLedger)` to `ProgressLedger`; observation collections and target labels remain repr-private.
- Extends `ProgressLedger.observe_tool` with keyword-only `mutation_epoch: int = 0`; existing tests and third-party callers that omit it remain compatible.

- [ ] **Step 1: Write RED tests for novelty, duplicate detection, epoch reset, and failed reads**

Add tests with this structure to `tests/test_progress.py`:

```python
def _read(path: str, call_id: str = "call") -> ToolCall:
    return ToolCall(
        call_id,
        "read_file",
        {"path": path, "start_line": 1, "end_line": None},
    )


def _read_result(call: ToolCall, output: str = "1: value") -> ToolResult:
    return ToolResult(call.call_id, call.name, "ok", output=output)


def test_exploration_ledger_classifies_exact_duplicate_within_epoch() -> None:
    ledger = ExplorationLedger()
    call = _read("src\\app.py")
    result = _read_result(call)

    ledger.begin_turn()
    assert ledger.observe(call, result, mutation_epoch=0) is ExplorationNovelty.NOVEL
    first = ledger.finish_turn()
    ledger.begin_turn()
    assert ledger.observe(call, result, mutation_epoch=0) is ExplorationNovelty.DUPLICATE
    second = ledger.finish_turn()

    assert first == ExplorationTurnSummary(1, 1, 0, 0)
    assert second == ExplorationTurnSummary(1, 0, 1, 0)
    assert second.duplicate_only is True


def test_same_read_after_mutation_epoch_is_novel() -> None:
    ledger = ExplorationLedger()
    call = _read("src/app.py")
    result = _read_result(call)
    ledger.begin_turn()
    ledger.observe(call, result, mutation_epoch=0)
    ledger.finish_turn()
    ledger.begin_turn()
    novelty = ledger.observe(call, result, mutation_epoch=1)
    assert novelty is ExplorationNovelty.NOVEL


def test_failed_read_has_no_visible_target_and_is_not_duplicate_only() -> None:
    ledger = ExplorationLedger()
    call = _read(r"..\outside.txt")
    result = ToolResult(call.call_id, call.name, "rejected", error="path rejected")
    ledger.begin_turn()
    assert ledger.observe(call, result, mutation_epoch=0) is ExplorationNovelty.FAILED
    summary = ledger.finish_turn()
    assert summary == ExplorationTurnSummary(1, 0, 0, 1)
    assert summary.duplicate_only is False
    assert ledger.observations[0].target_label is None
    assert "outside.txt" not in repr(ledger)
```

- [ ] **Step 2: Run RED for missing exploration interfaces**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-exploration-red tests/test_progress.py -k "exploration_ledger or mutation_epoch or visible_target"
```

Expected: nonzero exit because `ExplorationLedger`, `ExplorationNovelty`, and `ExplorationTurnSummary` do not exist.

- [ ] **Step 3: Implement safe classification and fingerprints**

In `progress.py`:

- Treat only `list_directory`, `read_file`, and `inspect_git` as reads.
- Hash request data as canonical JSON of tool name plus arguments; hash result data as canonical JSON of status, output, error, exit/timing/truncation flags, and changed paths.
- Use `(mutation_epoch, request_fingerprint, result_fingerprint)` as the exact novelty key.
- Count every read attempt in the turn; count `FAILED` for non-`ok` results; do not insert failed results into the novelty set.
- Build visible labels only for successful reads. Normalize successful file-tool paths lexically to `/`, reject drives, absolute roots and `..`, cap one label at 256 characters, and render `inspect_git` as `inspect_git:<first 12 request-hash characters>` rather than raw command text.
- Define `duplicate_only` as `attempted_reads > 0 and duplicate_reads == attempted_reads`; failed or mixed novel turns are not duplicate-only.

- [ ] **Step 4: Run GREEN and progress regressions**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-exploration-green tests/test_progress.py
```

Expected: exit `0`; record the actual passing count.

- [ ] **Step 5: Write RED tests for bounded deterministic coverage**

Add:

```python
def test_coverage_is_bounded_deterministic_and_content_free() -> None:
    ledger = ExplorationLedger()
    secret_body = "SECRET-MARKER-THAT-MUST-NOT-BE-RENDERED"
    for index in range(30):
        call = _read(f"src/module_{index:02d}.py", f"call-{index}")
        ledger.begin_turn()
        ledger.observe(call, _read_result(call, secret_body), mutation_epoch=0)
        ledger.finish_turn()
    ledger.mark_context_compacted()

    first = ledger.render_coverage(max_chars=512)
    second = ledger.render_coverage(max_chars=512)

    assert first == second
    assert first is not None and len(first) <= 512
    assert "Exploration coverage:" in first
    assert "unique targets: 30" in first
    assert "omitted targets:" in first
    assert secret_body not in first


def test_coverage_is_absent_before_compression_or_checkpoint() -> None:
    ledger = ExplorationLedger()
    assert ledger.render_coverage() is None
```

- [ ] **Step 6: Run coverage RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-coverage-red tests/test_progress.py -k "coverage"
```

Expected: nonzero exit because bounded coverage rendering is not implemented.

- [ ] **Step 7: Implement coverage rendering**

Render newest unique safe target labels while preserving their encounter order in the displayed subset. Include exact total unique, duplicate-result, and omitted-target counts. Return `None` unless `context_compacted` or explicit `force=True`; `AgentRunner` passes `force=state.progress.checkpoint_active`. Validate `force` as `bool` and `max_chars` as an integer in `[256, 12_000]`, and build output incrementally so the returned string never exceeds the cap.

- [ ] **Step 8: Run GREEN and Task2–Task10 regressions**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-coverage-green tests/test_progress.py tests/test_agent_loop.py tests/test_context.py tests/test_termination.py
```

Expected: exit `0`; record actual counts. Existing `ProgressLedger` behavior remains unchanged before integration in Corrective Task 3.

**Acceptance:** exact duplicates are identified across compressed history, mutation epochs permit necessary rereads, labels are safe and bounded, and no tool body enters coverage or repr.

---

### Corrective Task 2: Preserve summary interoperability and fallback navigation facts

**Files:**

- Modify: `src/coding_agent/context.py`
- Test: `tests/test_context.py`

**Interfaces:**

- Keeps `ContextManager.prepare(AgentState, ModelCallBudget) -> PreparedContext` unchanged.
- Adds private `_decode_summary_payload(text: str) -> object` and changes private `_fallback_summary` to accept `max_summary_chars: int`; no new public context API.
- Consumes `state.progress.exploration` only for safe target labels; `ContextManager` does not mutate progress or decision state.

- [ ] **Step 1: Write fenced-summary RED tests**

Add:

```python
def test_single_json_fence_is_accepted_as_model_summary(tmp_path: Path) -> None:
    state = make_compressible_state(tmp_path)
    response = ModelResponse(text=f"```json\n{valid_summary_json()}\n```")
    prepared = triggered_manager(FakeModelClient((response,))).prepare(
        state,
        ModelCallBudget(),
    )
    assert prepared.summary_source is SummarySource.MODEL
    assert prepared.summary_model_failed is False
    assert state.summary_fallback_latched is False


@pytest.mark.parametrize(
    "text",
    [
        "prefix\n```json\n{}\n```",
        "```json\n{}\n```\nsuffix",
        "```json\n{}\n```\n```json\n{}\n```",
        "```JSON\n{}\n```",
    ],
)
def test_noncanonical_fenced_summary_latches_fallback(
    tmp_path: Path,
    text: str,
) -> None:
    state = make_compressible_state(tmp_path)
    prepared = triggered_manager(
        FakeModelClient((ModelResponse(text=text),))
    ).prepare(state, ModelCallBudget())
    assert prepared.summary_source is SummarySource.FALLBACK
    assert state.summary_fallback_reason is SummaryFallbackReason.INVALID_SUMMARY
```

- [ ] **Step 2: Run fenced-summary RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-summary-fence-red tests/test_context.py -k "json_fence or fenced_summary"
```

Expected: nonzero exit because a fenced valid summary is currently passed directly to `json.loads` and falls back.

- [ ] **Step 3: Implement exact single-fence normalization**

Strip surrounding whitespace. Accept either the remaining bare JSON text, or a multiline value whose first line is the literal three-backtick marker with language `json`, whose last line is the literal three-backtick closing marker, and whose body contains no other three-backtick marker. Decode with `json.loads`, then retain every existing exact-field, exact-type, size, local-invariant, and exception rule. Do not accept arbitrary prose or scan for a JSON substring.

- [ ] **Step 4: Run GREEN and summary propagation regressions**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-summary-fence-green tests/test_context.py -k "summary or fallback or fatal or budget or base_exception"
```

Expected: exit `0`; bare JSON, fenced JSON, invalid summary fallback, fatal errors, budget errors, and `BaseException` behavior all pass.

- [ ] **Step 5: Write fallback target-capacity RED tests**

Add these helpers so every later name is concrete:

```python
def _populate_exploration(
    state: AgentState,
    paths: list[str],
    *,
    output: str,
) -> None:
    ledger = state.progress.exploration
    for index, path in enumerate(paths):
        call = ToolCall(
            f"coverage-{index}",
            "read_file",
            {"path": path, "start_line": 1, "end_line": None},
        )
        ledger.begin_turn()
        ledger.observe(
            call,
            ToolResult(call.call_id, call.name, "ok", output=output),
            mutation_epoch=0,
        )
        ledger.finish_turn()


def _fallback_files(tmp_path: Path, paths: list[str]) -> list[str]:
    state = make_compressible_state(tmp_path)
    _populate_exploration(state, paths, output="safe fixture body")
    prepared = triggered_manager(
        FakeModelClient((ModelError("ordinary summary failure"),))
    ).prepare(state, ModelCallBudget())
    return _parsed_summary(prepared.messages)["files_examined"]
```

Then add:

```python
def test_fallback_keeps_first_seen_safe_targets_within_summary_cap(
    tmp_path: Path,
) -> None:
    state = make_compressible_state(tmp_path)
    _populate_exploration(
        state,
        [f"src/file_{index:02d}.py" for index in range(20)],
        output="BODY-MUST-NOT-ENTER-SUMMARY",
    )
    prepared = triggered_manager(
        FakeModelClient((ModelError("ordinary summary failure"),))
    ).prepare(state, ModelCallBudget())
    parsed = _parsed_summary(prepared.messages)

    assert parsed["files_examined"][0].startswith("read_file:src/file_00.py")
    assert len(parsed["files_examined"]) > 8
    assert len(json.dumps(parsed, ensure_ascii=False)) <= 12_000
    assert "BODY-MUST-NOT-ENTER-SUMMARY" not in json.dumps(parsed)


def test_fallback_target_order_is_deterministic_and_deduplicated(
    tmp_path: Path,
) -> None:
    first = _fallback_files(tmp_path, ["b.py", "a.py", "b.py"])
    second = _fallback_files(tmp_path, ["b.py", "a.py", "b.py"])
    assert first == second
    assert first == ["read_file:b.py:1-null", "read_file:a.py:1-null"]
```

- [ ] **Step 6: Run fallback-capacity RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-fallback-paths-red tests/test_context.py -k "fallback_keeps or fallback_target_order"
```

Expected: nonzero exit because fallback currently retains only the newest eight file paths and does not merge exploration coverage.

- [ ] **Step 7: Implement bounded first-seen fallback targets**

Collect prior-summary targets, removed-turn safe paths, and `state.progress.exploration` safe labels in first-seen order. Deduplicate without sorting. Construct the fallback with zero targets, merge local invariants, then append one target at a time only while the resulting `ContextSummary.to_json()` stays within `max_summary_chars`. Keep existing newest-eight bounds for free-form facts, commands, and errors. Never append successful `ToolResult.output` or `error` as a target fact.

- [ ] **Step 8: Run GREEN and full context tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-fallback-paths-green tests/test_context.py
```

Expected: exit `0`; record actual count, with continuation clearing, complete tool pairs, summary latch, privacy, and hard-budget behavior unchanged.

**Acceptance:** compatible providers may return one strict JSON fence, invalid shapes still fall back, and deterministic fallback retains substantially more safe navigation state without copying content.

---

### Corrective Task 3: Integrate response-level convergence and exact decision recovery

**Files:**

- Modify: `src/coding_agent/progress.py`
- Modify: `src/coding_agent/agent.py`
- Test: `tests/test_progress.py`
- Test: `tests/test_agent_loop.py`

**Interfaces:**

- Adds `decision_attempts_without_progress: int = 0` to `ProgressLedger`.
- Uses exact new decision reason `duplicate_only_turn`.
- Keeps Standard/Deep `final_read_batch_limit` values `1` and `2`; changes their meaning from successful novel batches to responses that attempt reads after an ordinary checkpoint.
- Keeps all public Agent, model, context, tool, verification, and termination signatures unchanged.

- [ ] **Step 1: Write response-level accounting and duplicate-only RED tests**

Add to `tests/test_progress.py`:

```python
def _finish_read_turn(
    ledger: ProgressLedger,
    call: ToolCall,
    result: ToolResult,
    *,
    epoch: int = 0,
) -> ProgressStrength:
    ledger.begin_main_turn()
    ledger.observe_tool(
        call,
        result,
        mutation_advanced=False,
        verification_recorded=False,
        mutation_epoch=epoch,
    )
    return ledger.finish_main_turn()


def test_checkpoint_counts_duplicate_read_response_as_one_batch() -> None:
    ledger = ProgressLedger()
    call = _read("src/app.py")
    result = _read_result(call)
    _finish_read_turn(ledger, call, result)
    ledger.activate_checkpoint()
    _finish_read_turn(ledger, call, result)
    assert ledger.post_checkpoint_read_batches == 1


def test_duplicate_only_turn_closes_reads_without_final_allowance() -> None:
    ledger = ProgressLedger()
    call = _read("src/app.py")
    result = _read_result(call)
    _finish_read_turn(ledger, call, result)
    _finish_read_turn(ledger, call, result)

    decision = ledger.decide(
        ProgressLimits.for_profile(BudgetProfile.DEEP),
        remaining_main_calls=30,
    )

    assert decision == ProgressDecision(
        ProgressAction.DECISION_REQUIRED,
        "duplicate_only_turn",
    )
    assert ledger.decision_required is True
    assert ledger.post_checkpoint_read_batches == 0
```

- [ ] **Step 2: Run response-accounting RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-response-count-red tests/test_progress.py -k "duplicate_read_response or duplicate_only_turn"
```

Expected: nonzero exit because repeated observations return before incrementing `_turn_read_tools` and no duplicate-only decision exists.

- [ ] **Step 3: Implement response-level ProgressLedger integration**

Delegate read classification to `ExplorationLedger` from `observe_tool`. In `finish_main_turn`, consume exactly one `ExplorationTurnSummary`; when a checkpoint was already active, increment `post_checkpoint_read_batches` once whenever `attempted_reads > 0`, regardless of novelty or status. When `duplicate_only` is true and no strong progress occurred, latch a one-shot pending decision that `decide` returns as `DECISION_REQUIRED/duplicate_only_turn`; activate the checkpoint and set `decision_required` without consuming final-read allowance.

- [ ] **Step 4: Run GREEN and exact Standard/Deep boundary tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-response-count-green tests/test_progress.py -k "checkpoint or read_batch or duplicate or strong_progress"
```

Expected: exit `0`; ordinary Standard 1 / Deep 2 equality remains exact and duplicate-only closes reads immediately.

- [ ] **Step 5: Write exact decision-handshake RED tests**

Add unit and Agent tests:

```python
def test_first_failed_decision_gets_one_correction_then_stops() -> None:
    ledger = ProgressLedger(checkpoint_active=True, decision_required=True)
    limits = ProgressLimits.for_profile(BudgetProfile.DEEP)
    for expected in (1, 2):
        ledger.begin_main_turn()
        ledger.finish_main_turn()
        assert ledger.decision_attempts_without_progress == expected
        decision = ledger.decide(limits, remaining_main_calls=30)
        if expected == 1:
            assert decision.action is ProgressAction.CONTINUE
        else:
            assert decision == ProgressDecision(ProgressAction.STOP, "no_progress")


def test_duplicate_read_rejection_gets_one_model_reaction_that_can_write(
    tmp_path: Path,
) -> None:
    (tmp_path / "source.txt").write_text("source\n", encoding="utf-8")
    arguments = {"path": "source.txt", "start_line": 1, "end_line": None}
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(ToolCall("first", "read_file", arguments),)),
            ModelResponse(tool_calls=(ToolCall("repeat", "read_file", arguments),)),
            ModelResponse(tool_calls=(ToolCall("ignored", "read_file", arguments),)),
            ModelResponse(
                tool_calls=(ToolCall("write", "write_file", {
                    "path": "README.md",
                    "content": "# Project\n",
                }),)
            ),
            ModelResponse(text="README created."),
        ),
        tools=(ReadFileTool(), WriteFileTool()),
    )
    state = runner.run("create README")
    rejected = [
        item for item in state.messages
        if isinstance(item, ToolResult)
        and item.error is not None
        and item.error.startswith("agent_rejected:decision_required")
    ]
    assert len(rejected) == 1
    assert (tmp_path / "README.md").is_file()
    assert len(client.requests) == 5


def test_second_failed_decision_stops_without_extra_model_request(
    tmp_path: Path,
) -> None:
    (tmp_path / "source.txt").write_text("source\n", encoding="utf-8")
    arguments = {"path": "source.txt", "start_line": 1, "end_line": None}
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(ToolCall("first", "read_file", arguments),)),
            ModelResponse(tool_calls=(ToolCall("repeat", "read_file", arguments),)),
            ModelResponse(tool_calls=(ToolCall("ignored-1", "read_file", arguments),)),
            ModelResponse(tool_calls=(ToolCall("ignored-2", "read_file", arguments),)),
            ModelResponse(text="must not be requested"),
        ),
        tools=(ReadFileTool(),),
    )
    state = runner.run("inspect forever")
    assert state.termination_reason is TerminationReason.NO_PROGRESS
    assert len(client.requests) == 4
```

Use existing `runner`/gate/tool helpers instead of creating a second incompatible helper when implementing the final tests; keep the exact response sequence and assertions.

- [ ] **Step 6: Run decision-handshake RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-decision-handshake-red tests/test_progress.py tests/test_agent_loop.py -k "failed_decision or model_reaction or second_failed_decision"
```

Expected: nonzero exit because the current generic post-checkpoint limit terminates without tracking an exact corrective response.

- [ ] **Step 7: Implement exact handshake ordering**

At `begin_main_turn`, snapshot whether the turn starts with `decision_required`. At `finish_main_turn`, increment `decision_attempts_without_progress` only when that snapshot is true and the turn has no strong progress. In `decide`, process a pending duplicate-only signal first; then, while `decision_required` is true, allow attempts `0` and `1`, stop at equality `2`, and evaluate generic post-checkpoint turn limits only after this branch. `_record_strong_progress` clears checkpoint/decision attempt state but never clears `ExplorationLedger` observations.

In `AgentRunner`:

- Pass `state.mutation_index` to `observe_tool`.
- After `PreparedContext.compressed` succeeds, call `state.progress.exploration.mark_context_compacted()`.
- Append bounded coverage to temporary instructions when context was compressed or a checkpoint is active; never append it to `state.messages`.
- Preserve the current snapshot-before-batch rule so decision-required reads are rejected while legal mutation calls in the same response execute.
- Emit `DECISION_CHECKPOINT` with reason `duplicate_only_turn`; do not add target labels or fingerprints to any event.

- [ ] **Step 8: Run GREEN and Agent convergence regressions**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-decision-handshake-green tests/test_progress.py tests/test_agent_loop.py
```

Expected: exit `0`; record actual counts. Cancellation, multi-tool pairing, completion, verification, command correction, old no-progress, and exact-budget tests remain green.

- [ ] **Step 9: Prove temporary coverage and continuation lifecycle**

Add tests asserting:

```python
def test_compression_injects_coverage_without_persisting_it(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_text("x" * 50_000, encoding="utf-8")
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(ToolCall(
                "large-read",
                "read_file",
                {"path": "large.txt", "start_line": 1, "end_line": None},
            ),)),
            _summary_response(),
            ModelResponse(text="finished"),
        ),
        tools=(ReadFileTool(),),
        context_limits=ContextLimits(),
    )
    state = runner.run("inspect then finish")
    main_request = client.requests[-1]
    assert "Exploration coverage:" in (main_request.instructions or "")
    assert all(
        "Exploration coverage:" not in getattr(message, "content", "")
        for message in state.messages
    )
    assert state.continuation_items == ()


def test_short_uncompressed_run_does_not_inject_coverage(tmp_path: Path) -> None:
    runner, client = _runner(
        tmp_path,
        (ModelResponse(text="finished"),),
    )
    runner.run("finish directly")
    assert "Exploration coverage:" not in (client.requests[0].instructions or "")
```

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-coverage-agent tests/test_agent_loop.py -k "coverage or continuation"
```

Expected: exit `0`; coverage is temporary and provider-neutral, and continuation still clears atomically after compression.

**Acceptance:** the first repeated batch after compression forces action, the model sees rejection feedback before termination, exactly one corrective response is available, and no hard budget or verification invariant is bypassed.

---

### Corrective Task 4: Admit the new safe checkpoint reason without widening payloads

**Files:**

- Modify: `src/coding_agent/logging.py`
- Modify: `src/coding_agent/session_events.py`
- Test: `tests/test_logging.py`
- Test: `tests/test_session_events.py`

**Interfaces:**

- Existing `DECISION_CHECKPOINT` event data remains exactly `reason`, `phase`, and `main_calls_remaining`.
- The only new accepted reason is exact string `duplicate_only_turn`.
- No schema version, SQLite migration, REST/SSE field, GUI field, or new event type.

- [ ] **Step 1: Write allowlist RED tests**

Add:

```python
def test_duplicate_only_checkpoint_reason_is_auditable(tmp_path: Path) -> None:
    logger = RunEventLogger.create(tmp_path)
    event = logger.emit(
        EventType.DECISION_CHECKPOINT,
        {
            "reason": "duplicate_only_turn",
            "phase": "discover",
            "main_calls_remaining": 30,
        },
    )
    assert event.data["reason"] == "duplicate_only_turn"


def test_session_update_accepts_duplicate_only_checkpoint_reason() -> None:
    update = SessionUpdate(
        schema_version=SESSION_UPDATE_SCHEMA_VERSION,
        session_id=SESSION_ID,
        run_id=RUN_ID,
        sequence=1,
        timestamp_utc="2026-08-29T08:00:00.000000Z",
        kind=SessionUpdateKind.DECISION_CHECKPOINT,
        data={
            "reason": "duplicate_only_turn",
            "phase": "discover",
            "main_calls_remaining": 30,
        },
    )
    assert update.data["reason"] == "duplicate_only_turn"
```

Retain existing parameterized rejection of arbitrary reason strings and extra event keys.

- [ ] **Step 2: Run allowlist RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-checkpoint-reason-red tests/test_logging.py tests/test_session_events.py -k "duplicate_only_checkpoint"
```

Expected: nonzero exit because both exact allowlists reject the new reason.

- [ ] **Step 3: Add only the exact reason to both validators**

Add `duplicate_only_turn` to the existing reason sets. Do not alter required keys, schema version, redaction, Session projection, or persistence validation.

- [ ] **Step 4: Run GREEN and persistence-boundary regressions**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-checkpoint-reason-green tests/test_logging.py tests/test_session_events.py tests/test_session_controller.py tests/test_web_sse.py
```

Expected: exit `0`; record actual count, and arbitrary reason/payload tests remain rejected.

**Acceptance:** the new convergence reason is visible as a safe enum-like fact, while tool targets, fingerprints, summary text, and provider data remain absent from durable/UI payloads.

---

### Corrective Task 5: Reproduce the real README failure shape end to end

**Files:**

- Modify: `tests/integration/test_adaptive_convergence.py`
- Test: `tests/integration/test_adaptive_convergence.py`

**Interfaces:** Uses real `AgentRunner`, `ContextManager`, `ProgressLedger`, `ReadFileTool`, `WriteFileTool`, fake provider responses, and the existing fake verification executor. No real network, API key, subprocess, or provider SDK object.

- [ ] **Step 1: Write the realistic batched/compressed README RED fixture**

Create ten UTF-8 source files whose read results make the history cross the real `48_000` character trigger. Add these concrete helpers, using the existing `_verification_gate`, `_profile_policy`, and `_passing_verification_execution` definitions:

```python
def _read_batch(prefix: str, indexes: range) -> ModelResponse:
    return ModelResponse(
        tool_calls=tuple(
            ToolCall(
                f"{prefix}-{index}",
                "read_file",
                {
                    "path": f"source-{index}.txt",
                    "start_line": 1,
                    "end_line": None,
                },
            )
            for index in indexes
        )
    )


def _fenced_summary_response() -> ModelResponse:
    payload = {
        "goal": "create a project README",
        "established_facts": ["ten representative source files were inspected"],
        "files_examined": [f"source-{index}.txt" for index in range(10)],
        "changes_made": [],
        "commands_and_results": [],
        "unresolved_errors": [],
        "open_issues": ["README.md still needs to be created"],
        "verification_state": {},
        "avoid_repeating": ["do not reread source-0 through source-9"],
    }
    return ModelResponse(
        text="```json\n" + json.dumps(payload, sort_keys=True) + "\n```"
    )


def _realistic_readme_runner(
    workspace: Path,
    *,
    final_decision: ModelResponse,
) -> tuple[AgentRunner, FakeModelClient, _FakeVerificationExecutor]:
    large_body = "representative project fact\n" * 260
    for index in range(10):
        (workspace / f"source-{index}.txt").write_text(
            f"component {index}\n{large_body}",
            encoding="utf-8",
        )
    responses = (
        _read_batch("initial-a", range(0, 5)),
        _read_batch("initial-b", range(5, 10)),
        _fenced_summary_response(),
        _read_batch("duplicate", range(0, 5)),
        _read_batch("rejected", range(0, 5)),
        final_decision,
        ModelResponse(text="README.md was created and verified."),
    )
    model = FakeModelClient(responses)
    gate, executor = _verification_gate(workspace)
    runner = AgentRunner(
        model_client=model,
        tool_registry=ToolRegistry((ReadFileTool(), WriteFileTool())),
        execution_context=ExecutionContext(workspace),
        context_manager=ContextManager(model_client=model),
        termination_policy=_profile_policy(BudgetProfile.DEEP),
        verification_gate=gate,
        budget_profile=BudgetProfile.DEEP,
    )
    return runner, model, executor
```

The successful `final_decision` is:

```python
ModelResponse(tool_calls=(ToolCall(
    "create-readme",
    "write_file",
    {
        "path": "README.md",
        "content": "# Example project\n\nA bounded project overview.\n",
    },
),))
```

The helper scripts the shared client in this exact logical order:

1. Main response reads files 0–4 in one batch.
2. Main response reads files 5–9 in one batch.
3. Summary response returns valid summary JSON inside one strict `json` fence.
4. Main response repeats files 0–4; this batch executes once and is duplicate-only.
5. First decision response requests the same reads; every call is paired and rejected.
6. Corrective response calls `write_file` for `README.md`.
7. Final response reports completion; the existing forced fake verification returns fresh exit code `0` evidence.

Add assertions:

```python
def test_batched_compressed_readme_converges_after_duplicate_exploration(
    tmp_path: Path,
) -> None:
    write = ModelResponse(tool_calls=(ToolCall(
        "create-readme",
        "write_file",
        {
            "path": "README.md",
            "content": "# Example project\n\nA bounded project overview.\n",
        },
    ),))
    runner, model, executor = _realistic_readme_runner(
        tmp_path,
        final_decision=write,
    )
    state = runner.run("create README.md that introduces the whole project")

    assert state.status is AgentStatus.SUCCESS
    assert state.termination_reason is None
    assert state.mutation_index == state.validation_index == 1
    assert (tmp_path / "README.md").read_text(encoding="utf-8").startswith("# ")
    assert state.summary_model_call_count == 1
    assert state.progress.exploration.context_compacted is True
    assert state.progress.exploration.duplicate_only_turns == 1
    rejected = [
        item for item in state.messages
        if isinstance(item, ToolResult)
        and item.error is not None
        and item.error.startswith("agent_rejected:decision_required")
    ]
    assert len(rejected) == 5
    assert len(executor.calls) == 1
    assert state.main_model_call_count == 6
```

The expected main count excludes the one summary call and includes the six numbered main responses above.

- [ ] **Step 2: Run realistic README RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-real-readme-red tests/integration/test_adaptive_convergence.py -k "batched_compressed_readme"
```

Expected: nonzero exit under the old behavior because compression loses coverage, repeated reads are not counted as read batches, or the run reaches `no_progress` before the corrective write.

- [ ] **Step 3: Make only fixture-level adjustments required by real interfaces**

Do not change production behavior in this step. Align helper names with existing verification/context constructors, keep each generated file inside `tmp_path`, and keep the real `48_000/33_000/60_000` character thresholds. Do not disable compression or reduce the response to one read per turn.

- [ ] **Step 4: Run realistic README GREEN and failure-boundary companion**

Add a companion whose corrective response also contains only reads. Assert `NO_PROGRESS`, exactly two decision attempts without progress, no mutation, and no seventh main request. Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-real-readme-green tests/integration/test_adaptive_convergence.py -k "batched_compressed_readme or duplicate_decision_exhaustion"
```

Expected: exit `0`; successful fixture writes and verifies, failure fixture stops exactly at the approved boundary.

- [ ] **Step 5: Run all adaptive and provider-neutral integrations**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-adaptive-integration tests/integration/test_adaptive_convergence.py tests/integration/test_chat_completions_agent.py tests/integration/test_agent_failures.py
```

Expected: exit `0`; record actual count. The compatible Chat Completions adapter requires no mapping change and both success/non-success states remain accurately represented.

**Acceptance:** the exact architecture that failed in the real 33-character README run now converges under an offline fixture with batched reads and actual compression, not an idealized no-compression script.

---

### Corrective Task 6: Document the convergence-memory highlight and verify the whole repository

**Files:**

- Modify: `README.md`
- Modify: `README.txt`
- Modify: `docs/USAGE.md`
- Modify: `tests/test_docs.py`
- Review/update only for consistency: `AGENTS.md`, `DESIGN.md`, `TASKS.md`, `docs/superpowers/plans/Task26.md`

**Interfaces:** Documentation describes only behavior proven green in Corrective Tasks 1–5. `README.txt` retains its existing character limit and submission purpose.

- [ ] **Step 1: Write documentation-contract RED tests**

Add assertions requiring public docs to state all of the following without promising unlimited execution:

```python
def test_docs_describe_run_scoped_exploration_convergence() -> None:
    readme = _read_utf8(ROOT / "README.md")
    usage = _read_utf8(ROOT / "docs" / "USAGE.md")
    for text in (readme, usage):
        assert "ExplorationLedger" in text or "探索账本" in text
        assert "decision_required" in text
        assert "Standard 1 / Deep 2" in text
        assert "运行级" in text
    assert "长期记忆" in usage
    assert "不保存文件正文" in usage
```

Use existing document helpers/naming in the final test rather than duplicating them.

- [ ] **Step 2: Run documentation RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-docs-red tests/test_docs.py -k "exploration_convergence"
```

Expected: nonzero exit because public docs do not yet describe the corrective behavior.

- [ ] **Step 3: Update public documentation accurately**

Document:

- Exploration memory is per run, bounded, content-free metadata and not cross-session memory.
- Context compression preserves safe coverage but clears provider continuation.
- Duplicate-only exploration forces output-first action.
- Ordinary checkpoints retain Standard 1 / Deep 2 response batches.
- One corrective response follows a failed decision attempt, subject to hard safety/time/provider limits.
- `no_progress` remains possible and means the bounded decision handshake was exhausted.
- The feature improves convergence but does not add Planner, autonomous rollback, unlimited budget, or an operating-system sandbox.

Keep `README.txt` within its existing tested limit; never include real endpoint credentials, local absolute paths, or live-run contents.

- [ ] **Step 4: Run documentation GREEN**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-docs-green tests/test_docs.py
```

Expected: exit `0`; record actual count.

- [ ] **Step 5: Run focused corrective suite**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-corrective-focused tests/test_progress.py tests/test_context.py tests/test_agent_loop.py tests/test_logging.py tests/test_session_events.py tests/test_session_controller.py tests/test_docs.py tests/integration/test_adaptive_convergence.py
```

Expected: exit `0`; record actual passed/failed/skipped/warning counts.

- [ ] **Step 6: Run full Python and GUI suites**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .coding-agent\pytest-temp\task26-corrective-full
node --test tests/js/web_gui.test.mjs
```

Expected: both exit `0`; report actual counts rather than planned totals.

- [ ] **Step 7: Run Windows safety/process specializations**

Run the exact existing node IDs selected by `rg -n "reparse|junction|symlink|timeout|process_tree|output_limit" tests`, including every Windows reparse/junction/symlink test and every Shell timeout/process-tree/output-limit test. Expected: exit `0` with no permanent skip or xfail replacing target-Windows evidence.

- [ ] **Step 8: Run interface, privacy, dependency, and deferred-scope audits**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pip check
rg -n "OPENAI_API_KEY\s*=|CHAT_COMPLETIONS_API_KEY\s*=|Authorization:\s*Bearer|sk-[A-Za-z0-9]" . --glob "!*.pyc" --glob "!.git/**" --glob "!.coding-agent/**"
rg -n "C:\\Users\\|D:\\code\\|/home/|encrypted_reasoning|continuation_items|Exploration coverage:" README.md README.txt docs src tests --glob "!*.pyc"
rg -n "TODO|TBD|FIXME|pytest\.skip|pytest\.xfail|@pytest\.mark\.skip|@pytest\.mark\.xfail" src tests README.md README.txt docs TASKS.md DESIGN.md AGENTS.md
rg -n "LangChain|LlamaIndex|Agents SDK|AutoGen|CrewAI|subprocess.*shell=True|os\.system" src pyproject.toml
rg -n "from openai|import openai" src/coding_agent --glob "!openai_client.py" --glob "!chat_completions_client.py"
git diff -- src/coding_agent/messages.py src/coding_agent/model.py src/coding_agent/openai_client.py src/coding_agent/chat_completions_client.py src/coding_agent/state.py src/coding_agent/termination.py src/coding_agent/verification.py src/coding_agent/safety.py src/coding_agent/tools pyproject.toml
```

Expected: `pip check` exits `0`; scans contain only deliberate environment-variable names, negative-test strings, continuation lifecycle code, and audit-command text after manual classification. No credential value, host path in a public contract, exploration content persistence, provider change, dependency change, framework, shell escape, safety weakening, or verification weakening.

- [ ] **Step 9: Review exact diff and stop uncommitted**

Run:

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff -- AGENTS.md DESIGN.md TASKS.md README.md README.txt docs/USAGE.md docs/superpowers/plans/Task26.md src/coding_agent/progress.py src/coding_agent/context.py src/coding_agent/agent.py src/coding_agent/logging.py src/coding_agent/session_events.py tests/test_progress.py tests/test_context.py tests/test_agent_loop.py tests/test_logging.py tests/test_session_events.py tests/integration/test_adaptive_convergence.py tests/integration/test_chat_completions_agent.py tests/integration/test_agent_failures.py tests/test_docs.py
```

Expected: only the approved Task26 work plus this corrective amendment appears, Task26 remains `进行中`, nothing is staged, and no commit or remote action occurred.

**Acceptance:** public docs describe a verified architectural highlight without overclaiming, all Task1–Task26 behavior remains green, and final evidence is fresh, offline, Windows-specific where required, and privacy-safe.

---

## Corrective Amendment Acceptance Matrix

| Approved requirement | Primary evidence |
|---|---|
| Run-scoped exploration ledger survives compression | `tests/test_progress.py`, Agent coverage test |
| No body, credential, absolute path, or continuation in ledger | progress privacy tests and final scans |
| Exact request/result fingerprints and mutation epoch | exploration novelty/epoch tests |
| Batched reads count once per response | progress response-level equality tests |
| Failed reads do not masquerade as duplicates | failed-read classification test |
| Duplicate-only turn closes reads immediately | progress decision test and README integration |
| Ordinary checkpoint remains Standard 1 / Deep 2 | parameterized progress and integration tests |
| First failed decision gets one corrective response | progress and Agent handshake tests |
| Second failed decision stops without extra model call | Agent request-count companion test |
| Rejected reads retain call/result pairing | Agent message-history assertions |
| Legal same-batch mutation still executes | existing and updated mixed-batch test |
| Coverage is bounded, deterministic, and temporary | progress renderer and Agent instructions tests |
| Compression still clears continuation atomically | context/Agent continuation tests |
| Bare JSON remains accepted | existing context summary tests |
| Exactly one JSON fence is accepted | fenced-summary test |
| Prose, multiple objects, malformed fields still fall back | parameterized invalid-summary tests |
| Fallback retains first-seen safe targets beyond eight | fallback capacity/order tests |
| Fallback never copies successful tool body | marker-exclusion test |
| Safe audit/Session reason only | logging/session exact allowlist tests |
| Real batched compressed README flow succeeds | adaptive convergence integration |
| Exhausted decision handshake still returns accurate no-progress | integration companion |
| No provider/API/tool/safety/verification interface change | targeted diffs and full regressions |
| No new dependency, framework, network, or real key | `pip check`, scans, complete offline suite |

## Corrective Plan Self-Review

- Every approved design section maps to Corrective Tasks 1–6 and a matrix row.
- `ExplorationObservation`, `ExplorationTurnSummary`, `ExplorationLedger`, `ExplorationNovelty`, `decision_attempts_without_progress`, and `duplicate_only_turn` use one spelling throughout.
- Response-level allowance distinguishes attempted, novel, duplicate, and failed reads; no equality depends on file count inside a response.
- Duplicate-only closes reads before ordinary final allowance, while ordinary checkpoints keep exact Standard 1 / Deep 2 behavior.
- The first failed decision can be observed by the next model response; equality at two failures stops before another provider request.
- Mutation epoch is local metadata and does not weaken post-mutation verification restrictions.
- Summary normalization permits only one exact fence and does not parse arbitrary prose.
- Fallback target retention is size-bounded and never copies successful output.
- Observation payloads remain outside logs, Session, SSE, GUI, repr, and public reports.
- No task changes context hard limits, provider mappings, Task8 safety, Task11 verification, run modes, persistence schema, GUI layout, dependencies, or deferred Planner/MCP behavior.
- The realistic integration keeps real compression thresholds and 4–5 reads per response; it does not disable the mechanism that reproduced the bug.
- No corrective step stages, commits, pushes, pulls, fetches, creates a branch/worktree, dispatches an agent, or calls a live API.

## Locked File Map

### Create

- `src/coding_agent/budget.py` — profile enum, exact immutable budget limits, profile lookup.
- `src/coding_agent/progress.py` — phase enum, convergence limits, ledger, decisions, safe dynamic control rendering.
- `tests/test_budget.py` — profile and exact-limit tests.
- `tests/test_progress.py` — phase, weak/strong progress, checkpoint, no-progress, and rendering tests.
- `tests/integration/test_adaptive_convergence.py` — fully offline end-to-end scenarios.

### Modify: core

- `src/coding_agent/model.py`
- `src/coding_agent/context.py`
- `src/coding_agent/termination.py`
- `src/coding_agent/state.py`
- `src/coding_agent/agent.py`
- `src/coding_agent/instructions.py`
- `src/coding_agent/tools/shell.py`
- `src/coding_agent/config.py`
- `src/coding_agent/cli.py`
- `src/coding_agent/app.py`
- `src/coding_agent/logging.py`
- `src/coding_agent/report.py`

### Modify: session and Web

- `src/coding_agent/session.py`
- `src/coding_agent/session_store.py`
- `src/coding_agent/session_runtime.py`
- `src/coding_agent/session_controller.py`
- `src/coding_agent/session_events.py`
- `src/coding_agent/web.py`
- `src/coding_agent/web_static/index.html`
- `src/coding_agent/web_static/app.js`
- `src/coding_agent/web_static/styles.css`

### Modify: tests

- `tests/test_model.py`
- `tests/test_context.py`
- `tests/test_termination.py`
- `tests/test_agent_loop.py`
- `tests/test_instructions.py`
- `tests/tools/test_shell_tool.py`
- `tests/test_cli.py`
- `tests/test_app.py`
- `tests/test_logging.py`
- `tests/test_report.py`
- `tests/test_session.py`
- `tests/test_session_store.py`
- `tests/test_session_runtime.py`
- `tests/test_session_controller.py`
- `tests/test_session_events.py`
- `tests/test_web_api.py`
- `tests/test_web_sse.py`
- `tests/test_web_gui.py`
- `tests/js/web_gui.test.mjs`
- Existing provider tests only for regression assertions; production provider adapter files remain unchanged unless a failing test proves the accepted budget protocol cannot be preserved.

### Modify: project documentation

- `AGENTS.md`
- `DESIGN.md`
- `README.md`
- `README.txt`
- `docs/USAGE.md`
- `tests/test_docs.py`
- `TASKS.md` status only during execution.

### Must remain unchanged

- `src/coding_agent/messages.py`
- `src/coding_agent/openai_client.py`
- `src/coding_agent/chat_completions_client.py`
- `src/coding_agent/safety.py`
- `src/coding_agent/verification.py`
- `src/coding_agent/tools/base.py`
- `src/coding_agent/tools/registry.py`
- `src/coding_agent/tools/filesystem.py`
- `src/coding_agent/tools/java.py`
- `pyproject.toml`
- Dependency lock or environment files.

If implementation requires changing a must-remain-unchanged file, a public signature named above, a safety rule, or a verification invariant, stop and return to design review.

---

### Task 0: Reconfirm the Task25 baseline and activate Task26

**Files:**
- Read: `AGENTS.md`
- Read: `DESIGN.md`
- Read: `TASKS.md`
- Read: `docs/superpowers/plans/Task26.md`
- Modify: `TASKS.md` status for Task26 only

**Interfaces:**
- Consumes: committed Task25 `RunMode`, `ANSWERED`, Session schema v3, report schema v2, event schema v2.
- Produces: a clean, tested Task1–Task25 baseline with exactly Task26 marked `进行中`.

- [ ] **Step 1: Inspect the exact repository baseline**

Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git log -5 --oneline
git status --short --untracked-files=all
git diff --check
```

Expected: repository `D:/code/coding_agent`, expected branch, Task25 commit at `HEAD`, empty status, and exit code `0` from `git diff --check`.

- [ ] **Step 2: Re-read the approved sources and locked interfaces**

Run:

```powershell
Get-Content -Raw AGENTS.md
Get-Content -Raw DESIGN.md
Get-Content -Raw TASKS.md
Get-Content -Raw docs/superpowers/plans/Task26.md
Get-Content -Raw src/coding_agent/model.py
Get-Content -Raw src/coding_agent/context.py
Get-Content -Raw src/coding_agent/termination.py
Get-Content -Raw src/coding_agent/state.py
Get-Content -Raw src/coding_agent/agent.py
```

Expected: no conflict with the locked file map or signatures.

- [ ] **Step 3: Run the complete Task1–Task25 baseline**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/js/web_gui.test.mjs
```

Expected: both commands exit `0`; record actual passed, failed, skipped, warning, and Node test counts. Any failure stops Task26 before status changes.

- [ ] **Step 4: Activate Task26 only**

Change only Task26's status in `TASKS.md`:

```markdown
**当前状态**

`进行中`
```

Run:

```powershell
$active = (Select-String -Path TASKS.md -SimpleMatch '`进行中`').Count
if ($active -ne 1) { throw "expected exactly one active task, got $active" }
git diff --check -- TASKS.md
```

Expected: exit `0` and exactly Task26 is active.

**Acceptance:** Task25 is committed, the baseline is green, and no production behavior changed before the first RED test.

---

### Task 1: Define budget profiles and configuration admission

**Files:**
- Create: `src/coding_agent/budget.py`
- Create: `tests/test_budget.py`
- Modify: `src/coding_agent/config.py`
- Modify: `src/coding_agent/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces:

```python
class BudgetProfile(StrEnum):
    STANDARD = "standard"
    DEEP = "deep"

@dataclass(frozen=True, slots=True)
class BudgetProfileLimits:
    max_main_logical_calls: int
    max_summary_logical_calls: int
    max_provider_attempts: int
    max_summary_provider_attempts: int
    max_tool_calls: int
    max_runtime_seconds: float
    verification_tool_reserve: int

def limits_for_profile(profile: BudgetProfile) -> BudgetProfileLimits: ...
```

- Extends:

```python
RunConfig.budget_profile: BudgetProfile = BudgetProfile.STANDARD
load_run_config(..., budget_profile: BudgetProfile | str = BudgetProfile.STANDARD) -> RunConfig
```

- [ ] **Step 1: Write profile and config RED tests**

Create `tests/test_budget.py`:

```python
import pytest

from coding_agent.budget import (
    BudgetProfile,
    BudgetProfileLimits,
    limits_for_profile,
)


def test_budget_profiles_have_exact_wire_values() -> None:
    assert tuple(BudgetProfile) == (
        BudgetProfile.STANDARD,
        BudgetProfile.DEEP,
    )
    assert BudgetProfile.STANDARD.value == "standard"
    assert BudgetProfile.DEEP.value == "deep"


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (
            BudgetProfile.STANDARD,
            BudgetProfileLimits(24, 4, 48, 8, 80, 1200.0, 1),
        ),
        (
            BudgetProfile.DEEP,
            BudgetProfileLimits(40, 6, 80, 12, 140, 1800.0, 1),
        ),
    ],
)
def test_profile_limits_are_exact_and_immutable(profile, expected) -> None:
    actual = limits_for_profile(profile)
    assert actual == expected
    with pytest.raises(AttributeError):
        actual.max_tool_calls = 999  # type: ignore[misc]


def test_profile_lookup_rejects_non_enum_values() -> None:
    with pytest.raises(TypeError, match="profile must be BudgetProfile"):
        limits_for_profile("deep")  # type: ignore[arg-type]
```

Add to `tests/test_cli.py`:

```python
from coding_agent.budget import BudgetProfile


def test_config_defaults_to_standard_budget(valid_config_arguments) -> None:
    config = load_run_config(**valid_config_arguments)
    assert config.budget_profile is BudgetProfile.STANDARD


def test_cli_accepts_deep_budget_profile(monkeypatch, tmp_path) -> None:
    captured = capture_main_config(monkeypatch, tmp_path)
    exit_code = main(valid_cli_args(tmp_path) + ["--budget-profile", "deep"])
    assert exit_code == 0
    assert captured[0].budget_profile is BudgetProfile.DEEP


@pytest.mark.parametrize("value", ["", "DEEP", "auto", True, 1])
def test_config_rejects_invalid_budget_profile(valid_config_arguments, value) -> None:
    with pytest.raises(ConfigError, match="budget profile"):
        load_run_config(**valid_config_arguments, budget_profile=value)
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_budget.py tests/test_cli.py -k "budget_profile or profile_limits or budget_profiles"
```

Expected: nonzero exit because `coding_agent.budget`, `RunConfig.budget_profile`, and `--budget-profile` do not exist.

- [ ] **Step 3: Implement the minimal profile module and config path**

Create `src/coding_agent/budget.py` with the exact enum/dataclass/function above. Validate every integer with `type(value) is int and value > 0`, runtime with a finite positive numeric check, and reserve with `type(value) is int and value >= 0`. Return module-level frozen constants from an immutable mapping.

In `config.py`, append the defaulted field after `run_mode`, require an exact `BudgetProfile`, and normalize `BudgetProfile | str` in `load_run_config` before any SDK construction. In `cli.py`, add:

```python
parser.add_argument(
    "--budget-profile",
    choices=tuple(profile.value for profile in BudgetProfile),
    default=BudgetProfile.STANDARD.value,
    help="Run resource profile: standard or deep (default: standard).",
)
```

Pass `args.budget_profile` to `load_run_config`. Do not change existing argument names or the `--read-only` rules.

- [ ] **Step 4: Run GREEN and Task25 config regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_budget.py tests/test_cli.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_run_mode.py tests/test_config.py 2>$null
```

If `tests/test_config.py` does not exist, run `tests/test_run_mode.py tests/test_cli.py` instead and record that exact substitution. Expected: all selected tests pass.

**Acceptance:** profiles have exact immutable values, default to `standard`, reject invalid values before networking, and do not alter RunMode or credential behavior.

---

### Task 2: Extend `ModelCallBudget` with purpose-specific logical and provider caps

**Files:**
- Modify: `src/coding_agent/model.py`
- Modify: `tests/test_model.py`
- Regression: `tests/test_openai_client.py`
- Regression: `tests/test_chat_completions_client.py`

**Interfaces:**
- Retains: `ModelClient.complete(ModelRequest) -> ModelResponse` and existing standalone `ModelCallBudget(max_logical_calls=1, max_provider_attempts=3)` behavior.
- Extends `ModelBudgetReason` with exact values:

```python
MAIN_LOGICAL_CALL_LIMIT = "main_model_call_limit"
SUMMARY_LOGICAL_CALL_LIMIT = "summary_model_call_limit"
SUMMARY_PROVIDER_ATTEMPT_LIMIT = "summary_provider_attempt_limit"
```

- Extends `ModelCallBudget` with optional caps and visible counts:

```python
max_main_logical_calls: int | None = None
max_summary_logical_calls: int | None = None
max_summary_provider_attempts: int | None = None
main_logical_calls: int = 0
summary_logical_calls: int = 0
summary_provider_attempts: int = 0
```

- [ ] **Step 1: Write exact layered-budget RED tests**

Add to `tests/test_model.py`:

```python
def layered_budget() -> ModelCallBudget:
    return ModelCallBudget(
        max_logical_calls=28,
        max_provider_attempts=48,
        max_main_logical_calls=24,
        max_summary_logical_calls=4,
        max_summary_provider_attempts=8,
    )


def test_main_and_summary_logical_limits_are_independent(model_request) -> None:
    budget = layered_budget()
    for _ in range(24):
        index = budget.begin_logical_call(ModelCallPurpose.MAIN, model_request)
        budget.finish_logical_call(
            ModelCallPurpose.MAIN,
            index,
            response=ModelResponse(text="ok"),
            error_code=None,
        )
    for _ in range(4):
        index = budget.begin_logical_call(ModelCallPurpose.SUMMARY, model_request)
        budget.finish_logical_call(
            ModelCallPurpose.SUMMARY,
            index,
            response=ModelResponse(text="ok"),
            error_code=None,
        )
    assert budget.logical_calls == 28
    assert budget.main_logical_calls == 24
    assert budget.summary_logical_calls == 4
    with pytest.raises(ModelBudgetExceeded) as main_error:
        budget.begin_logical_call(ModelCallPurpose.MAIN, model_request)
    assert main_error.value.reason is ModelBudgetReason.MAIN_LOGICAL_CALL_LIMIT
    assert budget.logical_calls == 28


def test_summary_provider_subcap_never_exceeds_global_cap() -> None:
    budget = layered_budget()
    budget.logical_calls = 1
    budget.summary_logical_calls = 1
    budget._active_purpose = ModelCallPurpose.SUMMARY
    for expected in range(1, 9):
        assert budget.begin_provider_attempt(ModelCallPurpose.SUMMARY) == expected
    with pytest.raises(ModelBudgetExceeded) as caught:
        budget.begin_provider_attempt(ModelCallPurpose.SUMMARY)
    assert caught.value.reason is ModelBudgetReason.SUMMARY_PROVIDER_ATTEMPT_LIMIT
    assert budget.provider_attempts == 8
    assert budget.summary_provider_attempts == 8


def test_legacy_budget_without_purpose_caps_keeps_task9_semantics(model_request) -> None:
    budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=3)
    budget.begin_logical_call(ModelCallPurpose.MAIN, model_request)
    assert [budget.begin_provider_attempt(ModelCallPurpose.MAIN) for _ in range(3)] == [1, 2, 3]
    with pytest.raises(ModelBudgetExceeded) as caught:
        budget.begin_provider_attempt(ModelCallPurpose.MAIN)
    assert caught.value.reason is ModelBudgetReason.PROVIDER_ATTEMPT_LIMIT
```

Use a public test helper to place the budget in an active summary call; do not retain direct private-field assignment in the final test if the existing helper can begin the logical call.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_model.py -k "independent or subcap or legacy_budget"
```

Expected: nonzero exit because the purpose-specific fields and reasons do not exist.

- [ ] **Step 3: Implement purpose-specific claims without changing adapters**

In `ModelCallBudget.__post_init__`, validate optional caps as positive integers, require each purpose cap not exceed `max_logical_calls`, and require the summary provider cap not exceed `max_provider_attempts`. In `begin_logical_call`, check the purpose cap before emitting `LOGICAL_STARTED`; in `begin_provider_attempt`, check the summary subcap before emitting `PROVIDER_STARTED`. Increment total and purpose counts only after every check succeeds.

Keep `logical_call_index` and `provider_attempt_index` globally monotonic. Existing observation events continue to use `purpose`; do not add SDK or request payload fields.

- [ ] **Step 4: Run GREEN and both provider regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_model.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_openai_client.py tests/test_chat_completions_client.py
```

Expected: all pass; original no-shared-budget retry tests still make at most three physical calls, and neither production adapter file changes.

**Acceptance:** purpose caps are exact, totals equal the sum of purpose counts, no counter exceeds a cap, and Task9/Task15 adapter behavior remains accepted.

---

### Task 3: Add high/low-water compaction and run-scoped summary fallback latching

**Files:**
- Modify: `src/coding_agent/context.py`
- Modify: `src/coding_agent/state.py`
- Modify: `tests/test_context.py`
- Modify: `tests/test_agent_loop.py` only for state integration assertions

**Interfaces:**
- Extends `ContextLimits`:

```python
compression_trigger_chars: int = 48_000
compression_target_chars: int = 33_000
compression_trigger_items: int = 20
compression_target_items: int = 12
```

Existing `max_serialized_chars=60_000`, `max_history_items=24`, `recent_turns=8`, `max_summary_chars=12_000`, and `summary_max_output_tokens=4096` remain.

- Adds to `state.py`:

```python
class SummaryFallbackReason(StrEnum):
    MODEL_ERROR = "model_error"
    INVALID_SUMMARY = "invalid_summary"
    SUMMARY_BUDGET = "summary_budget"

summary_fallback_latched: bool = False
summary_fallback_reason: SummaryFallbackReason | None = None
```

- [ ] **Step 1: Write high/low-water and complete-turn RED tests**

Add focused helpers/tests to `tests/test_context.py`:

```python
def test_context_triggers_at_high_water_and_compacts_to_low_water(tmp_path) -> None:
    state = state_with_complete_tool_turns(tmp_path, item_count=20, chars=49_000)
    manager = ContextManager(model_client=valid_summary_model())
    prepared = manager.prepare(state, layered_test_budget())
    assert prepared.compressed is True
    assert prepared.size.serialized_chars <= 33_000
    assert prepared.size.history_items <= 12
    assert prepared.messages[0] == state.messages[0]
    ModelRequest(messages=prepared.messages)


def test_compaction_may_summarize_last_completed_turn_to_reach_target(tmp_path) -> None:
    state = state_with_one_oversized_completed_tool_turn(tmp_path)
    prepared = ContextManager(model_client=valid_summary_model()).prepare(
        state,
        layered_test_budget(),
    )
    assert prepared.size.serialized_chars <= 33_000
    assert prepared.size.history_items <= 12
    assert not any(isinstance(item, ToolResult) for item in prepared.messages)
    ModelRequest(messages=prepared.messages)


@pytest.mark.parametrize(
    ("chars", "items", "expected"),
    [(47_999, 19, False), (48_000, 19, True), (47_999, 20, True)],
)
def test_compression_trigger_equality(chars, items, expected) -> None:
    assert requires_sized_history(chars, items) is expected
```

- [ ] **Step 2: Run high/low-water RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_context.py -k "high_water or low_water or last_completed or trigger_equality"
```

Expected: nonzero because current compression starts only above hard limits and preserves the newest turn.

- [ ] **Step 3: Implement deterministic target compaction**

Validate `0 < target < trigger < hard` for characters and items. Make `requires_compression` use `>=` on trigger fields. Partition only complete turns, preserve the initial task, and extend the removed prefix until both target values hold. Permit all completed turns to be summarized. Validate the final tuple through `ModelRequest(messages=candidate)` before returning it.

If the bounded summary plus initial goal cannot meet both hard maxima, raise `ContextPreparationError(CONTEXT_BUDGET_EXHAUSTED)`; do not recursively summarize.

- [ ] **Step 4: Run high/low-water GREEN and existing pairing regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_context.py -k "water or compression or pairing or call_id or continuation"
```

Expected: all selected tests pass with no orphaned tool result.

- [ ] **Step 5: Write summary-latch and privacy RED tests**

Add:

```python
def test_first_invalid_summary_latches_local_fallback_for_same_run(tmp_path) -> None:
    model = FakeModelClient([
        ModelResponse(text="not-json"),
        AssertionError("second summary model call is forbidden"),
    ])
    state = compressible_state(tmp_path)
    manager = ContextManager(model_client=model)
    first = manager.prepare(state, layered_test_budget())
    assert first.summary_source is SummarySource.FALLBACK
    assert state.summary_fallback_latched is True
    assert state.summary_fallback_reason is SummaryFallbackReason.INVALID_SUMMARY
    state.messages = make_compressible_again(first.messages)
    second = manager.prepare(state, layered_test_budget())
    assert second.summary_source is SummarySource.FALLBACK
    assert len(model.requests) == 1


def test_new_run_retries_model_summary_after_prior_run_latched(tmp_path) -> None:
    model = FakeModelClient([
        ModelResponse(text="invalid"),
        valid_summary_response(),
    ])
    manager = ContextManager(model_client=model)
    first_state = compressible_state(tmp_path)
    manager.prepare(first_state, layered_test_budget())
    second_state = compressible_state(tmp_path)
    prepared = manager.prepare(second_state, layered_test_budget())
    assert prepared.summary_source is SummarySource.MODEL
    assert len(model.requests) == 2


def test_fallback_summary_never_contains_host_workspace_path(tmp_path) -> None:
    state = compressible_state(tmp_path)
    prepared = ContextManager(model_client=failing_summary_model()).prepare(
        state,
        layered_test_budget(),
    )
    rendered = prepared.messages[1].content
    assert str(tmp_path) not in rendered
    assert "workspace: configured root" in rendered


def test_fatal_budget_and_base_exceptions_are_not_latched(tmp_path) -> None:
    for scripted in (
        FatalModelError("fatal"),
        ModelBudgetExceeded(ModelBudgetReason.PROVIDER_ATTEMPT_LIMIT),
        KeyboardInterrupt(),
        SystemExit(7),
    ):
        state = compressible_state(tmp_path)
        with pytest.raises(type(scripted)):
            ContextManager(model_client=FakeModelClient([scripted])).prepare(
                state,
                layered_test_budget(),
            )
        assert state.summary_fallback_latched is False
```

- [ ] **Step 6: Run latch RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_context.py -k "latch or new_run or host_workspace or base_exceptions"
```

Expected: nonzero because the latch fields and one-model-attempt-per-run behavior do not exist.

- [ ] **Step 7: Implement the run-scoped latch and continuation transaction**

Attempt a model summary only when the latch is false and summary logical/provider sub-budget remains. Map ordinary `ModelError` to `MODEL_ERROR`, `_SummaryValidationError` to `INVALID_SUMMARY`, and summary-specific `ModelBudgetExceeded` reasons to `SUMMARY_BUDGET`. Set both latch fields before constructing the fallback.

Continue propagating fatal errors, global provider exhaustion, internal invariant errors, `KeyboardInterrupt`, and `SystemExit`. Summary requests keep `instructions=None` and `continuation_items=()`. Discard response continuation. Return `continuation_items=()` only after a complete candidate passes measurement and message validation; no-compression returns the original continuation tuple by identity.

- [ ] **Step 8: Run context GREEN and Task10/Task24 regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_context.py tests/test_model.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_agent_loop.py -k "compression or continuation or summary"
```

Expected: all selected tests pass; no provider adapter file changes.

**Acceptance:** compression uses hysteresis, history remains valid, fallback latches per run, a new run retries semantic summary, and hidden/local-sensitive content is not persisted or emitted.

---

### Task 4: Implement deterministic phases, progress strength, checkpoints, and safe control text

**Files:**
- Create: `src/coding_agent/progress.py`
- Create: `tests/test_progress.py`
- Modify: `src/coding_agent/state.py`

**Interfaces:**
- Produces:

```python
class AgentPhase(StrEnum):
    DISCOVER = "discover"
    ACT = "act"
    VERIFY = "verify"
    FINISH = "finish"

class ProgressStrength(StrEnum):
    NONE = "none"
    WEAK = "weak"
    STRONG = "strong"

class ProgressAction(StrEnum):
    CONTINUE = "continue"
    CHECKPOINT = "checkpoint"
    STOP = "stop"

@dataclass(frozen=True, slots=True)
class ProgressLimits:
    main_turn_limit: int
    read_tool_limit: int
    idle_turn_limit: int
    post_checkpoint_turn_limit: int
    final_decision_remaining_calls: int = 4

    @classmethod
    def for_profile(cls, profile: BudgetProfile) -> "ProgressLimits": ...

@dataclass(frozen=True, slots=True)
class ProgressDecision:
    action: ProgressAction
    reason: str | None = None

@dataclass(slots=True)
class ProgressLedger:
    phase: AgentPhase = AgentPhase.DISCOVER
    epoch: int = 0
    main_turns_since_strong_progress: int = 0
    read_tools_since_strong_progress: int = 0
    idle_main_turns: int = 0
    checkpoint_active: bool = False
    post_checkpoint_main_turns: int = 0
```

- Methods:

```python
ProgressLedger.begin_main_turn() -> None
ProgressLedger.observe_tool(call, result, *, mutation_advanced, verification_recorded) -> ProgressStrength
ProgressLedger.observe_completion_candidate() -> None
ProgressLedger.finish_main_turn() -> ProgressStrength
ProgressLedger.transition(phase: AgentPhase) -> bool
ProgressLedger.decide(limits: ProgressLimits, *, remaining_main_calls: int) -> ProgressDecision
render_execution_control(*, ledger, decision, profile, remaining_main_calls, remaining_tool_calls, verification_reserve) -> str
```

- `AgentState.progress` is a `ProgressLedger` created per run and excluded from sensitive repr details.

- [ ] **Step 1: Write profile and state RED tests**

Create `tests/test_progress.py`:

```python
def test_progress_limits_are_exact_by_profile() -> None:
    assert ProgressLimits.for_profile(BudgetProfile.STANDARD) == ProgressLimits(
        4, 12, 2, 2, 4
    )
    assert ProgressLimits.for_profile(BudgetProfile.DEEP) == ProgressLimits(
        6, 24, 3, 3, 4
    )


def test_new_ledger_starts_in_discover_with_zero_counts() -> None:
    ledger = ProgressLedger()
    assert ledger.phase is AgentPhase.DISCOVER
    assert ledger.epoch == 0
    assert ledger.decide(
        ProgressLimits.for_profile(BudgetProfile.STANDARD),
        remaining_main_calls=24,
    ).action is ProgressAction.CONTINUE
```

Add to `tests/test_agent_loop.py`:

```python
def test_agent_state_starts_with_fresh_progress_ledger(tmp_path) -> None:
    first = AgentState.start("one", tmp_path, 0.0)
    second = AgentState.start("two", tmp_path, 0.0)
    assert first.progress.phase is AgentPhase.DISCOVER
    assert first.progress is not second.progress
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_progress.py tests/test_agent_loop.py -k "progress_limits or new_ledger or fresh_progress"
```

Expected: nonzero because `progress.py` and `AgentState.progress` do not exist.

- [ ] **Step 3: Implement enums, validated limits, ledger construction, and phase transition**

Use exact enum wire values. `ProgressLimits.for_profile` must require an exact `BudgetProfile`. `transition` returns `False` when unchanged; otherwise it sets the phase, increments `epoch`, marks the current turn strong, resets all since-strong counters, and clears the checkpoint.

- [ ] **Step 4: Run the first GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_progress.py tests/test_agent_loop.py -k "progress_limits or new_ledger or fresh_progress"
```

Expected: selected tests pass.

- [ ] **Step 5: Write weak/strong progress and fingerprint RED tests**

Add:

```python
def test_novel_successful_inspection_is_weak_and_repeat_is_none() -> None:
    ledger = ProgressLedger()
    call = ToolCall("c1", "read_file", {"path": "src/a.py", "start_line": 1, "end_line": 20})
    result = ToolResult("c1", "read_file", "ok", output="1: value")
    ledger.begin_main_turn()
    assert ledger.observe_tool(
        call, result, mutation_advanced=False, verification_recorded=False
    ) is ProgressStrength.WEAK
    assert ledger.finish_main_turn() is ProgressStrength.WEAK
    repeated = ToolCall("different-provider-id", call.name, call.arguments)
    ledger.begin_main_turn()
    assert ledger.observe_tool(
        repeated, result_for(repeated, result),
        mutation_advanced=False,
        verification_recorded=False,
    ) is ProgressStrength.NONE
    assert ledger.finish_main_turn() is ProgressStrength.NONE


@pytest.mark.parametrize("mutation,verification", [(True, False), (False, True)])
def test_mutation_or_verification_is_strong(mutation, verification) -> None:
    ledger = ProgressLedger()
    ledger.begin_main_turn()
    strength = ledger.observe_tool(
        successful_tool_call(),
        successful_tool_result(),
        mutation_advanced=mutation,
        verification_recorded=verification,
    )
    assert strength is ProgressStrength.STRONG
    assert ledger.finish_main_turn() is ProgressStrength.STRONG
    assert ledger.epoch == 1
    assert ledger.main_turns_since_strong_progress == 0


def test_errors_rejections_and_synthetic_results_are_not_progress() -> None:
    for result in (
        rejected_result("security_rejected:path_denied"),
        error_result("tool_execution_failed"),
        rejected_result("agent_terminated:time_limit"),
    ):
        ledger = ProgressLedger()
        ledger.begin_main_turn()
        assert ledger.observe_tool(
            matching_call(result), result,
            mutation_advanced=False,
            verification_recorded=False,
        ) is ProgressStrength.NONE
```

Fingerprints must exclude provider `call_id` and use SHA-256 over canonical tool name/arguments plus stable public result fields. Store only hashes in the ledger.

- [ ] **Step 6: Run progress-strength RED, implement, and run GREEN**

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_progress.py -k "inspection or mutation_or_verification or synthetic"
```

Expected RED: nonzero because observation methods do not exist.

Implement the minimal observation state machine, then run the same command. Expected GREEN: all selected tests pass.

- [ ] **Step 7: Write exact checkpoint and stop RED tests**

Add parameterized tests:

```python
@pytest.mark.parametrize(
    ("profile", "weak_turns", "weak_tools", "idle_turns"),
    [
        (BudgetProfile.STANDARD, 4, 0, 0),
        (BudgetProfile.STANDARD, 0, 12, 0),
        (BudgetProfile.STANDARD, 0, 0, 2),
        (BudgetProfile.DEEP, 6, 0, 0),
        (BudgetProfile.DEEP, 0, 24, 0),
        (BudgetProfile.DEEP, 0, 0, 3),
    ],
)
def test_threshold_equality_activates_one_checkpoint(
    profile, weak_turns, weak_tools, idle_turns
) -> None:
    ledger = ledger_with_counts(weak_turns, weak_tools, idle_turns)
    decision = ledger.decide(
        ProgressLimits.for_profile(profile), remaining_main_calls=20
    )
    assert decision == ProgressDecision(ProgressAction.CHECKPOINT, "exploration_limit")
    assert ledger.checkpoint_active is True


def test_four_remaining_main_calls_force_final_decision_checkpoint() -> None:
    ledger = ProgressLedger()
    decision = ledger.decide(
        ProgressLimits.for_profile(BudgetProfile.STANDARD),
        remaining_main_calls=4,
    )
    assert decision == ProgressDecision(ProgressAction.CHECKPOINT, "final_call_reserve")


@pytest.mark.parametrize(
    ("profile", "post_turns"),
    [(BudgetProfile.STANDARD, 2), (BudgetProfile.DEEP, 3)],
)
def test_checkpoint_post_limit_stops_with_no_progress(profile, post_turns) -> None:
    ledger = active_checkpoint_ledger(post_turns=post_turns)
    decision = ledger.decide(
        ProgressLimits.for_profile(profile), remaining_main_calls=10
    )
    assert decision == ProgressDecision(ProgressAction.STOP, "no_progress")


def test_strong_progress_clears_checkpoint_and_starts_new_epoch() -> None:
    ledger = active_checkpoint_ledger(post_turns=1)
    record_strong_mutation(ledger)
    assert ledger.checkpoint_active is False
    assert ledger.post_checkpoint_main_turns == 0
    assert ledger.epoch == 1
```

- [ ] **Step 8: Run checkpoint RED, implement, and run GREEN**

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_progress.py -k "checkpoint or final_decision or no_progress or new_epoch"
```

Expected RED: nonzero because decisions are not implemented.

Implement equality-triggered decisions. `decide` may atomically activate a checkpoint only when returning `CHECKPOINT`; repeated calls before a completed main turn return `CONTINUE`. Valid model errors do not call `finish_main_turn` and therefore do not advance post-checkpoint counts.

Run the same command. Expected GREEN: all selected tests pass.

- [ ] **Step 9: Write and implement safe execution-control rendering**

Add:

```python
def test_execution_control_is_exact_bounded_and_contains_no_paths_or_payloads(tmp_path) -> None:
    ledger = active_checkpoint_ledger(post_turns=0)
    text = render_execution_control(
        ledger=ledger,
        decision=ProgressDecision(ProgressAction.CHECKPOINT, "exploration_limit"),
        profile=BudgetProfile.STANDARD,
        remaining_main_calls=17,
        remaining_tool_calls=61,
        verification_reserve=1,
    )
    assert text == (
        "Execution control:\n"
        "- phase: discover\n"
        "- budget profile: standard\n"
        "- main calls remaining: 17\n"
        "- tool calls remaining: 61\n"
        "- verification reserve: 1\n"
        "- progress checkpoint: active\n"
        "- required decision: answer, act, inspect only named essentials, or report blocker"
    )
    assert str(tmp_path) not in text
    assert len(text) <= 512
```

Run RED, implement using only fixed text and validated enum/count inputs, then run GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_progress.py
```

Expected final result: all progress tests pass.

**Acceptance:** progress is deterministic, exact repeats do not create weak progress, weak exploration still converges, strong evidence resets the epoch, and control text is bounded and nonsensitive.

---

### Task 5: Integrate profiles, phases, budgets, progress, and verification reserve into the Agent loop

**Files:**
- Modify: `src/coding_agent/termination.py`
- Modify: `src/coding_agent/state.py`
- Modify: `src/coding_agent/agent.py`
- Modify: `src/coding_agent/app.py`
- Modify: `tests/test_termination.py`
- Modify: `tests/test_agent_loop.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- `TerminationLimits` exact production fields:

```python
max_main_logical_calls: int = 24
max_summary_logical_calls: int = 4
max_provider_attempts: int = 48
max_summary_provider_attempts: int = 8
max_tool_calls: int = 80
max_runtime_seconds: float = 1200.0
verification_tool_reserve: int = 1
repetition_limit: int = 3
consecutive_error_limit: int = 3
safety_rejection_limit: int = 3
```

- `TerminationLimits.for_profile(BudgetProfile) -> TerminationLimits` maps exact profile values.
- `NextOperation` retains `MODEL` and `TOOL`, and adds `VERIFICATION`.
- Retain `TerminationReason.LOGICAL_MODEL_CALL_LIMIT` only for historical report decoding; new production runs use `MAIN_MODEL_CALL_LIMIT = "main_model_call_limit"`. Add `NO_PROGRESS = "no_progress"`.
- `TerminationPolicy.check` adds a keyword-only flag while preserving existing callers:

```python
check(
    state: AgentState,
    monotonic_time: float,
    *,
    next_operation: NextOperation,
    verification_reserve_active: bool = False,
) -> TerminationDecision
```

- Add to `AgentState`:

```python
budget_profile: BudgetProfile = BudgetProfile.STANDARD
main_model_call_count: int = 0
summary_model_call_count: int = 0
summary_provider_attempt_count: int = 0
required_verification_pending: bool = False
```

Keep `logical_model_call_count` as total logical calls and `model_call_count` as total provider attempts.

- [ ] **Step 1: Write exact TerminationLimits and equality RED tests**

Add to `tests/test_termination.py`:

```python
@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (BudgetProfile.STANDARD, (24, 4, 48, 8, 80, 1200.0, 1)),
        (BudgetProfile.DEEP, (40, 6, 80, 12, 140, 1800.0, 1)),
    ],
)
def test_termination_limits_match_budget_profile(profile, expected) -> None:
    limits = TerminationLimits.for_profile(profile)
    assert (
        limits.max_main_logical_calls,
        limits.max_summary_logical_calls,
        limits.max_provider_attempts,
        limits.max_summary_provider_attempts,
        limits.max_tool_calls,
        limits.max_runtime_seconds,
        limits.verification_tool_reserve,
    ) == expected


def test_last_main_call_is_allowed_and_next_is_blocked(state, policy) -> None:
    state.main_model_call_count = 23
    assert policy.check(state, 1.0, next_operation=NextOperation.MODEL).should_stop is False
    state.main_model_call_count = 24
    decision = policy.check(state, 1.0, next_operation=NextOperation.MODEL)
    assert decision.reason is TerminationReason.MAIN_MODEL_CALL_LIMIT


def test_verification_reserve_blocks_ordinary_tool_but_allows_gate(state) -> None:
    state.tool_call_count = 79
    ordinary = standard_policy().check(
        state,
        1.0,
        next_operation=NextOperation.TOOL,
        verification_reserve_active=True,
    )
    verification = standard_policy().check(
        state,
        1.0,
        next_operation=NextOperation.VERIFICATION,
        verification_reserve_active=True,
    )
    assert ordinary.reason is TerminationReason.TOOL_CALL_LIMIT
    assert verification.should_stop is False
```

- [ ] **Step 2: Run termination RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_termination.py -k "budget_profile or last_main or verification_reserve"
```

Expected: nonzero because the fields, profile factory, reason, and verification operation do not exist.

- [ ] **Step 3: Implement limits, state counts, and stable priority**

Implement `TerminationLimits.for_profile` from `budget.limits_for_profile`. Validate reserve as a nonnegative integer smaller than `max_tool_calls`. `TerminationPolicy` uses this exact normal priority:

1. `INTERNAL_INVARIANT`
2. `CONSECUTIVE_SAFETY_REJECTIONS`
3. `TIME_LIMIT`
4. `PROVIDER_ATTEMPT_LIMIT`
5. `NO_PROGRESS`
6. `MAIN_MODEL_CALL_LIMIT`
7. `TOOL_CALL_LIMIT`
8. `CONSECUTIVE_MODEL_ERRORS`
9. `CONSECUTIVE_TOOL_ERRORS`
10. `REPEATED_TOOL_CALL`

Immediate user interruption, audit failure, fatal model failure, context exhaustion, and empty response remain outside normal comparison. A completed valid response is accepted before checking the cap for a next operation.

- [ ] **Step 4: Run termination GREEN and priority regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_termination.py
```

Expected: all termination tests pass, including fake-clock and fingerprint tests.

- [ ] **Step 5: Write Agent orchestration RED tests**

Add focused tests to `tests/test_agent_loop.py`:

```python
def test_summary_and_main_counts_are_split_but_total_is_preserved(tmp_path) -> None:
    runner, model = runner_requiring_one_summary_then_completion(tmp_path)
    state = runner.run("inspect")
    assert state.main_model_call_count == 1
    assert state.summary_model_call_count == 1
    assert state.logical_model_call_count == 2
    assert state.model_call_count == 2


def test_invalid_summary_latches_without_consuming_later_main_capacity(tmp_path) -> None:
    state, model = run_two_compressions_with_first_invalid_summary(tmp_path)
    assert state.summary_model_call_count == 1
    assert state.main_model_call_count >= 2
    assert state.summary_fallback_latched is True
    assert summary_request_count(model.requests) == 1


def test_checkpoint_control_is_temporary_and_not_added_to_history(tmp_path) -> None:
    state, requests = run_until_decision_checkpoint(tmp_path)
    checkpoint_request = requests[-1]
    assert "progress checkpoint: active" in checkpoint_request.instructions
    assert all(
        "Execution control:" not in message.to_dict().get("content", "")
        for message in state.messages
    )


def test_checkpoint_then_mutation_enters_act_and_clears_no_progress(tmp_path) -> None:
    state = run_inspection_checkpoint_then_successful_mutation(tmp_path)
    assert state.progress.phase in {AgentPhase.ACT, AgentPhase.VERIFY, AgentPhase.FINISH}
    assert state.progress.checkpoint_active is False
    assert state.termination_reason is not TerminationReason.NO_PROGRESS


def test_checkpoint_then_continued_exploration_stops_without_extra_model_call(tmp_path) -> None:
    model = scripted_standard_no_progress_model()
    state = standard_runner(tmp_path, model).run("inspect forever")
    assert state.termination_reason is TerminationReason.NO_PROGRESS
    assert state.main_model_call_count == expected_checkpoint_stop_count()
    assert len(model.requests) == state.main_model_call_count + state.summary_model_call_count


def test_read_only_answer_transitions_discover_to_finish_without_mutation(tmp_path) -> None:
    state = read_only_runner(tmp_path, text_model("project summary")).run("explain")
    assert state.status is AgentStatus.ANSWERED
    assert state.progress.phase is AgentPhase.FINISH
    assert state.mutation_index == 0


def test_forced_verification_can_use_reserved_final_tool_slot(tmp_path) -> None:
    state = runner_at_tool_reserve_with_pending_verify(tmp_path).run("finish")
    assert state.status is AgentStatus.SUCCESS
    assert state.tool_call_count == 80
    assert state.verification_status is VerificationStatus.PASSED
```

Add a multi-tool assertion that an ordinary call blocked by the reserve plus all later calls receive paired `agent_terminated:tool_call_limit` results without Registry execution.

- [ ] **Step 6: Run Agent RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_agent_loop.py -k "split or latches or checkpoint or read_only_answer or reserved_final"
```

Expected: nonzero because AgentRunner does not create profile limits, progress control, split counts, phases, or verification reserve.

- [ ] **Step 7: Integrate the loop in the approved order**

In `app.py`, resolve `config.budget_profile` once, create `ContextManager` with the approved context limits, `TerminationPolicy(TerminationLimits.for_profile(...))`, and `ProgressLimits.for_profile(...)`, then pass the profile and progress limits to `AgentRunner`.

In `AgentRunner.run`, create one layered `ModelCallBudget` with total logical cap `main + summary`, purpose caps, global provider cap, and summary provider cap. `_sync_budget` writes all split and total counts. The loop order is cancellation, policy/progress decision, context prepare, budget sync, post-compression policy, dynamic instructions, main model, tool batch, completion/verification.

Call `ProgressLedger.begin_main_turn` only immediately before an allowed main logical call. Call `finish_main_turn` only after a valid main response and after all returned tool calls have been processed. A main `ModelError` increments only `consecutive_model_errors`; summary success or failure never resets it.

Set phases only from local facts: successful mutation to `ACT`, verification start to `VERIFY`, verification failure/staleness to `ACT`, fresh pass or valid read-only answer to `FINISH`. Never infer a phase from assistant prose.

- [ ] **Step 8: Run Agent GREEN and core regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_agent_loop.py tests/test_app.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_context.py tests/test_termination.py tests/test_verification.py tests/test_run_mode.py
```

Expected: all selected tests pass. Record actual counts.

**Acceptance:** the Agent does not make one extra model/tool request after a cap, summary activity cannot mask main failures, the checkpoint can recover into action, read-only answers remain valid, and forced verification retains its only reserved slot.

---

### Task 6: Add privacy-safe audit events and final report fields

**Files:**
- Modify: `src/coding_agent/logging.py`
- Modify: `src/coding_agent/report.py`
- Modify: `src/coding_agent/agent.py`
- Modify: `tests/test_logging.py`
- Modify: `tests/test_report.py`

**Interfaces:**
- Bump `EVENT_SCHEMA_VERSION` from `2` to `3` and `REPORT_SCHEMA_VERSION` from `2` to `3` for new runs.
- Add exact event types:

```python
PHASE_CHANGED = "phase_changed"
PROGRESS_OBSERVED = "progress_observed"
DECISION_CHECKPOINT = "decision_checkpoint"
NO_PROGRESS_DETECTED = "no_progress_detected"
SUMMARY_FALLBACK_LATCHED = "summary_fallback_latched"
```

- `RUN_STARTED` adds `budget_profile` and exact budget maxima.
- `RUN_COMPLETED` adds `budget_profile`, `phase`, `main_model_calls`, `summary_model_calls`, and `summary_provider_attempts` while retaining total logical/provider fields.
- `FinalReport` adds exact profile/phase/split-count fields. New in-memory reports require integers; historical safe projections may use null split counts during migration only.

- [ ] **Step 1: Write strict event-schema RED tests**

Add to `tests/test_logging.py`:

```python
def test_phase_progress_checkpoint_and_latch_events_have_exact_safe_keys(event_logger) -> None:
    cases = [
        (EventType.PHASE_CHANGED, {"from_phase": "discover", "to_phase": "act", "epoch": 1}),
        (EventType.PROGRESS_OBSERVED, {"strength": "weak", "source": "tool", "epoch": 0}),
        (EventType.DECISION_CHECKPOINT, {"reason": "exploration_limit", "phase": "discover", "main_calls_remaining": 18}),
        (EventType.NO_PROGRESS_DETECTED, {"phase": "discover", "post_checkpoint_main_turns": 2}),
        (EventType.SUMMARY_FALLBACK_LATCHED, {"reason": "invalid_summary", "summary_model_calls": 1}),
    ]
    for event_type, data in cases:
        event = event_logger.emit(event_type, data)
        assert event.schema_version == 3
        assert event.data == data


def test_new_events_reject_content_paths_continuation_and_extra_fields(event_logger, tmp_path) -> None:
    forbidden = [
        {"summary": "secret"},
        {"path": str(tmp_path)},
        {"continuation": "opaque"},
        {"instructions": "hidden"},
    ]
    for extra in forbidden:
        with pytest.raises(RunLogError):
            event_logger.emit(
                EventType.DECISION_CHECKPOINT,
                {"reason": "exploration_limit", "phase": "discover", "main_calls_remaining": 4, **extra},
            )
```

- [ ] **Step 2: Run event RED, implement exact allowlists, and run GREEN**

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_logging.py -k "phase_progress or new_events or schema_version"
```

Expected RED: new event names and schema version do not exist.

Add strict `_EVENT_KEYS`, enum/value validators, nonnegative counts, and allowed enum strings. Emit events only after corresponding local state changes. Run the same command; expected GREEN: all selected tests pass.

- [ ] **Step 3: Write report RED tests**

Add to `tests/test_report.py`:

```python
def test_final_report_contains_profile_phase_and_split_counts(success_state, metadata) -> None:
    success_state.budget_profile = BudgetProfile.DEEP
    success_state.progress.transition(AgentPhase.ACT)
    success_state.progress.transition(AgentPhase.VERIFY)
    success_state.progress.transition(AgentPhase.FINISH)
    success_state.main_model_call_count = 7
    success_state.summary_model_call_count = 2
    success_state.logical_model_call_count = 9
    success_state.summary_provider_attempt_count = 2
    success_state.model_call_count = 10
    report = FinalReport.from_state(success_state, metadata)
    payload = report.to_dict()
    assert payload["schema_version"] == 3
    assert payload["budget_profile"] == "deep"
    assert payload["phase"] == "finish"
    assert payload["main_model_calls"] == 7
    assert payload["summary_model_calls"] == 2
    assert payload["logical_model_calls"] == 9
    assert payload["summary_provider_attempts"] == 2
    assert payload["provider_attempts"] == 10
```

Add invalid-invariant tests requiring `logical_model_calls == main + summary`, summary-provider attempts not above provider attempts, and terminal success/answered phase `finish`.

- [ ] **Step 4: Run report RED, implement, and run GREEN**

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_report.py -k "profile_phase or split_counts or invariant"
```

Expected RED: schema v3 fields do not exist.

Implement exact frozen fields, validation, and JSON keys. Do not include progress fingerprints, control text, summary text, or absolute workspace. Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_logging.py tests/test_report.py
```

Expected: all pass.

**Acceptance:** new facts are observable without sensitive payloads, total/split counters agree, and audit failure remains fail-closed.

---

### Task 7: Persist immutable per-run budget profiles through Session schema v4

**Files:**
- Modify: `src/coding_agent/session.py`
- Modify: `src/coding_agent/session_store.py`
- Modify: `src/coding_agent/session_runtime.py`
- Modify: `src/coding_agent/session_controller.py`
- Modify: `tests/test_session.py`
- Modify: `tests/test_session_store.py`
- Modify: `tests/test_session_runtime.py`
- Modify: `tests/test_session_controller.py`

**Interfaces:**
- Add `budget_profile: BudgetProfile` after `run_mode` to `SessionRunRecord`, `SessionRunRequest`, and `RunHandle`.
- Extend controller admission without changing existing positional arguments:

```python
SessionController.create_session(
    message: str,
    *,
    skill_ids: tuple[str, ...] = (),
    run_mode: RunMode = RunMode.MODIFY,
    budget_profile: BudgetProfile = BudgetProfile.STANDARD,
) -> RunHandle

SessionController.submit_message(
    session_id: str,
    message: str,
    *,
    run_mode: RunMode = RunMode.MODIFY,
    budget_profile: BudgetProfile = BudgetProfile.STANDARD,
) -> RunHandle
```

- Bump `session_store.SCHEMA_VERSION` from `3` to `4`.
- Add column:

```sql
budget_profile TEXT NOT NULL DEFAULT 'standard'
    CHECK(budget_profile IN ('standard', 'deep'))
```

- Historical schema v3 rows and reports map to `standard`. Existing `run_mode` migration remains unchanged.

- [ ] **Step 1: Write strict domain and lifecycle RED tests**

Add:

```python
@pytest.mark.parametrize("profile", tuple(BudgetProfile))
def test_session_run_record_requires_and_preserves_budget_profile(profile) -> None:
    record = make_run_record(budget_profile=profile)
    assert record.budget_profile is profile
    with pytest.raises(TypeError, match="budget_profile"):
        make_run_record(budget_profile=profile.value)


@pytest.mark.parametrize("profile", tuple(BudgetProfile))
def test_budget_profile_survives_create_start_finish_and_reopen(tmp_path, profile) -> None:
    store = open_store(tmp_path)
    submission = store.create_session("message", budget_profile=profile)
    run_id = submission.run.run_id
    assert submission.run.budget_profile is profile
    assert store.start_run(run_id).budget_profile is profile
    store.finish_run(run_id, terminal_result_for(profile))
    store.close()
    assert open_store(tmp_path).get_run(run_id).budget_profile is profile


def test_follow_up_can_choose_new_profile_without_mutating_prior_run(controller_harness) -> None:
    first = controller_harness.create_session(
        "inspect", budget_profile=BudgetProfile.STANDARD
    )
    controller_harness.finish(first.run_id)
    second = controller_harness.submit_message(
        first.session_id, "go deeper", budget_profile=BudgetProfile.DEEP
    )
    runs = controller_harness.get_session(first.session_id).runs
    assert [run.budget_profile for run in runs] == [
        BudgetProfile.STANDARD,
        BudgetProfile.DEEP,
    ]
    assert second.budget_profile is BudgetProfile.DEEP
```

- [ ] **Step 2: Run domain RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session.py tests/test_session_runtime.py tests/test_session_controller.py -k "budget_profile or new_profile"
```

Expected: nonzero because Session types and signatures lack the field.

- [ ] **Step 3: Add exact provider-neutral fields and propagation**

Require `type(value) is BudgetProfile` in direct domain construction. Default only public admission methods and `SessionRunRequest` to `STANDARD`. `AgentSessionRunExecutor.execute` passes `request.budget_profile` through `dataclasses.replace` into `RunConfig`. Do not include control instructions or progress hashes in the session narrative.

- [ ] **Step 4: Run domain GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session.py tests/test_session_runtime.py tests/test_session_controller.py
```

Expected: all pass.

- [ ] **Step 5: Write schema v4 migration RED tests**

Add to `tests/test_session_store.py`:

```python
def test_fresh_schema_v4_persists_exact_budget_profiles(tmp_path) -> None:
    store = open_store(tmp_path)
    standard = store.create_session("one", budget_profile=BudgetProfile.STANDARD)
    store.finish_run(standard.run.run_id, terminal_result_for(BudgetProfile.STANDARD))
    deep = store.submit_message(
        standard.session.session_id,
        "two",
        budget_profile=BudgetProfile.DEEP,
    )
    with raw_connection(tmp_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        values = connection.execute(
            "SELECT budget_profile FROM session_runs ORDER BY ordinal"
        ).fetchall()
    assert [row[0] for row in values] == ["standard", "deep"]


def test_schema_v3_migrates_historical_runs_to_standard_atomically(tmp_path) -> None:
    create_version_3_store(tmp_path)
    store = open_store(tmp_path)
    run = store.list_sessions()[0].runs[0]
    assert run.budget_profile is BudgetProfile.STANDARD
    assert database_user_version(tmp_path) == 4


def test_schema_v4_rejects_corrupt_budget_profile_without_partial_state(tmp_path) -> None:
    store = open_store(tmp_path)
    run = store.create_session("one").run
    store.close()
    disable_checks_and_set_budget_profile(tmp_path, run.run_id, "unlimited")
    with pytest.raises(SessionStoreError, match="invalid_stored_data"):
        open_store(tmp_path).get_run(run.run_id)
```

Report migration from schema v2 to v3 adds `budget_profile="standard"`; split count fields in historical safe projections are explicit null because their true division is unknowable. New reports require integers.

- [ ] **Step 6: Run migration RED, implement one transaction, and run GREEN**

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_store.py -k "schema_v4 or schema_v3 or corrupt_budget"
```

Expected RED: schema remains v3 and the column does not exist.

Implement the v3→v4 migration in the existing exclusive schema transaction, update every insert/select column list explicitly, decode with `BudgetProfile(value)`, and map invalid stored values to the stable store error. Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_store.py
```

Expected: all store tests pass, including v1/v2/v3 migration and reparse/lease tests.

**Acceptance:** profile is immutable within a run, selectable on a new follow-up, persisted exactly, and migrated honestly without inventing historical split counts.

---

### Task 8: Expose profiles and safe convergence state through REST, SSE, CLI, and GUI

**Files:**
- Modify: `src/coding_agent/session_events.py`
- Modify: `src/coding_agent/web.py`
- Modify: `src/coding_agent/web_static/index.html`
- Modify: `src/coding_agent/web_static/app.js`
- Modify: `src/coding_agent/web_static/styles.css`
- Modify: `tests/test_session_events.py`
- Modify: `tests/test_web_api.py`
- Modify: `tests/test_web_sse.py`
- Modify: `tests/test_web_gui.py`
- Modify: `tests/js/web_gui.test.mjs`
- Regression: `tests/test_cli.py`

**Interfaces:**
- REST create/follow-up bodies add exact `budget_profile`, default `standard`.
- Admission responses and serialized run records add `budget_profile`.
- Bump `SESSION_UPDATE_SCHEMA_VERSION` from `2` to `3` and add exact safe kinds:

```python
RUN_PROGRESS = "run_progress"
PHASE_CHANGED = "phase_changed"
DECISION_CHECKPOINT = "decision_checkpoint"
CONTEXT_COMPRESSED = "context_compressed"
NO_PROGRESS_DETECTED = "no_progress_detected"
```

`RUN_PROGRESS` contains exactly `budget_profile`, `phase`, main/summary/provider/tool counts and maxima. Other new kinds contain only their enum reason/source and nonnegative counts; none accepts free text.
- Browser state adds `selectedBudgetProfile: "standard" | "deep"` and sends it with every new run.

- [ ] **Step 1: Write REST admission RED tests**

Add to `tests/test_web_api.py`:

```python
def test_budget_profile_defaults_to_standard(client, auth_headers, web_harness) -> None:
    response = client.post(
        "/api/sessions",
        headers=auth_headers,
        json={"message": "hello", "skill_ids": [], "run_mode": "modify"},
    )
    assert response.status_code == 201
    assert response.json()["budget_profile"] == "standard"
    assert web_harness.controller.last_budget_profile is BudgetProfile.STANDARD


@pytest.mark.parametrize("profile", tuple(BudgetProfile))
def test_create_and_follow_up_accept_exact_budget_profiles(
    client, auth_headers, session_id, profile, web_harness
) -> None:
    endpoint = "/api/sessions" if session_id is None else f"/api/sessions/{session_id}/messages"
    body = {"message": "hello", "budget_profile": profile.value}
    if session_id is None:
        body["skill_ids"] = []
    response = client.post(endpoint, headers=auth_headers, json=body)
    assert response.status_code in {200, 201}
    assert response.json()["budget_profile"] == profile.value


@pytest.mark.parametrize("value", ["", "DEEP", "auto", None, True, 1, {}])
def test_rest_rejects_invalid_budget_profile_before_controller(
    client, auth_headers, value, web_harness
) -> None:
    response = client.post(
        "/api/sessions",
        headers=auth_headers,
        json={"message": "hello", "skill_ids": [], "budget_profile": value},
    )
    assert response.status_code == 422
    assert web_harness.controller.calls == []
```

- [ ] **Step 2: Run REST RED, implement strict DTO mapping, and run GREEN**

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_web_api.py -k "budget_profile"
```

Expected RED: responses omit profile and controller methods lack the keyword.

Add a `mode="before"` exact-string validator like `run_mode`, pass the enum to the controller, and serialize it from stored records. Run the same command; expected GREEN: all selected tests pass.

- [ ] **Step 3: Write safe SSE projection RED tests**

Add to `tests/test_session_events.py` and `tests/test_web_sse.py`:

```python
def test_convergence_events_project_only_safe_runtime_fields(projector) -> None:
    updates = [
        projector(phase_changed_event("discover", "act", 1)),
        projector(checkpoint_event("exploration_limit", "discover", 18)),
        projector(compression_event("fallback", before=49_000, after=31_000)),
    ]
    assert [update.kind for update in updates] == [
        "phase_changed",
        "decision_checkpoint",
        "context_compressed",
    ]
    encoded = json.dumps([update.to_dict() for update in updates])
    for forbidden in ("instructions", "summary_text", "continuation", "C:\\\\Users", "Bearer "):
        assert forbidden not in encoded


def test_sse_replays_profile_phase_and_split_budget_in_sequence(
    client, auth_headers, event_hub
) -> None:
    publish_profile_phase_budget_updates(event_hub)
    events = read_sse_events(client, auth_headers)
    assert strictly_increasing_sequences(events)
    assert events[-1]["data"]["budget_profile"] == "deep"
    assert events[-1]["data"]["phase"] == "verify"
    assert events[-1]["data"]["main_model_calls"] == 7
    assert events[-1]["data"]["summary_model_calls"] == 1
```

- [ ] **Step 4: Run SSE RED, implement schema v3 projection, and run GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_events.py tests/test_web_sse.py -k "convergence or profile_phase or split_budget"
```

Expected RED before implementation and GREEN after adding strict allowlists. Existing replay, cursor, heartbeat, reset-required, capacity, authentication, and Origin tests must remain green.

- [ ] **Step 5: Write GUI contract and Node interaction RED tests**

Add to `tests/test_web_gui.py`:

```python
def test_gui_contains_compact_accessible_budget_profile_control(web_assets) -> None:
    html = web_assets.index_html
    assert 'data-budget-profile="standard"' in html
    assert 'data-budget-profile="deep"' in html
    assert 'aria-label="运行预算"' in html
    assert "无限" not in html
```

Add to `tests/js/web_gui.test.mjs`:

```javascript
test("budget profile defaults standard and is sent per run", async () => {
  const app = await fixture();
  assert.equal(app.selectedBudgetProfile(), "standard");
  app.clickBudgetProfile("deep");
  await app.submit("inspect deeply");
  assert.deepEqual(app.apiCalls.at(-1).body, {
    message: "inspect deeply",
    skill_ids: [],
    run_mode: "modify",
    budget_profile: "deep",
  });
});

test("active header projects phase budgets checkpoint and elapsed without extra bubble", async () => {
  const app = await fixtureWithActiveRun({ budget_profile: "standard" });
  app.publish(update("run_progress", {
    budget_profile: "standard",
    phase: "discover",
    main_model_calls: 8,
    main_model_limit: 24,
    summary_model_calls: 1,
    summary_model_limit: 4,
    provider_attempts: 10,
    provider_attempt_limit: 48,
    tool_calls: 17,
    tool_limit: 80,
  }));
  app.publish(update("decision_checkpoint", { reason: "exploration_limit" }));
  assert.match(app.activeHeaderText(), /调查中.*标准.*8\/24.*17\/80/);
  assert.match(app.activeStatusText(), /根据已有信息作出决策/);
  assert.equal(app.assistantBubbleCount(), 0);
});

test("terminal reply removes transient checkpoint status and keeps one assistant bubble", async () => {
  const app = await fixtureWithActiveRun({ budget_profile: "deep" });
  app.publish(update("decision_checkpoint", { reason: "final_call_reserve" }));
  app.publish(terminalAnsweredUpdate("final project explanation"));
  assert.equal(app.transientRunCardCount(), 0);
  assert.equal(app.assistantBubbleCount(), 1);
  assert.equal(app.assistantText(), "final project explanation");
});
```

- [ ] **Step 6: Run GUI RED, implement compact control and projection, and run GREEN**

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_web_gui.py -k "budget_profile"
node --test tests/js/web_gui.test.mjs
```

Expected RED: profile control/state and new runtime projections do not exist.

Implement two compact buttons adjacent to the existing run-mode control, with `standard` selected by default. Update only text-safe DOM properties such as `textContent`; do not add remote assets or unsafe HTML sinks. Transient phase/checkpoint text stays in the existing single active status surface and disappears on terminal projection.

Run the same commands. Expected GREEN: Python GUI contracts and all Node tests pass.

- [ ] **Step 7: Run transport/GUI/CLI regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_cli.py tests/test_web_api.py tests/test_web_sse.py tests/test_web_gui.py
node --test tests/js/web_gui.test.mjs
```

Expected: all pass; authentication, Host, Origin, loopback, run mode, Skill, follow-up, cancellation, and single-active-run behavior remain unchanged.

**Acceptance:** each run receives an explicit immutable profile, the GUI exposes only two bounded choices, progress is visible in one status surface, and no sensitive or hidden state reaches REST/SSE/DOM.

---

### Task 9: Add offline convergence integrations, documentation, and complete verification

**Files:**
- Create: `tests/integration/test_adaptive_convergence.py`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `README.txt`
- Modify: `docs/USAGE.md`
- Modify: `tests/test_docs.py`
- Verify all files in the locked map

**Interfaces:**
- No new production interface.
- Documentation must distinguish `RunMode`, `BudgetProfile`, `AgentPhase`, and `AgentStatus` and state that profiles are hard caps rather than promised consumption.

- [ ] **Step 1: Write end-to-end RED tests using only fakes and temporary workspaces**

Create `tests/integration/test_adaptive_convergence.py` with four scenarios:

```python
def test_read_only_project_explanation_finishes_before_standard_budget(tmp_path) -> None:
    runner, model = read_only_project_fixture(tmp_path)
    state = runner.run("Read this project and explain what it does")
    assert state.status is AgentStatus.ANSWERED
    assert state.termination_reason is None
    assert state.main_model_call_count < 24
    assert state.progress.phase is AgentPhase.FINISH


def test_readme_creation_recovers_from_checkpoint_then_verifies(tmp_path) -> None:
    runner = readme_creation_fixture_with_twelve_distinct_reads(tmp_path)
    state = runner.run("Create README.md introducing the project")
    assert state.status is AgentStatus.SUCCESS
    assert state.mutation_index == 1
    assert state.validation_index == 1
    assert state.verification_status is VerificationStatus.PASSED
    assert (tmp_path / "README.md").is_file()
    assert state.main_model_call_count <= 24


def test_invalid_first_summary_uses_local_fallback_and_main_work_continues(tmp_path) -> None:
    runner, model = two_compression_fixture(tmp_path, first_summary="invalid")
    state = runner.run("repair project")
    assert state.status is AgentStatus.SUCCESS
    assert state.summary_model_call_count == 1
    assert state.summary_fallback_latched is True
    assert state.main_model_call_count >= 2
    assert summary_request_count(model.requests) == 1


def test_post_checkpoint_exploration_stops_as_no_progress_not_main_limit(tmp_path) -> None:
    runner = endless_novel_read_fixture(tmp_path, BudgetProfile.STANDARD)
    state = runner.run("inspect indefinitely")
    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.NO_PROGRESS
    assert state.main_model_call_count < 24
```

Fixtures use `FakeModelClient`, fake clock, real local tools constrained to `tmp_path`, and fake or existing safe verification executors. They never import OpenAI SDK clients or read environment credentials.

- [ ] **Step 2: Run integration RED, implement only missing wiring, and run GREEN**

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/integration/test_adaptive_convergence.py
```

Expected: any remaining cross-component wiring gap fails with a specific assertion. Use systematic debugging before each production correction; do not relax the scenario.

After minimal wiring corrections, run the same command. Expected GREEN: all four pass.

- [ ] **Step 3: Write documentation contract RED tests**

Add to `tests/test_docs.py`:

```python
def test_docs_explain_profiles_phases_and_exact_default_limits() -> None:
    combined = read_public_docs()
    for required in (
        "standard", "deep", "BudgetProfile", "RunMode",
        "DISCOVER", "ACT", "VERIFY", "FINISH",
        "24", "4", "48", "80", "20 分钟",
        "40", "6", "140", "30 分钟",
        "no_progress",
    ):
        assert required in combined


def test_docs_do_not_claim_unlimited_budget_planner_or_provider_memory() -> None:
    combined = read_public_docs().lower()
    for forbidden in (
        "无限预算", "自动 planner", "服务端会话替代本地历史",
        "恢复 encrypted reasoning", "绕过验证",
    ):
        assert forbidden not in combined
```

- [ ] **Step 4: Run docs RED, update exact documentation, and run GREEN**

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_docs.py -k "profiles_phases or unlimited_budget"
```

Expected RED: public docs and `AGENTS.md` still describe the legacy 12/40/10-minute defaults.

Update:

- `AGENTS.md`: replace only the legacy limit bullet with exact `standard`/`deep` limits, separate main/summary counts, summary fallback, and no-progress checkpoint language.
- `README.md`: add a concise architecture highlight and CLI/Web profile examples.
- `README.txt`: preserve its length contract while adding the two profile names and deterministic convergence highlight.
- `docs/USAGE.md`: document selection, immutable per-run behavior, status meanings, troubleshooting for `no_progress`, `main_model_call_limit`, `provider_attempt_limit`, and summary fallback.

Do not claim Task26 is implemented until all final commands below pass. Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_docs.py
```

Expected: all documentation contracts pass.

- [ ] **Step 5: Run exact component verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_budget.py tests/test_progress.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_model.py tests/test_context.py tests/test_termination.py tests/test_agent_loop.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_logging.py tests/test_report.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_session.py tests/test_session_store.py tests/test_session_runtime.py tests/test_session_controller.py tests/test_session_events.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_cli.py tests/test_app.py tests/test_web_api.py tests/test_web_sse.py tests/test_web_gui.py
.\.venv\Scripts\python.exe -m pytest -q tests/integration/test_adaptive_convergence.py
node --test tests/js/web_gui.test.mjs
```

Expected: every command exits `0`; report actual counts rather than plan estimates.

- [ ] **Step 6: Run explicit provider and Task1–Task25 regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_openai_client.py tests/test_chat_completions_client.py tests/test_streaming.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_path_safety.py tests/test_command_safety.py tests/test_verification.py
.\.venv\Scripts\python.exe -m pytest -q tests/integration/test_agent_repair.py tests/integration/test_agent_failures.py tests/integration/test_read_only_agent.py
```

Expected: all commands exit `0`; no real network or API key is used.

- [ ] **Step 7: Run the complete repository suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/js/web_gui.test.mjs
```

Expected: exit `0`; capture passed, failed, skipped, warning, and Node totals.

- [ ] **Step 8: Run Windows-specific safety and process checks**

Run the actual existing node IDs discovered by collection:

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q tests/test_path_safety.py tests/test_command_safety.py tests/tools/test_shell_tool.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_path_safety.py -k "symlink or junction or reparse"
.\.venv\Scripts\python.exe -m pytest -q tests/tools/test_shell_tool.py -k "timeout or process_tree or taskkill"
```

Expected: mandatory Windows reparse/junction and process-tree cases execute. If an environment-specific symlink privilege case skips, report the exact node and confirm the pure-policy counterpart ran; do not introduce a permanent skip.

- [ ] **Step 9: Run signature, SDK isolation, dependency, secret, and scope audits**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import inspect; from coding_agent.model import ModelClient; from coding_agent.tools.base import Tool; from coding_agent.verification import VerificationGate; print(inspect.signature(ModelClient.complete)); print(inspect.signature(Tool.execute)); print(inspect.signature(VerificationGate.evaluate))"
rg -n "from openai|import openai" src/coding_agent --glob "!openai_client.py" --glob "!chat_completions_client.py" --glob "!app.py"
rg -n "LangChain|LlamaIndex|Agents SDK|AutoGen|CrewAI|MCP" pyproject.toml src tests
.\.venv\Scripts\python.exe -m pip check
rg -n "OPENAI_API_KEY\s*=|CHAT_COMPLETIONS_API_KEY\s*=|Authorization:\s*Bearer|sk-[A-Za-z0-9]" . --glob "!.git/**" --glob "!.coding-agent/**"
rg -n "previous_response_id|conversation=" src/coding_agent
rg -n "TO[D]O|TB[D]|FIXM[E]|pytest\.skip|pytest\.mark\.skip|xfail" src tests docs AGENTS.md DESIGN.md TASKS.md
```

Expected:

- core signatures are unchanged;
- SDK imports remain confined to approved adapter/composition boundaries;
- no Agent framework/new dependency appears;
- `pip check` exits `0`;
- no credential value, service-state substitution, unfinished marker, or new test suppression appears;
- existing deliberate test skips are individually explained if the scan finds them.

- [ ] **Step 10: Run privacy and absolute-path audits**

Run:

```powershell
rg -n "C:\\Users\\|D:\\code\\|/home/|continuation_items|encrypted_reasoning|summary_text|Execution control:" .coding-agent README.md README.txt docs src/coding_agent/session.py src/coding_agent/session_store.py src/coding_agent/logging.py src/coding_agent/report.py --glob "!*.pyc"
```

Expected: no persisted/logged host path, continuation, encrypted reasoning, summary body, or dynamic control text. Source identifiers and documentation descriptions may match only where tests explicitly assert they are excluded from output; inspect every match.

- [ ] **Step 11: Review whitespace, status, and the complete diff**

Run:

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff -- AGENTS.md DESIGN.md TASKS.md src/coding_agent tests README.md README.txt docs/USAGE.md docs/superpowers/plans/Task26.md
```

Expected: only Task26-approved files appear, `git diff --check` exits `0`, Task26 remains `进行中`, and no file is staged.

- [ ] **Step 12: Stop for user review and authorization**

Do not stage or commit. Report all RED/GREEN commands and real outputs, complete suite totals, Windows executed/skipped cases, layered budget evidence, context/continuation evidence, progress/phase evidence, migration evidence, GUI evidence, audits, changed files, status, and deviations. Wait for the user to inspect and authorize completion/commit.

**Acceptance:** the four real failure-shaped offline scenarios converge as designed, every legacy subsystem remains green, documentation matches implemented behavior, and the review stop contains no unsupported completion claim.

---

## Approved Convergence-Recovery Amendment

> **Historical baseline:** This section records the already-executed
> convergence implementation that exposed the real-run defect. Its
> successful-read batch accounting and immediate no-extra-call stop are
> intentionally replaced by `Corrective Task 3`; they are not current
> acceptance criteria and must not be re-executed.

The user approved this amendment after three real compatible-provider runs
showed two distinct deterministic failures: prolonged successful reads reached
`no_progress` without mutation, while a later run successfully created one
Python file and then ended after `shell_syntax_denied` followed by two
`executable_denied` results. The audit facts proved that the provider, file
mutation, mutation ledger, and Task8 enforcement were operating; the missing
boundary was deterministic convergence between discovery, mutation, and
model-selected verification.

The amendment locks these decisions:

- Keep the existing single `AgentRunner`; do not add a Planner.
- An ordinary checkpoint permits one final response that attempts reads for
  `standard` and two for `deep`. A duplicate-only read response closes reads
  immediately. Once the applicable allowance is consumed, read calls receive
  paired `agent_rejected:decision_required` results and are not executed.
- A successful mutation makes `AgentState.has_unverified_changes` true until
  a passing result has `validation_index == mutation_index`.
- `required_verification_pending` remains exclusively the forced
  user-`--verify` reservation and is not reused for model-selected validation.
- On the model response after a mutation, only a credible verification request
  is permitted until real failed verification evidence exists. A single model
  response that contains several mutation calls is evaluated against the state
  at the start of that response, so coherent multi-file writes remain legal.
- Failed verification opens a bounded repair epoch. Its reads use the same
  one/two final-read allowance; another mutation closes that epoch and again
  requires fresh verification.
- Rejected commands are never rewritten. Safe feedback states the exact
  single-process forms and the existing consecutive-three safety limit gives
  the initial rejection plus two correction opportunities.
- A modify response that reports completion or blockage while changes remain
  unverified, or exhaustion of deterministic recovery after a mutation, ends
  with `TerminationReason.CHANGES_UNVERIFIED`. It remains a failed storage
  status and exit code `1`, never `SUCCESS`.
- The GUI renders this reason as `修改待验证`, using persisted changed paths,
  verification status, and the latest safe tool error code. It does not reveal
  command text, output, host paths, or provider content.
- Internal paired `ToolResult.error` values and JSONL audit events keep the
  exact namespaced codes `agent_rejected:decision_required` and
  `agent_rejected:verification_required`. The Session persistence/SSE boundary
  must not relax its existing `[a-z][a-z0-9_]{0,63}` safe-code grammar:
  `SessionController` projects the two Agent codes to `decision_required` and
  `verification_required`, and projects an already-validated
  `security_rejected:<SafetyCode>` audit value to its `<SafetyCode>` suffix.
  Arbitrary namespaces or suffixes are rejected rather than persisted.
- `safety.py`, the Tool protocol, message types, provider adapters, verification
  credibility rules, database schema, and approved dependencies remain
  unchanged.

---

### Task 10: Reconfirm the uncommitted Task26 baseline before amendment work

**Files:**
- Read: `AGENTS.md`
- Read: `DESIGN.md`
- Read: `TASKS.md`
- Read: `docs/superpowers/plans/Task26.md`
- Read: all files currently changed by the approved Task26 implementation
- Modify: none

**Interfaces:**
- Consumes: the user-reviewed Task26 implementation with Task26 still
  `进行中` and no staged files.
- Produces: fresh baseline evidence that the amendment starts from the exact
  approved workspace and does not hide an unrelated change.

- [ ] **Step 1: Re-read the project rules and the complete amended plan**

Run:

```powershell
Get-Content -Raw AGENTS.md
Get-Content -Raw DESIGN.md
Get-Content -Raw TASKS.md
Get-Content -Raw docs/superpowers/plans/Task26.md
```

Expected: all commands exit `0`; Task26 is the only `进行中` task; the plan
contains the amendment decisions above.

- [ ] **Step 2: Verify repository identity and the existing Task26 diff**

Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git log -3 --oneline
git status --short --untracked-files=all
git diff --check
git diff --stat
```

Expected: the repository is the configured coding-agent repository on the
current approved branch; `git diff --check` exits `0`; no file is staged; the
only changes are the already-reviewed Task26 files plus this amended plan. Do
not stage, commit, switch branches, create a worktree, or touch the separate
demo workspace.

- [ ] **Step 3: Run the current Task26 baseline before adding amendment tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
node --test tests/js/web_gui.test.mjs
```

Expected: both commands exit `0`. Record the actual pass, fail, skip, warning,
and Node test counts. A failure stops execution before any amendment test or
production edit.

**Acceptance:** the starting code, tests, status, and diff are understood and
green; no file changes occur in this task.

---

### Task 11: Make checkpoint final-read allowance deterministic

**Files:**
- Modify: `src/coding_agent/progress.py`
- Modify: `tests/test_progress.py`

**Interfaces:**
- Consumes: `BudgetProfile`, existing progress thresholds, and successful
  read-tool observations.
- Produces:

```python
class ProgressAction(StrEnum):
    CONTINUE = "continue"
    CHECKPOINT = "checkpoint"
    DECISION_REQUIRED = "decision_required"
    STOP = "stop"

@dataclass(frozen=True, slots=True)
class ProgressLimits:
    main_turn_limit: int
    read_tool_limit: int
    idle_turn_limit: int
    post_checkpoint_turn_limit: int
    final_decision_remaining_calls: int = 4
    final_read_batch_limit: int = 1

@dataclass(slots=True)
class ProgressLedger:
    post_checkpoint_read_batches: int = 0
    decision_required: bool = False

    def activate_checkpoint(self) -> bool: ...
```

`ProgressLimits.for_profile(STANDARD)` returns final read limit `1`; `DEEP`
returns `2`. `activate_checkpoint()` returns `False` without mutation when a
checkpoint is already active; otherwise it activates the checkpoint and resets
both amendment counters.

- [ ] **Step 1: Write profile, equality, and reset RED tests**

Add these tests to `tests/test_progress.py`, and update the two existing exact
`ProgressLimits` expectations to include the sixth positional value:

```python
def test_final_read_batch_limits_are_exact_by_profile() -> None:
    standard = ProgressLimits.for_profile(BudgetProfile.STANDARD)
    deep = ProgressLimits.for_profile(BudgetProfile.DEEP)

    assert standard.final_read_batch_limit == 1
    assert deep.final_read_batch_limit == 2


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5])
def test_final_read_batch_limit_requires_positive_integer(invalid: object) -> None:
    with pytest.raises(ValueError, match="final_read_batch_limit"):
        ProgressLimits(4, 12, 2, 2, 4, invalid)  # type: ignore[arg-type]


def _finish_checkpoint_read_batch(ledger: ProgressLedger, index: int) -> None:
    call = ToolCall(
        call_id=f"read-{index}",
        name="read_file",
        arguments={
            "path": f"src/file-{index}.py",
            "start_line": 1,
            "end_line": 10,
        },
    )
    result = ToolResult(
        call_id=call.call_id,
        tool_name=call.name,
        status="ok",
        output=f"1: value-{index}",
    )
    ledger.begin_main_turn()
    ledger.observe_tool(
        call,
        result,
        mutation_advanced=False,
        verification_recorded=False,
    )
    ledger.finish_main_turn()


@pytest.mark.parametrize(
    ("profile", "allowed_batches"),
    [
        (BudgetProfile.STANDARD, 1),
        (BudgetProfile.DEEP, 2),
    ],
)
def test_checkpoint_allows_exact_final_read_batches_then_requires_decision(
    profile: BudgetProfile,
    allowed_batches: int,
) -> None:
    limits = ProgressLimits.for_profile(profile)
    ledger = ProgressLedger()
    assert ledger.activate_checkpoint() is True

    for index in range(allowed_batches):
        assert ledger.decide(
            limits,
            remaining_main_calls=10,
        ) == ProgressDecision(ProgressAction.CONTINUE)
        _finish_checkpoint_read_batch(ledger, index)

    assert ledger.decide(
        limits,
        remaining_main_calls=10,
    ) == ProgressDecision(
        ProgressAction.DECISION_REQUIRED,
        "final_read_allowance_exhausted",
    )
    assert ledger.decision_required is True
    assert ledger.post_checkpoint_read_batches == allowed_batches
    assert ledger.decide(
        limits,
        remaining_main_calls=10,
    ) == ProgressDecision(ProgressAction.CONTINUE)


def test_strong_progress_clears_final_read_and_decision_latches() -> None:
    ledger = ProgressLedger(
        checkpoint_active=True,
        post_checkpoint_main_turns=1,
        post_checkpoint_read_batches=1,
        decision_required=True,
    )
    call = ToolCall("write", "write_file", {"path": "result.py", "content": "x"})
    result = ToolResult(
        call_id="write",
        tool_name="write_file",
        status="ok",
        output="created",
        metadata=ToolResultMetadata(changed_paths=("result.py",)),
    )
    ledger.begin_main_turn()
    ledger.observe_tool(
        call,
        result,
        mutation_advanced=True,
        verification_recorded=False,
    )
    ledger.finish_main_turn()

    assert ledger.checkpoint_active is False
    assert ledger.post_checkpoint_main_turns == 0
    assert ledger.post_checkpoint_read_batches == 0
    assert ledger.decision_required is False
```

- [ ] **Step 2: Run the progress RED tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_progress.py -k "final_read or decision_latches or exact_by_profile"
```

Expected: nonzero because `final_read_batch_limit`, `DECISION_REQUIRED`,
`post_checkpoint_read_batches`, `decision_required`, and
`activate_checkpoint()` do not exist.

- [ ] **Step 3: Implement the minimal progress state and equality semantics**

In `src/coding_agent/progress.py`:

1. Add the enum value and the two ledger fields exactly as declared above.
2. Append `final_read_batch_limit` after `final_decision_remaining_calls` so
   existing five-argument construction remains source-compatible.
3. Validate the new limit with `_positive_integer`.
4. Implement `activate_checkpoint()` and use it from both automatic checkpoint
   branches in `decide()`.
5. Historical behavior incremented `post_checkpoint_read_batches` only when
   the checkpoint was active, the completed turn had one or more successful
   read tools, and no strong progress occurred. `Corrective Task 3` replaces
   this with response-level accounting for every attempted read batch,
   including duplicate and failed attempts. Multiple reads in one response
   still count as one batch.
6. In `_record_strong_progress()`, reset both amendment fields.
7. In `decide()`, preserve `STOP` as the first active-checkpoint check. Then
   return `CONTINUE` if `decision_required` is already latched; otherwise latch
   and return `DECISION_REQUIRED/final_read_allowance_exhausted` at equality.

This historical exclusion is superseded: corrective accounting counts a
response that attempts reads toward the allowance even when those reads are
rejected, failed, or repeated. Synthetic paired results remain non-executions
and are tested separately from novelty classification.

- [ ] **Step 4: Run progress GREEN and regression**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_progress.py
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_budget.py tests/test_termination.py tests/test_agent_loop.py -k "progress or checkpoint or no_progress or profile"
```

Expected: both commands exit `0`; record actual test counts.

- [ ] **Step 5: Add and pass exact safe control rendering RED/GREEN**

Update the existing rendering test and add:

```python
def test_decision_required_control_exposes_only_safe_action_contract() -> None:
    ledger = ProgressLedger(
        checkpoint_active=True,
        post_checkpoint_read_batches=1,
        decision_required=True,
    )
    text = render_execution_control(
        ledger=ledger,
        decision=ProgressDecision(
            ProgressAction.DECISION_REQUIRED,
            "final_read_allowance_exhausted",
        ),
        profile=BudgetProfile.STANDARD,
        remaining_main_calls=12,
        remaining_tool_calls=40,
        verification_reserve=0,
        has_unverified_changes=False,
    )

    assert "final read batches remaining: 0" in text
    assert "further read tools will be rejected" in text
    assert "required decision: modify, answer, or report blocker" in text
    assert "command" not in text.casefold()
    assert len(text) <= 768
```

Change the signature additively to:

```python
def render_execution_control(
    *,
    ledger: ProgressLedger,
    decision: ProgressDecision,
    profile: BudgetProfile,
    remaining_main_calls: int,
    remaining_tool_calls: int,
    verification_reserve: int,
    has_unverified_changes: bool = False,
) -> str: ...
```

Run RED before implementation and GREEN after implementation:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_progress.py -k "control"
```

Expected RED: unexpected keyword or missing final-read text. Expected GREEN:
exit `0` with the actual selected count. Rendering derives the allowance from
`ProgressLimits.for_profile(profile)` and never includes paths or payloads.

**Acceptance:** checkpoint reads are counted by response batch, exact equality
activates one decision latch, a strong local fact clears it, and rendered
control is bounded and privacy-safe.

---

### Task 12: Expose the exact verification contract without changing safety

**Files:**
- Modify: `src/coding_agent/state.py`
- Modify: `src/coding_agent/instructions.py`
- Modify: `src/coding_agent/tools/shell.py`
- Modify: `tests/test_agent_loop.py`
- Modify: `tests/test_instructions.py`
- Modify: `tests/tools/test_shell_tool.py`

**Interfaces:**
- Consumes: Task8 `CommandPolicy`, Task11 verification freshness, and existing
  `RunCommandTool` arguments `{command, purpose}`.
- Produces:

```python
@property
def AgentState.has_unverified_changes(self) -> bool: ...
```

No field is added for this derived fact. `required_verification_pending` keeps
its existing user-verify-only meaning.

- [ ] **Step 1: Write derived-state RED tests**

Add to `tests/test_agent_loop.py`:

```python
def test_has_unverified_changes_is_derived_from_freshness(tmp_path: Path) -> None:
    state = AgentState.start("change", tmp_path, 0.0)
    assert state.has_unverified_changes is False

    state.mutation_index = 1
    state.modified_paths = ("task_manager.py",)
    state.verification_status = VerificationStatus.STALE
    assert state.has_unverified_changes is True

    state.verification_status = VerificationStatus.PASSED
    assert state.has_unverified_changes is True

    command = AuthorizedCommand(
        argv=(sys.executable, "task_manager.py"),
        normalized_command="python task_manager.py",
        purpose="verification",
        source=CommandSource.MODEL,
    )
    state.last_verification = VerificationResult(
        status=VerificationStatus.PASSED,
        validation_index=1,
        command=command.normalized_command,
        source=command.source,
        exit_code=0,
        stdout="ok",
        stderr="",
        timed_out=False,
        truncated=False,
        duration_ms=1,
        error=None,
    )
    assert state.has_unverified_changes is False


def test_forced_verification_pending_remains_independent_of_derived_state(
    tmp_path: Path,
) -> None:
    state = AgentState.start("change", tmp_path, 0.0)
    state.mutation_index = 1
    state.verification_status = VerificationStatus.STALE

    assert state.has_unverified_changes is True
    assert state.required_verification_pending is False
```

Add `VerificationResult` to the existing import from
`coding_agent.verification`; do not introduce a duplicate test type.

- [ ] **Step 2: Run derived-state RED, implement, and run GREEN**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_loop.py -k "has_unverified_changes or forced_verification_pending_remains"
```

Expected RED: `AgentState` has no `has_unverified_changes`. Implement the exact
approved property in `state.py`, requiring mutation index above zero, passing
status, a result, and matching validation/mutation indexes. Re-run the same
command; expected GREEN with exit `0`.

- [ ] **Step 3: Write command-contract RED tests**

Add to `tests/test_instructions.py`:

```python
def test_modify_instructions_publish_exact_safe_verification_forms(
    tmp_path: Path,
) -> None:
    text = RunInstructionBuilder().build(
        tmp_path,
        run_mode=RunMode.MODIFY,
    ).text

    assert "one process per run_command call" in text
    assert "python <workspace-relative-file.py>" in text
    assert "python -m pytest" in text
    assert "python -m unittest" in text
    assert 'purpose="verification"' in text
    assert "run_java_tests" in text
    assert "&&" in text and "pipes" in text


def test_read_only_instructions_do_not_advertise_execution_forms(
    tmp_path: Path,
) -> None:
    text = RunInstructionBuilder().build(
        tmp_path,
        run_mode=RunMode.READ_ONLY,
    ).text

    assert "python <workspace-relative-file.py>" not in text
    assert 'purpose="verification"' not in text
```

Add to `tests/tools/test_shell_tool.py`:

```python
def test_run_command_schema_describes_single_process_verification_contract() -> None:
    description = RunCommandTool.schema["description"]

    assert isinstance(description, str)
    assert "single process" in description
    assert "python <workspace-relative-file.py>" in description
    assert "python -m pytest" in description
    assert 'purpose="verification"' in description
    assert "no shell operators" in description
```

- [ ] **Step 4: Run contract RED, implement, and run GREEN**

Run RED:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_instructions.py -k "verification_forms or execution_forms"
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/tools/test_shell_tool.py -k "schema_describes_single_process"
```

Expected: both commands fail because instructions only list tool names and the
schema description is generic.

Change only explanatory strings. The modify instructions and schema must say:

```text
Use one process per run_command call. Do not use shell operators such as && or
||, redirection, pipes, command chaining, py, or python3. Supported
verification forms include
python <workspace-relative-file.py>, python -m pytest ..., and
python -m unittest ... with purpose="verification". Use run_java_tests for
Java verification.
```

Do not change schema fields, strictness, execution code, `CommandPolicy`, or
the read-only capability list. Re-run both commands; expected GREEN with exit
`0` and actual counts recorded.

- [ ] **Step 5: Run safety and verification regressions**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_command_safety.py tests/tools/test_shell_tool.py tests/test_verification.py tests/test_instructions.py
```

Expected: exit `0`; existing allow/deny decisions, shell-free execution,
timeouts, output bounds, and evidence credibility remain unchanged.

**Acceptance:** the model receives an exact, provider-neutral command contract;
the security policy is unchanged; optional model verification and forced user
verification remain separate.

---

### Task 13: Enforce decision and verification gates in `AgentRunner`

**Files:**
- Modify: `src/coding_agent/agent.py`
- Modify: `src/coding_agent/progress.py`
- Modify: `src/coding_agent/state.py`
- Modify: `src/coding_agent/logging.py`
- Modify: `tests/test_agent_loop.py`
- Modify: `tests/test_logging.py`

**Interfaces:**
- Consumes: `ProgressLedger.decision_required`,
  `AgentState.has_unverified_changes`, existing `VerificationGate`, and Task8
  security results.
- Produces:

```python
class TerminationReason(StrEnum):
    CHANGES_UNVERIFIED = "changes_unverified"
```

Private Agent helpers use these exact rules:

```python
_READ_TOOL_NAMES = frozenset({"list_directory", "read_file", "inspect_git"})
_VERIFICATION_TOOL_NAMES = frozenset({"run_command", "run_java_tests"})

def _is_requested_verification(call: ToolCall) -> bool:
    return (
        call.name in _VERIFICATION_TOOL_NAMES
        and call.arguments.get("purpose") == "verification"
    )
```

The decision gate and verification gate are Agent orchestration policy, not
Task8 authorization. Their paired failures start with `agent_rejected:` and
never call `ToolRegistry.execute`.

- [ ] **Step 1: Write decision-required tool-pairing RED tests**

First add this exact helper beside the existing `RecordingTool`; it reuses that
fake's real constructor and execution recording rather than defining another
Tool implementation:

```python
def _named_recording_tool(
    name: str,
    schema: JSONObject,
    *outcomes: ToolExecution | BaseException,
) -> RecordingTool:
    tool = RecordingTool(*outcomes)
    tool.name = name
    tool.schema = deepcopy(schema)
    return tool
```

Add `RunCommandTool` to the existing tool imports. Then add focused tests to
`tests/test_agent_loop.py`:

```python
def test_decision_required_rejects_reads_but_executes_mutation_in_same_batch(
    tmp_path: Path,
) -> None:
    for name in ("first.py", "final.py", "extra.py"):
        (tmp_path / name).write_text(f"# {name}\n", encoding="utf-8")
    read = _named_recording_tool(
        "read_file",
        ReadFileTool.schema,
        ToolExecution(output="1: # first.py"),
        ToolExecution(output="1: # final.py"),
    )
    responses = (
        ModelResponse(
            tool_calls=(
                ToolCall(
                    "first-read",
                    "read_file",
                    {"path": "first.py", "start_line": 1, "end_line": None},
                ),
            )
        ),
        ModelResponse(
            tool_calls=(
                ToolCall(
                    "final-read",
                    "read_file",
                    {"path": "final.py", "start_line": 1, "end_line": None},
                ),
            )
        ),
        ModelResponse(
            tool_calls=(
                ToolCall(
                    "blocked-read",
                    "read_file",
                    {"path": "extra.py", "start_line": 1, "end_line": 2},
                ),
                ToolCall(
                    "allowed-write",
                    "write_file",
                    {"path": "README.md", "content": "# Project\n"},
                ),
            )
        ),
        ModelResponse(text="blocked until verified"),
    )
    runner, client = _runner(
        tmp_path,
        responses,
        tools=(read, WriteFileTool()),
        verification_gate=VerificationGate(
            required_command=None,
            execution_context=ExecutionContext(tmp_path),
        ),
        progress_limits=ProgressLimits(1, 12, 2, 3, 4, 1),
    )

    state = runner.run("create README")

    paired = [
        item
        for item in state.messages
        if isinstance(item, ToolResult) and item.call_id == "blocked-read"
    ]
    assert len(paired) == 1
    assert paired[0].status == "rejected"
    assert paired[0].error is not None
    assert paired[0].error.startswith("agent_rejected:decision_required")
    assert [call["path"] for call in read.executions] == ["first.py", "final.py"]
    assert state.mutation_index == 1
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# Project\n"
    assert client.requests[-1].instructions is not None
```

The following is the historical baseline test with an explicit unused fourth
response. Its `len(client.requests) == 3` assertion documented the defect and
is superseded by the exact one-corrective-response tests in `Corrective Task 3`;
do not preserve this request-count expectation in the corrective implementation:

```python
def test_repeated_read_after_decision_required_stops_without_extra_model_call(
    tmp_path: Path,
) -> None:
    read = _named_recording_tool(
        "read_file",
        ReadFileTool.schema,
        ToolExecution(output="1: first"),
        ToolExecution(output="1: final"),
    )
    responses = (
        ModelResponse(
            tool_calls=(
                ToolCall(
                    "first",
                    "read_file",
                    {"path": "first.py", "start_line": 1, "end_line": None},
                ),
            )
        ),
        ModelResponse(
            tool_calls=(
                ToolCall(
                    "final",
                    "read_file",
                    {"path": "final.py", "start_line": 1, "end_line": None},
                ),
            )
        ),
        ModelResponse(
            tool_calls=(
                ToolCall(
                    "blocked",
                    "read_file",
                    {"path": "extra.py", "start_line": 1, "end_line": None},
                ),
            )
        ),
        ModelResponse(text="must remain unused"),
    )
    runner, client = _runner(
        tmp_path,
        responses,
        tools=(read,),
        progress_limits=ProgressLimits(1, 12, 2, 2, 4, 1),
    )

    state = runner.run("inspect indefinitely")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.NO_PROGRESS
    assert [call["path"] for call in read.executions] == ["first.py", "final.py"]
    blocked = [
        item
        for item in state.messages
        if isinstance(item, ToolResult) and item.call_id == "blocked"
    ]
    assert len(blocked) == 1
    assert blocked[0].error is not None
    assert blocked[0].error.startswith("agent_rejected:decision_required")
    assert len(client.requests) == 3
```

- [ ] **Step 2: Run decision gate RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_loop.py -k "decision_required"
```

Expected: nonzero because `AgentRunner` currently executes every tool through
the Registry and does not handle `ProgressAction.DECISION_REQUIRED`.

- [ ] **Step 3: Implement decision action, paired rejection, and event truth**

In `AgentRunner`:

1. Treat `CHECKPOINT` and `DECISION_REQUIRED` as one-shot
   `DECISION_CHECKPOINT` events. Extend the accepted reason set with
   `final_read_allowance_exhausted`.
2. Append dynamic control when either the checkpoint or unverified-change gate
   is active, passing `has_unverified_changes` into
   `render_execution_control()`.
3. Snapshot `decision_required_at_turn_start` and
   `unverified_at_turn_start` immediately before each main model call. The
   snapshot applies to the entire returned tool batch so the first mutation in
   a multi-file response does not block later mutations in that response.
4. For a read call under the decision latch, append exactly one paired
   `ToolResult(status="rejected",
   error="agent_rejected:decision_required: further read tools are disabled; modify, answer, or report blocker")`.
5. Emit `TOOL_CALL_STARTED` followed by `TOOL_CALL_COMPLETED` with
   `executed=False`, increment the attempted tool count once, observe no
   progress, and do not call `ToolRegistry.execute`.
6. Extend `_safe_tool_error_code()` so Agent-stage results project either
   `agent_rejected:decision_required` or
   `agent_rejected:verification_required` into JSONL audit events; allow only
   those two new namespaced codes in JSONL validation. Session persistence is
   handled separately in Task14 and must never receive a colon-containing
   safe code. Add `final_read_allowance_exhausted` and
   `verification_failure` to the exact JSONL `DECISION_CHECKPOINT` reason
   allowlist. Do not classify Agent rejection as `security_rejected`.

Run GREEN:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_loop.py -k "decision_required"
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_logging.py -k "tool_call_completed"
```

Expected: both exit `0`; blocked calls are paired and logged as not executed,
and mutation calls in the same response still run sequentially.

- [ ] **Step 4: Write verification-required and completion-strength RED tests**

Add:

```python
def test_unverified_mutation_rejects_exploration_on_next_model_turn(
    tmp_path: Path,
) -> None:
    write = ToolCall("write", "write_file", {"path": "task.py", "content": "print('ok')\n"})
    read = ToolCall(
        "read-after-write",
        "read_file",
        {"path": "task.py", "start_line": 1, "end_line": None},
    )
    gate = VerificationGate(required_command=None, execution_context=ExecutionContext(tmp_path))
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(write,)),
            ModelResponse(tool_calls=(read,)),
            ModelResponse(text="cannot verify safely"),
        ),
        tools=(WriteFileTool(), ReadFileTool()),
        verification_gate=gate,
    )

    state = runner.run("write a Python file")

    result = next(
        item
        for item in state.messages
        if isinstance(item, ToolResult) and item.call_id == "read-after-write"
    )
    control = client.requests[1].instructions
    assert control is not None
    assert "unverified changes: active" in control
    assert "required action: verify, repair failed verification, or report blocker" in control
    assert result.error is not None
    assert result.error.startswith("agent_rejected:verification_required")
    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.CHANGES_UNVERIFIED
    assert state.mutation_index == 1
    assert state.verification_attempt_count == 0


def test_unverified_completion_is_not_strong_progress(tmp_path: Path) -> None:
    gate = VerificationGate(required_command=None, execution_context=ExecutionContext(tmp_path))
    runner, _ = _runner(
        tmp_path,
        (
            ModelResponse(
                tool_calls=(
                    ToolCall("write", "write_file", {"path": "a.py", "content": "x = 1\n"}),
                )
            ),
            ModelResponse(text="file written but I cannot verify it"),
        ),
        tools=(WriteFileTool(),),
        verification_gate=gate,
    )

    state = runner.run("write a.py")

    assert state.termination_reason is TerminationReason.CHANGES_UNVERIFIED
    assert state.progress.phase is AgentPhase.ACT
    assert state.progress.epoch == 1
    assert state.completion_text == "file written but I cannot verify it"


def test_failed_verification_opens_one_standard_repair_read_batch(
    tmp_path: Path,
) -> None:
    command = _named_recording_tool(
        "run_command",
        RunCommandTool.schema,
        _verification_execution(1, stderr="test failed"),
    )
    read = _named_recording_tool(
        "read_file",
        ReadFileTool.schema,
        ToolExecution(output="1: print('broken')"),
    )
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "write",
                        "write_file",
                        {"path": "task.py", "content": "print('broken')\n"},
                    ),
                )
            ),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "verify",
                        "run_command",
                        {"command": "python -m pytest -q", "purpose": "verification"},
                    ),
                )
            ),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "repair-read",
                        "read_file",
                        {"path": "task.py", "start_line": 1, "end_line": None},
                    ),
                )
            ),
            ModelResponse(text="verification remains blocked"),
        ),
        tools=(WriteFileTool(), command, read),
        verification_gate=VerificationGate(
            required_command=None,
            execution_context=ExecutionContext(tmp_path),
        ),
        budget_profile=BudgetProfile.STANDARD,
    )

    state = runner.run("write, test, and repair")

    assert len(command.executions) == 1
    assert len(read.executions) == 1
    assert state.last_verification is not None
    assert state.last_verification.status is VerificationStatus.FAILED
    assert state.progress.phase is AgentPhase.ACT
    assert state.termination_reason is TerminationReason.CHANGES_UNVERIFIED
    assert "progress checkpoint: active" in (client.requests[2].instructions or "")
    assert "further read tools will be rejected" in (client.requests[3].instructions or "")
```

Also update existing completion tests so only a real read-only `ANSWERED` or a
modify `SUCCESS` records completion as strong and transitions to `FINISH`.
An unverified completion must not clear a checkpoint before its terminal
classification.

- [ ] **Step 5: Run verification gate RED, implement, and run GREEN**

Run RED:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_loop.py -k "unverified_mutation or unverified_completion or completion_is_not_strong"
```

Expected: nonzero because post-mutation reads execute, completion is marked
strong before gate evaluation, and `CHANGES_UNVERIFIED` does not exist.

Implement:

1. Add the new termination enum value.
2. Extend `render_execution_control()` so `has_unverified_changes=True`
   appends exactly `unverified changes: active`, the required action asserted
   above, and the safe single-process verification forms from Task12. The
   section contains no path, rejected command, output, or exception text.
3. Snapshot `unverified_at_turn_start` for the complete response batch.
4. While that snapshot is true and no current failed verification evidence
   exists, allow only `run_command`/`run_java_tests` calls whose exact
   `purpose` is `verification`. Pair all other calls with
   `agent_rejected:verification_required` without Registry execution.
5. If current evidence at the same mutation index has status `FAILED`,
   `TIMED_OUT`, or `ERROR`, allow read and mutation tools for repair; command
   calls still require `purpose="verification"`.
6. When model-selected verification evidence is recorded, transition through
   `VERIFY`. Passing evidence stays available for final evaluation. Failed,
   timed-out, or error evidence transitions to `ACT`, activates one repair
   checkpoint, and emits `DECISION_CHECKPOINT/verification_failure`.
7. Move `observe_completion_candidate()` and `FINISH` transition after terminal
   classification. Preserve the existing gate-less `COMPLETION_CANDIDATE`
   compatibility test. A read-only answer marks strong and finishes; a modify
   success marks strong only after `VerificationOutcome.SUCCESS`.
8. If a non-forced gate sees non-empty completion text while
   `has_unverified_changes` is true, preserve the bounded completion text and
   terminate `CHANGES_UNVERIFIED` without claiming success.
9. Map `CONSECUTIVE_SAFETY_REJECTIONS`, `CONSECUTIVE_TOOL_ERRORS`, or
   `NO_PROGRESS` to `CHANGES_UNVERIFIED` only when the state has unverified
   modifications. Keep internal, audit, provider, time, user interruption, and
   fatal reasons exact.

Run GREEN:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_loop.py -k "unverified or completion or verification_failure or read_only_text"
```

Expected: exit `0`; record the actual selected count.

- [ ] **Step 6: Write safe command-correction RED tests**

Add an Agent test with a registered `run_command` fake that returns the same
Task8 rejection shapes:

```python
@pytest.mark.parametrize(
    "code",
    ["shell_syntax_denied", "executable_denied"],
)
def test_command_security_rejection_returns_bounded_correction_contract(
    tmp_path: Path,
    code: str,
) -> None:
    command = _named_recording_tool(
        "run_command",
        RunCommandTool.schema,
        SafetyViolation(SafetyCode(code), "rejected"),
    )
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(
                tool_calls=(
                    ToolCall("write", "write_file", {"path": "task.py", "content": "print('ok')\n"}),
                )
            ),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "bad-command",
                        "run_command",
                        {"command": "unsafe", "purpose": "verification"},
                    ),
                )
            ),
            ModelResponse(text="blocked"),
        ),
        tools=(WriteFileTool(), command),
        verification_gate=VerificationGate(
            required_command=None,
            execution_context=ExecutionContext(tmp_path),
        ),
    )

    state = runner.run("write and verify")
    next_request = client.requests[-1]
    rendered = "\n".join(
        item.error or ""
        for item in next_request.messages
        if isinstance(item, ToolResult)
    )
    assert "one process" in rendered
    assert "python <workspace-relative-file.py>" in rendered
    assert "python -m pytest" in rendered
    assert 'purpose="verification"' in rendered
    assert str(tmp_path) not in rendered
    assert sys.executable not in rendered
    assert state.status is AgentStatus.FAILED
```

The existing Registry maps the scripted real `SafetyViolation` to the same
`ToolResult` path used in production; no new exception or fake result type is
introduced.

- [ ] **Step 7: Run correction RED, implement, and run GREEN**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_loop.py -k "security_rejection_returns_bounded_correction"
```

Expected RED: the next request contains only the generic safety public message.

After Registry returns a `security_rejected:shell_syntax_denied` or
`security_rejected:executable_denied` result, construct a new immutable paired
`ToolResult` with the same call ID, tool name, status, output, and metadata, but
replace only its public error text with this bounded contract:

```text
security_rejected:<code>: command rejected; use one process without shell
operators; verification forms: python <workspace-relative-file.py>,
python -m pytest ..., or python -m unittest ... with purpose="verification";
use run_java_tests for Java
```

Do not alter other safety codes or expose the rejected command. Re-run the same
test; expected GREEN.

- [ ] **Step 8: Prove the existing three-rejection boundary and BaseException semantics**

Add this test; keep the existing
`test_three_security_rejections_use_security_reason` unchanged as the
zero-mutation control:

```python
def test_three_security_rejections_after_mutation_end_changes_unverified(
    tmp_path: Path,
) -> None:
    denied = lambda: SafetyViolation(SafetyCode.EXECUTABLE_DENIED, "denied")
    command = _named_recording_tool(
        "run_command",
        RunCommandTool.schema,
        denied(),
        denied(),
        denied(),
    )
    responses: list[ModelResponse] = [
        ModelResponse(
            tool_calls=(
                ToolCall(
                    "write",
                    "write_file",
                    {"path": "task.py", "content": "print('ok')\n"},
                ),
            )
        )
    ]
    responses.extend(
        ModelResponse(
            tool_calls=(
                ToolCall(
                    f"verify-{index}",
                    "run_command",
                    {"command": f"python{index + 2} task.py", "purpose": "verification"},
                ),
            )
        )
        for index in range(3)
    )
    runner, client = _runner(
        tmp_path,
        tuple(responses),
        tools=(WriteFileTool(), command),
        verification_gate=VerificationGate(
            required_command=None,
            execution_context=ExecutionContext(tmp_path),
        ),
    )

    state = runner.run("write and verify")

    assert state.status is AgentStatus.FAILED
    assert state.termination_reason is TerminationReason.CHANGES_UNVERIFIED
    assert state.consecutive_safety_rejections == 3
    assert state.mutation_index == 1
    assert state.validation_index is None
    assert state.verification_attempt_count == 0
    assert len(command.executions) == 3
    assert len(client.requests) == 4
```

Retain existing `KeyboardInterrupt` and `SystemExit` tests unchanged.

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_loop.py -k "three_rejection or consecutive_safety or keyboard or system_exit"
```

Expected RED before terminal mapping, then GREEN after minimal mapping. No test
may catch `BaseException`, reduce a limit, or add skip/xfail.

- [ ] **Step 9: Run core Agent, progress, verification, and safety regressions**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_progress.py tests/test_agent_loop.py tests/test_termination.py tests/test_verification.py tests/test_command_safety.py tests/tools/test_shell_tool.py
```

Expected: exit `0`; record actual counts. Tool calls remain sequential, every
call ID remains paired, and Task8/Task11 invariants remain green.

- [ ] **Step 10: Request the required core-module code review**

Use `superpowers:requesting-code-review` on the Task11–Task13 diff. The review
must inspect checkpoint equality, whole-response gate snapshots, call/result
pairing, completion-strength timing, unverified terminal mapping, command
non-rewriting, and Task8/Task11 regressions. Do not edit during the review.
If the review reports a concrete issue, return to the smallest affected RED
test before changing production code and rerun Step9 afterward. If the review
mechanism requires agent delegation that is not authorized for the execution
session, stop and obtain user authorization rather than silently skipping this
checkpoint.

**Acceptance:** advisory checkpoints become deterministic at the tool boundary;
multi-file response batches remain legal; unverified work never succeeds;
rejected commands receive safe correction without execution or rewriting; and
all recovery paths have explicit finite bounds.

---

### Task 14: Persist and present `changes_unverified` without a schema migration

**Files:**
- Modify: `src/coding_agent/logging.py`
- Modify: `src/coding_agent/session_events.py`
- Modify: `src/coding_agent/session_controller.py`
- Modify: `src/coding_agent/web_static/app.js`
- Modify: `src/coding_agent/web_static/styles.css`
- Read/verify unchanged: `src/coding_agent/report.py`
- Read/verify unchanged: `src/coding_agent/session.py`
- Modify: `tests/test_logging.py`
- Modify: `tests/test_report.py`
- Modify: `tests/test_session.py`
- Modify: `tests/test_session_controller.py`
- Modify: `tests/test_session_events.py`
- Modify: `tests/test_web_gui.py`
- Modify: `tests/js/web_gui.test.mjs`

**Interfaces:**
- Consumes: failed `FinalReport` with termination reason
  `changes_unverified`, `changed_paths`, verification report, and JSONL-safe
  namespaced tool rejection codes.
- Produces: the existing persisted `failed` run status and exit code `1`, plus
  a derived GUI activity kind `changes_unverified`. At the Session boundary,
  exact namespaced audit codes are projected to grammar-safe suffixes:

```python
def _session_safe_tool_error_code(value: object) -> str | None:
    """Return None or an allowlisted `[a-z][a-z0-9_]{0,63}` wire code."""
```

The accepted mapping is exact: `tool_error` and `tool_rejected` pass through;
`security_rejected:<member of SafetyCode>` becomes that member value;
`agent_rejected:decision_required` becomes `decision_required`; and
`agent_rejected:verification_required` becomes `verification_required`.
No arbitrary colon-containing value or suffix is persisted or published. No
SQLite column, CHECK constraint, report schema version, or REST field is added.

- [ ] **Step 1: Write report/log/session propagation RED tests**

Add this exact report assertion using the test module's existing
`run_metadata()` helper:

```python
def test_changes_unverified_report_is_failed_and_preserves_safe_facts(
    tmp_path: Path,
) -> None:
    state = AgentState.start("write", tmp_path, 0.0)
    state.status = AgentStatus.FAILED
    state.termination_reason = TerminationReason.CHANGES_UNVERIFIED
    state.failure_reason = TerminationReason.CHANGES_UNVERIFIED.value
    state.mutation_index = 1
    state.modified_paths = ("task_manager.py",)
    state.verification_status = VerificationStatus.STALE

    report = FinalReport.from_state(state, run_metadata())

    assert report.status is AgentStatus.FAILED
    assert report.exit_code == 1
    assert report.termination_reason is TerminationReason.CHANGES_UNVERIFIED
    assert report.changed_paths == ("task_manager.py",)
    assert report.verification.status is VerificationStatus.STALE
```

In logging tests, emit `RUN_COMPLETED` with
`termination_reason="changes_unverified"` and assert validation succeeds. In
session tests, round-trip a failed `SessionRunResult` whose final report carries
the same reason and assert the run remains `failed`, not `succeeded`.

- [ ] **Step 2: Run propagation RED, implement allowlist-only changes, and run GREEN**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_logging.py tests/test_report.py tests/test_session.py -k "changes_unverified"
```

Expected RED: logging rejects the new termination reason. Add it to the exact
safe termination allowlist and keep report/session validators compatible with
the existing failed shape. Do not change report or SQLite schema versions.
Re-run; expected GREEN.

- [ ] **Step 3: Write SSE/controller reason-contract RED tests**

Extend existing projection tests so `final_report`, persisted session detail,
and reload preserve:

```python
assert run.status is SessionRunStatus.FAILED
assert run.agent_status == "failed"
assert run.termination_reason == "changes_unverified"
assert run.final_report["changed_paths"] == ["task_manager.py"]
assert run.final_report["verification"]["status"] == "stale"
```

Keep `RUN_FINISHED` SSE's existing `{status, agent_status}` shape; the client
already reloads canonical session detail on terminal convergence. Add
`verification_failure` and `final_read_allowance_exhausted` to the exact
Session/SSE `decision_checkpoint` reason validators, with no arbitrary
free-form reason; the JSONL allowlist was updated in Task13.

Extend the existing `_safe_tool_completed_event()` helper with an optional
`safe_error_code` argument (using status `"rejected"` when it is non-null),
then add this parameterized `SessionController` projection test. It feeds
validated `TOOL_CALL_COMPLETED` data and asserts both persisted `tool_activity`
and emitted `tool_finished` use the expected wire value without degrading the
controller:

```python
@pytest.mark.parametrize(
    ("audit_code", "wire_code"),
    [
        ("security_rejected:executable_denied", "executable_denied"),
        ("agent_rejected:decision_required", "decision_required"),
        ("agent_rejected:verification_required", "verification_required"),
        ("tool_error", "tool_error"),
        ("tool_rejected", "tool_rejected"),
        (None, None),
    ],
)
def test_tool_error_code_is_projected_to_safe_session_wire_code(
    tmp_path: Path,
    audit_code: str | None,
    wire_code: str | None,
) -> None:
    class ScriptedExecutor:
        workspace = tmp_path.resolve(strict=True)

        def execute(self, request: object, **handlers: object) -> SessionRunOutcome:
            del request
            audit = handlers["run_event_handler"]
            audit(_safe_tool_completed_event(safe_error_code=audit_code))
            return failed_outcome()

    controller = make_controller(tmp_path, ScriptedExecutor())
    handle = controller.create_session("project safe code")
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)

    view = controller.get_session(handle.session_id)
    persisted = next(
        event
        for event in view.events
        if event.kind is PersistedSessionEventKind.TOOL_ACTIVITY
    )
    updates = controller.read_updates(handle.run_id).events
    published = next(
        item for item in updates if item.kind is SessionUpdateKind.TOOL_FINISHED
    )

    assert persisted.data["safe_error_code"] == wire_code
    assert published.data["safe_error_code"] == wire_code
    assert all(
        item.kind is not SessionUpdateKind.CONTROLLER_ERROR for item in updates
    )
    assert controller.shutdown(timeout_seconds=1.0) is True
```

Add a direct unit test for `_session_safe_tool_error_code()` that rejects an
unknown namespace and unknown Agent suffix with
`ValueError("invalid_safe_error_code")`.
The helper must validate against the existing `SafetyCode` enum rather than
accepting an arbitrary `security_rejected:` suffix. Keep the strict regex and
validators in `session.py` and `session_events.py` unchanged.

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_session_events.py tests/test_session_controller.py tests/test_web_sse.py -k "changes_unverified or decision_checkpoint or safe_session_wire_code or safe_error_code_is_projected"
```

Expected RED before allowlist/projection updates because the new checkpoint
reasons are rejected and namespaced codes violate the Session safe-code
grammar. Implement only the exact reason additions and the local
`SessionController` projection helper, apply it before both persistence and SSE
publication, and re-run for GREEN. A mapping failure degrades the controller
through its existing deterministic error path; it must not persist raw input.

- [ ] **Step 4: Write GUI RED tests for the dedicated terminal card**

Add this Node test using the established `controllerFixture()` and
`findElements()` helpers:

```javascript
test("unverified changes render one actionable terminal card after reload", async () => {
  const { document, elements } = controllerFixture();
  const api = {
    listSessions: async () => ({
      sessions: [{ session_id: "s1", title: "Pending", status: "idle", last_run_id: "r1" }],
    }),
    listSkills: async () => ({ skills: [], diagnostics: [], usable: true }),
    loadSession: async () => ({
      session: { session_id: "s1", title: "Pending", status: "idle", last_run_id: "r1" },
      runs: [{
        run_id: "r1",
        status: "failed",
        agent_status: "failed",
        termination_reason: "changes_unverified",
        final_report: {
          changed_paths: ["task_manager.py"],
          verification: { status: "stale" },
        },
      }],
      events: [
        {
          run_id: "r1",
          sequence: 1,
          kind: "user_message",
          data: { content: "write a Python file" },
        },
        {
          run_id: "r1",
          sequence: 2,
          kind: "tool_activity",
          data: {
            tool_name: "run_command",
            status: "rejected",
            duration_ms: 0,
            exit_code: null,
            timed_out: false,
            truncated: false,
            safe_error_code: "executable_denied",
            changed_paths: [],
          },
        },
      ],
      skill_ids: [],
    }),
  };
  const controller = gui.createUiController({ document, elements, api });
  await controller.initialize();
  elements.sessionList.dispatchEvent({
    type: "click",
    target: findElements(elements.sessionList, "button")[0],
  });
  await controller.whenIdle();

  const cards = findElements(elements.conversationLog, "div").filter(
    (element) => element.classList.contains("activity-card--changes-unverified"),
  );
  const rendered = elements.conversationLog.textContent;
  controller.destroy();

  assert.equal(cards.length, 1);
  assert.match(rendered, /修改待验证/);
  assert.match(rendered, /task_manager\.py/);
  assert.match(rendered, /尚未执行或尚未通过/);
  assert.match(rendered, /executable_denied/);
  assert.doesNotMatch(rendered, /运行失败/);
});
```

Add a Python static-contract assertion that
`activity-card--changes-unverified` is present, `appendPlainText` is used for
its facts, and `innerHTML` remains absent from `app.js`.

- [ ] **Step 5: Run GUI RED, implement, and run GREEN**

Run RED:

```powershell
node --test --test-name-pattern="unverified changes" tests/js/web_gui.test.mjs
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_web_gui.py -k "unverified"
```

Expected: no dedicated card or copy exists.

In `app.js`, derive the card from `run.termination_reason`,
`run.final_report.changed_paths`, `run.final_report.verification.status`, and
the latest persisted tool activity's `safe_error_code`. Render these bounded
facts:

```text
修改待验证
已修改：<normalized relative paths>
验证：尚未执行或尚未通过
原因：<safe code or verification_not_run>
建议：重新运行并提供强制验证命令，或让 Agent 使用允许的验证形式
```

In `appendActivity`, add the exact modifier class
`activity-card--changes-unverified` for this kind. Extend
`runProjectionFacts()` with `latestSafeErrorCode: Map<run_id, code>` populated
only from persisted `tool_activity.safe_error_code`. Use the existing activity
surface and safe text helpers. Do not render model
tool arguments, command strings, tool output, exception text, or absolute
paths. Add only a compact amber state modifier in `styles.css`; do not create
another assistant bubble or persistent tool-card list.

Re-run the two commands; expected GREEN. Then run:

```powershell
node --test tests/js/web_gui.test.mjs
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_web_gui.py tests/test_web_sse.py tests/test_web_api.py
```

Expected: both exit `0`; record actual counts.

**Acceptance:** storage truth remains failed/nonzero, canonical detail survives
reload, and the GUI distinguishes unverified modifications without exposing
sensitive execution content or claiming success.

---

### Task 15: Reproduce both real failure shapes offline and update Task26 documentation

**Files:**
- Modify: `tests/integration/test_adaptive_convergence.py`
- Modify: `tests/integration/test_agent_failures.py`
- Modify: `DESIGN.md`
- Modify: `TASKS.md` Task26 requirements/tests only
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `README.txt`
- Modify: `docs/USAGE.md`
- Modify: `tests/test_docs.py`

**Interfaces:**
- Consumes: the real `AgentRunner`, `ReadFileTool`, `WriteFileTool`,
  `RunCommandTool`, `CommandPolicy`, and optional-command `VerificationGate`.
- Produces: deterministic regression evidence for discovery convergence,
  command correction, and the unverified terminal state; documentation that
  presents this local phase gate as an architectural highlight.

- [ ] **Step 1: Replace the advisory-only README regression with exact gate tests**

In `tests/integration/test_adaptive_convergence.py`, add `import pytest`, add
`AgentState` to the existing `coding_agent.state` import, and add these exact
helper/test shapes. All execution stays inside `tmp_path`:

```python
def _run_readme_gate_fixture(
    workspace: Path,
    profile: BudgetProfile,
    final_read_batches: int,
) -> tuple[AgentState, FakeModelClient, _FakeVerificationExecutor]:
    initial_reads = 4 if profile is BudgetProfile.STANDARD else 6
    total_sources = initial_reads + final_read_batches + 1
    _create_source_files(workspace, total_sources)
    responses: list[ModelResponse] = [
        ModelResponse(tool_calls=(_read_call(index),))
        for index in range(initial_reads + final_read_batches)
    ]
    blocked_index = initial_reads + final_read_batches
    responses.extend(
        (
            ModelResponse(
                tool_calls=(
                    _read_call(blocked_index),
                    ToolCall(
                        "create-readme",
                        "write_file",
                        {
                            "path": "README.md",
                            "content": "# Example project\n\nA bounded fixture.\n",
                        },
                    ),
                )
            ),
            ModelResponse(text="README.md was created and verified."),
        )
    )
    model = FakeModelClient(tuple(responses))
    gate, executor = _verification_gate(workspace)
    runner = AgentRunner(
        model_client=model,
        tool_registry=ToolRegistry((ReadFileTool(), WriteFileTool())),
        execution_context=ExecutionContext(workspace),
        termination_policy=_profile_policy(profile),
        verification_gate=gate,
        budget_profile=profile,
    )
    return runner.run("create README.md"), model, executor


@pytest.mark.parametrize(
    ("profile", "final_read_batches"),
    [
        (BudgetProfile.STANDARD, 1),
        (BudgetProfile.DEEP, 2),
    ],
)
def test_readme_discovery_gate_blocks_extra_read_then_allows_write(
    tmp_path: Path,
    profile: BudgetProfile,
    final_read_batches: int,
) -> None:
    state, model, executor = _run_readme_gate_fixture(
        tmp_path,
        profile,
        final_read_batches,
    )

    blocked = [
        item
        for item in state.messages
        if isinstance(item, ToolResult)
        and item.error is not None
        and item.error.startswith("agent_rejected:decision_required")
    ]
    assert len(blocked) == 1
    assert state.status is AgentStatus.SUCCESS
    assert state.mutation_index == 1
    assert state.validation_index == 1
    assert (tmp_path / "README.md").is_file()
    assert state.main_model_call_count == len(model.requests)
    assert len(executor.calls) == 1
```

Update the existing `test_post_checkpoint_exploration_stops_as_no_progress_not_main_limit`
response tuple so it includes exactly the profile's initial threshold, final
read allowance, and one blocked read response. Assert the blocked result's
`agent_rejected:decision_required` prefix and exact model request count; do not
change its `NO_PROGRESS` and below-hard-budget assertions.

- [ ] **Step 2: Run the exact README gate RED and GREEN sequence**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/integration/test_adaptive_convergence.py -k "readme_discovery_gate or post_checkpoint"
```

Expected RED before Task11/13 behavior because the extra read executes. After
the production tasks are green, use the response construction above; expected
GREEN.

- [ ] **Step 3: Add the real Python verification recovery integration**

Register real `WriteFileTool`, `RunCommandTool`, and an optional-command
`VerificationGate(required_command=None, execution_context=...)`. Script:

```python
def test_python_write_recovers_from_rejected_commands_and_verifies(
    tmp_path: Path,
) -> None:
    model = FakeModelClient(
        (
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "write",
                        "write_file",
                        {
                            "path": "task_manager.py",
                            "content": "print('verified')\n",
                        },
                    ),
                )
            ),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "shell-syntax",
                        "run_command",
                        {
                            "command": "python task_manager.py && echo done",
                            "purpose": "verification",
                        },
                    ),
                )
            ),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "wrong-launcher",
                        "run_command",
                        {
                            "command": "python3 task_manager.py",
                            "purpose": "verification",
                        },
                    ),
                )
            ),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        "valid-command",
                        "run_command",
                        {
                            "command": "python task_manager.py",
                            "purpose": "verification",
                        },
                    ),
                )
            ),
            ModelResponse(text="task_manager.py was created and verified."),
        )
    )
    context = ExecutionContext(tmp_path)
    runner = AgentRunner(
        model_client=model,
        tool_registry=ToolRegistry((WriteFileTool(), RunCommandTool())),
        execution_context=context,
        verification_gate=VerificationGate(
            required_command=None,
            execution_context=context,
        ),
        termination_policy=_profile_policy(BudgetProfile.STANDARD),
        budget_profile=BudgetProfile.STANDARD,
    )

    state = runner.run("write any Python file and verify it")

    assert state.status is AgentStatus.SUCCESS
    assert state.mutation_index == state.validation_index == 1
    assert state.verification_attempt_count == 1
    assert state.verification_status is VerificationStatus.PASSED
    assert state.consecutive_safety_rejections == 0
    assert len(model.requests) == 5
```

This test executes only the generated trivial script, inherits the existing
credential-scrubbed environment, and performs no network operation.

- [ ] **Step 4: Run Python recovery RED and GREEN**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/integration/test_adaptive_convergence.py -k "python_write_recovers"
```

Expected RED before the amendment because generic rejection feedback leads the
scripted sequence to the old terminal behavior or lacks the new gate contract.
Expected GREEN afterward with one real verification execution and exact fresh
evidence.

- [ ] **Step 5: Add the exhausted-recovery integration**

Add this exact response sequence with three distinct invalid verification
commands and no legal fourth command:

```python
def test_python_write_with_exhausted_command_recovery_keeps_unverified_change(
    tmp_path: Path,
) -> None:
    invalid_commands = (
        "python task_manager.py && echo done",
        "python3 task_manager.py",
        "py task_manager.py",
    )
    responses: list[ModelResponse] = [
        ModelResponse(
            tool_calls=(
                ToolCall(
                    "write",
                    "write_file",
                    {
                        "path": "task_manager.py",
                        "content": "print('not yet verified')\n",
                    },
                ),
            )
        )
    ]
    responses.extend(
        ModelResponse(
            tool_calls=(
                ToolCall(
                    f"invalid-{index}",
                    "run_command",
                    {"command": command, "purpose": "verification"},
                ),
            )
        )
        for index, command in enumerate(invalid_commands, start=1)
    )
    model = FakeModelClient(tuple(responses))
    context = ExecutionContext(tmp_path)
    runner = AgentRunner(
        model_client=model,
        tool_registry=ToolRegistry((WriteFileTool(), RunCommandTool())),
        execution_context=context,
        verification_gate=VerificationGate(
            required_command=None,
            execution_context=context,
        ),
        termination_policy=_profile_policy(BudgetProfile.STANDARD),
        budget_profile=BudgetProfile.STANDARD,
    )

    state = runner.run("write any Python file and verify it")

    assert (tmp_path / "task_manager.py").is_file()
```

Add `RunCommandTool` to this test file's imports. Continue the assertions in
the same test:

```python
assert state.status is AgentStatus.FAILED
assert state.termination_reason is TerminationReason.CHANGES_UNVERIFIED
assert state.modified_paths == ("task_manager.py",)
assert state.mutation_index == 1
assert state.validation_index is None
assert state.verification_attempt_count == 0
assert state.verification_status is VerificationStatus.STALE
assert len(model.requests) == 4
```

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/integration/test_adaptive_convergence.py -k "exhausted_recovery"
```

Expected RED before terminal mapping and GREEN afterward. The created file
must remain present; the test must not describe failure as rollback.

- [ ] **Step 6: Update the stale-evidence failure regression**

Before documentation work, update
`tests/integration/test_agent_failures.py::test_new_mutation_invalidates_previous_model_verification`
to script only its first three existing responses and assert:

```python
assert code == report["exit_code"] == 1
assert report["status"] == "failed"
assert report["termination_reason"] == "changes_unverified"
assert report["main_model_calls"] == 3
assert report["mutation_index"] == 1
assert report["validation_index"] == 0
assert report["verification_attempts"] == 1
assert report["verification"]["status"] == "stale"
assert stderr.getvalue() == ""
```

This replaces the old expectation that 22 additional completion claims consume
the main-call budget. Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/integration/test_agent_failures.py -k "new_mutation_invalidates"
```

Expected: RED before Task13 terminal classification and GREEN after the exact
assertion update.

- [ ] **Step 7: Write documentation-contract RED tests**

Add exact assertions to `tests/test_docs.py`:

```python
def test_docs_explain_deterministic_decision_and_verification_recovery() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "DESIGN.md",
            ROOT / "TASKS.md",
            ROOT / "README.md",
            ROOT / "docs" / "USAGE.md",
        )
    )

    for phrase in (
        "Standard 1 / Deep 2",
        "decision_required",
        "changes_unverified",
        "拒绝但不自动改写",
        "修改待验证",
    ):
        assert phrase in combined


def test_docs_do_not_claim_unverified_changes_are_success() -> None:
    usage = (ROOT / "docs" / "USAGE.md").read_text(encoding="utf-8")

    assert "changes_unverified" in usage
    assert "退出码 1" in usage
    assert "文件不会自动回滚" in usage
    assert "SUCCESS" in usage
```

Use the existing `ROOT` constant and README.txt length helper rather than
duplicating them.

- [ ] **Step 8: Run docs RED, update the approved documents, and run GREEN**

Run RED:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_docs.py -k "decision_and_verification or unverified_changes"
```

Expected: missing approved terms.

Update:

- `DESIGN.md` sections 6, 15, 17, 20, and 22 with the exact state flow,
  derived freshness property, non-rewriting command recovery, and limitation.
- `TASKS.md` Task26 goal, modules, acceptance criteria, and tests with this
  amendment; keep status `进行中`.
- `AGENTS.md` with the final-read allowance, exact safe command forms, and the
  rule that unverified mutation never succeeds.
- `README.md` with one concise architecture-highlight paragraph.
- `README.txt` within its existing length contract.
- `docs/USAGE.md` with troubleshooting for `decision_required`,
  `changes_unverified`, legal verification commands, exit code `1`, and the
  explicit fact that files are not rolled back.

Re-run the same test; expected GREEN. Do not claim live-provider proof or
include the real workspace, audit IDs, command bodies, or credentials.

- [ ] **Step 9: Run amendment-focused and complete verification**

Run every command fresh:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_progress.py
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_loop.py
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_instructions.py tests/test_command_safety.py tests/tools/test_shell_tool.py tests/test_verification.py
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_logging.py tests/test_report.py tests/test_session.py tests/test_session_events.py tests/test_session_controller.py tests/test_web_api.py tests/test_web_sse.py tests/test_web_gui.py
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/integration/test_adaptive_convergence.py tests/integration/test_agent_failures.py
node --test tests/js/web_gui.test.mjs
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Expected: every command exits `0`. Record actual pass, fail, skip, warning, and
Node counts; never reuse the earlier Task26 total as new evidence.

- [ ] **Step 10: Run Windows, dependency, privacy, and scope audits**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_path_safety.py -k "reparse or junction or symlink"
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/tools/test_shell_tool.py -k "timeout or process_tree or output_limit"
& .\.venv\Scripts\python.exe -m pip check
git diff --check
git status --short --untracked-files=all
git diff --stat
```

Run source scans and inspect every match:

```powershell
rg -n "OPENAI_API_KEY\s*=|CHAT_COMPLETIONS_API_KEY\s*=|Authorization:\s*Bearer|sk-[A-Za-z0-9]" . --glob "!*.pyc" --glob "!.git/**" --glob "!.coding-agent/**"
rg -n "C:\\Users\\|D:\\code\\|/home/|encrypted_reasoning|continuation_items" README.md README.txt docs src tests --glob "!*.pyc"
rg -n "TODO|TBD|FIXME|pytest\.skip|pytest\.xfail|@pytest\.mark\.skip|@pytest\.mark\.xfail" src tests README.md README.txt docs TASKS.md DESIGN.md AGENTS.md
rg -n "LangChain|LlamaIndex|Agents SDK|AutoGen|CrewAI|subprocess.*shell=True|os\.system" src pyproject.toml
git diff -- src/coding_agent/safety.py src/coding_agent/messages.py src/coding_agent/verification.py src/coding_agent/openai_client.py src/coding_agent/chat_completions_client.py src/coding_agent/tools/base.py src/coding_agent/tools/registry.py src/coding_agent/tools/filesystem.py src/coding_agent/tools/java.py pyproject.toml
```

Expected: tests and `pip check` exit `0`; scans reveal no real credential,
personal absolute path in output contracts, placeholder, suppressed test,
Agent framework, shell escape, provider change, dependency change, safety-policy
change, or verification-rule change. Source references to environment-variable
names and deliberate negative-test strings are inspected rather than reported
as secrets.

- [ ] **Step 11: Review complete diff and stop for user approval**

Run:

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff -- AGENTS.md DESIGN.md TASKS.md README.md README.txt docs/USAGE.md docs/superpowers/plans/Task26.md src/coding_agent tests
```

Expected: only the original Task26 scope plus the explicitly amended
`instructions.py` and `tools/shell.py` contract text appear; Task26 remains
`进行中`; nothing is staged.

Do not stage or commit. Report every amendment RED/GREEN command and actual
result, the complete suite and Windows counts, the two reproduced failure
shapes, safe command correction evidence, the dedicated GUI result, audits,
changed files, deviations, and unresolved items. Wait for user review.

**Acceptance:** both observed failures have deterministic offline regressions;
the Agent either converges to action/verification or returns an accurate
bounded non-success; the GUI distinguishes preserved unverified work; all
legacy behavior and safety boundaries remain green.

---

## Final Acceptance Matrix

| Requirement | Primary evidence |
|---|---|
| Exact `standard` and `deep` profiles | `tests/test_budget.py`, config/CLI tests |
| Per-run immutable profile | Session domain/controller/store lifecycle tests |
| Main and summary logical calls independent | layered `tests/test_model.py` and Agent split-count tests |
| Shared global provider hard cap | model equality/subcap tests and both provider regressions |
| Summary provider subcap degrades locally | context summary-budget latch tests |
| No off-by-one or counter overflow | model/termination equality tests |
| Final forced verification tool reserve | Agent and termination reserve tests |
| 48k/20 trigger and 33k/12 target | context equality and low-water tests |
| Complete tool pairs preserved | context `ModelRequest` reconstruction tests |
| Last completed turn may be summarized | oversized complete-turn test |
| Continuation unchanged without compression | existing and updated context identity tests |
| Continuation cleared after compression | context and Agent continuation tests |
| One failed model summary latches current run | context latch tests and integration scenario |
| New run retries semantic summary | context new-run test |
| Fatal/global/BaseException paths propagate | parameterized context tests |
| Host absolute path excluded from summary | fallback privacy test and final scan |
| Weak and strong progress differ | `tests/test_progress.py` |
| Distinct reads eventually checkpoint | progress thresholds and integration README fixture |
| Exact repeats remain fast-stopped | progress and legacy termination fingerprint tests |
| Checkpoint can recover into mutation | Agent and integration tests |
| Continued exploration becomes `no_progress` | progress, Agent, and integration tests |
| Remaining four calls trigger final decision | progress equality test |
| Standard/Deep ordinary checkpoint final reads are exactly 1/2 attempted batches | progress equality tests and README integration fixture |
| Duplicate-only response closes reads immediately | exploration-ledger and Agent integration tests |
| First failed decision receives exactly one corrective response | decision-handshake boundary tests |
| Reads after allowance are paired but not executed | Agent decision-required tests and audit event assertions |
| Multi-file mutation batch is not split by the new gate | mixed blocked-read/allowed-write Agent test |
| Unverified state is derived without reusing forced verify | `has_unverified_changes` state tests |
| Exact command grammar is visible to the model | instructions and `RunCommandTool` schema tests |
| Rejected commands are never rewritten or auto-executed | Task8 regressions and real recovery integrations |
| Initial safety rejection has two bounded correction opportunities | three-rejection Agent and integration tests |
| Legal correction can produce fresh optional verification | real Python recovery integration |
| Exhausted recovery preserves files but cannot succeed | `changes_unverified` integration and report assertions |
| Unverified completion is not strong progress | Agent completion-strength test |
| Failed verification opens bounded repair reads | Agent verification-failure checkpoint tests |
| Dedicated unverified GUI survives reload | Session projection and Node GUI test |
| Namespaced audit errors stay safe at Session/SSE boundary | exact SessionController code-projection tests |
| Stage transitions use local facts | Agent phase tests |
| `RunMode` authority remains immutable | read-only/modify regressions and Registry tests |
| `FINISH` cannot bypass verification | Agent/verification/report invariant tests |
| Summary success cannot reset main error streak | Agent counter-reset test |
| Multi-tool termination keeps call/result pairs | Agent reserve/termination batch test |
| Events and report expose safe split facts | logging/report schema v3 tests |
| SQLite v3→v4 migration is atomic | session store migration tests |
| Historical profile maps to standard | migration test |
| REST rejects invalid profile before controller | Web API parameterized test |
| SSE remains ordered and payload-safe | Session event/SSE tests |
| GUI has compact profile control and one status surface | Python GUI contracts and Node tests |
| No SDK leakage/new dependency/network/key use | final audits and complete offline suite |
| Task1–Task25 remain compatible | explicit regressions and full suite |

## Plan Self-Review

- Every approved design section maps to a named task and acceptance-matrix row.
- Public names used by later tasks are defined in earlier `Interfaces` blocks.
- Main/summary/provider/tool counters have exact equality semantics and explicit totals.
- Summary fallback distinguishes sub-budget degradation from global hard-budget termination.
- The continuation lifecycle is covered for compression, no compression, model summary, and fallback summary.
- Strong-progress and novelty counters do not advance for model errors,
  rejected/error tools, synthetic paired results, or compression. The separate
  response-level final-read allowance does advance when a model response
  attempts reads, including attempts that are rejected or fail, so an error
  cannot create unlimited exploration allowance.
- Ordinary checkpoint final-read allowance counts model responses that attempt
  reads, not only successful or novel results and not individual files;
  equality is tested for both profiles. Duplicate-only turns close reads
  immediately and the decision handshake has an exact one-response correction.
- `required_verification_pending` remains forced-user-verify state, while
  `has_unverified_changes` is derived from mutation and fresh evidence.
- Completion text is marked strong only after `ANSWERED` or verified `SUCCESS`;
  unverified text cannot reset convergence.
- Agent-stage rejections and Task8 security rejections remain distinct; neither
  executes, rewrites, or logs the rejected command.
- Namespaced JSONL rejection codes are projected through an exact allowlist to
  grammar-safe Session/SSE suffixes; the existing persistence validator is not
  weakened and arbitrary namespaces cannot enter the GUI.
- The dedicated GUI terminal is a derived presentation of an existing failed
  run and requires no database or report schema migration.
- RunMode, verification, safety, streaming, Skill, follow-up, and single-active-run boundaries remain intact.
- No task introduces Planner/Executor, multi-Agent behavior, MCP, tokenizer, dependency, live API, remote operation, or unlimited execution.
- The plan contains concrete files, signatures, tests, commands, expected RED/GREEN causes, regressions, and a final review stop.

# Task 13 CLI Composition and Offline Repair Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`, `superpowers:test-driven-development`, `superpowers:systematic-debugging` for reproducible unexpected failures, and `superpowers:verification-before-completion` before reporting results. Execute directly in the current workspace only after user approval. Do not create a branch, worktree, subagent, commit, or remote operation.

**Goal:** Assemble the accepted Task 1–12 components into the real one-shot CLI and prove the complete read–modify–failed verification–repair–passing verification flow with a deterministic offline demo.

**Architecture:** `cli.py` remains a thin parser/configuration boundary and lazily delegates only validated `RunConfig` values. A new `app.py` is the composition root: it creates one execution context and command executor, registers the five accepted tools in a fixed order, creates the model/context/termination/verification/logger components, runs `AgentRunner`, closes the logger before printing, builds exactly one `FinalReport`, and returns that report's exit code. Tests inject only factories and streams at this boundary; production still constructs `OpenAIResponsesClient`.

**Tech Stack:** Python 3.11+, standard library, official `openai` package, pytest, Windows-first subprocess behavior.

**Spec:** `DESIGN.md` sections 1–17 and `TASKS.md` Task 13, with the accepted Task 8–12 plans and implementations as binding interfaces.

## Global constraints

- Use no Agent framework, hosted file tool, hosted execution tool, server conversation, or `previous_response_id`.
- Keep OpenAI SDK imports confined to `openai_client.py`; `app.py`, `cli.py`, Agent, messages, tools, context, verification, logging, and report code remain SDK-type-free.
- Default and CI tests are offline and use conspicuous fake credentials only.
- Do not change Task 8 safety rules, Task 10 budgets, Task 11 success/freshness rules, or Task 12 event/report schemas.
- Do not add dependencies or modify `pyproject.toml`.
- The existing console entry `coding-agent = coding_agent.cli:entrypoint` remains the production entry. Task 13 does not add a second `python -m coding_agent` entry.
- Task 13 execution changes Task 12 from `进行中` to `已完成` and Task 13 from `未开始` to `进行中`; Task 13 stays `进行中` at the review stop.
- README, video, ZIP, publishing, dependency locking, and final submission checks remain Task 14.

## Planning baseline

- Repository: `D:\code\coding_agent`; branch: `main`.
- HEAD: `1954776b550c8178f3152ff73a4bfaef525ccfaf` (`完成会话和工具调用日志`).
- Worktree was clean before this plan; `git diff --check` exited 0. Git emitted only a user-level ignore permission warning.
- Sandboxed full suite: `687 passed, 2 failed`; both failures were the accepted Task 7 Windows process-tree tests because `taskkill.exe` returned `process-tree cleanup failed` under the restricted account.
- Fresh host-permission rerun of the same offline suite: `689 passed in 16.53s`, exit 0.
- `TASKS.md` still says Task 12 is `进行中` although Task 12 is at HEAD and the user states it is accepted. This is status drift, not an implementation/design conflict; approved Task 13 execution corrects it in Task 0 only.

## Brainstorming decision

Three composition approaches were compared:

1. **Recommended — thin `cli.py` plus focused `app.py`.** Keeps argparse/config failure before heavy imports, gives one test seam for factories and streams, and makes ownership/cleanup visible without changing accepted business modules.
2. **All wiring in `cli.py`.** Has one fewer file but mixes argparse, object ownership, interruption, logger cleanup, report rendering, and test injection. It would make startup-order and double-output errors harder to audit.
3. **Generic dependency container or Builder graph.** Maximizes substitution but adds abstractions the first version does not need and obscures the interview explanation.

Approach 1 is locked. Dependency injection exists only in `app.py`; it does not spread into Agent, tools, messages, or provider code.

## Locked file map

### Create

- `src/coding_agent/app.py` — production factories, fixed composition order, logger ownership, interruption/close adjudication, final report rendering, and process exit mapping.
- `tests/test_app.py` — component construction, registration order, shared objects, startup failures, output, exits, cleanup, production/fake model boundaries, and secret safety.
- `tests/integration/test_agent_repair.py` — deterministic complete repair flow over a copied demo fixture.
- `tests/integration/test_agent_failures.py` — verification exhaustion, safety rejection, repetition, budget, context compression, logger failure, and repeatability integration paths.
- `examples/broken_pytest_project/calculator.py` — tracked two-defect source.
- `examples/broken_pytest_project/tests/test_calculator.py` — tracked immutable failing tests.

### Modify

- `src/coding_agent/cli.py` — retain argument definitions and config loading; add stream/application injection and lazy delegation after successful configuration.
- `tests/test_cli.py` — replace Task 1 success placeholder assertions with delegation, startup ordering, console-entry failure, stream, and secret assertions while retaining all config tests.
- `TASKS.md` — during approved execution Task 0 only, update Task 12 and Task 13 statuses as described above.

### Read and keep unchanged

- `src/coding_agent/config.py`, `messages.py`, `model.py`, `openai_client.py`, `state.py`, `agent.py`, `context.py`, `termination.py`, `verification.py`, `logging.py`, `report.py`, and `safety.py`.
- Every file under `src/coding_agent/tools/`.
- Existing tests other than `tests/test_cli.py`.
- `pyproject.toml`, `AGENTS.md`, `DESIGN.md`, and Task 1–12 plan files.

If implementation requires changing a read-only file, stop and return to brainstorming. In particular, do not add injectable guards to accepted tools merely to assert object identity.

## Locked public interfaces

`src/coding_agent/app.py` adds:

```python
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, TextIO

Clock = Callable[[], float]


class Application(Protocol):
    def __call__(
        self,
        config: RunConfig,
        *,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class ApplicationFactories:
    model_client: Callable[[RunConfig], ModelClient] = field(repr=False)
    logger: Callable[[RunConfig, Clock], RunEventLogger] = field(repr=False)
    command_executor: Callable[[], AuthorizedCommandExecutor] = field(repr=False)
    clock: Clock = field(repr=False)


def production_factories() -> ApplicationFactories: ...


def run_application(
    config: RunConfig,
    *,
    stdout: TextIO,
    stderr: TextIO,
    factories: ApplicationFactories | None = None,
) -> int: ...
```

`src/coding_agent/cli.py` keeps the accepted positional/option names and adds only keyword-only seams:

```python
def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    application: Application | None = None,
) -> int: ...
```

`entrypoint() -> NoReturn` remains unchanged and raises `SystemExit(main())`. `build_parser()` keeps `task`, required `--workspace`, optional `--verify`, and optional `--model`; there are no Task 13 flags.

`ApplicationFactories` has exactly four seams. There is no runner factory, registry factory, safety bypass, verification bypass, arbitrary service locator, or network switch. Tests use a fake model factory and deterministic logger factory while exercising the real config, safety, tools, Agent, gate, event logger, and report.

## Locked construction and ownership order

`cli.main` performs this exact order:

1. Resolve `stdout`/`stderr` to the supplied streams or current `sys.stdout`/`sys.stderr`.
2. Parse arguments with existing argparse behavior. Parse errors raise `SystemExit(2)` and do not import `coding_agent.app`.
3. Call `load_run_config`. That call trims the task, constructs `PathGuard`, canonicalizes the workspace, selects model/API key, authorizes `--verify` through `CommandPolicy`, checks credibility, and returns the exact `AuthorizedCommand` object.
4. On `ConfigError`, write one `error: <stable public message>` line to stderr and return 2. Do not import the application module.
5. Lazily import `run_application` only when no injected application is supplied, then call it once with the accepted `RunConfig` and streams.

`run_application` performs this exact order:

1. Validate `RunConfig`, factories, and writable stream interfaces without rendering their values.
2. Create one `ExecutionContext(config.workspace)`.
3. Create one `AuthorizedCommandExecutor` from the factory.
4. Construct and register tools in this order: `ListDirectoryTool`, `ReadFileTool`, `ReplaceTextTool`, `WriteFileTool`, `RunCommandTool(authorized_executor=executor)`.
5. Construct `OpenAIResponsesClient(model=config.model, api_key=config.api_key)` through the model factory. Production factory does not call the network during construction.
6. Construct `ContextManager(model_client=model_client)` and `TerminationPolicy()`.
7. Construct `VerificationGate(required_command=config.verify_command, execution_context=execution_context, executor=executor)`. This receives the exact `AuthorizedCommand` returned by config and the same executor used by `RunCommandTool`.
8. Create `RunEventLogger` through the logger factory with `config.workspace`, the same monotonic clock used by Agent, and `sensitive_values=(config.api_key,)`.
9. Construct `AgentRunner` with the same model client, registry, execution context, context manager, termination policy, verification gate, event sink, and clock.
10. Call `runner.run(config.task)` exactly once.
11. Convert `AgentInterrupted` to its carried terminal state; do not catch `SystemExit`.
12. Close the logger exactly once before building or printing the report.
13. Build `FinalReport.from_state(state, logger.metadata, sensitive_values=(config.api_key,))`.
14. Write `report.to_json()` exactly once to stdout and return `report.exit_code`.

Accepted file tools construct fresh `PathGuard` instances per call, and `RunCommandTool` constructs a fresh `CommandPolicy` per model command. Task 13 does not change those accepted interfaces. They all receive the same canonical workspace through the single `ExecutionContext`. Config authorization and model command authorization therefore share the same `CommandPolicy` implementation and rules, not one mutable policy object. The command executor and required `AuthorizedCommand` capability are shared by identity where the accepted interfaces support it.

## Locked logger lifecycle and exceptional exits

- Logger creation happens before `AgentRunner` construction/run. A `RunLogError` here prints `error: audit log unavailable (<code>)` to stderr, returns 1, produces no `FinalReport`, and calls neither model nor executor.
- Ordinary Agent return closes the logger before report creation/output.
- If close succeeds, the report and process exit code must be identical.
- If close fails after an ordinary state, set that state to `FAILED`, `termination_reason=AUDIT_LOG_FAILURE`, and `failure_reason="audit_log_failure"`; preserve real counters/evidence and render one nonzero report with `metadata.log_failure_code="log_close_failed"`.
- If close fails while handling `AgentInterrupted`, user interruption remains primary as locked by Task 12: render one interrupted report with exit 130 and the close failure code. It must never return 0.
- Unexpected `Exception` before a terminal state is available closes any created logger best-effort, prints only `error: internal application failure` to stderr, and returns 1 without exception text or a fabricated report.
- `KeyboardInterrupt` before `AgentRunner` owns a state prints only `error: interrupted` to stderr and returns 130. Inside the Agent it is represented by `AgentInterrupted` and gets a report.
- `SystemExit` is not caught. Argparse retains exit 2 semantics.
- stdout is empty for startup/configuration failures. For every reportable Agent terminal path, stdout contains exactly one JSON report and stderr is empty.

## Locked exit mapping

| Path | Exit | FinalReport |
| --- | ---: | --- |
| argparse/config/workspace/API key/model/unsafe `--verify` | 2 | none |
| logger path/open failure before Agent | 1 | none |
| `SUCCESS` with fresh passing verification | 0 | one on stdout |
| ordinary Agent failure, safety/repetition/model/tool/time/provider budget, verification never passes | 1 | one on stdout |
| audit emit/flush/close failure after state exists | 1 | one failed report on stdout |
| user interruption with Agent state | 130 | one interrupted report on stdout |
| interruption before Agent state | 130 | none; one stable stderr line |
| internal composition/report invariant failure | 1 | none; one stable stderr line |

There is no separate verification-failed process code in the approved design; it is exit 1 with verification evidence and a termination reason. A completion candidate, stale evidence, missing evidence, nonzero verification, timed-out verification, or audit failure can never return 0.

## Locked demo fixture

`examples/broken_pytest_project/calculator.py` starts as:

```python
def add(left: int, right: int) -> int:
    return left - right


def is_even(value: int) -> bool:
    return value % 2 == 1
```

`examples/broken_pytest_project/tests/test_calculator.py` is:

```python
from calculator import add, is_even


def test_adds_positive_numbers() -> None:
    assert add(2, 3) == 5


def test_detects_even_and_odd_numbers() -> None:
    assert is_even(4) is True
    assert is_even(3) is False
```

Every integration test copies this tracked directory with `shutil.copytree` into a fresh `tmp_path / "demo"`. Tests never run the Agent in the tracked example and never delete/reset user files. Task 8 does not define test files as a protected class, so Task 13 does not claim they are unmodifiable. Instead, the scripted model only modifies `calculator.py`, the test captures the test file's original bytes, and assertions prove those bytes are unchanged and `state.modified_paths == ("calculator.py",)`.

The user verification input is exactly `pytest -q`; `load_run_config` produces the capability before model startup. The fake model never emits the required verification command. First source replacement fixes `add` only, so forced verification fails on `is_even`; the next request must contain structured verification feedback with the real nonzero exit and failing assertion. The second replacement fixes `is_even`; the next forced verification passes at mutation index 2.

## Locked offline fake-model script

The success integration uses one `FakeModelClient` with these ordered responses:

1. `ToolCall("call-list", "list_directory", {"path": ".", "recursive": True, "max_depth": 3, "max_entries": 50})`.
2. Two ordered calls: read `tests/test_calculator.py`, then read `calculator.py`, both from line 1 to null end.
3. Replace `return left - right` with `return left + right`, expected count 1.
4. Text-only completion candidate `"The implementation is fixed."`; required verification executes and fails.
5. Replace `return value % 2 == 1` with `return value % 2 == 0`, expected count 1. The captured request must include the first verification feedback.
6. Text-only completion candidate `"The implementation is fixed and verified."`; required verification executes and passes.

Assertions lock: six logical calls, six provider attempts, five model tool calls plus two required verification executions, two mutations, two verification attempts, final validation index 2, `SUCCESS`, report exit 0, exact changed path, ordered JSONL beginning `run_started` and ending `run_completed`, and no secret/task/message/tool-output/continuation content in JSONL.

## Task 0: Reconfirm baseline and activate Task 13

**Files:** Read all locked design/source/test files; modify only `TASKS.md` status values.

- [ ] Run repository, branch, HEAD, status, and whitespace checks.

```powershell
git rev-parse --show-toplevel
git branch --show-current
git log -3 --oneline
git status --short --untracked-files=all
git diff --check
```

Expected: root `D:/code/coding_agent`, branch `main`, Task 12 commit at HEAD, no unauthorized changes, and zero whitespace errors. A user-level ignore permission warning is informational.

- [ ] Run the fresh Task 1–12 baseline.

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-baseline
```

Expected: exit 0. If restricted Windows process-tree cleanup alone fails, use systematic debugging, preserve the output, and request/perform the same authorized host-permission rerun; do not alter or skip those tests.

- [ ] Change only Task 12 `进行中` → `已完成` and Task 13 `未开始` → `进行中`; run a script/assertion that exactly one task is `进行中`.

Acceptance: accepted baseline is current and only Task 13 is active.

## Task 1: Thin CLI delegation after all startup validation

**Files:** Modify `src/coding_agent/cli.py`, `tests/test_cli.py`.

**Interfaces:** Produce the locked `Application` Protocol usage and additive `main` signature. Consume unchanged `load_run_config` and `RunConfig`.

- [ ] Add failing tests that inject a recording application and `StringIO` streams. The tests assert exact normalized config, one application call, no placeholder text, return-code pass-through, and no application call for missing key, bad workspace, or unsafe verify.

```python
def test_cli_delegates_one_validated_config_to_application(tmp_path: Path) -> None:
    calls: list[RunConfig] = []
    out, err = StringIO(), StringIO()
    def application(config: RunConfig, *, stdout: TextIO, stderr: TextIO) -> int:
        assert stdout is out and stderr is err
        calls.append(config)
        return 17
    code = main(
        [" repair ", "--workspace", str(tmp_path), "--verify", "pytest -q"],
        environ={"OPENAI_MODEL": "fake-model", "OPENAI_API_KEY": "fake-sentinel"},
        stdout=out,
        stderr=err,
        application=application,
    )
    assert code == 17
    assert len(calls) == 1 and calls[0].task == "repair"
    assert calls[0].verify_command is not None
    assert out.getvalue() == err.getvalue() == ""
```

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py::test_cli_delegates_one_validated_config_to_application -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-cli-red
```

Expected RED: `main()` rejects the new `stdout`, `stderr`, or `application` keyword, or still prints the Task 1 placeholder.

- [ ] Implement only stream resolution, unchanged config loading, config-error output, lazy app import, and one delegation.

- [ ] Run GREEN and all CLI/config tests.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-cli-green
```

Expected: all actual tests pass. Update the console subprocess test to exercise a startup rejection without a key and assert exit 2/no network; successful CLI execution is tested in-process through injection.

- [ ] Run Task 1–12 regression before proceeding.

Acceptance: invalid startup never imports/calls application; valid startup passes one authorized config; secrets are absent from both streams.

## Task 2: Composition graph, fixed registry, and shared capabilities

**Files:** Create `src/coding_agent/app.py`, `tests/test_app.py`.

**Interfaces:** Implement `ApplicationFactories`, `production_factories`, and `run_application` exactly as locked.

- [ ] Write a failing construction test using a recording fake model factory, logger factory, and executor factory. Use a fake model response sequence that terminates via real `VerificationGate`. Assert registry schema names are exactly:

```python
("list_directory", "read_file", "replace_text", "write_file", "run_command")
```

The test records the one executor returned by `command_executor`, inspects the `RunCommandTool` and gate construction through behavior/spies, and asserts the exact `config.verify_command` object is executed. It must not read a real environment key.

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_app.py::test_composition_uses_fixed_tools_and_shared_executor -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-app-red
```

Expected RED: `coding_agent.app` is absent.

- [ ] Implement production factories and the minimum graph through logger creation, without adding alternate business logic.

Production factories are exactly:

```python
ApplicationFactories(
    model_client=lambda config: OpenAIResponsesClient(
        model=config.model,
        api_key=config.api_key,
    ),
    logger=lambda config, clock: RunEventLogger.create(
        config.workspace,
        sensitive_values=(config.api_key,),
        monotonic_clock=clock,
    ),
    command_executor=AuthorizedCommandExecutor,
    clock=time.monotonic,
)
```

- [ ] Run GREEN, then `tests/test_cli.py tests/test_path_safety.py tests/test_command_safety.py tests/tools` regression.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_app.py::test_composition_uses_fixed_tools_and_shared_executor -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-app-green
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/test_path_safety.py tests/test_command_safety.py tests/tools -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-app-regression
```

Expected: both commands exit 0; report actual counts rather than the plan's estimate.

Acceptance: one workspace/context/executor, fixed tool order, exact required capability, real Task 8 dispatch, and production factory type are proven without a provider request.

## Task 3: Terminal lifecycle, report output, logger close, and exit mapping

**Files:** Modify `src/coding_agent/app.py`, `tests/test_app.py`.

- [ ] Add failing tests for success, ordinary failure, logger-create failure, logger-close failure after success, interrupted Agent state, and unexpected internal failure. Use `StringIO`; assert report/exit equality, stdout cardinality, stderr cardinality, `close_calls == 1`, and no secret/provider body in output.

Representative assertions:

```python
payload = json.loads(stdout.getvalue())
assert code == payload["exit_code"] == 0
assert payload["status"] == "success"
assert stderr.getvalue() == ""
assert stdout.getvalue().endswith("\n")
assert stdout.getvalue().count('"schema_version"') == 1
```

```python
assert code == 1
assert json.loads(stdout.getvalue())["termination_reason"] == "audit_log_failure"
assert "fake-sentinel" not in stdout.getvalue() + stderr.getvalue()
```

Run each new test alone first; expected RED is missing lifecycle/report behavior, never a test syntax/import-fixture error.

Use these exact node names and RED commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_app.py::test_success_closes_then_prints_one_matching_report -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-success-red
.\.venv\Scripts\python.exe -m pytest tests/test_app.py::test_logger_create_failure_stops_before_agent -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-log-create-red
.\.venv\Scripts\python.exe -m pytest tests/test_app.py::test_close_failure_downgrades_success_before_output -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-log-close-red
.\.venv\Scripts\python.exe -m pytest tests/test_app.py::test_agent_interrupt_closes_and_reports_130 -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-interrupt-red
.\.venv\Scripts\python.exe -m pytest tests/test_app.py::test_internal_failure_is_stable_and_redacted -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-internal-red
```

- [ ] Implement the locked try/run/close/report flow. Do not print before `close()` succeeds or is adjudicated. Do not catch `BaseException`; catch `AgentInterrupted`, `KeyboardInterrupt`, `RunLogError`, `ReportInvariantError`, and ordinary `Exception` only in the locked scopes.

- [ ] Run GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_app.py -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-lifecycle-green
```

- [ ] Run `tests/test_logging.py tests/test_report.py tests/test_agent_loop.py tests/test_verification.py` regression.

Acceptance: no double report, no success before close, no zero on stale/audit failure, interrupted exit 130, and all diagnostics are stable and redacted.

## Task 4: Build the immutable two-defect demo and successful repair integration

**Files:** Create the two example files and `tests/integration/test_agent_repair.py`.

- [ ] Add the locked example source/test files and first prove the copied fixture fails exactly two tests before Agent execution.

```powershell
.\.venv\Scripts\python.exe -m pytest examples/broken_pytest_project -q -p no:cacheprovider
```

Expected RED by fixture design: exit 1 with exactly two failed tests. This command is evidence that the committed example is genuinely broken; it is not a production-code RED.

- [ ] Write `test_cli_repairs_demo_after_failed_forced_verification` using `copytree`, `load_run_config(... verify_command="pytest -q")`, the six-response fake model script, a fixed run-ID logger factory, and real `run_application`.

The test must assert:

```python
assert code == 0
assert report["status"] == "success"
assert report["mutation_index"] == report["validation_index"] == 2
assert report["verification_attempts"] == 2
assert report["verification"]["exit_code"] == 0
assert report["changed_paths"] == ["calculator.py"]
assert copied_test.read_bytes() == original_test_bytes
assert "return left + right" in copied_source.read_text(encoding="utf-8")
assert "return value % 2 == 0" in copied_source.read_text(encoding="utf-8")
```

It also inspects `fake.requests[4]` and proves the first nonzero verification feedback and failing assertion are present, while no fake response asks to run the required command.

Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_agent_repair.py::test_cli_repairs_demo_after_failed_forced_verification -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-repair-red
```

Expected RED: missing example/application integration or an unmet exact flow assertion.

- [ ] Add only the test/factory wiring needed for GREEN; production behavior should already exist from Tasks 1–3.

- [ ] Run GREEN and re-run the copied demo's final `pytest -q` independently.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_agent_repair.py::test_cli_repairs_demo_after_failed_forced_verification -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-repair-green
```

The integration test itself invokes the authorized copied-workspace `pytest -q` twice; after it returns, invoke the final copied-workspace command only inside the test fixture helper and assert its exit code/output. Do not run against the tracked broken example as a passing check.

Acceptance: real file tools and subprocess verification perform two source mutations; failed evidence reaches the model; tests are unchanged; final proof is fresh.

## Task 5: Offline integration failure matrix and context paths

**Files:** Create `tests/integration/test_agent_failures.py`; modify no production module unless a Task 13 composition defect is exposed.

- [ ] Add one test at a time, run RED, then use the minimum test setup or in-scope app correction and run GREEN:

1. Forced verification remains nonzero until model/provider budget stops; exit/report are 1 and never `SUCCESS`.
2. A mutation after a passing model-selected verification makes evidence stale; completion cannot return 0.
3. Three identical no-progress calls terminate with `repeated_tool_call` before a fourth dispatch.
4. `.git/config` and `.coding-agent/logs/x.jsonl` writes are rejected with no file side effect; repeated safety rejection terminates.
5. Low injected `ContextLimits` at the component level exercises model summary success, clears continuation, and preserves legal call/result pairing.
6. Invalid summary exercises deterministic fallback and the run continues.
7. Logger emit failure stops before the next model/tool operation and reports `audit_log_failure`.
8. Two calls on two fresh copied fixtures create different run IDs/log paths and leave the tracked fixture unchanged.

Use these exact test names:

```text
test_forced_verification_never_passes_before_budget_stop
test_new_mutation_invalidates_previous_model_verification
test_repeated_tool_call_stops_before_fourth_dispatch
test_protected_write_rejections_have_no_side_effect
test_context_summary_clears_continuation_and_preserves_pairs
test_invalid_context_summary_uses_fallback_and_continues
test_log_emit_failure_blocks_next_operation
test_two_runs_use_independent_logs_and_fresh_fixture_copies
```

For every name, first run `python -m pytest <file>::<name> -q` and record the expected missing-behavior assertion; after the minimum implementation/test-fixture addition, run the same node and require exit 0. The common full-matrix command below is the regression gate after all eight cycles.

Use explicit fake clocks/limits for budget/time/context tests; no `sleep`, network, or real key.

Run focused matrix:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_agent_failures.py -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-failures
```

Then run Task 8–12 focused regressions.

Acceptance: every Task 13 failure requirement has a deterministic status/reason, zero forbidden side effects, and consistent report/log facts.

## Task 6: Real-entry offline checks and optional smoke boundary

**Files:** Modify `tests/test_cli.py`, `tests/test_app.py`; no README change.

- [ ] Test the installed `coding-agent.exe` with missing `OPENAI_API_KEY`; assert exit 2, empty stdout, stable stderr, and absence of key/request/network artifacts.
- [ ] In-process, monkeypatch only the production `OpenAIResponsesClient` constructor with a recording SDK-free stand-in, call `production_factories().model_client(fake_config)`, and assert the selected model/key are passed once. This checks default composition without calling `responses.create`.
- [ ] Install a socket/network tripwire in integration tests and assert zero calls while fake factories drive the complete demo.
- [ ] Audit that `app.py` imports `OpenAIResponsesClient` but imports no `openai` SDK module/type; all other non-adapter modules remain SDK-free.

The optional real smoke test is manual only:

```powershell
$env:OPENAI_API_KEY = '<set interactively; never paste into logs>'
$env:OPENAI_MODEL = '<user-selected available model>'
coding-agent "Fix the failing tests without modifying tests" --workspace .\examples\broken_pytest_project --verify "pytest -q"
```

Do not run this command during Task 13 execution without a separate user authorization. Its provider/account/network result is reported separately from automated acceptance and never changes the offline test result.

Acceptance: production selects Responses adapter; automated suites cannot reach network; no real secret is read.

## Task 7: Final verification and review stop

- [ ] Run Task 13 focused suites:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/test_app.py tests/integration -q -p no:cacheprovider --basetemp .\.venv\pytest-tmp\task13-focused
```

- [ ] Run explicit Task 1–12 regressions and then the full repository suite with a fresh base temp. Record actual pass/fail/skip/warning counts and exit codes.

- [ ] Run public-signature and construction audits with `inspect.signature`: `cli.main`, `entrypoint`, `ApplicationFactories`, `production_factories`, `run_application`, unchanged `ModelClient.complete`, `AgentRunner.run`, `VerificationGate`, `RunEventLogger.create/close`, and `FinalReport.from_state`.

- [ ] Audit fixed schema order and shared objects: registry names/order, one execution context, one executor, exact authorized verify object, one model client, one event logger, one clock.

- [ ] Audit startup ordering: invalid args/config/verify and unsafe log path result in zero model requests, executor calls, and Agent runs.

- [ ] Audit privacy/offline boundaries using source and runtime assertions: no key, Authorization header, environment dump, request/response payload, history, tool raw output, continuation, or encrypted reasoning appears in JSONL, report repr, stdout, or stderr.

- [ ] Audit dependencies and scope:

```powershell
git diff -- pyproject.toml
git diff -- src/coding_agent/messages.py src/coding_agent/model.py src/coding_agent/openai_client.py src/coding_agent/agent.py src/coding_agent/context.py src/coding_agent/termination.py src/coding_agent/verification.py src/coding_agent/logging.py src/coding_agent/report.py src/coding_agent/safety.py src/coding_agent/tools
```

Expected: empty.

- [ ] Scan for Agent frameworks, network calls outside adapter, test suppression, real-looking credentials, unfinished markers assembled from fragments, and forbidden deferred features. Any hit must be classified with file/line evidence.

- [ ] Run whitespace/status/diff review:

```powershell
git diff --check
git status --short --untracked-files=all
git diff -- src/coding_agent/app.py src/coding_agent/cli.py tests/test_app.py tests/test_cli.py tests/integration examples/broken_pytest_project TASKS.md
```

- [ ] Leave Task 13 `进行中`, do not stage/commit/push, and report every fresh command, exit code, count, warning, skip, deviation, and unverified item for user review.

## Final acceptance matrix

| Requirement | Evidence |
| --- | --- |
| Valid parse/config and first task message | CLI delegation test; repair request 1 |
| Missing key/workspace/unsafe verify before model | `tests/test_cli.py` zero-call tests |
| Unsafe logger path before Agent | logger-create failure test |
| Five tools exact order | composition registry assertion |
| Canonical workspace and shared context/executor/capability | composition identity assertions |
| Production Responses client, fake offline client | production factory spy + network tripwire |
| Read/modify/fail/feedback/repair/pass | repair integration six-response script |
| Tests unchanged and protected paths denied | byte assertion + safety integration |
| Latest mutation equals validation; success only then | report/state assertions |
| JSONL first/last/sequence and report consistency | repair log assertions |
| stdout/stderr cardinality and exit mapping | app lifecycle parameterized tests |
| Verification/budget/safety/audit/interruption exits | app and failure matrix |
| Logger flush/close once; close failure not success | close-spy tests |
| No sensitive payloads | logger/report/output scans |
| Two independent reproducible runs | fresh-copy/two-run test |
| Context compression and fallback cooperate | failure integration context tests |
| Task 1–12 unchanged | focused regressions, full suite, protected diff audit |
| Real API is opt-in only | manual command documented in this plan; never automated |

## Plan self-review result

- Coverage: every numbered Task 13 requirement maps to a task and acceptance row.
- Interfaces: all accepted Task 1–12 signatures remain unchanged; only the CLI signature grows by keyword-only composition seams and `app.py` adds new interfaces.
- Startup safety: config/verify authorization precedes lazy application import; logger creation precedes Agent execution.
- Ownership: one context, executor, capability, client, gate, logger, and clock are used where accepted interfaces permit identity sharing; file/path policy objects remain intentionally stateless per-call constructions.
- Success integrity: candidate/stale/nonzero/timeout/audit-close paths cannot return zero; report exit and process exit match whenever a report exists.
- Output: one report only after close adjudication; startup errors have no report.
- Demo: tracked fixture is immutable, copied per test, modifies source only, proves a real failed verification is fed back, and runs in under the two-minute demonstration target.
- Privacy/offline: fake factories and a network tripwire cover defaults; API key and continuation never enter logs or output.
- Scope: no README/video/ZIP/publishing, Task 14 work, dependency change, safety relaxation, budget change, or provider behavior change is planned.
- Placeholder/type scan: no undefined production type, ambiguous step, or deferred implementation marker remains.

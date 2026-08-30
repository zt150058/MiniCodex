# Run Projection, Adaptive Context, and Java Verification Design

**Date:** 2026-08-30

**Status:** Approved in conversation

**Scope:** GUI run projection correction, adaptive context compression, and a
dedicated Java black-box verification tool

## 1. Goal

This milestone resolves three connected problems observed during a real GUI run
against `D:\code\software_system`:

- intermediate model narration that accompanies tool calls is currently
  persisted and rendered as multiple assistant conversation bubbles;
- a history can exceed `max_history_items` while containing fewer than the
  preferred eight recent turns, causing context compression to terminate
  instead of adapting;
- a Java workspace cannot produce trusted fresh verification evidence because
  the existing command policy intentionally supports only the approved Python
  and read-only Git command surface.

The delivered behavior will keep transient narration in one live activity
surface, retain only the actual final answer in the durable conversation view,
compress complete turns adaptively, and add a dedicated local Java compile/run/
compare tool. The tool will be provider-neutral, workspace-contained, and
eligible to satisfy the existing verification gate without expanding the
model-facing arbitrary command surface.

After implementation and automated verification, the original README-creation
request will be repeated through the real GUI as a manual end-to-end smoke test.
The implementation itself will not directly create or edit the README in the
target Java workspace.

## 2. Baseline prerequisite

The repository currently contains approved but uncommitted Task 23 runtime and
GUI corrections. This design document does not alter or discard them. Before
the implementation plan may run, the baseline checkpoint must establish one of
these states:

1. the existing Task 23 changes have been reviewed and committed by the user;
   or
2. the user explicitly authorizes them as the exact dirty baseline for the new
   milestone.

The implementation must stop if any other modification is present. Planning and
implementation must not stage, commit, push, pull, fetch, create a branch, or
create a worktree unless a later direct user instruction grants that authority.
Task status transitions are not part of this design-writing turn.

## 3. Locked scope

### 3.1 Included

- project conversation projection by persisted `run_id`;
- one temporary activity card for active model narration;
- successful-run projection that shows only the last committed assistant text;
- failed/interrupted-run projection that hides process narration;
- adaptive removal of complete turns during context compression;
- one model summary attempt followed by deterministic local fallback when a
  larger removed range is required;
- continuation invalidation after successful compression;
- a strict `run_java_tests` tool;
- trusted system Java runtime discovery;
- recursive Java source and `.in`/`.out` fixture discovery with stable order;
- compile, per-case execution, newline normalization, and exact comparison;
- bounded input, output, diagnostics, duration, and process lifetime;
- verification-gate support for fresh Java evidence;
- offline unit and integration tests plus a real-JDK local smoke test;
- updates to the approved design, task, README, and usage documentation only
  after behavior is green.

### 3.2 Excluded

This milestone does not add:

- arbitrary Java, PowerShell, cmd, Bash, WSL, Gradle, Maven, Ant, Git, package
  manager, or network commands;
- Java dependency resolution, build-system parsing, JUnit discovery, coverage,
  sandbox virtualization, or container execution;
- a new final-success path or a bypass around `VerificationGate`;
- provider-specific types outside provider adapters;
- conversation deletion, audit-event deletion, or hidden reasoning display;
- changes to the message model, `ModelClient.complete()` signature, Agent
  framework, multi-agent execution, MCP, executable Skills, accounts, or remote
  deployment;
- a direct edit of the user's target Java workspace during implementation;
- real provider calls or real credentials in automated tests.

## 4. Evidence and root causes

The two inspected GUI runs in the target Java workspace terminated with
`context_budget_exhausted`. The latest run contained 25 history items and
55,649 serialized characters. It crossed the 24-item limit without containing
more than the preferred eight recent turns.

`ContextManager.prepare()` currently computes:

```python
removable_turn_count = len(turns) - self._limits.recent_turns
```

and terminates when the result is not positive. The preference to retain eight
turns is therefore treated as an absolute minimum even when a stricter item
budget requires removal.

`AgentRunner` currently invokes the confirmed-text handler whenever a model
response contains nonempty text, before processing its tool calls. The session
layer correctly persists every such confirmation as
`assistant_text_committed`. Consequently, provider narration such as “让我继续
读取……” becomes a durable assistant bubble even though the same response asks
the Agent to continue working.

The target workspace is a Java program with nine `.java` files and ten paired
`.in`/`.out` black-box fixtures. Launching the GUI with
`--verify "pytest -q"` cannot verify that project. The current `CommandPolicy`
correctly rejects unapproved Java commands, so Java support must not be added by
loosening `run_command`.

## 5. Chosen architecture

```text
provider stream / model response
            |
            v
       AgentRunner
       |          |
       |          +-- complete provider-neutral turns
       |                    |
       |                    v
       |              ContextManager
       |              adaptive compression
       |              continuation cleared
       |
       +-- persisted safe run events
                         |
                         v
                 GUI run projection
                 temporary activity card
                 final answer only

model tool call: run_java_tests
            |
            v
       ToolRegistry
            |
            v
     RunJavaTestsTool
       |          |
       |          +-- PathGuard for model-selected paths
       |          +-- JavaRuntimePolicy for trusted executables
       |          `-- AuthorizedCommandExecutor
       |                shell=False / fixed cwd / bounded streams /
       |                timeout / Windows process-tree cleanup
       |
       v
  structured ToolExecution
            |
            v
     VerificationGate
     fresh mutation-bound evidence
```

The GUI remains a projection rather than a second Agent state machine. Context
compression keeps its existing public API. Java execution is introduced as a
dedicated tool rather than an extension of the generic command string parser.

## 6. GUI run projection

### 6.1 Durable data remains unchanged

No Agent, message, session-event, store, REST, or SSE public type changes. The
backend continues to persist all safe `assistant_text_committed`, tool,
verification, and terminal events. Audit evidence is not deleted or rewritten.

Every projection decision uses the event's existing `run_id` and the durable
run status. Text from different runs is never coalesced.

### 6.2 Active run behavior

- streamed assistant deltas are accumulated only in the existing in-memory
  provisional buffer;
- provisional content appears in one compact activity card, not a conversation
  bubble;
- if the text becomes confirmed while the run is still active, it remains
  process narration rather than becoming a historical bubble;
- `tool_started`, `tool_finished`, `verification_started`, or
  `verification_finished` replaces the current activity-card content;
- only one activity card is visible for the active run;
- SSE reconnect and snapshot reset reconstruct the same projection without
  inventing additional messages.

### 6.3 Terminal run behavior

- for a successful run, the conversation renders only the last
  `assistant_text_committed` event belonging to that run;
- earlier committed text from the same successful run is treated as process
  narration and is hidden from the conversation;
- for a failed or interrupted run, all assistant text for that run is hidden and
  one terminal status card remains;
- user messages remain durable and visible;
- reopening a session produces the same result as watching it live.

The final answer is selected only from server-confirmed events. The browser does
not infer success from text and cannot create a final assistant message from a
provisional delta.

## 7. Adaptive context compression

### 7.1 Public interfaces remain unchanged

```python
class ContextManager:
    def prepare(
        self,
        state: AgentState,
        budget: ModelCallBudget,
    ) -> PreparedContext: ...
```

`ContextLimits`, `ContextSize`, `ContextSummary`, `PreparedContext`,
`SummarySource`, and `ContextPreparationError` retain their existing public
fields and meanings.

### 7.2 Complete-turn invariant

The existing `_partition_complete_turns()` invariant remains authoritative:

- history begins with the initial `UserMessage`;
- an existing context-summary `UserMessage` may follow it;
- each removable/retained turn begins with one `AssistantMessage`;
- every tool call is immediately followed by exactly one matching `ToolResult`;
- a turn is removed or retained as one unit;
- compression never creates an orphan tool result or a mismatched `call_id`.

### 7.3 Deterministic algorithm

1. Measure the active messages. If both limits are satisfied, return them and
   their continuation unchanged.
2. Partition the history into the initial task, optional prior summary, and
   complete assistant turns.
3. A compression candidate must retain at least the newest complete turn.
   Histories with no removable complete turn terminate with
   `context_budget_exhausted`.
4. Compute the first removed range as:

   ```python
   max(1, len(turns) - limits.recent_turns)
   ```

   This retains the preferred eight turns when possible but always permits at
   least one old turn to be summarized when a hard item/character budget
   requires it.
5. Make exactly one summary-model call for that first removed range.
6. A valid, bounded model summary is used for the first candidate. An ordinary
   nonfatal `ModelError`, empty response, tool-calling response, malformed JSON,
   invalid structure, or oversized summary uses the existing deterministic
   local fallback. `FatalModelError`, `ModelBudgetExceeded`,
   `KeyboardInterrupt`, and `SystemExit` continue to propagate.
7. If the first compressed candidate is still over either limit, increase the
   removed-turn count one complete turn at a time. Each expanded candidate uses
   `_fallback_summary()` over the complete expanded removed range. It never
   makes a second provider request.
8. Select the first candidate satisfying both budgets. This deterministically
   retains the greatest possible number of recent complete turns.
9. On success, return `continuation_items=()` atomically with the replacement
   messages. Continuation generated by the summary response is discarded.
10. If a bounded summary plus the newest complete turn still cannot fit, end
    with `context_budget_exhausted`.

When a valid model summary is later replaced by an expanded local fallback,
`summary_source` is `FALLBACK` and `summary_model_failed` remains `False`. It is
`True` only when the model call or its response failed the accepted nonfatal
summary contract.

### 7.4 Determinism and privacy

The local fallback retains the existing canonical JSON order, bounded newest
facts, deduplication, locally owned state invariants, and summary size limit.
Continuation snapshots and provider reasoning payloads are neither inserted
into the summary nor serialized, printed, or logged.

## 8. Java tool interface

### 8.1 Model-facing interface

`src/coding_agent/tools/java.py` adds:

```python
class RunJavaTestsTool:
    name = "run_java_tests"
    schema: JSONObject

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution: ...
```

The strict schema accepts exactly:

```json
{
  "source_root": "src",
  "main_class": "Main",
  "tests_directory": "tests",
  "purpose": "test"
}
```

`purpose` is either `test` or `verification`. All fields are required and extra
fields are rejected. `source_root` and `tests_directory` are workspace-relative
directories. `main_class` must match an ASCII Java qualified-name grammar whose
segments begin with a letter, `_`, or `$` and continue with letters, digits,
`_`, or `$`.

### 8.2 Test seams

The tool constructor provides additive dependency-injection seams without
changing the `Tool` protocol:

```python
class JavaCommandExecutor(Protocol):
    def execute(
        self,
        command: AuthorizedCommand,
        context: ExecutionContext,
        *,
        stdin_stream: BinaryIO | None = None,
    ) -> ToolExecution: ...

class RunJavaTestsTool:
    def __init__(
        self,
        *,
        runtime_policy_factory: JavaRuntimePolicyFactory | None = None,
        executor: JavaCommandExecutor | None = None,
        clock: Callable[[], float] = time.monotonic,
        temporary_directory_factory: JavaTemporaryDirectoryFactory | None = None,
    ) -> None: ...
```

Default production values use `JavaRuntimePolicy`,
`AuthorizedCommandExecutor`, `time.monotonic`, and a unique directory under the
workspace's `.coding-agent` internal state directory. Tests inject fakes and do
not require a provider or network.

## 9. Java discovery and comparison

### 9.1 Source discovery

- resolve `source_root` through `PathGuard.existing_directory()`;
- recursively visit entries in normalized relative-path order;
- validate every discovered path through `PathGuard`, including every ancestor,
  so nested symlinks, junctions, and reparse points cannot be traversed;
- accept only regular `.java` files;
- require at least one source;
- stop and reject when a 501st source would be accepted;
- pass source paths to `javac` in deterministic order.

### 9.2 Fixture discovery

- resolve `tests_directory` through `PathGuard.existing_directory()`;
- recursively discover regular `.in` and `.out` files in stable relative-path
  order;
- pair files by their relative path without the final suffix, using
  case-insensitive collision detection for Windows;
- reject duplicate keys, orphan inputs, orphan outputs, and an empty suite;
- permit at most 200 complete pairs;
- reject any input file larger than 262,144 raw bytes;
- reject any expected-output file larger than 65,536 raw bytes, while allowing
  one exactly at that limit;
- open the validated `.in` file as the child process's binary stdin;
- decode expected output as strict UTF-8 and reject invalid UTF-8 fixtures.

### 9.3 Build and execution

Compilation is equivalent to the following argument-array operation, never a
shell string:

```text
<trusted javac.exe> -encoding UTF-8 -proc:none -classpath <unique build directory> -d <unique build directory> <stable sources>
```

Each case is equivalent to:

```text
<trusted java.exe> -cp <unique build directory> <main_class>
```

The working directory is the canonical workspace. Standard input is the
validated `.in` file. Standard output and standard error remain separate. The
executor retains its existing incremental UTF-8 decoding with replacement for
invalid child-output bytes. The tool normalizes `CRLF` and bare `CR` to `LF` in
expected and actual output, then performs an otherwise exact comparison. It
does not trim whitespace, ignore blank lines, parse numbers, or apply tolerance.

Compilation plus all cases share one monotonic deadline:

```python
effective_timeout = min(context.command_timeout_seconds, 60.0)
```

Before every child launch, the tool computes the remaining duration and refuses
to start the first operation that no longer has positive time. Every launched
process receives only that remaining time through a fresh `ExecutionContext`.

Passing-case output is discarded after comparison. The first failure is kept;
later cases do not run. Child stdout and stderr retain the executor's existing
65,536-byte per-stream bound. The final diagnostic included in the tool JSON is
further bounded to 8,192 UTF-8 bytes and replaces the canonical workspace prefix
with `<workspace>`.

## 10. Java runtime and process safety

`src/coding_agent/safety.py` adds provider-neutral local runtime types:

```python
@dataclass(frozen=True, slots=True)
class JavaRuntime:
    javac: Path
    java: Path

class JavaRuntimePolicy:
    def __init__(
        self,
        workspace: Path,
        *,
        executable_locator: ExecutableLocator | None = None,
    ) -> None: ...

    @property
    def workspace(self) -> Path: ...

    def resolve(self) -> JavaRuntime: ...
```

The policy searches a sanitized PATH that removes the canonical workspace and
all of its descendants. Located paths must resolve to existing regular files
outside the workspace. The tool always launches the returned absolute paths.
Model arguments cannot supply or override them. If a trusted compiler and
runtime cannot both be found, the tool returns a stable
`executable_denied` safety rejection.

`AuthorizedCommandExecutor.execute()` gains one backward-compatible keyword:

```python
def execute(
    self,
    command: AuthorizedCommand,
    context: ExecutionContext,
    *,
    stdin_stream: BinaryIO | None = None,
) -> ToolExecution: ...
```

`None` retains the current `DEVNULL` behavior. A supplied binary stream is
passed directly to `Popen`; it is opened and closed by the Java tool. Existing
callers and the verification executor protocol continue to call the two
positional arguments unchanged.

The Java commands use `AuthorizedCommand` values created only by the Java
policy/tool boundary, with `CommandSource.MODEL` and the selected purpose. They
reuse the executor's `shell=False`, fixed cwd, sanitized child environment,
bounded concurrent readers, monotonic timeout, and Windows process-tree cleanup.
The sanitized child environment removes `CLASSPATH`, `JAVA_TOOL_OPTIONS`,
`_JAVA_OPTIONS`, `JDK_JAVA_OPTIONS`, and `JDK_JAVAC_OPTIONS` in addition to the
existing credential and Python/Git injection variables. The explicit classpath
and `-proc:none` prevent inherited classpath or annotation-processor injection.
The existing model-facing `CommandPolicy.authorize()` remains unchanged and
continues to reject Java command strings.

Build output is placed in a unique child of `.coding-agent/java-tests`. The
unique directory is removed in a `finally` path. It is internal state, is not
reported in `changed_paths`, and does not increment the mutation ledger. A
cleanup failure cannot produce passing metadata. No ordinary exception handler
catches `BaseException`.

## 11. Java result contract

Every successfully invoked `run_java_tests` operation returns exactly this
JSON shape through `ToolExecution.output`:

```json
{
  "case_count": 10,
  "failed_case": null,
  "passed_count": 10,
  "phase": "complete",
  "purpose": "verification",
  "safe_error_code": null,
  "source_count": 9,
  "stderr": "",
  "stdout": ""
}
```

Allowed phases are `discovery`, `compile`, `case`, `cleanup`, and `complete`.
Stable `safe_error_code` values distinguish compile failure, program failure,
output mismatch, output truncation, suite timeout, and cleanup failure. Passing
results have `phase="complete"`, no failed case, no safe error,
`passed_count == case_count`, `exit_code=0`, and `timed_out=False`.

Failure semantics are:

- strict argument, invalid path, reparse, source/fixture discovery, fixture
  size, and fixture-encoding failures occur before child execution and are
  returned by the existing registry as `rejected`;
- a compiler nonzero exit returns registry status `ok` and the compiler exit
  code in metadata;
- a program nonzero exit returns registry status `ok` and the program exit code;
- an exact-output mismatch returns registry status `ok` and stable synthetic
  exit code `1`;
- timeout returns registry status `ok`, `timed_out=True`, and `exit_code=None`;
- cleanup failure after otherwise successful execution returns registry status
  `ok`, phase `cleanup`, stable synthetic exit code `1`, and never passing
  evidence;
- an expected process-start or capture exception has a fixed safe message and
  cannot become verification evidence;
- `KeyboardInterrupt` and `SystemExit` propagate.

The JSON never contains source content, complete test input, environment values,
credentials, command authorization objects, provider objects, or unredacted
absolute workspace paths.

## 12. Verification integration

`VerificationGate.observe_tool_result()` keeps its current `run_command` path
and adds an independent `run_java_tests` decoder. It does not pretend that Java
is an `AuthorizedCommand` accepted by `is_credible_verification_command()`.

Java evidence is accepted only when all of these hold:

- call and result IDs/names match;
- registry result status is `ok`;
- call arguments have the exact Java-tool keys;
- `purpose` is `verification` in both arguments and output;
- the output has the exact locked shape and internally consistent counts;
- metadata and output phase agree;
- pass means complete suite, zero exit code, no timeout, no truncation, no safe
  error, and all discovered cases passed.

Accepted evidence increments `verification_attempt_count` once, stores a normal
provider-neutral `VerificationResult`, and sets `validation_index` to the
current `state.mutation_index`. Its safe command description is deterministic:

```text
run_java_tests source_root=<...> main_class=<...> tests_directory=<...>
```

It never contains executable or temporary absolute paths. Compile failure,
program failure, output mismatch, cleanup failure, and timeout create the
corresponding failed/timed-out evidence. `purpose="test"`, rejected calls,
registry errors, and malformed results never create passing evidence. A
malformed result that claims to be verification evidence raises the existing
`VerificationError` internal invariant.

`VerificationGate.evaluate()` remains authoritative. Success still requires a
fresh passed result whose `validation_index` equals `mutation_index`.
`COMPLETION_CANDIDATE` remains nonterminal until this gate accepts evidence.
When a user supplied `--verify`, the existing mandatory command continues to
take precedence and is not replaced by Java evidence.

For the target Java demo, the GUI is launched without
`--verify "pytest -q"`. The Agent may use `run_java_tests` first with
`purpose="test"` during work and finally with `purpose="verification"`.

## 13. Composition and lifecycle

The production composition root registers one `RunJavaTestsTool` alongside the
existing list, read, replace, write, and command tools. It shares the same
canonical workspace through `ExecutionContext`, but it does not create a global
registry or a second safety/verification state machine.

The tool's temporary build files are excluded from mutation tracking. A
successful README write still increments `mutation_index` exactly once and
makes prior verification stale. Only a later successful Java verification can
advance `validation_index` to that mutation.

No GUI, REST, SSE, session, provider, message, Agent, or state public interface
changes. Existing Python verification, user-supplied `--verify`, provider
continuation, cancellation, audit logging, final report, and exit-code behavior
must remain compatible.

## 14. File map

### 14.1 New files

- `src/coding_agent/tools/java.py`
- `tests/tools/test_java_tool.py`
- `tests/integration/test_java_agent.py`

### 14.2 Production files changed

- `src/coding_agent/context.py`: adaptive complete-turn compression only;
- `src/coding_agent/safety.py`: trusted Java runtime policy only;
- `src/coding_agent/tools/shell.py`: optional binary stdin seam on the existing
  executor only;
- `src/coding_agent/verification.py`: exact Java evidence decoder and observer
  branch only;
- `src/coding_agent/app.py`: register one Java tool using the existing
  composition root;
- `src/coding_agent/web_static/app.js`: run-aware conversation/activity
  projection only.

### 14.3 Test files changed

- `tests/test_context.py`
- `tests/test_command_safety.py`
- `tests/test_verification.py`
- `tests/test_app.py`
- `tests/js/web_gui.test.mjs`
- `tests/test_docs.py`

### 14.4 Baseline guidance synchronized before production edits

- `AGENTS.md`
- `DESIGN.md`
- `TASKS.md`

These files replace the obsolete five-tool/Python-only wording with the approved
dedicated Java boundary. They do not weaken `run_command`, framework, credential,
path, remote, or approval rules.

### 14.5 Public documentation changed after GREEN

- `README.txt`
- `README.md`
- `docs/USAGE.md`

The implementation must stop for approval if it needs to modify messages,
model clients, Agent/state/session interfaces, provider adapters, Web API/SSE,
CLI arguments, dependency metadata, or existing tool schemas.

## 15. Error handling and privacy

- all model-selected paths pass through `PathGuard`;
- Java executables are selected by deterministic local policy, never model
  text;
- no child process receives OpenAI or Chat Completions credentials;
- compiler/program output is bounded, workspace-path redacted, and never used as
  an exception message;
- no command line, environment dump, source, fixture input, continuation, hidden
  reasoning, or provider payload enters the GUI projection;
- ordinary Java failures are represented as safe tool evidence rather than
  tracebacks;
- a tool rejection or failed test cannot be transformed into passed evidence;
- temporary artifacts are cleaned, and cleanup failure cannot claim success;
- all automated tests remain offline and use synthetic credentials only;
- no broad handler catches `BaseException`.

## 16. Test strategy

### 16.1 GUI projection tests

Executable Node tests against the real `app.js` cover:

1. active stream deltas render one temporary activity card and no assistant
   bubble;
2. a confirmed text-plus-tool response remains process narration;
3. tool and verification events replace the current card rather than append
   cards;
4. a successful run renders only its last committed assistant text;
5. a failed or interrupted run renders no assistant process text and exactly
   one terminal card;
6. multiple runs in one session are projected independently by `run_id`;
7. reload, SSE replay, and reset-required produce the same projection;
8. model text still uses safe text nodes and never an HTML sink.

### 16.2 Context tests

Deterministic fake-model tests cover:

1. budget-compliant history is unchanged and continuation is preserved;
2. the observed 25-item/fewer-than-eight-turn pattern compresses instead of
   terminating;
3. the first candidate removes at least one oldest complete turn;
4. a valid model summary is requested at most once;
5. a still-oversized candidate expands the removed range locally without a
   second provider call;
6. ordinary `ModelError` and invalid summary responses use fallback;
7. `FatalModelError`, `ModelBudgetExceeded`, `KeyboardInterrupt`, and
   `SystemExit` propagate;
8. every retained/removed tool call and result remains paired and ordered;
9. successful compression clears active and summary-response continuation;
10. identical inputs produce identical local fallback output;
11. the first fitting candidate retains the greatest possible recent history;
12. an unshrinkable newest turn terminates deterministically.

### 16.3 Java safety and tool tests

Fake runtime, executor, clock, and temporary-directory seams cover:

1. exact strict schema and argument validation;
2. main-class grammar;
3. stable source and fixture order;
4. empty, orphan, duplicate, oversized, non-UTF-8, and over-limit discovery;
5. relative paths, protected paths, traversal, symlink, junction, and reparse
   rejection;
6. workspace-shadowed Java executables are ignored/rejected;
7. trusted absolute executable arrays, `shell=False`, fixed cwd, sanitized
   environment, and file-backed stdin;
8. compile success/failure and source count;
9. per-case stdin, nonzero exit, deterministic invalid-byte replacement, and
   first-failure stop;
10. CRLF/CR normalization, exact whitespace, and no-final-newline comparison;
11. 65,536/65,537-byte child-output boundaries and 8,192-byte diagnostic bound;
12. one 60-second maximum suite deadline and prevention of the first disallowed
    launch;
13. partial output, timeout, Windows tree termination, and cleanup failure;
14. no build artifact enters `changed_paths` or the mutation ledger;
15. no secret, source, full fixture input, or absolute workspace path appears in
    result JSON or repr.

### 16.4 Verification tests

Tests cover:

1. `purpose="test"` does not update final verification;
2. complete passing Java evidence updates status and current validation index;
3. compile, program, mismatch, cleanup, truncation, and timeout outcomes cannot
   pass;
4. stale evidence cannot satisfy a later mutation;
5. malformed or contradictory output raises the stable internal invariant;
6. a user-supplied required command retains precedence;
7. existing Python verification behavior is unchanged.

### 16.5 Integration and real-runtime verification

A fully offline headless Agent test uses a fake model and injected Java executor
to create a new README, invalidate verification, run Java verification, and
reach success only with fresh evidence. It proves registry, mutation ledger,
verification gate, and final-state integration without a JDK or provider.

One Windows-local smoke test compiles and runs a generated minimal Java fixture
with the real trusted JDK. It is conditionally skipped only when a compatible
JDK is absent; on the current development machine it must execute, because the
baseline check found `javac` and `java` version 22.0.1. The final report must
state whether this test actually ran rather than counting a skip as evidence.

Final verification also runs all existing Python, provider, Agent, context,
safety, verification, session, Web, GUI, Windows reparse, and Windows
process-tree tests; `pip check`; dependency and Agent-framework scans; credential
and absolute-personal-path scans; placeholder and skip/xfail audits;
`git diff --check`; status inspection; and a complete diff review.

## 17. Acceptance matrix

| Requirement | Evidence |
| --- | --- |
| Only one live activity card | Node active-run projection tests |
| Only final assistant answer persists visually | successful-run/reload projection tests |
| Failed run hides narration | failed/interrupted projection tests |
| Under-budget history unchanged | context no-compression test |
| Fewer than eight turns can still compress | reproduced 25-item regression test |
| Tool pairs remain valid | complete-turn pairing tests |
| At most one summary provider call | fake-model call-count test |
| Expanded removal is deterministic | fallback expansion and repeatability tests |
| Continuation cleared after compression | continuation lifecycle tests |
| Dedicated Java tool, no arbitrary shell | schema, policy, and command audit |
| Workspace and reparse protection | PathGuard/Java discovery safety tests |
| Trusted system JDK only | sanitized locator and shadow-executable tests |
| Stable source/case ordering | discovery-order tests |
| Exact black-box comparison | newline and whitespace comparison tests |
| Bounded output and runtime | truncation, diagnostic, deadline, and tree tests |
| Cleanup cannot claim pass | cleanup-failure test |
| Local test vs final verification distinction | purpose tests |
| Fresh Java evidence required | mutation/validation index tests |
| Existing `--verify` precedence | mandatory-command regression test |
| Provider-neutral and offline | import, fake-executor, network, and credential audits |
| Real Java path works locally | actual JDK smoke test with non-skip evidence |
| Existing behavior remains compatible | complete repository regression suite |

## 18. Alternatives considered

### 18.1 Persist no intermediate assistant text

Changing `AgentRunner` or the session event contract to stop persisting text
that accompanies tool calls would reduce stored events, but it would alter an
accepted core/session interface and discard useful audit evidence. The chosen
GUI projection fixes the user experience without weakening the backend record.

### 18.2 Treat `recent_turns` as absolute

The current behavior protects recency but can terminate below the character
budget solely because multi-tool turns contain many items. Making recency a
preference with a one-turn hard minimum preserves the newest actionable state
while satisfying the actual hard budgets.

### 18.3 Extend `run_command` to Java

Adding `javac` and `java` command strings to `CommandPolicy` would enlarge the
model-controlled command grammar, duplicate build/test orchestration in prompts,
and make evidence parsing fragile. The dedicated tool exposes only the four
locked arguments and performs all command construction deterministically.

### 18.4 Generate a Python Java-test harness

Writing a temporary Python harness into the workspace would mix implementation
artifacts with user changes, complicate the mutation ledger, and still require
Java subprocess authorization. The dedicated in-process tool is smaller and
easier to defend.

### 18.5 Compile-only verification

Compilation proves syntax and linking but not the ten accepted black-box
fixtures. The chosen compile-and-run design provides substantially stronger
fresh evidence for this project while remaining bounded and deterministic.

## 19. Limitations

- Java verification supports simple source trees and stdin/stdout fixture pairs,
  not general Maven/Gradle/JUnit projects.
- Newline style is normalized, but every other output byte after strict UTF-8
  decoding remains significant.
- The Java process is constrained by time, output, path, environment, and
  process-tree controls; it is not a hostile-code VM or operating-system
  sandbox.
- A missing local JDK prevents Java verification and must be reported; the Agent
  may not download one.
- GUI projection hides process narration from the normal conversation but does
  not erase accepted audit/session events.
- Adaptive compression guarantees maximal retained complete turns under the
  configured deterministic size model, not semantic perfection of a provider
  summary.
- The real target README creation remains a manual post-implementation smoke
  test because automated implementation must not mutate that separate project.

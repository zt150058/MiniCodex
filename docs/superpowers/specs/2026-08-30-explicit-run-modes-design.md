# Explicit Modify and Read-Only Run Modes Design

**Date:** 2026-08-30

**Status:** Approved in conversation

**Scope:** Per-run modify/read-only execution modes, deterministic read-only
tool capabilities, an `ANSWERED` terminal state, and CLI/Web/GUI integration

## 1. Goal

The current Agent has one completion contract: every model completion candidate
must pass `VerificationGate` before it can become `SUCCESS`. That contract is
correct for a coding task that may modify files, but it cannot represent a
read-only request such as “read this workspace and explain the project.”

A real GUI run demonstrated the mismatch. The Agent completed the requested
inspection, produced a substantive answer, then repeatedly re-entered the
verification loop because no credible post-modification verification existed.
It eventually failed at `logical_model_call_limit` after 12 logical model calls,
even though it had not changed the workspace.

This milestone introduces an explicit mode on every run:

- `modify`: the existing coding-agent behavior, including mandatory fresh
  verification before `SUCCESS`;
- `read_only`: a deterministic inspection capability that can terminate as
  `ANSWERED` after producing a final response without modifying the workspace.

The mode is selected by the user, never inferred from prompt text. It is
provider-neutral, persisted with the run, enforced by the local composition
root and safety policy, visible in CLI/REST/GUI output, and covered by fully
offline tests.

## 2. Baseline prerequisite

At design-writing time, `main` points to commit `465bda8`, while these existing
files are modified but uncommitted:

- `src/coding_agent/web_static/app.js`
- `tests/js/web_gui.test.mjs`

This design does not modify, discard, stage, or incorporate those changes.
Before an implementation plan is executed, the user must either commit them or
explicitly authorize them as the exact dirty baseline. Implementation must stop
if any other unapproved change is present.

`TASKS.md` currently marks Task 24 as `进行中`. The implementation plan must
verify that Task 24 has been reviewed and committed before changing Task 24 to
`已完成` and adding/starting Task 25. No task-status change belongs to this
design-writing turn.

No branch, worktree, subagent, stage, commit, push, pull, fetch, remote access,
real provider call, or credential use is authorized by this specification.

## 3. Locked decisions

The following decisions were approved in conversation:

1. Use one end-to-end, provider-neutral `RunMode` rather than a second Agent
   implementation or a verification-only exception.
2. Mode belongs to each run/message, not to the session as a whole.
3. The backward-compatible default is `modify`.
4. Read-only mode exposes `list_directory`, `read_file`, and a dedicated
   read-only Git inspection tool. It exposes no file mutation, Python/test,
   Java, generic command, or verification capability.
5. A valid read-only final answer uses the new `AgentStatus.ANSWERED` terminal
   state, exit code 0, and session run status `succeeded`.
6. Both the one-shot CLI and local Web GUI support explicit selection.
7. `SUCCESS` remains exclusively reserved for a modification-capable run with
   fresh passing verification evidence.

## 4. Included and excluded scope

### 4.1 Included

- a new `RunMode` enum with `MODIFY` and `READ_ONLY`;
- per-run propagation through configuration, session/controller/runtime,
  SQLite, REST/SSE, Agent state, audit facts, final report, and GUI;
- `AgentStatus.ANSWERED` and its strict report/session invariants;
- mode-specific `ToolRegistry` composition;
- a strict `inspect_git` tool that reuses the existing command executor and
  read-only Git safety grammar;
- a one-shot `--read-only` CLI flag;
- a compact GUI mode selector and historical mode badge;
- SQLite schema migration that maps historical runs to `modify`;
- deterministic error behavior, offline unit/integration/GUI tests, and full
  regression verification;
- synchronization of the approved design, task, README, and usage documents
  after production behavior is green.

### 4.2 Excluded

This milestone does not add:

- automatic prompt classification or inferred permissions;
- a session-wide fixed mode or a persisted GUI preference;
- a second Agent loop, planner, subagent, or Agent framework;
- arbitrary Shell, arbitrary Git, Python scripts, pytest, Java execution, or
  verification commands in read-only mode;
- MCP, executable Skills, remote Skills, plugins, accounts, remote deployment,
  or concurrent runs;
- deletion, move, permission change, binary editing, Git writes, commit, push,
  package installation, or network tools;
- an operating-system sandbox;
- changes to `ModelClient.complete(ModelRequest) -> ModelResponse`, provider
  adapter protocols, message/tool-call types, continuation formats, or provider
  retry behavior.

## 5. Chosen architecture

```text
one-shot CLI --read-only             GUI per-message mode selector
             |                                      |
             v                                      v
         RunConfig                         strict REST request DTO
             |                                      |
             |                              SessionController
             |                                      |
             |                              SessionRunRequest
             |                                      |
             +-------------------+------------------+
                                 |
                                 v
                         execute_agent_run
                         |               |
                         v               v
                    AgentState      mode-specific
                    run_mode        ToolRegistry
                         |               |
                         +-------+-------+
                                 |
                                 v
                           AgentRunner
                     modify       read_only
                       |               |
                VerificationGate     ANSWERED
                       |               |
                     SUCCESS       exit code 0
                                 |
                                 v
               FinalReport / SQLite / REST / SSE / GUI
```

There remains one `AgentRunner`, one context manager, one termination policy,
one streaming lifecycle, one session controller, and one provider boundary.
Mode changes capability composition and final-text handling; it does not fork
the core execution architecture.

## 6. Run mode interface

### 6.1 Provider-neutral type

Add `src/coding_agent/run_mode.py`:

```python
from enum import StrEnum


class RunMode(StrEnum):
    MODIFY = "modify"
    READ_ONLY = "read_only"
```

The independent module avoids importing configuration into state/session code
or session code into the composition root.

### 6.2 Configuration and state

`RunConfig` gains:

```python
run_mode: RunMode = RunMode.MODIFY
```

`load_run_config()` gains a keyword with the same default and rejects values
that are not a valid `RunMode` or matching enum string. `RunConfig` repr may
show the non-sensitive mode but must continue hiding credentials, base URLs,
and authorized verification objects as already required.

`AgentState` gains:

```python
run_mode: RunMode = RunMode.MODIFY
```

`AgentState.start()` gains a keyword-only `run_mode` with that default. Existing
test construction and provider-neutral model interfaces remain source
compatible.

The run mode is immutable in meaning after run admission. Code must not switch
an active state between modes.

### 6.3 Instruction snapshot

`RunInstructionBuilder.build()` gains a keyword-only run mode with a `modify`
default. Its local instruction snapshot states the selected mode and lists only
the capabilities present in that mode. Skill instructions remain subordinate:
they cannot register tools, change mode, bypass safety, or change completion
invariants. The instruction is guidance; deterministic registry composition
and state/report checks remain authoritative.

## 7. State machine and terminal invariants

### 7.1 New status

`AgentStatus` gains:

```python
ANSWERED = "answered"
```

Read-only transitions are:

```text
RUNNING
  +-- tool calls -> execute registered read-only tools -> RUNNING
  +-- nonempty final text -> ANSWERED
  +-- budget/model/tool/safety/internal failure -> FAILED
  `-- user cancellation -> INTERRUPTED
```

When a provider response contains tool calls, those calls keep the existing
ordered tool-processing semantics. Text accompanying tool calls remains
process narration under the existing confirmed/projection rules and is not a
terminal answer. `ANSWERED` is reached only from a later nonempty response with
no tool calls.

### 7.2 `ANSWERED` invariants

An `ANSWERED` state is valid only when all conditions hold:

- `run_mode is RunMode.READ_ONLY`;
- `completion_text` is nonempty;
- `termination_reason is None`;
- `failure_reason is None`;
- `mutation_index == 0`;
- `modified_paths == ()`;
- `verification_status is VerificationStatus.NOT_RUN`;
- `verification_attempt_count == 0`;
- `last_verification is None`.

`AgentRunner` emits the existing completion-candidate audit fact for the final
text, then transitions directly to `ANSWERED` without invoking
`VerificationGate`. It must check the mutation invariants before that
transition. Any mutation fact in read-only mode terminates with
`FAILED/INTERNAL_INVARIANT`.

### 7.3 Existing mode remains unchanged

In `MODIFY` mode, final text still becomes `COMPLETION_CANDIDATE`; production
runs still enter the existing `VerificationGate`; only fresh passing evidence
can set `SUCCESS`. Model prose alone remains insufficient. Existing tests that
prove prose without evidence cannot succeed must remain unchanged.

Both modes retain the current logical model call, physical provider attempt,
tool call, elapsed time, repetition, consecutive error, safety rejection,
context compression, cancellation, and audit-failure behavior.

## 8. Mode-specific tool capability

### 8.1 Exact tool sets

The production composition root creates a new registry for every run:

| Tool | `modify` | `read_only` |
| --- | ---: | ---: |
| `list_directory` | yes | yes |
| `read_file` | yes | yes |
| `replace_text` | yes | no |
| `write_file` | yes | no |
| `run_command` | yes | no |
| `run_java_tests` | yes | no |
| `inspect_git` | no | yes |

The existing six-tool modify registry and tool schemas remain unchanged.
Read-only mode does not construct or register mutation or verification tools.
Its `AgentRunner` receives `verification_gate=None`; the runner's explicit
`RunMode.READ_ONLY` branch, not the absence of a gate by itself, authorizes the
`ANSWERED` transition. Existing low-level tests that omit a gate in modify mode
continue to stop at `COMPLETION_CANDIDATE`.
Unknown calls continue to produce a paired `rejected` `ToolResult` without
execution.

### 8.2 `inspect_git` contract

Add `InspectGitTool` to `src/coding_agent/tools/shell.py`:

```python
class InspectGitTool:
    name = "inspect_git"
    schema: JSONObject

    def __init__(
        self,
        *,
        authorized_executor: AuthorizedCommandExecutor | None = None,
        policy_factory: PolicyFactory | None = None,
    ) -> None: ...

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution: ...
```

Its strict schema accepts exactly:

```json
{
  "command": "git status --short"
}
```

`command` is a required nonempty string; extra fields are rejected. Purpose is
not model-controlled and is fixed internally to `inspect`.

`CommandPolicy` gains one additive method:

```python
def authorize_git_inspection(
    self,
    command: object,
    *,
    source: CommandSource,
) -> AuthorizedCommand: ...
```

The method uses the existing native Windows command-line parser, trusted Git
launcher resolution, `_authorize_git()` grammar, `PathGuard`, and fixed Git
hardening flags. It rejects any first executable other than Git before an
`AuthorizedCommand` is returned. The only allowed subcommands remain `status`,
`diff`, `log`, `show`, and `ls-files`, with their existing argument allowlists.
The returned purpose is always `inspect`.

The tool reuses `AuthorizedCommandExecutor`, including argument-array launch,
`shell=False`, canonical workspace cwd, credential/environment isolation,
bounded stdout/stderr, monotonic timeout, and Windows process-tree cleanup.
Nonzero Git exit remains a successfully completed tool invocation with the
real exit code and streams; it is not converted into a tool exception.

## 9. Session, persistence, and API flow

### 9.1 Session types

The following provider-neutral records gain a required `RunMode` field with a
`MODIFY` default only where backward source compatibility is necessary:

- `SessionRunRequest.run_mode`;
- `SessionRunRecord.run_mode`;
- `SessionSubmission.run.run_mode` through the existing record;
- `RunHandle.run_mode` for immediate caller confirmation;
- `SessionRunOutcome` does not duplicate mode because the admitted request and
  stored run remain authoritative.

`SessionController.create_session()` and `submit_message()` gain keyword-only
`run_mode: RunMode = RunMode.MODIFY`. The controller freezes that value in the
store submission and the worker request. Follow-up history remains one safe
initial user message; run mode is not embedded in user content or inferred from
conversation text.

`AgentSessionRunExecutor.execute()` copies the request mode into the per-run
`RunConfig` with `dataclasses.replace()` before calling `execute_agent_run()`.

### 9.2 SQLite migration

Increment the session schema from version 2 to version 3. Fresh schema adds:

```sql
run_mode TEXT NOT NULL DEFAULT 'modify'
CHECK(run_mode IN ('modify', 'read_only'))
```

Initialization of an existing version-2 database performs one transaction:

```sql
ALTER TABLE session_runs
ADD COLUMN run_mode TEXT NOT NULL DEFAULT 'modify'
CHECK(run_mode IN ('modify', 'read_only'));
```

It then advances `PRAGMA user_version` to 3. Historical records therefore have
the deterministic value `modify`. In the same transaction, each non-null
historical `final_report_json` is decoded with the exact version-1 persisted
report contract, gains `run_mode="modify"`, advances to report schema version
2, and is written back in canonical JSON. Malformed historical report JSON
fails the migration without partial changes. Version 0/fresh creation uses the
version-3 schema directly. A database newer than supported, a migration
failure, or an invalid stored value produces the existing safe store error and
never silently chooses a mode.

All `INSERT`, decode, list, get, recovery, and terminal-transition paths preserve
the admitted mode. Migration tests use temporary workspaces and no real user
database.

### 9.3 REST and SSE

Strict DTOs become:

```json
POST /api/v1/sessions
{
  "message": "Introduce this project",
  "skill_ids": [],
  "run_mode": "read_only"
}
```

```json
POST /api/v1/sessions/{session_id}/messages
{
  "message": "Inspect the tests too",
  "run_mode": "read_only"
}
```

`run_mode` defaults to `modify` when omitted, accepts only the two exact enum
strings, and retains the existing strict rejection of wrong types and extra
fields. Create/follow-up responses contain `session_id`, `run_id`, and the
actual `run_mode`. Serialized run records also contain `run_mode`.

The in-memory `run_finished` update includes both the session run status and
the terminal `agent_status`, so the GUI can show `ANSWERED` immediately. The
durable session view remains authoritative after reload. No provider payload,
continuation, hidden reasoning, instruction text, or credential enters REST,
SSE, or SQLite.

## 10. CLI and GUI behavior

### 10.1 One-shot CLI

`coding-agent` adds the flag:

```text
--read-only    Inspect and answer without file mutation or verification tools
```

Absence maps to `RunMode.MODIFY`; presence maps to `RunMode.READ_ONLY`. Argument
names and the existing invocation style remain otherwise unchanged.

The one-shot CLI rejects `--read-only` combined with `--verify` before the
application or provider is constructed. It returns exit code 2 and a stable,
non-sensitive configuration error. This prevents silently ignoring a command
the user explicitly described as mandatory.

`coding-agent-web --verify` remains valid because it is a server-level setting
for modification-capable runs. A GUI read-only run does not execute that
command; a GUI modify run continues to require it.

### 10.2 Final report

`FinalReport` gains `run_mode: RunMode`, and `to_dict()` serializes it as
`run_mode`. `REPORT_SCHEMA_VERSION` advances from 1 to 2. New reports and
persisted report projections use only version 2; version-1 persisted reports
are accepted only by the version-2-to-version-3 database migration described
in section 9.2. An `ANSWERED` report has:

```json
{
  "run_mode": "read_only",
  "status": "answered",
  "exit_code": 0,
  "termination_reason": null,
  "changed_paths": [],
  "mutation_index": 0,
  "validation_index": null,
  "verification": {
    "status": "not_run"
  }
}
```

`FinalReport.from_state()` enforces every `ANSWERED` invariant in section 7.2.
`SUCCESS`, `FAILED`, and `INTERRUPTED` mappings remain unchanged. Audit close
failure may replace an otherwise answered state with
`FAILED/AUDIT_LOG_FAILURE`, matching the existing fail-closed policy.

The safe session summary accepts `answered` as an Agent status. Session runtime
maps both `SUCCESS` and `ANSWERED` to `SessionRunStatus.SUCCEEDED`, while
preserving the exact `agent_status` for GUI/report interpretation.

### 10.3 GUI

Add a compact segmented control inside the existing composer action row:

```text
[ 允许修改 ] [ 只读问答 ]                         [发送]
```

Rules:

- initial page state is `modify`;
- the selected value remains in browser memory until the user changes it or
  reloads the page;
- switching sessions does not silently change it;
- submission captures it for that run;
- the control is disabled while any run is active, matching the current
  single-active-run rule;
- each historical user-message label receives one small `可修改` or `只读`
  badge derived from its run record, never from message text;
- `agent_status="answered"` renders as `已回答` in the run header/terminal
  projection;
- `SUCCESS` retains its verification-success wording;
- the badge is inline metadata, not another activity card;
- no unsafe HTML sink, remote resource, framework, or second front-end state
  machine is introduced.

## 11. Logging, context, and provider compatibility

`EVENT_SCHEMA_VERSION` advances from 1 to 2. The run-start audit fact gains
`run_mode`; run-completed validation accepts `answered` and retains all
existing counters and redaction. `SESSION_UPDATE_SCHEMA_VERSION` also advances
from 1 to 2 because terminal `run_finished` data gains `agent_status`. The completion
candidate is logged before the answered transition. No log records full
instructions, user content beyond existing safe facts, provider continuation,
reasoning, environment dumps, or credentials.

Context measurement, complete-turn pairing, semantic/fallback summary behavior,
continuation clearing on compression, and shared logical/physical budgets are
identical in both modes. A read-only answer can still fail from context budget
exhaustion before a final response.

`OpenAIResponsesClient`, `ChatCompletionsModelClient`, `FakeModelClient`,
`ModelRequest`, and `ModelResponse` do not gain a mode field. Providers see mode
only through the local instruction snapshot and the exact tool schemas sent by
the composition root. SDK types remain confined to provider adapters.

## 12. Error handling and safety

- invalid CLI/API/stored modes are rejected, never inferred or normalized to a
  different permission;
- write, generic command, Java, and verification tools are absent from a
  read-only registry and therefore cannot execute;
- an unknown/disallowed tool call receives the existing paired rejected result
  and contributes to existing error/no-progress accounting;
- repeated disallowed calls eventually fail through the existing deterministic
  limits rather than being ignored;
- empty final responses remain `EMPTY_MODEL_RESPONSE`;
- model, provider, context, tool, time, cancellation, and audit failures retain
  their existing safe mappings;
- `KeyboardInterrupt` becomes the existing interrupted result; `SystemExit`
  and other uncaught `BaseException` values are not swallowed;
- a read-only state with any mutation fact fails as `INTERNAL_INVARIANT`;
- Skills cannot change mode or registry composition;
- `inspect_git` cannot execute workspace code and cannot perform Git writes;
- all filesystem operations still use `PathGuard`, and all process execution
  retains bounded output, timeout, fixed cwd, credential isolation, and
  Windows process-tree cleanup;
- automated tests do not read real API keys or access the network.

## 13. File map

### 13.1 New files

- `src/coding_agent/run_mode.py`
- `tests/test_run_mode.py`
- `docs/superpowers/plans/Task25.md` during the later writing-plans phase

### 13.2 Core production files changed

- `src/coding_agent/config.py`: run-mode config and validation;
- `src/coding_agent/instructions.py`: mode-aware immutable instructions;
- `src/coding_agent/state.py`: `run_mode` and `ANSWERED`;
- `src/coding_agent/agent.py`: read-only final transition and mutation invariant;
- `src/coding_agent/safety.py`: additive Git-inspection authorization method;
- `src/coding_agent/tools/shell.py`: strict `InspectGitTool`;
- `src/coding_agent/app.py`: mode-specific registry/gate composition;
- `src/coding_agent/logging.py`: run-mode and answered audit validation;
- `src/coding_agent/report.py`: run mode, answered report invariants, exit code;
- `src/coding_agent/cli.py`: one-shot `--read-only` and combination rejection.

### 13.3 Session and Web files changed

- `src/coding_agent/session.py`: run-mode records and answered safe summary;
- `src/coding_agent/session_store.py`: schema v3 migration and persistence;
- `src/coding_agent/session_events.py`: terminal update schema carries the
  exact `agent_status` needed for immediate answered rendering;
- `src/coding_agent/session_runtime.py`: per-request mode composition and mapping;
- `src/coding_agent/session_controller.py`: per-run mode admission;
- `src/coding_agent/web.py`: strict DTO, serialization, and terminal update;
- `src/coding_agent/web_static/index.html`: compact mode control;
- `src/coding_agent/web_static/app.js`: mode API/state/projection behavior;
- `src/coding_agent/web_static/styles.css`: compact control and inline badge;

### 13.4 Tests changed

- `tests/test_config.py` does not exist; config coverage remains in
  `tests/test_cli.py` and `tests/test_app.py`;
- `tests/test_cli.py`
- `tests/test_instructions.py`
- `tests/test_agent_loop.py`
- `tests/test_command_safety.py`
- `tests/tools/test_shell_tool.py`
- `tests/test_app.py`
- `tests/test_logging.py`
- `tests/test_report.py`
- `tests/test_session.py`
- `tests/test_session_store.py`
- `tests/test_session_events.py`
- `tests/test_session_runtime.py`
- `tests/test_session_controller.py`
- `tests/test_web_api.py`
- `tests/test_web_sse.py`
- `tests/web_support.py`
- `tests/js/web_gui.test.mjs`
- `tests/integration/test_read_only_agent.py`

### 13.5 Baseline and public documents changed after GREEN

- `AGENTS.md`: document the two model-facing tool sets and answered invariant;
- `DESIGN.md`: add explicit modes and update success/termination sections;
- `TASKS.md`: close approved Task 24 and add Task 25 with exact acceptance
  criteria/status;
- `README.txt`
- `README.md`
- `docs/USAGE.md`

No dependency, provider adapter, message type, verification implementation,
Java tool, context algorithm, packaging metadata, or unrelated test file may be
changed without stopping for user approval.

## 14. Test strategy

Every production behavior follows RED, observed expected failure, minimal
GREEN, and targeted regression before the next behavior.

### 14.1 Mode and state tests

1. enum values, strict construction, and repr/serialization;
2. omitted CLI/API mode defaults to `modify`;
3. `AgentState.start()` preserves the selected mode;
4. a direct read-only text response becomes `ANSWERED`;
5. a read-only list/read/tool-result/final-text flow becomes `ANSWERED`;
6. text accompanying tool calls is not prematurely answered;
7. mutation facts prevent `ANSWERED` and produce the internal invariant;
8. modify prose without evidence still cannot become `SUCCESS`;
9. both modes retain budget, empty response, cancellation, model error, and
   `SystemExit` behavior.

### 14.2 Capability and safety tests

1. modify registry exposes exactly the existing six schemas;
2. read-only registry exposes exactly list, read, and inspect Git;
3. `inspect_git` schema is strict and purpose is not model-controlled;
4. each of the five approved Git subcommands reaches an injected executor;
5. Python, pytest, ruff, mypy, Java, PowerShell, cmd, Bash, network tools,
   package tools, Git writes, malformed quoting, and extra arguments are
   rejected before execution;
6. fixed cwd, `shell=False`, bounded streams, timeout, credentials, and process
   tree tests continue to pass;
7. nonzero Git exit remains registry status `ok` with real metadata.

### 14.3 Report and audit tests

1. valid answered report has exit 0, no termination reason, no changes, and
   `not_run` verification;
2. every violated answered invariant raises `ReportInvariantError`;
3. success still requires fresh passing evidence;
4. run-start and run-completed audit events contain/accept the exact mode and
   answered status;
5. audit close failure converts answered to failed;
6. no mode-related log or repr leaks credentials or provider content.

### 14.4 Session and migration tests

1. fresh schema version 3 contains the checked mode column;
2. a real temporary version-2 database migrates to version 3 with all old runs
   set to `modify` and all valid persisted report JSON upgraded from report
   schema 1 to schema 2;
3. migration is transactional and failure maps to a safe store error;
4. create and follow-up runs preserve independently selected modes;
5. decode/list/get/recovery/finish retain the mode;
6. invalid stored mode cannot be loaded;
7. answered maps to session `succeeded` while preserving
   `agent_status="answered"`;
8. narrative and continuation isolation remain unchanged.

### 14.5 REST, SSE, CLI, and GUI tests

1. create/follow-up DTO defaults, both valid values, wrong types, unknown
   values, and extra fields;
2. handle and serialized run responses return actual mode;
3. terminal SSE update carries `succeeded` plus `answered`;
4. new audit and session-update envelopes use schema version 2;
5. CLI flag mapping and help text;
6. `--read-only --verify` fails with exit 2 before factories/provider calls;
7. Web server-level verify remains active for modify and is not executed for
   read-only;
8. GUI initial/default mode, switching, persistence in page memory, disabled
   active state, create/follow-up bodies, reload, inline mode badges, answered
   label, and existing safe text rendering;
9. existing single-active-run, cancellation, Skill selection, activity-card,
   final-answer projection, and SSE reconnect/reset behavior remains green.

### 14.6 Integration and final verification

A fully offline regression reproduces the reported user scenario with a
scripted fake model:

```text
user asks to inspect and introduce a workspace
-> list_directory
-> read_file calls
-> final explanatory text
-> ANSWERED, exit 0, zero mutations, zero verification attempts
```

It asserts the Agent stops on that final text rather than consuming the
logical-model-call limit. A paired modify-mode test proves the same unverified
text cannot succeed.

Final verification runs the focused mode/Agent/tool/report/session/Web/GUI
tests, every existing Python test, Node GUI tests, Windows path/reparse tests,
Windows timeout/process-tree tests, `pip check`, SDK and Agent-framework import
audits, dependency audit, credential and personal-path scans, placeholder and
skip/xfail scans, `git diff --check`, final status, and complete diff review.
All automated provider behavior remains fake and offline.

## 15. Acceptance matrix

| Requirement | Evidence |
| --- | --- |
| Explicit per-run mode | enum, controller, request, persistence tests |
| Backward default remains modify | CLI/API/store migration tests |
| Same session can switch modes | sequential follow-up integration test |
| Read-only cannot mutate | exact registry and unknown-write-tool tests |
| Only approved Git inspection | schema and five-subcommand safety matrix |
| No workspace code execution in read-only | Python/test/Java rejection tests |
| Read-only final text terminates normally | direct and multi-tool Agent tests |
| `ANSWERED` is not verified `SUCCESS` | state/report/session/GUI assertions |
| Answered exit code is 0 | FinalReport and CLI tests |
| Mutation cannot be answered | internal-invariant tests |
| Modify verification remains mandatory | existing plus paired regression |
| Existing budgets still apply | logical/provider/tool/time boundary tests |
| Mode survives restart/reload | SQLite migration and GUI reload tests |
| GUI chooses mode per message | create/follow-up request tests |
| CLI supports explicit read-only | parser/config/application tests |
| `--read-only --verify` is not ignored | exit-2/no-factory test |
| Web global verify remains compatible | modify/read-only executor tests |
| Provider boundary unchanged | signature/import and provider regressions |
| Skill cannot expand permissions | mode-specific registry/instruction tests |
| No credential/network/dependency regression | offline and audit commands |
| Reported failure is fixed | scripted project-introduction integration test |

## 16. Alternatives rejected

### 16.1 Separate read-only Agent runner

A second runner would isolate the surface superficially but duplicate context,
streaming, cancellation, budgets, audit, and error handling. The two loops would
drift and weaken the project’s core “one explicit state machine” explanation.

### 16.2 Verification-gate exception only

Skipping verification based on a boolean near `VerificationGate` would not
remove mutation/test capabilities, persist the user’s intent, or distinguish a
safe answer from an unverified coding claim. It would scatter policy across the
wrong layer.

### 16.3 Reuse generic `run_command` in read-only mode

The existing generic command schema intentionally allows Python tests, Python
scripts, ruff, mypy, and verification purposes. Prompting the model to use only
Git would not be a security boundary. A dedicated tool makes the actual
capability equal to the advertised schema.

### 16.4 Infer mode from prompt text

Natural-language classification is nondeterministic and could grant mutation
permission for an incorrectly classified request. User selection is explicit,
auditable, testable, and easy to explain.

## 17. Limitations

- Read-only mode protects against Agent-exposed mutation and workspace-code
  execution; it is not an operating-system sandbox for the model provider or
  Git binary.
- Git inspection can observe only the approved local repository facts and
  cannot query remotes.
- A read-only answer can still fail because of provider errors, context size,
  budgets, cancellation, repeated invalid calls, audit failure, or malformed
  responses.
- The Agent does not automatically suggest or switch modes after a failure.
- Mode choice persists with each run, but the GUI’s next-run selection exists
  only in page memory and resets to `modify` on reload.
- Historical version-2 runs are indistinguishable by original intent and are
  therefore conservatively labeled `modify`.
- `ANSWERED` means a safe read-only response was produced; it does not claim
  factual correctness beyond the files and tool results actually available to
  the model.

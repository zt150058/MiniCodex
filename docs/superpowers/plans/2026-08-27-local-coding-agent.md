# Local Coding Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Repository policy:** `AGENTS.md` forbids subagent dispatch unless the user explicitly requests it. Use `superpowers:executing-plans` by default. This plan itself must be approved before either execution workflow starts.

**Goal:** Build a Windows-first Python CLI coding agent that implements its own local agent loop, safe workspace tools, context compaction, and evidence-based verification using the OpenAI Responses API.

**Architecture:** A synchronous `AgentRunner` owns explicit `AgentState` and calls provider-neutral `ModelClient`, `ToolRegistry`, `ContextManager`, `VerificationGate`, and `TerminationPolicy` interfaces. OpenAI supplies only model responses and function calls; all history, context selection, safety checks, local execution, logging, and success decisions remain deterministic local code.

**Tech Stack:** Python 3.11 or newer, standard library, official `openai` Python package, pytest, Windows subprocess APIs, JSONL logs.

**Spec:** `DESIGN.md`, with implementation order and acceptance criteria in `TASKS.md` and repository rules in `AGENTS.md`.

## Global Constraints

- Target Windows and a one-shot CLI; do not add a REPL or cross-platform compatibility work.
- Use no Agent framework or Agent SDK and no server-hosted file or execution tool.
- Keep production code in `src/coding_agent/` and tests in `tests/`.
- The only production dependency is `openai`; the test dependency is `pytest`. Do not add another dependency without a new approved design discussion.
- Use `store=False`; do not use server-side conversations as local history.
- Execute tool calls sequentially and execute commands with `shell=False`.
- Expose only `list_directory`, `read_file`, `replace_text`, `write_file`, and `run_command`.
- Keep default budgets at 12 outbound model attempts, 40 tool calls, and 10 minutes total runtime. Retries and context-summary calls count toward the model budget.
- Keep command timeout at 60 seconds by default and at most 300 seconds; retain at most 64 KiB each of stdout and stderr.
- Read at most 256 KiB per file operation and write at most 512 KiB.
- Any mutation invalidates earlier verification. A supplied `--verify` command must run after the last mutation and exit 0 before success.
- Never log secrets, authentication headers, environment dumps, hidden reasoning, or provider continuation payloads.
- Do not create worktrees, dispatch subagents, commit, push, or operate on remotes unless the user explicitly authorizes the specific action.
- Follow TDD for every behavior: failing test, observed failure, minimal implementation, observed pass, then relevant regression suite.
- In execution, create `.venv` in Task 1. All later `python` commands mean the activated `.venv` interpreter; automation may use `.venv\Scripts\python.exe` explicitly.

## Planned File Map

| Path | Responsibility |
| --- | --- |
| `pyproject.toml` | Package metadata, CLI entry point, `openai` dependency, pytest extra/configuration |
| `.gitignore` | Local environments, caches, credentials, and `.coding-agent/` logs |
| `src/coding_agent/cli.py` | CLI parsing, configuration errors, exit-code mapping |
| `src/coding_agent/config.py` | Immutable runtime configuration and environment loading |
| `src/coding_agent/messages.py` | Provider-neutral messages, tool calls, results, serialization |
| `src/coding_agent/model.py` | Model protocol, request/response types, fake client |
| `src/coding_agent/state.py` | Explicit run state, counters, mutation and verification state |
| `src/coding_agent/agent.py` | Synchronous agent loop and state transitions |
| `src/coding_agent/context.py` | Context budget, semantic compaction, deterministic fallback |
| `src/coding_agent/termination.py` | Hard budgets, repetition fingerprints, termination decisions |
| `src/coding_agent/verification.py` | Freshness and final success gate |
| `src/coding_agent/openai_client.py` | OpenAI Responses API adapter and error classification |
| `src/coding_agent/safety.py` | Path guard, command parsing, allowlist and denial codes |
| `src/coding_agent/tools/base.py` | Tool protocol, schemas, execution context |
| `src/coding_agent/tools/registry.py` | Validate-authorize-execute dispatch pipeline |
| `src/coding_agent/tools/filesystem.py` | Directory, read, replace, and create tools |
| `src/coding_agent/tools/shell.py` | Bounded Windows subprocess execution |
| `src/coding_agent/logging.py` | Redaction and append-only JSONL event logging |
| `src/coding_agent/report.py` | Evidence-based terminal report |
| `tests/` | Unit, component, integration, and security tests mirroring production modules |
| `examples/broken_pytest_project/` | Deterministic demonstration target with an intentional failing test |

---

### Task 1: Project Skeleton and Minimal CLI

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/coding_agent/__init__.py`
- Create: `src/coding_agent/__main__.py`
- Create: `src/coding_agent/cli.py`
- Create: `src/coding_agent/config.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: environment mapping and CLI argument sequence.
- Produces: `RunConfig`, `ConfigError`, `parse_config(argv, environ) -> RunConfig`, and `main(argv=None, environ=None) -> int`.

- [ ] **Step 1: Write failing configuration tests**

```python
def test_parse_config_normalizes_workspace(tmp_path):
    config = parse_config(
        ["fix failing tests", "--workspace", str(tmp_path), "--verify", "pytest -q"],
        {"OPENAI_MODEL": "test-model", "OPENAI_API_KEY": "secret"},
    )
    assert config.task == "fix failing tests"
    assert config.workspace == tmp_path.resolve()
    assert config.verify_command == "pytest -q"
    assert repr(config).find("secret") == -1

def test_parse_config_rejects_missing_model(tmp_path):
    with pytest.raises(ConfigError, match="model"):
        parse_config(["task", "--workspace", str(tmp_path)], {"OPENAI_API_KEY": "secret"})

def test_main_returns_two_for_empty_verify(tmp_path, capsys):
    code = main(["task", "--workspace", str(tmp_path), "--verify", ""], {"OPENAI_MODEL": "m"})
    assert code == 2
    assert "configuration" in capsys.readouterr().err.lower()
```

- [ ] **Step 2: Run the focused tests and observe the expected import failure**

Run: `python -m pytest tests/test_cli.py -v`

Expected: FAIL because `coding_agent.cli`, `RunConfig`, and `parse_config` do not exist.

- [ ] **Step 3: Create package metadata and immutable configuration types**

```python
@dataclass(frozen=True)
class RunConfig:
    task: str
    workspace: Path
    model: str
    api_key: str = field(repr=False)
    verify_command: str | None = None
    max_model_calls: int = 12
    max_tool_calls: int = 40
    max_runtime_seconds: int = 600
    command_timeout_seconds: int = 60
    command_output_limit_bytes: int = 65_536


class ConfigError(ValueError):
    pass
```

Set `requires-python = ">=3.11"`, declare `openai` as the sole runtime dependency, declare `pytest` in a `test` optional dependency group, and expose `coding-agent = "coding_agent.cli:entrypoint"`. Do not install dependencies in this step unless the user has approved execution and dependency installation.

- [ ] **Step 4: Create the local virtual environment and install only approved dependencies**

Request network/dependency-install approval at execution time, then run:

```text
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[test]"
```

Expected: editable package installation succeeds with only `openai`, `pytest`, and their transitive dependencies. Do not run these commands while the plan is awaiting approval.

- [ ] **Step 5: Implement argument parsing and a non-success placeholder runner**

`parse_config` must prefer `--model` over `OPENAI_MODEL`, reject missing task/model/key or invalid workspace, and reject an empty supplied `--verify`. Until Task 4 wires the runner, valid configuration prints `agent runner is not implemented` to stderr and returns `1`, never a false success.

```python
def parse_config(argv: Sequence[str], environ: Mapping[str, str]) -> RunConfig:
    namespace = build_parser().parse_args(list(argv))
    model = namespace.model or environ.get("OPENAI_MODEL", "")
    api_key = environ.get("OPENAI_API_KEY", "")
    workspace = Path(namespace.workspace).resolve(strict=True)
    if not namespace.task.strip() or not model or not api_key or not workspace.is_dir():
        raise ConfigError("task, model, API key, and workspace directory are required")
    if namespace.verify is not None and not namespace.verify.strip():
        raise ConfigError("verify command cannot be empty")
    return RunConfig(namespace.task, workspace, model, api_key, namespace.verify)
```

- [ ] **Step 6: Run Task 1 tests and the CLI help**

Run: `python -m pytest tests/test_cli.py -v`

Expected: PASS.

Run: `python -m coding_agent --help`

Expected: exit 0 with task, `--workspace`, `--verify`, and `--model` documented.

- [ ] **Step 7: Run repository hygiene checks**

Run: `git status --short` and verify only Task 1 files changed. Scan the diff for the test key literal and confirm it appears only as test data and is never presented as a real credential.

- [ ] **Step 8: Commit only if the user has explicitly authorized local commits**

```text
git add pyproject.toml .gitignore src/coding_agent tests/test_cli.py
git commit -m "chore: scaffold python package and minimal cli"
```

### Task 2: Provider-Neutral Message Data Structures

**Files:**
- Create: `src/coding_agent/messages.py`
- Test: `tests/test_messages.py`

**Interfaces:**
- Consumes: JSON-compatible tool arguments and local execution metadata.
- Produces: `ToolCall`, `ToolResult`, `ToolResultStatus`, `UserMessage`, `AssistantMessage`, `ToolMessage`, `SummaryMessage`, `message_to_dict()`.

- [ ] **Step 1: Write failing message and serialization tests**

```python
def test_tool_result_serializes_explicit_nulls():
    result = ToolResult(
        call_id="c1", tool_name="read_file", status=ToolResultStatus.OK,
        output="line", error=None, metadata=ToolMetadata(),
    )
    payload = message_to_dict(ToolMessage(result))
    assert payload["result"]["error"] is None
    assert payload["result"]["metadata"]["exit_code"] is None

def test_tool_call_rejects_empty_id():
    with pytest.raises(ValueError, match="call id"):
        ToolCall(id="", name="read_file", arguments={"path": "a.py"})
```

- [ ] **Step 2: Run the test and observe missing types**

Run: `python -m pytest tests/test_messages.py -v`

Expected: FAIL on imports from `coding_agent.messages`.

- [ ] **Step 3: Implement frozen data classes and enums**

```python
JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)

class ToolResultStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    REJECTED = "rejected"

@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: Mapping[str, JsonValue]

@dataclass(frozen=True)
class ToolMetadata:
    exit_code: int | None = None
    timed_out: bool = False
    truncated: bool = False
    duration_ms: int = 0
    changed_paths: tuple[str, ...] = ()

@dataclass(frozen=True)
class ToolResult:
    call_id: str
    tool_name: str
    status: ToolResultStatus
    output: str
    error: str | None
    metadata: ToolMetadata

Message: TypeAlias = UserMessage | AssistantMessage | ToolMessage | SummaryMessage
```

Define the four message variants as frozen data classes and serialize recursively into plain dictionaries without importing `openai`.

- [ ] **Step 4: Add validation edge cases**

Test and implement rejection of empty tool names, non-object arguments, negative durations, duplicate assistant call IDs, and tool messages whose result has an empty `call_id`.

- [ ] **Step 5: Run focused and cumulative tests**

Run: `python -m pytest tests/test_messages.py tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 6: Commit only with explicit authorization**

```text
git add src/coding_agent/messages.py tests/test_messages.py
git commit -m "feat: define provider-neutral agent messages"
```

### Task 3: ModelClient Protocol and FakeModelClient

**Files:**
- Create: `src/coding_agent/model.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Consumes: message tuples and JSON-schema tool definitions.
- Produces: `ModelPurpose`, `ModelRequest`, `ModelUsage`, `ModelResponse`, `ModelClient`, `FakeModelClient`, `TransientModelError`, `FatalModelError`.

- [ ] **Step 1: Write failing protocol and fake-client tests**

```python
def test_fake_model_returns_script_and_records_request():
    response = ModelResponse(text="done", tool_calls=())
    fake = FakeModelClient([response])
    request = ModelRequest(instructions="i", messages=(), tools=(), purpose=ModelPurpose.AGENT)
    assert fake.complete(request) == response
    assert fake.requests == [request]

def test_fake_model_raises_when_script_is_exhausted():
    fake = FakeModelClient([])
    with pytest.raises(AssertionError, match="exhausted"):
        fake.complete(ModelRequest(instructions="i", messages=(), tools=(), purpose=ModelPurpose.AGENT))
```

- [ ] **Step 2: Run the test and observe missing model interfaces**

Run: `python -m pytest tests/test_model.py -v`

Expected: FAIL on imports.

- [ ] **Step 3: Implement exact request and response contracts**

```python
@dataclass(frozen=True)
class ModelRequest:
    instructions: str
    messages: tuple[Message, ...]
    tools: tuple[Mapping[str, JsonValue], ...]
    purpose: ModelPurpose
    max_output_tokens: int = 4096

@dataclass(frozen=True)
class ModelResponse:
    text: str | None
    tool_calls: tuple[ToolCall, ...]
    usage: ModelUsage | None = None
    provider_response_id: str | None = None
    continuation_items: tuple[object, ...] = field(default=(), repr=False)

class ModelClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...
```

Opaque continuation items must be excluded from equality-sensitive log serialization and repr output.

- [ ] **Step 4: Implement scripted responses and scripted exceptions**

Allow the fake script to contain `ModelResponse` or `Exception`; each call pops exactly one item and records the request first. This supports retry and error-path tests without network access.

```python
class FakeModelClient:
    def __init__(self, script: Sequence[ModelResponse | Exception]):
        self._script = deque(script)
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self._script:
            raise AssertionError("fake model script exhausted")
        item = self._script.popleft()
        if isinstance(item, Exception):
            raise item
        return item
```

- [ ] **Step 5: Run focused and cumulative tests**

Run: `python -m pytest tests/test_model.py tests/test_messages.py -v`

Expected: PASS.

- [ ] **Step 6: Commit only with explicit authorization**

```text
git add src/coding_agent/model.py tests/test_model.py
git commit -m "feat: add model client protocol and fake client"
```

### Task 4: Minimal Explicit Agent Loop

**Files:**
- Create: `src/coding_agent/state.py`
- Create: `src/coding_agent/agent.py`
- Create: `src/coding_agent/tools/base.py`
- Create: `src/coding_agent/tools/registry.py`
- Modify: `src/coding_agent/cli.py`
- Test: `tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `RunConfig`, `ModelClient`, and registered `Tool` implementations.
- Produces: `RunStatus`, `AgentState`, `RunOutcome`, `ExecutionContext`, `Tool`, `ToolRegistry`, `validate_arguments()`, result helpers, and `AgentRunner.run(task) -> RunOutcome`.

- [ ] **Step 1: Write failing two-turn loop tests**

```python
def test_loop_executes_tool_then_returns_completion_candidate(tmp_path):
    fake = FakeModelClient([
        ModelResponse(text=None, tool_calls=(ToolCall("c1", "echo", {"value": "x"}),)),
        ModelResponse(text="finished", tool_calls=()),
    ])
    registry = ToolRegistry([EchoTool()])
    outcome = AgentRunner(fake, registry, temporary_max_model_calls=4).run("task", tmp_path)
    assert outcome.status is RunStatus.COMPLETION_CANDIDATE
    assert fake.requests[1].messages[-1].result.call_id == "c1"
```

- [ ] **Step 2: Run the focused test and observe missing loop types**

Run: `python -m pytest tests/test_agent_loop.py::test_loop_executes_tool_then_returns_completion_candidate -v`

Expected: FAIL on imports.

- [ ] **Step 3: Implement the minimal state and tool contracts**

```python
class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETION_CANDIDATE = "completion_candidate"
    SUCCESS = "success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"

class Tool(Protocol):
    name: str
    schema: Mapping[str, JsonValue]
    def execute(self, call: ToolCall, context: ExecutionContext) -> ToolResult: ...

@dataclass(frozen=True)
class ExecutionContext:
    workspace: Path
    command_timeout_seconds: int = 60
    command_output_limit_bytes: int = 65_536

@dataclass
class AgentState:
    original_task: str
    workspace: Path
    messages: list[Message]
    max_model_calls: int = 12
    max_tool_calls: int = 40
    max_runtime_seconds: int = 600
    model_attempts: int = 0
    tool_calls: int = 0
    mutation_index: int = 0
    modified_files: set[str] = field(default_factory=set)
    status: RunStatus = RunStatus.RUNNING

@dataclass(frozen=True)
class RunOutcome:
    status: RunStatus
    reason: str
    state: AgentState
```

`AgentState` initially owns original task, workspace, messages, model/tool counters, consecutive failure counters, modified files, mutation index, and completion text. Do not add final success logic in this task.

- [ ] **Step 4: Implement validate-dispatch-execute-observe without safety policy yet**

The registry rejects unknown tools, duplicate call IDs, and arguments that are not objects. It converts unexpected tool exceptions into `ToolResultStatus.ERROR` with a stable `tool_exception` code instead of letting them escape.

```python
def execute(self, call: ToolCall, context: ExecutionContext) -> ToolResult:
    tool = self._tools.get(call.name)
    if tool is None:
        return rejected_result(call, "unknown_tool")
    try:
        validate_arguments(tool.schema, call.arguments)
        return tool.execute(call, context)
    except ToolArgumentError as exc:
        return error_result(call, "invalid_arguments", str(exc))
    except Exception:
        return error_result(call, "tool_exception", "tool execution failed")
```

Implement `validate_arguments(schema, arguments)` locally for the schema subset used by this project: object, properties, required, `additionalProperties=false`, string, integer, boolean, null unions, enum, minimum, and maximum. `ok_result`, `error_result`, and `rejected_result` accept a `ToolCall` and always copy `call.id` and `call.name` into `ToolResult`.

- [ ] **Step 5: Add failure-path tests**

Cover unknown tool, duplicate call ID, malformed arguments, tool exception, multiple sequential calls, and temporary model-call limit. Assert that completion text never maps directly to `SUCCESS`.

- [ ] **Step 6: Wire CLI to the runner without claiming success**

Inject dependencies through a `build_runner(config)` seam. Until Task 11 adds `VerificationGate`, map `COMPLETION_CANDIDATE` to exit `1` with an explicit `verification gate not implemented` message.

- [ ] **Step 7: Run cumulative tests**

Run: `python -m pytest tests/test_agent_loop.py tests/test_model.py tests/test_messages.py tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 8: Request core-module review and commit only with authorization**

Review the loop for framework leakage, hidden termination, and provider coupling. If authorized:

```text
git add src/coding_agent tests/test_agent_loop.py tests/test_cli.py
git commit -m "feat: implement minimal explicit agent loop"
```

### Task 5: Directory Listing and File Reading Tools

**Files:**
- Create: `src/coding_agent/tools/filesystem.py`
- Modify: `src/coding_agent/tools/registry.py`
- Test: `tests/tools/test_read_tools.py`

**Interfaces:**
- Consumes: `ExecutionContext.workspace` and validated tool arguments.
- Produces: `ListDirectoryTool`, `ReadFileTool`, stable text outputs with line/count metadata.

- [ ] **Step 1: Write failing directory and file-read tests**

```python
def test_list_directory_is_sorted_and_limited(tmp_path):
    (tmp_path / "b.py").write_text("b", encoding="utf-8")
    (tmp_path / "a.py").write_text("a", encoding="utf-8")
    result = ListDirectoryTool().execute(
        ToolCall("c1", "list_directory", {"path": ".", "recursive": False, "max_depth": 1, "max_entries": 1}),
        ExecutionContext(tmp_path),
    )
    assert result.status is ToolResultStatus.OK
    assert result.output.splitlines() == ["a.py"]
    assert result.metadata.truncated is True

def test_read_file_returns_numbered_slice(tmp_path):
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    result = ReadFileTool().execute(
        ToolCall("c2", "read_file", {"path": "a.py", "start_line": 2, "end_line": 3}), ExecutionContext(tmp_path)
    )
    assert result.output == "2: two\n3: three"
```

- [ ] **Step 2: Run focused tests and observe missing tools**

Run: `python -m pytest tests/tools/test_read_tools.py -v`

Expected: FAIL on imports.

- [ ] **Step 3: Implement strict tool schemas and bounded behavior**

Declare every property required and set `additionalProperties: false`. Enforce `max_depth` from 1 through 3, `max_entries` from 1 through 500, `start_line >= 1`, nullable `end_line`, stable case-insensitive Windows sorting, and a 262,144-byte read ceiling.

```python
class ReadFileTool:
    name = "read_file"
    schema = strict_read_file_schema()

    def execute(self, call: ToolCall, context: ExecutionContext) -> ToolResult:
        path = context.workspace / require_relative_path(call.arguments["path"])
        data = path.read_bytes()
        if len(data) > 262_144 or b"\x00" in data:
            return error_result(call, "read_limit_or_binary", "file is too large or binary")
        text = data.decode("utf-8")
        return numbered_slice_result(call, text, call.arguments["start_line"], call.arguments["end_line"])
```

- [ ] **Step 4: Add binary, encoding, and boundary tests**

Test empty directory, nested depth, nonexistent path, start after EOF, end before start, invalid UTF-8, embedded NUL, and a file exceeding 256 KiB. Return stable error codes such as `not_found`, `not_text`, `invalid_range`, and `read_limit_exceeded`.

- [ ] **Step 5: Register both tools and run cumulative tool tests**

Run: `python -m pytest tests/tools/test_read_tools.py tests/test_agent_loop.py -v`

Expected: PASS with real tools usable through `ToolRegistry`.

- [ ] **Step 6: Commit only with explicit authorization**

```text
git add src/coding_agent/tools tests/tools/test_read_tools.py
git commit -m "feat: add directory listing and file reading tools"
```

### Task 6: Deterministic File Modification Tools

**Files:**
- Modify: `src/coding_agent/tools/filesystem.py`
- Modify: `src/coding_agent/state.py`
- Modify: `src/coding_agent/agent.py`
- Test: `tests/tools/test_write_tools.py`

**Interfaces:**
- Consumes: workspace-relative UTF-8 paths and current `AgentState`.
- Produces: `ReplaceTextTool`, `WriteFileTool`, changed-path metadata, and mutation-driven verification invalidation.

- [ ] **Step 1: Write failing exact-replacement tests**

```python
def test_replace_text_changes_only_expected_matches(tmp_path):
    path = tmp_path / "a.py"
    path.write_text("x = 1\nx = 1\n", encoding="utf-8")
    result = ReplaceTextTool().execute(
        ToolCall("c1", "replace_text", {"path": "a.py", "old_text": "x = 1", "new_text": "x = 2", "expected_count": 2}),
        ExecutionContext(tmp_path),
    )
    assert result.metadata.changed_paths == ("a.py",)
    assert path.read_text(encoding="utf-8") == "x = 2\nx = 2\n"

def test_replace_mismatch_is_zero_mutation(tmp_path):
    path = tmp_path / "a.py"
    path.write_text("x = 1", encoding="utf-8")
    before = path.read_bytes()
    result = ReplaceTextTool().execute(
        ToolCall("c1", "replace_text", {"path": "a.py", "old_text": "x = 1", "new_text": "x = 2", "expected_count": 2}),
        ExecutionContext(tmp_path),
    )
    assert result.status is ToolResultStatus.ERROR
    assert path.read_bytes() == before
```

- [ ] **Step 2: Run focused tests and observe missing tools**

Run: `python -m pytest tests/tools/test_write_tools.py -v`

Expected: FAIL on imports.

- [ ] **Step 3: Implement replace and create-only write**

Read the source completely before mutation, compare actual count to positive `expected_count`, render the new content in memory, enforce the 524,288-byte ceiling, then write only after every check succeeds. `WriteFileTool` uses exclusive creation and returns `already_exists` instead of overwriting.

```python
actual_count = source.count(old_text)
if not old_text or expected_count < 1 or actual_count != expected_count:
    return error_result(call, "replace_count_mismatch", "actual count differs from expected_count")
rendered = source.replace(old_text, new_text)
encoded = rendered.encode("utf-8")
if len(encoded) > 524_288:
    return error_result(call, "write_limit_exceeded", "rendered file exceeds 512 KiB")
path.write_bytes(encoded)
return ok_result(call, changed_paths=(relative_path,))
```

- [ ] **Step 4: Add mutation-state behavior**

```python
def record_tool_result(state: AgentState, result: ToolResult) -> None:
    if result.status is ToolResultStatus.OK and result.metadata.changed_paths:
        state.mutation_index += 1
        state.modified_files.update(result.metadata.changed_paths)
        state.verification_status = VerificationStatus.STALE
```

Define `VerificationStatus` now as `NOT_RUN`, `STALE`, `PASSED`, and `FAILED`; Task 11 will enforce it.

- [ ] **Step 5: Test edge cases and state invariants**

Cover zero/negative expected count, empty old text, encoding failure, write size limit, create collision, parent missing, and a tool error that must not increase `mutation_index`.

- [ ] **Step 6: Run focused and cumulative tests**

Run: `python -m pytest tests/tools/test_write_tools.py tests/tools/test_read_tools.py tests/test_agent_loop.py -v`

Expected: PASS.

- [ ] **Step 7: Commit only with explicit authorization**

```text
git add src/coding_agent tests/tools/test_write_tools.py
git commit -m "feat: add deterministic file modification tools"
```

### Task 7: Bounded Windows Command Execution

**Files:**
- Create: `src/coding_agent/tools/shell.py`
- Modify: `src/coding_agent/tools/registry.py`
- Modify: `src/coding_agent/config.py`
- Test: `tests/tools/test_shell_tool.py`

**Interfaces:**
- Consumes: command string, `inspect|test|verification` purpose, workspace, timeout/output limits.
- Produces: `RunCommandTool`, command-populated `ToolResult`, Windows argument parsing and process-tree termination helpers.

- [ ] **Step 1: Write failing success, failure, and timeout tests**

```python
def test_run_command_captures_exit_code_and_streams(tmp_path):
    result = RunCommandTool().execute(
        ToolCall("c1", "run_command", {"command": 'python -c "import sys; print(\'out\'); print(\'err\', file=sys.stderr); sys.exit(3)"',
         "purpose": "test"}),
        ExecutionContext(tmp_path, command_timeout_seconds=5),
    )
    assert result.metadata.exit_code == 3
    assert "out" in result.output
    assert "err" in result.error

def test_run_command_times_out_and_marks_result(tmp_path):
    result = RunCommandTool().execute(
        ToolCall("c1", "run_command", {"command": 'python -c "import time; time.sleep(10)"', "purpose": "test"}),
        ExecutionContext(tmp_path, command_timeout_seconds=1),
    )
    assert result.metadata.timed_out is True
```

- [ ] **Step 2: Run focused tests and observe missing command tool**

Run: `python -m pytest tests/tools/test_shell_tool.py -v`

Expected: FAIL on imports.

- [ ] **Step 3: Implement Windows argument parsing and `shell=False` execution**

Use the Windows `CommandLineToArgvW` API through `ctypes` so a user-facing string such as `pytest -q` becomes an argv list without starting `cmd.exe`. Launch with `subprocess.Popen(argv, cwd=workspace, shell=False, stdout=PIPE, stderr=PIPE, text=False, creationflags=CREATE_NEW_PROCESS_GROUP)`.

```python
argv = split_windows_command_line(command)
process = subprocess.Popen(
    argv,
    cwd=context.workspace,
    shell=False,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
)
```

- [ ] **Step 4: Implement timeout, process-tree cleanup, and output caps**

On timeout, terminate the process and descendants, wait for cleanup, and return `timed_out=True`. Retain at most 65,536 bytes per stream, decode with UTF-8 replacement for reporting, and set `truncated=True` if either stream exceeded its cap.

```python
try:
    stdout, stderr = process.communicate(timeout=context.command_timeout_seconds)
    timed_out = False
except subprocess.TimeoutExpired:
    terminate_windows_process_tree(process.pid)
    stdout, stderr = process.communicate()
    timed_out = True
return command_tool_result(process.returncode, stdout, stderr, timed_out, context.command_output_limit_bytes)
```

- [ ] **Step 5: Add output, cwd, and purpose edge tests**

Test a 70 KiB stdout stream, a 70 KiB stderr stream, paths containing spaces, fixed workspace cwd, invalid purpose, empty command, invalid quoting, and timeout not leaving a child process alive.

- [ ] **Step 6: Run shell and cumulative tool tests**

Run: `python -m pytest tests/tools/test_shell_tool.py tests/tools -v`

Expected: PASS.

- [ ] **Step 7: Commit only with explicit authorization**

```text
git add src/coding_agent/tools/shell.py src/coding_agent/config.py tests/tools/test_shell_tool.py
git commit -m "feat: add bounded windows command execution tool"
```

### Task 8: Workspace and Command Safety Policies

**Files:**
- Create: `src/coding_agent/safety.py`
- Modify: `src/coding_agent/tools/base.py`
- Modify: `src/coding_agent/tools/registry.py`
- Modify: `src/coding_agent/tools/filesystem.py`
- Modify: `src/coding_agent/tools/shell.py`
- Modify: `src/coding_agent/config.py`
- Test: `tests/test_path_safety.py`
- Test: `tests/test_command_safety.py`

**Interfaces:**
- Consumes: untrusted model paths/commands and normalized workspace.
- Produces: `PathGuard.resolve_for_read()`, `PathGuard.resolve_for_write()`, `CommandPolicy.authorize()`, `SafetyDecision`, stable rejection codes.

- [ ] **Step 1: Write failing path-escape tests**

```python
@pytest.mark.parametrize("candidate", [r"..\outside.py", r"C:\Windows\win.ini", "", "a\x00b"])
def test_path_guard_rejects_non_workspace_paths(tmp_path, candidate):
    decision = PathGuard(tmp_path).resolve_for_read(candidate)
    assert decision.allowed is False

def test_path_guard_rejects_symlink_escape(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Windows link creation is unavailable")
    assert PathGuard(tmp_path).resolve_for_read("link.txt").allowed is False
```

- [ ] **Step 2: Write failing command-policy tests**

```python
@pytest.mark.parametrize("command", [
    "cmd.exe /c dir", "powershell Get-ChildItem", "pytest -q & whoami",
    "pip install requests", "git clean -fd", "curl https://example.com",
])
def test_command_policy_rejects_prohibited_commands(tmp_path, command):
    assert CommandPolicy(tmp_path).authorize(command).allowed is False

@pytest.mark.parametrize("command", ["pytest -q", "python -m pytest -q", "git diff", "git status"])
def test_command_policy_allows_documented_commands(tmp_path, command):
    assert CommandPolicy(tmp_path).authorize(command).allowed is True
```

- [ ] **Step 3: Run safety tests and observe missing policies**

Run: `python -m pytest tests/test_path_safety.py tests/test_command_safety.py -v`

Expected: FAIL on imports.

- [ ] **Step 4: Implement PathGuard with real-path containment and reparse checks**

Reject absolute paths, `..`, NUL, `.git`, and `.coding-agent`. Resolve the workspace once; for reads, resolve the target strictly; for new writes, resolve the nearest existing parent. Verify `os.path.commonpath([workspace, resolved]) == workspace` and reject any existing component marked as a symlink or Windows reparse point.

```python
@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    code: str
    resolved_path: Path | None = None
    argv: tuple[str, ...] = ()

def _contained(workspace: Path, candidate: Path) -> bool:
    return os.path.commonpath((str(workspace), str(candidate))) == str(workspace)
```

- [ ] **Step 5: Implement exact command allowlist and subcommand rules**

Allow `pytest`, `python -m pytest`, `python -m unittest`, `ruff`, `mypy`, `python <workspace-relative.py>`, and Git subcommands `status`, `diff`, `log`, `show`, `ls-files`. Reject shell programs, control operators, package installers, network programs, process/system tools, write-capable Git subcommands, parent traversal, and suspicious absolute arguments outside the workspace.

```python
ALLOWED_GIT_SUBCOMMANDS = frozenset({"status", "diff", "log", "show", "ls-files"})
PROHIBITED_PROGRAMS = frozenset({"cmd", "cmd.exe", "powershell", "pwsh", "bash", "wsl", "curl", "wget", "pip"})

def authorize(self, command: str) -> SafetyDecision:
    if any(operator in command for operator in ("&", "|", ">", "<")):
        return SafetyDecision(False, "command_control_operator")
    argv = tuple(split_windows_command_line(command))
    return self._authorize_argv(argv)
```

- [ ] **Step 6: Put authorization before execution everywhere**

`ToolRegistry` validates schema, then calls the relevant policy, and only then calls the tool. A denied call returns `ToolResultStatus.REJECTED` with a stable `path_*` or `command_*` code and no side effects. Apply the same command policy to CLI `--verify` during configuration.

```python
validate_arguments(tool.schema, call.arguments)
decision = tool.authorize(call, context)
if not decision.allowed:
    return rejected_result(call, decision.code)
return tool.execute_authorized(call, context, decision)
```

- [ ] **Step 7: Add junction, casing, and no-side-effect tests**

Test Windows junction/reparse escape where supported, case-insensitive drive paths, reserved directories, new file beneath a linked parent, rejected commands never invoking `Popen`, and a rejected `--verify` returning exit 2.

- [ ] **Step 8: Run all current tests and request safety review**

Run: `python -m pytest tests/test_path_safety.py tests/test_command_safety.py tests/tools tests/test_agent_loop.py tests/test_cli.py -v`

Expected: PASS. Review that no model instruction can bypass either policy.

- [ ] **Step 9: Commit only with explicit authorization**

```text
git add src/coding_agent tests/test_path_safety.py tests/test_command_safety.py
git commit -m "feat: enforce workspace and command safety policies"
```

### Task 9: OpenAI Responses Model Client

**Files:**
- Create: `src/coding_agent/openai_client.py`
- Modify: `src/coding_agent/config.py`
- Modify: `src/coding_agent/agent.py`
- Modify: `src/coding_agent/state.py`
- Test: `tests/test_openai_client.py`
- Test: `tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `ModelRequest`, `RunConfig.model`, `RunConfig.api_key`, and provider-neutral tool schemas.
- Produces: single-attempt `OpenAIResponsesClient.complete()`, request mapping, response parsing, `function_call_output` continuation, classified model errors, and the runner's shared `_complete_with_retry()` path.

- [ ] **Step 1: Write failing request-mapping tests with a fake SDK client**

```python
def test_openai_client_uses_stateless_responses_api():
    sdk = FakeSDK(response=FakeResponse(id="r1", output=[], usage=None))
    client = OpenAIResponsesClient(sdk=sdk, model="test-model")
    client.complete(ModelRequest(instructions="i", messages=(), tools=(STRICT_TOOL,), purpose=ModelPurpose.AGENT))
    kwargs = sdk.responses.calls[0]
    assert kwargs["store"] is False
    assert "previous_response_id" not in kwargs
    assert kwargs["tools"][0]["strict"] is True
    assert kwargs["max_output_tokens"] == 4096
```

- [ ] **Step 2: Write failing response and continuation tests**

Create fake output items for assistant text, two function calls, usage, and continuation items. Assert parsed tool calls preserve response order and IDs. On the next request, assert a `ToolMessage` becomes a `function_call_output` with the matching `call_id`.

- [ ] **Step 3: Run the focused tests and observe missing adapter**

Run: `python -m pytest tests/test_openai_client.py -v`

Expected: FAIL on imports.

- [ ] **Step 4: Implement SDK isolation and strict request conversion**

Construct the official `OpenAI` client from the configured key inside the adapter factory. Convert internal messages, continuation items, and strict function definitions into Responses API inputs. Convert SDK responses immediately into `ModelResponse`; no SDK object may reach `agent.py`, logs, or tests outside this module.

```python
def complete(self, request: ModelRequest) -> ModelResponse:
    try:
        response = self._sdk.responses.create(
            model=self._model,
            instructions=request.instructions,
            input=to_response_input(request.messages),
            tools=list(request.tools),
            store=False,
            max_output_tokens=request.max_output_tokens,
        )
    except Exception as exc:
        raise classify_openai_error(exc) from None
    return parse_response(response)
```

- [ ] **Step 5: Implement provider error classification and runner-owned retry**

The adapter performs exactly one outbound SDK call and translates authentication, not-found model, and invalid-request errors to `FatalModelError`; it translates timeouts, 429, and 5xx to `TransientModelError`. Sanitize exception text before exposing it.

```python
def _complete_with_retry(self, state: AgentState, request: ModelRequest) -> ModelResponse:
    for retry_index in range(3):
        if state.model_attempts >= state.max_model_calls:
            raise ModelBudgetExhausted
        state.model_attempts += 1
        try:
            return self.model_client.complete(request)
        except TransientModelError:
            if retry_index == 2:
                raise
            self.sleep(0.25 * (2 ** retry_index))
```

Put this provider-neutral retry path on `AgentRunner`, inject the sleeper for tests, and use it for every Agent decision call. Task 10 passes the same bound callable into `ContextManager`, so summary calls and retries share the same counter. Fatal errors bypass retry.

- [ ] **Step 6: Test malformed and incomplete provider responses**

Cover unknown output item types, malformed JSON arguments, missing `call_id`, duplicate IDs, incomplete status, absent usage, and provider exception text containing the test key. Unknown non-action items may be preserved only as opaque in-memory continuation items; malformed function calls must not execute.

- [ ] **Step 7: Run adapter and protocol suites without network access**

Run: `python -m pytest tests/test_openai_client.py tests/test_model.py tests/test_agent_loop.py -v`

Expected: PASS with zero real HTTP requests.

- [ ] **Step 8: Request model-boundary review and commit only with authorization**

Verify the adapter uses custom functions only, `store=False`, and no hosted tools. If authorized:

```text
git add src/coding_agent/openai_client.py src/coding_agent/config.py src/coding_agent/agent.py src/coding_agent/state.py tests/test_openai_client.py tests/test_agent_loop.py
git commit -m "feat: integrate openai responses model client"
```

### Task 10: Context Management, Termination, and Repetition Detection

**Files:**
- Create: `src/coding_agent/context.py`
- Create: `src/coding_agent/termination.py`
- Modify: `src/coding_agent/state.py`
- Modify: `src/coding_agent/agent.py`
- Modify: `src/coding_agent/model.py`
- Test: `tests/test_context.py`
- Test: `tests/test_termination.py`

**Interfaces:**
- Consumes: active history, structured state facts, continuation items, counters, monotonic clock, and the runner's bound `_complete_with_retry(state, request)` callable.
- Produces: `ContextManager.prepare(state)`, `ContextSummary`, `TerminationPolicy.check()`, `ToolFingerprint`, and explicit termination reasons.

- [ ] **Step 1: Write failing compaction-trigger and turn-boundary tests**

```python
def test_context_compacts_over_item_limit_without_splitting_tool_pair(state):
    state.messages = build_history_with_complete_tool_turns(25)
    prepared = ContextManager(max_chars=60_000, max_items=24, keep_recent_turns=8).prepare(state)
    assert prepared.compacted is True
    assert has_orphan_tool_result(prepared.messages) is False
    assert count_complete_turns(prepared.messages) >= 8

def test_context_does_not_compact_at_exact_limits(state):
    state.messages = build_history(items=24, serialized_chars=60_000)
    assert ContextManager().needs_compaction(state) is False
```

- [ ] **Step 2: Write failing summary-validation and fallback tests**

Require all nine fields: `goal`, `established_facts`, `files_examined`, `changes_made`, `commands_and_results`, `unresolved_errors`, `open_issues`, `verification_state`, and `avoid_repeating`. Feed invalid JSON and missing fields, then assert the deterministic fallback preserves original task, modified files, mutation index, verification state, latest errors, and rejected-call fingerprints.

- [ ] **Step 3: Implement compaction selection and semantic-summary call**

Select the oldest complete prefix while retaining eight recent complete turns. Issue a `ModelRequest` with `purpose=COMPACTION`, no tools, and a prompt requiring the exact JSON object through the runner-supplied `_complete_with_retry` callable. Every attempt therefore counts in the shared 12-call budget. Merge locally authoritative facts after parsing, regardless of model content.

```python
@dataclass(frozen=True)
class ContextSummary:
    goal: str
    established_facts: tuple[str, ...]
    files_examined: tuple[str, ...]
    changes_made: tuple[str, ...]
    commands_and_results: tuple[str, ...]
    unresolved_errors: tuple[str, ...]
    open_issues: tuple[str, ...]
    verification_state: str
    avoid_repeating: tuple[str, ...]

@dataclass(frozen=True)
class PreparedContext:
    messages: tuple[Message, ...]
    continuation_items: tuple[object, ...]
    compacted: bool

def prepare(self, state: AgentState) -> PreparedContext:
    if not self.needs_compaction(state):
        return PreparedContext(tuple(state.messages), state.continuation_items, False)
    prefix, recent = split_complete_turns(state.messages, keep_recent=8)
    response = self._complete_model(state, build_summary_request(prefix))
    summary = merge_authoritative_facts(parse_summary(response.text), state)
    return PreparedContext((SummaryMessage(summary), *recent), (), True)
```

Extend `AgentState` in this task with `started_at`, `continuation_items`, `compaction_count`, `consecutive_failures`, `consecutive_safety_rejections`, `no_progress_repetitions`, and the last tool fingerprint/result digest. Initialize `started_at` from an injected monotonic clock at run start.

- [ ] **Step 4: Start a fresh stateless provider segment after compaction**

Return a `SummaryMessage` plus retained messages and clear old continuation items. Test that no old opaque provider object remains and that later tool-call/result pairs still serialize correctly.

```python
state.messages[:] = list(prepared.messages)
state.continuation_items = prepared.continuation_items
state.compaction_count += 1
```

- [ ] **Step 5: Write failing termination and fingerprint tests**

```python
def test_fingerprint_ignores_json_key_order():
    assert ToolFingerprint.from_call(ToolCall("1", "read_file", {"path": "a", "start": 1})) == \
           ToolFingerprint.from_call(ToolCall("2", "read_file", {"start": 1, "path": "a"}))

@pytest.mark.parametrize("field,limit", [
    ("model_attempts", 12), ("tool_calls", 40), ("consecutive_failures", 3),
    ("consecutive_safety_rejections", 3), ("no_progress_repetitions", 3),
])
def test_termination_fires_at_exact_limit(state, field, limit):
    setattr(state, field, limit)
    assert TerminationPolicy().check(state, now=state.started_at).should_stop is True
```

- [ ] **Step 6: Implement monotonic runtime and progress rules**

Runtime stops at 600 seconds. A different tool call, changed tool result, successful mutation, or new verification evidence resets the no-progress counter. A successful tool call resets consecutive tool failures; it does not erase safety rejection history unless the next authorized action demonstrates progress.

```python
@dataclass(frozen=True)
class TerminationDecision:
    should_stop: bool
    reason: str | None = None

def check(self, state: AgentState, now: float) -> TerminationDecision:
    if now - state.started_at >= state.max_runtime_seconds:
        return TerminationDecision(True, "runtime_limit")
    if state.model_attempts >= state.max_model_calls or state.tool_calls >= state.max_tool_calls:
        return TerminationDecision(True, "call_budget")
    if max(state.consecutive_failures, state.consecutive_safety_rejections, state.no_progress_repetitions) >= 3:
        return TerminationDecision(True, "stalled")
    return TerminationDecision(False)
```

- [ ] **Step 7: Replace Task 4 temporary limit with TerminationPolicy**

Check termination before model calls and after every model/tool result. Map reasons to `FAILED` without an extra provider call. Ensure a retry cannot start after the model budget is exhausted.

```python
decision = self.termination_policy.check(state, self.monotonic())
if decision.should_stop:
    state.status = RunStatus.FAILED
    return RunOutcome(state.status, decision.reason or "terminated", state)
```

- [ ] **Step 8: Run context, termination, and loop tests**

Run: `python -m pytest tests/test_context.py tests/test_termination.py tests/test_agent_loop.py -v`

Expected: PASS, including fallback compaction and every exact boundary.

- [ ] **Step 9: Commit only with explicit authorization**

```text
git add src/coding_agent/context.py src/coding_agent/termination.py src/coding_agent/state.py src/coding_agent/agent.py src/coding_agent/model.py tests/test_context.py tests/test_termination.py
git commit -m "feat: add context and explicit termination policies"
```

### Task 11: Post-Mutation Verification Gate

**Files:**
- Create: `src/coding_agent/verification.py`
- Modify: `src/coding_agent/state.py`
- Modify: `src/coding_agent/agent.py`
- Modify: `src/coding_agent/tools/shell.py`
- Modify: `src/coding_agent/cli.py`
- Test: `tests/test_verification.py`

**Interfaces:**
- Consumes: completion candidate, mutation index, command results, optional user verify command.
- Produces: `VerificationEvidence`, `VerificationSource`, `VerificationDecision`, `VerificationGate.evaluate()`.

- [ ] **Step 1: Write failing forced-verification tests**

```python
def test_forced_verify_failure_cannot_succeed(runner, tmp_path):
    outcome = runner(verify_command="pytest -q", verify_exit_codes=[1]).run("fix", tmp_path)
    assert outcome.status is not RunStatus.SUCCESS
    assert outcome.state.verification.status is VerificationStatus.FAILED

def test_forced_verify_pass_after_latest_mutation_succeeds(runner, tmp_path):
    outcome = runner(verify_command="pytest -q", verify_exit_codes=[0]).run("fix", tmp_path)
    assert outcome.status is RunStatus.SUCCESS
    assert outcome.state.verification.command == "pytest -q"
    assert outcome.state.verification.validation_index > outcome.state.last_mutation_event_index
```

- [ ] **Step 2: Write failing stale and agent-selected verification tests**

Test that a passing verification followed by a mutation becomes stale; `echo ok`, directory listing, and `git status` never qualify; `pytest -q`, `python -m pytest`, and `python -m unittest` may qualify when run with `purpose="verification"` and exit 0.

- [ ] **Step 3: Implement evidence and local gate types**

```python
@dataclass(frozen=True)
class VerificationEvidence:
    command: str
    source: VerificationSource
    exit_code: int
    event_index: int
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool

class VerificationGate:
    def evaluate(self, state: AgentState) -> VerificationDecision: ...
```

The gate accepts only exit 0, no timeout, a credible command, and an event index newer than the last mutation. A model completion statement is never evidence.

- [ ] **Step 4: Implement forced verification as a local completion transition**

When `--verify` exists, the runner invokes the exact configured command after each completion candidate. Failure appends a `ToolMessage`-equivalent verification observation and resumes if budget remains; pass transitions to `SUCCESS`. Do not let the model alter the configured command.

```python
def _handle_completion(self, state: AgentState) -> RunOutcome | None:
    if state.verify_command is not None:
        evidence = self._run_verification(state.verify_command, VerificationSource.USER, state)
        state.verification_history.append(evidence)
    decision = self.verification_gate.evaluate(state)
    if decision.success:
        return RunOutcome(RunStatus.SUCCESS, "verification_passed", state)
    state.messages.append(verification_observation(decision, state.verification_history[-1:]))
    return None
```

- [ ] **Step 5: Implement no-flag behavior**

Without `--verify`, a completion candidate lacking fresh credible evidence receives a local observation instructing the model to run a verification command. Inspection-only commands remain visible in logs but cannot satisfy the gate.

```python
def is_credible_agent_verification(command: str) -> bool:
    argv = tuple(split_windows_command_line(command))
    return argv[:1] in (("pytest",), ("ruff",), ("mypy",)) or argv[:3] in (
        ("python", "-m", "pytest"), ("python", "-m", "unittest")
    )
```

- [ ] **Step 6: Wire final CLI status codes**

Map `SUCCESS` to 0, `FAILED` to 1, configuration errors to 2, and `KeyboardInterrupt` to 130. Remove Task 4's temporary completion-candidate error path.

```python
EXIT_CODES = {
    RunStatus.SUCCESS: 0,
    RunStatus.FAILED: 1,
    RunStatus.INTERRUPTED: 130,
}
```

- [ ] **Step 7: Run verification, loop, and command tests**

Run: `python -m pytest tests/test_verification.py tests/test_agent_loop.py tests/tools/test_shell_tool.py -v`

Expected: PASS with explicit proof that nonzero forced verification cannot yield exit 0.

- [ ] **Step 8: Request core-module review and commit only with authorization**

```text
git add src/coding_agent/verification.py src/coding_agent/state.py src/coding_agent/agent.py src/coding_agent/tools/shell.py src/coding_agent/cli.py tests/test_verification.py
git commit -m "feat: enforce post-change verification gate"
```

### Task 12: Redacted JSONL Logs and Evidence Reports

**Files:**
- Create: `src/coding_agent/logging.py`
- Create: `src/coding_agent/report.py`
- Modify: `src/coding_agent/agent.py`
- Modify: `src/coding_agent/cli.py`
- Test: `tests/test_logging.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: normalized local run events and known API key.
- Produces: `EventLogger.emit()`, `Redactor.redact()`, `FinalReport.render()`, `.coding-agent/logs/<run_id>.jsonl`.

- [ ] **Step 1: Write failing redaction and event tests**

```python
def test_logger_redacts_known_key_and_bearer(tmp_path):
    logger = EventLogger(tmp_path, run_id="r1", redactor=Redactor(["sk-test-secret"]))
    logger.emit("tool_result", {"output": "sk-test-secret", "error": "Bearer abc.def"})
    text = (tmp_path / ".coding-agent/logs/r1.jsonl").read_text(encoding="utf-8")
    assert "sk-test-secret" not in text
    assert "Bearer abc.def" not in text
    assert "[REDACTED]" in text

def test_logger_never_serializes_continuation_items(tmp_path):
    response = ModelResponse(text=None, tool_calls=(), continuation_items=(SecretOpaqueObject(),))
    EventLogger(tmp_path, "r1", Redactor([])).emit_model_response(response)
    assert "SecretOpaqueObject" not in read_log(tmp_path)
```

- [ ] **Step 2: Run focused tests and observe missing logger**

Run: `python -m pytest tests/test_logging.py tests/test_report.py -v`

Expected: FAIL on imports.

- [ ] **Step 3: Implement append-only events and fail-closed writes**

Each line contains `timestamp`, `run_id`, `event_index`, `event_type`, and redacted `payload`. Open the file with UTF-8 append mode, flush after every event, and increment event index only after a successful write. If the directory or write fails, raise `AuditLogError`; the runner stops before another model or tool action.

```python
def emit(self, event_type: str, payload: Mapping[str, JsonValue]) -> int:
    event = {"timestamp": self._clock(), "run_id": self.run_id,
             "event_index": self._next_index, "event_type": event_type,
             "payload": self.redactor.redact_mapping(payload)}
    with self.path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()
    self._next_index += 1
    return event["event_index"]
```

- [ ] **Step 4: Emit every required event from the runner**

Emit run start, model attempt, model error, model result metadata, tool call, safety rejection, tool result, mutation, compaction start/result/fallback, verification, termination, interruption, and final outcome. Never emit environment mappings, auth headers, hidden reasoning, or continuation payloads.

```python
logger.emit("tool_call", serialize_tool_call(call))
result = registry.execute(call, context)
logger.emit("tool_result", serialize_tool_result(result))
apply_result_to_state(state, result)
```

- [ ] **Step 5: Implement evidence-only final report**

```text
Status: SUCCESS|FAILED|INTERRUPTED
Reason: <local termination reason>
Modified files: <sorted relative paths>
Verification source: user|agent|none
Verification command: <actual command or none>
Exit code: <actual integer or none>
Timed out: true|false
Output truncated: true|false
```

Use the same state/evidence objects already logged; never parse a model completion string into proof.

- [ ] **Step 6: Test log/report consistency and failure behavior**

Assert final report command and exit code match the final JSONL verification event, event indices are strictly increasing, protected paths cannot be read by tools, and a simulated disk-write failure stops before the next fake model response is consumed.

- [ ] **Step 7: Run logging, report, and relevant security tests**

Run: `python -m pytest tests/test_logging.py tests/test_report.py tests/test_verification.py tests/test_path_safety.py -v`

Expected: PASS.

- [ ] **Step 8: Commit only with explicit authorization**

```text
git add src/coding_agent/logging.py src/coding_agent/report.py src/coding_agent/agent.py src/coding_agent/cli.py tests/test_logging.py tests/test_report.py
git commit -m "feat: add redacted run logs and evidence reports"
```

### Task 13: End-to-End Repair Scenario and Demo Project

**Files:**
- Create: `examples/broken_pytest_project/calculator.py`
- Create: `examples/broken_pytest_project/test_calculator.py`
- Create: `tests/integration/test_agent_repair.py`
- Create: `tests/integration/test_agent_failures.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: assembled CLI/runner, FakeModelClient, real local tools, forced verification, logs.
- Produces: deterministic demonstration workspace and end-to-end acceptance evidence.

- [ ] **Step 1: Add an intentionally broken example excluded from repository test discovery**

```python
# examples/broken_pytest_project/calculator.py
def add(left: int, right: int) -> int:
    return left - right

# examples/broken_pytest_project/test_calculator.py
from calculator import add

def test_adds_two_numbers():
    assert add(2, 3) == 5
```

Configure pytest `testpaths = ["tests"]` so the intentionally broken example is not collected by the repository's own default suite.

- [ ] **Step 2: Write failing full-repair integration tests**

Copy the example into `tmp_path`, script FakeModelClient to list/read, replace subtraction with multiplication, return a completion candidate, observe forced `pytest -q` failure, replace multiplication with addition, and return a second completion candidate.

```python
def test_agent_repairs_after_first_forced_verification_failure(tmp_path):
    workspace = copy_demo_project(tmp_path)
    runner = build_scripted_repair_runner(verify_command="pytest -q")
    outcome = runner.run("Fix the failing test", workspace)
    assert outcome.status is RunStatus.SUCCESS
    assert (workspace / "calculator.py").read_text(encoding="utf-8").endswith("left + right\n")
    assert [e.exit_code for e in outcome.state.verification_history] == [1, 0]
```

- [ ] **Step 3: Run the test and observe failure at the first missing integration seam**

Run: `python -m pytest tests/integration/test_agent_repair.py -v`

Expected: FAIL until the assembled runner, tool factory, or verification history wiring is completed.

- [ ] **Step 4: Add the minimal composition root**

Implement one `build_runner(config, model_client=None, event_logger=None)` function that constructs policies, the five tools, context manager, termination policy, verification gate, and logger. Production uses `OpenAIResponsesClient`; tests pass FakeModelClient explicitly. Do not introduce a dependency-injection framework.

```python
def build_runner(config: RunConfig, model_client: ModelClient | None = None,
                 event_logger: EventLogger | None = None) -> AgentRunner:
    client = model_client or OpenAIResponsesClient.from_config(config)
    path_guard = PathGuard(config.workspace)
    command_policy = CommandPolicy(config.workspace)
    registry = ToolRegistry(build_default_tools(path_guard, command_policy))
    return AgentRunner.from_components(config, client, registry, event_logger)
```

- [ ] **Step 5: Add failure-path integration tests**

Cover forced verification that never reaches 0, stale success after a later mutation, three repeated identical calls, three safety refusals, model budget exhaustion, fallback context compaction, and an audit-log failure stopping before the next tool call.

- [ ] **Step 6: Assert logs and reports use the same evidence**

Parse the JSONL file and assert the last verification event has command `pytest -q`, exit code 0, and the same event index, source, timeout, and truncation values rendered by `FinalReport`.

- [ ] **Step 7: Run the complete offline suite**

Run: `python -m pytest -q`

Expected: PASS; the example's intentional failure is not collected directly, and the integration test copies it before running its nested pytest command.

- [ ] **Step 8: Run a fresh CLI demo with FakeModelClient composition**

Run the test-only demo entry seam against a fresh copied workspace and save the terminal command plus real exit code in the task report. Expected final status: `SUCCESS`, with verification history `[1, 0]` and no network access.

- [ ] **Step 9: Request core integration review and commit only with authorization**

```text
git add examples tests/integration pyproject.toml src/coding_agent
git commit -m "test: add end-to-end repair scenario and demo project"
```

### Task 14: README, Video, and Submission Validation

**Files:**
- Modify: `README.md`
- Create: `README.txt`
- Create: `scripts/check_submission.py`
- Create: `tests/test_submission_check.py`
- Create outside Git at release time: a ZIP whose basename exactly equals the real personal name supplied by the user and which contains only the real `README.txt` and real MP4 demonstration.

**Interfaces:**
- Consumes: user-supplied real public repository URL, real personal name, real MP4 path, test evidence.
- Produces: public documentation, concise submission README, validated two-file ZIP, recorded manual video-duration evidence.

- [ ] **Step 1: Write failing submission-validator tests**

```python
def test_validate_readme_rejects_over_1000_characters(tmp_path):
    readme = tmp_path / "README.txt"
    readme.write_text("字" * 1001, encoding="utf-8")
    errors = validate_readme(readme, repository_url="https://github.com/example/project")
    assert "1000" in " ".join(errors)

def test_zip_contains_only_readme_and_video(tmp_path):
    archive = build_submission_zip(
        name="Student Name",
        readme=write_readme(tmp_path),
        video=write_fake_mp4(tmp_path, size=1024),
        output_dir=tmp_path,
    )
    with ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == ["README.txt", "demo.mp4"]
```

- [ ] **Step 2: Run validator tests and observe missing script**

Run: `python -m pytest tests/test_submission_check.py -v`

Expected: FAIL because `scripts.check_submission` does not exist.

- [ ] **Step 3: Implement conservative README and archive validation**

Count all Unicode characters after normalizing newlines; this is stricter and easier to defend than counting only CJK code points. Require at most 1000 characters, the exact user-supplied repository URL, a run command, and feature descriptions for verification and context compaction. Reject credential-like patterns. Require `.mp4`, size at most 200,000,000 bytes, and an archive named from the exact user-supplied personal name with only `README.txt` and the video basename.

```python
def validate_readme(path: Path, repository_url: str) -> list[str]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    errors = []
    if len(text) > 1000: errors.append("README.txt exceeds 1000 characters")
    if repository_url not in text: errors.append("repository URL is missing")
    if SECRET_PATTERN.search(text): errors.append("credential-like text detected")
    return errors

def build_submission_zip(name: str, readme: Path, video: Path, output_dir: Path) -> Path:
    if video.suffix.lower() != ".mp4" or video.stat().st_size > 200_000_000:
        raise SubmissionError("video must be MP4 and at most 200 MB")
    target = output_dir / f"{name}.zip"
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        archive.write(readme, "README.txt")
        archive.write(video, video.name)
    return target
```

- [ ] **Step 4: Write the full repository README**

Document prerequisites, environment variables, installation, one-shot CLI examples, the five tools, architecture, validation gate, context compaction, safety boundaries, limitations, offline test command, optional live smoke procedure, and evidence-report interpretation. State explicitly that the project is not an OS sandbox and the workspace must be trusted.

- [ ] **Step 5: Write the concise `README.txt` from real release inputs**

At execution time, require the user to supply the actual public repository URL before writing this file. Include only the repository URL, exact run steps, verification/context features, Windows scope, and credential note. Run the validator and report the actual character count.

- [ ] **Step 6: Record and validate the two-minute video**

Use this fixed timeline:

```text
00:00-00:10  Show the failing pytest project and task command.
00:10-00:25  Start coding-agent with --verify "pytest -q".
00:25-01:15  Show read/edit, first verification failure, and repair iteration.
01:15-01:35  Show final pytest pass, exit code, modified files, and JSONL evidence.
01:35-01:55  Explain explicit loop, local safety gate, and context compaction.
01:55-02:00  Show public repository URL and finish.
```

Use Windows file properties or the video editor's exported metadata to record actual duration at or below 120 seconds. Run the script for MP4 extension and byte-size validation. Review every frame containing terminals or configuration for secret exposure.

- [ ] **Step 7: Run full release verification**

Run: `python -m pytest -q`

Expected: PASS.

Run: `python -m compileall -q src tests scripts`

Expected: exit 0 with no output.

Run the submission validator with the real name, URL, README, and MP4. Expected: exit 0, README count at most 1000, MP4 at most 200 MB, and ZIP membership exactly two files.

- [ ] **Step 8: Scan source, docs, logs, history, and media for secrets**

Use deterministic text scans for known key value and common `sk-`/Bearer patterns across tracked files and `.coding-agent/logs`. Manually review the video and screenshots because binary media is not covered by text scans. If a real key was ever exposed, revoke it before proceeding.

- [ ] **Step 9: Review Git and deadline rules without pushing**

Run `git status --short`, `git log --oneline --decorate`, and `git remote -v`. Confirm the public repository is new for this assignment, commit history is intact, and the date is before 2026-09-02 24:00 Asia/Shanghai. Do not push until the user inspects the final state and explicitly authorizes the push.

- [ ] **Step 10: Commit only with explicit authorization**

```text
git add README.md README.txt scripts/check_submission.py tests/test_submission_check.py
git commit -m "docs: finalize readme demo and submission checklist"
```

Do not add the MP4 or submission ZIP to Git unless the user explicitly changes that policy.

## Final Verification Gate

Before claiming the project complete, run and read the full output of all applicable commands from Task 14. Report exact commands, exit codes, pass/fail counts, skipped tests, the real validator output, and any manual checks separately. Do not infer a live OpenAI result from fake-client tests.

The optional real OpenAI smoke test requires explicit user authorization for network access and a locally supplied `OPENAI_API_KEY`. Record its model name, command, exit code, and redacted result separately; it is not part of the default offline suite.

## Plan Approval Gate

This document is a proposal derived from the approved design baseline. Do not execute Task 1, create source files, install dependencies, create commits, or use an execution skill until the user has reviewed and explicitly approved this implementation plan. If any step conflicts with `DESIGN.md`, `TASKS.md`, or `AGENTS.md`, stop and return to brainstorming instead of modifying the architecture silently.

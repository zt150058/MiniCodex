# Task 7 Shell Command Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` and `superpowers:test-driven-development` to implement this plan task-by-task. Use `superpowers:verification-before-completion` before any completion claim. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Windows-first, fully offline `run_command` tool that executes a narrowly authorized Python command as an argument vector with fixed workspace cwd, bounded output, deterministic timeout metadata, and whole-process-tree cleanup.

**Architecture:** `RunCommandTool` lives in a focused `tools/shell.py` module. It validates the strict model-facing request, parses the Windows command line with a standard-library `ctypes` wrapper over `CommandLineToArgvW`, applies a temporary Task 7 Python-only authorization boundary, and launches with `subprocess.Popen(..., shell=False)`. Two bounded reader threads drain stdout and stderr concurrently while retaining only each stream's first 65,536 raw bytes; timeout cleanup uses Windows `taskkill.exe /PID <pid> /T /F` and records any cleanup failure without erasing the timeout fact.

**Tech Stack:** Python 3.11+, Windows API through `ctypes`, Python standard-library `subprocess`, `threading`, `codecs`, `json`, `time`, `pathlib`, and pytest. No new dependency is permitted.

**Spec:** `DESIGN.md` (tool execution, safety, and error-handling sections) and `TASKS.md` Task 7.

## Global Constraints

- Work only in `D:\code\coding_agent` on the current `main` worktree; do not create a branch or worktree.
- Do not use a subagent or parallel agent.
- Do not stage, commit, push, or contact a remote. The final source-control action is a user review and authorization gate.
- Do not change task status until execution begins. During execution only Task 6 may change from `进行中` to `已完成` and Task 7 from `未开始` to `进行中`.
- Keep `messages.py`, `model.py`, `state.py`, `agent.py`, `tools/registry.py`, `tools/filesystem.py`, `cli.py`, and `pyproject.toml unchanged.
- Do not connect the tool to the CLI or a real model and do not access the network or a real API key.
- Do not add PowerShell, `cmd.exe`, Bash, WSL, download tools, package managers, system-management programs, Git writes, or arbitrary executable access.
- Task 7 supplies a temporary Python-only functional boundary. Task 8 remains responsible for the complete deterministic `CommandPolicy` and path-security layer.
- Task 11 remains responsible for deciding whether command evidence satisfies a final verification gate.
- All tests create executable scripts and observable files only below pytest `tmp_path`.
- Every production behavior follows a separate RED then GREEN cycle. A RED that passes unexpectedly or fails for a test defect stops execution for review.

## Locked public contracts and semantics

### File map

- Create `src/coding_agent/tools/shell.py`: schema, validation, Windows parsing, temporary authorization, environment isolation, process execution, bounded capture, timeout cleanup, and stable JSON output.
- Create `tests/tools/test_shell_tool.py`: Windows parsing, contract, execution, output, timeout, process-tree, failure, and isolation tests.
- Modify `src/coding_agent/tools/base.py`: add only `ExecutionContext.command_timeout_seconds: float = 60.0` plus deterministic `0 < value <= 300` validation.
- Modify `TASKS.md` only when the user later authorizes execution: Task 6 `进行中` to `已完成`, Task 7 `未开始` to `进行中`.
- Create this plan at `docs/superpowers/plans/Task7.md`; do not modify it during execution unless the user first approves a plan correction.

`src/coding_agent/config.py` and `tests/test_cli.py` stay unchanged because Task 7 does not expose timeout through the CLI. The local execution value belongs to `ExecutionContext`; Task 11 or a later approved CLI design can wire user configuration separately.

### Model-facing interface

```python
class RunCommandTool:
    name = "run_command"
    schema: JSONObject

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution: ...
```

The exact argument keys are `{"command", "purpose"}`. `command` is a nonblank string without NUL. `purpose` is exactly `inspect`, `test`, or `verification`. Timeout is not model-facing. The schema has `strict: True`, both fields required, and `additionalProperties: False`; local code repeats every check.

Registration reuses the existing API without modifying `ToolRegistry`:

```python
registry = ToolRegistry([RunCommandTool()])
```

### Stable execution result

For every process that starts, `ToolExecution.output` is compact, sorted-key UTF-8 JSON with this exact shape:

```json
{"argv":["..."],"cleanup_error":null,"purpose":"test","stderr":"","stdout":""}
```

`argv` is the actual parsed argument vector, `cleanup_error` is either `null` or one stable nonsecret cleanup status string, and streams remain separate. `ToolResultMetadata` is reused unchanged:

- `exit_code`: the exact integer for a normally completed process, including nonzero values; `null` on timeout.
- `duration_ms`: nonnegative elapsed milliseconds from `time.monotonic_ns()`.
- `timed_out`: `true` only after the configured wait expires.
- `truncated`: `true` if stdout or stderr produced more than 65,536 raw bytes.
- `changed_paths`: always empty.

A nonzero exit is a successful tool execution (`ToolResult.status == "ok"` through the registry). It is not an argument rejection or tool exception. A nonexistent model-supplied executable is rejected by the temporary boundary before launch. If the already-authorized Python executable becomes unavailable between authorization and `Popen`, or process creation raises `PermissionError` or another `OSError`, it becomes a stable `CommandStartError` without the original exception text; the unchanged registry maps it to `status == "error"`. No traceback or environment mapping enters output.

### Windows parsing contract

`parse_windows_command_line(command: str) -> tuple[str, ...]` performs these exact steps:

1. Reject non-string, blank, NUL-containing, and unclosed-quote input with `ToolArgumentError`.
2. Detect unclosed quotes with a scanner that toggles quote state only when `"` is preceded by an even number of consecutive backslashes. This supplies the deterministic error that `CommandLineToArgvW` itself does not provide.
3. Call `shell32.CommandLineToArgvW` through `ctypes`; configure `argtypes` and `restype`, copy all `argc` strings, and release the native allocation with `kernel32.LocalFree` in `finally`.
4. Convert a null native result or empty argument vector into `ToolArgumentError("command could not be parsed by Windows")`.

This is intentionally Windows-native rather than `shlex` or `str.split()`. Tests construct representative inputs with `subprocess.list2cmdline` and verify spaces, empty arguments, backslashes, a spaced script path, and Unicode round-trip.

### Temporary Task 7 command boundary

Authorization occurs after parsing and before process creation. The only allowed forms are:

```text
<exact current sys.executable> -m pytest [arguments...]
<exact current sys.executable> -m unittest [arguments...]
<exact current sys.executable> <workspace-contained existing .py file> [arguments...]
```

The executable is normalized with `Path.resolve(strict=True)` and compared with the normalized `sys.executable` using `os.path.normcase`. Bare `python`, PATH lookup, `python -c`, stdin code (`python -`), other `-m` modules, interpreter switches, non-`.py` files, missing scripts, and scripts resolving outside the normalized workspace are rejected. `purpose` never relaxes this rule. This narrow boundary exists only so Task 7 cannot execute arbitrary programs before Task 8 replaces it with the approved unified policy.

### Cwd and environment

- Normalize `context.workspace` with `Path.resolve(strict=True)` and require a directory.
- Pass that path only through `Popen(cwd=workspace)`; never call `os.chdir()`.
- Start from `os.environ.copy()`, remove `OPENAI_API_KEY`, and set `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, and `PYTHONUNBUFFERED=1`.
- Never serialize or log the environment.
- Decode retained bytes with an incremental UTF-8 decoder using `errors="replace"`. For a truncated stream, call the decoder with `final=False`, which omits an incomplete trailing multibyte sequence; invalid complete bytes become U+FFFD without crashing.

### Output and process lifetime

- `stdout` and `stderr` each have an independent 65,536-byte raw retention budget.
- A daemon reader thread drains each pipe in 8,192-byte chunks to avoid the stdout/stderr pipe deadlock. Each collector retains only its prefix budget and continues discarding/draining later bytes; memory does not grow with child output.
- Exactly 65,536 bytes is not truncated. The first additional byte sets that stream's flag. Metadata combines the two flags with logical OR.
- On normal exit, join both reader threads and return the real exit code.
- On timeout, retain the timeout fact, call a tree terminator, wait briefly, and fall back to `Popen.kill()` for the parent if necessary. Return `exit_code=None` and `timed_out=True` even if cleanup fails.

The Windows tree terminator runs this fixed internal argument array, never a model string:

```python
[
    str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"),
    "/PID",
    str(process.pid),
    "/T",
    "/F",
]
```

It uses `subprocess.run(..., shell=False, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, timeout=10, check=False, creationflags=CREATE_NO_WINDOW)`. `taskkill /T /F` is chosen instead of a new dependency and, unlike killing only `Popen`, targets descendants that already exist. A nonzero taskkill result while the parent remains alive yields `"process-tree cleanup failed"`; inability to start or finish taskkill yields `"process-tree cleanup unavailable"`. The tool then best-effort kills the parent. This internal cleanup command does not expand the model-facing boundary.

`KeyboardInterrupt`, `SystemExit`, and every other `BaseException` propagate. Production code catches only the specific expected `OSError` and `subprocess.TimeoutExpired` cases.

---

### Task 0: Reconfirm the approved baseline

**Files:**
- Read: `AGENTS.md`
- Read: `DESIGN.md`
- Read: `TASKS.md`
- Read: `docs/superpowers/plans/Task4.md`
- Read: `docs/superpowers/plans/Task5.md`
- Read: `docs/superpowers/plans/Task6.md`
- Read: `docs/superpowers/plans/Task7.md`
- Read: `src/coding_agent/messages.py`
- Read: `src/coding_agent/state.py`
- Read: `src/coding_agent/agent.py`
- Read: `src/coding_agent/config.py`
- Read: `src/coding_agent/tools/base.py`
- Read: `src/coding_agent/tools/registry.py`
- Read: `src/coding_agent/tools/filesystem.py`
- Read: `tests/test_agent_loop.py`
- Read: `tests/test_cli.py`
- Read: `tests/tools/test_read_tools.py`
- Read: `tests/tools/test_write_tools.py`

**Interfaces:**
- Consumes: the committed Task 2-6 public interfaces exactly as listed above.
- Produces: verified permission to begin Task 7; no code behavior.

- [ ] **Step 1: Verify repository identity and baseline**

Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git log -3 --oneline
git status --short --untracked-files=all
git diff --check
```

Expected: root is `D:/code/coding_agent`, branch is `main`, Task 6 commit `10a1513` or its user-approved successor is in the last three commits, status is empty except this approved plan if it has not been committed, and `git diff --check` exits 0. Any additional change stops execution.

- [ ] **Step 2: Read every baseline file completely and compare interfaces**

Run:

```powershell
Get-Content -Raw AGENTS.md
Get-Content -Raw DESIGN.md
Get-Content -Raw TASKS.md
Get-Content -Raw docs/superpowers/plans/Task4.md
Get-Content -Raw docs/superpowers/plans/Task5.md
Get-Content -Raw docs/superpowers/plans/Task6.md
Get-Content -Raw docs/superpowers/plans/Task7.md
Get-Content -Raw src/coding_agent/messages.py
Get-Content -Raw src/coding_agent/state.py
Get-Content -Raw src/coding_agent/agent.py
Get-Content -Raw src/coding_agent/config.py
Get-Content -Raw src/coding_agent/tools/base.py
Get-Content -Raw src/coding_agent/tools/registry.py
Get-Content -Raw src/coding_agent/tools/filesystem.py
Get-Content -Raw tests/test_agent_loop.py
Get-Content -Raw tests/test_cli.py
Get-Content -Raw tests/tools/test_read_tools.py
Get-Content -Raw tests/tools/test_write_tools.py
```

Expected: `ExecutionContext(workspace: Path)`, `Tool.execute(arguments, context) -> ToolExecution`, the existing `ToolResultMetadata` fields, and `ToolRegistry([tool])` match this plan. No Task 7 implementation exists.

- [ ] **Step 3: Update only the authorized task status lines**

Modify `TASKS.md` only after Steps 1-2 pass:

```markdown
- Task 6 status: 已完成
- Task 7 status: 进行中
```

Run:

```powershell
Select-String -Path TASKS.md -Pattern '状态：进行中'
git diff -- TASKS.md
```

Expected: exactly one task is `进行中`; the diff changes only Task 6 and Task 7 status values.

**Acceptance:** Task 6 is demonstrably committed, the worktree contains no unapproved edits, interfaces match, and only Task 7 is active.

---

### Task 1: Execution timeout configuration, strict schema, validation, and registry compatibility

**Files:**
- Modify: `src/coding_agent/tools/base.py`
- Create: `src/coding_agent/tools/shell.py`
- Create: `tests/tools/test_shell_tool.py`

**Interfaces:**
- Consumes: `JSONObject`, `ToolResultMetadata`, `ExecutionContext`, `ToolExecution`, `ToolArgumentError`, and `ToolRegistry`.
- Produces: `ExecutionContext(workspace: Path, command_timeout_seconds: float = 60.0)` and `RunCommandTool.execute(arguments: JSONObject, context: ExecutionContext) -> ToolExecution`.

- [ ] **Step 1: Write the failing contract tests**

Create `tests/tools/test_shell_tool.py` with these imports, helper, and tests:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from coding_agent.messages import ToolCall
from coding_agent.tools.base import ExecutionContext, ToolArgumentError
from coding_agent.tools.registry import ToolRegistry
from coding_agent.tools.shell import RunCommandTool, parse_windows_command_line


def _command_for_script(script: Path, *arguments: str) -> str:
    return subprocess.list2cmdline([sys.executable, str(script), *arguments])


def _execute_script(
    tmp_path: Path,
    source: str,
    *,
    arguments: tuple[str, ...] = (),
    purpose: str = "test",
    timeout: float = 60.0,
    tool: RunCommandTool | None = None,
):
    script = tmp_path / "script.py"
    script.write_text(source, encoding="utf-8")
    selected_tool = tool if tool is not None else RunCommandTool()
    return selected_tool.execute(
        {
            "command": _command_for_script(script, *arguments),
            "purpose": purpose,
        },
        ExecutionContext(tmp_path, command_timeout_seconds=timeout),
    )


def test_execution_context_command_timeout_contract(tmp_path: Path) -> None:
    assert ExecutionContext(tmp_path).command_timeout_seconds == 60.0
    assert ExecutionContext(tmp_path, command_timeout_seconds=300).command_timeout_seconds == 300

    for value in (True, 0, -1, 300.01, 301, float("nan"), float("inf"), "60"):
        with pytest.raises(
            ValueError,
            match="command_timeout_seconds must be greater than 0 and at most 300",
        ):
            ExecutionContext(tmp_path, command_timeout_seconds=value)  # type: ignore[arg-type]


def test_run_command_schema_is_strict_and_timeout_is_not_model_facing() -> None:
    assert RunCommandTool.name == "run_command"
    assert RunCommandTool.schema == {
        "name": "run_command",
        "description": "Run a temporarily authorized Python command in the workspace.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "minLength": 1},
                "purpose": {
                    "type": "string",
                    "enum": ["inspect", "test", "verification"],
                },
            },
            "required": ["command", "purpose"],
            "additionalProperties": False,
        },
    }


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"purpose": "test"}, "arguments must contain exactly: command, purpose"),
        ({"command": "python", "purpose": "test", "timeout": 1}, "arguments must contain exactly: command, purpose"),
        ({"command": 7, "purpose": "test"}, "command must be a non-empty string"),
        ({"command": "   ", "purpose": "test"}, "command must be a non-empty string"),
        ({"command": "python\x00x", "purpose": "test"}, "command must not contain NUL"),
        ({"command": "python", "purpose": "build"}, "purpose must be inspect, test, or verification"),
        ({"command": "python", "purpose": 1}, "purpose must be inspect, test, or verification"),
    ],
)
def test_run_command_rejects_invalid_arguments(
    tmp_path: Path,
    arguments: object,
    message: str,
) -> None:
    with pytest.raises(ToolArgumentError, match=message):
        RunCommandTool().execute(arguments, ExecutionContext(tmp_path))  # type: ignore[arg-type]


def test_run_command_registers_without_registry_changes(tmp_path: Path) -> None:
    registry = ToolRegistry([RunCommandTool()])
    assert registry.schemas == (RunCommandTool.schema,)

    result = registry.execute(
        ToolCall(call_id="bad-command", name="run_command", arguments={"purpose": "test"}),
        ExecutionContext(tmp_path),
    )
    assert result.status == "rejected"
    assert result.error == (
        "invalid_arguments: run_command arguments must contain exactly: command, purpose"
    )
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "execution_context or schema or invalid_arguments or registers" -q --basetemp=.pytest-tmp-task7-red1
```

Expected: exit code 2 during collection because `coding_agent.tools.shell` does not exist. This is the expected missing-feature failure; any syntax failure in the test stops the cycle.

- [ ] **Step 3: Add the minimal configuration and validation implementation**

Add `import math` to `src/coding_agent/tools/base.py`, then modify `ExecutionContext` exactly as follows:

```python
@dataclass(frozen=True, slots=True)
class ExecutionContext:
    workspace: Path
    command_timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        timeout = self.command_timeout_seconds
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
            or timeout > 300
        ):
            raise ValueError(
                "command_timeout_seconds must be greater than 0 and at most 300"
            )
```

Create `src/coding_agent/tools/shell.py` with the minimal contract implementation:

```python
from __future__ import annotations

from coding_agent.messages import JSONObject
from coding_agent.tools.base import ExecutionContext, ToolArgumentError, ToolExecution

_ARGUMENT_NAMES = {"command", "purpose"}
_PURPOSES = {"inspect", "test", "verification"}


def _validated_arguments(arguments: object) -> tuple[str, str]:
    if not isinstance(arguments, dict) or set(arguments) != _ARGUMENT_NAMES:
        raise ToolArgumentError(
            "run_command arguments must contain exactly: command, purpose"
        )
    command = arguments["command"]
    if not isinstance(command, str) or not command.strip():
        raise ToolArgumentError("command must be a non-empty string")
    if "\x00" in command:
        raise ToolArgumentError("command must not contain NUL")
    purpose = arguments["purpose"]
    if not isinstance(purpose, str) or purpose not in _PURPOSES:
        raise ToolArgumentError("purpose must be inspect, test, or verification")
    return command.strip(), purpose


def parse_windows_command_line(command: str) -> tuple[str, ...]:
    command, _ = _validated_arguments({"command": command, "purpose": "inspect"})
    raise ToolArgumentError("command parsing is not available in this contract step")


class RunCommandTool:
    name = "run_command"
    schema: JSONObject = {
        "name": "run_command",
        "description": "Run a temporarily authorized Python command in the workspace.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "minLength": 1},
                "purpose": {
                    "type": "string",
                    "enum": ["inspect", "test", "verification"],
                },
            },
            "required": ["command", "purpose"],
            "additionalProperties": False,
        },
    }

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        _validated_arguments(arguments)
        raise ToolArgumentError("command parsing is not available in this contract step")
```

The explicit temporary rejection is removed in Task 2 and Task 3; it ensures this step does not execute a subprocess before parsing and authorization tests exist.

- [ ] **Step 4: Run GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "execution_context or schema or invalid_arguments or registers" -q --basetemp=.pytest-tmp-task7-green1
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -q --basetemp=.pytest-tmp-task7-cycle1
.\.venv\Scripts\python.exe -m pytest tests/test_messages.py tests/test_model.py tests/test_agent_loop.py tests/tools/test_read_tools.py tests/tools/test_write_tools.py -q --basetemp=.pytest-tmp-task7-regression1
```

Expected: the first command passes all selected Task 1 tests; the regression command exits 0 with zero failures and zero skips. Record the actual counts instead of copying an estimate.

**Acceptance:** timeout defaults and bounds are deterministic, schema and local checks agree, extra keys are rejected, timeout is not model-facing, and the unmodified registry accepts the tool.

---

### Task 2: Native Windows command-line parsing

**Files:**
- Modify: `src/coding_agent/tools/shell.py`
- Modify: `tests/tools/test_shell_tool.py`

**Interfaces:**
- Consumes: validated nonblank `command`.
- Produces: `parse_windows_command_line(command: str) -> tuple[str, ...]` with Windows-native quoting semantics.

- [ ] **Step 1: Append the failing parser tests**

Append to `tests/tools/test_shell_tool.py`:

```python
@pytest.mark.parametrize(
    "argv",
    [
        [sys.executable, "alpha beta", ""],
        [sys.executable, r"C:\path with spaces\script.py", r"ends-with-backslash\\"],
        [sys.executable, "引数 雪", 'embedded"quote', r"a\\\"b"],
    ],
)
def test_parse_windows_command_line_round_trips_windows_arguments(
    argv: list[str],
) -> None:
    command = subprocess.list2cmdline(argv)
    assert parse_windows_command_line(command) == tuple(argv)


def test_parse_windows_command_line_handles_spaced_python_script_path() -> None:
    argv = [sys.executable, r"D:\workspace with spaces\test script.py", "value"]
    assert parse_windows_command_line(subprocess.list2cmdline(argv)) == tuple(argv)


@pytest.mark.parametrize("command", ["", "   ", '"unterminated', 'python "still open'])
def test_parse_windows_command_line_rejects_empty_or_unclosed_input(
    command: str,
) -> None:
    expected = (
        "command must be a non-empty string"
        if not command.strip()
        else "command contains an unclosed quote"
    )
    with pytest.raises(ToolArgumentError, match=expected):
        parse_windows_command_line(command)


def test_parse_windows_command_line_does_not_treat_escaped_quote_as_closing() -> None:
    command = subprocess.list2cmdline([sys.executable, 'a"b', r"c\\d"])
    assert parse_windows_command_line(command) == (sys.executable, 'a"b', r"c\\d")


def test_parse_windows_command_line_maps_native_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def native_failure(command: str, argc: object) -> None:
        return None

    monkeypatch.setattr(
        "coding_agent.tools.shell._COMMAND_LINE_TO_ARGV_W",
        native_failure,
    )
    with pytest.raises(
        ToolArgumentError,
        match="command could not be parsed by Windows",
    ):
        parse_windows_command_line("python.exe")
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "parse_windows" -q --basetemp=.pytest-tmp-task7-red2
```

Expected: exit code 1 because the temporary parser raises `ToolArgumentError("command parsing is not available in this contract step")` for valid Windows command lines. Empty-input validation may already pass; at least the round-trip tests must fail for the missing parser.

- [ ] **Step 3: Replace the temporary parser with the exact native wrapper**

Add imports to `src/coding_agent/tools/shell.py`:

```python
import ctypes
from ctypes import wintypes
```

Configure the Windows calls and replace `parse_windows_command_line` with:

```python
_COMMAND_LINE_TO_ARGV_W = ctypes.windll.shell32.CommandLineToArgvW
_COMMAND_LINE_TO_ARGV_W.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
_COMMAND_LINE_TO_ARGV_W.restype = ctypes.POINTER(wintypes.LPWSTR)
_LOCAL_FREE = ctypes.windll.kernel32.LocalFree
_LOCAL_FREE.argtypes = [wintypes.HLOCAL]
_LOCAL_FREE.restype = wintypes.HLOCAL


def _has_unclosed_quote(command: str) -> bool:
    quoted = False
    backslashes = 0
    for character in command:
        if character == "\\":
            backslashes += 1
            continue
        if character == '"' and backslashes % 2 == 0:
            quoted = not quoted
        backslashes = 0
    return quoted


def parse_windows_command_line(command: str) -> tuple[str, ...]:
    command, _ = _validated_arguments({"command": command, "purpose": "inspect"})
    if _has_unclosed_quote(command):
        raise ToolArgumentError("command contains an unclosed quote")

    argc = ctypes.c_int()
    argv_pointer = _COMMAND_LINE_TO_ARGV_W(command, ctypes.byref(argc))
    if not argv_pointer or argc.value <= 0:
        raise ToolArgumentError("command could not be parsed by Windows")
    try:
        argv = tuple(argv_pointer[index] for index in range(argc.value))
    finally:
        _LOCAL_FREE(ctypes.cast(argv_pointer, wintypes.HLOCAL))
    if not argv or not argv[0]:
        raise ToolArgumentError("command could not be parsed by Windows")
    return argv
```

The native allocation is always released. Do not replace this with `shlex` or a whitespace split.

- [ ] **Step 4: Run GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "parse_windows" -q --basetemp=.pytest-tmp-task7-green2
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -q --basetemp=.pytest-tmp-task7-cycle2
.\.venv\Scripts\python.exe -m pytest tests/test_messages.py tests/test_model.py tests/test_agent_loop.py tests/tools/test_read_tools.py tests/tools/test_write_tools.py -q --basetemp=.pytest-tmp-task7-regression2
```

Expected: all parser tests pass on the target Windows host; regression exits 0 with zero failures and zero skips. A non-Windows host is not accepted as substitute evidence.

**Acceptance:** the exact native parser correctly preserves spaces, empty arguments, backslashes, quotes, Unicode, and spaced paths, while blank and unclosed input has stable rejection.

---

### Task 3: Temporary authorization, successful execution, fixed cwd, and secret-free environment

**Files:**
- Modify: `src/coding_agent/tools/shell.py`
- Modify: `tests/tools/test_shell_tool.py`

**Interfaces:**
- Consumes: parsed `tuple[str, ...]`, `ExecutionContext.workspace`, and validated `purpose`.
- Produces: Python-only authorization plus a normally completed `ToolExecution` with stable JSON and metadata.

- [ ] **Step 1: Append the failing execution and boundary tests**

Append to `tests/tools/test_shell_tool.py`:

```python
def test_run_command_executes_script_with_fixed_workspace_cwd(tmp_path: Path) -> None:
    execution = _execute_script(
        tmp_path,
        "from pathlib import Path\nprint(Path.cwd())\n",
        purpose="inspect",
    )
    payload = json.loads(execution.output or "")
    expected_payload = {
        "argv": [sys.executable, str(tmp_path / "script.py")],
        "cleanup_error": None,
        "purpose": "inspect",
        "stderr": "",
        "stdout": f"{tmp_path.resolve()}\r\n",
    }
    assert payload == expected_payload
    assert execution.output == json.dumps(
        expected_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert execution.metadata.exit_code == 0
    assert execution.metadata.timed_out is False
    assert execution.metadata.truncated is False
    assert execution.metadata.duration_ms >= 0
    assert execution.metadata.changed_paths == ()


def test_run_command_preserves_spaced_script_and_unicode_argument(tmp_path: Path) -> None:
    script = tmp_path / "script with spaces.py"
    script.write_text("import sys\nprint(sys.argv[1])\n", encoding="utf-8")
    execution = RunCommandTool().execute(
        {
            "command": _command_for_script(script, "雪 with space"),
            "purpose": "test",
        },
        ExecutionContext(tmp_path),
    )
    payload = json.loads(execution.output or "")
    assert payload["argv"] == [sys.executable, str(script), "雪 with space"]
    assert payload["stdout"] == "雪 with space\r\n"


def test_run_command_does_not_change_parent_cwd(tmp_path: Path) -> None:
    parent_cwd = Path.cwd()
    _execute_script(tmp_path, "print('ok')\n")
    assert Path.cwd() == parent_cwd


def test_run_command_does_not_pass_openai_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-child")
    execution = _execute_script(
        tmp_path,
        "import os\nprint(os.environ.get('OPENAI_API_KEY', '<absent>'))\n",
    )
    payload = json.loads(execution.output or "")
    assert payload["stdout"] == "<absent>\r\n"
    assert "must-not-reach-child" not in (execution.output or "")


@pytest.mark.parametrize(
    "argv",
    [
        ["cmd.exe", "/c", "echo", "unsafe"],
        ["powershell.exe", "-Command", "Write-Output unsafe"],
        [sys.executable, "-c", "print('unsafe')"],
        [sys.executable, "-"],
        [sys.executable, "-m", "pip", "list"],
    ],
)
def test_temporary_boundary_rejects_nonapproved_entry_points(
    tmp_path: Path,
    argv: list[str],
) -> None:
    with pytest.raises(
        ToolArgumentError,
        match="command is outside the temporary Task 7 boundary",
    ):
        RunCommandTool().execute(
            {
                "command": subprocess.list2cmdline(argv),
                "purpose": "verification",
            },
            ExecutionContext(tmp_path),
        )


def test_temporary_boundary_rejects_script_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print('unsafe')\n", encoding="utf-8")
    with pytest.raises(
        ToolArgumentError,
        match="command is outside the temporary Task 7 boundary",
    ):
        RunCommandTool().execute(
            {
                "command": _command_for_script(outside),
                "purpose": "inspect",
            },
            ExecutionContext(workspace),
        )


@pytest.mark.parametrize("module", ["pytest", "unittest"])
def test_temporary_boundary_accepts_only_approved_python_modules(
    tmp_path: Path,
    module: str,
) -> None:
    command = subprocess.list2cmdline([sys.executable, "-m", module, "--help"])
    execution = RunCommandTool().execute(
        {"command": command, "purpose": "inspect"},
        ExecutionContext(tmp_path),
    )
    assert execution.metadata.exit_code == 0
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "fixed_workspace or spaced_script or parent_cwd or api_key or temporary_boundary" -q --basetemp=.pytest-tmp-task7-red3
```

Expected: exit code 1 because `RunCommandTool.execute` still raises the temporary parsing-step rejection for valid scripts and does not yet enforce the locked boundary.

- [ ] **Step 3: Implement normalized workspace, authorization, environment, and the first bounded-input execution path**

Add these imports to `src/coding_agent/tools/shell.py`:

```python
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from coding_agent.messages import ToolResultMetadata
```

Add:

```python
def _normalized_workspace(context: ExecutionContext) -> Path:
    try:
        workspace = context.workspace.resolve(strict=True)
    except OSError as exc:
        raise ToolArgumentError("workspace must be an existing directory") from exc
    if not workspace.is_dir():
        raise ToolArgumentError("workspace must be an existing directory")
    return workspace


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _authorize_temporary_command(argv: tuple[str, ...], workspace: Path) -> None:
    try:
        executable = Path(argv[0]).resolve(strict=True)
        current_python = Path(sys.executable).resolve(strict=True)
    except OSError as exc:
        raise ToolArgumentError(
            "command is outside the temporary Task 7 boundary"
        ) from exc
    if not _same_path(executable, current_python) or len(argv) < 2:
        raise ToolArgumentError("command is outside the temporary Task 7 boundary")

    if argv[1] == "-m":
        if len(argv) >= 3 and argv[2] in {"pytest", "unittest"}:
            return
        raise ToolArgumentError("command is outside the temporary Task 7 boundary")
    if argv[1].startswith("-"):
        raise ToolArgumentError("command is outside the temporary Task 7 boundary")

    script = Path(argv[1])
    if not script.is_absolute():
        script = workspace / script
    try:
        script = script.resolve(strict=True)
        script.relative_to(workspace)
    except (OSError, ValueError) as exc:
        raise ToolArgumentError(
            "command is outside the temporary Task 7 boundary"
        ) from exc
    if not script.is_file() or script.suffix.casefold() != ".py":
        raise ToolArgumentError("command is outside the temporary Task 7 boundary")


def _child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def _json_output(
    argv: tuple[str, ...],
    purpose: str,
    stdout: str,
    stderr: str,
    cleanup_error: str | None,
) -> str:
    return json.dumps(
        {
            "argv": list(argv),
            "cleanup_error": cleanup_error,
            "purpose": purpose,
            "stderr": stderr,
            "stdout": stdout,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
```

Replace `RunCommandTool.execute` with this small first execution path:

```python
    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        command, purpose = _validated_arguments(arguments)
        argv = parse_windows_command_line(command)
        workspace = _normalized_workspace(context)
        _authorize_temporary_command(argv, workspace)

        started = time.monotonic_ns()
        completed = subprocess.run(
            argv,
            shell=False,
            cwd=workspace,
            env=_child_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        duration_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
        return ToolExecution(
            output=_json_output(
                argv,
                purpose,
                completed.stdout.decode("utf-8", errors="replace"),
                completed.stderr.decode("utf-8", errors="replace"),
                None,
            ),
            metadata=ToolResultMetadata(
                exit_code=completed.returncode,
                duration_ms=duration_ms,
            ),
        )
```

This `subprocess.run` path is used only for the small Task 3 fixtures. Task 5 replaces it with the final concurrently drained bounded `Popen` path before large output is tested or Task 7 can be approved.

- [ ] **Step 4: Run GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "fixed_workspace or spaced_script or parent_cwd or api_key or temporary_boundary" -q --basetemp=.pytest-tmp-task7-green3
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -q --basetemp=.pytest-tmp-task7-cycle3
.\.venv\Scripts\python.exe -m pytest tests/test_messages.py tests/test_model.py tests/test_agent_loop.py tests/tools/test_read_tools.py tests/tools/test_write_tools.py -q --basetemp=.pytest-tmp-task7-regression3
```

Expected: all selected execution and authorization tests pass; regressions exit 0. The output contains no API-key value.

**Acceptance:** only the exact current Python interpreter with an approved module or workspace `.py` script runs; cwd is normalized and fixed; the parent cwd is unchanged; environment output is never exposed and `OPENAI_API_KEY` is absent in the child.

---

### Task 4: Nonzero exits, stream separation, Unicode, invalid bytes, and startup mapping

**Files:**
- Modify: `src/coding_agent/tools/shell.py`
- Modify: `tests/tools/test_shell_tool.py`

**Interfaces:**
- Consumes: normally started Python process.
- Produces: exact exit-code preservation, stable stream decoding, and `CommandStartError` for launch failures.

- [ ] **Step 1: Append failing result-semantics tests**

Append to `tests/tools/test_shell_tool.py`:

```python
def test_nonzero_exit_is_successful_tool_execution(tmp_path: Path) -> None:
    script = tmp_path / "failure.py"
    script.write_text(
        "import sys\nprint('out')\nprint('err', file=sys.stderr)\nraise SystemExit(7)\n",
        encoding="utf-8",
    )
    registry = ToolRegistry([RunCommandTool()])
    result = registry.execute(
        ToolCall(
            call_id="nonzero",
            name="run_command",
            arguments={
                "command": _command_for_script(script),
                "purpose": "test",
            },
        ),
        ExecutionContext(tmp_path),
    )
    payload = json.loads(result.output or "")
    assert result.status == "ok"
    assert result.error is None
    assert result.metadata.exit_code == 7
    assert result.metadata.timed_out is False
    assert payload["stdout"] == "out\r\n"
    assert payload["stderr"] == "err\r\n"


def test_empty_and_separate_streams_are_stable(tmp_path: Path) -> None:
    empty = _execute_script(tmp_path, "pass\n")
    empty_payload = json.loads(empty.output or "")
    assert empty_payload["stdout"] == ""
    assert empty_payload["stderr"] == ""

    both = _execute_script(
        tmp_path,
        "import sys\nsys.stdout.write('no-newline')\nsys.stderr.write('错误')\n",
    )
    both_payload = json.loads(both.output or "")
    assert both_payload["stdout"] == "no-newline"
    assert both_payload["stderr"] == "错误"


def test_invalid_utf8_output_is_replaced_without_crashing(tmp_path: Path) -> None:
    execution = _execute_script(
        tmp_path,
        "import sys\nsys.stdout.buffer.write(b'\\xffok')\n",
    )
    payload = json.loads(execution.output or "")
    assert payload["stdout"] == "�ok"
    assert execution.metadata.exit_code == 0


def test_startup_os_errors_map_to_stable_registry_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "start.py"
    script.write_text("print('never')\n", encoding="utf-8")

    def denied(*args: object, **kwargs: object) -> object:
        raise PermissionError("localized and secret operating-system detail")

    monkeypatch.setattr("coding_agent.tools.shell.subprocess.run", denied)
    registry = ToolRegistry([RunCommandTool()])
    result = registry.execute(
        ToolCall(
            call_id="start-error",
            name="run_command",
            arguments={"command": _command_for_script(script), "purpose": "test"},
        ),
        ExecutionContext(tmp_path),
    )
    assert result.status == "error"
    assert result.error == (
        "tool_execution_failed: CommandStartError: command could not be started: permission denied"
    )
    assert "localized" not in (result.error or "")
    assert result.output is None


def test_user_interrupt_is_not_swallowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "interrupt.py"
    script.write_text("print('never')\n", encoding="utf-8")

    def interrupted(*args: object, **kwargs: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr("coding_agent.tools.shell.subprocess.run", interrupted)
    with pytest.raises(KeyboardInterrupt):
        RunCommandTool().execute(
            {"command": _command_for_script(script), "purpose": "test"},
            ExecutionContext(tmp_path),
        )
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "nonzero or separate_streams or invalid_utf8 or startup_os_errors or user_interrupt" -q --basetemp=.pytest-tmp-task7-red4
```

Expected: exit code 1 because startup `PermissionError` is not yet mapped to the stable `CommandStartError`; the nonzero/stream tests may already pass and establish that their semantics are preserved.

- [ ] **Step 3: Add stable startup error mapping without catching user interrupts**

Add to `src/coding_agent/tools/shell.py`:

```python
class CommandStartError(RuntimeError):
    """The authorized child process could not be created."""


def _start_error(exc: OSError) -> CommandStartError:
    if isinstance(exc, FileNotFoundError):
        detail = "executable unavailable"
    elif isinstance(exc, PermissionError):
        detail = "permission denied"
    else:
        detail = "operating system error"
    return CommandStartError(f"command could not be started: {detail}")
```

Wrap only the `subprocess.run(...)` call in the Task 3 implementation:

```python
        try:
            completed = subprocess.run(
                argv,
                shell=False,
                cwd=workspace,
                env=_child_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as exc:
            raise _start_error(exc) from exc
```

Do not use `except Exception` or `except BaseException`; `KeyboardInterrupt` must remain observable.

- [ ] **Step 4: Run GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "nonzero or separate_streams or invalid_utf8 or startup_os_errors or user_interrupt" -q --basetemp=.pytest-tmp-task7-green4
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -q --basetemp=.pytest-tmp-task7-cycle4
.\.venv\Scripts\python.exe -m pytest tests/test_messages.py tests/test_model.py tests/test_agent_loop.py tests/tools/test_read_tools.py tests/tools/test_write_tools.py -q --basetemp=.pytest-tmp-task7-regression4
```

Expected: every selected test and all regressions pass. The nonzero result remains `ok`, and no localized OS detail or traceback appears.

**Acceptance:** stdout/stderr remain distinct, empty/no-newline/Unicode/invalid-byte output is stable, nonzero exits retain their integer, launch failures have nonsecret errors, and user interrupt propagates.

---

### Task 5: Concurrent bounded stdout/stderr capture and exact 64 KiB semantics

**Files:**
- Modify: `src/coding_agent/tools/shell.py`
- Modify: `tests/tools/test_shell_tool.py`

**Interfaces:**
- Consumes: `subprocess.Popen[bytes]` stdout/stderr pipes.
- Produces: independent first-prefix capture limited to 65,536 raw bytes per stream and a combined truncation bit.

- [ ] **Step 1: Append failing byte-boundary and dual-stream tests**

Append to `tests/tools/test_shell_tool.py`:

```python
def test_exactly_64_kib_per_stream_is_not_truncated(tmp_path: Path) -> None:
    execution = _execute_script(
        tmp_path,
        "import sys\n"
        "sys.stdout.buffer.write(b'o' * 65536)\n"
        "sys.stderr.buffer.write(b'e' * 65536)\n",
    )
    payload = json.loads(execution.output or "")
    assert len(payload["stdout"].encode("utf-8")) == 65536
    assert len(payload["stderr"].encode("utf-8")) == 65536
    assert execution.metadata.truncated is False


@pytest.mark.parametrize(
    ("stdout_size", "stderr_size", "expected_stdout", "expected_stderr"),
    [
        (65537, 0, 65536, 0),
        (0, 65537, 0, 65536),
        (131072, 131072, 65536, 65536),
    ],
)
def test_each_stream_keeps_only_its_first_64_kib(
    tmp_path: Path,
    stdout_size: int,
    stderr_size: int,
    expected_stdout: int,
    expected_stderr: int,
) -> None:
    execution = _execute_script(
        tmp_path,
        "import sys\n"
        f"sys.stdout.buffer.write(b'o' * {stdout_size})\n"
        f"sys.stderr.buffer.write(b'e' * {stderr_size})\n",
    )
    payload = json.loads(execution.output or "")
    assert payload["stdout"] == "o" * expected_stdout
    assert payload["stderr"] == "e" * expected_stderr
    assert execution.metadata.truncated is True


def test_truncation_omits_split_utf8_tail_without_replacement(tmp_path: Path) -> None:
    execution = _execute_script(
        tmp_path,
        "import sys\n"
        "sys.stdout.buffer.write((('a' * 65535) + 'é').encode('utf-8'))\n",
    )
    payload = json.loads(execution.output or "")
    assert payload["stdout"] == "a" * 65535
    assert "�" not in payload["stdout"]
    assert execution.metadata.truncated is True


def test_large_simultaneous_streams_are_drained_without_deadlock(tmp_path: Path) -> None:
    execution = _execute_script(
        tmp_path,
        "import sys\n"
        "chunk_out = b'o' * 8192\n"
        "chunk_err = b'e' * 8192\n"
        "for _ in range(64):\n"
        "    sys.stdout.buffer.write(chunk_out)\n"
        "    sys.stdout.buffer.flush()\n"
        "    sys.stderr.buffer.write(chunk_err)\n"
        "    sys.stderr.buffer.flush()\n",
        timeout=10,
    )
    payload = json.loads(execution.output or "")
    assert payload["stdout"] == "o" * 65536
    assert payload["stderr"] == "e" * 65536
    assert execution.metadata.exit_code == 0
    assert execution.metadata.timed_out is False
    assert execution.metadata.truncated is True
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "64_kib or split_utf8 or simultaneous_streams" -q --basetemp=.pytest-tmp-task7-red5
```

Expected: exit code 1 because the Task 3 `subprocess.run` path returns more than 65,536 bytes and never sets `metadata.truncated`; the dual-stream fixture may finish but its length assertions fail.

- [ ] **Step 3: Replace unbounded post-exit capture with concurrent bounded collectors**

Add imports:

```python
import codecs
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Thread
from typing import BinaryIO
```

Add these exact helpers:

```python
_OUTPUT_LIMIT_BYTES = 64 * 1024
_READ_CHUNK_BYTES = 8 * 1024


@dataclass(slots=True)
class _BoundedBytes:
    data: bytearray = field(default_factory=bytearray)
    truncated: bool = False
    read_error: bool = False


def _drain_pipe(pipe: BinaryIO, capture: _BoundedBytes) -> None:
    try:
        while True:
            chunk = pipe.read(_READ_CHUNK_BYTES)
            if not chunk:
                return
            remaining = _OUTPUT_LIMIT_BYTES - len(capture.data)
            if remaining > 0:
                capture.data.extend(chunk[:remaining])
            if len(chunk) > remaining:
                capture.truncated = True
    except OSError:
        capture.read_error = True
    finally:
        pipe.close()


def _decode_captured(capture: _BoundedBytes) -> str:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    return decoder.decode(bytes(capture.data), final=not capture.truncated)


def _reader(pipe: BinaryIO, capture: _BoundedBytes) -> Thread:
    thread = Thread(target=_drain_pipe, args=(pipe, capture), daemon=True)
    thread.start()
    return thread
```

Introduce a typed process factory and constructor seam that Task 8 does not expose to the model:

```python
ProcessFactory = Callable[..., subprocess.Popen[bytes]]


class RunCommandTool:
    # Keep name and schema unchanged.

    def __init__(self, *, process_factory: ProcessFactory | None = None) -> None:
        self._process_factory = (
            subprocess.Popen if process_factory is None else process_factory
        )
```

In `tests/tools/test_shell_tool.py`, replace the two Task 4 monkeypatch-based constructions so they continue to exercise the same public `execute` call after the launch mechanism changes:

```python
# In test_startup_os_errors_map_to_stable_registry_error:
registry = ToolRegistry([RunCommandTool(process_factory=denied)])

# In test_user_interrupt_is_not_swallowed:
with pytest.raises(KeyboardInterrupt):
    RunCommandTool(process_factory=interrupted).execute(
        {"command": _command_for_script(script), "purpose": "test"},
        ExecutionContext(tmp_path),
    )
```

Remove the two corresponding `monkeypatch.setattr("coding_agent.tools.shell.subprocess.run", ...)` lines and remove each unused `monkeypatch` fixture argument. Do not change their assertions.

Replace the `subprocess.run` launch/capture portion of `execute` with:

```python
        started = time.monotonic_ns()
        try:
            process = self._process_factory(
                argv,
                shell=False,
                cwd=workspace,
                env=_child_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise _start_error(exc) from exc

        assert process.stdout is not None
        assert process.stderr is not None
        stdout_capture = _BoundedBytes()
        stderr_capture = _BoundedBytes()
        stdout_thread = _reader(process.stdout, stdout_capture)
        stderr_thread = _reader(process.stderr, stderr_capture)
        exit_code = process.wait()
        stdout_thread.join()
        stderr_thread.join()
        if stdout_capture.read_error or stderr_capture.read_error:
            raise RuntimeError("command output could not be captured")

        duration_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
        truncated = stdout_capture.truncated or stderr_capture.truncated
        return ToolExecution(
            output=_json_output(
                argv,
                purpose,
                _decode_captured(stdout_capture),
                _decode_captured(stderr_capture),
                None,
            ),
            metadata=ToolResultMetadata(
                exit_code=exit_code,
                truncated=truncated,
                duration_ms=duration_ms,
            ),
        )
```

The local callable type keeps the test seam explicit without changing the model-facing schema. At this point the two reader threads ensure neither child pipe blocks the other, and retained memory is bounded even while later bytes are drained.

- [ ] **Step 4: Run GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "64_kib or split_utf8 or simultaneous_streams" -q --basetemp=.pytest-tmp-task7-green5
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -q --basetemp=.pytest-tmp-task7-cycle5
.\.venv\Scripts\python.exe -m pytest tests/test_messages.py tests/test_model.py tests/test_agent_loop.py tests/tools/test_read_tools.py tests/tools/test_write_tools.py -q --basetemp=.pytest-tmp-task7-regression5
```

Expected: exact-boundary, stdout-only, stderr-only, both-stream, split-multibyte, and no-deadlock assertions pass; all regressions pass.

**Acceptance:** each stream retains at most 65,536 raw bytes independently, the first excess byte marks truncation, incomplete truncated UTF-8 tails are omitted, invalid complete bytes remain replacement-decoded, and simultaneous large output cannot deadlock on full pipes.

---

### Task 6: Configured timeout, partial output, and monotonic duration

**Files:**
- Modify: `src/coding_agent/tools/shell.py`
- Modify: `tests/tools/test_shell_tool.py`

**Interfaces:**
- Consumes: `ExecutionContext.command_timeout_seconds` and a running `Popen[bytes]`.
- Produces: `timed_out=True`, `exit_code=None`, captured partial streams, and monotonic `duration_ms` when the deadline expires.

- [ ] **Step 1: Append failing timeout tests**

Append to `tests/tools/test_shell_tool.py`:

```python
def test_short_wait_finishes_before_timeout_and_uses_monotonic_duration(
    tmp_path: Path,
) -> None:
    execution = _execute_script(
        tmp_path,
        "import time\ntime.sleep(0.15)\nprint('done')\n",
        timeout=2,
    )
    payload = json.loads(execution.output or "")
    assert payload["stdout"] == "done\r\n"
    assert execution.metadata.exit_code == 0
    assert execution.metadata.timed_out is False
    assert execution.metadata.duration_ms >= 100


def test_timeout_returns_partial_stdout_and_stderr(tmp_path: Path) -> None:
    execution = _execute_script(
        tmp_path,
        "import sys, time\n"
        "print('before-timeout-out', flush=True)\n"
        "print('before-timeout-err', file=sys.stderr, flush=True)\n"
        "time.sleep(1.0)\n",
        timeout=0.25,
    )
    payload = json.loads(execution.output or "")
    assert execution.metadata.timed_out is True
    assert execution.metadata.exit_code is None
    assert execution.metadata.duration_ms >= 200
    assert payload["stdout"] == "before-timeout-out\r\n"
    assert payload["stderr"] == "before-timeout-err\r\n"
    assert payload["cleanup_error"] is None


def test_timeout_retains_bounded_partial_output(tmp_path: Path) -> None:
    execution = _execute_script(
        tmp_path,
        "import sys, time\n"
        "sys.stdout.buffer.write(b'x' * 70000)\n"
        "sys.stdout.buffer.flush()\n"
        "time.sleep(1.0)\n",
        timeout=0.25,
    )
    payload = json.loads(execution.output or "")
    assert payload["stdout"] == "x" * 65536
    assert execution.metadata.timed_out is True
    assert execution.metadata.exit_code is None
    assert execution.metadata.truncated is True
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "short_wait or timeout_returns or timeout_retains" -q --basetemp=.pytest-tmp-task7-red6
```

Expected: exit code 1 after roughly two seconds because the current `process.wait()` has no timeout; each one-second fixture completes normally and therefore cannot produce `timed_out=True` or `exit_code=None`.

- [ ] **Step 3: Add deadline handling with parent cleanup as the minimal green behavior**

Replace the unconditional `exit_code = process.wait()` block with:

```python
        timed_out = False
        cleanup_error: str | None = None
        try:
            exit_code: int | None = process.wait(
                timeout=context.command_timeout_seconds
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = None
            try:
                process.kill()
                process.wait(timeout=5)
            except OSError:
                cleanup_error = "parent-process cleanup failed"
            except subprocess.TimeoutExpired:
                cleanup_error = "parent-process cleanup failed"

        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            cleanup_error = cleanup_error or "command output cleanup failed"
        if stdout_capture.read_error or stderr_capture.read_error:
            raise RuntimeError("command output could not be captured")
```

Update the return construction:

```python
            output=_json_output(
                argv,
                purpose,
                _decode_captured(stdout_capture),
                _decode_captured(stderr_capture),
                cleanup_error,
            ),
            metadata=ToolResultMetadata(
                exit_code=exit_code,
                timed_out=timed_out,
                truncated=truncated,
                duration_ms=duration_ms,
            ),
```

This RED/GREEN cycle proves deadline metadata and partial capture first. Task 7 immediately replaces parent-only cleanup with the required Windows tree terminator before approval.

- [ ] **Step 4: Run GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "short_wait or timeout_returns or timeout_retains" -q --basetemp=.pytest-tmp-task7-green6
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -q --basetemp=.pytest-tmp-task7-cycle6
.\.venv\Scripts\python.exe -m pytest tests/test_messages.py tests/test_model.py tests/test_agent_loop.py tests/tools/test_read_tools.py tests/tools/test_write_tools.py -q --basetemp=.pytest-tmp-task7-regression6
```

Expected: all selected tests finish promptly and pass; regressions pass. Actual elapsed time may exceed the configured timeout by cleanup scheduling, but metadata uses the monotonic total and the timeout fact is true.

**Acceptance:** the local positive timeout is enforced, normal short waits remain normal exits, timeout preserves bounded partial streams, and timeout returns `exit_code=null` without losing duration.

---

### Task 7: Terminate the complete Windows child-process tree

**Files:**
- Modify: `src/coding_agent/tools/shell.py`
- Modify: `tests/tools/test_shell_tool.py`

**Interfaces:**
- Consumes: timed-out `Popen[bytes]` with a numeric pid.
- Produces: `_terminate_process_tree(process: subprocess.Popen[bytes]) -> str | None` and no observable surviving descendant in the target Windows test.

- [ ] **Step 1: Append the failing process-tree test**

Append to `tests/tools/test_shell_tool.py`:

```python
def test_timeout_terminates_child_process_tree_before_child_side_effect(
    tmp_path: Path,
) -> None:
    assert os.name == "nt", "Task 7 process-tree acceptance requires Windows"
    marker = tmp_path / "orphan-marker.txt"
    child = tmp_path / "child.py"
    child.write_text(
        "from pathlib import Path\n"
        "import sys, time\n"
        "time.sleep(1.5)\n"
        "Path(sys.argv[1]).write_text('orphan survived', encoding='utf-8')\n",
        encoding="utf-8",
    )
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])\n"
        "print('child-started', flush=True)\n"
        "time.sleep(10)\n",
        encoding="utf-8",
    )

    execution = RunCommandTool().execute(
        {
            "command": _command_for_script(parent, str(child), str(marker)),
            "purpose": "test",
        },
        ExecutionContext(tmp_path, command_timeout_seconds=0.35),
    )
    payload = json.loads(execution.output or "")
    assert execution.metadata.timed_out is True
    assert execution.metadata.exit_code is None
    assert payload["stdout"] == "child-started\r\n"
    assert payload["cleanup_error"] is None

    time.sleep(1.6)
    assert not marker.exists()
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py::test_timeout_terminates_child_process_tree_before_child_side_effect -q --basetemp=.pytest-tmp-task7-red7
```

Expected: exit code 1 after roughly two seconds because parent-only `process.kill()` leaves `child.py` alive and it creates `orphan-marker.txt`. Immediately terminate any surviving fixture process after recording RED; do not proceed with an orphan running.

- [ ] **Step 3: Implement fixed internal `taskkill /T /F` cleanup**

Add:

```python
TreeTerminator = Callable[[subprocess.Popen[bytes]], str | None]


def _taskkill_path() -> Path:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return system_root / "System32" / "taskkill.exe"


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> str | None:
    try:
        completed = subprocess.run(
            [
                str(_taskkill_path()),
                "/PID",
                str(process.pid),
                "/T",
                "/F",
            ],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "process-tree cleanup unavailable"
    if completed.returncode != 0 and process.poll() is None:
        return "process-tree cleanup failed"
    return None
```

Extend the constructor without changing its existing test seam:

```python
    def __init__(
        self,
        *,
        process_factory: ProcessFactory | None = None,
        tree_terminator: TreeTerminator | None = None,
    ) -> None:
        self._process_factory = (
            subprocess.Popen if process_factory is None else process_factory
        )
        self._tree_terminator = (
            _terminate_process_tree if tree_terminator is None else tree_terminator
        )
```

Replace the timeout cleanup block with:

```python
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = None
            cleanup_error = self._tree_terminator(process)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    cleanup_error = cleanup_error or "parent-process cleanup failed"
```

Do not serialize taskkill stdout/stderr or any environment. The original `timed_out=True` and `exit_code=None` are assigned before cleanup and never overwritten.

- [ ] **Step 4: Run GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py::test_timeout_terminates_child_process_tree_before_child_side_effect -q --basetemp=.pytest-tmp-task7-green7
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -q --basetemp=.pytest-tmp-task7-cycle7
.\.venv\Scripts\python.exe -m pytest tests/test_messages.py tests/test_model.py tests/test_agent_loop.py tests/tools/test_read_tools.py tests/tools/test_write_tools.py -q --basetemp=.pytest-tmp-task7-regression7
```

Expected: the tree test passes on Windows, `cleanup_error` is null, and the marker remains absent after its child-side-effect deadline; all regressions pass. A permanent skip is not acceptable target-Windows evidence.

**Acceptance:** timeout uses an exact internal argument array with `shell=False`, terminates parent and descendants, preserves partial output, and leaves no observable child side effect.

---

### Task 8: Cleanup failure, launch failure, and invocation-flag evidence

**Files:**
- Modify: `src/coding_agent/tools/shell.py`
- Modify: `tests/tools/test_shell_tool.py`

**Interfaces:**
- Consumes: the process-factory and tree-terminator constructor seams.
- Produces: stable cleanup failure in JSON while timeout metadata remains authoritative, plus deterministic evidence for `shell=False`, cwd, and environment isolation.

- [ ] **Step 1: Append failing failure-path and launch-argument tests**

Append to `tests/tools/test_shell_tool.py`:

```python
def test_cleanup_failure_does_not_overwrite_timeout_fact(tmp_path: Path) -> None:
    def cleanup_failed(process: subprocess.Popen[bytes]) -> str:
        return "simulated process-tree cleanup failure"

    execution = _execute_script(
        tmp_path,
        "import time\nprint('started', flush=True)\ntime.sleep(10)\n",
        timeout=0.2,
        tool=RunCommandTool(tree_terminator=cleanup_failed),
    )
    payload = json.loads(execution.output or "")
    assert execution.metadata.timed_out is True
    assert execution.metadata.exit_code is None
    assert payload["stdout"] == "started\r\n"
    assert payload["cleanup_error"] == "simulated process-tree cleanup failure"


def test_cleanup_os_error_returns_unavailable_without_losing_timeout(
    tmp_path: Path,
) -> None:
    def cleanup_unavailable(process: subprocess.Popen[bytes]) -> str | None:
        process.kill()
        raise OSError("localized cleanup detail")

    execution = _execute_script(
        tmp_path,
        "import time\nprint('started', flush=True)\ntime.sleep(10)\n",
        timeout=0.2,
        tool=RunCommandTool(tree_terminator=cleanup_unavailable),
    )
    payload = json.loads(execution.output or "")
    assert execution.metadata.timed_out is True
    assert execution.metadata.exit_code is None
    assert payload["cleanup_error"] == "process-tree cleanup unavailable"
    assert "localized" not in (execution.output or "")


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (FileNotFoundError("secret localized detail"), "executable unavailable"),
        (PermissionError("secret localized detail"), "permission denied"),
        (OSError("secret localized detail"), "operating system error"),
    ],
)
def test_process_factory_os_errors_have_stable_nonsecret_mapping(
    tmp_path: Path,
    exception: OSError,
    expected: str,
) -> None:
    script = tmp_path / "never-started.py"
    script.write_text("print('never')\n", encoding="utf-8")

    def failed_factory(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        raise exception

    registry = ToolRegistry([RunCommandTool(process_factory=failed_factory)])
    result = registry.execute(
        ToolCall(
            call_id="failed-start",
            name="run_command",
            arguments={"command": _command_for_script(script), "purpose": "test"},
        ),
        ExecutionContext(tmp_path),
    )
    assert result.status == "error"
    assert result.error == (
        f"tool_execution_failed: CommandStartError: command could not be started: {expected}"
    )
    assert "secret" not in (result.error or "")


def test_process_launch_uses_shell_false_fixed_cwd_and_sanitized_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "not-for-child")
    script = tmp_path / "observed.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def recording_factory(
        argv: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.Popen[bytes]:
        observed["argv"] = argv
        observed.update(kwargs)
        return subprocess.Popen(argv, **kwargs)  # type: ignore[arg-type]

    execution = RunCommandTool(process_factory=recording_factory).execute(
        {"command": _command_for_script(script), "purpose": "inspect"},
        ExecutionContext(tmp_path),
    )
    assert execution.metadata.exit_code == 0
    assert observed["argv"] == (sys.executable, str(script))
    assert observed["shell"] is False
    assert observed["cwd"] == tmp_path.resolve()
    assert observed["stdin"] is subprocess.DEVNULL
    environment = observed["env"]
    assert isinstance(environment, dict)
    assert "OPENAI_API_KEY" not in environment
    assert environment["PYTHONUTF8"] == "1"
    assert environment["PYTHONIOENCODING"] == "utf-8"
    assert environment["PYTHONUNBUFFERED"] == "1"
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "cleanup_failure or process_factory_os_errors or launch_uses" -q --basetemp=.pytest-tmp-task7-red8
```

Expected: exit code 1 because a fake terminator that raises `OSError` is not yet converted to stable cleanup state, and a fake terminator that returns without killing exercises fallback while preserving its supplied cleanup string. The startup mapping and launch-argument tests may already pass and lock their behavior.

- [ ] **Step 3: Make fallback cleanup prompt and preserve the first cleanup fact**

Change only the timeout fallback wait duration and error precedence in `src/coding_agent/tools/shell.py`:

```python
_POST_TERMINATION_WAIT_SECONDS = 0.5

# In the timeout branch:
            try:
                cleanup_error = self._tree_terminator(process)
            except (OSError, subprocess.TimeoutExpired):
                cleanup_error = "process-tree cleanup unavailable"
            try:
                process.wait(timeout=_POST_TERMINATION_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=_POST_TERMINATION_WAIT_SECONDS)
                except (OSError, subprocess.TimeoutExpired):
                    cleanup_error = cleanup_error or "parent-process cleanup failed"
```

This preserves the first true tree-cleanup error and still guarantees a best-effort parent kill so test fixtures do not leak. Do not catch `KeyboardInterrupt` around the terminator.

- [ ] **Step 4: Run GREEN and complete Task 7 regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "cleanup_failure or process_factory_os_errors or launch_uses" -q --basetemp=.pytest-tmp-task7-green8
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -q --basetemp=.pytest-tmp-task7-task8-regression
.\.venv\Scripts\python.exe -m pytest tests/test_messages.py tests/test_model.py tests/test_agent_loop.py tests/tools/test_read_tools.py tests/tools/test_write_tools.py -q --basetemp=.pytest-tmp-task7-regression8
```

Expected: all failure-path tests, the complete Task 7 file, and every Task 2-6 regression pass with zero skips. Report actual counts and warnings.

**Acceptance:** cleanup failures are explicit but cannot overwrite timeout state; the parent is best-effort reaped; startup errors are stable and nonsecret; launch evidence proves argument-vector execution, `shell=False`, normalized cwd, and API-key removal.

---

### Task 9: Offline boundary and final verification

**Files:**
- Verify: `src/coding_agent/tools/base.py`
- Verify: `src/coding_agent/tools/shell.py`
- Verify: `tests/tools/test_shell_tool.py`
- Verify: `TASKS.md`
- Verify unchanged: `src/coding_agent/config.py`
- Verify unchanged: `src/coding_agent/tools/registry.py`
- Verify unchanged: `src/coding_agent/tools/filesystem.py`
- Verify unchanged: `src/coding_agent/agent.py`
- Verify unchanged: `pyproject.toml`

**Interfaces:**
- Consumes: the complete Task 7 implementation and Task 2-6 baseline.
- Produces: fresh, reproducible evidence for every Task 7 acceptance item; no status completion and no source-control mutation.

- [ ] **Step 1: Prove import and execution remain offline**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import sys; import coding_agent.tools.shell; assert 'openai' not in sys.modules; print('shell import is provider-free')"
Select-String -Path src/coding_agent/tools/shell.py -Pattern '^\s*(import|from)\s+(openai|socket|urllib|http|requests|httpx)\b'
```

Expected: the Python command exits 0 and prints `shell import is provider-free`; `Select-String` returns no matches. No network call occurs and no API key is read by the parent test code except the synthetic value used to prove child isolation.

- [ ] **Step 2: Run the complete Task 7 suite on Windows**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -q --basetemp=.pytest-tmp-task7-final
```

Expected: exit code 0, every Task 7 test passes, zero failures, and zero skips. Report actual pass and warning counts. The process-tree test must execute on Windows; a skip is an acceptance failure.

- [ ] **Step 3: Run configuration and Task 2-6 regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -q --basetemp=.pytest-tmp-task7-config
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -q --basetemp=.pytest-tmp-task7-agent
.\.venv\Scripts\python.exe -m pytest tests/tools/test_read_tools.py tests/tools/test_write_tools.py -q --basetemp=.pytest-tmp-task7-files
.\.venv\Scripts\python.exe -m pytest tests/test_messages.py tests/test_model.py -q --basetemp=.pytest-tmp-task7-types
```

Expected: each command exits 0 with zero failures and zero skips. This proves the defaulted `ExecutionContext` field did not break existing constructors and no Task 2-6 behavior regressed.

- [ ] **Step 4: Run the repository-wide suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-tmp-task7-all
```

Expected: exit code 0 with every collected test passing and zero skips. Report the real count and all warnings.

- [ ] **Step 5: Check public signatures, schema, and existing type reuse**

Run:

```powershell
@'
from dataclasses import fields
import inspect

from coding_agent.messages import ToolResultMetadata
from coding_agent.tools.base import ExecutionContext, ToolExecution
from coding_agent.tools.registry import ToolRegistry
from coding_agent.tools.shell import RunCommandTool, parse_windows_command_line

assert [field.name for field in fields(ExecutionContext)] == [
    "workspace",
    "command_timeout_seconds",
]
assert inspect.signature(parse_windows_command_line).parameters.keys() == {"command"}.keys()
assert list(inspect.signature(RunCommandTool.execute).parameters) == [
    "self",
    "arguments",
    "context",
]
assert RunCommandTool.schema["strict"] is True
parameters = RunCommandTool.schema["parameters"]
assert parameters["required"] == ["command", "purpose"]
assert parameters["additionalProperties"] is False
assert "timeout" not in parameters["properties"]
execution = ToolExecution(metadata=ToolResultMetadata())
assert type(execution.metadata) is ToolResultMetadata
assert ToolRegistry([RunCommandTool()]).schemas == (RunCommandTool.schema,)
print("Task 7 signatures, schema, registry, and type reuse verified")
'@ | .\.venv\Scripts\python.exe -
```

Expected: exit code 0 and the single verification line. No duplicate `ToolExecution`, `ToolResult`, or metadata class exists.

- [ ] **Step 6: Check deterministic launch, cwd, output, timeout, and tree-cleanup evidence**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "launch_uses or fixed_workspace or nonzero or 64_kib or simultaneous_streams or timeout_returns or process_tree or cleanup_failure" -q --basetemp=.pytest-tmp-task7-semantics
Select-String -Path src/coding_agent/tools/shell.py -Pattern 'shell=True|os\.chdir|str\.split|shlex'
Select-String -Path src/coding_agent/tools/shell.py -Pattern 'shell=False|CommandLineToArgvW|taskkill\.exe|_OUTPUT_LIMIT_BYTES'
```

Expected: selected semantic tests exit 0 with zero skips; the forbidden-pattern command returns no matches; the positive-pattern command shows the native parser, explicit `shell=False` launch sites, fixed taskkill executable, and byte-limit constant.

- [ ] **Step 7: Check the temporary boundary and deferred Task 8/Task 11 scope**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/tools/test_shell_tool.py -k "temporary_boundary or api_key" -q --basetemp=.pytest-tmp-task7-boundary
git diff --name-only
git diff -- src/coding_agent/config.py src/coding_agent/tools/registry.py src/coding_agent/tools/filesystem.py src/coding_agent/agent.py src/coding_agent/state.py src/coding_agent/cli.py pyproject.toml
Select-String -Path src/coding_agent/tools/shell.py -Pattern 'PathGuard|CommandPolicy|VerificationGate|PASSED|powershell\.exe|cmd\.exe|bash|wsl|pip install|git commit|git push'
```

Expected: boundary/API-key tests pass; changed files are only `TASKS.md`, `src/coding_agent/tools/base.py`, `src/coding_agent/tools/shell.py`, `tests/tools/test_shell_tool.py`, and this plan; protected-file diff is empty; deferred-feature scan is empty. The word `taskkill.exe` is expected only as the fixed internal cleanup executable and is not a model-facing command.

- [ ] **Step 8: Check dependencies and credentials**

Run:

```powershell
git diff -- pyproject.toml
.\.venv\Scripts\python.exe -c "import ast, pathlib; tree=ast.parse(pathlib.Path('src/coding_agent/tools/shell.py').read_text(encoding='utf-8')); imports={node.names[0].name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import)} | {node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}; allowed={'__future__','codecs','collections','ctypes','dataclasses','json','os','pathlib','subprocess','sys','threading','time','typing','coding_agent'}; assert imports <= allowed, imports-allowed; print('standard-library dependency boundary verified')"
git grep -n -I -E "sk-[A-Za-z0-9_-]{16,}|Bearer[[:space:]]+[A-Za-z0-9._-]{16,}" -- . ":!docs/superpowers/plans/Task7.md"
```

Expected: `pyproject.toml` diff is empty; AST dependency command exits 0; credential grep returns no matches. The synthetic text `must-not-reach-child` is not a credential and remains only in a test.

- [ ] **Step 9: Scan source/tests for unfinished or disabled behavior**

Run:

```powershell
$unfinished = @(
    ('TO' + 'DO'),
    ('TB' + 'D'),
    ('NotImplemented' + 'Error'),
    'pytest\.skip',
    '@pytest\.mark\.skip',
    '@pytest\.mark\.xfail'
) -join '|'
git grep -n -E $unfinished -- src tests
```

Expected: no matches. If any existing baseline match predates Task 7, record its exact commit provenance and ask the user rather than deleting unrelated code.

- [ ] **Step 10: Inspect whitespace, status, and the complete diff**

Run:

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff -- TASKS.md src/coding_agent/tools/base.py src/coding_agent/tools/shell.py tests/tools/test_shell_tool.py docs/superpowers/plans/Task7.md
```

Expected: `git diff --check` exits 0; status lists only the approved plan and Task 7 implementation files; the complete diff contains no Task 8 policy, Task 11 gate, CLI integration, unrelated formatting, dependency change, secret, network call, or weakened test.

- [ ] **Step 11: Record the Task 7 acceptance matrix**

Use fresh output from the commands above; do not substitute planned test counts:

| Acceptance item | Required evidence |
|---|---|
| Strict schema and exact local arguments | schema/invalid-argument tests |
| Timeout hidden from the model | schema assertion plus `ExecutionContext` tests |
| Windows spaces, quotes, empty args, backslashes, Unicode | parser round-trip tests |
| Argument-array execution and `shell=False` | recording process-factory test and source scan |
| Temporary Python-only command boundary | approved/rejected entry-point tests |
| Fixed normalized workspace cwd, no global cwd change | cwd tests and `os.chdir` scan |
| API key omitted from child environment | child observation and launch-kwargs tests |
| Stable UTF-8 plus invalid-byte behavior | Unicode and invalid-byte tests |
| Separate stdout/stderr and nonzero exit preservation | stream and registry nonzero tests |
| 65,536-byte independent prefix limits | exact, over-limit, dual-limit tests |
| Large dual streams cannot deadlock | simultaneous-stream test |
| Timeout returns partial output, null exit, duration | timeout tests |
| Whole Windows process tree terminates | child marker remains absent |
| Cleanup failure cannot erase timeout | injected cleanup-failure test |
| Startup failure is stable and nonsecret | process-factory error matrix |
| User interrupt is not swallowed | `KeyboardInterrupt` propagation test |
| Registry compatibility and type reuse | signature/type script |
| Offline and no new dependencies | import, AST, and `pyproject.toml` checks |
| Task 8 and Task 11 remain absent | scope scans and complete diff review |
| No disabled tests or unfinished code | source/test scan |
| No Task 2-6 regression | targeted suites and full suite |

If any row lacks evidence, leave Task 7 `进行中`, report the exact gap, and stop.

- [ ] **Step 12: Stop for user review and authorization**

Do not change Task 7 to `已完成`. Do not stage or commit. Report every RED/GREEN command and actual exit/result count, final test commands and counts, warnings/skips/failures, the acceptance matrix, changed files, and `git status`. Wait for the user to inspect and separately authorize Task 7 completion and commit.

**Acceptance:** every matrix row has fresh evidence, the full suite passes with no Task 7 skip, the diff stays inside scope, and the worktree remains uncommitted for review.

---

## Plan self-review

- **Task 7 requirement coverage:** every `TASKS.md` item maps to a named test and a final matrix row: schema, parsing, vector execution, cwd, timeout, separate bounded streams, nonzero exit, process-tree cleanup, duration, and offline behavior.
- **Parsing specificity:** the plan names `CommandLineToArgvW`, supplies its `ctypes` signatures, native-memory release, unclosed-quote scanner, and exact argument round trips.
- **Process-tree specificity:** the plan supplies the fixed `taskkill.exe /PID /T /F` array, flags, 10-second cleanup timeout, parent fallback, error strings, and a descendant side-effect test.
- **Deadlock and memory bound:** two simultaneous draining threads retain only 65,536 raw bytes per stream while discarding later drained bytes.
- **Unique truncation semantics:** each stream retains its prefix; exactly 65,536 bytes is complete; either stream's next byte sets the shared metadata bit; incomplete truncated UTF-8 tails are omitted.
- **Nonzero semantics:** a started process with exit 7 remains registry status `ok` and exposes 7 unchanged.
- **Credential isolation:** both child observation and captured Popen kwargs prove `OPENAI_API_KEY` removal; no environment is serialized.
- **Dependency and offline boundary:** only standard-library modules and existing project types are used; `pyproject.toml` remains unchanged.
- **Scope:** no complete Task 8 policy, complete path guard, Task 11 verification gate, CLI integration, model provider, network capability, logger, or report is introduced.
- **TDD ordering:** Tasks 1-8 each identify a missing behavior, exact RED command/reason, minimal GREEN code, GREEN command, and Task 2-6 regression command. Task 9 only verifies the resulting implementation.
- **Type consistency:** `RunCommandTool.execute`, `ExecutionContext.command_timeout_seconds`, `parse_windows_command_line`, `ProcessFactory`, `TreeTerminator`, `_json_output`, and every test call use one spelling and signature throughout.
- **Placeholder scan:** the implementation instructions contain concrete code, commands, error strings, and results; no ambiguous implementation step remains.
- **Approval boundary:** execution stops with Task 7 `进行中`; source-control and Task 8 work require later user authorization.

# Task 8 Unified Workspace and Command Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`, `superpowers:test-driven-development`, and `superpowers:verification-before-completion` to implement this plan task-by-task. Use `superpowers:systematic-debugging` before changing code for any reproducible unexpected failure. Do not use subagents, parallel agents, branches, or worktrees.

**Goal:** Replace the temporary Task 5–7 path and command checks with one deterministic Windows-first `PathGuard` and `CommandPolicy`, and authorize user-provided `--verify` commands before agent startup.

**Architecture:** Tool schemas continue to reject malformed JSON arguments locally. After schema-level validation, every filesystem entry point delegates path authorization to `PathGuard`, every command entry point delegates parsing and authorization to `CommandPolicy`, and only the returned guarded path or authorized argv may reach local I/O. A typed `SafetyViolation` carries a stable `SafetyCode`; `ToolRegistry` maps that exception to a distinguishable rejected result without changing the Task 2 message types, while CLI configuration maps it to a redacted exit-code-2 error.

**Tech Stack:** Python 3.11+, standard library only (`ctypes`, `dataclasses`, `enum`, `os`, `pathlib`, `shutil`, `stat`, `subprocess`, `sys`), pytest, Windows `CommandLineToArgvW`, Windows file attributes, and real Windows symlink/junction fixtures where the host permits them.

**Spec:** `DESIGN.md` sections 12–16 and `TASKS.md` Task 8, with `AGENTS.md` as the repository-level development policy.

## Global constraints

- Work only in `D:\code\coding_agent` on the current `main` worktree; do not create a branch or worktree.
- Do not stage, commit, push, or access a remote repository while executing this plan. After verification, wait for user review and authorization.
- Only Task 8 is in scope. Do not implement the OpenAI client, context compression, formal termination, Task 11 `VerificationGate`, JSONL logging, final reporting, CLI agent execution, or an OS sandbox.
- Add no dependency and do not access the network or a real API key.
- Keep `messages.py`, `model.py`, `state.py`, `agent.py`, and `pyproject.toml` unchanged.
- Keep the existing strict tool schemas, 256 KiB read limit, 512 KiB write limit, 64 KiB-per-stream command limit, timeout behavior, process-tree cleanup, and mutation-ledger behavior unchanged.
- Every production behavior follows RED → minimal GREEN → Task 2–7 regression before the next behavior.
- Windows reparse acceptance cannot be completed through a permanent skip or xfail. If a real file symlink cannot be created, the implementation remains unverified even though the pure policy and junction tests still run.

---

## Locked file map

**Create**

- `src/coding_agent/safety.py` — safety error types, guarded path value, `PathGuard`, Windows command parsing, trusted executable discovery, authorized command value, and `CommandPolicy`.
- `tests/test_path_safety.py` — lexical, containment, protected-directory, symlink, junction, reparse, dangling-link, and link-chain tests.
- `tests/test_command_safety.py` — parser, executable, argument, Python/test/linter/Git, control syntax, source, purpose, and environment-boundary tests.

**Modify**

- `src/coding_agent/tools/registry.py` — one catch branch for typed `SafetyViolation` before the existing `ToolArgumentError` branch.
- `src/coding_agent/tools/filesystem.py` — remove `_functional_workspace_path()` and delegate all list/read/replace/write targets and list children to `PathGuard`.
- `src/coding_agent/tools/shell.py` — re-export the moved parser, remove `_normalized_workspace()`, `_same_path()`, and `_authorize_temporary_command()`, execute only `AuthorizedCommand.argv`, and harden the child environment.
- `src/coding_agent/config.py` — store `AuthorizedCommand | None`, authorize `--verify` during configuration loading, and keep command text out of repr/errors.
- `src/coding_agent/cli.py` — preserve exit code 2 for configuration rejection and update help text; do not start an agent or execute verification.
- `tests/test_cli.py` — update the `RunConfig` contract and add startup authorization/rejection tests.
- `tests/tools/test_read_tools.py` — retain Task 5 behavior and add unified-policy/protected/list-filter tests.
- `tests/tools/test_write_tools.py` — retain Task 6 behavior and add unified-policy/protected/reparse zero-side-effect tests.
- `tests/tools/test_shell_tool.py` — preserve Task 7 execution behavior while replacing temporary-boundary assertions with `CommandPolicy` assertions.
- `tests/test_agent_loop.py` — add one stable safety-rejection/zero-ledger regression; do not alter Agent interfaces.
- `TASKS.md` — during execution only, after Task 0 passes, change Task 7 from `进行中` to `已完成` and Task 8 from `未开始` to `进行中`; Task 8 remains `进行中` at the final stop.

**Must remain unchanged**

- `src/coding_agent/messages.py`
- `src/coding_agent/model.py`
- `src/coding_agent/state.py`
- `src/coding_agent/agent.py`
- `src/coding_agent/tools/base.py`
- `pyproject.toml`

`tools/registry.py` is the only otherwise-principled exception: the current registry flattens all `ToolArgumentError` values into `invalid_arguments`, so a minimal earlier `SafetyViolation` catch is required to distinguish deterministic security rejection without changing Task 2 `ToolResult` or `ToolResultMetadata`.

## Locked security call chains

```text
Model ToolCall
→ ToolRegistry dispatch
→ strict schema and functional argument validation
→ PathGuard or CommandPolicy authorization
→ guarded absolute path or authorized argv only
→ local filesystem/subprocess execution
→ ToolExecution
→ ToolResult
```

```text
CLI argv
→ argparse
→ load_run_config
→ canonical workspace
→ `CommandPolicy.authorize(command, purpose="verification", source=CommandSource.USER_VERIFY)`
→ RunConfig stores AuthorizedCommand
→ configuration success
```

- Format/type/schema errors remain `ToolArgumentError` and map to the existing `invalid_arguments: <detail>` rejected-result format.
- Safety decisions raise `SafetyViolation(code, public_message)` and map to `ToolResult(status="rejected", error="security_rejected:<code>: <public_message>")`.
- The typed exception exposes `exc.code`; Task 12 logging can record that enum at the Registry catch point without parsing message prose. Task 8 does not add the logger.
- CLI catches the same typed rejection inside `load_run_config` and raises `ConfigError("--verify rejected (<code>): <public_message>")` without echoing the supplied command, absolute executable, environment, or credentials.
- `purpose` and `source` are validated and recorded but never widen the executable or argument allowlist.

## Locked public interfaces

The final public names and signatures are locked as follows:

- `SafetyCode(StrEnum)` has exactly the 13 values listed in Task 1's complete code block.
- `SafetyViolation.__init__(self, code: SafetyCode, public_message: str) -> None`; public attributes are `code` and `public_message`.
- `GuardedPath` is `@dataclass(frozen=True, slots=True)` with `absolute: Path` and `relative: str`.
- `PathGuard.__init__(self, workspace: Path) -> None`.
- `PathGuard.workspace(self) -> Path` is a read-only property.
- `PathGuard.existing_entry(self, raw_path: object) -> GuardedPath`.
- `PathGuard.existing_file(self, raw_path: object) -> GuardedPath`.
- `PathGuard.existing_directory(self, raw_path: object) -> GuardedPath`.
- `PathGuard.new_file(self, raw_path: object) -> GuardedPath`.
- `CommandSource(StrEnum)` has `MODEL = "model"` and `USER_VERIFY = "user_verify"`.
- `AuthorizedCommand` is `@dataclass(frozen=True, slots=True)` with `argv: tuple[str, ...]`, `normalized_command: str`, `purpose: str`, and `source: CommandSource`.
- `ExecutableLocator = Callable[[str], str | None]`.
- `CommandPolicy.__init__(self, workspace: Path, *, executable_locator: ExecutableLocator | None = None) -> None`.
- `CommandPolicy.workspace(self) -> Path` is a read-only property.
- `CommandPolicy.authorize(self, command: object, *, purpose: str, source: CommandSource) -> AuthorizedCommand`.
- `parse_windows_command_line(command: object) -> tuple[str, ...]`.

`parse_windows_command_line` moves from `tools/shell.py` to `safety.py`; `tools/shell.py` imports and re-exports it so the Task 7 import path remains valid. `CommandPolicy` returns the only argv that `RunCommandTool` may execute. `AuthorizedCommand.normalized_command` is created with `subprocess.list2cmdline(argv)` for deterministic internal evidence but is never included in `RunConfig.__repr__` or configuration errors.

## Locked PathGuard semantics

- Normalize and validate the workspace with `Path.resolve(strict=True)`, require a directory, and reject a workspace root that is itself a symlink/reparse point.
- Interpret model paths with `PureWindowsPath` in addition to `Path`; `Path.is_absolute()` alone is insufficient on Windows because drive-relative (`C:foo`), UNC, device, extended-length, and rooted-without-drive inputs have distinct forms.
- Accept safe mixed `/` and `\` separators and normalize output to POSIX `/`; accept `.` as the workspace root. Reject empty/whitespace, NUL, any `..` component, absolute/rooted/drive/UNC/device/extended paths, alternate data stream `:`, components ending in a dot or space, and Windows reserved device names.
- Match `.git` and `.coding-agent` case-insensitively in **any** normalized component. Do not reject `.gitignore`, `my.git`, or `.coding-agent-notes`.
- Reject every symlink, junction, or other reparse point in a model-accessible path, even when its target remains inside the workspace. This is deliberately more conservative than resolve-and-contain alone: it removes link-chain ambiguity, gives list/read/write the same rule, and reduces TOCTOU exposure.
- Inspect every existing component with `os.lstat()`. On Windows, reject when `st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT` is nonzero; also reject `Path.is_symlink()` so dangling file links are covered.
- After component inspection, call `resolve(strict=True)` for existing entries/parents and verify containment with `os.path.commonpath()` plus `os.path.normcase()`. Catch different-drive `ValueError`. Never use string-prefix containment.
- `existing_file` and `existing_directory` enforce the target type. `new_file` requires a nonexistent target and an existing real directory parent; it authorizes the parent, then returns `parent.absolute / leaf` and the normalized relative path.
- List traversal asks `PathGuard.existing_entry()` about every child. Protected and reparse children are omitted, not revealed or recursed into; unexpected disappearance/type errors remain deterministic rejections.
- The check is immediately before I/O and `write_file` retains exclusive `xb` creation. Task 8 does not claim race-free isolation against a malicious concurrent local process.

## Locked command allow/deny matrix

| Category | Allowed exact forms | Locked argument policy | Rejected examples |
| --- | --- | --- | --- |
| Current Python | bare `python`/`python.exe` rewritten to resolved `sys.executable`, or an absolute executable equal under `normcase(resolve())` to `sys.executable` | Existing workspace `.py` script through `PathGuard`; simple script args only; or exact `-m pytest` / `-m unittest` | `py`, another Python, `-c`, `-`, unknown `-m`, outside/protected/reparse script |
| pytest | trusted `pytest`/`pytest.exe`, or current Python `-m pytest` | `-q`, `--quiet`, `-v`, `--verbose`, `-x`, `--exitfirst`, `--disable-warnings`, `--strict-markers`, `--strict-config`, numeric `--maxfail`, fixed `--tb`, `-k`/`-m` expression, `--help`, `--version`, and guarded workspace node/path selectors | `-p`, `-c`, `--override-ini`, `--rootdir`, `--confcutdir`, `--basetemp`, `--pyargs`, response files, outside/parent/protected paths |
| unittest | current Python `-m unittest` only | no args; `-q`, `-v`, `-f`, `-b`, `--locals`, `--help`, `-k <pattern>`; safe dotted test names or guarded `.py`; `discover` with guarded `-s`/`-t` and separator-free `-p` glob | standalone `unittest`, response files, absolute/outside/parent/protected paths, unknown flags |
| ruff | trusted `ruff`/`ruff.exe` | `--help`, `--version`, or `check`; policy inserts `--isolated`; read-only check flags and guarded existing file/dir paths; no path means `.` | `format`, `--fix`, `--unsafe-fixes`, `--add-noqa`, `--config`, response files, outside paths |
| mypy | trusted `mypy`/`mypy.exe` | `--help`, `--version`, or guarded `.py`/directory targets with the listed diagnostic flags; policy inserts fixed `--config-file=NUL --no-incremental` | user config/plugin/python executable/cache/install flags, response files, outside paths |
| Git | trusted `git`/`git.exe` plus exact lower-case `status`, `diff`, `log`, `show`, or `ls-files` | per-subcommand read-only option allowlists; guarded pathspec only after `--`; policy inserts `--no-pager`, and diff-producing forms insert `--no-ext-diff --no-textconv` | `add`, `commit`, `checkout`, `switch`, `reset`, `clean`, `push`, `fetch`, `pull`, `clone`, `config`, `-c`, `--config-env`, pager, external diff/textconv, output files, unknown subcommands/options |
| Shell/system/network | none | none | PowerShell, cmd, Bash, sh, WSL, curl, wget, ssh, pip, npm, winget, taskkill, reg, sc, net, del, erase, move, copy, robocopy, unknown executable |
| Control syntax | none | raw command is rejected before parsing if it contains `&`, `|`, `>`, `<`, CR, LF, or NUL, even inside quotes | redirection, pipelines, chaining, multiline input |

Executable resolution is deterministic: Python aliases map directly to the current interpreter; `pytest`, `ruff`, and `mypy` first resolve exact launcher names in `Path(sys.executable).parent`, then use `shutil.which()` with empty/relative/workspace PATH entries removed; Git uses only that sanitized PATH lookup. Absolute launcher input is accepted only when it resolves to the same trusted target. Comparisons use resolved paths and `normcase`; `.exe` suffix and executable name matching are case-insensitive. A workspace lookalike executable is never trusted. If a requested trusted launcher is not installed at a trusted location, authorization fails with `executable_denied` rather than broadening lookup.

For all child commands, remove `OPENAI_API_KEY`, `PYTHONPATH`, `PYTHONHOME`, `PYTEST_ADDOPTS`, `PYTEST_PLUGINS`, `MYPYPATH`, `MYPY_CONFIG_FILE`, `GIT_DIR`, `GIT_WORK_TREE`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_EXTERNAL_DIFF`, `GIT_SSH`, `GIT_SSH_COMMAND`, `GIT_ASKPASS`, `SSH_ASKPASS`, and all `GIT_CONFIG_KEY_*`/`GIT_CONFIG_VALUE_*`/`GIT_CONFIG_COUNT` values case-insensitively. Set `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, `PYTHONUNBUFFERED=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=NUL`, `GIT_PAGER=cat`, `PAGER=cat`, `GIT_TERMINAL_PROMPT=0`, and `GIT_NO_LAZY_FETCH=1`. This blocks parent-environment and Git lazy-network widening while preserving the explicit first-version assumption that selected workspace scripts, pytest configuration, and conftest code are trusted workspace code. Model-supplied pytest `-p`/`-c`/config options remain denied.

---

### Task 0: Reconfirm the approved Task 7 baseline

**Files:** Read only; after all checks pass, modify only the two status values in `TASKS.md`.

**Interfaces:** No production interface change.

- [ ] **Step 1: Re-read the complete baseline**

Read `AGENTS.md`, `DESIGN.md`, `TASKS.md`, Task 4–7 plans, all source files listed in the user request, `tests/test_cli.py`, `tests/test_agent_loop.py`, and every Task 5–7 test. Record these replacement points before editing:

```text
filesystem.py:_functional_workspace_path -> PathGuard methods
shell.py:_normalized_workspace/_same_path/_authorize_temporary_command -> CommandPolicy
shell.py:parse_windows_command_line implementation -> safety.py plus shell re-export
config.py:RunConfig.verify_command str | None -> AuthorizedCommand | None
```

- [ ] **Step 2: Verify repository identity and cleanliness**

Run:

```powershell
Set-Location D:\code\coding_agent
git rev-parse --show-toplevel
git branch --show-current
git log -3 --oneline
git status --short --untracked-files=all
git diff --check
```

Expected: root is `D:/code/coding_agent`, branch is `main`, latest commit is the approved Task 7 commit, status is empty except the approved `docs/superpowers/plans/Task8.md` if it is untracked, and `git diff --check` exits 0. A global-ignore permission warning is reportable but does not alter the worktree result.

- [ ] **Step 3: Verify the Task 7 baseline tests before changing status**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\test_agent_loop.py tests\test_cli.py -q
```

Expected: exit 0 with actual pass/fail/skip/warning counts reported. Any failure stops execution.

- [ ] **Step 4: Update only Task 7 and Task 8 statuses**

Edit `TASKS.md` so Task 7 is `已完成`, Task 8 is `进行中`, and every other task retains its current value. Run:

```powershell
Select-String -Path TASKS.md -Pattern '已完成|进行中|未开始'
```

Expected: exactly Task 8 is `进行中`. Do not stage or commit.

**Acceptance:** Task 7 is committed and green, the baseline is clean apart from the approved plan, and only Task 8 becomes in progress.

---

### Task 1: Stable safety errors, workspace initialization, and Registry mapping

**Files:**

- Create: `src/coding_agent/safety.py`
- Create: `tests/test_path_safety.py`
- Modify: `src/coding_agent/tools/registry.py`
- Modify: `tests/test_agent_loop.py`

**Interfaces:** Produces `SafetyCode`, `SafetyViolation`, `GuardedPath`, and the `PathGuard.workspace` contract. Consumes existing `ToolArgumentError`, `ToolCall`, `ToolResult`, and `ToolRegistry` without redefining them.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_path_safety.py` with these imports and tests:

```python
from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace
from typing import Callable

import pytest

from coding_agent.safety import (
    GuardedPath,
    PathGuard,
    SafetyCode,
    SafetyViolation,
)


def _assert_violation(
    code: SafetyCode,
    operation: Callable[[], object],
) -> SafetyViolation:
    with pytest.raises(SafetyViolation) as exc_info:
        operation()
    assert exc_info.value.code is code
    assert str(exc_info.value).startswith(f"{code.value}: ")
    assert "OPENAI_API_KEY" not in str(exc_info.value)
    return exc_info.value


def test_safety_codes_are_stable_strings() -> None:
    assert {code.value for code in SafetyCode} == {
        "invalid_path",
        "workspace_invalid",
        "path_outside_workspace",
        "path_not_found",
        "path_type_mismatch",
        "parent_not_found",
        "protected_path",
        "reparse_point_denied",
        "command_parse_error",
        "shell_syntax_denied",
        "executable_denied",
        "argument_denied",
        "git_subcommand_denied",
    }


def test_path_guard_normalizes_a_real_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    guard = PathGuard(workspace / ".")

    assert guard.workspace == workspace.resolve()


def test_path_guard_rejects_missing_or_file_workspace(tmp_path: Path) -> None:
    _assert_violation(
        SafetyCode.WORKSPACE_INVALID,
        lambda: PathGuard(tmp_path / "missing"),
    )
    file_path = tmp_path / "workspace.txt"
    file_path.write_text("x", encoding="utf-8")
    _assert_violation(
        SafetyCode.WORKSPACE_INVALID,
        lambda: PathGuard(file_path),
    )
```

Append this complete test to `tests/test_agent_loop.py`:

```python
def test_registry_distinguishes_stable_safety_rejection(tmp_path: Path) -> None:
    class SafetyRejectingTool:
        name = "safety_reject"
        schema: JSONObject = {
            "name": "safety_reject",
            "description": "Reject for a deterministic safety reason.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        }

        def execute(
            self,
            arguments: JSONObject,
            context: ExecutionContext,
        ) -> ToolExecution:
            from coding_agent.safety import SafetyCode, SafetyViolation

            raise SafetyViolation(
                SafetyCode.PROTECTED_PATH,
                "protected path is unavailable",
            )

    registry = ToolRegistry((SafetyRejectingTool(),))
    result = registry.execute(
        ToolCall(call_id="safe_1", name="safety_reject", arguments={}),
        ExecutionContext(tmp_path),
    )

    assert result.status == "rejected"
    assert result.error == (
        "security_rejected:protected_path: protected path is unavailable"
    )
    assert result.metadata.changed_paths == ()
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\test_agent_loop.py::test_registry_distinguishes_stable_safety_rejection -q
```

Expected: nonzero exit because `coding_agent.safety` does not exist. This import failure is the planned RED for a new module; any syntax/fixture failure stops the step.

- [ ] **Step 3: Add the minimal production types and mapping**

Create the initial `src/coding_agent/safety.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import stat

from coding_agent.tools.base import ToolArgumentError


class SafetyCode(StrEnum):
    INVALID_PATH = "invalid_path"
    WORKSPACE_INVALID = "workspace_invalid"
    PATH_OUTSIDE_WORKSPACE = "path_outside_workspace"
    PATH_NOT_FOUND = "path_not_found"
    PATH_TYPE_MISMATCH = "path_type_mismatch"
    PARENT_NOT_FOUND = "parent_not_found"
    PROTECTED_PATH = "protected_path"
    REPARSE_POINT_DENIED = "reparse_point_denied"
    COMMAND_PARSE_ERROR = "command_parse_error"
    SHELL_SYNTAX_DENIED = "shell_syntax_denied"
    EXECUTABLE_DENIED = "executable_denied"
    ARGUMENT_DENIED = "argument_denied"
    GIT_SUBCOMMAND_DENIED = "git_subcommand_denied"


class SafetyViolation(ToolArgumentError):
    def __init__(self, code: SafetyCode, public_message: str) -> None:
        self.code = code
        self.public_message = public_message
        super().__init__(f"{code.value}: {public_message}")


@dataclass(frozen=True, slots=True)
class GuardedPath:
    absolute: Path
    relative: str


class PathGuard:
    def __init__(self, workspace: Path) -> None:
        try:
            normalized = Path(workspace).resolve(strict=True)
        except OSError as exc:
            raise SafetyViolation(
                SafetyCode.WORKSPACE_INVALID,
                "workspace must be an existing directory",
            ) from exc
        if not normalized.is_dir():
            raise SafetyViolation(
                SafetyCode.WORKSPACE_INVALID,
                "workspace must be an existing directory",
            )
        self._workspace = normalized

    @property
    def workspace(self) -> Path:
        return self._workspace
```

Modify `src/coding_agent/tools/registry.py` imports and exception order exactly as follows:

```python
from coding_agent.safety import SafetyViolation

# inside execute(), before ``except ToolArgumentError``
        except SafetyViolation as exc:
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                status="rejected",
                error=(
                    f"security_rejected:{exc.code.value}: "
                    f"{exc.public_message}"
                ),
            )
```

This import is one-way: `safety.py` imports `tools.base`, not Registry, so no cycle is introduced.

- [ ] **Step 4: Run GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\test_agent_loop.py::test_registry_distinguishes_stable_safety_rejection -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_cli.py -q
```

Expected: both commands exit 0. Report actual counts. Existing bad arguments still produce `invalid_arguments`, unknown tools remain unchanged, and the new safety rejection produces the canonical `security_rejected` prefix.

**Acceptance:** Safety codes are stable `StrEnum` values, messages are non-sensitive, Task 2 types are unchanged, and Registry distinguishes format rejection from safety rejection.

---

### Task 2: Lexical Windows path validation and containment

**Files:** Modify `src/coding_agent/safety.py` and `tests/test_path_safety.py`.

**Interfaces:** Implements the common lexical/containment path pipeline used by all four public `PathGuard` methods.

- [ ] **Step 1: Append the failing tests**

```python
@pytest.mark.parametrize(
    ("raw_path", "code"),
    [
        (None, SafetyCode.INVALID_PATH),
        (7, SafetyCode.INVALID_PATH),
        ("", SafetyCode.INVALID_PATH),
        ("   ", SafetyCode.INVALID_PATH),
        ("bad\x00name", SafetyCode.INVALID_PATH),
        ("../outside.txt", SafetyCode.PATH_OUTSIDE_WORKSPACE),
        (r"folder\..\outside.txt", SafetyCode.PATH_OUTSIDE_WORKSPACE),
        ("/outside.txt", SafetyCode.PATH_OUTSIDE_WORKSPACE),
        (r"\rooted.txt", SafetyCode.PATH_OUTSIDE_WORKSPACE),
        (r"C:\outside.txt", SafetyCode.PATH_OUTSIDE_WORKSPACE),
        (r"C:outside.txt", SafetyCode.PATH_OUTSIDE_WORKSPACE),
        (r"\\server\share\file.txt", SafetyCode.PATH_OUTSIDE_WORKSPACE),
        (r"\\?\C:\file.txt", SafetyCode.PATH_OUTSIDE_WORKSPACE),
        (r"\\.\PhysicalDrive0", SafetyCode.PATH_OUTSIDE_WORKSPACE),
        ("file.txt:secret", SafetyCode.INVALID_PATH),
        ("folder. /file.txt", SafetyCode.INVALID_PATH),
        ("CON", SafetyCode.INVALID_PATH),
    ],
)
def test_path_guard_rejects_unsafe_windows_path_forms(
    tmp_path: Path,
    raw_path: object,
    code: SafetyCode,
) -> None:
    guard = PathGuard(tmp_path)
    _assert_violation(code, lambda: guard.existing_entry(raw_path))


def test_path_guard_accepts_mixed_separators_and_normalizes_case_preserving_output(
    tmp_path: Path,
) -> None:
    target = tmp_path / "Folder" / "Child.txt"
    target.parent.mkdir()
    target.write_text("ok", encoding="utf-8")

    guarded = PathGuard(tmp_path).existing_entry(r"Folder/./Child.txt")

    assert guarded == GuardedPath(
        absolute=target.resolve(),
        relative="Folder/Child.txt",
    )


def test_path_guard_accepts_dot_as_workspace_entry(tmp_path: Path) -> None:
    guarded = PathGuard(tmp_path).existing_entry(".")
    assert guarded == GuardedPath(tmp_path.resolve(), ".")


def test_commonpath_different_drive_maps_to_outside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = PathGuard(tmp_path)

    def different_drive(paths: object) -> str:
        raise ValueError("Paths don't have the same drive")

    monkeypatch.setattr("coding_agent.safety.os.path.commonpath", different_drive)
    _assert_violation(
        SafetyCode.PATH_OUTSIDE_WORKSPACE,
        lambda: guard.existing_entry("missing.txt"),
    )
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py -q
```

Expected: nonzero exit because `PathGuard.existing_entry` is not implemented.

- [ ] **Step 3: Add minimal lexical and containment helpers**

Add these imports and constants to `safety.py`:

```python
from pathlib import Path, PureWindowsPath

_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}
```

Add these methods to `PathGuard`:

```python
    def _relative_parts(self, raw_path: object) -> tuple[str, ...]:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise SafetyViolation(SafetyCode.INVALID_PATH, "path is invalid")
        if "\x00" in raw_path:
            raise SafetyViolation(SafetyCode.INVALID_PATH, "path is invalid")
        windows_path = PureWindowsPath(raw_path)
        if windows_path.drive or windows_path.root or windows_path.is_absolute():
            raise SafetyViolation(
                SafetyCode.PATH_OUTSIDE_WORKSPACE,
                "path must remain inside the workspace",
            )
        normalized: list[str] = []
        for part in windows_path.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                raise SafetyViolation(
                    SafetyCode.PATH_OUTSIDE_WORKSPACE,
                    "path must remain inside the workspace",
                )
            folded = part.casefold()
            stem = folded.split(".", 1)[0]
            if (
                ":" in part
                or part.endswith((".", " "))
                or stem in _RESERVED_NAMES
            ):
                raise SafetyViolation(SafetyCode.INVALID_PATH, "path is invalid")
            normalized.append(part)
        return tuple(normalized)

    def _contained(self, candidate: Path) -> None:
        try:
            common = os.path.commonpath((str(self._workspace), str(candidate)))
        except ValueError as exc:
            raise SafetyViolation(
                SafetyCode.PATH_OUTSIDE_WORKSPACE,
                "path must remain inside the workspace",
            ) from exc
        if os.path.normcase(common) != os.path.normcase(str(self._workspace)):
            raise SafetyViolation(
                SafetyCode.PATH_OUTSIDE_WORKSPACE,
                "path must remain inside the workspace",
            )

    def _relative_text(self, absolute: Path) -> str:
        relative = absolute.relative_to(self._workspace)
        return "." if not relative.parts else relative.as_posix()

    def existing_entry(self, raw_path: object) -> GuardedPath:
        parts = self._relative_parts(raw_path)
        candidate = self._workspace.joinpath(*parts)
        self._contained(candidate)
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise SafetyViolation(
                SafetyCode.PATH_NOT_FOUND,
                "path does not exist",
            ) from exc
        except OSError as exc:
            raise SafetyViolation(SafetyCode.INVALID_PATH, "path is invalid") from exc
        self._contained(resolved)
        return GuardedPath(resolved, self._relative_text(resolved))
```

The `commonpath` test monkeypatch must be reached before the missing-target check; therefore `_contained(candidate)` stays before `resolve(strict=True)`.

- [ ] **Step 4: Run GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_cli.py -q
```

Expected: both exit 0 with actual counts. Mixed separators normalize to `/`, and every Windows absolute/drive/UNC/device/parent form is rejected without absolute path leakage.

**Acceptance:** Path semantics are Windows-aware, containment uses resolved `commonpath`/`normcase`, and no string-prefix check exists.

---

### Task 3: Existing file/directory and new-file contracts

**Files:** Modify `src/coding_agent/safety.py` and `tests/test_path_safety.py`.

**Interfaces:** Completes `existing_file`, `existing_directory`, and `new_file`.

- [ ] **Step 1: Append the failing tests**

```python
def test_existing_file_and_directory_enforce_target_type(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.txt"
    file_path.write_text("text", encoding="utf-8")
    directory = tmp_path / "folder"
    directory.mkdir()
    guard = PathGuard(tmp_path)

    assert guard.existing_file("notes.txt").absolute == file_path.resolve()
    assert guard.existing_directory("folder").absolute == directory.resolve()
    _assert_violation(
        SafetyCode.PATH_TYPE_MISMATCH,
        lambda: guard.existing_file("folder"),
    )
    _assert_violation(
        SafetyCode.PATH_TYPE_MISMATCH,
        lambda: guard.existing_directory("notes.txt"),
    )


def test_new_file_returns_real_parent_join_and_normalized_relative(tmp_path: Path) -> None:
    parent = tmp_path / "Folder"
    parent.mkdir()

    guarded = PathGuard(tmp_path).new_file(r"Folder\new.py")

    assert guarded == GuardedPath(
        absolute=parent.resolve() / "new.py",
        relative="Folder/new.py",
    )
    assert not guarded.absolute.exists()


def test_new_file_rejects_existing_target_and_bad_parent(tmp_path: Path) -> None:
    existing = tmp_path / "exists.txt"
    existing.write_text("x", encoding="utf-8")
    parent_file = tmp_path / "parent.txt"
    parent_file.write_text("x", encoding="utf-8")
    guard = PathGuard(tmp_path)

    _assert_violation(
        SafetyCode.PATH_TYPE_MISMATCH,
        lambda: guard.new_file("exists.txt"),
    )
    _assert_violation(
        SafetyCode.PARENT_NOT_FOUND,
        lambda: guard.new_file("missing/new.txt"),
    )
    _assert_violation(
        SafetyCode.PATH_TYPE_MISMATCH,
        lambda: guard.new_file("parent.txt/new.txt"),
    )
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py -q
```

Expected: nonzero exit because the three public methods are absent.

- [ ] **Step 3: Implement the minimal methods**

Add to `PathGuard`:

```python
    def existing_file(self, raw_path: object) -> GuardedPath:
        guarded = self.existing_entry(raw_path)
        if not guarded.absolute.is_file():
            raise SafetyViolation(
                SafetyCode.PATH_TYPE_MISMATCH,
                "path is not a file",
            )
        return guarded

    def existing_directory(self, raw_path: object) -> GuardedPath:
        guarded = self.existing_entry(raw_path)
        if not guarded.absolute.is_dir():
            raise SafetyViolation(
                SafetyCode.PATH_TYPE_MISMATCH,
                "path is not a directory",
            )
        return guarded

    def new_file(self, raw_path: object) -> GuardedPath:
        parts = self._relative_parts(raw_path)
        if not parts:
            raise SafetyViolation(
                SafetyCode.PATH_TYPE_MISMATCH,
                "new file path must name a file",
            )
        candidate = self._workspace.joinpath(*parts)
        self._contained(candidate)
        if candidate.exists() or candidate.is_symlink():
            raise SafetyViolation(
                SafetyCode.PATH_TYPE_MISMATCH,
                "target already exists",
            )
        parent = candidate.parent
        if not parent.exists():
            raise SafetyViolation(
                SafetyCode.PARENT_NOT_FOUND,
                "parent directory does not exist",
            )
        if not parent.is_dir():
            raise SafetyViolation(
                SafetyCode.PATH_TYPE_MISMATCH,
                "parent path is not a directory",
            )
        resolved_parent = parent.resolve(strict=True)
        self._contained(resolved_parent)
        absolute = resolved_parent / candidate.name
        return GuardedPath(absolute, "/".join(parts))
```

- [ ] **Step 4: Run GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_cli.py -q
```

Expected: both exit 0. Type mismatches, missing parents, and existing create targets are stable rejected states.

**Acceptance:** Callers receive both a canonical absolute `Path` and POSIX workspace-relative string, with target type and create-parent semantics decided centrally.

---

### Task 4: Protected components and non-revealing directory behavior

**Files:**

- Modify: `src/coding_agent/safety.py`
- Modify: `tests/test_path_safety.py`
- Modify: `tests/tools/test_read_tools.py`

**Interfaces:** Adds no new public API. All `PathGuard` entry points enforce the same component policy.

- [ ] **Step 1: Append the failing policy tests**

Append to `tests/test_path_safety.py`:

```python
@pytest.mark.parametrize(
    "raw_path",
    [
        ".git",
        ".GIT/config",
        "nested/.git/config",
        ".coding-agent",
        ".CODING-AGENT/logs/run.jsonl",
        "nested/.Coding-Agent/file.txt",
    ],
)
def test_protected_component_is_case_insensitive_at_any_depth(
    tmp_path: Path,
    raw_path: str,
) -> None:
    target = tmp_path.joinpath(*raw_path.replace("\\", "/").split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix:
        target.write_text("secret", encoding="utf-8")
    else:
        target.mkdir(exist_ok=True)

    _assert_violation(
        SafetyCode.PROTECTED_PATH,
        lambda: PathGuard(tmp_path).existing_entry(raw_path),
    )


def test_protected_component_does_not_match_similar_names(tmp_path: Path) -> None:
    for name in (".gitignore", "my.git", ".coding-agent-notes"):
        (tmp_path / name).write_text("ok", encoding="utf-8")

    guard = PathGuard(tmp_path)
    assert [
        guard.existing_file(name).relative
        for name in (".gitignore", "my.git", ".coding-agent-notes")
    ] == [".gitignore", "my.git", ".coding-agent-notes"]


def test_new_file_rejects_protected_component_before_parent_lookup(
    tmp_path: Path,
) -> None:
    _assert_violation(
        SafetyCode.PROTECTED_PATH,
        lambda: PathGuard(tmp_path).new_file(".coding-agent/logs/run.jsonl"),
    )
```

Append this integration test to `tests/tools/test_read_tools.py`:

```python
def test_list_directory_omits_protected_entries_without_hiding_similar_names(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret", encoding="utf-8")
    (tmp_path / ".coding-agent").mkdir()
    (tmp_path / ".coding-agent" / "log.jsonl").write_text(
        "secret",
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text("ok", encoding="utf-8")

    execution = ListDirectoryTool().execute(
        _list_arguments(recursive=True, max_depth=3),
        _context(tmp_path),
    )

    assert _json_output(execution) == {
        "entries": [{"path": ".gitignore", "type": "file"}]
    }
    for protected in (".git", ".coding-agent"):
        with pytest.raises(SafetyViolation) as exc_info:
            ListDirectoryTool().execute(
                _list_arguments(path=protected),
                _context(tmp_path),
            )
        assert exc_info.value.code is SafetyCode.PROTECTED_PATH
```

Also add to that test file:

```python
from coding_agent.safety import SafetyCode, SafetyViolation
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\tools\test_read_tools.py::test_list_directory_omits_protected_entries_without_hiding_similar_names -q
```

Expected: nonzero exit because protected components are currently accepted and `filesystem.py` has not delegated listing to `PathGuard` yet.

- [ ] **Step 3: Add the central protected check**

Add to `safety.py`:

```python
_PROTECTED_COMPONENTS = {".git", ".coding-agent"}
```

Add to `PathGuard` and call it immediately after `_relative_parts()` in `existing_entry()` and `new_file()`:

```python
    def _reject_protected(self, parts: tuple[str, ...]) -> None:
        if any(part.casefold() in _PROTECTED_COMPONENTS for part in parts):
            raise SafetyViolation(
                SafetyCode.PROTECTED_PATH,
                "protected path is unavailable",
            )
```

For the one filesystem integration test, use this complete iterator and imports; Task 5 extends only the caught code set, while Task 11 migrates the remaining tools:

```python
from coding_agent.safety import (
    GuardedPath,
    PathGuard,
    SafetyCode,
    SafetyViolation,
)


def _iter_directory_entries(
    guard: PathGuard,
    directory: GuardedPath,
    *,
    recursive: bool,
    max_depth: int,
    depth: int = 1,
) -> Iterator[GuardedPath]:
    for child in _directory_children(directory.absolute):
        raw_relative = child.relative_to(guard.workspace).as_posix()
        try:
            guarded_child = guard.existing_entry(raw_relative)
        except SafetyViolation as exc:
            if exc.code is SafetyCode.PROTECTED_PATH:
                continue
            raise
        yield guarded_child
        if recursive and guarded_child.absolute.is_dir() and depth < max_depth:
            yield from _iter_directory_entries(
                guard,
                guarded_child,
                recursive=True,
                max_depth=max_depth,
                depth=depth + 1,
            )
```

In `ListDirectoryTool.execute`, replace only the path/traversal block with:

```python
        guard = PathGuard(context.workspace)
        directory = guard.existing_directory(values["path"])
        entries: list[JSONObject] = []
        truncated = False
        for child in _iter_directory_entries(
            guard,
            directory,
            recursive=recursive,
            max_depth=max_depth,
        ):
            entries.append(
                {
                    "path": child.relative,
                    "type": _entry_type(child.absolute),
                }
            )
            if len(entries) == max_entries:
                truncated = True
                break
        return _json_execution({"entries": entries}, truncated=truncated)
```

- [ ] **Step 4: Run GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\tools\test_read_tools.py::test_list_directory_omits_protected_entries_without_hiding_similar_names -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_cli.py -q
```

Expected: both exit 0. Explicit access is rejected, root listing does not reveal protected entries, and similarly named ordinary files remain visible.

**Acceptance:** `.git` and `.coding-agent` are protected case-insensitively at any depth. Task 12's future internal logger is explicitly outside model tools and will use a separate internal writer, not a bypass flag on `PathGuard`.

---

### Task 5: Symlink, junction, reparse point, dangling link, and link-chain denial

**Files:** Modify `src/coding_agent/safety.py`, `tests/test_path_safety.py`, and the list integration in `tests/tools/test_read_tools.py`.

**Interfaces:** No new public method. The common component inspection applies to existing entries and new-file parents.

- [ ] **Step 1: Append real-OS and pure-policy failing tests**

Append these helpers and tests to `tests/test_path_safety.py`:

```python
def _create_symlink_or_fail(
    link: Path,
    target: Path,
    *,
    target_is_directory: bool,
) -> None:
    try:
        os.symlink(target, link, target_is_directory=target_is_directory)
    except OSError as exc:
        winerror = getattr(exc, "winerror", None)
        if winerror == 1314:
            pytest.fail(
                "real Windows symlink behavior remains unverified because "
                "the test account lacks symlink privilege (winerror=1314)"
            )
        pytest.fail(
            "real Windows symlink creation failed unexpectedly; "
            f"winerror={winerror}"
        )


def _create_junction_or_fail(link: Path, target: Path) -> None:
    completed = subprocess.run(
        [
            os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
            "/d",
            "/c",
            "mklink",
            "/J",
            str(link),
            str(target),
        ],
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(
            "real Windows junction behavior is required for Task 8; "
            f"mklink /J exited {completed.returncode}"
        )


def test_real_file_symlink_escape_is_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = workspace / "link.txt"
    _create_symlink_or_fail(link, outside, target_is_directory=False)

    _assert_violation(
        SafetyCode.REPARSE_POINT_DENIED,
        lambda: PathGuard(workspace).existing_file("link.txt"),
    )


def test_real_directory_symlink_and_internal_symlink_are_both_denied(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    internal = workspace / "real"
    internal.mkdir()
    _create_symlink_or_fail(
        workspace / "outside-link",
        outside,
        target_is_directory=True,
    )
    _create_symlink_or_fail(
        workspace / "inside-link",
        internal,
        target_is_directory=True,
    )
    guard = PathGuard(workspace)

    for name in ("outside-link", "inside-link"):
        _assert_violation(
            SafetyCode.REPARSE_POINT_DENIED,
            lambda name=name: guard.existing_directory(name),
        )


def test_reparse_workspace_root_is_denied(tmp_path: Path) -> None:
    real_workspace = tmp_path / "real-workspace"
    real_workspace.mkdir()
    linked_workspace = tmp_path / "linked-workspace"
    _create_symlink_or_fail(
        linked_workspace,
        real_workspace,
        target_is_directory=True,
    )

    _assert_violation(
        SafetyCode.REPARSE_POINT_DENIED,
        lambda: PathGuard(linked_workspace),
    )


def test_real_junction_escape_and_new_file_parent_are_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _create_junction_or_fail(workspace / "junction", outside)
    guard = PathGuard(workspace)

    _assert_violation(
        SafetyCode.REPARSE_POINT_DENIED,
        lambda: guard.existing_directory("junction"),
    )
    _assert_violation(
        SafetyCode.REPARSE_POINT_DENIED,
        lambda: guard.new_file("junction/new.txt"),
    )


def test_dangling_link_and_link_chain_are_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dangling = workspace / "dangling.txt"
    _create_symlink_or_fail(
        dangling,
        tmp_path / "does-not-exist.txt",
        target_is_directory=False,
    )
    real = workspace / "real.txt"
    real.write_text("x", encoding="utf-8")
    first = workspace / "first.txt"
    second = workspace / "second.txt"
    _create_symlink_or_fail(first, real, target_is_directory=False)
    _create_symlink_or_fail(second, first, target_is_directory=False)
    guard = PathGuard(workspace)

    for name in ("dangling.txt", "first.txt", "second.txt"):
        _assert_violation(
            SafetyCode.REPARSE_POINT_DENIED,
            lambda name=name: guard.existing_entry(name),
        )


def test_reparse_attribute_is_denied_through_public_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "ordinary.txt"
    target.write_text("x", encoding="utf-8")
    real_lstat = os.lstat

    def marked_lstat(path: os.PathLike[str] | str) -> object:
        result = real_lstat(path)
        if Path(path) == target:
            values = {
                name: getattr(result, name)
                for name in dir(result)
                if name.startswith("st_")
            }
            values["st_file_attributes"] = stat.FILE_ATTRIBUTE_REPARSE_POINT
            return SimpleNamespace(**values)
        return result

    monkeypatch.setattr("coding_agent.safety.os.lstat", marked_lstat)
    _assert_violation(
        SafetyCode.REPARSE_POINT_DENIED,
        lambda: PathGuard(tmp_path).existing_file("ordinary.txt"),
    )
```

Append to `tests/tools/test_read_tools.py`:

```python
def test_list_directory_omits_reparse_children(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    link = tmp_path / "linked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError as exc:
        winerror = getattr(exc, "winerror", None)
        if winerror == 1314:
            pytest.fail(
                "Task 8 directory-symlink behavior remains unverified because "
                "the test account lacks symlink privilege (winerror=1314)"
            )
        pytest.fail(
            "Task 8 requires a real Windows directory symlink; "
            f"unexpected winerror={winerror}"
        )
    (tmp_path / "visible.txt").write_text("ok", encoding="utf-8")

    execution = ListDirectoryTool().execute(
        _list_arguments(recursive=True, max_depth=3),
        _context(tmp_path),
    )

    assert _json_output(execution) == {
        "entries": [{"path": "visible.txt", "type": "file"}]
    }
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\tools\test_read_tools.py::test_list_directory_omits_reparse_children -q
```

Expected: nonzero exit because links currently resolve or are traversed. If Windows refuses real link/junction creation, the failure must explicitly identify the missing OS evidence; do not convert it to skip/xfail.

- [ ] **Step 3: Add one conservative reparse check to the common path pipeline**

Add to `safety.py`:

```python
def _is_reparse_point(path: Path) -> bool:
    try:
        result = os.lstat(path)
    except FileNotFoundError:
        return path.is_symlink()
    attributes = getattr(result, "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )
```

At the start of `PathGuard.__init__`, normalize lexically without resolving and reject a reparse workspace root:

```python
        requested_workspace = Path(os.path.abspath(workspace))
        if _is_reparse_point(requested_workspace):
            raise SafetyViolation(
                SafetyCode.REPARSE_POINT_DENIED,
                "reparse points are unavailable to model paths",
            )
```

Add and call this method after `_reject_protected(parts)` but before any `resolve()` in `existing_entry()` and `new_file()`:

```python
    def _reject_reparse_components(self, parts: tuple[str, ...]) -> None:
        current = self._workspace
        for part in parts:
            current = current / part
            if current.exists() or current.is_symlink():
                if _is_reparse_point(current):
                    raise SafetyViolation(
                        SafetyCode.REPARSE_POINT_DENIED,
                        "reparse points are unavailable to model paths",
                    )
```

For `new_file`, call it with the full parts tuple before checking target existence so a dangling target link and a reparse parent map to `REPARSE_POINT_DENIED` rather than a generic type error.

Extend the list iterator's existing `SafetyViolation` filter to omit both `PROTECTED_PATH` and `REPARSE_POINT_DENIED`; re-raise every other code.

- [ ] **Step 4: Run GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\tools\test_read_tools.py::test_list_directory_omits_reparse_children -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_cli.py -q
```

Expected: both commands exit 0 only when required real Windows link/junction behavior is proven. Report exact OS test outcomes and any creation limitation.

**Acceptance:** Every existing component, link chain, dangling link, internal link, outside link, junction, and new-file parent uses the same conservative reparse rule; no permanent skip or xfail exists.

---

### Task 6: Native command parsing, control syntax, and authorized-command value

**Files:**

- Modify: `src/coding_agent/safety.py`
- Create: `tests/test_command_safety.py`
- Modify: `src/coding_agent/tools/shell.py`
- Modify: `tests/tools/test_shell_tool.py`

**Interfaces:** Produces `CommandSource`, `AuthorizedCommand`, `CommandPolicy`, `ExecutableLocator`, and `parse_windows_command_line`. Preserves `coding_agent.tools.shell.parse_windows_command_line` as a re-export.

- [ ] **Step 1: Create the failing command tests**

Create `tests/test_command_safety.py`:

```python
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Callable

import pytest

from coding_agent.safety import (
    AuthorizedCommand,
    CommandPolicy,
    CommandSource,
    SafetyCode,
    SafetyViolation,
    parse_windows_command_line,
)
from coding_agent.tools.base import ToolArgumentError


def _assert_command_violation(
    code: SafetyCode,
    operation: Callable[[], object],
) -> SafetyViolation:
    with pytest.raises(SafetyViolation) as exc_info:
        operation()
    assert exc_info.value.code is code
    assert str(exc_info.value).startswith(f"{code.value}: ")
    return exc_info.value


@pytest.mark.parametrize(
    "argv",
    [
        [sys.executable, "alpha beta", ""],
        [sys.executable, r"C:\path with spaces\script.py", r"tail\\"],
        [sys.executable, "雪", 'embedded"quote'],
    ],
)
def test_native_parser_round_trips_windows_arguments(argv: list[str]) -> None:
    command = subprocess.list2cmdline(argv)
    assert parse_windows_command_line(command) == tuple(argv)


@pytest.mark.parametrize("command", [None, 7, "", "   ", 'python "open'])
def test_native_parser_uses_stable_parse_error(command: object) -> None:
    _assert_command_violation(
        SafetyCode.COMMAND_PARSE_ERROR,
        lambda: parse_windows_command_line(command),
    )


@pytest.mark.parametrize(
    "command",
    [
        "python a.py & whoami",
        "python a.py && whoami",
        "python a.py | more",
        "python a.py || exit",
        "python a.py > out.txt",
        "python a.py >> out.txt",
        "python a.py < in.txt",
        "python a.py\nwhoami",
        "python a.py\rwhoami",
        "python a.py\x00whoami",
        'python "literal&still-denied.py"',
    ],
)
def test_command_policy_rejects_control_syntax_before_execution(
    tmp_path: Path,
    command: str,
) -> None:
    _assert_command_violation(
        SafetyCode.SHELL_SYNTAX_DENIED,
        lambda: CommandPolicy(tmp_path).authorize(
            command,
            purpose="test",
            source=CommandSource.MODEL,
        ),
    )


@pytest.mark.parametrize("purpose", ["", "build", 1, True])
def test_command_policy_rejects_invalid_purpose_as_argument_error(
    tmp_path: Path,
    purpose: object,
) -> None:
    with pytest.raises(ToolArgumentError, match="purpose must be inspect, test, or verification"):
        CommandPolicy(tmp_path).authorize(
            "python script.py",
            purpose=purpose,  # type: ignore[arg-type]
            source=CommandSource.MODEL,
        )


def test_command_source_values_are_stable() -> None:
    assert CommandSource.MODEL.value == "model"
    assert CommandSource.USER_VERIFY.value == "user_verify"
```

Update the native-failure monkeypatch in `tests/tools/test_shell_tool.py` from `coding_agent.tools.shell._COMMAND_LINE_TO_ARGV_W` to `coding_agent.safety._COMMAND_LINE_TO_ARGV_W`. Change both the native-failure regex and the existing empty/unclosed-input regex to `command could not be parsed`; keep every assertion through the shell re-export.

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_command_safety.py tests\tools\test_shell_tool.py::test_parse_windows_command_line_maps_native_failure -q
```

Expected: nonzero exit because the command policy types/parser do not exist in `safety.py`.

- [ ] **Step 3: Move the parser and add the minimal deny-by-default policy**

Move the implementation out of `tools/shell.py` by adding this complete parser to `safety.py`:

```python
_COMMAND_LINE_TO_ARGV_W = ctypes.windll.shell32.CommandLineToArgvW
_COMMAND_LINE_TO_ARGV_W.argtypes = [
    wintypes.LPCWSTR,
    ctypes.POINTER(ctypes.c_int),
]
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


def parse_windows_command_line(command: object) -> tuple[str, ...]:
    if not isinstance(command, str) or not command.strip() or "\x00" in command:
        raise SafetyViolation(
            SafetyCode.COMMAND_PARSE_ERROR,
            "command could not be parsed",
        )
    normalized = command.strip()
    if _has_unclosed_quote(normalized):
        raise SafetyViolation(
            SafetyCode.COMMAND_PARSE_ERROR,
            "command could not be parsed",
        )
    argc = ctypes.c_int()
    argv_pointer = _COMMAND_LINE_TO_ARGV_W(normalized, ctypes.byref(argc))
    if not argv_pointer or argc.value <= 0:
        raise SafetyViolation(
            SafetyCode.COMMAND_PARSE_ERROR,
            "command could not be parsed",
        )
    try:
        argv = tuple(argv_pointer[index] for index in range(argc.value))
    finally:
        _LOCAL_FREE(ctypes.cast(argv_pointer, wintypes.HLOCAL))
    if not argv or not argv[0]:
        raise SafetyViolation(
            SafetyCode.COMMAND_PARSE_ERROR,
            "command could not be parsed",
        )
    return argv
```

Add to `safety.py`:

```python
from collections.abc import Callable
import ctypes
from ctypes import wintypes
import shutil
import subprocess
import sys

_PURPOSES = {"inspect", "test", "verification"}
_CONTROL_CHARACTERS = frozenset("&|><\r\n\x00")


class CommandSource(StrEnum):
    MODEL = "model"
    USER_VERIFY = "user_verify"


@dataclass(frozen=True, slots=True)
class AuthorizedCommand:
    argv: tuple[str, ...]
    normalized_command: str
    purpose: str
    source: CommandSource


ExecutableLocator = Callable[[str], str | None]


class CommandPolicy:
    def __init__(
        self,
        workspace: Path,
        *,
        executable_locator: ExecutableLocator | None = None,
    ) -> None:
        self._paths = PathGuard(workspace)
        self._executable_locator = (
            shutil.which if executable_locator is None else executable_locator
        )

    @property
    def workspace(self) -> Path:
        return self._paths.workspace

    def authorize(
        self,
        command: object,
        *,
        purpose: str,
        source: CommandSource,
    ) -> AuthorizedCommand:
        if not isinstance(purpose, str) or purpose not in _PURPOSES:
            raise ToolArgumentError(
                "purpose must be inspect, test, or verification"
            )
        if not isinstance(source, CommandSource):
            raise ToolArgumentError("source must be model or user_verify")
        if isinstance(command, str) and any(
            character in command for character in _CONTROL_CHARACTERS
        ):
            raise SafetyViolation(
                SafetyCode.SHELL_SYNTAX_DENIED,
                "shell control syntax is not allowed",
            )
        argv = parse_windows_command_line(command)
        raise SafetyViolation(
            SafetyCode.EXECUTABLE_DENIED,
            "executable is not allowed",
        )
```

In `tools/shell.py`, delete its ctypes/parser implementation and add:

```python
from coding_agent.safety import parse_windows_command_line
```

- [ ] **Step 4: Run GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_command_safety.py tests\tools\test_shell_tool.py::test_parse_windows_command_line_maps_native_failure -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_cli.py -q
```

Expected: both commands exit 0. Moving the implementation and re-exporting the function must preserve every existing Task 7 parser test without changing its assertions. Any Task 7 failure stops execution before Task 7 of this plan. Report actual counts.

**Acceptance:** Parsing remains native Windows parsing with guaranteed `LocalFree`; command control syntax has a dedicated code; all executables remain denied until individually authorized.

---

### Task 7: Current Python, workspace scripts, pytest, and unittest policy

**Files:** Modify `src/coding_agent/safety.py`, `tests/test_command_safety.py`, and the temporary-boundary expectations in `tests/tools/test_shell_tool.py`.

**Interfaces:** `CommandPolicy.authorize()` begins returning `AuthorizedCommand` for the locked Python/test forms.

- [ ] **Step 1: Append the failing allow/deny tests**

Append to `tests/test_command_safety.py`:

```python
def _authorize(
    tmp_path: Path,
    argv: list[str],
    *,
    purpose: str = "test",
    source: CommandSource = CommandSource.MODEL,
    locator: Callable[[str], str | None] | None = None,
) -> AuthorizedCommand:
    return CommandPolicy(
        tmp_path,
        executable_locator=locator,
    ).authorize(
        subprocess.list2cmdline(argv),
        purpose=purpose,
        source=source,
    )


def test_current_python_workspace_script_is_canonicalized(tmp_path: Path) -> None:
    script = tmp_path / "folder" / "check.py"
    script.parent.mkdir()
    script.write_text("print('ok')\n", encoding="utf-8")

    authorized = _authorize(tmp_path, ["python", r"folder\check.py", "value"])

    assert authorized.argv == (sys.executable, str(script.resolve()), "value")
    assert authorized.normalized_command == subprocess.list2cmdline(authorized.argv)
    assert authorized.purpose == "test"
    assert authorized.source is CommandSource.MODEL


@pytest.mark.parametrize("executable", ["python", "PYTHON.EXE"])
def test_python_alias_case_and_exe_suffix_map_to_current_interpreter(
    tmp_path: Path,
    executable: str,
) -> None:
    script = tmp_path / "script.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    authorized = _authorize(tmp_path, [executable, "script.py"])
    assert authorized.argv == (sys.executable, str(script.resolve()))


def test_relative_workspace_python_lookalike_is_not_a_bare_alias(
    tmp_path: Path,
) -> None:
    (tmp_path / "python.exe").write_bytes(b"fake")
    (tmp_path / "script.py").write_text("print('ok')\n", encoding="utf-8")
    _assert_command_violation(
        SafetyCode.EXECUTABLE_DENIED,
        lambda: _authorize(tmp_path, [r".\python.exe", "script.py"]),
    )


@pytest.mark.parametrize(
    "argv",
    [
        [sys.executable, "-c", "print('x')"],
        [sys.executable, "-"],
        [sys.executable, "-m", "pip", "list"],
        ["py", "script.py"],
    ],
)
def test_python_rejects_code_stdin_unknown_module_and_py_launcher(
    tmp_path: Path,
    argv: list[str],
) -> None:
    _assert_command_violation(
        SafetyCode.ARGUMENT_DENIED if argv[0] != "py" else SafetyCode.EXECUTABLE_DENIED,
        lambda: _authorize(tmp_path, argv),
    )


def test_python_rejects_outside_non_python_and_protected_scripts(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print('x')", encoding="utf-8")
    (workspace / "data.txt").write_text("x", encoding="utf-8")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "hook.py").write_text("x", encoding="utf-8")

    policy = CommandPolicy(workspace)
    for command in (
        subprocess.list2cmdline([sys.executable, str(outside)]),
        subprocess.list2cmdline([sys.executable, "data.txt"]),
        subprocess.list2cmdline([sys.executable, ".git/hook.py"]),
    ):
        with pytest.raises(SafetyViolation):
            policy.authorize(
                command,
                purpose="test",
                source=CommandSource.MODEL,
            )


@pytest.mark.parametrize("prefix", [["python", "-m", "pytest"], ["pytest"]])
def test_pytest_demo_forms_are_allowed(tmp_path: Path, prefix: list[str]) -> None:
    launcher = Path(sys.executable).with_name("pytest.exe")
    locator = lambda name: str(launcher) if name.casefold() in {"pytest", "pytest.exe"} else None

    authorized = _authorize(
        tmp_path,
        [*prefix, "-q", "--tb=short"],
        purpose="verification",
        source=CommandSource.USER_VERIFY,
        locator=locator,
    )

    if prefix[0] == "python":
        assert authorized.argv[:3] == (sys.executable, "-m", "pytest")
    else:
        assert authorized.argv[0] == str(launcher.resolve())
    assert authorized.argv[-2:] == ("-q", "--tb=short")


def test_direct_pytest_name_is_case_insensitive(tmp_path: Path) -> None:
    launcher = Path(sys.executable).with_name("pytest.exe")
    locator = lambda name: str(launcher) if name.casefold() in {"pytest", "pytest.exe"} else None
    authorized = _authorize(
        tmp_path,
        ["PyTeSt.ExE", "-q"],
        locator=locator,
    )
    assert authorized.argv == (str(launcher.resolve()), "-q")


@pytest.mark.parametrize(
    "arguments",
    [
        ["-p", "dangerous"],
        ["-c", "outside.ini"],
        ["--override-ini", "addopts=-p dangerous"],
        ["--rootdir", ".."],
        ["--basetemp", r"C:\outside"],
        ["@args.txt"],
        ["../outside_test.py"],
    ],
)
def test_pytest_rejects_plugin_config_response_and_unsafe_paths(
    tmp_path: Path,
    arguments: list[str],
) -> None:
    _assert_command_violation(
        SafetyCode.ARGUMENT_DENIED,
        lambda: _authorize(tmp_path, ["python", "-m", "pytest", *arguments]),
    )


def test_pytest_allows_guarded_node_selector(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_sample.py"
    test_file.parent.mkdir()
    test_file.write_text("def test_ok(): pass\n", encoding="utf-8")

    authorized = _authorize(
        tmp_path,
        ["python", "-m", "pytest", "tests/test_sample.py::test_ok", "-q"],
    )
    assert authorized.argv[-2:] == (
        f"{test_file.resolve()}::test_ok",
        "-q",
    )


def test_unittest_module_and_discover_forms_are_bounded(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text("pass\n", encoding="utf-8")

    module = _authorize(
        tmp_path,
        ["python", "-m", "unittest", "-q", "tests.test_sample"],
    )
    discover = _authorize(
        tmp_path,
        [
            "python", "-m", "unittest", "discover",
            "-s", "tests", "-p", "test_*.py", "-t", ".",
        ],
    )

    assert module.argv[-2:] == ("-q", "tests.test_sample")
    assert str(tests_dir.resolve()) in discover.argv
    assert str(tmp_path.resolve()) in discover.argv


def test_unittest_does_not_import_an_installed_or_stdlib_module(tmp_path: Path) -> None:
    _assert_command_violation(
        SafetyCode.ARGUMENT_DENIED,
        lambda: _authorize(tmp_path, ["python", "-m", "unittest", "os"]),
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["@args.txt"],
        ["discover", "-s", ".."],
        ["discover", "-p", "../*.py"],
        ["--unknown"],
    ],
)
def test_unittest_rejects_unbounded_arguments(
    tmp_path: Path,
    arguments: list[str],
) -> None:
    _assert_command_violation(
        SafetyCode.ARGUMENT_DENIED,
        lambda: _authorize(tmp_path, ["python", "-m", "unittest", *arguments]),
    )
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_command_safety.py -q
```

Expected: nonzero exit because the policy still denies every executable.

- [ ] **Step 3: Implement the exact Python/test argument policies**

Add these constants to `safety.py`:

```python
import re

_PYTEST_FLAGS = {
    "-q", "--quiet", "-v", "--verbose", "-x", "--exitfirst",
    "--disable-warnings", "--strict-markers", "--strict-config",
    "--help", "--version",
}
_PYTEST_TB = {"auto", "long", "short", "line", "native", "no"}
_UNITTEST_FLAGS = {"-q", "-v", "-f", "-b", "--locals", "--help"}
_DOTTED_TEST = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
```

Add private helpers to `CommandPolicy` with these exact responsibilities:

```python
    def _current_python(self, executable: str) -> Path | None:
        windows = PureWindowsPath(executable)
        folded = windows.name.casefold()
        current = Path(sys.executable).resolve(strict=True)
        if (
            folded in {"python", "python.exe"}
            and len(windows.parts) == 1
            and not windows.drive
            and not windows.root
        ):
            return current
        try:
            supplied = Path(executable).resolve(strict=True)
        except OSError:
            return None
        return supplied if os.path.normcase(str(supplied)) == os.path.normcase(str(current)) else None

    def _reject_response_or_path_escape(self, argument: str) -> None:
        if argument.startswith("@"):
            raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "argument is not allowed")
        windows = PureWindowsPath(argument)
        if windows.drive or windows.root or ".." in windows.parts:
            raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "argument is not allowed")

    def _guard_node(self, value: str) -> str:
        path_text, separator, node = value.partition("::")
        if separator and not node:
            raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "argument is not allowed")
        guarded = self._paths.existing_entry(path_text)
        return str(guarded.absolute) + (f"::{node}" if separator else "")

    def _guard_unittest_module(self, value: str) -> str:
        if _DOTTED_TEST.fullmatch(value) is None:
            raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "unittest target is not allowed")
        module_path = value.replace(".", "/")
        candidates = (f"{module_path}.py", f"{module_path}/__init__.py")
        for candidate in candidates:
            try:
                self._paths.existing_file(candidate)
            except SafetyViolation as exc:
                if exc.code is SafetyCode.PATH_NOT_FOUND:
                    continue
                raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "unittest target is not allowed") from exc
            return value
        raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "unittest target is not allowed")
```

Add the complete argument parsers:

```python
    def _authorize_pytest(self, arguments: tuple[str, ...]) -> tuple[str, ...]:
        rendered: list[str] = []
        index = 0
        while index < len(arguments):
            value = arguments[index]
            if value in _PYTEST_FLAGS:
                rendered.append(value)
            elif value.startswith("--maxfail="):
                count = value.partition("=")[2]
                if not count.isdigit() or int(count) <= 0:
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "pytest arguments are not allowed")
                rendered.append(value)
            elif value.startswith("--tb="):
                if value.partition("=")[2] not in _PYTEST_TB:
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "pytest arguments are not allowed")
                rendered.append(value)
            elif value in {"-k", "-m"}:
                if index + 1 >= len(arguments) or not arguments[index + 1]:
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "pytest arguments are not allowed")
                expression = arguments[index + 1]
                self._reject_response_or_path_escape(expression)
                rendered.extend((value, expression))
                index += 1
            elif value == "--":
                rendered.append("--")
                rendered.extend(self._guard_node(item) for item in arguments[index + 1:])
                return tuple(rendered)
            elif value.startswith("-") or value.startswith("@"):
                raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "pytest arguments are not allowed")
            else:
                rendered.append(self._guard_node(value))
            index += 1
        return tuple(rendered)

    def _authorize_unittest(self, arguments: tuple[str, ...]) -> tuple[str, ...]:
        rendered: list[str] = []
        discover = False
        index = 0
        while index < len(arguments):
            value = arguments[index]
            if value.startswith("@"):
                raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "unittest arguments are not allowed")
            if value in _UNITTEST_FLAGS:
                rendered.append(value)
            elif value == "-k" and not discover:
                if index + 1 >= len(arguments) or not arguments[index + 1]:
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "unittest arguments are not allowed")
                pattern = arguments[index + 1]
                self._reject_response_or_path_escape(pattern)
                rendered.extend((value, pattern))
                index += 1
            elif value == "discover" and not discover:
                discover = True
                rendered.append(value)
            elif discover and value in {"-s", "--start-directory", "-t", "--top-level-directory"}:
                if index + 1 >= len(arguments):
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "unittest arguments are not allowed")
                directory = self._paths.existing_directory(arguments[index + 1])
                rendered.extend((value, str(directory.absolute)))
                index += 1
            elif discover and value in {"-p", "--pattern"}:
                if index + 1 >= len(arguments):
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "unittest arguments are not allowed")
                pattern = arguments[index + 1]
                if not pattern or ".." in pattern or any(character in pattern for character in "/\\:"):
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "unittest arguments are not allowed")
                rendered.extend((value, pattern))
                index += 1
            elif discover or value.startswith("-"):
                raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "unittest arguments are not allowed")
            elif _DOTTED_TEST.fullmatch(value):
                rendered.append(self._guard_unittest_module(value))
            else:
                file_path = self._paths.existing_file(value)
                if file_path.absolute.suffix.casefold() != ".py":
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "unittest target is not Python source")
                rendered.append(str(file_path.absolute))
            index += 1
        return tuple(rendered)

    def _locate_from_sanitized_path(self, name: str) -> str | None:
        runtime_directory = Path(sys.executable).resolve(strict=True).parent
        accepted_entries: list[str] = []
        for raw_entry in os.environ.get("PATH", "").split(os.pathsep):
            if not raw_entry:
                continue
            entry = Path(raw_entry)
            if not entry.is_absolute():
                continue
            try:
                resolved = entry.resolve(strict=True)
            except OSError:
                continue
            try:
                common = os.path.commonpath((str(self.workspace), str(resolved)))
            except ValueError:
                common = ""
            inside_workspace = os.path.normcase(common) == os.path.normcase(str(self.workspace))
            if inside_workspace and os.path.normcase(str(resolved)) != os.path.normcase(str(runtime_directory)):
                continue
            accepted_entries.append(str(resolved))
        return shutil.which(name, path=os.pathsep.join(accepted_entries))

    def _trusted_launcher(
        self,
        supplied: str,
        accepted_names: set[str],
        *,
        allow_runtime: bool = True,
    ) -> Path:
        folded_names = {name.casefold() for name in accepted_names}
        windows = PureWindowsPath(supplied)
        if windows.name.casefold() not in folded_names:
            raise SafetyViolation(SafetyCode.EXECUTABLE_DENIED, "executable is not allowed")
        candidates: list[Path] = []
        supplied_path = Path(supplied)
        runtime_directory = Path(sys.executable).resolve(strict=True).parent
        if supplied_path.is_absolute():
            candidates.append(supplied_path)
        else:
            if len(windows.parts) != 1 or windows.drive or windows.root:
                raise SafetyViolation(SafetyCode.EXECUTABLE_DENIED, "executable is not allowed")
            if allow_runtime:
                for name in sorted(accepted_names):
                    candidates.append(runtime_directory / name)
            located = self._executable_locator(supplied)
            if located is not None:
                candidates.append(Path(located))
        for candidate in candidates:
            if _is_reparse_point(candidate):
                continue
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                continue
            try:
                common = os.path.commonpath((str(self.workspace), str(resolved)))
            except ValueError:
                common = ""
            inside_workspace = os.path.normcase(common) == os.path.normcase(str(self.workspace))
            runtime_match = os.path.normcase(str(resolved.parent)) == os.path.normcase(str(runtime_directory))
            if inside_workspace and (not allow_runtime or not runtime_match):
                continue
            if resolved.name.casefold() in folded_names:
                return resolved
        raise SafetyViolation(SafetyCode.EXECUTABLE_DENIED, "trusted executable is unavailable")
```

Change the `CommandPolicy.__init__` assignment created in Task 6 to:

```python
        self._executable_locator = (
            self._locate_from_sanitized_path
            if executable_locator is None
            else executable_locator
        )
```

Replace the deny-only end of `authorize()` with:

```python
        python = self._current_python(argv[0])
        if python is not None:
            if len(argv) >= 3 and argv[1:3] == ("-m", "pytest"):
                final = (str(python), "-m", "pytest", *self._authorize_pytest(argv[3:]))
            elif len(argv) >= 3 and argv[1:3] == ("-m", "unittest"):
                final = (str(python), "-m", "unittest", *self._authorize_unittest(argv[3:]))
            elif len(argv) >= 2 and not argv[1].startswith("-"):
                script = self._paths.existing_file(argv[1])
                if script.absolute.suffix.casefold() != ".py":
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "script must be a Python file")
                for argument in argv[2:]:
                    self._reject_response_or_path_escape(argument)
                final = (str(python), str(script.absolute), *argv[2:])
            else:
                raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "Python arguments are not allowed")
            return AuthorizedCommand(
                argv=tuple(final),
                normalized_command=subprocess.list2cmdline(final),
                purpose=purpose,
                source=source,
            )

        if Path(argv[0]).name.casefold() in {"pytest", "pytest.exe"}:
            executable = self._trusted_launcher(argv[0], {"pytest", "pytest.exe"})
            final = (str(executable), *self._authorize_pytest(argv[1:]))
            return AuthorizedCommand(
                argv=tuple(final),
                normalized_command=subprocess.list2cmdline(final),
                purpose=purpose,
                source=source,
            )

        raise SafetyViolation(SafetyCode.EXECUTABLE_DENIED, "executable is not allowed")
```

Update Task 7 tests so temporary-boundary rejections assert the new `SafetyViolation.code`. In the outside-script test, build the command explicitly with `subprocess.list2cmdline([sys.executable, str(outside)])` and assert `PATH_OUTSIDE_WORKSPACE`; do not use the now-relative `_command_for_script` helper for that case. Retain `parse_windows_command_line` re-export tests and retain the existing `python -m pytest --help` / `python -m unittest --help` execution test because `--help` is explicitly allowlisted and exits deterministically without running project code.

- [ ] **Step 4: Run GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_command_safety.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_cli.py -q
```

Expected: both exit 0. Report actual counts. Safe demo forms authorize to canonical argv; all code-string/stdin/plugin/config/outside forms reject before process creation.

**Acceptance:** Python aliases cannot resolve to workspace lookalikes, scripts are existing guarded `.py` files, pytest/unittest argument grammars are explicit, and `purpose`/`source` do not widen them.

---

### Task 8: Trusted ruff and mypy read-only policies

**Files:** Modify `src/coding_agent/safety.py` and `tests/test_command_safety.py`.

**Interfaces:** Extends `CommandPolicy.authorize()` only; no tool interface changes.

- [ ] **Step 1: Append the failing tests**

```python
def _locator_for(directory: Path) -> Callable[[str], str | None]:
    def locate(name: str) -> str | None:
        candidate = directory / name
        return str(candidate) if candidate.exists() else None
    return locate


def test_ruff_check_uses_trusted_launcher_and_guarded_paths(tmp_path: Path) -> None:
    trusted = tmp_path.parent / f"{tmp_path.name}-trusted"
    trusted.mkdir()
    launcher = trusted / "ruff.exe"
    launcher.write_bytes(b"test launcher")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("print('ok')\n", encoding="utf-8")

    authorized = _authorize(
        tmp_path,
        [str(launcher), "check", "--no-cache", "src/app.py"],
        locator=_locator_for(trusted),
    )

    assert authorized.argv == (
        str(launcher.resolve()),
        "check",
        "--isolated",
        "--no-cache",
        str(source.resolve()),
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["format", "."],
        ["check", "--fix", "."],
        ["check", "--unsafe-fixes", "."],
        ["check", "--add-noqa", "."],
        ["check", "--config", "ruff.toml", "."],
        ["check", "@args.txt"],
        ["check", ".."],
    ],
)
def test_ruff_rejects_mutating_config_response_and_outside_forms(
    tmp_path: Path,
    arguments: list[str],
) -> None:
    trusted = tmp_path.parent / f"{tmp_path.name}-trusted"
    trusted.mkdir()
    (trusted / "ruff.exe").write_bytes(b"test launcher")
    _assert_command_violation(
        SafetyCode.ARGUMENT_DENIED,
        lambda: _authorize(
            tmp_path,
            ["ruff", *arguments],
            locator=_locator_for(trusted),
        ),
    )


def test_mypy_inserts_fixed_empty_config_and_no_incremental(
    tmp_path: Path,
) -> None:
    trusted = tmp_path.parent / f"{tmp_path.name}-trusted"
    trusted.mkdir()
    launcher = trusted / "mypy.exe"
    launcher.write_bytes(b"test launcher")
    package = tmp_path / "package"
    package.mkdir()
    (package / "module.py").write_text("value: int = 1\n", encoding="utf-8")

    authorized = _authorize(
        tmp_path,
        [str(launcher), "--strict", "package"],
        purpose="verification",
        locator=_locator_for(trusted),
    )

    assert authorized.argv == (
        str(launcher.resolve()),
        "--config-file=NUL",
        "--no-incremental",
        "--strict",
        str(package.resolve()),
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["--config-file", "mypy.ini", "app.py"],
        ["--python-executable", "python.exe", "app.py"],
        ["--custom-typeshed-dir", "typeshed", "app.py"],
        ["--cache-dir", ".cache", "app.py"],
        ["--install-types", "app.py"],
        ["@args.txt"],
        ["../outside.py"],
    ],
)
def test_mypy_rejects_config_execution_and_unbounded_paths(
    tmp_path: Path,
    arguments: list[str],
) -> None:
    trusted = tmp_path.parent / f"{tmp_path.name}-trusted"
    trusted.mkdir()
    (trusted / "mypy.exe").write_bytes(b"test launcher")
    (tmp_path / "app.py").write_text("value: int = 1\n", encoding="utf-8")
    _assert_command_violation(
        SafetyCode.ARGUMENT_DENIED,
        lambda: _authorize(
            tmp_path,
            ["mypy", *arguments],
            locator=_locator_for(trusted),
        ),
    )


def test_workspace_fake_linter_is_not_trusted(tmp_path: Path) -> None:
    fake = tmp_path / "ruff.exe"
    fake.write_bytes(b"fake")
    source = tmp_path / "app.py"
    source.write_text("print('x')\n", encoding="utf-8")

    _assert_command_violation(
        SafetyCode.EXECUTABLE_DENIED,
        lambda: _authorize(
            tmp_path,
            [str(fake), "check", "app.py"],
            locator=lambda name: str(fake),
        ),
    )
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_command_safety.py -q
```

Expected: nonzero exit because `ruff` and `mypy` remain executable-denied.

- [ ] **Step 3: Implement explicit linter parsers**

Add constants:

```python
_RUFF_SIMPLE_FLAGS = {"--no-cache", "--quiet", "--verbose"}
_RUFF_OUTPUT_FORMATS = {"concise", "full", "json", "json-lines", "junit", "github", "gitlab", "pylint", "rdjson", "sarif"}
_RUFF_RULES = re.compile(r"[A-Za-z0-9,]+")
_MYPY_SIMPLE_FLAGS = {
    "--no-site-packages", "--show-error-codes", "--pretty", "--strict",
    "--warn-unused-ignores", "--ignore-missing-imports",
}
_MYPY_FOLLOW_IMPORTS = {"normal", "silent", "skip", "error"}
```

Add complete parsers to `CommandPolicy`:

```python
    def _authorize_ruff(self, arguments: tuple[str, ...]) -> tuple[str, ...]:
        if arguments in {("--help",), ("--version",)}:
            return arguments
        if not arguments or arguments[0] != "check":
            raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "ruff arguments are not allowed")
        rendered: list[str] = ["check", "--isolated"]
        index = 1
        while index < len(arguments):
            value = arguments[index]
            if value in _RUFF_SIMPLE_FLAGS:
                rendered.append(value)
            elif value.startswith("--output-format="):
                output_format = value.partition("=")[2]
                if output_format not in _RUFF_OUTPUT_FORMATS:
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "ruff arguments are not allowed")
                rendered.append(value)
            elif value.startswith(("--select=", "--ignore=", "--extend-select=", "--extend-ignore=")):
                rules = value.partition("=")[2]
                if _RUFF_RULES.fullmatch(rules) is None:
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "ruff arguments are not allowed")
                rendered.append(value)
            elif value.startswith("-") or value.startswith("@"):
                raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "ruff arguments are not allowed")
            else:
                rendered.append(str(self._paths.existing_entry(value).absolute))
            index += 1
        return tuple(rendered)

    def _authorize_mypy(self, arguments: tuple[str, ...]) -> tuple[str, ...]:
        if arguments in {("--help",), ("--version",)}:
            return arguments
        rendered: list[str] = ["--config-file=NUL", "--no-incremental"]
        target_count = 0
        for value in arguments:
            if value in _MYPY_SIMPLE_FLAGS:
                rendered.append(value)
            elif value.startswith("--follow-imports="):
                mode = value.partition("=")[2]
                if mode not in _MYPY_FOLLOW_IMPORTS:
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "mypy arguments are not allowed")
                rendered.append(value)
            elif value.startswith("-") or value.startswith("@"):
                raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "mypy arguments are not allowed")
            else:
                guarded = self._paths.existing_entry(value)
                if guarded.absolute.is_file() and guarded.absolute.suffix.casefold() not in {".py", ".pyi"}:
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "mypy target is not Python source")
                rendered.append(str(guarded.absolute))
                target_count += 1
        if target_count == 0:
            raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "mypy requires a workspace target")
        return tuple(rendered)
```

Before the final executable denial in `authorize()`, add:

```python
        executable_name = Path(argv[0]).name.casefold()
        if executable_name in {"ruff", "ruff.exe", "mypy", "mypy.exe"}:
            accepted_names = {executable_name.removesuffix(".exe"), executable_name.removesuffix(".exe") + ".exe"}
            executable = self._trusted_launcher(argv[0], accepted_names)
            arguments = (
                self._authorize_ruff(argv[1:])
                if executable_name.startswith("ruff")
                else self._authorize_mypy(argv[1:])
            )
            final = (str(executable), *arguments)
            return AuthorizedCommand(
                argv=tuple(final),
                normalized_command=subprocess.list2cmdline(final),
                purpose=purpose,
                source=source,
            )
```

- [ ] **Step 4: Run GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_command_safety.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_cli.py -q
```

Expected: both exit 0. A missing trusted launcher yields `executable_denied`; policy does not search or execute a workspace fake.

**Acceptance:** `ruff` is read-only (`check` only), `mypy` cannot load user-selected configuration and writes no incremental cache, and both operate only on guarded workspace targets.

---

### Task 9: Read-only Git subcommands and extension-point denial

**Files:** Modify `src/coding_agent/safety.py` and `tests/test_command_safety.py`.

**Interfaces:** Extends `CommandPolicy.authorize()` with exact read-only Git grammar.

- [ ] **Step 1: Append the failing Git matrix**

```python
def _git_locator(trusted: Path) -> Callable[[str], str | None]:
    launcher = trusted / "git.exe"
    launcher.write_bytes(b"test launcher")
    return lambda name: str(launcher) if name.casefold() in {"git", "git.exe"} else None


@pytest.mark.parametrize(
    "arguments",
    [
        ["status", "--short"],
        ["diff", "--check"],
        ["diff", "--cached", "--stat"],
        ["log", "--oneline", "-n", "3"],
        ["show", "HEAD", "--stat"],
        ["ls-files", "--cached"],
    ],
)
def test_read_only_git_forms_are_authorized(
    tmp_path: Path,
    arguments: list[str],
) -> None:
    trusted = tmp_path.parent / f"{tmp_path.name}-git"
    trusted.mkdir()
    authorized = _authorize(
        tmp_path,
        ["git", *arguments],
        purpose="inspect",
        locator=_git_locator(trusted),
    )

    assert authorized.argv[0] == str((trusted / "git.exe").resolve())
    assert authorized.argv[:7] == (
        str((trusted / "git.exe").resolve()),
        "-c",
        "core.fsmonitor=false",
        "-c",
        "diff.external=",
        "--no-pager",
        arguments[0],
    )


def test_git_pathspec_is_guarded_and_normalized(tmp_path: Path) -> None:
    trusted = tmp_path.parent / f"{tmp_path.name}-git"
    trusted.mkdir()
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("print('ok')", encoding="utf-8")

    authorized = _authorize(
        tmp_path,
        ["git", "diff", "--", r"src\app.py"],
        purpose="inspect",
        locator=_git_locator(trusted),
    )

    assert authorized.argv[-2:] == ("--", "src/app.py")
    assert "--no-ext-diff" in authorized.argv
    assert "--no-textconv" in authorized.argv


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        (["add", "."], SafetyCode.GIT_SUBCOMMAND_DENIED),
        (["commit", "-m", "x"], SafetyCode.GIT_SUBCOMMAND_DENIED),
        (["checkout", "main"], SafetyCode.GIT_SUBCOMMAND_DENIED),
        (["reset", "--hard"], SafetyCode.GIT_SUBCOMMAND_DENIED),
        (["clean", "-fd"], SafetyCode.GIT_SUBCOMMAND_DENIED),
        (["push"], SafetyCode.GIT_SUBCOMMAND_DENIED),
        (["config", "alias.x", "!calc"], SafetyCode.GIT_SUBCOMMAND_DENIED),
        (["-c", "alias.x=!calc", "x"], SafetyCode.ARGUMENT_DENIED),
        (["--config-env=x=y", "status"], SafetyCode.ARGUMENT_DENIED),
        (["--paginate", "status"], SafetyCode.ARGUMENT_DENIED),
        (["diff", "--ext-diff"], SafetyCode.ARGUMENT_DENIED),
        (["diff", "--textconv"], SafetyCode.ARGUMENT_DENIED),
        (["diff", "--output=stolen.txt"], SafetyCode.ARGUMENT_DENIED),
        (["show", "--show-signature"], SafetyCode.ARGUMENT_DENIED),
        (["log", "--exec=calc.exe"], SafetyCode.ARGUMENT_DENIED),
        (["status", "--", ".."], SafetyCode.ARGUMENT_DENIED),
    ],
)
def test_git_write_extensions_and_unsafe_paths_are_denied(
    tmp_path: Path,
    arguments: list[str],
    code: SafetyCode,
) -> None:
    trusted = tmp_path.parent / f"{tmp_path.name}-git"
    trusted.mkdir()
    _assert_command_violation(
        code,
        lambda: _authorize(
            tmp_path,
            ["git", *arguments],
            purpose="inspect",
            locator=_git_locator(trusted),
        ),
    )


def test_workspace_fake_git_is_not_trusted(tmp_path: Path) -> None:
    fake = tmp_path / "git.exe"
    fake.write_bytes(b"fake")
    _assert_command_violation(
        SafetyCode.EXECUTABLE_DENIED,
        lambda: _authorize(
            tmp_path,
            [str(fake), "status"],
            locator=lambda name: str(fake),
        ),
    )
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_command_safety.py -q
```

Expected: nonzero exit because Git is still denied.

- [ ] **Step 3: Implement the exact Git grammar**

Add constants:

```python
_GIT_SUBCOMMANDS = {"status", "diff", "log", "show", "ls-files"}
_GIT_STATUS_FLAGS = {
    "--short", "--porcelain", "--branch", "--show-stash", "--ignored",
    "--no-renames",
}
_GIT_DIFF_FLAGS = {
    "--check", "--cached", "--staged", "--stat", "--name-only",
    "--name-status",
}
_GIT_HISTORY_FLAGS = {
    "--oneline", "--stat", "--name-only", "--name-status", "--decorate",
}
_GIT_LS_FILES_FLAGS = {
    "--cached", "--others", "--modified", "--deleted", "--exclude-standard",
}
_SAFE_REVISION = re.compile(r"(?:HEAD(?:[~^]\d*)?|[0-9A-Fa-f]{7,40})")
```

Add to `CommandPolicy`:

```python
    def _git_pathspecs(self, values: tuple[str, ...]) -> tuple[str, ...]:
        rendered: list[str] = []
        for value in values:
            if value.startswith("-") or value.startswith("@"):
                raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "Git pathspec is not allowed")
            try:
                rendered.append(self._paths.existing_entry(value).relative)
            except SafetyViolation as exc:
                raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "Git pathspec is not allowed") from exc
        return tuple(rendered)

    def _authorize_git(self, arguments: tuple[str, ...]) -> tuple[str, ...]:
        if not arguments:
            raise SafetyViolation(SafetyCode.GIT_SUBCOMMAND_DENIED, "Git subcommand is not allowed")
        if arguments[0].startswith("-"):
            raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "Git global options are not allowed")
        subcommand = arguments[0]
        if subcommand not in _GIT_SUBCOMMANDS:
            raise SafetyViolation(SafetyCode.GIT_SUBCOMMAND_DENIED, "Git subcommand is not allowed")
        values = arguments[1:]
        before, separator, after = values, (), ()
        if "--" in values:
            marker = values.index("--")
            before, separator, after = values[:marker], ("--",), values[marker + 1:]
        rendered: list[str] = [subcommand]
        if subcommand == "status":
            for value in before:
                allowed_untracked = value.startswith("--untracked-files=") and value.partition("=")[2] in {"no", "normal", "all"}
                if value not in _GIT_STATUS_FLAGS and not allowed_untracked:
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "Git status arguments are not allowed")
                rendered.append(value)
        elif subcommand == "diff":
            revisions = 0
            rendered.extend(("--no-ext-diff", "--no-textconv"))
            for value in before:
                if value in _GIT_DIFF_FLAGS or re.fullmatch(r"-U\d+", value):
                    rendered.append(value)
                elif _SAFE_REVISION.fullmatch(value) and revisions < 2:
                    rendered.append(value)
                    revisions += 1
                else:
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "Git diff arguments are not allowed")
        elif subcommand in {"log", "show"}:
            revisions = 0
            rendered.extend(("--no-ext-diff", "--no-textconv"))
            index = 0
            while index < len(before):
                value = before[index]
                if value in _GIT_HISTORY_FLAGS:
                    rendered.append(value)
                elif value == "-n" and index + 1 < len(before) and before[index + 1].isdigit() and int(before[index + 1]) > 0:
                    rendered.extend((value, before[index + 1]))
                    index += 1
                elif value.startswith("--max-count=") and value.partition("=")[2].isdigit() and int(value.partition("=")[2]) > 0:
                    rendered.append(value)
                elif _SAFE_REVISION.fullmatch(value) and revisions < 1:
                    rendered.append(value)
                    revisions += 1
                else:
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "Git history arguments are not allowed")
                index += 1
        else:
            for value in before:
                if value not in _GIT_LS_FILES_FLAGS:
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "Git ls-files arguments are not allowed")
                rendered.append(value)
        if separator:
            rendered.append("--")
            rendered.extend(self._git_pathspecs(after))
        return tuple(rendered)
```

Before final denial in `authorize()`:

```python
        if Path(argv[0]).name.casefold() in {"git", "git.exe"}:
            executable = self._trusted_launcher(
                argv[0],
                {"git", "git.exe"},
                allow_runtime=False,
            )
            git_arguments = self._authorize_git(argv[1:])
            final = (
                str(executable),
                "-c", "core.fsmonitor=false",
                "-c", "diff.external=",
                "--no-pager",
                *git_arguments,
            )
            return AuthorizedCommand(
                argv=tuple(final),
                normalized_command=subprocess.list2cmdline(final),
                purpose=purpose,
                source=source,
            )
```

- [ ] **Step 4: Run GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_command_safety.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_cli.py -q
```

Expected: both exit 0. Git writes, configuration injection, pager, external diff, textconv, output-file, and unsafe pathspec forms reject deterministically.

**Acceptance:** Only the five lower-case read-only subcommands and their exact option grammars authorize; policy-inserted fixed `-c` values are not model-controlled.

---

### Task 10: Denied executable matrix, environment-prefix/response/path arguments, and trusted lookup

**Files:** Modify `src/coding_agent/safety.py` and `tests/test_command_safety.py`.

**Interfaces:** Finalizes deny-by-default executable discovery and common argument rejection.

- [ ] **Step 1: Append the failing denial matrix**

```python
@pytest.mark.parametrize(
    "argv",
    [
        ["powershell.exe", "-Command", "Get-ChildItem"],
        ["pwsh.exe", "-Command", "Get-ChildItem"],
        ["cmd.exe", "/c", "dir"],
        ["bash.exe", "-c", "ls"],
        ["sh.exe", "-c", "ls"],
        ["wsl.exe", "ls"],
        ["curl.exe", "https://example.com"],
        ["wget.exe", "https://example.com"],
        ["ssh.exe", "host"],
        ["pip.exe", "install", "package"],
        ["npm.cmd", "install"],
        ["winget.exe", "install", "package"],
        ["taskkill.exe", "/PID", "1"],
        ["reg.exe", "query", "HKCU"],
        ["sc.exe", "query"],
        ["net.exe", "user"],
        ["del", "file.txt"],
        ["move", "a", "b"],
        ["unknown.exe", "value"],
    ],
)
def test_unknown_shell_network_package_admin_and_prefix_programs_are_denied(
    tmp_path: Path,
    argv: list[str],
) -> None:
    _assert_command_violation(
        SafetyCode.EXECUTABLE_DENIED,
        lambda: _authorize(tmp_path, argv),
    )


def test_workspace_path_entry_cannot_shadow_runtime_pytest(tmp_path: Path) -> None:
    fake = tmp_path / "pytest.exe"
    fake.write_bytes(b"fake")
    authorized = _authorize(
        tmp_path,
        ["pytest", "-q"],
        locator=lambda name: str(fake),
    )
    assert authorized.argv[0] == str(
        Path(sys.executable).with_name("pytest.exe").resolve(strict=True)
    )
    assert authorized.argv[0] != str(fake.resolve())


def test_relative_workspace_pytest_launcher_is_denied(tmp_path: Path) -> None:
    (tmp_path / "pytest.exe").write_bytes(b"fake")
    _assert_command_violation(
        SafetyCode.EXECUTABLE_DENIED,
        lambda: _authorize(tmp_path, [r".\pytest.exe", "-q"]),
    )


def test_environment_assignment_prefix_is_an_argument_rejection(tmp_path: Path) -> None:
    _assert_command_violation(
        SafetyCode.ARGUMENT_DENIED,
        lambda: _authorize(tmp_path, ["NAME=value", "python", "script.py"]),
    )


@pytest.mark.parametrize(
    "argument",
    ["@response.txt", "../outside", r"C:\outside", r"\\server\share"],
)
def test_python_script_arguments_reject_response_absolute_and_parent_paths(
    tmp_path: Path,
    argument: str,
) -> None:
    script = tmp_path / "script.py"
    script.write_text("print('ok')", encoding="utf-8")
    _assert_command_violation(
        SafetyCode.ARGUMENT_DENIED,
        lambda: _authorize(tmp_path, ["python", "script.py", argument]),
    )
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_command_safety.py -q
```

Expected: nonzero exit with exactly the new environment-assignment test failing because deny-by-default currently classifies the prefix as `EXECUTABLE_DENIED` instead of the locked `ARGUMENT_DENIED`. Unknown programs and workspace fakes must already be denied; an unexpected authorization stops the step.

- [ ] **Step 3: Add the common environment-assignment rejection**

Immediately after parsing argv and before executable-category dispatch, add:

```python
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[0]):
            raise SafetyViolation(
                SafetyCode.ARGUMENT_DENIED,
                "environment assignment prefixes are not allowed",
            )
```

Do not change `_trusted_launcher`: Task 7 already supplies its exact sanitized lookup and workspace-fake filtering, and Task 10's tests verify those behaviors. Keep final executable denial unconditional; do not add generic PATH execution.

- [ ] **Step 4: Run GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_command_safety.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_cli.py -q
```

Expected: both exit 0 and report actual counts. No denied executable is launched, no response file is consumed, and no workspace lookalike becomes trusted.

**Acceptance:** The executable set is closed, trusted paths are resolved deterministically, and missing tools cause refusal instead of lookup expansion.

---

### Task 11: Route every filesystem tool through PathGuard

**Files:**

- Modify: `src/coding_agent/tools/filesystem.py`
- Modify: `tests/tools/test_read_tools.py`
- Modify: `tests/tools/test_write_tools.py`

**Interfaces:** Consumes `PathGuard`, `GuardedPath`, `SafetyViolation`, and `SafetyCode`. Removes the Task 5 `_functional_workspace_path` and `_relative_output_path` security sources.

- [ ] **Step 1: Append the failing filesystem integration tests**

Append to `tests/tools/test_read_tools.py`:

```python
@pytest.mark.parametrize("protected", [".git/config", ".GIT/config", ".coding-agent/log.jsonl"])
def test_read_file_uses_path_guard_for_protected_paths(
    tmp_path: Path,
    protected: str,
) -> None:
    target = tmp_path.joinpath(*protected.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("secret", encoding="utf-8")

    with pytest.raises(SafetyViolation) as exc_info:
        ReadFileTool().execute(_read_arguments(path=protected), _context(tmp_path))
    assert exc_info.value.code is SafetyCode.PROTECTED_PATH


def test_read_and_list_call_public_path_guard_methods(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "notes.txt").write_text("text", encoding="utf-8")
    calls: list[tuple[str, object]] = []
    real_file = PathGuard.existing_file
    real_directory = PathGuard.existing_directory

    def observed_file(self: PathGuard, raw_path: object):
        calls.append(("file", raw_path))
        return real_file(self, raw_path)

    def observed_directory(self: PathGuard, raw_path: object):
        calls.append(("directory", raw_path))
        return real_directory(self, raw_path)

    monkeypatch.setattr(PathGuard, "existing_file", observed_file)
    monkeypatch.setattr(PathGuard, "existing_directory", observed_directory)
    ReadFileTool().execute(_read_arguments(), _context(tmp_path))
    ListDirectoryTool().execute(_list_arguments(), _context(tmp_path))

    assert ("file", "notes.txt") in calls
    assert ("directory", ".") in calls
```

Add the needed import:

```python
from coding_agent.safety import PathGuard, SafetyCode, SafetyViolation
```

Append to `tests/tools/test_write_tools.py`:

```python
from coding_agent.safety import PathGuard, SafetyCode, SafetyViolation


@pytest.mark.parametrize(
    "path",
    [".git/config", ".GIT/config", ".coding-agent/logs/run.jsonl"],
)
def test_write_tools_reject_protected_paths_without_side_effect(
    tmp_path: Path,
    path: str,
) -> None:
    target = tmp_path.joinpath(*path.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    before = {
        item.relative_to(tmp_path).as_posix()
        for item in tmp_path.rglob("*")
    }

    with pytest.raises(SafetyViolation) as exc_info:
        WriteFileTool().execute(
            {"path": path, "content": "secret"},
            _context(tmp_path),
        )

    assert exc_info.value.code is SafetyCode.PROTECTED_PATH
    assert not target.exists()
    assert {
        item.relative_to(tmp_path).as_posix()
        for item in tmp_path.rglob("*")
    } == before


def test_replace_reparse_path_is_denied_and_target_bytes_are_unchanged(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_bytes(b"old\r\n")
    link = tmp_path / "linked.txt"
    try:
        os.symlink(outside, link, target_is_directory=False)
    except OSError as exc:
        winerror = getattr(exc, "winerror", None)
        if winerror == 1314:
            pytest.fail(
                "Task 8 file-symlink behavior remains unverified because "
                "the test account lacks symlink privilege (winerror=1314)"
            )
        pytest.fail(
            "Task 8 requires a real Windows file symlink; "
            f"unexpected winerror={winerror}"
        )
    before = outside.read_bytes()

    with pytest.raises(SafetyViolation) as exc_info:
        ReplaceTextTool().execute(
            _replace_arguments(
                path="linked.txt",
                old_text="old",
                new_text="new",
                expected_count=1,
            ),
            _context(tmp_path),
        )

    assert exc_info.value.code is SafetyCode.REPARSE_POINT_DENIED
    assert outside.read_bytes() == before


def test_replace_and_write_call_public_path_guard_methods(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "sample.txt").write_text("old", encoding="utf-8")
    calls: list[tuple[str, object]] = []
    real_file = PathGuard.existing_file
    real_new = PathGuard.new_file

    def observed_file(self: PathGuard, raw_path: object):
        calls.append(("file", raw_path))
        return real_file(self, raw_path)

    def observed_new(self: PathGuard, raw_path: object):
        calls.append(("new", raw_path))
        return real_new(self, raw_path)

    monkeypatch.setattr(PathGuard, "existing_file", observed_file)
    monkeypatch.setattr(PathGuard, "new_file", observed_new)
    ReplaceTextTool().execute(_replace_arguments(), _context(tmp_path))
    WriteFileTool().execute(
        {"path": "created.txt", "content": "content"},
        _context(tmp_path),
    )

    assert calls == [("file", "sample.txt"), ("new", "created.txt")]
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py tests\tools\test_write_tools.py -q
```

Expected: nonzero exit because read/replace/write still call `_functional_workspace_path` and the list migration is incomplete.

- [ ] **Step 3: Replace temporary path checks, without layering duplicate checks**

In `filesystem.py`, remove `_functional_workspace_path`, `_relative_output_path`, and the now-unused `os` import. Import:

```python
from coding_agent.safety import (
    GuardedPath,
    PathGuard,
    SafetyCode,
    SafetyViolation,
)
```

Replace directory traversal with this complete implementation:

```python
def _iter_directory_entries(
    guard: PathGuard,
    directory: GuardedPath,
    *,
    recursive: bool,
    max_depth: int,
    depth: int = 1,
) -> Iterator[GuardedPath]:
    for child in _directory_children(directory.absolute):
        raw_relative = child.relative_to(guard.workspace).as_posix()
        try:
            guarded_child = guard.existing_entry(raw_relative)
        except SafetyViolation as exc:
            if exc.code in {
                SafetyCode.PROTECTED_PATH,
                SafetyCode.REPARSE_POINT_DENIED,
            }:
                continue
            raise
        yield guarded_child
        if recursive and guarded_child.absolute.is_dir() and depth < max_depth:
            yield from _iter_directory_entries(
                guard,
                guarded_child,
                recursive=True,
                max_depth=max_depth,
                depth=depth + 1,
            )
```

Use these exact authorization replacements in each tool:

```python
        guard = PathGuard(context.workspace)
        directory = guard.existing_directory(values["path"])

        for child in _iter_directory_entries(
            guard,
            directory,
            recursive=values["recursive"],
            max_depth=values["max_depth"],
        ):
            entries.append(
                {"path": child.relative, "type": _entry_type(child.absolute)}
            )

        target = PathGuard(context.workspace).existing_file(values["path"]).absolute

        guarded_target = PathGuard(context.workspace).existing_file(values["path"])
        target = guarded_target.absolute
        relative = guarded_target.relative

        guarded_target = PathGuard(context.workspace).new_file(values["path"])
        target = guarded_target.absolute
        relative = guarded_target.relative
```

For `ReplaceTextTool` and `WriteFileTool`, replace every existing output `path` value and every `ToolResultMetadata.changed_paths` entry with `relative`; keep all reads, replacements, byte checks, and the exclusive `xb` write against `target`. For `ReadFileTool`, keep the existing output and truncation logic unchanged after replacing its target assignment. For `ListDirectoryTool`, retain the existing `max_entries` stop condition around the shown loop so the first entry beyond the retained limit sets `truncated=True` exactly as in Task 5.

Delete all duplicated `exists()`, file/directory, parent, drive, `..`, commonpath, and relative-output checks that are now guaranteed by `PathGuard`. Retain content/range/encoding/size/match validation and exclusive `xb` creation. Keep the `FileExistsError` race mapping as `ToolArgumentError("file already exists")`.

- [ ] **Step 4: Run GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py tests\tools\test_write_tools.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_cli.py -q
```

Expected: both exit 0. Report actual counts. Task 5/6 output, truncation, BOM/CRLF, byte limits, match count, exclusive creation, and ledger tests remain unchanged.

**Acceptance:** There is no `_functional_workspace_path`; all list/read/replace/write paths and recursive children pass through `PathGuard`, and safety rejection has zero mutation/ledger side effect.

---

### Task 12: Route RunCommandTool through CommandPolicy and harden the child environment

**Files:** Modify `src/coding_agent/tools/shell.py` and `tests/tools/test_shell_tool.py`.

**Interfaces:** `RunCommandTool` consumes only `AuthorizedCommand.argv`; Task 7 execution/output interfaces remain unchanged. Adds an optional `policy_factory` test seam without changing the tool schema.

- [ ] **Step 1: Update/add failing shell integration tests**

Change `_command_for_script` in `tests/tools/test_shell_tool.py` so model input is workspace-relative while expected executed argv remains canonical:

```python
def _command_for_script(script: Path, *arguments: str) -> str:
    return subprocess.list2cmdline(
        [sys.executable, script.name, *arguments]
    )
```

For the process-tree test, pass `child.name` and `marker.name`; trusted parent code resolves them from its fixed cwd. Append:

```python
from coding_agent.safety import (
    AuthorizedCommand,
    CommandPolicy,
    CommandSource,
    SafetyCode,
    SafetyViolation,
)


def test_run_command_executes_only_policy_returned_argv(tmp_path: Path) -> None:
    requested = "this raw string must not be parsed or executed"
    safe_script = tmp_path / "safe.py"
    safe_script.write_text("print('safe')\n", encoding="utf-8")
    observed: dict[str, object] = {}

    class RecordingPolicy:
        workspace = tmp_path.resolve()

        def authorize(
            self,
            command: object,
            *,
            purpose: str,
            source: CommandSource,
        ) -> AuthorizedCommand:
            observed["command"] = command
            observed["purpose"] = purpose
            observed["source"] = source
            argv = (sys.executable, str(safe_script.resolve()))
            return AuthorizedCommand(
                argv=argv,
                normalized_command=subprocess.list2cmdline(argv),
                purpose=purpose,
                source=source,
            )

    execution = RunCommandTool(
        policy_factory=lambda workspace: RecordingPolicy(),  # type: ignore[arg-type]
    ).execute(
        {"command": requested, "purpose": "inspect"},
        ExecutionContext(tmp_path),
    )

    payload = json.loads(execution.output or "")
    assert observed == {
        "command": requested,
        "purpose": "inspect",
        "source": CommandSource.MODEL,
    }
    assert payload["argv"] == [sys.executable, str(safe_script.resolve())]
    assert payload["stdout"] == "safe\r\n"


def test_run_command_security_rejection_does_not_start_process(tmp_path: Path) -> None:
    started = False

    def forbidden_factory(*args: object, **kwargs: object) -> object:
        nonlocal started
        started = True
        raise AssertionError("process must not start")

    with pytest.raises(SafetyViolation) as exc_info:
        RunCommandTool(process_factory=forbidden_factory).execute(
            {"command": "powershell.exe -Command Get-Date", "purpose": "inspect"},
            ExecutionContext(tmp_path),
        )
    assert exc_info.value.code is SafetyCode.EXECUTABLE_DENIED
    assert started is False


def test_child_environment_removes_policy_widening_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in {
        "OPENAI_API_KEY": "secret",
        "PYTHONPATH": "outside",
        "PYTHONHOME": "outside",
        "PYTEST_ADDOPTS": "-p dangerous",
        "PYTEST_PLUGINS": "dangerous",
        "MYPYPATH": "outside",
        "MYPY_CONFIG_FILE": "outside.ini",
        "GIT_DIR": "outside",
        "GIT_WORK_TREE": "outside",
        "GIT_OBJECT_DIRECTORY": "outside",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": "outside",
        "GIT_EXTERNAL_DIFF": "dangerous.exe",
        "GIT_SSH": "dangerous.exe",
        "GIT_SSH_COMMAND": "dangerous.exe",
        "GIT_ASKPASS": "dangerous.exe",
        "SSH_ASKPASS": "dangerous.exe",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "alias.x",
        "GIT_CONFIG_VALUE_0": "!dangerous.exe",
    }.items():
        monkeypatch.setenv(key, value)
    script = tmp_path / "env.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def recording_factory(
        argv: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.Popen[bytes]:
        observed.update(kwargs)
        return subprocess.Popen(argv, **kwargs)  # type: ignore[arg-type]

    execution = RunCommandTool(process_factory=recording_factory).execute(
        {"command": _command_for_script(script), "purpose": "test"},
        ExecutionContext(tmp_path),
    )

    assert execution.metadata.exit_code == 0
    environment = observed["env"]
    assert isinstance(environment, dict)
    folded = {key.casefold() for key in environment}
    for denied in {
        "openai_api_key", "pythonpath", "pythonhome", "pytest_addopts",
        "pytest_plugins", "mypypath", "mypy_config_file", "git_dir", "git_work_tree", "git_object_directory",
        "git_alternate_object_directories", "git_external_diff",
        "git_ssh", "git_ssh_command", "git_askpass", "ssh_askpass",
        "git_config_count", "git_config_key_0", "git_config_value_0",
    }:
        assert denied not in folded
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_CONFIG_GLOBAL"] == "NUL"
    assert environment["GIT_PAGER"] == "cat"
    assert environment["PAGER"] == "cat"
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["GIT_NO_LAZY_FETCH"] == "1"
```

Update the schema description assertion to `"Run an authorized command in the workspace."`. Replace temporary-boundary error-message assertions with exact `SafetyCode` assertions. Keep all output, nonzero-exit, dual-stream, 64 KiB, timeout, monotonic duration, startup-error, cleanup-failure, and Windows process-tree tests.

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py -q
```

Expected: nonzero exit because `RunCommandTool` has no `policy_factory`, still runs the temporary Task 7 authorizer, and does not sanitize the expanded environment set.

- [ ] **Step 3: Replace the temporary authorizer with the unified policy**

In `shell.py`, import:

```python
from coding_agent.safety import (
    CommandPolicy,
    CommandSource,
    parse_windows_command_line,
)
```

Keep `parse_windows_command_line` imported at module scope solely as the Task 7-compatible re-export. Delete `_normalized_workspace`, `_same_path`, and `_authorize_temporary_command`. Remove NUL handling from `_validated_arguments`; nonempty command and purpose remain functional argument checks, while `CommandPolicy` owns NUL/control rejection.

Add:

```python
PolicyFactory = Callable[[Path], CommandPolicy]
```

Extend `RunCommandTool.__init__`:

```python
        policy_factory: PolicyFactory | None = None,
```

Store:

```python
        self._policy_factory = CommandPolicy if policy_factory is None else policy_factory
```

Replace the beginning of `execute()` with:

```python
        command, purpose = _validated_arguments(arguments)
        policy = self._policy_factory(context.workspace)
        authorized = policy.authorize(
            command,
            purpose=purpose,
            source=CommandSource.MODEL,
        )
        argv = authorized.argv
        workspace = policy.workspace
```

Update the schema description to `Run an authorized command in the workspace.`. Keep `shell=False`, fixed `cwd=workspace`, `DEVNULL`, output readers, timeout, tree termination, and result mapping byte-for-byte equivalent.

Replace `_child_environment()` with:

```python
_REMOVED_ENVIRONMENT_KEYS = {
    "openai_api_key", "pythonpath", "pythonhome", "pytest_addopts",
    "pytest_plugins", "mypypath", "mypy_config_file", "git_dir", "git_work_tree", "git_object_directory",
    "git_alternate_object_directories", "git_external_diff", "git_ssh",
    "git_ssh_command", "git_askpass", "ssh_askpass",
}


def _child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        folded = key.casefold()
        if (
            folded in _REMOVED_ENVIRONMENT_KEYS
            or folded == "git_config_count"
            or folded.startswith("git_config_key_")
            or folded.startswith("git_config_value_")
        ):
            environment.pop(key, None)
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "NUL",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_LAZY_FETCH": "1",
        }
    )
    return environment
```

- [ ] **Step 4: Run GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_cli.py -q
```

Expected: both exit 0. Report actual counts. All Task 7 process behavior remains green, unsafe requests never call the process factory, and recorded Popen argv is exactly the authorized tuple.

**Acceptance:** `RunCommandTool` has no local executable whitelist/parser path; it executes only `AuthorizedCommand.argv` with `shell=False`, fixed canonical cwd, bounded output/timeout, and sanitized environment.

---

### Task 13: Authorize and store --verify before agent startup

**Files:** Modify `src/coding_agent/config.py`, `src/coding_agent/cli.py`, and `tests/test_cli.py`.

**Interfaces:** `RunConfig.verify_command` changes from `str | None` to `AuthorizedCommand | None` with `repr=False`. `load_run_config` and `main` signatures remain unchanged.

- [ ] **Step 1: Update/add failing config and CLI tests**

In `tests/test_cli.py`, import:

```python
from coding_agent.safety import (
    AuthorizedCommand,
    CommandSource,
    SafetyCode,
    SafetyViolation,
)
```

Replace the `RunConfig` equality in `test_config_normalizes_workspace` with:

```python
    assert config.task == "inspect the project"
    assert config.workspace == workspace.resolve()
    assert config.model == "env-model"
    assert config.api_key == SECRET_SENTINEL
    assert isinstance(config.verify_command, AuthorizedCommand)
    assert config.verify_command.purpose == "verification"
    assert config.verify_command.source is CommandSource.USER_VERIFY
    assert config.verify_command.argv[-1] == "-q"
```

Append:

```python
@pytest.mark.parametrize(
    ("verify", "code"),
    [
        ("powershell.exe -Command Get-Date", "executable_denied"),
        ("git commit -m unsafe", "git_subcommand_denied"),
        ("curl.exe https://example.com", "executable_denied"),
        ('python "unterminated', "command_parse_error"),
    ],
)
def test_config_rejects_unsafe_verify_without_echoing_command(
    tmp_path: Path,
    verify: str,
    code: str,
) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_run_config(
            task="inspect",
            workspace=tmp_path,
            model=None,
            verify_command=verify,
            environ=valid_environ(),
        )

    message = str(exc_info.value)
    assert message.startswith(f"--verify rejected ({code}): ")
    assert verify not in message
    assert SECRET_SENTINEL not in message


def test_config_rejects_verify_script_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print('unsafe')", encoding="utf-8")
    command = subprocess.list2cmdline([sys.executable, str(outside)])

    with pytest.raises(ConfigError, match="path_outside_workspace"):
        load_run_config(
            task="inspect",
            workspace=workspace,
            model=None,
            verify_command=command,
            environ=valid_environ(),
        )


def test_config_routes_workspace_validation_through_path_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RejectingPathGuard:
        def __init__(self, workspace: Path) -> None:
            assert workspace == tmp_path
            raise SafetyViolation(
                SafetyCode.REPARSE_POINT_DENIED,
                "workspace reparse points are unavailable",
            )

    monkeypatch.setattr("coding_agent.config.PathGuard", RejectingPathGuard)

    with pytest.raises(
        ConfigError,
        match=(
            r"workspace rejected \(reparse_point_denied\): "
            r"workspace reparse points are unavailable"
        ),
    ):
        load_run_config(
            task="inspect",
            workspace=tmp_path,
            model=None,
            verify_command=None,
            environ=valid_environ(),
        )


@pytest.mark.parametrize(
    "verify",
    ["pytest -q", "python -m pytest -q"],
)
def test_cli_authorizes_safe_verify_before_returning_success(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    verify: str,
) -> None:
    exit_code = main(
        ["inspect", "--workspace", str(tmp_path), "--verify", verify],
        environ=valid_environ(),
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert verify not in captured.out
    assert verify not in captured.err
    assert SECRET_SENTINEL not in captured.out + captured.err


def test_cli_unsafe_verify_exits_two_before_agent_or_model_import(
    tmp_path: Path,
) -> None:
    script = f"""
import builtins
real_import = builtins.__import__
def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name in {{'coding_agent.agent', 'coding_agent.model'}}:
        raise AssertionError('agent/model imported before verify authorization')
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = guarded_import
from coding_agent.cli import main
code = main(
    ['inspect', '--workspace', {str(tmp_path)!r}, '--verify', 'git commit -m unsafe'],
    environ={{'OPENAI_MODEL': 'fake', 'OPENAI_API_KEY': 'not-printed'}},
)
raise SystemExit(code)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 2
    assert "git_subcommand_denied" in completed.stderr
    assert "git commit -m unsafe" not in completed.stderr
    assert "not-printed" not in completed.stdout + completed.stderr


def test_run_config_repr_hides_authorized_verify_and_secret(tmp_path: Path) -> None:
    config = load_run_config(
        task="inspect",
        workspace=tmp_path,
        model=None,
        verify_command="pytest -q",
        environ=valid_environ(),
    )
    rendered = repr(config)
    assert "pytest" not in rendered
    assert "verify_command=" not in rendered
    assert SECRET_SENTINEL not in rendered
```

Keep the existing empty verify test; empty/whitespace remains `ConfigError("--verify must not be empty")`, not a safety parse error.

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
```

Expected: nonzero exit because `RunConfig` stores raw text and unsafe commands are not authorized.

- [ ] **Step 3: Store only an authorized verify structure**

In `config.py`, import:

```python
from coding_agent.safety import (
    AuthorizedCommand,
    CommandPolicy,
    CommandSource,
    PathGuard,
    SafetyCode,
    SafetyViolation,
)
```

Change the field to:

```python
    verify_command: AuthorizedCommand | None = field(default=None, repr=False)
```

Replace the existing direct `Path.resolve()`/`exists()`/`is_dir()` normalization block with the following policy-owned normalization. This code must run before verify authorization:

```python
    workspace_path = Path(workspace).expanduser()
    try:
        normalized_workspace = PathGuard(workspace_path).workspace
    except SafetyViolation as exc:
        if exc.code is SafetyCode.WORKSPACE_INVALID:
            if not workspace_path.exists():
                raise ConfigError("workspace does not exist") from None
            if not workspace_path.is_dir():
                raise ConfigError("workspace must be a directory") from None
        raise ConfigError(
            f"workspace rejected ({exc.code.value}): {exc.public_message}"
        ) from None
```

Also import `SafetyCode` in the same import group. `PathGuard` owns canonicalization, root reparse rejection, and containment; the two generic `WORKSPACE_INVALID` mappings preserve Task 1's user-facing missing/file distinction without disclosing an absolute system path.

Before returning `RunConfig`, replace raw verify storage with:

```python
    authorized_verify: AuthorizedCommand | None = None
    if verify_command is not None:
        normalized_verify = verify_command.strip()
        if not normalized_verify:
            raise ConfigError("--verify must not be empty")
        try:
            authorized_verify = CommandPolicy(normalized_workspace).authorize(
                normalized_verify,
                purpose="verification",
                source=CommandSource.USER_VERIFY,
            )
        except SafetyViolation as exc:
            raise ConfigError(
                f"--verify rejected ({exc.code.value}): {exc.public_message}"
            ) from None
```

Pass `workspace=normalized_workspace` and `verify_command=authorized_verify` into `RunConfig`. Do not retain another workspace resolver or containment implementation in `config.py`.

In `cli.py`, change `--verify` help to `Optional final verification command; authorized now and executed by Task 11.` Do not import AgentRunner/model, execute the authorized command, or add success gating.

- [ ] **Step 4: Run GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_cli.py -q
```

Expected: both exit 0. Unsafe verify returns 2 before agent/model import, safe `pytest -q` and `python -m pytest -q` store authorized argv, and neither raw command nor API key appears in output/repr.

**Acceptance:** Model `run_command` and user `--verify` use the same `CommandPolicy`; only source differs. Task 8 authorizes but does not execute final verification or decide success.

---

### Task 14: Cross-entry bypass and zero-side-effect integration

**Files:** Modify `tests/test_path_safety.py`, `tests/test_command_safety.py`, `tests/test_agent_loop.py`, `tests/tools/test_read_tools.py`, `tests/tools/test_write_tools.py`, and `tests/tools/test_shell_tool.py` only if a missing cross-entry assertion is discovered. Production changes are allowed only to correct a demonstrated Task 8 policy bypass.

**Interfaces:** Verifies all public entry points use the interfaces already locked; no new API.

- [ ] **Step 1: Add the failing cross-entry tests**

Append to `tests/test_command_safety.py`:

```python
def test_model_and_user_verify_share_identical_rules(tmp_path: Path) -> None:
    script = tmp_path / "verify.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    command = subprocess.list2cmdline(["python", "verify.py"])
    policy = CommandPolicy(tmp_path)

    model = policy.authorize(
        command,
        purpose="verification",
        source=CommandSource.MODEL,
    )
    user = policy.authorize(
        command,
        purpose="verification",
        source=CommandSource.USER_VERIFY,
    )

    assert model.argv == user.argv
    assert model.normalized_command == user.normalized_command
    assert model.source is CommandSource.MODEL
    assert user.source is CommandSource.USER_VERIFY


@pytest.mark.parametrize("purpose", ["inspect", "test", "verification"])
def test_purpose_cannot_authorize_forbidden_executable(
    tmp_path: Path,
    purpose: str,
) -> None:
    _assert_command_violation(
        SafetyCode.EXECUTABLE_DENIED,
        lambda: CommandPolicy(tmp_path).authorize(
            "cmd.exe /c dir",
            purpose=purpose,
            source=CommandSource.MODEL,
        ),
    )
```

Append to `tests/test_agent_loop.py`:

```python
def test_agent_safety_rejection_has_no_mutation_ledger_effect(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret", encoding="utf-8")
    call = ToolCall(
        call_id="protected_read",
        name="read_file",
        arguments={"path": ".GIT/config", "start_line": 1, "end_line": None},
    )
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="stopped")),
        tools=(ReadFileTool(),),
    )

    state = runner.run("attempt protected read")

    result = client.requests[1].messages[2]
    assert isinstance(result, ToolResult)
    assert result.status == "rejected"
    assert result.error == "security_rejected:protected_path: protected path is unavailable"
    assert state.mutation_index == 0
    assert state.modified_paths == ()
    assert state.verification_status is VerificationStatus.NOT_RUN
```

Append to `tests/test_path_safety.py`:

```python
@pytest.mark.parametrize(
    "raw_path",
    [
        r"nested/.GiT/config",
        r"nested\.CODING-agent/logs/run.jsonl",
        r"nested/./.git/config",
    ],
)
def test_mixed_separator_normalization_cannot_bypass_protection(
    tmp_path: Path,
    raw_path: str,
) -> None:
    _assert_violation(
        SafetyCode.PROTECTED_PATH,
        lambda: PathGuard(tmp_path).new_file(raw_path),
    )
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\test_command_safety.py tests\test_agent_loop.py::test_agent_safety_rejection_has_no_mutation_ledger_effect -q
```

Expected: if all tests pass immediately, that is acceptable only for this integration-only stage because each production behavior already had an earlier RED. Record the result as an integration confirmation, not a new TDD RED. Any failure is a concrete bypass; stop, use `systematic-debugging`, and make only the smallest Task 8 correction.

- [ ] **Step 3: Verify that temporary sources are gone**

Run:

```powershell
$temporary = Get-ChildItem -Path src,tests -Recurse -File | Select-String -Pattern '_functional_workspace_path|_authorize_temporary_command|_normalized_workspace|temporary Task 7 boundary'
if ($temporary) { $temporary; throw 'temporary security source remains' }
Get-ChildItem -Path src\coding_agent\tools,src\coding_agent\config.py -Recurse -File | Select-String -Pattern 'PathGuard|CommandPolicy'
```

Expected: the first check produces no matches and does not throw; the second shows all four filesystem tools, list traversal, `RunCommandTool`, and config integration. Any old security source must be removed rather than wrapped.

- [ ] **Step 4: Run focused GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\test_command_safety.py tests\test_agent_loop.py::test_agent_safety_rejection_has_no_mutation_ledger_effect -q
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py tests\test_cli.py -q
```

Expected: both exit 0. Report actual counts. No unsafe request changes a file, starts a process, or updates the mutation ledger.

**Acceptance:** There is one path policy, one command policy, no `purpose`/source bypass, no protected case/separator bypass, and Registry feedback remains structured and stable.

---

### Task 15: Offline boundary, final verification, diff review, and user stop

**Files:** Verification only. Task 8 remains `进行中`; do not stage or commit.

**Interfaces:** Verify the exact public signatures and no Task 2–7 regression.

- [ ] **Step 1: Run the offline import boundary**

Run:

```powershell
$env:OPENAI_API_KEY = $null
.\.venv\Scripts\python.exe -c "import builtins; real=builtins.__import__; builtins.__import__=lambda name,*a,**k: (_ for _ in ()).throw(AssertionError(name)) if name == 'openai' or name.startswith('openai.') or name in {'socket','requests','urllib','http'} else real(name,*a,**k); import coding_agent.safety, coding_agent.tools.filesystem, coding_agent.tools.shell, coding_agent.config, coding_agent.cli"
```

Expected: exit 0, no network module/OpenAI import, and no API key requirement at import time.

- [ ] **Step 2: Run every focused security and migrated component suite**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_command_safety.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py tests\tools\test_write_tools.py -q
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q
```

Expected: every command exits 0. Report actual pass/fail/skip/warning counts separately. Any real Windows symlink/junction test that cannot run keeps Task 8 unverified; no skip/xfail can replace it.

- [ ] **Step 3: Run the complete repository suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit 0 with actual counts. Do not infer counts from this plan.

- [ ] **Step 4: Verify signatures, type reuse, and exact policy ownership**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import inspect; from coding_agent.safety import PathGuard, CommandPolicy; assert str(inspect.signature(PathGuard.existing_file)) == '(self, raw_path: \'object\') -> \'GuardedPath\''; assert str(inspect.signature(PathGuard.existing_directory)) == '(self, raw_path: \'object\') -> \'GuardedPath\''; assert str(inspect.signature(PathGuard.new_file)) == '(self, raw_path: \'object\') -> \'GuardedPath\''; assert str(inspect.signature(CommandPolicy.authorize)) == '(self, command: \'object\', *, purpose: \'str\', source: \'CommandSource\') -> \'AuthorizedCommand\''; print('Task 8 public signatures verified')"
Get-ChildItem -Path src\coding_agent -Recurse -File -Filter *.py | Select-String -Pattern 'class (ToolResult|ToolResultMetadata|ToolExecution|ToolArgumentError|ExecutionContext)'
$forbidden = Get-ChildItem -Path src\coding_agent -Recurse -File -Filter *.py | Select-String -Pattern '_functional_workspace_path|_authorize_temporary_command|_normalized_workspace|str\.split\(|shlex|shell=True|os\.chdir'
if ($forbidden) { $forbidden; throw 'duplicate or prohibited implementation remains' }
```

Expected: signatures match the locked interfaces; existing Task 2–7 types are defined only in their original modules; the final forbidden-source check produces no matches and does not throw. `parse_windows_command_line` appears in `safety.py` and as a shell import/re-export only.

- [ ] **Step 5: Run the allow/deny, protected, reparse, and startup matrices explicitly**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py -k "protected or symlink or junction or reparse or dangling or outside or windows_path" -q
.\.venv\Scripts\python.exe -m pytest tests\test_command_safety.py -k "python or pytest or unittest or ruff or mypy or git or denied or control or source or purpose" -q
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -k "verify or secret or repr" -q
```

Expected: all selected tests pass with zero skip/xfail. Report exact selection counts.

- [ ] **Step 6: Audit dependencies, offline scope, secrets, unfinished markers, and test suppression**

Run:

```powershell
git diff -- pyproject.toml
$task8Sources = Get-Item src\coding_agent\safety.py,src\coding_agent\tools\filesystem.py,src\coding_agent\tools\shell.py
$networkImports = $task8Sources | Select-String -Pattern '^\s*(from|import)\s+(openai|socket|requests|urllib|http)(\.|\s|$)'
if ($networkImports) { $networkImports; throw 'Task 8 imported network or OpenAI code' }
$scanFiles = @(Get-ChildItem -Path src,tests,docs -Recurse -File | Where-Object FullName -ne (Resolve-Path docs\superpowers\plans\Task8.md)) + @(Get-Item AGENTS.md,DESIGN.md,TASKS.md,pyproject.toml,.gitignore)
$credentials = $scanFiles | Select-String -Pattern 'OPENAI_API_KEY\s*=\s*[''\"]|sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{12,}'
if ($credentials) { $credentials; throw 'credential-like content found' }
$unfinishedPattern = 'TO[D]O|TB[D]|Not' + 'ImplementedError|pass\s*(#.*)?$'
$unfinished = Get-ChildItem -Path src,tests,docs\superpowers\plans\Task8.md -Recurse -File | Select-String -Pattern $unfinishedPattern
if ($unfinished) { $unfinished }
$suppressed = Get-ChildItem -Path tests -Recurse -File -Filter *.py | Select-String -Pattern 'pytest\.skip|pytest\.xfail|@pytest\.mark\.skip|@pytest\.mark\.xfail'
if ($suppressed) { $suppressed; throw 'skip or xfail found' }
$frameworkFiles = @(Get-ChildItem -Path src,tests -Recurse -File) + @(Get-Item pyproject.toml)
$frameworks = $frameworkFiles | Select-String -Pattern 'langchain|llamaindex|autogen|crewai|agents sdk|agent sdk'
if ($frameworks) { $frameworks; throw 'prohibited framework found' }
```

Expected: no `pyproject.toml` diff; no network/OpenAI use in Task 8 modules; no credential match; no unfinished production/plan marker; no skip/xfail; no prohibited framework. Legitimate test function `pass` bodies must be manually distinguished from unfinished production code and reported.

- [ ] **Step 7: Audit Task 9/11/12 deferral and unchanged protected modules**

Run:

```powershell
git diff -- src\coding_agent\messages.py src\coding_agent\model.py src\coding_agent\state.py src\coding_agent\agent.py src\coding_agent\tools\base.py pyproject.toml
$deferred = Get-Item src\coding_agent\safety.py,src\coding_agent\tools\filesystem.py,src\coding_agent\tools\shell.py,src\coding_agent\config.py,src\coding_agent\cli.py | Select-String -Pattern 'OpenAI|Responses|VerificationGate|validation_index|SUCCESS|jsonl|final report|context compression'
if ($deferred) { $deferred; throw 'deferred feature found in Task 8 code' }
```

Expected: first command has no output; second has no Task 9/10/11/12 implementation. Mentions in user-facing comments/help must be reviewed and cannot claim those features exist.

- [ ] **Step 8: Check whitespace, status, and complete diff**

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff -- src\coding_agent\safety.py src\coding_agent\tools\registry.py src\coding_agent\tools\filesystem.py src\coding_agent\tools\shell.py src\coding_agent\config.py src\coding_agent\cli.py tests\test_path_safety.py tests\test_command_safety.py tests\test_cli.py tests\test_agent_loop.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py TASKS.md
```

Expected: `git diff --check` exits 0; only approved Task 8 files and `TASKS.md` status values are changed; no staged files exist. Review every line for duplicate policy, path/command leakage, weakened Task 5–7 tests, and accidental Task 9/11 work.

- [ ] **Step 9: Complete the Task 8 acceptance matrix**

Record fresh evidence for every row:

| Acceptance row | Required evidence |
| --- | --- |
| Relative-only and Windows path variants | `test_path_safety.py` lexical matrix |
| Resolve/commonpath/normcase containment | containment and different-drive tests |
| Existing file/dir/new file contracts | type and parent tests |
| `.git`/`.coding-agent` protection | direct, case, nested, mixed separator, list omission tests |
| Symlink/junction/reparse/link chain/dangling | real OS plus pure attribute tests, zero skip |
| All four filesystem tools unified | public-method spies and removed temporary helper scan |
| Stable safety error codes | enum, Registry, CLI tests |
| Native parsing/control syntax | roundtrip/native failure/control matrix |
| Python/pytest/unittest | allow/deny matrix and canonical argv |
| ruff/mypy | trusted launcher, read-only args, config/cache denial |
| Read-only Git | subcommand/option/pathspec/extension matrix |
| Shell/network/package/admin denial | executable matrix |
| RunCommand unified execution | returned-argv-only and process-not-started tests |
| Fixed cwd, shell false, timeout/output/tree cleanup | full Task 7 suite |
| Environment isolation | process-factory environment evidence |
| `--verify` startup authorization | safe/unsafe/exit-2/no-agent-import tests |
| Offline/no dependency/no secret | import, diff, and credential scans |
| Scope | protected-file diff and deferred-feature scans |

If any row lacks evidence, leave Task 8 `进行中`, report the exact gap, and stop.

- [ ] **Step 10: Stop for user review**

Do not change Task 8 to `已完成`; do not use a branch-finishing workflow; do not stage, commit, push, or begin Task 9. Report every RED/GREEN cycle, actual focused/full test counts and exit codes, real Windows link evidence, warnings/skips/failures, the full modified-file list, `git status`, the acceptance matrix, and the remaining OS-sandbox limitation. Wait for explicit user review and submission authorization.

**Acceptance:** All fresh verification is green with zero skip/xfail, real Windows reparse behavior is proven, the diff is in scope, and Task 8 remains in progress for user review.

---

## Explicitly deferred boundary

These policies restrict which filesystem paths and commands the Agent may request. They do not sandbox trusted workspace Python, pytest, unittest, ruff, mypy, or Git processes at the operating-system level. Executed workspace code may still access user/system resources, spawn processes, or use network APIs according to the current Windows account. No Task 8 rule may claim otherwise. A future README must state:

> 这些策略限制 Agent 可请求的文件和命令，但执行可信工作区代码仍可能访问操作系统资源，因此项目不是操作系统级沙箱。

Task 8 also does not eliminate every check/use race against a malicious concurrent local process. It validates immediately before I/O, rejects model-visible reparse points, and preserves exclusive new-file creation; stronger isolation would require an OS sandbox or handle-relative Windows APIs outside the approved first-version scope.

## Plan self-review checklist

- Every Task 8 acceptance criterion has a named test and final evidence row.
- All list/read/replace/write entry points and recursive children use `PathGuard`; temporary path checks are deleted.
- Model `run_command` and CLI `--verify` use the same `CommandPolicy`; temporary command checks are deleted.
- Windows relative, absolute, drive-relative, UNC, extended, device, mixed-separator, case, ADS, reserved-name, and different-drive forms are deterministic.
- Protected paths use case-insensitive any-component matching without false positives.
- Symlink, directory link, internal link, outside link, junction, generic reparse attribute, chain, dangling link, and new-file parent behavior is executable and cannot be permanently skipped.
- The allow/deny matrix is singular and exact; Git execution extension points and parent environment widening are handled.
- `SafetyCode`, signatures, field names, and error mapping remain consistent throughout the plan.
- No new dependency, network access, API key use, agent framework, Task 9, context work, Task 11 gate, logger, or OS sandbox is introduced.
- Every production behavior has an earlier RED and minimal GREEN; integration-only Task 14 explicitly records when no new RED is expected.
- No branch, worktree, stage, commit, push, or remote operation is included.
- Execution stops with Task 8 `进行中` for user approval.

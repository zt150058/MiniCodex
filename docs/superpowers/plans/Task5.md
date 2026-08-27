# File Reading and Directory Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILLS: Use `superpowers:executing-plans` and `superpowers:test-driven-development` task by task, then use `superpowers:verification-before-completion`. This plan forbids subagents, worktrees, staging, commits, pushes, and remote operations until the user has reviewed the completed implementation.

**Goal:** Implement the Task 5 `list_directory` and `read_file` tools as deterministic, offline implementations of the existing Task 4 tool protocol.

**Architecture:** Add one focused `tools/filesystem.py` module containing two structural `Tool` implementations plus private functional-validation and serialization helpers. Both tools return stable JSON through the existing `ToolExecution.output` field and express truncation through the existing `ToolResultMetadata.truncated`; the existing `ToolRegistry` remains unchanged and is exercised as the registration and `ToolResult` conversion boundary.

**Tech Stack:** Python 3.11+, standard library (`json`, `os`, `pathlib`, `collections.abc`), pytest, Windows-first `src/` layout.

**Spec:** `DESIGN.md` sections 4, 5, 7, 9, 12, 13, 16, and 18; `TASKS.md` Task 5; existing contracts in `src/coding_agent/messages.py`, `src/coding_agent/tools/base.py`, and `src/coding_agent/tools/registry.py`.

## Global constraints

- Work only on Task 5: `list_directory`, `read_file`, their strict schemas, deterministic functional validation, bounded outputs, existing-registry compatibility, and offline tests.
- Do not modify `messages.py`, `state.py`, `agent.py`, `model.py`, CLI code, configuration code, or any Task 2–4 public contract.
- Reuse `Tool`, `ToolExecution`, `ToolArgumentError`, `ExecutionContext`, `ToolRegistry`, `ToolResult`, `ToolResultMetadata`, and `JSONObject`; do not redefine or wrap them.
- Do not implement `replace_text`, `write_file`, Shell execution, OpenAI integration, context compression, verification, termination, logging, reporting, or any Task 6+ behavior.
- Do not add a dependency. Production code uses only the standard library; tests use only pytest and `tmp_path`.
- Tools are registered explicitly with `ToolRegistry((ListDirectoryTool(), ReadFileTool()))`. Task 5 does not create a global registry and does not wire tools into the CLI or a real model run.
- Task 5 performs only the functional path checks required to interpret a workspace-relative path: runtime type, nonempty value, NUL rejection, absolute/drive-qualified rejection, lexical parent-component rejection, normalization, and lexical workspace containment.
- Full `PathGuard`, symbolic-link escape checks, junction/reparse-point checks, and `.git/` or `.coding-agent/` protection remain Task 8. Task 5 must not claim to provide that complete security boundary.
- Every filesystem test creates and accesses files only below pytest's `tmp_path` workspace.
- Do not create a branch or worktree and do not stage, commit, push, or contact a remote.

## Public interface and exact behavior

### Tool classes

Create `src/coding_agent/tools/filesystem.py` with these public classes:

```python
class ListDirectoryTool:
    name: str = "list_directory"
    schema: JSONObject

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution: ...


class ReadFileTool:
    name: str = "read_file"
    schema: JSONObject

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution: ...
```

No new result class is introduced. Successful direct calls return `ToolExecution`; calls through `ToolRegistry.execute()` return the existing paired `ToolResult`.

### Strict input schemas

`ListDirectoryTool.schema` is exactly:

```python
{
    "name": "list_directory",
    "description": "List entries in a workspace-relative directory.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1},
            "recursive": {"type": "boolean"},
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 3},
            "max_entries": {
                "type": "integer",
                "minimum": 1,
                "maximum": 500,
            },
        },
        "required": ["path", "recursive", "max_depth", "max_entries"],
        "additionalProperties": False,
    },
}
```

`ReadFileTool.schema` is exactly:

```python
{
    "name": "read_file",
    "description": "Read numbered UTF-8 lines from a workspace-relative file.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {
                "anyOf": [
                    {"type": "integer", "minimum": 1},
                    {"type": "null"},
                ]
            },
        },
        "required": ["path", "start_line", "end_line"],
        "additionalProperties": False,
    },
}
```

The schemas improve model output reliability; both `execute()` methods independently enforce exact keys and runtime types. Python `bool` values are rejected where an integer is required.

### `list_directory` output and traversal

`ToolExecution.output` contains compact UTF-8 JSON with sorted keys:

```json
{"entries":[{"path":"src","type":"directory"},{"path":"src/main.py","type":"file"}]}
```

- Entry paths are normalized workspace-relative paths using `/`, even when the input path contains Windows `\` separators.
- `type` is `directory` or `file`; tests require explicit distinction. Task 8 will define link and reparse-point policy rather than adding a Task 5 link type.
- The requested directory itself is not included.
- Immediate children have depth 1. Their children have depth 2, and their grandchildren have depth 3.
- `recursive=False` lists only depth 1; `max_depth` is still validated but does not expand traversal.
- `recursive=True` performs stable depth-first pre-order traversal. Each directory's children are sorted by `(name.casefold(), name)` before emission. The tie-breaker avoids relying on filesystem enumeration or locale order.
- At most `max_entries` entries are returned. As soon as the emitted count reaches `max_entries`, traversal stops immediately and `metadata.truncated=True`, including when the directory happens to contain exactly that many entries. This conservative signal follows the Task 5 requirement without probing for another entry.
- An empty directory returns `{"entries":[]}` and default metadata.
- Missing paths and paths that are not directories raise `ToolArgumentError`.

### `read_file` output, ranges, and byte limit

`ToolExecution.output` contains compact UTF-8 JSON with sorted keys:

```json
{"lines":[{"line":2,"text":"second"},{"line":3,"text":"third"}]}
```

- Lines are numbered from 1.
- `end_line` is inclusive. `end_line=None` means continue through the available end of file.
- `start_line` and a non-null `end_line` must be positive integers, not booleans. `start_line > end_line` raises `ToolArgumentError`.
- Line terminators are removed from each returned `text`; a file without a final newline still returns its final line.
- An empty file returns `{"lines":[]}`.
- The 256 KiB limit applies to original raw bytes read from the beginning of the file, not the JSON-encoded response size. The implementation reads at most `256 * 1024` bytes and uses the file's size to determine whether unread raw bytes remain.
- If the raw limit cuts a multibyte UTF-8 character, only the incomplete trailing byte sequence is removed; earlier invalid UTF-8 remains an error. A partially read final text line may be returned with its real line number and `metadata.truncated=True`.
- `metadata.truncated=True` when raw bytes remain unread, when `start_line > 1` omits existing earlier lines, or when an inclusive `end_line` omits later available lines. It remains `False` only when the returned range represents all decoded content available within a file that did not exceed the raw-byte limit.
- A syntactically valid start beyond a small file's end returns an empty `lines` array and `truncated=True` when the file contained earlier lines.
- UTF-8 decoding is strict. A NUL byte in the inspected raw prefix is the deterministic Task 5 signal for suspected binary content. Either condition raises `ToolArgumentError`.
- Missing paths and directory paths raise `ToolArgumentError`.

## File map

- Create: `src/coding_agent/tools/filesystem.py` — schemas, functional validation, deterministic traversal, UTF-8 bounded read, and the two tool classes.
- Create: `tests/tools/test_read_tools.py` — all Task 5 public behavior and offline-boundary tests.
- Do not create `tests/tools/__init__.py`; pytest discovers this directory without making it a package.
- Inspect only: `src/coding_agent/tools/registry.py`; its existing constructor, `schemas`, and `execute()` interfaces already satisfy registration and result conversion.
- Modify only during a future approved execution: the Task 4 and Task 5 status values in `TASKS.md` so Task 4 becomes `已完成` and Task 5 is the only `进行中` item.

---

### Task 0: Reconfirm the approved execution baseline

**Files:**
- Inspect: `AGENTS.md`, `DESIGN.md`, `TASKS.md`, `docs/superpowers/plans/Task5.md`
- Inspect: `src/coding_agent/messages.py`, `src/coding_agent/tools/base.py`, `src/coding_agent/tools/registry.py`
- Modify during execution only: `TASKS.md`

**Interfaces:**
- Consumes: the Task 2–4 contracts listed in the public-interface section.
- Produces: an execution baseline with Task 4 complete and Task 5 as the sole active task.

- [ ] **Step 1: Verify repository, branch, commit, and clean tree**

Run from `D:\code\coding_agent`:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git status --short
git log -3 --oneline
```

Expected: repository root `D:/code/coding_agent`, branch `main`, empty short status, and Task 4 commit `5d87aed` in recent history. If the commit, branch, approved plan, or clean-tree assumption differs, stop and report the exact difference.

- [ ] **Step 2: Update only workflow status values**

Use `apply_patch` to change Task 4 from `进行中` to `已完成` and Task 5 from `未开始` to `进行中`. Do not alter Task 5 text or any later task status.

Run:

```powershell
git diff -- TASKS.md
```

Expected: exactly two status-value changes and exactly one `进行中` task.

**Acceptance:** execution begins from the approved Task 4 commit, and status tracking accurately identifies Task 5 without changing scope.

---

### Task 1: Strict schemas, registration, functional paths, and non-recursive listing

**Files:**
- Create: `tests/tools/test_read_tools.py`
- Create: `src/coding_agent/tools/filesystem.py`
- Inspect only: `src/coding_agent/tools/registry.py`

**Interfaces:**
- Consumes: `JSONObject`, `ToolResultMetadata`, `ExecutionContext`, `ToolExecution`, `ToolArgumentError`, and `ToolRegistry` exactly as currently defined.
- Produces: `ListDirectoryTool` and `ReadFileTool` with exact strict schemas; a working non-recursive `ListDirectoryTool.execute()`.

- [ ] **Step 1: Write the first failing test module**

Create `tests/tools/test_read_tools.py` with:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from coding_agent.messages import JSONObject, ToolCall, ToolResultMetadata
from coding_agent.tools.base import (
    ExecutionContext,
    ToolArgumentError,
    ToolExecution,
)
from coding_agent.tools.filesystem import ListDirectoryTool, ReadFileTool
from coding_agent.tools.registry import ToolRegistry


def _context(tmp_path: Path) -> ExecutionContext:
    return ExecutionContext(workspace=tmp_path)


def _json_output(execution: ToolExecution) -> JSONObject:
    assert isinstance(execution, ToolExecution)
    assert execution.output is not None
    decoded = json.loads(execution.output)
    assert isinstance(decoded, dict)
    return decoded


def _list_arguments(
    path: object = ".",
    recursive: object = False,
    max_depth: object = 1,
    max_entries: object = 500,
) -> JSONObject:
    return {
        "path": path,
        "recursive": recursive,
        "max_depth": max_depth,
        "max_entries": max_entries,
    }  # type: ignore[return-value]


def _read_arguments(
    path: object = "notes.txt",
    start_line: object = 1,
    end_line: object = None,
) -> JSONObject:
    return {
        "path": path,
        "start_line": start_line,
        "end_line": end_line,
    }  # type: ignore[return-value]


def test_tool_schemas_are_strict_and_complete() -> None:
    assert ListDirectoryTool.schema == {
        "name": "list_directory",
        "description": "List entries in a workspace-relative directory.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "recursive": {"type": "boolean"},
                "max_depth": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3,
                },
                "max_entries": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                },
            },
            "required": ["path", "recursive", "max_depth", "max_entries"],
            "additionalProperties": False,
        },
    }
    assert ReadFileTool.schema == {
        "name": "read_file",
        "description": (
            "Read numbered UTF-8 lines from a workspace-relative file."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {
                    "anyOf": [
                        {"type": "integer", "minimum": 1},
                        {"type": "null"},
                    ]
                },
            },
            "required": ["path", "start_line", "end_line"],
            "additionalProperties": False,
        },
    }


def test_tools_register_in_existing_registry_in_order() -> None:
    registry = ToolRegistry((ListDirectoryTool(), ReadFileTool()))

    assert registry.schemas == (
        ListDirectoryTool.schema,
        ReadFileTool.schema,
    )


def test_list_directory_returns_empty_result(tmp_path: Path) -> None:
    execution = ListDirectoryTool().execute(
        _list_arguments(),
        _context(tmp_path),
    )

    assert _json_output(execution) == {"entries": []}
    assert execution.metadata == ToolResultMetadata()


def test_list_directory_is_stable_and_marks_entry_types(tmp_path: Path) -> None:
    (tmp_path / "zeta.txt").write_text("z", encoding="utf-8")
    (tmp_path / "Alpha").mkdir()
    (tmp_path / "beta.txt").write_text("b", encoding="utf-8")

    execution = ListDirectoryTool().execute(
        _list_arguments(),
        _context(tmp_path),
    )

    assert _json_output(execution) == {
        "entries": [
            {"path": "Alpha", "type": "directory"},
            {"path": "beta.txt", "type": "file"},
            {"path": "zeta.txt", "type": "file"},
        ]
    }
    assert execution.metadata.truncated is False


def test_list_directory_accepts_windows_separators_and_normalizes_output(
    tmp_path: Path,
) -> None:
    target = tmp_path / "Nested" / "Child"
    target.mkdir(parents=True)
    (target / "item.txt").write_text("item", encoding="utf-8")

    execution = ListDirectoryTool().execute(
        _list_arguments(path=r"Nested\Child"),
        _context(tmp_path),
    )

    assert _json_output(execution) == {
        "entries": [{"path": "Nested/Child/item.txt", "type": "file"}]
    }


def test_list_directory_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(ToolArgumentError, match="directory does not exist"):
        ListDirectoryTool().execute(
            _list_arguments(path="missing"),
            _context(tmp_path),
        )


def test_list_directory_rejects_file_path(tmp_path: Path) -> None:
    (tmp_path / "not-a-directory.txt").write_text("x", encoding="utf-8")

    with pytest.raises(ToolArgumentError, match="path is not a directory"):
        ListDirectoryTool().execute(
            _list_arguments(path="not-a-directory.txt"),
            _context(tmp_path),
        )


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({}, "list_directory arguments must contain exactly"),
        (
            {**_list_arguments(), "extra": True},
            "list_directory arguments must contain exactly",
        ),
        (_list_arguments(path=""), "path must be a non-empty string"),
        (_list_arguments(path=None), "path must be a non-empty string"),
        (_list_arguments(path="bad\x00path"), "path must not contain NUL"),
        (_list_arguments(path="..\\outside"), "path must not contain '..'"),
        (_list_arguments(path=Path.cwd().anchor), "path must be relative"),
        (_list_arguments(recursive=1), "recursive must be a boolean"),
        (_list_arguments(max_depth=0), "max_depth must be between 1 and 3"),
        (_list_arguments(max_depth=4), "max_depth must be between 1 and 3"),
        (_list_arguments(max_depth=True), "max_depth must be between 1 and 3"),
        (_list_arguments(max_entries=0), "max_entries must be between 1 and 500"),
        (_list_arguments(max_entries=501), "max_entries must be between 1 and 500"),
        (_list_arguments(max_entries=True), "max_entries must be between 1 and 500"),
    ],
)
def test_list_directory_rejects_invalid_arguments(
    tmp_path: Path,
    arguments: JSONObject,
    message: str,
) -> None:
    with pytest.raises(ToolArgumentError, match=message):
        ListDirectoryTool().execute(arguments, _context(tmp_path))
```

- [ ] **Step 2: Run RED and verify the reason**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py -q --basetemp .\.pytest_cache\task5-red-1
```

Expected: nonzero collection failure because `coding_agent.tools.filesystem` does not exist. The failure must not be a syntax error, fixture error, or regression in an existing test.

- [ ] **Step 3: Implement schemas, functional path validation, and non-recursive listing**

Create `src/coding_agent/tools/filesystem.py` with the following imports, constants, helpers, schemas, and initial implementations:

```python
from __future__ import annotations

from collections.abc import Iterator
import json
import os
from pathlib import Path

from coding_agent.messages import JSONObject, ToolResultMetadata
from coding_agent.tools.base import (
    ExecutionContext,
    ToolArgumentError,
    ToolExecution,
)

_LIST_ARGUMENTS = {"path", "recursive", "max_depth", "max_entries"}
_READ_ARGUMENTS = {"path", "start_line", "end_line"}
_MAX_READ_BYTES = 256 * 1024


def _require_exact_arguments(
    arguments: object,
    required: set[str],
    tool_name: str,
) -> JSONObject:
    if not isinstance(arguments, dict) or set(arguments) != required:
        names = ", ".join(sorted(required))
        raise ToolArgumentError(
            f"{tool_name} arguments must contain exactly: {names}"
        )
    return arguments


def _bounded_integer(value: object, name: str, lower: int, upper: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolArgumentError(f"{name} must be between {lower} and {upper}")
    if value < lower or value > upper:
        raise ToolArgumentError(f"{name} must be between {lower} and {upper}")
    return value


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolArgumentError(f"{name} must be a positive integer")
    return value


def _functional_workspace_path(
    value: object,
    context: ExecutionContext,
) -> tuple[Path, Path]:
    if not isinstance(value, str) or not value.strip():
        raise ToolArgumentError("path must be a non-empty string")
    if "\x00" in value:
        raise ToolArgumentError("path must not contain NUL")

    relative = Path(value)
    if relative.is_absolute() or relative.drive:
        raise ToolArgumentError("path must be relative to the workspace")
    if ".." in relative.parts:
        raise ToolArgumentError("path must not contain '..'")

    workspace = context.workspace.absolute()
    candidate = (workspace / relative).absolute()
    try:
        common = os.path.commonpath((str(workspace), str(candidate)))
    except ValueError as exc:
        raise ToolArgumentError("path must remain inside the workspace") from exc
    if os.path.normcase(common) != os.path.normcase(str(workspace)):
        raise ToolArgumentError("path must remain inside the workspace")
    return workspace, candidate


def _entry_type(path: Path) -> str:
    if path.is_dir():
        return "directory"
    return "file"


def _directory_children(path: Path) -> list[Path]:
    return sorted(path.iterdir(), key=lambda item: (item.name.casefold(), item.name))


def _json_execution(payload: JSONObject, *, truncated: bool = False) -> ToolExecution:
    return ToolExecution(
        output=json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        metadata=ToolResultMetadata(truncated=truncated),
    )


class ListDirectoryTool:
    name = "list_directory"
    schema: JSONObject = {
        "name": "list_directory",
        "description": "List entries in a workspace-relative directory.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "recursive": {"type": "boolean"},
                "max_depth": {"type": "integer", "minimum": 1, "maximum": 3},
                "max_entries": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                },
            },
            "required": ["path", "recursive", "max_depth", "max_entries"],
            "additionalProperties": False,
        },
    }

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        values = _require_exact_arguments(arguments, _LIST_ARGUMENTS, self.name)
        recursive = values["recursive"]
        if not isinstance(recursive, bool):
            raise ToolArgumentError("recursive must be a boolean")
        _bounded_integer(values["max_depth"], "max_depth", 1, 3)
        _bounded_integer(values["max_entries"], "max_entries", 1, 500)
        workspace, directory = _functional_workspace_path(values["path"], context)
        if not directory.exists():
            raise ToolArgumentError("directory does not exist")
        if not directory.is_dir():
            raise ToolArgumentError("path is not a directory")

        entries = [
            {
                "path": child.relative_to(workspace).as_posix(),
                "type": _entry_type(child),
            }
            for child in _directory_children(directory)
        ]
        return _json_execution({"entries": entries})


class ReadFileTool:
    name = "read_file"
    schema: JSONObject = {
        "name": "read_file",
        "description": "Read numbered UTF-8 lines from a workspace-relative file.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {
                    "anyOf": [
                        {"type": "integer", "minimum": 1},
                        {"type": "null"},
                    ]
                },
            },
            "required": ["path", "start_line", "end_line"],
            "additionalProperties": False,
        },
    }

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        raise ToolArgumentError("read_file behavior is not active in this test cycle")
```

`Iterator`, `_READ_ARGUMENTS`, `_MAX_READ_BYTES`, and `_positive_integer` are introduced now because the next cycles use them; they do not add untested production behavior. The temporary `ReadFileTool.execute()` rejection is removed in Task 3.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py -q --basetemp .\.pytest_cache\task5-green-1
```

Expected: exit `0`; report the real pass count and warnings from pytest.

- [ ] **Step 5: Run Task 2–4 regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py -q --basetemp .\.pytest_cache\task5-regression-1
```

Expected: exit `0`; report the real passed, failed, skipped, and warning counts.

**Acceptance:** both exact strict schemas register with the existing registry; non-recursive directory output is empty or stably sorted with normalized paths and explicit types; malformed functional arguments are rejected before filesystem access.

---

### Task 2: Recursive depth, entry cap, truncation, and directory errors

**Files:**
- Modify: `tests/tools/test_read_tools.py`
- Modify: `src/coding_agent/tools/filesystem.py`

**Interfaces:**
- Consumes: `ListDirectoryTool.execute(arguments, context) -> ToolExecution` from Task 1.
- Produces: deterministic bounded recursion with immediate stop after the first omitted candidate.

- [ ] **Step 1: Append failing recursion and directory-error tests**

Append to `tests/tools/test_read_tools.py`:

```python
def _build_depth_tree(tmp_path: Path) -> None:
    level_1 = tmp_path / "level1"
    level_2 = level_1 / "level2"
    level_3 = level_2 / "level3"
    level_3.mkdir(parents=True)
    (level_3 / "depth4.txt").write_text("four", encoding="utf-8")


@pytest.mark.parametrize(
    ("max_depth", "expected_paths"),
    [
        (1, ["level1"]),
        (2, ["level1", "level1/level2"]),
        (3, ["level1", "level1/level2", "level1/level2/level3"]),
    ],
)
def test_list_directory_recursive_depth_is_counted_from_children(
    tmp_path: Path,
    max_depth: int,
    expected_paths: list[str],
) -> None:
    _build_depth_tree(tmp_path)

    execution = ListDirectoryTool().execute(
        _list_arguments(recursive=True, max_depth=max_depth),
        _context(tmp_path),
    )

    entries = _json_output(execution)["entries"]
    assert isinstance(entries, list)
    assert [entry["path"] for entry in entries] == expected_paths
    assert execution.metadata.truncated is False


def test_list_directory_non_recursive_ignores_expansion_depth(
    tmp_path: Path,
) -> None:
    _build_depth_tree(tmp_path)

    execution = ListDirectoryTool().execute(
        _list_arguments(recursive=False, max_depth=3),
        _context(tmp_path),
    )

    assert _json_output(execution) == {
        "entries": [{"path": "level1", "type": "directory"}]
    }


def test_list_directory_recursive_order_is_stable_depth_first(
    tmp_path: Path,
) -> None:
    (tmp_path / "Beta").mkdir()
    (tmp_path / "Beta" / "z.txt").write_text("z", encoding="utf-8")
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "A.txt").write_text("a", encoding="utf-8")
    (tmp_path / "gamma.txt").write_text("g", encoding="utf-8")

    execution = ListDirectoryTool().execute(
        _list_arguments(recursive=True, max_depth=2),
        _context(tmp_path),
    )

    entries = _json_output(execution)["entries"]
    assert isinstance(entries, list)
    assert [entry["path"] for entry in entries] == [
        "alpha",
        "alpha/A.txt",
        "Beta",
        "Beta/z.txt",
        "gamma.txt",
    ]


def test_list_directory_stops_at_entry_limit_and_marks_truncated(
    tmp_path: Path,
) -> None:
    for name in ("d.txt", "b.txt", "a.txt", "c.txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")

    execution = ListDirectoryTool().execute(
        _list_arguments(max_entries=3),
        _context(tmp_path),
    )

    assert _json_output(execution) == {
        "entries": [
            {"path": "a.txt", "type": "file"},
            {"path": "b.txt", "type": "file"},
            {"path": "c.txt", "type": "file"},
        ]
    }
    assert execution.metadata.truncated is True


def test_list_directory_reaching_exact_limit_is_truncated(
    tmp_path: Path,
) -> None:
    for name in ("b.txt", "a.txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")

    execution = ListDirectoryTool().execute(
        _list_arguments(max_entries=2),
        _context(tmp_path),
    )

    assert len(_json_output(execution)["entries"]) == 2
    assert execution.metadata.truncated is True


```

- [ ] **Step 2: Run RED and verify the reason**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py -q --basetemp .\.pytest_cache\task5-red-2
```

Expected: nonzero because the Task 1 implementation always returns all immediate children, does not recurse, does not enforce `max_entries`, and cannot set truncation for omitted entries. Existing schema, argument, empty-directory, sorting, path-separator, and directory-error tests must remain green.

- [ ] **Step 3: Add the bounded traversal and use it from `ListDirectoryTool`**

Add this helper below `_directory_children` in `src/coding_agent/tools/filesystem.py`:

```python
def _iter_directory_entries(
    directory: Path,
    *,
    recursive: bool,
    max_depth: int,
    depth: int = 1,
) -> Iterator[Path]:
    for child in _directory_children(directory):
        yield child
        if recursive and child.is_dir() and depth < max_depth:
            yield from _iter_directory_entries(
                child,
                recursive=True,
                max_depth=max_depth,
                depth=depth + 1,
            )
```

Replace the body of `ListDirectoryTool.execute()` after exact-argument validation with:

```python
        recursive = values["recursive"]
        if not isinstance(recursive, bool):
            raise ToolArgumentError("recursive must be a boolean")
        max_depth = _bounded_integer(
            values["max_depth"],
            "max_depth",
            1,
            3,
        )
        max_entries = _bounded_integer(
            values["max_entries"],
            "max_entries",
            1,
            500,
        )
        workspace, directory = _functional_workspace_path(values["path"], context)
        if not directory.exists():
            raise ToolArgumentError("directory does not exist")
        if not directory.is_dir():
            raise ToolArgumentError("path is not a directory")

        entries: list[JSONObject] = []
        truncated = False
        for child in _iter_directory_entries(
            directory,
            recursive=recursive,
            max_depth=max_depth,
        ):
            entries.append(
                {
                    "path": child.relative_to(workspace).as_posix(),
                    "type": _entry_type(child),
                }
            )
            if len(entries) == max_entries:
                truncated = True
                break
        return _json_execution({"entries": entries}, truncated=truncated)
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py -q --basetemp .\.pytest_cache\task5-green-2
```

Expected: exit `0`; report the real pass count and warnings.

- [ ] **Step 5: Run Task 2–4 regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py -q --basetemp .\.pytest_cache\task5-regression-2
```

Expected: exit `0`; report actual counts.

**Acceptance:** non-recursive and depth-1/2/3 recursive listings follow the documented stable order, reaching the entry cap stops traversal immediately with the required conservative truncation flag, and missing/non-directory targets are deterministic argument errors.

---

### Task 3: UTF-8 reads, inclusive ranges, real line numbers, and ordinary errors

**Files:**
- Modify: `tests/tools/test_read_tools.py`
- Modify: `src/coding_agent/tools/filesystem.py`

**Interfaces:**
- Consumes: the exact `ReadFileTool` schema created in Task 1.
- Produces: `ReadFileTool.execute(arguments, context) -> ToolExecution` for files no larger than 256 KiB, with inclusive ranges and strict UTF-8 decoding.

- [ ] **Step 1: Append failing read tests**

Append to `tests/tools/test_read_tools.py`:

```python
def test_read_file_returns_all_numbered_lines(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("first\nsecond\nthird\n", encoding="utf-8")

    execution = ReadFileTool().execute(
        _read_arguments(),
        _context(tmp_path),
    )

    assert _json_output(execution) == {
        "lines": [
            {"line": 1, "text": "first"},
            {"line": 2, "text": "second"},
            {"line": 3, "text": "third"},
        ]
    }
    assert execution.metadata.truncated is False


def test_read_file_uses_inclusive_line_range_and_real_numbers(
    tmp_path: Path,
) -> None:
    (tmp_path / "notes.txt").write_text(
        "one\ntwo\nthree\nfour\n",
        encoding="utf-8",
    )

    execution = ReadFileTool().execute(
        _read_arguments(start_line=2, end_line=3),
        _context(tmp_path),
    )

    assert _json_output(execution) == {
        "lines": [
            {"line": 2, "text": "two"},
            {"line": 3, "text": "three"},
        ]
    }
    assert execution.metadata.truncated is True


def test_read_file_null_end_means_available_end(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("one\ntwo\nthree", encoding="utf-8")

    execution = ReadFileTool().execute(
        _read_arguments(start_line=2, end_line=None),
        _context(tmp_path),
    )

    assert _json_output(execution) == {
        "lines": [
            {"line": 2, "text": "two"},
            {"line": 3, "text": "three"},
        ]
    }
    assert execution.metadata.truncated is True


def test_read_file_returns_empty_file(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_bytes(b"")

    execution = ReadFileTool().execute(
        _read_arguments(),
        _context(tmp_path),
    )

    assert _json_output(execution) == {"lines": []}
    assert execution.metadata.truncated is False


def test_read_file_preserves_single_line_without_final_newline(
    tmp_path: Path,
) -> None:
    (tmp_path / "notes.txt").write_text("only line", encoding="utf-8")

    execution = ReadFileTool().execute(
        _read_arguments(),
        _context(tmp_path),
    )

    assert _json_output(execution) == {
        "lines": [{"line": 1, "text": "only line"}]
    }


def test_read_file_handles_multibyte_utf8(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("你好\n🙂 café", encoding="utf-8")

    execution = ReadFileTool().execute(
        _read_arguments(),
        _context(tmp_path),
    )

    assert _json_output(execution) == {
        "lines": [
            {"line": 1, "text": "你好"},
            {"line": 2, "text": "🙂 café"},
        ]
    }


def test_read_file_start_beyond_end_returns_empty_truncated_result(
    tmp_path: Path,
) -> None:
    (tmp_path / "notes.txt").write_text("one\ntwo", encoding="utf-8")

    execution = ReadFileTool().execute(
        _read_arguments(start_line=5, end_line=None),
        _context(tmp_path),
    )

    assert _json_output(execution) == {"lines": []}
    assert execution.metadata.truncated is True


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({}, "read_file arguments must contain exactly"),
        (
            {**_read_arguments(), "extra": True},
            "read_file arguments must contain exactly",
        ),
        (_read_arguments(path=""), "path must be a non-empty string"),
        (_read_arguments(start_line=0), "start_line must be a positive integer"),
        (_read_arguments(start_line=True), "start_line must be a positive integer"),
        (_read_arguments(end_line=0), "end_line must be a positive integer"),
        (_read_arguments(end_line=True), "end_line must be a positive integer"),
        (_read_arguments(start_line=3, end_line=2), "start_line must not exceed end_line"),
    ],
)
def test_read_file_rejects_invalid_arguments(
    tmp_path: Path,
    arguments: JSONObject,
    message: str,
) -> None:
    (tmp_path / "notes.txt").write_text("content", encoding="utf-8")

    with pytest.raises(ToolArgumentError, match=message):
        ReadFileTool().execute(arguments, _context(tmp_path))


def test_read_file_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ToolArgumentError, match="file does not exist"):
        ReadFileTool().execute(
            _read_arguments(path="missing.txt"),
            _context(tmp_path),
        )


def test_read_file_rejects_directory_path(tmp_path: Path) -> None:
    (tmp_path / "folder").mkdir()

    with pytest.raises(ToolArgumentError, match="path is not a file"):
        ReadFileTool().execute(
            _read_arguments(path="folder"),
            _context(tmp_path),
        )


def test_read_file_rejects_non_utf8(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_bytes(b"valid\n\xffinvalid")

    with pytest.raises(ToolArgumentError, match="file is not valid UTF-8"):
        ReadFileTool().execute(
            _read_arguments(),
            _context(tmp_path),
        )


def test_registry_returns_paired_result_for_read_and_rejects_bad_arguments(
    tmp_path: Path,
) -> None:
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    registry = ToolRegistry((ListDirectoryTool(), ReadFileTool()))

    ok_result = registry.execute(
        ToolCall(
            call_id="read_ok",
            name="read_file",
            arguments=_read_arguments(),
        ),
        _context(tmp_path),
    )
    rejected_result = registry.execute(
        ToolCall(
            call_id="read_bad",
            name="read_file",
            arguments=_read_arguments(start_line=0),
        ),
        _context(tmp_path),
    )

    assert ok_result.call_id == "read_ok"
    assert ok_result.tool_name == "read_file"
    assert ok_result.status == "ok"
    assert ok_result.output is not None
    assert rejected_result.call_id == "read_bad"
    assert rejected_result.status == "rejected"
    assert rejected_result.error == (
        "invalid_arguments: start_line must be a positive integer"
    )
```

- [ ] **Step 2: Run RED and verify the reason**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py -q --basetemp .\.pytest_cache\task5-red-3
```

Expected: nonzero because `ReadFileTool.execute()` still returns the deliberate Task 1 rejection. Listing tests must remain green.

- [ ] **Step 3: Implement ordinary UTF-8 reads and ranges**

Add below `_json_execution` in `src/coding_agent/tools/filesystem.py`:

```python
def _without_line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1]
    return line


def _decode_complete_file(path: Path) -> tuple[str, bool]:
    try:
        return path.read_bytes().decode("utf-8"), False
    except UnicodeDecodeError as exc:
        raise ToolArgumentError("file is not valid UTF-8") from exc
```

Replace `ReadFileTool.execute()` with:

```python
    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        values = _require_exact_arguments(arguments, _READ_ARGUMENTS, self.name)
        start_line = _positive_integer(values["start_line"], "start_line")
        end_value = values["end_line"]
        end_line = (
            None
            if end_value is None
            else _positive_integer(end_value, "end_line")
        )
        if end_line is not None and start_line > end_line:
            raise ToolArgumentError("start_line must not exceed end_line")

        _, target = _functional_workspace_path(values["path"], context)
        if not target.exists():
            raise ToolArgumentError("file does not exist")
        if not target.is_file():
            raise ToolArgumentError("path is not a file")

        text, size_truncated = _decode_complete_file(target)
        source_lines = text.splitlines(keepends=True)
        selected = source_lines[start_line - 1 : end_line]
        lines: list[JSONObject] = [
            {
                "line": number,
                "text": _without_line_ending(line),
            }
            for number, line in enumerate(selected, start=start_line)
        ]
        omitted_before = bool(source_lines) and start_line > 1
        omitted_after = end_line is not None and len(source_lines) > end_line
        return _json_execution(
            {"lines": lines},
            truncated=size_truncated or omitted_before or omitted_after,
        )
```

This cycle intentionally reads the whole small fixture. Task 4 replaces `_decode_complete_file()` with the approved raw-byte-bounded implementation before Task 5 can be reported complete.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py -q --basetemp .\.pytest_cache\task5-green-3
```

Expected: exit `0`; report real counts and warnings.

- [ ] **Step 5: Run Task 2–4 regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py -q --basetemp .\.pytest_cache\task5-regression-3
```

Expected: exit `0`; report actual counts.

**Acceptance:** small UTF-8 files, empty files, final lines without terminators, multibyte text, full reads, inclusive ranges, explicit null ends, and out-of-content starts all return stable numbered output; malformed ranges, missing files, directories, and invalid encoding are rejected; registry results preserve call pairing.

---

### Task 4: Raw 256 KiB bound, cut-character handling, and binary rejection

**Files:**
- Modify: `tests/tools/test_read_tools.py`
- Modify: `src/coding_agent/tools/filesystem.py`

**Interfaces:**
- Consumes: `ReadFileTool.execute()` from Task 3.
- Produces: the final bounded Task 5 read semantics without reading more than 256 KiB of file content.

- [ ] **Step 1: Append failing size and binary tests**

Append to `tests/tools/test_read_tools.py`:

```python
def test_read_file_truncates_after_256_kib_of_raw_bytes(tmp_path: Path) -> None:
    limit = 256 * 1024
    (tmp_path / "notes.txt").write_bytes(b"a\n" * (limit // 2 + 20))

    execution = ReadFileTool().execute(
        _read_arguments(),
        _context(tmp_path),
    )

    payload = _json_output(execution)
    lines = payload["lines"]
    assert isinstance(lines, list)
    assert len(lines) == limit // 2
    assert lines[0] == {"line": 1, "text": "a"}
    assert lines[-1] == {"line": limit // 2, "text": "a"}
    assert execution.metadata.truncated is True


def test_read_file_drops_only_incomplete_utf8_at_raw_limit(
    tmp_path: Path,
) -> None:
    limit = 256 * 1024
    prefix = b"x" * (limit - 1)
    emoji = "🙂".encode("utf-8")
    (tmp_path / "notes.txt").write_bytes(prefix + emoji + b"\n")

    execution = ReadFileTool().execute(
        _read_arguments(),
        _context(tmp_path),
    )

    lines = _json_output(execution)["lines"]
    assert isinstance(lines, list)
    assert lines == [{"line": 1, "text": "x" * (limit - 1)}]
    assert execution.metadata.truncated is True


def test_read_file_rejects_suspected_binary_content(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_bytes(b"text\x00binary")

    with pytest.raises(ToolArgumentError, match="file appears to be binary"):
        ReadFileTool().execute(
            _read_arguments(),
            _context(tmp_path),
        )
```

- [ ] **Step 2: Run RED and verify the reason**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py -q --basetemp .\.pytest_cache\task5-red-4
```

Expected: nonzero because the Task 3 decoder reads the entire large file and does not reject NUL content. The normal UTF-8, range, argument, registry, and listing tests must remain green.

- [ ] **Step 3: Replace the temporary full read with the bounded decoder**

Replace `_decode_complete_file()` with:

```python
def _decode_utf8_prefix(path: Path) -> tuple[str, bool]:
    size_truncated = path.stat().st_size > _MAX_READ_BYTES
    with path.open("rb") as stream:
        raw = stream.read(_MAX_READ_BYTES)

    if b"\x00" in raw:
        raise ToolArgumentError("file appears to be binary")

    try:
        return raw.decode("utf-8"), size_truncated
    except UnicodeDecodeError as exc:
        cut_character = (
            size_truncated
            and exc.reason == "unexpected end of data"
            and exc.end == len(raw)
        )
        if not cut_character:
            raise ToolArgumentError("file is not valid UTF-8") from exc

        for trailing_count in range(1, 4):
            try:
                return raw[:-trailing_count].decode("utf-8"), True
            except UnicodeDecodeError:
                continue
        raise ToolArgumentError("file is not valid UTF-8") from exc
```

Change the one call in `ReadFileTool.execute()` from:

```python
        text, size_truncated = _decode_complete_file(target)
```

to:

```python
        text, size_truncated = _decode_utf8_prefix(target)
```

No other read behavior changes. `stat()` is used only to detect unread content; the file-content read remains capped at exactly 256 KiB.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py -q --basetemp .\.pytest_cache\task5-green-4
```

Expected: exit `0`; report the real pass count and warnings.

- [ ] **Step 5: Run Task 2–4 regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py -q --basetemp .\.pytest_cache\task5-regression-4
```

Expected: exit `0`; report actual counts.

**Acceptance:** file content reads never exceed 256 KiB, larger files produce truthful truncation, a multibyte character cut only by that limit does not cause a false encoding error, and deterministic binary suspicion is rejected.

---

### Task 5: Offline boundary and final verification

**Files:**
- Modify: `tests/tools/test_read_tools.py`
- Inspect: `src/coding_agent/tools/filesystem.py`, `src/coding_agent/tools/registry.py`, `TASKS.md`, `pyproject.toml`

**Interfaces:**
- Consumes: final `ListDirectoryTool` and `ReadFileTool` behavior.
- Produces: real verification evidence and a user-review stopping point.

- [ ] **Step 1: Add the offline import-boundary test**

Append to `tests/tools/test_read_tools.py`:

```python
def test_filesystem_tools_import_without_openai_api_key_or_network() -> None:
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "openai" or name.startswith("openai."):
        raise AssertionError("Task 5 imported OpenAI SDK")
    if name in {"socket", "urllib", "http", "requests"}:
        raise AssertionError("Task 5 imported a network module")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import coding_agent.tools.filesystem
"""
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py::test_filesystem_tools_import_without_openai_api_key_or_network -q --basetemp .\.pytest_cache\task5-offline
```

Expected: exit `0`, one test passed, no implementation change required. If it fails, stop and remove the unexpected dependency or network import before continuing.

- [ ] **Step 2: Run the complete Task 5 test module**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py -q --basetemp .\.pytest_cache\task5-verify
```

Expected: exit `0`, no failures and no skips. Report only the actual pass count, duration, warnings, and exit code.

- [ ] **Step 3: Run the full repository suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp .\.pytest_cache\task5-all
```

Expected: exit `0`, no failures and no skips. If Windows temporary-directory permissions interfere, use `superpowers:systematic-debugging` and do not report partial success.

- [ ] **Step 4: Verify exact interfaces, existing type reuse, and registry compatibility**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import inspect; import coding_agent.tools.filesystem as f; import coding_agent.tools.registry as r; expected={'arguments':'JSONObject','context':'ExecutionContext','return':'ToolExecution'}; assert tuple(inspect.signature(f.ListDirectoryTool.execute).parameters)==('self','arguments','context'); assert f.ListDirectoryTool.execute.__annotations__==expected; assert tuple(inspect.signature(f.ReadFileTool.execute).parameters)==('self','arguments','context'); assert f.ReadFileTool.execute.__annotations__==expected; registry=r.ToolRegistry((f.ListDirectoryTool(),f.ReadFileTool())); assert registry.schemas==(f.ListDirectoryTool.schema,f.ReadFileTool.schema); print('task-5 raw annotations, interfaces, and registry compatibility verified')"
```

Expected: exit `0` and the stated verification line. Raw annotations are checked because Task 2's recursive `JSONObject` alias is intentionally not expanded across module namespaces.

Run:

```powershell
.\.venv\Scripts\python.exe -c "import ast,pathlib; path=pathlib.Path('src/coding_agent/tools/filesystem.py'); tree=ast.parse(path.read_text(encoding='utf-8')); forbidden={'Tool','ToolExecution','ToolArgumentError','ExecutionContext','ToolRegistry','ToolResult','ToolResultMetadata','JSONObject'}; defined={node.name for node in ast.walk(tree) if isinstance(node,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef))}; assert not defined.intersection(forbidden),defined.intersection(forbidden); print('task-2 through task-4 types are reused')"
```

Expected: exit `0` and `task-2 through task-4 types are reused`.

- [ ] **Step 5: Audit dependencies, forbidden scope, and deferred Task 8 security**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import pathlib,tomllib; data=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); assert data['project']['dependencies']==['openai']; assert data['project']['optional-dependencies']['test']==['pytest']; print('approved dependencies only')"
```

Expected: exit `0` and `approved dependencies only`.

Run:

```powershell
$forbidden = @(
    'import openai',
    'from openai',
    'OPENAI_API_KEY',
    'subprocess',
    'socket',
    'requests',
    'replace_text',
    'write_file',
    'run_command',
    'PathGuard',
    'SafetyPolicy',
    'CommandPolicy',
    'VerificationGate',
    'TerminationPolicy',
    'ContextManager',
    'symlink',
    'junction',
    'reparse'
)
$matches = Select-String -Path .\src\coding_agent\tools\filesystem.py -Pattern $forbidden
if ($matches) { $matches; exit 1 }
Write-Output 'task-5 scope and deferred-security boundary verified'
```

Expected: exit `0` and the stated line. This proves only that later-task implementations were not introduced; it does not prove Task 8 path safety.

- [ ] **Step 6: Scan for credentials without printing matching values**

Run:

```powershell
$secretPatterns = @(
    's' + 'k-[A-Za-z0-9_-]{20,}',
    'Bearer\s+[A-Za-z0-9._-]{20,}'
)
$files = Get-ChildItem .\src, .\tests, .\docs -Recurse -File |
    Where-Object { $_.Extension -in '.py', '.md', '.toml', '.txt' }
$hitPaths = $files | Select-String -Pattern $secretPatterns |
    Select-Object -ExpandProperty Path -Unique
if ($hitPaths) { $hitPaths; exit 1 }
Write-Output 'no credential-like values found'
```

Expected: exit `0` and `no credential-like values found`; only paths are printed on failure.

- [ ] **Step 7: Scan placeholders, skipped tests, temporary branches, and diff quality**

Run:

```powershell
$sourceMarkers = @(
    ('T' + 'BD'),
    ('T' + 'ODO'),
    ('NotImplemented' + 'Error'),
    ('not active in this test ' + 'cycle'),
    ('decode_complete_' + 'file'),
    ('pytest' + '.skip'),
    ('pytest' + '.mark.skip'),
    ('implement' + ' later'),
    ('fill' + ' in details'),
    ('添加' + '适当测试'),
    ('处理' + '边界情况'),
    ('实现' + '相关逻辑'),
    ('同' + '上')
)
$sourcePaths = @(
    '.\src\coding_agent\tools\filesystem.py',
    '.\tests\tools\test_read_tools.py'
)
$sourceMatches = Select-String -Path $sourcePaths -Pattern $sourceMarkers
if ($sourceMatches) { $sourceMatches; exit 1 }

$planMarkers = @(
    ('T' + 'BD'),
    ('T' + 'ODO'),
    ('NotImplemented' + 'Error'),
    ('pytest' + '.skip'),
    ('pytest' + '.mark.skip'),
    ('implement' + ' later'),
    ('fill' + ' in details'),
    ('添加' + '适当测试'),
    ('处理' + '边界情况'),
    ('实现' + '相关逻辑'),
    ('同' + '上')
)
$planMatches = Select-String -Path .\docs\superpowers\plans\Task5.md -Pattern $planMarkers
if ($planMatches) { $planMatches; exit 1 }
Write-Output 'no placeholders, skips, or temporary branches found'

git diff --check
git status --short
git diff -- TASKS.md src/coding_agent/tools/filesystem.py tests/tools/test_read_tools.py docs/superpowers/plans/Task5.md
```

Expected:

- Marker scan exits `0` with the stated line.
- `git diff --check` exits `0` with no output.
- Status and diff contain only `TASKS.md`, `src/coding_agent/tools/filesystem.py`, `tests/tools/test_read_tools.py`, and the approved `Task5.md` plan.
- `src/coding_agent/tools/registry.py` remains byte-for-byte unchanged.

- [ ] **Step 8: Review the Task 5 acceptance matrix**

| Requirement | Passing evidence |
| --- | --- |
| Strict schemas and extra-key rejection | `test_tool_schemas_are_strict_and_complete`, both invalid-argument parameterizations |
| Existing `ToolRegistry` registration | `test_tools_register_in_existing_registry_in_order`, registry compatibility command |
| Empty directory | `test_list_directory_returns_empty_result` |
| Stable case-aware sorting | `test_list_directory_is_stable_and_marks_entry_types`, recursive-order test |
| File/directory distinction | explicit `type` assertions in listing tests |
| Windows separators and normalized output | `test_list_directory_accepts_windows_separators_and_normalizes_output` |
| Non-recursive listing | non-recursive depth test |
| Recursive depths 1, 2, and 3 | parameterized recursive-depth test |
| Depth and entry argument bounds | list invalid-argument parameterization |
| Entry limit and truncation | cap test plus conservative exact-cap test |
| Missing and non-directory listing targets | two direct rejection tests |
| Full UTF-8 read and line numbers | full-read and multibyte tests |
| Inclusive start/end and explicit null | range and null-end tests |
| Empty, single-line, and no-final-newline files | empty and single-line tests |
| Raw 256 KiB bound and truncation | large-file and cut-character tests |
| Invalid line ranges | read invalid-argument parameterization |
| Missing file and directory path | two direct rejection tests |
| Invalid UTF-8 and suspected binary | non-UTF-8 and NUL tests |
| Paired public `ToolResult` behavior | registry read/rejection test |
| Completely offline and no real key | fresh-process import test and static scan |
| No Task 6 or Task 8 implementation | file list, forbidden-scope scan, and full diff review |

If any row lacks real passing evidence, keep Task 5 `进行中`, report the exact gap, and stop.

- [ ] **Step 9: Wait for user review and authorization**

Report every RED command and its actual nonzero result, every GREEN and regression command with actual counts, final verification exit codes, all warnings/skips/failures, the changed-file list, and the explicit limitation that Task 8 security is not yet implemented.

Do not mark Task 5 `已完成`, stage, commit, push, contact a remote, or start Task 6. The suggested future commit message is `feat: add directory listing and file reading tools`, but committing requires a separate user review and authorization.

## Plan self-check

- Every Task 5 acceptance criterion maps to a named public-behavior test or deterministic audit.
- Names and signatures remain consistent: `ListDirectoryTool`, `ReadFileTool`, `execute(arguments, context) -> ToolExecution`, and the existing Task 2–4 types.
- Every production behavior is preceded by a RED test and followed by a GREEN command plus Task 2–4 regression command.
- The 256 KiB rule has one exact meaning: original raw bytes read from file offset zero; JSON response size is not the limiting quantity.
- Directory depth starts at immediate children, `end_line` is inclusive, explicit null means available EOF, and truncation semantics are unambiguous.
- No Task 6 mutation, Task 7 Shell execution, Task 8 unified security policy, model/API behavior, context behavior, verification, logging, reporting, CLI wiring, or new dependency is included.
- Tests are offline, use only `tmp_path` workspaces, and never read a real API key.
- The final steps include targeted tests, the full suite, signature/type reuse, registry compatibility, dependency audit, scope audit, credential scan, placeholder/skip scan, `git diff --check`, status, and complete diff review.
- Execution stops for user approval without staging, committing, pushing, or starting Task 6.

# Task 6 File Modification Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`, `superpowers:test-driven-development`, and `superpowers:verification-before-completion` to implement this plan task-by-task. Use `superpowers:systematic-debugging` before changing code in response to any reproducible unexpected failure. Do not use subagents or a Git worktree.

**Goal:** Add deterministic `replace_text` and create-only `write_file` tools, then record every successful changed-path result in a minimal mutation ledger that invalidates prior verification state.

**Architecture:** Both mutation tools extend the existing `coding_agent.tools.filesystem` module and reuse its functional workspace-relative path resolution, `ToolExecution`, and `ToolResultMetadata`. `ToolRegistry` remains unchanged: it converts a successful `ToolExecution` into the existing `ToolResult` and preserves `changed_paths`; `AgentRunner` remains the sole top-level state-transition owner and records mutation metadata after each sequential tool result. `AgentState` receives only the fields needed by Task 6; Task 11 will extend and enforce formal verification evidence.

**Tech Stack:** Python 3.11+, standard library, existing `openai` runtime dependency, pytest, Windows PowerShell, `src/` package layout.

**Spec:** `DESIGN.md` sections 6, 9, 10, and 14; `TASKS.md` Task 6; approved Task 6 request attached on 2026-08-27.

## Global constraints

- Implement only Task 6. Do not implement Task 7 Shell behavior, Task 8 unified path security, Task 11 verification decisions, context compression, logging, reporting, CLI integration, deletion, moving, renaming, or permission changes.
- Keep the implementation synchronous, local, deterministic, and completely offline. Do not read a real API key, instantiate an OpenAI client, or access the network.
- Do not add dependencies or modify `pyproject.toml`.
- Reuse `Tool`, `ToolExecution`, `ToolResult`, `ToolResultMetadata`, `ExecutionContext`, `ToolArgumentError`, `ToolRegistry`, `AgentState`, and `JSONObject`; do not redefine them.
- Keep `src/coding_agent/messages.py`, `src/coding_agent/model.py`, `src/coding_agent/tools/base.py`, `src/coding_agent/tools/registry.py`, `src/coding_agent/cli.py`, and `src/coding_agent/config.py` unchanged.
- All filesystem tests use a pytest `tmp_path` as `ExecutionContext.workspace`.
- Task 6 uses Task 5's functional relative-path checks only. It does not claim protection against symbolic-link, junction, or reparse-point escapes and does not protect `.git/` or `.coding-agent/`; those controls remain Task 8 work.
- Do not stage, commit, push, contact a remote, or mark Task 6 complete before user review and explicit authorization.
- Use `.venv`-local, Git-ignored pytest base directories and disable pytest's cache provider because this Windows checkout has an existing `.pytest_cache` ACL failure unrelated to the project behavior.

## Locked public interfaces and semantics

### `ReplaceTextTool`

```python
class ReplaceTextTool:
    name = "replace_text"
    schema: JSONObject

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution: ...
```

Its argument object contains exactly `path`, `old_text`, `new_text`, and `expected_count`. `str.count()` and `str.replace()` define non-overlapping match semantics. The source is read as raw bytes, decoded strictly as UTF-8, transformed in memory, encoded strictly as UTF-8, checked against the 512 KiB result limit, and only then written with `Path.write_bytes()`. This preserves all unaffected UTF-8 bytes, including CRLF line endings and a UTF-8 BOM. A count mismatch or any validation/encoding/size failure occurs before the write and therefore leaves the file byte-for-byte unchanged.

Success returns JSON equivalent to:

```json
{"path":"src/example.py","replacements":2}
```

and `ToolResultMetadata(changed_paths=("src/example.py",))`. The path is normalized to a workspace-relative POSIX-style string with `/` separators.

### `WriteFileTool`

```python
class WriteFileTool:
    name = "write_file"
    schema: JSONObject

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution: ...
```

Its argument object contains exactly `path` and `content`. `content` is encoded strictly as UTF-8 and limited to at most 524,288 encoded bytes; exactly 524,288 bytes is accepted. The parent must already exist and be a directory. Creation uses binary exclusive mode `xb`, so an existing file is never overwritten even if it appears after the pre-check. No parent directories are created.

Success returns JSON equivalent to:

```json
{"bytes_written":12,"path":"src/new.py"}
```

and `ToolResultMetadata(changed_paths=("src/new.py",))`.

### Minimal `AgentState` extension

```python
class VerificationStatus(StrEnum):
    NOT_RUN = "not_run"
    STALE = "stale"


@dataclass(slots=True)
class AgentState:
    # Existing fields remain unchanged and in their current order.
    mutation_index: int = 0
    modified_paths: tuple[str, ...] = ()
    verification_status: VerificationStatus = VerificationStatus.NOT_RUN
```

`NOT_RUN` is the default because Task 6 does not execute or evaluate verification. `STALE` means only that at least one successful changed-path result occurred. `VerificationStatus` is a `StrEnum`, so its stable JSON-compatible display values are `"not_run"` and `"stale"`; `AgentState` itself gains no serialization API in Task 6. The dataclass representation displays the three new public fields. Task 11 may add additional enum members and evidence fields, but Task 6 does not create `PASSED`/`FAILED` evidence or a `VerificationGate`.

`modified_paths` is an insertion-ordered tuple. New paths are appended once, existing paths retain their original position, and one successful tool call increments `mutation_index` exactly once even if its metadata names multiple paths. The ledger update predicate is exactly:

```python
result.status == "ok" and bool(result.metadata.changed_paths)
```

Read-only results, successful zero-change results, rejected calls, error results, and thrown tool exceptions do not change any ledger field.

## File map

- Modify: `src/coding_agent/tools/filesystem.py` — add write limit, encoding helpers, normalized changed-path metadata, `ReplaceTextTool`, and `WriteFileTool`.
- Modify: `src/coding_agent/state.py` — add `VerificationStatus` and the three minimal ledger fields.
- Modify: `src/coding_agent/agent.py` — observe successful changed-path `ToolResult` values and update `AgentState` deterministically.
- Create: `tests/tools/test_write_tools.py` — direct tool, schema, Registry, encoding, size, and zero-side-effect tests.
- Modify: `tests/test_agent_loop.py` — mutation ledger and verification invalidation component tests while retaining all Task 4 behavior.
- Modify during future execution only: `TASKS.md` — set Task 5 to `已完成` and Task 6 to `进行中` after execution preflight passes.
- Create now only: `docs/superpowers/plans/Task6.md` — this implementation plan.

---

### Task 0: Execution preflight and task-state transition

**Files:**
- Inspect: `AGENTS.md`
- Inspect: `DESIGN.md`
- Inspect: `TASKS.md`
- Inspect: `docs/superpowers/plans/Task6.md`
- Inspect: `src/coding_agent/messages.py`
- Inspect: `src/coding_agent/state.py`
- Inspect: `src/coding_agent/agent.py`
- Inspect: `src/coding_agent/tools/base.py`
- Inspect: `src/coding_agent/tools/registry.py`
- Inspect: `src/coding_agent/tools/filesystem.py`
- Inspect: `tests/test_agent_loop.py`
- Inspect: `tests/tools/test_read_tools.py`
- Modify after all checks pass: `TASKS.md`

**Interfaces:**
- Consumes: Task 5 commit `1909f24` on `main`, the approved Task 6 plan, and a clean implementation baseline.
- Produces: exactly one active task, Task 6, without altering Task 6 production behavior.

- [ ] **Step 1: Re-read every baseline file completely**

Use `Get-Content -Raw` or bounded `Get-Content` ranges until every listed file has been read through its final line. Confirm the actual interfaces match the locked interfaces above.

- [ ] **Step 2: Check repository identity and baseline**

Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git log -3 --oneline
git status --short --untracked-files=all
git diff --check
```

Expected: root `D:/code/coding_agent`, branch `main`, Task 5 commit `1909f24` reachable at the current baseline, no unapproved changes, and no whitespace errors. The approved untracked `docs/superpowers/plans/Task6.md` is allowed. Any other modification stops execution for user review.

- [ ] **Step 3: Update only the two task status values**

Apply this exact state transition in `TASKS.md`:

```diff
 ## 5. 文件读取与目录工具

 **当前状态**

-`进行中`
+`已完成`
 ...
 ## 6. 文件修改工具

 **当前状态**

-`未开始`
+`进行中`
```

Run:

```powershell
$values = @(Get-Content -LiteralPath .\TASKS.md | Where-Object { $_ -match '^`(未开始|进行中|已完成|受阻)`$' })
$active = @($values | Where-Object { $_ -eq '`进行中`' })
if ($active.Count -ne 1) { exit 1 }
Write-Output 'exactly one task is in progress'
git diff -- TASKS.md
```

Expected: exit `0`; the diff contains only Task 5 `进行中` to `已完成` and Task 6 `未开始` to `进行中`. Task 7 and later statuses remain unchanged.

**Acceptance:** the approved design and interfaces still match the repository, the only pre-existing untracked file is the approved Task 6 plan, and exactly Task 6 is active.

---

### Task 1: Complete deterministic `replace_text`

**Files:**
- Create: `tests/tools/test_write_tools.py`
- Modify: `src/coding_agent/tools/filesystem.py`

**Interfaces:**
- Consumes: `_require_exact_arguments()`, `_positive_integer()`, `_functional_workspace_path()`, `_json_execution()`, `ExecutionContext`, `ToolArgumentError`, `ToolExecution`, `ToolResultMetadata`, `JSONObject`, and `ToolRegistry`.
- Produces: `ReplaceTextTool.execute(arguments, context) -> ToolExecution`, exact schema, JSON result, and normalized one-path mutation metadata.

- [ ] **Step 1: Create the complete failing replacement test module**

Create `tests/tools/test_write_tools.py` with exactly this first-cycle content:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from coding_agent.messages import JSONObject, ToolCall, ToolResultMetadata
from coding_agent.tools.base import (
    ExecutionContext,
    ToolArgumentError,
    ToolExecution,
)
from coding_agent.tools.filesystem import (
    ListDirectoryTool,
    ReadFileTool,
    ReplaceTextTool,
)
from coding_agent.tools.registry import ToolRegistry


def _context(tmp_path: Path) -> ExecutionContext:
    return ExecutionContext(workspace=tmp_path)


def _json_output(execution: ToolExecution) -> JSONObject:
    assert execution.output is not None
    decoded = json.loads(execution.output)
    assert isinstance(decoded, dict)
    return decoded


def _replace_arguments(
    path: object = "sample.txt",
    old_text: object = "old",
    new_text: object = "new",
    expected_count: object = 1,
) -> JSONObject:
    return {
        "path": path,
        "old_text": old_text,
        "new_text": new_text,
        "expected_count": expected_count,
    }  # type: ignore[return-value]


def test_replace_text_schema_is_strict_and_complete() -> None:
    assert ReplaceTextTool.schema == {
        "name": "replace_text",
        "description": (
            "Replace an exact number of non-overlapping matches in a UTF-8 file."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "old_text": {"type": "string", "minLength": 1},
                "new_text": {"type": "string"},
                "expected_count": {"type": "integer", "minimum": 1},
            },
            "required": ["path", "old_text", "new_text", "expected_count"],
            "additionalProperties": False,
        },
    }


def test_replace_text_registers_with_existing_read_tools() -> None:
    registry = ToolRegistry(
        (ListDirectoryTool(), ReadFileTool(), ReplaceTextTool())
    )

    assert registry.schemas == (
        ListDirectoryTool.schema,
        ReadFileTool.schema,
        ReplaceTextTool.schema,
    )


def test_replace_text_replaces_one_match_and_reports_path(tmp_path: Path) -> None:
    target = tmp_path / "src" / "sample.py"
    target.parent.mkdir()
    target.write_bytes(b"value = 'old'\r\nkeep = True\r\n")

    execution = ReplaceTextTool().execute(
        _replace_arguments(
            path=r"src\sample.py",
            old_text="'old'",
            new_text="'new'",
        ),
        _context(tmp_path),
    )

    assert target.read_bytes() == b"value = 'new'\r\nkeep = True\r\n"
    assert _json_output(execution) == {
        "path": "src/sample.py",
        "replacements": 1,
    }
    assert execution.metadata == ToolResultMetadata(
        changed_paths=("src/sample.py",)
    )


def test_replace_text_replaces_all_expected_non_overlapping_matches(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("old old old", encoding="utf-8", newline="")

    execution = ReplaceTextTool().execute(
        _replace_arguments(expected_count=3),
        _context(tmp_path),
    )

    assert target.read_bytes() == b"new new new"
    assert _json_output(execution)["replacements"] == 3
    assert execution.metadata.changed_paths == ("sample.txt",)


def test_replace_text_supports_unicode_and_cross_line_matches(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("开始\n旧🙂值\n结束", encoding="utf-8", newline="")

    execution = ReplaceTextTool().execute(
        _replace_arguments(
            old_text="开始\n旧🙂值",
            new_text="开始\n新🙂值",
        ),
        _context(tmp_path),
    )

    assert target.read_text(encoding="utf-8") == "开始\n新🙂值\n结束"
    assert execution.metadata.changed_paths == ("sample.txt",)


def test_replace_text_preserves_bom_and_unaffected_line_endings(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sample.txt"
    before = b"\xef\xbb\xbfalpha\r\nbeta\r\n"
    target.write_bytes(before)

    ReplaceTextTool().execute(
        _replace_arguments(old_text="beta", new_text="gamma"),
        _context(tmp_path),
    )

    assert target.read_bytes() == b"\xef\xbb\xbfalpha\r\ngamma\r\n"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({}, "replace_text arguments must contain exactly"),
        (
            {**_replace_arguments(), "extra": True},
            "replace_text arguments must contain exactly",
        ),
        (_replace_arguments(path=None), "path must be a non-empty string"),
        (_replace_arguments(old_text=7), "old_text must be a string"),
        (_replace_arguments(old_text=""), "old_text must not be empty"),
        (_replace_arguments(new_text=7), "new_text must be a string"),
        (
            _replace_arguments(expected_count=0),
            "expected_count must be a positive integer",
        ),
        (
            _replace_arguments(expected_count=-1),
            "expected_count must be a positive integer",
        ),
        (
            _replace_arguments(expected_count=True),
            "expected_count must be a positive integer",
        ),
        (
            _replace_arguments(expected_count=1.0),
            "expected_count must be a positive integer",
        ),
    ],
)
def test_replace_text_rejects_invalid_arguments(
    tmp_path: Path,
    arguments: JSONObject,
    message: str,
) -> None:
    (tmp_path / "sample.txt").write_text("old", encoding="utf-8")

    with pytest.raises(ToolArgumentError, match=message):
        ReplaceTextTool().execute(arguments, _context(tmp_path))


def test_replace_text_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ToolArgumentError, match="file does not exist"):
        ReplaceTextTool().execute(
            _replace_arguments(path="missing.txt"),
            _context(tmp_path),
        )


def test_replace_text_rejects_directory_target(tmp_path: Path) -> None:
    (tmp_path / "folder").mkdir()

    with pytest.raises(ToolArgumentError, match="path is not a file"):
        ReplaceTextTool().execute(
            _replace_arguments(path="folder"),
            _context(tmp_path),
        )


def test_replace_text_rejects_non_utf8_without_modifying_bytes(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sample.txt"
    before = b"old\xffvalue"
    target.write_bytes(before)

    with pytest.raises(ToolArgumentError, match="file is not valid UTF-8"):
        ReplaceTextTool().execute(
            _replace_arguments(),
            _context(tmp_path),
        )

    assert target.read_bytes() == before


@pytest.mark.parametrize(
    ("source", "expected_count", "actual_count"),
    [
        ("no match", 1, 0),
        ("old", 2, 1),
        ("old old old", 2, 3),
    ],
)
def test_replace_text_count_mismatch_is_byte_for_byte_unchanged(
    tmp_path: Path,
    source: str,
    expected_count: int,
    actual_count: int,
) -> None:
    target = tmp_path / "sample.txt"
    target.write_text(source, encoding="utf-8", newline="")
    before = target.read_bytes()

    with pytest.raises(
        ToolArgumentError,
        match=(
            f"expected {expected_count} matches for old_text, found {actual_count}"
        ),
    ):
        ReplaceTextTool().execute(
            _replace_arguments(expected_count=expected_count),
            _context(tmp_path),
        )

    assert target.read_bytes() == before


def test_replace_text_rejects_result_over_512_kib_without_modification(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sample.txt"
    target.write_bytes(b"old")
    before = target.read_bytes()

    with pytest.raises(
        ToolArgumentError,
        match="result exceeds 512 KiB UTF-8 limit",
    ):
        ReplaceTextTool().execute(
            _replace_arguments(new_text="x" * (512 * 1024 + 1)),
            _context(tmp_path),
        )

    assert target.read_bytes() == before


def test_replace_text_rejects_unencodable_new_text_without_modification(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sample.txt"
    target.write_bytes(b"old")

    with pytest.raises(
        ToolArgumentError,
        match="new_text cannot be encoded as UTF-8",
    ):
        ReplaceTextTool().execute(
            _replace_arguments(new_text="\ud800"),
            _context(tmp_path),
        )

    assert target.read_bytes() == b"old"


def test_replace_text_registry_preserves_success_and_rejection_metadata(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("old", encoding="utf-8")
    registry = ToolRegistry((ReplaceTextTool(),))

    rejected = registry.execute(
        ToolCall(
            call_id="replace_bad",
            name="replace_text",
            arguments=_replace_arguments(expected_count=2),
        ),
        _context(tmp_path),
    )
    succeeded = registry.execute(
        ToolCall(
            call_id="replace_ok",
            name="replace_text",
            arguments=_replace_arguments(),
        ),
        _context(tmp_path),
    )

    assert rejected.status == "rejected"
    assert rejected.metadata.changed_paths == ()
    assert target.read_text(encoding="utf-8") == "new"
    assert succeeded.status == "ok"
    assert succeeded.metadata.changed_paths == ("sample.txt",)
```

- [ ] **Step 2: Run RED and verify the missing behavior**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_write_tools.py -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-red-1
```

Expected: nonzero during collection because `ReplaceTextTool` does not exist. A syntax error, fixture error, or unrelated Task 5 failure is not an acceptable RED; stop and correct the test if the failure differs.

- [ ] **Step 3: Add the minimal replacement implementation**

In `src/coding_agent/tools/filesystem.py`, add next to the existing argument constants:

```python
_REPLACE_ARGUMENTS = {"path", "old_text", "new_text", "expected_count"}
_MAX_WRITE_BYTES = 512 * 1024
```

Replace `_json_execution()` with this backward-compatible private helper:

```python
def _json_execution(
    payload: JSONObject,
    *,
    truncated: bool = False,
    changed_paths: tuple[str, ...] = (),
) -> ToolExecution:
    return ToolExecution(
        output=json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        metadata=ToolResultMetadata(
            truncated=truncated,
            changed_paths=changed_paths,
        ),
    )
```

Add these helpers below `_decode_utf8_prefix()`:

```python
def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ToolArgumentError(f"{name} must be a string")
    return value


def _encode_utf8(value: str, name: str) -> bytes:
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ToolArgumentError(f"{name} cannot be encoded as UTF-8") from exc


def _decode_utf8_file(path: Path) -> tuple[bytes, str]:
    raw = path.read_bytes()
    try:
        return raw, raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolArgumentError("file is not valid UTF-8") from exc


def _relative_output_path(workspace: Path, target: Path) -> str:
    return target.relative_to(workspace).as_posix()
```

Add after `ReadFileTool`:

```python
class ReplaceTextTool:
    name = "replace_text"
    schema: JSONObject = {
        "name": "replace_text",
        "description": (
            "Replace an exact number of non-overlapping matches in a UTF-8 file."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "old_text": {"type": "string", "minLength": 1},
                "new_text": {"type": "string"},
                "expected_count": {"type": "integer", "minimum": 1},
            },
            "required": ["path", "old_text", "new_text", "expected_count"],
            "additionalProperties": False,
        },
    }

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        values = _require_exact_arguments(
            arguments,
            _REPLACE_ARGUMENTS,
            self.name,
        )
        old_text = _required_string(values["old_text"], "old_text")
        if not old_text:
            raise ToolArgumentError("old_text must not be empty")
        new_text = _required_string(values["new_text"], "new_text")
        _encode_utf8(old_text, "old_text")
        _encode_utf8(new_text, "new_text")
        expected_count = _positive_integer(
            values["expected_count"],
            "expected_count",
        )

        workspace, target = _functional_workspace_path(
            values["path"],
            context,
        )
        if not target.exists():
            raise ToolArgumentError("file does not exist")
        if not target.is_file():
            raise ToolArgumentError("path is not a file")

        _, source = _decode_utf8_file(target)
        actual_count = source.count(old_text)
        if actual_count != expected_count:
            raise ToolArgumentError(
                f"expected {expected_count} matches for old_text, "
                f"found {actual_count}"
            )

        rendered = source.replace(old_text, new_text)
        encoded = _encode_utf8(rendered, "result")
        if len(encoded) > _MAX_WRITE_BYTES:
            raise ToolArgumentError("result exceeds 512 KiB UTF-8 limit")

        target.write_bytes(encoded)
        relative_path = _relative_output_path(workspace, target)
        return _json_execution(
            {
                "path": relative_path,
                "replacements": actual_count,
            },
            changed_paths=(relative_path,),
        )
```

The `result` helper name would otherwise produce `result cannot be encoded...`, but the required test expects the user-supplied field name for an invalid replacement. Before rendering, `_encode_utf8(new_text, "new_text")` deterministically catches that case. The rendered encoding call is for the complete-result bound and valid source/new-text combination.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_write_tools.py -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-green-1
```

Expected: exit `0`; all replacement tests pass with no skips. Record the actual pass count, duration, and warnings.

- [ ] **Step 5: Run Task 2–5 regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-regression-1
```

Expected: exit `0`; report the actual count. In particular, Task 5 listing and read metadata remain unchanged despite the private `_json_execution()` extension.

**Acceptance:** strict schema and runtime validation agree; single, multiple, Unicode, and cross-line replacements work; unmatched counts, malformed inputs, invalid UTF-8, invalid output Unicode, and results above 512 KiB cause no write; successful metadata contains one normalized changed path; Registry rejection metadata remains empty.

---

### Task 2: Complete create-only `write_file`

**Files:**
- Modify: `tests/tools/test_write_tools.py`
- Modify: `src/coding_agent/tools/filesystem.py`

**Interfaces:**
- Consumes: Task 1 encoding/path/JSON helpers and existing Tool contracts.
- Produces: `WriteFileTool.execute(arguments, context) -> ToolExecution`, exact schema, exclusive creation, encoded-byte limit, JSON result, and changed-path metadata.

- [ ] **Step 1: Extend imports, schema/registration expectations, and append all write tests**

Change the filesystem import in `tests/tools/test_write_tools.py` to:

```python
from coding_agent.tools.filesystem import (
    ListDirectoryTool,
    ReadFileTool,
    ReplaceTextTool,
    WriteFileTool,
)
```

Append:

```python
def _write_arguments(
    path: object = "created.txt",
    content: object = "content",
) -> JSONObject:
    return {
        "path": path,
        "content": content,
    }  # type: ignore[return-value]


def test_write_file_schema_is_strict_and_complete() -> None:
    assert WriteFileTool.schema == {
        "name": "write_file",
        "description": "Create a new UTF-8 file without overwriting.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    }


def test_all_four_filesystem_tools_register_in_order() -> None:
    registry = ToolRegistry(
        (
            ListDirectoryTool(),
            ReadFileTool(),
            ReplaceTextTool(),
            WriteFileTool(),
        )
    )

    assert registry.schemas == (
        ListDirectoryTool.schema,
        ReadFileTool.schema,
        ReplaceTextTool.schema,
        WriteFileTool.schema,
    )


def test_write_file_creates_normalized_nested_path_and_reports_bytes(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()

    execution = WriteFileTool().execute(
        _write_arguments(path=r"src\created.txt", content="hello\nworld"),
        _context(tmp_path),
    )

    assert (tmp_path / "src" / "created.txt").read_bytes() == b"hello\nworld"
    assert _json_output(execution) == {
        "bytes_written": 11,
        "path": "src/created.txt",
    }
    assert execution.metadata == ToolResultMetadata(
        changed_paths=("src/created.txt",)
    )


@pytest.mark.parametrize(
    ("content", "expected_bytes"),
    [
        ("", b""),
        ("你好🙂", "你好🙂".encode("utf-8")),
    ],
)
def test_write_file_creates_empty_and_unicode_files(
    tmp_path: Path,
    content: str,
    expected_bytes: bytes,
) -> None:
    execution = WriteFileTool().execute(
        _write_arguments(content=content),
        _context(tmp_path),
    )

    assert (tmp_path / "created.txt").read_bytes() == expected_bytes
    assert _json_output(execution)["bytes_written"] == len(expected_bytes)
    assert execution.metadata.changed_paths == ("created.txt",)


def test_write_file_accepts_exactly_512_kib_of_utf8_bytes(
    tmp_path: Path,
) -> None:
    content = "x" * (512 * 1024)

    execution = WriteFileTool().execute(
        _write_arguments(content=content),
        _context(tmp_path),
    )

    assert (tmp_path / "created.txt").stat().st_size == 512 * 1024
    assert _json_output(execution)["bytes_written"] == 512 * 1024
    assert execution.metadata.changed_paths == ("created.txt",)


def test_write_file_rejects_more_than_512_kib_by_encoded_byte_count(
    tmp_path: Path,
) -> None:
    content = "🙂" * (512 * 1024 // 4) + "x"

    with pytest.raises(
        ToolArgumentError,
        match="content exceeds 512 KiB UTF-8 limit",
    ):
        WriteFileTool().execute(
            _write_arguments(content=content),
            _context(tmp_path),
        )

    assert not (tmp_path / "created.txt").exists()


def test_write_file_never_overwrites_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "created.txt"
    target.write_bytes(b"original")

    with pytest.raises(ToolArgumentError, match="file already exists"):
        WriteFileTool().execute(
            _write_arguments(content="replacement"),
            _context(tmp_path),
        )

    assert target.read_bytes() == b"original"


def test_write_file_rejects_existing_directory(tmp_path: Path) -> None:
    (tmp_path / "created.txt").mkdir()

    with pytest.raises(ToolArgumentError, match="path is an existing directory"):
        WriteFileTool().execute(
            _write_arguments(),
            _context(tmp_path),
        )


def test_write_file_rejects_missing_parent_without_creating_directories(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ToolArgumentError,
        match="parent directory does not exist",
    ):
        WriteFileTool().execute(
            _write_arguments(path="missing/created.txt"),
            _context(tmp_path),
        )

    assert not (tmp_path / "missing").exists()


def test_write_file_rejects_parent_that_is_a_file(tmp_path: Path) -> None:
    (tmp_path / "parent").write_bytes(b"not a directory")

    with pytest.raises(
        ToolArgumentError,
        match="parent path is not a directory",
    ):
        WriteFileTool().execute(
            _write_arguments(path="parent/created.txt"),
            _context(tmp_path),
        )

    assert not (tmp_path / "parent" / "created.txt").exists()


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({}, "write_file arguments must contain exactly"),
        (
            {**_write_arguments(), "extra": True},
            "write_file arguments must contain exactly",
        ),
        (_write_arguments(path=None), "path must be a non-empty string"),
        (_write_arguments(content=None), "content must be a string"),
        (_write_arguments(content=7), "content must be a string"),
    ],
)
def test_write_file_rejects_invalid_arguments_without_creating_target(
    tmp_path: Path,
    arguments: JSONObject,
    message: str,
) -> None:
    with pytest.raises(ToolArgumentError, match=message):
        WriteFileTool().execute(arguments, _context(tmp_path))

    assert not (tmp_path / "created.txt").exists()


def test_write_file_rejects_unencodable_content_without_creating_target(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ToolArgumentError,
        match="content cannot be encoded as UTF-8",
    ):
        WriteFileTool().execute(
            _write_arguments(content="\ud800"),
            _context(tmp_path),
        )

    assert not (tmp_path / "created.txt").exists()


def test_write_file_registry_preserves_success_and_rejection_metadata(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry((WriteFileTool(),))

    succeeded = registry.execute(
        ToolCall(
            call_id="write_ok",
            name="write_file",
            arguments=_write_arguments(),
        ),
        _context(tmp_path),
    )
    rejected = registry.execute(
        ToolCall(
            call_id="write_bad",
            name="write_file",
            arguments=_write_arguments(),
        ),
        _context(tmp_path),
    )

    assert succeeded.status == "ok"
    assert succeeded.metadata.changed_paths == ("created.txt",)
    assert rejected.status == "rejected"
    assert rejected.metadata.changed_paths == ()
    assert (tmp_path / "created.txt").read_bytes() == b"content"
```

- [ ] **Step 2: Run RED and verify the missing behavior**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_write_tools.py -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-red-2
```

Expected: nonzero during collection because `WriteFileTool` does not exist. All already-implemented replacement behavior must have passed in the preceding GREEN; do not change replacement tests to make this RED easier.

- [ ] **Step 3: Implement exclusive create-only writing**

Add next to the argument constants in `src/coding_agent/tools/filesystem.py`:

```python
_WRITE_ARGUMENTS = {"path", "content"}
```

Add after `ReplaceTextTool`:

```python
class WriteFileTool:
    name = "write_file"
    schema: JSONObject = {
        "name": "write_file",
        "description": "Create a new UTF-8 file without overwriting.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    }

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        values = _require_exact_arguments(
            arguments,
            _WRITE_ARGUMENTS,
            self.name,
        )
        content = _required_string(values["content"], "content")
        encoded = _encode_utf8(content, "content")
        if len(encoded) > _MAX_WRITE_BYTES:
            raise ToolArgumentError("content exceeds 512 KiB UTF-8 limit")

        workspace, target = _functional_workspace_path(
            values["path"],
            context,
        )
        if target.exists():
            if target.is_dir():
                raise ToolArgumentError("path is an existing directory")
            raise ToolArgumentError("file already exists")
        if not target.parent.exists():
            raise ToolArgumentError("parent directory does not exist")
        if not target.parent.is_dir():
            raise ToolArgumentError("parent path is not a directory")

        try:
            with target.open("xb") as stream:
                stream.write(encoded)
        except FileExistsError as exc:
            raise ToolArgumentError("file already exists") from exc

        relative_path = _relative_output_path(workspace, target)
        return _json_execution(
            {
                "bytes_written": len(encoded),
                "path": relative_path,
            },
            changed_paths=(relative_path,),
        )
```

Every validation and byte-limit check precedes `open("xb")`. Exclusive creation is the deterministic no-overwrite enforcement; the earlier `exists()` check exists only to provide a stable directory-specific error.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_write_tools.py -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-green-2
```

Expected: exit `0`; all replacement and creation tests pass with no skips. Report actual counts, duration, and warnings.

- [ ] **Step 5: Run Task 2–5 regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\tools\test_read_tools.py -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-regression-2
```

Expected: exit `0`; report actual counts.

**Acceptance:** ordinary, empty, Unicode, and exact-limit files are created as exact UTF-8 bytes; byte count, normalized path, and metadata are truthful; over-limit/unencodable content, existing targets, missing/non-directory parents, and malformed arguments leave no new target and no changed path; no overwrite or directory creation API exists.

---

### Task 3: Minimal mutation ledger and verification invalidation

**Files:**
- Modify: `tests/test_agent_loop.py`
- Modify: `src/coding_agent/state.py`
- Modify: `src/coding_agent/agent.py`

**Interfaces:**
- Consumes: existing `AgentState`, `AgentRunner`, sequential `ToolRegistry.execute() -> ToolResult`, and Task 6 changed-path metadata.
- Produces: `VerificationStatus`, `AgentState.mutation_index`, `AgentState.modified_paths`, `AgentState.verification_status`, and deterministic AgentRunner observation of successful mutations.

- [ ] **Step 1: Add all state and runner tests before production changes**

In `tests/test_agent_loop.py`, add `import json` next to existing standard-library imports. Change imports to include:

```python
from coding_agent.state import AgentStatus, VerificationStatus
from coding_agent.tools.filesystem import (
    ReadFileTool,
    ReplaceTextTool,
    WriteFileTool,
)
```

Add these assertions to `test_direct_text_returns_completion_candidate()` after the existing counter assertions:

```python
    assert state.mutation_index == 0
    assert state.modified_paths == ()
    assert state.verification_status is VerificationStatus.NOT_RUN
    assert json.dumps(state.verification_status) == '"not_run"'
    assert "mutation_index=0" in repr(state)
    assert "modified_paths=()" in repr(state)
    assert "verification_status=" in repr(state)
```

Add these assertions to `test_tool_exception_becomes_error_result_without_traceback()` before its final status assertion:

```python
    assert state.mutation_index == 0
    assert state.modified_paths == ()
    assert state.verification_status is VerificationStatus.NOT_RUN
```

Append the following tests:

```python
def test_successful_replace_updates_ledger_and_marks_verification_stale(
    tmp_path: Path,
) -> None:
    (tmp_path / "sample.txt").write_text("old", encoding="utf-8")
    call = ToolCall(
        call_id="replace_1",
        name="replace_text",
        arguments={
            "path": "sample.txt",
            "old_text": "old",
            "new_text": "new",
            "expected_count": 1,
        },
    )
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="done")),
        tools=(ReplaceTextTool(),),
    )

    state = runner.run("replace text")

    assert state.mutation_index == 1
    assert state.modified_paths == ("sample.txt",)
    assert state.verification_status is VerificationStatus.STALE
    assert json.dumps(state.verification_status) == '"stale"'


def test_successful_write_updates_ledger_and_marks_verification_stale(
    tmp_path: Path,
) -> None:
    call = ToolCall(
        call_id="write_1",
        name="write_file",
        arguments={"path": "created.txt", "content": "content"},
    )
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="done")),
        tools=(WriteFileTool(),),
    )

    state = runner.run("create file")

    assert state.mutation_index == 1
    assert state.modified_paths == ("created.txt",)
    assert state.verification_status is VerificationStatus.STALE


def test_successful_calls_increment_per_call_and_deduplicate_in_first_seen_order(
    tmp_path: Path,
) -> None:
    write_b = ToolCall(
        call_id="write_b",
        name="write_file",
        arguments={"path": "b.txt", "content": "old"},
    )
    write_a = ToolCall(
        call_id="write_a",
        name="write_file",
        arguments={"path": "a.txt", "content": "a"},
    )
    replace_b = ToolCall(
        call_id="replace_b",
        name="replace_text",
        arguments={
            "path": "b.txt",
            "old_text": "old",
            "new_text": "new",
            "expected_count": 1,
        },
    )
    runner, _ = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(write_b, write_a, replace_b)),
            ModelResponse(text="done"),
        ),
        tools=(WriteFileTool(), ReplaceTextTool()),
    )

    state = runner.run("modify two paths")

    assert state.mutation_index == 3
    assert state.modified_paths == ("b.txt", "a.txt")
    assert state.verification_status is VerificationStatus.STALE


@dataclass(slots=True)
class MultiPathMutationTool:
    name: str = field(default="multi_path_mutation", init=False)
    schema: JSONObject = field(
        default_factory=lambda: {
            "name": "multi_path_mutation",
            "description": "Return two changed paths for ledger testing.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
        init=False,
    )

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        return ToolExecution(
            output="changed two paths",
            metadata=ToolResultMetadata(changed_paths=("z.py", "a.py")),
        )


def test_one_successful_call_with_multiple_paths_increments_once(
    tmp_path: Path,
) -> None:
    call = ToolCall(
        call_id="multi_1",
        name="multi_path_mutation",
        arguments={},
    )
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="done")),
        tools=(MultiPathMutationTool(),),
    )

    state = runner.run("record multiple paths")

    assert state.mutation_index == 1
    assert state.modified_paths == ("z.py", "a.py")
    assert state.verification_status is VerificationStatus.STALE


def test_read_file_does_not_change_mutation_state(tmp_path: Path) -> None:
    (tmp_path / "sample.txt").write_text("content", encoding="utf-8")
    call = ToolCall(
        call_id="read_1",
        name="read_file",
        arguments={"path": "sample.txt", "start_line": 1, "end_line": None},
    )
    runner, _ = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="done")),
        tools=(ReadFileTool(),),
    )

    state = runner.run("read without changing")

    assert state.mutation_index == 0
    assert state.modified_paths == ()
    assert state.verification_status is VerificationStatus.NOT_RUN


def test_failed_replace_does_not_change_mutation_state(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("old", encoding="utf-8")
    call = ToolCall(
        call_id="replace_bad",
        name="replace_text",
        arguments={
            "path": "sample.txt",
            "old_text": "old",
            "new_text": "new",
            "expected_count": 2,
        },
    )
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="done")),
        tools=(ReplaceTextTool(),),
    )

    state = runner.run("failed replace")

    result = client.requests[1].messages[2]
    assert isinstance(result, ToolResult)
    assert result.status == "rejected"
    assert target.read_text(encoding="utf-8") == "old"
    assert state.mutation_index == 0
    assert state.modified_paths == ()
    assert state.verification_status is VerificationStatus.NOT_RUN


def test_failed_write_does_not_change_mutation_state(tmp_path: Path) -> None:
    target = tmp_path / "created.txt"
    target.write_text("original", encoding="utf-8")
    call = ToolCall(
        call_id="write_bad",
        name="write_file",
        arguments={"path": "created.txt", "content": "replacement"},
    )
    runner, client = _runner(
        tmp_path,
        (ModelResponse(tool_calls=(call,)), ModelResponse(text="done")),
        tools=(WriteFileTool(),),
    )

    state = runner.run("failed write")

    result = client.requests[1].messages[2]
    assert isinstance(result, ToolResult)
    assert result.status == "rejected"
    assert target.read_text(encoding="utf-8") == "original"
    assert state.mutation_index == 0
    assert state.modified_paths == ()
    assert state.verification_status is VerificationStatus.NOT_RUN


def test_rejection_and_exception_after_success_preserve_existing_ledger(
    tmp_path: Path,
) -> None:
    write = ToolCall(
        call_id="write_ok",
        name="write_file",
        arguments={"path": "created.txt", "content": "content"},
    )
    rejected_write = ToolCall(
        call_id="write_bad",
        name="write_file",
        arguments={"path": "created.txt", "content": "replacement"},
    )
    explosion = ToolCall(call_id="explode_after_write", name="explode", arguments={})
    runner, client = _runner(
        tmp_path,
        (
            ModelResponse(tool_calls=(write, rejected_write, explosion)),
            ModelResponse(text="done"),
        ),
        tools=(WriteFileTool(), ExplodingTool()),
    )

    state = runner.run("preserve ledger after failures")

    first_request_with_results = client.requests[1].messages
    results = [
        message
        for message in first_request_with_results
        if isinstance(message, ToolResult)
    ]
    assert [result.status for result in results] == ["ok", "rejected", "error"]
    assert state.mutation_index == 1
    assert state.modified_paths == ("created.txt",)
    assert state.verification_status is VerificationStatus.STALE
```

- [ ] **Step 2: Run RED and verify the missing state interface**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-red-3
```

Expected: nonzero during collection because `VerificationStatus` does not exist. If the failure instead comes from Task 6 tool behavior, restore the preceding GREEN before changing state code.

- [ ] **Step 3: Add the minimal state fields**

In `src/coding_agent/state.py`, add immediately after `AgentStatus`:

```python
class VerificationStatus(StrEnum):
    NOT_RUN = "not_run"
    STALE = "stale"
```

Add after `tool_call_count` in `AgentState`, before completion/failure fields:

```python
    mutation_index: int = 0
    modified_paths: tuple[str, ...] = ()
    verification_status: VerificationStatus = VerificationStatus.NOT_RUN
```

Do not add `SUCCESS`, verification evidence, `validation_index`, commands, exit codes, timestamps, or a gate. Existing `AgentState.start()` relies on these defaults and needs no change.

- [ ] **Step 4: Add deterministic observation to `AgentRunner`**

Change the imports in `src/coding_agent/agent.py` to:

```python
from coding_agent.messages import AssistantMessage, ModelRequest, ToolResult
from coding_agent.state import AgentState, AgentStatus, VerificationStatus
```

Add this private function before `AgentRunner`:

```python
def _record_successful_mutation(
    state: AgentState,
    result: ToolResult,
) -> None:
    changed_paths = result.metadata.changed_paths
    if result.status != "ok" or not changed_paths:
        return

    state.mutation_index += 1
    known_paths = set(state.modified_paths)
    new_paths = tuple(path for path in changed_paths if path not in known_paths)
    state.modified_paths += new_paths
    state.verification_status = VerificationStatus.STALE
```

In the tool loop, place the observation after the `ToolResult` is appended and before the count is incremented:

```python
                    state.messages += (result,)
                    _record_successful_mutation(state, result)
                    state.tool_call_count += 1
```

`ToolResultMetadata` already rejects duplicates within one result. `known_paths` is built once per result, so its iteration does not affect output order; the tuple comprehension retains `changed_paths` order. `ToolRegistry` remains unchanged.

- [ ] **Step 5: Run GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-green-3
```

Expected: exit `0`; all Task 4 and new Task 6 loop tests pass. Record actual counts and warnings.

- [ ] **Step 6: Run Task 2–5 regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-regression-3
```

Expected: exit `0`; report actual counts. This separately proves message types, model fakes, read tools, and direct write tools did not regress.

**Acceptance:** both real mutation tools update state; three successful calls increment three times; repeated paths appear once in first-seen order; multiple changed paths from one successful call increment once; reads, replacement rejection, write rejection, and unexpected tool exceptions preserve both a default ledger and an existing stale ledger; every mutation marks the minimal verification status `STALE` without making a success decision.

---

### Task 4: Offline boundary and final verification

**Files:**
- Modify: `tests/tools/test_write_tools.py`
- Inspect: every Task 6 production/test change, `TASKS.md`, `pyproject.toml`, and existing public contracts.

**Interfaces:**
- Consumes: completed Task 6 behavior.
- Produces: fresh, reproducible evidence and a user-review stopping point.

- [ ] **Step 1: Add the offline import boundary test**

Add these imports to `tests/tools/test_write_tools.py`:

```python
import os
import subprocess
import sys
```

Append:

```python
def test_task6_imports_without_openai_api_key_or_network() -> None:
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "openai" or name.startswith("openai."):
        raise AssertionError("Task 6 imported OpenAI SDK")
    if name in {"socket", "urllib", "http", "requests"}:
        raise AssertionError("Task 6 imported a network module")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import coding_agent.agent
import coding_agent.state
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
.\.venv\Scripts\python.exe -m pytest tests\tools\test_write_tools.py::test_task6_imports_without_openai_api_key_or_network -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-offline
```

Expected: exit `0`, exactly one test passes, no production change is needed. A failure requires removing the unexpected import before continuing.

- [ ] **Step 2: Run Task 6 direct-tool tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\tools\test_write_tools.py -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-tools-final
```

Expected: exit `0`, no failures or skips. Report actual counts, duration, and warnings.

- [ ] **Step 3: Run the Agent loop and read-tool regressions separately**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-agent-final
.\.venv\Scripts\python.exe -m pytest tests\tools\test_read_tools.py -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-read-final
```

Expected: each command exits `0` with no skips. Record each actual count separately.

- [ ] **Step 4: Run the full repository suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-all-final
```

Expected: exit `0`, no failures or skips. The output count is authoritative; do not reuse a planned or earlier count.

- [ ] **Step 5: Verify exact schemas and public signatures**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import inspect; import coding_agent.tools.filesystem as f; expected={'arguments':'JSONObject','context':'ExecutionContext','return':'ToolExecution'}; assert f.ReplaceTextTool.name=='replace_text'; assert f.WriteFileTool.name=='write_file'; assert tuple(inspect.signature(f.ReplaceTextTool.execute).parameters)==('self','arguments','context'); assert f.ReplaceTextTool.execute.__annotations__==expected; assert tuple(inspect.signature(f.WriteFileTool.execute).parameters)==('self','arguments','context'); assert f.WriteFileTool.execute.__annotations__==expected; assert f.ReplaceTextTool.schema['strict'] is True and f.ReplaceTextTool.schema['parameters']['additionalProperties'] is False; assert f.WriteFileTool.schema['strict'] is True and f.WriteFileTool.schema['parameters']['additionalProperties'] is False; print('task-6 schemas and public tool signatures verified')"
```

Expected: exit `0` and the stated line.

Run:

```powershell
.\.venv\Scripts\python.exe -c "from coding_agent.state import AgentState,VerificationStatus; state=AgentState.start('audit'); assert state.mutation_index==0; assert state.modified_paths==(); assert state.verification_status is VerificationStatus.NOT_RUN; assert tuple(item.value for item in VerificationStatus)==('not_run','stale'); print('minimal task-6 state interface verified')"
```

Expected: exit `0` and `minimal task-6 state interface verified`.

- [ ] **Step 6: Verify existing type reuse and Registry compatibility**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import ast,pathlib; tree=ast.parse(pathlib.Path('src/coding_agent/tools/filesystem.py').read_text(encoding='utf-8')); forbidden={'Tool','ToolExecution','ToolArgumentError','ExecutionContext','ToolRegistry','ToolResult','ToolResultMetadata','JSONObject','AgentState'}; defined={node.name for node in ast.walk(tree) if isinstance(node,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef))}; assert not defined.intersection(forbidden),defined.intersection(forbidden); print('existing task-2 through task-5 public types are reused')"
```

Expected: exit `0` and the stated line.

Run:

```powershell
.\.venv\Scripts\python.exe -c "from coding_agent.tools.filesystem import ListDirectoryTool,ReadFileTool,ReplaceTextTool,WriteFileTool; from coding_agent.tools.registry import ToolRegistry; tools=(ListDirectoryTool(),ReadFileTool(),ReplaceTextTool(),WriteFileTool()); registry=ToolRegistry(tools); assert registry.schemas==tuple(tool.schema for tool in tools); print('existing ToolRegistry accepts all four filesystem tools unchanged')"
git diff --exit-code -- src/coding_agent/tools/registry.py src/coding_agent/tools/base.py src/coding_agent/messages.py
```

Expected: both commands exit `0`; the Registry line is printed and the Git diff command has no output.

- [ ] **Step 7: Audit ledger predicates and failure zero-side-effects**

Run the exact focused tests again by public name:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py::test_successful_calls_increment_per_call_and_deduplicate_in_first_seen_order tests\test_agent_loop.py::test_one_successful_call_with_multiple_paths_increments_once tests\test_agent_loop.py::test_read_file_does_not_change_mutation_state tests\test_agent_loop.py::test_failed_replace_does_not_change_mutation_state tests\test_agent_loop.py::test_failed_write_does_not_change_mutation_state tests\test_agent_loop.py::test_tool_exception_becomes_error_result_without_traceback tests\test_agent_loop.py::test_rejection_and_exception_after_success_preserve_existing_ledger tests\tools\test_write_tools.py::test_replace_text_count_mismatch_is_byte_for_byte_unchanged tests\tools\test_write_tools.py::test_write_file_rejects_more_than_512_kib_by_encoded_byte_count -q -p no:cacheprovider --basetemp .\.venv\pytest-task6-ledger-final
```

Expected: exit `0`; report the actual parameterized test count. This command is the direct evidence for successful-call counting, multiple paths per call, deterministic deduplication, read neutrality, rejection/error neutrality, byte-level replacement rollback, and no target on oversize write.

- [ ] **Step 8: Audit dependencies and offline scope**

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
    'run_command',
    'PathGuard',
    'SafetyPolicy',
    'CommandPolicy',
    'VerificationGate',
    'TerminationPolicy',
    'ContextManager',
    'validation_index',
    'symlink',
    'junction',
    'reparse',
    '.unlink(',
    '.rename(',
    '.chmod('
)
$sourcePaths = @(
    '.\src\coding_agent\tools\filesystem.py',
    '.\src\coding_agent\state.py',
    '.\src\coding_agent\agent.py'
)
$matches = Select-String -Path $sourcePaths -Pattern $forbidden
if ($matches) { $matches; exit 1 }
Write-Output 'task-6 scope and deferred task boundaries verified'
```

Expected: exit `0`. This proves only that later-task implementations were not introduced; it does not prove Task 8 path security or Task 11 verification correctness.

- [ ] **Step 9: Scan credentials without printing matched values**

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

Expected: exit `0`; only file paths are printed on failure.

- [ ] **Step 10: Scan placeholders, skipped tests, and temporary code**

Run:

```powershell
$markers = @(
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
$paths = @(
    '.\src\coding_agent\tools\filesystem.py',
    '.\src\coding_agent\state.py',
    '.\src\coding_agent\agent.py',
    '.\tests\tools\test_write_tools.py',
    '.\tests\test_agent_loop.py',
    '.\docs\superpowers\plans\Task6.md'
)
$matches = Select-String -Path $paths -Pattern $markers
if ($matches) { $matches; exit 1 }
Write-Output 'no placeholders, skipped tests, or temporary code found'
```

Expected: exit `0` and the stated line.

- [ ] **Step 11: Review exact diff and workspace state**

Run each command separately and record its exit code:

```powershell
git diff --check
git status --short --untracked-files=all
git diff -- TASKS.md src/coding_agent/tools/filesystem.py src/coding_agent/state.py src/coding_agent/agent.py tests/tools/test_write_tools.py tests/test_agent_loop.py docs/superpowers/plans/Task6.md
git diff --exit-code -- src/coding_agent/messages.py src/coding_agent/model.py src/coding_agent/tools/base.py src/coding_agent/tools/registry.py src/coding_agent/cli.py src/coding_agent/config.py pyproject.toml
```

Because new untracked files are not displayed by ordinary `git diff`, also read `tests/tools/test_write_tools.py` and `docs/superpowers/plans/Task6.md` completely and run a trailing-whitespace/final-newline check over them. Expected: only the approved Task 6 files and two task-status lines differ; protected interfaces and dependencies remain byte-for-byte unchanged.

- [ ] **Step 12: Review the Task 6 acceptance matrix**

| Requirement | Passing evidence |
| --- | --- |
| Exact strict schemas and extra-key rejection | two schema tests and invalid-argument parameterizations |
| Single and multiple exact replacement | single-match and three-match tests |
| Unicode and cross-line replacement | Unicode/cross-line test |
| Preserve unrelated UTF-8 bytes and line endings | BOM/CRLF test |
| Zero, fewer, and excess matches cause zero writes | parameterized byte-for-byte mismatch test |
| Empty `old_text` and invalid `expected_count`, including `bool` | replacement invalid-argument parameterization |
| Missing file, directory, and invalid UTF-8 rejection | three direct replacement rejection tests |
| Replacement result write bound and invalid Unicode | two zero-modification tests |
| Normalized replacement changed path | single replacement and Registry tests |
| Ordinary, empty, and Unicode new files | creation tests |
| Exactly 512 KiB accepted; encoded bytes above rejected | exact-boundary and multibyte-over-limit tests |
| No overwrite and directory target rejection | existing file/directory tests |
| Missing/non-directory parent rejected without creation | two parent tests |
| Invalid write arguments and unencodable content have no target | parameterized and Unicode-error tests |
| Exclusive Registry success/rejection metadata | write Registry test |
| Successful replace and write update state | two AgentRunner tests |
| One increment per successful call | sequential-call and multiple-path tests |
| Ledger deduplication and deterministic first-seen order | three-call `b.txt`, `a.txt`, `b.txt` test |
| Read, rejected calls, and exceptions do not mutate state | read, failed replace/write, exploding-tool, and post-success failure tests |
| Mutation makes verification `STALE` | successful mutation tests |
| Default state and display/JSON-compatible enum values | direct completion default assertions |
| Existing Task 2–5 interfaces remain compatible | regression suite, AST reuse, unchanged-file diff, Registry audit |
| Completely offline, no real key, no new dependency | fresh-process import, credential scan, dependency audit |
| No Task 7, Task 8, or Task 11 implementation | forbidden-scope scan and full diff review |

If any row lacks fresh passing evidence, keep Task 6 `进行中`, report the exact gap, and stop without staging or committing.

- [ ] **Step 13: Stop for user review**

Report every RED command with its actual nonzero exit code and expected missing behavior; every GREEN/regression/final command with real counts; warnings, skips, failures, and environment workarounds; interface and scope audit results; exact changed files; and the incomplete Task 8/Task 11 boundaries.

Do not mark Task 6 `已完成`, stage, commit, push, use a branch-finishing workflow, or start Task 7. The suggested future commit message is `feat: add deterministic file modification tools`, but it requires separate user authorization after review.

## Plan self-check

- Every Task 6 acceptance criterion maps to a named test or deterministic audit in the matrix.
- Every production behavior is introduced by a complete RED test set before its minimal implementation, followed by GREEN and Task 2–5 regression commands.
- Public names are consistent throughout: `ReplaceTextTool`, `WriteFileTool`, `VerificationStatus`, `mutation_index`, `modified_paths`, and `verification_status`.
- Both tools use `execute(arguments: JSONObject, context: ExecutionContext) -> ToolExecution`, and Registry continues producing the existing `ToolResult` without modification.
- The 512 KiB boundary is exactly 524,288 UTF-8 encoded bytes; equality is accepted and any larger result/content is rejected before writing.
- Replacement count uses non-overlapping Python string semantics and all mismatch paths are byte-for-byte non-mutating.
- The ledger increments once per successful changed-path result, retains first-seen path order without duplicates, and ignores reads, zero-change results, rejections, errors, and exceptions.
- The state extension is minimal: only `NOT_RUN` and `STALE` exist, with no verification evidence or decision logic.
- No deletion, move, rename, permission change, arbitrary patch, Shell execution, unified `PathGuard`, linked-path safety, reserved-directory policy, OpenAI call, context compression, termination policy, verification gate, automatic command, log, report, CLI wiring, or new dependency is planned.
- Default tests remain offline and operate only in pytest `tmp_path` workspaces.
- Execution stops for user approval before staging, committing, pushing, or starting Task 7.

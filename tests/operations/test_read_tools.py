from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from coding_agent.engine.messages import JSONObject, ToolCall, ToolResultMetadata
from coding_agent.operations.safety import PathGuard, SafetyCode, SafetyViolation
from coding_agent.operations.tools.base import (
    ExecutionContext,
    ToolArgumentError,
    ToolExecution,
)
from coding_agent.operations.tools.filesystem import ListDirectoryTool, ReadFileTool
from coding_agent.operations.tools.registry import ToolRegistry


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
    with pytest.raises(SafetyViolation) as exc_info:
        ListDirectoryTool().execute(
            _list_arguments(path="missing"),
            _context(tmp_path),
        )
    assert exc_info.value.code is SafetyCode.PATH_NOT_FOUND


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


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("", SafetyCode.INVALID_PATH),
        (None, SafetyCode.INVALID_PATH),
        ("bad\x00path", SafetyCode.INVALID_PATH),
        ("..\\outside", SafetyCode.PATH_OUTSIDE_WORKSPACE),
        (Path.cwd().anchor, SafetyCode.PATH_OUTSIDE_WORKSPACE),
    ],
)
def test_list_directory_rejects_unsafe_paths_with_stable_code(
    tmp_path: Path,
    path: object,
    code: SafetyCode,
) -> None:
    with pytest.raises(SafetyViolation) as exc_info:
        ListDirectoryTool().execute(
            _list_arguments(path=path),
            _context(tmp_path),
        )
    assert exc_info.value.code is code


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
    ("arguments", "expected"),
    [
        ({}, "read_file arguments must contain exactly"),
        (
            {**_read_arguments(), "extra": True},
            "read_file arguments must contain exactly",
        ),
        (_read_arguments(path=""), SafetyCode.INVALID_PATH),
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
    expected: str | SafetyCode,
) -> None:
    (tmp_path / "notes.txt").write_text("content", encoding="utf-8")

    if isinstance(expected, SafetyCode):
        with pytest.raises(SafetyViolation) as exc_info:
            ReadFileTool().execute(arguments, _context(tmp_path))
        assert exc_info.value.code is expected
    else:
        with pytest.raises(ToolArgumentError, match=expected):
            ReadFileTool().execute(arguments, _context(tmp_path))


def test_read_file_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SafetyViolation) as exc_info:
        ReadFileTool().execute(
            _read_arguments(path="missing.txt"),
            _context(tmp_path),
        )
    assert exc_info.value.code is SafetyCode.PATH_NOT_FOUND


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
import coding_agent.operations.tools.filesystem
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

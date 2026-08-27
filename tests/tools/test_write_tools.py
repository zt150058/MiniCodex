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
from coding_agent.tools.filesystem import (
    ListDirectoryTool,
    ReadFileTool,
    ReplaceTextTool,
    WriteFileTool,
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

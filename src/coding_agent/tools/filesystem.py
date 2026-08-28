from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path

from coding_agent.messages import JSONObject, ToolResultMetadata
from coding_agent.safety import (
    GuardedPath,
    PathGuard,
    SafetyCode,
    SafetyViolation,
)
from coding_agent.tools.base import (
    ExecutionContext,
    ToolArgumentError,
    ToolExecution,
)

_LIST_ARGUMENTS = {"path", "recursive", "max_depth", "max_entries"}
_READ_ARGUMENTS = {"path", "start_line", "end_line"}
_REPLACE_ARGUMENTS = {"path", "old_text", "new_text", "expected_count"}
_WRITE_ARGUMENTS = {"path", "content"}
_MAX_READ_BYTES = 256 * 1024
_MAX_WRITE_BYTES = 512 * 1024


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


def _entry_type(path: Path) -> str:
    if path.is_dir():
        return "directory"
    return "file"


def _directory_children(path: Path) -> list[Path]:
    return sorted(path.iterdir(), key=lambda item: (item.name.casefold(), item.name))


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


def _without_line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1]
    return line


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

        target = PathGuard(context.workspace).existing_file(
            values["path"]
        ).absolute

        text, size_truncated = _decode_utf8_prefix(target)
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

        guarded_target = PathGuard(context.workspace).existing_file(
            values["path"]
        )
        target = guarded_target.absolute
        relative = guarded_target.relative

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
        return _json_execution(
            {
                "path": relative,
                "replacements": actual_count,
            },
            changed_paths=(relative,),
        )


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

        guarded_target = PathGuard(context.workspace).new_file(values["path"])
        target = guarded_target.absolute
        relative = guarded_target.relative

        try:
            with target.open("xb") as stream:
                stream.write(encoded)
        except FileExistsError as exc:
            raise ToolArgumentError("file already exists") from exc

        return _json_execution(
            {
                "bytes_written": len(encoded),
                "path": relative,
            },
            changed_paths=(relative,),
        )

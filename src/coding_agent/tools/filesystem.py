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

        _, target = _functional_workspace_path(values["path"], context)
        if not target.exists():
            raise ToolArgumentError("file does not exist")
        if not target.is_file():
            raise ToolArgumentError("path is not a file")

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

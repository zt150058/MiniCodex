from __future__ import annotations

from collections.abc import Callable
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import subprocess
import sys

from coding_agent.tools.base import ToolArgumentError


_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}
_PROTECTED_COMPONENTS = {".git", ".coding-agent"}
_PURPOSES = {"inspect", "test", "verification"}
_CONTROL_CHARACTERS = frozenset("&|><\r\n\x00")
_PYTEST_FLAGS = {
    "-q", "--quiet", "-v", "--verbose", "-x", "--exitfirst",
    "--disable-warnings", "--strict-markers", "--strict-config",
    "--help", "--version",
}
_PYTEST_TB = {"auto", "long", "short", "line", "native", "no"}
_UNITTEST_FLAGS = {"-q", "-v", "-f", "-b", "--locals", "--help"}
_DOTTED_TEST = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_RUFF_SIMPLE_FLAGS = {"--no-cache", "--quiet", "--verbose"}
_RUFF_OUTPUT_FORMATS = {
    "concise", "full", "json", "json-lines", "junit", "github",
    "gitlab", "pylint", "rdjson", "sarif",
}
_RUFF_RULES = re.compile(r"[A-Za-z0-9,]+")
_MYPY_SIMPLE_FLAGS = {
    "--no-site-packages", "--show-error-codes", "--pretty", "--strict",
    "--warn-unused-ignores", "--ignore-missing-imports",
}
_MYPY_FOLLOW_IMPORTS = {"normal", "silent", "skip", "error"}
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


def _is_reparse_point(path: Path) -> bool:
    try:
        result = os.lstat(path)
    except FileNotFoundError:
        return path.is_symlink()
    attributes = getattr(result, "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


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


@dataclass(frozen=True, slots=True)
class GuardedPath:
    absolute: Path
    relative: str


class PathGuard:
    def __init__(self, workspace: Path) -> None:
        requested_workspace = Path(os.path.abspath(workspace))
        if _is_reparse_point(requested_workspace):
            raise SafetyViolation(
                SafetyCode.REPARSE_POINT_DENIED,
                "reparse points are unavailable to model paths",
            )
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

    def _reject_protected(self, parts: tuple[str, ...]) -> None:
        if any(part.casefold() in _PROTECTED_COMPONENTS for part in parts):
            raise SafetyViolation(
                SafetyCode.PROTECTED_PATH,
                "protected path is unavailable",
            )

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

    def _relative_text(self, absolute: Path) -> str:
        relative = absolute.relative_to(self._workspace)
        return "." if not relative.parts else relative.as_posix()

    def existing_entry(self, raw_path: object) -> GuardedPath:
        parts = self._relative_parts(raw_path)
        self._reject_protected(parts)
        self._reject_reparse_components(parts)
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
        self._reject_protected(parts)
        self._reject_reparse_components(parts)
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

    def new_directory(self, raw_path: object) -> GuardedPath:
        parts = self._relative_parts(raw_path)
        self._reject_protected(parts)
        self._reject_reparse_components(parts)
        if not parts:
            raise SafetyViolation(
                SafetyCode.PATH_TYPE_MISMATCH,
                "new directory path must name a directory",
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
        return GuardedPath(resolved_parent / candidate.name, "/".join(parts))


class CommandSource(StrEnum):
    MODEL = "model"
    USER_VERIFY = "user_verify"
    LOCAL_INTEGRITY = "local_integrity"


@dataclass(frozen=True, slots=True)
class AuthorizedCommand:
    argv: tuple[str, ...]
    normalized_command: str
    purpose: str
    source: CommandSource


ExecutableLocator = Callable[[str], str | None]


def _locate_from_sanitized_path(workspace: Path, name: str) -> str | None:
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
            common = os.path.commonpath((str(workspace), str(resolved)))
        except ValueError:
            common = ""
        inside_workspace = os.path.normcase(common) == os.path.normcase(
            str(workspace)
        )
        if inside_workspace and os.path.normcase(
            str(resolved)
        ) != os.path.normcase(str(runtime_directory)):
            continue
        accepted_entries.append(str(resolved))
    return shutil.which(name, path=os.pathsep.join(accepted_entries))


@dataclass(frozen=True, slots=True)
class JavaRuntime:
    javac: Path
    java: Path


class JavaRuntimePolicy:
    def __init__(
        self,
        workspace: Path,
        *,
        executable_locator: ExecutableLocator | None = None,
    ) -> None:
        self._paths = PathGuard(workspace)
        self._executable_locator = (
            self._locate_from_sanitized_path
            if executable_locator is None
            else executable_locator
        )

    @property
    def workspace(self) -> Path:
        return self._paths.workspace

    def _locate_from_sanitized_path(self, name: str) -> str | None:
        return _locate_from_sanitized_path(self.workspace, name)

    def _trusted(self, name: str) -> Path:
        located = self._executable_locator(name)
        if located is None:
            raise SafetyViolation(
                SafetyCode.EXECUTABLE_DENIED,
                "trusted Java runtime is unavailable",
            )
        try:
            resolved = Path(located).resolve(strict=True)
        except OSError:
            raise SafetyViolation(
                SafetyCode.EXECUTABLE_DENIED,
                "trusted Java runtime is unavailable",
            ) from None
        try:
            common = os.path.commonpath((str(self.workspace), str(resolved)))
        except ValueError:
            common = ""
        if (
            not resolved.is_file()
            or resolved.name.casefold() != name.casefold()
            or os.path.normcase(common)
            == os.path.normcase(str(self.workspace))
        ):
            raise SafetyViolation(
                SafetyCode.EXECUTABLE_DENIED,
                "trusted Java runtime is unavailable",
            )
        return resolved

    def resolve(self) -> JavaRuntime:
        return JavaRuntime(
            javac=self._trusted("javac.exe"),
            java=self._trusted("java.exe"),
        )


class CommandPolicy:
    def __init__(
        self,
        workspace: Path,
        *,
        executable_locator: ExecutableLocator | None = None,
    ) -> None:
        self._paths = PathGuard(workspace)
        self._executable_locator = (
            self._locate_from_sanitized_path
            if executable_locator is None
            else executable_locator
        )

    @property
    def workspace(self) -> Path:
        return self._paths.workspace

    def _current_python(self, executable: str) -> Path | None:
        windows = PureWindowsPath(executable)
        folded = windows.name.casefold()
        current = Path(sys.executable).resolve(strict=True)
        if (
            executable.casefold() in {"python", "python.exe"}
            and folded in {"python", "python.exe"}
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
        try:
            guarded = self._paths.existing_entry(path_text)
        except SafetyViolation as exc:
            raise SafetyViolation(
                SafetyCode.ARGUMENT_DENIED,
                "argument is not allowed",
            ) from exc
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
                try:
                    directory = self._paths.existing_directory(arguments[index + 1])
                except SafetyViolation as exc:
                    raise SafetyViolation(
                        SafetyCode.ARGUMENT_DENIED,
                        "unittest arguments are not allowed",
                    ) from exc
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
                try:
                    guarded = self._paths.existing_entry(value)
                except SafetyViolation as exc:
                    raise SafetyViolation(
                        SafetyCode.ARGUMENT_DENIED,
                        "ruff target is not allowed",
                    ) from exc
                rendered.append(str(guarded.absolute))
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
                try:
                    guarded = self._paths.existing_entry(value)
                except SafetyViolation as exc:
                    raise SafetyViolation(
                        SafetyCode.ARGUMENT_DENIED,
                        "mypy target is not allowed",
                    ) from exc
                if guarded.absolute.is_file() and guarded.absolute.suffix.casefold() not in {".py", ".pyi"}:
                    raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "mypy target is not Python source")
                rendered.append(str(guarded.absolute))
                target_count += 1
        if target_count == 0:
            raise SafetyViolation(SafetyCode.ARGUMENT_DENIED, "mypy requires a workspace target")
        return tuple(rendered)

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

    def _locate_from_sanitized_path(self, name: str) -> str | None:
        return _locate_from_sanitized_path(self.workspace, name)

    def _parse_authorized_input(self, command: object) -> tuple[str, ...]:
        if isinstance(command, str) and any(
            character in command for character in _CONTROL_CHARACTERS
        ):
            raise SafetyViolation(
                SafetyCode.SHELL_SYNTAX_DENIED,
                "shell control syntax is not allowed",
            )
        argv = parse_windows_command_line(command)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[0]):
            raise SafetyViolation(
                SafetyCode.ARGUMENT_DENIED,
                "environment assignment prefixes are not allowed",
            )
        return argv

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
            if supplied.casefold() not in folded_names:
                raise SafetyViolation(SafetyCode.EXECUTABLE_DENIED, "executable is not allowed")
            if len(windows.parts) != 1 or windows.drive or windows.root:
                raise SafetyViolation(SafetyCode.EXECUTABLE_DENIED, "executable is not allowed")
            if allow_runtime:
                for name in sorted(accepted_names):
                    candidates.append(runtime_directory / name)
            locator_names = [supplied, *sorted(accepted_names)]
            seen_locator_names: set[str] = set()
            for name in locator_names:
                folded = name.casefold()
                if folded in seen_locator_names:
                    continue
                seen_locator_names.add(folded)
                located = self._executable_locator(name)
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
        argv = self._parse_authorized_input(command)
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

        executable_name = Path(argv[0]).name.casefold()
        if executable_name in {"ruff", "ruff.exe", "mypy", "mypy.exe"}:
            accepted_names = {
                executable_name.removesuffix(".exe"),
                executable_name.removesuffix(".exe") + ".exe",
            }
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

        raise SafetyViolation(SafetyCode.EXECUTABLE_DENIED, "executable is not allowed")

    def authorize_git_inspection(
        self,
        command: object,
        *,
        source: CommandSource,
    ) -> AuthorizedCommand:
        if not isinstance(source, CommandSource):
            raise ToolArgumentError("source must be model or user_verify")
        argv = self._parse_authorized_input(command)
        executable = self._trusted_launcher(
            argv[0],
            {"git", "git.exe"},
            allow_runtime=False,
        )
        git_arguments = self._authorize_git(argv[1:])
        final = (
            str(executable),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "diff.external=",
            "--no-pager",
            *git_arguments,
        )
        return AuthorizedCommand(
            argv=final,
            normalized_command=subprocess.list2cmdline(final),
            purpose="inspect",
            source=source,
        )

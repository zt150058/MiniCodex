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

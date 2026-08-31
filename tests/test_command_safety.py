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
    JavaRuntimePolicy,
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


def _fake_java_runtime(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace = tmp_path / "workspace"
    runtime = tmp_path / "runtime"
    workspace.mkdir()
    runtime.mkdir()
    javac = runtime / "javac.exe"
    java = runtime / "java.exe"
    javac.write_bytes(b"trusted compiler")
    java.write_bytes(b"trusted runtime")
    return workspace, javac, java


def test_java_runtime_policy_returns_only_resolved_external_executables(
    tmp_path: Path,
) -> None:
    workspace, javac, java = _fake_java_runtime(tmp_path)
    located = {"javac.exe": str(javac), "java.exe": str(java)}
    resolved = JavaRuntimePolicy(
        workspace,
        executable_locator=located.get,
    ).resolve()
    assert resolved.javac == javac.resolve(strict=True)
    assert resolved.java == java.resolve(strict=True)


def test_java_runtime_policy_rejects_workspace_shadow_executables(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for name in ("javac.exe", "java.exe"):
        (workspace / name).write_bytes(b"shadow")
    located = {
        "javac.exe": str(workspace / "javac.exe"),
        "java.exe": str(workspace / "java.exe"),
    }
    with pytest.raises(SafetyViolation) as caught:
        JavaRuntimePolicy(workspace, executable_locator=located.get).resolve()
    assert caught.value.code is SafetyCode.EXECUTABLE_DENIED


@pytest.mark.parametrize("missing", ["javac.exe", "java.exe"])
def test_java_runtime_policy_rejects_missing_runtime_component(
    tmp_path: Path,
    missing: str,
) -> None:
    workspace, javac, java = _fake_java_runtime(tmp_path)
    located: dict[str, str | None] = {
        "javac.exe": str(javac),
        "java.exe": str(java),
    }
    located[missing] = None
    with pytest.raises(SafetyViolation) as caught:
        JavaRuntimePolicy(workspace, executable_locator=located.get).resolve()
    assert caught.value.code is SafetyCode.EXECUTABLE_DENIED
    assert caught.value.public_message == "trusted Java runtime is unavailable"


def test_model_command_policy_still_rejects_java_strings(tmp_path: Path) -> None:
    for command in ("java.exe Main", "javac.exe src\\Main.java"):
        with pytest.raises(SafetyViolation) as caught:
            CommandPolicy(tmp_path).authorize(
                command,
                purpose="test",
                source=CommandSource.MODEL,
            )
        assert caught.value.code is SafetyCode.EXECUTABLE_DENIED


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
    assert CommandSource.LOCAL_INTEGRITY.value == "local_integrity"


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


def _git_locator(trusted: Path) -> Callable[[str], str | None]:
    launcher = trusted / "git.exe"
    launcher.write_bytes(b"test launcher")
    return lambda name: str(launcher) if name.casefold() in {"git", "git.exe"} else None


@pytest.mark.parametrize(
    "command",
    [
        "git status --short",
        "git diff -- README.md",
        "git log -n 3",
        "git show HEAD -- README.md",
        "git ls-files -- README.md",
    ],
)
def test_authorize_git_inspection_accepts_existing_read_only_grammar(
    tmp_path: Path,
    command: str,
) -> None:
    trusted = tmp_path.parent / f"{tmp_path.name}-git-inspection"
    trusted.mkdir()
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    policy = CommandPolicy(tmp_path, executable_locator=_git_locator(trusted))

    authorized = policy.authorize_git_inspection(
        command,
        source=CommandSource.MODEL,
    )

    assert authorized.purpose == "inspect"
    assert authorized.source is CommandSource.MODEL
    assert Path(authorized.argv[0]).name.casefold() in {"git", "git.exe"}


@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest",
        "pytest -q",
        "java Main",
        "powershell -Command Get-ChildItem",
        "cmd /c dir",
        "bash -c ls",
        "git add .",
        "git commit -m x",
        "git push",
        "git status && whoami",
        'git status "',
    ],
)
def test_authorize_git_inspection_rejects_non_inspection_commands(
    tmp_path: Path,
    command: str,
) -> None:
    trusted = tmp_path.parent / f"{tmp_path.name}-git-inspection-rejected"
    trusted.mkdir()
    policy = CommandPolicy(tmp_path, executable_locator=_git_locator(trusted))

    with pytest.raises((SafetyViolation, ToolArgumentError)):
        policy.authorize_git_inspection(command, source=CommandSource.MODEL)


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

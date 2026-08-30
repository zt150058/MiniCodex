from __future__ import annotations

import os
from io import StringIO
from pathlib import Path
import subprocess
import sys
import tomllib
from typing import TextIO

import pytest

from coding_agent.cli import build_parser, main
from coding_agent.config import ApiMode, ConfigError, RunConfig, load_run_config
from coding_agent.run_mode import RunMode
from coding_agent.safety import (
    AuthorizedCommand,
    CommandSource,
    SafetyCode,
    SafetyViolation,
)


SECRET_SENTINEL = "do-not-print-this-test-value"
CHAT_SECRET_SENTINEL = "chat-key-must-never-be-printed"


def valid_environ() -> dict[str, str]:
    return {
        "OPENAI_MODEL": "env-model",
        "OPENAI_API_KEY": SECRET_SENTINEL,
    }


def valid_chat_environ() -> dict[str, str]:
    return {
        "OPENAI_MODEL": "chat-model",
        "CHAT_COMPLETIONS_API_KEY": CHAT_SECRET_SENTINEL,
    }


def test_config_defaults_to_modify(tmp_path: Path) -> None:
    config = load_run_config(
        task="inspect",
        workspace=tmp_path,
        model=None,
        verify_command=None,
        environ=valid_environ(),
    )

    assert config.run_mode is RunMode.MODIFY


def test_config_accepts_read_only(tmp_path: Path) -> None:
    config = load_run_config(
        task="inspect",
        workspace=tmp_path,
        model=None,
        verify_command=None,
        environ=valid_environ(),
        run_mode=RunMode.READ_ONLY,
    )

    assert config.run_mode is RunMode.READ_ONLY


@pytest.mark.parametrize("value", ["auto", "READ_ONLY", "", 1, True, None])
def test_config_rejects_invalid_run_mode(tmp_path: Path, value: object) -> None:
    with pytest.raises(ConfigError, match="run mode"):
        load_run_config(
            task="inspect",
            workspace=tmp_path,
            model=None,
            verify_command=None,
            environ=valid_environ(),
            run_mode=value,  # type: ignore[arg-type]
        )


def test_help_describes_local_agent_execution_and_verification() -> None:
    help_text = " ".join(build_parser().format_help().split())

    assert "Run a one-shot local coding agent" in help_text
    assert "read and modify workspace files and run authorized commands" in help_text
    assert "User-specified required final verification command" in help_text
    assert "--api-mode" in help_text
    assert "--base-url" in help_text
    assert "responses" in help_text
    assert "chat-completions" in help_text
    assert "--read-only" in help_text
    assert (
        "Inspect and answer without file mutation or verification tools"
        in help_text
    )
    for stale_text in (
        "Validate configuration",
        "Task to validate",
        "executed by Task 11",
        "Task 1",
        "Task1",
    ):
        assert stale_text not in help_text


def test_cli_read_only_flag_maps_to_config(tmp_path: Path) -> None:
    captured: list[RunConfig] = []

    exit_code = main(
        ["inspect", "--workspace", str(tmp_path), "--read-only"],
        environ=valid_environ(),
        application=lambda config, **streams: captured.append(config) or 0,
    )

    assert exit_code == 0
    assert captured[0].run_mode is RunMode.READ_ONLY


def test_cli_without_read_only_flag_remains_modify(tmp_path: Path) -> None:
    captured: list[RunConfig] = []

    exit_code = main(
        ["change", "--workspace", str(tmp_path)],
        environ=valid_environ(),
        application=lambda config, **streams: captured.append(config) or 0,
    )

    assert exit_code == 0
    assert captured[0].run_mode is RunMode.MODIFY


def test_cli_read_only_with_verify_exits_two_before_application(
    tmp_path: Path,
) -> None:
    called = False

    def application(*args: object, **kwargs: object) -> int:
        nonlocal called
        del args, kwargs
        called = True
        return 0

    stderr = StringIO()
    exit_code = main(
        [
            "inspect",
            "--workspace",
            str(tmp_path),
            "--read-only",
            "--verify",
            "pytest -q",
        ],
        environ=valid_environ(),
        application=application,
        stderr=stderr,
    )

    assert exit_code == 2
    assert called is False
    assert stderr.getvalue() == (
        "error: --read-only cannot be combined with --verify\n"
    )


def test_config_normalizes_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = load_run_config(
        task="  inspect the project  ",
        workspace=workspace / ".",
        model=None,
        verify_command="  pytest -q  ",
        environ=valid_environ(),
    )

    assert config.task == "inspect the project"
    assert config.workspace == workspace.resolve()
    assert config.model == "env-model"
    assert config.api_key == SECRET_SENTINEL
    assert isinstance(config.verify_command, AuthorizedCommand)
    assert config.verify_command.purpose == "verification"
    assert config.verify_command.source is CommandSource.USER_VERIFY
    assert config.verify_command.argv[-1] == "-q"


def test_responses_mode_is_backward_compatible_default(tmp_path: Path) -> None:
    config = load_run_config(
        task="inspect",
        workspace=tmp_path,
        model=None,
        verify_command=None,
        environ=valid_environ(),
    )

    assert config.api_mode is ApiMode.RESPONSES
    assert config.base_url is None
    assert config.api_key == SECRET_SENTINEL


def test_chat_mode_uses_only_chat_credential_and_normalizes_base_url(
    tmp_path: Path,
) -> None:
    environment = valid_chat_environ()
    environment["OPENAI_API_KEY"] = "wrong-responses-key"

    config = load_run_config(
        task="inspect",
        workspace=tmp_path,
        model=None,
        verify_command=None,
        api_mode="chat-completions",
        base_url="  https://provider.example/api/maas/v1  ",
        environ=environment,
    )

    assert config.api_mode is ApiMode.CHAT_COMPLETIONS
    assert config.base_url == "https://provider.example/api/maas/v1/"
    assert config.api_key == CHAT_SECRET_SENTINEL
    assert "wrong-responses-key" not in repr(config)
    assert CHAT_SECRET_SENTINEL not in repr(config)
    assert "provider.example" not in repr(config)


@pytest.mark.parametrize(
    ("api_mode", "base_url", "message"),
    [
        (
            "unknown",
            None,
            "api mode must be one of: responses, chat-completions",
        ),
        (
            "responses",
            "https://provider.example/v1",
            "--base-url is not allowed with responses",
        ),
        (
            "chat-completions",
            None,
            "--base-url is required with chat-completions",
        ),
        (
            "chat-completions",
            "   ",
            "--base-url is required with chat-completions",
        ),
        (
            "chat-completions",
            "http://provider.example/v1",
            "--base-url must be an absolute HTTPS URL",
        ),
        (
            "chat-completions",
            "provider.example/v1",
            "--base-url must be an absolute HTTPS URL",
        ),
        (
            "chat-completions",
            "https:///api/v1",
            "--base-url must be an absolute HTTPS URL",
        ),
        (
            "chat-completions",
            "https://user:pass@provider.example/v1",
            "--base-url must be an absolute HTTPS URL",
        ),
        (
            "chat-completions",
            "https://provider.example/v1?region=x",
            "--base-url must be an absolute HTTPS URL",
        ),
        (
            "chat-completions",
            "https://provider.example/v1#section",
            "--base-url must be an absolute HTTPS URL",
        ),
        (
            "chat-completions",
            "\x00https://provider.example/v1",
            "--base-url must be an absolute HTTPS URL",
        ),
        (
            "chat-completions",
            "\thttps://provider.example/v1",
            "--base-url must be an absolute HTTPS URL",
        ),
        (
            "chat-completions",
            "https://provider.example/v1\tbad",
            "--base-url must be an absolute HTTPS URL",
        ),
        (
            "chat-completions",
            "https://provider.example/v1\u00a0bad",
            "--base-url must be an absolute HTTPS URL",
        ),
        (
            "chat-completions",
            "\x7fhttps://provider.example/v1",
            "--base-url must be an absolute HTTPS URL",
        ),
        (
            "chat-completions",
            r"https://provider.example/v1\bad",
            "--base-url must be an absolute HTTPS URL",
        ),
        (
            "chat-completions",
            "https://provider.example:invalid/v1",
            "--base-url must be an absolute HTTPS URL",
        ),
        (
            "chat-completions",
            42,
            "--base-url must be an absolute HTTPS URL",
        ),
    ],
)
def test_config_rejects_invalid_mode_url_combinations_before_credentials(
    tmp_path: Path,
    api_mode: str,
    base_url: object | None,
    message: str,
) -> None:
    with pytest.raises(ConfigError, match=message) as caught:
        load_run_config(
            task="inspect",
            workspace=tmp_path / "missing",
            model=None,
            verify_command=None,
            api_mode=api_mode,
            base_url=base_url,  # type: ignore[arg-type]
            environ={},
        )

    rendered = str(caught.value)
    assert "provider.example" not in rendered
    assert SECRET_SENTINEL not in rendered


@pytest.mark.parametrize(
    ("api_mode", "base_url", "environment", "missing_name"),
    [
        (
            "responses",
            None,
            {
                "OPENAI_MODEL": "model",
                "CHAT_COMPLETIONS_API_KEY": CHAT_SECRET_SENTINEL,
            },
            "OPENAI_API_KEY",
        ),
        (
            "chat-completions",
            "https://provider.example/v1",
            {
                "OPENAI_MODEL": "model",
                "OPENAI_API_KEY": SECRET_SENTINEL,
            },
            "CHAT_COMPLETIONS_API_KEY",
        ),
    ],
)
def test_mode_credentials_never_fall_back(
    tmp_path: Path,
    api_mode: str,
    base_url: str | None,
    environment: dict[str, str],
    missing_name: str,
) -> None:
    with pytest.raises(ConfigError, match=missing_name):
        load_run_config(
            task="inspect",
            workspace=tmp_path,
            model=None,
            verify_command=None,
            api_mode=api_mode,
            base_url=base_url,
            environ=environment,
        )


def test_run_config_rejects_programmatic_responses_base_url(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ConfigError,
        match="--base-url is not allowed with responses",
    ):
        RunConfig(
            task="inspect",
            workspace=tmp_path,
            model="model",
            api_key=SECRET_SENTINEL,
            api_mode=ApiMode.RESPONSES,
            base_url="https://provider.example/v1",
        )


def test_run_config_rejects_programmatic_chat_without_base_url(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ConfigError,
        match="--base-url is required with chat-completions",
    ):
        RunConfig(
            task="inspect",
            workspace=tmp_path,
            model="model",
            api_key=CHAT_SECRET_SENTINEL,
            api_mode=ApiMode.CHAT_COMPLETIONS,
        )


def test_config_cli_model_overrides_environment(tmp_path: Path) -> None:
    config = load_run_config(
        task="inspect",
        workspace=tmp_path,
        model="  cli-model  ",
        verify_command=None,
        environ=valid_environ(),
    )

    assert config.model == "cli-model"


def test_config_uses_environment_model(tmp_path: Path) -> None:
    config = load_run_config(
        task="inspect",
        workspace=tmp_path,
        model=None,
        verify_command=None,
        environ=valid_environ(),
    )

    assert config.model == "env-model"


def test_config_rejects_empty_task(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="task must not be empty"):
        load_run_config(
            task="   ",
            workspace=tmp_path,
            model=None,
            verify_command=None,
            environ=valid_environ(),
        )


def test_config_rejects_missing_workspace(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(ConfigError, match="workspace does not exist"):
        load_run_config(
            task="inspect",
            workspace=missing,
            model=None,
            verify_command=None,
            environ=valid_environ(),
        )


def test_config_rejects_workspace_file(tmp_path: Path) -> None:
    workspace_file = tmp_path / "file.txt"
    workspace_file.write_text("content", encoding="utf-8")

    with pytest.raises(ConfigError, match="workspace must be a directory"):
        load_run_config(
            task="inspect",
            workspace=workspace_file,
            model=None,
            verify_command=None,
            environ=valid_environ(),
        )


def test_config_rejects_missing_model(tmp_path: Path) -> None:
    environ = {"OPENAI_API_KEY": SECRET_SENTINEL}

    with pytest.raises(ConfigError, match="OPENAI_MODEL"):
        load_run_config(
            task="inspect",
            workspace=tmp_path,
            model=None,
            verify_command=None,
            environ=environ,
        )


def test_config_rejects_missing_api_key(tmp_path: Path) -> None:
    environ = {"OPENAI_MODEL": "env-model"}

    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        load_run_config(
            task="inspect",
            workspace=tmp_path,
            model=None,
            verify_command=None,
            environ=environ,
        )


def test_config_rejects_empty_verify(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="--verify must not be empty"):
        load_run_config(
            task="inspect",
            workspace=tmp_path,
            model=None,
            verify_command="   ",
            environ=valid_environ(),
        )


def test_run_config_repr_hides_secret(tmp_path: Path) -> None:
    config = load_run_config(
        task="inspect",
        workspace=tmp_path,
        model=None,
        verify_command=None,
        environ=valid_environ(),
    )

    assert SECRET_SENTINEL not in repr(config)
    assert "api_key=" not in repr(config)


def test_cli_accepts_valid_arguments(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    received: list[RunConfig] = []

    def application(
        config: RunConfig,
        *,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int:
        received.append(config)
        return 0

    exit_code = main(
        [
            "inspect the project",
            "--workspace",
            str(tmp_path),
            "--verify",
            "pytest -q",
            "--model",
            "cli-model",
        ],
        environ={"OPENAI_API_KEY": SECRET_SENTINEL},
        application=application,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert len(received) == 1
    assert received[0].task == "inspect the project"
    assert captured.err == ""
    assert captured.out == ""
    assert SECRET_SENTINEL not in captured.out


def test_cli_accepts_explicit_chat_configuration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    received: list[RunConfig] = []

    def application(
        config: RunConfig,
        *,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int:
        received.append(config)
        return 0

    code = main(
        [
            "inspect",
            "--workspace",
            str(tmp_path),
            "--api-mode",
            "chat-completions",
            "--base-url",
            "https://provider.example/api/v1",
            "--model",
            "chat-model",
        ],
        environ={"CHAT_COMPLETIONS_API_KEY": CHAT_SECRET_SENTINEL},
        application=application,
    )

    captured = capsys.readouterr()
    assert code == 0
    assert len(received) == 1
    assert received[0].api_mode is ApiMode.CHAT_COMPLETIONS
    assert received[0].base_url == "https://provider.example/api/v1/"
    assert received[0].api_key == CHAT_SECRET_SENTINEL
    assert CHAT_SECRET_SENTINEL not in captured.out + captured.err


def test_responses_base_url_exits_two_before_application(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden_application(
        config: RunConfig,
        *,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int:
        raise AssertionError("application must not run")

    code = main(
        [
            "inspect",
            "--workspace",
            str(tmp_path),
            "--api-mode",
            "responses",
            "--base-url",
            "https://provider.example/v1",
        ],
        environ=valid_environ(),
        application=forbidden_application,
    )

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err == "error: --base-url is not allowed with responses\n"
    assert SECRET_SENTINEL not in captured.err


def test_cli_rejects_unknown_api_mode(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        main(
            [
                "inspect",
                "--workspace",
                str(tmp_path),
                "--api-mode",
                "unknown",
            ],
            environ=valid_environ(),
        )

    assert caught.value.code == 2


def test_cli_missing_task_exits_two(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(
            ["--workspace", str(tmp_path)],
            environ=valid_environ(),
        )

    assert exc_info.value.code == 2


def test_cli_invalid_workspace_exits_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        ["inspect", "--workspace", str(tmp_path / "missing")],
        environ=valid_environ(),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "workspace does not exist" in captured.err


def test_cli_missing_model_exits_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        ["inspect", "--workspace", str(tmp_path)],
        environ={"OPENAI_API_KEY": SECRET_SENTINEL},
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "OPENAI_MODEL" in captured.err


def test_cli_empty_verify_exits_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        ["inspect", "--workspace", str(tmp_path), "--verify", "   "],
        environ=valid_environ(),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--verify must not be empty" in captured.err


def test_cli_error_does_not_print_secret(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        ["inspect", "--workspace", str(tmp_path / "missing")],
        environ=valid_environ(),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert SECRET_SENTINEL not in captured.out
    assert SECRET_SENTINEL not in captured.err


def test_dependency_declarations_are_limited_to_approved_packages() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["requires-python"] == ">=3.11"
    assert metadata["project"]["dependencies"] == ["openai", "fastapi", "uvicorn"]
    assert metadata["project"]["optional-dependencies"]["test"] == ["pytest", "httpx"]
    assert metadata["build-system"]["requires"] == ["setuptools>=68"]
    assert metadata["build-system"]["build-backend"] == "setuptools.build_meta"


def test_console_scripts_and_web_assets_use_approved_entrypoints() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["scripts"] == {
        "coding-agent": "coding_agent.cli:entrypoint",
        "coding-agent-web": "coding_agent.web_cli:entrypoint",
    }
    assert metadata["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]
    assert metadata["tool"]["setuptools"]["package-data"] == {
        "coding_agent": ["web_static/*.html", "web_static/*.css", "web_static/*.js"]
    }


def test_gitignore_covers_runtime_and_local_credentials() -> None:
    ignored = set(Path(".gitignore").read_text(encoding="utf-8").splitlines())

    assert {
        ".venv/",
        ".coding-agent/",
        ".env",
        ".env.*",
        "*.local.toml",
        "*.local.json",
        "__pycache__/",
        "*.egg-info/",
        ".pytest_cache/",
    }.issubset(ignored)


def test_standard_console_command_rejects_missing_key_before_app(
    tmp_path: Path,
) -> None:
    launcher = Path(sys.executable).with_name("coding-agent.exe")
    assert launcher.is_file()

    environ = os.environ.copy()
    environ.pop("OPENAI_API_KEY", None)
    environ["OPENAI_MODEL"] = "env-model"
    completed = subprocess.run(
        [str(launcher), "inspect", "--workspace", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environ,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "OPENAI_API_KEY is not configured" in completed.stderr
    assert "coding_agent.app" not in completed.stderr
    assert SECRET_SENTINEL not in completed.stdout
    assert SECRET_SENTINEL not in completed.stderr


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
    received: list[RunConfig] = []

    def application(
        config: RunConfig,
        *,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int:
        received.append(config)
        return 0

    exit_code = main(
        ["inspect", "--workspace", str(tmp_path), "--verify", verify],
        environ=valid_environ(),
        application=application,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert len(received) == 1
    assert received[0].verify_command is not None
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
    assert config.verify_command is not None
    assert config.verify_command.normalized_command not in rendered
    assert "verify_command=" not in rendered
    assert SECRET_SENTINEL not in rendered


def test_config_rejects_noncredible_user_verify_without_echoing_it(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigError) as caught:
        load_run_config(
            task="inspect",
            workspace=tmp_path,
            model="gpt-test",
            verify_command="git status --short",
            environ={"OPENAI_API_KEY": "secret-sentinel"},
        )

    assert str(caught.value) == (
        "--verify rejected (verification_not_credible): "
        "command is not a credible verification command"
    )
    assert "git status" not in str(caught.value)
    assert "secret-sentinel" not in str(caught.value)


def test_cli_delegates_one_validated_config_to_application(tmp_path: Path) -> None:
    calls: list[RunConfig] = []
    expected_stdout = StringIO()
    expected_stderr = StringIO()

    def application(
        config: RunConfig,
        *,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int:
        assert stdout is expected_stdout
        assert stderr is expected_stderr
        calls.append(config)
        return 17

    code = main(
        [
            " repair ",
            "--workspace",
            str(tmp_path),
            "--verify",
            "pytest -q",
        ],
        environ={
            "OPENAI_MODEL": "fake-model",
            "OPENAI_API_KEY": SECRET_SENTINEL,
        },
        stdout=expected_stdout,
        stderr=expected_stderr,
        application=application,
    )

    assert code == 17
    assert len(calls) == 1
    assert calls[0].task == "repair"
    assert calls[0].verify_command is not None
    assert expected_stdout.getvalue() == ""
    assert expected_stderr.getvalue() == ""

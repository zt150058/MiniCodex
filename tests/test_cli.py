from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from coding_agent.cli import main
from coding_agent.config import ConfigError, RunConfig, load_run_config


SECRET_SENTINEL = "do-not-print-this-test-value"


def valid_environ() -> dict[str, str]:
    return {
        "OPENAI_MODEL": "env-model",
        "OPENAI_API_KEY": SECRET_SENTINEL,
    }


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

    assert config == RunConfig(
        task="inspect the project",
        workspace=workspace.resolve(),
        model="env-model",
        api_key=SECRET_SENTINEL,
        verify_command="pytest -q",
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
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == (
        "Configuration valid. Agent execution is not implemented in task 1.\n"
    )
    assert captured.err == ""
    assert SECRET_SENTINEL not in captured.out


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
    assert metadata["project"]["dependencies"] == ["openai"]
    assert metadata["project"]["optional-dependencies"]["test"] == ["pytest"]
    assert metadata["build-system"]["requires"] == ["setuptools>=68"]
    assert metadata["build-system"]["build-backend"] == "setuptools.build_meta"


def test_console_script_points_to_task_one_entrypoint() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["scripts"] == {
        "coding-agent": "coding_agent.cli:entrypoint"
    }
    assert metadata["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]


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


def test_standard_console_command_runs(tmp_path: Path) -> None:
    launcher = Path(sys.executable).with_name("coding-agent.exe")
    assert launcher.is_file()

    environ = os.environ.copy()
    environ.update(valid_environ())
    completed = subprocess.run(
        [str(launcher), "inspect", "--workspace", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environ,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == (
        "Configuration valid. Agent execution is not implemented in task 1.\n"
    )
    assert completed.stderr == ""
    assert SECRET_SENTINEL not in completed.stdout
    assert SECRET_SENTINEL not in completed.stderr

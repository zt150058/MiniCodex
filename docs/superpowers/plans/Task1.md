# Task 1: Project Scaffold and Minimal CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan one task at a time, but only after the user explicitly approves this plan.

**Goal:** Complete only `TASKS.md` task 1 by creating an installable Python 3.11+ package, a pytest layout, configuration parsing, and a one-shot CLI that validates its inputs but does not run an Agent.

**Architecture:** Keep task 1 to two small runtime modules. `cli.py` owns `argparse`, exit-code mapping, and the console entry point; `config.py` owns environment lookup, input normalization, workspace validation, and the immutable `RunConfig`. No Agent-facing abstraction is introduced in this task.

**Tech Stack:** Windows PowerShell, Python 3.11+, standard library (`argparse`, `dataclasses`, `os`, `pathlib`, `typing`), `setuptools` as the build backend, official `openai` as the sole application dependency, and `pytest` as the sole test dependency.

---

## Approval and execution rules

- This document is a plan only. Creating it does not authorize implementation.
- Do not execute any step below until the user explicitly approves this task-1 plan.
- During execution, use `superpowers:test-driven-development` for every behavior slice.
- Before claiming task 1 is complete, use `superpowers:verification-before-completion`.
- Do not use subagents, parallel agents, Git worktrees, remote operations, or automatic commits.
- Keep task 1 marked `进行中` while it is awaiting user review. Change it to `已完成` only after the user accepts the implementation evidence.
- If any step requires behavior that conflicts with `DESIGN.md`, stop and return to brainstorming instead of changing the architecture.

## Scope boundary

### Files task 1 may create

- `pyproject.toml`
- `.gitignore`
- `src/coding_agent/__init__.py`
- `src/coding_agent/config.py`
- `src/coding_agent/cli.py`
- `tests/test_cli.py`

### Administrative file task 1 may modify

- `TASKS.md`, and only the **当前状态** field of task 1.

### Explicitly excluded behavior

- Message data structures
- `ModelClient` or `FakeModelClient`
- Agent state or the Agent loop
- File tools or directory tools
- Shell execution or command safety policy
- OpenAI API calls or SDK adapter code
- Context management or compaction
- Verification execution or the final verification gate
- Logging, reports, sessions, multi-agent behavior, or a Planner

`--verify` is only parsed, trimmed, and stored in `RunConfig` here. Task 1 rejects an explicitly supplied empty value, but does not parse, authorize, or execute the command; that work remains in tasks 7, 8, and 11.

## Exact task-1 interfaces

`src/coding_agent/config.py` will expose:

```python
class ConfigError(ValueError): ...

@dataclass(frozen=True, slots=True)
class RunConfig:
    task: str
    workspace: Path
    model: str
    api_key: str = field(repr=False)
    verify_command: str | None = None

def load_run_config(
    *,
    task: str,
    workspace: str | Path,
    model: str | None,
    verify_command: str | None,
    environ: Mapping[str, str] | None = None,
) -> RunConfig: ...
```

`src/coding_agent/cli.py` will expose:

```python
def build_parser() -> argparse.ArgumentParser: ...

def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int: ...

def entrypoint() -> NoReturn: ...
```

For a valid task-1 invocation, `main()` prints exactly:

```text
Configuration valid. Agent execution is not implemented in task 1.
```

and returns `0`. This means only that parsing and configuration validation succeeded; it does not claim that the requested coding task ran. Argument or configuration failures exit with code `2`. The CLI never prints the task configuration, model value, environment mapping, or API key.

## Acceptance matrix

| Task-1 acceptance criterion | Test or check that proves it |
| --- | --- |
| Package runs through its defined standard command | `test_standard_console_command_runs` invokes the installed `coding-agent.exe` |
| Missing task exits `2` with a clear error | `test_cli_missing_task_exits_two` |
| Invalid workspace exits `2` with a clear error | `test_cli_invalid_workspace_exits_two` and configuration tests |
| Missing model exits `2` with a clear error | `test_cli_missing_model_exits_two` |
| Explicitly empty `--verify` exits `2` | `test_cli_empty_verify_exits_two` and `test_config_rejects_empty_verify` |
| CLI model overrides `OPENAI_MODEL` | `test_config_cli_model_overrides_environment` |
| `OPENAI_MODEL` fallback works | `test_config_uses_environment_model` |
| `OPENAI_API_KEY` is read but not printed | `test_run_config_repr_hides_secret` and `test_cli_error_does_not_print_secret` |
| Workspace is normalized and must exist as a directory | `test_config_normalizes_workspace`, `test_config_rejects_missing_workspace`, and `test_config_rejects_workspace_file` |
| `.coding-agent/` and local credentials are ignored | `test_gitignore_covers_runtime_and_local_credentials` |
| Only approved application and test dependencies are declared | `test_dependency_declarations_are_limited_to_approved_packages` plus the final metadata check |

---

## Step 0: Record the implementation start without changing behavior

**Files:** Modify only `TASKS.md`, changing task 1's status from `未开始` to `进行中`. No source or test file is created in this step.

**Interface or data structure:** None.

**Exact edit:** In section `## 1. 项目骨架与最小 CLI`, replace only:

```markdown
**当前状态**

`未开始`
```

with:

```markdown
**当前状态**

`进行中`
```

**Command:**

```powershell
git diff -- TASKS.md
```

**Expected result:** The diff contains one status-line change in task 1 and no change to any requirement, architecture decision, later task, or acceptance criterion.

**Acceptance criterion:** `AGENTS.md` requires one active task and accurate task status. If Git is unavailable, inspect the same file directly and report that the Git check could not run.

---

## Step 1: Write the failing configuration tests

**Files:** Create `tests/test_cli.py`. Do not create `src/`, `pyproject.toml`, or `.gitignore` yet.

**Interface under test:** `ConfigError`, `RunConfig`, and `load_run_config(...)` exactly as declared above.

**Test code:**

```python
from __future__ import annotations

from pathlib import Path

import pytest

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
```

**Command:** No test is run until Step 2; the red test file must exist before the runtime package exists.

**Expected result:** Static review shows every task-1 configuration success and failure path has an explicit assertion. The import is intentionally unresolved at this point.

**Acceptance criterion:** Covers model precedence, environment reads, workspace normalization, missing/non-directory workspace, empty task, empty verification command, and secret-safe representation.

---

## Step 2: Run the configuration tests and confirm the expected failure

**Files:** Create only the ignored local virtual environment directory `.venv/`; do not create repository source files.

**Interface or data structure:** No new interface. This step proves the test is red for the missing task-1 implementation.

**Commands:** Run from the repository root in PowerShell after implementation approval:

```powershell
py -3.11 --version
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install pytest
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
Remove-Item Env:PYTHONPATH
```

Dependency installation requires the normal user/sandbox authorization at execution time. If `py -3.11` is unavailable, stop and ask the user which Python 3.11+ executable to use; do not silently change the supported version.

**Expected result:** The pytest command exits nonzero during collection with `ModuleNotFoundError: No module named 'coding_agent'`. Failure because pytest itself is absent, because Python is older than 3.11, or because of a test syntax error is not the expected red state and must be diagnosed before continuing.

**Acceptance criterion:** The failing test demonstrates that the configuration package has not yet been implemented, for the expected reason.

---

## Step 3: Implement the minimum configuration package

**Files:** Create `src/coding_agent/__init__.py` and `src/coding_agent/config.py`.

**Interfaces and data structures:** Implement exactly `ConfigError`, `RunConfig`, and `load_run_config(...)`. Do not import `openai`, create an API client, or add Agent behavior.

**`src/coding_agent/__init__.py`:**

```python
"""Local coding agent package."""
```

**`src/coding_agent/config.py`:**

```python
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Mapping


class ConfigError(ValueError):
    """Raised when task-1 CLI configuration is invalid."""


@dataclass(frozen=True, slots=True)
class RunConfig:
    task: str
    workspace: Path
    model: str
    api_key: str = field(repr=False)
    verify_command: str | None = None


def load_run_config(
    *,
    task: str,
    workspace: str | Path,
    model: str | None,
    verify_command: str | None,
    environ: Mapping[str, str] | None = None,
) -> RunConfig:
    source = os.environ if environ is None else environ

    normalized_task = task.strip()
    if not normalized_task:
        raise ConfigError("task must not be empty")

    workspace_path = Path(workspace).expanduser()
    try:
        normalized_workspace = workspace_path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ConfigError(f"workspace does not exist: {workspace_path}") from exc
    if not normalized_workspace.is_dir():
        raise ConfigError(f"workspace must be a directory: {workspace_path}")

    selected_model = model if model is not None else source.get("OPENAI_MODEL", "")
    normalized_model = selected_model.strip()
    if not normalized_model:
        raise ConfigError("model is not configured; pass --model or set OPENAI_MODEL")

    normalized_api_key = source.get("OPENAI_API_KEY", "").strip()
    if not normalized_api_key:
        raise ConfigError("OPENAI_API_KEY is not configured")

    normalized_verify: str | None = None
    if verify_command is not None:
        normalized_verify = verify_command.strip()
        if not normalized_verify:
            raise ConfigError("--verify must not be empty")

    return RunConfig(
        task=normalized_task,
        workspace=normalized_workspace,
        model=normalized_model,
        api_key=normalized_api_key,
        verify_command=normalized_verify,
    )
```

**Command:** No test command in this edit step; run the focused suite immediately in Step 4.

**Expected result:** The implementation contains only standard-library configuration logic and no output of configuration values.

**Acceptance criterion:** This is the minimum implementation needed for all Step 1 assertions, with the API key excluded from `RunConfig.__repr__`.

---

## Step 4: Re-run the configuration tests and confirm green

**Files:** No file changes.

**Interface or data structure:** Verifies `ConfigError`, `RunConfig`, and `load_run_config(...)` without extending them.

**Command:**

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
Remove-Item Env:PYTHONPATH
```

**Expected result:** Exit code `0`; exactly `10 passed` and no warnings or collection errors.

**Acceptance criterion:** The complete configuration slice is green before CLI behavior is added.

---

## Step 5: Add failing tests for the one-shot CLI

**Files:** Modify `tests/test_cli.py` only.

**Interfaces under test:** `build_parser()`, `main(argv, *, environ)`, and `entrypoint()` from `coding_agent.cli`.

**Exact import additions near the top of `tests/test_cli.py`:**

```python
from coding_agent.cli import main
```

**Exact tests to append:**

```python
def test_cli_accepts_valid_arguments(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
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
```

**Command:** No test is run until Step 6. The new import intentionally references a module that does not yet exist.

**Expected result:** Static review confirms the success path, all required exit-2 paths, and secret-safe error output are asserted without invoking an Agent.

**Acceptance criterion:** Covers the task-1 CLI success and failure requirements while leaving command safety and execution out of scope.

---

## Step 6: Run the CLI tests and confirm the expected failure

**Files:** No file changes.

**Interface or data structure:** No new interface. This proves `coding_agent.cli` is missing.

**Command:**

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
Remove-Item Env:PYTHONPATH
```

**Expected result:** The command exits nonzero during collection with `ModuleNotFoundError: No module named 'coding_agent.cli'`. A different failure must be resolved before implementation.

**Acceptance criterion:** The CLI test slice is demonstrably red for the expected missing-module reason.

---

## Step 7: Implement the minimum CLI

**Files:** Create `src/coding_agent/cli.py` only.

**Interfaces:** Implement exactly `build_parser()`, `main(...)`, and `entrypoint()`. `main()` validates configuration, prints a fixed non-secret task-1 message on success, maps `ConfigError` to exit code `2`, and does not import any later-task module.

**Implementation code:**

```python
from __future__ import annotations

import argparse
import sys
from typing import Mapping, NoReturn, Sequence

from coding_agent.config import ConfigError, load_run_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coding-agent",
        description="Validate configuration for a one-shot local coding-agent task.",
    )
    parser.add_argument("task", help="One-shot coding task to validate")
    parser.add_argument(
        "--workspace",
        required=True,
        help="Existing workspace directory",
    )
    parser.add_argument(
        "--verify",
        default=None,
        help="Optional final verification command; execution is added later",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model; overrides OPENAI_MODEL",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_run_config(
            task=args.task,
            workspace=args.workspace,
            model=args.model,
            verify_command=args.verify,
            environ=environ,
        )
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print("Configuration valid. Agent execution is not implemented in task 1.")
    return 0


def entrypoint() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
```

**Command:** No test command in this edit step; run it immediately in Step 8.

**Expected result:** The module contains no Agent runner, model client, tool, API request, context, or verification logic.

**Acceptance criterion:** Minimal one-shot argument parsing and exit-code behavior are implemented without crossing the task-1 boundary.

---

## Step 8: Re-run all configuration and CLI tests

**Files:** No file changes.

**Interfaces:** Verifies `config.py` and `cli.py` together.

**Command:**

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
Remove-Item Env:PYTHONPATH
```

**Expected result:** Exit code `0`; exactly `16 passed`.

**Acceptance criterion:** Both red—green slices pass together before package metadata is introduced.

---

## Step 9: Add failing package and ignore-rule tests

**Files:** Modify `tests/test_cli.py` only.

**Interfaces and data structures:** The package metadata must define the `coding-agent` console entry point, Python 3.11+, approved dependencies, and `src/` package discovery. `.gitignore` must cover runtime logs, virtual environments, caches, and local credential files.

**Exact import additions near the top of `tests/test_cli.py`:**

```python
import os
import subprocess
import sys
import tomllib
```

**Exact tests to append:**

```python
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
```

**Command:** No test is run until Step 10.

**Expected result:** Static review confirms that the test reads package metadata with Python 3.11's `tomllib`, checks only direct dependency declarations, verifies the exact console target, and executes the Windows launcher without a network call.

**Acceptance criterion:** Covers package execution, approved dependencies, `src/` layout, and Git ignore requirements.

---

## Step 10: Run the package metadata test and confirm the expected failure

**Files:** No file changes.

**Interface or data structure:** No new interface. This proves package metadata is not present.

**Command:**

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py::test_dependency_declarations_are_limited_to_approved_packages -q
Remove-Item Env:PYTHONPATH
```

**Expected result:** Exit code is nonzero and the test fails with `FileNotFoundError` for `pyproject.toml`. Failure from an unrelated import or syntax error is not acceptable.

**Acceptance criterion:** The packaging slice is red because the task-1 project metadata has not yet been created.

---

## Step 11: Add the minimum package metadata and ignore rules

**Files:** Create `pyproject.toml` and `.gitignore` only.

**Interfaces and data structures:** Define the `coding-agent` console command and direct dependency groups. No dependency beyond official `openai` and `pytest` is added; `setuptools` is declared solely as the PEP 517 build backend.

**`pyproject.toml`:**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "coding-agent"
version = "0.1.0"
description = "A locally executed coding agent implemented from scratch"
requires-python = ">=3.11"
dependencies = ["openai"]

[project.optional-dependencies]
test = ["pytest"]

[project.scripts]
coding-agent = "coding_agent.cli:entrypoint"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

**`.gitignore`:**

```gitignore
.venv/
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.coverage
htmlcov/

.env
.env.*
*.local.toml
*.local.json

.coding-agent/
```

**Command:** No test command in this edit step. Install the package and run the green check in Step 12.

**Expected result:** Metadata declares one application dependency (`openai`), one test dependency (`pytest`), and the standard Windows console command. No lockfile or additional tool configuration is introduced.

**Acceptance criterion:** The project has the minimum approved Python package and ignore configuration required by task 1.

---

## Step 12: Install the editable package and turn the packaging slice green

**Files:** The installer may create ignored `.venv/` contents and local packaging metadata such as `src/coding_agent.egg-info/`. Do not manually edit generated metadata.

**Interface or data structure:** Verifies the installed `coding-agent.exe` entry point targets `coding_agent.cli:entrypoint`.

**Commands:**

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
```

Dependency installation requires user/sandbox authorization at execution time. It may download the declared packages and their transitive runtime dependencies, but it must not modify `pyproject.toml` or add a lockfile.

**Expected result:** Editable installation exits `0`; pytest exits `0` with exactly `20 passed`. `test_standard_console_command_runs` launches `.venv\Scripts\coding-agent.exe` and receives exit code `0` plus the fixed task-1 message.

**Acceptance criterion:** The package runs through its project-defined standard command and the complete task-1 test file is green.

---

## Step 13: Run the complete task-1 verification suite

**Files:** No file changes.

**Interfaces:** Verifies all task-1 interfaces and only task-1 tests.

**Commands:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
.\.venv\Scripts\coding-agent.exe --help
```

**Expected result:** The pytest command exits `0` with `20 passed`. The help command exits `0` and lists positional `task` plus `--workspace`, `--verify`, and `--model`. Record the actual command, exit code, and output; do not claim success if either command was not run.

**Acceptance criterion:** All task-1 tests pass together, and the installed command exposes exactly the task-1 CLI surface.

---

## Step 14: Check API-key safety

**Files:** No file changes.

**Interface or data structure:** Confirms that `RunConfig.__repr__`, success output, and error output do not reveal the environment-provided credential. No logger exists in task 1.

**Commands:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py::test_run_config_repr_hides_secret tests\test_cli.py::test_cli_error_does_not_print_secret tests\test_cli.py::test_standard_console_command_runs -q

$files = Get-ChildItem -Recurse -File | Where-Object {
    $_.FullName -notmatch '\\(\.git|\.venv)\\' -and
    $_.Extension -notin @('.pdf', '.pyc')
}
$matches = $files | Select-String -Pattern 'sk-[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._-]{20,}'
if ($matches) {
    $matches
    exit 1
}
Write-Output "No credential-like values found in repository text files."
```

**Expected result:** The focused pytest command exits `0` with `3 passed`. The repository scan prints only `No credential-like values found in repository text files.` and exits `0`. If it finds a match, stop, report the exact file without echoing the credential value, remove the leak, and rerun the checks.

**Acceptance criterion:** No credential value is printed or stored in source, tests, metadata, documentation, or generated task-1 output.

---

## Step 15: Check dependencies, forbidden frameworks, and generated files

**Files:** No intentional file changes. Generated `src/coding_agent.egg-info/` may exist locally and must remain ignored.

**Interface or data structure:** Confirms direct dependency declarations and absence of later-task/framework imports.

**Commands:**

```powershell
.\.venv\Scripts\python.exe -c "import pathlib,tomllib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); assert d['project']['dependencies']==['openai']; assert d['project']['optional-dependencies']['test']==['pytest']; print('Approved direct dependencies only: openai, pytest')"

$forbidden = Select-String -Path pyproject.toml,src\coding_agent\*.py,tests\*.py -Pattern 'langchain|llamaindex|openai.agents|autogen|crewai|claude_agent' -CaseSensitive:$false
if ($forbidden) {
    $forbidden
    exit 1
}
Write-Output "No prohibited agent framework references found in task-1 files."

git status --short
```

**Expected result:** The metadata command exits `0` and prints the two approved dependency groups. The framework scan exits `0` with no matches. `git status --short` shows only the task-1 implementation files, the task-1 status edit, already-existing user changes, and ignored/generated files as appropriate; it must not show `.venv/`, `.coding-agent/`, local credential files, or an added lockfile.

**Acceptance criterion:** No unapproved direct dependency, prohibited framework, or unrelated repository file was introduced.

---

## Step 16: Perform the task-1 plan self-check

**Files:** No file changes unless a concrete defect is found. Any correction must remain within the paths and interfaces named in this plan, then all affected checks must be rerun.

**Interfaces and data structures:** Compare the implemented names against `RunConfig`, `ConfigError`, `load_run_config`, `build_parser`, `main`, and `entrypoint` exactly.

**Checks and commands:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q

$markers = @(("T" + "BD"), ("T" + "ODO"))
$placeholderHits = Select-String -Path docs\superpowers\plans\2026-08-27-project-scaffold-cli.md -Pattern $markers
if ($placeholderHits) {
    $placeholderHits
    exit 1
}
Write-Output "No placeholder markers found in the task-1 plan."

git diff --check
git diff -- TASKS.md pyproject.toml .gitignore src\coding_agent\__init__.py src\coding_agent\config.py src\coding_agent\cli.py tests\test_cli.py
```

Then manually compare the final diff against this checklist:

1. Every row in the acceptance matrix has a passing test or explicit check.
2. Test imports and calls use the same six public names defined by the implementation.
3. `cli.py` imports only `config.py` from this project.
4. No excluded module or later-task behavior exists.
5. `--verify` is stored only; it is neither authorized nor executed.
6. No real credential or environment dump is present.
7. No dependency other than approved application/test packages is declared; the build backend remains packaging infrastructure only.
8. No rule in `AGENTS.md` was weakened or bypassed.

**Expected result:** Pytest exits `0` with `20 passed`; the placeholder scan and `git diff --check` exit `0`; the diff contains only task-1 files plus the task-1 status field. Any mismatch blocks the review handoff.

**Acceptance criterion:** All user-requested self-check categories are explicitly verified: full acceptance coverage, no placeholder wording, consistent function names, no scope expansion, and compliance with `AGENTS.md`.

---

## Step 17: Wait for user review and authorization

**Files:** Keep task 1 as `进行中` in `TASKS.md`. Do not change it to `已完成` before user acceptance.

**Interface or data structure:** None.

**Evidence to present:**

- The exact files created or modified.
- Each test command actually run, its real exit code, and its real result.
- The console-command result.
- The credential scan result.
- The dependency/framework scan result.
- Any skipped or unavailable check, clearly labeled as unverified.
- Confirmation that no later-task behavior was added.

**Command:** No commit, push, remote, or history-rewriting command is permitted in this step.

**Expected result:** Stop and wait for the user to inspect the implementation and evidence. The suggested future commit message remains `chore: scaffold python package and minimal cli`, but even that commit requires a separate, explicit user authorization.

**Acceptance criterion:** Task 1 is not claimed complete and no Git commit is created without user review and authorization.

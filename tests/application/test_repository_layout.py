from __future__ import annotations

import importlib
from pathlib import Path

import pytest


RESPONSIBILITY_PACKAGES = (
    "application",
    "engine",
    "providers",
    "operations",
    "operations.tools",
    "sessions",
    "skills",
    "web",
)

ENGINE_MODULES = (
    "agent",
    "budget",
    "context",
    "instructions",
    "logging",
    "messages",
    "model",
    "progress",
    "report",
    "run_mode",
    "state",
    "streaming",
    "termination",
    "verification",
)

OPERATION_MODULES = (
    "safety",
    "tools.base",
    "tools.filesystem",
    "tools.java",
    "tools.registry",
    "tools.shell",
)

PROVIDER_MODULES = (
    "openai_client",
    "chat_completions_client",
    "model_catalog",
)

SKILL_MODULES = ("catalog", "packages")

SESSION_MODULES = (
    "session",
    "session_controller",
    "session_deletion",
    "session_events",
    "session_runtime",
    "session_store",
)

APPLICATION_MODULES = ("app", "config", "cli")
WEB_MODULES = ("app", "auth", "cli")

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "src" / "coding_agent"
ROOT_DOCUMENTS = {"AGENTS.md", "README.md", "README.txt"}


@pytest.mark.parametrize("suffix", RESPONSIBILITY_PACKAGES)
def test_responsibility_package_is_importable(suffix: str) -> None:
    module = importlib.import_module(f"coding_agent.{suffix}")
    assert module.__name__ == f"coding_agent.{suffix}"
    assert hasattr(module, "__path__")


@pytest.mark.parametrize("name", ENGINE_MODULES)
def test_engine_module_is_importable(name: str) -> None:
    module = importlib.import_module(f"coding_agent.engine.{name}")
    assert module.__name__ == f"coding_agent.engine.{name}"


@pytest.mark.parametrize("name", OPERATION_MODULES)
def test_operation_module_is_importable(name: str) -> None:
    module = importlib.import_module(f"coding_agent.operations.{name}")
    assert module.__name__ == f"coding_agent.operations.{name}"


@pytest.mark.parametrize("name", PROVIDER_MODULES)
def test_provider_module_is_importable(name: str) -> None:
    module = importlib.import_module(f"coding_agent.providers.{name}")
    assert module.__name__ == f"coding_agent.providers.{name}"


@pytest.mark.parametrize("name", SKILL_MODULES)
def test_skill_module_is_importable(name: str) -> None:
    module = importlib.import_module(f"coding_agent.skills.{name}")
    assert module.__name__ == f"coding_agent.skills.{name}"


@pytest.mark.parametrize("name", SESSION_MODULES)
def test_session_module_is_importable(name: str) -> None:
    module = importlib.import_module(f"coding_agent.sessions.{name}")
    assert module.__name__ == f"coding_agent.sessions.{name}"


@pytest.mark.parametrize("name", APPLICATION_MODULES)
def test_application_module_is_importable(name: str) -> None:
    module = importlib.import_module(f"coding_agent.application.{name}")
    assert module.__name__ == f"coding_agent.application.{name}"


@pytest.mark.parametrize("name", WEB_MODULES)
def test_web_module_is_importable(name: str) -> None:
    module = importlib.import_module(f"coding_agent.web.{name}")
    assert module.__name__ == f"coding_agent.web.{name}"


def test_root_package_contains_only_marker_and_subpackages() -> None:
    assert sorted(path.name for path in PACKAGE_ROOT.glob("*.py")) == ["__init__.py"]


def test_root_contains_only_three_project_documents() -> None:
    found = {
        path.name
        for path in ROOT.iterdir()
        if path.is_file() and path.suffix.lower() in {".md", ".txt", ".pdf"}
    }
    assert found == ROOT_DOCUMENTS


def test_project_documents_have_final_locations() -> None:
    assert (ROOT / "docs/project/DESIGN.md").is_file()
    assert (ROOT / "docs/project/TASKS.md").is_file()
    assert (ROOT / "docs/project/requirement.pdf").is_file()


def test_readme_describes_folders_without_file_level_inventory() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for heading in ("## 项目简介", "## 仓库结构", "## 目录职责", "## 详细文档"):
        assert heading in text
    for folder in (
        "src/coding_agent/",
        "application/",
        "engine/",
        "providers/",
        "operations/",
        "sessions/",
        "skills/",
        "web/",
        "tests/",
        "docs/",
    ):
        assert folder in text
    assert "逐个源码文件" not in text


def test_readme_txt_submission_contract() -> None:
    text = (ROOT / "README.txt").read_text(encoding="utf-8")
    assert len(text) <= 1000
    assert "https://github.com/zt150058/MiniCodex" in text
    assert "Python 3.11" in text
    assert "coding-agent" in text
    assert "coding-agent-web" in text


def test_agents_points_to_current_design_and_tasks() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "docs/project/DESIGN.md" in text
    assert "docs/project/TASKS.md" in text

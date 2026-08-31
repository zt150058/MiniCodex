from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"


def test_ci_workflow_runs_offline_test_and_packaging_checks_on_windows() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    for required in (
        "push:",
        "pull_request:",
        "contents: read",
        "runs-on: windows-latest",
        "timeout-minutes: 30",
        "actions/checkout@v7",
        "actions/setup-python@v7",
        'python-version: "3.11"',
        "actions/setup-node@v7",
        'node-version: "24"',
        'python -m pip install -e ".[test]"',
        "python -m pytest -p no:cacheprovider -q",
        "node --test tests/js/web_gui.test.mjs",
        "coding-agent --help",
        "coding-agent-web --help",
        "python -m pip wheel . --no-deps",
        "git diff --check",
    ):
        assert required in text


def test_ci_workflow_does_not_require_live_provider_credentials() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "OPENAI_API_KEY" not in text
    assert "CHAT_COMPLETIONS_API_KEY" not in text

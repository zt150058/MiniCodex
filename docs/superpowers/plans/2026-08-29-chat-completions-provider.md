# Chat Completions Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Before production behavior, use `superpowers:test-driven-development`; for any unexpected failure, use `superpowers:systematic-debugging`; before completion, use `superpowers:verification-before-completion`; after the core adapter, use `superpowers:requesting-code-review`. Keep tightly coupled core implementation inline. The user has authorized subagents only for independent read-only audits or reviews; they must not edit shared core files.

**Goal:** Add a provider-neutral OpenAI-compatible Chat Completions model client that supports BayesDL GLM tool-calling loops while preserving the existing Responses client and `ModelClient.complete(ModelRequest) -> ModelResponse` boundary.

**Architecture:** Keep `OpenAIResponsesClient` unchanged and add an independent `ChatCompletionsModelClient` adapter selected by explicit `api-mode + base-url` configuration. The Chat adapter maps the complete locally managed history on every call, returns no continuation, validates immediate assistant/tool pairing before the SDK boundary, and translates SDK responses into existing internal types. Existing child-process environment sanitization is extended only to remove the Chat credential, while URL and malformed-SDK-response boundaries are hardened locally. Configuration, transport, response parsing, Agent integration, and documentation are verified entirely with fake SDK objects and no network.

**Tech Stack:** Python 3.11+, standard library, existing official `openai` package, pytest, PowerShell on Windows. No new dependency.

**Spec:** `docs/superpowers/specs/2026-08-29-chat-completions-provider-design.md`

## Global Constraints

- Preserve `ModelClient.complete(ModelRequest) -> ModelResponse` and all provider-neutral message/tool types.
- Do not modify `src/coding_agent/openai_client.py`; its accepted Responses behavior is a regression boundary.
- `--api-mode` accepts only `responses` and `chat-completions`; the default is `responses`.
- `responses` rejects `--base-url` before SDK construction; `chat-completions` requires an absolute HTTPS base URL and rejects C0/DEL controls, non-peripheral whitespace, and backslashes before URL parsing.
- Responses reads only `OPENAI_API_KEY`; Chat Completions reads only `CHAT_COMPLETIONS_API_KEY`; there is no fallback and no API-key CLI argument.
- Remove both credential names case-insensitively from every `run_command` child environment; preserve unrelated safe environment values.
- Never log, report, print, persist, or include an API key, Authorization header, provider response body, SDK exception repr, or environment dump.
- Treat parser failures, `APIResponseValidationError`, and `json.JSONDecodeError` as non-retrying `invalid_model_response` failures with stable text and no exception chaining.
- Every Chat request contains the complete prepared internal history; it does not use conversation, `previous_response_id`, or server persistence.
- Chat `ModelResponse.continuation_items` is always empty, including summary and post-compression calls.
- Use `max_tokens`, not `max_completion_tokens`; do not retry with alternate request fields.
- Detect tool calls from `choice.message.tool_calls`, not `finish_reason`; accept `finish_reason="stop"` with tool calls.
- Default tests are offline and must not call a real API. Do not reuse any credential from an earlier conversation.
- Do not create a branch/worktree, install dependencies, stage, commit, push, pull, fetch, or access a remote repository. User-authorized subagents are read-only audit/review helpers only.
- Replace the writing-plans skill's normal commit steps with read-only `git diff --check`, `git diff`, and user review checkpoints.
- Task15 is `进行中`; implementation remains paused at the safety-amendment gate until this revised plan is approved. It becomes `已完成` only after all acceptance tests and final review pass.

---

## Locked File Map

### Create

- `src/coding_agent/chat_completions_client.py` — Chat-only URL validation, request mapping, response parsing, retry/error conversion, and the public client.
- `tests/test_chat_completions_client.py` — fake-SDK unit tests for every adapter boundary.
- `tests/integration/test_chat_completions_agent.py` — real `AgentRunner` plus fake Chat SDK continuous-loop tests.

### Modify

- `src/coding_agent/config.py` — `ApiMode`, mode/base-URL validation, separated credential selection, and new `RunConfig` fields.
- `src/coding_agent/cli.py` — `--api-mode` and `--base-url` arguments.
- `src/coding_agent/app.py` — explicit production-adapter selection.
- `src/coding_agent/tools/shell.py` — add only the Chat credential name to the existing case-insensitive child-environment removal set.
- `tests/test_cli.py` — configuration and CLI combination tests.
- `tests/test_app.py` — Responses/Chat composition-root selection tests.
- `tests/tools/test_shell_tool.py` — actual-child and process-factory credential isolation regression tests.
- `tests/test_docs.py` — executable documentation contract for both API modes.
- `README.md`, `README.txt`, `docs/USAGE.md`, `docs/OPENAI_API.md` — user-facing provider selection, security, compatibility, and testing guidance.
- `DESIGN.md` — reconcile mode-specific credential and child-process security contracts.
- `TASKS.md` — Task15 acceptance/file scope plus final status transition from `进行中` -> `已完成` after verification.

### Preserve Without Production Edits

- `src/coding_agent/model.py`
- `src/coding_agent/messages.py`
- `src/coding_agent/openai_client.py`
- `src/coding_agent/agent.py`
- `src/coding_agent/context.py`
- tool behavior outside the exact `CHAT_COMPLETIONS_API_KEY` child-environment removal entry
- safety, verification, termination, logging, report, and dependency declarations

## Execution Resume Gate After the Safety Amendment

- Baseline verification completed sequentially with `720 passed`; an earlier concurrent duplicate full-suite launch was diagnosed as self-inflicted test-process interference and required no source fix.
- Initial API configuration/CLI behavior and Chat request mapping were implemented with focused green regressions before the review finding.
- Task 3 parser tests were added but not run; `_parse_response` and all later production work remain unimplemented.
- After this revised plan is approved, resume in this order: add the newly specified URL RED cases to Tasks 1 and 2, execute Task 2A child-environment RED/GREEN, then run the existing Task 3 RED test before writing parser code.
- All current changes remain unstaged. Do not reset, restore, stage, or commit them.

---

### Task 0: Reconfirm the Baseline Before Any Implementation Mutation

**Files:**
- Read: `AGENTS.md`
- Read: `DESIGN.md`
- Read: `TASKS.md`
- Read: `docs/superpowers/specs/2026-08-29-chat-completions-provider-design.md`
- Read: `docs/superpowers/plans/Task9.md`
- Read: `docs/superpowers/plans/Task10.md`
- Read: `docs/superpowers/plans/Task14.md`
- Read: current Git status and diff

**Interfaces:**
- Consumes: the approved design baseline and the user's existing unstaged Task14/Task15 design changes.
- Produces: a fresh offline baseline proving implementation can begin without overwriting unrelated work.

- [ ] **Step 1: Re-read all binding instructions and approved architecture**

Read every listed file completely. Confirm Task14 is `已完成`, Task15 is `进行中`, the new adapter is additive, and `openai_client.py`, Agent, messages, ContextManager, tool behavior outside the approved credential filter, dependencies, and public ModelClient boundary are protected.

- [ ] **Step 2: Inspect the working tree without changing it**

Run:

```powershell
git status --short --untracked-files=all
git diff --check
git diff --name-only
```

Expected: the approved `DESIGN.md`, `TASKS.md`, Task15 spec, and this plan may be unstaged. If any other pre-existing path is modified, inspect it and stop for user direction if Task15 would overlap it. Do not reset, restore, stage, or commit anything.

- [ ] **Step 3: Run the pre-implementation offline baseline**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Expected: all current tests PASS with exit code 0 and no network. If the baseline fails, do not begin Task15; invoke systematic debugging to diagnose and report whether the failure predates implementation.

---

### Task 1: Add Explicit API Configuration and CLI Validation

**Files:**
- Modify: `TASKS.md:557`
- Modify: `src/coding_agent/config.py:1-96`
- Modify: `src/coding_agent/cli.py:13-67`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: existing `RunConfig`, `load_run_config`, and `build_parser()`.
- Produces: `ApiMode`, `RunConfig.api_mode: ApiMode`, `RunConfig.base_url: str | None`, and new keyword parameters `api_mode` and `base_url` on `load_run_config`.

- [ ] **Step 1: Confirm Task15 remains the only active task**

Do not change status at this step. Confirm Tasks 1–14 remain `已完成`, Task15 remains `进行中`, and exactly one task is active.

Run:

```powershell
rg -n "当前状态|`已完成`|`进行中`|`未开始`" TASKS.md
```

Expected: Task15 is the only `进行中` entry.

- [ ] **Step 2: Write failing configuration and CLI tests**

Extend imports and the environment helper in `tests/test_cli.py`:

```python
from coding_agent.config import ApiMode, ConfigError, RunConfig, load_run_config


CHAT_SECRET_SENTINEL = "chat-key-must-never-be-printed"


def valid_chat_environ() -> dict[str, str]:
    return {
        "OPENAI_MODEL": "chat-model",
        "CHAT_COMPLETIONS_API_KEY": CHAT_SECRET_SENTINEL,
    }
```

Add these exact behavioral tests:

```python
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
        ("unknown", None, "api mode must be one of: responses, chat-completions"),
        ("responses", "https://provider.example/v1", "--base-url is not allowed with responses"),
        ("chat-completions", None, "--base-url is required with chat-completions"),
        ("chat-completions", "   ", "--base-url is required with chat-completions"),
        ("chat-completions", "http://provider.example/v1", "--base-url must be an absolute HTTPS URL"),
        ("chat-completions", "provider.example/v1", "--base-url must be an absolute HTTPS URL"),
        ("chat-completions", "https:///api/v1", "--base-url must be an absolute HTTPS URL"),
        ("chat-completions", "https://user:pass@provider.example/v1", "--base-url must be an absolute HTTPS URL"),
        ("chat-completions", "https://provider.example/v1?region=x", "--base-url must be an absolute HTTPS URL"),
        ("chat-completions", "https://provider.example/v1#section", "--base-url must be an absolute HTTPS URL"),
        ("chat-completions", "\x00https://provider.example/v1", "--base-url must be an absolute HTTPS URL"),
        ("chat-completions", "\thttps://provider.example/v1", "--base-url must be an absolute HTTPS URL"),
        ("chat-completions", "https://provider.example/v1\tbad", "--base-url must be an absolute HTTPS URL"),
        ("chat-completions", "https://provider.example/v1\u00a0bad", "--base-url must be an absolute HTTPS URL"),
        ("chat-completions", "\x7fhttps://provider.example/v1", "--base-url must be an absolute HTTPS URL"),
        ("chat-completions", r"https://provider.example/v1\bad", "--base-url must be an absolute HTTPS URL"),
    ],
)
def test_config_rejects_invalid_mode_url_combinations_before_credentials(
    tmp_path: Path,
    api_mode: str,
    base_url: str | None,
    message: str,
) -> None:
    with pytest.raises(ConfigError, match=message) as caught:
        load_run_config(
            task="inspect",
            workspace=tmp_path / "missing",
            model=None,
            verify_command=None,
            api_mode=api_mode,
            base_url=base_url,
            environ={},
        )

    rendered = str(caught.value)
    assert "provider.example" not in rendered
    assert SECRET_SENTINEL not in rendered


@pytest.mark.parametrize(
    ("api_mode", "base_url", "environment", "missing_name"),
    [
        ("responses", None, {"OPENAI_MODEL": "model", "CHAT_COMPLETIONS_API_KEY": CHAT_SECRET_SENTINEL}, "OPENAI_API_KEY"),
        ("chat-completions", "https://provider.example/v1", {"OPENAI_MODEL": "model", "OPENAI_API_KEY": SECRET_SENTINEL}, "CHAT_COMPLETIONS_API_KEY"),
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
```

Add direct `RunConfig` invariants:

```python
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
```

Update the help test so `build_parser().format_help()` contains `--api-mode`, `--base-url`, `responses`, and `chat-completions`. Add a valid Chat CLI test:

```python
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
```

Add an argparse test invoking `--api-mode unknown` and assert `SystemExit.code == 2`. The valid Chat invocation must not print either secret.

Prove an illegal CLI combination stops before the application boundary:

```python
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
```

This proves the illegal combination is rejected before application import, SDK construction, or a network request.

- [ ] **Step 3: Run the new tests to verify RED**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q -p no:cacheprovider
```

Expected: FAIL during import because `ApiMode` does not exist, with no application or network call.

- [ ] **Step 4: Implement `ApiMode`, URL validation, and credential selection**

Add standard-library imports and the enum in `config.py`:

```python
from enum import StrEnum
from urllib.parse import urlsplit


class ApiMode(StrEnum):
    RESPONSES = "responses"
    CHAT_COMPLETIONS = "chat-completions"
```

Extend `RunConfig` without changing its existing required fields:

```python
@dataclass(frozen=True, slots=True)
class RunConfig:
    task: str
    workspace: Path
    model: str
    api_key: str = field(repr=False)
    api_mode: ApiMode = ApiMode.RESPONSES
    base_url: str | None = field(default=None, repr=False)
    verify_command: AuthorizedCommand | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.api_mode, ApiMode):
            raise ConfigError(
                "api mode must be one of: responses, chat-completions"
            )
        if self.api_mode is ApiMode.RESPONSES:
            if self.base_url is not None:
                raise ConfigError("--base-url is not allowed with responses")
            return
        if self.base_url is None:
            raise ConfigError("--base-url is required with chat-completions")
        object.__setattr__(
            self,
            "base_url",
            _normalize_chat_base_url(self.base_url),
        )
```

Define `_normalize_chat_base_url` in the same module before the first `RunConfig` instance is created. Python resolves the helper when `__post_init__` runs, after module initialization.

Add a config-local validator that never includes the supplied URL in its error:

```python
_BASE_URL_ERROR = (
    "--base-url must be an absolute HTTPS URL without userinfo, query, or fragment"
)


def _normalize_chat_base_url(value: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(_BASE_URL_ERROR)
    if any(
        ord(character) <= 0x1F
        or ord(character) == 0x7F
        or character == "\\"
        for character in value
    ):
        raise ConfigError(_BASE_URL_ERROR)
    normalized = value.strip(" ")
    if not normalized:
        raise ConfigError("--base-url is required with chat-completions")
    if any(character.isspace() for character in normalized):
        raise ConfigError(_BASE_URL_ERROR)
    try:
        parsed = urlsplit(normalized)
        host = parsed.hostname
        parsed.port
    except ValueError:
        raise ConfigError(_BASE_URL_ERROR) from None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or host is None
        or not host.strip()
        or parsed.username is not None
        or parsed.password is not None
        or "?" in normalized
        or "#" in normalized
    ):
        raise ConfigError(_BASE_URL_ERROR)
    return normalized.rstrip("/") + "/"
```

Add optional keywords after `verify_command`:

```python
def load_run_config(
    *,
    task: str,
    workspace: str | Path,
    model: str | None,
    verify_command: str | None,
    api_mode: ApiMode | str = ApiMode.RESPONSES,
    base_url: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> RunConfig:
```

Immediately after selecting `source`, validate in the approved order:

```python
    try:
        selected_mode = ApiMode(api_mode)
    except (TypeError, ValueError):
        raise ConfigError(
            "api mode must be one of: responses, chat-completions"
        ) from None

    normalized_base_url: str | None = None
    if selected_mode is ApiMode.RESPONSES:
        if base_url is not None:
            raise ConfigError("--base-url is not allowed with responses")
        credential_name = "OPENAI_API_KEY"
    else:
        if base_url is None:
            raise ConfigError("--base-url is required with chat-completions")
        normalized_base_url = _normalize_chat_base_url(base_url)
        credential_name = "CHAT_COMPLETIONS_API_KEY"

    normalized_api_key = source.get(credential_name, "").strip()
    if not normalized_api_key:
        raise ConfigError(f"{credential_name} is not configured")
```

Remove the old unconditional `OPENAI_API_KEY` block, retain the current task/workspace/model/verify validation after this block, and return `api_mode=selected_mode` plus `base_url=normalized_base_url`.

- [ ] **Step 5: Add the two CLI arguments**

In `build_parser()` add:

```python
    parser.add_argument(
        "--api-mode",
        choices=("responses", "chat-completions"),
        default="responses",
        help="Model API mode; defaults to responses",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="HTTPS API base URL; required only for chat-completions",
    )
```

Pass `api_mode=args.api_mode` and `base_url=args.base_url` to `load_run_config`. Do not add an API-key argument.

Change the existing `--model` help text from `OpenAI model` to `Model identifier; overrides OPENAI_MODEL` so Chat mode is not described as an OpenAI-only path.

- [ ] **Step 6: Run GREEN and Responses configuration regression**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_openai_client.py -q -p no:cacheprovider
git diff --check
```

Expected: all tests PASS; `git diff --check` exits 0. Inspect the diff and confirm no key value or provider-specific default URL was added.

---

### Task 2: Implement Chat Request Mapping and Local Invariants

**Files:**
- Create: `src/coding_agent/chat_completions_client.py`
- Create: `tests/test_chat_completions_client.py`

**Interfaces:**
- Consumes: `UserMessage`, `AssistantMessage`, `ToolResult`, `ModelRequest`, and strict internal tool schemas.
- Produces: `_normalize_base_url(value: str) -> str`, `_map_messages(request: ModelRequest) -> list[dict[str, object]]`, and `_map_tools(tool_schemas: tuple[JSONObject, ...]) -> list[dict[str, object]]` for the public client added in Task 4.

- [ ] **Step 1: Write failing mapper tests with a fake Chat resource**

Create `tests/test_chat_completions_client.py` with imports, constants, fake resource objects, and exact request assertions:

```python
from __future__ import annotations

from collections import deque
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from coding_agent.chat_completions_client import (
    _map_messages,
    _map_tools,
    _normalize_base_url,
)
from coding_agent.messages import (
    AssistantMessage,
    ModelRequest,
    ToolCall,
    ToolResult,
    UserMessage,
)
from coding_agent.model import FatalModelError


FAKE_KEY = "chat-unit-key-never-send"
FAKE_BASE_URL = "https://provider.example/api/maas/v1/"
TOOL_SCHEMA = {
    "name": "echo",
    "description": "Return the supplied text.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
}
```

Add tests that assert:

```python
def test_complete_history_maps_to_standard_chat_messages() -> None:
    first = ToolCall("call_1", "echo", {"z": 2, "text": "雪"})
    second = ToolCall("call_2", "echo", {"text": "two"})
    first_result = ToolResult(
        call_id="call_1",
        tool_name="echo",
        status="ok",
        output="one",
    )
    second_result = ToolResult(
        call_id="call_2",
        tool_name="echo",
        status="ok",
        output="two",
    )
    request = ModelRequest(
        messages=(
            UserMessage("begin"),
            AssistantMessage(content="calling", tool_calls=(first, second)),
            first_result,
            second_result,
            AssistantMessage(content="prior text"),
            UserMessage("continue"),
        )
    )

    assert _map_messages(request) == [
        {"role": "user", "content": "begin"},
        {
            "role": "assistant",
            "content": "calling",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "echo",
                        "arguments": '{"text":"雪","z":2}',
                    },
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "echo",
                        "arguments": '{"text":"two"}',
                    },
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": first_result.to_json()},
        {"role": "tool", "tool_call_id": "call_2", "content": second_result.to_json()},
        {"role": "assistant", "content": "prior text"},
        {"role": "user", "content": "continue"},
    ]


def test_strict_tool_maps_to_nested_chat_function() -> None:
    assert _map_tools((TOOL_SCHEMA,)) == [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Return the supplied text.",
                "strict": True,
                "parameters": TOOL_SCHEMA["parameters"],
            },
        }
    ]


def test_nonempty_continuation_is_rejected_before_mapping() -> None:
    request = ModelRequest(
        messages=(UserMessage("begin"),),
        continuation_items=(object(),),
    )

    with pytest.raises(FatalModelError, match="continuation must be empty"):
        _map_messages(request)


def test_tool_results_must_immediately_match_assistant_call_order() -> None:
    first = ToolCall("call_1", "echo", {"text": "one"})
    second = ToolCall("call_2", "echo", {"text": "two"})
    request = ModelRequest(
        messages=(
            UserMessage("begin"),
            AssistantMessage(tool_calls=(first, second)),
            ToolResult("call_2", "echo", "ok"),
            ToolResult("call_1", "echo", "ok"),
        )
    )

    with pytest.raises(FatalModelError, match="matching tool results"):
        _map_messages(request)
```

Parametrize malformed schemas using the existing Responses cases: `strict=False`, missing description, extra key, `additionalProperties=True`, and incomplete `required`. Assert a stable `FatalModelError` and no schema/argument content in the error. Parametrize direct base URLs with the same valid/invalid matrix as Task 1, including NUL, leading/interior TAB, non-breaking internal whitespace, DEL, and a backslash path; assert the supplied host and raw value never appear in a validation error.

- [ ] **Step 2: Run mapper tests to verify RED**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_client.py -q -p no:cacheprovider
```

Expected: FAIL because `coding_agent.chat_completions_client` does not exist.

- [ ] **Step 3: Implement exact URL, schema, and message mapping**

Create `chat_completions_client.py` with standard-library imports, existing internal types, stable constants, and these mapping rules:

```python
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
from urllib.parse import urlsplit

from coding_agent.messages import (
    AssistantMessage,
    JSONObject,
    ModelRequest,
    ToolResult,
    UserMessage,
)
from coding_agent.model import FatalModelError, ModelError


class InvalidChatCompletionsResponseError(ModelError):
    """The provider returned a completed but unusable Chat payload."""

    observation_error_code = "invalid_model_response"


_BASE_URL_ERROR = (
    "Chat Completions base_url must be an absolute HTTPS URL without "
    "userinfo, query, or fragment"
)
_STRICT_SCHEMA_ERROR = (
    "Chat Completions request is invalid: tool schema is not strict"
)
_CONTINUATION_ERROR = (
    "Chat Completions request is invalid: continuation must be empty"
)
_MESSAGE_ORDER_ERROR = (
    "Chat Completions request is invalid: assistant tool calls must be "
    "followed by matching tool results"
)


def _canonical_json(value: JSONObject) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
```

Implement direct-client URL validation without importing configuration code:

```python
def _normalize_base_url(value: str) -> str:
    if not isinstance(value, str) or any(
        ord(character) <= 0x1F
        or ord(character) == 0x7F
        or character == "\\"
        for character in value
    ):
        raise ValueError(_BASE_URL_ERROR)
    normalized = value.strip(" ")
    if not normalized:
        raise ValueError(_BASE_URL_ERROR)
    if any(character.isspace() for character in normalized):
        raise ValueError(_BASE_URL_ERROR)
    try:
        parsed = urlsplit(normalized)
        host = parsed.hostname
        parsed.port
    except ValueError:
        raise ValueError(_BASE_URL_ERROR) from None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or host is None
        or not host.strip()
        or parsed.username is not None
        or parsed.password is not None
        or "?" in normalized
        or "#" in normalized
    ):
        raise ValueError(_BASE_URL_ERROR)
    return normalized.rstrip("/") + "/"
```

Implement the independent strict-schema validator and nested Chat function mapping:

```python
def _schema_node_is_strict(node: object) -> bool:
    if not isinstance(node, dict):
        return False
    if node.get("type") == "object":
        properties = node.get("properties")
        required = node.get("required")
        if (
            not isinstance(properties, dict)
            or node.get("additionalProperties") is not False
            or not isinstance(required, list)
            or any(not isinstance(item, str) for item in required)
            or len(required) != len(set(required))
            or set(required) != set(properties)
        ):
            return False
        if not all(_schema_node_is_strict(child) for child in properties.values()):
            return False
    for branch_name in ("anyOf", "oneOf"):
        branches = node.get(branch_name)
        if branches is not None:
            if not isinstance(branches, list) or not branches:
                return False
            if not all(_schema_node_is_strict(branch) for branch in branches):
                return False
    if "items" in node and not _schema_node_is_strict(node["items"]):
        return False
    return True


def _map_tools(
    tool_schemas: tuple[JSONObject, ...],
) -> list[dict[str, object]]:
    mapped: list[dict[str, object]] = []
    for schema in tool_schemas:
        if set(schema) != {"name", "description", "strict", "parameters"}:
            raise FatalModelError(_STRICT_SCHEMA_ERROR)
        name = schema["name"]
        description = schema["description"]
        parameters = schema["parameters"]
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(description, str)
            or not description.strip()
            or schema["strict"] is not True
            or not isinstance(parameters, dict)
            or parameters.get("type") != "object"
            or not _schema_node_is_strict(parameters)
        ):
            raise FatalModelError(_STRICT_SCHEMA_ERROR)
        mapped.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "strict": True,
                    "parameters": deepcopy(parameters),
                },
            }
        )
    return mapped
```

Implement immediate pairing and mapping:

```python
def _validate_message_order(request: ModelRequest) -> None:
    index = 0
    while index < len(request.messages):
        message = request.messages[index]
        if isinstance(message, ToolResult):
            raise FatalModelError(_MESSAGE_ORDER_ERROR)
        if not isinstance(message, AssistantMessage) or not message.tool_calls:
            index += 1
            continue
        first_result = index + 1
        after_results = first_result + len(message.tool_calls)
        if after_results > len(request.messages):
            raise FatalModelError(_MESSAGE_ORDER_ERROR)
        results = request.messages[first_result:after_results]
        for call, result in zip(message.tool_calls, results, strict=True):
            if (
                not isinstance(result, ToolResult)
                or result.call_id != call.call_id
                or result.tool_name != call.name
            ):
                raise FatalModelError(_MESSAGE_ORDER_ERROR)
        index = after_results


def _map_messages(request: ModelRequest) -> list[dict[str, object]]:
    if request.continuation_items:
        raise FatalModelError(_CONTINUATION_ERROR)
    _validate_message_order(request)
    mapped: list[dict[str, object]] = []
    for message in request.messages:
        if isinstance(message, UserMessage):
            mapped.append({"role": "user", "content": message.content})
        elif isinstance(message, AssistantMessage):
            assistant: dict[str, object] = {
                "role": "assistant",
                "content": message.content,
            }
            if message.tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": call.call_id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": _canonical_json(call.arguments),
                        },
                    }
                    for call in message.tool_calls
                ]
            mapped.append(assistant)
        else:
            mapped.append(
                {
                    "role": "tool",
                    "tool_call_id": message.call_id,
                    "content": message.to_json(),
                }
            )
    return mapped
```

Do not add a `name` field to tool-result messages. Do not import or change Agent, ContextManager, or Responses code.

- [ ] **Step 4: Run mapper GREEN and message regression**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_client.py tests\test_messages.py tests\test_openai_client.py -q -p no:cacheprovider
git diff --check
```

Expected: mapper tests PASS, all existing message/Responses tests PASS, and diff check exits 0.

---

### Task 2A: Remove Both Model Credentials from Child Processes

**Files:**
- Modify: `src/coding_agent/tools/shell.py:44-63`
- Modify: `tests/tools/test_shell_tool.py:290-301,709-740,901-961`

**Interfaces:**
- Consumes: existing `_REMOVED_ENVIRONMENT_KEYS` and `_child_environment()` case-insensitive filtering.
- Produces: the same child environment contract with both `openai_api_key` and `chat_completions_api_key` removed; command authorization and execution APIs remain unchanged.

- [ ] **Step 1: Write failing actual-child and captured-environment tests**

Add an actual allowed Python child test next to the existing OpenAI-key test:

```python
def test_run_command_does_not_pass_chat_completions_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CHAT_COMPLETIONS_API_KEY",
        "chat-key-must-not-reach-child",
    )
    execution = _execute_script(
        tmp_path,
        "import os\n"
        "print(os.environ.get('CHAT_COMPLETIONS_API_KEY', '<absent>'))\n",
    )

    payload = json.loads(execution.output or "")
    if payload["stdout"] != "<absent>\r\n":
        pytest.fail("Chat Completions credential reached child process")
    assert "chat-key-must-not-reach-child" not in (execution.output or "")
```

Extend `test_process_launch_uses_shell_false_fixed_cwd_and_sanitized_environment` to set a mixed-case `ChAt_Completions_Api_Key`, set `MINICODEX_SAFE_TEST_VALUE=preserved`, and assert against a folded-key map:

```python
folded_environment = {key.casefold(): value for key, value in environment.items()}
assert "openai_api_key" not in folded_environment
if "chat_completions_api_key" in folded_environment:
    pytest.fail("Chat Completions credential reached captured child environment")
assert folded_environment["minicodex_safe_test_value"] == "preserved"
```

Also add `ChAt_Completions_Api_Key` to the input map in `test_child_environment_removes_policy_widening_values` and add `chat_completions_api_key` to its denied folded-key set. These two captured-environment assertions prove case-insensitive removal independently of Windows' case-insensitive environment lookup.

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py::test_run_command_does_not_pass_chat_completions_api_key tests\tools\test_shell_tool.py::test_process_launch_uses_shell_false_fixed_cwd_and_sanitized_environment tests\tools\test_shell_tool.py::test_child_environment_removes_policy_widening_values -q -p no:cacheprovider
```

Expected: FAIL because `CHAT_COMPLETIONS_API_KEY` is still visible in the actual child and captured environment. Confirm the fake credential value is not printed by the test runner.

- [ ] **Step 3: Make the minimal child-environment change**

Add exactly one entry to the existing set:

```python
_REMOVED_ENVIRONMENT_KEYS = {
    "openai_api_key", "chat_completions_api_key", "pythonpath", "pythonhome",
    "pytest_addopts", "pytest_plugins", "mypypath", "mypy_config_file",
    "git_dir", "git_work_tree", "git_object_directory",
    "git_alternate_object_directories", "git_external_diff", "git_ssh",
    "git_ssh_command", "git_askpass", "ssh_askpass",
}
```

Do not introduce pattern-based credential removal, alter the caller environment, or change subprocess command, timeout, capture, authorization, or verification behavior.

- [ ] **Step 4: Run child-environment GREEN and provider regressions**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py tests\test_cli.py tests\test_chat_completions_client.py tests\test_openai_client.py -q -p no:cacheprovider
git diff --check
```

Expected: all selected tests PASS and diff check exits 0. Inspect `git diff -- src/coding_agent/tools/shell.py` and confirm the only production tool change is the new folded credential name.

---

### Task 3: Parse Text, Tool Calls, Finish Reasons, IDs, and Usage

**Files:**
- Modify: `src/coding_agent/chat_completions_client.py`
- Modify: `tests/test_chat_completions_client.py`

**Interfaces:**
- Consumes: an SDK-like Chat completion object or equivalent mappings.
- Produces: `_parse_response(response: object) -> ModelResponse` and stable `InvalidChatCompletionsResponseError` failures.

- [ ] **Step 1: Add fake response builders and successful parsing tests**

Add SDK-shaped builders that use `SimpleNamespace` and do not import Chat SDK response types:

```python
def tool_call_item(
    call_id: str,
    *,
    name: str = "echo",
    arguments: str = '{"text":"hello"}',
    call_type: str = "function",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        type=call_type,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def chat_response(
    *,
    content: str | None = "done",
    tool_calls: list[object] | None = None,
    finish_reason: str | None = "stop",
    response_id: object = "chatcmpl_test",
    usage: object | None = None,
    role: str = "assistant",
    legacy_function_call: object | None = None,
) -> SimpleNamespace:
    message = SimpleNamespace(
        role=role,
        content=content,
        tool_calls=tool_calls,
        function_call=legacy_function_call,
    )
    return SimpleNamespace(
        id=response_id,
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=usage,
    )
```

Add tests for text only, one function call, multiple calls preserving order, text plus calls, `finish_reason="stop"` plus calls, `finish_reason="tool_calls"`, absent/null response ID, and complete usage mapping:

```python
def test_stop_with_text_and_multiple_tool_calls_preserves_all_outputs() -> None:
    response = _parse_response(
        chat_response(
            content="I will inspect.",
            tool_calls=[
                tool_call_item("call_2", arguments='{"text":"two"}'),
                tool_call_item("call_1", arguments='{"text":"one"}'),
            ],
            finish_reason="stop",
            usage=SimpleNamespace(
                prompt_tokens=12,
                completion_tokens=7,
                total_tokens=19,
            ),
        )
    )

    assert response.text == "I will inspect."
    assert [call.call_id for call in response.tool_calls] == ["call_2", "call_1"]
    assert response.usage == TokenUsage(12, 7, 19)
    assert response.provider_response_id == "chatcmpl_test"
    assert response.continuation_items == ()
```

- [ ] **Step 2: Add an explicit invalid-payload matrix**

Parametrize all of these cases and exact public reasons:

| Case | Stable reason |
| --- | --- |
| choices missing/not list/empty/two entries | `response must contain exactly one choice` |
| message missing or role not assistant | `choice message is invalid` |
| finish reason `length` | `finish reason is not supported` |
| finish reason `content_filter` | `finish reason is not supported` |
| finish reason null or unknown | `finish reason is not supported` |
| content non-string/non-null | `assistant content is invalid` |
| empty/whitespace content and no calls | `no text or function tool calls` |
| legacy `function_call` non-null | `legacy function_call is not supported` |
| tool_calls non-list/non-null | `tool_calls is invalid` |
| tool type not `function` | `unsupported tool call type` |
| call ID empty/duplicate | `function call id is invalid` / `duplicate function call id` |
| function object/name missing | `function call is invalid` |
| arguments non-string/invalid JSON/JSON array | `function arguments are not valid JSON` / `function arguments must be an object` |
| response ID present but empty/non-string | `response id is invalid` |
| usage missing one field, bool, negative, or string | `usage is invalid` |

For every case assert the full prefix is `invalid Chat Completions payload: `, the fake secret response-body marker is absent, and `_parse_response` raises `InvalidChatCompletionsResponseError` rather than an SDK or JSON exception.

- [ ] **Step 3: Run response tests to verify RED**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_client.py -q -p no:cacheprovider
```

Expected: FAIL because `_parse_response` and the successful response mapping do not exist.

- [ ] **Step 4: Implement defensive attribute/mapping parsing**

Add `TokenUsage`, `ToolCall`, and `ModelResponse` imports. Implement field access without exposing values:

```python
_MISSING = object()


def _invalid_response(reason: str) -> InvalidChatCompletionsResponseError:
    return InvalidChatCompletionsResponseError(
        f"invalid Chat Completions payload: {reason}"
    )


def _field(value: object, name: str, reason: str) -> object:
    if isinstance(value, Mapping):
        found = value.get(name, _MISSING)
    else:
        found = getattr(value, name, _MISSING)
    if found is _MISSING:
        raise _invalid_response(reason)
    return found


def _optional_field(value: object, name: str) -> object | None:
    if isinstance(value, Mapping):
        found = value.get(name, None)
    else:
        found = getattr(value, name, None)
    return found
```

Implement `_parse_response` in this exact order:

1. Require a list/tuple of exactly one choice.
2. Require `finish_reason` to be exactly `stop` or `tool_calls`.
3. Require an assistant message and reject non-null legacy `function_call`.
4. Convert a nonblank string content to text; treat null or blank string as no text; reject other types.
5. Treat null tool_calls as empty; otherwise require list/tuple.
6. For each item, require type `function`, a unique nonblank string ID, a nonblank function name, and a JSON-object arguments string; construct internal `ToolCall` values in provider order.
7. Reject when both text and calls are absent.
8. Treat missing/null top-level ID as `provider_response_id=None`; if present, require a nonblank string.
9. Treat missing/null usage as `None`; if present, require all three token fields and construct `TokenUsage(prompt_tokens, completion_tokens, total_tokens)` so bools, negatives, strings, and partial usage fail.
10. Return `ModelResponse(text=text, tool_calls=tuple(tool_calls), usage=usage, provider_response_id=response_id, continuation_items=())`; wrap internal type errors as `invalid Chat Completions payload: invalid model response`.

The parser must inspect `message.tool_calls` regardless of `finish_reason`, so the allowed `stop` plus calls case remains GREEN.

Use this concrete implementation shape:

```python
def _parse_response(response: object) -> ModelResponse:
    choices = _field(
        response,
        "choices",
        "response must contain exactly one choice",
    )
    if not isinstance(choices, (list, tuple)) or len(choices) != 1:
        raise _invalid_response("response must contain exactly one choice")
    choice = choices[0]
    finish_reason = _field(
        choice,
        "finish_reason",
        "finish reason is not supported",
    )
    if finish_reason not in {"stop", "tool_calls"}:
        raise _invalid_response("finish reason is not supported")

    message = _field(choice, "message", "choice message is invalid")
    if _field(message, "role", "choice message is invalid") != "assistant":
        raise _invalid_response("choice message is invalid")
    if _optional_field(message, "function_call") is not None:
        raise _invalid_response("legacy function_call is not supported")

    content = _field(message, "content", "assistant content is invalid")
    if content is None:
        text = None
    elif isinstance(content, str):
        text = content if content.strip() else None
    else:
        raise _invalid_response("assistant content is invalid")

    raw_calls = _field(message, "tool_calls", "tool_calls is invalid")
    if raw_calls is None:
        raw_calls = []
    if not isinstance(raw_calls, (list, tuple)):
        raise _invalid_response("tool_calls is invalid")

    calls: list[ToolCall] = []
    seen_ids: set[str] = set()
    for raw_call in raw_calls:
        if _field(
            raw_call,
            "type",
            "unsupported tool call type",
        ) != "function":
            raise _invalid_response("unsupported tool call type")
        call_id = _field(
            raw_call,
            "id",
            "function call id is invalid",
        )
        if not isinstance(call_id, str) or not call_id.strip():
            raise _invalid_response("function call id is invalid")
        normalized_call_id = call_id.strip()
        if normalized_call_id in seen_ids:
            raise _invalid_response("duplicate function call id")
        function = _field(raw_call, "function", "function call is invalid")
        name = _field(function, "name", "function call is invalid")
        if not isinstance(name, str) or not name.strip():
            raise _invalid_response("function call is invalid")
        encoded_arguments = _field(
            function,
            "arguments",
            "function arguments are not valid JSON",
        )
        if not isinstance(encoded_arguments, str):
            raise _invalid_response("function arguments are not valid JSON")
        try:
            arguments = json.loads(encoded_arguments)
        except json.JSONDecodeError as exc:
            raise _invalid_response(
                "function arguments are not valid JSON"
            ) from exc
        if not isinstance(arguments, dict):
            raise _invalid_response("function arguments must be an object")
        try:
            calls.append(
                ToolCall(
                    call_id=normalized_call_id,
                    name=name,
                    arguments=arguments,
                )
            )
        except (TypeError, ValueError) as exc:
            raise _invalid_response("function call is invalid") from exc
        seen_ids.add(normalized_call_id)

    if text is None and not calls:
        raise _invalid_response("no text or function tool calls")

    raw_id = _optional_field(response, "id")
    if raw_id is None:
        response_id = None
    elif isinstance(raw_id, str) and raw_id.strip():
        response_id = raw_id.strip()
    else:
        raise _invalid_response("response id is invalid")

    raw_usage = _optional_field(response, "usage")
    usage = None
    if raw_usage is not None:
        try:
            usage = TokenUsage(
                input_tokens=_field(raw_usage, "prompt_tokens", "usage is invalid"),
                output_tokens=_field(
                    raw_usage,
                    "completion_tokens",
                    "usage is invalid",
                ),
                total_tokens=_field(raw_usage, "total_tokens", "usage is invalid"),
            )
        except InvalidChatCompletionsResponseError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_response("usage is invalid") from exc

    try:
        return ModelResponse(
            text=text,
            tool_calls=tuple(calls),
            usage=usage,
            provider_response_id=response_id,
            continuation_items=(),
        )
    except (TypeError, ValueError) as exc:
        raise _invalid_response("invalid model response") from exc
```

- [ ] **Step 5: Run parser GREEN and internal-type regressions**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_client.py tests\test_messages.py tests\test_model.py -q -p no:cacheprovider
git diff --check
```

Expected: all tests PASS and diff check exits 0.

---

### Task 4: Add the Public Client, SDK Call, Retry, Budget, and Redaction

**Files:**
- Modify: `src/coding_agent/chat_completions_client.py`
- Modify: `tests/test_chat_completions_client.py`

**Interfaces:**
- Consumes: `_normalize_base_url`, `_map_messages`, `_map_tools`, `_parse_response`, official `OpenAI`, and existing `ModelCallBudget`/`invoke_model`.
- Produces: `ChatCompletionsModelClient(model, api_key, base_url, sdk_client=None, sleeper=time.sleep)`, `.complete(request)`, and `.complete_with_budget(request, budget)`.

- [ ] **Step 1: Write failing public-boundary and exact-request tests**

Add fake Chat resources:

```python
class FakeCompletionsResource:
    def __init__(self, outcomes: tuple[object, ...]) -> None:
        self.outcomes = deque(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(deepcopy(kwargs))
        if not self.outcomes:
            raise AssertionError("unexpected Chat Completions API call")
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeSDKClient:
    def __init__(self, *outcomes: object) -> None:
        completions = FakeCompletionsResource(outcomes)
        self.chat = SimpleNamespace(completions=completions)
```

Add tests for:

- runtime `ModelClient` conformance and the exact `complete(self, request)` signature;
- constructor trimming model/base URL, passing the normalized values as keyword arguments `api_key`, `base_url`, and `max_retries=0` to `OpenAI`, callable sleeper validation, and no key/base URL in repr or instance storage;
- direct constructor rejection of invalid model, key, and URL without echoing values;
- exact SDK kwargs with `model`, complete `messages`, `max_tokens`, and `tools` only when nonempty;
- absence of `n`, `stream`, `tool_choice`, `store`, `conversation`, `previous_response_id`, and `max_completion_tokens`;
- local continuation/order/schema failures occurring before `create`.

The exact no-tool request assertion is:

```python
assert sdk.chat.completions.calls == [
    {
        "model": "chat-model",
        "messages": [{"role": "user", "content": "offline"}],
        "max_tokens": 321,
    }
]
```

- [ ] **Step 2: Write failing retry, budget, observer, and redaction tests**

Create fake subclasses that do not require real HTTP request/response objects:

```python
class FakeRateLimitError(RateLimitError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeServerError(InternalServerError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeTimeoutError(APITimeoutError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeConnectionError(APIConnectionError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeAuthenticationError(AuthenticationError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakePermissionError(PermissionDeniedError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeBadRequestError(BadRequestError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeUnprocessableError(UnprocessableEntityError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeNotFoundError(NotFoundError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class FakeAPIResponseValidationError(APIResponseValidationError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)


class RecordingModelObserver:
    def __init__(self) -> None:
        self.items: list[ModelObservation] = []

    def observe_model(self, observation: ModelObservation) -> None:
        self.items.append(observation)
```

Import `traceback`, `ModelObservation`, and `ModelObservationKind`. Add the exact malformed-SDK boundary test:

```python
@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(
            FakeAPIResponseValidationError("malformed-secret"),
            id="sdk-response-validation",
        ),
        pytest.param(
            json.JSONDecodeError(
                "malformed-secret",
                "private-json-document",
                0,
            ),
            id="sdk-json-decode",
        ),
    ],
)
def test_sdk_malformed_payload_is_nonretrying_redacted_invalid_response(
    outcome: BaseException,
) -> None:
    sdk = FakeSDKClient(outcome)
    sleeps: list[float] = []
    observer = RecordingModelObserver()
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=sleeps.append,
    )
    budget = ModelCallBudget(observer=observer)

    with pytest.raises(
        InvalidChatCompletionsResponseError,
        match=(
            "^invalid Chat Completions payload: "
            "provider response could not be decoded$"
        ),
    ) as caught:
        invoke_model(
            client,
            ModelRequest(messages=(UserMessage("offline"),)),
            budget,
        )

    assert len(sdk.chat.completions.calls) == 1
    assert sleeps == []
    assert budget.provider_attempts == 1
    failures = [
        item
        for item in observer.items
        if item.kind is ModelObservationKind.PROVIDER_FAILED
    ]
    assert len(failures) == 1
    assert failures[0].error_code == "invalid_model_response"
    assert failures[0].retry_scheduled is False
    assert caught.value.__cause__ is None
    rendered = "".join(
        traceback.format_exception(
            caught.type,
            caught.value,
            caught.value.__traceback__,
        )
    ) + repr(observer.items)
    assert "malformed-secret" not in rendered
    assert "private-json-document" not in rendered
    assert FAKE_KEY not in rendered
```

Add tests that require:

- each transient class retries twice and recovers with delays `[0.25, 0.50]`;
- a third transient failure raises exactly `Chat Completions request failed after 3 attempts: transient provider error`, with three calls and no fourth call;
- permanent classes make one call, no sleep, and raise stable `FatalModelError` strings;
- arbitrary `OpenAIError` becomes `Chat Completions request failed: provider error`;
- `FakeAPIResponseValidationError` and `json.JSONDecodeError` from `create` each make exactly one call, do not sleep, finish the provider attempt with `invalid_model_response` and `retry_scheduled=false`, and raise exactly `InvalidChatCompletionsResponseError("invalid Chat Completions payload: provider response could not be decoded")` from `None`;
- malformed-SDK error text, API response body, JSON `doc`, fake keys, and exception repr do not appear in the exception, traceback, observer repr, stdout, or stderr;
- `KeyboardInterrupt` and `SystemExit` propagate unchanged;
- parse failure makes one provider call and is not retried;
- `invoke_model` records `invalid_model_response` for parser failure;
- three physical tries claim three shared provider attempts but one logical call;
- a two-attempt shared budget blocks the third request before SDK invocation;
- provider observation order is STARTED, FAILED, STARTED, FAILED, STARTED, COMPLETED with codes and 250/500 ms delays;
- exception text containing the fake key and `Authorization: Bearer` never appears in error text, traceback, observer repr, stdout, or stderr;
- an isolated subprocess removes both credential environment variables, replaces `socket.create_connection` with a failing sentinel, injects the fake SDK, and successfully returns offline text.

- [ ] **Step 3: Run public-client tests to verify RED**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_client.py -q -p no:cacheprovider
```

Expected: FAIL because `ChatCompletionsModelClient` does not exist.

- [ ] **Step 4: Implement the constructor and logical-call wrapper**

Add official SDK exceptions and model-budget imports. The OpenAI import must include the malformed-response class before its broader base is used in exception handling:

```python
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    OpenAI,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
```

Then implement:

```python
class ChatCompletionsModelClient:
    __slots__ = ("_client", "_model", "_sleeper")

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        sdk_client: object | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        if not isinstance(base_url, str):
            raise ValueError(_BASE_URL_ERROR)
        normalized_base_url = _normalize_base_url(base_url)
        if not callable(sleeper):
            raise TypeError("sleeper must be callable")
        self._model = model.strip()
        self._client = (
            OpenAI(
                api_key=api_key.strip(),
                base_url=normalized_base_url,
                max_retries=0,
            )
            if sdk_client is None
            else sdk_client
        )
        self._sleeper = sleeper

    def complete(self, request: ModelRequest) -> ModelResponse:
        budget = ModelCallBudget(max_logical_calls=1, max_provider_attempts=3)
        return invoke_model(self, request, budget)
```

Do not store `api_key` or `base_url` as attributes.

- [ ] **Step 5: Implement exact SDK invocation and retry classification**

In `complete_with_budget`, map and validate before claiming an attempt. Build kwargs as a dict and add `tools` only when nonempty:

```python
        mapped_messages = _map_messages(request)
        mapped_tools = _map_tools(request.tool_schemas)
        request_kwargs: dict[str, object] = {
            "model": self._model,
            "messages": mapped_messages,
            "max_tokens": request.max_output_tokens,
        }
        if mapped_tools:
            request_kwargs["tools"] = mapped_tools
```

Use exactly three attempt slots. Before each `create`, call `budget.begin_provider_attempt(purpose)`. On success call `finish_provider_attempt` with no error. Classify errors exactly as follows:

| SDK error | observation code | local result |
| --- | --- | --- |
| AuthenticationError | `authentication_rejected` | fatal authentication rejected |
| PermissionDeniedError | `permission_rejected` | fatal authentication rejected |
| NotFoundError | `not_found` | fatal model or endpoint not found |
| BadRequestError / UnprocessableEntityError | `request_rejected` | fatal request rejected |
| RateLimitError | `rate_limit` | transient |
| APITimeoutError | `timeout` | transient |
| APIConnectionError | `connection_error` | transient |
| InternalServerError or APIStatusError 5xx | `server_error` | transient |
| APIResponseValidationError / JSONDecodeError | `invalid_model_response` | nonfatal invalid payload; no retry |
| any other OpenAIError | `provider_error` | fatal provider error |

Catch `APIResponseValidationError` before the broader `OpenAIError` branch because it subclasses `OpenAIError`; catch `json.JSONDecodeError` in the same narrow malformed-payload branch. Finish that physical attempt as failed with `invalid_model_response`, never sleep, and raise the stable nonfatal local error from `None`. For attempts 0 and 1, schedule 0.25/0.50 only if another provider attempt remains. If the shared budget has no remaining attempt, finish the current failure as non-retrying and call `begin_provider_attempt` once to emit the existing blocked observation and raise `ModelBudgetExceeded` before any SDK call. On attempt 2, raise the stable exhausted transient error. Do not catch `BaseException` or generic `ValueError`.

After provider success, call `_parse_response(response)` exactly once and return its `ModelResponse`. Parsing remains outside the retry catch, ensuring invalid payloads are not retried.

Implement classification and the loop with this concrete shape:

```python
def _classify_provider_error(
    error: OpenAIError,
) -> tuple[str, str, bool]:
    if isinstance(error, AuthenticationError):
        return (
            "authentication_rejected",
            "Chat Completions request failed: authentication rejected",
            False,
        )
    if isinstance(error, PermissionDeniedError):
        return (
            "permission_rejected",
            "Chat Completions request failed: authentication rejected",
            False,
        )
    if isinstance(error, NotFoundError):
        return (
            "not_found",
            "Chat Completions request failed: model or endpoint not found",
            False,
        )
    if isinstance(error, (BadRequestError, UnprocessableEntityError)):
        return (
            "request_rejected",
            "Chat Completions request failed: request rejected",
            False,
        )
    if isinstance(error, RateLimitError):
        return ("rate_limit", "", True)
    if isinstance(error, APITimeoutError):
        return ("timeout", "", True)
    if isinstance(error, APIConnectionError):
        return ("connection_error", "", True)
    status_code = getattr(error, "status_code", None)
    if isinstance(error, InternalServerError) or (
        isinstance(error, APIStatusError)
        and isinstance(status_code, int)
        and 500 <= status_code <= 599
    ):
        return ("server_error", "", True)
    return (
        "provider_error",
        "Chat Completions request failed: provider error",
        False,
    )


def complete_with_budget(
    self,
    request: ModelRequest,
    budget: ModelCallBudget,
) -> ModelResponse:
    mapped_messages = _map_messages(request)
    mapped_tools = _map_tools(request.tool_schemas)
    request_kwargs: dict[str, object] = {
        "model": self._model,
        "messages": mapped_messages,
        "max_tokens": request.max_output_tokens,
    }
    if mapped_tools:
        request_kwargs["tools"] = mapped_tools
    purpose = budget.active_purpose
    response: object | None = None

    for attempt in range(3):
        provider_attempt_index = budget.begin_provider_attempt(purpose)
        try:
            response = self._client.chat.completions.create(**request_kwargs)
        except (APIResponseValidationError, json.JSONDecodeError):
            budget.finish_provider_attempt(
                purpose,
                provider_attempt_index,
                error_code="invalid_model_response",
                retry_scheduled=False,
                retry_delay_ms=None,
            )
            raise InvalidChatCompletionsResponseError(
                "invalid Chat Completions payload: "
                "provider response could not be decoded"
            ) from None
        except OpenAIError as exc:
            error_code, public_message, transient = _classify_provider_error(exc)
            if not transient:
                budget.finish_provider_attempt(
                    purpose,
                    provider_attempt_index,
                    error_code=error_code,
                    retry_scheduled=False,
                    retry_delay_ms=None,
                )
                raise FatalModelError(public_message) from None
            if attempt == 2:
                budget.finish_provider_attempt(
                    purpose,
                    provider_attempt_index,
                    error_code=error_code,
                    retry_scheduled=False,
                    retry_delay_ms=None,
                )
                raise TransientModelError(
                    "Chat Completions request failed after 3 attempts: "
                    "transient provider error"
                ) from None
            if budget.remaining_provider_attempts == 0:
                budget.finish_provider_attempt(
                    purpose,
                    provider_attempt_index,
                    error_code=error_code,
                    retry_scheduled=False,
                    retry_delay_ms=None,
                )
                budget.begin_provider_attempt(purpose)
                raise AssertionError("unreachable provider budget branch")
            delay = (0.25, 0.50)[attempt]
            budget.finish_provider_attempt(
                purpose,
                provider_attempt_index,
                error_code=error_code,
                retry_scheduled=True,
                retry_delay_ms=int(delay * 1000),
            )
            self._sleeper(delay)
            continue
        budget.finish_provider_attempt(
            purpose,
            provider_attempt_index,
            error_code=None,
            retry_scheduled=False,
            retry_delay_ms=None,
        )
        break

    assert response is not None
    return _parse_response(response)
```

Place `complete_with_budget` on `ChatCompletionsModelClient`; the standalone function presentation above exists only to make the method body unambiguous.

- [ ] **Step 6: Run core adapter GREEN and Responses isolation regression**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_client.py tests\test_openai_client.py tests\test_model.py tests\test_messages.py -q -p no:cacheprovider
git diff --check
```

Expected: all tests PASS. Confirm `git diff -- src/coding_agent/openai_client.py` is empty and `rg -n "ChatCompletions|chat\.completions" src/coding_agent/agent.py src/coding_agent/messages.py src/coding_agent/context.py` returns no matches.

---

### Task 5: Core Adapter Review Gate

**Files:**
- Review only: `src/coding_agent/chat_completions_client.py`
- Review only: `tests/test_chat_completions_client.py`
- Review only: the one-entry production diff in `src/coding_agent/tools/shell.py`
- Review only: credential-isolation additions in `tests/tools/test_shell_tool.py`
- Compare: `docs/superpowers/specs/2026-08-29-chat-completions-provider-design.md`

**Interfaces:**
- Consumes: the completed standalone Chat adapter from Tasks 2–4 and the Task 2A credential-isolation change.
- Produces: a user-visible review report with requirement coverage, test evidence, and any exact findings before composition-root changes.

- [ ] **Step 1: Invoke the required review skill with a read-only boundary**

Read and apply `superpowers:requesting-code-review`. Keep all fixes and tightly coupled implementation inline. The user has authorized an independent subagent only to inspect the finished diff and report findings; if used, instruct it not to edit files, run network operations, or perform Git writes.

- [ ] **Step 2: Review every core invariant against evidence**

Check each of these directly in source and tests:

- keyword-only public constructor and exact public method signatures;
- no SDK types outside the adapter;
- no key/base URL stored or rendered;
- direct HTTPS validation and no vendor default;
- strict nested function tools and canonical JSON arguments;
- full-history user/assistant/tool mapping and immediate ordered pairing;
- empty continuation both inbound requirement and outbound result;
- tool detection independent of finish reason;
- exactly one choice and all invalid response cases;
- token usage and response ID mapping;
- SDK retry disabled, local retry schedule, shared attempt budget, stable observation codes;
- SDK response-validation/JSON-decode failures are nonfatal, non-retrying, and fully redacted;
- both model credential variables are absent from actual and captured child environments;
- no provider exception/body/header/key leakage;
- no edit to Responses/core files.

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_client.py tests\tools\test_shell_tool.py tests\test_openai_client.py tests\test_model.py -q -p no:cacheprovider
git diff --check
git diff -- src/coding_agent/chat_completions_client.py tests/test_chat_completions_client.py
git diff -- src/coding_agent/tools/shell.py tests/tools/test_shell_tool.py
```

Expected: tests PASS, diff check exits 0, and review finds no Critical or Important violation. If a reproducible finding exists, stop, report its exact file/line/test, and wait for user approval before fixing it through systematic debugging and TDD.

- [ ] **Step 3: Obtain the core-module review checkpoint**

Present the test command/result and the review checklist to the user. Continue to Task 6 only after the user approves the core adapter or explicitly approves the exact finding fixes.

---

### Task 6: Wire Explicit Adapter Selection into the Application

**Files:**
- Modify: `src/coding_agent/app.py:7-54`
- Modify: `tests/test_app.py:1-145`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `RunConfig.api_mode`, `RunConfig.base_url`, `OpenAIResponsesClient`, and `ChatCompletionsModelClient`.
- Produces: `_production_model_client(config) -> ModelClient` selecting exactly one adapter without probing or calling it.

- [ ] **Step 1: Write failing composition-root tests**

Update imports to include `ApiMode` and add a Chat config helper using `load_run_config`. Keep the existing default Responses test and add:

```python
def test_production_factory_selects_chat_adapter_without_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_run_config(
        task="inspect",
        workspace=tmp_path,
        model="chat-model",
        verify_command=None,
        api_mode="chat-completions",
        base_url="https://provider.example/api/v1",
        environ={"CHAT_COMPLETIONS_API_KEY": FAKE_KEY},
    )
    calls: list[tuple[str, str, str]] = []
    stand_in = FakeModelClient((ModelResponse(text="unused"),))

    def fake_chat_constructor(
        *, model: str, api_key: str, base_url: str
    ) -> ModelClient:
        calls.append((model, api_key, base_url))
        return stand_in

    def forbidden_responses_constructor(*, model: str, api_key: str) -> ModelClient:
        raise AssertionError("Responses adapter must not be constructed")

    monkeypatch.setattr(
        "coding_agent.app.ChatCompletionsModelClient",
        fake_chat_constructor,
    )
    monkeypatch.setattr(
        "coding_agent.app.OpenAIResponsesClient",
        forbidden_responses_constructor,
    )

    selected = production_factories().model_client(config)

    assert config.api_mode is ApiMode.CHAT_COMPLETIONS
    assert selected is stand_in
    assert calls == [(config.model, config.api_key, config.base_url)]
    assert stand_in.requests == ()
```

Strengthen the Responses test so a monkeypatched Chat constructor raises if touched. Add a logger/final-report regression using a Chat config and injected fake model to prove the selected Chat key never appears in stdout, stderr, JSONL, or config repr.

- [ ] **Step 2: Run application tests to verify RED**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_app.py tests\test_cli.py -q -p no:cacheprovider
```

Expected: FAIL because `coding_agent.app.ChatCompletionsModelClient` does not exist and the production factory always selects Responses.

- [ ] **Step 3: Implement explicit selection only**

Import `ApiMode` and the new client. Replace `_production_model_client` with:

```python
def _production_model_client(config: RunConfig) -> ModelClient:
    if config.api_mode is ApiMode.RESPONSES:
        return OpenAIResponsesClient(model=config.model, api_key=config.api_key)
    if config.base_url is None:
        raise ValueError("chat-completions base_url is missing")
    return ChatCompletionsModelClient(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
    )
```

Do not probe either endpoint and do not catch construction errors in the factory. Leave logger sensitive values as `(config.api_key,)`; no log/report schema change is authorized.

- [ ] **Step 4: Run composition GREEN and default Responses regression**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_app.py tests\test_cli.py tests\test_openai_client.py tests\test_agent_loop.py -q -p no:cacheprovider
git diff --check
```

Expected: all tests PASS; existing default configuration still constructs only `OpenAIResponsesClient`; no SDK request occurs during configuration or selection.

---

### Task 7: Prove Continuous Agent Loops and Compression with a Fake Chat SDK

**Files:**
- Create: `tests/integration/test_chat_completions_agent.py`
- Preserve: `src/coding_agent/agent.py`
- Preserve: `src/coding_agent/context.py`

**Interfaces:**
- Consumes: real `AgentRunner`, `ContextManager`, `ChatCompletionsModelClient`, `ToolRegistry`, and fake SDK completion outcomes.
- Produces: recorded Chat request payloads proving full-history replay and legal assistant/tool ordering across all mandatory scenarios.

- [ ] **Step 1: Build an offline integration harness**

Create a local tool and complete fake SDK harness:

```python
@dataclass(slots=True)
class EchoTool:
    executed: list[tuple[str, Path]] = field(default_factory=list)
    name: str = field(default="echo", init=False)
    schema: JSONObject = field(
        default_factory=lambda: {
            "name": "echo",
            "description": "Return the supplied text.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
        },
        init=False,
    )

    def execute(
        self,
        arguments: JSONObject,
        context: ExecutionContext,
    ) -> ToolExecution:
        if set(arguments) != {"text"} or not isinstance(arguments["text"], str):
            raise ToolArgumentError("text must be the only string argument")
        text = arguments["text"]
        self.executed.append((text, context.workspace))
        return ToolExecution(output=text)


class FakeCompletionsResource:
    def __init__(self, outcomes: tuple[object, ...]) -> None:
        self.outcomes = deque(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(deepcopy(kwargs))
        if not self.outcomes:
            raise AssertionError("unexpected Chat Completions API call")
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeSDKClient:
    def __init__(self, *outcomes: object) -> None:
        self.chat = SimpleNamespace(
            completions=FakeCompletionsResource(outcomes)
        )


def _response(
    *,
    content: str | None,
    calls: tuple[tuple[str, str], ...] = (),
    finish_reason: str = "stop",
) -> SimpleNamespace:
    tool_calls = [
        SimpleNamespace(
            id=call_id,
            type="function",
            function=SimpleNamespace(
                name="echo",
                arguments=json.dumps(
                    {"text": text},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        for call_id, text in calls
    ]
    return SimpleNamespace(
        id="chatcmpl_offline",
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(
                    role="assistant",
                    content=content,
                    tool_calls=tool_calls or None,
                    function_call=None,
                ),
            )
        ],
        usage=None,
    )
```

The client must use `FAKE_BASE_URL`, `FAKE_KEY`, the fake SDK, and a no-op sleeper. `_runner` must inject the same Chat client into `AgentRunner` and `ContextManager`:

```python
def _runner(
    tmp_path: Path,
    outcomes: tuple[object, ...],
    *,
    context_limits: ContextLimits | None = None,
) -> tuple[AgentRunner, FakeCompletionsResource, EchoTool]:
    sdk = FakeSDKClient(*outcomes)
    client = ChatCompletionsModelClient(
        model="chat-model",
        api_key=FAKE_KEY,
        base_url=FAKE_BASE_URL,
        sdk_client=sdk,
        sleeper=lambda delay: None,
    )
    tool = EchoTool()
    runner = AgentRunner(
        model_client=client,
        tool_registry=ToolRegistry((tool,)),
        execution_context=ExecutionContext(tmp_path),
        context_manager=(
            ContextManager(model_client=client, limits=context_limits)
            if context_limits is not None
            else ContextManager(model_client=client)
        ),
        clock=lambda: 0.0,
    )
    return runner, sdk.chat.completions, tool
```

Add `_assert_legal_chat_history(messages)` that walks each request in order. When an assistant message has tool calls, it records their ordered IDs and requires the immediately following messages to be role `tool` with identical `tool_call_id` order. It rejects a standalone tool message, incomplete pending list, or any intervening user/assistant message.

Implement the legality helper concretely:

```python
def _assert_legal_chat_history(messages: list[dict[str, object]]) -> None:
    index = 0
    while index < len(messages):
        message = messages[index]
        role = message["role"]
        if role == "tool":
            raise AssertionError("standalone tool message")
        if role != "assistant" or not message.get("tool_calls"):
            index += 1
            continue
        raw_calls = message["tool_calls"]
        assert isinstance(raw_calls, list)
        expected_ids = [call["id"] for call in raw_calls]
        results = messages[index + 1 : index + 1 + len(expected_ids)]
        assert len(results) == len(expected_ids)
        assert [result["role"] for result in results] == [
            "tool"
        ] * len(expected_ids)
        assert [result["tool_call_id"] for result in results] == expected_ids
        index += 1 + len(expected_ids)
```

- [ ] **Step 2: Write scenario 1 — text plus tool call, result, final text**

Script a first completion with content `I will call echo.`, one `call_1`, and `finish_reason="stop"`; script a second completion with `finished`. Assert:

```python
assert state.status is AgentStatus.COMPLETION_CANDIDATE
assert state.completion_text == "finished"
assert tool.executed == [("one", tmp_path)]
assert len(resource.calls) == 2
assert [message["role"] for message in resource.calls[1]["messages"]] == [
    "user",
    "assistant",
    "tool",
]
assert resource.calls[1]["messages"][1]["content"] == "I will call echo."
assert resource.calls[1]["messages"][2]["tool_call_id"] == "call_1"
```

Call `_assert_legal_chat_history` on both recorded requests and assert no request contains conversation, previous_response_id, store, or continuation fields.

- [ ] **Step 3: Write scenario 2 — two consecutive tool rounds, then text**

Script `call_1`, then `call_2`, then final text. Use different arguments to avoid no-progress repetition. Assert three provider calls, two Echo executions in order, the second request contains the first assistant/tool pair, the third contains both complete pairs, and every request passes the legality helper.

```python
runner, resource, tool = _runner(
    tmp_path,
    (
        _response(content=None, calls=(("call_1", "one"),)),
        _response(content=None, calls=(("call_2", "two"),)),
        _response(content="finished two rounds"),
    ),
)
state = runner.run("use echo twice")
assert state.completion_text == "finished two rounds"
assert tool.executed == [("one", tmp_path), ("two", tmp_path)]
assert len(resource.calls) == 3
assert [message["role"] for message in resource.calls[2]["messages"]] == [
    "user",
    "assistant",
    "tool",
    "assistant",
    "tool",
]
for request in resource.calls:
    _assert_legal_chat_history(request["messages"])
```

- [ ] **Step 4: Write scenario 3 — one response with multiple tool calls/results**

Script one assistant response containing `call_1` and `call_2` in that order with `finish_reason="stop"`, followed by final text. Assert the second request has one assistant message followed by two tool messages whose IDs are exactly `call_1`, `call_2`; assert Echo execution order and full `ToolResult.to_json()` content.

```python
runner, resource, tool = _runner(
    tmp_path,
    (
        _response(
            content="calling twice",
            calls=(("call_1", "one"), ("call_2", "two")),
            finish_reason="stop",
        ),
        _response(content="finished batch"),
    ),
)
state = runner.run("use two calls in one response")
sent = resource.calls[1]["messages"]
assert state.completion_text == "finished batch"
assert tool.executed == [("one", tmp_path), ("two", tmp_path)]
assert [message["role"] for message in sent] == [
    "user",
    "assistant",
    "tool",
    "tool",
]
assert [sent[2]["tool_call_id"], sent[3]["tool_call_id"]] == [
    "call_1",
    "call_2",
]
for message in sent[2:]:
    decoded = ToolResult.from_json(message["content"])
    assert decoded.call_id == message["tool_call_id"]
```

- [ ] **Step 5: Write scenario 4 — compression then continued Chat call**

Use nine distinct Echo-call responses, then `_response(content=_summary_text())`, then `_response(content="continued after compression")`. Define the summary fixture exactly:

```python
def _summary_text() -> str:
    return json.dumps(
        {
            "goal": "continue the task",
            "established_facts": ["nine echo calls completed"],
            "files_examined": [],
            "changes_made": [],
            "commands_and_results": [],
            "unresolved_errors": [],
            "open_issues": [],
            "verification_state": {},
            "avoid_repeating": [],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
```

Configure:

```python
ContextLimits(
    max_serialized_chars=60_000,
    max_history_items=18,
    recent_turns=8,
)
```

The summary JSON must contain exactly the nine existing `ContextSummary` fields. Assert 11 logical provider requests total, the summary request has no `tools` key, the final request contains the initial user message plus a `coding-agent context summary\n` user message plus eight complete recent assistant/tool turns, the state continuation is empty, and every recorded request passes the legality helper.

```python
outcomes = tuple(
    _response(
        content=None,
        calls=((f"call_{index}", f"value {index}"),),
    )
    for index in range(9)
) + (
    _response(content=_summary_text()),
    _response(content="continued after compression"),
)
runner, resource, tool = _runner(
    tmp_path,
    outcomes,
    context_limits=ContextLimits(
        max_serialized_chars=60_000,
        max_history_items=18,
        recent_turns=8,
    ),
)
state = runner.run("compress legal Chat history")
assert state.completion_text == "continued after compression"
assert state.continuation_items == ()
assert len(resource.calls) == 11
assert "tools" not in resource.calls[9]
final_messages = resource.calls[10]["messages"]
assert final_messages[0]["role"] == "user"
assert final_messages[1]["role"] == "user"
assert final_messages[1]["content"].startswith(
    "coding-agent context summary\n"
)
for request in resource.calls:
    _assert_legal_chat_history(request["messages"])
```

- [ ] **Step 6: Write scenario 5 — explicit per-request pairing contract**

Create a dedicated test using two calls in the first round and one call in the second. For every recorded request, invoke `_assert_legal_chat_history`, then additionally assert every tool ID was declared by the immediately preceding assistant group and appears exactly once. This test must fail if result order is reversed, if an assistant message is omitted, or if a tool message is inserted later in history.

```python
runner, resource, tool = _runner(
    tmp_path,
    (
        _response(
            content=None,
            calls=(("pair_1", "one"), ("pair_2", "two")),
        ),
        _response(content=None, calls=(("pair_3", "three"),)),
        _response(content="pairing complete"),
    ),
)
state = runner.run("verify every pairing")
assert state.completion_text == "pairing complete"
for request in resource.calls:
    messages = request["messages"]
    _assert_legal_chat_history(messages)
    declared = [
        call["id"]
        for message in messages
        if message["role"] == "assistant"
        for call in message.get("tool_calls", [])
    ]
    returned = [
        message["tool_call_id"]
        for message in messages
        if message["role"] == "tool"
    ]
    assert returned == declared
    assert len(returned) == len(set(returned))
```

- [ ] **Step 7: Run the new integration contract tests**

Before changing production code in response to these tests, run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\integration\test_chat_completions_agent.py -q -p no:cacheprovider
```

Expected: all five tests PASS because Tasks 2–6 were driven by narrower RED/GREEN unit tests. Any failure is a real integration mismatch; invoke `superpowers:systematic-debugging`, identify the boundary that violated the spec, add the narrowest RED unit test, and make the minimal correction without editing Agent or ContextManager unless the approved design is proven inconsistent.

- [ ] **Step 8: Run continuous-loop and compression regressions**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\integration\test_chat_completions_agent.py tests\test_context.py tests\test_agent_loop.py tests\integration\test_agent_failures.py -q -p no:cacheprovider
git diff --check
```

Expected: all tests PASS and `git diff -- src/coding_agent/agent.py src/coding_agent/context.py src/coding_agent/messages.py` is empty.

---

### Task 8: Update Public Documentation and Executable Contracts

**Files:**
- Modify: `tests/test_docs.py`
- Modify: `README.md`
- Modify: `README.txt`
- Modify: `docs/USAGE.md`
- Modify: `docs/OPENAI_API.md`

**Interfaces:**
- Consumes: actual parser help, both production adapter source files, and approved Task15 behavior.
- Produces: accurate provider-selection documentation without real credentials or a hardcoded provider default.

- [ ] **Step 1: Write failing documentation-contract tests**

Update the parser-name tuple in `test_usage_matches_parser_tools_exit_codes_and_log_path` to include `--api-mode` and `--base-url`. Require `CHAT_COMPLETIONS_API_KEY`, the two mode values, the Responses/base-URL illegal combination, the Chat/base-URL requirement, the statement that neither model credential enters `run_command` child processes, and the compatibility warning.

Rename the API guide test to cover both adapters. Update its heading order to require sections for:

- provider/mode selection;
- Responses request mapping and continuation;
- Chat Completions full-history mapping;
- assistant tool_calls and tool result pairing;
- shared retry/budget behavior;
- offline tests;
- still-unsupported extensions.

Add source assertions:

```python
responses_source = _read_utf8(ROOT / "src" / "coding_agent" / "openai_client.py")
chat_source = _read_utf8(
    ROOT / "src" / "coding_agent" / "chat_completions_client.py"
)
assert ".responses.create(" in responses_source
assert "store=False" in responses_source
assert ".chat.completions.create(" in chat_source
assert "max_retries=0" in chat_source
assert '"max_tokens"' in chat_source
assert "previous_response_id" not in chat_source
assert "conversation" not in chat_source
```

Replace the obsolete unsupported requirements for `custom base_url`, `第三方 compatible endpoint`, and `其他 provider adapter`. The remaining unsupported table must explicitly contain custom Responses endpoint, Azure-specific API, proxy configuration, server conversation, streaming, async API, automatic endpoint detection, legacy `function_call`, and non-function Chat tools.

- [ ] **Step 2: Run document tests to verify RED**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py -q -p no:cacheprovider
```

Expected: FAIL because public docs still describe Responses as the only adapter and omit the new CLI options.

- [ ] **Step 3: Update `docs/USAGE.md` and the landing READMEs**

Document two credential preparations without ever showing a real value:

```powershell
$env:OPENAI_API_KEY = '<openai-api-key>'
$env:CHAT_COMPLETIONS_API_KEY = '<chat-completions-provider-key>'
$env:OPENAI_MODEL = '<model-id>'
```

Explain that only the selected mode's key is required, keys have no fallback, and both model credential names are removed from workspace Python/pytest/verification child environments. Add exact examples:

```powershell
coding-agent "修复失败测试" --workspace . --api-mode responses --model '<openai-model-id>' --verify "pytest -q"

coding-agent "修复失败测试" --workspace . --api-mode chat-completions --base-url '<https-provider-base-url-with-api-prefix>' --model '<compatible-model-id>' --verify "pytest -q"
```

State that `responses` is the default, `responses + --base-url` is invalid, Chat requires an absolute HTTPS URL, and configuring a URL does not prove compatibility. The endpoint must support standard Chat Completions assistant `tool_calls`, function IDs, strict tool schema, and `role=tool` results paired by `tool_call_id`.

Update `README.md` to describe both adapters and keep the existing documentation links. Update `README.txt` concisely so its existing 650–850 Unicode-character contract still passes; include both API modes, `--base-url`, and the two environment-variable names without adding a provider address or key.

- [ ] **Step 4: Rewrite `docs/OPENAI_API.md` as a two-adapter guide**

Use a neutral title such as `# OpenAI Responses 与 compatible Chat Completions 接入说明`. Preserve all accepted Responses details unchanged, then add the Chat contract:

- explicit configuration matrix;
- independent adapter file and unchanged ModelClient boundary;
- full local history every request;
- exact user/assistant/assistant tool_calls/tool result mapping;
- canonical arguments and ordered multi-call results;
- direct tool_calls inspection despite `finish_reason="stop"`;
- `max_tokens`, optional tools key, one choice, finish reason/usage validation;
- empty continuation and no server state;
- identical local retry schedule and shared budget semantics;
- fake SDK and Agent integration test commands;
- compatibility warning and unsupported features.

Do not claim universal OpenAI compatibility, live BayesDL verification by Task15, custom Responses endpoints, streaming, async, automatic detection, or `max_completion_tokens` fallback.

- [ ] **Step 5: Run documentation GREEN and privacy checks**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py tests\test_cli.py -q -p no:cacheprovider
rg -n "sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{12,}|Authorization:" README.md README.txt docs\USAGE.md docs\OPENAI_API.md
git diff --check
```

Expected: tests PASS; the credential-pattern scan returns no matches; diff check exits 0.

---

### Task 9: Full Offline Verification, Final Review, and Task Closure

**Files:**
- Review: every Task15 file in the locked file map
- Modify last: `TASKS.md` Task15 status only

**Interfaces:**
- Consumes: all implementation, tests, docs, and review evidence from Tasks 1–8 plus Task 2A.
- Produces: fresh offline evidence that all acceptance criteria pass and Task15 may be marked `已完成`.

- [ ] **Step 1: Run the focused Task15 and regression suite**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests\test_chat_completions_client.py tests\integration\test_chat_completions_agent.py tests\test_cli.py tests\test_app.py tests\test_docs.py tests\tools\test_shell_tool.py tests\test_openai_client.py tests\test_model.py tests\test_messages.py tests\test_context.py tests\test_agent_loop.py tests\integration\test_agent_failures.py -q -p no:cacheprovider
```

Expected: every selected test PASS with no network or real credential.

- [ ] **Step 2: Run the complete offline suite**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Expected: all repository tests PASS with exit code 0.

- [ ] **Step 3: Perform scope, dependency, architecture, and privacy audits**

Run:

```powershell
git diff --check
git status --short --untracked-files=all
git diff --name-only
rg -n "langchain|llamaindex|openai-agents|autogen|crewai" pyproject.toml src tests
rg -n "chat\.completions|ChatCompletions" src\coding_agent\agent.py src\coding_agent\messages.py src\coding_agent\context.py src\coding_agent\tools
rg -n "sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{12,}|Authorization:" README.md README.txt docs\USAGE.md docs\OPENAI_API.md src
git diff -- src\coding_agent\openai_client.py src\coding_agent\agent.py src\coding_agent\messages.py src\coding_agent\context.py pyproject.toml
git diff -- src\coding_agent\tools\shell.py
```

Expected:

- diff check exits 0;
- changed paths are limited to the locked Task15 map plus the already approved design/spec/plan files;
- framework, core-layer Chat reference, credential-pattern, and protected-production-file diffs return no matches/output;
- the shell production diff contains only the new case-folded `chat_completions_api_key` removal-set entry;
- `pyproject.toml` remains unchanged with only `openai` and pytest declarations.

- [ ] **Step 4: Apply `superpowers:verification-before-completion` and final inline review**

Re-read the approved spec section by section and map every requirement to a passing test or inspected source line. Record actual commands, exit codes, test counts, and any skipped tests. Do not infer a pass from earlier output and do not report live-provider compatibility as tested.

If any test, scan, or requirement fails, leave Task15 `进行中`, invoke systematic debugging for reproducible code failures, and report the real blocker. Do not weaken tests or broaden scope.

- [ ] **Step 5: Mark Task15 complete only after all evidence is green**

Change only Task15's status in `TASKS.md` from `进行中` to `已完成`. Then rerun fresh verification after this final documentation mutation:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
git diff --check
git status --short --untracked-files=all
```

Expected: full suite PASS, diff check exits 0, Tasks 1–15 are all `已完成`, and there is no `进行中` task.

- [ ] **Step 6: Report completion without Git or network mutation**

Report:

- files created/modified;
- exact focused and full test commands with real counts and exit codes;
- offline fake-SDK coverage for the five continuous-loop scenarios;
- explicit confirmation that no real API was called;
- explicit confirmation that Responses regression passed, Agent/messages/context/Responses core files were not modified, and the shell diff is limited to the approved credential-filter entry;
- any remaining compatibility limitation;
- current unstaged working-tree status.

Do not stage, commit, push, pull, fetch, create a branch/worktree, or claim BayesDL live success.

---

## Execution Gate

This revised plan does not authorize resumed implementation by itself. The user must approve this file explicitly. After approval, resume tightly coupled implementation inline with `superpowers:executing-plans`; user-authorized subagents may perform independent read-only audits or reviews but may not edit core files. Stop at the Task 5 core-adapter review checkpoint and again for any design conflict, new dependency, edit outside the revised locked file map, real API need, or scope expansion.
